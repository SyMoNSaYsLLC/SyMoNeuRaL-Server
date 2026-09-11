"""Reading the card. One nvidia-smi exec per second at most, shared by every caller.

Extracted from `backend/server.py` unchanged. This is the first real extraction out of that
4,400-line file and the shape `SPLIT-API` repeats, so it is deliberately small and boring:
the same functions, the same state, the same behaviour, in a file whose subject is one thing.

## Why it is its own module rather than part of `gpu.py`

The lease and the card reading answer different questions. The lease says *who may touch the
GPU*; this says *what the GPU currently reports*. They are used together and neither needs the
other -- nothing here takes a lock, and `gpu.py` does not read telemetry.

Splitting them now rather than later is the 500-line rule applied before the fact: the lease
plus the card reading plus the drain arithmetic that is still in `scripts/gpu-governor.sh`
would not fit one module, and finding that out after writing it is how a file gets to 4,400
lines in the first place.

## The one thing to know before calling `smi()`

`smi()` is synchronous and, on a cache miss, execs `nvidia-smi` itself with an 8 s timeout.
**Do not call it from a coroutine without offloading.** `refresh_telemetry()` is the
`asyncio.to_thread` wrapper and is what request handlers should use -- `/api/status` did not,
and every poll of the most-polled endpoint on the box execed on the event loop until
`121806af`. The two call sites disagreed about the same function, which is how it was found.
"""
from __future__ import annotations

import asyncio
import logging
import pathlib
import subprocess
import time

log = logging.getLogger("symoneural.api")

_TELEMETRY_FIELDS = ("memory.free", "memory.total", "power.draw", "temperature.gpu")
_telemetry: dict[str, float | int | None] = {}
_telemetry_at = 0.0
_TELEMETRY_TTL = 1.0

# Why the driver's health is read from the telemetry call instead of its own probe:
# `/api/status` is polled and also drives the websocket for every connected visitor, so it
# must not spawn a process per request. `_read_smi()` already execs nvidia-smi at most once
# per second, and a driver problem makes THAT call fail -- so the fault is free information
# sitting in a call we were making anyway. Classifying it here adds no exec at all.
#
# Staleness window: driver state is at most `_TELEMETRY_TTL` (1 s) stale, same as the
# numbers beside it. A mismatch does not come and go, so one second is far more freshness
# than the fault needs.
_smi_fault: tuple[str, str] = ("ok", "")

#: What `nvidia-smi` says when the kernel module and the userspace library disagree. This is
#: the 2026-09-09 case: a dist-upgrade replaced the driver, the running kernel kept the old
#: modules, and every GPU path failed while the API reported itself healthy.
_MISMATCH_MARKERS = (
    "driver/library version mismatch",
    "failed to initialize nvml",
    "couldn't communicate with the nvidia driver",
)

#: nvidia-persistenced's pidfile. A stat, not a `systemctl is-active` subprocess, because
#: this is read on the status path. It was `loaded failed failed` on this box before the
#: 2026-09-09 reboot, alongside the mismatch.
_PERSISTENCED_PID = pathlib.Path("/run/nvidia-persistenced/nvidia-persistenced.pid")


def _read_smi() -> dict[str, float | int | None]:
    """All four telemetry fields in ONE nvidia-smi call.

    This used to be four separate synchronous `subprocess.run` calls made from inside async
    request handlers, each with an 8 second timeout. Every status poll therefore blocked the
    event loop across four process spawns -- and the loop it was blocking is the one
    streaming chat tokens, so a visitor watching the rack could stall someone else's
    generation. One exec, off the loop, cached for a second.

    Float for fractional fields (power.draw reads '11.42'), int for the rest. Casting
    everything to int silently turned power draw into None, which the rack rendered as a
    dead sensor -- a display that quietly shows nothing is worse than one showing a wrong
    number, because nobody goes looking for the bug.
    """
    global _smi_fault
    try:
        out = subprocess.run(
            ["nvidia-smi", f"--query-gpu={','.join(_TELEMETRY_FIELDS)}",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=8)
        if out.returncode != 0:
            _smi_fault = _classify_smi_failure(out.returncode, out.stderr, out.stdout)
            return dict.fromkeys(_TELEMETRY_FIELDS)
        parts = [p.strip() for p in out.stdout.strip().splitlines()[0].split(",")]
        values: dict[str, float | int | None] = {}
        for name, raw in zip(_TELEMETRY_FIELDS, parts):
            try:
                values[name] = float(raw) if "." in raw else int(raw)
            except ValueError:
                values[name] = None
        # The driver answered. The only remaining GPU-health question is whether
        # nvidia-persistenced is up, which is a stat rather than a subprocess.
        _smi_fault = (("ok", "") if _PERSISTENCED_PID.exists() else (
            "persistenced_down",
            "The driver is healthy but nvidia-persistenced is not running, so the first GPU "
            "request of each idle period pays the driver-initialisation cost. Surfaces work; "
            "cold requests are slower. `systemctl status nvidia-persistenced`."))
        return values
    except FileNotFoundError:
        _smi_fault = ("absent", "No nvidia-smi on PATH: this host has no NVIDIA driver "
                                "installed. GPU surfaces cannot serve here; CPU surfaces "
                                "are unaffected.")
        return dict.fromkeys(_TELEMETRY_FIELDS)
    except Exception as exc:
        _smi_fault = ("unreadable", f"nvidia-smi did not complete "
                                    f"({type(exc).__name__}). GPU state is unknown.")
        return dict.fromkeys(_TELEMETRY_FIELDS)


def _classify_smi_failure(rc: int, stderr: str, stdout: str) -> tuple[str, str]:
    """Turn a failed nvidia-smi into a state an operator can act on.

    The distinction that matters is **mismatch versus anything else**, because a mismatch is
    the one class of GPU fault that restarting this service cannot fix -- the kernel module
    and the userspace library have to be brought back into agreement, and on this box that
    means a reboot. Reporting it as a generic surface failure is what made the 2026-09-09
    upgrade read as "the app is broken" instead of "reboot the box".
    """
    blob = f"{stderr}\n{stdout}".lower()
    if any(m in blob for m in _MISMATCH_MARKERS):
        return ("mismatch",
                "NVIDIA driver/library version mismatch: the loaded kernel module and the "
                "userspace library disagree, which happens when a driver upgrade lands "
                "under a running kernel. REBOOT REQUIRED -- restarting this service will "
                "not fix it. CPU surfaces are unaffected and still serving.")
    first = next((l for l in stderr.splitlines() if l.strip()), "").strip()
    return ("unreadable",
            f"nvidia-smi exited {rc}"
            + (f": {first[:200]}" if first else " with no message")
            + ". GPU state is unknown; CPU surfaces are unaffected.")


def gpu_driver_health() -> tuple[str, str]:
    """(state, detail) for the driver. One of ok / mismatch / persistenced_down /
    absent / unreadable.

    Reads through the telemetry cache, so calling it costs nothing beyond the one
    nvidia-smi exec per second that the rack already performs.
    """
    smi("memory.total")            # refreshes `_smi_fault` if the cache has expired
    return _smi_fault


def smi(field: str):
    """One telemetry field, from a short-lived cache."""
    global _telemetry, _telemetry_at
    now = time.monotonic()
    if now - _telemetry_at > _TELEMETRY_TTL:
        _telemetry = _read_smi()
        _telemetry_at = now
    return _telemetry.get(field)


async def refresh_telemetry() -> None:
    """Refresh the cache off the event loop."""
    global _telemetry, _telemetry_at
    _telemetry = await asyncio.to_thread(_read_smi)
    _telemetry_at = time.monotonic()
