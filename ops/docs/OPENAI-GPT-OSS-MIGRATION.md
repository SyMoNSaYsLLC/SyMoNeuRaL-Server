# SyMoNeuRaL OpenAI 20B — the LLM candidate, and what has to be true before it runs

**Opened 2026-08-22.** **Weights downloaded and converted 2026-08-22 on Garrett's explicit
authorization, live-smoked and benchmarked — see §3a-§3d.
**NOT activated: one measured blocker, §3d.** Qwen unchanged and not deleted. No deploy.**

| | |
|---|---|
| internal id | **`symon-openai-20b`** |
| display name | **SyMoNeuRaL OpenAI 20B** |
| short name | **SyMon OpenAI 20B** |
| upstream | **`openai/gpt-oss-20b`** |
| status | **AUDIT / CANDIDATE** |
| downloaded | **yes — 2026-08-22, 32 GiB staged, see §3a** |
| converted | **yes — 12.85 GiB GGUF, MXFP4 preserved, see §3b** |
| smoked | **yes — 2026-08-22, loads/generates/fits; 5 of 6 readings, see §3c** |
| benchmarked | **yes — base-vs-base vs Qwen, see §3d** |
| licence text | **stored — Apache-2.0, `backend/models/licenses/`** |
| `general.name` | **`SyMoNeuRaL OpenAI 20B`** (was `Hf`) |
| **promotable?** | **NO — one measured blocker: the qwen2 persona adapter, §3d** |
| active | **no** |

## 0. Scope, stated first because it is the thing most likely to be over-read

**This is an LLM candidate. It replaces nothing else.**

- **Image stays FLUX/Schnell.** There is no local open-weight OpenAI image model in this repo's
  scope, and `ops/docs/COMFY-FLUX-BUNDLE.md` formalises the existing stack rather than migrating
  it. **Any claim that an OpenAI weight replaces FLUX is false.**
- **Audio stays whisper.cpp.** An OpenAI Whisper *API* is not a local open-weight replacement for
  a local model. If it is ever wanted it is a separate, clearly-marked **API/FUTURE** provider.
- **`openai/gpt-oss-120b` is FUTURE only** — not staged, not planned, not sized for this card.

## 1. What it would replace, measured

| | |
|---|---|
| active chat | `backend/models/llm/symon-1.0-7b-q4_k_m.gguf` — 4.36 GiB, `bartowski/Qwen2.5-7B-Instruct-GGUF`, Apache-2.0, licence text on disk |
| active draft | `backend/models/llm/symon-1.0-draft-0.5b-q4_k_m.gguf` — 0.37 GiB, speculative decode |
| set at | `backend/server.py:187`, `:191` |
| runtime | llama.cpp-family engine, `-ngl 99` (`api.py:1163`) |

**Qwen remains active and is not deleted.** It becomes `rollback` **only** after a smoke record
exists and Garrett approves activation — two conditions, not one.

## 2. The runtime gate — ANSWERED 2026-08-22. Verdict was **NEEDS CONVERSION**; now **DONE**

**Everything required is present in this tree. A conversion step was required because upstream
ships safetensors and the engine consumes GGUF.** That conversion **ran on 2026-08-22 and
succeeded** — §3b. This section is kept as the pre-conversion analysis it was, because it is what
the decision was made on; the rows below describe **upstream**, not this disk.

### What upstream actually ships — read from the HF API, not from memory

| | |
|---|---|
| `original/model.safetensors` | **13,761,300,984 B = 12.81 GiB**, single file |
| top-level shards | `model-0000{0,1,2}-of-00002.safetensors` — **13,761,316,904 B = 12.81 GiB** total |
| GGUF in the **upstream repo** | **none** — which is why a conversion step existed at all |
| parameters | 21,511,953,984 |
| quantisation | **MXFP4**, with attention, router and embedding/output head **not** converted |
| licence | **Apache-2.0** |

**Apache-2.0 closes the licence question** that §5 had open as `unknown-blocked` — the text
still has to be stored on disk before activation, but the answer is no longer unknown.

### What this box can do — measured from the engine source

| Capability | State |
|---|---|
| engine | `engines/symoneural-llm/build/bin/symoneural-llm` — **`build 296, commit 2246ab7`** |
| `gpt-oss` architecture | ✅ `LLM_ARCH_OPENAI_MOE` → `"gpt-oss"`, `llama-arch.cpp:121` |
| Harmony chat template | ✅ `LLM_CHAT_TEMPLATE_OPENAI_MOE`, `llama-chat.cpp:75` |
| **MXFP4 as a ggml type** | ✅ **`GGML_TYPE_MXFP4 = 39`**, `ggml.h:429`; `GGML_FTYPE_MOSTLY_MXFP4` |
| **MXFP4 on CUDA** | ✅ `convert.cu`, `getrows.cu`, MMQ configs — **the GPU path, not just CPU** |
| GGUF writer support | ✅ `gguf-py/gguf/constants.py`: `GPT_OSS`, tensor map, `MXFP4 = 39`, `MOSTLY_MXFP4_MOE = 38` |
| **converter module** | ✅ **`engines/symoneural-llm/conversion/gpt_oss.py`** — `@ModelBase.register("GptOssForCausalLM")`, with **`repack_mxfp4()`** |

**`repack_mxfp4` is the detail that makes this workable.** It repacks the MXFP4 blocks rather
than dequantising them — `dequant_model()` returns early when `_is_mxfp4` — so the conversion
preserves the 4-bit weights instead of inflating them to bf16. Without that the output would be
several times larger and would not fit this card at all.

### Why the verdict is NEEDS CONVERSION and not READY

The engine reads **GGUF**. Upstream publishes **safetensors only**. So one step stands between
them, and it is supported in-tree.

**The conversion needs PyTorch, and the interpreter matters:**

| Interpreter | torch |
|---|---|
| `/usr/bin/python3` | **absent** |
| **`training/.venv/bin/python3`** | **2.11.0+cu128, `cuda available: True`, sm_120 recognised** |

**Use `training/.venv/bin/python3` for the conversion.** The system interpreter cannot run it.

### Footprints — measured, not projected

**Disk — re-measured 2026-08-22 after the download, because the pre-download projection was
already wrong.** The projection said ~26 GiB peak on the assumption of one 12.81 GiB download.
**Two trees were fetched** (§3a) and the GGUF has since been written (§3b), so the real total is
**~45 GiB**, not 26 — and all four items below are **retained on Garrett's instruction** until
the activation decision is made (the live-smoke condition was met on 2026-08-22, §3c):

| | |
|---|---|
| `original/` (unconvertible, retained) | 13 GiB |
| `hf/` (convertible) | 19 GiB |
| dead `.incomplete` leftovers, reclaimable | 6,574,559,947 B |
| **GGUF, written 2026-08-22** | **12.85 GiB** (13,792,638,624 B after the name patch) |
| **total staged now** | **~45 GiB** — all four retained on instruction |
| available on `/home` before → after conversion | **793 GB → 780 GB** |

**Disk is still not a constraint**, but note the mount: `df /` reports **277 GB** and is the
*wrong* filesystem. `backend/models` lives on `/home` (`/dev/nvme0n1p5`, 1.4T). A capacity check
run against `/` would be off by a factor of three in the reassuring direction.

**VRAM — and this is the finding that changes the smoke command.** The card is **16,303 MiB**,
972 MiB used at idle. The production launch argv is `-c 65536 -cb -np 2`, and the module's own
measured comment records **9,485 MiB total for a 4.36 GiB model** — so **KV and overhead cost
~3.9 GiB at that context**.

> **12.81 GiB of weights + ~3.9 GiB of KV ≈ 16.7 GiB on a 16,303 MiB card. It will not fit.**

> ⚠️ **BOTH claims in this block were disproved by measurement on 2026-08-22 — see §3d.**
> Idle was **239 MiB**, not 972. And the "it will not fit" conclusion is **FALSE**: the candidate
> ran at the full production context `-c 65536 -cb -np 2`, **generating, at 14,297 MiB peak.**
>
> **The error was applying Qwen2.5-7B's KV measurement to a different model.** ~3.9 GiB of KV was
> measured on a 28-block dense model and reused here for a 24-block 32-expert one, as if KV cost
> followed context length alone rather than the model's own shape. **That is carrying a figure
> across a boundary it was never measured across** — the failure this repo's rules name — committed
> in the document that names it. The paragraph is left standing, marked, because deleting it would
> hide the mistake rather than record it.

**The smoke still uses the reduced context, and the reason now stands on different ground:**
the production context *does* fit, but a smoke should not be the first thing to discover that.
`--smoke-candidate` uses **`-c 8192 -np 1`**, and says why in its own output — because *an OOM nobody predicted reads like
an incompatible model rather than an argv that was too greedy.*

## 2a. Isolated smoke — the candidate proves itself or fails

```bash
scripts/modelops/symoneural-modelops-stage.sh --smoke-candidate symon-openai-20b
```

**Isolation is structural, not a flag.** The mode launches the engine binary directly against the
candidate file, on port **8099** (not the production 8081), in its own process, and **never
imports or invokes the production API module** — which is the only thing that knows what the
production defaults are. A fallback is therefore not *disabled*; it is **unreachable**.

**A flag that disables a fallback can be wrong. A function that cannot name the fallback cannot
load it** — and the function is held to exactly that by
`test_the_smoke_mode_cannot_NAME_what_it_must_not_load`, which forbids the production symbols and
filenames from appearing **anywhere in its body**. The body explains the isolation in neutral
terms for that reason.

| Property | How |
|---|---|
| no adapter | the printed argv carries no adapter flag; asserted |
| no draft model | no draft flag; speculative decode is a pairing trained for the production default |
| own port | 8099; the production port never appears in the body |
| **fails when the candidate is missing** | **exit 5**, `REFUSED`, and it says the active model was not consulted |
| fails when the engine is missing | exit 5 |
| reports what ran | candidate path, engine path, **engine `--version`**, and the exact argv |
| production default | **unchanged.** Rollback weights present and untouched; asserted against the disk |

**The smoke path does not need PyTorch** — it is the C++ engine binary. Only the conversion does.

**"Disabled for smoke" means disabled in the test path.** It does not mean deleted, moved, or
that the production default changed.

## 3. Staging — recorded, not run

```bash
scripts/modelops/symoneural-modelops-stage.sh --stage-openai-gpt-oss-20b
```

Writes `backend/models/staging/openai-gpt-oss-20b/STAGED-MANIFEST.json` and `ROLLBACK.md`, and
**prints** the download command:

```bash
hf download openai/gpt-oss-20b \
  --exclude "original/*" --exclude "metal/*" \
  --local-dir backend/models/staging/openai-gpt-oss-20b/hf/
```

> **Not `huggingface-cli`.** That entrypoint is **deprecated and no longer works**, and its
> failure mode is the one worth writing down: it prints a deprecation notice and **exits 0
> without downloading anything.** A caller that checks the exit code sees success and an empty
> directory. Found by running it — this document recorded the dead command until 2026-08-22,
> when the first authorized download produced 12 KB and a zero exit. `hf` is the replacement
> and is already installed. Measured against `huggingface_hub 1.23.0`.

**It will not run it.** Even with `SYMONEURAL_MODELOPS_CONFIRM` set to the phrase, the script
declines and says why: tens of GB onto a disk already holding **194 GB** should not be one
environment variable away from being spent. **The download is Garrett's to run by hand**, after
he says so.

**Staging is gitignored** (`.gitignore:5`, `backend/models/*`), so neither the weights nor the
staged manifest can be committed. Structural, not a promise.

## 3a. What was actually downloaded — 2026-08-22, and the correction it forced

**Two downloads happened, and the first one fetched the wrong thing.** Recording both, because the
mistake is the useful part.

| Tree | Bytes | Convertible? |
|---|---|---|
| `original/` | 13 GiB, single `model.safetensors` | **NO** |
| **`hf/`** | **19 GiB, 3 shards + tokenizer** | **yes** |

**Why `original/` cannot be converted** — three independent blockers, all found by reading the
downloaded files *before* running the converter rather than after it failed:

1. `original/config.json` has **no `architectures` key**, so `ModelBase` cannot dispatch to the
   `@ModelBase.register("GptOssForCausalLM")` handler at all.
2. Its tensors are named `block.0.attn.qkv.weight` — the **original OpenAI layout**. The converter
   expects the HF names (`gate_up_proj`, `down_proj`).
3. **No tokenizer.** `original/` ships weights only.

> **The `--include "original/*"` in §3's printed command was wrong**, and it was wrong in a way
> that costs 13 GiB to discover. `original/` is the OpenAI *reference* checkpoint, not the HF one.
> The correct filter is `--exclude "original/*" --exclude "metal/*"`.

**The root download, verified byte-exact against the HF API's reported sizes:**

| File | Bytes |
|---|---|
| `model-00000-of-00002.safetensors` | 4,792,272,488 |
| `model-00001-of-00002.safetensors` | 4,798,702,184 |
| `model-00002-of-00002.safetensors` | 4,170,342,232 |
| `tokenizer.json` | 27,868,174 |
| `model.safetensors.index.json` | 36,355 — names **3 shards / 459 tensors**, all present |
| `LICENSE` | 11,357 |

All three conversion blockers are now closed: `architectures: ["GptOssForCausalLM"]`,
`quant_method: mxfp4`, full tokenizer.

### Two operational findings worth keeping

**The download stalled, and an unauthenticated fetch is why.** Two shards sat idle 932 s and 669 s,
2.81 GiB short. `hf auth whoami` → **not logged in**; no `HF_TOKEN`, no `HUGGINGFACE_HUB_TOKEN`, no
`~/.cache/huggingface/token`. So every byte here came down anonymous, against a rate limit, which
matches the warning the client printed. **Re-running `hf download` resumed from the `.incomplete`
files** and moved 5,271 MiB in 60 s. Nothing was re-fetched from zero.

**6,574,559,947 bytes of dead `.incomplete` files remain** under `hf/.cache/huggingface/download/`.
The resume wrote into fresh temp files rather than continuing those two, so they are reclaimable —
measured static over a 10 s window, with no writer process alive. **Not deleted**: no mode of this
workflow deletes without authorization.

### Shard integrity — because a resumed download can be the right length and the wrong bytes

Two of the three shards were completed by **resuming from `.incomplete` files after a stall**, and
a resume that appends onto a corrupt prefix produces a file of exactly the expected size. **Byte
count is therefore not sufficient evidence here.** Each shard's safetensors header was parsed and
its offsets checked — seconds of work, no torch required:

| Shard | Header | Tensors | Last tensor ends | Payload | |
|---|---|---|---|---|---|
| `model-00000-of-00002` | 22,240 | 196 | 4,792,250,240 | 4,792,250,240 | ✅ |
| `model-00001-of-00002` | 22,304 | 197 | 4,798,679,872 | 4,798,679,872 | ✅ |
| `model-00002-of-00002` | 7,568 | 66 | 4,170,334,656 | 4,170,334,656 | ✅ |

**459 tensors, matching `model.safetensors.index.json` exactly.** Dtypes are **`BF16` and `U8`** —
and the `U8` is the load-bearing observation: **the MXFP4 blocks are still packed 4-bit in uint8,
not dequantised.** If these read as all-BF16 the weights would already have been inflated upstream
of us and the size projection below would be wrong.

### The corrected conversion command

```bash
training/.venv/bin/python3 engines/symoneural-llm/convert_hf_to_gguf.py \
  backend/models/staging/openai-gpt-oss-20b/hf \
  --outfile backend/models/staging/openai-gpt-oss-20b/symon-openai-20b.gguf \
  --outtype auto
```

**Note the input path is `hf/`, not the staging root.** Pointed at the root, the converter would
find `original/` and hit blocker 1.

#### Judge the result by output size, not by the exit code

`--outtype auto` is the untested part of that command. **MXFP4 preservation comes from
`_is_mxfp4` short-circuiting `dequant_model()`, not from `--outtype`** — so if `auto` resolves to
bf16 in this fork, the conversion *succeeds*, exits 0, and writes an inflated model.

| Output size | Verdict |
|---|---|
| **~12–13 GiB** | **MXFP4 preserved — correct** |
| ~40+ GiB | dequantised to bf16 — **wrong; redo with an explicit outtype** |

**This has to be checked at conversion time, not at smoke time.** 793 GB free means disk will not
stop a 40 GiB write, and the failure would surface as a smoke OOM — which reads as *"the candidate
is incompatible"* rather than *"the file is three times the size it should be."* That is the exact
misdiagnosis the `-c 8192` note in §2a exists to prevent, arriving by a different route.

## 3b. Conversion — RUN 2026-08-22. **MXFP4 preserved.**

```bash
training/.venv/bin/python3 engines/symoneural-llm/convert_hf_to_gguf.py \
  backend/models/staging/openai-gpt-oss-20b/hf \
  --outfile backend/models/staging/openai-gpt-oss-20b/symon-openai-20b.gguf \
  --outtype auto
```

| | |
|---|---|
| output | `backend/models/staging/openai-gpt-oss-20b/symon-openai-20b.gguf` |
| **bytes** | **13,792,638,592 = 12.85 GiB** |
| tensors | **459** — matching the safetensors index exactly |
| architecture | **`gpt-oss`** — the name `llama-arch.cpp:121` registers |
| **file type** | **38 = `MOSTLY_MXFP4_MOE`** |
| tensor types | **72 MXFP4**, 98 BF16, 289 F32 |
| geometry | 24 blocks, 32 experts, 4 used, 131072 context |
| tokenizer | gpt2 BPE + Harmony chat template, both embedded |
| disk | 793 GB → **780 GB** free |
| write rate | ~446 MB/s, 31 s |

### The size gate passed, and here is why `--outtype auto` was safe after all

**`--help` describes `auto` as "the highest-fidelity 16-bit float type", which reads exactly like
the inflation risk.** It is not, and the reason is worth recording because the flag name actively
misleads here:

- `conversion/gpt_oss.py:18-21` — **`dequant_model()` returns early when `_is_mxfp4`.**
- `repack_mxfp4()` adds tensors with **`raw_dtype=GGMLQuantizationType.MXFP4`**, which bypasses
  the outtype quantiser entirely.

So `--outtype` only governs the tensors that were **never** MXFP4 — attention, router, embeddings,
which upstream ships as BF16 and which appear in the output as 98 BF16 tensors. **The 72 quantised
expert tensors are untouched by it.**

**Three independent confirmations, not one:**

1. **The converter's own `--dry-run`** printed `n_tensors = 459, total_size = 13.8G` *before writing
   a byte*. That check cost seconds and would have caught a 40 GiB plan for free — it is the right
   first move for any future candidate.
2. **Zero `is not in MXFP4` warnings** in the log, against **72 `Repacked ... MXFP4` lines**.
3. **The written file parsed back** with `gguf-py`'s own reader: `file_type 38`, 72 MXFP4 tensors.

> **Size alone would not have been proof.** 12.85 GiB is consistent with MXFP4 *and* with several
> other outcomes; `file_type 38` plus 72 MXFP4 tensors is what actually settles it. The size gate
> was the cheap screen, not the verdict.

### Isolated smoke — dry run now passes

`--smoke-candidate symon-openai-20b --dry-run` was **exit 5, `FAIL no .gguf`** before conversion and
is now **exit 0**, finding both the candidate and engine `build 296, commit 2246ab7`.

**The VRAM question is still open and only a live run answers it.** 12.85 GiB of weights = 13,160
MiB against a **16,303 MiB** card with ~972 MiB used at idle — roughly **2,200 MiB** left for KV and
compute buffers at `-c 8192 -np 1`. Plausible, and **not measured.** That is the whole reason
`SMOKE-PASSED.txt` is gate 2.

## 3c. Live isolated smoke — RUN 2026-08-22. **It runs.**

`SMOKE-PASSED.txt` is written and carries the readings; it is in gitignored staging, so this is
the tracked summary.

| Reading | Result |
|---|---|
| runtime load | **PASS** — health in 4 s, no warnings, `n_ctx_slot 8192` |
| tokenizer / template | **PASS** — Harmony markers in `/props`, and `reasoning_content` came back populated, so the analysis channel parses end-to-end |
| one real generation | **PASS** — exact phrase, 96 tokens, 165.4 tok/s generation, 454.0 tok/s prompt |
| VRAM measured | **PASS** — 239 → **12,911 MiB peak** → 239, on a 16,303 MiB card |
| **governor lease** | **NOT DONE — and not possible this way. See below.** |
| previous default still loads | **PASS** — Qwen reloaded and generated afterwards, 5,261 MiB |

```
prompt:   Say exactly: SyMoNeuRaL OpenAI candidate online.
response: SyMoNeuRaL OpenAI candidate online.
```

### The VRAM projection was wrong in the safe direction

§2 predicted ~2,200 MiB of headroom from an assumed 972 MiB idle. **Idle was 239 MiB**, so real
headroom at peak was **3,392 MiB** — about 1.2 GiB more than predicted. **The projection was
conservative, not accurate**, and it is the measurement that stands. This changes nothing about
the production context: `-c 65536 -np 2` was never attempted and is still predicted not to fit.

### Reading 5 is a structural gap, not an oversight

**No governor lease was taken, and this path cannot take one.** The governor lives in the
production module, and the smoke path is forbidden from importing it — that forbidding is exactly
what makes a fallback *unreachable* rather than merely *disabled*. **A lease and this isolation
are mutually exclusive.**

So the record proves the candidate **runs**; it does **not** prove it behaves as a governor tenant
alongside other work. Whoever promotes it still owes that reading through the normal serving path.
**Reading 4 does not cover it** — that the weights fit is not that the candidate cooperates.

### Isolation, read from the kernel rather than argued from the argv

| Claim | How it was established |
|---|---|
| only the candidate was opened | `/proc/<pid>/fd` + `/proc/<pid>/maps` — the candidate GGUF **and nothing else** |
| no Qwen, draft, adapter, FLUX or whisper | **zero** matches across that process's fds and maps |
| **port 8081 never listening** | the fallback was not blocked, it was **absent** — no production LLM server existed |
| response attributable to this engine | `model` = candidate path, `system_fingerprint` = `b296-2246ab7` |
| only GPU tenant | the smoke engine, 12,664 MiB; nothing else held the card |

> **One thing worth stating plainly, because "isolated" invites over-reading:** `backend/server.py`
> **was running throughout** (pid 1849, up 1h44m). It was neither used nor disturbed — it held no
> model file and no GPU memory, because it spawns an engine on demand and had not. Saying "nothing
> else was running" would have been false; saying "nothing else served this request" is what was
> proven.

### What the smoke does not say

**One deterministic 96-token completion is evidence of life, not of quality.** No benchmark, no
A/B against the current default, no eval. Nothing here argues the candidate is *better* than Qwen —
only that it loads, generates, fits, and releases the card.

## 3d. Naming, licence, benchmark — and why promotion did NOT happen

### general.name fixed without editing a byte of the original

It read `Hf`, from the input directory name. `gguf-py` ships **`gguf_new_metadata.py`, which writes a
copy** rather than editing in place — so the validated original was never touched. The copy was
read back (architecture, `file_type 38`, all 459 tensors and their types, tokenizer, Harmony
template — **identical**), then made canonical by atomic rename, sha256 preserved.

| | |
|---|---|
| `general.name` | **`SyMoNeuRaL OpenAI 20B`** — the real GGUF field, not just a display string |
| size | 13,792,638,624 B — **32 B larger**, being the longer name plus alignment |
| GGUFs in staging | **exactly one.** Two would have been worse than a wrong name: the smoke selects with `find -print -quit`, so it would have validated one file while promotion used the other |

**Licence stored** at `backend/models/licenses/openai-gpt-oss-20b-LICENSE.txt`, 11,357 B,
byte-identical to upstream, sha256 `58d1e17f…`, read and confirmed as **Apache-2.0 Version 2.0**.
This discharges the **local activation** gate only — it is *not* a commercial-readiness finding,
and ML-2's four fields remain unrecorded for every model here.

### Benchmark — base vs base, and the headline is not throughput

Same prompt, same context, isolated port, no adapter, no draft, on the same idle card.

| | **SyMoNeuRaL OpenAI 20B** | **Qwen (current default)** |
|---|---|---|
| load | 4.03 s | **2.02 s** |
| peak VRAM | 12,911 MiB | **5,259 MiB** |
| prompt | 571.8 tok/s | **1,807.1 tok/s** |
| **generation** | **166.3 tok/s** | 147.6 tok/s |
| tokens for a one-sentence answer | **259** | **25** |
| wall clock | 1.72 s | **0.21 s** |

**Read the token column before the tok/s column.** gpt-oss spent **259 tokens on a one-sentence
request** against Qwen's 25 — the Harmony reasoning channel is charged whether or not anyone reads
it. A 13% generation-rate win alongside a **10× token cost** is not a throughput win, and the
1.72 s vs 0.21 s wall clock is what a user would actually feel.

**And both answers were wrong.** Asked "What is SyMoNeuRaL?", gpt-oss produced *"a hybrid
neural-symbolic architecture…"* and Qwen *"a symbolic model neural network library…"*. Neither is
this project. **The prompt measured fluency, not knowledge** — and the production Qwen path answers
it *with* the persona adapter that this isolated benchmark deliberately excluded. **Base vs base is
the only honest label for this table.**

### The one real blocker — measured, after two of my own predictions were disproved

I predicted three blockers. **Probing each separately turned that into one.**

| Probe | Result |
|---|---|
| **A** — full production argv | **exit 1**, `llama_adapter_lora_init: failed to apply lora adapter: model arch and LoRA arch mismatch` |
| **B** — minus `--lora`, draft kept | **STARTED**, generated, peak 14,297 MiB |
| **C** — minus draft too | **STARTED**, peak 14,229 MiB |

- **Blocker 1 — the adapter. FATAL, and the only one.** `api.py:1196-1197` applies `--lora`
  **unconditionally when the file exists**. That adapter is `general.architecture: qwen2`, base
  `Qwen/Qwen2.5-7B-Instruct`. The candidate is `gpt-oss`. The engine refuses and exits 1.
- **Blocker 2 — the draft. WRONG.** I predicted the 151,936-vs-201,088 vocab gap would make `-md`
  reject. It does not: the server started and generated. *Loading is not working*, though —
  164.4 tok/s with the draft vs 166.3 without means speculative decode is buying **nothing**,
  which is what a mismatched vocabulary predicts.
- **Blocker 3 — VRAM. WRONG, and this doc was the source of the error.** §2 says
  *"12.81 GiB + ~3.9 GiB KV ≈ 16.7 GiB… it will not fit."* **Measured: 14,297 MiB at the full
  production context, generating.** The ~3.9 GiB KV figure was measured on **Qwen2.5-7B (28
  blocks)** and applied to **gpt-oss (24 blocks, 32 experts, different attention geometry)** as
  though KV cost were a property of context length alone. It is a property of *the model's shape*.
  **Carrying one model's KV measurement onto another is the same error as carrying a figure forward
  and re-dating it** — the thing this repo warns about — and I did it in the doc that warns about it.

> **The real remaining concern is not startup, it is co-residency.** At production context with the
> draft, peak was **15,409 MiB in one probe** — leaving 894 MiB, **below the governor's 1.5 GB drain
> floor.** That is an image-stack co-tenancy problem, not a load failure.

### Why promotion was not taken, with all six gates green

**All six gates pass.** They are also, all six, readings of files and a marker — **not one of them
asks whether the chat surface starts.** Probe A says it does not. This is the **#94 failure
`.claude/CLAUDE.md` names** — green checks over a dead surface — caught before archiving instead of
after.

The blocker has a small fix: apply `--lora` only when the adapter's architecture matches the
model's. **But the fix is not the whole change**, because five sites read `CHAT_ADAPTER.exists()`
as a proxy for *"the adapter is in use"* (`:1963`, `:2015`, `:2020`, `:2355`, `:2522`), and one
hardcodes `"SymonChat S1-7B"`. After promotion the file still exists and is **not applied**, so the
rack unit would announce **"SymonChat S1-7B + persona adapter"** while serving a 20B model with no
persona, and `/api` would report `"adapter": true`. **That is shipping a claim that is not true**,
which is the one thing this repo is built to refuse.

**And the product consequence is a decision, not a config detail: promotion loses the persona
adapter entirely.** There is no gpt-oss-shaped LoRA on this box, and training one is its own task
with its own corpus run. The adapter is what makes the surface *SymonChat* rather than *base Qwen* —
and the benchmark above is precisely the evidence that base models do not know what SyMoNeuRaL is.

**Garrett's call, with the work scoped:** an `adapter_applies()` arch-match predicate, the five
status sites reading it instead of `.exists()`, a model-aware display string, `CHAT_MODEL` and a
recorded `ROLLBACK_MODEL`, each with a test and each verified by sabotage. Small, but it touches the
live chat launch path and it changes what the product says about itself.

## 4. The six activation gates

`--activate-candidate symon-openai-20b` exits **3** and prints REFUSED unless **all** hold:

1. candidate staged — `STAGED-MANIFEST.json` exists
2. **`SMOKE-PASSED.txt` exists**
3. `ROLLBACK.md` exists
4. licence recorded — the manifest no longer says `UNRECORDED`
5. runtime compatibility recorded — likewise
6. `SYMONEURAL_MODELOPS_APPROVE=symon-openai-20b` in the environment

**Gate 2 is the one that matters.** `exists` and `grep` ask what is on disk; **neither can ask
whether a model works.** That is #94's lesson — eighteen green checks over a dead surface —
applied to models. `--smoke-plan` prints the six readings the marker must contain: runtime load,
tokenizer round-trip, one real generation, **measured** VRAM, a governor lease taken and
released, and **the previous default proven to still load afterwards.**

**Even with all six passing, the script does not rewrite `CHAT_MODEL`.** It backs up `api.py` and
stops, saying why: promotion edits a source file the API reads at import, and **that belongs in a
reviewed commit with a test, not a shell one-liner.** The gate's job is to say whether promotion
is *allowed* — not to get it past review.

## 5. Licence — unrecorded, and therefore blocking

**Answered 2026-08-22: the upstream licence is Apache-2.0**, read from the HF API rather than
recalled. So it is no longer `unknown-blocked` on the *question* — but gate 4 still refuses
activation, because the **text is not on disk** and the manifest still says `UNRECORDED`.

Before it can be anything else: the upstream licence read, its **text stored on disk** beside the
others in `backend/models/licenses/`, and the four commercial fields recorded that
`MODEL-LICENSES.md` ML-2 says are missing for **every** model here — redistribution, commercial
use, modification, output restrictions.

**This is not pedantry about a candidate.** Three weights already on this box are
`redistribution-restricted` in practice because their licence text is absent (ML-1). Adding a
fourth unrecorded model would repeat a known-open finding on purpose.

## 6. Naming — house name is display, upstream is recorded exactly

**SyMoNeuRaL OpenAI 20B** / **SyMon OpenAI 20B** are display names. The manifest records
`openai/gpt-oss-20b` verbatim.

**Never rename a licence file. Never hide upstream origin.** `PROVENANCE.json`'s own reason:
*"a house name with no recorded origin is an unfalsifiable claim about what the bytes are."*

## 7. Not authorized

No download · no activation · no `CHAT_MODEL` edit · no Qwen deletion or move · no weight
committed · no licence file renamed · no claim that this is active, working, or better · no
claim it replaces the image or audio stacks · no deploy.

**Until Garrett says otherwise: Qwen 7B is the chat model, and `symon-openai-20b` is a name in a
document.**
