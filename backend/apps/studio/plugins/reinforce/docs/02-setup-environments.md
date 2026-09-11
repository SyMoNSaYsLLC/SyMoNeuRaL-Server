# 02 - Setup and environments

Repository layout, the pristine-vs-isolated venv policy, and the per-sample runnability matrix.

> Part of the [symoneural_reinforce documentation set](README.md). Sliced from the consolidated manual at `../../../../docs/symoneural-manual.md`, which remains the canonical single file.

# Part II — Setup and runnability

## Paths

Every command in this document uses these two variables. Set them once:

```bash
export CUDA_SAMPLES=/home/google/Symoneural/cuda-samples
export VENVS=/home/google/Symoneural/venvs   # isolated environments
```

## Repository layout — and what changed

The upstream repository was reorganised. Documentation written against the old
layout, including the original Playbook 01, is broken in three specific ways:

| Old instruction | Reality |
|---|---|
| `cuda-samples/Samples/...` | **`Samples/` is now `cpp/`** |
| `cd .../bandwidthTest && make` | builds with **CMake**, not `make` |
| `bandwidthTest` | **deleted from the repository.** `cpp/1_Utilities/` has only `deviceQuery`, `deviceQueryDrv`, `topologyQuery` |

```
cuda-samples/
├── python/              <- the samples this document covers
│   ├── 1_GettingStarted/      (8 samples)
│   ├── 2_CoreConcepts/        (20 samples)
│   ├── 3_FrameworkInterop/    (2 samples)
│   ├── 4_DistributedComputing/(3 samples)
│   ├── Utilities/             <- the shared helper package
│   ├── .venv/                 <- the working environment (Python 3.13.5)
│   ├── requirements.txt
│   └── cudasamplepython       <- a stray text file, NOT a module (see below)
├── cpp/                 <- was Samples/
├── build/               <- CMake tree, already populated
│   └── cpp/<category>/<name>/<name>
├── Common/  cmake/  bin/
```

> **On `cudasamplepython`.** Older listings show a `cudasamplepython/` package with
> `__init__.py`, `cuda_samples_utils.py` and `README.md`. **No such module exists in
> this clone.** `python/cudasamplepython` is a stray UTF-8 text file containing a
> directory-tree dump. The real package — with exactly those three files — is
> `python/Utilities/`, documented in full in Part IV. Nothing is missing; the name
> is just wrong.

## Building the C++ side

Already done in this clone, but for reference:

```bash
cd $CUDA_SAMPLES
cmake -B build -S .
cmake --build build -j$(nproc)
```

Useful prebuilt binaries:

```bash
$CUDA_SAMPLES/build/cpp/1_Utilities/deviceQuery/deviceQuery
$CUDA_SAMPLES/build/cpp/1_Utilities/topologyQuery/topologyQuery
$CUDA_SAMPLES/build/cpp/6_Performance/alignedTypes      # bandwidth (bandwidthTest replacement)
$CUDA_SAMPLES/build/cpp/6_Performance/transpose
$CUDA_SAMPLES/build/cpp/6_Performance/UnifiedMemoryPerf
```

## The environments

**Policy: `$CUDA_SAMPLES/python/.venv` stays pristine.** It holds exactly the four
packages in `python/requirements.txt` and nothing else. Every sample that needs
anything beyond that gets an isolated venv outside the project tree.

This is not fussiness. Two of the extras actively damage the base environment:
`numba-cuda` pins `numpy<2.5` and will **silently downgrade** your numpy, and the
three pinned samples below contradict the base `cuda-core`/`cuda-python` versions
outright. Keeping them separate means the environment you rely on never moves.

| Venv | For | Why separate |
|---|---|---|
| `$CUDA_SAMPLES/python/.venv` | 24 of 33 samples | **pristine base** — the 4 packages in `requirements.txt`, untouched |
| `$VENVS/venv-extras` | 9 samples | adds `cuda-cccl`, `nvtx`, `numba-cuda`, `torch`, `mpi4py` — `numba-cuda` would downgrade base numpy 2.5.2 → 2.4.6 |
| `$VENVS/venv-nvmath` | `matrixMulSharedMem` | pins `cuda-core==0.7.0` vs the base `1.0.1` |
| `$VENVS/venv-rapids` | `pageRank` | RAPIDS 26.8 pins `cuda-core<1.0.0` |
| `$VENVS/venv-ckpt` | `processCheckpoint` | pins `cuda-python<13.3.0` vs the base `13.3.1` |
| `$VENVS/venv-tf` | `customTensorFlowKernel` | keeps TensorFlow's pins isolated |

### The pristine base venv

```bash
source $CUDA_SAMPLES/python/.venv/bin/activate
pip install -r $CUDA_SAMPLES/python/requirements.txt
```

That is `cuda-python>=13.0.0`, `cuda-core>=1.0.0`, `cupy-cuda13x>=14.0.0`,
`numpy>=2.3.2`. As installed here: cuda-python 13.3.1, cuda-core 1.0.1,
cuda-bindings 13.3.1, cuda-pathfinder 1.6.0, cupy-cuda13x 14.1.1, numpy 2.5.2,
pillow 12.3.0. **Do not add to it.** 24 of the 33 samples run against exactly this.

Verify it is clean at any time:

```bash
$CUDA_SAMPLES/python/.venv/bin/pip freeze
# expect exactly 7 lines; anything more means something leaked in
```

### Creating the isolated environments

Put them outside the project so nothing in the repo tree is mutated:

```bash
export VENVS=/tmp/cuda-venvs        # or anywhere outside $CUDA_SAMPLES
mkdir -p $VENVS

# base + the common extras — covers 9 samples
python3 -m venv $VENVS/venv-extras && $VENVS/venv-extras/bin/pip install \
  'cuda-python>=13.0.0' 'cuda-core>=1.0.0' 'cupy-cuda13x>=14.0.0' 'numpy>=2.3.2' pillow \
  'cuda-cccl[cu13]>=1.0.0' nvtx 'numba-cuda>=0.29.0' 'nvidia-nvjitlink>=13.2.0' torch mpi4py

python3 -m venv $VENVS/venv-nvmath && $VENVS/venv-nvmath/bin/pip install \
  'cuda-python>=13.0.0' 'cuda-core==0.7.0' 'cupy-cuda13x>=14.0.0' 'numpy>=2.3.2' 'nvmath-python[cu13]==0.9.0'

python3 -m venv $VENVS/venv-rapids && $VENVS/venv-rapids/bin/pip install \
  --extra-index-url=https://pypi.nvidia.com \
  'cuda-python>=13.0.0' 'cuda-core<1.0.0' 'cugraph-cu13>=26.0.0' 'cudf-cu13>=26.0.0' \
  'dask-cuda>=26.4.0' 'cupy-cuda13x>=14.0.0' 'numpy>=2.3.2'

python3 -m venv $VENVS/venv-ckpt && $VENVS/venv-ckpt/bin/pip install \
  'cuda-python>=13.0.0,<13.3.0' 'cuda-core>=1.0.0' 'numpy>=2.3.2'

python3 -m venv $VENVS/venv-tf && $VENVS/venv-tf/bin/pip install \
  'numpy>=2.3.2' 'tensorflow>=2.10.0' 'cupy-cuda13x>=14.0.0' 'cuda-python>=13.0.0' 'cuda-core>=1.0.0'
```

### System packages

```bash
sudo apt install openmpi-bin     # supplies mpirun; needed by multiGPUGradientAverage
```

`nsys` is already present at `/usr/local/cuda/bin/nsys`.

## Runnability matrix

Derived by diffing each sample's `requirements.txt` against the installed set, then
confirmed by actually running it. **Every row below was executed.**

| Sample | Venv | Extra deps | Status | Headline result |
|---|---|---|---|---|
| [`deviceQuery`](#devicequery) | `.venv` | — | PASS | sm_120, 70 MPs, 48 MB L2 |
| [`systemInfo`](#systeminfo) | `.venv` | — | PASS | driver 13.3, BLACKWELL |
| [`vectorAdd`](#vectoradd) | `.venv` | — | PASS | 50k elements, 196x256 |
| [`numpyVsCupy`](#numpyvscupy) | `.venv` | — | PASS | **27x** over NumPy |
| [`simplePrint`](#simpleprint) | `venv-extras` | numba-cuda, nvjitlink | PASS | both kernel styles print |
| [`copyImageArraytoGPU`](#copyimagearraytogpu) | `.venv` | — | PASS | mean px 127.33 on GPU |
| [`blurImageUnifiedMemory`](#blurimageunifiedmemory) | `.venv` | — | PASS | writes 2 PNGs |
| [`kernelNsysProfile`](#kernelnsysprofile) | `venv-extras` | nvtx | PASS | 3 kernels verified |
| [`binarySearch`](#binarysearch) | `venv-extras` | cuda-cccl[cu13] | PASS | lower/upper bound OK |
| [`blockwiseSum`](#blockwisesum) | `.venv` | — | PASS | 431.7 GB/s |
| [`cudaComputeLambdas`](#cudacomputelambdas) | `venv-extras` | cuda-cccl[cu13] | PASS | reduce/transform/scan OK |
| [`cudaGraphs`](#cudagraphs) | `.venv` | — | PASS | **1.91x** vs individual launches |
| [`fftSignalAnalysis`](#fftsignalanalysis) | `.venv` | — | PASS | 5/5 tones detected |
| [`greenContext`](#greencontext) | `.venv` | — | PASS *(needs flags)* | **5.88x** critical-kernel latency |
| [`jitLtoLinking`](#jitltolinking) | `.venv` | — | PASS | PTX + LTO both match |
| [`launchConfigTuning`](#launchconfigtuning) | `.venv` | — | PASS | block=64 optimal, **2.36x** |
| [`matrixMulSharedMem`](#matrixmulsharedmem) | `venv-nvmath` | nvmath-python | PASS | cuBLASLt **32,338 GFLOPS** vs custom 4,210 |
| [`memoryResources`](#memoryresources) | `.venv` | — | PASS | 3 resource types verified |
| [`pageRank`](#pagerank) | `venv-rapids` | RAPIDS (cugraph, cudf, dask-cuda) | PASS | **1730x** over CPU reference |
| [`parallelHistogram`](#parallelhistogram) | `.venv` | — | PASS | **89.5x** privatized atomics |
| [`parallelReduction`](#parallelreduction) | `venv-extras` | cuda-cccl | PASS | custom 0.024 ms beats library 0.071 ms |
| [`prefixSum`](#prefixsum) | `venv-extras` | cuda-cccl | PASS | 91.9 M elem/ms |
| [`processCheckpoint`](#processcheckpoint) | `venv-ckpt` | — | PASS | 350 ms checkpoint+restore, hash intact |
| [`reduction`](#reduction) | `.venv` | — | PASS | **752.30 GB/s** |
| [`reductionMultiBlockCG`](#reductionmultiblockcg) | `venv-extras` | cuda-cccl | PASS *(needs flags)* | **708.92 GB/s**, 1 launch |
| [`simpleZeroCopy`](#simplezerocopy) | `.venv` | — | PASS | 0.0 relative error |
| [`streamingCopyComputeOverlap`](#streamingcopycomputeoverlap) | `.venv` | — | PASS | **no speedup** — PCIe-bound |
| [`tmaTensorMap`](#tmatensormap) | `.venv` | — | PASS | TMA runs on sm_120 |
| [`customPyTorchKernel`](#custompytorchkernel) | `venv-extras` | torch | PASS | autograd through custom kernel |
| [`customTensorFlowKernel`](#customtensorflowkernel) | `venv-tf` | tensorflow | PASS | custom ReLU in Keras |
| [`ipcMemoryPool`](#ipcmemorypool) | `.venv` | — | PASS | IPC round-trip OK (1 GPU) |
| [`multiGPUGradientAverage`](#multigpugradientaverage) | `venv-extras` | mpi4py + openmpi-bin | PASS *(needs flags)* | PASS with `mpirun -np 2` |
| [`simpleP2P`](#simplep2p) | `.venv` | — | waived *(1 GPU)* | waives cleanly |
| [`Utilities`](#utilities) | `.venv` | — | library | 3 helper functions |

**32 of 33 samples executed successfully**, each from the venv named in its row —
the base venv was never modified. `simpleP2P` is the sole exception and
it cannot be otherwise: it needs a second GPU, detects that it has one, and waives.
That is the sample working correctly.

Three needed something the README does not make obvious — `greenContext`
(`--split 8,8`), `reductionMultiBlockCG` (two include dirs), and
`multiGPUGradientAverage` (`mpirun`). Each is documented at its own entry in Part IV.

---
