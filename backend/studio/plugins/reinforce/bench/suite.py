"""Benchmark suite: engine operators against the measured dossier figures.

Each benchmark reports achieved throughput next to the number the equivalent
cuda-samples benchmark produced on this GPU, so a regression is visible rather
than merely plausible. Reference figures come from
``frontend/site/docs/01-hardware-dossier.md``; they were measured on 2026-08-16.

**Sizing.** Everything runs past 100 MB where bandwidth is the subject. With
48 MB of L2 on this part, a smaller working set measures cache: the same D2D
copy reported 994 GB/s at 8 MB and 380 GB/s at 512 MB. :func:`bench_l2_cliff`
demonstrates that on purpose.
"""
from __future__ import annotations


import time
from dataclasses import dataclass, field
from typing import Any, Callable

from symoneural.compute._cupy import cp
import numpy as np

from symoneural.compute.ops import Ops
from symoneural.core.context import DeviceContext
from symoneural.core.errors import CapabilityWaived

#: Figures measured on this box by the cuda-samples curriculum.
REFERENCE = {
    "dram_gbs": 752.30,        # reduction sample
    "dram_cg_gbs": 708.92,     # reductionMultiBlockCG
    "theoretical_gbs": 896.1,
    "transpose_gbs": 2202.44,  # transpose sample, fine-grained (L2-resident)
    "matmul_gflops": 4209.83,  # matrixMulSharedMem, custom tiled kernel
    "cublaslt_gflops": 32338.50,
    "graph_speedup": 1.91,     # cudaGraphs
    "h2d_gbs": 6.94,
    "d2h_gbs": 7.20,
}


#: Regimes a benchmark can run in. A ratio is only meaningful against a
#: reference measured in the SAME regime -- comparing an L2-resident run to a
#: DRAM-bound reference (or the reverse) manufactures a regression that is not
#: there. This exact mistake reported transpose at 0.33x when the kernel was
#: fine: the run was 4096^2 (64 MB, DRAM) against a reference taken at 1024^2
#: (4 MB, entirely inside this part's 48 MB L2).
#:
#: Each entry gives (floor, ceiling) for the ratio band treated as healthy.
REGIME_BANDS: dict[str, tuple[float, float]] = {
    # Working set comfortably exceeds L2; should land near the DRAM figure.
    "dram": (0.80, 1.25),
    # Working set fits in L2; legitimately several times the DRAM number, and
    # noisier because kernel time approaches launch overhead.
    "l2": (0.60, 4.00),
    # Between roughly 1x and 3x L2: partially cached. Judge against the DRAM
    # reference, which is the FLOOR for this regime -- partial caching can only
    # help. Hence a tight floor and a very loose ceiling. Comparing straddle
    # against the L2 reference instead reported 0.33x for a transpose running
    # at 730 GB/s, i.e. 0.97x of DRAM speed and entirely healthy.
    "l2-straddle": (0.80, 4.00),
    # Bounded by the PCIe link, which is extremely stable run to run.
    "pcie": (0.90, 1.15),
    # Cooperative launch caps the grid at 2 blocks/SM so every block stays
    # co-resident. Structurally below a two-stage kernel; not a regression.
    "grid-capped": (0.45, 1.25),
    # FLOP-bound; sensitive to matrix size, so the band is wide.
    "compute": (0.50, 1.50),
    # Ratio of two timings taken here; self-consistent.
    "relative": (0.80, 2.00),
    # Informational only -- no reference, never judged.
    "info": (0.0, float("inf")),
    "waived": (0.0, float("inf")),
}


@dataclass
class Result:
    name: str
    metric: str
    value: float
    unit: str
    reference: float | None = None
    note: str = ""
    #: Which band :data:`REGIME_BANDS` should judge this against.
    regime: str = "dram"
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def ratio(self) -> float | None:
        if not self.reference:
            return None
        return self.value / self.reference

    @property
    def band(self) -> tuple[float, float]:
        return REGIME_BANDS.get(self.regime, REGIME_BANDS["dram"])

    @property
    def healthy(self) -> bool:
        """Within the band for its own regime.

        Returns True when there is no reference or the regime is informational --
        an unjudged result is not a failing one.
        """
        r = self.ratio
        if r is None or self.regime in ("info", "waived"):
            return True
        lo, hi = self.band
        return lo <= r <= hi

    @property
    def status(self) -> str:
        if self.ratio is None or self.regime in ("info", "waived"):
            return "--"
        if self.healthy:
            return "ok"
        return "SLOW" if self.ratio < self.band[0] else "FAST?"

    def render(self) -> str:
        ref = ""
        if self.reference:
            r = self.ratio or 0
            ref = (f"  [ref {self.reference:>9.2f} {self.unit}  {r:5.2f}x "
                   f"{self.status:<5s} {self.regime}]")
        note = f"   {self.note}" if self.note else ""
        return f"  {self.name:<30s} {self.value:>10.2f} {self.unit}{ref}{note}"


def memory_regime(working_bytes: int, l2_bytes: int) -> str:
    """Classify a benchmark by working set against the device's real L2.

    Derived, never hardcoded. A hardcoded label goes wrong the moment a size
    changes -- at ``--quick`` the "DRAM-bound" transpose shrank to 16 MB, which
    is L2-resident on this part, and was duly flagged as 3.71x "too fast"
    against a DRAM reference. The size is the ground truth, so read it.
    """
    if l2_bytes <= 0:
        return "dram"
    if working_bytes < l2_bytes * 0.75:
        return "l2"
    if working_bytes < l2_bytes * 3:
        return "l2-straddle"
    return "dram"


def _time_device(fn: Callable[[], Any], iters: int = 20, warmup: int = 5,
                 stream: Any = None) -> float:
    """Mean per-iteration time in ms, with the device fully drained.

    **Do not replace this with CuPy events unless the work is on CuPy's current
    stream.** The operators launch on a ``cuda.core`` stream; a ``cp.cuda.Event``
    records against CuPy's stream, so the two never synchronise and the events
    measure *launch submission* rather than execution. That bug reported 34,578
    GB/s for a device copy and 8.4 PFLOPS for a 512^3 matmul -- both physically
    impossible on a part whose ceiling is 896 GB/s.

    A full device sync bracketing the loop is slightly pessimistic (it includes
    launch overhead amortised across *iters*) but it is correct, which matters
    more.
    """
    for _ in range(warmup):
        fn()
    if stream is not None:
        stream.sync()
    cp.cuda.runtime.deviceSynchronize()

    t0 = time.perf_counter()
    for _ in range(iters):
        fn()
    if stream is not None:
        stream.sync()
    cp.cuda.runtime.deviceSynchronize()
    return (time.perf_counter() - t0) / iters * 1e3


# ---------------------------------------------------------------------------
def bench_copy(ops: Ops, stream: Any, mb: int = 512, l2: int = 0) -> Result:
    """Vectorised device-to-device copy. Counts DRAM traffic as read+write."""
    n = mb * 1024 * 1024 // 4
    src = cp.ones(n, dtype=cp.float32)
    dst = cp.empty_like(src)
    ms = _time_device(lambda: ops.copy(src, dst, stream=stream), stream=stream)
    gbs = 2 * src.nbytes / (ms * 1e-3) / 1e9
    reg = memory_regime(2 * src.nbytes, l2)
    return Result("copy_vec4 (D2D)", "bandwidth", gbs, "GB/s",
                  REFERENCE["dram_gbs"], regime=reg,
                  note=f"{mb} MB, float4 path, read+write counted")


def bench_reduction(ops: Ops, stream: Any, mb: int = 512, l2: int = 0) -> Result:
    n = mb * 1024 * 1024 // 4
    x = cp.ones(n, dtype=cp.float32)
    ms = _time_device(lambda: ops.sum(x, stream=stream), iters=10, stream=stream)
    gbs = x.nbytes / (ms * 1e-3) / 1e9
    return Result("reduce_sum (2-stage)", "bandwidth", gbs, "GB/s",
                  REFERENCE["dram_gbs"], regime=memory_regime(x.nbytes, l2),
                  note=f"{mb} MB")


def bench_reduction_cg(ops: Ops, stream: Any, mb: int = 512) -> Result:
    n = mb * 1024 * 1024 // 4
    x = cp.ones(n, dtype=cp.float32)
    try:
        ms = _time_device(lambda: ops.sum_cooperative(x, stream=stream),
                          iters=10, stream=stream)
    except CapabilityWaived as exc:
        return Result("reduce_sum (single-pass CG)", "bandwidth", 0.0, "GB/s",
                      None, regime="waived", note=f"WAIVED: {exc}")
    gbs = x.nbytes / (ms * 1e-3) / 1e9
    grid = ops.cooperative_grid_size(n)
    return Result("reduce_sum (single-pass CG)", "bandwidth", gbs, "GB/s",
                  REFERENCE["dram_cg_gbs"], regime="grid-capped",
                  note=f"{mb} MB, one launch, grid capped at {grid} co-resident blocks")


def bench_transpose(ops: Ops, stream: Any, dim: int = 4096, l2: int = 0) -> list[Result]:
    """Transpose at two sizes, against two different references.

    **The reference depends on the size, and mixing them is a trap.** The
    upstream ``transpose`` sample reported 2202 GB/s at 1024x1024 -- 4 MB, so
    entirely inside this part's 48 MB L2. That figure is an L2 number and it is
    meaningless to compare a DRAM-bound run against it.

    Measured scaling here makes the boundary obvious:

    ====== ====== ========= ==============
    dim    MB     GB/s      residency
    ====== ====== ========= ==============
    1024   4      843       L2 (see below)
    2048   16     2810      L2
    3072   36     812       exceeds L2
    4096   64     723       DRAM-bound
    ====== ====== ========= ==============

    The 1024 entry is *depressed*, not slow: 8 MB of traffic at L2 speed takes
    ~3 us, comparable to the ~3.4 us launch overhead this wall-clock harness
    cannot subtract. Small-and-fast is where this harness is least accurate,
    which is why the L2 datapoint below uses 2048.
    """
    out: list[Result] = []

    # L2-resident, comparable to the sample's 1024x1024 figure.
    l2_dim = 2048
    x = cp.random.rand(l2_dim, l2_dim, dtype=cp.float32)
    o = cp.empty_like(x)
    ms = _time_device(lambda: ops.transpose(x, o, stream=stream), stream=stream)
    out.append(Result("transpose (small, L2)", "bandwidth",
                      2 * x.nbytes / (ms * 1e-3) / 1e9, "GB/s",
                      REFERENCE["transpose_gbs"],
                      regime=memory_regime(2 * x.nbytes, l2),
                      note=f"{l2_dim}^2 = {x.nbytes / 2**20:.0f} MB, inside 48 MB L2"))
    del x, o
    cp.get_default_memory_pool().free_all_blocks()

    # DRAM-bound: judge against the DRAM figure, not the L2 one.
    x = cp.random.rand(dim, dim, dtype=cp.float32)
    o = cp.empty_like(x)
    ms = _time_device(lambda: ops.transpose(x, o, stream=stream), stream=stream)
    reg = memory_regime(2 * x.nbytes, l2)
    # Name follows the measured regime, so a --quick run that shrinks below L2
    # is not mislabelled "DRAM-bound" in the output it prints.
    out.append(Result(f"transpose (large, {reg})", "bandwidth",
                      2 * x.nbytes / (ms * 1e-3) / 1e9, "GB/s",
                      # DRAM figure is the correct floor for both "dram" and
                      # "l2-straddle"; only a fully L2-resident run belongs
                      # against the cache reference.
                      REFERENCE["transpose_gbs"] if reg == "l2"
                      else REFERENCE["dram_gbs"],
                      regime=reg,
                      note=f"{dim}^2 = {x.nbytes / 2**20:.0f} MB"))
    return out


def bench_matmul(ops: Ops, stream: Any, dim: int = 1024) -> Result:
    a = cp.random.rand(dim, dim, dtype=cp.float32)
    b = cp.random.rand(dim, dim, dtype=cp.float32)
    out = cp.empty((dim, dim), dtype=cp.float32)
    ms = _time_device(lambda: ops.matmul(a, b, out, stream=stream), stream=stream)
    gflops = (2.0 * dim ** 3) / (ms * 1e-3) / 1e9
    return Result("matmul_tiled", "throughput", gflops, "GFLOPS",
                  REFERENCE["matmul_gflops"], regime="compute",
                  note=f"{dim}^3; cuBLASLt reference {REFERENCE['cublaslt_gflops']:.0f}")


def bench_transfer(ctx: DeviceContext, mb: int = 256) -> list[Result]:
    """Host<->device, the PCIe Gen 3 x8 ceiling on this box."""
    n = mb * 1024 * 1024
    host = cp.cuda.alloc_pinned_memory(n)
    h = np.frombuffer(host, np.uint8, n)
    h[:] = 1
    d = cp.empty(n, dtype=cp.uint8)
    # NOTE: deliberately no stream= here. d.set()/d.get() are CuPy transfers
    # that run on CuPy's current stream, not on a cuda.core stream. Passing a
    # cuda.core handle would sync an unrelated, idle stream and prove nothing;
    # the deviceSynchronize() inside _time_device is what actually drains
    # these. Every call that launches OUR kernels does forward stream=stream.
    ms_up = _time_device(lambda: d.set(h), iters=10)
    ms_dn = _time_device(lambda: d.get(out=h), iters=10)
    return [
        Result("H2D (pinned)", "bandwidth", n / (ms_up * 1e-3) / 1e9, "GB/s",
               REFERENCE["h2d_gbs"], regime="pcie",
               note="PCIe Gen 3 x8 ceiling ~7.88 GB/s"),
        Result("D2H (pinned)", "bandwidth", n / (ms_dn * 1e-3) / 1e9, "GB/s",
               REFERENCE["d2h_gbs"], regime="pcie"),
    ]


def bench_l2_cliff(ops: Ops, stream: Any, ctx: DeviceContext) -> list[Result]:
    """Show that buffers inside L2 report a bandwidth that is not DRAM's."""
    out = []
    l2_mb = ctx.caps.l2_bytes / 2**20
    for mb in (8, 32, 128, 512):
        n = mb * 1024 * 1024 // 4
        src = cp.ones(n, dtype=cp.float32)
        dst = cp.empty_like(src)
        ms = _time_device(lambda: ops.copy(src, dst, stream=stream), iters=10, stream=stream)
        gbs = 2 * src.nbytes / (ms * 1e-3) / 1e9
        where = "inside L2" if mb < l2_mb else ("straddles L2" if mb < l2_mb * 3
                                                else "DRAM-bound")
        out.append(Result(f"  copy @ {mb:>4d} MB", "bandwidth", gbs, "GB/s",
                          None, regime="info", note=where))
        del src, dst
        cp.get_default_memory_pool().free_all_blocks()
    return out


def bench_graph(ctx: DeviceContext, ops: Ops) -> Result:
    """CUDA graph replay against individual launches, on a small-kernel chain.

    This is where the engine's scheduler earns its keep -- cudaGraphs measured
    1.91x on the same pattern.
    """
    from cuda.core import LaunchConfig, launch

    from symoneural.compute.ops import DEFAULT_BLOCK, _grid_for
    from symoneural.scheduler.graph import GraphCache

    stream = ctx.create_stream()
    n = 1 << 16                      # small on purpose: launch-bound regime
    x = cp.ones(n, dtype=cp.float32)
    y = cp.ones(n, dtype=cp.float32)
    o1 = cp.empty(n, dtype=cp.float32)
    o2 = cp.empty(n, dtype=cp.float32)
    o3 = cp.empty(n, dtype=cp.float32)

    k = ops.cache.kernel("elementwise", "saxpy<float>")
    grid = _grid_for(n, DEFAULT_BLOCK, ctx.caps.multiprocessor_count)
    cfg = LaunchConfig(grid=grid, block=DEFAULT_BLOCK)
    chain = ((x, y, o1), (o1, y, o2), (o2, y, o3))

    def issue(target):
        for a, b, o in chain:
            launch(target, cfg, k, a.data.ptr, b.data.ptr, o.data.ptr,
                   np.float32(1.5), np.uint64(n))

    iters = 1000
    for _ in range(50):
        issue(stream)
    stream.sync()
    t0 = time.perf_counter()
    for _ in range(iters):
        issue(stream)
    stream.sync()
    per_launch_us = (time.perf_counter() - t0) / iters * 1e6

    cache = GraphCache(ctx)
    g = cache.capture("bench:saxpy_chain", stream, issue,
                      buffers={"x": x, "y": y, "o3": o3})
    for _ in range(50):
        g.launch(stream)
    stream.sync()
    t0 = time.perf_counter()
    for _ in range(iters):
        g.launch(stream)
    stream.sync()
    per_graph_us = (time.perf_counter() - t0) / iters * 1e6

    speedup = per_launch_us / per_graph_us if per_graph_us else 0.0
    return Result("cuda graph replay", "speedup", speedup, "x",
                  REFERENCE["graph_speedup"], regime="relative",
                  note=f"{per_launch_us:.2f} us/iter -> {per_graph_us:.2f} us/iter "
                       f"({iters} iters, 3 kernels)")


def bench_micro_model(ctx: DeviceContext, ops: Ops) -> list[Result]:
    """Batch-scaling of the micro-MLP -- the roofline argument, measured."""
    from symoneural.model.micro import MicroMLP, MLPConfig

    stream = ctx.create_stream()
    mlp = MicroMLP(ops, MLPConfig(d_in=1024, d_hidden=4096, d_out=1024))
    results = []
    base = None
    for batch in (1, 8, 64, 256):
        x = cp.random.rand(batch, 1024, dtype=cp.float32)
        ms = _time_device(lambda: mlp.forward(x, stream=stream), iters=20, stream=stream)
        rows_s = batch / (ms * 1e-3)
        if base is None:
            base = rows_s
        results.append(Result(f"  MLP batch={batch:<4d}", "throughput",
                              rows_s, "rows/s", None, regime="info",
                              note=f"{ms:.3f} ms/pass, {rows_s / base:5.1f}x vs batch=1"))
    return results


# ---------------------------------------------------------------------------
def run_all(quick: bool = False) -> list[Result]:
    ctx = DeviceContext(0)
    ops = Ops(ctx)
    stream = ctx.create_stream()
    mb = 128 if quick else 512

    print(f"\n  Device: {ctx.caps.summary()}")
    print(f"  Driver: {DeviceContext.driver_version()}\n")

    results: list[Result] = []

    print("Memory bandwidth (reference: 752 GB/s measured, 896 GB/s theoretical)")
    l2 = ctx.caps.l2_bytes
    batch = [bench_copy(ops, stream, mb, l2), bench_reduction(ops, stream, mb, l2),
             bench_reduction_cg(ops, stream, mb)]
    batch += bench_transpose(ops, stream, 2048 if quick else 4096, l2)
    for r in batch:
        print(r.render())
        results.append(r)

    print("\nL2 cliff -- why bandwidth tests must exceed ~100 MB on this part")
    for r in bench_l2_cliff(ops, stream, ctx):
        print(r.render())
        results.append(r)

    print("\nCompute")
    r = bench_matmul(ops, stream, 512 if quick else 1024)
    print(r.render())
    results.append(r)

    print("\nHost transfer (PCIe Gen 3 x8 host cap)")
    for r in bench_transfer(ctx, 64 if quick else 256):
        print(r.render())
        results.append(r)

    print("\nLaunch overhead")
    r = bench_graph(ctx, ops)
    print(r.render())
    results.append(r)

    print("\nMicro-model batch scaling (bandwidth-bound -> batching wins)")
    for r in bench_micro_model(ctx, ops):
        print(r.render())
        results.append(r)

    return results
