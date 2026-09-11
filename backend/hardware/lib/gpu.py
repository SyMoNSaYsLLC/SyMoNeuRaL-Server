"""The lease's Python side. Currently one thing: telling the governor what it evicts.

`scripts/gpu-governor.sh` holds the lock and must keep holding it -- `mkdir` is the atomic
primitive, it has no runtime dependency, and it survives `api.py` being dead, which a governor
living inside the API process cannot. It is also proven: 46 samples, 0 two-holder, 0
two-resident, negative control red on 25 of 27. Rewriting the component that holds the central
invariant means re-proving it, and the proof is the expensive part.

## What is NOT here, and why -- read this before adding to it

`class GpuQueue` was on the list for this extraction and **could not come.** It calls
`bus.announce()` (`api.py:996`), `push_rack()` (`api.py:2804`) and `run()`, and `push_rack`
calls `build_status()` -- which is the rack, and the rack is most of `api.py`. Moving
`GpuQueue` therefore means either dragging the rack out with it, which is `SPLIT-API` stage
1's job and not this commit's, or injecting three callables into its constructor, which
changes the call site that this extraction was required not to change.

So `GpuQueue` extraction is **blocked behind the rack extraction**, not behind anything here.
That is a sequencing finding, and it is written down rather than worked around.
"""
from __future__ import annotations

import asyncio
import logging
import os
import pathlib
import subprocess
import sys

log = logging.getLogger("symoneural.api")

ROOT = next(_p for _p in pathlib.Path(__file__).resolve().parents if (_p / "backend" / "server.py").is_file())
#: The governor. Spelled from the repository root rather than relative to this file, because
#: this module may be imported from `backend/` or from `backend/` depending on the caller.
GOVERNOR = ROOT / "scripts" / "gpu-governor.sh"


async def record_engine(pid: int) -> None:
    """Tell the governor which process is actually holding the card.

    The lease records the *holder* -- the process that took the lock. During a live render
    `run/gpu.lock.d/holder` read `image 1509`, and 1509 is this API: the process that
    spawned the engine and is waiting on it. Evicting by that pid would stop the API and
    leave the engine resident. So the spawned pid is recorded separately and eviction
    signals it by identity instead of by `pkill -f <pattern>`.

    The pgid is offered only when the child is genuinely a group leader. `run()` below
    passes `start_new_session=True`, so its children are; `_llama` at the chat spawn and
    `sigils.lib.render._spawn` are not, and their process group is this API's own. Handing the
    governor that pgid would arm a group kill aimed at ourselves -- strictly worse than the
    pattern kill being replaced. `os.getpgid(pid) == pid` is the check that distinguishes
    them, and the governor re-verifies it rather than trusting us.

    Best-effort by design: a failure here costs the identity path and falls back to the
    pattern arms, which is the behaviour that exists today. It must never fail a render.
    """
    try:
        pgid = os.getpgid(pid)
    except (ProcessLookupError, PermissionError):
        return
    argv = [str(GOVERNOR), "engine", str(pid)]
    if pgid == pid:
        argv.append(str(pgid))
    try:
        # `to_thread`, not a bare `subprocess.run`. This is called from two coroutines, and a
        # blocking exec in either stalls the WHOLE event loop for up to the 10 s timeout --
        # no other request, no streaming token, and not /api/status. Shipped that way and
        # caught in review: every engine spawn would have looked like an outage to the
        # watchdog that polls /api/status, which is a monitor made useless by its own server.
        await asyncio.to_thread(
            subprocess.run, argv, capture_output=True, timeout=10, check=False)
    except Exception:  # noqa: BLE001 -- see the docstring: never fail a render over this
        log.warning("could not record engine pid %s with the governor", pid)


# ====================================================================== drain arithmetic
#
# Moved out of `scripts/gpu-governor.sh`, where it was an `awk -F','` block summing
# `nvidia-smi --query-compute-apps` CSV. Parsing CSV and doing arithmetic on it is the shape
# bash is worst at, and the patternless-drain defect lived exactly there.
#
# The lock did NOT move and must not: `mkdir` is the atomic primitive, bash has no runtime
# dependency, and a shell script can break a stale lock when `api.py` is dead. Only the
# measurement came here.
#
# ## The failure direction is the whole safety argument
#
# Bash calling Python introduces the runtime dependency bash was valuable for not having.
# That is acceptable only because **an unreadable answer is never a drained answer.** This
# function exits non-zero rather than printing 0, and the governor's fallback is the
# CARD-WIDE reading against `DRAIN_FLOOR_CARDWIDE_MIB` (1500) rather than the compute floor
# (1024) -- a cruder measure with a *stricter* threshold. So losing this module makes the
# governor wait longer, never hand over sooner.
#
# Printing 0 on failure would be the opposite: an unreadable card would read as an empty one
# and get handed to the next tenant on no evidence. `test_drain_fails_closed` mutates it to
# do exactly that and asserts the governor then reports a drain it has not earned.

def compute_mib(pattern: str = "") -> int:
    """Device memory held by CUDA contexts, in MiB. Raises rather than guessing.

    With a `pattern`, sums only contexts whose process path contains that substring -- "has
    THIS process let go" rather than "is the card clear". Both questions are asked by the
    governor and they are not the same one: after evicting chat, the card still legitimately
    holds an idle ComfyUI context, and waiting for that to leave would wedge the handover.

    An EMPTY result is a legitimate reading -- it is what "nothing holds a context" looks
    like -- and returns 0. A query that could not be read raises. That distinction is the
    entire point of the function.
    """
    out = subprocess.run(
        ["nvidia-smi", "--query-compute-apps=process_name,used_memory",
         "--format=csv,noheader,nounits"],
        capture_output=True, text=True, timeout=20)
    if out.returncode != 0:
        raise RuntimeError(f"nvidia-smi exited {out.returncode}")
    total = 0
    for line in out.stdout.splitlines():
        if not line.strip():
            continue
        if pattern and pattern not in line:
            continue
        field = line.rsplit(",", 1)[-1].strip()
        if not field.isdigit():
            # Summed, not first-match: two contexts of 400 and 12000 MiB must not read as
            # 400. And a non-numeric field is a read failure, not a zero.
            raise RuntimeError(f"unparsable used_memory field: {field!r}")
        total += int(field)
    return total


def _cli(argv: list[str]) -> int:
    """`python3 backend/gpu.py compute-mib [pattern]` -- what the governor calls.

    Prints one integer and exits 0, or prints nothing and exits 1. Nothing else, because the
    caller is a shell script reading stdout and a stray line would become a number.
    """
    if len(argv) < 1 or argv[0] != "compute-mib":
        print("usage: gpu.py compute-mib [process-path-substring]", file=sys.stderr)
        return 2
    try:
        print(compute_mib(argv[1] if len(argv) > 1 else ""))
        return 0
    except Exception as exc:                                   # noqa: BLE001
        print(f"compute_mib: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(_cli(sys.argv[1:]))
