# Playbook 04 — Fine-Tuning Specialists

> Part of the [symoneural_reinforce documentation set](README.md). Sliced from the consolidated manual at `../../../../../frontend/site/docs/symoneural-manual.md`, which remains the canonical single file.

[< Playbook 03 — Inference Engines Shootout](playbook-03.md)

## Playbook 04 — Fine-Tuning Specialists
#### LoRA, QLoRA, and preference tuning: turning a small generalist into an expert on YOUR task

The cheat code of local AI: a 3B model fine-tuned on your exact task routinely beats a 70B generalist *at that task*. This lab takes you from raw data to a merged, quantized specialist you can serve with the engines from Playbook 03.

---

### Stage 0 — When to fine-tune (and when not to)

Fine-tune when you need: consistent format/style, a narrow skill done reliably, domain vocabulary, or behavior that survives without a giant prompt.
Do NOT fine-tune for: injecting facts that change (use RAG, Playbook 08), one-off tasks (prompt harder), or fixing a model that's simply too small to reason about the task.

Rule: **RAG for knowledge, fine-tuning for behavior.**

---

### Stage 1 — Data is 80% of the outcome (the unglamorous stage)

Target: 500–5,000 examples in chat format. Quality beats quantity below ~10k.

```jsonl
{"messages": [{"role":"system","content":"You are a log-triage assistant."},{"role":"user","content":"<raw log>"},{"role":"assistant","content":"<ideal structured triage>"}]}
```

Sources, in order of value:
1. **Real examples you wrote/approved** — gold
2. **Teacher-generated** (Playbook 05) — a big model produces drafts, you filter
3. Public datasets in your domain — bronze, dedupe and filter hard

Hygiene checklist (do all of these, every time):
- Dedupe near-identical examples (`pip install datasketch` for MinHash, or embedding similarity)
- Hold out 5-10% as a validation set BEFORE looking at training loss
- Read 50 random examples yourself. If 5 are bad, your model will learn bad.
- Balance: if 90% of examples are one subtype, the model becomes that subtype.

**Deliverable:** `train.jsonl` + `val.jsonl` + a paragraph in your lab notebook on where the data came from and what you filtered.

---

### Stage 2 — QLoRA fine-tune (one evening, one consumer GPU)

Why QLoRA: full fine-tuning of even a 7B needs ~80+ GB. QLoRA freezes the model in 4-bit and trains tiny low-rank adapters — a 7-8B fits in ~10-12 GB.

```bash
pip install torch transformers peft trl bitsandbytes datasets
```

```python
from transformers import AutoModelForCausalLM, AutoTokenizer, BitsAndBytesConfig
from peft import LoraConfig
from trl import SFTTrainer, SFTConfig
from datasets import load_dataset
import torch

model_id = "Qwen/Qwen2.5-3B-Instruct"
bnb = BitsAndBytesConfig(load_in_4bit=True, bnb_4bit_quant_type="nf4",
                         bnb_4bit_compute_dtype=torch.bfloat16, bnb_4bit_use_double_quant=True)
model = AutoModelForCausalLM.from_pretrained(model_id, quantization_config=bnb, device_map="auto")
tok = AutoTokenizer.from_pretrained(model_id)

peft_cfg = LoraConfig(
    r=16, lora_alpha=32, lora_dropout=0.05,
    target_modules="all-linear",   # adapters on every linear layer — modern default
    task_type="CAUSAL_LM",
)

data = load_dataset("json", data_files={"train":"train.jsonl","val":"val.jsonl"})

trainer = SFTTrainer(
    model=model, peft_config=peft_cfg,
    train_dataset=data["train"], eval_dataset=data["val"],
    args=SFTConfig(
        output_dir="out-specialist",
        per_device_train_batch_size=2, gradient_accumulation_steps=8,  # effective batch 16
        num_train_epochs=2, learning_rate=2e-4, lr_scheduler_type="cosine",
        warmup_ratio=0.03, bf16=True, logging_steps=10,
        eval_strategy="steps", eval_steps=50, save_strategy="epoch",
        max_length=2048,
    ),
)
trainer.train()
```

Knobs that actually matter (in order): **data quality > learning rate (1e-4–3e-4) > epochs (1-3; watch val loss) > rank r (8-32)**. Everything else is noise at this scale.

Reading the loss curves:
- Train ↓ and val ↓ → keep going
- Train ↓ and val ↑ → overfitting; stop, use the earlier checkpoint, or get more data
- Both flat and high → LR too low, data inconsistent, or task too hard for the base model

**Deliverable:** trained adapter + train/val loss screenshot in your notebook.

---

### Stage 3 — Merge, quantize, serve (1 hour)

```python
# Merge adapter into base weights (load base in fp16 for a clean merge)
from peft import PeftModel
base = AutoModelForCausalLM.from_pretrained(model_id, torch_dtype=torch.float16)
merged = PeftModel.from_pretrained(base, "out-specialist/checkpoint-final").merge_and_unload()
merged.save_pretrained("specialist-merged"); tok.save_pretrained("specialist-merged")
```
```bash
# → GGUF → quantize → serve (Playbooks 00 & 03)
python llama.cpp/convert_hf_to_gguf.py specialist-merged --outfile specialist-f16.gguf
./llama.cpp/build/bin/llama-quantize specialist-f16.gguf specialist-q4km.gguf Q4_K_M
```

**Evaluate like you mean it:** run your held-out val prompts through base-model-vs-specialist side by side. Score them (yourself, or LLM-as-judge — Playbook 05 has the pattern). "It feels better" is not a result.

**Deliverable:** a win/loss/tie count, specialist vs base, on ≥50 held-out prompts.

---

### Stage 4 — Preference tuning with DPO (optional level-up)

When SFT gets the format right but choices wrong (tone, verbosity, judgment calls), train on *pairs*: chosen vs rejected responses.

```jsonl
{"prompt":"...","chosen":"<the answer you prefer>","rejected":"<the plausible but worse answer>"}
```
```python
from trl import DPOTrainer, DPOConfig
trainer = DPOTrainer(
    model=model, peft_config=peft_cfg,
    train_dataset=pairs,
    args=DPOConfig(output_dir="out-dpo", beta=0.1, learning_rate=5e-6,
                   per_device_train_batch_size=1, gradient_accumulation_steps=16, bf16=True),
)
trainer.train()
```
Cheap pair source: your SFT model's near-misses as `rejected`, your corrections as `chosen`. A few hundred good pairs move behavior noticeably.

### Iron laws
1. RAG for knowledge, fine-tuning for behavior.
2. 500 excellent examples beat 50,000 scraped ones.
3. Validation set before training, side-by-side eval after. Loss curves are not product quality.
4. Specialists compress better and run faster than generalists — fine-tuning is a *hardware* strategy, not just a quality one (it's what lets Playbook 00's small models work).


<br>

---

> ### Status of this playbook
>
> **Unverified in this pass.** Method unchanged — the pipeline design and the
> filtering discipline are the durable content here and neither depends on hardware.
>
> **One hardware consequence:** Stage 2 tells you to serve the teacher with vLLM and
> batch through it. On a single 15.9 GiB card the teacher and student cannot both be
> resident, so plan on generating first and training second rather than an online loop.
