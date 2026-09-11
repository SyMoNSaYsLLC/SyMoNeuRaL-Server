# SyMoNeuRaL Studio Upgrade Scope — a ComfyUI-shaped Studio that SyMoNeuRaL owns

**Status: proposed direction-lock. Nothing here is implemented and this commit implements
nothing.** Task #103 carries it. Garrett, 2026-08-22: *"Do not implement yet unless explicitly
authorized."* The reason it is written before any folder migration is his: *"so folder
migration does not erase the intended architecture."*

Companion: `backend/studio/docs/symoneural-studio-node-system.md` (registry, graph schema, validator,
compiler). **RuntimeOps half, task #104:** `backend/registry/docs/symoneural-runtime-registry.md`,
`backend/hardware/docs/symoneural-model-hot-swap.md`. Contracts: `ops/docs/MODEL-REGISTRY.md`,
`ops/docs/RUNTIME-PROFILES.md`, `ops/docs/HARDWARE-PROFILES.md`, `ops/docs/GPU-GOVERNOR.md`.
Measured ground truth: `ops/docs/BOX-REALITY-AUDIT.md`.

Read `ops/backend/authority/docs/README.md` first: files in this directory are arguments, not state.
`.claude/HANDOVER.md` is the one state document.

**Source.** Normalized from the scope packet at
`review/symoneural-studio-upgrade-scope-2026-08-22/`, which is untracked
(`.gitignore:166`) and stays that way. Everything in §3 below was **measured against this
disk at `35704e74`**, because the packet was assembled from an uploaded snapshot and history
rather than from the working tree — and §3.4 records three places where that difference
matters.

---

## 1. The direction

Studio becomes the primary workflow surface for image, chat/LLM, model control, local/cloud
execution, and later plugin-style application workflows.

**Visually it is ComfyUI-like:** dark node-graph canvas, draggable nodes, typed ports and
wires, model / prompt / sampler / VAE / output nodes, workflow templates, node-level errors,
queue/progress/result surface, result gallery, node documentation links, node Swagger/OpenAPI
links.

**Architecturally it is SyMoNeuRaL's:** graph schema, node registry, model registry, target
resolver, queue/accounts/credits, and the local/cloud execution policy.

| Layer | Owner |
|---|---|
| Graph UI | SyMoNeuRaL |
| Workflow schema | SyMoNeuRaL |
| Node registry | SyMoNeuRaL |
| Model registry | SyMoNeuRaL |
| Hardware profiles + target resolver | SyMoNeuRaL |
| Queue, accounts, credits boundary | SyMoNeuRaL |
| ComfyUI | **optional private backend/runner only** |
| Diffusers / vLLM / local / cloud runners | allowed later |

**The product rule.** ComfyUI look: yes. ComfyUI workflow backend: yes, privately. Raw public
ComfyUI admin surface: **no**. ComfyUI is a UX reference and a private runner; it is not the
public product shell and not the product core.

### 1.1 Studio is the surface. The core is ModelOps + RuntimeOps.

Added 2026-08-22, and it generalises this whole scope beyond ComfyUI. **Studio is the visual
surface.** The real core is:

| Core component | Where it is specified |
|---|---|
| model registry | `ops/docs/MODEL-REGISTRY.md` |
| **runtime registry** | `backend/registry/docs/symoneural-runtime-registry.md` §2, `ops/docs/RUNTIME-PROFILES.md` |
| target resolver / **runtime router** | §6 here; `symoneural-runtime-registry.md` §3 |
| **hot swap manager** | `backend/hardware/docs/symoneural-model-hot-swap.md` |
| **GPU governor** | `ops/docs/GPU-GOVERNOR.md`, and `ENGINEERING.md` for the rules in force |
| job queue | §5.1 here; `symoneural-model-hot-swap.md` §2 |
| node / API / docs link contract | §9 here; node-system §2 |
| **Backstage-style catalog direction** | §11 here |
| **Nx-style future workspace direction** | §12 here |

Consequences worth stating, because they change what "done" means:

- **A model registry is not a runtime registry.** One answers *what can be served*, the other
  *what can serve it*. The router joins them; collapsing the tables is the design error
  `symoneural-runtime-registry.md` §1 exists to prevent.
- **The graph surface is one client of this core, not its owner.** An LLM chat job, an ASR job
  and a bare API call reach the same router without a canvas.
- **Seven runtime families, at four different maturity levels today.** Two built, one
  source-only, four absent — measured, in `BOX-REALITY-AUDIT.md` §8. **No document in this repo
  may claim a runtime is running.**

---

### 1.2 Studio family — Reinforce and Exp, and what Studio exposes

Added 2026-08-22 from Garrett's pre-migration scope, §4, and his follow-up on what Studio
should expose. **Direction and permission boundary only — nothing here is implemented, and no
file moves on account of it.**

#### The family

| Surface | Role in the family | Where the code is today (measured, `git ls-files`) |
|---|---|---|
| **Studio** | the graph / workflow surface | `backend/apps/studio/` — 145 tracked files |
| **Reinforce** | Studio-family **LoRA / adaptation / reinforcement / training** area | `backend/apps/studio/plugins/reinforce/` — **76 tracked files** |
| **Exp** | Studio-family **experience-plugin** surface | `backend/apps/studio/plugins/exp/` — **28 tracked files** |

**The correction the measurement forces.** The brief asks that *"Reinforce should not remain a
disconnected side plugin."* On this disk it is not one: both Reinforce and Exp are already
`backend/apps/studio/plugins/*`. What is separate is the **Live Stack row**, not the location of
the code. So the deliverable here is the grouping being written down — not a move.

**The Live Stack may keep showing them as separate units,** because that is the current
observable state: each is a distinct running or queued unit that can be tested on its own. That
is allowed and stays allowed through audit and transition. **Studio being offline does not make
Reinforce or Exp unrelated to Studio.**

**What the migration must not do:** it must not treat the separate rows as licence to split
Reinforce or Exp off permanently as unrelated applications.

**Exp's reference posture.** Exp uses the **DeepSeek harness as reference and inspiration
only.** Its code is not to be copied without a licence and security review. The harness is not
in this repository — it is `/home/google/Downloads/deepseek-harness-master.zip` — and **task #89
already owns that comparison**; this section opens no parallel track.

#### What Studio exposes

Three capability tiers, and the third is gated. This is the part that must be settled before
implementation, because it is a permission boundary and retrofitting one of those is how a
public surface ends up able to overwrite a weight file.

**1. Model selection — an ordinary Studio feature.** A node names a runtime, a model and a
target, and the resolver (§6) decides whether that combination is allowed here:

```
Chat Model node
  runtime: vLLM | llama.cpp
  model:   symon-1.0-7b-q4_k_m
  target:  cloud | local_owner_nvidia | local_customer
```

Nothing privileged: this is model routing, and every value is validated against the model
registry and the runtime registry rather than accepted from the graph.

**2. LoRA / adapter control — Studio, through Reinforce.** This is what Reinforce *is*, and the
surface it owns:

```
Studio
└── Reinforce
      ├── LoRA training
      ├── LoRA attach / detach
      ├── adapter stack
      ├── reward / feedback loops
      ├── evals
      ├── merge / export
      └── publish-to-model-registry
```

Some of that machinery already exists in-tree — `rewards.py`, `rollout.py`, `runner.py`,
`presets.py`, `registry.py`, `dataset_guard.py`, `bench/` — which is why Reinforce is the right
home rather than a new surface. **Existing is not the same as proven:** what those modules
actually do on this box is `BOX-REALITY-AUDIT.md`'s question, not this document's.

**3. Base model weight changes — allowed, but owner/admin only.** The gate is the point of this
tier.

| Operation | Owner / admin | Public user |
|---|---|---|
| fine-tune | yes | no |
| quantize | yes | no |
| convert | yes | no |
| merge LoRA into base | yes | no |
| export GGUF / safetensors | yes | no |
| register a new model **version** | yes | no |
| mutate a production base weight in place | — | **never** |
| overwrite an existing model file | — | **never** |
| write an arbitrary path | — | **never** |
| run arbitrary training code | — | **never** |

The four `never` rows are not "public users lack the permission" — **nothing in this system does
them.** They are absent operations rather than restricted ones, and that distinction is what
makes the boundary enforceable: a permission check can be misconfigured, a code path that does
not exist cannot be.

Two consequences that follow directly:

- **New version, never in-place.** Every authorized weight-producing operation *registers a new
  model version*; it does not edit the model it derived from. `MODEL-REGISTRY.md`'s per-entry
  `provenance/license reference` is what makes that auditable, and an in-place mutation would
  destroy the provenance of the thing it overwrote.
- **The current baseline is a protected input.** The four `backend/models/image/` FLUX/Schnell
  files are PROD (`BOX-REALITY-AUDIT.md` §1.1). They are read by these operations and are not a
  legal write target for any of them.

**Not authorized by this section:** no node system, no Reinforce refactor, no weight operation,
no permission code, and no file movement. `PROJECT-TASKS.md` #103 and #104 carry the
implementation, and each already requires a `SMOKE-*.md` that only a real run can write.

---

### 1.3 Studio is a plugin host, and the interface comes before the tenants

Added 2026-08-22. **The migration order is the deliverable of this section**, and it is a rule
about sequence rather than about design:

> **Define the Studio plugin interface first. Then migrate Exp, Reinforce, Harness and Discovery
> into Studio. Do not migrate tenants into a host with no extension contract.**

Garrett's phrasing of the failure it prevents: *"do not build three special cases instead of one
plugin host."* Four tenants each wired in its own way is not a host — it is four forks of the
same decision, and the fourth is the one that discovers the first three disagreed.

**What exists today.** `backend/apps/studio/plugins/__init__.py` already has the beginnings of
one: `PLUGINS = ("discovery", "exp", "reinforce")`, with `load()` refusing a name not in that
tuple (*"add it there first"*), plus `missing()`, `describe()`, and `REQUIRED` / `RECOGNISED` /
`OPTIONAL_PRESENT` sets. So there is a **registration list and a conformance check**, which is
more than nothing and less than a contract: it says which plugins exist and what a plugin is
missing, not what a plugin may *do* — no node contribution, no route contribution, no lifecycle,
no capability declaration.

**The four tenants, and where each stands** (`BOX-REALITY-AUDIT.md` §10.2, §11.1, §11.2):

| Tenant | On disk | Gate |
|---|---|---|
| **Reinforce** | `plugins/reinforce/`, 76 tracked files | already inside Studio; torch absent, so the training path is not exercisable here |
| **Exp** | `plugins/exp/`, 28 tracked files | already inside Studio; DeepSeek-harness comparison is **#89** |
| **Discovery** | `plugins/discovery/`, 7 tracked files | registered, deliberately no router/page/row yet |
| **Harness** | `harness/plugin-comfyui/`, 4 tracked files | **outside** Studio — the one that actually has to move |

**Three of the four are already in the right directory.** So "migrate the tenants into Studio" is
mostly *not* a file move — it is giving them an interface to be tenants *of*. Harness is the
exception and it is four files.

**What the interface has to carry** for the host to be worth having: node contributions (with the
full contract from `symoneural-studio-node-system.md` §2) · route contributions and where they
mount · declared capabilities and required runtimes · a lifecycle that can report *not available
here* without failing the host · and **conformance that is tested**, since `missing()` already
establishes the shape.

**No arbitrary public custom Python nodes.** A plugin host that loads arbitrary code from a public
surface is remote code execution with a friendly name. `custom_nodes/*` is AUDIT
(`BOX-REALITY-AUDIT.md` §7) and the security boundaries in §10 here govern.

**Nothing moves on this section's authority.** Tasks #103 and #104 carry the implementation, and
each already requires a `SMOKE-*.md` that only a real run can write.

---

## 2. Why this time is different — the argument this scope has to win

**A node canvas for this page was already built and deleted.** Roughly a thousand lines:
snap-to-grid, SVG wires, port-type checking. The reasoning is recorded in
`tools/build/build_studio.py:13-22` and again in `backend/apps/studio/routes.py:9`, where it is
called "the largest single decision in this app":

> `comfyui_frontend_package 1.49.6` turned out to be installed in
> `engines/symoneural-ui/.venv`, which is the same production editor ComfyUI itself serves,
> and it computes its API base as `location.pathname.split('/').slice(0,-1).join('/')` —
> meaning sub-path hosting is a supported configuration upstream, not a hack. A hand-written
> canvas would have been a permanently worse copy of a thing already on the disk, and every
> ComfyUI node update would have been a bug in it.

**That argument is still true, and it is fatal to any scope that does not answer it.** If the
goal is to replicate ComfyUI's editor — same node set, same semantics, node catalogue fetched
from `GET /object_info` — then upstream churn is inherited by construction, the copy is
permanently behind, and this canvas gets deleted a third time for the reason it was deleted
the first two.

**The answer, and the whole justification for the work:** the deleted canvas aimed to
*replicate*. This one exists to *own a schema with more than one compile target and more than
one execution target*. ComfyUI's editor speaks exactly one format — ComfyUI's — for exactly
one place to run: wherever that ComfyUI is. It structurally cannot express "this graph, on
the customer's own RTX 3060, if their driver is new enough, otherwise in our cloud, billed to
this account". That is the discriminating constraint, and it is the only one that justifies
the rebuild.

**The test to apply to every line of implementation work:** does this exist because our schema
reaches a target upstream's format cannot, or because we wanted our own version of a node
editor? If the latter, it is the deleted canvas again and it should not be written. A node
type that only ever compiles to Comfy, for only one machine, is a node ComfyUI's own editor
should have drawn.

This scope is therefore a **deliberate reversal of the old UI decision, not greenfield.** What
it preserves from that decision is the part that was right: the private Comfy execution
boundary, the GPU lease and governor discipline, and Comfy prompt compilation where it is
useful. What it removes is raw-public-Comfy-as-product.

---

## 3. Current state, measured on this disk at `35704e74`

### 3.1 Already built and reusable

| Module | Lines | What it is |
|---|---|---|
| `backend/apps/studio/graph.py` | 308 | **The compile target, in one-target form.** SyMoNeuRaL canvas document (`nodes`/`links`) → ComfyUI prompt graph, plus `validate` and `inject`. |
| `backend/apps/studio/workflows.py` | 143 | Stock workflows in Comfy prompt format, every class name and filename read out of the node set installed on this box — not copied from a tutorial. The seed of the templates. |
| `backend/apps/studio/comfy.py` | 422 | The ComfyUI bridge: HTTP queue, WebSocket monitor, GPU lease. Every endpoint documented against the local clone's source line. |
| `backend/apps/studio/plugins/reinforce/registry.py` | — | The model-registry *concept*, implemented: scan-never-hardcode, derive-never-look-up, every figure labelled measured / vendor / projected. |

`graph.py` has three live callers and **no page**: `POST /api/studio/queue`,
`GET /api/studio/workflow/{name}`, and `tools_impl/comfy_tool.execute`. Its own docstring says
the document format "may change; nothing in `site/` produces one". **Freezing that format is
the first deliverable, and it is real work, not documentation.**

### 3.2 The live violation of the product rule

`/studio/editor/*` is a same-origin reverse proxy in front of **ComfyUI's own production
frontend**, in an iframe (`routes.py:7`, `page.html:169`). `ops/Caddyfile:150` reads
`@studio path /studio /studio/*` and reverse-proxies the subtree to `127.0.0.1:8800`, so that
editor is reachable **from the public internet**.

The only thing in front of it is `backend/apps/studio/gate.py`: `SYMONEURAL_STUDIO_ENABLED`
plus `SYMONEURAL_STUDIO_TOKEN`. That module's own docstring is explicit that this is not a
cleared posture:

> As of 2026-08-20 no content filtering and no allow-list are implemented here. That is a
> deliberate pre-launch state, not a cleared posture […] with both variables set, every tool
> runs unrestricted.

So "raw public ComfyUI admin surface: no" is a rule the shipped code **breaks today**,
mitigated by an operator token and by the surface being off most of the time. This is current
state, not a future concern, and it is the one part of this direction that is not
hypothetical.

**Ordering consequence.** #88 ("No tokens while we are testing: take the token requirement off
Studio") pulls the opposite way: **removing the token before removing the raw editor would
publish a ComfyUI admin surface.** #88 comes after.

### 3.3 Swagger is real; Studio's half of it is not wired

- `/docs` **exists and is public.** It is a hand-registered route at `backend/server.py:1808`
  with local assets — which is why `FastAPI(...)` at `api.py:1384` sets `docs_url=None,
  redoc_url=None` while keeping `openapi_url="/openapi.json"`. `ops/Caddyfile:101` proxies
  `/docs*`; `:104` proxies `/openapi.json`. `backend/apps/test_api_reference.py` guards it.
- `/swagger-ui` is a **different document** — the gateway's own, on `:8000`. Two API
  documents, two addresses, neither shadowing the other. Studio operations belong in `/docs`.
- **Studio's routers declare no `tags=` and no `operation_id`.** `routes.py:63-64` is a bare
  `APIRouter()` twice. So there is no `Studio` group in Swagger and no stable operation ids
  for any `api_href` to point at. Fixing that is the precondition for §9 and the smallest
  useful first increment of the whole task.

### 3.4 The packet's examples are illustrative, not a model inventory

Garrett, 2026-08-22: *"The packet examples are illustrative, not authoritative model
inventory. Do not write the Studio spec as if this box currently has SDXL or a ComfyUI
checkpoints directory."*

Their *shape* is right and is kept verbatim in the node-system spec as field-shape
illustration. Their *values* describe a machine this is not, and an MVP built to them would
fail on the first node.

1. **`"model_id": "sdxl-base"`** — there is no SDXL on this box. `backend/models/image/` holds
   `symoneural-image-unet-q4_k.gguf`, `symoneural-image-t5-q8_0.gguf`,
   `symoneural-image-clip.safetensors`, `symoneural-image-vae.safetensors`: FLUX.1-schnell,
   quantised. **`ComfyUI/models/checkpoints/` does not exist at all**, so the
   `CheckpointLoaderSimple` shape every ComfyUI tutorial uses has nothing to load.
2. **`steps: 25, cfg: 7`** — `workflows.py:31-32` is unambiguous: *"`cfg` is 1.0. Schnell is
   guidance-distilled; classifier-free guidance is baked in. Raising cfg does not sharpen the
   image, it destroys it."* The shipped graph uses `steps: 4, cfg: 1.0`. The packet's defaults
   would destroy every render on the only image model present.
3. **A `negative` input port on the sampler node** — `workflows.py:35`: at cfg 1.0 *"the
   negative prompt is inert"*, wired only to satisfy `KSampler`. A negative port on this
   hardware is **a control that does not reach the engine**, which is barred by the same rule
   #79 turns on: every control shown must reach the engine, or it does not get a widget.

**Consequence for the MVP, and it is a design constraint rather than a footnote:** the five
starter nodes are defined against FLUX.1-schnell GGUF loaders, not `CheckpointLoaderSimple`;
`cfg` is not a user-facing control while schnell is the only model; and `negative` is either
absent or badged as inert until a model arrives that has an unconditional branch to steer.

### 3.5 Model families — the node system is family-aware

**The node system is model-family aware.** A family is a first-class property, not an
assumption baked into a node: what a sampler node exposes, and what it means, differs by
family, and the registry says which.

**SyMoNeuRaL may support SDXL, FLUX, Diffusers, Comfy, vLLM and future backends later.** The
schema is written so a family can be added without reshaping the graph format.

**The current first image baseline for this box is the existing SyMoNeuRaL FLUX/Schnell-style
stack in `backend/models/image/`:**

```
symoneural-image-unet-q4_k.gguf      the quantised UNet
symoneural-image-t5-q8_0.gguf        T5-XXL text encoder
symoneural-image-clip.safetensors    CLIP-L text encoder
symoneural-image-vae.safetensors     the autoencoder
```

`ComfyUI/models/checkpoints/` is **absent**, and no SDXL checkpoint is present.

**Four rules for the Schnell/FLUX family, preserved from
`backend/apps/studio/workflows.py:31-35, 71`** and binding on any node that claims this
family:

1. **`cfg` remains 1.0 for Schnell.** It is guidance-distilled; classifier-free guidance is
   baked in.
2. **The negative prompt is inert at cfg 1.0.** There is no unconditional branch to steer, so
   it is wired only to satisfy `KSampler`.
3. **Raising cfg is not a quality improvement for Schnell** — *"it destroys it"*.
4. **FLUX guidance is embedded conditioning**, not SDXL-style classifier-free guidance:
   *"FLUX takes its guidance as an embedded conditioning value, not through cfg"*
   (`workflows.py:71`, the `FluxGuidance` node).

**Rules on this section, all of them Garrett's, 2026-08-22:**

- **The first Studio spec does not require SDXL** and does not require a ComfyUI checkpoints
  directory. Nothing here may imply SDXL is installed.
- **SDXL appears only as a `FUTURE` / `EXAMPLE` model family**, labelled as such wherever it
  appears, never as the current baseline.
- **No new model weights are downloaded**, and **no weights are moved or committed**. The four
  files above are what is here; the registry describes them, it does not fetch them.

---

## 4. Product modes

### 4.1 Simple mode

Preserves the original SyMoNeuRaL single-input principle. The user types one thing — *"make a
cinematic image of X"*, *"turn this into anime"*, *"upscale this"*, *"make a voiceover"*,
*"build a workflow for this model"* — and SyMon converts it into a graph behind the scenes.

The user sees: prompt box, selected template/model, the cost/credit boundary **when one
exists**, queue/progress, result gallery, and an `Open Graph` option.

### 4.2 Graph mode

The ComfyUI-like canvas: load templates, drag nodes, wire typed ports, inspect parameters,
inspect hardware badges, click node docs, click node API/OpenAPI links, validate before run,
compile to an execution target, submit to queue.

### 4.3 Generated graph mode

The bridge between them, and the reason both can exist without a fork:

```
single prompt  ->  SyMon-created graph  ->  editable Studio graph  ->  validated job  ->  result
```

Beginners keep one text box; power users get Comfy-style control; there is one execution path
underneath.

---

## 5. Execution targets

Four names. Three are places; `AUTO` is a request for the resolver in §6 to choose one, never
a fourth place to run.

### 5.1 `CLOUD` — SyMoNeuRaL server/GPU

The customer uses symoneural.com from anywhere and the job runs on our hosted
backend/worker/GPU. **The customer never gets raw ComfyUI, raw CUDA, raw filesystem, or raw
GPU access** — §1's product rule restated as access control, and the thing §3.2 currently
breaks.

Required concepts: cloud worker profile · queue job · model allowlist · timeout · VRAM
admission check · output gallery · billing/credits hook later.

The admission check refuses **before** admission, with the arithmetic, rather than killing a
run halfway through; `plan_residency(free_bytes)` is the existing shape of that. The model
allowlist is what makes the surface auditable, and it is the control `gate.py` says is absent.
**No price, no tier, no plan appears anywhere until Garrett sets one** — the ban on invented
pricing applies here, and `apps/accounts` already refuses to carry a price column.

### 5.2 `LOCAL_CUSTOMER` — unknown customer hardware

The customer may run on their own machine, and **the browser alone cannot reliably know CUDA,
VRAM, driver state, Python, or model paths.** Two detection tiers, never conflated in the UI:

| Tier | What it can know | Label |
|---|---|---|
| **Browser-only** | Approximate only: WebGL/WebGPU adapter strings, rough device class. No VRAM, no driver version, no CUDA. | **approximate** |
| **Local helper/agent/CLI/desktop companion** | A real probe, because it is a process on the machine. | **measured** |

A browser reading may never be presented as a measurement. That is this repo's
measured/vendor/projected rule applied to hardware detection, and it is why
`NEEDS_LOCAL_AGENT` exists as a badge.

The local helper reports: OS · CPU · RAM · GPU vendor · GPU name · VRAM · CUDA/ROCm/Metal
availability · driver version · Python/runtime availability · disk space where a download
needs it.

Studio then recommends compatible workflows and models, optimized alternatives, required
downloads, driver/runtime gaps, and **cloud fallback** when local execution is unsupported or
too small. An unsupported node shows *why* — the specific missing thing. "Unsupported" with no
reason is indistinguishable from a bug.

There is already a desktop client (`desktop-client/`, #94) and a CLI (#90). The probe should be
a capability of something that exists rather than a fourth program a customer installs; which
one is implementation work, not a decision this scope makes.

### 5.3 `LOCAL_OWNER_NVIDIA` — the owner's own NVIDIA box

Garrett's box/server, **treated as a known profile rather than guessed every time** — the one
machine whose numbers are measured. Current class: RTX 5070 Ti, 16 GB, NVIDIA/CUDA path.

Required concepts: profile id **`rtx5070ti-16gb`** · CUDA/NVIDIA worker profile ·
compatibility table · **the same queue contract as cloud**, marked owner/local.

- **No CPU fallback for GPU workloads unless explicitly authorized.** A silent CPU fallback
  turns a four-second render into a twenty-minute one and reports success — the decorative
  indicator failure with a stopwatch attached.
- **Owner/local is not a raw GPU endpoint.** It inherits the single-card lock every surface on
  this box holds (`ENGINEERING.md`): 16303 MiB, one card, and a Studio job queues behind
  chat, training and the miner. RavenCalc remains the exception it already is — CPU symbolic
  algebra, never takes the lock.

### 5.4 `AUTO`

Resolved once by §6 and **recorded on the job**. A run that silently went to cloud because
local was busy is a figure without its label. Cloud fallback is explicit, never automatic
billing or automatic execution.

---

## 6. The target resolver

One function, one place, so "can I run this?" has one answer that can be tested.

**Input:** the workflow graph · the requested target (`cloud` | `local_customer` |
`local_owner_nvidia` | `auto`) · the detected hardware profile, with its detection tier ·
model registry metadata · node registry metadata.

**Output:** status `allowed` | `cloud_recommended` | `unsupported` · the chosen backend · the
resolved target · badges · **a reason whenever the status is not `allowed`** · per-node
decisions.

Rules:

1. **Never degrade silently.** Not supported on the requested target means a reason and a
   recommendation, not a quiet substitution or a dropped node.
2. **A refusal shows its working.** `plan_fit()` sets the pattern: a refusal returns the
   itemised sum, "because *won't fit* with no arithmetic is indistinguishable from a bug".
3. **Node-level incompatibility names the node id and node type.** The user needs to know
   which node to change.
4. **A verdict computed from an `approximate` profile is itself approximate** and says so. The
   resolver may not launder a browser guess into a measurement by passing it through
   arithmetic.
5. **A single-target node is allowed but must carry an obvious badge** — and see §2 for why a
   node that is single-target *and* single-backend is a smell.

---

## 7. Compile targets

The **SyMoNeuRaL graph is the source of truth and the canonical save format.**

```
SyMoNeuRaL Studio graph
  -> Comfy API JSON
  -> Diffusers job
  -> vLLM job
  -> local hardware job
```

Compile rules:

- **Compilation is one-way per run.** The Studio graph compiles into backend-specific job
  payloads; **a backend payload is never the canonical save format**, or the schema is that
  runner's schema wearing our name.
- **Unknown node types are rejected by name.**
- **Unknown model ids are rejected by registry lookup.**
- **Unsupported hardware returns a validation/resolve error before queue submission**, not a
  failure at run time.
- **Node errors preserve node id, and the port or parameter where possible.** `comfy.py`
  already documents why: ComfyUI's `node_errors` "is the single most useful thing to put in
  front of a user with a broken graph, and summarising it would throw away the node id that is
  wrong." Every runner's errors arrive with that fidelity, mapped onto *our* node ids.
- **Compilation does not execute.**

---

## 8. Hardware badges

Ten values. **This supersedes the seven named earlier on 2026-08-22** — `NEEDS_VRAM`,
`NEEDS_CUDA` and `NEEDS_QUEUE` were added by the packet. Recorded as a supersession rather
than swapped silently, because an implementer reading only the earlier list would build the
wrong enum.

| Badge | Means |
|---|---|
| `RUNS_LOCAL` | Fits the detected local profile, with the arithmetic available on demand |
| `CLOUD_RECOMMENDED` | Does not fit locally, or fits so tightly the run is not worth starting |
| `UNSUPPORTED` | No runner on any target can execute it |
| `OWNER_GPU_ONLY` | Runs only on `LOCAL_OWNER_NVIDIA` |
| `NEEDS_LOCAL_AGENT` | Cannot be judged from the browser; requires the §5.2 probe |
| `NEEDS_MODEL_DOWNLOAD` | Capable, but the weights are not present |
| `NEEDS_DRIVER_RUNTIME` | Capable hardware, missing CUDA/ROCm/Metal or a runtime |
| `NEEDS_VRAM` | Short of VRAM for this node at these parameters |
| `NEEDS_CUDA` | Requires CUDA specifically, not just any accelerator |
| `NEEDS_QUEUE` | Cannot run inline; must go through the queue |

**Badges are not decorative.** Each must be backed by registry metadata, hardware probe data,
or an explicit *unknown* state. `CLOUD_RECOMMENDED` on a model whose numbers were never
computed is barred, and so is a badge that renders green because a field was missing.

**What exists, stated precisely.** `plugins/reinforce/registry.py` has `plan_fit()` — a
four-term VRAM projection, itemised so a refusal can show its working — and
`plan_residency(free_bytes)`. It carries the two rules the badge engine needs and the
measured / vendor / projected vocabulary. **But it is LLM-only:** `GGUF_DIR = MODELS_DIR /
"llm"`, `arch_from_config` raises `KeyError` for anything that is not a causal LM, and the
terms are LoRA rank, sequence length and batch. It does **not** compute diffusion fit. The
badge engine therefore **extends** it to diffusion weights — UNet plus text encoders plus VAE,
resident concurrently, no optimiser state. This scope does not claim that arithmetic exists;
overstating existing capability is the same class of error as an unSHA'd figure.

---

## 9. Planned API surface, and Swagger

**Planned. None of these routes exists yet.** The two that exist and overlap are
`POST /api/studio/queue` and `GET /api/studio/workflow/{name}`; migrating from those is part of
the task, not a quiet rename.

```
GET  /api/studio/nodes                  the node catalogue -- ours, not Comfy's /object_info
GET  /api/studio/nodes/{node_type}      one node type
GET  /api/studio/workflows/templates    templates (seeded by workflows.py)
POST /api/studio/workflows/validate     validate without compiling
POST /api/studio/workflows/compile      graph -> chosen backend payload; does not execute
POST /api/studio/jobs                   submit; target is a field on the job
GET  /api/studio/jobs/{job_id}          status, progress, result
POST /api/studio/hardware/probe-report  the local helper posts its findings
GET  /api/studio/hardware/profiles      known profiles, incl. rtx5070ti-16gb
GET  /api/studio/model-registry          the registry, as data
```

Each route carries `tags=["Studio"]`, a stable `operation_id`, an honest request/response
schema, and **tests or a documented smoke record before it may be called green** — see §3.3
for why the tags and ids do not exist yet.

**Swagger/OpenAPI `/docs` exposes these operations.** Documenting a write route is not
authorising it: `POST /api/studio/jobs` belongs in public Swagger and stays behind the gate,
which is `gate.py`'s job.

### Node docs/API link contract

Every node carries `docs_href`, `api_href` and `openapi_operation_id`. Node help links to
whichever applies: the **node docs page**, the matching **`/docs` OpenAPI operation**, the
**model registry entry**, or the **hardware profile explanation**. Full field list and the
canonical JSON contract: `backend/studio/docs/symoneural-studio-node-system.md` §2.

A node's docs page is **public output**, so it inherits the assertions
`tools/build/build_studio.py` already makes: no `corpus.jsonl`, no `build_dataset`, no filesystem
paths off this box.

---

## 10. Security boundaries

**Never exposed:** raw public ComfyUI admin · raw model-folder browser · arbitrary custom-node
installer · arbitrary Python execution · direct GPU access · user-supplied filesystem paths ·
customer access to Garrett's raw GPU endpoint.

**Never committed, and never fetched by this surface:** model weights, caches, virtualenvs,
`node_modules`, `.env` files, databases, raw transcript history. Studio's registry *describes*
weights that are already on disk (§3.5); it does not download them, move them, or put them in
git. `ops/docs/EXPORTS.md` names the artefacts that may never be served or quoted at all.

**Custom nodes are never executed in the serving interpreter.** That interpreter is the
serving path and `ENGINEERING.md` forbids installing into it; an arbitrary-custom-node
runner would be that rule broken by design.

All execution goes through one path:

```
Studio UI -> SyMoNeuRaL API -> validate -> resolve -> compile -> queue -> worker/backend -> gallery
```

---

## 11. Backstage-style catalog direction

**Future direction. Do not install Backstage unless explicitly authorized.** Captured so the
component boundaries are written down before a migration invents different ones.

The value borrowed is the *shape*: every component, API and resource is an entity with an
owner, a docs link and its dependencies — which is the same discipline §9's node/API/docs link
contract applies one level down.

**Components**

```
symoneural-api        symoneural-studio      runtime-router        model-registry
hardware-router       gpu-governor           comfy-private-worker  application-lab
vllm-server           llama-cpp-server       stable-diffusion-cpp-server
whisper-cpp-server
platform-linux        platform-apple         platform-android      platform-windows
```

**Systems**

```
symoneural-server     symoneural-studio      symoneural-platform-targets
```

**APIs**

```
studio-api        runtime-api        model-registry-api
hardware-profile-api               jobs-api
```

**Resources**

```
linux-host              rtx5070ti-16gb          backend-model-store
symoneural-queue        cloud-worker            local-agent
apple-darwin-sdks       windows-mingw-yocto-candidate            android-sdk-candidate
```

`application-lab` and the four `platform-*` components are what stop the catalog from
describing a single web app. `ops/docs/REPOSITORY-PURPOSE.md` is the entity these all hang off:
this repo is the backend/server **proving ground**, applications are **incubated** here before
promotion, and promotion is gated by `GUARDRAILS.md`.

**A catalog entry must carry its maturity, or it lies by omission.** `vllm-server`,
`whisper-cpp-server` and any TensorRT/Triton entry describe runtimes that are **absent** today
(`BOX-REALITY-AUDIT.md` §8.2); `llama-cpp-server` and `stable-diffusion-cpp-server` are
**built**; `comfy-private-worker` is **source-only**. A catalog listing them without a level
reads as an inventory of things that exist.

The same applies to the platform resources, and harder (`BOX-REALITY-AUDIT.md` §9):
`apple-darwin-sdks` is **real** — 3.2 GiB extracted — but `xtool` cannot load `libxadi.so` and
`swift` is not on PATH, so nothing builds for Apple today. `windows-mingw-yocto-candidate` is
named a *candidate* because upstream `meta-mingw` is absent. `android-sdk-candidate` has no
toolchain behind it whatsoever. `linux-host` is the only platform resource that is currently
`running` — it is this box.

---

## 12. Nx-style future workspace direction

**Future direction only. No folder migration now** — and this document exists precisely so a
migration cannot quietly pick different boundaries.

**Future apps**

```
apps/web       apps/api        apps/studio      apps/local-agent
apps/worker-llm               apps/worker-image                apps/worker-asr
apps/apps-lab                 -- incubated applications, classified PROD/AUDIT/REMOVED
apps/platform-linux           apps/platform-apple
apps/platform-android         apps/platform-windows
```

**Future libs**

```
libs/model-registry     libs/runtime-registry    libs/hardware-profiles
libs/studio-graph       libs/openapi-client      libs/queue-contracts
libs/gpu-governor       libs/backstage-catalog
libs/platform-contracts libs/app-contracts
```

`apps/apps-lab` and the four `apps/platform-*` directories exist in this list for one reason:
**a migration must not collapse this repo into a single web app.** It is the SyMoNeuRaL
backend/server proving ground, applications are incubated here before promotion, and the
concepts that must survive intact are listed in `ops/docs/REPOSITORY-PURPOSE.md`.

**Three things to settle before any of this moves**, all of them findings rather than opinions:

1. **`backend/apps/studio/plugins/*` and `custom_nodes/*` are still AUDIT** (audit §5). A
   migration that relocates them before they are classified moves code nobody has decided to
   keep — 112 tracked files in `plugins/` alone.
2. **`libs/gpu-governor` would be the third home for governor knowledge**, after
   `ENGINEERING.md` (rules in force) and `scripts/gpu-governor.sh` (behaviour). That is
   the second-state-document trap; the lib must *contain* the script's logic, not restate it.
3. **The worker split assumes runtimes that mostly do not exist yet.** `apps/worker-asr` has no
   `whisper.cpp` to wrap. Creating the directory does not create the capability, and an empty
   worker app reads as a broken one.
4. **The four `apps/platform-*` directories are gated by `GUARDRAILS.md`, not by this list.**
   All four native platforms are individually held; the browser API is the only cleared build
   surface, and no platform build starts on inference. Creating the directories early would
   present gated work as cleared — the specific failure `GUARDRAILS.md` says "no numbered tasks
   exist for the four" to avoid. **Toolchains are the carve-out and are not held.**

---

## 13. First implementation milestone

Small and measured, and **not authorized by this document.**

- registry-driven node palette
- five starter nodes: `image.model_loader`, `image.prompt`, `image.sampler`,
  `image.vae_decode`, `image.output` — defined against the **FLUX.1-schnell GGUF loaders
  actually on this disk** (`UnetLoaderGGUF`, `DualCLIPLoaderGGUF`, `VAELoader`), not
  `CheckpointLoaderSimple`; see §3.4
- workflow save/load as SyMoNeuRaL JSON
- validate endpoint, compile endpoint to **private** Comfy API JSON, queue job endpoint
- result gallery reuse, hardware badge display, `/docs` operation links

Do **not** begin with every model type, every backend, every customer-local path, or arbitrary
plugin execution.

**The first increment is smaller than all of that:** give Studio's routers `tags=["Studio"]`
and stable `operation_id`s (§3.3). Until that exists, every `api_href` in the node registry
points at nothing.

---

## 14. Acceptance for the direction-lock commit

Stated here so it can be checked rather than asserted. This document states: Studio is a
ComfyUI-style graph UI owned by SyMoNeuRaL (§1) · raw ComfyUI must not be publicly exposed
(§1, §3.2, §10) · Simple mode and Graph mode both exist (§4) · the SyMoNeuRaL graph is the
canonical save format (§7) · the four compile targets are named (§7) · the four execution
targets are named (§5) · browser-only detection is approximate and real detection needs a
helper/agent (§5.2) · the owner NVIDIA profile is explicit with no CPU fallback unless
authorized (§5.3) · the badges are named (§8) · the node docs/API link contract is defined
(§9, node-system §2) · the planned `/api/studio` routes are named (§9) · `/docs` exposes
Studio operations with stable operation ids (§9) · no implementation beyond spec and task
unless explicitly authorized (header, §11).

## 15. Not in this commit, and not a Studio question

`review/symoneural-studio-upgrade-scope-2026-08-22/audit/INPUTS-INSPECTED.md` records that
`symoneural.zip.part-00/01/02` concatenate to a 77-file, ~84 MB archive that left this box,
containing `claudejsonl/` and a nested `symoneuralmostrecent.zip`.

`ops/docs/EXPORTS.md` rule 1 — written 2026-08-22, from the #75 finding the same day — is
**"No whole-repo zip exports, ever."** Rule 3 excludes session transcripts. Whether
`training/corpus.jsonl` or `training/build_dataset.py` were inside cannot be determined from
here: the archive is not on this box in inspectable form. Recorded so it is not lost; it
belongs to #75, not to #103, and nothing in this commit acts on it.
