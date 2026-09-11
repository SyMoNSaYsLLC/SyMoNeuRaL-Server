# models/llm/ — the language weights

GGUF files, ~50 GB, **not in git**. A clone gets nothing here; `scripts/fetch-models.sh`
fills it.

| file | role |
|---|---|
| `symon-1.0-30b-a3b-q2_k_l.gguf` | **the active chat model.** 30.5B total / 3.3B active MoE |
| `symon-1.0-14b-q4_k_m.gguf` | opt-in dense tier |
| `symon-1.0-27b-q2_k_xl.gguf` + `-vision-f16` | opt-in large tier, with its vision tower |
| `symon-1.0-32b-q2_k_xl.gguf` | fetched, **never measured on this card** |
| `symon-1.0-7b-q4_k_m.gguf` | the base the persona LoRA was trained against |
| `symon-1.0-draft-0.5b-q4_k_m.gguf` | speculative draft. **Not in the live argv today** |

Measured on the RTX 5070 Ti (15.92 GiB), 2026-09-11: the active model runs at 236.6 tok/s
with `-c 33792` and 1,115 MiB of headroom, 8/8 on the QA set.

## Every file here is house-named

Nothing keeps its upstream filename. `models/PROVENANCE.json` is the only record of which
upstream artefact each one is, and `tests/models/test_weight_names.py` fails if a file
appears that is not in it.

**Never rename a file here by hand.** `scripts/fetch-models.sh` has an `adopt` mode that
renames in place — a rename is not a re-quantisation, so the bytes are untouched and 40 GB
is not re-transferred.

## Two things measured and worth knowing

The adapter at `training/adapter/` was trained against the **7B** and does not apply to the
active model: different architecture, and `GET /lora-adapters` on the engine returns `[]`.

Expert pruning of an MoE works mechanically and produces **broken models**. Router healing
does not fix it — routing entropy is 93% of uniform before and after. See `models/README.md`
before spending a week on it.
