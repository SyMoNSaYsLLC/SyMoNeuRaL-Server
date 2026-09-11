"""Memory resource pools.

Thin, owning wrappers over the three ``cuda.core`` memory resources verified by
the ``memoryResources`` sample:

===================== ==================================================
``DeviceMemoryResource``  device-only, full 752 GB/s DRAM path
``PinnedMemoryResource``  page-locked host, the fast side of a 7 GB/s link
``ManagedMemoryResource`` unified, migrates on demand
===================== ==================================================

**Sizing warning.** The target GPU has 48 MB of L2. Any buffer under roughly
100 MB is served substantially from cache, so a bandwidth number taken on a
small buffer is a cache measurement. :func:`escapes_l2` exists to make that
mistake hard to commit by accident.

**Pinned memory is not free.** It is page-locked host RAM; over-allocating it
starves the OS. :class:`MemoryPools` tracks the pinned high-water mark so a
leak shows up in :meth:`MemoryPools.stats` rather than as a mysterious hang.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .errors import AllocationError

try:
    from cuda.core import (
        DeviceMemoryResource,
        ManagedMemoryResource,
        PinnedMemoryResource,
    )
except ImportError as exc:  # pragma: no cover
    raise ImportError("cuda-core is required") from exc


def escapes_l2(nbytes: int, l2_bytes: int, factor: float = 2.0) -> bool:
    """True when *nbytes* is large enough that L2 will not dominate.

    ``factor=2.0`` is deliberately conservative. On the target box, 8 MB
    measured 994 GB/s (cached) while 128 MB measured 380 GB/s one-way -- the
    same benchmark, a 2.6x difference, entirely from cache residency.
    """
    return nbytes >= l2_bytes * factor


@dataclass
class PoolStats:
    """Counters for leak-hunting. Bytes are cumulative unless marked live."""

    device_allocated: int = 0
    device_live: int = 0
    pinned_allocated: int = 0
    pinned_live: int = 0
    pinned_peak: int = 0
    managed_allocated: int = 0
    managed_live: int = 0
    allocations: int = 0
    releases: int = 0

    def as_dict(self) -> dict[str, int]:
        return dict(self.__dict__)


@dataclass
class MemoryPools:
    """Owns one resource of each kind for a device, plus accounting.

    ``device_id`` must match the current :class:`~symoneural.core.context.DeviceContext`.
    """

    device_id: int = 0
    stats: PoolStats = field(default_factory=PoolStats)

    def __post_init__(self) -> None:
        self.device = DeviceMemoryResource(self.device_id)
        self.pinned = PinnedMemoryResource()
        self.managed = ManagedMemoryResource()
        self._live: dict[int, tuple[str, int]] = {}
        # cuda.core requires an explicit stream on every allocate() -- passing
        # None raises "stream is required and must not be None". Hold the
        # device default stream so callers may omit it.
        try:
            from cuda.core import Device

            self._default_stream = Device(self.device_id).default_stream
        except Exception:  # pragma: no cover - no driver
            self._default_stream = None

    def _stream(self, stream: Any | None) -> Any:
        return stream if stream is not None else self._default_stream

    # -- allocation --------------------------------------------------------
    def _track(self, buf: Any, kind: str, nbytes: int) -> Any:
        self._live[id(buf)] = (kind, nbytes)
        self.stats.allocations += 1
        setattr(self.stats, f"{kind}_allocated",
                getattr(self.stats, f"{kind}_allocated") + nbytes)
        live = getattr(self.stats, f"{kind}_live") + nbytes
        setattr(self.stats, f"{kind}_live", live)
        if kind == "pinned":
            self.stats.pinned_peak = max(self.stats.pinned_peak, live)
        return buf

    def alloc_device(self, nbytes: int, stream: Any | None = None) -> Any:
        if nbytes <= 0:
            raise AllocationError(f"device allocation must be positive, got {nbytes}")
        try:
            buf = self.device.allocate(nbytes, stream=self._stream(stream))
        except Exception as exc:
            raise AllocationError(
                f"device allocation of {nbytes / 2**20:.1f} MiB failed: {exc}"
            ) from exc
        return self._track(buf, "device", nbytes)

    def alloc_pinned(self, nbytes: int, stream: Any | None = None) -> Any:
        """Page-locked host memory -- the staging buffer for PCIe transfer.

        Pinned gains ~7% over pageable on this box (6.94 vs 6.49 GB/s H2D). The
        real reason to use it is that only pinned memory can overlap with
        compute, not the headline number.
        """
        if nbytes <= 0:
            raise AllocationError(f"pinned allocation must be positive, got {nbytes}")
        try:
            buf = self.pinned.allocate(nbytes, stream=self._stream(stream))
        except Exception as exc:
            raise AllocationError(
                f"pinned allocation of {nbytes / 2**20:.1f} MiB failed "
                f"(page-locked host memory is a limited resource): {exc}"
            ) from exc
        return self._track(buf, "pinned", nbytes)

    def alloc_managed(self, nbytes: int, stream: Any | None = None) -> Any:
        if nbytes <= 0:
            raise AllocationError(f"managed allocation must be positive, got {nbytes}")
        try:
            buf = self.managed.allocate(nbytes, stream=self._stream(stream))
        except Exception as exc:
            raise AllocationError(
                f"managed allocation of {nbytes / 2**20:.1f} MiB failed: {exc}"
            ) from exc
        return self._track(buf, "managed", nbytes)

    # -- release -----------------------------------------------------------
    def release(self, buf: Any, stream: Any | None = None) -> None:
        """Close a buffer and update live counters."""
        rec = self._live.pop(id(buf), None)
        try:
            buf.close(stream) if stream is not None else buf.close()
        except TypeError:
            buf.close()
        except Exception:  # pragma: no cover - already-freed buffers
            pass
        if rec:
            kind, nbytes = rec
            setattr(self.stats, f"{kind}_live",
                    max(0, getattr(self.stats, f"{kind}_live") - nbytes))
            self.stats.releases += 1

    def close_all(self, stream: Any | None = None) -> None:
        for buf in list(self._live):
            pass  # ids only; buffers are released by their owners
        self._live.clear()

    @property
    def live_count(self) -> int:
        return len(self._live)
