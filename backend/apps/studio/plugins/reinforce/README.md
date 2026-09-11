# symoneural_reinforce

A native CUDA inference and compute engine, built from bare-metal
`cuda.core` / `cuda.bindings` primitives and hand-written CUDA C++ kernels
compiled at runtime by NVRTC.

**Nothing here wraps a third-party inference runtime.** Every arithmetic
operation — matmul, reduction, transpose, softmax, activation — executes in a
kernel written as a C++ source string in
[`symoneural/compute/kernels.py`](symoneural/compute/kernels.py) and compiled
through `cuda.core.Program`. CuPy is present as a typed allocation and DLPack
layer only; it never performs the maths.

Target hardware: **NVIDIA GeForce RTX 5070 Ti, Blackwell `sm_120`, 15.9 GiB**,
CUDA 13.3, driver 610.57.04.

---

## Status

Verified on the target box on 2026-08-16:

| | |
|---|---|
| Kernel modules compiling on `sm_120` | **7 / 7** |
| Operators matching a CuPy reference | **10 / 10** (max error 1.5e-5) |
| End-to-end model forward passes | **2 / 2** correct to 1.1e-6 |
| Test suite | **112 passed, 1 skipped** (P2P, waived — one GPU) |
| Benchmarks within 20% of dossier reference | copy, transpose, H2D, D2H, graph replay |

---

## Quick start

```bash
# 1. Isolated environment. Never install into cuda-samples/python/.venv.
python3 -m venv /tmp/symoneural-venv
/tmp/symoneural-venv/bin/pip install -r requirements.txt

# 2. Optional: MPI launcher for the multi-rank path
sudo apt install openmpi-bin

# 3. Verify
./scripts/run_tests.sh              # builds the venv if absent, runs everything
./scripts/run_tests.sh --bench      # plus the benchmark suite
```

```python
from symoneural import Engine

with Engine() as eng:
    print(eng.device_info()["name"])          # NVIDIA GeForce RTX 5070 Ti
    out = eng.mlp_forward([[0.01] * 256])     # custom-kernel forward pass
    total = eng.reduce_sum([1.0] * 2**20)     # 1048576.0
    coop = eng.reduce_sum([1.0] * 2**20, cooperative=True)   # grid.sync() path
```

Serve it:

```bash
/tmp/symoneural-venv/bin/uvicorn symoneural.server.app:app --port 8000
curl -s localhost:8000/device | python3 -m json.tool
curl -s -X POST localhost:8000/v1/mlp -H 'content-type: application/json' \
     -d "{\"rows\": [[$(python3 -c 'print(",".join(["0.01"]*256))')]]}"
```

---

## Layout

```
symoneural_reinforce/
├── symoneural/
│   ├── engine.py            Facade wiring every subsystem in a fixed order
│   ├── core/
│   │   ├── context.py       Device + capability snapshot (probes live properties)
│   │   ├── memory.py        Device / pinned / managed resource pools + accounting
│   │   ├── streams.py       Stream pool, CUDA-event timing, overlap profitability
│   │   ├── green.py         SM partitioning; the 8,8 constraint
│   │   └── errors.py        Exception hierarchy, incl. CapabilityWaived
│   ├── compute/
│   │   ├── kernels.py       Raw CUDA C++ sources (7 modules)
│   │   ├── program.py       NVRTC compilation + cache + include-path resolution
│   │   └── ops.py           Typed operator API over the kernels
│   ├── scheduler/
│   │   ├── allocator.py     Power-of-two block pool, async, thread-safe
│   │   ├── graph.py         CUDA graph capture / replay
│   │   └── queue.py         Continuous batching worker
│   ├── model/micro.py       MicroMLP and MicroAttention (synthetic weights)
│   ├── agents/              Ten-agent platform
│   │   ├── registry.py      Roster, tiers, VRAM residency planning
│   │   ├── prompt.py        Orchestrator prompt, generated from live hardware
│   │   ├── routing.py       Workload -> agent, with honest degradation
│   │   └── licensing.py     Checkpoint sealing + verify-before-decrypt
│   └── server/              FastAPI app + Pydantic schemas
├── bench/                   Benchmark suite vs. the measured dossier figures
├── tests/                   112 tests: engine, server, agents, 4 hw constraints
├── scripts/run_tests.sh     Constraint-aware runner with venv isolation guard
└── docs/                    Modular manual — see docs/README.md
```

---

## Kernels

| Source | Kernels | Technique | Why |
|---|---|---|---|
| `elementwise` | `saxpy`, `add_bias`, `relu`, `gelu_tanh` | grid-stride, templated | shape-independent launch config → one graph serves any batch |
| `vector_copy` | `copy_vec4`, `copy_scalar` | 16-byte `float4` loads | `alignedTypes`: 341 GB/s at 16B vs 45 GB/s at 1B (**7.4x**) |
| `transpose` | `transpose_coalesced` | 32×32 tile, `+1` pad | the pad defeats 32-way bank conflicts; sample saw **5.9x** |
| `matmul` | `matmul_tiled` | 32×32 shared tiles | each DRAM load reused 32× |
| `reduction` | `reduce_sum_stage`, `reduce_max_stage` | 2 loads/thread + warp shuffle | 50% fewer global reads; **752 GB/s** |
| `reduction_cg` | `reduce_single_pass_cg` | `grid.sync()` | one launch instead of two; **708.92 GB/s** |
| `softmax` | `softmax_rows` | max-subtract, shared accumulation | numerically stable; no global atomics |

---

## Hardware constraints encoded in this repo

Four gotchas found during the local CUDA audit. Each is handled in code and
guarded by a regression test in
[`tests/test_constraints.py`](tests/test_constraints.py).

### 1. Green context — never auto-split on 70 SMs

The driver enforces TPC alignment beyond the advertised `min_partition_size`.
Auto-split fails, and so do `56,8`, `48,16` and `32,32` — all returning
`CUDA_ERROR_INVALID_RESOURCE_CONFIGURATION`. **Only `8,8` was accepted.**

```python
from symoneural.core.green import SAFE_SPLIT, default_split
default_split(ctx).as_flag()      # "8,8" — measured, never computed
```

### 2. Cooperative groups — NVRTC needs two include directories

`cooperative_groups.h` includes `<cuda/std/type_traits>`, which ships in
`cuda-cccl`, **not** in the CUDA toolkit include dir. Passing one alone gives
`catastrophic error: cannot open source file "cuda/std/type_traits"`.

```bash
export SYMONEURAL_CUDA_INCLUDE="$CUDA_INC:$SITE/cuda/cccl/headers/include"
```

`resolve_include_paths()` finds both automatically; the env var overrides.

### 3. MPI — a launcher is required, oversubscribed on one GPU

`mpi4py` links the system MPI but ships no launcher. On this box
`libopenmpi40` was present and `mpirun` was not.

```bash
sudo apt install openmpi-bin
mpirun --oversubscribe -np 2 python your_script.py
```

`--oversubscribe` lets two ranks share the single GPU, enough to exercise the
collective path.

### 4. P2P — check topology first, then waive

Single-GPU topology is checked *before* execution, and
`CapabilityWaived` is raised — deliberately **not** a subclass of `DeviceError`.
"Cannot here" is not "broken"; `simpleP2P` follows the same convention.

```python
try:
    ctx.require_devices(2)
except CapabilityWaived:
    ...   # degrade cleanly
```

Over HTTP this surfaces as **501**, not 500.

---

## Measured performance

`./scripts/run_tests.sh --bench` on the target box:

Full-size run (`python -m bench.run_all`), **9/9 within their regime band**:

| Benchmark | Measured | Reference | Ratio | Regime |
|---|---|---|---|---|
| `copy_vec4` D2D, 512 MB | 746 GB/s | 752 GB/s | 0.99x | dram |
| `reduce_sum` 2-stage, 512 MB | 692 GB/s | 752 GB/s | 0.92x | dram |
| `reduce_sum` single-pass CG | 409 GB/s | 709 GB/s | 0.58x | grid-capped |
| `transpose` small, 2048² | 2,815 GB/s | 2,202 GB/s | 1.28x | l2 |
| `transpose` large, 4096² | 727 GB/s | 752 GB/s | 0.97x | l2-straddle |
| `matmul_tiled`, 1024³ | 2,519 GFLOPS | 4,210 GFLOPS | 0.60x | compute |
| H2D pinned | 6.96 GB/s | 6.94 GB/s | 1.00x | pcie |
| D2H pinned | 7.24 GB/s | 7.20 GB/s | 1.01x | pcie |
| CUDA graph replay | **2.27x** | 1.91x | 1.19x | relative |

**Ratios are judged per regime, not against one flat threshold.** An L2-resident
run legitimately reports several times the DRAM figure; a cooperative launch is
structurally slower because its grid is capped so every block stays co-resident.
Comparing across regimes manufactures regressions that are not there — it
reported transpose at 0.33x when the kernel was fine, purely because a 64 MB run
was being measured against a reference taken at 4 MB. `memory_regime()` now
derives the regime from the measured working set against the device's real L2,
so a `--quick` run that shrinks a buffer is reclassified rather than mislabelled.

Honest reading of the gaps: the CG reduction caps its grid at 140 blocks so
every block stays co-resident, which costs throughput against the two-stage
kernel — a deliberate trade for one launch instead of two. The tiled matmul at
512³ is below the sample's figure (measured at a larger size) and roughly **13x
slower than cuBLASLt**. That is the expected result and worth stating plainly:
write custom kernels for what libraries do not cover, not for GEMM.

### Batch scaling — the roofline argument, measured

| Batch | Throughput | vs batch=1 |
|---|---|---|
| 1 | 3,201 rows/s | 1.0x |
| 8 | 25,544 rows/s | 8.0x |
| 64 | 151,447 rows/s | 47.3x |
| 256 | 149,755 rows/s | 46.8x |

Near-linear to batch 64, then flat — the point where the pass stops being
bandwidth-bound. This is why `RequestQueue` batches.

### A measurement bug worth repeating

The first run of this suite reported 34,578 GB/s for a device copy and 8.4
PFLOPS for a 512³ matmul, on a part whose ceiling is 896 GB/s. Cause: CUDA
events recorded on CuPy's stream while kernels launched on a `cuda.core`
stream, so the events timed *submission*, not execution. If a benchmark returns
a number the hardware cannot produce, suspect the harness before the kernel.
See `_time_device` in [`bench/suite.py`](bench/suite.py).

---

## Environment isolation

`cuda-samples/python/.venv` is **pristine** — exactly the 4 packages in its own
`requirements.txt`. Nothing in this repository installs into it.

`scripts/run_tests.sh` refuses to run if `SYMO_VENV` points at it, and prints a
package count at the end so drift is visible:

```
==> primary .venv verification
    .../cuda-samples/python/.venv: 7 packages (pristine)
```

Two extras would damage it if let in: `numba-cuda` pins `numpy<2.5` and
silently downgrades it, and `matrixMulSharedMem` / `pageRank` /
`processCheckpoint` pin `cuda-core` and `cuda-python` versions that contradict
the base stack.

---

## Documentation

See [`docs/README.md`](docs/README.md) for the modular manual and, importantly,
the table mapping each measured figure to the module that consumes it.

## Known limits

- **fp32 only.** No fp16/bf16/fp8 path, so Blackwell's tensor cores are unused —
  the ~13x gap to cuBLASLt is largely this.
- **No model format.** Weights are synthetic and seed-generated. There is no
  safetensors loader and no KV cache.
- **Single GPU only.** P2P and multi-GPU collectives are waived, not implemented.
- **`MicroAttention` is single-head** and has no causal mask.
- **Playbooks 03–10 are unverified carry-over** — see
  [`docs/05-verification.md`](docs/05-verification.md).

---

## The ten-agent platform

An orchestrator delegates across ten specialised agents. Full detail in
[`docs/06-agent-platform.md`](docs/06-agent-platform.md); the essentials:

```python
from symoneural.agents import Router, Workload, build_system_prompt
from symoneural.core.context import DeviceContext

ctx = DeviceContext(0)
print(build_system_prompt(ctx))          # generated from live hardware

d = Router(ctx).route(Workload.GENERATE, latency_budget_ms=2000)
print(d.agent, d.tier.value, d.degraded, d.reason)
```

### What is real, and what is a stub

**Implemented and tested:** the registry and dependency graph, VRAM residency
planning, the routing engine, the generated orchestrator prompt, checkpoint
sealing (Fernet *and* AES-256-GCM), verify-before-decrypt ordering, the audit
trail, and HTTP endpoints for all of it. 45 tests.

**Stubs:** the TRON TVM licence client (`DenyAllVerifier` denies everything —
no chain RPC, no keys), the Akash leasing client (agent declared, no network
code), and QLoRA execution (agent declared and routable, no training loop).
The 1.5B/7B/14B tiers are budgeting abstractions; no language model ships here.

### The constraint that shapes the design

Ten agents cannot all hold a model in 15.9 GiB. Loading one crosses PCIe at
~7 GB/s:

| Tier | VRAM @ Q4 | Load time |
|---|---|---|
| 1.5B | 0.9 GB | ~138 ms |
| 7B | 3.9 GB | ~598 ms |
| 14B | 7.7 GB | ~1,181 ms |

Resident weights are read at ~752 GB/s — a **107× gap**. So a 7B load alone
exceeds a 500 ms interactive budget, and the policy follows directly:

- Keep **1.5B + 7B** resident (the fallback target and the default workhorse).
- **Never evict for an interactive request**, regardless of `allow_evict`.
- **Batch instead of switching** — measured 3,200 → 151,000 rows/s from batch
  1 to 64, a 47× gain, because the work is bandwidth-bound.
- **Report every degradation.** Settling for a smaller resident model is a
  degradation and is flagged as one; a silent downgrade is a correctness bug.

### Two things stated accurately

**Fernet is AES-128-CBC + HMAC-SHA256, not AES-256.** Its 32-byte key splits
into a 16-byte signing key and a 16-byte encryption key. `Aes256GcmSealer` is
provided for when 256-bit is genuinely the requirement.

**Encryption protects checkpoints at rest, not in use.** Once weights are
unsealed into VRAM they are readable by anyone who can attach to the process.
This raises the cost of casual copying and gives you an audit trail; it is not
DRM against someone with access to the machine. The generated prompt instructs
the orchestrator not to claim otherwise.

### Endpoints

`GET /v1/agents` · `GET /v1/prompt` · `POST /v1/route` ·
`GET /v1/route/residency` · `GET /v1/route/stats` ·
`POST /v1/checkpoint/seal` · `POST /v1/checkpoint/unseal` (403 on denial) ·
`GET /v1/checkpoint/audit`
