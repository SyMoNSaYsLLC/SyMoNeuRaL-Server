# Model storage — measured 2026-09-09

The spec's model section requires that `backend/models/` hold *"only canonical SyMoNeuRaL
house-named runnable local artifacts and required local metadata/state"*, that Drive hold
the *"public/original upstream distributions"*, and that no local original be removed
without `REMOTE_VERIFIED`, `LOCAL_SYMONEURAL_RUNTIME_ARTIFACT_VERIFIED` and
`PROVENANCE_RECORDED`.

## Measured outcome: the local requirement is already satisfied

`backend/models/` is 49G, and **every weight file in it is already house-named**:

| Path | Size | Role |
|---|---:|---|
| `llm/symon-1.0-32b-q2_k_xl.gguf` | 11.92 GB | language |
| `llm/symon-1.0-27b-q2_k_xl.gguf` | 11.04 GB | language |
| `llm/symon-1.0-14b-q4_k_m.gguf` | 8.37 GB | language |
| `llm/symon-1.0-7b-q4_k_m.gguf` | 4.36 GB | language |
| `llm/symon-1.0-27b-vision-f16.gguf` | 0.86 GB | vision projector |
| `llm/symon-1.0-draft-0.5b-q4_k_m.gguf` | 0.37 GB | speculative draft |
| `image/symoneural-image-unet-q4_k.gguf` | 6.41 GB | diffusion |
| `image/symoneural-image-t5-q8_0.gguf` | 4.84 GB | text encoder |
| `image/symoneural-image-vae.safetensors` | 0.31 GB | VAE |
| `image/symoneural-image-clip.safetensors` | 0.23 GB | CLIP |
| `whisper/symoneural-listen-base-en.bin` | 0.14 GB | speech |

**There is no original public model on local disk to remove.** `rebrand/` and `staging/`,
where upstream originals were staged during renaming, are both empty (0 files) — those
originals already went to Drive, and `/yocto/sendtodrive/models` (6.1G) has since been
filed under `Models/Historical/sendtodrive-models-20260820`. So the three removal gates
have nothing to gate: the question they guard does not arise.

Two files initially looked like upstream-named weights:

```
backend/models/hf/hub/models--Qwen--Qwen2.5-7B-Instruct/.no_exist/…/model.safetensors
backend/models/hf/hub/models--Qwen--Qwen3.6-27B/.no_exist/…/model.safetensors
```

Both are **0 bytes**. `.no_exist` is HuggingFace's *negative* cache: a zero-byte marker
recording that a file does **not** exist upstream so the client stops re-requesting it.
They are cache bookkeeping, not weights. Judging them by their path would have produced a
finding about two models that were never there.

## These 49G stay, and the spec is why

The model section ends *"Runtime must work with Drive unavailable."* These eleven files are
the runtime artefacts — not copies of it. Offloading them would move the running server's
weights to a network share, which is the opposite of what that line requires. `49G` is the
correct measured value for `LOCAL_RUNTIME_MODEL_BYTES`, not a cleanup failure.

## Reacquisition is complete for all eleven

`backend/models/PROVENANCE.json` records 11 weights, and:

```
with upstream_repo + upstream_file : 11 of 11
with sha256 recorded               :  9 of 11
modified_by_us = true              :  0 of 11
```

So every artefact can be re-fetched and renamed by `scripts/fetch-models.sh`, which reads
those two fields precisely so a restore does not need the bytes carried. Nothing on this
box has been re-quantised, merged or fine-tuned, which is what `modified_by_us: 0` states.

Two weights have no recorded `sha256`. That is a gap in verification strength, not in
reacquisition: the upstream identity is present, so the file can be fetched, but a returned
file cannot be hash-checked against a local record. Recorded here rather than quietly left.

## Verified, not asserted

`backend/apps/test_weight_names.py` passes 24/24. It checks `bytes_on_disk` in
`PROVENANCE.json` against the real file, so a truncated download fails a test instead of
serving quietly, and it asserts every row of `NAMES.md` matches the JSON so the reader's
attribution table cannot drift from the machine's.

## What renaming does and does not license

`NAMES.md` states the position already settled in this repository, and it is correct:
Apache-2.0 and MIT both permit renaming a redistributed artefact; neither permits dropping
the notice. So the file on disk is the project's to name and the attribution row is not the
project's to delete. A house name with no recorded origin is an unfalsifiable claim about
what the bytes are — which is why `PROVENANCE.json` and `NAMES.md` are load-bearing rather
than decorative.

The one artefact that *is* first-party is the persona LoRA under `training/adapter/`, which
is deliberately absent from that table because it is not a redistributed work.
