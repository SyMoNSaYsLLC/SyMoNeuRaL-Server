#!/usr/bin/env python3
"""Break the API's prerequisites one at a time and record what an operator would actually see.

    python3 tools/failure_modes.py                 # every case
    python3 tools/failure_modes.py --only governor  # one case
    python3 tools/failure_modes.py --baseline       # clean foreground start only

The question is not "does it fail" -- of course it fails. The question is **whether it fails
at startup with a message naming the cause, or starts green and fails later at request time.**
The second is the defect commissioning exists to find, because a service that starts is
assumed to work, and a 500 on first use reads to an operator as "the app is broken" rather
than "this prerequisite is missing".

Safety, because this deliberately breaks things:

  * Test instances bind **port 8801**, never 8800. The production service keeps serving
    throughout, and a test that hangs or crashes cannot take it down.
  * Exactly **one** break is held at a time, each restored in a `finally` so an exception
    restores state rather than leaving it.
  * After every restore, production `/api/status` is re-checked **and** the backup file is
    confirmed gone. A restore nobody verified is not a restore.
  * It never stops, starts or restarts the systemd unit -- that is polkit-gated here, so it
    is root work and belongs in `ops/commission-apply.sh`.

Manual recovery, if this dies part-way:
`review/commissioning-20260909/PHASE3-RECOVERY.md`.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import shutil
import signal
import stat
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


def _repo_root() -> Path:
    """Find the root by its marker, not by counting parents."""
    here = Path(__file__).resolve()
    for cand in (here, *here.parents):
        if (cand / "backend" / "api.py").is_file():
            return cand
    raise SystemExit(f"repo root not found above {here}: no backend/api.py marker")


ROOT = _repo_root()
TEST_PORT = 8801
PROD_URL = "http://127.0.0.1:8800/api/status"
BAK = ".commission-bak"
EVID = ROOT / "review" / "commissioning-20260909"
#: Deliberately NOT under run/: one of the cases below makes run/ unwritable, and a harness
#: whose own bookkeeping lives in the directory it is breaking cannot clean up after itself.
PIDFILE = EVID / "phase3-foreground.pid"

#: The unit's environment, reconstructed. Deliberately WITHOUT LD_LIBRARY_PATH: `systemctl
#: show symoneural-api -p Environment` reports only PYTHONUNBUFFERED and SYMONEURAL_PORT, and
#: an interactive shell here carries LD_LIBRARY_PATH=/usr/local/cuda/lib64 which changes which
#: CUDA runtime symoneural-diffuse loads. Inheriting the shell's copy would make a foreground
#: test pass while production behaved differently -- the exact class of lie this phase exists
#: to catch.
def unit_env(port: int, extra: dict[str, str] | None = None) -> dict[str, str]:
    env = {
        "PATH": "/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        "HOME": os.environ.get("HOME", "/home/google"),
        "USER": os.environ.get("USER", "google"),
        "LANG": os.environ.get("LANG", "C.UTF-8"),
        "PYTHONUNBUFFERED": "1",
        "SYMONEURAL_PORT": str(port),
    }
    if extra:
        env.update(extra)
    return env


def http_code(url: str, timeout: float = 10.0) -> int:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.status
    except urllib.error.HTTPError as e:
        return e.code
    except Exception:
        return 0


def prod_healthy() -> bool:
    return http_code(PROD_URL) == 200


class Attempt:
    """One foreground start: did it come up, how long, and what did it say."""

    def __init__(self, started: bool, seconds: float, code: int,
                 output: str, exit_code: int | None) -> None:
        self.started = started
        self.seconds = seconds
        self.code = code
        self.output = output
        self.exit_code = exit_code

    @property
    def verdict(self) -> str:
        if self.started and self.code == 200:
            return "STARTED AND SERVED"
        if self.started:
            return f"started but /api/status returned {self.code}"
        return f"REFUSED TO START (exit {self.exit_code})"


def start_foreground(port: int = TEST_PORT, extra_env: dict[str, str] | None = None,
                     wait: float = 45.0, tag: str = "baseline") -> Attempt:
    """Launch api.py the way ExecStart does and watch until it serves or dies.

    Everything after `Popen` lives inside the try, including writing the pidfile. The first
    version wrote the pidfile *before* the try and put it under `run/` -- so the case that
    chmods `run/` to 0500 raised PermissionError in the gap between spawning the child and
    arming its cleanup, and orphaned a live server on 8801. It was found by looking for it,
    not by the harness noticing. Hence both changes: the window is closed, and neither the
    log nor the pidfile lives under a directory these tests deliberately break.
    """
    log = EVID / f"phase3-{tag}.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    url = f"http://127.0.0.1:{port}/api/status"
    proc = None
    try:
        with log.open("wb") as fh:
            proc = subprocess.Popen(
                [sys.executable, "backend/api.py"],
                cwd=str(ROOT), env=unit_env(port, extra_env),
                stdout=fh, stderr=subprocess.STDOUT,
                start_new_session=True,      # its own process group; never signals ours
            )
        PIDFILE.write_text(str(proc.pid))
        t0 = time.monotonic()
        code = 0
        while time.monotonic() - t0 < wait:
            if proc.poll() is not None:      # died before serving
                break
            code = http_code(url, timeout=3.0)
            if code:
                break
            time.sleep(0.25)
        elapsed = time.monotonic() - t0
        alive = proc.poll() is None
        return Attempt(alive and bool(code), elapsed, code,
                       log.read_text(errors="replace"), proc.returncode)
    finally:
        if proc is not None and proc.poll() is None:
            os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            try:
                proc.wait(timeout=20)
            except subprocess.TimeoutExpired:
                os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                proc.wait(timeout=10)
        PIDFILE.unlink(missing_ok=True)


@contextlib.contextmanager
def moved_away(target: Path):
    """Rename a path aside and put it back, whatever happens.

    A rename inside one directory is instantaneous and rewrites no data, so a 6 GB model is
    as cheap to 'remove' as a shell script and is provably not deleted.
    """
    bak = target.with_name(target.name + BAK)
    if not target.exists():
        raise SystemExit(f"refusing to break what is already absent: {target}")
    if bak.exists():
        raise SystemExit(f"a previous run left {bak}; see PHASE3-RECOVERY.md")
    mode = stat.S_IMODE(target.stat().st_mode)
    target.rename(bak)
    try:
        yield
    finally:
        bak.rename(target)
        target.chmod(mode)


@contextlib.contextmanager
def mode_changed(target: Path, new_mode: int):
    original = stat.S_IMODE(target.stat().st_mode)
    target.chmod(new_mode)
    try:
        yield
    finally:
        target.chmod(original)


def classify(a: Attempt, surface: str) -> tuple[str, str]:
    """fail-fast vs fail-late, and the line an operator would actually read."""
    if not a.started:
        tail = [l for l in a.output.strip().splitlines() if l.strip()]
        return "fail-fast", (tail[-1][:200] if tail else "(no output)")
    return "fail-late", (f"started clean; {surface} will fail at request time "
                         f"with nothing said at startup")


CASES = ("governor", "config", "badport", "runperms", "model")


def run_case(name: str) -> dict:
    """One break, held alone, restored in a finally."""
    if not prod_healthy():
        raise SystemExit("production /api/status is not 200 BEFORE the break; "
                         "refusing to proceed -- a failure would not be attributable")

    if name == "governor":
        target = ROOT / "scripts" / "gpu-governor.sh"
        with moved_away(target):
            a = start_foreground(tag="governor")
        kind, msg = classify(a, "every GPU surface")
        expect = "fail-fast: api.py:58 asserts the file exists at import"

    elif name == "config":
        target = ROOT / "run" / "config" / "api.env"
        with moved_away(target):
            a = start_foreground(tag="config")
        kind, msg = classify(a, "the surfaces the env file enables")
        expect = "unknown before measuring"

    elif name == "badport":
        a = start_foreground(extra_env={"SYMONEURAL_PORT": "not-a-port"}, tag="badport")
        kind, msg = classify(a, "the whole service")
        expect = "fail-fast: int() on a non-numeric port at api.py:348"

    elif name == "runperms":
        target = ROOT / "run"
        with mode_changed(target, 0o500):
            a = start_foreground(tag="runperms")
        kind, msg = classify(a, "anything that writes under run/")
        expect = "unknown before measuring"

    elif name == "model":
        target = ROOT / "backend" / "models" / "llm" / "symon-1.0-draft-0.5b-q4_k_m.gguf"
        with moved_away(target):
            a = start_foreground(tag="model")
        kind, msg = classify(a, "/api/chat speculative decoding")
        expect = "fail-late: MODELS paths are Path objects at module scope, never stat'd"

    else:
        raise SystemExit(f"unknown case {name}")

    # The restore has already run in the finally above. Verify it, twice over.
    leftovers = [str(p.relative_to(ROOT))
                 for p in ROOT.rglob(f"*{BAK}") if ".git" not in p.parts]
    healthy = prod_healthy()

    return {
        "case": name,
        "verdict": a.verdict,
        "kind": kind,
        "operator_sees": msg,
        "expected": expect,
        "seconds_to_serve": round(a.seconds, 2),
        "restore_verified": healthy and not leftovers,
        "leftover_backups": leftovers,
        "prod_still_200": healthy,
    }


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--only", choices=CASES)
    ap.add_argument("--baseline", action="store_true",
                    help="clean foreground start, no break")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    if args.baseline:
        a = start_foreground()
        print(f"clean foreground start on :{TEST_PORT} -> {a.verdict} "
              f"in {a.seconds:.2f}s")
        print("--- captured output ---")
        print(a.output.strip())
        return 0 if a.started else 1

    cases = [args.only] if args.only else list(CASES)
    results = []
    for name in cases:
        r = run_case(name)
        results.append(r)
        if not r["restore_verified"]:
            print(json.dumps(r, indent=2))
            raise SystemExit(
                f"RESTORE FAILED after case '{name}'. Stopping immediately rather than "
                "testing on a half-broken box. See PHASE3-RECOVERY.md.")
        if not args.json:
            print(f"\n== {name} ==")
            print(f"  result        : {r['verdict']}")
            print(f"  classified    : {r['kind']}")
            print(f"  operator sees : {r['operator_sees']}")
            print(f"  expected      : {r['expected']}")
            print(f"  restored      : yes (prod 200, no leftover backups)")

    if args.json:
        print(json.dumps(results, indent=2))
    else:
        fast = sum(1 for r in results if r["kind"] == "fail-fast")
        print(f"\n  {len(results)} case(s): {fast} fail-fast, {len(results) - fast} fail-late")
        print("  every restore verified; production served throughout")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
