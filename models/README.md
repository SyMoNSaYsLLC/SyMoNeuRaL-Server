# models/ — the weights, and everything you do to them

Real files, not symlinks. ~50 GB here and the tree does not carry them: a clone gets this
README, `PROVENANCE.json`, `NAMES.md` and `licenses/`, and fetches the rest.

```
models/
  llm/                the language weights the chat surface loads
  licenses/           the upstream licence text for every weight here
  PROVENANCE.json     which upstream artefact each house name came from. THE record.
  NAMES.md            the same thing, readable. Generated from the manifest, not typed.
```

**Nothing here keeps an upstream filename.** Language weights are `symon-1.0-*`, everything
else is `symoneural-*`. `tests/models/test_weight_names.py` fails if a file appears that is
not in the manifest or not named to the rule. A house name with no recorded origin is an
unfalsifiable claim about what the bytes are.

---

## What is here now

| file | role |
|---|---|
| `symon-1.0-30b-a3b-q2_k_l.gguf` | **the active chat model.** 30.5B total / 3.3B active MoE |
| `symon-1.0-14b-q4_k_m.gguf` | opt-in dense tier |
| `symon-1.0-27b-q2_k_xl.gguf` + `-vision-f16` | opt-in large tier, with its vision tower |
| `symon-1.0-32b-q2_k_xl.gguf` | fetched, **never measured on this card** |
| `symon-1.0-7b-q4_k_m.gguf` | the base the persona LoRA was trained against |
| `symon-1.0-draft-0.5b-q4_k_m.gguf` | speculative-decoding draft. **Not in the live argv** |

Measured on the RTX 5070 Ti (15.92 GiB), 2026-09-11:

```
30B-A3B   236.6 tok/s   -c 33792   1,115 MiB headroom   8/8 on the QA set
gpt-oss-20b 166.2 tok/s -c 66560   1,172 MiB headroom
gpt-oss-120b 15.2 tok/s --cpu-moe  3,257 MiB VRAM
```

The card is **memory-bandwidth bound**: memory clock pinned at 14,001/14,001 MHz (100%) while
power sits at 227/300 W (76%). Time per token is proportional to bytes read per token, so a
power-limit increase cannot help this workload and a smaller quantisation can.

---

## Fetching what is missing

```bash
scripts/fetch-models.sh
```

Safe to re-run. It is **idempotent in both directions**: on a box that already downloaded
upstream names it renames in place (`adopt`), and a rename is not a re-quantisation, so the
bytes are untouched and 40 GB is not re-transferred. On a fresh clone the adopt calls are
no-ops and the house name is simply what lands.

Every source is ungated and commercially licensed. FLUX.1-**schnell** only — FLUX.1-dev is
non-commercial and must never be substituted into anything customer-facing.

---

## Adding a model

Five steps, and the manifest is not optional — a weight with no `PROVENANCE.json` row fails
the suite.

1. **Choose the house name.** `symon-1.0-<size><-variant>-<quant>.gguf` for language,
   `symoneural-<surface>-<part>-<quant>` for everything else.

2. **Fetch it under that name.**
   ```bash
   curl -L -o models/llm/symon-1.0-<name>.gguf \
     https://huggingface.co/<repo>/resolve/main/<upstream-file>
   ```

3. **Record it.** Append to `PROVENANCE.json` — **append, do not sort.** A test reads the
   first two `llm/` entries positionally.
   ```json
   { "path": "llm/symon-1.0-<name>.gguf",
     "role": "what this is for, and what it measured",
     "bytes_on_disk": 0,
     "upstream_repo": "org/Repo-GGUF",
     "upstream_file": "Upstream-Name.gguf",
     "license": "Apache-2.0",
     "license_text": "licenses/Upstream.LICENSE.txt",
     "modified_by_us": false }
   ```
   `bytes_on_disk` is **measured**, never copied from a model card:
   `stat -c %s models/llm/<file>`.

4. **Carry the licence.** Drop the upstream text into `licenses/`. Apache-2.0 §4 obliges
   attribution to travel with a redistributed artefact, and renaming is redistribution.

5. **Add the `NAMES.md` row and prove it.**
   ```bash
   python3 -m pytest tests/models -q      # 29 passed, 1 skipped when correct
   ```

---

## Setting parameters

Two places, and they are different questions.

### Engine parameters — what the card runs

`backend/core/config.py`. These decide whether the model fits.

| constant | now | what it does |
|---|---|---|
| `CHAT_MODEL` | the 30B-A3B | which file is loaded |
| `CHAT_CTX_TOTAL` | `33792` | `-c`: **total** context, divided across slots |
| `CHAT_MODEL_LABEL` | `SymonChat S1-30B-A3B` | the name the rack and the chat page show |
| `SPEC_DRAFT_MAX` | `2` | speculative draft depth, when a draft model applies |

The engine takes more than this file uses. Measured from `--help` on this build:

```
-ngl N          layers on the card. 99 is a ceiling, not a count
-c N            total context. Per slot = N / -np
-np N           slots. Two slots share -c; each gets half
-cb             continuous batching -- slots interleave instead of queueing
-ctk / -ctv T   KV cache quantisation. The cheapest context you can buy
-ncmoe N        keep the first N layers' MoE experts on the CPU
-cmoe           all MoE weights on the CPU. How the 120B ran in 3.3 GiB of VRAM
-fa on|off|auto flash attention
--no-warmup     skip the startup decode
```

**How to pick them.** Not by guessing — overshoot and back off:

```bash
python3 tools/bench/bench_maxfit.py --model models/llm/<file>
```

It raises `-c` until the allocation fails, then steps back to the largest value that fits
with headroom. KV cost scales with **layers × heads**, not with parameter count, which is why
a 24-layer 20B takes a far larger context than a 48-layer 30B on the same card.

Then sweep the rest of the argv against that ceiling:

```bash
python3 tools/bench/bench_config.py --model models/llm/<file>
```

One model, many argvs. It answers *"what is the best this box can do with these weights"*,
which is a different question from *"which model is faster"* — that one is
`tools/bench/bench_models.py`.

### Sampler parameters — what the model writes

Not in this repo. They are per-request, and the engine's live defaults are readable:

```bash
curl -s 127.0.0.1:8081/props | python3 -m json.tool | head -40
```

Thirty values — temperature, top_k, top_p, min_p, repeat_penalty, mirostat, the DRY family.
`POST /api/chat` accepts `temperature` and `max_tokens` and clamps both; out-of-range is
clamped rather than refused, because answering a truncation is worse than refusing one.

---

## Swapping the active model

Never by editing `core/config.py` on a live box. The swap is the highest-consequence change
here and it has a script whose guardrails are refusals rather than comments:

```bash
scripts/model-staging/symoneural-model-stage.sh --dry-run          # say what would happen
scripts/model-staging/symoneural-model-stage.sh --inventory        # what is actually here
scripts/model-staging/symoneural-model-stage.sh --stage-<name>     # prepare, fetch nothing
scripts/model-staging/symoneural-model-stage.sh --smoke-candidate  # run it in isolation
scripts/model-staging/symoneural-model-stage.sh --activate-candidate
scripts/model-staging/symoneural-model-stage.sh --rollback         # the one for a hurry
```

**Nothing is downloaded, activated, moved or deleted without an explicit flag.**
`--inventory`, `--dry-run` and `--smoke-plan` are read-only. `--activate-candidate` refuses on
six separate conditions. `--rollback` restores `core/config.py` from the backup written at
promotion time.

---

## Fine-tuning and LoRA

The training bay is `backend/studio/plugins/reinforce/` and it is a **surface**, not a script:
supervised, preference and reinforcement tuning, driven from `/api/train/*`.

```
GET  /api/train/models      what can be tuned
GET  /api/train/datasets    what it can be tuned on
GET  /api/train/presets     the recipes
POST /api/train/preflight   will this run fit, and on what
POST /api/train/start       start it
GET  /api/train/status      progress
POST /api/train/stop        SIGTERM to the process group
```

### The one thing to understand before starting a run

**A training run holds the whole card until it finishes.** The governor never evicts `train`,
so chat, image and remix queue behind it. That is architectural, not a limitation to engineer
away. `POST /api/train/stop` sends SIGTERM to the **process group** so the governor's release
trap runs and waits for VRAM to drain below the floor — a SIGKILL would return the lease
before the CUDA context finished tearing down, and the next surface would allocate into
memory that is still held.

### Running one

```bash
curl -s 127.0.0.1:8800/api/train/presets  | python3 -m json.tool
curl -s 127.0.0.1:8800/api/train/datasets | python3 -m json.tool

curl -s -X POST 127.0.0.1:8800/api/train/preflight \
  -H 'content-type: application/json' \
  -d '{"model":"symon-1.0-7b-q4_k_m","preset":"qlora-r16","dataset":"persona-v3"}'

curl -s -X POST 127.0.0.1:8800/api/train/start \
  -H 'content-type: application/json' \
  -d '{"model":"symon-1.0-7b-q4_k_m","preset":"qlora-r16","dataset":"persona-v3"}'
```

No token, no header. There are none on this box and there will not be —
`tests/structure/test_no_tokens.py` is the rule as code.

Run **preflight first**. It is the difference between finding out now and finding out forty
minutes in, and `dataset_guard.py` refuses a dataset that would poison the adapter rather
than training on it quietly.

### Where the adapter goes, and why it might not apply

Adapters are training **output** and live outside `models/` on purpose — `CHAT_ADAPTER` in
`core/config.py` points at `training/adapter/symoneural-lora.gguf`.

`adapter_applies()` in `backend/core/engine.py` checks architecture compatibility before
adding `--lora` to the argv, and logs loudly when an adapter is present but not applicable.
**Right now nothing applies**: the adapter was trained against the 7B and the active model is
the 30B-A3B, which is a different architecture. `GET /lora-adapters` on the engine returns
`[]`, measured. Re-tune against the active base, or keep the 7B as the chat model.

### Proving a run happened

Consensus is not training. An in-context lesson is not training. The evidence is:

```
training/adapter/<name>.gguf                 the artefact
the held-out evaluation result beside it     the number
GET /lora-adapters on the engine             not []
```

If those three are not all present, the milestone is not met.

---

## Expert pruning and the Fabric

Measured 2026-09-11, and the result is negative — recorded so nobody spends the week again:

- pruning works mechanically. A 20.9B MoE reduced to 6.58B in 5.73 GiB, unchanged tok/s.
- **the pruned models are broken.** Router healing does not fix it: routing entropy is 93% of
  uniform both before and after, so the router was never the thing that was lost.
- expert **caching** does not rescue an oversized model either: an oracle cache tops out at
  ~60% hit rate at 18.6% residency.

91.4% of a 20B MoE's parameters are expert weights, and the expert index is the
slowest-varying dimension in GGUF, so experts are contiguous byte ranges and are cheap to
address. That part is real. What does not work is dropping them.

See `backend/fabric_core/lib/expertcache.py` and the bench tools `moe_capture.py`,
`moe_prune.py`, `moe_prune_sweep.py`, `moe_sequence.py` under `tools/bench/`.

---

## Licensing

`LICENSES.md` at the repo root is the inventory; `licenses/` here holds the texts. Model
weights are **not** covered by the SyMoNeuRaL licence — each carries its own terms from its
originator, which may restrict commercial use, redistribution, or use of the output. A
`symon-1.0-*` name is a runtime identity, not a claim of authorship: `PROVENANCE.json` records
what every one of them actually is, which is also how "does this CVE affect us" stays
answerable in one lookup.
