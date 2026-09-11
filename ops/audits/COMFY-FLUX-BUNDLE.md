# SyMoNeuRaL Image FLUX Schnell — the bundle, measured

**Opened 2026-08-22.** Docs and inventory only. **No model downloaded, no component changed, no
workflow edited, no ComfyUI exposure changed, no deploy.**

`symoneural-image-flux-schnell` · **BUILT / AUDIT** · the active image default.

## 0. The correction this file leads with

**OpenAI does not replace this.** `openai/gpt-oss-20b` is an **LLM** candidate
(`models/docs/OPENAI-GPT-OSS-MIGRATION.md`); there is no local open-weight OpenAI image model in
this repo's scope. **The image stack is kept and formalised, not migrated.** Any claim that an
OpenAI weight replaces FLUX here would be false.

## 1. The four components — all present, all manifested

Measured 2026-08-22. Loaded from `backend/server.py:202-205`, named in
`backend/apps/studio/workflows.py:48-51`. Both lists are **identical**, which is the property
worth having and the one a migration would break first.

| Role | File | Bytes | Upstream | Licence |
|---|---|---|---|---|
| UNet / diffusion | `image/symoneural-image-unet-q4_k.gguf` | 6,884,606,880 | `leejet/FLUX.1-schnell-gguf` | Apache-2.0 ✅ |
| T5 text encoder | `image/symoneural-image-t5-q8_0.gguf` | 5,199,794,784 | `second-state/FLUX.1-schnell-GGUF` | Apache-2.0 ✅ |
| CLIP text encoder | `image/symoneural-image-clip.safetensors` | 246,144,152 | `second-state/FLUX.1-schnell-GGUF` | Apache-2.0 ✅ |
| VAE | `image/symoneural-image-vae.safetensors` | 335,304,388 | `second-state/FLUX.1-schnell-GGUF` | Apache-2.0 ✅ |

**12.67 GiB total. `modified_by_us: false` on all four** — renaming a file is not modifying the
weights, which matters for Apache-2.0 §4. Licence texts and the FLUX model card are on disk
(`models/licenses/FLUX.1-schnell.MODEL-CARD.md`).

**Four separately-loaded components, not one checkpoint.** That is the whole reason the SDXL
`CheckpointLoaderSimple` shape does not transfer — `workflows.py:26` puts it bluntly: that graph
*"has nothing to load here."*

## 2. The graph, and the one loader that had to be found by running it

From `workflows.py`:

| Node | Class | Note |
|---|---|---|
| 1 | `UnetLoaderGGUF` | the diffusion model |
| 2 | **`DualCLIPLoaderSDCPP`** | **not `DualCLIPLoaderGGUF`** |
| 3 | `VAELoader` | |
| 4, 6 | `CLIPTextEncode` | positive; negative **inert** |
| 5 | `FluxGuidance` | embedded conditioning |
| 7 | `EmptySD3LatentImage` | |
| 8 | `KSampler` | `steps: 4`, `cfg: 1.0`, `euler`/`simple`, `denoise: 1.0` |
| 9 | `VAEDecode` | |

**Node 2 is the load-bearing detail.** `workflows.py:59` records that it was *"found by running
a render, not by"* reading a doc: the local `symoneural-image-t5-q8_0.gguf` is a
**stable-diffusion.cpp** file — no `general.architecture` — so upstream's GGUF loader rejects it
outright and `DualCLIPLoaderSDCPP` is the one that works.

**This is the reason the custom node exists.** `.gitignore` records that `symoneural_gguf`'s
`DualCLIPLoaderSDCPP` is *"the one thing in that tree that is OURS"*, its source of truth lives at
`backend/apps/studio/custom_nodes/symoneural_gguf/`, and a start script links it into place. **A
migration that drops it silently makes the bundle unloadable while every file is still present.**

## 3. The Schnell rules — preserved verbatim, and they are in the source

`workflows.py:31-35`, not paraphrased:

- **`cfg` is 1.0.** *"Schnell is guidance-distilled; classifier-free guidance is baked in.
  Raising cfg does not sharpen the image, it destroys it."*
- **`steps` is 4.** *"That is the point of schnell. 20 steps costs five times as long for no"*
  gain.
- **The negative prompt is inert.** *"With cfg 1.0 there is no unconditional branch to steer"* —
  it is required by `KSampler` and does nothing.
- **FLUX guidance is embedded conditioning** (node 5), **not** SDXL-style classifier-free
  guidance. Different mechanism; they cannot share a control's explanation.

**Consequence for any UI.** `backend/fabric_core/docs/symoneural-parameters.md` §3 is the contract: a control
that is shown, looks active and is ignored is the defect. Negative prompt and cfg are **locked or
inert here**, and must be labelled, disabled or hidden — never presented as a way to improve
output.

## 4. Private runner, public surface

| | |
|---|---|
| **ComfyUI** | `127.0.0.1:8188` (`comfy.py:75-76`). A **private backend runner** |
| **SyMoNeuRaL Studio** | the public control plane and UI |

**Raw public ComfyUI is not the product.** `BOX-REALITY-AUDIT.md` §7 lists it as REMOVED *as the
thing customers get*, and the `/studio/editor/*` proxy is a separate open finding — **HIGH-1** in
`ops/audits/SECURITY-AUDIT.md`, not closed. #103's ordering stands: the raw editor goes before #88
opens anything.

**Renders started inside the editor are intercepted for the GPU lease.** Every
`POST /studio/editor/api/prompt` routes through `_KEEPER`, because a render begun in the embedded
editor would otherwise take 7 GB of a 15.9 GiB card while `chat` or `train` sat blocked on
`acquire`. **That is a lease protection, not an access control** — the distinction BLOCKER-1
turns on.

## 5. Status, and what would change it

**BUILT / AUDIT.** All four files present and manifested, the loader graph is real and its one
surprising node is explained. What is missing for **PROD** is a **bundle-level stamped smoke
record**: `backend/apps/studio/SMOKE-*.md` files exist for other Studio work, and there is no
equivalent asserting *these four files, this graph, one real render, on this card*.

| To claim | Proof required |
|---|---|
| the bundle loads | a render through the real graph, not a file check |
| it is reproducible | same seed, same output, recorded |
| the custom node is in place | the render succeeding **is** that proof |
| VRAM fits beside chat | measured, not projected. `api.py` already states chat+image weights do **not** both fit in 15.92 GiB |
| PROD | all of the above, stamped |

**Smoke path:** `scripts/modelops/symoneural-modelops-stage.sh --smoke-plan`. The marker cannot
be written honestly without running the thing — which is its whole job.

## 6. Rollback

**There is nothing to roll back to, and that is the finding.** These four files *are* the image
default; no previous image bundle is retained. So:

- **no mode of the staging script deletes a weight** — if these go, the surface has no fallback;
- `vae/ae.safetensors` is **335,304,388 B — identical in size to the active VAE**, and
  `BOX-REALITY-AUDIT.md` §1.4 already flagged a duplicate. It is `unknown-blocked` (unmanifested).
  **Confirm by hash before treating it as either a spare or a duplicate.** Nothing is deleted here.

## 7. Not authorized

No image model downloaded · no component replaced, renamed or moved · no workflow edited · no
`cfg`/`steps` change · no ComfyUI exposure change · no raw public ComfyUI · no SDXL claim · no
deploy.

Related: `models/docs/SYMONEURAL-MODEL-BUNDLES.md` · `backend/image/docs/symoneural-image-scope.md` ·
`backend/fabric_core/docs/symoneural-parameters.md` · `ops/audits/SECURITY-AUDIT.md` HIGH-1.
