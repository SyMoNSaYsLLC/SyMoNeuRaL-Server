# 2_CoreConcepts — Core concepts

20 sample document(s), each with the verified *On this box* result and the complete upstream README.

> Part of the [symoneural_reinforce documentation set](README.md). Sliced from the consolidated manual at `../../../../../frontend/site/docs/symoneural-manual.md`, which remains the canonical single file.

## 2_CoreConcepts — Core concepts

Twenty samples — the substance of the curriculum. Reduction, scan, histogram, tiling, graphs, streams, memory resources, TMA, SM partitioning and checkpointing. Three of them need their own venv; two need extra command-line flags.

<br>

### binarySearch

> #### On this box
>
> **Command**
> ```bash
> cd $CUDA_SAMPLES/python/2_CoreConcepts/binarySearch
> source $VENVS/venv-extras/bin/activate      # isolated: base + cuda-cccl, nvtx, numba-cuda, torch, mpi4py
> python binarySearch.py
> ```
>
> **Result** — All cases OK — `lower_bound`/`upper_bound` matched expectations including the duplicate-key case.
>
> *Wall time: 8.7 s*
>
> **Notes** — Slowest getting-started-tier sample at 8.7 s; nearly all of it is `cuda.compute` JIT warm-up, not search time.

<details>
<summary><b>Full README — binarySearch</b></summary>

#### binarySearch (Python)

##### Description

This sample demonstrates the parallel binary-search algorithms
exposed by **cuda.compute** (from the `cuda-cccl` package). Given
a sorted `d_data` array and a batch of `d_values` to locate, one
device-wide call returns the insertion index for every value:

- `cuda.compute.lower_bound` writes, for each value, the lowest index
  where it could be inserted into `d_data` without breaking the sort
  order. Equivalent to `numpy.searchsorted(..., side="left")`.
- `cuda.compute.upper_bound` is the analogous upper form, equivalent
  to `numpy.searchsorted(..., side="right")`.

The sample runs both algorithms on two curated inputs: one with
distinct elements (where `lower_bound` and `upper_bound` agree on
any value not in the data) and one with duplicates (where they
diverge on present values). Results are verified against
`numpy.searchsorted`.

##### What You'll Learn

- How to call `cuda.compute.lower_bound` / `upper_bound` with CuPy
  arrays
- The semantic difference between `lower_bound` and `upper_bound`,
  especially for inputs containing duplicates
- How the output dtype (`np.uintp`) is used for indices

##### Key Libraries

- [`cuda.compute`](https://nvidia.github.io/cccl/python.html) (from the `cuda-cccl` package) - device algorithms
- [`cuda.core`](https://nvidia.github.io/cuda-python/cuda-core/latest/) - device setup
- `cupy` - device buffers
- `numpy` - host-side reference via `numpy.searchsorted`

##### Key APIs

###### From `cuda.compute`

- `cuda.compute.lower_bound(d_data, num_items, d_values, num_values, d_out)`
- `cuda.compute.upper_bound(d_data, num_items, d_values, num_values, d_out)`

###### From `cuda_samples_utils`

- `print_gpu_info()` - print device name and compute capability

##### Requirements

###### Hardware

- NVIDIA GPU with Compute Capability 7.0 or higher
- Minimum GPU memory: 512 MB

###### Software

- CUDA Toolkit 13.0 or newer
- Python 3.10 or newer
- `cuda-cccl` (>=1.0.0)
- `cuda-core` (>=1.0.0)
- `cupy-cuda13x` (>=14.0.0)

If the CUDA toolkit is not on your `PATH`, set `CUDA_HOME` so that
cuda.compute's JIT path can locate its dependencies:

```bash
export CUDA_HOME=/usr/local/cuda
```

##### Installation

Install the required packages from `requirements.txt`:

```bash
cd $CUDA_SAMPLES/python/2_CoreConcepts/binarySearch
pip install -r requirements.txt
```

The `requirements.txt` installs:

- `cuda-cccl` (>=1.0.0) - ships the `cuda.compute` module
- `cuda-core` (>=1.0.0)
- `cupy-cuda13x` (>=14.0.0)
- `numpy` (>=1.24.0)

##### How to Run

###### Basic usage

```bash
cd $CUDA_SAMPLES/python/2_CoreConcepts/binarySearch
python binarySearch.py
```

###### With custom parameters

```bash
python binarySearch.py --device 1
```

##### Expected Output

```
Device: <Your GPU Name>
Compute Capability: <X.Y>

Case 1: distinct data, mixed queries
  data    = [1, 3, 5, 7, 9]
  values  = [0, 3, 4, 10]
  lower_bound: got [0, 1, 2, 5]  expected [0, 1, 2, 5]  OK
  upper_bound: got [0, 2, 2, 5]  expected [0, 2, 2, 5]  OK

Case 2: duplicates in data
  data    = [1, 3, 3, 5, 7, 9]
  values  = [3, 3, 5, 8]
  lower_bound: got [1, 1, 3, 5]  expected [1, 1, 3, 5]  OK
  upper_bound: got [3, 3, 4, 5]  expected [3, 3, 4, 5]  OK

Done
```

**Note:** Device name and compute capability will vary based on your GPU.

##### Files

- `binarySearch.py` - Python implementation
- `README.md` - This file
- `requirements.txt` - Sample dependencies
- `../../Utilities/cuda_samples_utils.py` - Common utilities (imported by this sample)


</details>

<br>

### blockwiseSum

> #### On this box
>
> **Command**
> ```bash
> cd $CUDA_SAMPLES/python/2_CoreConcepts/blockwiseSum
> python blockwiseSum.py
> ```
>
> **Result** — All three variants PASSED over 1,048,576 elements. Kernel 0.010 ms, **431.7 GB/s**.
>
> *Wall time: 3.4 s*
>
> **Notes** — 431 GB/s looks low against the 896 GB/s peak because a 4 MB array is too small to saturate DRAM — it partly lives in the 48 MB L2. Compare with `reduction` (752 GB/s on a larger array).

<details>
<summary><b>Full README — blockwiseSum</b></summary>

#### Sample: Block-wise Array Sum (Python)

##### Description

Demonstrates fundamental CUDA thread cooperation: thread/block indexing, strided loops, and block-wise reduction using shared memory. This sample shows three progressively complex kernel patterns using the **cuda.core API**:

1. **Simple indexing** - One thread per element
2. **Strided loop** - Each thread processes multiple elements
3. **Block partial sum** - Shared memory reduction within each block

##### What You'll Learn

- How to calculate global thread ID from block and thread indices
- Strided loop pattern for processing arrays larger than grid size
- Block-level cooperation using shared memory and `__syncthreads()`

##### Key Concepts

###### Thread and Block Indexing

```
Global Thread ID = blockIdx.x * blockDim.x + threadIdx.x
Stride = blockDim.x * gridDim.x
```

###### Strided Loop Pattern

Each thread processes multiple elements, enabling fixed grid size for arbitrary array lengths:

```c
for (size_t i = tid; i < N; i += stride) {
    output[i] = input[i] * 2.0f;
}
```

##### Key APIs

###### From `cuda.core`:

- `Device` - Device management and context
- `Program` - Compile CUDA C++ kernels
- `ProgramOptions` - Kernel compilation options (architecture target)
- `LaunchConfig` - Configure grid/block dimensions and shared memory
- `launch()` - Execute kernel
- `EventOptions` - GPU timing configuration

###### From CuPy:

- `cp.asarray()` - Transfer data to GPU
- `cp.zeros_like()` - Allocate GPU arrays

##### Requirements

###### Hardware:

- NVIDIA GPU with CUDA support

###### Software:

- CUDA Toolkit 13.0 or newer
- Python 3.10 or newer
- See `requirements.txt` for Python packages

##### Installation

```bash
pip install -r requirements.txt
```

##### How to Run

```bash
python blockwiseSum.py
```

##### Expected Output

```
Device: <Your GPU>
Compute Capability: sm_XX
Array size: 1,048,576 elements

Simple indexing: Test PASSED
Strided loop:    Test PASSED
Block-wise sum:  Test PASSED

Kernel time: X.XXX ms, Bandwidth: XXX.X GB/s

Done
```

##### Files

- `blockwiseSum.py` - Python implementation with CUDA kernels
- `README.md` - This file
- `requirements.txt` - Sample dependencies

##### See Also

- [cuda.core Documentation](https://nvidia.github.io/cuda-python/cuda-core/latest/)
- [CUDA Shared Memory](https://docs.nvidia.com/cuda/cuda-c-programming-guide/index.html#shared-memory)
- [CuPy Documentation](https://docs.cupy.dev/)


</details>

<br>

### cudaComputeLambdas

> #### On this box
>
> **Command**
> ```bash
> cd $CUDA_SAMPLES/python/2_CoreConcepts/cudaComputeLambdas
> source $VENVS/venv-extras/bin/activate      # isolated: base + cuda-cccl, nvtx, numba-cuda, torch, mpi4py
> python cudaComputeLambdas.py
> ```
>
> **Result** — All OK — `reduce_into` summed 1..10 to 55, `unary_transform` and a predicated `inclusive_scan` both matched references.
>
> *Wall time: 5.7 s*
>
> **Notes** — Python lambdas compiled into device code. Needs `cuda-cccl[cu13]`, which is not in the base requirements — run from `$VENVS/venv-extras`.

<details>
<summary><b>Full README — cudaComputeLambdas</b></summary>

#### cudaComputeLambdas (Python)

##### Description

This sample demonstrates how **cuda.compute** (from the
`cuda-cccl` package) accepts plain Python callables, including
lambdas, as the operators that drive device-wide reductions,
transforms, and scans. Internally `cuda.compute` JIT-compiles the
callable through Numba for the GPU, so you can iterate on the
operator in pure Python and still get a fused device-wide kernel.

The sample exercises three algorithm families:

1. `cuda.compute.reduce_into` - sum via `lambda a, b: a + b`.
2. `cuda.compute.unary_transform` - elementwise `y = x*x + 1` via a
   lambda.
3. `cuda.compute.inclusive_scan` - prefix sum over only the even
   values, driven by a regular Python function as the binary
   operator.

##### What You'll Learn

- Passing a Python `lambda` directly as the operator to a cuda.compute
  device algorithm
- Using a regular Python `def` function for the same purpose when the
  op is non-trivial
- The three core algorithm families in cuda.compute: reductions,
  transforms, and scans
- How cuda.compute auto-compiles the op to LTO-IR via Numba

##### Key Libraries

- [`cuda.compute`](https://nvidia.github.io/cccl/python.html) (from the `cuda-cccl` package) - device algorithms and JIT-compiled Python ops
- [`cuda.core`](https://nvidia.github.io/cuda-python/cuda-core/latest/) - device setup
- `cupy` - device buffers
- `numpy` - scalar init values and host-side verification

##### Key APIs

###### From `cuda.compute`

- `cuda.compute.reduce_into(d_in, d_out, num_items, op, h_init)` - device-wide reduction
- `cuda.compute.unary_transform(d_in, d_out, num_items, op)` - elementwise unary transform
- `cuda.compute.inclusive_scan(d_in, d_out, op, init_value, num_items)` - inclusive prefix scan

###### From `cuda_samples_utils`

- `print_gpu_info()` - print device name and compute capability

##### Requirements

###### Hardware

- NVIDIA GPU with Compute Capability 7.0 or higher

###### Software

- CUDA Toolkit 13.0 or newer (cuda.compute compiles ops to LTO-IR via
  Numba, which needs the toolkit's `nvvm` and `libdevice`).
- Python 3.10 or newer
- `cuda-cccl` (>=1.0.0)
- `cuda-core` (>=1.0.0)
- `cupy-cuda13x` (>=14.0.0)
- `numba-cuda` (pulled in transitively by `cuda-cccl`)

If the CUDA toolkit is not on your `PATH`, set `CUDA_HOME` so Numba
can locate `libdevice`:

```bash
export CUDA_HOME=/usr/local/cuda
```

##### Installation

Install the required packages from `requirements.txt`:

```bash
cd $CUDA_SAMPLES/python/2_CoreConcepts/cudaComputeLambdas
pip install -r requirements.txt
```

The `requirements.txt` installs:

- `cuda-cccl` (>=1.0.0) - ships the `cuda.compute` module
- `cuda-core` (>=1.0.0)
- `cupy-cuda13x` (>=14.0.0)
- `numpy` (>=1.24.0)

##### How to Run

###### Basic usage

```bash
cd $CUDA_SAMPLES/python/2_CoreConcepts/cudaComputeLambdas
python cudaComputeLambdas.py
```

###### With custom parameters

```bash
python cudaComputeLambdas.py --device 1
```

##### Expected Output

```
Device: <Your GPU Name>
Compute Capability: <X.Y>

reduce_into(lambda a,b: a+b) over 1..10 -> 55 (expected 55)  OK

unary_transform(lambda x: x*x + 1):
  got      = [1, 2, 5, 10, 17, 26, 37, 50]
  expected = [1, 2, 5, 10, 17, 26, 37, 50]  OK

inclusive_scan(add-evens-only) over [1,2,3,4,5,6]:
  got      = [0, 2, 2, 6, 6, 12]
  expected = [0, 2, 2, 6, 6, 12]  OK

Done
```

**Note:** Device name and compute capability will vary based on your GPU.

##### Files

- `cudaComputeLambdas.py` - Python implementation
- `README.md` - This file
- `requirements.txt` - Sample dependencies
- `../../Utilities/cuda_samples_utils.py` - Common utilities (imported by this sample)


</details>

<br>

### cudaGraphs

> #### On this box
>
> **Command**
> ```bash
> cd $CUDA_SAMPLES/python/2_CoreConcepts/cudaGraphs
> python cudaGraphs.py
> ```
>
> **Result** — Individual launches 7.81 us/iter vs graph replay 4.10 us/iter = **1.91x**. Replay on updated buffers verified.
>
> *Wall time: 0.8 s*
>
> **Notes** — A near-2x win purely from removing launch overhead. This is the single most transferable trick for small-kernel AI workloads — it is the same mechanism behind CUDA-graph capture in PyTorch inference.

<details>
<summary><b>Full README — cudaGraphs</b></summary>

#### cudaGraphs (Python)

##### Description

This sample demonstrates how to capture a multi-stage kernel pipeline as a
CUDA graph with `cuda.core` and replay it with a single driver call.

The sample runs a three-stage elementwise pipeline
`r3 = (a + b) * c - a` in two modes:

1. **Individual launches** - one `launch(stream, ...)` per stage, repeated
   for every iteration of the pipeline.
2. **CUDA graph replay** - the same three launches are recorded into a
   `Graph` once and replayed with `graph.launch(stream)` on each
   iteration.

Both paths are timed over N iterations and their results are verified
against a reference computation. The sample also re-launches the graph
after mutating the input buffers to show that the graph captures
pointers (not data), so the same graph can process new inputs without
rebuilding.

##### What You'll Learn

- Creating a `GraphBuilder` from a stream with `stream.create_graph_builder()`
- Capturing launches with `begin_building()` and `end_building()`
- Completing a graph with `builder.complete()` and uploading it to a stream
- Replaying the graph with `graph.launch(stream)`
- Measuring the launch-overhead savings for small kernels
- Re-running the same graph against updated input data

##### Key Libraries

- [`cuda.core`](https://nvidia.github.io/cuda-python/cuda-core/latest/) - Pythonic access to CUDA runtime, programs, and graphs
- `cupy` - input buffers and result verification
- `numpy` - scalar kernel arguments

##### Key APIs

###### From `cuda.core`

- `Stream.create_graph_builder()` - obtain a `GraphBuilder`
- `GraphBuilder.begin_building()` / `end_building()` - begin and finish recording launches issued against the builder
- `GraphBuilder.complete()` - produce an executable `Graph`
- `Graph.upload(stream)` - upload the graph structure to the device
- `Graph.launch(stream)` - replay the entire graph
- `launch(graph_builder, config, kernel, ...)` - record a kernel launch into the graph being built

###### From `cuda_samples_utils`

- `print_gpu_info()` - print device name and compute capability

##### Requirements

###### Hardware

- NVIDIA GPU with Compute Capability 7.0 or higher
- Minimum GPU memory: 512 MB

###### Software

- CUDA Toolkit 13.0 or newer (matches `cuda-python` 13.x)
- Python 3.10 or newer
- `cuda-python` (>=13.0.0)
- `cuda-core` (>=1.0.0)
- `cupy-cuda13x` (>=14.0.0)

##### Installation

Install the required packages from `requirements.txt`:

```bash
cd $CUDA_SAMPLES/python/2_CoreConcepts/cudaGraphs
pip install -r requirements.txt
```

The `requirements.txt` installs:

- `cuda-python` (>=13.0.0)
- `cuda-core` (>=1.0.0)
- `cupy-cuda13x` (>=14.0.0)

##### How to Run

###### Basic usage

```bash
cd $CUDA_SAMPLES/python/2_CoreConcepts/cudaGraphs
python cudaGraphs.py
```

###### With custom parameters

```bash
# Larger vectors and more iterations
python cudaGraphs.py --elements 4096 --iters 2000

# Use a specific GPU
python cudaGraphs.py --device 1
```

Short vectors exaggerate the launch-overhead savings; larger vectors
will show the two approaches converging because per-launch overhead
becomes negligible next to kernel runtime.

##### Expected Output

Speedup numbers vary with GPU and host CPU.

```
Device: <Your GPU Name>
Compute Capability: <X.Y>

Individual launches: 1000 iters in 0.0085s  (8.49 us/iter)

Building CUDA graph...
Graph replay:       1000 iters in 0.0034s  (3.41 us/iter)
Graph speedup: 2.49x

Graph replay on updated data verified (same graph, new buffer contents)

Done
```

**Note:** Device name, compute capability, and speedup will vary based on
your GPU and host CPU.

##### Files

- `cudaGraphs.py` - Python implementation using `cuda.core` CUDA graphs
- `README.md` - This file
- `requirements.txt` - Sample dependencies
- `../../Utilities/cuda_samples_utils.py` - Common utilities (imported by this sample)

##### See Also

- [CUDA Python Documentation](https://nvidia.github.io/cuda-python/)
- [`cuda.core` graphs API](https://nvidia.github.io/cuda-python/cuda-core/latest/api.html#cuda-graphs)
- Upstream `cuda.core` example: [`cuda_graphs.py`](https://github.com/NVIDIA/cuda-python/blob/main/cuda_core/examples/cuda_graphs.py)
- [CUDA Graphs programming guide](https://docs.nvidia.com/cuda/cuda-c-programming-guide/index.html#cuda-graphs)


</details>

<br>

### fftSignalAnalysis

> #### On this box
>
> **Command**
> ```bash
> cd $CUDA_SAMPLES/python/2_CoreConcepts/fftSignalAnalysis
> python fftSignalAnalysis.py
> ```
>
> **Result** — Test PASSED. GPU FFT matched CPU; all five injected tones (440/880/1320/2000/5000 Hz) detected.
>
> *Wall time: 1.3 s*
>
> **Notes** — Uses cuFFT through CuPy. Good template for any spectral preprocessing in an audio ML pipeline.

<details>
<summary><b>Full README — fftSignalAnalysis</b></summary>

#### Sample: FFT Signal Analysis (Python)

##### Description

Analyze signal frequencies using Fast Fourier Transform (FFT) on the GPU. This sample demonstrates CuPy's cuFFT for GPU-accelerated frequency analysis: generating composite signals, computing magnitude spectrum, detecting dominant frequencies via peak detection, and comparing GPU vs CPU FFT performance.

##### What You'll Learn

- Using CuPy's `cp.fft.rfft()` for real-to-complex FFT on GPU
- Computing magnitude spectrum from FFT results
- Peak detection to identify dominant frequencies
- Comparing GPU (cuFFT) vs CPU (NumPy) FFT performance
- Uses cuda.core APIs for device management and CUDA event timing

##### Key Concepts

- **FFT (Fast Fourier Transform)**: Efficiently computes the Discrete Fourier Transform
- **Magnitude Spectrum**: `|FFT(signal)| * 2 / N` gives amplitude at each frequency
- **rfft**: Real FFT - optimized for real-valued input signals
- **Peak Detection**: Finding local maxima to identify dominant frequencies

###### Stream Interop

This sample demonstrates CuPy integration with cuda.core streams:

```python
# Create stream with cuda.core
stream = device.create_stream()

# Use with CuPy operations
cp.cuda.Stream.from_external(stream).use()
```

##### Key APIs

###### From `cuda.core`:

- `Device` - Device management and context
- `EventOptions` - Configure events for GPU timing
- `stream.record()` - Record events for timing

###### From CuPy:

- `cp.fft.rfft()` - Real-to-complex FFT (GPU-accelerated via cuFFT)
- `cp.fft.rfftfreq()` - Generate frequency bins for rfft
- `cp.cuda.Stream.from_external()` - Interop with cuda.core streams

###### From NumPy:

- `np.fft.rfft()` - CPU FFT for comparison

##### Requirements

###### Hardware:

- NVIDIA GPU with CUDA support

###### Software:

- CUDA Toolkit 13.0 or newer
- Python 3.10 or newer
- See `requirements.txt` for Python packages

##### Installation

```bash
pip install -r requirements.txt
```

##### How to Run

```bash
python fftSignalAnalysis.py
```

##### Expected Output

```
============================================================
FFT Signal Analysis
============================================================

Device: <Your GPU>
Compute Capability: sm_XX

Signal Parameters:
  Samples: 1,048,576
  Sample Rate: 44,100 Hz
  ...

------------------------------------------------------------
GPU FFT (cuFFT)
------------------------------------------------------------
Time: X.XXX ms

Detected Frequencies:
     440.0 Hz (magnitude: X.XXXX)
     ...

------------------------------------------------------------
CPU FFT (NumPy)
------------------------------------------------------------
Time: XX.XXX ms

------------------------------------------------------------
PERFORMANCE SUMMARY
------------------------------------------------------------
GPU (cuFFT): X.XXX ms
CPU (NumPy): XX.XXX ms
Speedup: XXx

------------------------------------------------------------
VERIFICATION
------------------------------------------------------------
GPU vs CPU FFT magnitude: Test PASSED

Frequency Detection Accuracy:
     440 Hz: [OK]
     ...

Done
```

**Note:** Times and speedup vary by hardware.

##### Files

- `fftSignalAnalysis.py` - Main sample using cuda.core and CuPy
- `README.md` - This file
- `requirements.txt` - Dependencies

##### See Also

- [cuda.core Documentation](https://nvidia.github.io/cuda-python/cuda-core/latest/)
- [CuPy FFT Documentation](https://docs.cupy.dev/en/stable/reference/fft.html)
- [cuFFT Documentation](https://docs.nvidia.com/cuda/cufft/)


</details>

<br>

### greenContext

> #### On this box
>
> **Command**
> ```bash
> cd $CUDA_SAMPLES/python/2_CoreConcepts/greenContext
> python greenContext.py --split 8,8
> ```
>
> **Result** — PASS **only with an explicit split**. Critical-kernel latency 26.614 ms (baseline) -> 4.526 ms (green ctx) = **5.88x**. Baseline wasted ~26.02 ms waiting for SMs.
>
> *Wall time: 0.4 s*
>
> **Notes** — **Gotcha:** the default auto-split fails on this GPU with `could not find an SM split that the driver accepts (total SMs=70, min_partition_size=8)`. Explicit large splits also fail — `56,8`, `48,16` and `32,32` all return `CUDA_ERROR_INVALID_RESOURCE_CONFIGURATION`. Only the small **`--split 8,8`** was accepted. 70 SMs does not partition cleanly on this consumer Blackwell part; the driver enforces TPC-alignment rules beyond the advertised `min_partition_size`.

<details>
<summary><b>Full README — greenContext</b></summary>

#### greenContext (Python)

##### Description

This sample demonstrates how to use **green contexts** with
`cuda.core` to statically partition a GPU's streaming multiprocessors
(SMs) so that independent kernels can run on dedicated subsets of the
device.

This examples takes A long-running kernel that fills the GPU's SMs,
and a short but latency-sensitive "critical" kernel is launched shortly after.
Without green contexts, the critical kernel must wait for SMs to
free up. With green contexts, the GPU's SMs are partitioned so the
critical kernel has its own dedicated SMs and can start immediately.

Three timed scenarios are compared:

1. **Reference**: the critical kernel alone on the primary context,
   with no competing work. Establishes the pure compute time of the
   critical kernel when every SM on the device is available to it.
2. **Baseline**: both kernels run on the device's primary context,
   on two non-blocking streams that contend for all SMs.
3. **Green contexts**: the SMs are split into two disjoint groups
   (e.g. 112 + 16). Each kernel runs on a stream that belongs to its
   own green context, so the critical kernel never waits for SMs
   held by the long-running kernel.

The headline metric is the total wall time of the critical kernel
from launch to completion. In the baseline it is dominated by time
spent waiting behind the long-running kernel. With green contexts it
reflects the kernel's own compute time on its (smaller) SM
partition. The reference row lets you separate those two effects:

- `baseline - reference` is roughly the time the critical kernel
  spent waiting for SMs in the baseline run (the cost that green
  contexts eliminate).
- `green / reference` is the compute slowdown caused by running on
  a smaller SM partition (the cost that green contexts introduce).

##### What You'll Learn

- Querying a device's SM resources via `Device.resources.sm` and
  reading `sm_count`, `min_partition_size`, `coscheduled_alignment`
- Splitting an `SMResource` into disjoint partitions with
  `sm.split(SMResourceOptions(count=(A, B)))`
- Creating a green context from an SM partition via
  `Device.create_context(ContextOptions(resources=[group]))`
- Creating a non-blocking stream on a green context with
  `ctx.create_stream()`
- Using CUDA events with timing enabled to measure kernel wall time
  across streams
- Cleaning up green contexts safely with `ctx.close()`

##### Key Libraries

- [`cuda.core`](https://nvidia.github.io/cuda-python/cuda-core/latest/) - device management, SM partitioning, green contexts, compilation, and launching
- `numpy` - scalar kernel arguments

##### Key APIs

###### From `cuda.core`

- `Device.resources.sm` - the device's SM-type device resource
- `SMResource.split(SMResourceOptions(count=(A, B)))` - partition SMs
  into disjoint groups (plus an optional remainder)
- `Device.create_context(ContextOptions(resources=[sm_group]))` -
  create a green context provisioned with a specific SM partition
- `Context.is_green` / `Context.resources` - introspect a green
  context
- `Context.create_stream()` - create a non-blocking stream that is
  tied to the green context's SM partition
- `Context.close()` - destroy a green context (must not be the
  thread's current context when closed)
- `Device.create_event(EventOptions(timing_enabled=True))` /
  `Stream.record(event)` / `event2 - event1` - measure elapsed time
  in milliseconds between two events on the device
- `Program(..., ProgramOptions(std="c++17", arch=f"sm_{device.arch}"))`
  / `program.compile("cubin", name_expressions=(...))` - compile the
  delay and critical kernels in one TU
- `launch(stream, LaunchConfig(grid=..., block=...), kernel, ...)` -
  submit a kernel on a specific stream

##### Requirements

###### Hardware

- Any NVIDIA GPU supported by green contexts.
- Green-context SM partitioning is designed for larger server GPUs
  (H100, H200, B200, ...) but works on any supported GPU as long as
  the SM count is large enough to split meaningfully.

###### Software

- NVIDIA driver >= 12.4
- CUDA Toolkit 13.0 or newer.
- Python 3.10 or newer.
- `cuda-core` (`>=1.0.0`)

##### Installation

Install the required packages from `requirements.txt`:

```bash
cd $CUDA_SAMPLES/python/2_CoreConcepts/greenContext
pip install -r requirements.txt
```

##### How to Run

###### Basic usage

The auto-default split reserves a small partition (~16 SMs) for the
critical kernel and gives the rest to the long-running kernel. The
exact sizes are chosen by probing the driver with a dry-run `sm.split`,
escalating the alignment granularity in powers of two until the driver
accepts the pair. This handles architectures where the driver enforces
stricter alignment (e.g. TPC/GPC-pair alignment on Blackwell) than the
reported `min_partition_size`. When that happens the sample prints a
`Note:` line with the granularity it landed on.

```bash
cd $CUDA_SAMPLES/python/2_CoreConcepts/greenContext
python greenContext.py
```

###### Match the CUDA programming guide example (112 + 16)

```bash
python greenContext.py --split 112,16
```

###### Tune the workload

```bash
# Longer long-running kernel, larger host launch gap
python greenContext.py --delay-us 3000 --launch-gap-ms 2.0

# Smaller/lighter critical kernel so its own compute time is negligible
python greenContext.py --critical-n 65536 --critical-iters 128

# Symmetric split: maximum SMs for the critical kernel, long kernel is
# roughly 2x slower but the critical kernel runs close to its reference time.
python greenContext.py --split 64,64

# Use a specific GPU
python greenContext.py --device 1
```

###### All options

```
--device           CUDA device ID (default: 0)
--split            SM split as 'LONG,CRITICAL', e.g. '112,16'.
                   Each side must be a multiple of the device's
                   min_partition_size, and the driver may enforce additional
                   architecture-specific alignment (e.g. TPC/partition-grid
                   alignment on Blackwell). Omit --split to auto-select a
                   driver-accepted split.
--delay-us         Per-block busy-wait of the delay kernel, in us (default: 2000)
--delay-waves      Number of waves of the delay kernel on the long
                   partition. Drives the default --delay-blocks (default: 16)
--delay-blocks     Number of blocks for the delay kernel. Overrides
                   --delay-waves if set.
                   (default: --delay-waves * device SM count)
--critical-n       Work size of the critical kernel (default: 4194304)
--critical-iters   Inner math-loop iterations inside the critical kernel.
                   Higher values make the critical kernel's own compute
                   time more substantial relative to its wait time
                   (default: 1024)
--launch-gap-ms    Host delay between launching the long and critical
                   kernels (default: 1.0 ms)
```

##### Expected Output

The output depends on the GPU and the number of SMs.
On an RTX 4090 (128 SMs) with the default auto split:

```
[Green Context Sample using CUDA Core API]
Device: NVIDIA GeForce RTX 4090
Compute Capability: sm_89
Total SMs:                 128
Min. SM partition size:    2
SM co-scheduled alignment: 2
SM split (long/critical):  112 / 16
Workload parameters:
  delay kernel: 2048 blocks, 2000 us/block (~32.0 ms on 128 SMs)
  critical kernel: 4194304 elements, 1024 inner iterations
  host launch gap: 1.0 ms

Compiling kernels ...
Running reference scenario (critical kernel alone) ...
Running baseline scenario (primary context) ...
Running green context scenario ...

scenario                             SMs (long/crit)     long (ms)   crit total (ms)   crit offset (ms)
-------------------------------------------------------------------------------------------------------
crit alone (primary ctx)                       -/128             -             0.425                  -
baseline (primary ctx)                       128/128        32.034            30.024              1.090
green ctx (112+16 SMs)                        112/16        38.017             2.696              1.075

long (ms)        : wall time of the delay kernel
crit total (ms)  : launch-to-complete wall time of the critical kernel
crit offset (ms) : when the critical stream started, relative to the long stream start

Critical-kernel latency speedup (baseline vs green ctx): 11.14x
Green-ctx compute cost vs unconstrained (crit alone):    6.34x
Baseline time spent waiting for SMs (not computing):     ~29.60 ms

Done
```

**What to look for:**

- The critical kernel alone (reference row) takes only a fraction of
  a millisecond; almost all of the baseline's `crit total` is time
  spent queued waiting for SMs, not compute.
- The **critical kernel's wall time drops sharply** in the
  green-context scenario (from ~30 ms to a few ms in the example
  above) because it no longer waits for SMs held by the long-running
  kernel.
- The **long-running kernel's duration may increase** proportional
  to the reduction in SMs available to it (128 -> 112 SMs ~= 14%
  slower; 128 -> 64 SMs ~= 2x slower). This is an expected tradeoff:
  you reserve SMs for a critical kernel by taking them away from the
  background workload.
- The **compute cost** ratio (`green / reference`) shows how close
  the critical kernel is to ideal linear scaling with its SM count.
  A 112/16 split gives the critical kernel only 12.5% of the SMs and
  costs it roughly 6-7x its reference time; a 64/64 split gives it
  half the SMs and costs roughly 1.5-2x.
- The `crit offset` column is approximately `--launch-gap-ms` in
  both full scenarios; it confirms the host launched the critical
  kernel the same amount of time after the long kernel in both runs.

Exact timings vary with GPU model, driver version, clock state, and
other concurrent GPU work.

##### Files

- `greenContext.py` - Python implementation using `cuda.core` green-context APIs
- `README.md` - This file
- `requirements.txt` - Sample dependencies

##### See Also

- [CUDA Python Documentation](https://nvidia.github.io/cuda-python/)
- [Green Contexts in the CUDA C++ Programming Guide](https://docs.nvidia.com/cuda/cuda-c-programming-guide/index.html#green-contexts)
- [`cuda.core` green-context test suite](https://github.com/NVIDIA/cuda-python/blob/main/cuda_core/tests/test_green_context.py) - the authoritative API reference


</details>

<br>

### jitLtoLinking

> #### On this box
>
> **Command**
> ```bash
> cd $CUDA_SAMPLES/python/2_CoreConcepts/jitLtoLinking
> python jitLtoLinking.py
> ```
>
> **Result** — Both paths verified against NumPy — PTX linking and LTO linking produced matching results.
>
> *Wall time: 0.6 s*
>
> **Notes** — LTO across separately-compiled device modules. Relevant when you ship precompiled kernels and want cross-module inlining.

<details>
<summary><b>Full README — jitLtoLinking</b></summary>

#### JIT Compilation and Link-Time Optimization (Python)

##### Description

This sample demonstrates how to build a kernel out of two independently
compiled translation units and link them at runtime with
`cuda.core.Linker`. This is the pattern a library would use to accept
user-supplied device code as a plug-in without recompiling its own
kernels from scratch.

The sample runs the same program in two linking modes:

1. **PTX linking** - each module is compiled with
   `ProgramOptions(relocatable_device_code=True)` down to PTX, and the
   `Linker` emits a final cubin. The two modules stay independently
   compiled (no cross-module inlining).
2. **Link-Time Optimization (LTO)** - each module is compiled with
   `ProgramOptions(link_time_optimization=True)` down to LTO IR, and the
   `Linker` is configured with `LinkerOptions(link_time_optimization=True)`
   so the optimizer runs again across both modules, typically matching
   the code generation of a single-source build.

The "main" kernel `apply_transform` calls a `user_transform` device
function that lives in a separate source string, and the results of both
linking modes are verified against a NumPy reference.

##### What You'll Learn

- Compiling multiple `Program` objects into PTX or LTO IR
- Linking independent object codes into a single cubin with `Linker`
- Choosing between `relocatable_device_code` and `link_time_optimization`
- How a library's main kernel can call into user-supplied device code
- When to prefer LTO over plain PTX linking

##### Key Libraries

- [`cuda.core`](https://nvidia.github.io/cuda-python/cuda-core/latest/) - Pythonic access to CUDA runtime, programs, and the JIT linker
- `cupy` - input and output buffers on the GPU
- `numpy` - reference computation on the host

##### Key APIs

###### From `cuda.core`

- `ProgramOptions(relocatable_device_code=True)` + `Program.compile("ptx")` - produce relocatable PTX
- `ProgramOptions(link_time_optimization=True)` + `Program.compile("ltoir")` - produce LTO IR
- `Linker(*object_codes, options=LinkerOptions(...))` - create a JIT linker over multiple object codes
- `LinkerOptions(link_time_optimization=True)` - opt into LTO during linking
- `Linker.link("cubin")` - produce a loadable module
- `ObjectCode.get_kernel(name)` - fetch a kernel from the linked module

###### From `cuda_samples_utils`

- `print_gpu_info()` - print device name and compute capability

##### Requirements

###### Hardware

- NVIDIA GPU with Compute Capability 7.0 or higher

###### Software

- CUDA Toolkit 13.0 or newer (matches `cuda-python` 13.x)
- Python 3.10 or newer
- `cuda-python` (>=13.0.0)
- `cuda-core` (>=1.0.0)
- `cupy-cuda13x` (>=14.0.0)

##### Installation

Install the required packages from `requirements.txt`:

```bash
cd $CUDA_SAMPLES/python/2_CoreConcepts/jitLtoLinking
pip install -r requirements.txt
```

The `requirements.txt` installs:

- `cuda-python` (>=13.0.0)
- `cuda-core` (>=1.0.0)
- `cupy-cuda13x` (>=14.0.0)

##### How to Run

###### Basic usage

```bash
cd $CUDA_SAMPLES/python/2_CoreConcepts/jitLtoLinking
python jitLtoLinking.py
```

###### With custom parameters

```bash
# Larger element count
python jitLtoLinking.py --elements 1048576

# Use a specific GPU
python jitLtoLinking.py --device 1
```

##### Expected Output

```
Device: <Your GPU Name>
Compute Capability: <X.Y>

[1] PTX linking (no LTO)
  [ptx] result verified against NumPy reference

[2] LTO linking (link-time optimization)
  [lto] result verified against NumPy reference

Both PTX and LTO linked kernels produced matching results. Done
```

**Note:** Device name and compute capability will vary based on your GPU.

##### Files

- `jitLtoLinking.py` - Python implementation using `cuda.core.Linker`
- `README.md` - This file
- `requirements.txt` - Sample dependencies
- `../../Utilities/cuda_samples_utils.py` - Common utilities (imported by this sample)

##### See Also

- [CUDA Python Documentation](https://nvidia.github.io/cuda-python/)
- [`cuda.core` compilation API](https://nvidia.github.io/cuda-python/cuda-core/latest/api.html#cuda-compilation-toolchain)
- Upstream `cuda.core` example: [`jit_lto_fractal.py`](https://github.com/NVIDIA/cuda-python/blob/main/cuda_core/examples/jit_lto_fractal.py)
- [NVIDIA nvJitLink documentation](https://docs.nvidia.com/cuda/nvjitlink/index.html)


</details>

<br>

### launchConfigTuning

> #### On this box
>
> **Command**
> ```bash
> cd $CUDA_SAMPLES/python/2_CoreConcepts/launchConfigTuning
> python launchConfigTuning.py
> ```
>
> **Result** — Optimal **block_size=64** on this GPU, **2.36x** faster than the worst configuration tested.
>
> *Wall time: 1.5 s*
>
> **Notes** — Worth internalising: 64 threads/block beat 256 and 1024 here. The common '256 is a good default' advice costs you real performance on this part — always sweep.

<details>
<summary><b>Full README — launchConfigTuning</b></summary>

#### Sample: Launch Configuration Tuning (Python)

##### Description

Benchmark different CUDA kernel launch configurations to find the optimal block-size setting using `cuda.core` APIs. This sample demonstrates **performance tuning** by measuring execution time across various thread block sizes.

##### What You'll Learn

- Compiling CUDA kernels at runtime with `cuda.core.Program`
- Launching kernels with different `LaunchConfig` settings
- Benchmarking kernel performance with precise timing
- Understanding how thread block size affects performance
- Tuning for memory-bound vs compute-bound kernels

##### Key Concepts

###### Launch Configuration with cuda.core

```python
# Configure kernel launch with specific thread block size
config = LaunchConfig(
    grid=(grid_size,),
    block=(block_size,),
    shmem_size=shared_memory_bytes
)

# Launch kernel
launch(stream, config, kernel, *args)
stream.sync()
```

###### Thread Block Sizing

Thread block size significantly impacts performance due to:

| Factor | Impact |
|--------|--------|
| **Occupancy** | More active warps can hide memory latency |
| **Registers** | More threads/block = fewer registers/thread |
| **Shared Memory** | Divided among blocks on each SM |
| **Warp Efficiency** | Block size should be multiple of 32 |

###### Benchmarking Approach

```python
# Use CUDA events for accurate GPU timing (not CPU wall-clock)
start_event = device.create_event(options=EventOptions(enable_timing=True))
end_event = device.create_event(options=EventOptions(enable_timing=True))

stream.record(start_event)
for _ in range(n_iterations):
    launch(stream, config, kernel, *args)
stream.record(end_event)
end_event.sync()
elapsed_ms = (end_event - start_event) / n_iterations
```

##### Key APIs

###### From `cuda.core`:

- `Device` - CUDA device management
- `Program` - Runtime kernel compilation (NVRTC)
- `ProgramOptions` - Compilation options (architecture target)
- `LaunchConfig` - Kernel launch configuration (grid/block dimensions)
- `launch` - Execute compiled kernel (accepts Buffer objects directly)
- `EventOptions` - GPU timing with CUDA events
- `ManagedMemoryResource` - Device-preferred unified memory
- `ManagedMemoryResourceOptions` - Set preferred_location for representative benchmarks

###### From `numpy`:

- `np.from_dlpack()` - Zero-copy view of GPU buffers via DLPack

###### Benchmarked Kernels:

- **vector_add** - Simple memory-bound kernel (C = A + B) - low sensitivity to block size
- **reduce_sum** - Shared memory reduction - high sensitivity to block size

##### Requirements

###### Hardware:

- NVIDIA GPU with CUDA support
- Minimum GPU memory: 512 MB

###### Software:

- CUDA Toolkit 13.0 or newer
- Python 3.10 or newer
- See `requirements.txt` for Python packages

###### Platform Support:

The benchmark loops in this sample read kernel results back from
`ManagedMemoryResource` allocations between launches, which requires the
device property `concurrent_managed_access=True`. This is only supported on
Linux with HMM (Pascal and newer). On Windows (WDDM/MCDM/TCC) the property
is `False`, so the sample exits early with a waive message and exit code
`2`.

##### Installation

```bash
pip install -r requirements.txt
```

##### How to Run

```bash
python launchConfigTuning.py
```

##### Expected Output

```
============================================================
Launch Configuration Tuning (cuda.core)
Finding the Best Block Size for Your Kernel
============================================================

Device: <Your GPU Name>
Compute Capability: X.X

Compiling CUDA kernels with cuda.core.Program...
  Target architecture: sm_XX
  [OK] vector_add kernel compiled
  [OK] reduce_sum kernel compiled

============================================================
VECTOR ADDITION - Launch Configuration Tuning
============================================================

Problem size: 10,000,000 elements
Kernel: vector_add (C = A + B)

Testing thread configurations: [32, 64, 128, 256, 512, 1024]
------------------------------------------------------------
Block Size:   32 | Blocks: 312500 | Time: X.XXXX ± X.XXXX ms
Block Size:   64 | Blocks: 156250 | Time: X.XXXX ± X.XXXX ms
...
------------------------------------------------------------

[OK] OPTIMAL: block_size=XXX (X.XXXX ms)
[FAIL] WORST: block_size=XXX (X.XXXX ms)
  Speedup: X.XXx

[OK] Results verified correct!

...

============================================================
SAMPLE COMPLETE
============================================================

Key Takeaway: The optimal thread configuration depends on your
specific kernel characteristics. Always benchmark to find the best!
```

##### Tuning Guidelines

###### Start Here
- **128-256 threads/block** is a good starting point for most kernels
- Always use **multiples of 32** (warp size)

###### Memory-Bound Kernels
- Less sensitive to thread configuration
- Focus on memory access patterns
- Higher thread counts help hide latency

###### Compute-Bound Kernels
- More sensitive to thread configuration
- Watch for register pressure at high thread counts
- Profile with Nsight Compute

###### Reduction Kernels
- Block size affects shared memory usage
- Power-of-2 sizes simplify reduction logic
- Often 256-512 threads works well

##### Files

- `launchConfigTuning.py` - Python implementation using cuda.core
- `README.md` - This file
- `requirements.txt` - Sample dependencies

##### See Also

- [cuda.core Documentation](https://nvidia.github.io/cuda-python/cuda-core/latest/)
- [cuda.core.LaunchConfig](https://nvidia.github.io/cuda-python/cuda-core/latest/generated/cuda.core.LaunchConfig.html)
- [CUDA Occupancy Calculator](https://docs.nvidia.com/cuda/cuda-occupancy-calculator/)
- [CUDA Best Practices Guide - Execution Configuration](https://docs.nvidia.com/cuda/cuda-c-best-practices-guide/index.html#execution-configuration-optimizations)
- [Nsight Compute Profiler](https://developer.nvidia.com/nsight-compute)


</details>

<br>

### matrixMulSharedMem

> #### On this box
>
> **Command**
> ```bash
> cd $CUDA_SAMPLES/python/2_CoreConcepts/matrixMulSharedMem
> source $VENVS/venv-nvmath/bin/activate      # isolated: cuda-core==0.7.0 + nvmath-python==0.9.0
> python matrixMulSharedMem.py
> ```
>
> **Result** — Both PASSED. nvmath/cuBLASLt **32,338 GFLOPS** (0.066 ms) vs hand-written tiled shared-memory kernel **4,210 GFLOPS** (0.510 ms) — the library is **7.7x** faster.
>
> *Wall time: 0.8 s*
>
> **Notes** — **Needs its own venv** (`cuda-core==0.7.0`, `nvmath-python==0.9.0`) — those pins are incompatible with the working venv's `cuda-core 1.0.1`. The lesson in the numbers: a well-written tiled kernel still loses to cuBLASLt by ~8x. Write custom kernels for what libraries do not cover, not for GEMM.

<details>
<summary><b>Full README — matrixMulSharedMem</b></summary>

#### Matrix Multiplication with Shared Memory (GEMM)

> **Known issue — version-pinned sample.** Unlike the other samples in this
> repository, this sample is pinned to `cuda-core==0.7.0` and
> `nvmath-python[cu13]==0.9.0`. The reason is that nvmath-python 0.9.0
> still uses `cuda-core`'s pre-1.0 API name `EventOptions(enable_timing=...)`
> in its own internals, which `cuda-core>=1.0` no longer accepts.
>
> If you install this sample's `requirements.txt` into the same environment
> as the other samples, pip will downgrade `cuda-core` and the other
> samples (which use the 1.0 API) will stop working. The recommended
> workflow is one of:
>
> - Install this sample's requirements in a **dedicated virtual
>   environment**, or
> - Re-run the other samples' `pip install -r requirements.txt` afterwards
>   to upgrade `cuda-core` back to 1.0.
>
> This sample will be re-aligned with the rest of the repository
> (`cuda-core>=1.0.0`) once nvmath-python ships a release that targets
> cuda-core's 1.0 naming audit.

Demonstrates efficient matrix multiplication using nvmath-python APIs and custom CUDA kernels with tiling, shared memory, and loop unrolling.

##### Overview

- Uses nvmath.linalg.advanced.Matmul for high-performance GEMM via cuBLASLt
- Compares with custom CUDA kernel using tiling and shared memory
- Shows how tiling reduces global memory bandwidth requirements
- Demonstrates shared memory for data reuse within thread blocks
- Uses loop unrolling to improve instruction-level parallelism

##### What You'll Learn

- How to use nvmath stateful API for optimized matrix multiplication
- How to tile matrix operations for better cache locality
- Using shared memory to reduce redundant global memory accesses
- Loop unrolling techniques for GPU kernels
- Benchmarking and comparing kernel performance

##### Key Libraries

- `nvmath-python` - NVIDIA math library with cuBLASLt access
- `cuda.core` - Modern CUDA Python API for custom kernel compilation
- `cupy` - GPU array library for Python

##### Key APIs

###### From `nvmath.linalg.advanced`:

- `Matmul()` - Stateful matrix multiplication with planning and execution phases
- `MatmulComputeType` - Compute type options for mixed-precision

###### From `cuda.core`:

- `Device()` - CUDA device management and properties
- `Program()` - Runtime kernel compilation (NVRTC)
- `LaunchConfig()` - Kernel launch configuration (grid/block dimensions)
- `launch()` - Kernel execution on a stream
- `Stream.record_event()` / `Event.elapsed_time()` - GPU timing

##### Requirements

###### Hardware:

- NVIDIA GPU with Compute Capability 7.0 or higher
- Minimum GPU memory: 256 MB (for 1024×1024 matrices)

###### Software:

- CUDA Toolkit 13.0 or newer
- Python 3.10 or newer
- See requirements.txt for package dependencies

##### Installation

```bash
cd $CUDA_SAMPLES/python/2_CoreConcepts/matrixMulSharedMem
python -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

##### How to Run

```bash
python matrixMulSharedMem.py
```

##### Expected Output

```
======================================================================
Matrix Multiplication with Shared Memory (GEMM)
Using nvmath and cuda.core APIs
======================================================================

Device: NVIDIA GeForce RTX 4090
Compute Capability: sm_89

Custom kernel compiled [OK]

Matrix dimensions: A(1024x1024) × B(1024x1024) = C(1024x1024)
Custom kernel tile size: 16x16

----------------------------------------------------------------------
NVMATH MATMUL (cuBLASLt)
----------------------------------------------------------------------
Using nvmath.linalg.advanced.Matmul stateful API
Average time: X.XXX ms
Performance: XXXX.XX GFLOPS

----------------------------------------------------------------------
CUSTOM KERNEL (Tiled + Shared Memory + Loop Unrolling)
----------------------------------------------------------------------
Grid: (64, 64), Block: (16, 16)
Average time: X.XXX ms
Performance: XXX.XX GFLOPS

----------------------------------------------------------------------
VERIFICATION
----------------------------------------------------------------------
nvmath         : PASSED (max error: X.XXe-XX)
Custom kernel  : PASSED (max error: X.XXe-XX)

======================================================================
PERFORMANCE SUMMARY
======================================================================
Implementation                 Time (ms)    GFLOPS
----------------------------------------------------------------------
nvmath (cuBLASLt)              X.XXX        XXXX.XX
Custom (shared mem + unroll)   X.XXX        XXX.XX
```

##### Tiling Concept

```
     Matrix A (M×K)          Matrix B (K×N)          Matrix C (M×N)
    ┌───────────────┐       ┌───────────────┐       ┌───────────────┐
    │ T00 │ T01 │...│       │ T00 │ T01 │...│       │     │     │   │
    ├─────┼─────┼───┤       ├─────┼─────┼───┤       ├─────┼─────┼───┤
    │ T10 │ T11 │...│   ×   │ T10 │ T11 │...│   =   │     │ Cij │   │
    ├─────┼─────┼───┤       ├─────┼─────┼───┤       ├─────┼─────┼───┤
    │ ... │ ... │...│       │ ... │ ... │...│       │     │     │   │
    └───────────────┘       └───────────────┘       └───────────────┘

    Cij = Σ (A_tile_row × B_tile_col) for all tiles along K
```

##### nvmath Stateful API

```python
import nvmath.linalg.advanced as nvmath_advanced

# Create matrices (CuPy arrays)
A = cp.random.rand(m, k).astype(cp.float32)
B = cp.random.rand(k, n).astype(cp.float32)

# Use stateful API for fine-grained control
with nvmath_advanced.Matmul(A, B) as mm:
    mm.plan()           # Find optimal algorithm
    C = mm.execute()    # Execute computation
```

##### Memory Access Optimization (Custom Kernel)

| Implementation | Global Reads per C element | Reduction |
|---------------|---------------------------|-----------|
| Naive         | 2 × K                     | (baseline)|
| Tiled (16×16) | 2 × K / 16                | 16×       |

##### Files

- `matrixMulSharedMem.py` - Python implementation comparing nvmath vs custom kernel
- `README.md` - This file
- `requirements.txt` - Sample dependencies

##### See Also

- [nvmath-python Documentation](https://docs.nvidia.com/cuda/nvmath-python/)
- [CUDA Python Documentation](https://nvidia.github.io/cuda-python/)
- [cuda.core API Guide](https://nvidia.github.io/cuda-python/cuda-core/latest/)
- [CuPy Documentation](https://docs.cupy.dev/)


</details>

<br>

### memoryResources

> #### On this box
>
> **Command**
> ```bash
> cd $CUDA_SAMPLES/python/2_CoreConcepts/memoryResources
> python memoryResources.py
> ```
>
> **Result** — All three verified: pinned staging + device kernel + `copy_to`; ManagedMemoryResource with GPU writes visible through the host mapping; explicit DeviceMemoryResource.
>
> *Wall time: 0.6 s*
>
> **Notes** — The memory-resource abstraction is what you want for any allocator-aware AI code — it maps onto the same idea as PyTorch's caching allocator.

<details>
<summary><b>Full README — memoryResources</b></summary>

#### Sample: Memory Resources and Buffers (Python)

##### Description

This sample demonstrates the `cuda.core` memory management model: a
`MemoryResource` owns a pool of memory and hands out `Buffer` objects that
can be passed to kernels, copied between resources with
`Buffer.copy_to()`, and viewed as NumPy or CuPy arrays through DLPack. The
script exercises three common resources side-by-side:

1. **`DeviceMemoryResource`** - device-local GPU memory. Every `Device`
   exposes a default pool via `Device.memory_resource`, and applications
   can create additional pools explicitly.
2. **`PinnedMemoryResource`** - page-locked host memory, used here as the
   input and output staging buffers around a GPU kernel (the canonical
   pinned-H2D / compute / pinned-D2H pattern).
3. **`ManagedMemoryResource`** - unified memory that the driver migrates
   between host and device on demand; host views see the GPU's writes
   without an explicit copy.

The same `scale_and_bias` kernel runs on each resource and every result is
verified on the host.

##### What You'll Learn

- Creating and using `DeviceMemoryResource`, `PinnedMemoryResource`, and
  `ManagedMemoryResource`
- Allocating `Buffer` objects from a resource with a bound stream
- Copying between buffers across resources with `Buffer.copy_to()`
- Taking zero-copy NumPy or CuPy views of a `Buffer` via DLPack
- Releasing buffers with stream-ordered `close(stream)` semantics

##### Key Libraries

- [`cuda.core`](https://nvidia.github.io/cuda-python/cuda-core/latest/) - Pythonic access to CUDA runtime, programs, and memory resources
- `cupy` - GPU array views of device buffers
- `numpy` - host array views of pinned and managed buffers

##### Key APIs

###### From `cuda.core`

- `Device.memory_resource` - default memory pool attached to a device
- `DeviceMemoryResource`, `PinnedMemoryResource`, `ManagedMemoryResource` - allocate buffers of the corresponding memory kind
- `MemoryResource.allocate(nbytes, stream=...)` - returns a `Buffer`
- `Buffer.copy_to(dst_buffer, stream=...)` - async, stream-ordered copy
- `Buffer.close(stream)` - stream-ordered deallocation
- `Buffer` supports `__dlpack__` for zero-copy views

###### From CuPy and NumPy

- `cp.from_dlpack()` / `np.from_dlpack()` - zero-copy array view of a `Buffer`

###### From `cuda_samples_utils`

- `print_gpu_info()` - print device name and compute capability

##### Requirements

###### Hardware

- NVIDIA GPU with Compute Capability 7.0 or higher
- Managed memory support (most discrete GPUs)

###### Software

- CUDA Toolkit 13.0 or newer (matches `cuda-python` 13.x)
- Python 3.10 or newer
- `cuda-python` (>=13.0.0)
- `cuda-core` (>=1.0.0)
- `cupy-cuda13x` (>=14.0.0)

###### Platform Support

The `ManagedMemoryResource` demo in this sample exercises **concurrent host
access** to managed allocations while the GPU is active, which requires the
device property `concurrent_managed_access=True`. This is only supported on
Linux with HMM (Pascal and newer). On Windows (WDDM/MCDM/TCC) the property
is `False`, so the sample exits early with a waive message and exit code
`2`. The `DeviceMemoryResource` + `PinnedMemoryResource` demos in this
sample would still work on Windows on their own, but to keep the sample
self-contained the entire script waives when concurrent managed access is
unavailable.

##### Installation

Install the required packages from `requirements.txt`:

```bash
cd $CUDA_SAMPLES/python/2_CoreConcepts/memoryResources
pip install -r requirements.txt
```

The `requirements.txt` installs:

- `cuda-python` (>=13.0.0)
- `cuda-core` (>=1.0.0)
- `cupy-cuda13x` (>=14.0.0)

##### How to Run

###### Basic usage

```bash
cd $CUDA_SAMPLES/python/2_CoreConcepts/memoryResources
python memoryResources.py
```

###### With custom parameters

```bash
# Larger buffer size
python memoryResources.py --elements 1048576

# Use a specific GPU
python memoryResources.py --device 1
```

##### Expected Output

```
Device: <Your GPU Name>
Compute Capability: <X.Y>

[1] DeviceMemoryResource + PinnedMemoryResource (staging)
  Pinned staging, device kernel, and copy_to verified

[2] ManagedMemoryResource (unified memory)
  GPU writes observed directly through the host-visible mapping

[3] Explicit DeviceMemoryResource
  Explicit DeviceMemoryResource allocation verified

All memory resource demos passed.
```

**Note:** Device name and compute capability will vary based on your GPU.

##### Files

- `memoryResources.py` - Python implementation using `cuda.core` memory resources
- `README.md` - This file
- `requirements.txt` - Sample dependencies
- `../../Utilities/cuda_samples_utils.py` - Common utilities (imported by this sample)

##### See Also

- [CUDA Python Documentation](https://nvidia.github.io/cuda-python/)
- [`cuda.core` memory API](https://nvidia.github.io/cuda-python/cuda-core/latest/api.html#memory-management)
- Upstream `cuda.core` example: [`memory_ops.py`](https://github.com/NVIDIA/cuda-python/blob/main/cuda_core/examples/memory_ops.py)
- Upstream `cuda.core` example: [`memory_pool_resources.py`](https://github.com/NVIDIA/cuda-python/blob/main/cuda_core/examples/memory_pool_resources.py)


</details>

<br>

### pageRank

> #### On this box
>
> **Command**
> ```bash
> cd $CUDA_SAMPLES/python/2_CoreConcepts/pageRank
> source $VENVS/venv-rapids/bin/activate      # isolated: RAPIDS 26.8 + cuda-core<1.0.0
> python pageRank.py
> ```
>
> **Result** — Test PASSED. cuGraph **1.331 ms** vs CPU reference **2302.184 ms** = **1730x**. Scores summed to 1.000000.
>
> *Wall time: 4.3 s*
>
> **Notes** — **Needs its own venv** — RAPIDS `cugraph-cu13`/`cudf-cu13` 26.8.0 pin `cuda-core<1.0.0`. Install with `--extra-index-url=https://pypi.nvidia.com`. The 1730x is the largest speedup in the whole sample set, because the CPU reference is pure Python.

<details>
<summary><b>Full README — pageRank</b></summary>

#### Sample: PageRank Algorithm (Python)

> **Known issue — version-pinned sample.** Unlike the other samples in this
> repository, this sample is pinned to `cuda-core<1.0.0`. The reason is that
> `cudf-cu13` transitively requires `numba-cuda<0.29.0`, and every
> `numba-cuda` release in that range pins `cuda-core<1.0.0`. Installing this
> sample's `requirements.txt` into a shared environment will downgrade
> `cuda-core` and break the other samples (which use the 1.0 API).
>
> The recommended workflow is one of:
>
> - Install this sample's requirements in a **dedicated virtual
>   environment**, or
> - Re-run the other samples' `pip install -r requirements.txt` afterwards
>   to upgrade `cuda-core` back to 1.0.
>
> This sample will be re-aligned with the rest of the repository
> (`cuda-core>=1.0.0`) once `cudf-cu13` ships a release that lifts its
> `numba-cuda` upper bound.

##### Description

Demonstrates GPU-accelerated PageRank computation for graph analysis using RAPIDS cuGraph, with cuda.core for device, stream, and GPU timing. This sample focuses on cuda.core integration with high-level libraries (cuGraph/cuDF); for custom kernel programming (Program, LaunchConfig, launch), see the blockwiseSum sample.

##### What You'll Learn

- Graph representation using cuDF DataFrames for edge lists
- GPU-optimized PageRank via RAPIDS cuGraph library
- Performance comparison between cuGraph GPU and CPU reference implementation
- cuda.core device/stream management and GPU timing

##### Key Libraries

- `cugraph` - RAPIDS GPU-accelerated graph analytics
- `cudf` - RAPIDS GPU DataFrame library
- `cuda.core` - Device, stream, and event APIs for GPU timing
- `cupy` - GPU array library (Stream.from_external for cuDF/cuGraph)
- `numpy` - CPU reference implementation

##### Key APIs

###### From cuda.core:

- `Device(0)` - Create device, `device.set_current()`, `device.create_stream()`
- `EventOptions(enable_timing=True)` - GPU timing via `stream.record()`
- `cp.cuda.Stream.from_external(stream).use()` - Make cuDF/cuGraph use cuda.core stream

###### From cuGraph:

- `cugraph.Graph(directed=True)` - Create directed graph structure
- `Graph.from_cudf_edgelist()` - Build graph from edge list DataFrame
- `cugraph.pagerank()` - GPU-accelerated PageRank algorithm

###### From cuDF:

- `cudf.DataFrame()` - GPU DataFrame for edge lists

##### Requirements

###### Hardware:

- NVIDIA GPU with Compute Capability 7.0 or higher
- Minimum GPU memory: 512 MB (for 10K node graph)

###### Software:

- CUDA Toolkit 13.0 or newer
- Python 3.10 or newer
- See requirements.txt for package dependencies

###### Platform Support:

This sample depends on RAPIDS (`cugraph-cu13`, `cudf-cu13`, `dask-cuda`),
which is currently published only as **Linux (manylinux) wheels** on
`pypi.nvidia.com` — no Windows wheels exist. On Windows the sample exits
early with a waive message and exit code `2` instead of attempting an
install that cannot succeed.

##### Installation

```bash
cd $CUDA_SAMPLES/python/2_CoreConcepts/pageRank
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

##### How to Run

```bash
python pageRank.py
```

##### Algorithm

The PageRank formula iteratively computes node importance:

```
PR(v) = (1-d)/N + d * Σ PR(u)/out_degree(u)
```

Where:
- `d` = damping factor (typically 0.85)
- `N` = total number of nodes
- Sum is over all nodes `u` that link to `v`

##### Expected Output

```
============================================================
PageRank Algorithm (using RAPIDS cuGraph)
============================================================

Device: NVIDIA GeForce RTX ...
Compute Capability: sm_XX

Graph Parameters:
  Nodes: 10,000
  Avg edges/node: 15
  Total edges: ~150,000
  Avg in-degree: 14.9

------------------------------------------------------------
GPU PageRank (RAPIDS cuGraph)
------------------------------------------------------------
Time: X.XXX ms

Top 5 nodes by PageRank:
  1. Node XXXXX: 0.XXXXXX
  ...

------------------------------------------------------------
CPU PageRank (Reference)
------------------------------------------------------------
Time: XXXX.XXX ms
Iterations: XX

------------------------------------------------------------
PERFORMANCE SUMMARY
------------------------------------------------------------
GPU (cuGraph): X.XXX ms
CPU (Reference): XXXX.XXX ms
Speedup: XXXX.Xx

------------------------------------------------------------
VERIFICATION
------------------------------------------------------------
GPU vs CPU PageRank scores: Test PASSED

PageRank Properties:
  Sum of scores: 1.000000 (should be ~1.0)
  Sum check: ✓

Done
```

##### Files

- `pageRank.py` - Python implementation using RAPIDS cuGraph
- `README.md` - This file
- `requirements.txt` - Sample dependencies

##### Why cuGraph?

RAPIDS cuGraph provides production-grade, GPU-accelerated graph analytics:

- **Highly optimized** - Uses advanced GPU parallelization techniques
- **Scalable** - Handles graphs with billions of edges
- **Easy to use** - Simple Python API similar to NetworkX
- **Integrated** - Works seamlessly with cuDF, cuML, and other RAPIDS libraries

##### Applications

- Web page ranking (original Google PageRank)
- Social network influence analysis
- Citation network analysis
- Recommendation systems
- Fraud detection in financial networks

##### See Also

- [RAPIDS cuGraph Documentation](https://docs.rapids.ai/api/cugraph/stable/)
- [cuGraph GitHub Repository](https://github.com/rapidsai/cugraph)
- [RAPIDS Installation Guide](https://rapids.ai/start.html)


</details>

<br>

### parallelHistogram

> #### On this box
>
> **Command**
> ```bash
> cd $CUDA_SAMPLES/python/2_CoreConcepts/parallelHistogram
> python parallelHistogram.py
> ```
>
> **Result** — Both PASSED over 10,000,000 values. Global atomics 1.494 ms vs privatized (shared-memory) atomics 0.017 ms = **89.5x**.
>
> *Wall time: 1.0 s*
>
> **Notes** — The biggest algorithmic win per line of code in this repo. Contention on global atomics is catastrophic; privatize into shared memory then merge. Same pattern applies to any GPU counting/binning step.

<details>
<summary><b>Full README — parallelHistogram</b></summary>

#### Sample: Parallel Histogram with Atomics (Python)

##### Description

Compute histograms on the GPU using atomic operations to handle concurrent updates from multiple threads. This sample demonstrates the modern **cuda.core API** for kernel compilation and launch, comparing two approaches:

1. **Global Atomics** - All threads atomically update a single global histogram
2. **Privatized Histograms** - Each block uses shared memory, then merges to global

##### What You'll Learn

- Compiling CUDA C kernels with `cuda.core.Program`
- Configuring kernel launches with `cuda.core.LaunchConfig`
- Launching kernels with `cuda.core.launch()`
- Using **atomic operations** (`atomicAdd`) for thread-safe updates
- Optimizing with **shared memory privatization**
- GPU timing with `cuda.core` Events

##### Key Concepts

###### Atomic Operations

When multiple threads update the same histogram bin, a race condition occurs. Atomic operations ensure thread-safe updates:

```cuda
atomicAdd(&histogram[data[i]], 1);  // Thread-safe increment
```

###### Global vs Privatized Atomics

| Approach | Pros | Cons |
|----------|------|------|
| Global | Simple | High contention on popular bins |
| Privatized | Significantly faster | Extra shared memory, synchronization |

##### Key APIs

###### From `cuda.core`:

- `Device` - Device management and context
- `Program` - Compile CUDA C source code
- `ProgramOptions` - Set architecture, optimization flags
- `LaunchConfig` - Configure grid and block dimensions
- `launch()` - Launch compiled kernel
- `Stream` - Async stream management
- `EventOptions` - Configure events for GPU timing
- `stream.record()` - Record events for timing

###### From `cupy`:

- `cp.random.randint()` - Generate random data directly on GPU
- `cp.zeros()` - Allocate zeroed GPU arrays

###### CUDA Atomic Functions (in kernel):

- `atomicAdd()` - Thread-safe addition

##### Requirements

###### Hardware:
- NVIDIA GPU with CUDA support

###### Software:
- CUDA Toolkit 13.0 or newer
- Python 3.10 or newer
- See `requirements.txt` for Python packages

##### Installation

```bash
pip install -r requirements.txt
```

##### How to Run

```bash
python parallelHistogram.py
```

##### Expected Output

```
============================================================
Parallel Histogram with Atomics (cuda.core)
============================================================

Device: <Your GPU>
Compute Capability: ComputeCapability(major=X, minor=Y)

Compiling CUDA kernels with cuda.core.Program...
  Compiled for architecture: sm_XY

Generating 10,000,000 random values on GPU...

Verifying correctness...
  Global atomics:     PASSED
  Privatized atomics: PASSED

Benchmarking (100 iterations)...
  Global atomics:     X.XXX ms
  Privatized atomics: X.XXX ms
  Speedup:            XXx

Test PASSED
```

##### Files

- `parallelHistogram.py` - Main sample using cuda.core
- `README.md` - This file
- `requirements.txt` - Dependencies

##### See Also

- [cuda.core Documentation](https://nvidia.github.io/cuda-python/cuda-core/latest/)
- [CUDA Atomic Functions](https://docs.nvidia.com/cuda/cuda-c-programming-guide/index.html#atomic-functions)
- [CUDA Shared Memory](https://docs.nvidia.com/cuda/cuda-c-programming-guide/index.html#shared-memory)


</details>

<br>

### parallelReduction

> #### On this box
>
> **Command**
> ```bash
> cd $CUDA_SAMPLES/python/2_CoreConcepts/parallelReduction
> source $VENVS/venv-extras/bin/activate      # isolated: base + cuda-cccl, nvtx, numba-cuda, torch, mpi4py
> python parallelReduction.py
> ```
>
> **Result** — Test PASSED. Hand-written reduction 0.024 ms vs `cuda.compute.reduce_into()` 0.071 ms — here the custom kernel is ~3x faster than the library call.
>
> *Wall time: 2.4 s*
>
> **Notes** — Instructive counterpoint to `matrixMulSharedMem`: for a simple bandwidth-bound reduction the hand-written kernel wins, because the library path carries dispatch overhead the kernel does not.

<details>
<summary><b>Full README — parallelReduction</b></summary>

#### Sample: Parallel Reduction (Python)

##### Description

Efficiently sum a large array on GPU using parallel reduction. This sample demonstrates:
1. **Custom CUDA kernel** showing reduction tree pattern and synchronization
2. **cuda.compute.reduce_into()** for production-ready reduction

##### What You'll Learn

- **Reduction tree pattern**: Divide-and-conquer parallel algorithm
- **Thread synchronization**: Using `__syncthreads()` for coordination
- **Avoiding warp divergence**: Sequential thread IDs vs strided IDs

##### Key Concepts

###### Reduction Tree Pattern

Parallel reduction uses a tree-based approach where each iteration halves active elements:

```
Initial:  [a0, a1, a2, a3, a4, a5, a6, a7]
Step 1:   [a0+a4, a1+a5, a2+a6, a3+a7]      threads 0-3 active
Step 2:   [a0+a2+a4+a6, a1+a3+a5+a7]        threads 0-1 active
Step 3:   [sum of all]                       thread 0 only
```

This requires only `log2(N)` steps to reduce N elements.

###### Avoiding Warp Divergence

```c
// Good: Sequential thread IDs (warps stay coherent)
if (tid < s) {
    sdata[tid] += sdata[tid + s];
}

// Bad: Strided IDs (causes warp divergence)
if (tid % (2 * s) == 0) {  // Don't do this!
    sdata[tid] += sdata[tid + s];
}
```

##### Requirements

###### Hardware

- NVIDIA GPU with CUDA support

###### Software

- CUDA Toolkit 13.0+
- Python 3.10+
- `cuda-python` (13.0.0+)
- `cuda-core` (>=1.0.0)
- `cuda-cccl` (1.0.0+)
- `cupy-cuda13x` (>=14.0.0)
- `numpy` (>=2.3.2)

##### Installation

```bash
pip install -r requirements.txt
```

##### How to Run

```bash
python parallelReduction.py
```

##### Expected Output

```
======================================================================
Parallel Reduction - Efficient GPU Array Summation
======================================================================

Device: <your GPU name>
Compute Capability: <version>

Array size: 1,048,576 elements (4.2 MB)
Expected sum: <value>

Compiling custom CUDA kernel...

======================================================================
PART 1: Custom Kernel (Educational)
======================================================================

Reduction tree kernel:       <result>
Expected:                    <result>
Error:                       <small value>
Time:                        <varies> ms

======================================================================
PART 2: cuda.compute.reduce_into() (Production)
======================================================================

cuda.compute result:         <result>
Expected:                    <result>
Error:                       <small value>
Time:                        <varies> ms

Test PASSED!
```

Note: Exact values vary due to random input data. `cuda.compute.reduce_into()` is typically faster than the custom kernel because it calls CUB's `DeviceReduce`, which uses highly tuned, architecture‑specific kernels and optimized memory access patterns.

##### Files

- `parallelReduction.py` - Custom kernel + cuda.compute comparison
- `README.md` - This documentation
- `requirements.txt` - Python dependencies

##### See Also

- [Mark Harris - Optimizing Parallel Reduction in CUDA](https://developer.download.nvidia.com/assets/cuda/files/reduction.pdf)
- [cuda.core Documentation](https://nvidia.github.io/cuda-python/cuda-core/latest/)


</details>

<br>

### prefixSum

> #### On this box
>
> **Command**
> ```bash
> cd $CUDA_SAMPLES/python/2_CoreConcepts/prefixSum
> source $VENVS/venv-extras/bin/activate      # isolated: base + cuda-cccl, nvtx, numba-cuda, torch, mpi4py
> python prefixSum.py
> ```
>
> **Result** — Inclusive scan 0.109 ms, **91.9 M elements/ms**.
>
> *Wall time: 5.2 s*
>
> **Notes** — CUB-backed scan via `cuda.compute`. Scan is the primitive behind stream compaction and radix sort — and behind token filtering in batched inference.

<details>
<summary><b>Full README — prefixSum</b></summary>

#### Prefix Sum (Scan)

Demonstrates parallel prefix sum (scan) algorithms using cuda.compute with cuda.core stream management.

##### Overview

- Inclusive scan: `output[i] = [init_value] + input[0] + input[1] + ... + input[i]`
- Exclusive scan: `output[i] = init_value + input[0] + input[1] + ... + input[i-1]`
- Uses cuda.compute APIs for optimized CUB-based implementations
- Uses cuda.core APIs for device and stream management
- Demonstrates CuPy integration via `Stream.from_external`

##### Requirements

###### Hardware

- NVIDIA GPU with CUDA support

###### Software

- CUDA Toolkit 13.0+
- Python 3.10+
- `cuda-python` (13.0.0+)
- `cuda-core` (>=1.0.0)
- `cuda-cccl` (1.0.0+)
- `cupy-cuda13x` (14.0.0+)
- `numpy` (>=2.3.2)

##### Usage

```bash
# Create and activate virtual environment
python -m venv venv
source venv/bin/activate  # Linux/macOS
# venv\Scripts\activate   # Windows

# Install dependencies
pip install -r requirements.txt

# Run sample
python prefixSum.py
```

##### Key Concepts

| Scan Type | Formula | First Element |
|-----------|---------|---------------|
| Inclusive | `output[i] = [init_value] + Σ input[0..i]` | `[init_value] + input[0]` |
| Exclusive | `output[i] = init_value + Σ input[0..i-1]` | `init_value` (typically `0`, the identity for sum) |

###### Stream Management

This sample demonstrates proper stream usage across libraries:

```python
# Create stream with cuda.core
stream = device.create_stream()

# Wrap for CuPy compatibility (cuda.core Stream implements the __cuda_stream__ protocol)
cp_stream = cp.cuda.Stream.from_external(stream)

# Use with CuPy operations
with cp_stream:
    d_input = cp.asarray(data)
    d_output = cp.empty_like(d_input)

# Pass to cuda.compute
inclusive_scan(
    d_in=d_input,
    d_out=d_output,
    op=OpKind.PLUS,
    init_value=None,
    num_items=len(d_input),
    stream=stream,
)
```

##### Applications

- Stream compaction
- Radix sort
- Histogram computation
- Polynomial evaluation


</details>

<br>

### processCheckpoint

> #### On this box
>
> **Command**
> ```bash
> cd $CUDA_SAMPLES/python/2_CoreConcepts/processCheckpoint
> source $VENVS/venv-ckpt/bin/activate      # isolated: cuda-python<13.3.0
> python processCheckpoint.py
> ```
>
> **Result** — PASS. lock 0.357 ms, checkpoint 183.277 ms, restore 165.672 ms, unlock 0.257 ms, total 349.562 ms. Buffer hash identical before and after (`b045f7975dc23352`).
>
> *Wall time: 1.1 s*
>
> **Notes** — **Needs its own venv** — pins `cuda-python<13.3.0` while the working venv has 13.3.1. Checkpoint+restore of GPU state costs ~350 ms here; that is the budget for preemption or migration of a resident model.

<details>
<summary><b>Full README — processCheckpoint</b></summary>

#### processCheckpoint (Python)

##### Description

This sample demonstrates how to use the **CUDA process checkpoint API**
via `cuda.core.checkpoint.Process` to suspend, capture, and restore the
CUDA state of a running Linux process.

CUDA process checkpointing is the driver-level primitive that powers
CRIU + `cuda-checkpoint` integration.

The sample:

1. Allocates a GPU buffer and fills it with a deterministic pattern
   via a small kernel.
2. Reads the buffer back to host and computes a SHA-256 hash.
3. Runs the full checkpoint lifecycle on its own process:
   `lock → checkpoint → restore → unlock`.
4. Reads the buffer back again and verifies that the hash is
   unchanged, proving that GPU memory contents survived the round
   trip.

The sample prints the CUDA process state after each step so the
full state machine is visible:

```
         lock()          checkpoint()              restore()         unlock()
running ---------> locked ------------> checkpointed -----------> locked ---------> running
```

##### What You'll Learn

- Creating a `cuda.core.checkpoint.Process` for the current process
  by PID and observing its `.state` transitions.
- Running the full `lock → checkpoint → restore → unlock` cycle with
  a lock timeout.
- The fact that `restore()` leaves the process in the `locked` state;
  you must still call `unlock()` to return to `running`.
- Verifying that GPU memory is preserved across the checkpoint
  round-trip by comparing SHA-256 hashes of the buffer before and
  after.
- The rough cost of each step (checkpoint and restore dominate and
  scale with the device-memory footprint being captured).

##### Key Libraries

- [`cuda.core`](https://nvidia.github.io/cuda-python/cuda-core/latest/)
  - device management, memory allocation, kernel compilation and
    launch, and the `checkpoint.Process` wrapper.
- [`cuda.bindings`](https://nvidia.github.io/cuda-python/cuda-bindings/latest/)
  - used directly for a pageable `cuMemcpyDtoH`.

##### Key APIs

###### From `cuda.core.checkpoint`

- `checkpoint.Process(pid)` - create a handle to a CUDA process by
  PID. Accepts `os.getpid()` for the self-checkpoint case shown
  here.
- `Process.state` - one of `"running"`, `"locked"`, `"checkpointed"`,
  or `"failed"`.
- `Process.lock(timeout_ms=…)` - block further CUDA API calls on the
  process; completes already-submitted work. Always pass a non-zero
  timeout to avoid deadlocks.
- `Process.checkpoint()` - copy device memory to host-side driver
  allocations and release GPU resources. Process state becomes
  `checkpointed`.
- `Process.restore(gpu_mapping=None)` - re-acquire GPU resources and
  copy memory back to device. Leaves the process in the `locked`
  state.
- `Process.unlock()` - return the process to `running`.
- `Process.restore_thread_id` - thread ID that `restore()` must be
  called from in the target process (not used in the self-checkpoint
  case here).

###### From `cuda.core`

- `Device.set_current()` / `Device.memory_resource.allocate(...)` /
  `Stream`, `LaunchConfig`, `Program`, `launch` - standard device,
  compile, and launch primitives used to produce the buffer
  contents.

###### From `cuda.bindings.driver`

- `cuMemcpyDtoH(host_ptr, device_handle, nbytes)` - synchronous D2H
  copy into a pageable host buffer.

##### Requirements

###### Hardware

- Any NVIDIA GPU supported by CUDA process checkpointing. CUDA
  checkpointing is currently limited to x86-64 Linux.

###### Software

- Linux (the CUDA checkpoint API is Linux-only).
- NVIDIA driver with CUDA process checkpoint support.
- CUDA Toolkit 13.0 or newer.
- Python 3.10 or newer.
- `cuda-core >= 1.0.0`.

##### Installation

Install the required packages from `requirements.txt`:

```bash
cd $CUDA_SAMPLES/python/2_CoreConcepts/processCheckpoint
pip install -r requirements.txt
```

##### How to Run

###### Basic usage

```bash
python processCheckpoint.py
```

###### Larger GPU footprint to see checkpoint time scale

```bash
python processCheckpoint.py --buffer-mib 512
```

###### Use a specific GPU

```bash
python processCheckpoint.py --device 1
```

###### All options

```
--device           CUDA device ID (default: 0)
--buffer-mib       GPU buffer size in MiB (default: 16)
--lock-timeout-ms  Timeout passed to Process.lock in ms (default: 5000)
```

##### Expected Output

On an RTX 4090 with a 16 MiB buffer:

```
[Process Checkpoint Sample using CUDA Core API]
PID:                748330
Device:             NVIDIA GeForce RTX 4090
Compute Capability: sm_89
Buffer size:        16 MiB
Lock timeout:       5000 ms

Compiling kernel ...
Writing deterministic pattern to GPU buffer ...
Buffer hash (before): b045f7975dc23352

Running checkpoint lifecycle on self ...

step               duration (ms)       state after
--------------------------------------------------
initial                        -           running
lock                       0.578            locked
checkpoint               268.369      checkpointed
restore                  235.024            locked
unlock                     1.648           running
--------------------------------------------------
total                    505.618

Buffer hash (before): b045f7975dc23352
Buffer hash (after):  b045f7975dc23352

PASS: GPU buffer contents survived checkpoint/restore.

Done
```

**What to look for:**

- The **four state transitions** are all observable: `running →
locked → checkpointed → locked → running`. Note that `restore()`
  leaves the process in `locked`, not `running`.
- The **checkpoint and restore steps dominate** the wall-clock time
  (hundreds of ms even for a small buffer) - they copy GPU memory to
  and from driver-managed host allocations. Increasing
  `--buffer-mib` visibly increases the checkpoint time.
- The `lock` and `unlock` steps are essentially free (sub-ms) - they
  just flip the process state.
- The SHA-256 **hashes before and after match**, proving the GPU
  memory contents survived the round trip.

Exact timings vary with GPU model, driver version, system load, and
the size of the device memory footprint being captured.

##### Files

- `processCheckpoint.py` - Python implementation using `cuda.core.checkpoint`
- `README.md` - This file
- `requirements.txt` - Sample dependencies

##### See Also

- [CUDA Python Documentation](https://nvidia.github.io/cuda-python/)
- [`NVIDIA/cuda-checkpoint`](https://github.com/NVIDIA/cuda-checkpoint)
  - the CUDA checkpoint/restore utility, the CRIU plugin, and C
    reference programs (`r570-features.c`, `r580-migration-api.c`).
- [Checkpointing CUDA Applications with CRIU](https://developer.nvidia.com/blog/checkpointing-cuda-applications-with-criu/)
  - NVIDIA technical blog post on the broader CRIU workflow.


</details>

<br>

### reduction

> #### On this box
>
> **Command**
> ```bash
> cd $CUDA_SAMPLES/python/2_CoreConcepts/reduction
> python reduction.py
> ```
>
> **Result** — PASSED. Two-stage reduction, 8,388,608 global reads, 32768 block outputs, **752.30 GB/s**.
>
> *Wall time: 2.3 s*
>
> **Notes** — This is the most trustworthy DRAM-bandwidth figure the sample set produces: 752 GB/s = **84% of the 896 GB/s theoretical peak**. Use it, not the marketing number, when you do roofline maths for this box.

<details>
<summary><b>Full README — reduction</b></summary>

#### Sample: Fast Array Sum using Shared Memory (Python)

##### Description

Two-stage parallel reduction: each GPU block sums its chunk in **shared memory** (tree reduction, two elements per thread), writes one partial sum per block; the host combines partial sums for the final result.

**Stack:** `cuda-core` for `Device`, stream, events, `Program` / `launch()`. **CuPy** allocates device memory and copies; `launch()` takes device pointers as `ndarray.data.ptr` (Python `int`). Copies run on the same CUDA stream as the kernel via `cp.cuda.Stream.from_external(stream)` (cuda.core `Stream` implements the CUDA stream protocol) and `with cp_stream:`.

##### What you will learn

- Shared-memory block reduction and sequential-addressing tree reduction
- `LaunchConfig` with dynamic shared memory and `launch()` with pointer arguments
- Aligning CuPy transfers with a `cuda.core` stream (`Stream.from_external`)
- GPU timing with `EventOptions` / `device.create_event()`

##### Key libraries

| Library    | Role |
|------------|------|
| `cuda-core`| Device, stream, events, compile, launch |
| `cupy`     | `cp.empty`, `cp.asarray`, `cp.asnumpy`, `Stream.from_external` |
| `numpy`    | Host data and CPU reference sum |

##### Key APIs (quick reference)

- **cuda.core:** `Device`, `create_stream`, `Program` / `ProgramOptions`, `LaunchConfig`, `launch`, `EventOptions`, `create_event`
- **CuPy:** `cp.empty`, `cp.asarray`, `cp.cuda.Stream.from_external(stream)`, `with cp_stream:`, `cp.asnumpy`

##### Requirements

- NVIDIA GPU, CUDA-capable driver; **CUDA Toolkit 13+** (for toolchain alignment with `cuda-core`)
- **Python 3.10+**

```bash
pip install -r requirements.txt
```

##### How to run

```bash
python reduction.py
```

Defaults: 2²⁴ elements, 256 threads/block, `float`, 100 benchmark iterations.

**Change data type** (selects `blockReduceKernel_int` / `_float` / `_double`):

```bash
python reduction.py --type float    # default; 32-bit float
python reduction.py --type double   # 64-bit float
python reduction.py --type int      # 32-bit integer (exact equality check)
```

Combine with other flags as needed, e.g. `python reduction.py --type int --n 1048576`.

Other main flags: `--n`, `--threads`, `--iterations`. Full list: `python reduction.py --help`.

##### Output

Example run (`python reduction.py`, defaults) on **Tesla T10**, compute capability **7.5**:

```
======================================================================
Fast Array Sum using Shared Memory - Two-Stage Reduction
======================================================================

Demonstrates: Efficient parallel reduction using shared memory

Device Information:
  Name: Tesla T10
  Compute Capability: sm_7.5

Configuration:
  Array size: 16,777,216 elements
  Data type: float
  Memory: 64.00 MB
  Threads per block: 256

Two-Stage Reduction Strategy:
  Stage 1: GPU block reduction
    - Number of blocks: 32768
    - Elements per block: 512
    - Output: 32768 partial sums
  Stage 2: CPU final reduction
    - Combine 32768 partial sums -> 1 final result

Compiling CUDA kernel...
  Kernel 'blockReduceKernel_float' compiled successfully

> Generating random input data...
> Computing reference result on CPU...
  CPU time: 2.428208 seconds

> Warming up GPU...
  Warm-up completed

> Benchmarking Stage 1 (GPU block reduction)...
  Running 100 iterations...

> Running Stage 2 (CPU final reduction)...

======================================================================
Performance Results
======================================================================

Stage 1 (GPU block reduction):
  Average time: 0.338404 ms
  Throughput: 198.31 GB/s

Stage 2 (CPU final reduction):
  Time: 0.078073 ms
  (32768 partial sums)

Total time: 0.416477 ms
Speedup vs CPU: 5830.35x

> Validating results...
  GPU result: 2147639808.00000000
  CPU result: 2147639929.62027407
Test PASSED

======================================================================
Summary
======================================================================
Key optimizations:
  - Load 2 elements per thread: 8,388,608 global reads (50% savings)
  - Shared memory for reduction: ~10-20x faster than global memory
  - Parallel block outputs: 32768 independent writes
Result: 198.31 GB/s throughput
======================================================================
Two-Stage Reduction completed successfully!
======================================================================
```

##### Files

`reduction.py` · `requirements.txt` · `README.md`


</details>

<br>

### reductionMultiBlockCG

> #### On this box
>
> **Command**
> ```bash
> cd $CUDA_SAMPLES/python/2_CoreConcepts/reductionMultiBlockCG
> source $VENVS/venv-extras/bin/activate      # isolated: base + cuda-cccl, nvtx, numba-cuda, torch, mpi4py
> SITE=$VENVS/venv-extras/lib/python3.13/site-packages
> python reductionMultiBlockCG.py \
>   --cuda-include-dir "$SITE/nvidia/cu13/include:$SITE/cuda/cccl/headers/include"
> ```
>
> **Result** — PASSED with **708.92 GB/s** in a single kernel launch — 70 blocks -> `grid.sync()` -> block 0 finalises.
>
> **Notes** — **Gotcha:** `--cuda-include-dir` is mandatory and needs **two** directories joined by `:`. Passing only the CUDA toolkit include fails with `cannot open source file "cuda/std/type_traits"` — cooperative_groups pulls in libcu++, which ships in the `cuda-cccl` pip package, not in `/usr/local/cuda/include`. Find them with:
```python
from cuda.cccl.headers import get_include_paths; print(get_include_paths())
```

<details>
<summary><b>Full README — reductionMultiBlockCG</b></summary>

#### Sample: Single-Pass Multi-Block Reduction with Cooperative Groups (Python)

##### Description

Single-kernel, two-stage reduction using **Cooperative Groups** and `grid.sync()` so all blocks synchronize inside one launch—no second kernel or CPU stage for the reduction tree.

**Stack:** `cuda-core` (device, compile, cooperative `launch()`, stream, **CUDA events** for GPU timing). **CuPy** for H↔D copies on the same stream (`Stream.from_external(cuda.core_stream)`, `ndarray.data.ptr` to `launch()`). **`try`/`finally`** closes the stream if cooperative launch fails. Requires **compute capability > 6.0** (Pascal+).

##### What you will learn

- `cooperative_groups::grid_group` and `grid.sync()` across the grid
- Cooperative `LaunchConfig(..., cooperative_launch=True)` and sizing blocks for residency
- Timing the GPU path with `EventOptions` / `stream.record()` / event elapsed time

##### Key libraries

| Library | Role |
|---------|------|
| `cuda-core` | Device, stream, events, `Program` / `ProgramOptions`, cooperative `launch()` |
| `cupy` | `cp.empty`, `cp.asarray`, `cp.asnumpy`, `Stream.from_external` |
| `numpy` | Host data, reference sum, `default_rng` |

##### Requirements

- NVIDIA GPU, **Pascal or newer**; **CUDA Toolkit 13+**; **Python 3.10+**
- NVRTC must see **`cooperative_groups.h`** and **CCCL** headers (`cuda/std/*`)

```bash
pip install -r requirements.txt
```

Pick a CuPy wheel that matches your CUDA major version (e.g. `cupy-cuda13x` in `requirements.txt`).

##### How to run

**`--cuda-include-dir` is required.** Multiple paths can be combined using the
OS path separator (`:` on Linux/macOS, `;` on Windows).

Linux / macOS:

```bash
python reductionMultiBlockCG.py \
  --cuda-include-dir /usr/local/cuda/include/cccl:/usr/local/cuda/include
```

Windows (PowerShell or cmd, note the `;` separator and quotes around the
combined value):

```powershell
python reductionMultiBlockCG.py `
  --cuda-include-dir "$env:CUDA_PATH\include;$env:CUDA_PATH\include\cccl"
```

**Jetson / split include trees:** pass every directory NVRTC needs in one `--cuda-include-dir` argument, e.g.
`/usr/local/cuda/include/cccl:/usr/local/cuda/targets/sbsa-linux/include` (adjust paths to your image). If headers are scattered, you can instead merge them into one tree with symlinks and point `--cuda-include-dir` at that folder.

Defaults: **2²⁵** elements, threads = device max (capped at 1024), auto `--maxblocks`, **100** iterations. Other flags: `--n`, `--threads`, `--maxblocks`, `--iterations`. See **`python reductionMultiBlockCG.py --help`**.

##### Output

```
======================================================================
Single-Pass Multi-Block Reduction with Cooperative Groups
======================================================================

Demonstrates: Multi-stage reduction in a single kernel using grid.sync()

Device Information:
  Name: NVIDIA Thor
  Compute Capability: sm_11.0

Reduction Configuration:
  Number of elements: 33,554,432
  Data size: 128.00 MB

Compiling CUDA kernel...
  Kernel compiled successfully

Launch Configuration:
  Threads per block: 1024
  Number of blocks: 20
  Total threads: 20,480
  Shared memory per block: 4096 bytes
  Launch mode: Cooperative (grid-wide sync enabled)

> Generating random input data...
> Computing reference result on CPU...
  CPU time: 0.008903 seconds

> Warming up GPU...
  Warm-up successful

> Running benchmark (100 iterations)...

> Performance Results:
  Average GPU time: 0.977166 ms
  Throughput: 137.35 GB/s
  Speedup vs CPU: 9.11x

> Validating results...
Test PASSED

======================================================================
Summary
======================================================================

Single-kernel two-stage reduction:
  Stage 1: 20 blocks -> 20 partial sums
  grid.sync() <- All blocks synchronize (KEY innovation)
  Stage 2: Block 0 -> 1 final result
  Total: 1 kernel launch, 137.35 GB/s

Comparison:
  • Traditional: 2 kernel launches or kernel + CPU
  • This sample: 1 kernel with grid.sync() between stages
  • Benefit: Eliminates ~5-20us launch overhead per stage

======================================================================
Single-Pass Multi-Block Reduction completed successfully!
======================================================================
```

##### Troubleshooting (short)

- **Cooperative launch not supported / fails:** need sm_60+; reduce `--maxblocks` or `--threads` so all blocks can be resident.
- **Compile errors missing headers:** extend `--cuda-include-dir` with the path that contains CCCL / cooperative groups (see Jetson note above).
- **Low throughput:** often block count vs occupancy; try defaults first, then tune `--threads` / `--maxblocks`.

##### Related samples

**blockArraySum** (atomics + grid-stride) → **reduction** (two-stage shared memory) → **this sample** (single kernel + `grid.sync()`).

##### Further reading

- [CUDA Cooperative Groups](https://docs.nvidia.com/cuda/cuda-c-programming-guide/index.html#cooperative-groups)
- [Reduction whitepaper (PDF)](https://developer.download.nvidia.com/assets/cuda/files/reduction.pdf)

##### Files

`reductionMultiBlockCG.py` · `requirements.txt` · `README.md`


</details>

<br>

### simpleZeroCopy

> #### On this box
>
> **Command**
> ```bash
> cd $CUDA_SAMPLES/python/2_CoreConcepts/simpleZeroCopy
> python simpleZeroCopy.py
> ```
>
> **Result** — Validation PASSED over 1,048,576 elements, relative error 0.000000e+00.
>
> *Wall time: 0.5 s*
>
> **Notes** — Zero-copy means the kernel reads host memory across PCIe. On this box that is a ~7 GB/s pipe, so it is a latency/convenience tool for small or streamed data — never for anything you touch repeatedly.

<details>
<summary><b>Full README — simpleZeroCopy</b></summary>

#### Sample: simpleZeroCopy (Python)

##### Description

This sample demonstrates zero-copy access using **`cuda.core`** to compile and launch a kernel, and **`cuda.bindings.runtime`** for mapped pinned host memory (`cudaHostAlloc` with `cudaHostAllocMapped`, `cudaHostGetDevicePointer`, and `cudaFreeHost`). The GPU loads and stores through **device** addresses that refer to that host memory—no `cudaMemcpy` in or out. The example is vector add with inputs and output as NumPy views of the host side of those buffers.

##### What you will learn

- How to allocate **mapped** pinned host memory with `cudaHostAlloc` (via `cuda.bindings.runtime`) so the GPU can use `cudaHostGetDevicePointer` addresses in a kernel
- How `cuda.core.PinnedMemoryResource` differs (staging/copies; not guaranteed to be `cudaHostAllocMapped` for direct kernel access)
- How to build NumPy views of host addresses with `ctypes` and `numpy.frombuffer`
- How to launch CUDA kernels with `cuda.core`’s `Program` and `launch`, passing **device** pointers for mapped buffers
- When zero-copy is beneficial vs. device memory with explicit transfers
- How to validate results on the host without a D2H memcpy

##### Key libraries

- `numpy` – CPU arrays and reference computation
- `cuda-core` – `Device`, stream, `Program`, `LaunchConfig`, `launch`
- `cuda-python` (`cuda.bindings.runtime`) – `cudaHostAlloc` / `cudaHostGetDevicePointer` / `cudaFreeHost` for mapped host memory

##### Key APIs

**From cuda.core:** `Device`, `device.create_stream()`, `Program`, `ProgramOptions`, `LaunchConfig`, `launch`

**From cuda.bindings.runtime:** `cudaHostAlloc` (with `cudaHostAllocMapped` | `cudaHostAllocPortable`), `cudaHostGetDevicePointer`, `cudaFreeHost`

**From the standard library:** `ctypes` – wrap host pointers for `numpy.frombuffer` float32 views

**Memory management:** Free host memory with `cudaFreeHost` in a `finally` block; call `stream.close()` when done.

##### Zero-Copy Memory: When to Use

###### Benefits
- **No explicit transfers**: Simplifies code by eliminating `cudaMemcpy` calls
- **Automatic synchronization**: Host can access results immediately after kernel completes
- **Good for small data**: Overhead of explicit transfers can exceed benefits for small arrays
- **Excellent for integrated GPUs**: On systems like Jetson (Tegra), CPU and GPU share physical memory

###### Limitations
- **Slower access**: Limited by PCIe bandwidth vs. device memory bandwidth
- **Not for compute-intensive**: Device memory is much faster for frequently accessed data
- **Discrete GPU overhead**: Each access crosses PCIe bus

###### Best Use Cases
1. Small data sets where transfer overhead dominates
2. Data accessed infrequently by GPU
3. Integrated GPU platforms (shared memory)
4. Streaming data from host to device
5. Prototyping and debugging (simplifies memory management)

##### Requirements

1. **NVIDIA GPU** and a **driver** compatible with your installed `cuda-python` / `cuda-core` wheels.
2. **Python 3.10 or newer**
3. Install **`pip install -r requirements.txt`** (NumPy, `cuda-python`, `cuda-core`). A **system** CUDA Toolkit is not strictly required if the process can load the driver/runtime; use `LD_LIBRARY_PATH` in *How to run* if you hit missing-library errors.

**Install packages:**
```bash
pip install -r requirements.txt
```

Or manually:
```bash
pip install numpy>=2.3.2 cuda-core>=1.0.0 cuda-python>=13.0.0
```

##### How to run

Basic usage:
```bash
# Pre-steps: Set library path
export LD_LIBRARY_PATH=/usr/local/cuda/lib64:$LD_LIBRARY_PATH

# Run with default parameters (1M elements)
python simpleZeroCopy.py
```

With custom parameters:
```bash
# Use 2M elements
python simpleZeroCopy.py --num_elements 2097152

# Show help
python simpleZeroCopy.py --help
```

###### Command line arguments

- `--num_elements`: Number of elements in vectors (default: 1048576)
  - Each vector uses `num_elements * 4 bytes` (float32)
  - Default: ~4 MB per vector, ~12 MB total

##### Expected Output

Device name and compute capability **depend on your system**; the rest of the log should match this shape when validation passes.

```
======================================================================
simpleZeroCopy - CUDA Python Sample
======================================================================

Device Information:
  Name: <your GPU>
  Compute Capability: <major>.<minor>

> Memory: mapped pinned host (cudaHostAlloc + cudaHostGetDevicePointer)

Compiling CUDA kernel...
  Kernel compiled successfully

Allocating memory:
  Vector size: 1,048,576 elements
  Memory per vector: 4.00 MB
  Total memory: 12.00 MB

> Allocating mapped pinned host memory...
  Mapped host memory allocated successfully

> Initializing vectors on host...
> Computing reference result on CPU...

> Launching vectorAddGPU kernel...
  Note: GPU accesses host memory directly (zero-copy)
  Kernel execution complete

> Checking results from vectorAddGPU()...
  Comparing 1,048,576 elements...
  Relative error: 0.000000e+00
  Validation PASSED

======================================================================
simpleZeroCopy completed successfully!
======================================================================
```

##### Files

- `simpleZeroCopy.py` – Main Python implementation
- `README.md` – This file
- `requirements.txt` – Python package dependencies


</details>

<br>

### streamingCopyComputeOverlap

> #### On this box
>
> **Command**
> ```bash
> cd $CUDA_SAMPLES/python/2_CoreConcepts/streamingCopyComputeOverlap
> python streamingCopyComputeOverlap.py
> ```
>
> **Result** — **No speedup on this box.** 2 streams 18.86 ms (1.00x), 4 streams 19.19 ms (0.98x), 8 streams 20.15 ms (0.93x) — more streams made it slightly *worse*.
>
> *Wall time: 16.7 s*
>
> **Notes** — This is the most interesting negative result in the set, and it is a hardware story, not a bug. The sample assumes you can hide transfers behind compute; here the PCIe Gen 3 x8 link (~7 GB/s, Appendix A) is so much slower than the 752 GB/s DRAM path that transfer dominates end-to-end and there is nothing left to hide it behind. Adding streams just adds scheduling overhead. On a Gen 5 x16 host the same code should show the textbook speedup.

<details>
<summary><b>Full README — streamingCopyComputeOverlap</b></summary>

#### Sample: Streaming Copy + Compute Overlap (Python)

##### Description

Demonstrate how to overlap memory transfers (H2D/D2H) with kernel computation using CUDA streams. This technique hides transfer latency and improves GPU utilization.

##### What You'll Learn

- Using `PinnedMemoryResource` for async-capable host memory
- Using `DeviceMemoryResource` for GPU memory allocation
- Creating multiple streams with `Device.create_stream()`
- Async memory copies with `Buffer.copy_to()`
- Overlapping H2D transfers, kernel execution, and D2H transfers

##### Key Concept

**Without overlap (sequential):**
```
[====H2D====][====Compute====][====D2H====]
```

**With overlap (multiple streams):**
```
Stream 0: [H2D][Compute][D2H]
Stream 1:      [H2D][Compute][D2H]
Stream 2:           [H2D][Compute][D2H]
```

##### Key APIs (all from `cuda.core`)

- `Device` - Device management
- `Device.create_stream()` - Create CUDA streams
- `Stream.sync()` - Synchronize stream
- `PinnedMemoryResource` - Pinned host memory (required for async transfers)
- `DeviceMemoryResource` - GPU device memory
- `Buffer.copy_to(dst, stream=stream)` - Async memory copy
- `Program`, `LaunchConfig`, `launch` - Kernel compilation and execution

###### From `numpy`:

- `np.from_dlpack()` - Zero-copy view of pinned memory buffers

##### Requirements

- CUDA Toolkit 13.0+
- Python 3.10+
- `cuda-python`, `cuda-core`, `numpy`

##### Installation

```bash
pip install -r requirements.txt
```

##### How to Run

```bash
python streamingCopyComputeOverlap.py
```

##### Expected Output

```
============================================================
Streaming Copy + Compute Overlap
Using pure cuda.core APIs
============================================================

Device: NVIDIA GeForce RTX XXXX
Kernel compiled [OK]

Problem size: 16,000,000 elements (61 MB)

--- Sequential (no overlap) ---
Timeline: [H2D][Compute][D2H]
Time: X.XX ms (±X.XX)

--- Streamed (with overlap) ---
Stream 0: [H2D][Compute][D2H]
Stream 1:      [H2D][Compute][D2H]
Stream 2:           [H2D][Compute][D2H]
...
2 streams: X.XX ms (±X.XX) - speedup: X.XXx
4 streams: X.XX ms (±X.XX) - speedup: X.XXx
8 streams: X.XX ms (±X.XX) - speedup: X.XXx

============================================================
Key: Pinned memory + multiple streams = overlap transfers with compute

Note: Speedup depends on hardware characteristics. This technique
benefits most when transfer time is significant relative to compute.
============================================================
```

##### See Also

- [cuda.core Documentation](https://nvidia.github.io/cuda-python/cuda-core/latest/)
- [CUDA Streams Best Practices](https://docs.nvidia.com/cuda/cuda-c-best-practices-guide/index.html#overlapping-data-transfers)


</details>

<br>

### tmaTensorMap

> #### On this box
>
> **Command**
> ```bash
> cd $CUDA_SAMPLES/python/2_CoreConcepts/tmaTensorMap
> python tmaTensorMap.py
> ```
>
> **Result** — Ran fully. TMA copy verified for 1024 elements across 8 tiles; `replace_address` verified (descriptor reused against a new source tensor).
>
> *Wall time: 4.2 s*
>
> **Notes** — The README says Hopper CC 9.0+ and that older GPUs exit cleanly without running the kernel. This GPU is CC 12.0, so the kernel **does** run — Blackwell has TMA. Don't let the Hopper-centric wording put you off.

<details>
<summary><b>Full README — tmaTensorMap</b></summary>

#### tmaTensorMap (Python)

##### Description

This sample demonstrates how to use Tensor Memory Accelerator (TMA)
descriptors with `cuda.core` on Hopper and later GPUs (compute
capability >= 9.0). TMA enables efficient bulk data movement between
global and shared memory using hardware-managed tensor map
descriptors, which are a key building block for modern GEMM kernels
and large shared-memory tile loads.

The sample:

1. Creates a TMA tiled descriptor from a CuPy device array via
   `StridedMemoryView.from_any_interface(...).as_tensor_map(...)`.
2. Passes the descriptor by value (as `__grid_constant__`) to a
   kernel that uses libcudacxx TMA/barrier wrappers to bulk-load a
   tile into shared memory, then copies it out to verify correctness.
3. Reuses the same descriptor against a new source tensor with
   `replace_address()` to avoid rebuilding it.

##### What You'll Learn

- Creating a TMA descriptor from a strided device tensor via
  `StridedMemoryView.as_tensor_map(box_dim=...)`
- Passing a tensor map to a kernel by value using
  `__grid_constant__`
- Using libcudacxx (`cuda/barrier`) to coordinate TMA loads with a
  block-scoped barrier
- Reusing a descriptor against a new source buffer via
  `tensor_map.replace_address(new_tensor)`
- Compiling a kernel to CUBIN for a specific target arch so Hopper
  features are available
- Using `cuda.pathfinder` to locate the CUDA toolkit include directory
  CCCL headers and libcudacxx

##### Key Libraries

- [`cuda.core`](https://nvidia.github.io/cuda-python/cuda-core/latest/) - compilation, launching, and tensor-map helpers
- `cuda.pathfinder` - locate the CUDA toolkit include directory
- `cupy` - allocate and fill device tensors
- `numpy` - scalar kernel arguments

##### Key APIs

###### From `cuda.core`

- `StridedMemoryView.from_any_interface(tensor, stream_ptr=-1)` - build a typed view from any DLPack/CUDA-array-interface tensor
- `StridedMemoryView.as_tensor_map(box_dim=(...))` - produce a TMA descriptor for the given tile shape
- `tensor_map.replace_address(new_tensor)` - retarget an existing descriptor at a new tensor
- `Program(code, code_type="c++", options=ProgramOptions(std="c++17", arch="sm_90", include_path=[...]))` - compile a C++ kernel against libcudacxx
- `program.compile("cubin")` - produce a CUBIN so `__grid_constant__` and TMA intrinsics are fully supported
- `launch(stream, config, kernel, tensor_map, ...)` - pass the TMA descriptor as a kernel argument

###### From `cuda.pathfinder`

- `get_cuda_path_or_home()` - return the detected CUDA toolkit root for locating `include/cccl`

###### From `cuda_samples_utils`

- `print_gpu_info()` - print device name and compute capability

##### Requirements

###### Hardware

- NVIDIA Hopper or newer GPU with Compute Capability 9.0 or higher (H100, H200, B200, ...)
- On GPUs older than Hopper the sample exits cleanly without running the kernel
- Minimum GPU memory: 512 MB

###### Software

- CUDA Toolkit 13.0 or newer with libcudacxx (cccl) headers
- Python 3.10 or newer
- `cuda-python` (>=13.0.0)
- `cuda-core` (>=1.0.0)
- `cupy-cuda13x` (>=14.0.0)

##### Installation

Install the required packages from `requirements.txt`:

```bash
cd $CUDA_SAMPLES/python/2_CoreConcepts/tmaTensorMap
pip install -r requirements.txt
```

The `requirements.txt` installs:

- `cuda-python` (>=13.0.0)
- `cuda-core` (>=1.0.0)
- `cupy-cuda13x` (>=14.0.0)

##### How to Run

###### Basic usage

```bash
cd $CUDA_SAMPLES/python/2_CoreConcepts/tmaTensorMap
python tmaTensorMap.py
```

###### With custom parameters

```bash
# Larger tensor (must be a multiple of the 128-element tile)
python tmaTensorMap.py --elements 8192

# Use a specific GPU
python tmaTensorMap.py --device 1
```

##### Expected Output

On a Hopper (sm_90) GPU:

```
Device: NVIDIA H100 PCIe
Compute Capability: 9.0

TMA copy verified: 1024 elements across 8 tiles
replace_address verified: descriptor reused with new source tensor
```

**Note:** Device name and compute capability will vary based on your GPU.

##### Files

- `tmaTensorMap.py` - Python implementation using `cuda.core` TMA APIs
- `README.md` - This file
- `requirements.txt` - Sample dependencies
- `../../Utilities/cuda_samples_utils.py` - Common utilities (imported by this sample)

##### See Also

- [CUDA Python Documentation](https://nvidia.github.io/cuda-python/)
- [TMA in the CUDA C++ Programming Guide](https://docs.nvidia.com/cuda/cuda-c-programming-guide/index.html#tensor-memory-accelerator)
- [`cuda::barrier` reference](https://nvidia.github.io/cccl/libcudacxx/extended_api/synchronization_primitives/barrier.html)


</details>

---
