# Playbook 03 — Inference Engines Shootout

> Part of the [symoneural_reinforce documentation set](README.md). Sliced from the consolidated manual at `../../../../../docs/symoneural-manual.md`, which remains the canonical single file.

[< Playbook 02 — Transformer Anatomy & Profiling](playbook-02.md)

## Playbook 03 — Inference Engines Shootout
#### llama.cpp vs vLLM vs TensorRT-LLM vs Ollama: pick the runtime like an engineer, not a fan

The same model on the same GPU can differ 3x in throughput depending on the engine and its settings. This lab makes you benchmark them yourself and learn what each is actually for.

---

### Stage 0 — The map (10 min read)

| Engine | Built for | Quant formats | Strength | Cost |
|---|---|---|---|---|
| **llama.cpp** | single user, any hardware | GGUF (K-quants, IQ) | runs anywhere, CPU+GPU split, lowest RAM | modest batch throughput |
| **Ollama** | convenience layer over llama.cpp | GGUF | one-command UX, model registry, API | hides tuning knobs, some overhead |
| **vLLM** | serving many requests | GPTQ/AWQ/FP8/some GGUF | paged attention, continuous batching → huge throughput | wants full-GPU residency, heavier install |
| **TensorRT-LLM** | max NVIDIA performance | own compiled engines | fastest single-GPU numbers | painful build, per-GPU compile, NVIDIA only |
| **ExecuTorch / LiteRT** | phones & embedded | int8/int4 | mobile deployment | not for desktops (Playbook 10) |

Decision rule of thumb: **one user → llama.cpp/Ollama; many concurrent requests or agents fanning out → vLLM; squeezing a fixed NVIDIA deployment → TensorRT-LLM.**

---

### Stage 1 — Baseline: llama.cpp done properly (1 hour)

Most people run llama.cpp with defaults and lose 30%+ performance. The knobs that matter:

```bash
./build/bin/llama-server -m model-8b-q4km.gguf \
  -ngl 99          `# layers offloaded to GPU — 99 = all; lower if OOM (partial offload)` \
  -c 8192          `# context size — KV cache is allocated for this; don't overprovision` \
  -fa on           `# flash attention — usually free speed` \
  -b 2048 -ub 512  `# batch sizes for prefill` \
  --port 8080

# Benchmark properly:
./build/bin/llama-bench -m model-8b-q4km.gguf -p 512,4096 -n 128 -ngl 99 -fa 1
```

Experiments to run (change ONE knob at a time, record tok/s):
1. `-ngl 99` vs `-ngl 20` — feel the cliff of partial offload
2. `-fa on` vs off
3. `-c 4096` vs `-c 32768` — watch VRAM, then find the OOM edge
4. Q4_K_M vs Q6_K vs IQ3_XXS of the same model — bandwidth math from Playbook 01 in action

**Deliverable:** your llama.cpp tuning table; a best-config one-liner saved for your box.

---

### Stage 2 — vLLM: throughput mode (1-2 hours)

```bash
pip install vllm

# Serve (AWQ model from Playbook 00 works here)
vllm serve Qwen/Qwen2.5-7B-Instruct-AWQ \
  --max-model-len 8192 \
  --gpu-memory-utilization 0.90
```

The core ideas that make vLLM different:
- **PagedAttention**: KV cache in fixed-size blocks (like OS virtual memory) → near-zero fragmentation → more concurrent sequences fit
- **Continuous batching**: new requests join the running batch mid-flight instead of waiting → GPU never idles

Benchmark single-stream vs many-stream:
```bash
pip install openai
python - <<'EOF'
# Fire N concurrent requests at the OpenAI-compatible endpoint and measure aggregate tok/s
import asyncio, time
from openai import AsyncOpenAI
client = AsyncOpenAI(base_url="http://localhost:8000/v1", api_key="x")

async def one(i):
    r = await client.chat.completions.create(model="Qwen/Qwen2.5-7B-Instruct-AWQ",
        messages=[{"role":"user","content":f"Write 200 words about topic {i}."}], max_tokens=300)
    return r.usage.completion_tokens

async def main(n):
    t0 = time.time()
    toks = await asyncio.gather(*[one(i) for i in range(n)])
    dt = time.time()-t0
    print(f"{n:3d} concurrent: {sum(toks)/dt:7.1f} tok/s aggregate")

for n in (1, 4, 16, 64):
    asyncio.run(main(n))
EOF
```

You should see aggregate throughput scale dramatically with concurrency while llama.cpp's would plateau early. That curve IS the reason vLLM exists.

**Deliverable:** concurrency-vs-throughput table for vLLM and (for contrast) llama.cpp-server at 1/4/16 concurrent.

---

### Stage 3 — The same model, three ways (the shootout, 1 evening)

Pick one model (e.g., 7-8B class). Run the identical prompt set through:
1. llama.cpp (your tuned config, Q4_K_M)
2. Ollama (default) — measure the convenience tax vs #1
3. vLLM (AWQ)
4. (Optional, masochists) TensorRT-LLM — expect hours of build for the best single-stream numbers

Measure for each: single-stream tok/s, time-to-first-token at 4K prompt, aggregate tok/s at 16 concurrent, VRAM used.

**Deliverable:** the shootout table. Keep it — this is the table everyone argues about online and almost nobody has actually produced for their own hardware.

---

### Stage 4 — Choosing, permanently

- Daily driver / chat / one agent → **llama.cpp** tuned, or Ollama if you value convenience over 10-15%
- Agent swarms, batch data processing, serving your LAN → **vLLM**
- Locked deployment, every ms matters, NVIDIA → **TensorRT-LLM**
- Mixing CPU RAM + VRAM to run oversized models → **llama.cpp** partial offload (only game in town)

### Iron laws
1. Engine choice is a workload decision (single vs concurrent), not a fashion decision.
2. Untuned benchmarks are noise. `-ngl`, `-fa`, context size, and quant change everything.
3. Throughput and latency are different sports; know which one you're playing.
4. The convenience layer always costs something — measure the tax, then decide if it's worth it.


<br>

---

> ### Status of this playbook
>
> **Unverified in this pass** — no fine-tuning run was performed. Method unchanged.
>
> **What this box adds:** PyTorch **2.13.0+cu130** installs cleanly and ships an
> `sm_120` binary (`torch.cuda.get_arch_list()` includes `sm_120`), so **no source
> build is needed for Blackwell** — a common worry with new architectures, and one
> you can stop having.
>
> Practical ceiling with 15.9 GiB: QLoRA on a 7–8B model is comfortable; 13–14B is
> tight but feasible with gradient checkpointing and a small batch.
>
> **Samples that demonstrate this playbook:** `customPyTorchKernel` (dropping custom
> CUDA into a torch model with autograd intact).
