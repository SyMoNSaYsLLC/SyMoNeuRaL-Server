"""Device context management.

Wraps ``cuda.core.Device`` with the capability facts the engine needs to make
launch decisions, and caches them so hot paths never re-query the driver.

Hardware notes for the target box (measured, see ``docs/01-hardware-dossier.md``):

* RTX 5070 Ti, Blackwell, ``sm_120``, 70 SMs x 128 cores, 15.9 GiB.
* 48 MB L2 -- large enough that any working set under ~100 MB is measuring cache,
  not DRAM. :attr:`DeviceContext.l2_bytes` exists so benchmarks can size past it.
* DRAM ~752 GB/s measured; host<->device capped at ~7 GB/s by a PCIe Gen 3 x8
  host link. :attr:`DeviceContext.pcie_bound` is the flag the scheduler reads to
  decide that stream-overlap is not worth attempting.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .errors import CapabilityWaived, DeviceError

try:
    from cuda.bindings import driver
    from cuda.core import Device, system
except ImportError as exc:  # pragma: no cover - import guard
    raise ImportError(
        "cuda-core is required. Install with: pip install 'cuda-core>=1.0.0'"
    ) from exc


@dataclass(frozen=True)
class DeviceCapabilities:
    """Immutable snapshot of everything the engine branches on."""

    device_id: int
    name: str
    arch: str
    compute_capability: tuple[int, int]
    total_memory: int
    free_memory: int
    multiprocessor_count: int
    max_threads_per_block: int
    max_threads_per_sm: int
    warp_size: int
    l2_bytes: int
    shared_memory_per_block: int
    memory_bus_width: int
    memory_clock_khz: int
    supports_cooperative: bool
    supports_managed: bool

    @property
    def sm_arch(self) -> str:
        return f"sm_{self.arch}"

    @property
    def theoretical_bandwidth_gbs(self) -> float:
        """Peak DRAM bandwidth: clock x 2 (DDR) x bus_width / 8.

        On the target box this yields 896.1 GB/s. Measured throughput is ~752
        GB/s (84%), which is the number benchmarks should be judged against --
        see ``docs/01-hardware-dossier.md``.
        """
        return self.memory_clock_khz * 1e3 * 2 * (self.memory_bus_width / 8) / 1e9

    def summary(self) -> str:
        maj, minor = self.compute_capability
        return (
            f"{self.name} | {self.sm_arch} (cc {maj}.{minor}) | "
            f"{self.multiprocessor_count} SMs | "
            f"{self.total_memory / 2**30:.2f} GiB | "
            f"L2 {self.l2_bytes / 2**20:.0f} MB | "
            f"{self.theoretical_bandwidth_gbs:.0f} GB/s peak"
        )


def _attr(props: Any, *names: str, default: Any = 0) -> Any:
    """Read the first attribute that exists.

    ``cuda.core`` property names have moved between releases; rather than pin to
    one spelling we probe the alternatives and fall back to a default.
    """
    for n in names:
        try:
            v = getattr(props, n)
        except (AttributeError, RuntimeError):
            continue
        if v is not None:
            return v
    return default


class DeviceContext:
    """Owns one CUDA device and its capability snapshot.

    Use as a context manager so the device is made current for the duration::

        with DeviceContext(0) as ctx:
            print(ctx.caps.summary())
    """

    def __init__(self, device_id: int = 0) -> None:
        try:
            devices = Device.get_all_devices()
        except Exception as exc:  # pragma: no cover - no driver present
            raise DeviceError(f"could not enumerate CUDA devices: {exc}") from exc

        if not devices:
            raise DeviceError("no CUDA-capable device found")
        if device_id >= len(devices):
            raise DeviceError(
                f"device {device_id} requested but only {len(devices)} present"
            )

        self.device_id = device_id
        self.device = Device(device_id)
        self.device.set_current()
        self._caps: DeviceCapabilities | None = None
        self._device_count = len(devices)

    # -- capabilities ------------------------------------------------------
    @property
    def caps(self) -> DeviceCapabilities:
        if self._caps is None:
            self._caps = self._probe()
        return self._caps

    def _probe(self) -> DeviceCapabilities:
        d = self.device
        p = d.properties
        major = _attr(p, "compute_capability_major", default=0)
        minor = _attr(p, "compute_capability_minor", default=0)
        # cuda.core exposes no total-memory property; the driver call is the
        # only reliable source and also gives us current free bytes.
        try:
            _rc, free_b, total_b = driver.cuMemGetInfo()
        except Exception:  # pragma: no cover
            free_b = total_b = 0
        return DeviceCapabilities(
            device_id=self.device_id,
            name=d.name,
            arch=str(d.arch),
            compute_capability=(int(major), int(minor)),
            total_memory=int(total_b),
            free_memory=int(free_b),
            memory_bus_width=int(_attr(p, "global_memory_bus_width", default=0)),
            memory_clock_khz=int(_attr(p, "memory_clock_rate", default=0)),
            multiprocessor_count=int(_attr(p, "multiprocessor_count")),
            max_threads_per_block=int(_attr(p, "max_threads_per_block", default=1024)),
            max_threads_per_sm=int(
                _attr(p, "max_threads_per_multiprocessor", default=1536)
            ),
            warp_size=int(_attr(p, "warp_size", default=32)),
            l2_bytes=int(_attr(p, "l2_cache_size", default=0)),
            shared_memory_per_block=int(
                _attr(p, "max_shared_memory_per_block", "shared_mem_per_block",
                      default=49152)
            ),
            supports_cooperative=bool(
                _attr(p, "cooperative_launch", default=False)
            ),
            supports_managed=bool(_attr(p, "managed_memory", default=False)),
        )

    @property
    def device_count(self) -> int:
        return self._device_count

    @property
    def pcie_bound(self) -> bool:
        """True when host<->device transfer is the limiting factor.

        On the target box the host caps PCIe at Gen 3 x8 (~7 GB/s measured)
        against ~752 GB/s of DRAM bandwidth -- a ~107x gap. The scheduler reads
        this to skip multi-stream overlap, which measured 1.00x / 0.98x / 0.93x
        for 2 / 4 / 8 streams and is therefore pure overhead here.
        """
        return True

    # -- streams -----------------------------------------------------------
    def create_stream(self, nonblocking: bool = False):
        """Create a stream. **Blocking by default, deliberately.**

        ``cuda.core`` defaults to ``nonblocking=True``, which does *not*
        synchronise with the legacy default stream (handle 0) — and CuPy runs
        everything on exactly that stream. The result is that a buffer filled
        by ``cp.random.rand`` and then read by an engine kernel is a data race:
        usually fine, occasionally garbage, never an error.

        That bug appeared three times in this project wearing different hats —
        a benchmark reporting 34 TB/s, a flaky graph-replay test, and an
        intermittently wrong MLP forward pass. Rather than sprinkle barriers at
        every call site, streams here are **blocking**, so the driver orders
        them against CuPy's work automatically.

        Pass ``nonblocking=True`` when you genuinely want independence from the
        default stream and will handle ordering yourself. The cost of blocking
        is only paid when there is default-stream work to order against.
        """
        try:
            from cuda.core import StreamOptions

            return self.device.create_stream(
                options=StreamOptions(nonblocking=nonblocking)
            )
        except (ImportError, TypeError):  # pragma: no cover - older cuda.core
            return self.device.create_stream()

    def sync(self) -> None:
        self.device.sync()

    # -- guards ------------------------------------------------------------
    def require_cooperative(self) -> None:
        """Waive rather than fail when cooperative launch is unavailable."""
        if not self.caps.supports_cooperative:
            raise CapabilityWaived(
                f"{self.caps.name} does not support cooperative kernel launch; "
                "the single-pass multi-block reduction requires it"
            )

    def require_devices(self, n: int) -> None:
        """Waive when there are not enough GPUs, the way simpleP2P does."""
        if self._device_count < n:
            raise CapabilityWaived(
                f"{n} GPUs required, {self._device_count} present -- waiving"
            )

    def free_memory(self) -> int:
        """Currently free device bytes. Queried live, not cached."""
        try:
            _rc, free_b, _total = driver.cuMemGetInfo()
            return int(free_b)
        except Exception:  # pragma: no cover
            return 0

    @staticmethod
    def driver_version() -> str:
        """User-mode driver version, e.g. ``13.3 (branch r610_85)``."""
        try:
            ver = system.get_user_mode_driver_version()
            branch = system.get_driver_branch()
            return f"{ver} (branch {branch})"
        except Exception:  # pragma: no cover
            return "unknown"

    # -- context manager ---------------------------------------------------
    def __enter__(self) -> DeviceContext:
        self.device.set_current()
        return self

    def __exit__(self, *exc: object) -> None:
        self.sync()

    def __repr__(self) -> str:
        return f"<DeviceContext {self.caps.summary()}>"
