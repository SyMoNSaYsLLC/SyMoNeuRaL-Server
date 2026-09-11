# MIT AI Training — Consolidated Manual

**2026 edition · merged, corrected, and verified on this machine**

This single document replaces eleven separate playbooks and thirty-four separate
sample READMEs. It exists because the original playbooks had drifted: they pointed
at repository paths that no longer exist, told you to build a sample NVIDIA has
since deleted, and quoted generic hardware numbers for a machine nobody owns.

Everything here has been re-checked against the actual clone at
`cuda-samples/` and the actual GPU in this box. Where a number appears, it was
measured on 2026-08-16 and the raw capture is in Appendix A. Where something could
not be verified, Appendix B says so explicitly.

| | |
|---|---|
| **Supersedes** | `00-MANUAL-INDEX.md` … `10-edge-deployment.md` (still on disk, unmodified) |
| **Absorbs** | all 34 READMEs under `cuda-samples/python/` — 33 samples + the `Utilities` package, reproduced in full |
| **Hardware** | NVIDIA GeForce RTX 5070 Ti · Blackwell · sm_120 · 15.9 GiB · driver 610.57.04 / CUDA 13.3 |
| **Verified** | 32 of 33 samples executed successfully; 1 (`simpleP2P`) waives by design on a single-GPU box |

---

## How to read this

1. **[Part I — Your machine](#part-i--your-machine)** — what the hardware actually
   does, measured. Read this first; every performance claim later depends on it.
2. **[Part II — Setup and runnability](#part-ii--setup-and-runnability)** — the
   environments, and a per-sample table of what runs where.
3. **[Part III — The playbooks](#part-iii--the-playbooks)** — the original eleven,
   corrected, each tied to the samples that now demonstrate it.
4. **[Part IV — The CUDA Python curriculum](#part-iv--the-cuda-python-curriculum)** —
   all 34 sample documents, each with a verified *On this box* block.
5. **Appendices** — raw hardware captures, and an honest list of what was not verified.

---

## The five findings that change how you should work on this box

1. **PCIe is your bottleneck, and it is worse than the spec sheet implies.** The
   GPU can do Gen 5. The host caps it at **Gen 3, 8 lanes**. Measured host↔device
   throughput is **~6.9 GB/s up, ~7.2 GB/s down** — about 1% of the GPU's internal
   memory bandwidth. Anything that streams data across PCIe is running on a
   drinking straw.
2. **Once data is resident, the GPU is fast.** Measured **752 GB/s** of real DRAM
   throughput (84% of the 896 GB/s theoretical peak), confirmed independently by
   three different samples. The design rule follows directly: get data onto the
   GPU once, keep it there.
3. **Stream-overlap tuning does nothing here** — `streamingCopyComputeOverlap`
   measured 1.00x / 0.98x / 0.93x for 2 / 4 / 8 streams. Not a bug: transfer so
   dominates compute on a Gen 3 x8 link that there is nothing to hide it behind.
4. **Launch overhead is worth attacking.** CUDA graphs gave **1.91x** on a
   small-kernel loop, and shared-memory privatization gave **89.5x** on histogram
   atomics. Both are bigger wins than any kernel micro-optimisation in the set.
5. **Keep `python/.venv` pristine; isolate every extra.** Nine samples need
   packages beyond `requirements.txt`, and three more (`matrixMulSharedMem`,
   `pageRank`, `processCheckpoint`) carry pins that directly contradict the base
   stack. Worse, `numba-cuda` **silently downgrades numpy 2.5.2 → 2.4.6** if you
   let it into the base environment. Everything extra belongs in its own venv
   outside the project tree — see Part II.

---

# Part I — Your machine

Measured 2026-08-16. Raw captures in [Appendix A](#appendix-a--raw-hardware-captures).

## The GPU

| Property | Value |
|---|---|
| Name | NVIDIA GeForce RTX 5070 Ti |
| Architecture | Blackwell |
| Compute capability | **12.0** (`sm_120`) |
| SMs × cores | 70 × 128 = **8,960** CUDA cores |
| Global memory | 15,858 MB (15.92 GiB) |
| Memory bus | 256-bit |
| Memory clock | 14,001 MHz |
| **Theoretical DRAM bandwidth** | **896.1 GB/s** |
| L2 cache | 48 MB (50,331,648 bytes) |
| Shared memory / block | 48 KB (102,400 B per SM) |
| Max threads / block · / SM | 1,024 · 1,536 |
| Warp size | 32 |
| Copy engines | 2 (concurrent copy + kernel execution) |
| ECC | Disabled |
| Cooperative kernel launch | Supported |
| Managed memory / UVA | Supported |
| VBIOS | 98.03.58.00.23 |
| Power limit | 300 W default (250–330 W range) |
| Driver | 610.57.04 · CUDA driver 13.3 · runtime 13.3 |
| UUID | GPU-15e0078a-cb3a-50d1-a40b-94e4d538fc78 |

## The PCIe ceiling — the most important thing on this page

The original Playbook 01 pasted this and moved on:

```
pcie.link.gen.current, pcie.link.width.current
1, 8
```

That reading is an **idle power-saving state**, not a hardware fact, and treating
it as one is exactly the kind of error this document exists to remove. Here is the
full picture from `nvidia-smi -q`:

```
GPU Link Info
    PCIe Generation
        Max            : 3      <- what this link will ever negotiate
        Current        : 1      <- idle downclock (ASPM)
        Device Current : 1
        Device Max     : 5      <- what the GPU is capable of
        Host Max       : 3      <- what the motherboard offers  <<< the real cap
    Link Width
        Max            : 16x
        Current        : 8x
```

Sampled every 0.4 s during a sustained transfer benchmark, the link trained up to
**Gen 3** and stopped — never Gen 4, never Gen 5, never wider than 8x:

| | idle | under load |
|---|---|---|
| PCIe generation | 1 | **3** (= `Max`, = `Host Max`) |
| Link width | 8x | 8x |
| Power draw | ~12 W | ~57 W |
| Temperature | 44–45 °C | 47–48 °C |

**Gen 3 x8 = 7.88 GB/s theoretical.** Measured, with pinned memory:

| Transfer | Measured | % of Gen 3 x8 peak |
|---|---|---|
| Host → Device (pinned) | **6.94 GB/s** | 88% |
| Host → Device (pageable) | 6.49 GB/s | 82% |
| Device → Host (pinned) | **7.20 GB/s** | 91% |
| Device → Host (pageable) | 7.15 GB/s | 91% |

The link is running at essentially its full Gen 3 x8 capability. There is no
tuning fix — it is the slot. What you can do is stop crossing it: keep working
sets resident in the 15.9 GiB of VRAM.

*(If this is unexpected, it is worth checking whether the card is in the CPU-direct
x16 slot rather than a chipset slot. `Host Max: 3` suggests the platform itself
tops out at Gen 3, but slot choice is the first thing to rule out.)*

## Memory bandwidth — four independent measurements

Since the repository no longer ships `bandwidthTest`, these come from four
different sources, which is a much better check than any single benchmark:

| Source | Measurement | Notes |
|---|---|---|
| CuPy D2D copy, 512 MB | 380.7 GB/s one-way → **761 GB/s DRAM traffic** | a copy reads *and* writes, so DRAM sees 2× |
| `reduction` sample | **752.30 GB/s** | 8.4 M reads, two-stage |
| `reductionMultiBlockCG` sample | **708.92 GB/s** | single launch with `grid.sync()` |
| `alignedTypes` (C++) | 341.5 GB/s one-way → ~683 GB/s | 50 MB working set |

**Use ~750 GB/s as the working figure — 84% of the 896 GB/s theoretical peak.**

### The L2 trap

The same benchmark at different sizes:

| Buffer | D2D reported | What is really happening |
|---|---|---|
| 8 MB | **994 GB/s** | fits entirely in the 48 MB L2 — not a DRAM measurement |
| 32 MB | 493 GB/s | partially cached |
| 128 MB | 380 GB/s | DRAM-bound |
| 512 MB | 380 GB/s | DRAM-bound, stable |

With 48 MB of L2 on this part, **any bandwidth test under ~100 MB is measuring
cache**. This is the single easiest way to publish a wrong number.

## A driver quirk worth knowing

Driver 610 reports stale clocks: `clocks.sm` read **480 MHz while utilization was
100%**, and several clock queries return `Requested functionality has been
deprecated`. Maximum clocks are reported correctly (3,210 MHz SM / 14,001 MHz
memory). **Do not trust `nvidia-smi` instantaneous clock readings on this driver** —
use power draw and achieved throughput as your activity signal instead.

## What this means for AI work

| Situation | Verdict on this box |
|---|---|
| Model fits in 15.9 GiB | Fast. 752 GB/s of weight-reading bandwidth. |
| Model needs CPU offload | Painful. Every offloaded layer crosses a 7 GB/s link. |
| Streaming a dataset from host each step | Bottlenecked on PCIe; pre-stage onto the GPU. |
| Multi-GPU anything | Not testable here — one GPU. |
| Small kernels in a loop | Use CUDA graphs (measured 1.91x). |

Applying the decode-speed formula (`bandwidth ÷ model bytes`) with the **measured**
752 GB/s rather than a spec-sheet number:

| Model @ Q4 | Size | Predicted decode |
|---|---|---|
| 8B | ~4.4 GB | ~170 tok/s |
| 14B | ~7.7 GB | ~98 tok/s |
| 32B | ~17.6 GB | **does not fit** (15.9 GiB) |
| 32B @ IQ2 | ~9.6 GB | ~78 tok/s |

That table is arithmetic, and one row of it has now been tested and is wrong. It said a
large model "does not fit"; the paragraph below is what happened when one was actually
loaded. The table is left standing because the correction is the point.

~~The practical ceiling on this card is a **14B at Q4/Q6, or a 32B at IQ2**.~~ — superseded
by the measurement below. The real ceiling is a **27B at Q2_K**, with room for 64K of
context.

### Measured: Qwen3.6-27B fully resident (2026-08-18)

The "does not fit" row above came from parameter-count arithmetic, never from a load
attempt. This is the load attempt. All figures **measured on this machine**, llama.cpp
build `4df29be`, `llama-bench -p 512 -n 128`, weights
`symon-1.0-27b-q2_k_xl.gguf` (11,849,779,424 bytes on disk):

| | Reading |
|---|---|
| Reported size / params | 11.03 GiB, 26.90 B |
| Offload | `-ngl 99` — every layer on the GPU, no CPU offload |
| Prompt (pp512) | **1537.77 ± 94.82 tok/s** |
| Generation (tg128) | **56.90 ± 0.22 tok/s** |
| Peak VRAM during the bench | **11,916 MiB of 16,303** — at llama-bench's short context, *not* a deployable session |

A 26.9 B model runs fully GPU-resident on a 15.92 GiB card. The engine needed no work:
the GGUF header declares `general.architecture = qwen35` and the local llama.cpp build
already carries `LLM_ARCH_QWEN35`.

**This validates the bandwidth formula, with a correction.** 752 GB/s ÷ 11.85 GB predicts
**63.46 tok/s**; the card delivered **56.90**. The formula is **~11.5% optimistic** — real
decode came in at 90% of predicted. That is one datapoint, not a calibration curve, but it
is the first time any row of the table above has had a measurement to sit next to. Treat
the other predicted rows as similarly optimistic rather than as results.

### Measured: what context fits in the headroom

The 11,916 MiB bench figure is peak at llama-bench's short context and implies more
headroom than a real session has. Every number below is total resident VRAM reported by
`nvidia-smi` with `llama-server` loaded and idle at that context, same weights, `-ngl 99`:

| Context | KV type | Result | Resident VRAM |
|---|---|---|---|
| 8,192 | f16 | loads | 12,354 MiB |
| 16,384 | f16 | loads | 12,874 MiB |
| 32,768 | f16 | loads | 13,914 MiB |
| 32,768 | q8_0 | loads | 13,040 MiB |
| 65,536 | q8_0 | loads | **14,288 MiB** |
| 131,072 | q8_0 | **fails** | — |

The 128K failure is a real allocator error, not a timeout:

```
ggml_backend_cuda_buffer_type_alloc_buffer: allocating 598.50 MiB on device 0:
    cudaMalloc failed: out of memory
llama_init_from_model: failed to initialize the context:
    failed to allocate buffer for rs cache
```

Note what failed: the **recurrent-state cache**, not the KV cache. This architecture is
hybrid, and recurrent state is sized per slot rather than per token, so do not read the 128K
failure as a point on the KV slope below.

KV grows linearly, and the slope is what the rows above actually measure. Taking
differences rather than absolutes (the absolute figures include the weights and the compute
buffers, so only the deltas isolate KV):

- **f16: 63.5 MiB per 1K tokens** — 16K→32K costs 1,040 MiB for 16,384 tokens.
- **q8_0: 38.1 MiB per 1K tokens** — 32K→64K costs 1,248 MiB for 32,768 tokens.

So q8_0 is about 60% the cost of f16 here, not the half you would get from the bit width
alone. At the same 32K context the two differ by a directly measured **874 MiB**
(13,914 vs 13,040), and that saving is what buys the jump from 32K to 64K.

**64K at q8_0 is the largest context that loads**, at 14,288 MiB of 16,303 — about 2 GB of
the card still free.

What this does *not* establish, in order of how likely it is to mislead. It is a
**load-and-idle** measurement: the server allocated the context and sat there, and nothing
here exercises it under generation. Concurrency is untested and matters — that context is a
pool shared across the server's slots, not 64K guaranteed to each simultaneous user. Whether
q8_0 KV degrades output quality is not measured, only that it allocates. And the smaller
quants of this model (UD-IQ2_M at 10.85 GB, UD-IQ2_XXS at 9.39 GB) have not been loaded here;
they are smaller on disk, which is a file size, not a fit.

---

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

# Part III — The playbooks

The original eleven documents, reproduced with corrections applied where they were
wrong. Each carries a header box recording what changed and which samples now
demonstrate its ideas.


<br>

---

> ### Status of this playbook
>
> Unchanged in substance. The dependency map below still holds; what has changed is that Playbooks 01–03 now have runnable, measured backing from the CUDA Python samples instead of generic hardware tables.

## The Local AI Engineer's Manual — 2026 Edition
#### Ten hands-on playbooks that connect into one complete skill set

Each playbook is a lab: stages, runnable commands, and a deliverable. Work them roughly in order — each builds vocabulary and artifacts the next one uses. Done honestly (measure everything, skip nothing), this covers the full territory of running, shrinking, tuning, and deploying serious AI on hardware you own.

---

### Table of Contents

| # | Playbook | The piece of the puzzle it covers |
|---|---|---|
| 00 | **Model Compression Lab** *(already delivered)* | Quantization → pruning → distillation → FPGA. The shrink pipeline. |
| 01 | **Hardware & the Math of Inference** | Why models run at the speed they do. Bandwidth, FLOPs, roofline, sizing models to silicon. |
| 02 | **Transformer Anatomy & Profiling** | What's actually inside the model — attention, FFN, KV cache — and how to measure where time/memory goes. |
| 03 | **Inference Engines Shootout** | llama.cpp vs vLLM vs TensorRT-LLM vs Ollama. Picking and tuning the runtime. |
| 04 | **Fine-Tuning Specialists** | LoRA/QLoRA/DPO — turning a small generalist into an expert on YOUR task. |
| 05 | **Distillation & Synthetic Data** | Using big models to manufacture training data that makes small models punch up. |
| 06 | **KV Cache, Long Context & Memory Tricks** | The hidden memory hog. Paged attention, quantized KV, prompt caching. |
| 07 | **Speed Tricks: Speculative Decoding & Friends** | Getting 2-4x more tokens/sec from the same hardware. |
| 08 | **Local RAG & Embeddings** | Giving small models knowledge without retraining. Vector search on your own machine. |
| 09 | **Agents & Orchestration on Local Models** | Tool use, routing, multi-worker systems with small models. |
| 10 | **Edge Deployment** | Pi, Jetson, phones, pure CPU, ternary models. The last mile. |

---

### The dependency map

```
01 Hardware math ──┐
02 Anatomy ────────┼──► 03 Engines ──► 06 KV cache ──► 07 Speed
                   │
00 Compression ────┼──► 04 Fine-tune ──► 05 Distill
                   │
                   └──► 08 RAG ──► 09 Agents
                              03+00 ──► 10 Edge
```

Read 01 and 02 first — they are the grammar everything else is written in. After that, follow your interest.

### Ground rules for every lab
1. **Measure after every step.** A number you didn't produce yourself is a rumor.
2. **Small victim model first.** Learn the pipeline on a 1B, apply it to the 70B later.
3. **One variable at a time.** Change quant AND engine AND settings together and you learn nothing.
4. **Keep a lab notebook** (a `results.md` per lab) — your own tables become your real manual.
5. **Verify claims against disk state.** Treat "it worked" as a hypothesis.

### Currency note
Written against the state of tooling as of early 2026. Names to watch for drift: llama.cpp quant formats, vLLM flags, ExecuTorch/LiteRT APIs. The *concepts* (bandwidth-bound decoding, calibrated quantization, distillation, paged KV) are stable — when a command dies, the idea it implements is still the thing to search for.


<br>

---

> ### Status of this playbook
>
> **Corrections applied.** This playbook had the most drift of any in the set:
>
> - The bandwidth-measurement step told you to `git clone` cuda-samples and run
>   `cd cuda-samples/Samples/1_Utilities/bandwidthTest && make`. **All three parts are wrong**:
>   `Samples/` is now `cpp/`, the build is CMake not `make`, and `bandwidthTest`
>   has been removed from the repository. Replacement commands are in the box below.
> - The pasted `pcie.link.gen.current = 1` was carried as a hardware fact. It is an
>   idle ASPM reading. The real cap is **Gen 3 x8**, measured under load — see Part I.
> - The hardware table lists a 4090, a 3060 and an M4 Max. Your box is none of them.
>   Part I has the measured equivalent for the 5070 Ti.
> - "performance = mingy(compute ceiling, ...)" — typo for `min(`.
>
> **Measured replacement for the dead bandwidthTest step:**
>
> ```bash
> # GPU global-memory bandwidth (the bandwidthTest replacement in this repo)
> $CUDA_SAMPLES/build/cpp/6_Performance/alignedTypes
>
> # Host<->device and device<->device, via CuPy — size past 100 MB to escape the 48 MB L2
> python - <<'EOF'
> import cupy as cp
> n = 512*1024*1024
> a, b = cp.empty(n, cp.uint8), cp.empty(n, cp.uint8)
> s, e = cp.cuda.Event(), cp.cuda.Event()
> for _ in range(3): cp.copyto(b, a)
> cp.cuda.runtime.deviceSynchronize(); s.record()
> for _ in range(20): cp.copyto(b, a)
> e.record(); e.synchronize()
> ms = cp.cuda.get_elapsed_time(s, e)/20
> print(f"D2D {n/(ms*1e-3)/1e9:.1f} GB/s one-way ({2*n/(ms*1e-3)/1e9:.1f} GB/s DRAM traffic)")
> EOF
> ```
>
> **Measured on this box:** 752 GB/s DRAM, 6.9 GB/s H2D, 7.2 GB/s D2H. Use these,
> not the table below, for any sizing decision on this machine.
>
> **Samples that demonstrate this playbook:** `deviceQuery` and `systemInfo` (Stage 2),
> `numpyVsCupy` (transfer vs compute cost), `reduction` and `reductionMultiBlockCG`
> (achieved bandwidth), `launchConfigTuning` (the roofline in practice).

## Playbook 01 — Hardware & the Math of Inference
#### Why models run at the speed they do, and how to size a model to silicon before downloading a single byte

Most people benchmark by trial and error. You're going to learn the three formulas that predict performance *before* you touch the hardware. This is the highest-leverage knowledge in the whole manual.

---

### Stage 1 — The three numbers that rule everything (30 min, pen and paper)

Every piece of hardware has:
1. **Memory capacity** (GB) — determines what *fits*
2. **Memory bandwidth** (GB/s) — determines decode speed
3. **Compute** (TFLOPS) — determines prefill speed and batch throughput

#### Formula 1: Does it fit?
```
Model VRAM ≈ params × bytes_per_param + KV cache + overhead (~1-2 GB)

FP16: 2 bytes/param    INT8: 1    Q4: ~0.55    IQ2: ~0.3
```
Example: 8B model at Q4 ≈ 8 × 0.55 = **4.4 GB** + KV + overhead → fits in 8 GB.

#### Formula 2: How fast will it generate? (the big one)
Token generation is **memory-bandwidth bound**: every token requires reading ALL weights from memory once.
```
Max tokens/sec ≈ memory_bandwidth (GB/s) ÷ model_size_in_memory (GB)
```
Examples:
| Hardware | Bandwidth | 8B @ Q4 (4.4 GB) | 70B @ Q4 (~38 GB) |
|---|---|---|---|
| RTX 4090 | ~1000 GB/s | ~220 tok/s | doesn't fit |
| RTX 3060 12GB | ~360 GB/s | ~80 tok/s | doesn't fit |
| Apple M4 Max | ~546 GB/s | ~120 tok/s | ~14 tok/s |
| DDR5 desktop (2ch) | ~90 GB/s | ~20 tok/s | ~2.4 tok/s |
| Raspberry Pi 5 | ~17 GB/s | ~4 tok/s (1B model: ~30) | no |

This one formula explains: why quantization speeds up decoding (smaller model = fewer bytes to read), why CPUs with fast RAM are viable, why a 4090 barely beats a 3090 at single-stream decode (similar bandwidth), and why Macs are good at this (unified memory bandwidth).

#### Formula 3: Prefill (prompt processing) is compute-bound
```
Prefill tok/s ≈ compute_TFLOPS × efficiency / (2 × params)
```
Long prompts stress compute; generation stresses bandwidth. Two different bottlenecks — a machine can be great at one and bad at the other.

**Deliverable:** compute predicted tok/s for YOUR GPU and 3 model sizes. Write them down. You'll test them in Stage 3.

---

### Stage 2 — Interrogate your own hardware (30 min)

```bash
# GPU: name, VRAM, and measure real bandwidth
nvidia-smi --query-gpu=name,memory.total,memory.used --format=csv


google  ~/MIT_AI_Training/MIT_AI_Training  10:48  nvidia-smi
Sun Aug 16 10:48:42 2026       
+-----------------------------------------------------------------------------------------+
| NVIDIA-SMI 610.57.04              KMD Version: 610.57.04     CUDA UMD Version: 13.3     |
+-----------------------------------------+------------------------+----------------------+
| GPU  Name                 Persistence-M | Bus-Id          Disp.A | Volatile Uncorr. ECC |
| Fan  Temp   Perf          Pwr:Usage/Cap |           Memory-Usage | GPU-Util  Compute M. |
|                                         |                        |               MIG M. |
|=========================================+========================+======================|
|   0  NVIDIA GeForce RTX 5070 Ti     On  |   00000000:01:00.0 Off |                  N/A |
|  0%   36C    P8              4W /  300W |     240MiB /  16303MiB |      0%      Default |
|                                         |                        |                  N/A |
+-----------------------------------------+------------------------+----------------------+

+-----------------------------------------------------------------------------------------+
| Processes:                                                                              |
|  GPU   GI   CI              PID   Type   Process name                        GPU Memory |
|        ID   ID                                                               Usage      |
|=========================================================================================|
|    0   N/A  N/A            1557      G   /usr/lib/xorg/Xorg                      159MiB |
|    0   N/A  N/A            1672      G   /usr/bin/sddm-greeter-qt6                16MiB |
+-----------------------------------------------------------------------------------------+
google  ~/MIT_AI_Training/MIT_AI_Training  10:48  nvidia-smi --query-gpu=name,memory.total,memory.used --format=csv
name, memory.total [MiB], memory.used [MiB]
NVIDIA GeForce RTX 5070 Ti, 16303 MiB, 240 MiB
google  ~/MIT_AI_Training/MIT_AI_Training  10:51  


# Real memory bandwidth benchmark (CUDA)
git clone https://github.com/NVIDIA/cuda-samples
# DEAD COMMAND — Samples/ is now cpp/, the build is CMake, and
# bandwidthTest was deleted from the repository. See the box above
# for the measured replacement.
# cd cuda-samples/Samples/1_Utilities/bandwidthTest && make && ./bandwidthTest

# CPU RAM bandwidth
sudo apt install sysbench
sysbench memory --memory-block-size=1M --memory-total-size=20G run


Running the test with following options:
Number of threads: 1
Initializing random number generator from current time


Running memory speed test with the following options:
  block size: 1024KiB
  total size: 20480MiB
  operation: write
  scope: global

Initializing worker threads...

Threads started!

Total operations: 20480 (29442.18 per second)

20480.00 MiB transferred (29442.18 MiB/sec)


General statistics:
    total time:                          0.6947s
    total number of events:              20480

Latency (ms):
         min:                                    0.03
         avg:                                    0.03
         max:                                    0.11
         95th percentile:                        0.03
         sum:                                  691.70

Threads fairness:
    events (avg/stddev):           20480.0000/0.00
    execution time (avg/stddev):   0.6917/0.00


# PCIe link speed (matters for CPU-GPU offload splits)
nvidia-smi --query-gpu=pcie.link.gen.current,pcie.link.width.current --format=csv
```
(.venv) google  ~/MIT_AI_Training/MIT_AI_Training  11:37  nvidia-smi --query-gpu=pcie.link.gen.current,pcie.link.width.current --format=csv
pcie.link.gen.current, pcie.link.width.current
1, 8


Also learn the roofline mental model: performance = mingy(compute ceiling, bandwidth × arithmetic intensity). Batch=1 decoding has arithmetic intensity ≈ 1 FLOP/byte → deep in the bandwidth-bound region. Batching raises intensity → moves toward compute-bound → this is why servers batch.

**Deliverable:** a `my-hardware.md` file with your measured bandwidth (GPU and RAM), VRAM, and TFLOPS.

---



### Stage 3 — Predict, then verify (1 hour)

```bash
# Grab two GGUF models of different sizes (e.g., 1B and 8B at Q4_K_M)
# then benchmark with llama.cpp:
./build/bin/llama-bench -m model-8b-q4km.gguf -p 512 -n 128
# -p = prefill test, -n = generation test
```

Compare measured tok/s to your Formula 2 prediction. You should land within ~±25%. If you're way off:
- Much slower than predicted → thermal throttling, PCIe offloading (model didn't fully fit), or background load
- Check offload: `nvidia-smi` during the run; watch for RAM↔VRAM traffic

**Deliverable:** table of predicted vs measured for 2+ models. This calibrates your intuition permanently.

---

### Stage 4 — The sizing decision procedure (the takeaway)

Given a task and a box, run this checklist:
1. Minimum acceptable tok/s? (Chat: 10+. Agents/batch: 5 ok. Coding: 20+ feels right.)
2. Bandwidth ÷ target tok/s = max model bytes you can afford.
3. Max bytes ÷ 0.55 = max params at Q4 (÷ 0.3 for IQ2 if quality allows).
4. Does a model of that size do the task? If not → distill/specialize (Playbook 04/05) or change hardware.
5. Long prompts in the workflow? Check prefill compute too (RAG and agents = long prompts).

#### Hardware cheat sheet (2026-era, single-user inference)
| Box | Sweet spot |
|---|---|
| 8 GB GPU | 7-8B @ Q4, 3B @ Q8 |
| 12-16 GB GPU | 13-14B @ Q4, 8B @ Q6 |
| 24 GB GPU | 32B @ Q4, 70B @ IQ2 (tight) |
| 2× 24 GB | 70B @ Q4 (split) |
| 64-128 GB Mac / DDR5 server | 70B+ @ Q4, slow but roomy |
| Pi 5 / N100 mini-PC | 0.5-3B @ Q4 |

### Iron laws
1. Decode speed = bandwidth ÷ model bytes. Everything else is a footnote.
2. VRAM capacity decides what fits; bandwidth decides how it feels.
3. Prefill and decode are different bottlenecks — benchmark both.
4. A prediction you verified is intuition; one you didn't is superstition.


<br>

---

> ### Status of this playbook
>
> **Still accurate.** The parameter-census and KV-cache maths are architecture
> facts and have not drifted.
>
> **Added:** the profiling stage now has a CUDA-level counterpart. `kernelNsysProfile`
> shows NVTX-annotated phases end to end, and `nsys` is installed at
> `/usr/local/cuda/bin/nsys`:
>
> ```bash
> nsys profile -o /tmp/prof --force-overwrite true python your_script.py
> nsys stats /tmp/prof.nsys-rep
> ```
>
> **Sizing note for this box:** with 15.9 GiB total, the Stage 2 KV-cache maths bites
> early. At 131 KB/token (Llama-3.1-8B, FP16 KV), a 32K context costs 4.3 GB of KV on
> top of the weights — over a quarter of the card before you have loaded anything else.
>
> **Samples that demonstrate this playbook:** `kernelNsysProfile`, `launchConfigTuning`
> (occupancy effects), `memoryResources` (allocator behaviour).

## Playbook 02 — Transformer Anatomy & Profiling
#### Open the hood: what's inside a model, where the bytes live, and how to measure where time goes

You can't optimize what you can't locate. This lab dissects a real model layer by layer, then profiles it, so terms like "FFN", "heads", "KV cache", and "GQA" become things you've measured rather than words you've read.

---

### Stage 1 — Dissect a real model (1 hour)

```python
from transformers import AutoModelForCausalLM
import torch

model = AutoModelForCausalLM.from_pretrained("Qwen/Qwen2.5-1.5B", torch_dtype=torch.float16)
print(model)          # the full architecture tree
cfg = model.config
print(cfg)            # hidden_size, num_layers, num_heads, num_key_value_heads, intermediate_size
```

Now account for every parameter yourself:

```python
def param_census(model):
    buckets = {}
    for name, p in model.named_parameters():
        key = ("embed" if "embed" in name else
               "attn"  if any(k in name for k in ["q_proj","k_proj","v_proj","o_proj"]) else
               "ffn"   if any(k in name for k in ["gate_proj","up_proj","down_proj"]) else
               "norm"  if "norm" in name else "head")
        buckets[key] = buckets.get(key, 0) + p.numel()
    total = sum(buckets.values())
    for k, v in sorted(buckets.items(), key=lambda x: -x[1]):
        print(f"{k:8s} {v/1e6:8.1f}M  {100*v/total:5.1f}%")

param_census(model)
```

What you'll find (roughly, for modern LLMs):
- **FFN ≈ 55-65%** of parameters — the biggest target for pruning/quantization
- **Attention ≈ 20-30%**
- **Embeddings ≈ 5-20%** (huge share in small models — why small models resist compression more)
- Norms ≈ rounding error

Also decode the config: `num_key_value_heads < num_attention_heads` means **GQA** (grouped-query attention) — fewer KV heads = smaller KV cache = cheaper long context. This single config line predicts long-context memory cost.

**Deliverable:** the census table for two models (e.g., 1.5B and 8B) and a sentence on how their proportions differ.

---

### Stage 2 — KV cache math (30 min, calculator)

The forgotten memory consumer. Per token cached:
```
KV bytes/token = 2 (K and V) × num_layers × num_kv_heads × head_dim × bytes_per_value
```
Example, Llama-3.1-8B (32 layers, 8 KV heads, head_dim 128, FP16):
```
2 × 32 × 8 × 128 × 2 = 131 KB/token  →  128K context ≈ 16.8 GB (!)
```
The KV cache of one long conversation can exceed the model itself. This is why Playbook 06 exists.

**Deliverable:** compute KV/token for your favorite model and the context length where KV = model size.

---

### Stage 3 — Profile where time actually goes (1-2 hours)

```python
import torch
from torch.profiler import profile, ProfilerActivity

inputs = tok("The quick brown fox", return_tensors="pt").to("cuda")
model = model.to("cuda")

with profile(activities=[ProfilerActivity.CPU, ProfilerActivity.CUDA]) as prof:
    with torch.no_grad():
        model.generate(**inputs, max_new_tokens=64)

print(prof.key_averages().table(sort_by="cuda_time_total", row_limit=15))
```

What to look for:
- Matmul kernels (gemm/gemv) dominating → normal; that's weight reading
- Lots of tiny kernels + gaps → launch overhead; small models on big GPUs are launch-bound
- Compare a 16-token prompt vs a 4000-token prompt: watch prefill time explode (compute-bound, Playbook 01)

Second lens — watch memory live:
```python
torch.cuda.reset_peak_memory_stats()
model.generate(**long_inputs, max_new_tokens=512)
print(f"Peak VRAM: {torch.cuda.max_memory_allocated()/1e9:.2f} GB")
```
Run with 100-token and 8000-token prompts; the difference is mostly KV cache — your Stage 2 math made visible.

**Deliverable:** profiler table + a peak-VRAM-vs-context-length mini table (4 context lengths).

---

### Stage 4 — What each part does (the mental model to keep)

- **Embedding**: token ID → vector. Lookup table, bandwidth-trivial.
- **Attention (QKV + output proj)**: mixes information *across positions*. The only place tokens talk to each other. Grows with context (via KV cache reads).
- **FFN (gate/up/down)**: per-token computation, where most "knowledge" is stored. No cross-token interaction. Biggest, most prunable, most quantizable.
- **Residual stream**: the shared bus every layer reads/writes. Why you can delete layers and the model degrades gracefully instead of dying.
- **LM head**: final projection to vocabulary. Often tied to embeddings in small models.

Practical consequences you now understand mechanically:
| Observation | Cause |
|---|---|
| Long chats slow down and eat VRAM | KV cache growth, attention reads it every token |
| MoE models are fast for their size | Only some FFN experts read per token → fewer bytes/token |
| Quantizing FFN hurts least, embeddings hurt most | Knowledge is redundant in FFN; embeddings are lookup-precise |
| Pruning targets FFN channels & whole layers | 60% of params, graceful residual-stream degradation |

### Iron laws
1. FFN is where the parameters are; attention is where the interaction is; KV is where the context cost is.
2. KV cache is a first-class memory consumer — budget it like model weights.
3. Profile before optimizing; the bottleneck is usually not where you guessed.
4. Config file → performance prediction. Learn to read configs like spec sheets.


<br>

---

> ### Status of this playbook
>
> **Unverified in this pass.** No engine was installed or benchmarked here, so
> every number in this playbook remains the author's original claim. Treat the
> comparison table as orientation, not as measurement — see Appendix B.
>
> **What this box adds:** two findings from Part I bear directly on engine choice.
>
> 1. **PCIe Gen 3 x8** means llama.cpp partial offload (`-ngl` below the full layer
>    count) is far more expensive here than on a typical benchmark machine. Prefer
>    configurations that fit entirely in VRAM.
> 2. **CUDA graphs gave 1.91x** on a small-kernel loop (`cudaGraphs` sample). Engines
>    that support graph capture are exploiting exactly that mechanism — it is a real
>    effect on this hardware, not a marketing claim.
>
> **Samples that demonstrate this playbook:** `cudaGraphs` (launch-overhead removal),
> `streamingCopyComputeOverlap` (why overlap does not save you here),
> `launchConfigTuning` (per-kernel tuning).

## Playbook 03 — Inference Engines Shootout
#### llama.cpp vs vLLM vs TensorRT-LLM vs Ollama: pick the runtime like an engineer, not a fan

The same model on the same GPU can differ 3x in throughput depending on the engine and its settings. This lab makes you benchmark them yourself and learn what each is actually for.

---

### Stage 0 — The map (10 min read)

| Engine | Built for | Quant formats | Strength | Cost |
|---|---|---|---|---|
| **llama.cpp** | single user, any hardware | GGUF (K-quants, IQ) | runs anywhere, CPU+GPU split, lowest RAM | modest batch throughput |
| **Ollama** | convenience layer over llama.cpp | GGUF | one-command UX, model registry, API | hides tuning knobs, some overhead |
| **vLLM** | serving many requests | GPTQ/AWQ/FP8/some GGUF | paged attention, continuous batching → huge throughput | wants full-GPU residency, heavier install |
| **TensorRT-LLM** | max NVIDIA performance | own compiled engines | fastest single-GPU numbers | painful build, per-GPU compile, NVIDIA only |
| **ExecuTorch / LiteRT** | phones & embedded | int8/int4 | mobile deployment | not for desktops (Playbook 10) |

Decision rule of thumb: **one user → llama.cpp/Ollama; many concurrent requests or agents fanning out → vLLM; squeezing a fixed NVIDIA deployment → TensorRT-LLM.**

---

### Stage 1 — Baseline: llama.cpp done properly (1 hour)

Most people run llama.cpp with defaults and lose 30%+ performance. The knobs that matter:

```bash
./build/bin/llama-server -m model-8b-q4km.gguf \
  -ngl 99          `# layers offloaded to GPU — 99 = all; lower if OOM (partial offload)` \
  -c 8192          `# context size — KV cache is allocated for this; don't overprovision` \
  -fa on           `# flash attention — usually free speed` \
  -b 2048 -ub 512  `# batch sizes for prefill` \
  --port 8080

# Benchmark properly:
./build/bin/llama-bench -m model-8b-q4km.gguf -p 512,4096 -n 128 -ngl 99 -fa 1
```

Experiments to run (change ONE knob at a time, record tok/s):
1. `-ngl 99` vs `-ngl 20` — feel the cliff of partial offload
2. `-fa on` vs off
3. `-c 4096` vs `-c 32768` — watch VRAM, then find the OOM edge
4. Q4_K_M vs Q6_K vs IQ3_XXS of the same model — bandwidth math from Playbook 01 in action

**Deliverable:** your llama.cpp tuning table; a best-config one-liner saved for your box.

---

### Stage 2 — vLLM: throughput mode (1-2 hours)

```bash
pip install vllm

# Serve (AWQ model from Playbook 00 works here)
vllm serve Qwen/Qwen2.5-7B-Instruct-AWQ \
  --max-model-len 8192 \
  --gpu-memory-utilization 0.90
```

The core ideas that make vLLM different:
- **PagedAttention**: KV cache in fixed-size blocks (like OS virtual memory) → near-zero fragmentation → more concurrent sequences fit
- **Continuous batching**: new requests join the running batch mid-flight instead of waiting → GPU never idles

Benchmark single-stream vs many-stream:
```bash
pip install openai
python - <<'EOF'
# Fire N concurrent requests at the OpenAI-compatible endpoint and measure aggregate tok/s
import asyncio, time
from openai import AsyncOpenAI
client = AsyncOpenAI(base_url="http://localhost:8000/v1", api_key="x")

async def one(i):
    r = await client.chat.completions.create(model="Qwen/Qwen2.5-7B-Instruct-AWQ",
        messages=[{"role":"user","content":f"Write 200 words about topic {i}."}], max_tokens=300)
    return r.usage.completion_tokens

async def main(n):
    t0 = time.time()
    toks = await asyncio.gather(*[one(i) for i in range(n)])
    dt = time.time()-t0
    print(f"{n:3d} concurrent: {sum(toks)/dt:7.1f} tok/s aggregate")

for n in (1, 4, 16, 64):
    asyncio.run(main(n))
EOF
```

You should see aggregate throughput scale dramatically with concurrency while llama.cpp's would plateau early. That curve IS the reason vLLM exists.

**Deliverable:** concurrency-vs-throughput table for vLLM and (for contrast) llama.cpp-server at 1/4/16 concurrent.

---

### Stage 3 — The same model, three ways (the shootout, 1 evening)

Pick one model (e.g., 7-8B class). Run the identical prompt set through:
1. llama.cpp (your tuned config, Q4_K_M)
2. Ollama (default) — measure the convenience tax vs #1
3. vLLM (AWQ)
4. (Optional, masochists) TensorRT-LLM — expect hours of build for the best single-stream numbers

Measure for each: single-stream tok/s, time-to-first-token at 4K prompt, aggregate tok/s at 16 concurrent, VRAM used.

**Deliverable:** the shootout table. Keep it — this is the table everyone argues about online and almost nobody has actually produced for their own hardware.

---

### Stage 4 — Choosing, permanently

- Daily driver / chat / one agent → **llama.cpp** tuned, or Ollama if you value convenience over 10-15%
- Agent swarms, batch data processing, serving your LAN → **vLLM**
- Locked deployment, every ms matters, NVIDIA → **TensorRT-LLM**
- Mixing CPU RAM + VRAM to run oversized models → **llama.cpp** partial offload (only game in town)

### Iron laws
1. Engine choice is a workload decision (single vs concurrent), not a fashion decision.
2. Untuned benchmarks are noise. `-ngl`, `-fa`, context size, and quant change everything.
3. Throughput and latency are different sports; know which one you're playing.
4. The convenience layer always costs something — measure the tax, then decide if it's worth it.


<br>

---

> ### Status of this playbook
>
> **Unverified in this pass** — no fine-tuning run was performed. Method unchanged.
>
> **What this box adds:** PyTorch **2.13.0+cu130** installs cleanly and ships an
> `sm_120` binary (`torch.cuda.get_arch_list()` includes `sm_120`), so **no source
> build is needed for Blackwell** — a common worry with new architectures, and one
> you can stop having.
>
> Practical ceiling with 15.9 GiB: QLoRA on a 7–8B model is comfortable; 13–14B is
> tight but feasible with gradient checkpointing and a small batch.
>
> **Samples that demonstrate this playbook:** `customPyTorchKernel` (dropping custom
> CUDA into a torch model with autograd intact).

## Playbook 04 — Fine-Tuning Specialists
#### LoRA, QLoRA, and preference tuning: turning a small generalist into an expert on YOUR task

The cheat code of local AI: a 3B model fine-tuned on your exact task routinely beats a 70B generalist *at that task*. This lab takes you from raw data to a merged, quantized specialist you can serve with the engines from Playbook 03.

---

### Stage 0 — When to fine-tune (and when not to)

Fine-tune when you need: consistent format/style, a narrow skill done reliably, domain vocabulary, or behavior that survives without a giant prompt.
Do NOT fine-tune for: injecting facts that change (use RAG, Playbook 08), one-off tasks (prompt harder), or fixing a model that's simply too small to reason about the task.

Rule: **RAG for knowledge, fine-tuning for behavior.**

---

### Stage 1 — Data is 80% of the outcome (the unglamorous stage)

Target: 500–5,000 examples in chat format. Quality beats quantity below ~10k.

```jsonl
{"messages": [{"role":"system","content":"You are a log-triage assistant."},{"role":"user","content":"<raw log>"},{"role":"assistant","content":"<ideal structured triage>"}]}
```

Sources, in order of value:
1. **Real examples you wrote/approved** — gold
2. **Teacher-generated** (Playbook 05) — a big model produces drafts, you filter
3. Public datasets in your domain — bronze, dedupe and filter hard

Hygiene checklist (do all of these, every time):
- Dedupe near-identical examples (`pip install datasketch` for MinHash, or embedding similarity)
- Hold out 5-10% as a validation set BEFORE looking at training loss
- Read 50 random examples yourself. If 5 are bad, your model will learn bad.
- Balance: if 90% of examples are one subtype, the model becomes that subtype.

**Deliverable:** `train.jsonl` + `val.jsonl` + a paragraph in your lab notebook on where the data came from and what you filtered.

---

### Stage 2 — QLoRA fine-tune (one evening, one consumer GPU)

Why QLoRA: full fine-tuning of even a 7B needs ~80+ GB. QLoRA freezes the model in 4-bit and trains tiny low-rank adapters — a 7-8B fits in ~10-12 GB.

```bash
pip install torch transformers peft trl bitsandbytes datasets
```

```python
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
from peft import LoraConfig
from trl import SFTTrainer, SFTConfig
from datasets import load_dataset
import torch

model_id = "Qwen/Qwen2.5-3B-Instruct"
bnb = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4",
                         bnb_4bit_compute_dtype=torch.bfloat16, bnb_4bit_use_double_quant=True)
model = AutoModelForCausalLM.from_pretrained(model_id, quantization_config=bnb, device_map="auto")
tok = AutoTokenizer.from_pretrained(model_id)

peft_cfg = LoraConfig(
    r=16, lora_alpha=32, lora_dropout=0.05,
    target_modules="all-linear",   # adapters on every linear layer — modern default
    task_type="CAUSAL_LM",
)

data = load_dataset("json", data_files={"train":"train.jsonl","val":"val.jsonl"})

trainer = SFTTrainer(
    model=model, peft_config=peft_cfg,
    train_dataset=data["train"], eval_dataset=data["val"],
    args=SFTConfig(
        output_dir="out-specialist",
        per_device_train_batch_size=2, gradient_accumulation_steps=8,  # effective batch 16
        num_train_epochs=2, learning_rate=2e-4, lr_scheduler_type="cosine",
        warmup_ratio=0.03, bf16=True, logging_steps=10,
        eval_strategy="steps", eval_steps=50, save_strategy="epoch",
        max_length=2048,
    ),
)
trainer.train()
```

Knobs that actually matter (in order): **data quality > learning rate (1e-4–3e-4) > epochs (1-3; watch val loss) > rank r (8-32)**. Everything else is noise at this scale.

Reading the loss curves:
- Train ↓ and val ↓ → keep going
- Train ↓ and val ↑ → overfitting; stop, use the earlier checkpoint, or get more data
- Both flat and high → LR too low, data inconsistent, or task too hard for the base model

**Deliverable:** trained adapter + train/val loss screenshot in your notebook.

---

### Stage 3 — Merge, quantize, serve (1 hour)

```python
# Merge adapter into base weights (load base in fp16 for a clean merge)
from peft import PeftModel
base = AutoModelForCausalLM.from_pretrained(model_id, torch_dtype=torch.float16)
merged = PeftModel.from_pretrained(base, "out-specialist/checkpoint-final").merge_and_unload()
merged.save_pretrained("specialist-merged"); tok.save_pretrained("specialist-merged")
```
```bash
# → GGUF → quantize → serve (Playbooks 00 & 03)
python llama.cpp/convert_hf_to_gguf.py specialist-merged --outfile specialist-f16.gguf
./llama.cpp/build/bin/llama-quantize specialist-f16.gguf specialist-q4km.gguf Q4_K_M
```

**Evaluate like you mean it:** run your held-out val prompts through base-model-vs-specialist side by side. Score them (yourself, or LLM-as-judge — Playbook 05 has the pattern). "It feels better" is not a result.

**Deliverable:** a win/loss/tie count, specialist vs base, on ≥50 held-out prompts.

---

### Stage 4 — Preference tuning with DPO (optional level-up)

When SFT gets the format right but choices wrong (tone, verbosity, judgment calls), train on *pairs*: chosen vs rejected responses.

```jsonl
{"prompt":"...","chosen":"<the answer you prefer>","rejected":"<the plausible but worse answer>"}
```
```python
from trl import DPOTrainer, DPOConfig
trainer = DPOTrainer(
    model=model, peft_config=peft_cfg,
    train_dataset=pairs,
    args=DPOConfig(output_dir="out-dpo", beta=0.1, learning_rate=5e-6,
                   per_device_train_batch_size=1, gradient_accumulation_steps=16, bf16=True),
)
trainer.train()
```
Cheap pair source: your SFT model's near-misses as `rejected`, your corrections as `chosen`. A few hundred good pairs move behavior noticeably.

### Iron laws
1. RAG for knowledge, fine-tuning for behavior.
2. 500 excellent examples beat 50,000 scraped ones.
3. Validation set before training, side-by-side eval after. Loss curves are not product quality.
4. Specialists compress better and run faster than generalists — fine-tuning is a *hardware* strategy, not just a quality one (it's what lets Playbook 00's small models work).


<br>

---

> ### Status of this playbook
>
> **Unverified in this pass.** Method unchanged — the pipeline design and the
> filtering discipline are the durable content here and neither depends on hardware.
>
> **One hardware consequence:** Stage 2 tells you to serve the teacher with vLLM and
> batch through it. On a single 15.9 GiB card the teacher and student cannot both be
> resident, so plan on generating first and training second rather than an online loop.

## Playbook 05 — Distillation & Synthetic Data
#### Using big models to manufacture the training data that makes small models punch above their weight

This is how every strong small model of the 2024-2026 era was actually made. You'll build a teacher→student pipeline: generate data with a large model, filter it ruthlessly, and train your small specialist on it (with Playbook 04's machinery).

---

### Stage 0 — The three flavors of distillation

| Flavor | What transfers | Cost | You'll do it? |
|---|---|---|---|
| **Hard-label** (SFT on teacher outputs) | behavior & skills | cheap — just inference | YES — this lab |
| **Soft-label** (match teacher's full token distributions) | finer-grained knowledge | needs teacher logits + training infra | only if you control both models |
| **On-policy** (teacher corrects the *student's* attempts) | fixes student's actual mistakes | 2x inference, best results | Stage 4, the level-up |

Also check licensing: some hosted-model terms restrict training on outputs. Open-weight teachers (Llama, Qwen, Mistral families) are the clean path for local work.

---

### Stage 1 — Design the data spec before generating anything (1 hour, no code)

Distillation fails in the design, not the training. Write down:
1. **Task definition** — one sentence. "Convert messy shell command descriptions into safe, correct bash one-liners with a one-line explanation."
2. **Input distribution** — what will REAL inputs look like? List 10 subtypes and rough proportions.
3. **Output contract** — exact format, length, tone. Write 5 examples *by hand*. These are your seeds and your quality bar.
4. **Failure catalog** — what does a bad output look like? These become your filters.

**Deliverable:** a `data-spec.md` with all four sections. Twenty minutes here saves days later.

---

### Stage 2 — Generate at scale (1 evening)

Two-step generation beats one-step: first synthesize diverse *inputs*, then have the teacher answer them.

```python
# Step 1: synthesize diverse prompts by remixing dimensions (self-instruct style)
import itertools, random, json

subtypes   = ["file ops", "text processing", "networking", "process mgmt", "archives"]
difficulty = ["simple", "multi-step", "edge-case heavy"]
phrasing   = ["terse", "verbose beginner", "vague"]

seeds = [{"subtype": s, "difficulty": d, "phrasing": p}
         for s, d, p in itertools.product(subtypes, difficulty, phrasing)]

GEN_PROMPT = """Write {n} distinct user requests about {subtype} shell tasks.
Difficulty: {difficulty}. The user writes in a {phrasing} style.
Output one request per line, no numbering."""
# Feed GEN_PROMPT to the teacher for each seed combo → thousands of varied inputs.
```

```python
# Step 2: teacher answers every input, constrained by your output contract
ANSWER_PROMPT = """<your output contract from data-spec.md, verbatim>

User request: {request}"""

# Serve the teacher with vLLM (Playbook 03) and batch through it:
from openai import OpenAI
client = OpenAI(base_url="http://localhost:8000/v1", api_key="x")

def answer(request):
    r = client.chat.completions.create(
        model="teacher", temperature=0.7,
        messages=[{"role": "user", "content": ANSWER_PROMPT.format(request=request)}],
        max_tokens=400)
    return r.choices[0].message.content
```

Practical numbers: 2,000-10,000 pairs is a strong specialist dataset. On a local 70B teacher via vLLM that's an overnight run; via a 32B teacher, an evening.

**Deliverable:** `raw_pairs.jsonl` — thousands of (input, teacher_output) pairs.

---

### Stage 3 — Filter ruthlessly (the step everyone skips, the step that matters most)

Layered filters, cheapest first:

```python
# Layer 1: mechanical — format compliance, length bounds, dedupe
import json, re
from datasketch import MinHash, MinHashLSH

def mechanical_ok(x):
    return (50 < len(x["output"]) < 2000
            and x["output"].count("```") % 2 == 0        # closed code blocks
            and not re.search(r"as an ai|i cannot", x["output"], re.I))

# Layer 2: executable verification (the killer feature when outputs are code)
# Run generated bash in a container; keep only pairs whose command parses/behaves:
#   bash -n script.sh  → syntax check, zero risk
# For math/data tasks: check the answer programmatically.

# Layer 3: LLM-as-judge for the survivors
JUDGE = """Rate this response 1-5 against the contract below. A 5 is flawless.
Contract: <contract>
Request: {inp}
Response: {out}
Reply with only the digit."""
# Keep 4-5 only. Judge with a *different* model than the teacher if possible (bias).
```

Expect to keep 40-70%. If you're keeping 95%, your judge is asleep; if 10%, your generation prompt fights your contract.

**Deliverable:** `train.jsonl` (filtered) + a filter funnel table: generated → after mechanical → after verification → after judge.

---

### Stage 4 — Train, evaluate, and the on-policy loop

1. Train the student on `train.jsonl` (exactly Playbook 04 Stage 2).
2. Evaluate student vs teacher on held-out inputs — win/loss/tie by judge. A good specialist reaches 80-95% of teacher quality *on this task* at 1/20th the size.
3. **On-policy round (the pro move):** collect the student's *failures* from evaluation, have the teacher produce corrected answers for exactly those inputs, add to training data, train one more epoch. One or two rounds of this targets the student's real weaknesses instead of re-teaching what it already knows.

```
generate → filter → train → eval → harvest failures → teacher corrects → retrain
                                  └────────────── the loop ──────────────┘
```

### Iron laws
1. The spec and the filters are the product; generation is the easy part.
2. Verify executably whenever the domain allows it — a compiler is the cheapest, most honest judge.
3. Never let the teacher grade its own homework (different judge model).
4. Distill the task, not the teacher — you want a specialist, not a tiny impressionist.
5. On-policy correction of real student errors beats more random data, every time.


<br>

---

> ### Status of this playbook
>
> **Unverified in this pass** (no llama.cpp runs). Method unchanged.
>
> **Sharper on this box:** the memory budget worksheet in Stage 5 matters more here
> than on a 24 GB card. 15.9 GiB total, and KV cache is the term that grows without
> warning. The samples that make the memory machinery concrete:
>
> **Samples that demonstrate this playbook:** `memoryResources` (device / pinned /
> managed resources side by side), `simpleZeroCopy` (host memory read directly by the
> GPU — and why it is a trap at 7 GB/s), `blurImageUnifiedMemory` (unified memory in
> practice).

## Playbook 06 — KV Cache, Long Context & Memory Tricks
#### Taming the hidden memory hog: quantized KV, paged attention, prompt caching, and honest long-context limits

You computed KV cache size in Playbook 02. Now you'll control it — because for agents and long chats, KV management decides what your hardware can actually do more than model choice does.

---

### Stage 1 — Reproduce the problem (30 min)

```bash
# Same model, two context allocations; watch VRAM (nvidia-smi in another terminal)
./build/bin/llama-server -m model-8b-q4km.gguf -ngl 99 -c 4096
./build/bin/llama-server -m model-8b-q4km.gguf -ngl 99 -c 65536
```
Note the VRAM difference — that's pre-allocated KV. Now feed a genuinely long prompt (paste a long document) and watch tok/s sag as context fills: every new token's attention must read the whole cache. Long context costs memory AND bandwidth.

**Deliverable:** VRAM and tok/s at 4 context fill levels (empty, 8K, 32K, 60K).

---

### Stage 2 — Quantize the KV cache (the free-est lunch here)

Weights aren't the only thing you can quantize:

```bash
# llama.cpp: KV cache in 8-bit or 4-bit (requires flash attention)
./build/bin/llama-server -m model.gguf -ngl 99 -c 32768 -fa on \
  -ctk q8_0 -ctv q8_0     # K and V cache both int8 → KV memory halved
# aggressive: -ctk q4_0 -ctv q4_0  → quarter memory, mild quality risk
```

Rules of thumb from wide community experience:
- **K and V at q8_0**: nearly lossless, use by default when context > 8K
- **V at q4_0**: usually fine; **K at q4_0**: riskier (keys steer attention) — test on YOUR task
- GQA models (Playbook 02) already shrank KV 4-8x architecturally; quantization stacks on top

**Deliverable:** rerun Stage 1's table with q8 KV; add a quality spot-check (same 10 prompts, compare answers).

---

### Stage 3 — Prompt caching: stop paying for the same prefix twice

Agents and RAG resend a giant, mostly-identical prompt every turn. Caching the prefix's KV skips recomputation:

- **llama.cpp server**: caches the common prefix across requests automatically per slot; design prompts so stable parts (system, tools, documents) come FIRST and variable parts (user turn) LAST. Reordering a prompt can cut time-to-first-token 5-10x in agent loops.
- **vLLM**: enable prefix caching:
```bash
vllm serve <model> --enable-prefix-caching
```
  Then measure: send 20 requests sharing a 3K-token system prompt, compare TTFT with and without.

Prompt-structure rule that follows: **immutable → semi-stable → volatile**, top to bottom. Never put a timestamp at the top of a cached prompt (it invalidates everything below it).

**Deliverable:** TTFT with/without caching for a shared-prefix workload — the single most valuable optimization for the agent work in Playbook 09.

---

### Stage 4 — When context runs out anyway: the honest toolbox

1. **Summarize-and-roll**: at ~70% full, summarize the oldest exchanges into a compact note, keep recent turns verbatim. Simple, effective, lossy — the standard for long chats.
2. **Retrieval instead of context** (Playbook 08): don't carry 200K tokens; store them and fetch the relevant 2K.
3. **Context-window extension caution**: models advertise 128K+ but quality at depth varies. Run your own "needle" test — plant 5 facts at different depths in a long document, ask for them, score recall by depth. Trust your table, not the marketing number.
4. **Sliding window / attention sinks**: some models/runtimes keep only recent KV + a few anchor tokens. Good for streams; forgets the middle by design.

**Deliverable:** your needle-test table for your main model (recall at 4 depths × 2 context lengths).

---

### Stage 5 — Memory budget worksheet (keep this)

For any deployment, fill in:
```
VRAM total:                      ______ GB
- Model weights (params×bytes):  ______ GB
- KV: tokens × KV/token (P02):   ______ GB   ← × 0.5 if q8 KV
- Activations/overhead:          ~1-2  GB
= Headroom:                      ______ GB   (negative → smaller quant, less context, or offload)
```
Run this BEFORE downloading. It replaces an afternoon of OOM whack-a-mole.

### Iron laws
1. KV cache is a memory consumer co-equal with weights; budget it explicitly.
2. q8 KV is the default nobody regrets; q4 K needs testing.
3. Cache-friendly prompt order (stable→volatile) is free 5-10x TTFT in loops.
4. Advertised context ≠ usable context. Needle-test it yourself.
5. The best long-context trick is usually not needing long context (summarize or retrieve).


<br>

---

> ### Status of this playbook
>
> **Unverified in this pass** (no draft-model runs). Method unchanged.
>
> **Measured, and directly relevant:** speculative decoding wins by amortising the
> per-token cost of reading weights. Two effects on this box are worth carrying into
> Stage 3's "supporting cast":
>
> - **CUDA graphs: 1.91x measured** on a small-kernel loop. Speculation produces
>   exactly the small-kernel-in-a-loop pattern graphs are best at.
> - With a draft and a target model both resident in 15.9 GiB, budget carefully —
>   an 8B target at Q4 plus a 1B draft at Q4 is about 5 GB before KV.
>
> **Samples that demonstrate this playbook:** `cudaGraphs`, `launchConfigTuning`.

## Playbook 07 — Speed Tricks: Speculative Decoding & Friends
#### 2-4x more tokens/sec from the same silicon, and knowing which trick applies when

Playbook 01 taught you decode speed = bandwidth ÷ model bytes. That's the wall. This lab is about the legal ways around the wall: guessing tokens cheaply and verifying them in bulk, plus the smaller wins that stack.

---

### Stage 0 — Why speculation works (5 min)

Reading all weights once produces ONE token — but verifying N candidate tokens in a single forward pass costs barely more than producing one (the weight-read is shared). So: let a tiny "draft" model guess 4-8 tokens, then have the big model verify them all at once. Accepted tokens are FREE bandwidth-wise. Output is mathematically identical to the big model alone — rejected guesses are simply discarded and regenerated.

Speedup ≈ acceptance_rate × draft_length, minus overhead. Predictable text (code, JSON, formulaic prose) accepts more → speeds up more.

---

### Stage 1 — Draft-model speculation in llama.cpp (1 hour)

Pair a big model with a tiny sibling from the SAME family (tokenizer must match):

```bash
# Example: 8B target + 1B draft (or 32B + 1.5B — bigger gap, bigger win)
./build/bin/llama-server \
  -m  Llama-3.1-8B-Instruct-Q4_K_M.gguf \
  -md Llama-3.2-1B-Instruct-Q4_K_M.gguf \
  -ngl 99 -ngld 99 -fa on \
  --draft-max 8 --draft-min 1

# Benchmark vs no-draft baseline on THREE workload types:
#   1. code generation   2. JSON extraction   3. creative prose
```

Expected pattern: code/JSON 1.8-2.5x, prose 1.2-1.5x, adversarially random text ~1.0x. Tune `--draft-max`: too high wastes draft compute on rejections, too low caps the win. 4-8 is the usual sweet spot.

**Deliverable:** a 3-workload × 2-config (spec on/off) tok/s table, plus your chosen draft-max.

---

### Stage 2 — Self-speculation: n-gram / prompt lookup (free, no draft model)

When output copies from input (editing, extraction, RAG quoting), the "draft" can be substrings of the prompt itself:

```bash
# llama.cpp lookup decoding example binary
./build/bin/llama-lookup -m model.gguf -f long-document.txt \
  -p "Rewrite the above fixing grammar only:" -n 512
```
vLLM equivalent concept: `--speculative-config` with ngram method. Costs nothing (no second model in VRAM) and shines exactly where agents live: tool-output echoing, code edits, structured rewrites.

**Deliverable:** measure an "edit this document" task with and without lookup decoding.

---

### Stage 3 — The supporting cast (stack these)

| Trick | Gain | Where |
|---|---|---|
| Flash attention (`-fa on`) | 10-30% + less VRAM | always-on if supported |
| Right quant for bandwidth (P00/P01) | linear with size | everywhere |
| Batch your own work | huge aggregate | vLLM continuous batching (P03) |
| Prompt caching (P06) | 5-10x TTFT | agent loops, RAG |
| **Structured output / grammars** | fewer wasted tokens + retries | JSON tasks: `--grammar-file json.gbnf` (llama.cpp) or vLLM guided decoding — malformed-output retries are the silent throughput killer |
| Shorter outputs by prompt design | linear | "Answer in ≤3 sentences" is a speed optimization |
| Compile/graph modes (CUDA graphs, TRT-LLM) | 10-40% | fixed deployments |

Also know what does NOT help single-stream decode: more TFLOPS (bandwidth-bound), more CPU cores past memory saturation, PCIe 5 vs 4 when fully GPU-resident.

**Deliverable:** turn on flash attention + a grammar for one JSON workload; record tok/s AND retry-rate before/after.

---

### Stage 4 — The combined build

Assemble your fastest honest config for one real workload (e.g., "code assistant on my 4090"):
```
Q4_K_M weights + q8 KV + flash attn + 1B draft + cached system prompt + grammar for tool calls
```
Measure end-to-end task time (not just tok/s) vs the naive setup from a month ago. 3-5x total is common. Write down the config; that's your production recipe.

### Iron laws
1. Verification is cheap, generation is expensive — that asymmetry is the whole trick.
2. Speculation output = target-model output. It's a free lunch with a VRAM side-dish.
3. The more predictable the text, the bigger the win. Code and JSON love speculation.
4. Wasted tokens (verbose answers, failed parses, retries) are the biggest hidden slowdown — grammars and tight prompts are speed features.
5. Stack tricks; measure the stack, not just the pieces.


<br>

---

> ### Status of this playbook
>
> **Unverified in this pass.** Method unchanged.
>
> **What this box adds:** RAPIDS installs and works here (`pageRank` measured
> **1730x** over a CPU reference). If your retrieval layer outgrows a flat index,
> `cugraph`/`cudf` are a real option on this machine — the install recipe is in Part II.
>
> Note the PCIe caveat: a vector index that lives in host RAM and is queried from the
> GPU will be bottlenecked at ~7 GB/s. Keep the index resident in VRAM if it fits.
>
> **Samples that demonstrate this playbook:** `pageRank` (graph analytics on GPU),
> `fftSignalAnalysis` (GPU preprocessing), `prefixSum` and `parallelHistogram`
> (the primitives under filtering and binning).

## Playbook 08 — Local RAG & Embeddings
#### Giving small models knowledge without retraining: vector search, chunking, and retrieval that actually works, all on your own machine

Fine-tuning (P04) changes behavior; RAG supplies facts. A 3B model with good retrieval beats a 70B reciting from memory on *your* documents. This lab builds the whole pipeline locally and — the part everyone skips — teaches you to measure retrieval quality.

---

### Stage 1 — Embeddings from first principles (1 hour)

```bash
pip install sentence-transformers
```
```python
from sentence_transformers import SentenceTransformer
import numpy as np

# Strong small local embedders (2026-era): bge family, gte family, nomic-embed,
# e5 family. Start ~100-400M params; embedding models are tiny vs LLMs.
model = SentenceTransformer("BAAI/bge-small-en-v1.5")

docs = ["QEMU presents disks via virtio, IDE, or USB passthrough.",
        "Ternary quantization stores weights as -1, 0, +1.",
        "The Panama schedule is a 2-2-3 rotating shift pattern."]
q = "how do virtual machines expose storage devices"

D = model.encode(docs, normalize_embeddings=True)
Q = model.encode([q], normalize_embeddings=True)
print((D @ Q.T).ravel())   # cosine similarities — highest should be doc 0
```

Play: try queries that share NO words with the target doc (semantic match), then queries with shared words but wrong meaning. This calibrates what embeddings can and can't do.

**Deliverable:** 10 query→expected-doc pairs from your own notes; report how many rank #1.

---

### Stage 2 — Chunking: where RAG is won or lost (1 evening)

Documents must be split before embedding. The trade: small chunks = precise retrieval but shattered context; big chunks = context intact but diluted embeddings.

```python
# Solid default: 300-800 token chunks, 10-15% overlap, split on structure first
def chunk(text, target=500, overlap=60):
    import re
    paras = re.split(r"\n\s*\n", text)          # respect paragraph boundaries
    chunks, cur = [], ""
    for p in paras:
        if len((cur + p).split()) > target and cur:
            chunks.append(cur.strip())
            cur = " ".join(cur.split()[-overlap:]) + "\n" + p   # overlap tail
        else:
            cur += "\n\n" + p
    if cur.strip(): chunks.append(cur.strip())
    return chunks
```

Upgrades that matter, in order of value:
1. **Prepend context to every chunk**: `"[{doc_title} > {section}] {chunk}"` — cheap, big retrieval gains
2. **Respect structure**: never split mid-code-block or mid-table; markdown headers are gold
3. Semantic chunking (split at embedding-similarity dips) — marginal gains, try last

**Deliverable:** chunk your real corpus (your VM notes, project docs) two ways (300 vs 800 target), keep both for Stage 4's bake-off.

---

### Stage 3 — The full local stack (1 evening)

```bash
pip install chromadb   # simple local vector DB; alternatives: qdrant, sqlite-vec, faiss
```
```python
import chromadb
client = chromadb.PersistentClient(path="./ragdb")
col = client.create_collection("notes", metadata={"hnsw:space": "cosine"})

col.add(ids=[f"c{i}" for i in range(len(chunks))],
        documents=chunks,
        embeddings=model.encode(chunks, normalize_embeddings=True).tolist(),
        metadatas=[{"source": src} for src in sources])

def retrieve(query, k=5):
    qe = model.encode([query], normalize_embeddings=True).tolist()
    return col.query(query_embeddings=qe, n_results=k)

# Generation: stable prompt order for cache friendliness (Playbook 06!)
PROMPT = """You answer strictly from the provided context. If the context is
insufficient, say so and name what's missing. Cite chunk ids like [c3].

Context:
{context}

Question: {question}"""
```

Two upgrades that separate toy RAG from real RAG:
- **Hybrid search**: dense vectors miss exact identifiers (error codes, function names). Add BM25 keyword search (`pip install rank-bm25`) and merge result lists (reciprocal rank fusion, ~10 lines).
- **Reranking**: retrieve 20 with fast search, rerank to top-5 with a cross-encoder (`sentence_transformers.CrossEncoder`, e.g. bge-reranker). Biggest single quality jump available.

**Deliverable:** working `ask.py` over your own documents with hybrid retrieval + reranker.

---

### Stage 4 — Measure retrieval before blaming the LLM (the discipline)

Most "RAG is bad" is retrieval failure, invisible unless measured separately.

```python
# Gold set: 20-30 (question, ids_of_chunks_that_answer_it) pairs from YOUR corpus
def recall_at_k(gold, k=5):
    hits = sum(any(g in retrieve(q, k)["ids"][0] for g in gold_ids)
               for q, gold_ids in gold)
    return hits / len(gold)
```

Run the bake-off across your variants: small vs large chunks × dense vs hybrid × rerank on/off. Pick the winner on recall@5, THEN judge end-to-end answers.

Triage table when answers are bad:
| Symptom | Layer | Fix |
|---|---|---|
| Right chunk not in top-5 | retrieval | hybrid, rerank, better chunk context |
| Chunk retrieved, answer ignores it | generation | stronger grounding prompt, smaller k, better model |
| Answer invents beyond context | generation | "insufficient context" instruction, cite-required prompt |
| Chunk truncates the needed fact | chunking | bigger chunks or structure-aware splitting |

**Deliverable:** recall@5 table for 4+ configs, and your chosen production config.

### Iron laws
1. RAG quality is decided at chunking and retrieval; the LLM mostly reveals it.
2. Hybrid (dense+keyword) is the default; pure vector search fails on identifiers.
3. Rerankers are the cheapest large quality win in the stack.
4. Measure recall@k with a gold set before touching generation prompts.
5. Stable-prefix prompt layout makes RAG fast (P06) — design for the cache.


<br>

---

> ### Status of this playbook
>
> **Unverified in this pass.** Method unchanged.
>
> **Directly relevant, and measured:** `ipcMemoryPool` **works on this single-GPU box**.
> It is inter-*process*, not inter-*device* — a parent process shares a GPU allocation
> with a child, which is precisely the mechanism you want for multi-worker serving
> where several processes share one loaded model. Do not skip it because it sits in
> the `4_DistributedComputing` folder.
>
> **Samples that demonstrate this playbook:** `ipcMemoryPool` (shared GPU memory
> across worker processes), `greenContext` (partitioning SMs so a latency-critical
> request is not stuck behind a long one — **5.88x** measured), `cudaGraphs`.

## Playbook 09 — Agents & Orchestration on Local Models
#### Tool use, routing, and multi-worker systems built on small models — the engineering, not the hype

An agent is just a loop: model → decides an action → environment executes → result goes back in. Small local models CAN run agents reliably if you engineer the loop for them. This lab builds that loop from scratch, then scales it to routed multi-worker patterns.

---

### Stage 1 — The bare-metal agent loop (build it yourself first, 1 evening)

No framework. Understanding the loop naked is worth more than any library.

```python
import json, subprocess
from openai import OpenAI
client = OpenAI(base_url="http://localhost:8080/v1", api_key="x")  # llama.cpp/vLLM server

TOOLS = [{
  "type": "function",
  "function": {
    "name": "run_bash",
    "description": "Run a read-only shell command and return stdout+stderr.",
    "parameters": {"type": "object",
      "properties": {"command": {"type": "string"}},
      "required": ["command"]}}}]

def run_bash(command):
    # SANDBOX: allowlist, no writes. Never hand a raw shell to a model.
    if any(t in command for t in [">", "rm ", "sudo", "mv ", "curl", "wget"]):
        return "DENIED: read-only tool."
    r = subprocess.run(command, shell=True, capture_output=True, text=True, timeout=15)
    return (r.stdout + r.stderr)[:4000]           # ALWAYS truncate tool output

def agent(task, max_steps=8):
    msgs = [{"role": "system", "content":
             "You solve tasks using tools. Think briefly, act, observe, repeat. "
             "When done, answer with FINAL: <answer>."},
            {"role": "user", "content": task}]
    for step in range(max_steps):
        r = client.chat.completions.create(model="local", messages=msgs,
                                           tools=TOOLS, temperature=0.2)
        m = r.choices[0].message
        if m.tool_calls:
            msgs.append(m)
            for tc in m.tool_calls:
                out = run_bash(**json.loads(tc.function.arguments))
                msgs.append({"role": "tool", "tool_call_id": tc.id, "content": out})
        else:
            return m.content
    return "STOPPED: step budget exhausted."

print(agent("How many .py files under ~/AI_Local_NVIDIA are larger than 10KB?"))
```

The five load-bearing details (each one, removed, breaks small-model agents):
1. **Low temperature** (0-0.3) — agents need determinism, not creativity
2. **Truncated tool output** — one fat `ls -R` can flood the context
3. **Step budget** — small models loop forever without one
4. **Explicit stop token** (`FINAL:`) — an unambiguous exit
5. **Grammar-constrained tool calls** where the engine supports it (P07) — malformed JSON is THE small-model agent failure; grammars eliminate it

**Deliverable:** your loop completing 5 multi-step read-only tasks; note which of the five details each failure traced to when you relax them (do relax them — instructive).

---

### Stage 2 — Reliability engineering (what separates demos from tools)

- **Verify claims against ground truth.** Models report success that didn't happen. After any state-changing action, CHECK: file exists? tests pass? exit code 0? Treat completion as a hypothesis to verify, not a fact to log.
- **Retries with feedback**: on malformed/failed calls, append the error and let it try again (2-3 max), then fail loudly.
- **Structured scratchpad**: for tasks > ~5 steps, have the agent maintain a `STATE.md`/plan it re-reads each step — context is not memory; the file is the memory.
- **Idempotent tools**: design tools so running twice is safe; agents WILL run things twice.
- **Observability**: log every step (prompt, call, result) as JSONL. Debugging agents without transcripts is archaeology without a shovel.

**Deliverable:** add verification + retry + JSONL logging to Stage 1's loop; show one transcript where verification caught a false success.

---

### Stage 3 — Routing: right-size the model per step (the local superpower)

You have MANY models (P00-P04). Route by difficulty instead of paying the big model for everything:

```python
ROUTES = {
    "classify/extract/format":       "qwen2.5-1.5b (or your P04 specialist)",
    "tool-use steps, simple code":   "7-8B class",
    "planning, hard debugging":      "32B+ class (or slow big model on CPU)",
}
# Router = the small model itself with a one-line classification prompt,
# or embeddings + nearest-centroid over example tasks (faster, cheaper).
```

Serve two models at once (e.g., 1.5B always-resident + 8B on demand) with llama.cpp's multi-model support or two servers. Measure: total tokens × model-cost vs single-big-model baseline on a 20-task suite. Typical result: ~70-80% of steps route small with no quality loss on the suite.

**Deliverable:** routing table + before/after cost-quality comparison.

---

### Stage 4 — Multi-worker orchestration (careful, here be dragons)

Patterns that work locally, in ascending complexity:
1. **Pipeline**: fixed stages (extract → transform → verify), each possibly a different model/specialist. Most reliable; start here.
2. **Orchestrator-workers**: a planner decomposes, workers execute in parallel, planner integrates. Use when subtasks are independent.
3. **Reviewer pattern**: generator + a separate verifier model that must approve (different model to avoid self-agreement bias — same principle as P05's judge).

Hard-won rules for multi-worker systems:
- **Single owner per resource.** Two agents writing one file/repo = corruption. Route all writes through one worker; respect the routing protocol even when a shortcut looks faster — raise exceptions with the owner explicitly rather than working around it.
- **Handoffs are documents, not vibes**: a handoff = task, context, acceptance criteria, and current verified state. (Your consolidation-script instinct is exactly right — formalize it.)
- **Shared state lives on disk** (files, sqlite), never in "the conversation."
- Parallelism multiplies throughput AND failure modes; add workers only after the single-agent loop is boringly reliable.

**Deliverable:** a 2-worker pipeline (e.g., small-model extractor → specialist formatter → verifier) with document handoffs, run on a real task from your own projects.

### Iron laws
1. An agent is a loop plus discipline: budget, truncation, verification, logs.
2. Malformed output is the #1 small-model failure — constrain with grammars.
3. Completion claims are hypotheses; disk state is truth.
4. Route by difficulty: most steps are small-model steps.
5. One writer per resource; handoffs as documents; state on disk.
6. Multi-agent is an optimization of a working single agent, never a substitute for one.


<br>

---

> ### Status of this playbook
>
> **Unverified in this pass** — no edge hardware was involved. Method unchanged.
>
> **One note:** this box is the *opposite* of an edge target, and that makes it a good
> place to build the artifacts you then ship. The `processCheckpoint` sample measures
> **350 ms** to checkpoint and restore GPU state, which is the relevant number if you
> ever migrate or preempt a resident model rather than reloading it.
>
> **Samples that demonstrate this playbook:** `processCheckpoint`, `deviceQuery`
> (capability gating before deployment).

## Playbook 10 — Edge Deployment
#### The last mile: Pi, Jetson, mini-PCs, phones, pure CPU, and ternary models

Everything converges here. You have a small specialist (P04/P05), aggressively quantized (P00), and you understand the bandwidth math (P01). Now you put it on hardware that fits in your hand — and verify it earns its watts.

---

### Stage 0 — Match target to expectation (Playbook 01 applied)

| Target | Bandwidth | Realistic 2026 workload |
|---|---|---|
| Raspberry Pi 5 (8/16GB) | ~17 GB/s | 0.5-3B @ Q4: 4-30 tok/s. Classifiers, extractors, home automation brains |
| N100/N150 mini-PC | ~30-38 GB/s | 3-4B comfortable, 7-8B slow-but-usable |
| Jetson Orin Nano/NX | 68-102 GB/s + GPU | 7-8B @ Q4 at chat speed; vision models |
| Modern phone (flagship) | 50-77 GB/s | 1-4B on-device via ExecuTorch/LiteRT |
| Old desktop, DDR4 | ~40-50 GB/s | 7-8B @ Q4 ≈ 8-12 tok/s — don't sneer at e-waste |
| Small FPGA (Zynq) | — | NOT an LLM host. Small quantized CNNs/MLPs (P00 Stage 5) |

Predict tok/s with Formula 2 before buying anything.

---

### Stage 1 — CPU-only mastery with llama.cpp (1 evening, works on everything)

llama.cpp's CPU path is the universal edge runtime. The knobs:

```bash
# Build with native optimizations on the TARGET device
cmake -B build -DCMAKE_BUILD_TYPE=Release && cmake --build build -j

# Run — threads matter enormously:
./build/bin/llama-bench -m qwen2.5-1.5b-q4km.gguf -t 4      # try t = physical cores
# On big.LITTLE ARM (Pi, phones): threads > perf-cores HURTS. Sweep -t 2..8 and graph it.
```

CPU-specific truths:
- Q4_K_M is usually the CPU sweet spot; sub-3-bit quants can be SLOWER on CPU (dequant overhead) while saving RAM — measure, don't assume
- RAM speed ≈ tok/s: on a desktop, enabling XMP/faster DIMMs is a legitimate inference upgrade
- `--mlock` prevents the OS from paging weights out mid-generation

**Deliverable:** thread-sweep graph + quant-format table on your weakest machine.

---

### Stage 2 — Raspberry Pi / mini-PC as an always-on model server (1 evening)

The killer edge pattern isn't chat on the Pi — it's the Pi as a **24/7 specialist endpoint** for your network (your P04 specialist, always on, ~5W).

```bash
# On the Pi (64-bit OS):
sudo apt install -y build-essential cmake git
git clone https://github.com/ggerganov/llama.cpp && cd llama.cpp
cmake -B build -DCMAKE_BUILD_TYPE=Release && cmake --build build -j4

./build/bin/llama-server -m specialist-1.5b-q4km.gguf -t 4 -c 2048 --host 0.0.0.0 --port 8080
```

Make it a service (systemd) so it survives reboots:
```ini
# /etc/systemd/system/llm.service
[Unit]
Description=Edge LLM server
After=network.target
[Service]
ExecStart=/home/pi/llama.cpp/build/bin/llama-server -m /home/pi/models/specialist.gguf -t 4 -c 2048 --host 0.0.0.0 --port 8080
Restart=always
[Install]
WantedBy=multi-user.target
```

Then measure what matters at the edge: sustained tok/s after 10 minutes (thermal throttling is real — add a heatsink), watts at the wall if you have a meter, and requests/day it can absorb. A Pi 5 running a 1.5B specialist handles thousands of extraction/classification calls daily.

**Deliverable:** a systemd-managed endpoint + cold/warm/10-min-sustained tok/s numbers.

---

### Stage 3 — Ternary on CPU: the BitNet path (half a day)

The 2026 frontier of edge inference: models trained ternary (P00 Stage 4) run shockingly fast on plain CPUs because weights are ~1.58 bits and matmuls become add/subtract-dominated.

```bash
git clone https://github.com/microsoft/BitNet && cd BitNet
# Follow repo setup; fetch an official ternary checkpoint (e.g., the 2B-class b1.58 models)
# then benchmark with its CPU inference path and compare against a same-size Q4 GGUF model.
```

What to note: tokens/sec, RAM footprint, and quality on YOUR eval prompts vs a conventional 4-bit peer. Ternary models trade some quality ceiling for radical efficiency — the right call for fixed narrow tasks, wrong for open-ended assistants. This is the technology to track hardest through 2026-27; native ternary + NPUs is where edge is heading.

**Deliverable:** ternary-vs-Q4 comparison table (speed, RAM, quality on 20 prompts).

---

### Stage 4 — Phones & NPUs (survey + one path)

- **ExecuTorch** (PyTorch): export → quantize (int8/int4) → run via Android/iOS runtime with NPU delegates where available
- **LiteRT** (ex-TFLite): mature delegate ecosystem (NNAPI/CoreML/GPU)
- Pragmatic shortcut: several apps wrap llama.cpp on-device (GGUF straight onto the phone) — fine for prototyping before committing to a toolchain
- NPUs (2026 laptops/phones) excel at int8/int4 with vendor toolchains; portability is still rough — budget integration time accordingly

**Deliverable (choose one):** a 1-3B model generating text on an actual phone, whichever path.

---

### Stage 5 — The capstone: end-to-end proof

Combine the entire manual once, small scale, no steps skipped:

1. Pick a real recurring task from your own life/projects (log triage, note tagging, calendar text parsing…)
2. Distill it: teacher generates data (P05) → filter → QLoRA a 1-2B student (P04)
3. Quantize to Q4/IQ3 with imatrix (P00) and needle/eval-test it (P06/P04)
4. Deploy as a systemd endpoint on the smallest box that meets your tok/s floor (P01 math first)
5. Wire one agent or script to call it (P09), with verification
6. Write the one-page postmortem: predicted vs measured at every stage

Finish that and you haven't read about this field — you've done the whole thing, end to end, on hardware you own.

### Iron laws
1. Bandwidth math first, purchase second.
2. Sustained (thermal-throttled) performance is the real number at the edge.
3. On CPU, the fastest quant is not always the smallest — measure dequant overhead.
4. The edge pattern that wins is the always-on specialist endpoint, not chat on a Pi.
5. Ternary + NPU is the trajectory; build the skills now on BitNet-class tools.


---

# Part IV — The CUDA Python curriculum

All 34 sample documents. Each README is reproduced **in full and unaltered** except
for heading depth and corrected `cd` paths. Each is preceded by an **On this box**
block recording the exact command run and the actual result — no predicted output.


## 1_GettingStarted — Getting started

Eight samples covering device discovery, your first runtime-compiled kernel, host↔device transfer, unified memory and profiling. Work these in the order listed.

<br>

### deviceQuery

> #### On this box
>
> **Command**
> ```bash
> cd $CUDA_SAMPLES/python/1_GettingStarted/deviceQuery
> python deviceQuery.py
> ```
>
> **Result** — PASS. Reports sm_120, 70 MPs, 15858 MB global, 256-bit bus, 48 MB L2, 2 copy engines, ECC disabled, cooperative launch supported.
>
> *Wall time: 0.6 s*
>
> **Notes** — The C++ twin is already built: `$CUDA_SAMPLES/build/cpp/1_Utilities/deviceQuery/deviceQuery`. Run both — the Python one uses `cuda.core`, the C++ one the runtime API, and they agree.

<details>
<summary><b>Full README — deviceQuery</b></summary>

#### Sample: Device Query (Python)

##### Description

Query and display detailed properties of all CUDA-capable devices in your system using the modern `cuda.core` API.

##### What You'll Learn

- How to enumerate CUDA devices in the system
- Using the `cuda.core` API for device management
- Querying comprehensive device properties (compute capability, memory, limits)
- Accessing low-level device attributes via `cuda.bindings`
- Checking peer-to-peer (P2P) access capabilities between GPUs

##### Key Libraries

- `cuda.core` - Modern CUDA Python API
- `cuda.bindings` - Low-level CUDA bindings for runtime and driver APIs

##### Key APIs

###### From `cuda.core`:

- `Device.get_all_devices()` - Get tuple of all available Device instances
- `Device(device_id)` - Get Device object for specific device ID
- `system.get_driver_version()` - Query CUDA driver version
- `Device.set_current()` - Set the current device for API calls
- `Device.properties` - Access comprehensive device properties
- `Device.name` - Get device name string
- `Device.can_access_peer()` - Check P2P access to peer device

###### From `cuda.bindings.runtime`:

- `cudart.cudaRuntimeGetVersion()` - Get CUDA runtime version
- `cudart.cudaDeviceGetAttribute()` - Query specific device attributes

###### From `cuda.bindings.driver`:

- `cuda.cuMemGetInfo()` - Get memory information for current device

##### Device Properties Queried

###### Compute Capabilities:
- Compute capability version (major.minor)
- Driver and runtime versions
- Number of multiprocessors and CUDA cores

###### Memory Information:
- Total global memory
- Memory clock rate and bus width
- L2 cache size
- Constant and shared memory sizes
- Maximum memory pitch

###### Execution Configuration Limits:
- Maximum threads per block and per multiprocessor
- Maximum block dimensions (x, y, z)
- Maximum grid dimensions (x, y, z)
- Warp size
- Registers per block

###### Texture Capabilities:
- Maximum texture dimensions (1D, 2D, 3D)
- Maximum layered texture sizes

###### Feature Support:
- Unified Addressing (UVA)
- Managed Memory
- Compute Preemption
- Cooperative Kernel Launch
- ECC support
- Host page-locked memory mapping
- Concurrent copy and kernel execution

###### System Information:
- PCI bus information
- Compute mode
- Driver mode (Windows only)
- P2P access matrix (multi-GPU systems)

##### Requirements

###### Hardware:

- NVIDIA GPU with CUDA support (any compute capability)
- No specific GPU memory requirement (query only)

###### Software:

- CUDA Toolkit 13.0 or newer (recommended; matches `cuda-python` 13.x)
- Python 3.10 or newer
- `cuda-python` package (>=13.0.0)
- `cuda-core` package (>=1.0.0)

##### Installation

Install the required packages from requirements.txt:

```bash
cd $CUDA_SAMPLES/python/1_GettingStarted/deviceQuery
pip install -r requirements.txt
```

The requirements.txt installs:
- `cuda-python` (>=13.0.0)
- `cuda-core` (>=1.0.0)

##### How to Run

###### Basic usage:

```bash
cd $CUDA_SAMPLES/python/1_GettingStarted/deviceQuery
python deviceQuery.py
```

###### Skip P2P information:

```bash
python deviceQuery.py --no-p2p
```

##### Expected Output

```
[CUDA Device Query using CUDA Core API]
Detected 1 CUDA Capable device(s)

Device 0: <Your GPU Name>
  CUDA Driver Version / Runtime Version          12.4 / 12.6
  CUDA Capability Major/Minor version number:    8.9
  Total amount of global memory:                 24217 MBytes (25393954816 bytes)
  (132) Multiprocessors, (128) CUDA Cores/MP:    16896 CUDA Cores
  GPU Max Clock rate:                            1980 MHz (1.98 GHz)
  Memory Clock rate:                             10501 Mhz
  Memory Bus Width:                              384-bit
  L2 Cache Size:                                 67108864 bytes
  Maximum Texture Dimension Size (x,y,z)         1D=(131072), 2D=(131072, 65536), 3D=(16384, 16384, 16384)
  Maximum Layered 1D Texture Size, (num) layers  1D=(32768), 2048 layers
  Maximum Layered 2D Texture Size, (num) layers  2D=(32768, 32768), 2048 layers
  Total amount of constant memory:               65536 bytes
  Total amount of shared memory per block:       49152 bytes
  Total shared memory per multiprocessor:        102400 bytes
  Total number of registers available per block: 65536
  Warp size:                                     32
  Maximum number of threads per multiprocessor:  1536
  Maximum number of threads per block:           1024
  Max dimension size of a thread block (x,y,z):  (1024, 1024, 64)
  Max dimension size of a grid size    (x,y,z):  (2147483647, 65535, 65535)
  Maximum memory pitch:                          2147483647 bytes
  Texture alignment:                             512 bytes
  Concurrent copy and kernel execution:          Yes with 2 copy engine(s)
  Run time limit on kernels:                     Yes
  Integrated GPU sharing Host Memory:            No
  Support host page-locked memory mapping:       Yes
  Device has ECC support:                        Enabled
  Device supports Unified Addressing (UVA):      Yes
  Device supports Managed Memory:                Yes
  Device supports Compute Preemption:            Yes
  Supports Cooperative Kernel Launch:            Yes
  Device PCI Domain ID / Bus ID / location ID:   0 / 1 / 0
  Compute Mode:
     < Default (multiple host threads can use cudaSetDevice() with device simultaneously) >

Done
```

**Note:** Output will vary based on your specific GPU model and system configuration.

For multi-GPU systems, the output will include information for all detected devices and a P2P access matrix showing which GPUs can directly access each other's memory.

##### Files

- `deviceQuery.py` - Python implementation using cuda.core API
- `requirements.txt` - Sample dependencies

##### Use Cases

- **System Diagnostics** - Verify CUDA installation and GPU detection
- **Hardware Profiling** - Understand GPU capabilities before optimization
- **Multi-GPU Systems** - Identify P2P topology for optimal data placement
- **Kernel Development** - Determine execution configuration limits
- **Compatibility Checks** - Verify compute capability requirements

##### See Also

- [CUDA Python Documentation](https://nvidia.github.io/cuda-python/)
- [cuda.core API Guide](https://nvidia.github.io/cuda-python/cuda-core/latest/)
- [CUDA Programming Guide - Device Information](https://docs.nvidia.com/cuda/cuda-c-programming-guide/index.html#device-enumeration)


</details>

<br>

### systemInfo

> #### On this box
>
> **Command**
> ```bash
> cd $CUDA_SAMPLES/python/1_GettingStarted/systemInfo
> python systemInfo.py
> ```
>
> **Result** — PASS. Driver 13.3 user-mode / 610.57.4 kernel-mode, NVML (13,610,57,4), branch r610_85, BLACKWELL, 15.92 GiB.
>
> *Wall time: 0.2 s*
>
> **Notes** — Fastest sanity check that the driver stack is alive. `5070ti.txt` in this folder is a saved run from this very box.

<details>
<summary><b>Full README — systemInfo</b></summary>

#### Sample: System Information Query (Python)

##### Description

This sample demonstrates how to inspect the CUDA driver, NVML, and every
installed GPU through the
[`cuda.core.system`](https://nvidia.github.io/cuda-python/cuda-core/latest/)
module.

`cuda.core.system` wraps the NVIDIA Management Library (NVML) and can be
imported without CUDA being installed or initialized, so it is useful as a
lightweight pre-flight check before any CUDA context is created. The script
prints driver and NVML versions, the current process name, per-device
metadata (name, compute capability, architecture, memory, PCI info,
temperature, performance state), and, on multi-GPU systems, the topology
and peer-to-peer capabilities between each pair of devices.

##### What You'll Learn

- Querying CUDA driver and NVML versions with `cuda.core.system`
- Enumerating GPUs without creating a CUDA context
- Reading per-device metadata exposed by NVML (name, UUID, memory usage,
  temperature, performance state)
- Inspecting GPU-to-GPU topology and peer-to-peer (P2P) capabilities

##### Key Libraries

- [`cuda.core.system`](https://nvidia.github.io/cuda-python/cuda-core/latest/) - Python wrapper around NVML

##### Key APIs

From `cuda.core.system`:

- `get_driver_version()`, `get_driver_version_full()`, `get_driver_branch()` - CUDA driver version tuple and branch string
- `get_nvml_version()` - NVML library version
- `get_num_devices()` - number of GPUs visible to NVML
- `get_process_name(pid)` - process name for a given PID
- `Device(index=...)` - NVML-backed device handle (no CUDA context required)
  - `name`, `uuid`, `cuda_compute_capability`, `arch`, `brand`
  - `memory_info` (`total`, `used`, `free`)
  - `pci_info` (`domain`, `bus`, `device`, `bus_id`)
  - `temperature.sensor(TemperatureSensors.TEMPERATURE_GPU)`
  - `performance_state`
- `get_topology_common_ancestor(dev0, dev1)` - `GpuTopologyLevel` between two devices
- `get_p2p_status(dev0, dev1, GpuP2PCapsIndex.P2P_CAPS_INDEX_READ)` - peer-access capability between two devices

Import stable symbols from the top-level `cuda.core` package (not `cuda.core.experimental`).

##### Requirements

1. **NVIDIA Graphics Card** with CUDA support
2. **CUDA Drivers** installed on your system
3. **CUDA Toolkit** installed on your system
4. **Python 3.12 or newer**

###### Hardware

- One or more NVIDIA GPUs
- Driver compatible with `cuda-python` 13.x

###### Software

- CUDA Toolkit 13.0 or newer (matches `cuda-python` 13.x)
- Python 3.10 or newer
- `cuda-python` (>=13.0.0)
- `cuda-core` (>=1.0.0)

##### Installation

Install the required packages from `requirements.txt`:

```bash
cd $CUDA_SAMPLES/python/1_GettingStarted/systemInfo
pip install -r requirements.txt
```

The `requirements.txt` installs:

- `cuda-python` (>=13.0.0)
- `cuda-core` (>=1.0.0)

##### How to Run

###### Basic usage

```bash
cd $CUDA_SAMPLES/python/1_GettingStarted/systemInfo
python systemInfo.py
```

###### Skip topology queries

Useful on machines with only one GPU or to shorten the output:

```bash
python systemInfo.py --no-topology
```

##### Expected Output

Output varies with your hardware. On a machine with two GPUs you should see
something like:

```
======================================================================
Driver / NVML
======================================================================
CUDA driver version: 13.2
CUDA driver version (full): (13, 2, 0)
NVML version: (13, 595, 58, 3)
Driver branch: r595_88
Current process: /usr/bin/python

======================================================================
Devices detected: 2
======================================================================

-- Device 0 --
Name: <Your GPU Name>
UUID: ...
Compute capability: 8.9
Architecture: ADA
Brand: BRAND_GEFORCE
Memory: total=23.99 GiB, used=960.00 KiB, free=23.52 GiB
PCI: domain=0000 bus=41 device=00 id=00000000:41:00.0
Temperature (GPU sensor): 47 C
Performance state: <Pstates.PSTATE_8: 8>

...

======================================================================
GPU topology and peer-to-peer
======================================================================
Device 0 <-> Device 1: topology=TOPOLOGY_HOSTBRIDGE, p2p_read=..., p2p_write=...

Done
```

**Note:** Device names, compute capability, temperatures, and topology
details will vary based on your GPUs and system.

##### Files

- `systemInfo.py` - Python implementation using `cuda.core.system`
- `README.md` - This file
- `requirements.txt` - Sample dependencies

##### See Also

- [CUDA Python Documentation](https://nvidia.github.io/cuda-python/)
- [`cuda.core.system` API reference](https://nvidia.github.io/cuda-python/cuda-core/latest/api.html)
- [NVML reference](https://docs.nvidia.com/deploy/nvml-api/)


</details>

<br>

### vectorAdd

> #### On this box
>
> **Command**
> ```bash
> cd $CUDA_SAMPLES/python/1_GettingStarted/vectorAdd
> python vectorAdd.py
> ```
>
> **Result** — Test PASSED. Compiled `vectorAdd<float>` for sm_120 at runtime, 196 blocks x 256 threads over 50000 elements.
>
> *Wall time: 3.6 s*
>
> **Notes** — First run costs ~3.6 s almost entirely in NVRTC compilation, not in the kernel. That compile cost is why `cudaGraphs` and `jitLtoLinking` exist.

<details>
<summary><b>Full README — vectorAdd</b></summary>

#### Sample: Vector Addition (Python)

##### Description

Run your first GPU kernel: add two vectors element-wise on the GPU using the [`cuda.core`](https://nvidia.github.io/cuda-python/cuda-core/latest/) API with runtime compilation.

##### What You'll Learn

- Writing CUDA kernels in C++ with template support
- Runtime compilation of CUDA kernels from Python
- Using `cuda.core` for device management, programs, and launches
- Configuring and launching kernels with grid and block dimensions
- Using CuPy for GPU memory management
- Verifying GPU results against CPU computation

##### Key Libraries

- [`cuda.core`](https://nvidia.github.io/cuda-python/cuda-core/latest/) — Pythonic access to CUDA runtime and compilation
- `cupy` — GPU array library for Python

##### Key APIs

###### From `cuda.core`

- `Device` — Initialize and manage CUDA device
- `Program` — Create program from kernel source code
- `ProgramOptions` — Set compilation options (C++ standard, architecture)
- `LaunchConfig` — Configure kernel launch parameters
- `launch` — Execute kernel on specified stream

Import stable symbols from the top-level package (not `cuda.core.experimental`). See the [cuda.core documentation](https://nvidia.github.io/cuda-python/cuda-core/latest/).

###### From CuPy

- `cp.random.rand()` — Generate random arrays on GPU
- `cp.empty()` — Allocate uninitialized GPU arrays
- `cp.allclose()` — Verify results with tolerance

###### From `cuda_samples_utils`

- `verify_array_result()` — Verify computation results

##### Kernel Techniques

- **1D Grid-Stride Loop** — Handle arbitrary array sizes with fixed grid
- **Template Programming** — Generic kernel for different data types
- **Bounds Checking** — Prevent out-of-bounds memory access

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

Install the required packages from requirements.txt:

```bash
cd $CUDA_SAMPLES/python/1_GettingStarted/vectorAdd
pip install -r requirements.txt
```

The requirements.txt installs:

- `cuda-python` (>=13.0.0)
- `cuda-core` (>=1.0.0)
- `cupy-cuda13x` (>=14.0.0)

##### How to Run

###### Basic usage

```bash
cd $CUDA_SAMPLES/python/1_GettingStarted/vectorAdd
python vectorAdd.py
```

###### With custom parameters

```bash
# Custom vector size
python vectorAdd.py --elements 1000000

# Use specific GPU
python vectorAdd.py --device 1

# Skip verification for benchmarking
python vectorAdd.py --no-verify
```

##### Expected Output

```
[Vector addition using CUDA Core API]
Device: <Your GPU Name>
Compute Capability: sm_<XX>
Compiling kernel 'vectorAdd<float>'...
Kernel compiled successfully
[Vector addition of 50000 elements]
CUDA kernel launch with 196 blocks of 256 threads
Verifying result...
Test PASSED

Done
```

**Note:** Device name and compute capability will vary based on your GPU.

##### Files

- `vectorAdd.py` — Python implementation using cuda.core API
- `README.md` — This file
- `requirements.txt` — Sample dependencies
- `../../Utilities/cuda_samples_utils.py` — Common utilities (imported by this sample)

##### See Also

- [CUDA Python Documentation](https://nvidia.github.io/cuda-python/)
- [cuda.core API](https://nvidia.github.io/cuda-python/cuda-core/latest/)
- [CuPy Documentation](https://docs.cupy.dev/)


</details>

<br>

### numpyVsCupy

> #### On this box
>
> **Command**
> ```bash
> cd $CUDA_SAMPLES/python/1_GettingStarted/numpyVsCupy
> python numpyVsCupy.py
> ```
>
> **Result** — PASS. 4096x4096 dot: NumPy 0.518 s vs CuPy 0.0189 s = **27x**. Host->device transfer of the two arrays cost 0.090 s.
>
> *Wall time: 1.9 s*
>
> **Notes** — Note the transfer line: 0.090 s to move the inputs, 0.019 s to do the maths. On this box the PCIe Gen 3 x8 link (see Appendix A) makes transfer 4.8x more expensive than the compute. Keep data resident on the GPU.

<details>
<summary><b>Full README — numpyVsCupy</b></summary>

#### Sample: Numpy vs. Cupy (Python)

##### Description

This sample demonstrates performance comparison between NumPy (CPU) and CuPy (GPU) for matrix multiplication operations. It benchmarks the execution time of matrix dot products on both CPU and GPU, showing the performance benefits of GPU acceleration for numerical computations.

##### What you will learn

- How to set up and use CuPy for GPU-accelerated numerical computations.
- How to benchmark NumPy vs CuPy performance for matrix operations.
- How to transfer data between CPU (NumPy) and GPU (CuPy) memory using `cp.asarray()`.
- How to use CUDA device management with the cuda-core library.
- How to validate computational results between CPU and GPU implementations using `np.testing.assert_allclose()`.
- How to handle GPU warmup to avoid first-run overhead in benchmarking.
- How to create and manage explicit CUDA streams with `device.create_stream()`.
- How to properly cleanup streams with `stream.close()` in try/finally blocks.
- How to access GPU device information (name, compute capability).
- How to create timing context managers for performance measurement using CUDA events.

##### Key libraries

- `numpy`
- `cupy`
- `cuda-core`

##### Key APIs

**From cuda.core:**
- `Device()` – Get CUDA device object for specific GPU
- `device.create_stream()` – Create explicit CUDA stream
- `stream.close()` – Close and cleanup stream resources

##### Requirements
1. **NVIDIA Graphics Card** with CUDA support
2. **CUDA Drivers** installed on your system
3. **CUDA Toolkit** installed on your system
4. **Python 3.12 or newer**

**Install packages:**
```bash
pip install -r requirements.txt
```

##### How to run

Basic usage:
```bash
# Pre-steps:
export LD_LIBRARY_PATH=/usr/local/cuda/lib64:$LD_LIBRARY_PATH
# Run from the Python directory:
cd $CUDA_SAMPLES/python/1_GettingStarted/numpyVsCupy
python -m 1_GettingStarted.numpyVsCupy.numpyVsCupy
```

With custom parameters:
```bash
python -m 1_GettingStarted.numpyVsCupy.numpyVsCupy --n_size 5000
```

###### Command line arguments

- `--n_size`, `-n`: Size of the matrix (n * n) for benchmarking (default: 4096)

##### Expected Output
```
Validation PASSED: NumPy and CuPy results match within tolerance
Demo completed successfully!
```

##### Files
- `numpyVsCupy.py` – Python implementation
- `README.md` – This file
- `requirements.txt` – Required packages


</details>

<br>

### simplePrint

> #### On this box
>
> **Command**
> ```bash
> cd $CUDA_SAMPLES/python/1_GettingStarted/simplePrint
> source $VENVS/venv-extras/bin/activate      # isolated: base + cuda-cccl, nvtx, numba-cuda, torch, mpi4py
> python simplePrint.py
> ```
>
> **Result** — PASS. Both the `cuda.core` kernel and the Numba `cuda.grid(3)` kernel printed their block/thread IDs.
>
> *Wall time: 0.9 s*
>
> **Notes** — **Never install `numba-cuda` into the base venv.** It pins `numpy<2.5` and will silently downgrade a clean 2.5.2 install to 2.4.6. Run it from `$VENVS/venv-extras` instead, where the downgrade is contained and harmless.

<details>
<summary><b>Full README — simplePrint</b></summary>

#### simplePrint - Printing from CUDA Kernels

##### Description

This sample demonstrates how to use `printf()` inside CUDA kernels using **two different approaches**:

1. **CUDA C++ kernels** compiled with `cuda.core.Program` - Full C++ features and control
2. **Numba CUDA kernels** - Pythonic kernel authoring using `numba.cuda.grid()` for modern indexing

The sample shows basic device management, kernel compilation with inline CUDA C++ code, and multi-dimensional kernel launches (2D grid × 3D blocks) using modern CUDA Python. The Numba example demonstrates the recommended `numba.cuda.grid()` indexing style while also showing how it relates to classic CUDA C++ block/thread IDs. Both approaches use `cuda.core` APIs for stream management and synchronization, demonstrating interoperability.

This is the Python equivalent of the C++ `simplePrintf` sample, enhanced with Numba CUDA examples.

##### Key Concepts

CUDA Python (cuda.core), Numba CUDA, Kernel Compilation, Printf in Kernels, Multi-dimensional Launch, Pythonic GPU Programming, Modern Thread Indexing (grid()), Stream-based Execution, cuda.core/Numba Interoperability

##### CUDA APIs involved

###### [cuda.core (cuda-python)](https://nvidia.github.io/cuda-python/)

- `Device()` - Device management
- `Device.create_stream()` - Create CUDA streams
- `Stream.sync()` - Synchronize stream execution
- `Program()` - Compile CUDA C++ kernels
- `LaunchConfig()` - Configure kernel launch
- `launch()` - Execute kernels on streams

###### [Numba CUDA](https://nvidia.github.io/numba-cuda/)

- `@cuda.jit` - JIT compile Python functions to CUDA kernels
- `cuda.grid()` - Get global thread position (recommended modern approach)
- `cuda.blockIdx`, `cuda.threadIdx` - Thread/block indices (classic style)
- `cuda.gridDim`, `cuda.blockDim` - Grid/block dimensions
- **Note:** Uses `cuda.core` APIs for stream management (interoperability)

###### CUDA Kernel Functions

- `printf()` - Print from device code (C++)
- `print()` - Print from device code (Numba, limited formatting)
- `blockIdx`, `threadIdx` - Thread/block indices
- `gridDim`, `blockDim` - Grid/block dimensions

###### What You Learn

- Device initialization with `cuda.core.Device`
- Compiling CUDA C++ kernels with `Program` and `ProgramOptions`
- Writing Pythonic CUDA kernels with Numba's `@cuda.jit` decorator
- Using `numba.cuda.grid()` for modern thread indexing (recommended approach)
- Understanding the relationship between global coordinates and classic block/thread IDs
- **Interoperability**: Using `cuda.core` streams with Numba CUDA kernels
- Comparing CUDA C++ vs Pythonic kernel authoring approaches
- Multi-dimensional kernel launches (2D grid, 3D blocks)
- Using streams for kernel execution and synchronization
- Using `printf()` and `print()` in GPU kernels for debugging
- Understanding print limitations in Numba CUDA (no f-strings)
- Proper error handling and resource management

##### Requirements

###### Hardware:

- NVIDIA GPU with Compute Capability 7.0 or higher
- Minimum GPU memory: 512 MB

###### Software:

- CUDA Toolkit 13.0 or newer
- Python 3.10 or newer
- `cuda-python` package (13.0+)
- `cuda-core` package (>=1.0.0)
- `numba-cuda` package (0.24.0+, for Pythonic kernel authoring)

Download and install:
- [CUDA Toolkit](https://developer.nvidia.com/cuda-downloads)
- [cuda-python package](https://nvidia.github.io/cuda-python/): `pip install cuda-python`
- [numba-cuda](https://nvidia.github.io/numba-cuda/): `pip install numba-cuda`

##### Build and Run

```bash
# Install dependencies
pip install -r requirements.txt

# Run the sample
python simplePrint.py
```

##### Expected Output

```
Simple Print - Printing from CUDA Kernels
Demonstrating both CUDA C++ and Numba CUDA approaches

Device: <Your GPU Name>
Compute Capability: sm_<XX>

======================================================================
METHOD 1: CUDA C++ Kernel (via cuda.core.Program)
======================================================================
Advantage: Full C++ features, better for complex kernels

Compiling CUDA C++ kernel...
Kernel compiled successfully.

Kernel configuration:
  Grid:  (2, 2)
  Block: (2, 2, 2)
  Total threads: 32

Launching kernel with value=10. Output:

[0, 0]:		Value is: 10
[0, 1]:		Value is: 10
[0, 2]:		Value is: 10
[0, 3]:		Value is: 10
[0, 4]:		Value is: 10
[0, 5]:		Value is: 10
[0, 6]:		Value is: 10
[0, 7]:		Value is: 10
[1, 0]:		Value is: 10
...
[3, 7]:		Value is: 10

CUDA C++ kernel execution complete.


======================================================================
METHOD 2: Numba CUDA Kernel (Pythonic / modern indexing)
======================================================================
Advantage: Uses numba.cuda.grid(3) for global indexing,
           while still showing classic CUDA C++ IDs for reference.
           Uses cuda.core for stream management (interoperability).

Kernel configuration:
  Grid:  (2, 2)
  Block: (2, 2, 2)
  Total threads: 32

Launching Numba CUDA kernel (grid(3) + classic IDs) with value=10:
Uses numba.cuda.grid(3) to get global (x, y, z),
and prints the corresponding blockId/threadId like the C++ sample.
Stream managed by cuda.core for consistency with C++ example.

global[ 0 , 0 , 0 ]  -> [ 0 ,  0 ]: Value is: 10
global[ 1 , 0 , 0 ]  -> [ 0 ,  1 ]: Value is: 10
global[ 0 , 1 , 0 ]  -> [ 0 ,  2 ]: Value is: 10
...
global[ 3 , 3 , 1 ]  -> [ 3 ,  7 ]: Value is: 10

Numba CUDA kernel execution complete.

======================================================================
Done! Both kernel approaches demonstrated successfully.
======================================================================
```

##### Understanding the Output

- **Grid**: 2×2 = 4 blocks (labeled 0-3)
- **Block**: 2×2×2 = 8 threads per block (labeled 0-7)
- **Total**: 32 threads, each printing its position and value

###### CUDA C++ Kernel:
Each thread calculates:
- Block ID (linear): `blockIdx.y * gridDim.x + blockIdx.x`
- Thread ID (linear): `threadIdx.z * blockDim.x * blockDim.y + threadIdx.y * blockDim.x + threadIdx.x`

###### Numba CUDA Kernel:
Each thread shows:
- **Global position** using `numba.cuda.grid(3)` → `(x, y, z)` coordinates across entire grid
- **Classic IDs** (block ID, thread ID) calculated the same way as C++ for comparison
- This demonstrates how modern indexing relates to traditional CUDA C++ style

###### Comparing the Two Approaches

**CUDA C++ Kernel (Method 1):**
- Uses C++ syntax and `printf()` with full formatting control
- Requires compilation via `cuda.core.Program`
- Best for complex kernels needing C++ features (templates, libraries, etc.)
- Uses classic block/thread ID indexing
- Output: `[0, 0]:		Value is: 10` (clean formatting)

**Numba CUDA Kernel (Method 2):**
- Uses Python syntax with `@cuda.jit` decorator
- JIT compiled automatically when called
- Best for prototyping and simpler kernels
- **Modern indexing**: Uses `numba.cuda.grid(3)` to get global thread coordinates (recommended)
- Also shows classic block/thread IDs to help relate the two indexing models
- **Interoperability**: Uses `cuda.core` streams via `stream` for consistency
- Demonstrates that numba-cuda kernels can work seamlessly with cuda.core infrastructure
- Limited print formatting (no f-strings, basic `print()` only; adds spaces between arguments)
- Output: `global[ 0 , 0 , 0 ] -> [ 0 , 0 ]: Value is: 10` (shows both indexing styles; note extra spaces due to `print()` behavior)

##### Experiments

Try modifying:

###### For Both Approaches:
- **Grid size**: Change `grid=(4, 4)` for 16 blocks
- **Block size**: Change `block=(4, 4, 4)` for 64 threads per block
- **Conditional printing**: Print only from specific threads (e.g., `if threadId == 0:`)

###### CUDA C++ Specific:
- **Format strings**: Experiment with different `printf()` formats
- **Kernel code**: Add complex C++ computations before printing
- **External libraries**: Include CUDA math libraries or device functions (e.g., `<cuda/std/cmath>`, `<cub/cub.cuh>`)

###### Numba CUDA Specific:
- **Grid indexing**: Try `numba.cuda.grid(1)` or `numba.cuda.grid(2)` for different dimensions
- **Conditional printing**: Print only from threads where `x == 0` or `y == z`
- **Python operations**: Use NumPy-like operations in the kernel
- **Device math libraries**: Use [nvmath-python device APIs](https://docs.nvidia.com/cuda/nvmath-python/latest/device-apis/index.html) for optimized math operations (similar to CUDA math libraries in C++)
- **Shared memory**: Add `numba.cuda.shared.array()` for fast inter-thread communication
- **Atomic operations**: Try `numba.cuda.atomic.add()` for thread-safe updates
- **Print variations**: Experiment with what numba-cuda's `print()` can and cannot handle
- **Streams**: Create multiple `cuda.core` streams and launch numba-cuda kernels on them concurrently
- **Interoperability**: Mix numba-cuda kernels and CUDA C++ kernels on the same stream

##### Notes

###### General:
- Printing from GPU is relatively slow - use sparingly in production code
- Printf output is buffered and limited (~1MB buffer on most GPUs)

###### CUDA C++ Kernels:
- Always call `stream.sync()` after kernel launch to flush printf output
- Full `printf()` format string support (%, flags, width, precision)

###### Numba CUDA Kernels:
- **Recommended**: Use `numba.cuda.grid(ndim)` for thread indexing (modern, Pythonic)
  - `grid(1)` for 1D indexing, `grid(2)` for 2D, `grid(3)` for 3D
  - Returns global thread position across the entire grid
- **Interoperability**: Use `cuda.core` streams with Numba kernels via `stream`
  - Create streams: `stream = device.create_stream()`
  - Launch kernels: `kernel[grid, block, stream](args)`
  - Synchronize: `stream.sync()`
- Numba's `print()` has limited capabilities compared to Python's `print()`
- F-strings are NOT supported in Numba CUDA kernels
- Use comma-separated arguments: `print("Value:", x)` instead of f-strings
- **Note**: `print()` automatically adds spaces between comma-separated arguments (e.g., `print("[", x, "]")` outputs `[ 0 ]` not `[0]`)
- Always synchronize the stream to flush output

##### Files

- `simplePrint.py` - Python implementation using cuda.core API
- `README.md` - This file
- `requirements.txt` - Sample dependencies

##### See Also

###### CUDA Python (cuda.core):
- [cuda.core Documentation](https://nvidia.github.io/cuda-python/)
- [CUDA Python Examples](https://github.com/NVIDIA/cuda-python/tree/main/cuda_core/examples)

###### Numba CUDA:
- [Numba CUDA Documentation](https://nvidia.github.io/numba-cuda/)
- [numba.cuda.grid() Reference](https://nvidia.github.io/numba-cuda/reference/kernel.html#numba.cuda.grid)
- [nvmath-python Device APIs](https://docs.nvidia.com/cuda/nvmath-python/latest/device-apis/index.html) - Optimized math operations for Numba CUDA kernels

###### CUDA References:
- [CUDA C Programming Guide - Printf](https://docs.nvidia.com/cuda/cuda-c-programming-guide/index.html#formatted-output)
- [C++ simplePrintf Sample](https://github.com/NVIDIA/cuda-samples/tree/master/Samples/0_Introduction/simplePrintf)


</details>

<br>

### copyImageArraytoGPU

> #### On this box
>
> **Command**
> ```bash
> cd $CUDA_SAMPLES/python/1_GettingStarted/copyImageArraytoGPU
> python copyImageArraytoGPU.py
> ```
>
> **Result** — Test PASSED. 256x256x3 image round-tripped; mean pixel 127.33 computed on the GPU.
>
> *Wall time: 3.3 s*
>
> **Notes** — Shows the CuPy view over a `cuda.core` allocation — zero-copy interop between the two libraries, no extra transfer.

<details>
<summary><b>Full README — copyImageArraytoGPU</b></summary>

#### Sample: Image Array Copy to GPU (Python)

##### Description

Copy image arrays between CPU and GPU memory using the modern `cuda.core` API with optimal performance through pinned memory and asynchronous transfers.

##### What You'll Learn

- How to use pinned memory for faster CPU↔GPU transfers
- Using the `cuda.core` API for memory management
- Working with DLPack for zero-copy array views
- Performing asynchronous memory transfers with CUDA streams
- Interoperability between CUDA Core API and CuPy
- Proper CUDA resource management and cleanup

##### Key Libraries

- `cuda.core` - Modern CUDA Python API
- `numpy` - Array operations and DLPack support
- `cupy` - GPU array operations and CUDA interoperability

##### Key APIs

###### From `cuda.core`:

- `Device()` - Initialize and access CUDA device
- `Device.set_current()` - Set the current device for API calls
- `Device.create_stream()` - Create CUDA stream for async operations
- `Device.memory_resource` - Access device memory allocator
- `PinnedMemoryResource()` - Allocate pinned host memory
- `buffer.copy_to()` - Copy data between memory spaces
- `buffer.close()` - Release allocated memory

###### From `numpy`:

- `np.from_dlpack()` - Create array view from DLPack capsule
- `np.copyto()` - Copy data between arrays

###### From `cupy`:

- `cp.from_dlpack()` - Create GPU array view from DLPack capsule
- `cp.cuda.Stream.from_external()` - Use external CUDA stream

###### From `cuda_samples_utils`:

- `verify_array_result()` - Verify computation results

##### Requirements

###### Hardware:

- NVIDIA GPU with CUDA support
- Sufficient GPU memory for image data (sample uses ~200KB for 256×256×3 image)

###### Software:

- CUDA Toolkit 13.0 or newer
- Python 3.10 or newer
- NumPy 2.3.2 or newer (required for DLPack support)
- `cuda-python` package (>=13.0.0+)
- `cuda-core` package (>=1.0.0)
- `cupy-cuda13x` package (14.0.0+)

##### Installation

Install the required packages from requirements.txt:

```bash
cd $CUDA_SAMPLES/python/1_GettingStarted/copyImageArraytoGPU
pip install -r requirements.txt
```

The requirements.txt installs:
- `numpy` (2.3.2+, required for DLPack)
- `cuda-python` (>=13.0.0+)
- `cuda-core` (>=1.0.0)
- `cupy-cuda13x` (14.0.0+)

##### How to Run

###### Basic usage:

```bash
cd $CUDA_SAMPLES/python/1_GettingStarted/copyImageArraytoGPU
python copyImageArraytoGPU.py
```

##### Expected Output

```
[Image Array Copy to GPU using CUDA Core API]
Device: NVIDIA GeForce RTX 4090
[Image array copy of 256x256x3 image]
Creating sample image...
Copying image to GPU...
Creating CuPy view of GPU data...
Mean pixel value (computed on GPU): 127.50
Copying image back from GPU...
Verifying result...
Test PASSED

Done
```

**Note:** Device name will vary based on your GPU.

##### Files

- `copyImageArraytoGPU.py` - Python implementation using cuda.core API
- `README.md` - This file
- `requirements.txt` - Sample dependencies
- `../../Utilities/cuda_samples_utils.py` - Common utilities (imported by this sample)

##### See Also

- [CUDA Python Documentation](https://nvidia.github.io/cuda-python/)
- [cuda.core API Guide](https://nvidia.github.io/cuda-python/cuda-core/latest/)
- [DLPack Specification](https://dmlc.github.io/dlpack/latest/)
- [CuPy Documentation](https://docs.cupy.dev/)


</details>

<br>

### blurImageUnifiedMemory

> #### On this box
>
> **Command**
> ```bash
> cd $CUDA_SAMPLES/python/1_GettingStarted/blurImageUnifiedMemory
> python blurImageUnifiedMemory.py
> ```
>
> **Result** — Test PASSED. Compiled for sm_120, blurred 256x256 grayscale, max difference from original 0.5076. Wrote `original_image.png` and `blurred_image.png` into the sample folder.
>
> *Wall time: 0.5 s*
>
> **Notes** — Writes two PNGs next to the script. Unified memory hides the copy, but on a discrete GPU behind Gen 3 x8 the copy still happens — it is convenience, not free bandwidth.

<details>
<summary><b>Full README — blurImageUnifiedMemory</b></summary>

#### Sample: Image Blur with Unified Memory (Python)

##### Description

Blur images on GPU using modern `cuda.core` APIs for kernel compilation, execution, and memory management. This sample demonstrates **zero-copy data sharing** between CPU and GPU using unified (managed) memory.

##### What You'll Learn

- Compiling CUDA kernels at runtime with `cuda.core.Program`
- Launching kernels with `cuda.core.launch` and `LaunchConfig`
- Using unified memory with `cuda.core.ManagedMemoryResource`
- **Zero-copy CPU access** to unified memory via `np.from_dlpack()`
- Seamless CPU/GPU memory access without explicit transfers

##### Key Concepts

###### Kernel Compilation with cuda.core.Program

```python
# Compile CUDA C++ kernel at runtime
program = Program(KERNEL_CODE, code_type="c++", options=options)
compiled = program.compile(target_type="cubin")
kernel = compiled.get_kernel("box_blur_3x3")
```

###### Kernel Launch with cuda.core.launch

```python
# Configure and launch kernel
config = LaunchConfig(grid=grid_size, block=block_size)

# Buffers can be passed directly as kernel arguments
launch(stream, config, kernel, src_buf, dst_buf, H, W)
```

###### Unified Memory (Managed Memory)

This sample uses `ManagedMemoryResource` for simplicity: a single allocation is accessible from both CPU and GPU without explicit transfers. For performance-critical workloads, consider `LegacyPinnedMemoryResource` + `DeviceMemoryResource` instead, which gives explicit control over host/device placement and transfer costs.

Unified memory is accessible from both CPU and GPU without explicit data transfers:

```python
# Allocate unified memory
options = ManagedMemoryResourceOptions(preferred_location=device.device_id)
mr = ManagedMemoryResource(options)
src_buf = mr.allocate(n_bytes, stream)
dst_buf = mr.allocate(n_bytes, stream)
try:
    # Synchronize to ensure allocations are complete before CPU access
    stream.sync()

    # Create numpy views of unified memory using DLPack protocol (zero-copy)
    src_np = np.from_dlpack(src_buf).view(np.float32).reshape(H, W)
    dst_np = np.from_dlpack(dst_buf).view(np.float32).reshape(H, W)

    # CPU writes directly to unified memory
    src_np[:] = input_data

    # Launch kernel - buffers can be passed directly as arguments
    launch(stream, config, kernel, src_buf, dst_buf, H, W)
    stream.sync()

    # Return zero-copy view; caller must close buffers when done
    return dst_np, src_buf, dst_buf
except Exception:
    src_buf.close()
    dst_buf.close()
    raise
```

When returning a zero-copy view, the caller must close the buffers after use (e.g., in a `try/finally` block) to avoid leaking managed memory.

##### Key APIs

###### From `cuda.core`:

- `Device` - CUDA device management
- `Program` - Runtime kernel compilation (NVRTC)
- `ProgramOptions` - Compilation options (architecture target)
- `LaunchConfig` - Kernel launch configuration (grid/block dimensions)
- `launch` - Execute compiled kernel
- `ManagedMemoryResource` - Unified memory allocation

###### Zero-Copy Techniques:

- `np.from_dlpack(buffer)` - Create numpy view of unified memory using DLPack protocol
- Pass `buffer` directly to `launch()` as kernel arguments
- When returning a zero-copy view, return `(view, src_buf, dst_buf)` and have the caller close buffers in `try/finally` after use

##### Kernel Techniques

- **2D Thread Mapping** - Each thread computes one output pixel
- **Stencil Pattern** - Read neighboring pixels (3x3 neighborhood)
- **Boundary Handling** - Clamp to edge for border pixels
- **Box Filter** - 3x3 averaging for blur effect

##### Requirements

###### Hardware:

- NVIDIA GPU with CUDA support
- Minimum GPU memory: 256 MB

###### Software:

- CUDA Toolkit 13.0 or newer
- Python 3.10 or newer
- `cuda-python` package (13.0.0+)
- `cuda-core` package (>=1.0.0)
- `numpy` package (>=2.3.2)
- `pillow` package (10.0.0+)

###### Platform Support:

This sample relies on `ManagedMemoryResource` with **concurrent host access**
to managed allocations while GPU kernels are in flight. That behavior
requires the device property `concurrent_managed_access=True`, which is only
supported on Linux with HMM (Pascal and newer). On Windows (WDDM/MCDM/TCC)
the property is `False`, so the sample exits early with a waive message and
exit code `2` instead of attempting a run that would crash the process.

##### Installation

```bash
cd $CUDA_SAMPLES/python/1_GettingStarted/blurImageUnifiedMemory
pip install -r requirements.txt
```

##### How to Run

```bash
python blurImageUnifiedMemory.py
```

##### Expected Output

```
============================================================
Image Blur with Unified Memory (cuda.core)
============================================================

Device: <Your GPU Name>
Compute Capability: sm_<XY>

Compiling CUDA kernel with cuda.core.Program...
  Compiled for architecture: sm_<XY>

Image size: 256x256 grayscale
Creating sample image...
Blurring image on GPU...

Saving results...
  Saved: original_image.png
  Saved: blurred_image.png

Verifying result...
  Test PASSED
  Max difference from original: <value>
```

##### Output Files

- `original_image.png` - Test pattern image before blur
- `blurred_image.png` - Image after 3x3 box blur

##### Files

- `blurImageUnifiedMemory.py` - Python implementation using cuda.core
- `README.md` - This file
- `requirements.txt` - Sample dependencies

##### See Also

- [cuda.core Documentation](https://nvidia.github.io/cuda-python/cuda-core/latest/)
- [cuda.core.Program](https://nvidia.github.io/cuda-python/cuda-core/latest/generated/cuda.core.Program.html)
- [cuda.core.ManagedMemoryResource](https://nvidia.github.io/cuda-python/cuda-core/latest/generated/cuda.core.ManagedMemoryResource.html)
- [CUDA Managed Memory](https://docs.nvidia.com/cuda/cuda-c-programming-guide/index.html#um-unified-memory-programming-hd)


</details>

<br>

### kernelNsysProfile

> #### On this box
>
> **Command**
> ```bash
> cd $CUDA_SAMPLES/python/1_GettingStarted/kernelNsysProfile
> source $VENVS/venv-extras/bin/activate      # isolated: base + cuda-cccl, nvtx, numba-cuda, torch, mpi4py
> python kernelNsysProfile.py
> ```
>
> **Result** — PASSED. Vector Add, SAXPY and Transform kernels all verified against NumPy references, with NVTX ranges around each phase.
>
> *Wall time: 1.4 s*
>
> **Notes** — `nsys` is present at `/usr/local/cuda/bin/nsys` on this box. Profile with:
```bash
nsys profile -o /tmp/kprof --force-overwrite true python kernelNsysProfile.py
nsys stats /tmp/kprof.nsys-rep
```

<details>
<summary><b>Full README — kernelNsysProfile</b></summary>

#### Sample: Kernel Nsys Profiling - CUDA C++ Kernel Profiling with cuda.core (Python)

##### Description

This sample demonstrates how to profile custom CUDA C++ kernels compiled and launched with `cuda.core` using NVIDIA Nsight Systems. It implements three GPU operations (vector addition, SAXPY, vector transform) as custom kernels and shows how to instrument code with NVTX markers for profiling analysis.

##### What you will learn

- How to write and compile CUDA C++ kernels with `cuda.core.Program`
- How to launch kernels with `LaunchConfig` and manage CUDA streams
- How to use NVTX markers (`nvtx.annotate()`) to annotate code sections
- How to profile kernels with Nsight Systems and analyze performance
- Modern CUDA Python workflow with `cuda.core.Device` and proper resource cleanup

##### Requirements

- NVIDIA GPU with Compute Capability 7.0+
- CUDA Toolkit 13.0+
- Python 3.10+
- Packages: `numpy`, `cuda-python`, `cuda-core`, `cupy-cuda13x`, `nvtx` (see `requirements.txt`; NumPy >=2.3.2)

**Install:**
```bash
pip install -r requirements.txt
```

##### How to run

```bash
python kernelNsysProfile.py
python kernelNsysProfile.py --array-size 10000000  # Custom size
```

##### Nsys Profiling

**Basic profile:**
```bash
nsys profile -o gpu_profile python kernelNsysProfile.py
nsys-ui gpu_profile.nsys-rep  # View results
```

The program uses color-coded NVTX markers:
- **Purple**: Phase 2 (cuda.core Custom Kernels - main focus)
- **Yellow/Blue/Green**: Other phases
- **Cyan**: Nested operations

Focus on Phase 2 to analyze kernel execution times, launch overhead, and GPU utilization.

**For detailed Nsys usage and analysis techniques, see the [NVIDIA Nsight Systems documentation](https://docs.nvidia.com/nsight-systems/).**

##### Troubleshooting

**Missing packages:**
```bash
pip install -r requirements.txt
```

**Out of memory:**
```bash
python kernelNsysProfile.py -n 10000000  # Reduce array size
```

**Nsys not found:**
```bash
export PATH=/usr/local/cuda/bin:$PATH
```

##### See Also

- [CUDA Python Documentation](https://nvidia.github.io/cuda-python/)
- [NVIDIA Nsight Systems Documentation](https://docs.nvidia.com/nsight-systems/)
- [CuPy Documentation](https://docs.cupy.dev/)


</details>

---

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

## 3_FrameworkInterop — Framework interop

Two samples, and the most directly applicable to AI work: how to call a hand-written CUDA kernel from PyTorch and from TensorFlow with gradients intact.

<br>

### customPyTorchKernel

> #### On this box
>
> **Command**
> ```bash
> cd $CUDA_SAMPLES/python/3_FrameworkInterop/customPyTorchKernel
> source $VENVS/venv-extras/bin/activate      # isolated: base + cuda-cccl, nvtx, numba-cuda, torch, mpi4py
> python customPyTorchKernel.py
> ```
>
> **Result** — All tests PASSED including the 3D-tensor case, with autograd working through the custom op.
>
> *Wall time: 1.7 s*
>
> **Notes** — Torch **2.13.0+cu130** installed cleanly and ships sm_120 (`torch.cuda.get_arch_list()` -> `['sm_75','sm_80','sm_86','sm_90','sm_100','sm_120']`), so no source build is needed for Blackwell. This is the single most directly useful sample for AI work: it is how you drop a hand-written CUDA kernel into a PyTorch model with gradients intact.

<details>
<summary><b>Full README — customPyTorchKernel</b></summary>

#### Sample: PyTorch Custom GPU Operator

##### Description

This sample demonstrates how to add a custom GPU operation to PyTorch using the `cuda.core` API. It implements a simple square operation (y = x²) to show the complete workflow from CUDA kernel to PyTorch integration with autograd support.

##### Requirements

- NVIDIA GPU with Compute Capability 7.0+
- CUDA Toolkit 13.0+
- Python 3.10+
- PyTorch 2.0+
- cuda-python >= 13.0.0
- cuda-core >=1.0.0

##### Installation

```bash
cd python/3_FrameworkInterop/customPyTorchKernel
pip install -r requirements.txt
```

**Windows users:** The default `torch` wheel on PyPI for Windows is CPU-only and will cause `torch.cuda.is_available()` to return `False`. Install a CUDA-enabled build from PyTorch's wheel index *before* (or after) the command above:

```bash
pip install torch --index-url https://download.pytorch.org/whl/cu128
```

Replace `cu128` with the wheel suffix matching your installed CUDA driver (e.g. `cu121`, `cu124`, `cu126`, `cu128`). The driver's CUDA version must be >= the wheel's bundled runtime.

##### How to Run

```bash
# Basic usage
python customPyTorchKernel.py

# Test with more elements
python customPyTorchKernel.py --size 1000000

# Use specific GPU
CUDA_VISIBLE_DEVICES=1 python customPyTorchKernel.py
```

##### Expected Output

The sample runs three tests:
1. Forward pass correctness (y = x²)
2. Backward pass correctness (gradient computation)
3. Multi-dimensional tensor support

All tests should pass, confirming the custom operator works correctly with PyTorch's autograd system.

##### Key Concepts

The sample demonstrates:
- Writing CUDA kernels with grid-stride loops
- Runtime kernel compilation with cuda.core
- PyTorch autograd integration via `torch.autograd.Function`
- Stream management using PyTorch's current stream
- Kernel caching for performance

The code is self-documenting with inline comments explaining each step.


</details>

<br>

### customTensorFlowKernel

> #### On this box
>
> **Command**
> ```bash
> cd $CUDA_SAMPLES/python/3_FrameworkInterop/customTensorFlowKernel
> source $VENVS/venv-tf/bin/activate      # isolated: TensorFlow
> python customTensorFlowKernel.py
> ```
>
> **Result** — PASSED — custom ReLU operator working, usable inside a `tf.keras.Sequential` via a Lambda layer.
>
> *Wall time: 2.5 s*
>
> **Notes** — Installed into its own venv to keep TensorFlow's pins away from the working environment. It works, but PyTorch's path (above) is far less friction on this stack.

<details>
<summary><b>Full README — customTensorFlowKernel</b></summary>

#### Sample: TensorFlow Custom GPU Operator

##### Description

Learn how to add a custom GPU operation to TensorFlow using `cuda.core` with `tf.py_function`. This sample implements a custom **ReLU operation** (y = max(0, x)) for rapid prototyping of GPU operations.

##### Key Question Answered

**Q: How do I add a custom GPU op to TensorFlow?**

**A:** Use `tf.py_function` to wrap cuda.core kernels:
1. Write CUDA kernels (forward + backward) with grid-stride loops
2. Compile them with cuda.core
3. Wrap in Python functions
4. Use `tf.py_function` to call from TensorFlow
5. Register gradients with `@tf.custom_gradient`

##### Requirements

- NVIDIA GPU with Compute Capability 7.0+
- CUDA Toolkit 13.0+
- Python 3.10+
- TensorFlow 2.10+
- cuda-python >= 13.0.0
- cuda-core >=1.0.0 (required for LEGACY_DEFAULT_STREAM)
- numpy >= 2.3.2
- CuPy (for device pointer access)

##### Installation

```bash
cd python/3_FrameworkInterop/customTensorFlowKernel
pip install -r requirements.txt
```

##### How to Run

```bash
python customTensorFlowKernel.py
python customTensorFlowKernel.py --size 1000000
```

##### Usage Example

```python
import tensorflow as tf
from customTensorFlowKernel import custom_relu

# Simple usage
x = tf.random.normal([100], dtype=tf.float32)
y = custom_relu(x)

# In a Keras model
model = tf.keras.Sequential([
    tf.keras.layers.Dense(128),
    tf.keras.layers.Lambda(custom_relu),
    tf.keras.layers.Dense(10)
])
```

##### Key Concepts

- **tf.py_function**: Bridges TensorFlow and Python code using cuda.core (has overhead, not XLA-compatible)
- **@tf.custom_gradient**: Registers custom backward pass
- **cuda.core**: Primary GPU manager (device, stream, kernel compilation)
- **CuPy**: Internal helper for device pointer access only

##### Production Alternatives

This sample is for rapid prototyping. For production:
- **TensorFlow C++ Custom Op**: Full performance, XLA compatible
- **XLA Custom Calls**: For XLA-compiled models
- See TensorFlow documentation for details

##### See Also

- [cuda.core Documentation](https://nvidia.github.io/cuda-python/cuda-core/latest/)
- [TensorFlow tf.py_function](https://www.tensorflow.org/api_docs/python/tf/py_function)
- [TensorFlow @custom_gradient](https://www.tensorflow.org/api_docs/python/tf/custom_gradient)
- [TensorFlow C++ Custom Op Guide](https://www.tensorflow.org/guide/create_op)
- [CuPy Documentation](https://docs.cupy.dev/)


</details>

---

## 4_DistributedComputing — Distributed computing

Three samples. Note that only `simpleP2P` genuinely requires a second GPU — `ipcMemoryPool` is inter-process and runs fine here, and `multiGPUGradientAverage` runs with two oversubscribed MPI ranks.

<br>

### ipcMemoryPool

> #### On this box
>
> **Command**
> ```bash
> cd $CUDA_SAMPLES/python/4_DistributedComputing/ipcMemoryPool
> python ipcMemoryPool.py
> ```
>
> **Result** — **Works on a single GPU.** IPC round-trip OK: parent created an IPC-enabled `DeviceMemoryResource` (`is_ipc_enabled=True`), child process mapped the 4096-byte buffer and wrote back a pattern the parent observed.
>
> *Wall time: 1.0 s*
>
> **Notes** — Worth calling out because the folder name suggests multi-GPU: this is *inter-process*, not inter-device. It runs fine with one GPU and is the mechanism behind sharing a loaded model's memory across worker processes.

<details>
<summary><b>Full README — ipcMemoryPool</b></summary>

#### ipcMemoryPool (Python)

##### Description

This sample demonstrates how to share GPU memory between Python
processes using CUDA Inter-Process Communication (IPC) and
`cuda.core`'s IPC-enabled memory pools.

By default each process has its own CUDA virtual address space and
cannot see allocations made by another process. With an IPC-enabled
`DeviceMemoryResource` the parent allocates once, and the child
process maps that same physical GPU memory into its own address space
so both read and write the same bytes. The sample performs a
round-trip test:

1. Parent creates an IPC-enabled `DeviceMemoryResource` and allocates
   a `Buffer`.
2. Parent fills the buffer with a known pattern.
3. Parent sends the `Buffer` to a child process through an
   `multiprocessing.Queue`. cuda.core's pickle reducers re-create the
   memory resource and map the buffer in the child.
4. Child verifies the parent's pattern, writes a new pattern, and
   signals completion.
5. Parent verifies the child's writes.

##### What You'll Learn

- Enabling IPC on a `DeviceMemoryResource` with `ipc_enabled=True`
- Sending `Buffer` objects across process boundaries via `mp.Queue`
- How cuda.core's pickle reducers rebuild the MR and map the buffer
  in the receiving process
- Why `multiprocessing` must use the `"spawn"` start method with CUDA
- Detecting IPC support at runtime (POSIX file-descriptor handle
  type, memory-pool support, Linux-only)

##### Key Libraries

- [`cuda.core`](https://nvidia.github.io/cuda-python/cuda-core/latest/) - IPC-enabled memory resources and buffer reducers
- `cupy` - zero-copy views over the shared device memory via DLPack
- `multiprocessing` - standard library process management

##### Key APIs

###### From `cuda.core`

- `DeviceMemoryResource(device, options=DeviceMemoryResourceOptions(ipc_enabled=True))` - create an IPC-enabled memory pool
- `DeviceMemoryResourceOptions(max_size=..., ipc_enabled=True)` - configure the underlying pool
- `mr.allocate(nbytes)` - allocate a `Buffer` from the IPC pool
- `Buffer.is_mapped` - True when the buffer is usable in the current process
- `Device.properties.memory_pools_supported` - runtime feature check
- `Device.properties.handle_type_posix_file_descriptor_supported` - runtime feature check

###### From `cuda_samples_utils`

- `print_gpu_info()` - print device name and compute capability

##### Requirements

###### Hardware

- NVIDIA GPU with Compute Capability 7.0 or higher
- Device that supports CUDA memory pools and POSIX file-descriptor IPC handles (the sample detects and reports this at startup)
- Minimum GPU memory: 512 MB

###### Software

- Linux x86_64 (POSIX file-descriptor IPC handles are not available on Windows or macOS)
- CUDA Toolkit 13.0 or newer (matches `cuda-python` 13.x)
- Python 3.10 or newer
- `cuda-python` (>=13.0.0)
- `cuda-core` (>=1.0.0)
- `cupy-cuda13x` (>=14.0.0)

##### Installation

Install the required packages from `requirements.txt`:

```bash
cd $CUDA_SAMPLES/python/4_DistributedComputing/ipcMemoryPool
pip install -r requirements.txt
```

The `requirements.txt` installs:

- `cuda-python` (>=13.0.0)
- `cuda-core` (>=1.0.0)
- `cupy-cuda13x` (>=14.0.0)

##### How to Run

###### Basic usage

```bash
cd $CUDA_SAMPLES/python/4_DistributedComputing/ipcMemoryPool
python ipcMemoryPool.py
```

###### With custom parameters

```bash
# Larger shared buffer
python ipcMemoryPool.py --elements 65536

# Use a specific GPU
python ipcMemoryPool.py --device 1
```

On platforms or devices that do not support CUDA IPC, the sample
prints a diagnostic and exits cleanly with status 0.

##### Expected Output

```
Device: <Your GPU Name>
Compute Capability: <X.Y>

Created IPC-enabled DeviceMemoryResource (is_ipc_enabled=True)
Parent wrote pattern (first 5 values): [100. 101. 102. 103. 104.]
Parent sent buffer to child pid=<pid>; waiting...
[child pid=<pid>] received buffer: is_mapped=True, size=4096
Parent sees child's pattern (first 5 values): [-0. -1. -2. -3. -4.]
IPC round-trip: OK
```

**Note:** Device name, compute capability, and child PID will vary
based on your system.

##### Files

- `ipcMemoryPool.py` - Python implementation using `cuda.core` IPC memory pools
- `README.md` - This file
- `requirements.txt` - Sample dependencies
- `../../Utilities/cuda_samples_utils.py` - Common utilities (imported by this sample)

##### See Also

- [CUDA Python Documentation](https://nvidia.github.io/cuda-python/)
- [`cuda.core` memory API](https://nvidia.github.io/cuda-python/cuda-core/latest/api.html#memory)
- Upstream `cuda.core` IPC tests: [`test_memory_ipc.py`](https://github.com/NVIDIA/cuda-python/blob/main/cuda_core/tests/memory_ipc/test_memory_ipc.py)
- [CUDA IPC programming guide](https://docs.nvidia.com/cuda/cuda-c-programming-guide/index.html#interprocess-communication)


</details>

<br>

### multiGPUGradientAverage

> #### On this box
>
> **Command**
> ```bash
> cd $CUDA_SAMPLES/python/4_DistributedComputing/multiGPUGradientAverage
> source $VENVS/venv-extras/bin/activate      # isolated: base + cuda-cccl, nvtx, numba-cuda, torch, mpi4py
> mpirun --oversubscribe -np 2 python multiGPUGradientAverage.py
> ```
>
> **Result** — Test PASSED with 2 ranks oversubscribed onto the single GPU. Kernel 32.571 ms, MPI Allreduce (host-staged) 4.590 ms, total 37.162 ms.
>
> **Notes** — **Gotcha:** running it bare gives `ERROR: This sample requires at least 2 MPI processes!`. You need a launcher — `mpi4py` alone is not enough. On this box `libopenmpi40` was present but `mpirun` was not; `sudo apt install openmpi-bin` supplied it. `--oversubscribe` lets both ranks share the one GPU, which is enough to exercise the gradient-averaging logic even though it proves nothing about scaling.

<details>
<summary><b>Full README — multiGPUGradientAverage</b></summary>

#### Sample: multiGPUGradientAverage (Python)

##### Description

This sample demonstrates gradient averaging across multiple GPUs using MPI and cuda.core. Each GPU computes local gradients, which are synchronized (averaged) across all GPUs using MPI Allreduce with host-staging (GPU → CPU → MPI → CPU → GPU) for maximum compatibility.

##### What you will learn

- How to initialize MPI for multi-process GPU communication
- How to map MPI ranks to CUDA devices consistently
- How to integrate cuda.core streams with CuPy using `Stream.from_external`
- How to compile and launch custom CUDA kernels using cuda.core
- How to use cuda.core Event for GPU timing measurements
- How to use MPI Allreduce with host-staging for universal compatibility

##### Prerequisites

- Python 3.10+
- CUDA Toolkit 13.0+
- Standard MPI implementation (OpenMPI, MPICH, or Intel MPI)
- Multiple NVIDIA GPUs (tested with 2+ GPUs)

##### Installation

```bash
pip install -r requirements.txt
```

##### Running

**IMPORTANT:** This sample **MUST** be launched by an MPI runtime with at
least 2 processes. On Linux/macOS this is typically `mpirun`; on Windows with
Microsoft MPI the launcher is `mpiexec` (and the flag for process count is
`-n`). Either form is accepted by most MPI stacks.

Linux / macOS (OpenMPI, MPICH, Intel MPI):

```bash
# Single node (2 GPUs)
mpirun -np 2 python multiGPUGradientAverage.py --size 10000

# Single node (4 GPUs)
mpirun -np 4 python multiGPUGradientAverage.py --size 10000

# With specific GPUs
CUDA_VISIBLE_DEVICES=0,2 mpirun -np 2 python multiGPUGradientAverage.py
```

Windows (Microsoft MPI — `mpiexec` is installed under
`C:\Program Files\Microsoft MPI\Bin\` and is not on PATH by default):

```powershell
& "C:\Program Files\Microsoft MPI\Bin\mpiexec.exe" -n 2 `
    python multiGPUGradientAverage.py --size 10000
```

##### Sample Output

```
[Rank 0] World size = 4

======================================================================
Multi-GPU Gradient Average Demo
======================================================================
Number of MPI ranks (GPUs): 4
Gradient vector length per GPU: 10000
Device: NVIDIA GeForce RTX 4090
Computation: gradients computed on GPU via cuda.core.
Communication: gradients averaged via MPI_Allreduce on host (CPU) buffers.
======================================================================

Sample averaged gradient values (rank 0):
  avg_grad[0] = 1.500000
  avg_grad[5000] = 6.500000
  avg_grad[9999] = 11.499000

Expected values:
  expected[0] = 1.500000
  expected[5000] = 6.500000
  expected[9999] = 11.499000

Verifying gradient averaging correctness...
[PASS] Gradient averaging is correct.
[PASS] Gradient averaging is correct on all ranks.

Performance:
  Kernel time (GPU only): 0.123 ms
  MPI communication time (host-staging, end-to-end): 0.456 ms
  Total time: 0.579 ms

======================================================================
Demo complete.
======================================================================
```

##### Key Technical Details

The sample uses cuda.core streams and makes CuPy use them via `Stream.from_external`:

```python
stream = device.create_stream()
cp.cuda.Stream.from_external(stream).use()
```

GPU timing is measured using cuda.core Event:

```python
from cuda.core import EventOptions
timing_options = EventOptions(enable_timing=True)
start_event = stream.record(options=timing_options)
# ... GPU work ...
end_event = stream.record(options=timing_options)
end_event.sync()
kernel_time = end_event - start_event  # Returns milliseconds
```

The host-staging pattern transfers data GPU → CPU → MPI → CPU → GPU for universal MPI compatibility without requiring CUDA-aware MPI.

##### Troubleshooting

**Error: "This sample requires at least 2 MPI processes!"**

Solution:
- Linux / macOS: `mpirun -np 2 python multiGPUGradientAverage.py`
- Windows (Microsoft MPI): `& "C:\Program Files\Microsoft MPI\Bin\mpiexec.exe" -n 2 python multiGPUGradientAverage.py`
  (or `mpiexec -n 2 ...` after adding `C:\Program Files\Microsoft MPI\Bin\` to `PATH`).

See the **Running** section above for fully-formed examples.


</details>

<br>

### simpleP2P

> #### On this box
>
> **Command**
> ```bash
> cd $CUDA_SAMPLES/python/4_DistributedComputing/simpleP2P
> python simpleP2P.py
> ```
>
> **Result** — **Waived — correctly.** `CUDA-capable device count: 1` -> `Two or more GPUs with Peer-to-Peer access capability are required, waiving this sample.` Exit code 2.
>
> *Wall time: 0.2 s*
>
> **Notes** — This is the one sample that cannot demonstrate its point on this machine, and the only one not fully exercised. The graceful waive is the sample behaving as designed, not a failure. The C++ `p2pBandwidthLatencyTest` in `build/cpp/5_Domain_Specific/` has the same requirement.

<details>
<summary><b>Full README — simpleP2P</b></summary>

#### Sample: simpleP2P (Python)

##### Description

This sample demonstrates peer-to-peer (P2P) memory access between multiple GPUs in CUDA using the cuda.core Python library. P2P allows GPUs to directly access each other's memory without routing data through the host (CPU), enabling efficient multi-GPU applications. This sample detects P2P-capable GPUs, enables peer access, measures bandwidth using CUDA events for accurate GPU-side timing, and launches kernels (using grid-stride loops) that read from one GPU's memory and write to another GPU's memory.

##### What you will learn

- How to detect multiple CUDA-capable GPUs using `system.get_num_devices()` and `Device(id)`
- How to check P2P capability between GPU pairs using `device.can_access_peer()`
- How to enable and disable peer access using `DeviceMemoryResource.peer_accessible_by`
- How to allocate device memory on specific GPUs using `DeviceMemoryResource`
- How to perform direct GPU-to-GPU memory transfers with explicit event-based synchronization
- How to measure P2P bandwidth using CUDA events for accurate GPU-side timing
- How to use event-based synchronization between streams for sequential bandwidth measurement
- How to launch kernels on one GPU that access memory from another GPU
- How to compile and launch CUDA kernels using cuda.core's `Program` and `launch` APIs with grid-stride loops
- How to validate multi-GPU computation results
- How to properly clean up resources using try/finally blocks

##### Key libraries

- `numpy` - CPU array operations and data initialization
- `cuda-core` - Modern Python interface to CUDA runtime with full P2P support

##### Key APIs

**From cuda.core:**
- `system` – Pre-instantiated singleton for system-level CUDA information
- `system.get_num_devices()` – Get number of CUDA-capable devices
- `Device(id)` – Get specific CUDA device handle
- `device.can_access_peer(peer)` – Check if this device can access peer device memory
- `device.set_current()` – Set active device for subsequent operations
- `device.create_stream()` – Create CUDA stream for kernel execution
- `DeviceMemoryResource(device)` – Create memory resource for specific GPU
- `memory_resource.peer_accessible_by` – Get/set which devices can access this memory pool's allocations
  - Example: `mr.peer_accessible_by = [1]` grants device 1 access
  - Example: `mr.peer_accessible_by = []` revokes all access
- `PinnedMemoryResource()` – Allocate pinned (page-locked) host memory
- `EventOptions(enable_timing=True)` – Create options for CUDA events with timing enabled
- `stream.record(options=event_options)` – Record a CUDA event on a stream
- `event.elapsed_time(start_event)` – Get elapsed time in milliseconds between two events
- `stream.wait_event(event)` – Make a stream wait for an event to complete
- `stream.close()` – Clean up stream resources
- `Program()` – Compile CUDA C++ kernel code
- `LaunchConfig()` – Configure kernel launch parameters (grid, block)
- `launch()` – Launch compiled kernel with arguments
- `buffer.copy_from(src, stream=stream)` – Copy data from source buffer asynchronously
- `buffer.copy_to(dst, stream=stream)` – Copy data to destination buffer asynchronously

**From DLPack:**
- `numpy.from_dlpack()` – Create NumPy array view of memory buffer

**Memory Management:**
- Resources (streams, buffers) should be cleaned up using try/finally blocks to ensure proper cleanup even if errors occur
- Streams should be explicitly closed with `stream.close()` in finally blocks

##### Peer-to-Peer (P2P): When to Use

###### Benefits
- **Direct GPU-to-GPU transfers**: Bypass host memory for faster communication
- **Higher bandwidth**: PCIe or NVLink bandwidth between GPUs (up to 600 GB/s with NVLink)
- **Lower latency**: No CPU involvement in data transfers
- **Efficient multi-GPU**: Essential for scaling deep learning, HPC, and simulation workloads
- **Simplified programming**: Kernels can directly access remote GPU memory

###### Requirements
- **Two or more GPUs**: System must have multiple CUDA-capable GPUs
- **P2P support**: GPUs must be P2P-capable (check with `can_access_peer()`)
- **PCIe topology**: Usually requires GPUs on same PCIe root complex
- **Platform support**: Not available on Mac OSX, limited on ARM platforms

###### Best Use Cases
1. Multi-GPU deep learning training (model parallelism, data parallelism)
2. Large-scale scientific simulations across multiple GPUs
3. Real-time rendering with multiple GPUs
4. GPU clusters with direct GPU communication
5. Reducing CPU-GPU traffic in multi-GPU systems

##### Requirements

1. **Two or more NVIDIA Graphics Cards** with CUDA support and P2P capability
2. **CUDA Drivers** installed on your system
3. **CUDA Toolkit 13.0+** installed on your system
4. **Python 3.10 or newer**
5. **Proper PCIe topology** (GPUs should be on same PCIe root complex for best performance)

**Note**: This sample will gracefully exit if fewer than 2 GPUs are detected or if P2P is not supported between any GPU pair.

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

# Run with default parameters (16M elements = 64MB)
python simpleP2P.py
```

With custom parameters:
```bash
# Use 32M elements (128MB)
python simpleP2P.py --num_elements 33554432

# Show help
python simpleP2P.py --help
```

###### Command line arguments

- `--num_elements`: Number of elements in arrays (default: 16777216)
  - Each array uses `num_elements * 4 bytes` (float32)
  - Default: 64 MB per array
  - Sample allocates 2 device buffers + 1 host buffer

##### Expected Output

```
======================================================================
simpleP2P - CUDA Python Sample
======================================================================

Starting...

Checking for multiple GPUs...
CUDA-capable device count: 2

Checking GPU(s) for support of peer to peer memory access...
> Peer access from Tesla T10 (GPU0) -> Tesla T10 (GPU1): Yes
> Peer access from Tesla T10 (GPU1) -> Tesla T10 (GPU0): Yes

Using GPU0 (Tesla T10) and GPU1 (Tesla T10)

Allocating buffers (64MB on GPU0, GPU1 and CPU Host)...
  Peer access enabled: GPU0 <-> GPU1
  Peer access status: MR0 accessible by (1,), MR1 accessible by (0,)
  Memory allocated successfully

Measuring P2P bandwidth...
  Performing 100 ping-pong copies between GPUs...
  P2P bandwidth: 12.37 GB/s

Preparing host buffer and memcpy to GPU0...
  Data initialized and copied to GPU

Compiling CUDA kernel...
  Kernels compiled successfully

Run kernel on GPU1, taking source data from GPU0 and writing to GPU1...
  Kernel execution complete

Run kernel on GPU0, taking source data from GPU1 and writing to GPU0...
  Kernel execution complete

Copy data back to host from GPU0 and verify results...

Checking results...
  Comparing 16,777,216 elements...
Test PASSED
  [PASS] Validation PASSED

Disabling peer access...
  Peer access revoked: MR0 accessible by (), MR1 accessible by ()

======================================================================
simpleP2P completed successfully!
======================================================================

Shutting down...
```

**Note**: P2P bandwidth varies based on:
- PCIe generation
- NVLink
- System topology and configuration

##### Files

- `simpleP2P.py` – Main Python implementation
- `README.md` – This file
- `requirements.txt` – Python package dependencies


</details>

---

## Utilities — Utilities

The shared helper package imported by the samples. This is what older listings call `cudasamplepython`.

<br>

### Utilities

> #### On this box
>
> **Command**
> ```bash
> cd $CUDA_SAMPLES/python/Utilities
> (imported by the samples, not run directly)
> ```
>
> **Result** — Library module — `check_cuda_requirements()`, `verify_array_result()`, `print_gpu_info()`.
>
> **Notes** — **This is what the `cudasamplepython/` folder in older listings refers to.** There is no `cudasamplepython` module in this clone: `python/cudasamplepython` is a stray tree-dump text file, and the real package lives here in `python/Utilities/`. Samples reach it by path injection, not by installing a package:
```python
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "Utilities"))
from cuda_samples_utils import verify_array_result
```

<details>
<summary><b>Full README — Utilities</b></summary>

#### CUDA Python Utilities

Common utilities for CUDA Python samples using the `cuda.core` API.

##### Overview

This module provides reusable utility functions for CUDA samples to reduce code duplication. Samples import from `cuda_samples_utils.py` using simple path-based imports (no package structure needed).

##### Installation Requirements

Install from the Python samples directory:

```bash
cd $CUDA_SAMPLES/python
pip install -r requirements.txt
```

This installs a common CUDA 13 stack (see `python/requirements.txt`):

- `cuda-python` (>=13.0.0)
- `cuda-core` (>=1.0.0)
- `cupy-cuda13x` (>=14.0.0)
- `numpy` (>=2.3.2)

##### How to Use in Samples

Import utilities using path-based import:

```python
import sys
from pathlib import Path

# Add Utilities directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "Utilities"))
from cuda_samples_utils import verify_array_result

# Use the utility
if verify_array_result(result, expected):
    print("Success!")
```

##### Available Functions

###### Result Verification

**`verify_array_result(result, expected, rtol=1e-5, atol=1e-8, verbose=True)`**

Verify computed results match expected values. The helper detects whether both
arguments are NumPy arrays or both are CuPy arrays and uses the matching
library's `allclose` (no unnecessary cross-device transfers).

**Parameters:**
- `result`: NumPy or CuPy array with computed results
- `expected`: NumPy or CuPy array with expected values (same kind as `result`)
- `rtol`: Relative tolerance (default: 1e-5)
- `atol`: Absolute tolerance (default: 1e-8)
- `verbose`: Print test result (default: True)

**Returns:**
- `True` if results match within tolerance, `False` otherwise

**Example:**
```python
expected = a + b
if verify_array_result(c, expected):
    print("Computation correct!")
```

###### Package Check

**`check_cuda_requirements()`**

Check if required CUDA packages are available.

**Returns:**
- `True` if requirements are met, `False` otherwise

**Example:**
```python
if not check_cuda_requirements():
    sys.exit(1)
```

##### Design Philosophy

These utilities focus on common operations that are **not** part of `cuda.core` API:
- Result verification for NumPy or CuPy arrays
- Package requirements checking

For CUDA operations like device initialization, kernel compilation, and grid size calculations, samples should use `cuda.core` API directly to demonstrate the proper usage patterns.

##### Complete Example

See `../1_GettingStarted/vectorAdd/vectorAdd.py` for a complete example:

```python
import sys
from pathlib import Path

# Import utility
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "Utilities"))
from cuda_samples_utils import verify_array_result

import cupy as cp
from cuda.core import Device, Program, ProgramOptions, LaunchConfig, launch

# Use cuda.core directly for device and kernel operations
device = Device(0)
device.set_current()

program_options = ProgramOptions(std="c++17", arch=f"sm_{device.arch}")
program = Program(kernel_source, code_type="c++", options=program_options)
module = program.compile("cubin", name_expressions=("kernel_name",))
kernel = module.get_kernel("kernel_name")

# Calculate grid size inline
threads_per_block = 256
blocks_per_grid = (num_elements + threads_per_block - 1) // threads_per_block

# Launch kernel - pass cupy arrays directly
config = LaunchConfig(grid=blocks_per_grid, block=threads_per_block)
launch(stream, config, kernel, a, b, c, cp.int32(num_elements))

# Verify results using utility
verify_array_result(c, expected)
```

##### Benefits

- **Code Reuse**: Write common functionality once
- **Consistency**: All samples use the same patterns
- **Maintainability**: Bug fixes benefit all samples
- **Transparency**: Samples show cuda.core API usage directly
- **Simplicity**: No complex package structure needed


</details>

---

# Appendix A — Raw hardware captures

All captured 2026-08-16 on this machine. Nothing in this appendix is edited.

## `systemInfo.py` — driver and device summary

```text

======================================================================
Driver / NVML
======================================================================
CUDA driver version (user-mode): 13.3
CUDA driver version (kernel-mode): 610.57.4
NVML version: (13, 610, 57, 4)
Driver branch: r610_85
Current process: /home/google/Symoneural/cuda-samples/python/.venv/bin/python

======================================================================
Devices detected: 1
======================================================================

-- Device 0 --
Name: NVIDIA GeForce RTX 5070 Ti
UUID: GPU-15e0078a-cb3a-50d1-a40b-94e4d538fc78
Compute capability: 12.0
Architecture: BLACKWELL
Brand: GeForce
Memory: total=15.92 GiB, used=936.12 MiB, free=14.57 GiB
PCI: domain=0000 bus=01 device=00 id=00000000:01:00.0
Temperature (GPU sensor): 46 C
Performance state: 0

Done
```

## `deviceQuery.py` — full device properties (Python, cuda.core)

```text
[CUDA Device Query using CUDA Core API]
Detected 1 CUDA Capable device(s)

Device 0: NVIDIA GeForce RTX 5070 Ti
  CUDA Driver Version / Runtime Version          13.3 / 13.3
  CUDA Capability Major/Minor version number:    12.0
  Total amount of global memory:                 15858 MBytes (16628514816 bytes)
  ( 70) Multiprocessors, (128) CUDA Cores/MP:    8960 CUDA Cores
  GPU Max Clock rate:                            2572 MHz (2.57 GHz)
  Memory Clock rate:                             14001 Mhz
  Memory Bus Width:                              256-bit
  L2 Cache Size:                                 50331648 bytes
  Maximum Texture Dimension Size (x,y,z)         1D=(131072), 2D=(131072, 65536), 3D=(16384, 16384, 16384)
  Maximum Layered 1D Texture Size, (num) layers  1D=(32768), 2048 layers
  Maximum Layered 2D Texture Size, (num) layers  2D=(32768, 32768), 2048 layers
  Total amount of constant memory:               65536 bytes
  Total amount of shared memory per block:       49152 bytes
  Total shared memory per multiprocessor:        102400 bytes
  Total number of registers available per block: 65536
  Warp size:                                     32
  Maximum number of threads per multiprocessor:  1536
  Maximum number of threads per block:           1024
  Max dimension size of a thread block (x,y,z):  (1024, 1024, 64)
  Max dimension size of a grid size    (x,y,z):  (2147483647, 65535, 65535)
  Maximum memory pitch:                          2147483647 bytes
  Texture alignment:                             512 bytes
  Concurrent copy and kernel execution:          Yes with 2 copy engine(s)
  Run time limit on kernels:                     Yes
  Integrated GPU sharing Host Memory:            No
  Support host page-locked memory mapping:       Yes
  Device has ECC support:                        Disabled
  Device supports Unified Addressing (UVA):      Yes
  Device supports Managed Memory:                Yes
  Device supports Compute Preemption:            Yes
  Supports Cooperative Kernel Launch:            Yes
  Device PCI Domain ID / Bus ID / location ID:   0 / 1 / 0
  Compute Mode:                                  
     < Default (multiple host threads can use cudaSetDevice() with device simultaneously) >

Done
```

## `deviceQuery` — full device properties (C++, runtime API)

```text
build/cpp/1_Utilities/deviceQuery/deviceQuery Starting...

 CUDA Device Query (Runtime API) version (CUDART static linking)

Detected 1 CUDA Capable device(s)

Device 0: "NVIDIA GeForce RTX 5070 Ti"
  CUDA Driver Version / Runtime Version          13.3 / 13.3
  CUDA Capability Major/Minor version number:    12.0
  Total amount of global memory:                 15858 MBytes (16628514816 bytes)
  (070) Multiprocessors, (128) CUDA Cores/MP:    8960 CUDA Cores
  GPU Max Clock rate:                            2572 MHz (2.57 GHz)
  Memory Clock rate:                             14001 Mhz
  Memory Bus Width:                              256-bit
  L2 Cache Size:                                 50331648 bytes
  Maximum Texture Dimension Size (x,y,z)         1D=(131072), 2D=(131072, 65536), 3D=(16384, 16384, 16384)
  Maximum Layered 1D Texture Size, (num) layers  1D=(32768), 2048 layers
  Maximum Layered 2D Texture Size, (num) layers  2D=(32768, 32768), 2048 layers
  Total amount of constant memory:               65536 bytes
  Total amount of shared memory per block:       49152 bytes
  Total shared memory per multiprocessor:        102400 bytes
  Total number of registers available per block: 65536
  Warp size:                                     32
  Maximum number of threads per multiprocessor:  1536
  Maximum number of threads per block:           1024
  Max dimension size of a thread block (x,y,z): (1024, 1024, 64)
  Max dimension size of a grid size    (x,y,z): (2147483647, 65535, 65535)
  Maximum memory pitch:                          2147483647 bytes
  Texture alignment:                             512 bytes
  Concurrent copy and kernel execution:          Yes with 2 copy engine(s)
  Run time limit on kernels:                     Yes
  Integrated GPU sharing Host Memory:            No
  Support host page-locked memory mapping:       Yes
  Alignment requirement for Surfaces:            Yes
  Device has ECC support:                        Disabled
  Device supports Unified Addressing (UVA):      Yes
  Device supports Managed Memory:                Yes
  Device supports Compute Preemption:            Yes
  Supports Cooperative Kernel Launch:            Yes
  Device PCI Domain ID / Bus ID / location ID:   0 / 1 / 0
  Compute Mode:
     < Default (multiple host threads can use ::cudaSetDevice() with device simultaneously) >

deviceQuery, CUDA Driver = CUDART, CUDA Driver Version = 13.3, CUDA Runtime Version = 13.3, NumDevs = 1
Result = PASS
```

## `topologyQuery` — CPU/GPU topology

```text
GPU0 <-> CPU:
  * Atomic Supported: no
```

## CuPy bandwidth benchmark — the `bandwidthTest` replacement

```text
Device: NVIDIA GeForce RTX 5070 Ti
Compute capability: 12.0
Memory bus width: 256-bit
Memory clock: 14001 MHz
Theoretical DRAM bandwidth (clock x 2 x bus/8): 896.1 GB/s

    Size |   H2D page    H2D pin |   D2H page    D2H pin |        D2D
    (MB) |       GB/s       GB/s |       GB/s       GB/s |       GB/s
--------------------------------------------------------------------------
       1 |       6.47       6.85 |       4.55       6.84 |     125.21
       8 |       6.50       6.99 |       6.70       7.11 |     994.48
      32 |       6.38       6.95 |       6.93       7.19 |     493.88
     128 |       6.42       6.93 |       7.11       7.16 |     380.30
     512 |       6.49       6.94 |       7.15       7.20 |     380.71

Note: D2D column counts the copy size once (bandwidthTest convention).
      Actual DRAM traffic is 2x that figure (one read + one write).
```

## `alignedTypes` — global-memory copy throughput by type

```text
[./alignedTypes/alignedTypes] - Starting...
GPU Device 0: "Blackwell" with compute capability 12.0

[NVIDIA GeForce RTX 5070 Ti] has 70 MP(s) x 128 (Cores/MP) = 8960 (Cores)
> Compute scaling value = 1.00
> Memory Size = 49999872
Allocating memory...
Generating host input data array...
Uploading input data to GPU memory...
Testing misaligned types...
uint8...
Avg. time: 1.014156 ms / Copy throughput: 45.916012 GB/s.
	TEST OK
uint16...
Avg. time: 0.510344 ms / Copy throughput: 91.244404 GB/s.
	TEST OK
RGBA8_misaligned...
Avg. time: 0.293750 ms / Copy throughput: 158.522592 GB/s.
	TEST OK
LA32_misaligned...
Avg. time: 0.176062 ms / Copy throughput: 264.485685 GB/s.
	TEST OK
RGB32_misaligned...
Avg. time: 0.149500 ms / Copy throughput: 311.478330 GB/s.
	TEST OK
RGBA32_misaligned...
Avg. time: 0.137000 ms / Copy throughput: 339.897893 GB/s.
	TEST OK
Testing aligned types...
RGBA8...
Avg. time: 0.291781 ms / Copy throughput: 159.592195 GB/s.
	TEST OK
I32...
Avg. time: 0.287062 ms / Copy throughput: 162.215581 GB/s.
	TEST OK
LA32...
Avg. time: 0.175437 ms / Copy throughput: 265.427921 GB/s.
	TEST OK
RGB32...
Avg. time: 0.137375 ms / Copy throughput: 338.970049 GB/s.
	TEST OK
RGBA32...
Avg. time: 0.136344 ms / Copy throughput: 341.533883 GB/s.
	TEST OK
RGBA32_2...
Avg. time: 0.139406 ms / Copy throughput: 334.031006 GB/s.
	TEST OK

[alignedTypes] -> Test Results: 0 Failures
Shutting down...
Test passed
```

## `transpose` — shared-memory transpose variants

```text
Transpose Starting...

GPU Device 0: "Blackwell" with compute capability 12.0

> Device 0: "NVIDIA GeForce RTX 5070 Ti"
> SM Capability 12.0 detected:
> [NVIDIA GeForce RTX 5070 Ti] has 70 MP(s) x 128 (Cores/MP) = 8960 (Cores)
> Compute performance scaling factor = 1.00

Matrix size: 1024x1024 (32x32 tiles), tile size: 32x32, block size: 32x16

transpose simple copy       , Throughput = 2186.2688 GB/s, Time = 0.00357 ms, Size = 1048576 fp32 elements, NumDevsUsed = 1, Workgroup = 512
transpose shared memory copy, Throughput = 2134.4695 GB/s, Time = 0.00366 ms, Size = 1048576 fp32 elements, NumDevsUsed = 1, Workgroup = 512
transpose naive             , Throughput = 372.2734 GB/s, Time = 0.02099 ms, Size = 1048576 fp32 elements, NumDevsUsed = 1, Workgroup = 512
transpose coalesced         , Throughput = 999.7977 GB/s, Time = 0.00781 ms, Size = 1048576 fp32 elements, NumDevsUsed = 1, Workgroup = 512
transpose optimized         , Throughput = 2189.7983 GB/s, Time = 0.00357 ms, Size = 1048576 fp32 elements, NumDevsUsed = 1, Workgroup = 512
transpose coarse-grained    , Throughput = 2164.9431 GB/s, Time = 0.00361 ms, Size = 1048576 fp32 elements, NumDevsUsed = 1, Workgroup = 512
transpose fine-grained      , Throughput = 2202.4414 GB/s, Time = 0.00355 ms, Size = 1048576 fp32 elements, NumDevsUsed = 1, Workgroup = 512
transpose diagonal          , Throughput = 2043.1888 GB/s, Time = 0.00382 ms, Size = 1048576 fp32 elements, NumDevsUsed = 1, Workgroup = 512
Test passed
```

## `UnifiedMemoryPerf` — unified vs explicit copy, by size

```text
GPU Device 0: "Blackwell" with compute capability 12.0

Running ........................................................

Overall Time For matrixMultiplyPerf 

Printing Average of 20 measurements in (ms)
Size_KB	 UMhint	UMhntAs	 UMeasy	  0Copy	MemCopy	CpAsync	CpHpglk	CpPglAs
4	  0.118	  0.121	  0.670	  0.011	  0.024	  0.063	  0.025	  0.020
16	  0.141	  0.128	  1.204	  0.032	  0.034	  0.029	  0.036	  0.034
64	  0.239	  0.237	  1.520	  0.142	  0.077	  0.067	  0.074	  0.067
256	  0.502	  0.454	  3.125	  0.814	  0.238	  0.224	  0.220	  0.208
1024	  1.720	  1.524	  9.429	  6.839	  0.981	  0.944	  0.870	  0.860
4096	  6.522	  6.326	 36.912	 59.704	  4.119	  3.981	  4.001	  4.069
16384	 26.869	 25.143	144.480	409.653	 18.536	 18.360	 18.339	 18.558

NOTE: The CUDA Samples are not meant for performance measurements. Results may vary when GPU Boost is enabled.
```

## `LargeKernelParameter` — 4 KB vs 32 KB kernel parameter limit

```text
Kernel 4KB parameter limit - time (us):57.7569
Kernel 32,764 byte parameter limit - time (us):26.6701
Test passed!
```

## PCIe link state and power, sampled during the transfer benchmark

Sampled every 0.4 s. Columns: gen.current, gen.max, gpu.max, host.max, width.current, width.max, clocks.sm, clocks.mem, power, temp, util.

```text
1, 3, 5, 3, 8, 16, 480 MHz, 405 MHz, 12.46 W, 44, 1 %
3, 3, 5, 3, 8, 16, 480 MHz, 405 MHz, 13.48 W, 45, 1 %
3, 3, 5, 3, 8, 16, 480 MHz, 405 MHz, 28.32 W, 46, 100 %
...
3, 3, 5, 3, 8, 16, 480 MHz, 405 MHz, 13.48 W, 45, 1 %
3, 3, 5, 3, 8, 16, 480 MHz, 405 MHz, 28.32 W, 46, 100 %
3, 3, 5, 3, 8, 16, 480 MHz, 405 MHz, 43.51 W, 47, 100 %
...
1, 3, 5, 3, 8, 16, 480 MHz, 405 MHz, 12.40 W, 45, 1 %
1, 3, 5, 3, 8, 16, 480 MHz, 405 MHz, 12.55 W, 45, 4 %
```

The `3,` rows are the link trained up under load. `Max` and `Host Max` are both 3 — Gen 3 is the ceiling this platform offers, regardless of the GPU's Gen 5 capability.

## `nvidia-smi -q` — full dump

<details><summary>Expand (369 lines)</summary>

```text

==============NVSMI LOG==============

Timestamp                                              : Sun Aug 16 12:33:54 2026
Driver Version                                         : 610.57.04 [Deprecated; will be removed in CUDA 14.0. Use KMD Version instead]
CUDA Version                                           : 13.3 [Deprecated; will be removed in CUDA 14.0. Use CUDA UMD Version instead]
KMD Version                                            : 610.57.04
CUDA UMD Version                                       : 13.3

Attached GPUs                                          : 1
GPU 00000000:01:00.0
    Product Name                                       : NVIDIA GeForce RTX 5070 Ti
    Product Brand                                      : GeForce
    Product Architecture                               : Blackwell
    Display Mode                                       : Requested functionality has been deprecated
    Display Attached                                   : Yes
    Display Active                                     : Enabled
    Persistence Mode                                   : Enabled
    Addressing Mode                                    : None
    MIG Mode
        Current                                        : N/A
        Pending                                        : N/A
    Accounting Mode                                    : Disabled
    Accounting Mode Buffer Size                        : 4000
    Driver Model
        Current                                        : N/A
        Pending                                        : N/A
    Serial Number                                      : 0
    GPU UUID                                           : GPU-15e0078a-cb3a-50d1-a40b-94e4d538fc78
    GPU PDI                                            : 0x6d745dfa53335a17
    Minor Number                                       : 0
    VBIOS Version                                      : 98.03.58.00.23
    MultiGPU Board                                     : No
    Board ID                                           : 0x100
    Board Part Number                                  : N/A
    GPU Part Number                                    : 2C05-300-A1
    FRU Part Number                                    : N/A
    Platform Info
        Chassis Serial Number                          : 
        Slot Number                                    : 0
        Tray Index                                     : 0
        Host ID                                        : 1
        Peer Type                                      : Direct Connected
        Module Id                                      : 1
        GPU Fabric GUID                                : 0x0000000000000000
    Inforom Version
        Image Version                                  : G005.0000.98.01
        OEM Object                                     : 2.1
        ECC Object                                     : N/A
        Power Management Object                        : N/A
    Inforom BBX Object Flush
        Latest Timestamp                               : N/A
        Latest Duration                                : N/A
    Inforom Time Data
        Time Run                                       : N/A
    GPU Operation Mode
        Current                                        : N/A
        Pending                                        : N/A
    GPU C2C Mode                                       : Disabled
    GPU Virtualization Mode
        Virtualization Mode                            : None
        Host VGPU Mode                                 : N/A
        vGPU Heterogeneous Mode                        : N/A
    GPU Recovery Action                                : None
    GSP Firmware Version                               : 610.57.04
    IBMNPU
        Relaxed Ordering Mode                          : N/A
    PCI
        Bus                                            : 0x01
        Device                                         : 0x00
        Domain                                         : 0x0000
        Base Classcode                                 : 0x3
        Sub Classcode                                  : 0x0
        Device Id                                      : 0x2C0510DE
        Bus Id                                         : 00000000:01:00.0
        Sub System Id                                  : 0x143C196E
        GPU Link Info
            PCIe Generation
                Max                                    : 3
                Current                                : 1
                Device Current                         : 1
                Device Max                             : 5
                Host Max                               : 3
            Link Width
                Max                                    : 16x
                Current                                : 8x
        Bridge Chip
            Type                                       : N/A
            Firmware                                   : N/A
        Replays Since Reset                            : 9476
        Replay Number Rollovers                        : 8
        Tx Throughput                                  : 1227 KB/s
        Rx Throughput                                  : 958 KB/s
        Atomic Caps Outbound                           : N/A
        Atomic Caps Inbound                            : FETCHADD_32 FETCHADD_64 SWAP_32 SWAP_64 CAS_32 CAS_64 
    Fan Speed                                          : 0 %
    Performance State                                  : P8
    Clocks Event Reasons
        Idle                                           : Not Active
        Applications Clocks Setting                    : Not Active
        SW Power Cap                                   : Not Active
        HW Slowdown                                    : Not Active
            HW Thermal Slowdown                        : Not Active
            HW Power Brake Slowdown                    : Not Active
        Sync Boost                                     : Not Active
        SW Thermal Slowdown                            : Not Active
        Display Clock Setting                          : Not Active
    Clocks Event Reasons Counters
        SW Power Capping                               : 219139 us
        Sync Boost                                     : 0 us
        SW Thermal Slowdown                            : 0 us
        HW Thermal Slowdown                            : 0 us
        HW Power Braking                               : 0 us
    Sparse Operation Mode                              : N/A
    FB Memory Usage
        Total                                          : 16303 MiB
        Reserved                                       : 445 MiB
        Used                                           : 949 MiB
        Free                                           : 14911 MiB
    BAR1 Memory Usage
        Total                                          : 16384 MiB
        Used                                           : 38 MiB
        Free                                           : 16346 MiB
    Conf Compute Protected Memory Usage
        Total                                          : 0 MiB
        Used                                           : 0 MiB
        Free                                           : 0 MiB
    Compute Mode                                       : Default
    Utilization
        GPU                                            : 3 %
        Memory                                         : 12 %
        Encoder                                        : 0 %
        Decoder                                        : 0 %
        JPEG                                           : 0 %
        OFA                                            : 0 %
    Encoder Stats
        Active Sessions                                : 0
        Average FPS                                    : 0
        Average Latency                                : 0
    FBC Stats
        Active Sessions                                : 0
        Average FPS                                    : 0
        Average Latency                                : 0
    DRAM Encryption Mode
        Current                                        : Disabled
        Pending                                        : Disabled
    ECC Mode
        Current                                        : N/A
        Pending                                        : N/A
    ECC Errors
        Volatile
            SRAM Correctable                           : N/A
            SRAM Uncorrectable Parity                  : N/A
            SRAM Uncorrectable SEC-DED                 : N/A
            DRAM Correctable                           : N/A
            DRAM Uncorrectable                         : N/A
        Aggregate
            SRAM Correctable                           : N/A
            SRAM Uncorrectable Parity                  : N/A
            SRAM Uncorrectable SEC-DED                 : N/A
            DRAM Correctable                           : N/A
            DRAM Uncorrectable                         : N/A
            SRAM Threshold Exceeded                    : N/A
        Aggregate Uncorrectable SRAM Sources
            SRAM L2                                    : N/A
            SRAM SM                                    : N/A
            SRAM Microcontroller                       : N/A
            SRAM PCIE                                  : N/A
            SRAM Other                                 : N/A
        Channel Repair Pending                         : No
        TPC Repair Pending                             : No
        Unrepairable Memory                            : N/A
    Retired Pages
        Single Bit ECC                                 : N/A
        Double Bit ECC                                 : N/A
        Pending Page Blacklist                         : N/A
    Remapped Rows                                      : N/A
    Temperature
        GPU Current Temp                               : 43 C
        GPU Current T.Limit Temp                       : 45 C
        GPU Shutdown T.Limit Temp Specification        : -5 C
        GPU Slowdown T.Limit Temp Specification        : -2 C
        GPU Max Operating T.Limit Temp Specification   : 0 C
        GPU Target Temperature Specification           : N/A
        Memory Current Temp                            : N/A
        Memory Max Operating T.Limit Temp Specification: N/A
    GPU Power Readings
        Average Power Draw                             : 12.24 W
        Instantaneous Power Draw                       : 12.49 W
        GPU Ceiling Power Limit
            Current Power Limit                        : 300.00 W
            Requested Power Limit                      : 300.00 W
            Default Power Limit                        : 300.00 W
        GPU Base Power
            Current Base Power                         : N/A
            Requested Base Power                       : N/A
            Default Base Power                         : N/A
        Min Power Limit                                : 250.00 W
        Max Power Limit                                : 330.00 W
    GPU Memory Power Readings 
        Average Power Draw                             : N/A
        Instantaneous Power Draw                       : N/A
    Module Power Readings
        Average Power Draw                             : N/A
        Instantaneous Power Draw                       : N/A
        Current Power Limit                            : N/A
        Requested Power Limit                          : N/A
        Default Power Limit                            : N/A
        Min Power Limit                                : N/A
        Max Power Limit                                : N/A
    Power Smoothing                                    : N/A
    Workload Power Profiles
        Requested Profiles                             : N/A
        Enforced Profiles                              : N/A
    EDPp Multiplier                                    : N/A
    Clocks
        Graphics                                       : 382 MHz
        SM                                             : 382 MHz
        Memory                                         : 405 MHz
        Video                                          : 652 MHz
    Applications Clocks
        Graphics                                       : Requested functionality has been deprecated
        Memory                                         : Requested functionality has been deprecated
    Default Applications Clocks
        Graphics                                       : Requested functionality has been deprecated
        Memory                                         : Requested functionality has been deprecated
    Deferred Clocks
        Memory                                         : N/A
    Max Clocks
        Graphics                                       : 3210 MHz
        SM                                             : 3210 MHz
        Memory                                         : 14001 MHz
        Video                                          : 3090 MHz
    Max Customer Boost Clocks
        Graphics                                       : N/A
    Clock Policy
        Auto Boost                                     : N/A
        Auto Boost Default                             : N/A
    Fabric
        State                                          : N/A
        Status                                         : N/A
        CliqueId                                       : N/A
        ClusterUUID                                    : N/A
        Health
            Summary                                    : N/A
            Bandwidth                                  : N/A
            Route Recovery in progress                 : N/A
            Route Unhealthy                            : N/A
            Access Timeout Recovery                    : N/A
            Incorrect Configuration                    : N/A
            Partition Assigned                         : N/A
    Processes
        GPU instance ID                   : N/A
        Compute instance ID               : N/A
        Process ID                        : 1565
            Type                          : G
            Name                          : /usr/lib/xorg/Xorg
            Used GPU Memory               : 325 MiB
        GPU instance ID                   : N/A
        Compute instance ID               : N/A
        Process ID                        : 1746
            Type                          : G
            Name                          : /usr/bin/kwalletd6
            Used GPU Memory               : 3 MiB
        GPU instance ID                   : N/A
        Compute instance ID               : N/A
        Process ID                        : 1874
            Type                          : G
            Name                          : /usr/bin/ksmserver
            Used GPU Memory               : 3 MiB
        GPU instance ID                   : N/A
        Compute instance ID               : N/A
        Process ID                        : 1876
            Type                          : G
            Name                          : /usr/bin/kded6
            Used GPU Memory               : 3 MiB
        GPU instance ID                   : N/A
        Compute instance ID               : N/A
        Process ID                        : 1877
            Type                          : G
            Name                          : /usr/bin/kwin_x11
            Used GPU Memory               : 154 MiB
        GPU instance ID                   : N/A
        Compute instance ID               : N/A
        Process ID                        : 1903
            Type                          : G
            Name                          : /usr/bin/plasmashell
            Used GPU Memory               : 101 MiB
        GPU instance ID                   : N/A
        Compute instance ID               : N/A
        Process ID                        : 1937
            Type                          : G
            Name                          : /usr/bin/kaccess
            Used GPU Memory               : 3 MiB
        GPU instance ID                   : N/A
        Compute instance ID               : N/A
        Process ID                        : 1938
            Type                          : G
            Name                          : /usr/lib/x86_64-linux-gnu/libexec/polkit-kde-authentication-agent-1
            Used GPU Memory               : 3 MiB
        GPU instance ID                   : N/A
        Compute instance ID               : N/A
        Process ID                        : 2108
            Type                          : G
            Name                          : /usr/bin/flameshot
            Used GPU Memory               : 3 MiB
        GPU instance ID                   : N/A
        Compute instance ID               : N/A
        Process ID                        : 2149
            Type                          : G
            Name                          : /usr/bin/kdeconnectd
            Used GPU Memory               : 3 MiB
        GPU instance ID                   : N/A
        Compute instance ID               : N/A
        Process ID                        : 2188
            Type                          : G
            Name                          : /usr/lib/x86_64-linux-gnu/libexec/DiscoverNotifier
            Used GPU Memory               : 3 MiB
        GPU instance ID                   : N/A
        Compute instance ID               : N/A
        Process ID                        : 2258
            Type                          : G
            Name                          : /usr/lib/x86_64-linux-gnu/libexec/xdg-desktop-portal-kde
            Used GPU Memory               : 3 MiB
        GPU instance ID                   : N/A
        Compute instance ID               : N/A
        Process ID                        : 2412
            Type                          : G
            Name                          : /usr/bin/konsole
            Used GPU Memory               : 3 MiB
        GPU instance ID                   : N/A
        Compute instance ID               : N/A
        Process ID                        : 2443
            Type                          : G
            Name                          : /usr/bin/dolphin
            Used GPU Memory               : 3 MiB
        GPU instance ID                   : N/A
        Compute instance ID               : N/A
        Process ID                        : 2688
            Type                          : G
            Name                          : /opt/google/chrome/chrome https://claude.com/cai/oauth/authorize?code=true&client_id=9d1c250a-e61b-44d9-88ed-5944d1962f5e&response_type=code&redirect_uri=http%3A%2F%2Flocalhost%3A33579%2Fcallback&scope=org%3Acreate_api_key+user%3Aprofile+user%3Ainference+user%3Asessions%3Aclaude_code+user%3Amcp_servers+user%3Afile_upload&code_challenge=8tCeGneQ3EArvQePb5D-ephhItl4SncZLcuMC7IP9Ks&code_challenge_method=S256&state=1WFQ_wXnil70mSAdK1yLOW_gifeX_1nqqGYApHcZSis
            Used GPU Memory               : 3 MiB
        GPU instance ID                   : N/A
        Compute instance ID               : N/A
        Process ID                        : 2732
            Type                          : G
            Name                          : /opt/google/chrome/chrome --type=gpu-process --ozone-platform=x11 --crashpad-handler-pid=2695 --enable-crash-reporter=, --change-stack-guard-on-fork=enable --gpu-preferences=YAAAAAAAAAAgAQAEAAAAAAAAAAAAAGAASAAAAAAAAAABAAAAAAAAAEAAAAAAAAAAAAAAAAAAAAACAAAAAAAAAAAAAAAAAAAAMAAAAAAAAAAwAAAAAAAAAAEAAAAAAAAACAAAAAAAAAAMAAAAAQAAAAAAAAAAAAAACAAAAAAAAAAIAAAAAAAAAA== --shared-files --metrics-shmem-handle=4,i,16145400830234091511,15907328619784115906,262144 --field-trial-handle=3,i,5333793400955105363,123731939696457208,262144 --variations-seed-version=20260816-030043.531000-production --pseudonymization-salt-handle=7,i,14497610698969613647,14539764267232168727,4 --trace-process-track-uuid=3190708988185955192
            Used GPU Memory               : 61 MiB
        GPU instance ID                   : N/A
        Compute instance ID               : N/A
        Process ID                        : 5292
            Type                          : G
            Name                          : /usr/bin/dolphin
            Used GPU Memory               : 3 MiB
        GPU instance ID                   : N/A
        Compute instance ID               : N/A
        Process ID                        : 5335
            Type                          : G
            Name                          : /usr/bin/kate
            Used GPU Memory               : 3 MiB
        GPU instance ID                   : N/A
        Compute instance ID               : N/A
        Process ID                        : 6386
            Type                          : G
            Name                          : /usr/bin/konsole
            Used GPU Memory               : 3 MiB
    Capabilities
        EGM                                            : disabled
```

</details>

---

# Appendix B — What was and was not verified

## Verified by execution

- **All 33 CUDA Python samples were run on this machine.** 32 completed
  successfully; `simpleP2P` waived because the box has one GPU, which is the
  sample's designed behaviour on such a system.
- Every number in the Part II matrix, in every *On this box* block, and in Part I
  traces to a captured log. The raw logs are in the session scratchpad under
  `runlogs/` and `captures/`.
- Repository-layout claims (`Samples/` → `cpp/`, `bandwidthTest` absent, CMake
  build, prebuilt binaries) were confirmed by listing the filesystem.
- Dependency conflicts were confirmed by building the four isolated environments
  and running the affected samples in them.
- The numpy 2.5.2 → 2.4.6 downgrade was confirmed by diffing `pip freeze` before
  and after.

## NOT verified — carried over from the original playbooks

These claims were in the source documents and are reproduced unchanged. **No
attempt was made to test them in this pass**, and they should be treated as the
original author's assertions:

| Playbook | Unverified content |
|---|---|
| 01 | The hardware comparison table (4090 / 3060 / M4 Max / DDR5 / Pi 5 figures); the quantization bytes-per-param constants; the `llama-bench` workflow |
| 03 | **The entire engine comparison.** No engine was installed. llama.cpp, vLLM, Ollama and TensorRT-LLM numbers and claims are all untested here |
| 04 | LoRA/QLoRA/DPO procedures and any implied throughput |
| 05 | The distillation pipeline and filtering yields |
| 06 | KV-quantization quality claims; prompt-caching behaviour |
| 07 | Speculative-decoding speedup figures (2–4x) |
| 08 | Embedding-model recommendations; chunking defaults |
| 09 | Agent-loop and routing claims |
| 10 | All edge-hardware claims (Pi, Jetson, phones, BitNet) — no edge device involved |

## Inferred, not directly measured

- **The predicted decode-speed table in Part I** applies the bandwidth formula to
  the measured 752 GB/s. The bandwidth is measured; the tok/s figures are arithmetic
  from it, not observed inference runs. **One point on it has since been measured**
  (2026-08-18): the formula predicted 63.46 tok/s for an 11.85 GB model and the card
  delivered 56.90, so it runs **~11.5% optimistic**. Every remaining row in that table
  is still arithmetic and should be read as an upper bound.
- **"Model does not fit" thresholds** came from parameter-count arithmetic against
  15.9 GiB, not from attempting to load those models. **This was wrong, and the load was
  attempted** (2026-08-18): Qwen3.6-27B at Q2_K is 26.90 B parameters and runs fully
  GPU-resident with 64K of q8_0 context. The arithmetic had ruled out models this size.
  Thresholds for quantizations and models *other* than the one measured in Part I remain
  arithmetic and remain unverified.
- **The suggestion that the card might be in a chipset rather than CPU-direct slot**
  is a hypothesis. What is measured is `Host Max: 3` and a link that trains to Gen 3
  x8 under load. The cause was not investigated.

## Environment provenance

**The base venv `$CUDA_SAMPLES/python/.venv` is pristine and contains exactly the
original 7 packages.** Verified by `pip freeze` diff against the pre-work snapshot:

```
cuda-bindings==13.3.1   cuda-core==1.0.1      cuda-pathfinder==1.6.0
cuda-python==13.3.1     cupy-cuda13x==14.1.1  numpy==2.5.2
pillow==12.3.0
```

Full disclosure of how that came to be, since it affects how much you should trust
the run results:

- During the first pass, the extras (`cuda-cccl`, `nvtx`, `numba-cuda`, `torch`,
  `mpi4py`) **were** installed into the base venv, which downgraded numpy
  2.5.2 → 2.4.6 via `numba-cuda`'s `numpy<2.5` pin.
- The venv was subsequently **wiped and rebuilt** from the pre-work `pip freeze`
  snapshot. It now matches the original byte-for-byte in package terms, and
  `vectorAdd` was re-run against it to confirm it still works.
- The 9 affected samples were then **re-run from `$VENVS/venv-extras`**, an
  isolated environment outside the project tree. All 9 passed again. The results
  quoted in this document for those samples come from those isolated re-runs, so
  every documented recipe is one that was actually executed as written.

Isolated environments used, all outside the repository:
`venv-extras`, `venv-nvmath`, `venv-rapids`, `venv-ckpt`, `venv-tf`.

To check the base venv has not drifted:

```bash
$CUDA_SAMPLES/python/.venv/bin/pip freeze | wc -l    # expect 7
```

---

*Generated 2026-08-16. Sources: the eleven playbooks in this directory and the 34
READMEs under `cuda-samples/python/`, merged in full.*

