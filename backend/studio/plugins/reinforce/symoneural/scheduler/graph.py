"""CUDA graph capture and replay.

The measurement that justifies this module: the local ``cudaGraphs`` sample
timed 1000 iterations of a three-kernel pipeline two ways --

======================  =============  ==========
mode                    per iteration  speedup
======================  =============  ==========
individual launches     7.81 us        1.00x
graph replay            4.10 us        **1.91x**
======================  =============  ==========

Nearly half the time in a small-kernel pipeline is CPU-side launch overhead.
Capture the launches once and replay the whole DAG with a single driver call
and it disappears. This is the single most transferable optimisation in the
curriculum for inference, where the same op sequence runs for every request.

**The pointer contract.** A graph bakes in the *addresses* passed at capture
time, not the contents. Replay therefore requires that you write new inputs
into the same buffers. :class:`CapturedGraph` owns its buffers to make that
contract explicit rather than a footgun -- writing to a freed pointer and
replaying is a silent corruption, not a crash.
"""
from __future__ import annotations


from dataclasses import dataclass, field
from typing import Any, Callable

from ..core.errors import SchedulerError


@dataclass
class CapturedGraph:
    """A completed CUDA graph plus the buffers whose addresses it captured."""

    name: str
    graph: Any
    builder: Any
    buffers: dict[str, Any] = field(default_factory=dict)
    replays: int = 0

    def launch(self, stream: Any) -> None:
        """Replay the whole DAG with one driver call."""
        self.graph.launch(stream)
        self.replays += 1

    def buffer(self, key: str) -> Any:
        """The captured buffer for *key* -- write inputs here before replay."""
        if key not in self.buffers:
            raise SchedulerError(
                f"graph {self.name!r} has no captured buffer {key!r}; "
                f"captured: {sorted(self.buffers)}"
            )
        return self.buffers[key]

    def __repr__(self) -> str:
        return f"<CapturedGraph {self.name!r} replays={self.replays}>"


class GraphCache:
    """Builds and stores graphs by key.

    Typical use: one graph per (operation, shape) so a serving loop replays
    rather than re-launching.
    """

    def __init__(self, ctx: Any) -> None:
        self.ctx = ctx
        self._graphs: dict[str, CapturedGraph] = {}

    def __contains__(self, key: str) -> bool:
        return key in self._graphs

    def __len__(self) -> int:
        return len(self._graphs)

    def get(self, key: str) -> CapturedGraph | None:
        return self._graphs.get(key)

    def capture(
        self,
        key: str,
        stream: Any,
        record: Callable[[Any], None],
        buffers: dict[str, Any] | None = None,
        *,
        overwrite: bool = False,
    ) -> CapturedGraph:
        """Capture the launches issued by *record* into a replayable graph.

        *record* receives a graph builder and must issue its ``launch(...)``
        calls against it instead of against a stream::

            def record(gb):
                launch(gb, cfg, kernel, a.data.ptr, out.data.ptr, n)

            g = cache.capture("mlp:64x512", stream, record,
                              buffers={"x": x, "out": out})

        Buffers passed here are retained for the graph's lifetime, because the
        graph holds their raw addresses.
        """
        if key in self._graphs and not overwrite:
            return self._graphs[key]

        try:
            builder = stream.create_graph_builder()
            builder.begin_building()
            record(builder)
            builder.end_building()
            graph = builder.complete()
            graph.upload(stream)
        except Exception as exc:
            raise SchedulerError(f"graph capture failed for {key!r}: {exc}") from exc

        cg = CapturedGraph(name=key, graph=graph, builder=builder,
                           buffers=dict(buffers or {}))
        self._graphs[key] = cg
        return cg

    def replay(self, key: str, stream: Any) -> None:
        g = self._graphs.get(key)
        if g is None:
            raise SchedulerError(f"no captured graph {key!r}; "
                                 f"have: {sorted(self._graphs)}")
        g.launch(stream)

    def clear(self) -> None:
        self._graphs.clear()

    def stats(self) -> dict[str, int]:
        return {k: g.replays for k, g in self._graphs.items()}
