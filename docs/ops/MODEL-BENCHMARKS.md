# SyMoNeuRaL model benchmarks — the ledger, and what each figure was read on

**Opened 2026-08-23.** Every figure below carries **the SHA it was read on**. A figure without a
SHA cannot be checked, and this project has published one that was never true of the commit it
sat beside.

> **This file owns the ledger: which benchmarks exist, what each measured, the SHA it was read
> on, and — the part that matters most — what has NOT been measured.**
> `docs/ops/OPENAI-GPT-OSS-MIGRATION.md` §3 keeps the **narrative** of the gpt-oss run: why each
> probe was chosen and which of the author's predictions it disproved. The figures are
> transcribed here rather than paraphrased, and
> **`backend/apps/test_control_plane_matrix.py` asserts the two files still agree** — so
> duplication is enforced rather than trusted.

## 0. The rules this ledger applies to itself

1. **Every figure names its SHA.** No exceptions, including figures I like.
2. **`—` means not measured.** It never means "probably fine".
3. **A benchmark measures what the harness measured** — usually throughput, tokens and VRAM.
   Throughput is not quality, and this file never lets one stand in for the other.
4. **Anti-cheat scoring is the Referee's** (`docs/specs/symoneural-bootcamp.md` §3). A figure the
   Referee scored `fallback_trap` FAIL may not appear as a benchmark at any value: **provenance is
   checked before content**, because a reply from the wrong engine invalidates whatever else it
   shows.

## 1. LLM benchmark — base vs base, `96366d93`

Same prompt, same context, isolated port (8099), **no adapter, no draft**, same idle card
(RTX 5070 Ti, 16,303 MiB, **239 MiB idle**).

| | **SyMoNeuRaL OpenAI 20B** (candidate) | **Qwen 7B** (starter) |
|---|---|---|
| load | 4.03 s | **2.02 s** |
| peak VRAM | 12,911 MiB | **5,259 MiB** |
| prompt | 571.8 tok/s | **1,807.1 tok/s** |
| **generation** | **166.3 tok/s** | 147.6 tok/s |
| tokens for a one-sentence answer | **259** | **25** |
| wall clock | 1.72 s | **0.21 s** |

**SHA `96366d93` · 2026-08-22 · runtime `symoneural-llm` (llama.cpp fork, build 296, commit `2246ab7`).**

**Read the token column before the tok/s column.** A **13% generation-rate win** alongside a
**10× token cost** is not a throughput win. The Harmony reasoning channel is charged whether or
not anyone reads it, and **1.72 s vs 0.21 s wall clock** is what a person would actually feel.

**`base vs base` is the only honest label.** The production Qwen path runs *with* the persona
adapter, which this benchmark deliberately excluded — so this table does not describe the
shipping surface, and must not be quoted as though it did.

### The knowledge probe in this run is a negative control, and it PASSED twice

Asked *"What is SyMoNeuRaL?"*, gpt-oss answered *"a hybrid neural-symbolic architecture"* and
Qwen *"a symbolic model neural network library"*. **Both wrong, and both a PASS.**

This was first reported as a *caveat on the benchmark* — the right data with the wrong sign. Under
Bootcamp §3 scoring, a `negative_control` passes on a **generic or absent** answer: the probe was
only ever asking whether an isolated path leaks project-private context. It did not. **A model
naming this box's card or ports would have been the alarm.**

## 2. Production-argv probes — `96366d93`

Not a throughput measurement. This is the **"does the surface start"** measurement, which is the
one the six file-based activation gates cannot ask.

| Probe | Argv | Result |
|---|---|---|
| **A** | full production argv | **exit 1** — `llama_adapter_lora_init: failed to apply lora adapter: model arch and LoRA arch mismatch` |
| **B** | minus `--lora`, draft kept | **STARTED**, generated, peak **14,297 MiB** |
| **C** | minus draft too | **STARTED**, peak **14,229 MiB** |

**SHA `96366d93`.** Three readings come out of this and two of them corrected the author:

- **The adapter is the only fatal blocker.** `qwen2` LoRA against a `gpt-oss` base, engine refuses.
- **The draft does not reject** — it starts and generates, but **164.4 tok/s with the draft vs
  166.3 without** means speculative decode buys **nothing** across a mismatched vocabulary.
- **The VRAM prediction was wrong, and its error is this repo's signature failure.** The doc had
  projected *"12.81 GiB + ~3.9 GiB KV ≈ 16.7 GiB — it will not fit"*; measured **14,297 MiB at
  full production context, generating.** The ~3.9 GiB KV figure was measured on **Qwen2.5-7B (28
  blocks)** and applied to **gpt-oss (24 blocks, 32 experts, different attention geometry)** as
  though KV cost were a property of context length rather than of the model's shape. **Carrying
  one model's measurement onto another is the same error as carrying a figure forward and
  re-dating it.**

**The live concern is co-residency, not startup.** At production context with the draft, one probe
peaked at **15,409 MiB**, leaving **894 MiB** — **below the governor's 1.5 GB drain floor.**

## 3. Candidate smoke — `dbb2adc5`

| Reading | Result |
|---|---|
| one real generation | **PASS** — exact phrase, 96 tokens, **165.4 tok/s** generation, **454.0 tok/s** prompt |
| VRAM lifecycle | **PASS** — 239 → **12,911 MiB peak** → 239 (the card is released) |
| sole GPU tenant | the smoke engine, **12,664 MiB**; nothing else held the card |
| previous default still loads | **PASS** — Qwen reloaded and generated afterwards, **5,261 MiB** |

**SHA `dbb2adc5` · 2026-08-22 · isolated port 8099, production module never imported.**

## 4. What is NOT measured — the honest majority of this file

| Position | Benchmark state | Why |
|---|---|---|
| **Chat quality** (either model) | **— not measured** | Every quality reading here is **one prompt at temperature 0**. `capability` probes return **inconclusive** by design rather than letting a regex pretend to judge prose |
| **Image / FLUX throughput** | **— not measured** | The bundle serves; no stamped tok/s or images-per-second figure exists. ~11.8 GiB resident is a *capacity* reading, not a benchmark |
| **Sigils** | **— not measured** | Shares the Image weights; no independent figure |
| **ASR / whisper** | **— cannot be measured today** | Weight present, **runtime absent** — `contrib/` does not exist. See `APPLICATION-MODEL-CAPABILITY-MATRIX.md` §1 |
| **vLLM parity** | **— not measured** | vLLM 0.25.1 is installed but **no service runs**. See `VLLM-BENCH-PARITY.md` |
| **14B / 27B / 32B tiers** | **— not measured** | On disk, manifested, no bench at production context. 27B/32B are `q2_k_xl`, a quantisation this repo has **not quality-tested** |
| **Concurrency / co-residency** | **partial** | The 15,409 MiB single-probe peak is the only reading; no Sigils-plus-Chat concurrency probe has been run |
| **Miner hashrate** | **partial, caveat attached** | 52–53 MH/s exists and **its binary cannot be rebuilt from this tree** (`contrib/build-kawpowminer.sh` untracked). **Do not publish a current hashrate claim without current proof** |
| **Studio reasoning model** | **— not measured** | `SYMONEURAL_STUDIO_LLM` selects it and **nothing pins it**; which model serves Studio is not asserted by any test |

**Two of the nine gaps are the same gap.** ASR and the miner both have artefacts in
`/contrib`, which is gitignored — so both are capabilities whose runtime cannot be rebuilt from
this tree. That is a pattern, not two coincidences.

## 5. Caveats carried forward

- **No starter changed to produce this ledger.** Qwen remains the Chat starter; gpt-oss remains a
  smoke-passed, benchmarked **candidate that is not activated**.
- **Measured at `507e09ee`, 2026-08-23**, for the "not measured" column; the figure rows carry
  their own earlier SHAs and are **transcriptions, not re-runs**. Nothing here was re-benchmarked
  today, and this sentence exists so nobody reads the ledger as a fresh run.
- **404 commits between 2026-08-17 and `7a4e5c98` are not audited.**

**Related** `docs/ops/OPENAI-GPT-OSS-MIGRATION.md` (narrative) · `docs/ops/VLLM-BENCH-PARITY.md` ·
`docs/specs/symoneural-bootcamp.md` §3 · `docs/specs/symoneural-control-plane-matrix.md` ·
`docs/ops/MEASUREMENTS.md` (suite counts, a different question) ·
`backend/apps/test_control_plane_matrix.py`
