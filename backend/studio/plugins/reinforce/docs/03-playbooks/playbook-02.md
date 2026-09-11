# Playbook 02 — Transformer Anatomy & Profiling

> Part of the [symoneural_reinforce documentation set](README.md). Sliced from the consolidated manual at `../../../../../frontend/site/docs/symoneural-manual.md`, which remains the canonical single file.

[< Playbook 01 — Hardware & the Math of Inference](playbook-01.md)

## Playbook 02 — Transformer Anatomy & Profiling
#### Open the hood: what's inside a model, where the bytes live, and how to measure where time goes

You can't optimize what you can't locate. This lab dissects a real model layer by layer, then profiles it, so terms like "FFN", "heads", "KV cache", and "GQA" become things you've measured rather than words you've read.

---

### Stage 1 — Dissect a real model (1 hour)

```python
from transformers import AutoModelForCausalLM
import torch

model = AutoModelForCausalLM.from_pretrained("Qwen/Qwen2.5-1.5B", torch_dtype=torch.float16)
print(model)          # the full architecture tree
cfg = model.config
print(cfg)            # hidden_size, num_layers, num_heads, num_key_value_heads, intermediate_size
```

Now account for every parameter yourself:

```python
def param_census(model):
    buckets = {}
    for name, p in model.named_parameters():
        key = ("embed" if "embed" in name else
               "attn"  if any(k in name for k in ["q_proj","k_proj","v_proj","o_proj"]) else
               "ffn"   if any(k in name for k in ["gate_proj","up_proj","down_proj"]) else
               "norm"  if "norm" in name else "head")
        buckets[key] = buckets.get(key, 0) + p.numel()
    total = sum(buckets.values())
    for k, v in sorted(buckets.items(), key=lambda x: -x[1]):
        print(f"{k:8s} {v/1e6:8.1f}M  {100*v/total:5.1f}%")

param_census(model)
```

What you'll find (roughly, for modern LLMs):
- **FFN ≈ 55-65%** of parameters — the biggest target for pruning/quantization
- **Attention ≈ 20-30%**
- **Embeddings ≈ 5-20%** (huge share in small models — why small models resist compression more)
- Norms ≈ rounding error

Also decode the config: `num_key_value_heads < num_attention_heads` means **GQA** (grouped-query attention) — fewer KV heads = smaller KV cache = cheaper long context. This single config line predicts long-context memory cost.

**Deliverable:** the census table for two models (e.g., 1.5B and 8B) and a sentence on how their proportions differ.

---

### Stage 2 — KV cache math (30 min, calculator)

The forgotten memory consumer. Per token cached:
```
KV bytes/token = 2 (K and V) × num_layers × num_kv_heads × head_dim × bytes_per_value
```
Example, Llama-3.1-8B (32 layers, 8 KV heads, head_dim 128, FP16):
```
2 × 32 × 8 × 128 × 2 = 131 KB/token  →  128K context ≈ 16.8 GB (!)
```
The KV cache of one long conversation can exceed the model itself. This is why Playbook 06 exists.

**Deliverable:** compute KV/token for your favorite model and the context length where KV = model size.

---

### Stage 3 — Profile where time actually goes (1-2 hours)

```python
import torch
from torch.profiler import profile, ProfilerActivity

inputs = tok("The quick brown fox", return_tensors="pt").to("cuda")
model = model.to("cuda")

with profile(activities=[ProfilerActivity.CPU, ProfilerActivity.CUDA]) as prof:
    with torch.no_grad():
        model.generate(**inputs, max_new_tokens=64)

print(prof.key_averages().table(sort_by="cuda_time_total", row_limit=15))
```

What to look for:
- Matmul kernels (gemm/gemv) dominating → normal; that's weight reading
- Lots of tiny kernels + gaps → launch overhead; small models on big GPUs are launch-bound
- Compare a 16-token prompt vs a 4000-token prompt: watch prefill time explode (compute-bound, Playbook 01)

Second lens — watch memory live:
```python
torch.cuda.reset_peak_memory_stats()
model.generate(**long_inputs, max_new_tokens=512)
print(f"Peak VRAM: {torch.cuda.max_memory_allocated()/1e9:.2f} GB")
```
Run with 100-token and 8000-token prompts; the difference is mostly KV cache — your Stage 2 math made visible.

**Deliverable:** profiler table + a peak-VRAM-vs-context-length mini table (4 context lengths).

---

### Stage 4 — What each part does (the mental model to keep)

- **Embedding**: token ID → vector. Lookup table, bandwidth-trivial.
- **Attention (QKV + output proj)**: mixes information *across positions*. The only place tokens talk to each other. Grows with context (via KV cache reads).
- **FFN (gate/up/down)**: per-token computation, where most "knowledge" is stored. No cross-token interaction. Biggest, most prunable, most quantizable.
- **Residual stream**: the shared bus every layer reads/writes. Why you can delete layers and the model degrades gracefully instead of dying.
- **LM head**: final projection to vocabulary. Often tied to embeddings in small models.

Practical consequences you now understand mechanically:
| Observation | Cause |
|---|---|
| Long chats slow down and eat VRAM | KV cache growth, attention reads it every token |
| MoE models are fast for their size | Only some FFN experts read per token → fewer bytes/token |
| Quantizing FFN hurts least, embeddings hurt most | Knowledge is redundant in FFN; embeddings are lookup-precise |
| Pruning targets FFN channels & whole layers | 60% of params, graceful residual-stream degradation |

### Iron laws
1. FFN is where the parameters are; attention is where the interaction is; KV is where the context cost is.
2. KV cache is a first-class memory consumer — budget it like model weights.
3. Profile before optimizing; the bottleneck is usually not where you guessed.
4. Config file → performance prediction. Learn to read configs like spec sheets.


<br>

---

> ### Status of this playbook
>
> **Unverified in this pass.** No engine was installed or benchmarked here, so
> every number in this playbook remains the author's original claim. Treat the
> comparison table as orientation, not as measurement — see Appendix B.
>
> **What this box adds:** two findings from Part I bear directly on engine choice.
>
> 1. **PCIe Gen 3 x8** means llama.cpp partial offload (`-ngl` below the full layer
>    count) is far more expensive here than on a typical benchmark machine. Prefer
>    configurations that fit entirely in VRAM.
> 2. **CUDA graphs gave 1.91x** on a small-kernel loop (`cudaGraphs` sample). Engines
>    that support graph capture are exploiting exactly that mechanism — it is a real
>    effect on this hardware, not a marketing claim.
>
> **Samples that demonstrate this playbook:** `cudaGraphs` (launch-overhead removal),
> `streamingCopyComputeOverlap` (why overlap does not save you here),
> `launchConfigTuning` (per-kernel tuning).
