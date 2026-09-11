# SyMoNeuRaL QLoRA — upgrade spec

**Proposal, not state.** Per `ops/backend/authority/docs/README.md`, nothing in this directory is
authoritative for what the project is. `.claude/HANDOVER.md` is the state document and
`.claude/CLAUDE.md` is the rulebook. This file is an argument to evaluate.

Written 2026-08-17 against the tree at `595835d`. It quotes `file:line`; **re-grep before
trusting any of them.** That warning is unusually live here: `backend/server.py`,
`scripts/gpu-governor.sh`, `tools/build/build_pages.py` and `tools/build/build_training.py` were all
being edited by other agents while this was written, and the `train` unit's line number moved
once mid-audit. Every load-bearing claim below was re-verified against the working tree at
the end of the pass; the line numbers are the part most likely to have drifted since.

Asked for by the owner: *"update/upgrade the qlora. The symoneural qlora doesnt even give a
place to load the model and use predetermined professional tuning methods"*, and then:
*"symoneural qlora should be based off of symoneural reinforce and the other references such
as fine tuning and studio (just not with all the apps in studio as it was before)."*

`ops/backend/authority/docs/README.md` carries a one-row-per-spec table. This file needs a row added to it —
`qlora-upgrade.md` | Model picker + preset profiles for the `train` rack unit | proposed, not
implemented. That edit is outside this file's remit and has not been made.

---

## 0. The complaint is correct, and it is worse than "no UI"

The owner's phrasing — *no place to load the model* — is precisely right, and the audit found
three layers of it:

| Layer | State |
|---|---|
| A page to drive it | **None.** The `train` unit's `href` is `/training.html`, which is the 422 KB **manual**, not a tuning UI. |
| An API route | **None.** `backend/server.py` defines 14 routes plus one router (`tuner`); not one of them is `/api/train*`. `grep -c "/api/train" backend/server.py` → **0**. |
| A choice of base model | **One.** Exactly one base model on this box can be fine-tuned at all — see §4.1. |
| A choice of method | **None.** Everything but four values is hardcoded in `training/train_lora.py`. |

So the surface is a rack unit that reports state, links to a book, and is driven by one
shell command a human has to remember. The rack unit itself is honest — it goes `busy` when
the governor records `train` as holder — but there is nothing behind it.

---

## 1. What exists today

### 1.1 The trainer — `training/train_lora.py` (148 lines)

Four values are exposed on the CLI. Everything else is a literal.

| Knob | Value | Where | Exposed? |
|---|---|---|---|
| base model | `Qwen/Qwen2.5-7B-Instruct` | `:41` (`BASE_MODEL`), `:48` | `--base` |
| epochs | `3.0` | `:49` | `--epochs` |
| max seq length | `1024` | `:50` | `--seq-len` |
| LoRA rank `r` | `16` | `:51` | `--rank` |
| learning rate | `1e-4` | `:52` | `--lr` |
| corpus path | `training/corpus.jsonl` | `:46` | `--corpus` |
| output path | `training/adapter` | `:47` | `--out` |
| **lora_alpha** | `r * 2` → 32 | `:104` | hardcoded |
| **lora_dropout** | `0.05` | `:105` | hardcoded |
| **bias** | `"none"` | `:106` | hardcoded |
| **target_modules** | q,k,v,o,gate,up,down | `:110-111` | hardcoded |
| **quantisation** | 4-bit **NF4**, double-quant on, bf16 compute | `:91-97` | hardcoded |
| **per_device_train_batch_size** | `1` | `:122` | hardcoded |
| **gradient_accumulation_steps** | `8` (effective batch **8**) | `:123` | hardcoded |
| **gradient_checkpointing** | `True` | `:101`, `:124` | hardcoded |
| **lr_scheduler_type** | `cosine` | `:126` | hardcoded |
| **warmup** | `max(3, int(0.05 * N * epochs / 8))` steps | `:129` | hardcoded |
| **optimizer** | `paged_adamw_8bit` | `:133` | hardcoded |
| **bf16** | `True` | `:132` | hardcoded |
| **save_strategy** | `"no"` | `:131` | hardcoded |
| **report_to** | `[]` | `:134` | hardcoded |
| **logging_steps** | `10` | `:130` | hardcoded |
| trainer class | `transformers.Trainer` | `:115` | hardcoded |
| loss masking | hand-rolled `-100` prompt mask | `:74-85` | hardcoded |

Two design choices in it are good and must survive any rewrite: loss is computed on the
assistant turn only (`:83-84`), and the adapter is kept separate rather than merged so
llama.cpp can load it as a GGUF LoRA at serve time. Both are documented in the module
docstring with their reasons.

### 1.2 The API — nothing

`backend/server.py:1355-1363` defines the unit and that is the whole of it:

```
Unit(id="train", label="SyMoNeuRaL Quantized Low-Rank Adaptation Tool", slot="2U",
     state="busy" if holder == "train" else
           ("ready" if CHAT_ADAPTER.exists() else "offline"),
     bus="gpu", href="/training.html", ...)
```

`CHAT_ADAPTER` is `training/adapter/symoneural-lora.gguf` (`:93`). `ready` here means *an
adapter file exists on disk*, not *this unit can accept work* — every other `ready` unit on
the rack has a route behind it. That is the honest reading of the current state and it is
also the strongest single argument for this spec.

### 1.3 The environment — `training/.venv`, verified by `pip list`

| Package | Version | Note |
|---|---|---|
| torch | **2.11.0+cu128** | `get_arch_list()` includes `sm_120` — no source build needed |
| transformers | **5.15.0** | |
| peft | **0.20.0** | |
| bitsandbytes | **0.50.1** | |
| trl | **1.10.0** | present and **unused** |
| accelerate | 1.14.0 | |
| datasets | 5.0.1 | |
| gguf | 0.19.0 | used here to read GGUF metadata for §4 |

`trl` exposes `SFTTrainer/SFTConfig`, `DPOTrainer`, `GRPOTrainer`, `KTOTrainer`,
`RewardTrainer`, `RLOOTrainer`, `DistillationTrainer`. None is used.

### 1.4 The governor

`.claude/CLAUDE.md` states the rule plainly: **"`train` is never evicted to serve a page
view."** `scripts/gpu-governor.sh:91-101` implements it — a `train` holder with a live pid
produces `REFUSING to evict a training run -- wait for it or stop it deliberately`, and the
`train` branch is the exact opposite of the miner branch two lines below it, which yields to
everything.

**`train_lora.py` never touches the governor.** No `acquire`, no `with`, no subprocess. The
lock was taken by a human wrapping the command — the form is recorded at
`ops/history/archive/HANDOVER-2026-08-16-1910.md:579`:

```
gpu-governor.sh with train -- training/.venv/bin/python training/train_lora.py ...
```

What `run/governor.log` actually records for `train` on 2026-08-16:

```
16:26:50  wait     'train' wants the card
16:26:50  evict    stopping 'chat' to make room -- the weight sets do not co-fit
16:26:50  drain    settled at 842 MiB after 0s (floor 1500 MiB)
16:26:50  acquire  'train' holds the card -- 15017 MiB free, waited 0s
16:28:59  release  'train' releasing
16:29:53  acquire  'train' holds the card -- 15017 MiB free, waited 0s
16:32:40  release  'train' releasing
16:35:58  release  'train' releasing          <-- no matching acquire
16:36:49  evict    REFUSING to evict a training run -- wait for it or stop it deliberately
```

Read this carefully rather than as a timing figure. Two held windows (2m09s, 2m47s), and a
**third release with no acquire** at 16:35:58 — while `training/adapter/*` is stamped
16:35–16:36. Either the run that produced the shipped adapter was not under the lock, or the
log is incomplete. This is exactly the unpaired-release hazard `.claude/CLAUDE.md` warns
about ("Never call a bare `release`"), showing up in the one place it matters most. **No
wall-clock training figure may be quoted from this log.**

### 1.5 Defects found while reading, all verified

1. **`HF_HOME` points at a directory that does not exist.** `train_lora.py:35,39`:
   `ROOT = HERE.parent.parent` → `/home/google`, so `HF_HOME` becomes
   `/home/google/models/hf`. Confirmed absent. The real cache is
   `models/hf/` (15 GB), moved there by `9b5da84`. A fresh run today
   re-downloads ~14.2 GiB into a non-repo path, silently, and the docstring's promise that
   *"where are the models" has one answer* is broken. The repo already has the fix pattern:
   `tools/build/build_training.py:33` asserts `(ROOT / "backend" / "api.py").is_file()` with the
   comment *"This exact calculation has been wrong twice in this repo's history ... and it
   fails silently."* It has now been wrong three times.

2. **No validation split, no eval, no checkpoints, no logging sink.** `encode()` maps the
   entire corpus to `train_dataset`; `save_strategy="no"`; `report_to=[]`; `training/runs/`
   is empty. There is no loss curve, no held-out set, and no intermediate checkpoint. The
   repo's own manual (`frontend/site/docs/symoneural-manual.md`, Playbook 04 Stage 1) instructs: *"Hold
   out 5-10% as a validation set BEFORE looking at training loss."* The shipped trainer
   violates the manual it was written from.

3. **The shipped adapter is not reproducible.** No seed is set, no run config is written
   beside the weights, and `training/adapter/README.md` is the unedited PEFT stub — every
   field is `[More Information Needed]`, including *Training Hyperparameters* and *Results*.

4. **The manual's Playbook 04 code would raise `TypeError` on this box.** Its snippet passes
   `warmup_ratio=0.03`. Verified against the installed `transformers 5.15.0` and
   `trl 1.10.0`: **`warmup_ratio` is absent from both `TrainingArguments` and `SFTConfig`**
   (`group_by_length` is gone too). `train_lora.py:127`'s comment saying 5.x dropped it in
   favour of an explicit step count is **correct** — a rare case in this repo where the
   comment beat the doc. Every preset in §5 therefore expresses warmup in **steps**.

5. **The manual's Playbook 04 status block is stale on torch.** It claims
   *"PyTorch 2.13.0+cu130"*; the venv has **2.11.0+cu128**. The venv is the authority.

---

## 2. What to take from SyMoNeuRaL Reinforce

Correcting the record first, because a previous brief got it wrong and sent an agent hunting
a build system that never existed: the engine is `backend/apps/studio/plugins/reinforce/`, **35 Python
files** (the `symoneural/` package itself is 4,090 lines; the rest is `bench/`, `tests/` and
`scripts/`), moved there in `9b5da84`. There is **no `symoneural_reinforce/`
directory, no `.cu` file and no `CMakeLists.txt`** — kernels are C++ source strings in
`symoneural/compute/kernels.py` compiled through NVRTC at runtime by
`symoneural/compute/program.py`.

Four patterns there are directly what a QLoRA surface is missing.

### 2.1 A registry with residency planning — the model picker's real shape

`symoneural/agents/registry.py` is the closest thing in this repo to what the owner is
asking for. It declares tiers with a VRAM cost each (`TIER_VRAM`, `:49-54`), and
`plan_residency(free_bytes)` / `resident_budget(free_bytes, kv_reserve_fraction=0.35)`
(`:237-289`) decide what actually fits *before* anything is loaded.

Its docstring also supplies the budget figure this whole spec hangs on:

> *"This box has 15.9 GiB of VRAM, of which **~14.2 GiB is free in practice**."*
> — `backend/apps/studio/plugins/reinforce/symoneural/agents/registry.py:6-7`

Corroborated live: `nvidia-smi` reports 16,303 MiB total, 14,832 MiB free, 1,027 MiB already
used with nothing of ours running. **Budget against ~14.2 GiB, never the 15.92 GiB
nameplate.** Budgeting against nameplate is how you OOM at step 0.

**Take:** a `MODELS` registry keyed by base model, each row carrying a derived VRAM cost, and
a `plan_fit(preset, model, free_bytes)` that runs before a single weight is read.

### 2.2 `CapabilityWaived` → HTTP 501 — the right answer to "won't fit"

`symoneural/core/errors.py` defines `CapabilityWaived` as deliberately **not** a subclass of
`DeviceError`, on the reasoning that *"'cannot run here' never masquerades as 'broken'"*, and
`server/app.py` surfaces it as **501, not 500**.

**Take:** picking a 14B at rank 64 and seq 2048 on this card is not an error, it is a
capability this box does not have. The preflight should return 501 with the arithmetic that
proves it, not let CUDA OOM at step 0 and return 500.

### 2.3 `/health` and `/stats` telemetry — the shape a training run needs

`server/schemas.py` `StatsResponse` returns allocator, memory-pool, queue and graph stats plus
`kernel_compiles` and `queue_depth`. `DeviceResponse` carries `free_memory_gib`,
`pcie_bound`, `overlap_profitable` — policy facts, not decoration.

**Take:** `GET /api/train/status` returns `{step, total_steps, epoch, train_loss, val_loss,
peak_vram_bytes, elapsed_s, eta_s, holder}`. Every field a real reading, per the no-decorative-
indicators rule. A progress bar with no `total_steps` behind it is the dishonest pixel that
rule exists to prevent.

### 2.4 Constraints encoded in code, each guarded by a regression test

`tests/test_constraints.py` guards four hardware gotchas found by audit — the green-context
`8,8` split, the two NVRTC include dirs, the MPI launcher, the P2P waiver. The README's
framing is the one to copy: *"measured, never computed."*

**Take:** the VRAM fit table in §4 is arithmetic until a test asserts the measured peak
against it. That test is a deliverable, not a nicety.

### 2.5 What NOT to take from Reinforce

- **Its own FastAPI app on port 8000.** `.claude/CLAUDE.md` is explicit that FastAPI does all
  the routing and `api.py` mounts `site/` last. The QLoRA surface must be an `APIRouter`
  mounted into `backend/server.py`, exactly as `apps/streamer` is at `api.py:1888`. A second origin
  breaks `console.js`'s WebSocket-with-polling-fallback.
- **Its licensing/checkpoint-sealing subsystem.** Out of scope, and `backend/studio/docs/symon-ml-review.md`
  §3 already argues client-side DRM has a structural ceiling.
- **Its NVRTC/kernel layer.** QLoRA runs on torch + bitsandbytes. Nothing here needs a
  hand-written kernel.

### 2.6 On `backend/hardware/docs/cuda-audit.md`

Read as instructed. Its §1.1 finding is **independently verified here**:
`symoneural/core/context.py:149` reads

```python
multiprocessor_count=int(_attr(p, "multiprocessor_count")),
```

— the only `_attr` call in that function without an explicit `default=`, while every
neighbouring call guards itself. `_attr` defaults to `0`, so a property-name mismatch yields
zero SMs silently. Already corroborated in `ops/backend/authority/docs/README.md`.

That audit's §5 honest-labelling allegations are **noted and not acted on** here, per
instruction. They touch the argument the whole site rests on and deserve their own careful
pass; nothing in this spec depends on them.

---

## 3. What the reference trees actually contain

Several reference trees in this repo have turned out to be empty or misidentified, so each
was opened rather than trusted by name.

### 3.1 Not present — do not plan around them

**`references/` contains no axolotl, no unsloth, no LLaMA-Factory, no
text-generation-webui, and no LM Studio capture.** Searched by name to depth 3 across all
eleven trees. If the owner believes one of those is on the box, it is not.

### 3.2 `references/Nemotron-main/use-case-examples/sql-lora-finetuning-and-deployment` — real, but thin

108 KB: a README, two notebooks, `bird_sql/` dataset helpers, and `finetune.py` — which is
**40 lines**, all of them boilerplate around
`TrainFinetuneRecipeForNextTokenPrediction(cfg)` from `nemo_automodel`, driven by
`bird_peft_nemotron_nano.yaml`. It targets **Nemotron-3-Nano-30B on 2 GPUs** and deploys via
NIM/vLLM. Neither the model nor the topology is reachable on this box.

**The citable idea is structural, not numeric: the run is a config file, and the entry point
is thirty lines.** That is exactly the shape a preset system wants — a named YAML/JSON per
profile, one runner. Do not lift hyperparameters from it; they are for a 30B on two cards.

### 3.3 `references/skills/skills/tao-finetune-huggingface-model` — real, and the most useful thing here

NVIDIA TAO, Apache-2.0, 20 curated reference documents. Three of them are literally the
patterns this spec proposes:

- **`references/model-discovery.md`** — a `model_type` → AutoModel-class mapping with explicit
  **rejection criteria** and a "config fields to extract" list. This is a model picker's
  validation layer written out.
- **`references/workflow-intake-preflight.md`** — hardware audit before training, free-disk
  soft-warn, presence-only credential checks (`[ -n "$HF_TOKEN" ]`, value never read), and a
  loadability probe that catches gated/script-based/missing models *before* the run starts.
  Line 64 gives its defaults: `n_epochs=3`, `lora_r=16`.
- **`references/error-playbook.md`** — two rows worth encoding:
  - `:48` — *"LoRA reports 5-10% trainable (expected **0.1-1%**) → target regex too broad."*
  - `:52` — *"OOM at step 0 → halve `per_device_train_batch_size`, double
    `gradient_accumulation_steps`, enable `gradient_checkpointing`."*

`SKILL.md`'s six-step workflow — inspect & qualify, hardware audit, research, **generate and
smoke**, train + eval + infer, push — supplies the "smoke test before scale-up" step that
becomes the first preset in §5. Its stated order of authority (user input > live research >
curated references > model memory) is a good rule for a preset system too.

`references/vlm-scripts.md:77-93` gives a concrete LoRA config: `lora_r: 16`,
`lora_alpha: 32`, `learning_rate: 2.0e-4`, target modules
`q_proj|k_proj|v_proj|o_proj|gate_proj|up_proj|down_proj` — the same seven this repo already
uses, arrived at independently.

**Caveat to record:** the skill's own compatibility line requires *"≥ 24 GB VRAM for ≤3B
models"* and a docker + NGC container path. Neither applies here. Take its **method** —
preflight, rejection criteria, error playbook, smoke-first — and none of its thresholds.

### 3.4 `references/stable-diffusion-webui-master` — real, and it is the "studio" to learn from *and* to resist

The model picker is one dropdown wired to a directory scan:
`modules/shared_options.py:171` binds `sd_model_checkpoint` to a `gr.Dropdown` whose choices
come from `list_checkpoint_tiles()`, backed by `modules/sd_models.py:153 list_models()` →
`checkpoints_list` of `CheckpointInfo` objects, with `get_closet_checkpoint_match()` for
fuzzy resolution and a `refresh=` hook. **That is the whole pattern, and it is about 40 lines
of real logic.** It is worth copying.

Everything around it is what the owner said no to — see §9.

### 3.5 Also present but not applicable

`references/skills/` carries `tao-finetune-clip`, `tao-finetune-cosmos-reason`,
`nemotron-asr-finetune`, `digital-health-clinical-asr-finetune`, `nv-*-finetune` and the
`earth2studio-*` family. All real; all domain-specific (CV, ASR, medical imaging, weather).
The `earth2studio-*` skills are a weather forecasting toolkit and are **not** the "studio" the
owner meant. `references/Projects_Crypto` (5.4 GB) is Antminer firmware and is unrelated.

---

## 4. The model picker

### 4.1 What is actually on this box

| File | Size on disk | Format | Fine-tunable with peft + bitsandbytes? |
|---|---|---|---|
| `models/hf/hub/models--Qwen--Qwen2.5-7B-Instruct` | 14.2 GiB (`total_size` 15,231,233,024 B) | HF safetensors, bf16, 4 shards | **Yes — the only one** |
| `models/llm/symon-1.0-7b-q4_k_m.gguf` | 4.36 GiB | GGUF Q4_K_M | No |
| `models/llm/symon-1.0-14b-q4_k_m.gguf` | 8.37 GiB | GGUF Q4_K_M | No |
| `models/llm/symon-1.0-draft-0.5b-q4_k_m.gguf` | 0.37 GiB | GGUF Q4_K_M | No |
| `models/image/*` (FLUX.1-schnell, ae, clip_l, t5xxl) | 11.8 GiB | GGUF + safetensors | No — diffusion, different surface |
| `training/adapter/adapter_model.safetensors` | 154 MiB | PEFT LoRA, fp32 | output, not a base |

**GGUF is not a training format for this stack.** `transformers`/`peft`/`bitsandbytes`
require HF-format safetensors plus a `config.json`; a GGUF Q4_K_M file has neither a torch
state dict nor the module structure `LoraConfig(target_modules=[...])` names. llama.cpp can
*serve* a GGUF LoRA — that is why `train_lora.py` converts its output — but it cannot produce
one.

So: **a picker built today over what is on disk has exactly one entry.** A dropdown with one
item is a UI that lies about choice. The picker is only honest if it also offers
fetch-on-demand.

Note also that `scripts/fetch-models.sh` fetches **no safetensors at all** — only GGUFs and
licence files. The 14.2 GiB HF cache arrived as a side effect of the single training run, via
the `HF_HOME` line that no longer resolves (§1.5.1). Nothing in the repo would recreate it.

### 4.2 The VRAM arithmetic

**Budget: ~14.2 GiB free in practice**, not 15.92 GiB nameplate (§2.1). Everything below is
GiB; mixing GB and GiB is precisely the kind of slip this repo catches.

Four terms, and the second is the one everyone forgets:

```
weights = quantised_linear_params × 4.127 bits / 8      # 4-bit NF4 + double quant
        + resident_bf16_params    × 2 bytes             # embeddings + lm_head + norms + biases
trainable = lora_params × (4 fp32 weight + 4 fp32 grad + 2 adamw-8bit state) bytes
overhead  = CUDA context + cuBLAS workspace + fragmentation
activations = f(seq_len, batch, gradient_checkpointing)
```

- **4.127 bits/param** is the QLoRA paper's own figure for NF4 with double quantisation —
  4 bits plus ~0.127 bits/param of quantisation constants (Dettmers et al., *QLoRA*,
  arXiv:2305.14314, §3 "Double Quantization"). **Vendor/published spec, not measured here.**
- **Embeddings and `lm_head` do not get quantised.** `nn.Embedding` is not a `Linear4bit`,
  and bitsandbytes skips `lm_head` by default. With a 152,064-token vocab and
  `"tie_word_embeddings": false` in the local `config.json`, that is **1.09B of 7.62B params
  staying at bf16** — 2.03 GiB that a naive `params × 0.5 bytes` estimate throws away.

**Derivation for Qwen2.5-7B-Instruct**, from the local `config.json` (hidden 3584, 28 layers,
FFN 18944, 28 heads, 4 KV heads → head_dim 128, KV width 512) and cross-checked against
`model.safetensors.index.json`:

```
per-layer linear   = 3584² (q) + 3584·512 (k) + 3584·512 (v) + 3584² (o)
                   + 3584·18944 × 3 (gate, up, down)         = 233,046,016
× 28 layers                                                   = 6,525,288,448
embed_tokens + lm_head = 152,064 × 3,584 × 2                  = 1,089,994,752
norms + qkv biases                                            =       333,312
                                                        total = 7,615,616,512
```

The index file's `total_size` is 15,231,233,024 bytes ÷ 2 = **7,615,616,512** — the
derivation lands on the file byte-for-byte, so the split between quantised and resident is
trustworthy.

The adapter arithmetic checks out the same way. `r=16` on those seven modules across 28
layers gives **40,370,176** trainable params; ×4 bytes = 161,480,704, and
`adapter_model.safetensors` on disk is **161,533,192** bytes — the 52 KB difference is the
safetensors header. fp32 confirmed. `symoneural-lora.gguf` is 80,767,680 = ×2 + 27 KB header,
so f16. **Derived, and corroborated by on-disk size.**

Trainable fraction: 40,370,176 / 7,615,616,512 = **0.53%** — inside TAO's stated 0.1–1% band
(`error-playbook.md:48`), so the target-module list is not over-broad.

### 4.3 The three candidates

All figures **projected** — arithmetic from architecture metadata, not a measurement. §6 says
what must be measured before any of it is published.

| | Qwen2.5-**0.5B** | Qwen2.5-**7B** | Qwen2.5-**14B** |
|---|---|---|---|
| source of shape | GGUF KV metadata | local `config.json` + index | GGUF KV metadata |
| layers / hidden / FFN | 24 / 896 / 4864 | 28 / 3584 / 18944 | 48 / 5120 / 13824 |
| heads / KV heads | 14 / 2 | 28 / 4 | 40 / 8 |
| total params | ~0.49B | 7.616B | ~14.77B |
| 4-bit linear params | 0.358B | 6.525B | 13.212B |
| → NF4 @ 4.127 b/p | 0.17 GiB | **3.14 GiB** | **6.35 GiB** |
| bf16-resident params | 0.136B (tied) [^tie] | 1.090B | 1.557B |
| → bf16 @ 2 B/p | 0.25 GiB | **2.03 GiB** | **2.90 GiB** |
| **weights subtotal** | **~0.43 GiB** | **~5.17 GiB** | **~9.25 GiB** |
| LoRA params @ r=16 | 4.6M | 40.4M | 68.8M |
| → fp32 w + fp32 grad + 8-bit adam | 0.04 GiB | 0.38 GiB | 0.64 GiB |
| CUDA ctx + workspace (est.) | ~0.5 GiB | ~0.5 GiB | ~0.5 GiB |
| activations, bs1 seq1024 + ckpt (est.) | ~0.2 GiB | ~0.5–1.5 GiB | ~0.5–1.5 GiB |
| **projected peak** | **~1.2 GiB** | **~6.5–7.5 GiB** | **~10.9–11.9 GiB** |
| **of a 14.2 GiB budget** | trivial | **comfortable** | **no margin for error** |
| HF safetensors on box? | **No** (~1 GB fetch) | **Yes** | **No** (~27.5 GiB fetch) |

[^tie]: GGUF KV metadata does not expose `tie_word_embeddings`, so tying was read off the
tensor list instead: the 0.5B file carries `token_embd.weight` and **no** `output.weight`
(290 tensors) — tied. The 14B carries both (579 tensors) — untied, so its `lm_head` is
counted separately above. The 7B's local `config.json` states `"tie_word_embeddings": false`
directly. All three verified against the files on this box.

Disk is not the constraint: `/home` has 884 GB free.

The verdict the picker should encode, and it matches the manual's own Playbook 04 status note
(*"QLoRA on a 7–8B model is comfortable; 13–14B is tight but feasible with gradient
checkpointing and a small batch"*):

- **0.5B** — smoke tests and pipeline validation. Not a product model.
- **7B** — the workhorse. This is the one that has actually been trained here.
- **14B** — feasible at r≤16, batch 1, seq ≤1024, gradient checkpointing **mandatory**. At
  r=32, or seq 2048, or batch 2, the preflight should refuse with 501 and show the sum.

### 4.4 The picker's behaviour

1. **Scan, don't hardcode.** Enumerate directories under the HF cache that contain a
   `config.json` — the `list_models()` pattern from sd-webui (§3.4), with a `refresh` hook.
2. **Qualify each candidate** before offering it, per TAO `model-discovery.md`: read
   `model_type`, `num_hidden_layers`, `hidden_size`, `vocab_size`, `tie_word_embeddings`;
   reject anything that is not a causal LM; reject GGUF with a message that says *why*, not
   just "unsupported".
3. **Derive the VRAM row from the config**, not from a lookup table. The arithmetic in §4.2
   is mechanical; a hardcoded table goes stale the first time someone adds a model.
4. **Preflight before load**, `plan_residency`-shaped (§2.1): `free_bytes` from
   `cuMemGetInfo`, minus projected peak, against the chosen preset. Not fitting raises
   `CapabilityWaived` → **501** with the sum shown.
5. **Fetch-on-demand, explicitly.** Offering a model not on disk must state the download size
   up front (~27.5 GiB for the 14B) and write into `models/hf`. Which means fixing
   `HF_HOME` (§1.5.1) is a prerequisite, not a follow-up.
6. **Never enumerate `training/*.jsonl`.** See §8.

---

## 5. Preset tuning profiles

Four profiles. Named for what they do, not for their rank.

**Provenance is stated per value and no value is labelled `measured`.** Nothing about
training quality or throughput has ever been measured on this box (§1.5.2, §1.4), so
`measured` would be a lie. The three legitimate labels here are:

- **published spec** — QLoRA paper, peft/transformers defaults
- **repo manual** — `frontend/site/docs/symoneural-manual.md` Playbook 04
- **as-shipped here** — what `train_lora.py` currently does, unvalidated

Shared across every preset, because the hardware decides them:
4-bit **NF4** + double quantisation, bf16 compute dtype *(published spec — QLoRA §3)*;
`bf16=True`; `gradient_checkpointing=True` *(repo manual: mandatory at 7B+ on 16 GiB)*;
`optim="paged_adamw_8bit"` *(published spec — QLoRA's paged optimizers, and what avoids an
allocator spike on a card with no headroom)*; `lora_dropout=0.05` *(published spec — peft's
common default; also `train_lora.py:105`)*; `bias="none"`; **warmup expressed in steps, never
`warmup_ratio`** *(measured: absent from transformers 5.15.0 — §1.5.4)*.

### 5.1 The profiles

| | **Smoke** | **Voice** | **Recall** | **Long-form** |
|---|---|---|---|---|
| **when it is right** | Prove the pipeline runs end-to-end before spending an hour | Teach style, persona, refusals — behaviour, not facts | Absorb domain vocabulary and facts the base does not know | Documents longer than a chat turn: manuals, transcripts, logs |
| base model | **7B** (or 0.5B once fetched) [^smoke] | 7B | 7B | 7B |
| examples used | first 32 | all | all | all |
| epochs | 1 | 3 | 2 | 2 |
| rank `r` | 8 | 16 | 32 | 16 |
| `lora_alpha` | 16 | 32 | 64 | 32 |
| target modules | q,v only | the seven [^alllinear] | the seven [^alllinear] | the seven [^alllinear] |
| learning rate | 2e-4 | 1e-4 | 2e-4 | 1e-4 |
| scheduler | cosine | cosine | cosine | cosine |
| `max_length` | 512 | 1024 | 1024 | **2048** |
| batch × grad-accum | 1 × 4 (eff. 4) | 1 × 16 (eff. 16) | 1 × 16 (eff. 16) | 1 × 8 (eff. 8) |
| val split | 10% | 10% | 10% | 10% |
| `save_strategy` | no | epoch | epoch | epoch |
| projected peak VRAM | ~6 GiB (7B) / ~1.2 GiB (0.5B) | ~6.5–7.5 GiB | ~7.5–8.5 GiB | ~8.5–10 GiB |

[^alllinear]: **`"all-linear"` and the explicit seven are the same set on Qwen2 — do not offer
both.** Verified by instantiating `Qwen2ForCausalLM` from the local `config.json` on the meta
device and listing `nn.Linear` leaves: a `Qwen2DecoderLayer` contains exactly seven
(`q,k,v,o,gate,up,down`), and the only other `nn.Linear` in the model is `lm_head`, which
peft's `all-linear` shorthand excludes by design. So the manual's *"`all-linear` — modern
default"* and `train_lora.py:110-111`'s hand-enumerated list are two spellings of one thing.
A preset that advertised "more module coverage" would be a knob that does nothing, and a user
would burn a run finding that out. **Rank is what separates Voice from Recall, not coverage** —
which is consistent with the arithmetic in §5.2, where r=32 gives exactly 2× the r=16 param
count over the same modules. Use the explicit list, because it is readable in a run manifest
and it survives a peft change of heart about what `all-linear` means.

[^smoke]: Smoke's speed comes from 1 epoch × 32 examples × r=8 × seq 512, **not** from a
smaller base — so it should default to the 7B, which is the only base actually on this box
(§4.1). Defaulting it to the 0.5B would gate the fastest-feedback preset behind a ~1 GB
download *and* behind the `HF_HOME` fix (§10 step 1), which is precisely backwards for a
preset whose job is to fail fast. Offer the 0.5B once fetched, for the case where even a 7B
load is too slow to iterate against.

### 5.2 Where each number comes from

- **`r=16`, `lora_alpha=32`, `dropout=0.05`** — the most-cited QLoRA/peft configuration.
  Appears three times independently in this repo's own sources: `train_lora.py:102-105`,
  `frontend/site/docs/symoneural-manual.md` Playbook 04 (`r=16, lora_alpha=32, lora_dropout=0.05`), and
  TAO `references/vlm-scripts.md:77-78`. TAO's preflight defaults agree
  (`workflow-intake-preflight.md:64` — `n_epochs=3, lora_r=16`). *published spec + repo manual.*
- **`alpha = 2r`** — the scaling convention (`train_lora.py:104` computes it that way).
  Keeping the ratio fixed is what makes rank the single knob it appears to be. *convention.*
- **`lr` 1e-4 to 3e-4** — the manual states the priority order outright: *"data quality >
  learning rate (1e-4–3e-4) > epochs (1-3; watch val loss) > rank r (8-32). Everything else
  is noise at this scale."* Every learning rate and epoch count above sits inside those
  bands. 2e-4 specifically is the manual's snippet value and TAO
  `vlm-scripts.md:93`. 1e-4 is `train_lora.py:52`. *repo manual + as-shipped here.*
- **Effective batch 16** — the manual's snippet targets it (bs 2 × ga 8). On this card batch
  must stay at 1, so it is reached as 1 × 16. Note this **changes** the shipped effective
  batch of 8 (`train_lora.py:123`). *repo manual.*
- **`target_modules` = the seven** — `train_lora.py:110-111`, with the reason given in the
  docstring: *"Attention-only adapters pick up style but are noticeably worse at absorbing
  facts."* That reason is exactly why **Smoke** targets q,v only: it is not trying to learn
  anything, it is trying to finish. Every other preset uses all seven, because on Qwen2 there
  is no larger set to escalate to — see the footnote above. *as-shipped here + repo manual.*
- **`r=32` for Recall** — top of the manual's stated 8–32 band, chosen for the case the
  manual says rank matters for. Trainable params roughly double to ~81M; still ~1.06% of
  7.62B, at the edge of TAO's 0.1–1% band (`error-playbook.md:48`) — worth flagging in the UI,
  not worth refusing.
- **`r=8` for Smoke** — bottom of the same band; the point is speed, not quality.
- **10% validation split** — `frontend/site/docs/symoneural-manual.md` Playbook 04 Stage 1: *"Hold out
  5-10% as a validation set BEFORE looking at training loss."* Not currently done (§1.5.2).
  *repo manual.*
- **`max_length=2048` for Long-form** — the manual's snippet value; also `SFTConfig`'s
  `max_length` default is 1024, so 2048 is an explicit choice. Qwen2.5 supports 32,768
  context (`config.json`), so 2048 is a VRAM decision, not a model limit. *repo manual.*
- **Projected peak VRAM** — §4.2 arithmetic. **Projected. Must be measured before publication.**

### 5.3 Two implementation notes the presets imply

- **Move to `trl`'s `SFTTrainer`/`SFTConfig` — but not for the masking.** trl is installed and
  unused, and the manual's own Playbook 04 uses it, so the move is right for the val split,
  eval strategy and packing. `SFTConfig` also carries **`assistant_only_loss`**, which looks
  like a drop-in replacement for the `-100` masking `train_lora.py:74-85` hand-rolls — **it is
  not, on this model.** That flag requires the chat template to emit `{% generation %}`
  markers so trl can find the assistant span. Checked: `training/adapter/chat_template.jinja`
  (the stock Qwen2.5 template) contains **zero** `{% generation %}` blocks — its only match
  for "generation" is `{%- if add_generation_prompt %}` at line 52, which is a different
  mechanism entirely. So `assistant_only_loss=True` would fail against this template rather
  than silently mis-mask, which is the good failure, but it still means:
  **the hand-rolled masking is a workaround for a real gap, not legacy cruft.** Keep it, or
  patch the template to add generation markers and verify the resulting label mask is
  byte-identical first. Do not treat this as a cleanup.
- **Encode the OOM ladder rather than crashing.** TAO `error-playbook.md:52`: halve batch,
  double grad-accum, enable checkpointing. Batch is already 1 and checkpointing already on, so
  on this box the only remaining rungs are *lower rank*, *shorter seq*, *smaller base*. The
  preflight should say which rung it is offering, in those words.

### 5.4 Deliberately not in v1: preference tuning

`trl 1.10.0` ships `DPOTrainer`, `GRPOTrainer`, `KTOTrainer`, `RewardTrainer`. DPO needs a
reference model resident alongside the policy — on 4-bit that is achievable by disabling the
adapter rather than loading twice, but it is a second design problem and it needs *paired
preference data*, which does not exist here. The manual lists DPO under Playbook 04; this
spec explicitly defers it. Say so in the UI rather than showing a greyed-out tab.

---

## 6. What must be measured before any figure reaches the site

`.claude/CLAUDE.md`: *"Label every figure: **measured** on this machine, **vendor**
specification, or **projected** arithmetic. Never present a projection as a result."*

Every number in §4.3 and §5.1 is **projected**. Nothing about QLoRA on this box has been
measured — one adapter exists, produced by an unlogged run with no eval.

| Figure | How to measure | Label until then |
|---|---|---|
| Peak VRAM per (model × preset) | `torch.cuda.max_memory_allocated()` + `max_memory_reserved()` at run end; compare against `nvidia-smi` peak | projected |
| Wall-clock per epoch, tok/s | Trainer timing, and a governor acquire→release pair that is actually **paired** (§1.4) | **unmeasured** — do not quote the existing log |
| Train / val loss curves | Requires the val split that does not yet exist (§1.5.2) | does not exist |
| Whether the adapter improves anything | A held-out eval — the refusal behaviour is the one that matters most, since CLAUDE.md says the pricing refusal is *trained in, not prompted* | **entirely unmeasured** |
| Trainable-param % per preset | `model.print_trainable_parameters()` — already called at `train_lora.py:113`, just never recorded | derived (0.53% at r=16 confirmed by file size) |
| 14B feasibility | One run. It either completes or OOMs; there is no third answer | projected |
| Model-load time from cold cache | Time `from_pretrained` under the governor | unmeasured |
| Governor queue impact on serving | Wall-clock a `/api/chat` request issued while `train` holds the card | unmeasured |

Rule to carry into the page: **the site may publish that a 7B QLoRA fits in 15.92 GiB and
show the arithmetic, labelled projected. It may not publish a tok/s, an epoch time, or a
quality claim until the run above has been done.** "Publish the numbers, keep the methods"
still applies — a peak-VRAM figure and an epoch time give nothing away; the corpus does.

Add a frontend assertion to `node tests/frontend.mjs` when the page lands, per the repo rule
that every frontend fix earns an assertion.

---

## 7. The honest constraint section — what one 16 GiB consumer card cannot do

This belongs on the page, not just in the spec. The site publishes its negative results
deliberately (the PCIe Gen 3 ×8 ceiling, the failed multi-stream overlap); these are the same
class of finding.

1. **No full fine-tuning, of anything.** 7.616B params under AdamW needs weights + gradients +
   two optimizer moments. At fp32 that is 16 bytes/param = **~113 GiB**; bf16 mixed precision
   with an fp32 master copy lands in the same place. Against a 14.2 GiB budget the shortfall
   is roughly **8×**. The manual's *"~80+ GB"* is the same claim under a more forgiving
   accounting. QLoRA is not a cost optimisation here — it is the only thing that makes a 7B
   trainable on this box at all.

2. **No model above ~14B, at any rank.** A 32B in 4-bit is ~16 GiB of weights before a single
   gradient exists — over budget with the optimizer at zero. 70B is not close. Lowering rank
   does not help: rank governs the *adapter*, and the adapter is 0.4 GiB of an 11 GiB problem.

3. **No 14B with comfort.** ~10.9–11.9 GiB projected against 14.2 GiB is a 2–3 GiB margin
   covering activations, fragmentation and whatever else touches the card. Bump seq to 2048,
   rank to 32, or batch to 2 and it OOMs. This should be offered with the arithmetic visible,
   not hidden behind a spinner.

4. **No training while serving.** This is architectural, not a limitation to engineer away.
   The governor serialises the card; `.claude/CLAUDE.md` says `train` is never evicted; a
   fine-tune therefore locks chat, image and remix out **for its entire duration**, and the
   log already shows two `REFUSING to evict` events (§1.4). A "start training" button is a
   button that takes the whole rack offline. Say that on the page, next to the button.

5. **Therefore: no unauthenticated training route.** A world-callable, never-evicted,
   long-running GPU route is a rack-wide denial of service that costs one HTTP request.
   `.claude/HANDOVER.md` §5 item 12 already notes `/api/chat` is open to whatever reaches the
   origin. The in-repo pattern to copy is the ASIC gate —
   `SYMONEURAL_ASIC_ENABLED` + `SYMONEURAL_ASIC_TOKEN` in `backend/apps/asicminer/__init__.py`, off by
   default. This is a hard requirement, not a hardening task for later.

6. **No multi-GPU anything.** One card. No FSDP, no DeepSpeed ZeRO-3, no tensor parallelism,
   no NVLink — `tools/build/build_stack.py:110` already records the last of these. Reinforce's P2P
   test is *waived*, not failed, for the same reason, and that is the right vocabulary here
   too: cannot-here, not broken.

7. **CPU offload is not a rescue.** ZeRO-style optimizer offload crosses PCIe, and this host
   is capped at **Gen 3 ×8, ~7 GB/s measured** (`backend/apps/studio/plugins/reinforce/.../registry.py:21-27`,
   and the ×8 ceiling is already published on the site). Offloading optimizer state per step
   over a link that slow converts a VRAM problem into a wall-clock one. *(That specific
   throughput figure is among those `cuda-audit.md` §4.3 questions — it alleges the published
   H2D number was taken on a path the serving code does not use. Flagged, not adjudicated,
   per §2.6; the conclusion here survives at any plausible Gen 3 ×8 value, because the
   argument is about an order of magnitude, not a constant.)*

8. **No interactive iteration on a big model.** Even at 7B, changing a hyperparameter means
   re-running from scratch — there is no warm-start, and the rack is locked meanwhile. The
   **Smoke** preset exists precisely because the feedback loop is otherwise measured in tens
   of minutes.

9. **No serving the adapter you just trained without a conversion step.** The trainer emits
   PEFT safetensors; the chat surface loads `symoneural-lora.gguf`. `convert_lora_to_gguf.py`
   is a manual step (`train_lora.py:143`) and nothing automates it. A UI that says "trained"
   while chat still runs the old adapter is a dishonest status.

---

## 8. Trade-secret guard — non-negotiable, and easy to violate by accident

`.claude/CLAUDE.md` names two artefacts protected only by not being public:
`training/corpus.jsonl` and `training/build_dataset.py`. Trade secret survives only while
reasonable measures are taken; once out, it cannot be pulled back. This spec quotes neither.

A surface where a user picks a dataset is the single most likely way to leak them, because
the obvious implementation — enumerate `training/*.jsonl` into a dropdown — publishes the
corpus. Binding rules for anything built from this spec:

- The dataset picker **never lists, previews, counts by kind, reads or serves**
  `training/corpus.jsonl` or `training/build_dataset.py`. Not as a default, not as an example,
  not greyed out.
- The default dataset is **user-supplied upload**. There is no "use the SyMoNeuRaL corpus"
  option in any UI reachable from the web.
- **No route returns dataset contents**, including error messages. A validation failure
  reports *line 41: missing "messages" key*, never the line.
- Uploads land in a path that `scripts/deploy.sh` does not copy. Renders already learned this
  lesson — 19 unreferenced PNGs sat in the public webroot until the backend restructure moved
  them to `backend/output/`. A corpus in `site/` would be worse by orders of magnitude.
- The `.claude/CLAUDE.md` warning applies literally here: *"An agent asked to 'publish the
  manual' could reasonably mistake the corpus for documentation."* An agent asked to "add a
  dataset picker" will make the same mistake unless the code says no in a comment at the
  enumeration site.

The reconciliation with the site's transparency argument is unchanged: **publish the numbers,
keep the methods.** VRAM arithmetic, peak memory, epoch time and the preset table are all
publishable and give nothing away. The corpus is the product.

---

## 9. What is deliberately NOT taken from "studio"

The owner was explicit: *"just not with all the apps in studio as it was before."*
`references/stable-diffusion-webui-master` is the studio in question, and the split is clean.

**Taken:** the model dropdown backed by a directory scan with a refresh hook
(`sd_models.py:153`), the `CheckpointInfo` record so a model is an object with a title, a hash
and a path rather than a filename string, and fuzzy resolution
(`get_closet_checkpoint_match`) so a saved preset that names a model still resolves after a
rename.

**Not taken, and why:**

| Left out | Why |
|---|---|
| The extension system — `canvas-zoom-and-pan`, `hypertile`, `LDSR`, `ScuNET`, `SwinIR`, `soft-inpainting`, `mobile`, `prompt-bracket-checker`, `postprocessing-for-training`, … | This is the "all the apps" the owner rejected. Each is a tab that dilutes the one job. |
| The scripts drawer — `xyz_grid`, `loopback`, `outpainting_mk_2`, `prompt_matrix`, `custom_code`, … | Plugin sprawl. `custom_code.py` in particular executes user-supplied Python — an obvious non-starter on a box that holds a trade-secret corpus. |
| A model zoo / downloader browser | The picker offers what is on disk plus a named fetch. Browsing a hub from inside the surface is a second product. |
| A settings page with hundreds of options | The presets **are** the settings. A preset system that also exposes every knob is just a settings page with extra steps. |
| Gradio | The site is hand-written HTML + `console.js` against a FastAPI origin, and CLAUDE.md fixes that architecture. Gradio brings its own server and its own origin. |

**The principle:** a studio's model picker is good because it is one control that always
reflects the truth on disk. A studio's app drawer is bad here because this surface has exactly
one job — turn a corpus into an adapter — and every tab added to it is a tab arguing that it
does not.

The same restraint applies to what is taken from Reinforce (§2.5): its registry and its
waiver semantics, not its server, its licensing subsystem or its kernel layer.

---

## 10. Implementation shape, in dependency order

Not a schedule. This is what has to be true before the next thing can be.

1. **Fix `HF_HOME`** in `train_lora.py` (§1.5.1) and add the `assert` that
   `tools/build/build_training.py:33` already models. Nothing else works until the cache resolves.
2. **Extract the run config into a dataclass/JSON**, one file per preset, `train_lora.py`
   reduced to a runner. The Nemotron shape (§3.2): the run *is* a config file.
3. **Add val split, `save_strategy="epoch"`, a seed, and a written run manifest** beside the
   adapter, replacing the PEFT stub README. Without this nothing downstream can be measured.
4. **Move to `SFTTrainer` + `assistant_only_loss`** (§5.3), verifying the label mask is
   identical first.
5. **Model registry + preflight**, `plan_residency`-shaped, `CapabilityWaived` → 501 (§2.1,
   §2.2, §4.4).
6. **`backend/apps/qlora/` as an `APIRouter`**, mounted in `backend/server.py` beside `tuner`
   (`api.py:1888`), token-gated on the ASIC pattern (§7.5). Routes:
   `GET /api/train/models`, `GET /api/train/presets`, `POST /api/train/preflight`,
   `POST /api/train/start`, `GET /api/train/status`, `POST /api/train/stop`.
7. **The surface acquires the governor lock itself** as `train` — `gpu-governor.sh with train
   -- …` so it always releases, and **never a bare `release`** (§1.4).
8. **Measure everything in §6.** Only now do numbers exist.
9. **The page.** A generator, `tools/build_qlora.py`, writing into `site/`. That means: the
   BEGIN/END marker contract, idempotence, run twice and `diff` before committing, and no
   `text-overflow:ellipsis` anywhere near the model attribution — `built on
   Qwen2.5-7B-Instruct` is an Apache-2.0 licence condition, and the rack has already been
   caught truncating it. Repoint the `train` unit's `href` off `/training.html`.
10. **Frontend assertion** in `tests/frontend.mjs`.

Steps 1–4 are pure `training/` work and touch no file another agent writes. Step 9 rewrites
`site/`, which per CLAUDE.md is the one directory two writers will clobber — it cannot run
concurrently with the other page generators.

---

## 11. What this spec does not decide

- Whether the training run should be a subprocess or an in-process thread. Subprocess is
  safer (a crashed fine-tune cannot take the API with it) and matches how the governor's
  `with` form works; in-process gives live loss without parsing stdout. Not resolved here.
- How the adapter reaches the chat surface — the GGUF conversion is manual today (§7.9), and
  hot-swapping an adapter under `llama-server` is a serving question, not a training one.
- Whether uploaded datasets persist between runs, and who may read them. This is a
  multi-tenancy question the rest of the site has not had to answer yet.
- Anything in `backend/hardware/docs/cuda-audit.md` §5. Noted, untouched (§2.6).
