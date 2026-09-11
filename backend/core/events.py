"""Structured runtime events: one line per event, machine-readable, nothing silent.

    from core import events
    events.emit("engine_spawned", runtime="symoneural-llm", pid=73205, ctx=33792)

produces

    14:29:27.412 engine_spawned runtime=symoneural-llm pid=73205 ctx=33792

## What this replaces, and why the shape is copied rather than invented

Our log said `starting chat surface` and then, eight seconds later, `chat surface up`. Both
true, neither answerable: how long, with what argv, from what previous state, and -- when it
did not come up -- which of six reasons. Four hundred lines of prose that `grep` can search
and nothing can parse.

The shape here is taken from a runtime log the owner pointed at, and the five properties
worth having are all things ours lacked:

1. **`key=value` on every event, with a stable event name.** `engine_spawn_failed` is
   greppable across versions; "chat surface failed to come up" is a sentence somebody will
   reword.
2. **Phases are timed and emitted together.** One `startup_complete` line carrying every
   phase and its duration beats fifteen scattered lines you have to subtract by hand.
3. **A state change names `previous`, `next` and `cause`.** "chat surface up" does not say
   what it was before or what moved it; both matter when it flaps.
4. **A runtime reports status with a `reason` when it is not ready.** `status=failed` with
   no reason is the log entry that costs an afternoon.
5. **A skip is an event.** `skipped` with a reason, always -- silence and "did not need to"
   read identically, and this repository has already shipped a deploy that published nothing
   while printing "deployed".

## Rules

Values are never interpolated into the message. `emit("x", path=p)` -- not
`log.info("x %s", p)` -- because the whole point is that a field can be extracted.

**Never emit a secret.** `run/config/api.env` is mode 600; a value from it must not reach a
field, and neither must a prompt or a transcript. Fields are for identities, counts,
durations and states.
"""
from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from typing import Any, Iterator

log = logging.getLogger("symoneural.events")

#: Phase name -> milliseconds, for the run in progress. Emitted whole by `startup_complete`.
_phases: dict[str, int] = {}
_t0: float | None = None


def _render(value: Any) -> str:
    """A field value, flattened. Quoted only when it would otherwise split a field."""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, float):
        return f"{value:.3f}".rstrip("0").rstrip(".")
    text = str(value)
    return f'"{text}"' if (" " in text or "=" in text or not text) else text


def emit(event: str, **fields: Any) -> None:
    """One event. `event` is a stable snake_case name; everything else is a field.

    Fields are sorted so two occurrences of the same event diff cleanly -- an event whose
    field order depends on kwargs order cannot be compared between runs.
    """
    parts = " ".join(f"{k}={_render(v)}" for k, v in sorted(fields.items()))
    log.info("%s%s", event, f" {parts}" if parts else "")


def state(subject: str, previous: str, next_: str, cause: str, **fields: Any) -> None:
    """A state machine moved. Always names where it was, where it went, and what moved it."""
    emit("state_changed", subject=subject, previous=previous, next=next_, cause=cause, **fields)


def runtime_status(runtime: str, status: str, reason: str | None = None, **fields: Any) -> None:
    """A runtime's readiness. `status` is starting | ready | failed | stopped | absent.

    `reason` is required in spirit for anything but `ready`: a failure with no reason is the
    entry that costs an afternoon. It is not enforced, because a missing reason is better
    than a fabricated one.
    """
    emit("runtime_status", runtime=runtime, status=status, reason=reason, **fields)


def skipped(what: str, reason: str, **fields: Any) -> None:
    """Something was NOT done, and why. Never let this be silence."""
    emit("skipped", what=what, reason=reason, **fields)


@contextmanager
def phase(name: str) -> Iterator[None]:
    """Time a startup phase and record it. Emits on failure; `startup_complete` emits the rest.

    A phase that raises is reported immediately with its duration, because the duration
    before a failure is usually the diagnostic -- 30 ms is a missing file, 30 s is a timeout.
    """
    started = time.monotonic()
    try:
        yield
    except Exception as exc:
        _phases[name] = int((time.monotonic() - started) * 1000)
        emit("phase_failed", phase=name, ms=_phases[name],
             error=type(exc).__name__, detail=str(exc)[:200])
        raise
    _phases[name] = int((time.monotonic() - started) * 1000)


def startup_begin() -> None:
    global _t0
    _t0 = time.monotonic()
    _phases.clear()
    emit("startup_begin")


def startup_complete(**fields: Any) -> None:
    """Every phase and its duration, on one line, with the total.

    One line rather than fifteen: a reader comparing two starts wants the phase map side by
    side, and fifteen scattered lines means subtracting timestamps by hand.
    """
    total = int((time.monotonic() - _t0) * 1000) if _t0 is not None else -1
    slowest = max(_phases.items(), key=lambda kv: kv[1], default=("none", 0))
    emit("startup_complete", ms=total, phases=len(_phases),
         slowest=slowest[0], slowest_ms=slowest[1],
         durations=";".join(f"{k}={v}" for k, v in _phases.items()), **fields)


def phases() -> dict[str, int]:
    """The phase map, for /api/status and the rack. A copy -- callers must not mutate it."""
    return dict(_phases)
