# Playbook 01 — Hardware & the Math of Inference

> Part of the [symoneural_reinforce documentation set](README.md). Sliced from the consolidated manual at `../../../../../docs/symoneural-manual.md`, which remains the canonical single file.

[< The Local AI Engineer's Manual — 2026 Edition](playbook-00-index.md)

## Playbook 01 — Hardware & the Math of Inference
#### Why models run at the speed they do, and how to size a model to silicon before downloading a single byte

Most people benchmark by trial and error. You're going to learn the three formulas that predict performance *before* you touch the hardware. This is the highest-leverage knowledge in the whole manual.

---

### Stage 1 — The three numbers that rule everything (30 min, pen and paper)

Every piece of hardware has:
1. **Memory capacity** (GB) — determines what *fits*
2. **Memory bandwidth** (GB/s) — determines decode speed
3. **Compute** (TFLOPS) — determines prefill speed and batch throughput

#### Formula 1: Does it fit?
```
Model VRAM ≈ params × bytes_per_param + KV cache + overhead (~1-2 GB)

FP16: 2 bytes/param    INT8: 1    Q4: ~0.55    IQ2: ~0.3
```
Example: 8B model at Q4 ≈ 8 × 0.55 = **4.4 GB** + KV + overhead → fits in 8 GB.

#### Formula 2: How fast will it generate? (the big one)
Token generation is **memory-bandwidth bound**: every token requires reading ALL weights from memory once.
```
Max tokens/sec ≈ memory_bandwidth (GB/s) ÷ model_size_in_memory (GB)
```
Examples:
| Hardware | Bandwidth | 8B @ Q4 (4.4 GB) | 70B @ Q4 (~38 GB) |
|---|---|---|---|
| RTX 4090 | ~1000 GB/s | ~220 tok/s | doesn't fit |
| RTX 3060 12GB | ~360 GB/s | ~80 tok/s | doesn't fit |
| Apple M4 Max | ~546 GB/s | ~120 tok/s | ~14 tok/s |
| DDR5 desktop (2ch) | ~90 GB/s | ~20 tok/s | ~2.4 tok/s |
| Raspberry Pi 5 | ~17 GB/s | ~4 tok/s (1B model: ~30) | no |

This one formula explains: why quantization speeds up decoding (smaller model = fewer bytes to read), why CPUs with fast RAM are viable, why a 4090 barely beats a 3090 at single-stream decode (similar bandwidth), and why Macs are good at this (unified memory bandwidth).

#### Formula 3: Prefill (prompt processing) is compute-bound
```
Prefill tok/s ≈ compute_TFLOPS × efficiency / (2 × params)
```
Long prompts stress compute; generation stresses bandwidth. Two different bottlenecks — a machine can be great at one and bad at the other.

**Deliverable:** compute predicted tok/s for YOUR GPU and 3 model sizes. Write them down. You'll test them in Stage 3.

---

### Stage 2 — Interrogate your own hardware (30 min)

```bash
# GPU: name, VRAM, and measure real bandwidth
nvidia-smi --query-gpu=name,memory.total,memory.used --format=csv


google  ~/MIT_AI_Training/MIT_AI_Training  10:48  nvidia-smi
Sun Aug 16 10:48:42 2026       
+-----------------------------------------------------------------------------------------+
| NVIDIA-SMI 610.57.04              KMD Version: 610.57.04     CUDA UMD Version: 13.3     |
+-----------------------------------------+------------------------+----------------------+
| GPU  Name                 Persistence-M | Bus-Id          Disp.A | Volatile Uncorr. ECC |
| Fan  Temp   Perf          Pwr:Usage/Cap |           Memory-Usage | GPU-Util  Compute M. |
|                                         |                        |               MIG M. |
|=========================================+========================+======================|
|   0  NVIDIA GeForce RTX 5070 Ti     On  |   00000000:01:00.0 Off |                  N/A |
|  0%   36C    P8              4W /  300W |     240MiB /  16303MiB |      0%      Default |
|                                         |                        |                  N/A |
+-----------------------------------------+------------------------+----------------------+

+-----------------------------------------------------------------------------------------+
| Processes:                                                                              |
|  GPU   GI   CI              PID   Type   Process name                        GPU Memory |
|        ID   ID                                                               Usage      |
|=========================================================================================|
|    0   N/A  N/A            1557      G   /usr/lib/xorg/Xorg                      159MiB |
|    0   N/A  N/A            1672      G   /usr/bin/sddm-greeter-qt6                16MiB |
+-----------------------------------------------------------------------------------------+
google  ~/MIT_AI_Training/MIT_AI_Training  10:48  nvidia-smi --query-gpu=name,memory.total,memory.used --format=csv
name, memory.total [MiB], memory.used [MiB]
NVIDIA GeForce RTX 5070 Ti, 16303 MiB, 240 MiB
google  ~/MIT_AI_Training/MIT_AI_Training  10:51  


# Real memory bandwidth benchmark (CUDA)
git clone https://github.com/NVIDIA/cuda-samples
# DEAD COMMAND — Samples/ is now cpp/, the build is CMake, and
# bandwidthTest was deleted from the repository. See the box above
# for the measured replacement.
# cd cuda-samples/Samples/1_Utilities/bandwidthTest && make && ./bandwidthTest

# CPU RAM bandwidth
sudo apt install sysbench
sysbench memory --memory-block-size=1M --memory-total-size=20G run


Running the test with following options:
Number of threads: 1
Initializing random number generator from current time


Running memory speed test with the following options:
  block size: 1024KiB
  total size: 20480MiB
  operation: write
  scope: global

Initializing worker threads...

Threads started!

Total operations: 20480 (29442.18 per second)

20480.00 MiB transferred (29442.18 MiB/sec)


General statistics:
    total time:                          0.6947s
    total number of events:              20480

Latency (ms):
         min:                                    0.03
         avg:                                    0.03
         max:                                    0.11
         95th percentile:                        0.03
         sum:                                  691.70

Threads fairness:
    events (avg/stddev):           20480.0000/0.00
    execution time (avg/stddev):   0.6917/0.00


# PCIe link speed (matters for CPU-GPU offload splits)
nvidia-smi --query-gpu=pcie.link.gen.current,pcie.link.width.current --format=csv
```
(.venv) google  ~/MIT_AI_Training/MIT_AI_Training  11:37  nvidia-smi --query-gpu=pcie.link.gen.current,pcie.link.width.current --format=csv
pcie.link.gen.current, pcie.link.width.current
1, 8


Also learn the roofline mental model: performance = mingy(compute ceiling, bandwidth × arithmetic intensity). Batch=1 decoding has arithmetic intensity ≈ 1 FLOP/byte → deep in the bandwidth-bound region. Batching raises intensity → moves toward compute-bound → this is why servers batch.

**Deliverable:** a `my-hardware.md` file with your measured bandwidth (GPU and RAM), VRAM, and TFLOPS.

---



### Stage 3 — Predict, then verify (1 hour)

```bash
# Grab two GGUF models of different sizes (e.g., 1B and 8B at Q4_K_M)
# then benchmark with llama.cpp:
./build/bin/llama-bench -m model-8b-q4km.gguf -p 512 -n 128
# -p = prefill test, -n = generation test
```

Compare measured tok/s to your Formula 2 prediction. You should land within ~±25%. If you're way off:
- Much slower than predicted → thermal throttling, PCIe offloading (model didn't fully fit), or background load
- Check offload: `nvidia-smi` during the run; watch for RAM↔VRAM traffic

**Deliverable:** table of predicted vs measured for 2+ models. This calibrates your intuition permanently.

---

### Stage 4 — The sizing decision procedure (the takeaway)

Given a task and a box, run this checklist:
1. Minimum acceptable tok/s? (Chat: 10+. Agents/batch: 5 ok. Coding: 20+ feels right.)
2. Bandwidth ÷ target tok/s = max model bytes you can afford.
3. Max bytes ÷ 0.55 = max params at Q4 (÷ 0.3 for IQ2 if quality allows).
4. Does a model of that size do the task? If not → distill/specialize (Playbook 04/05) or change hardware.
5. Long prompts in the workflow? Check prefill compute too (RAG and agents = long prompts).

#### Hardware cheat sheet (2026-era, single-user inference)
| Box | Sweet spot |
|---|---|
| 8 GB GPU | 7-8B @ Q4, 3B @ Q8 |
| 12-16 GB GPU | 13-14B @ Q4, 8B @ Q6 |
| 24 GB GPU | 32B @ Q4, 70B @ IQ2 (tight) |
| 2× 24 GB | 70B @ Q4 (split) |
| 64-128 GB Mac / DDR5 server | 70B+ @ Q4, slow but roomy |
| Pi 5 / N100 mini-PC | 0.5-3B @ Q4 |

### Iron laws
1. Decode speed = bandwidth ÷ model bytes. Everything else is a footnote.
2. VRAM capacity decides what fits; bandwidth decides how it feels.
3. Prefill and decode are different bottlenecks — benchmark both.
4. A prediction you verified is intuition; one you didn't is superstition.


<br>

---

> ### Status of this playbook
>
> **Still accurate.** The parameter-census and KV-cache maths are architecture
> facts and have not drifted.
>
> **Added:** the profiling stage now has a CUDA-level counterpart. `kernelNsysProfile`
> shows NVTX-annotated phases end to end, and `nsys` is installed at
> `/usr/local/cuda/bin/nsys`:
>
> ```bash
> nsys profile -o /tmp/prof --force-overwrite true python your_script.py
> nsys stats /tmp/prof.nsys-rep
> ```
>
> **Sizing note for this box:** with 15.9 GiB total, the Stage 2 KV-cache maths bites
> early. At 131 KB/token (Llama-3.1-8B, FP16 KV), a 32K context costs 4.3 GB of KV on
> top of the weights — over a quarter of the card before you have loaded anything else.
>
> **Samples that demonstrate this playbook:** `kernelNsysProfile`, `launchConfigTuning`
> (occupancy effects), `memoryResources` (allocator behaviour).
