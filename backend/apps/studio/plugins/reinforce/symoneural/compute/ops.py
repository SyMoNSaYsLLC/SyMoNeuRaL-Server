"""Tensor operators built on the JIT-compiled kernels.

Every operator takes and returns CuPy arrays. CuPy is used purely as a typed
allocation and DLPack layer -- all arithmetic runs in kernels from
:mod:`symoneural.compute.kernels`, compiled by ``cuda.core.Program``. No
operator delegates its maths to CuPy or to any third-party library.

Launch geometry follows what ``launchConfigTuning`` measured on this GPU:
**64 threads per block**, 2.36x better than the worst configuration tested and
notably not the conventional 256.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from ..core.errors import CapabilityWaived, SymoneuralError
from ._cupy import cp
from .program import KernelCache

try:
    from cuda.core import LaunchConfig, launch
except ImportError as exc:  # pragma: no cover
    raise ImportError("cuda-core is required") from exc

#: Measured optimum on sm_120 (launchConfigTuning). Not the conventional 256.
DEFAULT_BLOCK = 64
TILE = 32          # must match TILE in kernels.MATMUL_SRC
TRANSPOSE_TILE = 32
TRANSPOSE_BLOCK_ROWS = 8


def _grid_for(n: int, block: int, sm_count: int, waves: int = 8) -> int:
    """Grid size for a grid-stride kernel.

    Capped at ``waves * sm_count`` blocks: grid-stride loops do not need one
    block per element, and an oversized grid just adds scheduling cost.
    """
    need = (n + block - 1) // block
    return max(1, min(need, waves * sm_count))


def cupy_barrier() -> None:
    """Barrier between CuPy's stream and the engine's ``cuda.core`` streams.

    **Call this after producing an input with CuPy and before handing it to an
    operator.** CuPy allocation and arithmetic (``cp.random.rand``, ``asarray``,
    ``fill``, ``+``) run on CuPy's *current* stream. Engine operators launch on
    a ``cuda.core`` stream. CUDA does not order work across two streams
    implicitly, so without a barrier a kernel can read a buffer CuPy has not
    finished writing.

    The failure is intermittent and silent — a wrong numeric result, not a
    crash — which makes it worth an explicit call rather than a convention.
    The same mismatch caused a phantom benchmark reading of 34 TB/s and a
    flaky graph-replay test; this is the third form it took.

    Cost is a full device sync: negligible next to a forward pass, too
    expensive to put inside every operator, which is why it is the caller's
    job at the boundary.
    """
    cp.cuda.runtime.deviceSynchronize()


def _require_f32(**arrays: cp.ndarray) -> None:
    """Reject non-float32 inputs before they reach a kernel.

    Kernels take raw pointers, so a float64 array is reinterpreted bytewise
    rather than rejected -- the result is finite, plausible-looking garbage
    (values around 1e20) with no error anywhere. Cheap guard, silent failure
    mode without it.
    """
    for name, arr in arrays.items():
        if arr is None:
            continue
        if arr.dtype != cp.float32:
            raise SymoneuralError(
                f"{name} must be float32, got {arr.dtype}. Kernels read raw "
                "pointers; a wider dtype is reinterpreted, not converted. "
                f"Use .astype(cupy.float32) on {name}."
            )
        if not arr.flags.c_contiguous:
            raise SymoneuralError(
                f"{name} must be C-contiguous; use cupy.ascontiguousarray()"
            )


class Ops:
    """Operator set bound to one device context and kernel cache."""

    def __init__(self, ctx: Any, cache: KernelCache | None = None) -> None:
        self.ctx = ctx
        self.cache = cache or KernelCache(ctx.caps.arch)
        self.sm_count = ctx.caps.multiprocessor_count

    # -- element-wise ------------------------------------------------------
    def saxpy(self, x: cp.ndarray, y: cp.ndarray, alpha: float,
              out: cp.ndarray | None = None, stream: Any = None) -> cp.ndarray:
        """out = alpha * x + y, element-wise."""
        if x.shape != y.shape:
            raise SymoneuralError(f"shape mismatch: {x.shape} vs {y.shape}")
        _require_f32(x=x, y=y, out=out)
        out = cp.empty_like(x) if out is None else out
        n = x.size
        k = self.cache.kernel("elementwise", "saxpy<float>")
        grid = _grid_for(n, DEFAULT_BLOCK, self.sm_count)
        launch(stream or self.ctx.create_stream(),
               LaunchConfig(grid=grid, block=DEFAULT_BLOCK), k,
               x.data.ptr, y.data.ptr, out.data.ptr,
               np.float32(alpha), np.uint64(n))
        return out

    def relu_(self, x: cp.ndarray, stream: Any = None) -> cp.ndarray:
        """In-place ReLU."""
        _require_f32(x=x)
        k = self.cache.kernel("elementwise", "relu<float>")
        grid = _grid_for(x.size, DEFAULT_BLOCK, self.sm_count)
        launch(stream or self.ctx.create_stream(),
               LaunchConfig(grid=grid, block=DEFAULT_BLOCK), k,
               x.data.ptr, np.uint64(x.size))
        return x

    def gelu_(self, x: cp.ndarray, stream: Any = None) -> cp.ndarray:
        """In-place GELU (tanh approximation)."""
        _require_f32(x=x)
        k = self.cache.kernel("elementwise", "gelu_tanh<float>")
        grid = _grid_for(x.size, DEFAULT_BLOCK, self.sm_count)
        launch(stream or self.ctx.create_stream(),
               LaunchConfig(grid=grid, block=DEFAULT_BLOCK), k,
               x.data.ptr, np.uint64(x.size))
        return x

    def add_bias_(self, x: cp.ndarray, bias: cp.ndarray,
                  stream: Any = None) -> cp.ndarray:
        """In-place row-broadcast bias add. *x* is (rows, cols), *bias* is (cols,)."""
        if x.ndim != 2:
            raise SymoneuralError(f"add_bias expects 2D, got {x.ndim}D")
        _require_f32(x=x, bias=bias)
        rows, cols = x.shape
        if bias.size != cols:
            raise SymoneuralError(f"bias size {bias.size} != cols {cols}")
        k = self.cache.kernel("elementwise", "add_bias<float>")
        grid = _grid_for(x.size, DEFAULT_BLOCK, self.sm_count)
        launch(stream or self.ctx.create_stream(),
               LaunchConfig(grid=grid, block=DEFAULT_BLOCK), k,
               x.data.ptr, bias.data.ptr, np.uint32(rows), np.uint32(cols))
        return x

    # -- copy --------------------------------------------------------------
    def copy(self, src: cp.ndarray, dst: cp.ndarray | None = None,
             stream: Any = None) -> cp.ndarray:
        """Device-to-device copy, vectorised to float4 when alignment allows.

        ``alignedTypes`` measured 341 GB/s at 16-byte width against 45 GB/s at
        1 byte, so the wide path is taken whenever it is legal.
        """
        _require_f32(src=src, dst=dst)
        dst = cp.empty_like(src) if dst is None else dst
        n = src.size
        vec_ok = (n % 4 == 0
                  and src.data.ptr % 16 == 0
                  and dst.data.ptr % 16 == 0)
        st = stream or self.ctx.create_stream()
        if vec_ok:
            k = self.cache.kernel("vector_copy", "copy_vec4")
            n4 = n // 4
            grid = _grid_for(n4, DEFAULT_BLOCK, self.sm_count)
            launch(st, LaunchConfig(grid=grid, block=DEFAULT_BLOCK), k,
                   src.data.ptr, dst.data.ptr, np.uint64(n4))
        else:
            k = self.cache.kernel("vector_copy", "copy_scalar")
            grid = _grid_for(n, DEFAULT_BLOCK, self.sm_count)
            launch(st, LaunchConfig(grid=grid, block=DEFAULT_BLOCK), k,
                   src.data.ptr, dst.data.ptr, np.uint64(n))
        return dst

    # -- transpose ---------------------------------------------------------
    def transpose(self, x: cp.ndarray, out: cp.ndarray | None = None,
                  stream: Any = None) -> cp.ndarray:
        """Coalesced 2D transpose via a padded shared tile."""
        if x.ndim != 2:
            raise SymoneuralError(f"transpose expects 2D, got {x.ndim}D")
        _require_f32(x=x, out=out)
        h, w = x.shape
        out = cp.empty((w, h), dtype=x.dtype) if out is None else out
        k = self.cache.kernel("transpose", "transpose_coalesced")
        grid = ((w + TRANSPOSE_TILE - 1) // TRANSPOSE_TILE,
                (h + TRANSPOSE_TILE - 1) // TRANSPOSE_TILE, 1)
        launch(stream or self.ctx.create_stream(),
               LaunchConfig(grid=grid,
                            block=(TRANSPOSE_TILE, TRANSPOSE_BLOCK_ROWS, 1)),
               k, x.data.ptr, out.data.ptr, np.uint32(w), np.uint32(h))
        return out

    # -- matmul ------------------------------------------------------------
    def matmul(self, a: cp.ndarray, b: cp.ndarray,
               out: cp.ndarray | None = None, stream: Any = None) -> cp.ndarray:
        """Tiled GEMM: (M,K) x (K,N) -> (M,N), float32, row-major."""
        if a.ndim != 2 or b.ndim != 2:
            raise SymoneuralError("matmul expects 2D operands")
        _require_f32(a=a, b=b, out=out)
        m, ka = a.shape
        kb, n = b.shape
        if ka != kb:
            raise SymoneuralError(f"inner dims disagree: {ka} vs {kb}")
        out = cp.empty((m, n), dtype=cp.float32) if out is None else out
        k = self.cache.kernel("matmul", "matmul_tiled")
        grid = ((n + TILE - 1) // TILE, (m + TILE - 1) // TILE, 1)
        launch(stream or self.ctx.create_stream(),
               LaunchConfig(grid=grid, block=(TILE, TILE, 1)), k,
               a.data.ptr, b.data.ptr, out.data.ptr,
               np.uint32(m), np.uint32(n), np.uint32(ka))
        return out

    # -- reductions --------------------------------------------------------
    def _reduce(self, x: cp.ndarray, kernel_name: str, stream: Any) -> float:
        _require_f32(x=x)
        block = 256                       # reductions want a wider block
        st = stream or self.ctx.create_stream()
        k = self.cache.kernel("reduction", kernel_name)
        cur = x.ravel()
        n = cur.size
        while True:
            grid = max(1, min((n + block * 2 - 1) // (block * 2),
                              self.sm_count * 8))
            partial = cp.empty(grid, dtype=cp.float32)
            launch(st, LaunchConfig(grid=grid, block=block,
                                    shmem_size=block * 4), k,
                   cur.data.ptr, partial.data.ptr, np.uint32(n))
            st.sync()
            if grid == 1:
                return float(partial[0])
            cur, n = partial, grid

    def sum(self, x: cp.ndarray, stream: Any = None) -> float:
        """Two-stage shared-memory sum. ~752 GB/s on this GPU at scale."""
        return self._reduce(x, "reduce_sum_stage", stream)

    def max(self, x: cp.ndarray, stream: Any = None) -> float:
        return self._reduce(x, "reduce_max_stage", stream)

    def sum_cooperative(self, x: cp.ndarray, stream: Any = None) -> float:
        """Single-pass reduction using ``grid.sync()``.

        One launch instead of two, ~708 GB/s measured. Every block must be
        resident simultaneously, so the grid is capped at what the device can
        actually co-schedule.

        Raises :class:`CapabilityWaived` if the device cannot launch
        cooperatively.
        """
        _require_f32(x=x)
        self.ctx.require_cooperative()
        block = 256
        flat = x.ravel()
        n = flat.size
        # All blocks must co-reside: cap at 2 blocks/SM for a 256-thread block
        # against the 1536 threads/SM this part supports.
        grid = max(1, min(self.sm_count * 2, (n + block - 1) // block))
        partials = cp.empty(grid, dtype=cp.float32)
        result = cp.empty(1, dtype=cp.float32)
        k = self.cache.kernel("reduction_cg", "reduce_single_pass_cg")
        st = stream or self.ctx.create_stream()
        try:
            launch(st,
                   LaunchConfig(grid=grid, block=block,
                                shmem_size=block * 4, is_cooperative=True), k,
                   flat.data.ptr, partials.data.ptr, result.data.ptr,
                   np.uint32(n))
        except Exception as exc:
            raise CapabilityWaived(
                f"cooperative launch of {grid} blocks x {block} threads was "
                f"rejected by the driver: {exc}"
            ) from exc
        # Sync the stream the work is actually on. A bare ctx.sync() also works
        # but hides which stream mattered, and a caller timing this needs the
        # same handle it passed in.
        st.sync()
        return float(result[0])

    def cooperative_grid_size(self, n: int, block: int = 256) -> int:
        """Grid the cooperative reduction will use for *n* elements.

        Exposed because it explains the throughput gap: every block must be
        co-resident, so the grid is capped at 2 blocks/SM (140 on this part)
        regardless of *n*. That ceiling is the price of one launch instead of
        two -- not a defect.
        """
        return max(1, min(self.sm_count * 2, (n + block - 1) // block))

    # -- softmax -----------------------------------------------------------
    def softmax_(self, x: cp.ndarray, stream: Any = None) -> cp.ndarray:
        """In-place row-wise softmax, numerically stabilised."""
        if x.ndim != 2:
            raise SymoneuralError(f"softmax expects 2D, got {x.ndim}D")
        _require_f32(x=x)
        rows, cols = x.shape
        block = min(256, max(32, 1 << (int(cols).bit_length() - 1)))
        k = self.cache.kernel("softmax", "softmax_rows")
        launch(stream or self.ctx.create_stream(),
               LaunchConfig(grid=rows, block=block, shmem_size=block * 4), k,
               x.data.ptr, np.uint32(rows), np.uint32(cols))
        return x
