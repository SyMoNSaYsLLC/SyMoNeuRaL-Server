# Playbook 06 — KV Cache, Long Context & Memory Tricks

> Part of the [symoneural_reinforce documentation set](README.md). Sliced from the consolidated manual at `../../../../../frontend/site/docs/symoneural-manual.md`, which remains the canonical single file.

[< Playbook 05 — Distillation & Synthetic Data](playbook-05.md)

## Playbook 06 — KV Cache, Long Context & Memory Tricks
#### Taming the hidden memory hog: quantized KV, paged attention, prompt caching, and honest long-context limits

You computed KV cache size in Playbook 02. Now you'll control it — because for agents and long chats, KV management decides what your hardware can actually do more than model choice does.

---

### Stage 1 — Reproduce the problem (30 min)

```bash
# Same model, two context allocations; watch VRAM (nvidia-smi in another terminal)
./build/bin/llama-server -m model-8b-q4km.gguf -ngl 99 -c 4096
./build/bin/llama-server -m model-8b-q4km.gguf -ngl 99 -c 65536
```
Note the VRAM difference — that's pre-allocated KV. Now feed a genuinely long prompt (paste a long document) and watch tok/s sag as context fills: every new token's attention must read the whole cache. Long context costs memory AND bandwidth.

**Deliverable:** VRAM and tok/s at 4 context fill levels (empty, 8K, 32K, 60K).

---

### Stage 2 — Quantize the KV cache (the free-est lunch here)

Weights aren't the only thing you can quantize:

```bash
# llama.cpp: KV cache in 8-bit or 4-bit (requires flash attention)
./build/bin/llama-server -m model.gguf -ngl 99 -c 32768 -fa on \
  -ctk q8_0 -ctv q8_0     # K and V cache both int8 → KV memory halved
# aggressive: -ctk q4_0 -ctv q4_0  → quarter memory, mild quality risk
```

Rules of thumb from wide community experience:
- **K and V at q8_0**: nearly lossless, use by default when context > 8K
- **V at q4_0**: usually fine; **K at q4_0**: riskier (keys steer attention) — test on YOUR task
- GQA models (Playbook 02) already shrank KV 4-8x architecturally; quantization stacks on top

**Deliverable:** rerun Stage 1's table with q8 KV; add a quality spot-check (same 10 prompts, compare answers).

---

### Stage 3 — Prompt caching: stop paying for the same prefix twice

Agents and RAG resend a giant, mostly-identical prompt every turn. Caching the prefix's KV skips recomputation:

- **llama.cpp server**: caches the common prefix across requests automatically per slot; design prompts so stable parts (system, tools, documents) come FIRST and variable parts (user turn) LAST. Reordering a prompt can cut time-to-first-token 5-10x in agent loops.
- **vLLM**: enable prefix caching:
```bash
vllm serve <model> --enable-prefix-caching
```
  Then measure: send 20 requests sharing a 3K-token system prompt, compare TTFT with and without.

Prompt-structure rule that follows: **immutable → semi-stable → volatile**, top to bottom. Never put a timestamp at the top of a cached prompt (it invalidates everything below it).

**Deliverable:** TTFT with/without caching for a shared-prefix workload — the single most valuable optimization for the agent work in Playbook 09.

---

### Stage 4 — When context runs out anyway: the honest toolbox

1. **Summarize-and-roll**: at ~70% full, summarize the oldest exchanges into a compact note, keep recent turns verbatim. Simple, effective, lossy — the standard for long chats.
2. **Retrieval instead of context** (Playbook 08): don't carry 200K tokens; store them and fetch the relevant 2K.
3. **Context-window extension caution**: models advertise 128K+ but quality at depth varies. Run your own "needle" test — plant 5 facts at different depths in a long document, ask for them, score recall by depth. Trust your table, not the marketing number.
4. **Sliding window / attention sinks**: some models/runtimes keep only recent KV + a few anchor tokens. Good for streams; forgets the middle by design.

**Deliverable:** your needle-test table for your main model (recall at 4 depths × 2 context lengths).

---

### Stage 5 — Memory budget worksheet (keep this)

For any deployment, fill in:
```
VRAM total:                      ______ GB
- Model weights (params×bytes):  ______ GB
- KV: tokens × KV/token (P02):   ______ GB   ← × 0.5 if q8 KV
- Activations/overhead:          ~1-2  GB
= Headroom:                      ______ GB   (negative → smaller quant, less context, or offload)
```
Run this BEFORE downloading. It replaces an afternoon of OOM whack-a-mole.

### Iron laws
1. KV cache is a memory consumer co-equal with weights; budget it explicitly.
2. q8 KV is the default nobody regrets; q4 K needs testing.
3. Cache-friendly prompt order (stable→volatile) is free 5-10x TTFT in loops.
4. Advertised context ≠ usable context. Needle-test it yourself.
5. The best long-context trick is usually not needing long context (summarize or retrieve).


<br>

---

> ### Status of this playbook
>
> **Unverified in this pass** (no draft-model runs). Method unchanged.
>
> **Measured, and directly relevant:** speculative decoding wins by amortising the
> per-token cost of reading weights. Two effects on this box are worth carrying into
> Stage 3's "supporting cast":
>
> - **CUDA graphs: 1.91x measured** on a small-kernel loop. Speculation produces
>   exactly the small-kernel-in-a-loop pattern graphs are best at.
> - With a draft and a target model both resident in 15.9 GiB, budget carefully —
>   an 8B target at Q4 plus a 1B draft at Q4 is about 5 GB before KV.
>
> **Samples that demonstrate this playbook:** `cudaGraphs`, `launchConfigTuning`.
