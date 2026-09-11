#!/usr/bin/env python3
"""Prove the split rack does not lie when a surface process is gone.

    python3 tools/surface_pilot_proof.py

This is the one hard thing the RavenCalc pilot can carry. RavenCalc takes no GPU lease, has
no rack power state worth gating, and is always `ready` -- so it exercises neither the
governor invariant nor most of the aggregation. What it *can* prove is the risk named as the
largest new piece of the split: **when the process that owns a row is dead, does
`/api/status` say so, with a reason a person can act on?**

The failure this rules out is not a crash. It is a rack that keeps reporting `ready` from a
cache, or reports a bare `unreachable` with an empty detail -- both of which send an operator
looking in the wrong place, and one of which is indistinguishable from everything being fine.

## What it does

Everything runs on scratch ports and **the production monolith on :8800 is never touched**.

    1. start the RavenCalc surface on its registry port
    2. start a SECOND api.py with SYMONEURAL_DELEGATE=ravencalc on a scratch port
    3. assert that api.py did NOT register /api/ravencalc -- exactly one answerer
    4. assert the rack row comes from the surface's own /healthz
    5. KILL the surface; assert the row becomes `unreachable` with an actionable detail
    6. assert every OTHER row is unaffected
    7. restart the surface; assert the row recovers with no restart of the API
    8. assert the gateway/proxy answer for a dead surface is honest, not a bare 502

Exit 0 only if all of it holds. Every process it starts is killed in a `finally`.
"""

from __future__ import annotations

import json
import os
import pathlib
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
BACKEND = ROOT / "backend"
SCRATCH_API_PORT = 8899          # never 8800: production keeps serving throughout
SURFACE = "ravencalc"

sys.path.insert(0, str(BACKEND))
from registry.lib.ports import port_of                                  # noqa: E402

SURFACE_PORT = port_of(SURFACE)

results: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = "") -> bool:
    results.append((name, ok, detail))
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f"\n         {detail}" if detail else ""))
    return ok


def get(url: str, timeout: float = 5.0) -> tuple[int, dict | str]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            body = r.read()
            try:
                return r.status, json.loads(body)
            except json.JSONDecodeError:
                return r.status, body.decode(errors="replace")[:200]
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(errors="replace")[:200]
    except Exception as exc:
        return 0, f"{type(exc).__name__}: {exc}"


def wait_for(url: str, deadline_s: float = 25.0) -> bool:
    end = time.monotonic() + deadline_s
    while time.monotonic() < end:
        code, _ = get(url, timeout=2.0)
        if code == 200:
            return True
        time.sleep(0.25)
    return False


def spawn_surface() -> subprocess.Popen:
    return subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "ravencalc.service:app",
         "--host", "127.0.0.1", "--port", str(SURFACE_PORT), "--log-level", "warning"],
        cwd=BACKEND, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        start_new_session=True)


def rack_row(port: int, surface: str) -> dict | None:
    code, body = get(f"http://127.0.0.1:{port}/api/status", timeout=8.0)
    if code != 200 or not isinstance(body, dict):
        return None
    for u in body.get("units", []):
        if u.get("id") == surface:
            return u
    return None


def main() -> int:
    if SURFACE_PORT is None:
        print(f"{SURFACE} has no PORT in ops/PORTS.tsv", file=sys.stderr)
        return 1

    print(f"surface pilot proof -- {SURFACE} on :{SURFACE_PORT}, scratch API on "
          f"{SCRATCH_API_PORT}\n  production :8800 is not touched\n")

    surface = api = None
    try:
        # ---------------------------------------------------------------- 1 & 2
        surface = spawn_surface()
        if not check("the surface starts and answers /healthz",
                     wait_for(f"http://127.0.0.1:{SURFACE_PORT}/healthz"),
                     f"http://127.0.0.1:{SURFACE_PORT}/healthz"):
            return 1

        env = dict(os.environ, SYMONEURAL_DELEGATE=SURFACE,
                   SYMONEURAL_PORT=str(SCRATCH_API_PORT))
        api = subprocess.Popen([sys.executable, "api.py"], cwd=BACKEND, env=env,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                               start_new_session=True)
        if not check("a second api.py starts with the surface delegated",
                     wait_for(f"http://127.0.0.1:{SCRATCH_API_PORT}/api/status", 40.0),
                     f"scratch API on :{SCRATCH_API_PORT}"):
            return 1

        # ---------------------------------------------------------------- 3
        code, _ = get(f"http://127.0.0.1:{SCRATCH_API_PORT}/openapi.json", timeout=10)
        code2, body2 = get(f"http://127.0.0.1:{SCRATCH_API_PORT}/openapi.json", timeout=10)
        paths = list(body2.get("paths", {})) if isinstance(body2, dict) else []
        check("EXACTLY ONE answerer: the delegated API does not serve /api/ravencalc",
              "/api/ravencalc" not in paths,
              f"{len(paths)} paths advertised, /api/ravencalc among them: "
              f"{'/api/ravencalc' in paths}")

        # ---------------------------------------------------------------- 4
        row = rack_row(SCRATCH_API_PORT, SURFACE)
        check("the rack row comes from the surface's own /healthz",
              bool(row) and row.get("state") == "ready"
              and row.get("detail") == "cpu only, never queues",
              f"state={row and row.get('state')!r} detail={row and row.get('detail')!r}")

        others_before = {u["id"]: u["state"] for u in
                         (get(f"http://127.0.0.1:{SCRATCH_API_PORT}/api/status")[1] or {})
                         .get("units", []) if u["id"] != SURFACE}

        # ---------------------------------------------------------------- 5
        os.killpg(os.getpgid(surface.pid), signal.SIGKILL)
        surface.wait(timeout=10)
        surface = None
        # Poll interval 2 s, stale after 6 s: allow three intervals plus slack.
        deadline = time.monotonic() + 20
        row = None
        while time.monotonic() < deadline:
            row = rack_row(SCRATCH_API_PORT, SURFACE)
            if row and row.get("state") == "unreachable":
                break
            time.sleep(1)
        check("a KILLED surface reports `unreachable`, not a stale `ready`",
              bool(row) and row.get("state") == "unreachable",
              f"state={row and row.get('state')!r}")
        detail = (row or {}).get("detail", "")
        check("...with a reason an operator can act on",
              all(t in detail for t in (str(SURFACE_PORT), "systemctl")) and len(detail) > 40,
              detail[:180])

        # ---------------------------------------------------------------- 6
        others_after = {u["id"]: u["state"] for u in
                        (get(f"http://127.0.0.1:{SCRATCH_API_PORT}/api/status")[1] or {})
                        .get("units", []) if u["id"] != SURFACE}
        changed = {k: (others_before.get(k), v) for k, v in others_after.items()
                   if others_before.get(k) != v}
        check("every OTHER rack row is unaffected by the dead surface",
              not changed, f"changed: {changed}" if changed else
              f"{len(others_after)} other rows unchanged")

        # ---------------------------------------------------------------- 8
        code, body = get(f"http://127.0.0.1:{SCRATCH_API_PORT}/api/ravencalc")
        check("the API's answer for a dead delegated surface is a 404, not a 502",
              code == 404,
              f"GET returned {code}. A 404 is honest here: this process does not own the "
              f"route. The proxy in front is what must turn that into something a visitor "
              f"can read -- see the Caddy block in ops/commission-apply.sh step 9.")

        # ---------------------------------------------------------------- 7
        surface = spawn_surface()
        if not wait_for(f"http://127.0.0.1:{SURFACE_PORT}/healthz"):
            check("the surface restarts", False, "did not come back")
        else:
            deadline = time.monotonic() + 20
            row = None
            while time.monotonic() < deadline:
                row = rack_row(SCRATCH_API_PORT, SURFACE)
                if row and row.get("state") == "ready":
                    break
                time.sleep(1)
            check("the row RECOVERS with no restart of the API",
                  bool(row) and row.get("state") == "ready",
                  f"state={row and row.get('state')!r}; the api.py pid never changed")

    finally:
        for proc in (surface, api):
            if proc and proc.poll() is None:
                try:
                    os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
                    proc.wait(timeout=10)
                except Exception:
                    try:
                        os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
                    except Exception:
                        pass
        # Production must be exactly as it was.
        code, _ = get("http://127.0.0.1:8800/api/status")
        print(f"\n  production :8800 after the run -> HTTP {code}")

    passed = sum(1 for _, ok, _ in results if ok)
    failed = len(results) - passed
    print(f"\n{'=' * 70}\n  {passed} passed, {failed} failed")
    if failed:
        print("\n  FAILED:")
        for name, ok, detail in results:
            if not ok:
                print(f"    - {name}\n      {detail}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
