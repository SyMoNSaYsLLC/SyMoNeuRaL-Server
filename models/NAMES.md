# Model names — house name, upstream artefact, licence

Task #74 item 3. Every weight file on this box carries a SyMoNeuRaL name. This is the
table that says what each one actually is.

**Why this file exists when `PROVENANCE.json` already does.** The JSON is the machine's
copy — `scripts/fetch-models.sh` reads `upstream_repo`/`upstream_file` to re-fetch a file
it has renamed, and `backend/apps/test_weight_names.py` checks `bytes_on_disk` against the
real file so a truncated download fails a test instead of serving quietly. This file is the
reader's copy, and it is what attribution is rendered from. A rename with no readable
attribution table is the exact failure #74 was opened to prevent: a vendor filename becomes
a log line, then an error message, then a page, and the reverse — a house name with no
recorded origin — is an unfalsifiable claim about what the bytes are.

**The rename is not a licence question, and the attribution is.** Apache-2.0 and MIT both
permit renaming a redistributed artefact. Neither permits dropping the notice. So the file
on disk is ours to name and the row below is not ours to delete. The precedent is already
set in this repo: `built on Qwen2.5-7B-Instruct` is treated as an Apache-2.0 condition, and
every `text-overflow:ellipsis` rule was removed from the CSS because that attribution had
been truncated to `…7B-Ins…` on the rack.

**Nothing here was modified by us.** Every row is `modified_by_us: false` in the manifest —
no entry has been re-quantised, merged, fine-tuned or otherwise altered. The one artefact
that *is* ours is the persona LoRA in `training/adapter/`, which is not in this table
because it is not a redistributed work.

This table is generated-checkable, not generated: `test_weight_names.py` asserts that every
row here matches `PROVENANCE.json`, so the two cannot drift. Edit the JSON, then this file.

## Language models — `backend/models/llm/`

| House name | Upstream repository | Upstream file | Licence | Role |
|---|---|---|---|---|
| `symon-1.0-7b-q4_k_m.gguf` | `bartowski/Qwen2.5-7B-Instruct-GGUF` | `Qwen2.5-7B-Instruct-Q4_K_M.gguf` | Apache-2.0 | chat surface, resident workhorse; the base the SyMoNeuRaL persona LoRA is trained against |
| `symon-1.0-14b-q4_k_m.gguf` | `bartowski/Qwen2.5-14B-Instruct-GGUF` | `Qwen2.5-14B-Instruct-Q4_K_M.gguf` | Apache-2.0 | heavy tier; loaded only when it is the whole job |
| `symon-1.0-draft-0.5b-q4_k_m.gguf` | `bartowski/Qwen2.5-0.5B-Instruct-GGUF` | `Qwen2.5-0.5B-Instruct-Q4_K_M.gguf` | Apache-2.0 | speculative decode draft model for the chat surface |
| `symon-1.0-27b-q2_k_xl.gguf` | `unsloth/Qwen3.6-27B-GGUF` | `Qwen3.6-27B-UD-Q2_K_XL.gguf` | Apache-2.0 | opt-in large chat tier; 12,354 MiB resident at `-ngl 99`, ctx 8192, f16 KV |
| `symon-1.0-27b-vision-f16.gguf` | `unsloth/Qwen3.6-27B-GGUF` | `mmproj-F16.gguf` | Apache-2.0 | vision tower for the 27B tier; text inference works without it |
| `symon-1.0-30b-a3b-q2_k_l.gguf` | `unsloth/Qwen3-30B-A3B-Instruct-2507-GGUF` | `Qwen3-30B-A3B-Instruct-2507-UD-Q2_K_XL.gguf` | Apache-2.0 | **ACTIVE chat model since 2026-09-11.** 30.5B total / 3.3B active MoE; 236.6 tok/s at `-c 33792`, 1,115 MiB headroom, 8/8 on the QA set |
| `symon-1.0-32b-q2_k_xl.gguf` | `unsloth/Qwen3-32B-GGUF` | `Qwen3-32B-UD-Q2_K_XL.gguf` | Apache-2.0 | 32B tier, opt-in; fetched 2026-08-20 and **not yet measured on this card** |

## Image models — `backend/models/image/`

All four are the FLUX.1-schnell release, which is Apache-2.0. They are split across two
upstream repositories because that is where each part was actually fetched from, and
recording the repository we used rather than the one we could have used is the point.

| House name | Upstream repository | Upstream file | Licence | Role |
|---|---|---|---|---|
| `symoneural-image-unet-q4_k.gguf` | `leejet/FLUX.1-schnell-gguf` | `flux1-schnell-q4_k.gguf` | Apache-2.0 | diffusion transformer; 6.41 GiB on card |
| `symoneural-image-t5-q8_0.gguf` | `second-state/FLUX.1-schnell-GGUF` | `t5xxl-Q8_0.gguf` | Apache-2.0 | text encoder; detected by tensor names, not by filename, which is why the rename is safe |
| `symoneural-image-clip.safetensors` | `second-state/FLUX.1-schnell-GGUF` | `clip_l.safetensors` | Apache-2.0 | CLIP-L text encoder |
| `symoneural-image-vae.safetensors` | `second-state/FLUX.1-schnell-GGUF` | `ae.safetensors` | Apache-2.0 | autoencoder |

## Speech — `backend/models/whisper/`

| House name | Upstream repository | Upstream file | Licence | Role |
|---|---|---|---|---|
| `symoneural-listen-base-en.bin` | `ggerganov/whisper.cpp` | `ggml-base.en.bin` | MIT | speech-to-text for the voice and sigils surfaces; passed by path, so safe to rename |

## Three things deliberately **not** renamed

Each of these keeps its upstream name because the name is a lookup key owned by someone
else's code, not a label we chose. Renaming them would not rebrand anything — it would
break something, or hide something.

| Path | Why the name stays |
|---|---|
| `backend/models/rembg/u2net.onnx` | `rembg` resolves a session *by model name* and expects `<name>.onnx` inside `U2NET_HOME`. `symoneural-cutout` is not a name rembg knows, so the rename does not rebrand background removal, it disables it. |
| `backend/models/hf/hub/models--*` | The `huggingface_hub` cache layout. The directory name **is** the index; `from_pretrained` resolves through it. Renaming does not rename a model, it hides one. |
| `backend/models/licenses/*` | Third-party licence texts. A licence file that does not name its licensor is not a licence. This is the one place where a house name would be a false statement rather than a brand. |

## Known gap — three artefacts have no licence text on disk

`symon-1.0-27b-q2_k_xl.gguf`, `symon-1.0-27b-vision-f16.gguf` and
`symon-1.0-32b-q2_k_xl.gguf` are recorded as Apache-2.0 but carry `license_text: null` in
the manifest — there is no corresponding file in `backend/models/licenses/`. The other
eight have one.

This is written down rather than quietly left, because Apache-2.0 §4(a) obliges the licence
text to travel with a redistributed work, and these three tiers are opt-in but real. The fix
is to fetch each upstream `LICENSE` alongside the weights in `scripts/fetch-models.sh` and
fill in `license_text`; it is small and it is not done. Do not close #74 believing this
table is complete — it is accurate about what is on disk, including about what is missing.
