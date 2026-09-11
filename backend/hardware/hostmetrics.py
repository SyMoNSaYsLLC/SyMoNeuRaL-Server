"""CPU, RAM and disk, read from this host. Same contract as `modelmetrics`: readings only.

Owner instruction, 2026-09-11: *"i want everything shown and available on the ui for model
hardware gpu cpu ram parameters sliders etc"*. The GPU half lives in `modelmetrics.py`; this
is the host half, and it is a separate module for the reason the 500-line rule exists rather
than because the two are conceptually far apart.

## Every figure is a reading with a source, and `None` never means zero

Identical to `modelmetrics.Reading` and deliberately the same shape, so the page renders both
with one function. A field that cannot be read carries the reason, because on a status page
"0 GB free" and "we could not ask" look the same and mean opposite things.

## Why `/proc` and not just psutil

psutil is installed here (7.0.0, measured) and is used for the things it does well --
per-core utilisation needs an interval sample and hand-rolling that is how you get a number
that is silently the average since boot. But `/proc/meminfo` and `/proc/loadavg` are read
directly: they are one file read with no interval, the kernel is the source, and naming
`/proc/meminfo` in the `source` field is more useful to somebody checking the number than
naming a library that read it for them.

## The one number people get wrong on this box

**`MemAvailable`, not `MemFree`.** Measured here right now: MemFree is 21.6 GB and
MemAvailable is 91.5 GB, because Linux has given ~70 GB to page cache that it will hand back
the moment anything asks. A dashboard showing MemFree on a 98 GB box reports 78% used when
the true figure is 7%, and somebody makes a capacity decision on it. Both are published, with
`MemAvailable` first and the difference explained.
"""
from __future__ import annotations

import asyncio
import os
import pathlib
import shutil
from typing import Any

from .modelmetrics import _reading

PROC = pathlib.Path("/proc")

#: Where the repo lives, for the disk reading. The page reports the filesystem that holds the
#: project, not "/" -- on this box `archive/` alone is 285 GB and it is the number that matters.
REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent


def _meminfo() -> dict[str, int]:
    """`/proc/meminfo` as kB ints. One file read, no interval, kernel is the source."""
    out: dict[str, int] = {}
    for line in (PROC / "meminfo").read_text().splitlines():
        key, _, rest = line.partition(":")
        parts = rest.split()
        if parts and parts[0].isdigit():
            out[key.strip()] = int(parts[0])
    return out


def read_memory() -> dict[str, Any]:
    """RAM. `MemAvailable` leads; `MemFree` is published beside it with the difference named."""
    src = "/proc/meminfo"
    try:
        m = _meminfo()
    except OSError as exc:
        why = f"{src} unreadable ({type(exc).__name__})"
        return {k: _reading(None, "GiB", why)
                for k in ("total", "available", "free", "cached", "used")}

    gib = lambda kb: round(kb / 1048576, 2)                              # noqa: E731
    total, avail = m.get("MemTotal", 0), m.get("MemAvailable", 0)
    return {
        "total": _reading(gib(total), "GiB", f"{src} MemTotal"),
        # The honest headroom figure. See the module docstring.
        "available": _reading(gib(avail), "GiB", f"{src} MemAvailable"),
        "free": _reading(gib(m.get("MemFree", 0)), "GiB",
                         f"{src} MemFree -- excludes reclaimable page cache; "
                         f"'available' is the number to plan against"),
        "cached": _reading(gib(m.get("Cached", 0)), "GiB", f"{src} Cached"),
        "used": _reading(gib(total - avail), "GiB", f"{src} MemTotal - MemAvailable"),
        "used_pct": _reading(round(100 * (total - avail) / total, 1) if total else None, "%",
                             f"{src} (MemTotal - MemAvailable) / MemTotal"),
    }


def read_load() -> dict[str, Any]:
    """Load average and the run-queue, straight out of `/proc/loadavg`."""
    src = "/proc/loadavg"
    try:
        parts = (PROC / "loadavg").read_text().split()
    except OSError as exc:
        why = f"{src} unreadable ({type(exc).__name__})"
        return {k: _reading(None, "", why) for k in ("load1", "load5", "load15", "procs")}
    return {
        "load1": _reading(float(parts[0]), "", f"{src} field 1"),
        "load5": _reading(float(parts[1]), "", f"{src} field 2"),
        "load15": _reading(float(parts[2]), "", f"{src} field 3"),
        "procs": _reading(parts[3], "running/total", f"{src} field 4"),
    }


def _cpu_model() -> str | None:
    try:
        for line in (PROC / "cpuinfo").read_text().splitlines():
            if line.startswith("model name"):
                return line.split(":", 1)[1].strip()
    except OSError:
        pass
    return None


async def read_cpu(interval: float = 0.20) -> dict[str, Any]:
    """CPU identity and utilisation.

    **Utilisation is sampled over an interval and that interval is published.** psutil's
    zero-interval call returns the average since boot, which on a box up for days is a
    constant that looks like a live reading -- the single most convincing wrong number a
    dashboard can show. The sample runs off-thread so a 200 ms measurement does not stall
    the event loop; `api.py` has already shipped one outage caused by a blocking call in a
    coroutine and it is not a lesson worth repeating.
    """
    model, cores = _cpu_model(), os.cpu_count()
    out: dict[str, Any] = {
        "model": _reading(model, "", "/proc/cpuinfo 'model name'"),
        "threads": _reading(cores, "threads", "os.cpu_count()"),
    }
    try:
        import psutil
    except ImportError:
        why = "psutil is not installed; utilisation needs an interval sample"
        out["percent"] = _reading(None, "%", why)
        out["per_core"] = _reading(None, "%", why)
        return out

    src = f"psutil.cpu_percent(interval={interval})"
    try:
        overall = await asyncio.to_thread(psutil.cpu_percent, interval)
        per_core = await asyncio.to_thread(psutil.cpu_percent, interval, True)
        out["percent"] = _reading(overall, "%", src)
        out["per_core"] = _reading(per_core, "%", f"{src}, percpu=True")
    except Exception as exc:                                            # noqa: BLE001
        out["percent"] = _reading(None, "%", f"{src} failed ({type(exc).__name__})")
        out["per_core"] = _reading(None, "%", f"{src} failed ({type(exc).__name__})")
    return out


def read_disk() -> dict[str, Any]:
    """The filesystem holding the repository, not `/`. See the module docstring."""
    src = f"shutil.disk_usage({REPO_ROOT})"
    try:
        usage = shutil.disk_usage(REPO_ROOT)
    except OSError as exc:
        why = f"{src} failed ({type(exc).__name__})"
        return {k: _reading(None, "GiB", why) for k in ("total", "used", "free", "used_pct")}
    gib = lambda b: round(b / 1073741824, 1)                             # noqa: E731
    return {
        "path": _reading(str(REPO_ROOT), "", "the repository root"),
        "total": _reading(gib(usage.total), "GiB", src),
        "used": _reading(gib(usage.used), "GiB", src),
        "free": _reading(gib(usage.free), "GiB", src),
        "used_pct": _reading(round(100 * usage.used / usage.total, 1), "%", src),
    }


async def snapshot() -> dict[str, Any]:
    """CPU, RAM, disk and load. The CPU sample is the only one that costs wall time."""
    cpu = await read_cpu()
    return {"cpu": cpu, "memory": read_memory(), "disk": read_disk(), "load": read_load()}
