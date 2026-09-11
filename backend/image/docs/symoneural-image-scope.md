# SyMoNeuRaL Image — scope, and the baseline that is actually on this disk

**Scope captured 2026-08-22.** Docs and scope only. **No implementation, no image-to-image built,
no model downloaded, no weight committed, no deploy.**

## 1. What it is

> **SyMoNeuRaL Image is the GPU image-generation surface for this server.**

Classification: **PROD direction**, current prompt-to-image implementation preserved and audited
before migration. Rack row `image`, `bus="gpu"`, `2U`, `/image.html`.

It **shares the same 16 GB consumer GPU** with Chat, Remix, Studio/Reinforce, Sigils and Miner,
and runs through the governor and queue. **That is not a capacity claim for multi-user hosting.**

## 2. The baseline — measured, four files, all present

`backend/models/image/`, read 2026-08-22:

| File | Size |
|---|---|
| `symoneural-image-clip.safetensors` | 246,144,152 B |
| `symoneural-image-t5-q8_0.gguf` | 5,199,794,784 B |
| `symoneural-image-unet-q4_k.gguf` | 6,884,606,880 B |
| `symoneural-image-vae.safetensors` | 335,304,388 B |

**FLUX/Schnell. Four separately-loaded components, not one checkpoint.** That shape is the whole
reason the SDXL assumptions do not transfer.

**REMOVED — do not assume** (`BOX-REALITY-AUDIT.md` §7): SDXL as the current baseline — **none is
installed** · `ComfyUI/models/checkpoints` as a source — the whole `ComfyUI/` tree is **absent** ·
`CheckpointLoaderSimple` / SDXL example graphs as the production shape · **raw public ComfyUI as
the product** · CPU fallback for image work — the code has none.

**SDXL is future/example only**, unless installed later and proven. `PROVENANCE.json` is the only
place the house-name → upstream-artefact mapping exists, and `NAMES.md` is a **licence
obligation** rather than documentation.

## 3. The Schnell rules — preserve all four

1. **`cfg` remains 1.0.**
2. **Negative prompt is inert at cfg 1.0.** Accepted, no effect.
3. **Raising cfg is not a quality improvement for Schnell.** Any copy implying otherwise is wrong.
4. **FLUX guidance is embedded conditioning**, not SDXL-style classifier-free guidance — a
   different mechanism, so it cannot share a control's explanation.

Steps stay Schnell-appropriate; the current Studio source uses **4**.

**A UI field that exists but is inert for this model must be labelled clearly, or hidden or
disabled for this profile.** `symoneural-parameters.md` §2-3 is the general contract, and its point
applies exactly here: a control that is shown, looks active, and is ignored is the defect —
locked, inert and unsupported are the three honest states.

## 4. Requested upgrades — captured, not implemented

**R-152 asks for image-to-image and adjustable parameters.** Both are **AUDIT / requested
upgrade** and neither is built here.

**Text-to-image controls**, when authorized: prompt · seed · size/aspect · steps · guidance/cfg
*only where valid for the profile* · sampler/runtime profile *only where valid* · model selection
**only from registered allowed models**.

**Image-to-image**, when authorized: init-image upload · denoise/strength · seed · size/aspect
handling · optional mask if later scoped · output gallery link · **safety, size and type limits on
the upload** · explicit route tests.

**Model-profile-aware, both ways.** For FLUX/Schnell: cfg shown fixed or explained; negative
prompt not made to look effective; seed exposed because reproducibility matters; size/aspect only
within known safe bounds; steps only with model-specific guardrails; profile shown as the current
baseline. For a future SDXL: its controls may include cfg and negative-prompt behaviour — and
**must not leak into FLUX/Schnell as false knobs.**

## 5. GPU rules

Acquire the lease for an active render and release it when the render ends · **residency is not the
work lock** — a resident model is not actively holding the card unless the governor says so ·
respect queue limits and timeouts · report queue/busy honestly · **no silent CPU fallback** ·
**must not block RavenCalc**, which is CPU-only by design.

## 6. Output and gallery

**Generated images must be reachable immediately from the live site or API — never dependent on a
manual deploy.** If current behaviour serves renders from `/api`, that is preserved and documented.

**This is not hypothetical.** Open task **#86** exists because *a page can ship to `site/` and
never reach the webroot, and nothing goes red*, and a render whose URL 404s until a deploy runs is
the same failure with a shorter fuse. **A render must not be reported as ready unless the output
exists and is served by a route that works without a deploy.**

Output handling must define: generated filename shape · pruning/retention policy · 404 behaviour
for pruned images · **no path traversal** · cache behaviour for immutable outputs · and metadata
recording prompt, seed, model profile, size, steps, runtime and source/init image where
applicable.

**No stale last-known output presented as a fresh render.**

## 7. Image is not Studio

| | |
|---|---|
| **Image** | the simple user-facing generation page. Safe, useful controls. Text-to-image and image-to-image. **No graph editor required** |
| **Studio** | the advanced graph/workflow surface, private Comfy runner allowed, model/runtime/hardware aware, LoRA/Reinforce/Exp integration |

**Do not collapse Image into Studio, and do not make a casual user open Studio to generate or
iterate an image.** **Do not expose raw ComfyUI as Image** — `/studio/editor/*` currently proxies
ComfyUI's own frontend and is AUDIT for exactly that reason (`BOX-REALITY-AUDIT.md` §7).

## 8. Runtime and registry direction

Candidates: the current direct image pipeline · Comfy **private** worker · stable-diffusion.cpp for
GGUF/quantized local image work · Diffusers where applicable · a future optimised NVIDIA path
**only after benchmark proof**. **No claim that any of these is running** — the maturity ladder is
`ops/docs/RUNTIME-PROFILES.md` and the readings are `BOX-REALITY-AUDIT.md` §8.

The model registry owns model id, family, format, local path, provenance/licence, runtime and
target compatibility, min/recommended VRAM, default **and locked** parameters, supported controls
and docs/API hrefs. **Once the registry exists, the page must not hardcode model truth.**

## 9. Page copy direction

Say that Image renders on the shared GPU using the current FLUX/Schnell stack, queues behind other
GPU work, and releases the card when the render is done — and that each control is limited by the
selected model profile. While the controls are not built, say so plainly: parameter controls and
image-to-image are **planned upgrades**, and the current surface remains prompt-to-image until the
scoped implementation lands.

**Avoid, unless proven and scoped:** "SDXL" · "Stable Diffusion checkpoint" · "negative prompt
improves output" · "raise CFG for quality" · "instant generation" · "production capacity" ·
"unlimited images" · "raw ComfyUI".

## 10. Credits direction

Image is one of the expensive surfaces (~9 s of exclusive GPU each; suggested bucket 20/300).
Future credit integration should support charge-per-job, free-tier limits, queue status and later
result delivery. **No pricing claim unless current pricing docs authorize it**, and **no payments
or credits implemented in this scope.**

## 11. Not authorized

No implementation · no image-to-image · no control added or removed · no model download · no weight
committed · no generated image committed except an explicit test fixture · no raw ComfyUI exposure ·
no folder migration · no deploy.
