"""Stream scheduling and event-based timing.

**Read this before adding streams to anything.** The obvious move on a discrete
GPU is to overlap host->device transfer with compute across several streams.
That was measured on this box and it does not work:

===========  ==========  =========
n_streams    time (ms)   speedup
===========  ==========  =========
1 (serial)   18.86       1.00x
2            18.86       1.00x
4            19.19       0.98x
8            20.15       0.93x
===========  ==========  =========

The cause is structural, not a tuning failure. Overlap hides transfer behind
compute; here transfer crosses a PCIe Gen 3 x8 link (~7 GB/s) while compute
reads DRAM at ~752 GB/s. Transfer dominates end to end, so there is nothing to
hide it behind and extra streams only add scheduling overhead.

:class:`StreamScheduler` therefore defaults to a small pool and exposes
:attr:`StreamScheduler.overlap_is_profitable` so callers do not have to
re-derive this. On a Gen 5 x16 host the same code would benefit; the flag is
computed, not hard-coded off.
"""

from __future__ import annotations

import time
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Iterator

from .errors import SchedulerError


@dataclass
class Timing:
    """Result of an event-timed region."""

    name: str
    device_ms: float
    wall_ms: float

    def bandwidth_gbs(self, nbytes: int) -> float:
        """GB/s for *nbytes* moved, using device time."""
        return nbytes / (self.device_ms * 1e-3) / 1e9 if self.device_ms > 0 else 0.0

    def __str__(self) -> str:
        return f"{self.name}: {self.device_ms:.3f} ms device / {self.wall_ms:.3f} ms wall"


class StreamScheduler:
    """A fixed pool of CUDA streams with round-robin hand-out.

    Streams are created once and reused. Creating a stream per request is a
    common and expensive mistake; the pool makes reuse the default path.
    """

    def __init__(self, ctx: Any, n_streams: int = 2) -> None:
        if n_streams < 1:
            raise SchedulerError(f"n_streams must be >= 1, got {n_streams}")
        self.ctx = ctx
        self._streams = [ctx.create_stream() for _ in range(n_streams)]
        self._next = 0

    def __len__(self) -> int:
        return len(self._streams)

    @property
    def streams(self) -> list[Any]:
        return list(self._streams)

    @property
    def default(self) -> Any:
        return self._streams[0]

    def acquire(self) -> Any:
        """Next stream, round-robin."""
        s = self._streams[self._next]
        self._next = (self._next + 1) % len(self._streams)
        return s

    @property
    def overlap_is_profitable(self) -> bool:
        """Whether multi-stream copy/compute overlap is worth the complexity.

        False on any host where PCIe is the binding constraint -- see the module
        docstring for the measurements behind this.
        """
        return not self.ctx.pcie_bound

    def recommend_stream_count(self) -> int:
        """How many streams a copy/compute pipeline should actually use here."""
        return 1 if self.ctx.pcie_bound else min(4, len(self._streams))

    def sync_all(self) -> None:
        for s in self._streams:
            s.sync()

    # -- timing ------------------------------------------------------------
    @contextmanager
    def timed(self, name: str, stream: Any | None = None) -> Iterator[list]:
        """Time a region with CUDA events, not wall clock alone.

        Wall clock on its own measures launch overhead and Python; events
        measure the device. Both are reported because a large gap between them
        is itself the diagnosis (launch-bound, not compute-bound).

        Yields a one-element list that receives the :class:`Timing`::

            with sched.timed("matmul") as t:
                ...launch...
            print(t[0])
        """
        stream = stream or self.default
        try:
            from cuda.core import Event
            start = self.ctx.device.create_event()
            end = self.ctx.device.create_event()
            use_events = True
        except Exception:  # pragma: no cover
            start = end = None
            use_events = False

        box: list = []
        if use_events:
            stream.record(start)
        t0 = time.perf_counter()
        try:
            yield box
        finally:
            wall = (time.perf_counter() - t0) * 1e3
            if use_events:
                stream.record(end)
                end.sync()
                try:
                    dev_ms = float(end - start)
                except Exception:  # pragma: no cover
                    dev_ms = wall
            else:  # pragma: no cover
                stream.sync()
                dev_ms = wall
            box.append(Timing(name=name, device_ms=dev_ms, wall_ms=wall))
