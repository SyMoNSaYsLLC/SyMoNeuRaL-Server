# SyMoNeuRaL Model Registry — the contract

**Status: stub. A contract for something not yet built, not a description of current state.**

**The authority on what exists today is `backend/apps/studio/plugins/reinforce/registry.py`.**
That module already implements the registry concept for LLM weights, with its two rules in its
own docstring beside the code that obeys them. This file is the contract a **unified** registry
must meet once it covers image, audio and video families as well. Where the two disagree, the
module is what the machine does and this file is what it should grow into.

Read that module before adding a field here. The other two files in this directory —
`EXPORTS.md` and `MEASUREMENTS.md` — are rules in force; this one is a target.

Consumers: `docs/specs/symoneural-studio-upgrade-scope.md`,
`docs/specs/symoneural-studio-node-system.md`,
`docs/specs/symoneural-runtime-registry.md`, `docs/specs/symoneural-model-hot-swap.md`, and
the planned `GET /api/models`.

**This registry is not the runtime registry.** It answers *what can be served*;
`docs/ops/RUNTIME-PROFILES.md` answers *what can serve it*. The join between them is the
runtime router, and collapsing the two tables is the design error
`symoneural-runtime-registry.md` §1 exists to prevent.

---

## The rule this exists to state

**The registry is the source of truth for models — not random folders on disk.** A model the
registry does not describe is a model Studio cannot offer, however present its files are.

## Record fields

| Field | Notes |
|---|---|
| `model_id` | stable, ours |
| `display_name` | |
| `model_family` | **llm / image / asr / embedding / vision / audio / video** — the coarse family the router keys on |
| `architecture_family` | `flux`, `sdxl`, `llama`, … — the specific lineage a node must match |
| `format` | **gguf / safetensors / diffusers / onnx / bin** |
| `task` | image, chat, audio, video, embedding, … |
| `source` | Hugging Face, NGC, local internal, … |
| `source_url` | |
| `license` | **gates what Studio may expose or run** |
| `weights_location` | an **internal reference, never a public raw path** |
| `quantization` | |
| `precision` | |
| `min_vram_gb` | derived, never typed in |
| `recommended_vram_gb` | derived, never typed in |
| `supported_runtimes` | `runtime_id`s from `docs/ops/RUNTIME-PROFILES.md` — not families, so a model cannot claim a runtime that is `absent` |
| `supported_targets` | `cloud` \| `local_customer` \| `local_owner_nvidia` \| `auto` |
| `local_path_or_source` | a local path **or** a managed source — never a public raw path |
| `load_policy` | **`resident` / `on_demand` / `disabled`** |
| `eviction_priority` | lower is evicted first. `train` is never evicted — `docs/ENGINEERING.md` |
| `download_state` | present / absent / partial — and **absent is a state, not an error** |
| `measured_or_vendor` | `measured` \| `vendor` \| `projected` |
| `allowed_for_public_cloud` | |
| `allowed_for_local_customer` | |
| `allowed_for_owner_gpu` | |
| `docs_href` | the model's own docs page |
| `api_href` | the matching `/docs` operation |
| `model_registry_href` | the canonical registry entry, for a node to link to |

## Rules

- **Scan, never hardcode.** A hardcoded model table goes stale the first time a directory
  changes. Every row is produced by reading the file — `config.json` for HF format, the GGUF
  key/value header for llama.cpp format. If the file is not there, the row is not there.
- **Derive, never look up.** VRAM figures are computed from the architecture numbers just
  read, so a model nobody anticipated still gets an honest estimate.
- **Label vendor specs separately from measured readings.** Three values only: measured on this
  machine, vendor specification, projected arithmetic. Never present a projection as a result.
- **Do not enumerate protected datasets or adapters into public dropdowns.**
  `docs/ops/EXPORTS.md` names them; a model picker that helpfully scans sibling directories is
  how they get published.
- **Do not commit model weights.** The registry describes weights already on disk; it does not
  fetch them, move them, or put them in git.
- **Do not scan arbitrary sibling folders as registry truth.** Scanning is how rows are built
  from *known* roots, not a licence to walk the filesystem.
- **The license field is load-bearing.** It decides whether a model may be served at all, and
  to which target.

## Current image baseline on this box

Measured 2026-08-22 at `35704e74`. `backend/models/image/`:

```
symoneural-image-unet-q4_k.gguf      quantised UNet
symoneural-image-t5-q8_0.gguf        T5-XXL text encoder
symoneural-image-clip.safetensors    CLIP-L text encoder
symoneural-image-vae.safetensors     autoencoder
```

Family: FLUX.1-schnell-style. **`ComfyUI/models/checkpoints/` is absent and no SDXL checkpoint
is present.** SDXL appears in these documents only as a `FUTURE` / `EXAMPLE` family.

Family-specific behaviour for flux is fixed by `backend/apps/studio/workflows.py:31-35, 71` and
any registry row claiming this family inherits it: `cfg` is 1.0, the negative prompt is inert
at cfg 1.0, raising cfg degrades rather than sharpens, and guidance is embedded conditioning
rather than classifier-free.

## LLM and ASR inventory on this box

Measured 2026-08-22 at `41524770`; evidence in `docs/ops/BOX-REALITY-AUDIT.md` §8.

**LLM — PROD inventory.** `backend/models/llm/`, six GGUF files, 39.64 GB:
`symon-1.0-32b-q2_k_xl`, `-27b-q2_k_xl`, `-27b-vision-f16`, `-14b-q4_k_m`, `-7b-q4_k_m`,
`-draft-0.5b-q4_k_m`. llama.cpp (`symoneural-llm`) is **built** and is the likely
local/owner/customer runtime for them. **vLLM is a cloud candidate only — no service is
running and this file does not claim one.**

**ASR — inventory present, runtime absent.** `backend/models/whisper/symoneural-listen-base-en.bin`
(148 MB) is real. `whisper.cpp` is **absent**: `contrib/` does not exist and there is no
`whisper-cli` on this box. So the weights are current inventory and there is **no production
ASR route to claim** — `apps/voice` already reports `offline` and names the missing path.

---

## Registry sections — added 2026-08-22, and the inventory that populates them

**The registry is not a list any more; it is a reading.** `tools/lib/modelops_inventory.py` scans the
disk, joins it to `PROVENANCE.json`, and joins that to the paths the running surfaces actually
load. **Re-run it rather than trusting the numbers below** — that is the standing rule and this
file is subject to it.

| # | Section | Populated by |
|---|---|---|
| 1 | **active local defaults** | 7 files, parsed from `api.py` and `voice/asr.py` |
| 2 | **local candidates** | `symon-openai-20b` — not downloaded, not active |
| 3 | **rollbacks** | the Qwen 14B/27B/32B tiers, retained deliberately |
| 4 | **component bundles** | FLUX/Schnell (4 files), Listen Base EN, the vision projector |
| 5 | **API-only future providers** | none today. An API is never a swap for a local model |
| 6 | **retired/removed** | none. **No mode of the staging script deletes a weight** |
| 7 | **unknown-blocked** | **17 files, 78.26 GiB** — no upstream, no licence, no role |

**Section 7 is the finding.** `PROVENANCE.json` covers 11 of 28 weight files; the other 17 are
61% of the weight bytes on this box and had no record anywhere. Full list and the three
observations that make it actionable: `docs/ops/SYMONEURAL-MODEL-BUNDLES.md` §5.

**Bundles, not files, are what get promoted.** The image surface loads four components and the
chat surface loads two; a registry keyed on single files cannot express *"this set works
together"*. See `SYMONEURAL-MODEL-BUNDLES.md` §1.
