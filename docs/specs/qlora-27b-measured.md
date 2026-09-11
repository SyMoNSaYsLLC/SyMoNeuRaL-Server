# QLoRA on Qwen3.6-27B — what the card actually does

**Measured on this machine, 2026-08-18.** RTX 5070 Ti, 15.49 GiB as CUDA reports it (the
15.92 GiB figure elsewhere is the vendor nameplate; `torch.cuda.mem_get_info` returns
15.49 GiB total, 15.03 GiB free with nothing else resident).

This is the empirical companion to `qlora-upgrade.md`, whose §4.2 method projected these
numbers from safetensors headers before any of it was loaded. Where the two differ, this
file is the measurement and wins.

Every figure below is **measured** unless the line says otherwise. The harness is
`training/probe_27b.py`, which asserts its own plan and writes `run/probe_27b.json`; the
configuration it proves is what `training/train_lora.py` takes when the config is hybrid.

## The load works. Four traps do not announce themselves.

### 1. `AutoModelForCausalLM` silently random-initialises the 27B

`AutoModelForCausalLM` maps `Qwen3_5Config` → `Qwen3_5ForCausalLM`, whose parameters are
named `model.layers.*`. The checkpoint ships `model.language_model.layers.*`. Built on the
meta device and diffed against `model.safetensors.index.json`:

| class | expects | supplied by checkpoint | randomly initialised |
|---|---|---|---|
| `Qwen3_5ForCausalLM` | 853 | **1** | **852** |
| `Qwen3_5ForConditionalGeneration` | 1187 | 1184 | 3 (rotary `inv_freq`, computed not loaded) |

There is no `_checkpoint_conversion_mapping` to bridge them. Transformers reports this as a
*warning*, so with a plain `device_map={"": 0}` nothing raises — you get an hour of
fine-tuning on noise. The correct entry point is **`AutoModelForImageTextToText`**, which
maps to `Qwen3_5ForConditionalGeneration`. `train_lora.py` now asserts the coverage on the
meta device before it loads a byte.

`config.language_model_only` does not help: it is a Qwen-side knob and transformers does not
read it. The vision tower is *placed*, not prevented. The 15 `mtp.*` tensors are never built
by this class and are dropped as unexpected.

### 2. A `device_map` entry of `"cpu"` moves the whole tensor back for every forward

Placing `model.language_model.embed_tokens` on the CPU does not stream it. accelerate's
`AlignDevicesHook.pre_forward` calls `set_module_tensor_to_device`, which copies the
**entire** weight to the execution device:

```
torch.OutOfMemoryError: CUDA out of memory. Tried to allocate 4.74 GiB
```

4.74 GiB is 1,271,398,400 params at **4 bytes** — `llm_int8_enable_fp32_cpu_offload=True`
upcasts CPU-placed modules to fp32. So the offload that was supposed to save 2.37 GiB
instead demands 4.74 GiB, and it fails at the first forward, four minutes into the run.

The parameter is also left as a **meta** tensor with the data in accelerate's `weights_map`
("Some parameters are on the meta device because they were offloaded to the cpu"), so
reading `.weight` off the loaded module raises `Cannot copy out of meta tensor; no data!`.

What works is a shim that does the gather on the CPU and returns a GPU tensor, with the
weight read straight from its shard. An embedding lookup needs one row per token: 6.8 MiB at
the corpus's longest example, against 4.74 GiB. This is *not* the transaction §7.7 rules
out — §7.7 is about optimizer state crossing PCIe every step, and this table is frozen.

### 3. Quantising `lm_head` costs more than it saves

`bitsandbytes` 4-bit matmul does not stay quantised through a training step.

- **Forward** falls back to `_dequant_linear_fallback` whenever `M > 1536` tokens, or when
  the per-arch heuristic declines (`backends/cuda/ops.py:584`). It materialises the full
  dequantised weight: `B_dq = torch.empty(shapeB, dtype=A.dtype, device=A.device)`.
- **Backward** always does, unconditionally — `grad_A = torch.matmul(grad_output,
  F.dequantize_4bit(B, ctx.state))` (`autograd/_functions.py:384`). There is no fused
  backward path, so the forward kernel choice is irrelevant.

At a 248,320-token vocab and hidden 5120 that transient is **2.37 GiB**, measured:

```
torch.OutOfMemoryError: CUDA out of memory. Tried to allocate 2.37 GiB
```

So NF4 on `lm_head` trades 1.76 GiB of residency for a 2.37 GiB transient — a net loss. It
is harmless at Qwen2.5's 152k vocab and decisive here. For every other Linear the same
dequant applies but the largest is `[17408, 5120]` = 0.17 GiB, which is fine.

### 4. `prepare_model_for_kbit_training` upcasts the output embedding and OOMs the load

PEFT casts **every** non-`Params4bit` fp16/bf16 parameter to fp32
(`peft/utils/other.py:196-202`). On the norms that is the QLoRA recipe and costs kilobytes.
On a 248,320 × 5120 output embedding it is 2.37 → 4.74 GiB, with 14.07 GiB already resident:

```
torch.OutOfMemoryError: Tried to allocate 4.74 GiB
  peft/utils/other.py:202  param.data = param.data.to(torch.float32)
```

The embeddings are frozen and never receive a gradient, so fp32 buys no stability here. The
fix is `_prepare_kbit_keep_embeddings` in `train_lora.py` — the same function minus the
embeddings, skipped by `id()` of the parameters behind `get_output_embeddings()` /
`get_input_embeddings()`. Measured: 463,375,600 params upcast, 2,542,796,800 left bf16.

The 7B/dense path still calls stock `prepare_model_for_kbit_training`; it is what produced
the shipped adapter and there is no reason to re-roll it.

## Measured residency

| | GiB |
|---|---|
| text linear weights, NF4 + double quant | **11.70** |
| `lm_head`, NF4 (unusable — see trap 3) | 0.61 |
| `lm_head`, bf16 | 2.37 |
| `embed_tokens`, bf16 (kept off the card by the CPU shim) | 0 |
| vision tower (offloaded, never called on a text corpus) | 0 |
| fp32 upcast of the norms | ~0.01 |

The upcast line prints `463,375,600 params`, which looks alarming and is not: 460,730,096 of
them are the vision tower, sitting on `meta`, where a dtype change allocates nothing. The
2.6 M that are genuinely resident are the norms, and fp32 costs 5 MB over bf16.

Weights with a usable bf16 head: **14.07 GiB of 15.49** — measured with
`torch.cuda.memory_allocated()` after load, not projected. An earlier revision of this file
said 14.45 GiB, which was arithmetic over the tensor list; the real figure is lower.

That is still not enough. With the head resident the run OOMs **22 MiB short in the forward
pass**, before any gradient or optimizer state exists. Neither a bf16 adapter nor a paged
8-bit optimizer rescues it — together they move peak allocation by 0.08 GiB (14.89 → 14.81),
which is the wrong order of magnitude for a deficit in the forward.

### The head has to leave the card, and a module swap does not move it

Replacing `lm_head` with `torch.nn.Identity()` and `del`-ing the local freed **nothing**:

```
lm_head off the card: -0.19 GiB freed, 14.26 GiB resident
```

Allocation went *up*, by exactly the adapter. Other references survive the swap — locals in
the calling frame, and accelerate's hooks. What actually returns the memory is emptying the
storage in place, which does not care who else points at the module:

```python
head_cpu = head.weight.detach().to("cpu", torch.bfloat16).pin_memory()
head.weight.data = torch.empty(0, device=head.weight.device, dtype=head.weight.dtype)
```

Measured after that change: **2.37 GiB freed, 11.90 GiB resident.**

### Streamed cross-entropy: the measured fit

With the head in pinned CPU bf16, the loss is computed by `StreamedCE`
(`training/train_lora.py`), chunked over the **vocab** rather than over tokens — a vocab slice
serves every token at once, so one sweep of the weight covers the whole sequence. Online
logsumexp in the forward, a second sweep for `grad_hidden` in the backward, no weight gradient
because the head is frozen. Verified against `F.cross_entropy` on CPU before it was run on the
card: loss delta 4.768e-07, grad delta 6.985e-10 at matched precision.

It is also **more accurate than the resident head it replaces**, which is not the result you
expect from a memory workaround. Against a full-fp32 reference, relative L2 error on
`grad_hidden` with a bf16 head:

| | relative L2 |
|---|---|
| stock `F.cross_entropy` through a bf16 `lm_head` | 7.65e-03 |
| `StreamedCE` | 2.25e-03 |

Both are dominated by bf16's 8-bit mantissa, not by the chunking; `StreamedCE` keeps its
logsumexp and its probabilities in fp32 and only rounds at the final `grad @ W` product, so it
rounds once where the stock path rounds twice.

One dtype trap of its own: custom autograd Functions are **excluded from autocast**, so under
`Trainer(bf16=True)` the hidden states arrive fp32 while the head is bf16 and the matmul raises
`expected mat1 and mat2 to have the same dtype`. `StreamedCE` casts to the weight's dtype on
entry and returns the gradient in the input's dtype, so it does not care what the caller does.

Full step at seq 662, answer 578, r=16, bf16 adapter, paged 8-bit optimizer:

```
MEASURED peak allocated :  14.26 GiB
MEASURED peak reserved  :  14.44 GiB   (what the card must hold)
driver-reported in use  :  14.31 GiB   (includes the ~0.32 GiB CUDA context)
card total              :  15.49 GiB
headroom, driver        :   1.17 GiB
```

**It fits, with 1.17 GiB to spare.** Cost: ~2.37 GiB of PCIe per sweep, two sweeps per
micro-step. At the measured Gen 3 ×8 ceiling that is a *projected* ~11 minutes added over
981 micro-steps (327 examples × 3 epochs) — projection, not a measurement; the real number
comes out of the training run.

## Sequence length, measured from the corpus

Statistics only — the corpus is trade secret and none of its content is reproduced here.
Re-measured with **Qwen3.6's** tokenizer; the earlier figures in this file were Qwen2.5's and
ran 3–4 tokens long.

| n=327 | min | median | mean | p90 | p99 | max |
|---|---|---|---|---|---|---|
| whole example | 104 | 181 | 227 | 439 | 537 | **662** |
| assistant turn only | 20 | 96 | 142 | 355 | 445 | **578** |

Batch is 1 and nothing is padded, so peak is set by the longest example, not by `--seq-len`.
Coverage: seq 256 → ~75%, seq 512 → ~98%, **seq 768 → 100%**.

The second row is the one that matters for `lm_head`. `encode()` masks the prompt to -100, so
only the assistant turn ever needs logits — and being the *trailing* segment, it is reachable
exactly via `logits_to_keep` rather than by an approximate slice. **But the saving is small:
578 of 662 tokens, 87%.** The longest example in this corpus is nearly all answer, so
answer-only slicing takes the logits transient from ~1.54 GiB to ~1.34 GiB and does not
change the outcome. Recorded because it is the obvious idea and it does not work here.

## LoRA target set

48 of 64 layers are `linear_attn` and carry no `q/k/v/o_proj` at all; only the 16 where
`(i+1) % 4 == 0` are full `self_attn`. The 7B's target list therefore reaches attention in
16 layers and **silently misses the other 48** — no error, just a quarter-adapted model.

| target set | params @ r=16 | % of model | GiB @ 10 B/param |
|---|---|---|---|
| 7B list (MLP + full-attn) | 79,691,776 | 0.29% | 0.74 |
| + `in_proj_qkv`, `out_proj` | 100,139,008 | 0.36% | 0.93 |
| + every `linear_attn` proj | 116,727,808 | 0.42% | 1.09 |

`in_proj_a` and `in_proj_b` are excluded deliberately: they are `[48, 5120]`, so r=16 is a
third of full rank on a 48-wide output. That is not a low-rank adaptation.

## Where this leaves §7.2

`qlora-upgrade.md` §7.2 said *"No model above ~14B, at any rank. A 32B in 4-bit is ~16 GiB of
weights before a single gradient exists."* The measurement **confirms** it for the recipe §7
was describing and does not overturn it: 14.07 GiB of weights on a 15.49 GiB card leaves
1.42 GiB, and a stock QLoRA step OOMs inside the forward. §7 needs no retraction.

**The 27B fits only because `lm_head` stopped being resident** — and that is not a tuning
knob, it is a custom autograd Function, a CPU-pinned copy of the head, a reimplementation of
`prepare_model_for_kbit_training`, and an in-place storage empty. Four traps, none of which
announce themselves. Anyone reading §7.2 as "so it turns out 27B is fine" has read it wrong.

## Conversion path is clear

`convert_lora_to_gguf.py` resolves the architecture from the **top-level** `architectures`
key, because Qwen3.6's `text_config` has no `architectures` of its own
(`conversion/base.py:2686`). `Qwen3_5ForConditionalGeneration` is registered for both the
text path (`conversion/__init__.py:225` → `qwen`) and the mmproj path (`:321` → `qwen3vl`),
and `gguf-py/gguf/tensor_mapping.py` maps every `linear_attn` module explicitly
(`in_proj_qkv`:252, `in_proj_z`:387, `out_proj`:883, `in_proj_a`:888, `in_proj_b`:912). So an
adapter over the hybrid layers can be converted and served through `api.py`'s `--lora` hook.

## Open risk, not yet evaluated

The serving base is `symon-1.0-27b-q2_k_xl`. An adapter trained against NF4 weights would
meet a **~2.5 bpw** base at inference. The 7B path is NF4 → Q4_K_M, roughly matched; this is
a materially wider gap, and `UD-Q4_K_XL` at 17.61 GB does not fit the card, so it is
structural rather than something a different quant fixes. Untested either way.
