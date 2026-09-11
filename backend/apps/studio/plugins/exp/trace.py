"""An append-only record of everything the runtime did.

This is the second of the two ideas worth taking from the Cordis material (`docs/integration-
sources.md` records the first, and the whole verdict). Its argument there was made about agent
sessions and it applies exactly as well here: a plugin system whose state you can only inspect
*now* is one you cannot debug, because the interesting moment -- the reload that dropped a
service, the effect that raised while unwinding -- has already passed by the time you look.

Two sinks, and both matter:

* **A ring in memory**, capped, served by `GET /api/exp/events`. This is what the page reads,
  and it is why the plugin table can show what just happened rather than only what is.
* **A JSONL file**, optional, one object per line, opened in append mode and closed again for
  every write. Appends under `O_APPEND` smaller than a pipe buffer are atomic on Linux, so two
  processes writing the same file interleave lines rather than corrupt them -- which matters
  because the API and a CLI run of this package are two processes and both may be tracing.

The file lives in `run/`, with the pidfiles and the GPU lock, and CLAUDE.md's note on that
directory applies: it is runtime state. It is not a log in the sense of something logrotate
should own, and it is not the thing to grep for what the code does -- `git log` is.

Nothing is redacted here. A plugin that traces a secret has traced a secret; the runtime does
not inspect what it is given, and pretending to filter would be worse than not filtering,
because it would be believed. `routes.py` is where config values are withheld from a tokenless
reader, and that is the only place the distinction is made.
"""
from __future__ import annotations

import collections
import json
import os
import pathlib
import time
import typing

__all__ = ["Trace", "Event"]

Event = dict[str, typing.Any]


class Trace:
    def __init__(self, *, path: str | os.PathLike | None = None, limit: int = 2000) -> None:
        self.path = pathlib.Path(path) if path else None
        self.ring: collections.deque[Event] = collections.deque(maxlen=limit)
        self.seq = 0
        self.dropped_writes = 0

    def add(self, event: str, **fields) -> Event:
        """Record one. Never raises: a runtime whose tracing can break the thing it is tracing
        is worse than no tracing, and a full disk is a real state this box has been in.

        Two ways a write can fail and both count as a dropped write rather than an exception:
        the file (a full disk, a read-only mount, a vanished parent) and the *payload*.
        `default=str` handles an object `json` does not know, but a reference cycle raises
        `ValueError`, a non-string mapping key raises `TypeError` and a deeply nested field
        raises `RecursionError` -- all three from inside `json.dumps`, all three caught here.
        The ring keeps the record either way: it is appended before the file is touched, so a
        payload the file sink cannot take is still visible on the page.
        """
        self.seq += 1
        record: Event = {"seq": self.seq, "t": round(time.time(), 3), "event": event}
        record.update(fields)
        self.ring.append(record)
        if self.path is not None:
            try:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("a", encoding="utf-8") as fh:
                    fh.write(json.dumps(record, default=str) + "\n")
            except (OSError, TypeError, ValueError, RecursionError):
                self.dropped_writes += 1
        return record

    def since(self, seq: int = 0, limit: int = 200) -> list[Event]:
        """Everything after `seq`, oldest first, up to `limit`.

        The cursor is the sequence number and not a timestamp, because two events can share a
        millisecond and a timestamp cursor has to choose between re-sending one and losing one.

        When more than `limit` events have arrived since the last poll this returns the
        **oldest** of them, not the newest. The caller advances its cursor over what it was
        handed, so the remainder comes back on the next poll: the feed runs behind rather than
        skipping a reload's middle. What is genuinely unrecoverable is what the ring has already
        evicted -- `add` caps it at `maxlen` -- and that is what the page's wrapped-ring note is
        about."""
        out = [e for e in self.ring if e["seq"] > seq]
        return out[:limit]

    def tail(self, limit: int = 50) -> list[Event]:
        return list(self.ring)[-limit:]

    def __len__(self) -> int:
        return len(self.ring)
