"""Block-based asynchronous device allocator.

A serving loop allocates and frees the same handful of shapes thousands of
times. Going to the driver each time is wasteful and fragments the heap, so
this allocator rounds every request up to a power-of-two block and recycles
freed blocks from a free list.

The idea is the one behind PagedAttention and behind PyTorch's caching
allocator: fixed-size blocks trade a little internal waste for near-zero
fragmentation and O(1) reuse.

**Capacity matters here.** The target GPU has 15.9 GiB and no second card to
spill to, and the PCIe link out is ~7 GB/s, so spilling to host is not a
recovery strategy -- it is a 100x cliff. :meth:`BlockAllocator.reserve` fails
fast rather than letting the driver thrash.
"""

from __future__ import annotations

import threading
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from ..core.errors import AllocationError

MIN_BLOCK = 4096  # one page; smaller requests round up to this


def round_to_block(nbytes: int, min_block: int = MIN_BLOCK) -> int:
    """Round *nbytes* up to the next power of two, floored at *min_block*."""
    if nbytes <= min_block:
        return min_block
    return 1 << (nbytes - 1).bit_length()


@dataclass
class AllocatorStats:
    requests: int = 0
    hits: int = 0            # served from the free list
    misses: int = 0          # went to the driver
    bytes_requested: int = 0
    bytes_reserved: int = 0  # actually held, including rounding waste
    live_blocks: int = 0
    peak_reserved: int = 0

    @property
    def hit_rate(self) -> float:
        return self.hits / self.requests if self.requests else 0.0

    @property
    def waste_bytes(self) -> int:
        """Rounding overhead. Rises with odd sizes; a tuning signal."""
        return max(0, self.bytes_reserved - self.bytes_requested)

    def as_dict(self) -> dict[str, float | int]:
        d: dict[str, float | int] = dict(self.__dict__)
        d["hit_rate"] = round(self.hit_rate, 4)
        d["waste_bytes"] = self.waste_bytes
        return d


@dataclass
class Block:
    """One pooled device allocation."""

    buffer: Any
    size: int
    requested: int
    in_use: bool = True

    @property
    def ptr(self) -> int:
        return int(self.buffer.handle) if hasattr(self.buffer, "handle") else 0


class BlockAllocator:
    """Power-of-two block pool over a ``DeviceMemoryResource``.

    Thread-safe: the request queue may hand work to multiple workers.
    """

    def __init__(self, pools: Any, stream: Any | None = None,
                 capacity_bytes: int | None = None) -> None:
        self.pools = pools
        self.stream = stream
        self.capacity_bytes = capacity_bytes
        self.stats = AllocatorStats()
        self._free: dict[int, list[Block]] = defaultdict(list)
        self._live: dict[int, Block] = {}
        self._lock = threading.Lock()

    # -- core --------------------------------------------------------------
    def allocate(self, nbytes: int) -> Block:
        """Get a block of at least *nbytes*, recycling when possible."""
        if nbytes <= 0:
            raise AllocationError(f"allocation must be positive, got {nbytes}")
        size = round_to_block(nbytes)

        with self._lock:
            self.stats.requests += 1
            self.stats.bytes_requested += nbytes

            bucket = self._free[size]
            if bucket:
                blk = bucket.pop()
                blk.in_use = True
                blk.requested = nbytes
                self.stats.hits += 1
                self.stats.live_blocks += 1
                self._live[id(blk)] = blk
                return blk

            if (self.capacity_bytes is not None
                    and self.stats.bytes_reserved + size > self.capacity_bytes):
                raise AllocationError(
                    f"allocator capacity exceeded: {size / 2**20:.1f} MiB "
                    f"requested, {self.stats.bytes_reserved / 2**20:.1f} MiB "
                    f"already reserved, cap {self.capacity_bytes / 2**20:.1f} MiB. "
                    "Spilling to host is not viable on this box -- the PCIe link "
                    "is ~7 GB/s against ~752 GB/s of DRAM."
                )
            self.stats.misses += 1

        buf = self.pools.alloc_device(size, stream=self.stream)
        with self._lock:
            blk = Block(buffer=buf, size=size, requested=nbytes)
            self.stats.bytes_reserved += size
            self.stats.peak_reserved = max(self.stats.peak_reserved,
                                           self.stats.bytes_reserved)
            self.stats.live_blocks += 1
            self._live[id(blk)] = blk
            return blk

    def free(self, blk: Block) -> None:
        """Return a block to the pool. The device allocation is retained."""
        with self._lock:
            if not blk.in_use:
                return
            blk.in_use = False
            self._live.pop(id(blk), None)
            self.stats.live_blocks = max(0, self.stats.live_blocks - 1)
            self._free[blk.size].append(blk)

    def reserve(self, sizes: list[int]) -> None:
        """Pre-warm the pool so the first request does not pay driver latency."""
        blocks = [self.allocate(s) for s in sizes]
        for b in blocks:
            self.free(b)

    def release_all(self) -> None:
        """Return every pooled allocation to the driver."""
        with self._lock:
            for bucket in self._free.values():
                for blk in bucket:
                    self.pools.release(blk.buffer, stream=self.stream)
            self._free.clear()
            for blk in self._live.values():
                self.pools.release(blk.buffer, stream=self.stream)
            self._live.clear()
            self.stats.bytes_reserved = 0
            self.stats.live_blocks = 0

    # -- introspection -----------------------------------------------------
    @property
    def free_block_count(self) -> int:
        return sum(len(v) for v in self._free.values())

    def histogram(self) -> dict[int, int]:
        """Free blocks per size class -- shows whether rounding is sane."""
        return {k: len(v) for k, v in sorted(self._free.items()) if v}

    def __repr__(self) -> str:
        s = self.stats
        return (f"<BlockAllocator live={s.live_blocks} free={self.free_block_count} "
                f"reserved={s.bytes_reserved / 2**20:.1f}MiB "
                f"hit_rate={s.hit_rate:.1%}>")
