# The Local AI Engineer's Manual — 2026 Edition
### Ten hands-on playbooks that connect into one complete skill set

Each playbook is a lab: stages, runnable commands, and a deliverable. Work them roughly in order — each builds vocabulary and artifacts the next one uses. Done honestly (measure everything, skip nothing), this covers the full territory of running, shrinking, tuning, and deploying serious AI on hardware you own.

---

## Table of Contents

| # | Playbook | The piece of the puzzle it covers |
|---|---|---|
| 00 | **Model Compression Lab** *(already delivered)* | Quantization → pruning → distillation → FPGA. The shrink pipeline. |
| 01 | **Hardware & the Math of Inference** | Why models run at the speed they do. Bandwidth, FLOPs, roofline, sizing models to silicon. |
| 02 | **Transformer Anatomy & Profiling** | What's actually inside the model — attention, FFN, KV cache — and how to measure where time/memory goes. |
| 03 | **Inference Engines Shootout** | llama.cpp vs vLLM vs TensorRT-LLM vs Ollama. Picking and tuning the runtime. |
| 04 | **Fine-Tuning Specialists** | LoRA/QLoRA/DPO — turning a small generalist into an expert on YOUR task. |
| 05 | **Distillation & Synthetic Data** | Using big models to manufacture training data that makes small models punch up. |
| 06 | **KV Cache, Long Context & Memory Tricks** | The hidden memory hog. Paged attention, quantized KV, prompt caching. |
| 07 | **Speed Tricks: Speculative Decoding & Friends** | Getting 2-4x more tokens/sec from the same hardware. |
| 08 | **Local RAG & Embeddings** | Giving small models knowledge without retraining. Vector search on your own machine. |
| 09 | **Agents & Orchestration on Local Models** | Tool use, routing, multi-worker systems with small models. |
| 10 | **Edge Deployment** | Pi, Jetson, phones, pure CPU, ternary models. The last mile. |

---

## The dependency map

```
01 Hardware math ──┐
02 Anatomy ────────┼──► 03 Engines ──► 06 KV cache ──► 07 Speed
                   │
00 Compression ────┼──► 04 Fine-tune ──► 05 Distill
                   │
                   └──► 08 RAG ──► 09 Agents
                              03+00 ──► 10 Edge
```

Read 01 and 02 first — they are the grammar everything else is written in. After that, follow your interest.

## Ground rules for every lab
1. **Measure after every step.** A number you didn't produce yourself is a rumor.
2. **Small victim model first.** Learn the pipeline on a 1B, apply it to the 70B later.
3. **One variable at a time.** Change quant AND engine AND settings together and you learn nothing.
4. **Keep a lab notebook** (a `results.md` per lab) — your own tables become your real manual.
5. **Verify claims against disk state.** Treat "it worked" as a hypothesis.

## Currency note
Written against the state of tooling as of early 2026. Names to watch for drift: llama.cpp quant formats, vLLM flags, ExecuTorch/LiteRT APIs. The *concepts* (bandwidth-bound decoding, calibrated quantization, distillation, paged KV) are stable — when a command dies, the idea it implements is still the thing to search for.
