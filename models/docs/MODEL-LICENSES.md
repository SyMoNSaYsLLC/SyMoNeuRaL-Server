# Model licences — the eleven weights, and the three that cannot be redistributed yet

**Opened 2026-08-22.** Docs only. **No model downloaded, no weight committed, no licence text
fetched by this document.**

**Classification: PROD direction — required before commercial distribution. AUDIT until the gaps
in §2 are closed.**

## 0. This reads `PROVENANCE.json`; it does not replace it

`backend/models/PROVENANCE.json` is the **authority** for what each house-named weight came from,
and it is tracked deliberately — `.gitignore` re-includes it through the `backend/models/*`
exclusion because *"the weights are fetched, so if the manifest is not in git it is not
anywhere."*

Its `bytes_on_disk` is **measured, not copied from a model card**, and
`backend/apps/test_weight_names.py` checks it against the real file whenever the file is present,
*"so a truncated or substituted download fails a test instead of serving quietly."* That is the
standard the rest of this file is held to.

**What this file adds** is the set of questions a licence *name* does not answer:
redistribution · commercial use · modification · output restrictions · gated access.

## 1. The eleven weights, read from the manifest 2026-08-22

| House name | Upstream | Licence | Licence text on disk |
|---|---|---|---|
| `llm/symon-1.0-7b-q4_k_m.gguf` | `bartowski/Qwen2.5-7B-Instruct-GGUF` | Apache-2.0 | ✅ |
| `llm/symon-1.0-14b-q4_k_m.gguf` | `bartowski/Qwen2.5-14B-Instruct-GGUF` | Apache-2.0 | ✅ |
| `llm/symon-1.0-draft-0.5b-q4_k_m.gguf` | `bartowski/Qwen2.5-0.5B-Instruct-GGUF` | Apache-2.0 | ✅ |
| **`llm/symon-1.0-27b-q2_k_xl.gguf`** | `unsloth/Qwen3.6-27B-GGUF` | Apache-2.0 | ❌ **null** |
| **`llm/symon-1.0-27b-vision-f16.gguf`** | `unsloth/Qwen3.6-27B-GGUF` | Apache-2.0 | ❌ **null** |
| **`llm/symon-1.0-32b-q2_k_xl.gguf`** | `unsloth/Qwen3-32B-GGUF` | Apache-2.0 | ❌ **null** |
| `image/symoneural-image-unet-q4_k.gguf` | `leejet/FLUX.1-schnell-gguf` | Apache-2.0 | ✅ |
| `image/symoneural-image-t5-q8_0.gguf` | `second-state/FLUX.1-schnell-GGUF` | Apache-2.0 | ✅ |
| `image/symoneural-image-clip.safetensors` | `second-state/FLUX.1-schnell-GGUF` | Apache-2.0 | ✅ |
| `image/symoneural-image-vae.safetensors` | `second-state/FLUX.1-schnell-GGUF` | Apache-2.0 | ✅ |
| `whisper/symoneural-listen-base-en.bin` | `ggerganov/whisper.cpp` | MIT | ✅ |

**`modified_by_us: false` on every entry.** The manifest states the principle: *"Renaming the file
is not modifying the weights — no entry here has been re-quantised, merged or otherwise altered by
us."* That matters for Apache-2.0 §4, which treats modification differently from redistribution.

`backend/models/licenses/` holds nine texts: the three Qwen2.5 licences, `whisper.cpp`,
`openai-whisper`, `onnxruntime`, `rembg`, `u2net`, and `FLUX.1-schnell.MODEL-CARD.md`.

## 2. Finding ML-1 — three weights claim Apache-2.0 with no licence text on disk

**`license_text: null` for all three unsloth/Qwen3.x entries**, while all eight others point at a
file in `backend/models/licenses/`.

**Why this is a real gap and not bookkeeping.** `PROVENANCE.json`'s own note gives the reason the
manifest exists at all, and the second of its three reasons is exactly this: *"Apache-2.0 section 4
obliges us to keep attribution travelling with a redistributed artefact."* A licence *name* in a
JSON field is not the notice; the **text** is. And `NAMES.md` is tracked precisely because
*"untracking it is the one way to lose the notice without deleting it."*

**Consequence, stated narrowly:**

- **Serving them from this box today is not the problem.** Nothing in `LICENSES.md` §2 turns on
  local inference.
- **Redistributing them is blocked** — in a customer build, an appliance image, or any export —
  until the upstream licence text is on disk and referenced. Status:
  **`notice-required`, currently unsatisfied → `redistribution-restricted` in practice.**

**The fix is small and is not done here:** fetch each upstream `LICENSE`, store it under
`backend/models/licenses/`, and set `license_text` in the manifest. That is a change to tracked
files and to a fetch script, which this docs-only scope does not authorize.

**Note the asymmetry worth checking before trusting the Apache-2.0 label on those three.** The
other eight name a licence *and* carry its text; these three name a licence and carry nothing. The
label is plausible — Qwen3 releases are Apache-2.0 — but **plausible is the word this repo treats
as a warning.** Confirm from upstream when the text is fetched, and if it turns out otherwise, the
status is `unknown-blocked` and the entry is wrong today.

## 2a. ML-3 — the manifest covers 11 of 28 weight files

**Measured 2026-08-22 by `tools/lib/modelops_inventory.py`, which did not exist when §1 was
written.** §1's eleven rows are complete *as a reading of the manifest*. They are not a reading
of the disk.

| | files | bytes |
|---|---|---|
| in `PROVENANCE.json` | 11 | 48.85 GiB |
| **not in the manifest** | **17** | **78.26 GiB** |
| manifest entries with no file | 0 | — |

**All 17 are `unknown-blocked`:** no upstream repo, no licence, no licence text, no role, no
runtime, no promotion status. That is 61% of the weight bytes on this box, and the reason nobody
had noticed is that no document was measuring — `BOX-REALITY-AUDIT.md` §7 had it as "~57 GB of
unreferenced weights" and no one had counted.

The full list is `models/docs/SYMONEURAL-MODEL-BUNDLES.md` §5. **The cheapest one to close is
`rembg/u2net.onnx`** — its licence texts are *already on disk* (`licenses/u2net.LICENSE.txt`,
`rembg.LICENSE.txt`, `onnxruntime.LICENSE.txt`); only the manifest entry is missing. The
**largest single win** is the `minimax_h3_*` group: four files, 26.76 GiB, which *look* like one
bundle spanning `diffusion_models`, `text_encoders`, `vae` and `loras` — and looks-like is why
they are `unknown-blocked` rather than guessed.

**Nothing is deleted, moved or renamed on the strength of this finding.** They are named.

## 3. Required per-model fields — what is present and what is not

| Field | State |
|---|---|
| model id / house name | ✅ `path` |
| source | ✅ `upstream_repo` + `upstream_file` |
| licence | ✅ `license` |
| provenance | ✅ the manifest itself |
| local path | ✅ |
| **modification allowed?** | partial — `modified_by_us: false` records *whether we did*, not *whether we may* |
| **redistribution allowed?** | ❌ **not recorded** |
| **commercial use allowed?** | ❌ **not recorded** |
| **output restrictions?** | ❌ **not recorded** |
| attribution required? | ❌ not as a field; implied by `license_text` |
| gated access? | ❌ not recorded |

**That is finding ML-2:** the manifest answers *where a weight came from*, which is what it was
built for, and **does not answer whether we may ship it or sell output from it.** Those four
missing fields are the ones a commercial mode needs, and they are the difference between provenance
and entitlement.

**Apache-2.0 and MIT both permit commercial use and redistribution with notice**, so the expected
answers are favourable for all eleven — **but expected is not recorded**, and
`ops/backend/authority/docs/symoneural-commercial-mode.md` must not read them off an assumption. **A model with an
unrecorded answer is `unknown-blocked` for commercial mode.**

## 4. Three things deliberately not renamed — and one is a licence rule

From the manifest, preserved here because a migration would "tidy" them:

- **`backend/models/rembg/u2net.onnx`** — rembg resolves a session by model name and expects
  `<name>.onnx` inside `U2NET_HOME`. A rename *"does not rebrand anything, it just breaks
  background removal."*
- **`backend/models/hf/hub/models--*`** — the huggingface_hub cache layout. *"The directory name IS
  the index."* Renaming *"does not rename a model, it hides one."*
- **`backend/models/licenses/*`** — **third-party licence texts.** *"A licence file that does not
  name its licensor is not a licence. This is the one place where a house name would be a false
  statement rather than a brand."*

The third is a licence rule wearing a naming rule's clothes, and it is the one to defend hardest.

## 5. What promotes this to complete

| To claim | Proof |
|---|---|
| every model has a licence status | eleven rows, none `unknown-blocked` |
| notices are satisfiable | **`license_text` non-null for all eleven** — three to go |
| redistribution is permitted | the four missing fields in §3 recorded per model |
| the manifest is trustworthy | `test_weight_names.py` green, byte counts matching disk |
| commercial mode may read this | §3 complete **and** `SECURITY-AUDIT.md` BLOCKER/HIGH closed |

## 6. Not authorized

No model downloaded · no licence text fetched · no weight committed · no manifest field added · no
rename of any of the three in §4 · no export or distribution · no deploy.

Related: `ops/audits/LICENSE-AUDIT.md` · `LICENSES.md` §2 · `ops/registry/EXPORTS.md` ·
`models/docs/MODEL-REGISTRY.md` · `backend/models/NAMES.md`.
