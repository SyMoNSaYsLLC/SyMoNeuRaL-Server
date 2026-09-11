# CUDA engine audit — `backend/apps/studio/plugins/reinforce/`

Read-only audit, 2026-08-17. Queue item 8 of `.claude/HANDOVER.md` §5.
Nothing in the repo was modified. No kernel was executed on the GPU.

## 0. Premise correction — where the engine actually is

The task brief (and `.claude/HANDOVER.md` §10's layout block) describes
`symoneural_reinforce/` at the repo root, containing `CMakeLists.txt`, `cmake/`, `build/`,
`bin/`, `CHANGELOG.md`. **None of that describes the engine.** Those five artefacts are the
*vendored NVIDIA samples* tree, `contrib/cuda-samples/`.

The first-party engine is at **`/home/google/Symoneural/backend/apps/studio/plugins/reinforce/`**, moved
there in commit `9b5da84`. It is **pure Python + NVRTC**: 7 CUDA C++ kernel sources held as
Python strings in `symoneural/compute/kernels.py`, compiled at runtime through
`cuda.core.Program`. There is **no C++ build system, no `.cu` file on disk, no CMake, no
compiled artefact** anywhere in the tree. `git ls-files` over the tree returns Python,
Markdown, one shell script and two config files.

`.claude/HANDOVER.md` §10's layout block is stale on this point and is the likely source of
the brief's premise. Worth one line of correction there, since §10 is what the next agent reads.

Verified static machine facts used below (`nvidia-smi`, `frontend/site/docs/01-hardware-dossier.md`):
RTX 5070 Ti, compute capability **12.0** (`sm_120`), 70 SMs, 1536 threads/SM, 65536
registers/block, 100 KB shared/SM, 48 MiB L2, PCIe link currently negotiated at **Gen 1 ×8**
(idle downtrain of the Gen 3 ×8 host cap).

---

## 1. Correctness bugs

Ranked by severity. Confidence and verification status stated per finding.

### 1.1 `multiprocessor_count` silently defaults to 0, collapsing every grid to one block
**`symoneural/core/context.py:149`** — confidence **high**, unverified on hardware.

```python
multiprocessor_count=int(_attr(p, "multiprocessor_count")),
```

Every other `_attr` call in `_probe()` passes an explicit `default=`. This one does not, so
it inherits `_attr`'s own `default: Any = 0` (line 78). `_attr` swallows `AttributeError`
**and `RuntimeError`**, so any driver hiccup or a `cuda.core` release that renames the
property yields `sm_count = 0` with no warning.

Failure scenario: `DeviceContext._probe()` returns `multiprocessor_count = 0`.
`Ops.sm_count = 0` (`compute/ops.py:97`). Then `_grid_for(n, 64, 0, waves=8)` =
`max(1, min(need, 8*0))` = **1**. Every grid-stride kernel — `saxpy`, `relu`, `gelu`,
`add_bias`, both copy kernels — launches **one block of 64 threads** regardless of `n`.
`Ops._reduce` likewise collapses to `grid = max(1, min(…, 0))` = 1. Results stay *correct*
(the grid-stride loops still cover the range); throughput drops by roughly three orders of
magnitude, and nothing raises. This is precisely the "would silently fall back" case.

Second-order effect on published numbers: `memory_clock_khz` defaults to 0 (line 148), so
`theoretical_bandwidth_gbs` becomes `0.0`. That value is served over HTTP by
`Engine.device_info()` → `GET /device`, and embedded verbatim into the generated
orchestrator prompt as "`0 GB/s theoretical`" (`agents/prompt.py:40,74`). A degraded probe
therefore publishes a fabricated-looking figure rather than failing.

The probe-alternatives design in `_attr` is defensible. The *defaults* are the defect: a
missing SM count or memory clock should raise `DeviceError`, not silently become zero.

### 1.2 Output-buffer size is never validated in four operators
**`symoneural/compute/ops.py:152-177` (`copy`), `99-113` (`saxpy`), `180-195` (`transpose`),
`198-215` (`matmul`)** — confidence **high**, unverified on hardware.

`_require_f32` checks dtype and C-contiguity. **Nothing checks that a caller-supplied `out`
/ `dst` is large enough.** `copy` is the clearest:

```python
dst = cp.empty_like(src) if dst is None else dst
n = src.size                       # <- src's size, never compared to dst's
```

Failure scenario: `ops.copy(src, dst)` with `src.size == 2**24` and `dst.size == 2**10`
launches `copy_vec4` over `n4 = 2**22` `float4` elements into a 4 KiB allocation — a
16 MiB out-of-bounds device write. Because the launch is asynchronous and no error check
follows it (see 1.3), the resulting `cudaErrorIllegalAddress` surfaces at whatever
unrelated synchronising call comes next, usually in a different module. Same shape for
`saxpy(out=…)`, `transpose(out=…)` and `matmul(out=…)`; `matmul` additionally never checks
that `out.shape == (m, n)`.

`bench_matmul` and `bench_transpose` both pass explicit `out` buffers, so this path is
exercised in-tree — it is correct today only because the callers happen to size correctly.

### 1.3 No asynchronous error check after any launch
**`symoneural/compute/ops.py`, all launch sites** — confidence **high**, unverified on hardware.

`cuda.core.launch()` reports launch-time failures synchronously, but an illegal address, a
misaligned access or a `too many resources requested` inside the kernel is asynchronous.
There is no `cudaGetLastError`-equivalent anywhere, and only `_reduce` and
`sum_cooperative` sync at all. `relu_`, `gelu_`, `add_bias_`, `saxpy`, `copy`, `transpose`,
`matmul` and `softmax_` all return immediately with the work in flight.

The vendored samples check every call (`checkCudaErrors` in `contrib/cuda-samples/Common/`).
The consequence here is diagnostic, not numeric: a fault raised by 1.2 or by a bad launch
config is attributed to the next unrelated operator. Given that the engine sits behind a
FastAPI process serving a public site, that turns a localisable bug into a mystery 500.

### 1.4 `BlockAllocator.allocate()` checks capacity outside the lock that records it
**`symoneural/scheduler/allocator.py:100-133`** — confidence **high** on the code shape,
**unverified** that any caller is concurrent today (see 2.2).

The class docstring says "Thread-safe: the request queue may hand work to multiple workers."
The capacity test reads `self.stats.bytes_reserved` inside the first `with self._lock`
block (lines 114-122), then **releases the lock** for `self.pools.alloc_device(size, …)`
(line 125), then re-acquires it to do `self.stats.bytes_reserved += size` (line 128).

Failure scenario: `capacity_bytes = 8 GiB`, four worker threads each call
`allocate(4 * 2**30)` simultaneously. All four read `bytes_reserved == 0`, all four pass the
check, all four call `alloc_device`. 16 GiB is requested against a 15.92 GiB card with
~946 MiB already resident; the driver OOMs and `alloc_device` raises, wrapped as
`AllocationError`. The check that exists to "fail fast rather than letting the driver
thrash" is exactly what fails to fire. Fix is to reserve the bytes optimistically inside the
first critical section and roll back on allocation failure.

### 1.5 `BlockAllocator.free()` performs no stream or event synchronisation
**`symoneural/scheduler/allocator.py:135-143`** — confidence **medium-high**, unverified.

The module is titled "Block-based **asynchronous** device allocator". `free()` sets
`in_use = False` and pushes the block onto the free list with no event recorded and no
stream wait. A block freed while a kernel is still reading it can be handed to the next
`allocate()` and written by a different consumer immediately. PyTorch's caching allocator —
cited in the module docstring as the model — solves this with `record_stream`/events.

Mitigating: `BlockAllocator` is constructed with a single `stream` and, in practice, that
stream is `StreamScheduler.default`, so single-stream use is ordered by construction. The
hazard is latent, and becomes live the moment anyone passes a second stream or uses
`StreamScheduler.acquire()`.

### 1.6 `MemoryPools` accounting is keyed on `id()` of an unreferenced object, and `close_all` is a no-op
**`symoneural/core/memory.py:97, 163-166`** — confidence **high**, unverified.

```python
self._live[id(buf)] = (kind, nbytes)      # line 97 — no reference to buf is kept
```

The dict stores a tuple, not the buffer, so nothing keeps `buf` alive. Once a caller drops
its reference and CPython frees the object, **`id()` is available for reuse**. A later
allocation landing on the same address silently overwrites the record; a subsequent
`release()` on it subtracts the *old* buffer's byte count from `pinned_live`. The class
whose stated purpose is "so a leak shows up in `MemoryPools.stats` rather than as a
mysterious hang" therefore reports corrupted numbers under exactly the churn it is meant to
watch. (`BlockAllocator._live` has the same `id()` key but *does* store the object, so it is
safe — the two differ, and only one is wrong.)

```python
def close_all(self, stream=None) -> None:
    for buf in list(self._live):
        pass                     # ids only; buffers are released by their owners
    self._live.clear()
```

`close_all` frees nothing and does not reset `stats.*_live`. Failure scenario: allocate
1 GiB pinned, call `close_all()`; `live_count` reads 0 while `stats()["pinned_live"]` reads
1 GiB permanently, and the page-locked memory is still held. Every later leak check against
that field is meaningless.

### 1.7 `AllocatorStats.waste_bytes` is arithmetically wrong after the first cache hit
**`symoneural/scheduler/allocator.py:52-54`** — confidence **high**, unverified.

`bytes_requested` is **cumulative across all requests**; `bytes_reserved` is **currently
held**. Subtracting them is a category error. Sequence: `allocate(5 MiB)` → requested 5,
reserved 8, waste correctly 3 MiB. `free()`, then `allocate(5 MiB)` again → requested 10,
reserved 8, `max(0, 8-10)` = **0**. The docstring calls it "a tuning signal"; in any
recycling workload — the workload the allocator exists for — it reads 0 forever.

### 1.8 `StreamScheduler.timed()` silently reports wall-clock as device time
**`symoneural/core/streams.py:119-140`** — confidence **high** on mechanism, unverified
on hardware. **Landmine, not a live fault** (see 2.2).

`self.ctx.device.create_event()` is called with no options. Verified against the installed
`cuda-core==1.0.1`: `EventOptions.timing_enabled` defaults to **`False`**. `cuEventElapsedTime`
on events created without timing returns `CUDA_ERROR_INVALID_HANDLE`, so `float(end - start)`
raises — and line 139's bare `except Exception: dev_ms = wall` swallows it and substitutes
the wall clock.

The context manager's whole documented purpose is that "wall clock on its own measures
launch overhead and Python; events measure the device… a large gap between them is itself
the diagnosis". As written, the gap is always exactly zero and the diagnosis is never
available. Under this project's honesty rules a number labelled `device_ms` that is actually
`wall_ms` is the sharpest form of mislabelling. Fix is one argument:
`create_event(EventOptions(timing_enabled=True))`, and the bare `except` should at minimum
record that it fell back.

`from cuda.core import Event` on line 118 is imported and never used.

### 1.9 `GraphCache.capture()` silently ignores new buffers for an existing key
**`symoneural/scheduler/graph.py:104-105`** — confidence **high**, unverified.

```python
if key in self._graphs and not overwrite:
    return self._graphs[key]        # the caller's `buffers=` argument is discarded
```

The module docstring is explicit that "a graph bakes in the *addresses* passed at capture
time" and that `CapturedGraph` "owns its buffers to make that contract explicit rather than
a footgun". The cache then defeats it: a serving loop that allocates a fresh input tensor
per request and calls `capture("mlp:64x512", stream, record, buffers={"x": new_x})` gets
back the graph bound to **request 1's** addresses. Replay computes on stale data and writes
to a buffer the caller no longer reads. Silent corruption, exactly as the docstring warns,
introduced by the caching layer that warns about it. It should raise when `buffers` differ
from the captured set.

### 1.10 `scripts/run_tests.sh` — the venv guard points at a path that cannot exist
**`backend/apps/studio/plugins/reinforce/scripts/run_tests.sh:42, 159-165`** — confidence **high**, verified
by path expansion.

```bash
PROTECTED="$(cd "$REPO/.." 2>/dev/null && pwd)/cuda-samples/python/.venv"
```

`REPO` = `…/backend/apps/studio/plugins/reinforce`, so `$REPO/..` = `…/backend/apps` and `PROTECTED`
resolves to `/home/google/Symoneural/backend/apps/cuda-samples/python/.venv`. The real path
is `/home/google/Symoneural/contrib/cuda-samples/python/.venv` — the tree moved under
`contrib/` in the restructure (`4b6eaba`). Consequences:

1. The refusal guard (lines 43-49) compares `SYMO_VENV` against a directory that does not
   exist, so **it can never fire**.
2. The drift check (158-165) tests `-x "$PRIMARY/bin/pip"` on the same dead path and
   therefore **always** takes the `else` branch, printing
   `(primary venv not present; nothing to verify)`. README lines 239-245 claim the script
   "prints a package count at the end so drift is visible" and quote sample output reading
   `7 packages (pristine)`. **That output cannot be produced by the script as shipped.**

Point 2 is **verified by direct reproduction**, not inferred: the `-x "$PRIMARY/bin/pip"`
test from line 160 was run against both candidate paths. The stale path takes the `else`
branch; the real path would take the `if` branch. The script as shipped can only print
"not present".

Scope, stated accurately: this is *not* a live path to clobbering the pinned venv. Line 57
gates installation on `[[ ! -x "$PY" ]]`, and
`contrib/cuda-samples/python/.venv/bin/python` is executable, so pointing `SYMO_VENV` there
skips the install block entirely and the run fails on missing pytest instead. The live
exposures are (a) the drift check being dead while README says it works, and (b) line 84,
which *prints* `$SYMO_VENV/bin/pip install 'cuda-cccl[cu13]>=1.0.0'` as remediation — a
human following that with `SYMO_VENV` mispointed would execute it by hand.

Verified independently: `contrib/cuda-samples/python/.venv/bin/pip freeze | wc -l` → **7**.
The venv is intact.

> **Related, and deliberately *not* raised as a defect.** `set -euo pipefail` (line 22) means
> a non-zero `pytest` at line 123 terminates the script before `STATUS=$?` on line 124, so
> `--bench` and the verification block do not run after a test failure. The script's exit
> code is still correct via `set -e`, and skipping benchmarks after a failed suite is
> arguably the right behaviour. Noted only so nobody rediscovers it and mistakes it for the
> `deploy.sh` subshell bug in HANDOVER §1, which it superficially resembles and is not.

### 1.11 `/v1/mlp?batched=true` defeats the batching queue it advertises
**`symoneural/server/app.py:101`** — confidence **high**, unverified end to end.

```python
out = np.stack([eng.infer(r) for r in req.rows])
```

`Engine.infer` is `queue.submit_and_wait` — it **blocks** on each row before submitting the
next. `RequestQueue._collect` therefore never holds more than one request: it takes the
first, then waits the full `max_wait_ms` (5 ms) for a second that cannot arrive because its
submitter is blocked, then gives up. Failure scenario: POST 8 rows with `batched: true` →
8 sequential single-row GPU passes plus ~40 ms of pure batching-timeout latency, versus one
batched pass. `QueueStats.avg_batch` will read 1.0 forever, and `max_batch=8` is never
reached. The correct shape is submit-all-then-wait-all.

README's headline batch-scaling table (3,201 → 151,447 rows/s, 47×) is measured by
`bench_micro_model`, which calls `mlp.forward` directly and never touches the queue. So the
one endpoint that could demonstrate the batching argument is the one that cannot.

---

## 2. Architecture fit

### 2.1 Layout divergence from cuda-samples — justified
The samples are a directory of standalone demos: `cpp/` under CMake with
`CMAKE_CUDA_ARCHITECTURES 75 80 86 87 89 90 100 110 120`, plus `python/` holding one
self-contained script per concept. The engine is an installable package with a
`pyproject.toml`, a layered import graph and a test suite.

**Verdict: the divergence is correct.** A package is the right shape for a library and the
wrong shape to compare against a folder of demos; there is nothing to build ahead of time
because NVRTC compiles at import. The engine borrows the samples' *Python* idiom
(`cuda.core` + CuPy for allocation, kernels as source strings) rather than their C++ one,
which matches how the curriculum in `ops/guides/cuda-curriculum/` was actually run here.

The **accidental** part of the divergence is 1.10: `run_tests.sh` still encodes the
pre-`4b6eaba` path to the samples tree.

### 2.2 Three subsystems are constructed and never used
`Engine.__init__` wires `MemoryPools`, `BlockAllocator`, `GraphCache` and a two-stream
`StreamScheduler`. Grep across the tree (excluding `tests/` and `bench/`):

| Subsystem | Reachable from an execution path? |
|---|---|
| `BlockAllocator` | **No.** Every operator allocates via `cp.empty_like` / `cp.empty`. |
| `GraphCache` | **No.** Only `bench_graph` builds one, and it builds its own. |
| `MemoryPools.alloc_pinned` / `alloc_managed` | **No** caller anywhere, including bench. |
| `StreamScheduler.acquire()` | **No.** Only `.default` is ever read; stream 2 of 2 is idle. |
| `StreamScheduler.timed()` | **No** caller. |

Consequences worth stating plainly:

- `Engine.stats()` reports `allocator` and `memory_pools` counters that are structurally
  always zero, and `graphs` which is always `{}`. Those are served over HTTP by
  `GET /stats` (`server/schemas.py:66`).
- `compute/kernels.py`'s module docstring says ReLU and GELU are "fused with nothing else on
  purpose: the engine composes them through CUDA graphs rather than through ever-wider fused
  kernels." **No code path composes anything through a CUDA graph.** That sentence describes
  an intent, not the implementation.
- `ops/docs/DOCS-INDEX.md`'s "which measurement drives which module" table claims the PCIe cap is
  consumed by "`core/context.py` → `pcie_bound`; allocator refuses host spill". There is no
  host-spill code in the allocator; it raises on a capacity cap and mentions PCIe in the
  message.

This is why 1.4, 1.5, 1.6, 1.8 and 1.9 are **landmines rather than live faults** — they will
fire the first time someone routes real work through these subsystems, which item 12 of the
HANDOVER queue (engines behind an interface) makes likely.

### 2.3 `symoneural/__init__.py` forces a CuPy import to read a string constant
`from .engine import Engine` at package import means `import symoneural.compute.kernels` —
a module containing nothing but Python strings and one dict — fails with
`ModuleNotFoundError: No module named 'cupy'` outside the venv. Encountered directly during
this audit. Lazy-import `Engine` or drop it from `__init__`.

### 2.4 Idioms that do match the samples
`CapabilityWaived` mirroring `simpleP2P`'s waive-don't-fail convention; NVRTC
`name_expressions` for template instantiation; the two-directory include resolution for
`cooperative_groups.h` + libcu++; the stage-2 stride loop in the CG reduction (same
structure and same reason as `reductionMultiBlockCG.py:144-150`). All correct.

---

## 3. sm_120 / Blackwell specifics

### 3.1 All 7 kernel sources compile clean for sm_120 — verified
Compiled to `.cubin` with `nvcc 13.3.73 -arch=sm_120 -std=c++17 -Xptxas -v` into a scratch
directory outside the repo. No GPU execution. All succeed; **zero spill stores and zero
spill loads** in every kernel:

| Kernel | Registers | Shared | Note |
|---|---|---|---|
| `matmul_tiled` | 37 | 8448 B | 37 × 1024 threads = 37,888 ≤ 65,536/block — the `block=(32,32)` config is valid |
| `transpose_coalesced` | 30 | 4224 B | = 32 × 33 × 4, the +1 pad as documented |
| `reduce_single_pass_cg` | 22 | dynamic | |
| `softmax_rows` | 18 | dynamic | |
| `reduce_sum_stage` / `reduce_max_stage` | 15 | dynamic | |
| `copy_vec4` / `copy_scalar` | 14 / 10 | — | |

`elementwise.cu` emits no entry points standalone, as expected: its four kernels are
templates materialised only through NVRTC `name_expressions`. That is the correct idiom.

### 3.2 The cooperative grid is capped at one third of what the hardware holds
**`symoneural/compute/ops.py:259-261, 283-291`** — confidence **high** on the arithmetic,
**unverified** on the throughput consequence.

```python
# All blocks must co-reside: cap at 2 blocks/SM for a 256-thread block
# against the 1536 threads/SM this part supports.
grid = max(1, min(self.sm_count * 2, (n + block - 1) // block))
```

The comment cites 1536 threads/SM and then picks 2 blocks × 256 = **512** threads/SM. It
contradicts itself. The vendored sample this module is modelled on derives the number
instead:

```python
# contrib/cuda-samples/python/2_CoreConcepts/reductionMultiBlockCG/reductionMultiBlockCG.py:184-188
max_blocks_per_sm = max_threads_per_sm // threads_per_block   # 1536 // 256 = 6
max_blocks = max_blocks_per_sm * num_sms                      # 6 * 70 = 420
```

Confirmed against ptxas: `reduce_single_pass_cg` uses 22 registers and 1 KB dynamic shared
memory, so per SM the limits are threads 1536/256 = 6 blocks, registers 65536/(22×256) = 11
blocks, shared 102400/1024 = 100 blocks. **Six blocks per SM are co-resident; 420 blocks
total.** The engine launches **140**.

The sample's own comment notes it is standing in for
`cudaOccupancyMaxActiveBlocksPerMultiprocessor`, which is the API that should be used here
(exposed by the driver bindings already in the dependency set).

**Second cause, same kernel:** `reduce_single_pass_cg` runs its block-level tree all the way
down to `s = 1` with a `cg::sync(cta)` at every level (`kernels.py:324-327` and `338-341`),
while the engine's *own* `reduce_sum_stage` and the sample both cut over to
`__shfl_down_sync` for the final warp. That is 5 extra full-block barriers per reduction.

Why this matters beyond performance: README lines 187 and 195-197 report the CG reduction at
0.58× and explain it as "structurally slower because its grid is capped so every block stays
co-resident", and `REGIME_BANDS` encodes a permissive `(0.45, 1.25)` band called
`grid-capped` to keep that from registering as a regression. **Neither cause is
structural.** One is a hardcoded constant three times below the hardware limit; the other is
a missing shuffle tail the same file already implements elsewhere. A self-imposed cap
presented as a hardware property, with a widened acceptance band protecting it, is the one
finding here that crosses from performance into the honesty rules.

### 3.3 `sm_120` is derived, not hardcoded — sound
`KernelCache(ctx.caps.arch)` takes the architecture from `Device.arch` at runtime and
normalises to `sm_NNN` (`compute/program.py:104`). Nothing pins 120. `pyproject.toml`'s
`keywords = [… "blackwell", "sm_120"]` is metadata only.

### 3.4 `green.py` branches on `multiprocessor_count == 70`
`default_split` (`core/green.py:92-101`) special-cases 70 SMs to return `SAFE_SPLIT = (8,8)`.
Given the documented driver behaviour — auto-split and `56,8`/`48,16`/`32,32` all rejected
with `CUDA_ERROR_INVALID_RESOURCE_CONFIGURATION` — a measured constant is the right call and
the module says so. Two caveats:

- Note `(8,8)` uses **16 of 70 SMs**; the other 54 are unpartitioned. That is a real
  restriction on what a green context can buy here and is not stated.
- **The module never creates a green context.** It has no CUDA import at all — it is
  constants plus arithmetic. Its docstring opens with a measured 5.88× latency improvement
  (26.614 ms → 4.526 ms) taken from the `greenContext` sample, which reads as a property of
  this module. It is not; this module cannot produce it.

### 3.5 No fp16/bf16/fp8 path — honestly disclosed
Every kernel is fp32; `_require_f32` rejects anything else. Blackwell's tensor cores are
therefore unused and the ~13× gap to cuBLASLt follows. README "Known limits" states this
plainly and attributes the gap correctly. No finding — the disclosure is exactly right.

---

## 4. The PCIe Gen 3 ×8 ceiling

### 4.1 The policy layer is sound
`StreamScheduler`'s module docstring carries the measured negative result (1.00× / 0.98× /
0.93× for 2 / 4 / 8 streams) with the structural explanation. `RequestQueue` runs one worker
and cites `overlap_is_profitable` rather than hardcoding. `BlockAllocator` refuses to grow
past a cap rather than spilling to host. `routing.py` never evicts for an interactive
request because a 7B swap exceeds the budget. This is the best-reasoned part of the tree.

### 4.2 But `pcie_bound` is `return True`, unconditionally
**`symoneural/core/context.py:171-179`** — confidence **high**, verified by reading.

```python
@property
def pcie_bound(self) -> bool:
    ...
    return True
```

`core/streams.py:24` states: *"On a Gen 5 ×16 host the same code would benefit; the flag is
computed, not hard-coded off."* It is hard-coded — on. `ops/docs/DOCS-INDEX.md`'s measurement table
lists it as consumed from the PCIe measurement. On a Gen 5 ×16 box the engine would still
report `overlap_profitable: false` over `GET /device`, `recommend_stream_count()` would
still return 1, and the queue would still refuse a second worker. The driver exposes
`pciBusWidth` / link generation; this could be derived.

### 4.3 The serving path never uses pinned memory — the published H2D figure is measured on a path the engine does not take
Confidence **high**, verified by grep.

`MemoryPools.alloc_pinned` documents itself as "the staging buffer for PCIe transfer" and
quotes 6.94 GB/s pinned against 6.49 GB/s pageable. **It has no caller anywhere in the
tree** — not in `engine.py`, not in `ops.py`, not in `bench/`.

The actual host↔device path is `Engine.mlp_forward` / `attention_forward` / `reduce_sum`:
`cp.asarray(np.ascontiguousarray(...))` in, `cp.asnumpy(out)` out. Both are **pageable**
transfers through CuPy. `bench_transfer` (`bench/suite.py:288`) measures with
`cp.cuda.alloc_pinned_memory` — CuPy's own pinned allocator, not `MemoryPools` — and
publishes **6.96 GB/s H2D / 7.24 GB/s D2H** into the README table.

So the tree contains PCIe-aware staging machinery that nothing uses, and publishes a pinned
measurement while every request crosses the link pageable. The numbers are not *wrong* —
they were measured as stated — but the README's implied connection between them and the
engine's transfer strategy does not hold. On the honesty framing this repo uses, the
benchmark should either state that it measures a path the engine does not take, or the
engine should take it.

### 4.4 A full `deviceSynchronize()` on every request
`Engine.mlp_forward` calls `cupy_barrier()` = `cp.cuda.runtime.deviceSynchronize()`
(`ops.py:64`) before every forward pass, from a FastAPI threadpool worker. Correct in
isolation, and the docstring's reasoning is good — but on a box where
`scripts/gpu-governor.sh` serialises tenants, a device-wide sync per HTTP request drains
*everything* on the card, not just this engine's work. Worth knowing before this is wired
into the main API.

---

## 5. Honest labelling

The tree is, overall, unusually disciplined here: `frontend/site/docs/01-hardware-dossier.md` marks
Measured vs theoretical consistently, `bench/suite.py:27` labels the whole `REFERENCE` dict
as measured on this box with a date, `memory_regime()` derives the regime instead of
hardcoding a label, and README's "Known limits" and "What is real, and what is a stub"
sections are candid. The foreign deviceQuery output at
`ops/guides/cuda-curriculum/1_GettingStarted.md:158-184` (132 SMs, cc 8.9) is correctly framed
as upstream "Expected Output" with `<Your GPU Name>` — not a mislabel.

Against that standard, seven items fall short:

1. **The generated orchestrator prompt asserts projections as measured facts.**
   `agents/prompt.py:64-66` tells the model: *"They are measured facts about the machine you
   are running on, not guidance."* The block that follows then includes `swap_seconds_7b` and
   `swap_seconds_14b` (`prompt.py:45-46`), which are `TIER_VRAM[tier] / 1e9 / 7.0` — pure
   arithmetic over an assumed Q4 size for models that, per README, do not ship in this repo.
   Those are **projected**, presented under a sentence that says they are measured. This is
   the most consequential labelling finding, because the consumer is an LLM instructed to
   treat them as physical limits.

2. **Two module docstrings disagree with the code on swap cost, from a GB/GiB conflation.**
   `TIER_VRAM[Tier.RESIDENT] = int(3.9 * 2**30)` = 4.187e9 bytes, so `swap_cost_ms` (÷ 7.0e9)
   = **598 ms**. README's table is *consistent* with the code — checked against all three
   rows, which discriminate cleanly: 138 / 598 / 1181 ms are the GiB basis, whereas a GB
   basis would give 129 / 557 / 1100. But `agents/registry.py:24` and `agents/routing.py:8`
   both state **"roughly 560 ms each way"**, the GB-basis figure. So the narrow, accurate
   claim is: two docstrings are stale by ~7% against the code and the README, and the "3.9
   GB" written throughout the prose actually means 3.9 GiB.

3. **README's tier/load-time table is unlabelled projection.** Lines 305-309: "1.5B | 0.9 GB
   | ~138 ms", etc. Arithmetically correct (see above) but derived, sitting in the same
   document as the measured benchmark table, with no marker distinguishing the two.

4. **`StreamScheduler.timed()` labels wall time as `device_ms`** — see 1.8.

5. **The CG reduction's 0.58× is attributed to a structural cap that is a hardcoded
   constant** — see 3.2. The `grid-capped` regime band `(0.45, 1.25)` institutionalises it.

6. **`core/streams.py:24` says `pcie_bound` "is computed, not hard-coded off"; it is
   `return True`** — see 4.2. `ops/docs/DOCS-INDEX.md` repeats the claim in its measurement table.

7. **README's environment-isolation section is internally inconsistent and describes output
   the script cannot produce.** Line 236 says the samples venv holds "exactly the 4 packages
   in its own requirements.txt"; line 245 quotes "7 packages (pristine)". Both are
   defensible separately — 4 direct requirements, 7 installed with transitives (verified: the
   venv has cuda-bindings, cuda-pathfinder and pillow beyond the 4) — but stated nine lines
   apart without reconciliation, against a project rule that pins the number at 7. And per
   1.10 the quoted output cannot be emitted at all.

Not a finding, but worth recording: `bench_transfer`'s note "PCIe Gen 3 ×8 ceiling ~7.88
GB/s" is a **theoretical** figure printed unlabelled next to a measured one. The dossier
labels it correctly at line 72; the benchmark output does not.

---

## 6. What is sound

Stated with the same specificity as the faults, because several of these are non-obvious
and should survive any future refactor.

- **All 7 kernel modules compile clean for `sm_120` with zero register spills** (§3.1).
  `matmul_tiled`'s 37 registers × 1024 threads = 37,888 ≤ 65,536 per block, so the
  `block=(32,32)` launch config is valid by margin, not by luck.
- **`DeviceContext.create_stream(nonblocking=False)` is a genuine and non-obvious
  correctness fix.** Verified against the installed `cuda-core==1.0.1`:
  `StreamOptions.nonblocking` defaults to **`True`**, and a non-blocking stream does not
  order against the legacy default stream that CuPy uses. Making engine streams *blocking*
  is what makes every "CuPy allocates, our kernel computes" handoff safe without a barrier at
  each call site. The docstring's account of the three bugs this caused (34 TB/s benchmark,
  flaky graph-replay test, intermittently wrong MLP) is the right kind of institutional
  memory.
- **The reduction kernels are correct for every block size the callers use.**
  `reduce_sum_stage` / `reduce_max_stage` hand off to `__shfl_down_sync` at exactly the right
  point, and the `blockDim.x >= 64` guard makes the 32-thread case correct too. Traced by
  hand for 32/64/128/256. (They require power-of-two block sizes, which `_reduce`'s fixed
  256 and `softmax_`'s `1 << (bit_length-1)` both guarantee.)
- **`softmax_rows` is numerically stable and correct when `cols < blockDim.x`** — idle
  threads seed `-FLT_MAX` for the max pass and `0` for the sum pass. The block-size formula
  always lands on a power of two in [32, 256].
- **`memory_regime()` deriving the regime from the measured working set against the device's
  real L2**, rather than hardcoding a label per benchmark, with the documented reason (a
  phantom 0.33× transpose "regression" caused by comparing a 64 MB run to a 4 MB reference).
  This is exactly the right instinct.
- **`_time_device` using wall clock plus `deviceSynchronize()` and documenting why CuPy
  events were wrong** (they recorded on CuPy's stream while kernels ran on a `cuda.core`
  stream, timing submission not execution — 34,578 GB/s on a 896 GB/s part). Slightly
  pessimistic and correct, and it says so.
- **`_require_f32` closes a genuinely silent failure mode** — kernels take raw pointers, so
  a float64 array is reinterpreted bytewise into plausible ~1e20 garbage with no error. The
  same reasoning is applied again in `model/micro.py:74-81`, where the explicit
  `.astype(np.float32, copy=False)` guards NumPy's float32 × Python-float → float64
  promotion.
- **`CapabilityWaived` deliberately not subclassing `DeviceError`**, following `simpleP2P`,
  and surfacing over HTTP as **501** rather than 500 (`server/app.py:132`). "Cannot here" is
  correctly distinguished from "broken".
- **`CompilationError` carrying the NVRTC log plus a targeted hint** for the
  `cuda/std/type_traits` failure, and `resolve_include_paths()` finding both the toolkit
  include dir and the cuda-cccl libcu++ headers automatically with an env override. This is
  the single most annoying failure in NVRTC + cooperative groups and it is handled properly.
- **The transpose tile's `+1` pad, the two-elements-per-thread reduction load, and the
  `float4` copy path with an alignment fallback** (`n % 4 == 0` and both pointers 16-byte
  aligned) are all textbook-correct and each cites the sample that measured it.
- **The stub boundary is drawn honestly.** README names `DenyAllVerifier`, the Akash client
  and QLoRA execution as stubs; `get_custodian`'s docstring says outright that the ephemeral
  key is "correct for a demonstration endpoint and wrong for production"; the seal response
  embeds a warning that encryption protects at rest and not in use. Fernet being AES-128-CBC
  and not AES-256 is called out in three places.

---

## 7. Explicitly unverified

Everything below was reasoned from source, installed-package defaults and CPU-only
compilation. **No kernel was executed and no GPU measurement was taken.**

- 1.1, 1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.9, 1.11 — code-shape findings, not observed failures.
- 1.10 is the exception: both halves were reproduced. The path expansion was evaluated, and
  the `-x "$PRIMARY/bin/pip"` branch test was run against both the stale and the real path.
- 1.8 — the `EventOptions.timing_enabled = False` default is verified by introspection of
  the installed `cuda-core==1.0.1`; that `cuEventElapsedTime` consequently raises and the
  bare `except` substitutes wall time is inference from CUDA semantics.
- 3.2 — the 140-vs-420 arithmetic is verified (ptxas register counts + dossier deviceQuery +
  the sample's own formula). The **throughput** consequence of raising the cap, and of adding
  a shuffle tail, is not measured and would need a governor lease to test.
- Every README performance figure was taken at face value. None was re-measured.
- The 112-passed/1-skipped test result in README was not reproduced; the test venv
  (`/tmp/symoneural-venv`) does not currently exist on this box and creating it would
  require `pip install`, which is out of scope here.

## 8. Suggested order if any of this is fixed

Not part of the audit; the fixes are a separate decision.

1. **1.1** (`multiprocessor_count` default) — one line, prevents a silent 1000× slowdown.
2. **1.10** (`run_tests.sh`'s stale `PROTECTED` path) — one line, restores a guard and a
   drift check the project rules depend on.
3. **§5 items 1, 2, 6** — the labelling fixes, since they are what the site's argument rests
   on. Item 2 is two docstrings; item 6 is one `return True`.
4. **1.2 / 1.3** (bounds checks and an async error check) — cheap, and they convert the
   worst class of bug here from mysterious to localised.
5. **3.2** — derive the cooperative grid from occupancy and add the shuffle tail, then
   re-measure before touching README's claim.
6. Everything in §2.2 is dormant. Fix it *when* something starts using it, not before —
   except 1.9, which will corrupt silently the first time it is used.

---

*Audited read-only. `git status` shows no change under `backend/apps/studio/plugins/reinforce/` or
`contrib/cuda-samples/`. Compilation was done into a scratch directory outside the repo.
`contrib/cuda-samples/python/.venv` verified at 7 packages, unmodified. Nothing was
installed into any environment.*
