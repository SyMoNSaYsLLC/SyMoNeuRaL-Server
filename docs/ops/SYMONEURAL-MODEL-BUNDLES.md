# SyMoNeuRaL model bundles — every model-like asset, measured

**Opened 2026-08-22.** Docs and inventory only. **No model downloaded, no active default
changed, no weight deleted or moved, no weight committed.**

## 0. The finding this file was opened for

> **17 of 28 weight files on this box — 78.26 GiB — are absent from
> `backend/models/PROVENANCE.json`.**

The manifest covers 11 files / 48.85 GiB. **61% of the weight bytes here have no recorded
upstream, no licence and no role**, and no document noticed because **no document was
measuring**. `docs/ops/BOX-REALITY-AUDIT.md` §7 had flagged "~57 GB of unreferenced weights" as
AUDIT; this is that finding, measured properly and now re-runnable.

**Re-measure, do not read:**

```bash
python3 tools/modelops_inventory.py            # the table below
python3 tools/modelops_inventory.py --json     # the same, machine-readable
scripts/modelops/symoneural-modelops-stage.sh --inventory    # plus disk
```

Every figure in this file came out of that tool. **If this file and the tool disagree, the tool
is right and this file is stale** — the same rule `PROJECT-TASKS.md` has about the progress page.

## 1. Why a bundle and not a model

**A model here is rarely one file.** The image surface loads **four** separately-loaded
components, which is exactly why the SDXL one-checkpoint assumption does not transfer
(`BOX-REALITY-AUDIT.md` §1.2). The chat surface loads a model **and** a draft model for
speculative decode. So the unit that can be promoted, smoked or rolled back is a **bundle**, and
a registry keyed on single files cannot express "this set works together".

A bundle has: an id · a display name · components (each a real file) · a runtime that can load
them · a status · a smoke path · a rollback.

## 2. Classification vocabulary

| Class | Means |
|---|---|
| `active-default` | the running surface loads this **now**, read from source |
| `candidate` | staged for promotion, **not** in use |
| `rollback` | a known-good previous default, retained deliberately |
| `component` | part of a bundle, not independently promotable |
| `adapter` | training **output** — LoRA. Never a base weight |
| `runtime-dependency` | needed by a runtime rather than by a surface |
| `retired` | deliberately no longer used; not deleted |
| **`unknown-blocked`** | **no provenance recorded. The honest default** |

**`unknown-blocked` is not "probably fine".** `docs/ops/LICENSE-AUDIT.md`'s vocabulary says an
unrecorded licence is a blocker until provenance exists, because you cannot ship what you cannot
describe. `tools/modelops_inventory.py::_classify` returns it for any file the manifest does not
know, and `test_an_unmanifested_weight_is_unknown_blocked` pins that.

## 3. Active defaults — 7 files, read from source not assumed

The tool parses the **loader sites** rather than importing them (`api.py` builds a FastAPI app at
module scope; importing it to learn four filenames would run all of that on a box that might be
broken).

| Role | File | Size | Bundle |
|---|---|---|---|
| `chat` | `llm/symon-1.0-7b-q4_k_m.gguf` | 4.36 GiB | SyMoNeuRaL Chat 7B |
| `chat-draft` | `llm/symon-1.0-draft-0.5b-q4_k_m.gguf` | 0.37 GiB | SyMoNeuRaL Chat 7B |
| `image-unet` | `image/symoneural-image-unet-q4_k.gguf` | 6.41 GiB | SyMoNeuRaL Image FLUX Schnell |
| `image-t5` | `image/symoneural-image-t5-q8_0.gguf` | 4.84 GiB | ″ |
| `image-clip` | `image/symoneural-image-clip.safetensors` | 0.23 GiB | ″ |
| `image-vae` | `image/symoneural-image-vae.safetensors` | 0.31 GiB | ″ |
| `asr` | `whisper/symoneural-listen-base-en.bin` | 0.14 GiB | SyMoNeuRaL Listen Base EN |

**A bug worth recording, because it is the shape of the whole problem.** The first version of
the tool read only `api.py` and reported the listen model as an idle component — while
`backend/apps/voice/asr.py:56` was loading it. **One loader site missed is one active model
misclassified**, so the sites are an explicit list and
`test_the_asr_model_is_found_from_the_voice_app_not_just_api` exists to keep it honest.

## 4. The bundles

### 4.1 SyMoNeuRaL Chat 7B — `symon-chat-7b` — **active default**

| | |
|---|---|
| components | `llm/symon-1.0-7b-q4_k_m.gguf` + `llm/symon-1.0-draft-0.5b-q4_k_m.gguf` (speculative decode) |
| upstream | `bartowski/Qwen2.5-7B-Instruct-GGUF`, `bartowski/Qwen2.5-0.5B-Instruct-GGUF` |
| licence | Apache-2.0, **texts present on disk** |
| runtime | llama.cpp-family engine, `-ngl 99` (`api.py:1163`) |
| set at | `backend/api.py:187`, `:191` |
| adapter | `CHAT_ADAPTER`, reported by `/api/status` (`api.py:2355`) |
| status | **PROD / active** |

### 4.2 SyMoNeuRaL Image FLUX Schnell — `symoneural-image-flux-schnell` — **active default**

Full detail: **`docs/ops/COMFY-FLUX-BUNDLE.md`**. Four components, all present, all
manifested, all Apache-2.0 with texts on disk. **Status: BUILT / AUDIT** — the files and the
loader graph are real; a stamped smoke record for the bundle as a bundle does not yet exist.

### 4.3 SyMoNeuRaL Listen Base EN — `symoneural-listen-base-en` — **active default**

`whisper/symoneural-listen-base-en.bin`, 147,964,211 B, upstream `ggerganov/whisper.cpp`,
**MIT**, licence text on disk, loaded by `voice/asr.py:56`. **Status: BUILT / AUDIT.**

**Not replaced, and not replaceable by an API.** An OpenAI Whisper *API* is not a local
open-weight replacement for a local model; if that is ever wanted it is a separate,
clearly-marked **API/FUTURE** provider, never a swap of this bundle.

### 4.4 SyMoNeuRaL Qwen tiers — `rollback`

`llm/symon-1.0-14b-q4_k_m.gguf` (8.37 GiB) · `llm/symon-1.0-27b-q2_k_xl.gguf` (11.04) ·
`llm/symon-1.0-32b-q2_k_xl.gguf` (11.92). Manifested, Apache-2.0.

**Retained deliberately. No mode of the staging script deletes a weight** — disk is cheaper than
a model you cannot get back.

### 4.5 SyMoNeuRaL Vision Projector — `component`, and licence-blocked

`llm/symon-1.0-27b-vision-f16.gguf`, 927,607,360 B, upstream `unsloth/Qwen3.6-27B-GGUF`.
The vision tower for the 27B tier; **text inference works without it.**

**`license_text: null`** — one of the three ML-1 gaps. **Redistribution blocked** until the
upstream text is on disk. Serving locally is unaffected.

### 4.6 SyMoNeuRaL OpenAI 20B — `symon-openai-20b` — **CANDIDATE, not staged, not downloaded**

See **`docs/ops/OPENAI-GPT-OSS-MIGRATION.md`**. Upstream `openai/gpt-oss-20b`, **Apache-2.0**.
**Nothing has been fetched.** Qwen stays active until a smoke record exists *and* Garrett
approves.

**Runtime gate answered 2026-08-22: NEEDS CONVERSION.** The engine supports the architecture, the
Harmony template and **MXFP4 on CUDA** (`GGML_TYPE_MXFP4 = 39`); upstream ships safetensors only,
and `conversion/gpt_oss.py` converts them with `repack_mxfp4()` — repacking the 4-bit blocks
rather than inflating them. Conversion needs `training/.venv/bin/python3` (torch 2.11.0+cu128);
the smoke does not need torch at all.

**It will not fit at the production context:** 12.81 GiB of weights plus ~3.9 GiB of KV at
`-c 65536 -np 2` is ~16.7 GiB on a 16,303 MiB card. The isolated smoke uses `-c 8192 -np 1`.

### 4.7 Adapters — `training/`, protected, reported separately

`training/adapter/adapter_model.safetensors` (161,533,192 B) ·
`training/adapter-qwen36/adapter_model.safetensors` (200,384,784 B)

**Training output, not base weights**, and the inventory keeps the two lists apart on purpose —
merging them is how an adapter ends up treated as something shippable. Both sit in the
**protected** tree: Coder's and Project's denylists refuse `training/adapter*` **after
`resolve()`**, so a symlink cannot reach them.

**Base-weight mutation stays owner/admin only**, and the four never-operations from
`symoneural-studio-upgrade-scope.md` §1.2 are absent operations rather than restricted ones. **No
training data is exportable.**

## 5. The 17 unknown-blocked files

**Every one is `unknown-blocked`: no upstream, no licence, no role, no runtime, no promotion
status recorded.** Listed largest first, as measured.

| Size | File |
|---|---|
| 19.53 GiB | `diffusion_models/minimax_h3_fl2va_pruned_int8_convrot.safetensors` |
| 14.61 GiB | `text_encoders/qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors` |
| 11.46 GiB | `diffusion_models/z_image_turbo_bf16.safetensors` |
| 8.59 GiB | `checkpoints/stable_audio_3_medium.safetensors` |
| 7.49 GiB | `text_encoders/qwen_3_4b.safetensors` |
| 4.85 GiB | `vae/minimax_h3_video_vae_fp16.safetensors` |
| 4.24 GiB | `text_encoders/qwen3.5_2b_bf16.safetensors` |
| 1.82 GiB | `loras/minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors` |
| 1.57 GiB | `clip_vision/dino_v3_vit_h.safetensors` |
| 1.11 GiB | `text_encoders/t5gemma_b_b_ul2.safetensors` |
| 0.69 GiB | `diffusion_models/triposplat_fp16.safetensors` |
| 0.56 GiB | `vae/minimax_h3_audio_vae_fp32.safetensors` |
| 0.54 GiB | `vae/triposplat_vae_decoder_fp16.safetensors` |
| 0.41 GiB | `background_removal/birefnet.safetensors` |
| 0.31 GiB | `vae/flux2-vae.safetensors` |
| 0.31 GiB | `vae/ae.safetensors` |
| 0.16 GiB | `rembg/u2net.onnx` |

**Three observations that make this list actionable rather than alarming:**

- **`rembg/u2net.onnx` is the cheapest to close.** Its licence texts are **already on disk** —
  `licenses/u2net.LICENSE.txt`, `licenses/rembg.LICENSE.txt`, `licenses/onnxruntime.LICENSE.txt`.
  The licence is known; only the manifest entry is missing. And `PROVENANCE.json` already
  explains why the *filename* must not be renamed: rembg resolves a session by model name.
- **`vae/ae.safetensors` is 335,304,388 B — byte-identical in size to the active
  `image/symoneural-image-vae.safetensors`.** `BOX-REALITY-AUDIT.md` §1.4 already flagged a
  duplicate VAE. Confirm by hash before anything is deleted, and **nothing is deleted here.**
- **The `minimax_h3_*` group (4 files, 26.76 GiB) looks like one bundle**, spanning
  `diffusion_models`, `text_encoders`, `vae` and `loras`. If so it is a single provenance entry's
  worth of work for a quarter of the unknown bytes. **Looks like is not is** — it needs reading,
  which is why it is `unknown-blocked` and not guessed at.

**None of these is deleted, moved, or assumed. They are named.** That is the deliverable.

## 6. Promotion, smoke and rollback

`scripts/modelops/symoneural-modelops-stage.sh`, and the rule it enforces:

> **Nothing is downloaded, activated, moved or deleted without an explicit flag.**

| Mode | Effect |
|---|---|
| `--inventory` · `--dry-run` · `--smoke-plan` | **read-only** |
| `--stage-openai-gpt-oss-20b` | writes a staging dir, manifest and rollback note. **Prints the download command; does not run it** |
| `--smoke-candidate <id>` | runs the candidate **in isolation** — see below. Exit 5 if it cannot |
| `--activate-candidate <id>` | **six gates**, all required |
| `--rollback` | restores the backup; **never deletes a weight** |

**The six activation gates:** candidate staged · **`SMOKE-PASSED.txt` present** · rollback
recorded · licence recorded (not `UNRECORDED`) · runtime compatibility recorded ·
`SYMONEURAL_MODELOPS_APPROVE=<id>`. Any failure exits **3** and says REFUSED — *"a promotion path
that exits 0 when it did not promote is the shape that lets a caller believe it worked."*

**Isolated smoke: the fallback is unreachable, not disabled.** `--smoke-candidate` launches the
engine binary directly against the candidate, on its own port, in its own process, and **never
invokes the production API module** — the only thing that knows the production defaults. *A flag
that disables a fallback can be wrong; a function that cannot name the fallback cannot load it*,
and `test_the_smoke_mode_cannot_NAME_what_it_must_not_load` forbids the production symbols and
filenames from appearing anywhere in that function's body. No adapter, no draft model, own port,
nonzero exit on a missing candidate or engine, and it reports the model path, the engine path and
the engine's own `--version`.

**"Disabled for smoke" means disabled in the test path.** Not deleted, not moved, and the
production default unchanged — asserted against the disk.

**The smoke marker cannot be written honestly without a run.** `exists` and `grep` ask what is
on disk; neither can ask whether a model works — the lesson `.claude/CLAUDE.md` draws from #94,
applied to models.

**Two deliberate non-implementations**, both because a shell script is the wrong place:

- the download, even with the confirm phrase set. Tens of GB onto a disk already holding 194 GB
  should not be one environment variable away.
- the `CHAT_MODEL` rewrite. Promotion edits a source file the API reads at import; **that belongs
  in a reviewed commit with a test.** The gate says whether promotion is *allowed* — not how to
  get it past review.

**Staging is gitignored** by `.gitignore:5` `backend/models/*`, so no weight and no staged
manifest can be committed. Structural, not a promise.

## 7. Registry sections

`docs/ops/MODEL-REGISTRY.md` carries the contract. The sections this inventory populates:
**active local defaults** (§3) · **local candidates** (§4.6) · **rollbacks** (§4.4) ·
**component bundles** (§4.2, §4.5) · **API-only future providers** (none today; §4.3 states the
rule) · **retired/removed** (none) · **unknown-blocked** (§5, seventeen).

## 8. Not authorized by this document

No model downloaded · no active default changed · no weight deleted, moved or renamed · no weight
committed · no licence file renamed · no upstream origin hidden · no OpenAI activation · no
commercial claim · no deploy.

**House names are display. Upstream is recorded exactly.** `PROVENANCE.json`'s own reason
stands: *"a house name with no recorded origin is an unfalsifiable claim about what the bytes
are."*
