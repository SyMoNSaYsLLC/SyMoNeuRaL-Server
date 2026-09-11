#!/usr/bin/env python3
"""Read real telemetry off Antminer and MicroBT rigs, and print it as JSON.

**This file runs under `backend/apps/asicminer/.venv/bin/python`, NOT the serving
interpreter.** pyasic pulls in 31 packages; the API deliberately runs on the system
interpreter with fastapi, uvicorn, pydantic and sympy and nothing else. So the boundary is
a subprocess printing JSON on stdout -- the same shape as `scripts/gpu-governor.sh` and the
llama.cpp/stable-diffusion.cpp binaries, which the API also drives by exec rather than by
import. Nothing here is importable from the API and it must stay that way.

    .venv/bin/python probe.py 10.0.0.11 10.0.0.12      # probe named hosts
    .venv/bin/python probe.py --selftest               # no network, proves the venv works

Exit code is 0 whenever the probe itself ran, including when every rig was unreachable --
"no rig answered" is a result, not an error. A non-zero exit means the probe is broken.

**Honesty:** every field printed here is read off a rig. There is no placeholder, no
default hashrate and no simulated device. A rig that does not answer is reported
`reachable: false` with null readings, because the alternative -- a plausible-looking
number for hardware that is not there -- is exactly the dishonest pixel `.claude/CLAUDE.md`
forbids. Any figure this emits is **measured**; nothing here is vendor or projected.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys

TIMEOUT = 8.0          # a rig on a local network answers in well under a second


def _num(v):
    """pyasic returns rich types (AlgoHashRate, Decimal). Reduce to plain JSON numbers."""
    if v is None:
        return None
    for attr in ("rate", "value"):                      # AlgoHashRate-ish wrappers
        if hasattr(v, attr):
            v = getattr(v, attr)
            break
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if f != f else round(f, 3)              # drop NaN


async def probe_one(host: str) -> dict:
    """One rig. Never raises: an unreachable rig is a reading, not an exception."""
    out = {
        "host": host, "reachable": False, "vendor": None, "model": None,
        "firmware": None, "hashrate_th_s": None, "expected_th_s": None,
        "temp_c": None, "fans_rpm": [], "power_w": None, "uptime_s": None,
        "pools": [], "error": None,
    }
    try:
        from pyasic import get_miner
    except Exception as e:                              # venv broken -- say so plainly
        out["error"] = f"pyasic unavailable: {e.__class__.__name__}: {e}"
        return out

    try:
        miner = await asyncio.wait_for(get_miner(host), timeout=TIMEOUT)
    except asyncio.TimeoutError:
        out["error"] = f"no response within {TIMEOUT:.0f}s"
        return out
    except Exception as e:
        out["error"] = f"{e.__class__.__name__}: {e}"
        return out

    if miner is None:                                   # nothing on that address
        out["error"] = "no miner detected at this address"
        return out

    try:
        data = await asyncio.wait_for(miner.get_data(), timeout=TIMEOUT)
    except asyncio.TimeoutError:
        out["error"] = f"identified as {getattr(miner, 'model', '?')} but timed out reading data"
        return out
    except Exception as e:
        out["error"] = f"{e.__class__.__name__}: {e}"
        return out

    g = lambda k: getattr(data, k, None)                # noqa: E731 -- pyasic fields vary by model
    out.update(
        reachable=True,
        vendor=str(g("make") or getattr(miner, "make", None) or "") or None,
        model=str(g("model") or getattr(miner, "model", None) or "") or None,
        firmware=str(g("firmware") or "") or None,
        hashrate_th_s=_num(g("hashrate")),
        expected_th_s=_num(g("expected_hashrate")),
        temp_c=_num(g("temperature_avg")),
        power_w=_num(g("wattage")),
        uptime_s=_num(g("uptime")),
        fans_rpm=[s for s in (_num(getattr(f, "speed", f)) for f in (g("fans") or []))
                  if s is not None],
        pools=[
            {"url": str(getattr(p, "url", "") or ""), "user": str(getattr(p, "user", "") or ""),
             "active": bool(getattr(p, "active", False))}
            for p in (g("pools") or [])
        ],
    )
    return out


async def probe_all(hosts: list[str]) -> list[dict]:
    return list(await asyncio.gather(*(probe_one(h) for h in hosts)))


def selftest() -> dict:
    """Prove the venv is intact without touching the network.

    Worth having because this venv is pinned to an old pyasic for a specific reason (see
    README) and a silent upgrade breaks it at import time, which would otherwise surface
    as every rig appearing unreachable -- a misleading symptom pointing at the network.
    """
    r = {"ok": False, "pyasic": None, "backends": [], "error": None}
    try:
        import importlib.metadata as md
        r["pyasic"] = md.version("pyasic")
        from pyasic.rpc.bmminer import BMMinerRPCAPI    # Antminer
        from pyasic.rpc.btminer import BTMinerRPCAPI    # MicroBT / Whatsminer
        r["backends"] = [BMMinerRPCAPI.__name__, BTMinerRPCAPI.__name__]
        r["ok"] = True
    except Exception as e:
        r["error"] = f"{e.__class__.__name__}: {e}"
    return r


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("hosts", nargs="*", help="rig addresses to probe")
    ap.add_argument("--selftest", action="store_true",
                    help="check the venv without any network access")
    a = ap.parse_args()

    if a.selftest:
        print(json.dumps(selftest(), indent=2))
        return 0
    # No hosts is the normal state on a box with no rigs attached. Print an empty result
    # rather than a usage error, so the caller gets valid JSON either way.
    print(json.dumps({"rigs": asyncio.run(probe_all(a.hosts)) if a.hosts else []}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
