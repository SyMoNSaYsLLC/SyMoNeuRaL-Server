# Playbook 07 — Speed Tricks: Speculative Decoding & Friends
### 2-4x more tokens/sec from the same silicon, and knowing which trick applies when

Playbook 01 taught you decode speed = bandwidth ÷ model bytes. That's the wall. This lab is about the legal ways around the wall: guessing tokens cheaply and verifying them in bulk, plus the smaller wins that stack.

---

## Stage 0 — Why speculation works (5 min)

Reading all weights once produces ONE token — but verifying N candidate tokens in a single forward pass costs barely more than producing one (the weight-read is shared). So: let a tiny "draft" model guess 4-8 tokens, then have the big model verify them all at once. Accepted tokens are FREE bandwidth-wise. Output is mathematically identical to the big model alone — rejected guesses are simply discarded and regenerated.

Speedup ≈ acceptance_rate × draft_length, minus overhead. Predictable text (code, JSON, formulaic prose) accepts more → speeds up more.

---

## Stage 1 — Draft-model speculation in llama.cpp (1 hour)

Pair a big model with a tiny sibling from the SAME family (tokenizer must match):

```bash
# Example: 8B target + 1B draft (or 32B + 1.5B — bigger gap, bigger win)
./build/bin/llama-server \
  -m  Llama-3.1-8B-Instruct-Q4_K_M.gguf \
  -md Llama-3.2-1B-Instruct-Q4_K_M.gguf \
  -ngl 99 -ngld 99 -fa on \
  --draft-max 8 --draft-min 1

# Benchmark vs no-draft baseline on THREE workload types:
#   1. code generation   2. JSON extraction   3. creative prose
```

Expected pattern: code/JSON 1.8-2.5x, prose 1.2-1.5x, adversarially random text ~1.0x. Tune `--draft-max`: too high wastes draft compute on rejections, too low caps the win. 4-8 is the usual sweet spot.

**Deliverable:** a 3-workload × 2-config (spec on/off) tok/s table, plus your chosen draft-max.

---

## Stage 2 — Self-speculation: n-gram / prompt lookup (free, no draft model)

When output copies from input (editing, extraction, RAG quoting), the "draft" can be substrings of the prompt itself:

```bash
# llama.cpp lookup decoding example binary
./build/bin/llama-lookup -m model.gguf -f long-document.txt \
  -p "Rewrite the above fixing grammar only:" -n 512
```
vLLM equivalent concept: `--speculative-config` with ngram method. Costs nothing (no second model in VRAM) and shines exactly where agents live: tool-output echoing, code edits, structured rewrites.

**Deliverable:** measure an "edit this document" task with and without lookup decoding.

---

## Stage 3 — The supporting cast (stack these)

| Trick | Gain | Where |
|---|---|---|
| Flash attention (`-fa on`) | 10-30% + less VRAM | always-on if supported |
| Right quant for bandwidth (P00/P01) | linear with size | everywhere |
| Batch your own work | huge aggregate | vLLM continuous batching (P03) |
| Prompt caching (P06) | 5-10x TTFT | agent loops, RAG |
| **Structured output / grammars** | fewer wasted tokens + retries | JSON tasks: `--grammar-file json.gbnf` (llama.cpp) or vLLM guided decoding — malformed-output retries are the silent throughput killer |
| Shorter outputs by prompt design | linear | "Answer in ≤3 sentences" is a speed optimization |
| Compile/graph modes (CUDA graphs, TRT-LLM) | 10-40% | fixed deployments |

Also know what does NOT help single-stream decode: more TFLOPS (bandwidth-bound), more CPU cores past memory saturation, PCIe 5 vs 4 when fully GPU-resident.

**Deliverable:** turn on flash attention + a grammar for one JSON workload; record tok/s AND retry-rate before/after.

---

## Stage 4 — The combined build

Assemble your fastest honest config for one real workload (e.g., "code assistant on my 4090"):
```
Q4_K_M weights + q8 KV + flash attn + 1B draft + cached system prompt + grammar for tool calls
```
Measure end-to-end task time (not just tok/s) vs the naive setup from a month ago. 3-5x total is common. Write down the config; that's your production recipe.

## Iron laws
1. Verification is cheap, generation is expensive — that asymmetry is the whole trick.
2. Speculation output = target-model output. It's a free lunch with a VRAM side-dish.
3. The more predictable the text, the bigger the win. Code and JSON love speculation.
4. Wasted tokens (verbose answers, failed parses, retries) are the biggest hidden slowdown — grammars and tight prompts are speed features.
5. Stack tricks; measure the stack, not just the pieces.
