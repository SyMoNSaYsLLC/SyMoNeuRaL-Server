# SyMoNeuRaL — documentation

The manual (`symoneural-manual.md`, ~8,400 lines) remains the canonical single
file. This directory is a modular view of the same content, sliced so each
concern can be read on its own.

> **Naming, since it is confusing on first read.** The manual's own `<h1>` still
> says "MIT AI Training — Consolidated Manual" and that is deliberate, not an
> oversight: `tools/build_training.py` matches that exact phrase to rebrand the
> document into `site/training.html`, so renaming the heading would silently
> break the purge and put the old name on the live page. The generator asserts
> that nothing remains after it runs, and the live page carries zero occurrences.
> Anything user-facing is already clean; this heading is build input.

> **This is not the only copy of files 01 through 05.** `backend/apps/studio/plugins/reinforce/docs/`
> holds a second set, because the CUDA engine ships with its own documentation.
> The two overlap on twenty files and differ only in that header line. If you are
> editing one, check whether the other needs the same change.

## Contents

| Document | What it covers |
|---|---|
| [01 — Hardware dossier](01-hardware-dossier.md) | Measured specs for the RTX 5070 Ti, the PCIe Gen 3 x8 host bottleneck, bandwidth from four independent sources, and every raw capture. **Every number the benchmark suite compares against comes from here.** |
| [02 — Setup and environments](02-setup-environments.md) | Repository layout, what changed upstream, the pristine-vs-isolated venv policy, and the per-sample runnability matrix. |
| [03 — Playbooks](03-playbooks/) | The eleven AI playbooks, one file each, corrected and cross-referenced to the samples that demonstrate them. |
| [04 — CUDA curriculum](04-cuda-curriculum/) | All 34 sample documents grouped by category, each with its verified *On this box* result and complete upstream README. |
| [05 — Verification record](05-verification.md) | What was proven by execution, what was carried over untested, and environment provenance. |

## Playbooks

| # | Playbook |
|---|---|
| — | [Index and dependency map](03-playbooks/playbook-00-index.md) |
| 01 | [Hardware & the math of inference](03-playbooks/playbook-01.md) |
| 02 | [Transformer anatomy & profiling](03-playbooks/playbook-02.md) |
| 03 | [Inference engines shootout](03-playbooks/playbook-03.md) |
| 04 | [Fine-tuning specialists](03-playbooks/playbook-04.md) |
| 05 | [Distillation & synthetic data](03-playbooks/playbook-05.md) |
| 06 | [KV cache, long context & memory tricks](03-playbooks/playbook-06.md) |
| 07 | [Speed tricks: speculative decoding](03-playbooks/playbook-07.md) |
| 08 | [Local RAG & embeddings](03-playbooks/playbook-08.md) |
| 09 | [Agents & orchestration](03-playbooks/playbook-09.md) |
| 10 | [Edge deployment](03-playbooks/playbook-10.md) |

## Curriculum by category

| Category | Samples | Highlights |
|---|---|---|
| [1_GettingStarted](04-cuda-curriculum/1_GettingStarted.md) | 8 | device query, first JIT kernel, unified memory, nsys profiling |
| [2_CoreConcepts](04-cuda-curriculum/2_CoreConcepts.md) | 20 | reduction, scan, histogram, tiling, graphs, streams, TMA, green context |
| [3_FrameworkInterop](04-cuda-curriculum/3_FrameworkInterop.md) | 2 | custom kernels inside PyTorch and TensorFlow |
| [4_DistributedComputing](04-cuda-curriculum/4_DistributedComputing.md) | 3 | IPC memory pools, MPI gradient averaging, P2P |
| [Utilities](04-cuda-curriculum/Utilities.md) | 1 | the shared helper package |

## Which measurement drives which module

The engine is not merely inspired by these documents — specific figures set
specific defaults. If a number here changes, the corresponding code should too.

| Measurement | Value | Consumed by |
|---|---|---|
| Optimal block size (`launchConfigTuning`) | **64** threads, 2.36x over worst | `compute/ops.py` → `DEFAULT_BLOCK` |
| DRAM bandwidth (`reduction`) | **752 GB/s** | `bench/suite.py` → `REFERENCE["dram_gbs"]` |
| Single-pass CG reduction | **708.92 GB/s** | `compute/ops.py` → `sum_cooperative()` |
| Vectorised access (`alignedTypes`) | 341 vs 45 GB/s (**7.4x**) | `compute/kernels.py` → `copy_vec4` |
| Privatised atomics (`parallelHistogram`) | **89.5x** | shared-memory accumulation in every reducing kernel |
| CUDA graph replay (`cudaGraphs`) | **1.91x** | `scheduler/graph.py` |
| Stream overlap | **1.00 / 0.98 / 0.93x** — no gain | `core/streams.py` → `overlap_is_profitable` |
| PCIe host cap | Gen 3 x8, **~7 GB/s** | `core/context.py` → `pcie_bound`; allocator refuses host spill |
| L2 size | **48 MB** | `core/memory.py` → `escapes_l2()` |
| Green context split | only **8,8** accepted | `core/green.py` → `SAFE_SPLIT` |
| Tiled matmul vs cuBLASLt | 4,210 vs 32,338 GFLOPS | honesty note in `compute/ops.py` |
