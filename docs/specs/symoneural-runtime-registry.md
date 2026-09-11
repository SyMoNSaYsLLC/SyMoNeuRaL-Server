# SyMoNeuRaL Runtime Registry and Runtime Router

**Status: proposed. Nothing here is implemented and this commit implements nothing.** Task #104
carries it. Garrett, 2026-08-22: *"Do not implement yet."*

**The idea this file exists to record.** Studio is the **visual surface**. The real core is
ModelOps + RuntimeOps: a model registry, a runtime registry, a target resolver, a hot-swap
manager, a GPU governor, a job queue, and the node/API/docs link contract. Studio is one
window onto that core, not the core itself.

Companions: `docs/specs/symoneural-studio-upgrade-scope.md` (product direction),
`docs/specs/symoneural-model-hot-swap.md` (residency operations),
`docs/specs/symoneural-studio-node-system.md` (nodes).
Contracts: `docs/ops/RUNTIME-PROFILES.md`, `docs/ops/MODEL-REGISTRY.md`,
`docs/ops/HARDWARE-PROFILES.md`, `docs/ops/GPU-GOVERNOR.md`.

**The audit is upstream of this file.** `docs/ops/BOX-REALITY-AUDIT.md` §8 is the authority on
which runtimes exist here. Every runtime named below carries its **maturity level** from
`RUNTIME-PROFILES.md`, and **nothing in this document claims a service is running.** Two are
built, one is source-only, four are absent.

---

## 1. Two registries, and why they are not one

The single most common way this design goes wrong is collapsing them.

| | Answers | Keyed by |
|---|---|---|
| **Model registry** | *What can be served?* | `model_id` |
| **Runtime registry** | *What can serve it?* | `runtime_id` |

A model is a file with a family, a format, a licence and a VRAM cost. A runtime is a process
with an API style, a load strategy and a hot-swap capability. **The same model may be servable
by several runtimes, and the same runtime serves many models** — so a single table would either
duplicate every model per runtime or lose the difference. The **runtime router** (§3) is the
only thing that joins them.

## 2. Runtime registry entries

Fields, per Garrett's list, plus `maturity` which this repo requires:

| Field | Notes |
|---|---|
| `runtime_id` | stable, ours |
| `family` | llama.cpp \| stable-diffusion.cpp \| ComfyUI \| whisper.cpp \| vLLM \| TensorRT-LLM \| Triton |
| `maturity` | `absent` \| `source-only` \| `built` \| `running` \| `measured` — **mandatory** |
| `model_formats` | gguf \| safetensors \| diffusers \| onnx \| bin |
| `api_styles` | openai-compatible \| comfy-prompt \| native-cli \| http-json |
| `targets` | cloud \| local_customer \| local_owner_nvidia \| auto |
| `health_endpoint` | |
| `model_list_endpoint` | |
| `load_strategy` / `unload_strategy` | |
| `hot_swap_support` | `native` \| `restart` \| `none` \| `unknown` |
| `multi_model_support` | `concurrent` \| `one-at-a-time` \| `unknown` |
| `gpu_memory_requirements` | derived; labelled measured / vendor / projected |
| `concurrency_class` | llm \| image \| asr \| embedding \| utility |
| `docs_href`, `api_href`, `openapi_operation_id` | where applicable |

### The seven families, with their roles and their real levels

Roles are Garrett's. Levels are measured — see the audit for the evidence behind each.

```yaml
- runtime_id: symoneural-llm            # llama.cpp fork
  role: primary GGUF/local LLM runtime candidate
  maturity: built                       # engines/symoneural-llm/build/bin/, CUDA compiled in
  targets: [local_customer, local_owner_nvidia]
  api_styles: [openai-compatible, native-cli]
  model_formats: [gguf]
  concurrency_class: llm

- runtime_id: symoneural-diffuse        # stable-diffusion.cpp fork
  role: local/customer/owner image runtime candidate
  maturity: built                       # engines/symoneural-diffuse/build/bin/symoneural-diffuse
  targets: [local_customer, local_owner_nvidia]
  model_formats: [gguf, safetensors]
  concurrency_class: image

- runtime_id: comfy-private             # ComfyUI fork, engines/symoneural-ui
  role: PRIVATE workflow/image runner -- complex image/audio/video graphs, the FLUX bridge
  maturity: source-only                 # main.py present, nothing listening on 8188
  targets: [local_owner_nvidia, cloud]
  api_styles: [comfy-prompt]
  concurrency_class: image
  note: not a public raw product surface -- see upgrade-scope 3.2 and 10

- runtime_id: symoneural-listen         # whisper.cpp
  role: primary ASR runtime candidate
  maturity: absent                      # contrib/ does not exist; no whisper-cli on the box
  targets: [local_customer, local_owner_nvidia]
  concurrency_class: asr

- runtime_id: vllm-cloud
  role: primary CLOUD LLM runtime candidate -- high throughput, OpenAI-compatible,
        future dynamic adapter/LoRA serving where supported
  # Corrected 2026-08-23 at 507e09ee: this read `absent`, which was false. vLLM 0.25.1 is
  # installed at /home/google/.venvs/vllm (outside the repo, created 2026-07-20), imports, and
  # sees the 5070 Ti via torch 2.11.0+cu130. NO service runs. The ladder has no word for
  # "installed, importable, not serving" -- ruling pending, see docs/ops/VLLM-BENCH-PARITY.md §1.
  maturity: installed-not-serving       # NOT a ladder level; a measurement pending a ruling
  targets: [cloud]
  api_styles: [openai-compatible]
  concurrency_class: llm

- runtime_id: nvidia-diagnostics
  role: DIAGNOSTIC/BENCHMARK REFERENCE ONLY -- GPU diagnostics, CUDA benchmarking,
        memory/concurrency experiments, efficiency references
  maturity: absent                      # no contrib/cuda-samples
  note: never blindly copied into app logic; no sample source into product logic without
        a license and security review (test_references_boundary.py:70 already guards this)

- runtime_id: tensorrt-llm | triton     # FUTURE / AUDIT ONLY
  role: future NVIDIA-optimized serving path, after proof
  maturity: absent
  note: CUDA graphs / MPS experiments only where measured
```

## 3. The runtime router

One decision point, so "what will run this, where, and may this user have it?" has one
testable answer.

**Input**

- job type (`llm` | `image` | `asr` | `embedding` | `utility`)
- the workflow graph
- requested target: `cloud` | `local_customer` | `local_owner_nvidia` | `auto`
- detected hardware profile, **with its detection tier** (browser = approximate, agent = measured)
- model registry metadata
- runtime registry metadata
- **current GPU memory and process state** — read, not assumed
- **user account / credit / permission state**

**Output**

- selected runtime · selected model · selected target
- verdict: `allowed` | `queued` | `rejected` | `cloud recommended` | `unsupported`
- **a reason whenever the verdict is not `allowed`**
- docs/API links for the decision — so the UI can explain itself

It routes to: `symoneural-llm` · `symoneural-diffuse` · `comfy-private` · `symoneural-listen` ·
`vllm-cloud` · and TensorRT-LLM/Triton **only when proven**.

### Rules

1. **`queued` and `rejected` are different answers.** The card being busy is not the same as the
   job being impossible, and collapsing them makes a queue look like a failure.
2. **A runtime below `built` is never selected.** The router reads `maturity` and refuses with
   the level in the reason — *"whisper.cpp is absent on this profile"*, not *"unsupported"*.
3. **Never degrade silently.** No substituting a runtime, dropping a node, or falling back to
   CPU to make a job succeed.
4. **A verdict from an `approximate` profile is itself approximate**, and says so.
5. **The GPU state is read at decision time.** `docs/ops/GPU-GOVERNOR.md` — and the reading is
   compute memory, not whole-card, because the whole-card figure includes this box's desktop
   (R-171).
6. **Account/credit/permission is an input, not a wrapper.** A router that decides first and
   checks entitlement afterwards has already told the user they can have something.
7. **The decision is recorded on the job.** Including which target `auto` resolved to.

## 4. Planned API surface

**Planned. None of these routes exists.** Named here so Studio nodes have something to link to,
and so `/docs` can carry stable operation ids — of which the tracked tree currently has
**zero** (audit §4.1).

```
GET  /api/runtimes                  the registry
GET  /api/runtimes/{runtime_id}     one runtime
GET  /api/runtimes/status           health + residency + memory pressure
POST /api/runtimes/load             hot-swap manager
POST /api/runtimes/unload
POST /api/runtimes/switch

GET  /api/models                    the model registry
GET  /api/models/{model_id}
POST /api/models/resolve            the router decision, without running anything

GET  /api/hardware/profiles
POST /api/hardware/probe-report     the local agent posts its findings

POST /api/jobs/llm
POST /api/jobs/image
POST /api/jobs/asr
GET  /api/jobs/{job_id}
```

Each carries `tags=["Runtime"]` or `tags=["Studio"]`, a stable `operation_id`, an honest
request/response schema, and **tests or a stamped smoke record before it may be called green.**

**Note the overlap with the Studio routes** in `symoneural-studio-upgrade-scope.md` §9:
`/api/studio/hardware/*` and `/api/hardware/*` are the same capability under two prefixes, and
`/api/studio/model-registry` overlaps `/api/models`. **One of each, not both.** Deciding which
prefix wins is part of #104 and must happen before either is built — this is the same class of
collision the audit found at `GET /api/studio/nodes` (§4.2), caught earlier this time.
