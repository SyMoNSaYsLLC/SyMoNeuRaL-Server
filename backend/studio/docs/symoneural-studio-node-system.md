# SyMoNeuRaL Studio Node System — registry, graph schema, validator, compiler

**Status: implementation plan. This is not authorization to implement.** Task #103 carries it.
Companion to `backend/studio/docs/symoneural-studio-upgrade-scope.md`, which holds the product
direction, the execution targets and the security boundaries; this file holds the data
structures.

Contracts: `ops/docs/MODEL-REGISTRY.md`, `ops/docs/HARDWARE-PROFILES.md`,
`ops/docs/RUNTIME-PROFILES.md`, `ops/docs/GPU-GOVERNOR.md`. Runtime side of the same
architecture: `backend/registry/docs/symoneural-runtime-registry.md`,
`backend/hardware/docs/symoneural-model-hot-swap.md` (task #104).

**Source.** Normalized from `review/symoneural-studio-upgrade-scope-2026-08-22/`, which is
untracked (`.gitignore:166`). The packet's JSON and YAML are kept below as **field-shape
illustration**; where a value describes a machine this is not, it is corrected against the
disk and the correction is marked. See the scope spec §3.4-3.5.

---

## 1. Architecture

Registry-driven, in five layers:

```
1. Node registry          what a node is        (data, not frontend components)
2. Workflow graph schema  what a graph is       (ours, canonical)
3. Studio UI renderer     draws 1 and 2
4. Backend validator      rejects before compiling
5. Compiler + workers     graph -> backend payload -> run
```

A node definition states what the node is, its inputs and outputs, its parameters, the
hardware it needs, the model metadata it requires, the targets it supports, the backends it
compiles to, the validation rules that apply, and the docs/API pages it links to.

**The frontend renders it. The backend validates it. The compiler turns it into
backend-specific jobs. Workers run it.** One definition, four consumers — so a node cannot be
documented differently from how it behaves.

---

## 2. Node registry

Node definitions live in a **data registry, not only hardcoded frontend components.** The
initial source may be YAML, JSON or Python data structures, but it must be serializable by:

```
GET /api/studio/nodes
GET /api/studio/nodes/{node_type}
```

### Required fields

| Field | Notes |
|---|---|
| `type` | e.g. `image.sampler` — namespaced, ours |
| `display_name` | shown on the node |
| `category` | palette grouping |
| `description` | one line |
| `docs_href` | the node's own docs page |
| `api_href` | the matching operation in `/docs` |
| `openapi_operation_id` | set when the node maps to an API route |
| `inputs` / `outputs` | typed ports |
| `parameters` | widget-backed values, with server-side clamps |
| `targets` | which execution targets accept it |
| `backends` | `comfy` \| `diffusers` \| `vllm` \| `local` |
| `model_family` | which families this node is valid for (scope spec §3.5) |
| `hardware` | requirements; every figure **labelled** measured / vendor / projected |
| `model_requirements` | resolved through the model registry |
| `supported_runtimes` | `runtime_id`s that can execute this node (`ops/docs/RUNTIME-PROFILES.md`) |
| `required_model_family` | llm / image / asr / embedding / vision / audio / video |
| `required_model_format` | gguf / safetensors / diffusers / onnx / bin |
| `hardware_badges` | the ten values in scope spec §8 |
| `model_registry_href` | the model registry entry, where applicable |
| `runtime_registry_href` | the runtime registry entry, where applicable |
| `validation` | rules the validator enforces before a compile is attempted |

`node_id` is an **instance** field, not a type field: stable within a graph, and the id that
node-level errors quote.

**Field names, third pass — recorded, not swapped silently**, because three messages on
2026-08-22 used different keys and an implementer reading only one of them builds the wrong
object:

| Canonical | Superseded spellings | From |
|---|---|---|
| `display_name` | `display` | pass 1 |
| `backends` | `supported_backends` | pass 1 |
| `supported_runtimes` | `runtime_candidates` (in the pass-3 example) | pass 3 |
| `required_model_format` | `formats` (in the pass-3 example) | pass 3 |

The pass-3 *field list* and its *example* disagreed with each other — the list says "supported
runtimes" and "required model format", the JSON says `runtime_candidates` and `formats`. The
list wins, because a list of field names is a schema statement and an example is an
illustration. Both spellings are written down here so the disagreement is visible rather than
silently resolved.

### The canonical node contract

```json
{
  "type": "image.prompt",
  "display_name": "Prompt",
  "docs_href": "/studio/docs/nodes/image.prompt",
  "api_href": "/docs#/Studio/validate_studio_workflow",
  "openapi_operation_id": "validate_studio_workflow",
  "inputs": [],
  "outputs": ["conditioning"],
  "targets": ["cloud", "local_customer", "local_owner_nvidia"],
  "backends": ["comfy", "diffusers"],
  "hardware_badges": ["RUNS_LOCAL"]
}
```

### The fuller YAML form, with the corrections marked

Two nodes, showing every field group. **The `image.sampler` entry differs from the packet on
three values**, because the packet's were written from a snapshot and this box runs
FLUX.1-schnell — see scope spec §3.4.

```yaml
nodes:
  - type: image.prompt
    display_name: Prompt
    category: image/text
    description: Text prompt used to create conditioning.
    docs_href: /studio/docs/nodes/image.prompt
    api_href: /docs#/Studio/validate_studio_workflow
    openapi_operation_id: validate_studio_workflow
    model_family: [flux, sdxl]        # sdxl: FUTURE/EXAMPLE, not installed
    inputs: []
    outputs:
      - name: conditioning
        type: conditioning
    parameters:
      - name: text
        type: string
        required: true
        multiline: true
    targets: [cloud, local_customer, local_owner_nvidia]
    backends: [comfy, diffusers]
    hardware:
      min_vram_gb: 0
      recommended_vram_gb: 0
      cuda_required: false
      label: projected
    hardware_badges: [RUNS_LOCAL]
    validation:
      max_text_length: 4096

  - type: image.sampler
    display_name: Sampler
    category: image/generation
    description: Runs denoising/sampling for an image model.
    docs_href: /studio/docs/nodes/image.sampler
    api_href: /docs#/Studio/compile_studio_workflow
    openapi_operation_id: compile_studio_workflow
    model_family: [flux]              # CORRECTED: the only family on this disk
    inputs:
      - name: model
        type: image_model
      - name: positive
        type: conditioning
      # CORRECTED -- no `negative` port for the flux family. At cfg 1.0 the negative
      # prompt is inert (workflows.py:35); a port that cannot reach the engine is barred.
      - name: latent
        type: latent
    outputs:
      - name: latent
        type: latent
    parameters:
      # CORRECTED: the packet had steps 25 / cfg 7, which are SDXL-shaped values.
      # workflows.py:31-32 -- schnell is guidance-distilled; raising cfg destroys the image.
      - name: steps
        type: integer
        min: 1
        max: 80
        default: 4
      - name: cfg
        type: number
        const: 1.0                    # fixed for flux, not a user-facing control
        user_visible: false
      - name: guidance                # FLUX takes guidance as embedded conditioning
        type: number                  # (workflows.py:71, the FluxGuidance node)
        default: 3.5
      - name: sampler
        type: enum
        values: [euler, dpmpp_2m, dpmpp_sde]
        default: euler
    targets: [cloud, local_customer, local_owner_nvidia]
    backends: [comfy, diffusers]
    hardware:
      min_vram_gb: 8                  # label: projected -- derived, never typed in
      recommended_vram_gb: 12
      cuda_required: false
      label: projected
    hardware_badges: [CLOUD_RECOMMENDED, NEEDS_MODEL_DOWNLOAD]
```

And a node from a different family entirely, showing the runtime fields — this is the pass-3
example with its keys normalised to the canonical spellings above:

```json
{
  "type": "llm.chat",
  "display_name": "Chat Model",
  "category": "llm/generation",
  "docs_href": "/studio/docs/nodes/llm.chat",
  "api_href": "/docs#/Runtime/resolve_model_runtime",
  "openapi_operation_id": "resolve_model_runtime",
  "supported_runtimes": ["symoneural-llm", "vllm-cloud"],
  "runtime_registry_href": "/api/runtimes/symoneural-llm",
  "required_model_family": "llm",
  "required_model_format": ["gguf", "safetensors"],
  "model_registry_href": "/api/models?family=llm",
  "targets": ["cloud", "local_customer", "local_owner_nvidia"],
  "hardware_badges": ["RUNS_LOCAL", "CLOUD_RECOMMENDED"]
}
```

**`vllm-cloud` is `installed-not-serving` on this box** — corrected 2026-08-23 at `507e09ee`;
this line read `absent`, which was false (vLLM 0.25.1 is installed outside the repo and imports,
but **no service runs**; `ops/docs/VLLM-BENCH-PARITY.md` §1). `symoneural-llm` is `built`.

**And this correction is an argument for the design in this section, not against it.** A node
listing a runtime does **not** assert that runtime is running — the router refuses by maturity
level and says which. Because the router gates on *serving*, not on *installed*, **the false
`absent` label never granted anything it should not have**: a node naming `vllm-cloud` was
refused before the correction and is still refused after it. That separation is what lets a node
be written once and stay honest as the box changes — and it just absorbed a three-week-old wrong
label without a behaviour change, which is the strongest evidence for it in this file.

Two constraints on the `hardware` block, both from rules already in force:

- **The numbers are derived, not authored.** A hand-typed `min_vram_gb` is the hardcoded model
  table `plugins/reinforce/registry.py` exists to prevent, and it goes stale the first time a
  quantisation changes. Each figure carries its label.
- **A node's docs page is public output** and inherits the assertions
  `tools/build/build_studio.py` already makes: no `corpus.jsonl`, no `build_dataset`, no filesystem
  paths off this box.

---

## 3. Workflow schema

**The SyMoNeuRaL graph is the canonical save format. Do not store ComfyUI prompt JSON as the
product truth.**

```json
{
  "id": "workflow_txt2img_basic",
  "name": "Basic Text to Image",
  "version": 1,
  "target": "auto",
  "nodes": [
    {
      "id": "n_model",
      "type": "image.model_loader",
      "position": {"x": 60, "y": 100},
      "params": {"model_id": "symoneural-image-flux-schnell-q4k"}
    },
    {
      "id": "n_prompt",
      "type": "image.prompt",
      "position": {"x": 60, "y": 320},
      "params": {"text": "cinematic neon city at night"}
    },
    {
      "id": "n_sampler",
      "type": "image.sampler",
      "position": {"x": 430, "y": 220},
      "params": {"steps": 4, "guidance": 3.5, "sampler": "euler"}
    },
    {
      "id": "n_output",
      "type": "image.output",
      "position": {"x": 760, "y": 220},
      "params": {"gallery": true}
    }
  ],
  "edges": [
    {"from_node": "n_model",   "from_output": "model",        "to_node": "n_sampler", "to_input": "model"},
    {"from_node": "n_prompt",  "from_output": "conditioning", "to_node": "n_sampler", "to_input": "positive"},
    {"from_node": "n_sampler", "from_output": "latent",       "to_node": "n_output",  "to_input": "latent"}
  ]
}
```

**Corrected from the packet:** `model_id` was `sdxl-base`, and the sampler params were
`steps: 25, cfg: 7`. There is no SDXL on this box and cfg is fixed at 1.0 for schnell. The
`version` field is what lets the format change without orphaning saved graphs, and it is the
reason `graph.py`'s "may change" caveat gets to stop being true.

---

## 4. Frontend renderer

The frontend loads the node registry and renders the graph. Required regions: canvas · node
palette · inspector panel · queue/log/validation panel · result gallery · docs/API link
affordances · target selector · hardware badge display.

Each node draws: title · category/type · inputs and outputs as ports · parameters · hardware
badges · validation state · docs link · API link.

A parameter marked `user_visible: false` (like `cfg` for flux) is **not drawn**. It is not
drawn-and-disabled: a control the user can see but not move, whose value never varies, reads
as a broken widget.

---

## 5. Validation

```
POST /api/studio/workflows/validate
```

Before compilation or job submission the validator checks: all node types exist · all required
params exist · all edge ports exist · output type matches input type · no cycles unless
explicitly supported · an output node exists where required · the requested target is
supported · hardware requirements are satisfiable **or explicitly unresolved** · model ids
exist in the model registry · raw filesystem paths are rejected · arbitrary Python and
custom-node execution is rejected.

**"Explicitly unresolved" is a first-class result, not a failure.** An unknown local profile
means `NEEDS_LOCAL_AGENT`, not a guess and not a red.

**Validation output preserves node ids:**

```json
{
  "ok": false,
  "errors": [
    {
      "node_id": "n_sampler",
      "node_type": "image.sampler",
      "message": "Sampler recommends 12 GB VRAM; detected profile has 6 GB.",
      "badge": "CLOUD_RECOMMENDED"
    }
  ]
}
```

---

## 6. Target resolver

Runs **after** validation and **before** compile/queue. Input: workflow graph · requested
target · hardware profile · model registry metadata · node registry metadata. Output: status
`allowed` | `cloud_recommended` | `unsupported` · chosen backend · resolved target · badges ·
reason · per-node decisions.

Behaviour and rules: scope spec §6.

---

## 7. Compilation

```
POST /api/studio/workflows/compile
```

Emits one of: Comfy API JSON · Diffusers job JSON · vLLM job JSON · local hardware job JSON.

**Compilation does not execute.** `graph.py`'s `to_prompt` is the existing implementation of
the first of those four, and its `validate` and `inject` are the existing shape of §5.

---

## 8. Execution

```
Studio UI -> POST /api/studio/jobs -> SyMoNeuRaL queue -> worker -> backend runner -> gallery
```

Workers: **Comfy worker** (private Comfy API JSON runner) · **Diffusers worker** (Python
pipeline) · **vLLM worker** (text/LLM) · **local helper** (customer machine, later).

The Comfy worker is private. It is reached through the queue, never by a browser, and never by
proxying an admin surface to a visitor — scope spec §3.2 and §10.

---

## 9. Initial node set

Five nodes only:

`image.model_loader` · `image.prompt` · `image.sampler` · `image.vae_decode` · `image.output`

Bound to the **FLUX.1-schnell GGUF stack in `backend/models/image/`** — `UnetLoaderGGUF`,
`DualCLIPLoaderGGUF`, `VAELoader` — and **not** `CheckpointLoaderSimple`, which has nothing to
load here because `ComfyUI/models/checkpoints/` does not exist. `workflows.py` already
enumerates the installed node set with its required inputs; that enumeration is the input to
this work, not a guess to redo.

Later, and in no committed order: negative prompt (once a family with an unconditional branch
exists) · LoRA/adapter · upscale · img2img · inpaint · audio · video · LLM/chat · tool/API
nodes. Additional model families — **SDXL is the worked FUTURE example** — arrive as registry
entries plus loader nodes, not as a reshaped graph format.

---

## 10. What a green implementation must eventually prove

Tests, or a stamped smoke record beside the code. These are the shape of the checks on #103,
and none of them can pass on a surface that was never run:

- the registry returns the starter nodes
- the validator rejects an unknown node type
- the validator rejects a bad edge type
- the compiler emits Comfy API JSON for the starter workflow
- `/docs` shows Studio routes with stable operation ids
- every node `api_href` points at an operation that exists
- the queue endpoint never exposes a raw Comfy admin surface
- an unresolved customer-local hardware state renders honestly — `NEEDS_LOCAL_AGENT`, not a
  fabricated capability and not a red
- the flux sampler exposes no `negative` port and no movable `cfg`
