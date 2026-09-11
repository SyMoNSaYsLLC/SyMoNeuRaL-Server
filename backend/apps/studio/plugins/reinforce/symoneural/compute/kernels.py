"""Raw CUDA C++ kernel sources, as Python strings compiled by NVRTC at runtime.

Every kernel here is written from scratch against primitives the local
cuda-samples curriculum validated on this GPU. Nothing wraps a third-party
inference codebase.

Design decisions and where they come from (all measured, see
``docs/01-hardware-dossier.md`` and ``docs/04-cuda-curriculum/``):

* **Vectorised loads (``float4``).** ``alignedTypes`` measured 341 GB/s for
  16-byte accesses versus 45 GB/s for single bytes -- a 7.4x spread from access
  width alone. Bandwidth-bound kernels here load ``float4`` wherever alignment
  allows.
* **Shared-memory privatisation.** ``parallelHistogram`` measured 89.5x for
  privatised over global atomics. Any kernel that accumulates does it in shared
  memory first.
* **Tiling for matmul.** ``matrixMulSharedMem`` measured 4,210 GFLOPS for a
  tiled custom kernel against 32,338 for cuBLASLt. The custom kernel is here
  because the brief calls for native implementations; the honest framing is in
  the module docstring of ``matmul.py``.
* **``grid.sync()`` single-pass reduction.** ``reductionMultiBlockCG`` measured
  708.92 GB/s in one launch, versus a two-launch scheme. Saves ~5-20 us of
  launch overhead per stage.
* **Block size 64.** ``launchConfigTuning`` found 64 optimal on this part,
  2.36x over the worst configuration tested -- notably *not* the conventional
  256. Defaults here follow the measurement.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Element-wise transforms. Templated so one source serves float/double.
# ---------------------------------------------------------------------------
ELEMENTWISE_SRC = r"""
// Grid-stride element-wise ops. Grid-stride (rather than one-thread-one-element)
// keeps the launch config independent of problem size, which is what lets the
// scheduler bake a single CUDA graph and replay it for any batch.

template <typename T>
__global__ void saxpy(const T* __restrict__ x,
                      const T* __restrict__ y,
                      T* __restrict__ out,
                      T alpha, unsigned long long n)
{
    unsigned long long stride = (unsigned long long)blockDim.x * gridDim.x;
    for (unsigned long long i = (unsigned long long)blockIdx.x * blockDim.x + threadIdx.x;
         i < n; i += stride) {
        out[i] = alpha * x[i] + y[i];
    }
}

template <typename T>
__global__ void add_bias(T* __restrict__ x,
                         const T* __restrict__ bias,
                         unsigned int rows, unsigned int cols)
{
    unsigned long long total = (unsigned long long)rows * cols;
    unsigned long long stride = (unsigned long long)blockDim.x * gridDim.x;
    for (unsigned long long i = (unsigned long long)blockIdx.x * blockDim.x + threadIdx.x;
         i < total; i += stride) {
        x[i] += bias[i % cols];
    }
}

// ReLU and GELU fused with nothing else on purpose: the engine composes them
// through CUDA graphs rather than through ever-wider fused kernels.
template <typename T>
__global__ void relu(T* __restrict__ x, unsigned long long n)
{
    unsigned long long stride = (unsigned long long)blockDim.x * gridDim.x;
    for (unsigned long long i = (unsigned long long)blockIdx.x * blockDim.x + threadIdx.x;
         i < n; i += stride) {
        T v = x[i];
        x[i] = v > T(0) ? v : T(0);
    }
}

template <typename T>
__global__ void gelu_tanh(T* __restrict__ x, unsigned long long n)
{
    // tanh approximation: 0.5x(1 + tanh(sqrt(2/pi)(x + 0.044715 x^3)))
    const T k0 = T(0.7978845608028654);   // sqrt(2/pi)
    const T k1 = T(0.044715);
    unsigned long long stride = (unsigned long long)blockDim.x * gridDim.x;
    for (unsigned long long i = (unsigned long long)blockIdx.x * blockDim.x + threadIdx.x;
         i < n; i += stride) {
        T v = x[i];
        T inner = k0 * (v + k1 * v * v * v);
        x[i] = T(0.5) * v * (T(1) + tanh(inner));
    }
}
"""

# ---------------------------------------------------------------------------
# Vectorised copy. Mirrors what alignedTypes measured: width is everything.
# ---------------------------------------------------------------------------
VECTOR_COPY_SRC = r"""
// float4 = 16-byte access. alignedTypes measured 341 GB/s at this width against
// 45 GB/s for uint8 on the same GPU. Requires n % 4 == 0 and 16-byte alignment;
// the Python wrapper falls back to the scalar kernel when that does not hold.
extern "C" __global__ void copy_vec4(const float4* __restrict__ src,
                                     float4* __restrict__ dst,
                                     unsigned long long n4)
{
    unsigned long long stride = (unsigned long long)blockDim.x * gridDim.x;
    for (unsigned long long i = (unsigned long long)blockIdx.x * blockDim.x + threadIdx.x;
         i < n4; i += stride) {
        dst[i] = src[i];
    }
}

extern "C" __global__ void copy_scalar(const float* __restrict__ src,
                                       float* __restrict__ dst,
                                       unsigned long long n)
{
    unsigned long long stride = (unsigned long long)blockDim.x * gridDim.x;
    for (unsigned long long i = (unsigned long long)blockIdx.x * blockDim.x + threadIdx.x;
         i < n; i += stride) {
        dst[i] = src[i];
    }
}
"""

# ---------------------------------------------------------------------------
# Coalesced transpose with a padded shared tile.
# ---------------------------------------------------------------------------
TRANSPOSE_SRC = r"""
// TILE_DIM x BLOCK_ROWS tiling with a +1 pad on the shared array.
//
// The pad is the whole trick: without it, column-major reads from the tile all
// land in the same shared-memory bank and serialise 32 ways. The local
// `transpose` sample measured 372 GB/s naive against 2202 GB/s optimised --
// ~5.9x, from coalescing plus this one padding element.

#define TILE_DIM 32
#define BLOCK_ROWS 8

extern "C" __global__ void transpose_coalesced(const float* __restrict__ idata,
                                               float* __restrict__ odata,
                                               unsigned int width,
                                               unsigned int height)
{
    __shared__ float tile[TILE_DIM][TILE_DIM + 1];   // +1 defeats bank conflicts

    unsigned int x = blockIdx.x * TILE_DIM + threadIdx.x;
    unsigned int y = blockIdx.y * TILE_DIM + threadIdx.y;

    for (int j = 0; j < TILE_DIM; j += BLOCK_ROWS) {
        if (x < width && (y + j) < height)
            tile[threadIdx.y + j][threadIdx.x] = idata[(y + j) * width + x];
    }
    __syncthreads();

    x = blockIdx.y * TILE_DIM + threadIdx.x;
    y = blockIdx.x * TILE_DIM + threadIdx.y;

    for (int j = 0; j < TILE_DIM; j += BLOCK_ROWS) {
        if (x < height && (y + j) < width)
            odata[(y + j) * height + x] = tile[threadIdx.x][threadIdx.y + j];
    }
}
"""

# ---------------------------------------------------------------------------
# Tiled matmul.
# ---------------------------------------------------------------------------
MATMUL_SRC = r"""
// Tiled GEMM: C[MxN] = A[MxK] * B[KxN], row-major.
//
// Each block stages a TILE x TILE square of A and of B into shared memory, so
// every element loaded from DRAM is reused TILE times. Without tiling the same
// kernel is bandwidth-bound and lands near the transpose-naive figure.

#define TILE 32

extern "C" __global__ void matmul_tiled(const float* __restrict__ A,
                                        const float* __restrict__ B,
                                        float* __restrict__ C,
                                        unsigned int M, unsigned int N, unsigned int K)
{
    __shared__ float As[TILE][TILE + 1];
    __shared__ float Bs[TILE][TILE + 1];

    unsigned int row = blockIdx.y * TILE + threadIdx.y;
    unsigned int col = blockIdx.x * TILE + threadIdx.x;
    float acc = 0.0f;

    unsigned int ntiles = (K + TILE - 1) / TILE;
    for (unsigned int t = 0; t < ntiles; ++t) {
        unsigned int aCol = t * TILE + threadIdx.x;
        unsigned int bRow = t * TILE + threadIdx.y;

        As[threadIdx.y][threadIdx.x] = (row < M && aCol < K) ? A[row * K + aCol] : 0.0f;
        Bs[threadIdx.y][threadIdx.x] = (bRow < K && col < N) ? B[bRow * N + col] : 0.0f;
        __syncthreads();

        #pragma unroll
        for (int k = 0; k < TILE; ++k)
            acc += As[threadIdx.y][k] * Bs[k][threadIdx.x];
        __syncthreads();
    }

    if (row < M && col < N)
        C[row * N + col] = acc;
}
"""

# ---------------------------------------------------------------------------
# Reductions.
# ---------------------------------------------------------------------------
REDUCTION_SRC = r"""
// Two-stage shared-memory reduction. Each thread loads TWO elements on the way
// in, halving the block count for a given n -- the local `reduction` sample
// credits that trick with 50% fewer global reads and measured 752.30 GB/s.
//
// Warp-level shuffle finishes the last 32 lanes without __syncthreads().

extern "C" __global__ void reduce_sum_stage(const float* __restrict__ g_in,
                                            float* __restrict__ g_out,
                                            unsigned int n)
{
    extern __shared__ float sdata[];
    unsigned int tid = threadIdx.x;
    unsigned int i = blockIdx.x * (blockDim.x * 2) + threadIdx.x;
    unsigned int gridSize = blockDim.x * 2 * gridDim.x;

    float sum = 0.0f;
    while (i < n) {
        sum += g_in[i];
        if (i + blockDim.x < n) sum += g_in[i + blockDim.x];
        i += gridSize;
    }
    sdata[tid] = sum;
    __syncthreads();

    for (unsigned int s = blockDim.x / 2; s > 32; s >>= 1) {
        if (tid < s) sdata[tid] += sdata[tid + s];
        __syncthreads();
    }

    if (tid < 32) {
        float v = sdata[tid];
        if (blockDim.x >= 64) v += sdata[tid + 32];
        for (int off = 16; off > 0; off >>= 1)
            v += __shfl_down_sync(0xffffffff, v, off);
        if (tid == 0) g_out[blockIdx.x] = v;
    }
}

extern "C" __global__ void reduce_max_stage(const float* __restrict__ g_in,
                                            float* __restrict__ g_out,
                                            unsigned int n)
{
    extern __shared__ float sdata[];
    unsigned int tid = threadIdx.x;
    unsigned int i = blockIdx.x * (blockDim.x * 2) + threadIdx.x;
    unsigned int gridSize = blockDim.x * 2 * gridDim.x;

    float m = -3.402823466e+38f;
    while (i < n) {
        m = fmaxf(m, g_in[i]);
        if (i + blockDim.x < n) m = fmaxf(m, g_in[i + blockDim.x]);
        i += gridSize;
    }
    sdata[tid] = m;
    __syncthreads();

    for (unsigned int s = blockDim.x / 2; s > 32; s >>= 1) {
        if (tid < s) sdata[tid] = fmaxf(sdata[tid], sdata[tid + s]);
        __syncthreads();
    }
    if (tid < 32) {
        float v = sdata[tid];
        if (blockDim.x >= 64) v = fmaxf(v, sdata[tid + 32]);
        for (int off = 16; off > 0; off >>= 1)
            v = fmaxf(v, __shfl_down_sync(0xffffffff, v, off));
        if (tid == 0) g_out[blockIdx.x] = v;
    }
}
"""

# ---------------------------------------------------------------------------
# Single-pass cooperative-groups reduction.
# ---------------------------------------------------------------------------
REDUCTION_CG_SRC = r"""
// Single-pass multi-block reduction using grid.sync().
//
// Stage 1: every block reduces its slice to one partial.
// grid.sync(): ALL blocks rendezvous -- the whole point, and why this needs a
//              cooperative launch with every block resident simultaneously.
// Stage 2: block 0 folds the partials to the final scalar.
//
// One launch instead of two. reductionMultiBlockCG measured 708.92 GB/s here
// and saves ~5-20 us of launch overhead per stage.
//
// REQUIRES: cooperative launch support, is_cooperative=True on the LaunchConfig,
// and a grid no larger than the device can hold resident at once. Compiling
// this needs BOTH the CUDA include dir and the libcu++ headers from the
// cuda-cccl package -- see compute/program.py, which resolves them.

#include <cooperative_groups.h>
namespace cg = cooperative_groups;

extern "C" __global__ void reduce_single_pass_cg(const float* __restrict__ g_in,
                                                 float* __restrict__ g_partials,
                                                 float* __restrict__ g_out,
                                                 unsigned int n)
{
    extern __shared__ float sdata[];
    cg::thread_block cta = cg::this_thread_block();
    cg::grid_group grid = cg::this_grid();

    unsigned int tid = threadIdx.x;
    unsigned int gtid = blockIdx.x * blockDim.x + threadIdx.x;
    unsigned int gridSize = blockDim.x * gridDim.x;

    float sum = 0.0f;
    for (unsigned int i = gtid; i < n; i += gridSize)
        sum += g_in[i];

    sdata[tid] = sum;
    cg::sync(cta);

    for (unsigned int s = blockDim.x / 2; s > 0; s >>= 1) {
        if (tid < s) sdata[tid] += sdata[tid + s];
        cg::sync(cta);
    }
    if (tid == 0) g_partials[blockIdx.x] = sdata[0];

    grid.sync();               // <-- every block waits here

    if (blockIdx.x == 0) {
        float total = 0.0f;
        for (unsigned int i = tid; i < gridDim.x; i += blockDim.x)
            total += g_partials[i];
        sdata[tid] = total;
        cg::sync(cta);
        for (unsigned int s = blockDim.x / 2; s > 0; s >>= 1) {
            if (tid < s) sdata[tid] += sdata[tid + s];
            cg::sync(cta);
        }
        if (tid == 0) *g_out = sdata[0];
    }
}
"""

# ---------------------------------------------------------------------------
# Softmax, for the micro-model attention block.
# ---------------------------------------------------------------------------
SOFTMAX_SRC = r"""
// Row-wise softmax, one block per row, numerically stabilised by subtracting
// the row max before exponentiating. Both passes privatise into shared memory
// rather than hitting global atomics -- the parallelHistogram lesson (89.5x)
// applies to any accumulation, not just counting.

extern "C" __global__ void softmax_rows(float* __restrict__ x,
                                        unsigned int rows, unsigned int cols)
{
    extern __shared__ float buf[];
    unsigned int row = blockIdx.x;
    if (row >= rows) return;

    float* rowp = x + (size_t)row * cols;
    unsigned int tid = threadIdx.x;

    float m = -3.402823466e+38f;
    for (unsigned int i = tid; i < cols; i += blockDim.x)
        m = fmaxf(m, rowp[i]);
    buf[tid] = m;
    __syncthreads();
    for (unsigned int s = blockDim.x / 2; s > 0; s >>= 1) {
        if (tid < s) buf[tid] = fmaxf(buf[tid], buf[tid + s]);
        __syncthreads();
    }
    float rowmax = buf[0];
    __syncthreads();

    float partial = 0.0f;
    for (unsigned int i = tid; i < cols; i += blockDim.x) {
        float e = expf(rowp[i] - rowmax);
        rowp[i] = e;
        partial += e;
    }
    buf[tid] = partial;
    __syncthreads();
    for (unsigned int s = blockDim.x / 2; s > 0; s >>= 1) {
        if (tid < s) buf[tid] += buf[tid + s];
        __syncthreads();
    }
    float total = buf[0];
    __syncthreads();

    float inv = 1.0f / total;
    for (unsigned int i = tid; i < cols; i += blockDim.x)
        rowp[i] *= inv;
}
"""

ALL_SOURCES = {
    "elementwise": ELEMENTWISE_SRC,
    "vector_copy": VECTOR_COPY_SRC,
    "transpose": TRANSPOSE_SRC,
    "matmul": MATMUL_SRC,
    "reduction": REDUCTION_SRC,
    "reduction_cg": REDUCTION_CG_SRC,
    "softmax": SOFTMAX_SRC,
}

#: Templated kernels need explicit instantiation names at compile time.
TEMPLATE_INSTANTIATIONS = {
    "elementwise": (
        "saxpy<float>", "saxpy<double>",
        "add_bias<float>", "relu<float>", "gelu_tanh<float>",
    ),
}
