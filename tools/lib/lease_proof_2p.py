#!/usr/bin/env python3
"""The GPU lease invariant, proven across two PROCESSES rather than two coroutines.

    python3 tools/lib/lease_proof_2p.py                 # the proof, the negative control, the stale case
    python3 tools/lib/lease_proof_2p.py --only proof
    python3 tools/lib/lease_proof_2p.py --worker ...    # internal

## Why this exists

`tools/lib/gpu_lease_proof.py` fires concurrent requests at ONE uvicorn and asserts the card is
never double-held: 33 samples, two witnesses, never two holders. That proves the `asyncio`
gate inside one process. The surface split makes that insufficient — the real mutex is the
`mkdir` lock in `<root>/run/gpu.lock.d`, and nothing had ever contended for it from two
processes and measured the result.

## The invariant, and both witnesses

  never two holders          -- the observable: `run/gpu.lock.d/holder` names one surface+pid
  never two model sets resident -- the HARM: a lock bug that never overlaps in time but leaves
                                two engines loaded still OOMs a 16 GB card

Both are sampled. Dropping the second would pass a lock that serialises acquisition and leaks
residency, which is the failure that actually costs the card.

## Why it runs in an isolated root, and what that costs

`run/resident` on this box reads `chat`, and `cmd_acquire` evicts the previous resident before
handing over. `evict chat` is `symoneural-cli _stop-chat || pkill -f 'bin/symoneural-llm'` --
a PATTERN kill. Run against the production `run/`, this proof would kill the live chat engine
(8330 MiB resident, serving) and, because the pattern matches any `bin/symoneural-llm`, its own
test engines too.

So each worker gets a temp root holding a COPY of the real `scripts/gpu-governor.sh`, whose
`RUN` is derived from its own location (`gpu-governor.sh:42`). The script, the lock mechanism,
the staleness break and the eviction logic are all the real ones; only the directory differs.

**What that does not prove:** that production's `run/` is the shared one. It is the same code
reading a different path, so the mechanism is proven and the deployment is not. The negative
control below is exactly the failure that distinction hides, which is why it is mandatory.

## Clean start

A dirty start makes "never two holders" true for the wrong reason: a stale holder left by
something else serialises everything by accident. So the real lock must be free before this
begins, and VRAM at t=0 is recorded because the card is rarely empty -- the live chat engine
sits at ~8.3 GB by design, and a proof that starts with weights loaded measures something
different from one that starts cold.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time

ROOT = next(_p for _p in pathlib.Path(__file__).resolve().parents if (_p / "backend" / "server.py").is_file())
GOVERNOR = ROOT / "scripts" / "gpu-governor.sh"
ENGINE = ROOT / "symoneural-llm" / "build" / "bin" / "symoneural-llm"
#: 0.40 GB. Deliberately the smallest weight on the box: two resident at once is ~1.3 GB
#: against ~7.3 GB free, so even a FAILING lock cannot OOM the card during the negative
#: control. A proof whose failure mode is an OOM is a proof nobody runs twice.
MODEL = ROOT / "models" / "llm" / "symon-1.0-draft-0.5b-q4_k_m.gguf"
SAMPLE_S = 0.15


# ------------------------------------------------------------------ readings
def compute_apps() -> dict[int, int]:
    """pid -> MiB, from the driver. The residency witness."""
    try:
        r = subprocess.run(["nvidia-smi", "--query-compute-apps=pid,used_memory",
                            "--format=csv,noheader,nounits"],
                           capture_output=True, text=True, timeout=20)
    except Exception:
        return {}
    out: dict[int, int] = {}
    for line in r.stdout.strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) == 2 and parts[0].isdigit():
            out[int(parts[0])] = int(parts[1]) if parts[1].isdigit() else 0
    return out


def vram() -> dict:
    try:
        r = subprocess.run(["nvidia-smi", "--query-gpu=memory.total,memory.used,memory.free",
                            "--format=csv,noheader,nounits"],
                           capture_output=True, text=True, timeout=20)
        t, u, f = [int(x.strip()) for x in r.stdout.strip().split(",")]
        return {"total_mib": t, "used_mib": u, "free_mib": f}
    except Exception as exc:
        return {"error": str(exc)}


def holder_of(root: pathlib.Path) -> tuple[str, int] | None:
    """(surface, pid) from a root's holder file.

    Split on whitespace and take TWO fields. The file is `chat 1512` -- surface AND pid --
    and an earlier proof in this repo counted those as two holders and reported a violation
    in every single round.
    """
    try:
        surface, pid = (root / "run" / "gpu.lock.d" / "holder").read_text().split()
        return surface, int(pid)
    except Exception:
        return None


# ------------------------------------------------------------------ the isolated root
def make_root(tag: str) -> pathlib.Path:
    """A temp root carrying the REAL governor. Only `RUN` differs from production."""
    d = pathlib.Path(tempfile.mkdtemp(prefix=f"lease-{tag}-"))
    (d / "scripts").mkdir()
    (d / "backend").mkdir()
    (d / "run").mkdir()
    shutil.copy2(GOVERNOR, d / "scripts" / "gpu-governor.sh")
    # The governor asserts `$ROOT/backend/server.py` exists and exits if not -- the guard that
    # catches a mis-derived root. Satisfy it honestly rather than removing the check.
    (d / "backend" / "server.py").write_text("# root marker for tools/lib/lease_proof_2p.py\n")
    return d


# ------------------------------------------------------------------ the worker
def worker(surface: str, root: str, port: int, hold_s: float) -> int:
    """Acquire, load a real engine, hold, unload, release. One process, run under the sampler.

    `SYMONEURAL_OWNER_PID` is this process, not the shell's: for the standalone `acquire`
    form the script exits immediately, so the default `$PPID` would name a dead process and
    staleness detection would break a live lock on its first poll (`gpu-governor.sh:315`).
    """
    r = pathlib.Path(root)
    gov = str(r / "scripts" / "gpu-governor.sh")
    # `drain()` reads ALL compute on the card when it has no pattern, against a 1024 MiB
    # floor -- and production's chat engine sits at 8330 MiB by design. So on this box every
    # patternless drain is going to fail; the only question is whether it burns 60s first.
    # `SYMONEURAL_DRAIN_TIMEOUT_S` is an env override the script already provides.
    env = dict(os.environ, SYMONEURAL_OWNER_PID=str(os.getpid()),
               SYMONEURAL_DRAIN_TIMEOUT_S="3")
    started = time.monotonic()
    a = subprocess.run([gov, "acquire", surface, "60"], env=env,
                       capture_output=True, text=True, timeout=180)
    if a.returncode != 0:
        print(json.dumps({"surface": surface, "acquired": False,
                          "waited_s": round(time.monotonic() - started, 2),
                          "stderr": a.stderr[-300:]}))
        return 1
    waited = round(time.monotonic() - started, 2)

    engine = subprocess.Popen(
        [str(ENGINE), "-m", str(MODEL), "-ngl", "99", "--host", "127.0.0.1",
         "--port", str(port), "-c", "512", "--no-warmup"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    resident_after = None
    for _ in range(60):
        time.sleep(0.25)
        if engine.pid in compute_apps():
            resident_after = round(time.monotonic() - started, 2)
            break
    time.sleep(hold_s)
    try:
        os.killpg(os.getpgid(engine.pid), signal.SIGTERM)
        engine.wait(timeout=30)
    except Exception:
        pass
    # Wait for the driver to actually reclaim it. Releasing while the CUDA context is still
    # tearing down is how the next tenant OOMs at step 0 -- the governor's `release` drains
    # for exactly this reason, and the worker must not race ahead of it.
    for _ in range(60):
        if engine.pid not in compute_apps():
            break
        time.sleep(0.25)
    subprocess.run([gov, "release", surface], env=env, capture_output=True, text=True,
                   timeout=180)
    print(json.dumps({"surface": surface, "acquired": True, "waited_s": waited,
                      "engine_pid": engine.pid, "resident_after_s": resident_after,
                      "total_s": round(time.monotonic() - started, 2)}))
    return 0


# ------------------------------------------------------------------ the sampler
class Sampler(threading.Thread):
    """Samples both witnesses every 150 ms.

    `baseline` is the set of compute pids present at t=0 -- production's resident chat engine
    and anything else already on the card. "Ours" is everything that appeared AFTER that.
    
    The first version of this took an `engine_pids` set that the orchestrator populated from
    the workers' JSON reports -- which arrive only when a worker EXITS. So during the run the
    set was empty, every sample recorded zero resident engines of ours, and
    `two_resident_samples` was 0 no matter what happened. That is a vacuous pass on half the
    invariant: the residency witness, which is the one that catches the harm rather than the
    observable. Baselining at t=0 needs no coordination and cannot be empty when it matters.
    """

    def __init__(self, roots: list[pathlib.Path], baseline: set[int]):
        super().__init__(daemon=True)
        self.roots = roots
        self.baseline = baseline
        self.samples: list[dict] = []
        self.stop = threading.Event()

    def run(self) -> None:
        while not self.stop.is_set():
            apps = compute_apps()
            holders = {}
            for r in self.roots:
                h = holder_of(r)
                if h:
                    holders[h[0]] = h[1]
            self.samples.append({
                "t": round(time.monotonic(), 3),
                "holders": holders,
                # Production's resident chat engine is not a violation -- it is residency by
                # design, and counting it would make every sample red.
                "ours_resident": {p: m for p, m in apps.items() if p not in self.baseline},
                "all_compute_mib": sum(apps.values()),
            })
            time.sleep(SAMPLE_S)


def judge(samples: list[dict]) -> dict:
    """The two assertions, over the samples. Returns the verdict rather than printing it."""
    two_holders = [s for s in samples if len(s["holders"]) > 1]
    two_resident = [s for s in samples if len(s["ours_resident"]) > 1]
    distinct = sorted({h for s in samples for h in s["holders"]})
    # The holder sequence over time. `distinct_holders_seen` alone cannot distinguish
    # "A then B" from "A and B at once" -- the two-holder count does that, but the sequence
    # is what makes a report readable and catches a surprise like a worker that reported
    # acquired=False still appearing as a holder.
    seq: list[str] = []
    for smp in samples:
        cur = ",".join(sorted(smp["holders"])) or "-"
        if not seq or seq[-1] != cur:
            seq.append(cur)
    return {
        "samples": len(samples),
        "distinct_holders_seen": distinct,
        "holder_sequence": seq,
        "contended": len(distinct) > 1,
        "two_holders_samples": len(two_holders),
        "two_resident_samples": len(two_resident),
        "peak_ours_mib": max((sum(s["ours_resident"].values()) for s in samples), default=0),
        "ok": not two_holders and not two_resident,
    }


# ------------------------------------------------------------------ the cases
def run_pair(roots: list[pathlib.Path], hold_s: float = 4.0) -> tuple[dict, list[dict]]:
    """Two workers, started together. `roots` of length 1 = a shared lock; 2 = separate."""
    a_root = roots[0]
    b_root = roots[1] if len(roots) > 1 else roots[0]
    baseline = set(compute_apps())          # whatever already holds the card, right now
    sampler = Sampler(sorted({a_root, b_root}), baseline)
    procs = []
    for surface, r, port in (("lease-a", a_root, 8891), ("lease-b", b_root, 8892)):
        procs.append(subprocess.Popen(
            [sys.executable, __file__, "--worker", surface, str(r), str(port), str(hold_s)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, cwd=ROOT))
    sampler.start()
    reports = []
    for p in procs:
        out, err = p.communicate(timeout=400)
        for line in out.strip().splitlines():
            try:
                rec = json.loads(line)
                reports.append(rec)
            except json.JSONDecodeError:
                pass
    sampler.stop.set()
    sampler.join(timeout=5)
    return judge(sampler.samples), reports


def case_stale(root: pathlib.Path) -> dict:
    """SIGKILL a holder without releasing; the next acquirer must break the lock and proceed."""
    gov = str(root / "scripts" / "gpu-governor.sh")
    victim = subprocess.Popen(
        [sys.executable, "-c",
         "import subprocess,os,sys,time\n"
         f"env=dict(os.environ, SYMONEURAL_OWNER_PID=str(os.getpid()))\n"
         f"subprocess.run([{gov!r},'acquire','lease-stale','30'],env=env)\n"
         "time.sleep(300)\n"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True, cwd=ROOT)
    held = None
    for _ in range(80):
        time.sleep(0.25)
        held = holder_of(root)
        if held:
            break
    if not held:
        victim.kill()
        return {"ok": False, "why": "the victim never took the lock"}
    os.killpg(os.getpgid(victim.pid), signal.SIGKILL)
    victim.wait(timeout=20)
    started = time.monotonic()
    env = dict(os.environ, SYMONEURAL_OWNER_PID=str(os.getpid()),
               SYMONEURAL_DRAIN_TIMEOUT_S="3")
    r = subprocess.run([gov, "acquire", "lease-next", "40"], env=env,
                       capture_output=True, text=True, timeout=180)
    waited = round(time.monotonic() - started, 2)
    got = holder_of(root)
    log = (r.stdout or "") + (r.stderr or "")
    if r.returncode == 0:
        subprocess.run([gov, "release", "lease-next"], env=env, capture_output=True, timeout=90)

    # THE MECHANISM UNDER TEST is `break_if_stale`: a holder that died without releasing must
    # not wedge the card forever (`gpu-governor.sh:131`). Assert that, not the exit code.
    #
    # The exit code cannot be the assertion on this box. After the break, `cmd_acquire` evicts
    # the recorded resident, and for a surface with no `evict` arm that ends in a PATTERNLESS
    # drain -- which reads the whole card's compute against a 1024 MiB floor while production's
    # chat engine holds 8330 MiB. So the hand-over is refused. That refusal is the governor
    # being conservative and CORRECT: it will not hand over a card it cannot confirm is clear.
    # An isolated root isolates the LOCK; it does not isolate the card.
    broke = "breaking the lock" in log
    wedged = got is not None and got[1] == held[1]      # still naming the dead pid
    return {"ok": broke and not wedged,
            "stale_holder": held, "waited_s": waited, "new_holder": got,
            "lock_broken": broke, "still_wedged_on_dead_pid": wedged,
            "acquire_rc": r.returncode,
            "handover": "granted" if r.returncode == 0 else "refused by drain (expected here)",
            "log": [l for l in log.strip().splitlines() if l.strip()][-4:]}


# ------------------------------------------------------------------ main
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--worker", nargs=4, metavar=("SURFACE", "ROOT", "PORT", "HOLD"))
    ap.add_argument("--only", choices=["proof", "negative", "stale"])
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    if args.worker:
        s, r, p, h = args.worker
        return worker(s, r, int(p), float(h))

    for path, what in ((GOVERNOR, "governor"), (ENGINE, "engine"), (MODEL, "model")):
        if not path.exists():
            print(f"missing {what}: {path}", file=sys.stderr)
            return 1

    print("two-process GPU lease proof\n")

    # ---------------------------------------------------------- clean start
    print("== clean start ==")
    prod_lock = ROOT / "run" / "gpu.lock.d"
    if prod_lock.exists():
        h = holder_of(ROOT)
        print(f"  REFUSING: {prod_lock} exists (holder {h}).")
        print("  A stale or live holder makes 'never two holders' true for the wrong reason.")
        return 1
    print(f"  production {prod_lock.relative_to(ROOT)}: absent -- free")
    t0 = vram()
    apps0 = compute_apps()
    print(f"  VRAM at t=0: {t0.get('used_mib')} MiB used / {t0.get('free_mib')} MiB free "
          f"of {t0.get('total_mib')}")
    print(f"  compute contexts at t=0: {apps0 or 'none'}")
    if apps0:
        print("  NOTE: the card is not empty. The live chat engine is resident by design, so")
        print("        this proof measures contention on a WARM card, not a cold one.")
    results: dict[str, dict] = {}

    # ---------------------------------------------------------- the proof
    if args.only in (None, "proof"):
        print("\n== the proof: two processes, ONE shared lock ==")
        shared = make_root("shared")
        try:
            verdict, reports = run_pair([shared])
            results["proof"] = verdict
            for r in reports:
                print(f"  {r['surface']}: acquired={r.get('acquired')} "
                      f"waited={r.get('waited_s')}s resident_after={r.get('resident_after_s')}s "
                      f"engine_pid={r.get('engine_pid')}")
            print(f"  samples={verdict['samples']}  holders seen={verdict['distinct_holders_seen']}")
            print(f"  contended={verdict['contended']}  "
                  f"two-holder samples={verdict['two_holders_samples']}  "
                  f"two-resident samples={verdict['two_resident_samples']}  "
                  f"peak ours={verdict['peak_ours_mib']} MiB")
            print(f"  -> {'PASS' if verdict['ok'] and verdict['contended'] else 'FAIL'}")
            if not verdict["contended"]:
                print("     (a run where only one worker ever held the lock proves nothing)")
        finally:
            shutil.rmtree(shared, ignore_errors=True)

    # ---------------------------------------------------------- negative control
    if args.only in (None, "negative"):
        print("\n== negative control: two processes, TWO roots -- MUST go red ==")
        print("  `gpu-governor.sh:29-30` warns a wrong RUN silently unshares the lock.")
        a, b = make_root("neg-a"), make_root("neg-b")
        try:
            verdict, reports = run_pair([a, b])
            results["negative"] = verdict
            print(f"  samples={verdict['samples']}  holders seen={verdict['distinct_holders_seen']}")
            print(f"  two-holder samples={verdict['two_holders_samples']}  "
                  f"two-resident samples={verdict['two_resident_samples']}  "
                  f"peak ours={verdict['peak_ours_mib']} MiB")
            went_red = not verdict["ok"]
            print(f"  -> {'PASS (it went red, as required)' if went_red else 'FAIL -- the control did NOT fail'}")
            if not went_red:
                print("     A proof that cannot fail is not evidence. This is the check on the check.")
        finally:
            shutil.rmtree(a, ignore_errors=True)
            shutil.rmtree(b, ignore_errors=True)

    # ---------------------------------------------------------- stale holder
    if args.only in (None, "stale"):
        print("\n== stale holder: SIGKILL a holder, the next acquirer must proceed ==")
        r = make_root("stale")
        try:
            v = case_stale(r)
            results["stale"] = v
            print(f"  killed holder: {v.get('stale_holder')}")
            print(f"  lock broken by break_if_stale: {v.get('lock_broken')}")
            print(f"  still wedged on the dead pid: {v.get('still_wedged_on_dead_pid')}")
            print(f"  hand-over: {v.get('handover')}  (acquire rc={v.get('acquire_rc')}, "
                  f"waited {v.get('waited_s')}s)")
            for line in v.get("log") or []:
                print(f"    {line}")
            print(f"  -> {'PASS' if v['ok'] else 'FAIL: ' + str(v.get('why', ''))}")
        finally:
            shutil.rmtree(r, ignore_errors=True)

    # ---------------------------------------------------------- after
    print("\n== after ==")
    t1, apps1 = vram(), compute_apps()
    print(f"  VRAM: {t1.get('used_mib')} MiB used / {t1.get('free_mib')} free "
          f"(t=0 was {t0.get('used_mib')}/{t0.get('free_mib')})")
    print(f"  compute contexts: {apps1 or 'none'}")
    leaked = set(apps1) - set(apps0)
    print(f"  leaked contexts: {leaked or 'none'}")
    print(f"  production lock: {'HELD -- BAD' if prod_lock.exists() else 'absent -- free'}")

    ok = True
    if "proof" in results:
        ok &= results["proof"]["ok"] and results["proof"]["contended"]
    if "negative" in results:
        ok &= not results["negative"]["ok"]
    if "stale" in results:
        ok &= results["stale"]["ok"]
    ok &= not leaked and not prod_lock.exists()

    if args.json:
        print("\n" + json.dumps({"t0": t0, "t1": t1, "results": results, "ok": ok}, indent=2))
    print(f"\n{'=' * 70}\n  {'ALL CASES AS REQUIRED' if ok else 'SOMETHING DID NOT HOLD'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
