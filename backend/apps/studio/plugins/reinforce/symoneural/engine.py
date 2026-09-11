"""The engine facade: one object that wires every subsystem together.

::

    from symoneural import Engine

    with Engine() as eng:
        eng.mlp_forward([[0.1] * 256])          # end-to-end custom-kernel pass
        eng.stats()                             # allocator / queue / graph counters

Construction order matters and is fixed here so callers cannot get it wrong:
device context -> memory pools -> block allocator -> stream scheduler ->
kernel cache -> operators -> models -> graph cache -> request queue.
"""

from __future__ import annotations

from typing import Any

from .compute._cupy import cp
import numpy as np

from .compute.ops import Ops, cupy_barrier
from .compute.program import KernelCache
from .core.context import DeviceContext
from .core.memory import MemoryPools
from .core.streams import StreamScheduler
from .model.micro import (
    AttentionConfig,
    MicroAttention,
    MicroMLP,
    MLPConfig,
)
from .scheduler.allocator import BlockAllocator
from .scheduler.graph import GraphCache
from .scheduler.queue import RequestQueue


class Engine:
    """Owns the device and every subsystem built on it."""

    def __init__(
        self,
        device_id: int = 0,
        mlp_config: MLPConfig | None = None,
        attention_config: AttentionConfig | None = None,
        n_streams: int = 2,
        max_batch: int = 8,
        max_wait_ms: float = 5.0,
    ) -> None:
        self.ctx = DeviceContext(device_id)
        self.pools = MemoryPools(device_id)
        self.streams = StreamScheduler(self.ctx, n_streams=n_streams)
        self.allocator = BlockAllocator(self.pools, stream=self.streams.default)
        self.cache = KernelCache(self.ctx.caps.arch)
        self.ops = Ops(self.ctx, self.cache)
        self.graphs = GraphCache(self.ctx)

        self.mlp = MicroMLP(self.ops, mlp_config or MLPConfig())
        self.attention = MicroAttention(self.ops, attention_config or AttentionConfig())

        self.queue = RequestQueue(self._handle_batch, max_batch=max_batch,
                                  max_wait_ms=max_wait_ms)
        self._started = False

    # -- lifecycle ---------------------------------------------------------
    def start(self) -> Engine:
        if not self._started:
            self.queue.start()
            self._started = True
        return self

    def stop(self) -> None:
        if self._started:
            self.queue.stop()
            self._started = False
        self.streams.sync_all()

    def __enter__(self) -> Engine:
        return self.start()

    def __exit__(self, *exc: object) -> None:
        self.stop()

    # -- direct execution --------------------------------------------------
    def mlp_forward(self, rows: list[list[float]] | np.ndarray) -> np.ndarray:
        """Run the micro-MLP over a batch of rows. Returns a host array."""
        x = cp.asarray(np.ascontiguousarray(rows, dtype=np.float32))
        # cp.asarray stages on CuPy's stream; the kernels below run on ours.
        # Without this barrier they can read a partially-written buffer.
        cupy_barrier()
        st = self.streams.default
        out = self.mlp.forward(x, stream=st)
        st.sync()
        return cp.asnumpy(out)

    def attention_forward(self, rows: list[list[float]] | np.ndarray) -> np.ndarray:
        """Run single-head attention over a (seq_len, d_model) block."""
        x = cp.asarray(np.ascontiguousarray(rows, dtype=np.float32))
        cupy_barrier()
        st = self.streams.default
        out = self.attention.forward(x, stream=st)
        st.sync()
        return cp.asnumpy(out)

    def reduce_sum(self, values: list[float] | np.ndarray,
                   cooperative: bool = False) -> float:
        """Sum on the GPU. *cooperative* selects the single-pass grid.sync() path."""
        x = cp.asarray(np.ascontiguousarray(values, dtype=np.float32))
        cupy_barrier()
        return (self.ops.sum_cooperative(x) if cooperative
                else self.ops.sum(x, stream=self.streams.default))

    # -- batched execution -------------------------------------------------
    def _handle_batch(self, payloads: list[Any]) -> list[Any]:
        """Queue worker: stack same-shaped rows into one launch.

        Batching is the lever that matters for bandwidth-bound work -- one pass
        over the weights serves every row in the batch.
        """
        rows = [np.asarray(p, dtype=np.float32).reshape(-1) for p in payloads]
        widths = {r.size for r in rows}
        if len(widths) != 1:
            return [self.mlp_forward(r.reshape(1, -1))[0] for r in rows]

        batch = np.stack(rows)
        out = self.mlp_forward(batch)
        return [out[i] for i in range(len(rows))]

    def submit(self, row: list[float]) -> Any:
        return self.queue.submit(row)

    def infer(self, row: list[float], timeout: float = 30.0) -> np.ndarray:
        """Submit one row through the batching queue and wait for it."""
        return self.queue.submit_and_wait(row, timeout=timeout)

    # -- introspection -----------------------------------------------------
    def device_info(self) -> dict[str, Any]:
        c = self.ctx.caps
        return {
            "name": c.name,
            "arch": c.sm_arch,
            "compute_capability": f"{c.compute_capability[0]}.{c.compute_capability[1]}",
            "multiprocessors": c.multiprocessor_count,
            "total_memory_gib": round(c.total_memory / 2**30, 2),
            "free_memory_gib": round(self.ctx.free_memory() / 2**30, 2),
            "l2_mib": round(c.l2_bytes / 2**20),
            "theoretical_bandwidth_gbs": round(c.theoretical_bandwidth_gbs, 1),
            "driver": DeviceContext.driver_version(),
            "device_count": self.ctx.device_count,
            "cooperative_launch": c.supports_cooperative,
            "pcie_bound": self.ctx.pcie_bound,
            "overlap_profitable": self.streams.overlap_is_profitable,
        }

    def stats(self) -> dict[str, Any]:
        return {
            "allocator": self.allocator.stats.as_dict(),
            "memory_pools": self.pools.stats.as_dict(),
            "queue": self.queue.stats.as_dict(),
            "graphs": self.graphs.stats(),
            "kernel_compiles": self.cache.compile_count,
            "queue_depth": self.queue.depth,
        }

    def __repr__(self) -> str:
        return f"<Engine {self.ctx.caps.summary()}>"
