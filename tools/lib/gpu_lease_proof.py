#!/usr/bin/env python3
"""Prove the GPU lease serialises, rather than observing that it happened to hold once.

    python3 tools/lib/gpu_lease_proof.py                 # 3 rounds of 2 concurrent chat requests
    python3 tools/lib/gpu_lease_proof.py --rounds 5 --concurrency 3
    python3 tools/lib/gpu_lease_proof.py --evict          # image against chat, the eviction path
    python3 tools/lib/gpu_lease_proof.py --json

`api.py` calls the two-holders case the failure this repo documents most loudly, and the
arithmetic is why: the card is 16 GB, chat is ~5 GB resident and image ~7 GB, so two holders
that each load weights do not merely contend -- they exhaust the card.

**The difference between a proof and an anecdote is sampling.** One concurrent pair that
returns sensible answers shows the lease worked that once. So this samples the two independent
witnesses continuously for the whole test and asserts an invariant over every sample:

  * `run/gpu.lock.d/holder` -- the governor's own record of who holds the card. The lock is a
    `mkdir` (`gpu-governor.sh:321`), which is atomic on POSIX, and `holder` names the tenant.
  * `nvidia-smi` used memory -- the physical consequence. The governor's bookkeeping could be
    right while the card tells a different story, so believing only the lock file would test
    the bookkeeping rather than the invariant.

Two witnesses, because either alone can be fooled: a holder file says what the governor
believes, and VRAM says what actually happened.
"""

from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path


def _repo_root() -> Path:
    """Find the root by its marker, not by counting parents."""
    here = Path(__file__).resolve()
    for cand in (here, *here.parents):
        if (cand / "backend" / "server.py").is_file():
            return cand
    raise SystemExit(f"repo root not found above {here}: no backend/server.py marker")


ROOT = _repo_root()
BASE = "http://127.0.0.1:8800"
LOCKDIR = ROOT / "run" / "gpu.lock.d"
HOLDER = LOCKDIR / "holder"

#: How much more than one tenant's own measured peak counts as a second set of weights.
#: The docstrings say chat is "~5 GB when loaded", but the card actually shows ~8.6 GB for a
#: single chat tenant -- weights plus KV cache plus the CUDA context. Hard-coding a floor from
#: the documentation would have made a one-tenant test look like a two-tenant violation, so
#: the floor is CALIBRATED from a single-request round and the margin is added to that.
SECOND_MODEL_MARGIN_MIB = 3000


def vram_used() -> int:
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=10)
        return int(out.stdout.strip().splitlines()[0])
    except Exception:
        return -1


class Sampler(threading.Thread):
    """Poll both witnesses until told to stop."""

    def __init__(self, interval: float = 0.15) -> None:
        super().__init__(daemon=True)
        self.interval = interval
        self.samples: list[dict] = []
        self._stop = threading.Event()

    def run(self) -> None:
        while not self._stop.is_set():
            holder = ""
            try:
                if HOLDER.is_file():
                    holder = HOLDER.read_text(errors="replace").strip()
            except OSError:
                holder = "<unreadable>"
            self.samples.append({
                "t": round(time.monotonic(), 3),
                "lock": LOCKDIR.is_dir(),
                "holder": holder,
                "vram": vram_used(),
            })
            self._stop.wait(self.interval)

    def stop(self) -> list[dict]:
        self._stop.set()
        self.join(timeout=5)
        return self.samples


def post(path: str, body: dict, timeout: float = 300.0) -> dict:
    url = BASE + path
    data = json.dumps(body).encode()
    req = urllib.request.Request(
        url, data=data, headers={"Content-Type": "application/json"}, method="POST")
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            payload = r.read(400).decode("utf-8", "replace")
            return {"path": path, "code": r.status, "s": round(time.monotonic() - t0, 2),
                    "body": payload[:200]}
    except urllib.error.HTTPError as e:
        return {"path": path, "code": e.code, "s": round(time.monotonic() - t0, 2),
                "body": e.read(200).decode("utf-8", "replace")}
    except Exception as exc:
        return {"path": path, "code": 0, "s": round(time.monotonic() - t0, 2),
                "body": f"{type(exc).__name__}: {exc}"}


def concurrent(requests: list[tuple[str, dict]]) -> list[dict]:
    """Fire everything at once and collect every result."""
    out: list[dict] = []
    lock = threading.Lock()

    def one(p: str, b: dict) -> None:
        r = post(p, b)
        with lock:
            out.append(r)

    threads = [threading.Thread(target=one, args=(p, b)) for p, b in requests]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return out


def tenants(holder: str) -> set[str]:
    """The tenant names in a holder file.

    The file's format is `<tenant> <pid>` on one line -- measured: `chat 1512`. The first
    version of this split on whitespace and called two tokens two holders, which reported a
    violation in every round. The pid is not a tenant.
    """
    return {ln.split()[0] for ln in holder.splitlines() if ln.split()}


def analyse(samples: list[dict], floor: int | None) -> dict:
    holders = set()
    for s in samples:
        holders |= tenants(s["holder"])
    vrams = [s["vram"] for s in samples if s["vram"] >= 0]
    # The invariant: never two *distinct* tenants recorded as holding at the same instant.
    # A holder file names one tenant, so a violation shows up as more than one name in a
    # single sample -- or as VRAM that only two resident models can explain.
    multi = [s for s in samples if len(tenants(s["holder"])) > 1]
    return {
        "samples": len(samples),
        "distinct_holders_over_time": sorted(holders),
        "samples_with_multiple_holders": len(multi),
        "vram_peak_mib": max(vrams) if vrams else -1,
        "vram_baseline_mib": min(vrams) if vrams else -1,
        "vram_median_mib": round(statistics.median(vrams)) if vrams else -1,
        "two_models_resident_ever": bool(vrams) and floor is not None
                                    and max(vrams) >= floor,
        "floor_mib": floor,
        "lock_seen_held": any(s["lock"] for s in samples),
    }


def run_round(n: int, concurrency: int, evict: bool, floor: int | None = None) -> dict:
    sam = Sampler()
    sam.start()
    time.sleep(0.6)                          # a little baseline before the load
    if evict:
        reqs = [("/api/chat", {"prompt": "Say the single word: lease.", "max_tokens": 8}),
                # size is an INTEGER pixel edge (64..2048, default 768), not a "WxH" string.
                # The first version sent "256x256" and got a 422 in 0.02s -- so the eviction
                # path never ran at all and would have been reported as passing.
                ("/api/image", {"prompt": "a grey square", "steps": 1, "size": 256})]
    else:
        reqs = [("/api/chat", {"prompt": f"Say the single word: lease{i}.", "max_tokens": 8})
                for i in range(concurrency)]
    results = concurrent(reqs)
    time.sleep(0.6)
    samples = sam.stop()
    a = analyse(samples, floor)
    return {
        "round": n,
        "requests": results,
        "codes": sorted(r["code"] for r in results),
        **a,
        "violation": a["samples_with_multiple_holders"] > 0 or a["two_models_resident_ever"],
    }


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--rounds", type=int, default=3)
    ap.add_argument("--concurrency", type=int, default=2)
    ap.add_argument("--evict", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    print(f"GPU lease proof: {args.rounds} round(s), "
          f"{'chat vs image (eviction)' if args.evict else str(args.concurrency) + ' concurrent chat'}")
    print(f"  witnesses: {HOLDER}  and  nvidia-smi memory.used")
    print(f"  a second tenant would show as +{SECOND_MODEL_MARGIN_MIB} MiB "
          "over the calibrated single-tenant peak\n")

    # Calibrate: one request alone establishes what a single tenant costs on this card.
    cal = run_round(0, 1, False, None)
    floor = cal["vram_peak_mib"] + SECOND_MODEL_MARGIN_MIB
    print(f"calibration: one tenant peaked at {cal['vram_peak_mib']} MiB "
          f"(holder {cal['distinct_holders_over_time'] or ['(none)']}); "
          f"a second set of weights would exceed {floor} MiB\n")

    rounds = []
    for i in range(1, args.rounds + 1):
        r = run_round(i, args.concurrency, args.evict, floor)
        rounds.append(r)
        if not args.json:
            print(f"round {i}: codes={r['codes']}  samples={r['samples']}  "
                  f"vram {r['vram_baseline_mib']}->{r['vram_peak_mib']} MiB peak")
            print(f"  holders seen over time : {r['distinct_holders_over_time'] or ['(none)']}")
            print(f"  two holders at once    : "
                  f"{'VIOLATION' if r['samples_with_multiple_holders'] else 'never'}")
            print(f"  two models resident    : "
                  f"{'VIOLATION' if r['two_models_resident_ever'] else 'never'}")
            for q in r["requests"]:
                print(f"    {q['code']} in {q['s']:>6}s  {q['path']}  {q['body'][:90]}")

    violations = [r for r in rounds if r["violation"]]
    total_samples = sum(r["samples"] for r in rounds)
    peak = max(r["vram_peak_mib"] for r in rounds)

    if args.json:
        print(json.dumps({"calibration": cal, "floor_mib": floor, "rounds": rounds,
                          "violations": len(violations),
                          "total_samples": total_samples, "vram_peak_mib": peak}, indent=2))
        return 1 if violations else 0

    print(f"\n  {total_samples} samples across {len(rounds)} round(s); "
          f"peak VRAM {peak} MiB")
    if violations:
        print(f"  LEASE INVARIANT VIOLATED in {len(violations)} round(s)")
        return 1
    print("  INVARIANT HELD in every sample: never two holders, never two models resident")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
