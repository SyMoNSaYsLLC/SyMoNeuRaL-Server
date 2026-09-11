# Playbook 10 — Edge Deployment

> Part of the [symoneural_reinforce documentation set](README.md). Sliced from the consolidated manual at `../../../../../docs/symoneural-manual.md`, which remains the canonical single file.

[< Playbook 09 — Agents & Orchestration on Local Models](playbook-09.md)

## Playbook 10 — Edge Deployment
#### The last mile: Pi, Jetson, mini-PCs, phones, pure CPU, and ternary models

Everything converges here. You have a small specialist (P04/P05), aggressively quantized (P00), and you understand the bandwidth math (P01). Now you put it on hardware that fits in your hand — and verify it earns its watts.

---

### Stage 0 — Match target to expectation (Playbook 01 applied)

| Target | Bandwidth | Realistic 2026 workload |
|---|---|---|
| Raspberry Pi 5 (8/16GB) | ~17 GB/s | 0.5-3B @ Q4: 4-30 tok/s. Classifiers, extractors, home automation brains |
| N100/N150 mini-PC | ~30-38 GB/s | 3-4B comfortable, 7-8B slow-but-usable |
| Jetson Orin Nano/NX | 68-102 GB/s + GPU | 7-8B @ Q4 at chat speed; vision models |
| Modern phone (flagship) | 50-77 GB/s | 1-4B on-device via ExecuTorch/LiteRT |
| Old desktop, DDR4 | ~40-50 GB/s | 7-8B @ Q4 ≈ 8-12 tok/s — don't sneer at e-waste |
| Small FPGA (Zynq) | — | NOT an LLM host. Small quantized CNNs/MLPs (P00 Stage 5) |

Predict tok/s with Formula 2 before buying anything.

---

### Stage 1 — CPU-only mastery with llama.cpp (1 evening, works on everything)

llama.cpp's CPU path is the universal edge runtime. The knobs:

```bash
# Build with native optimizations on the TARGET device
cmake -B build -DCMAKE_BUILD_TYPE=Release && cmake --build build -j

# Run — threads matter enormously:
./build/bin/llama-bench -m qwen2.5-1.5b-q4km.gguf -t 4      # try t = physical cores
# On big.LITTLE ARM (Pi, phones): threads > perf-cores HURTS. Sweep -t 2..8 and graph it.
```

CPU-specific truths:
- Q4_K_M is usually the CPU sweet spot; sub-3-bit quants can be SLOWER on CPU (dequant overhead) while saving RAM — measure, don't assume
- RAM speed ≈ tok/s: on a desktop, enabling XMP/faster DIMMs is a legitimate inference upgrade
- `--mlock` prevents the OS from paging weights out mid-generation

**Deliverable:** thread-sweep graph + quant-format table on your weakest machine.

---

### Stage 2 — Raspberry Pi / mini-PC as an always-on model server (1 evening)

The killer edge pattern isn't chat on the Pi — it's the Pi as a **24/7 specialist endpoint** for your network (your P04 specialist, always on, ~5W).

```bash
# On the Pi (64-bit OS):
sudo apt install -y build-essential cmake git
git clone https://github.com/ggerganov/llama.cpp && cd llama.cpp
cmake -B build -DCMAKE_BUILD_TYPE=Release && cmake --build build -j4

./build/bin/llama-server -m specialist-1.5b-q4km.gguf -t 4 -c 2048 --host 0.0.0.0 --port 8080
```

Make it a service (systemd) so it survives reboots:
```ini
# /etc/systemd/system/llm.service
[Unit]
Description=Edge LLM server
After=network.target
[Service]
ExecStart=/home/pi/llama.cpp/build/bin/llama-server -m /home/pi/models/specialist.gguf -t 4 -c 2048 --host 0.0.0.0 --port 8080
Restart=always
[Install]
WantedBy=multi-user.target
```

Then measure what matters at the edge: sustained tok/s after 10 minutes (thermal throttling is real — add a heatsink), watts at the wall if you have a meter, and requests/day it can absorb. A Pi 5 running a 1.5B specialist handles thousands of extraction/classification calls daily.

**Deliverable:** a systemd-managed endpoint + cold/warm/10-min-sustained tok/s numbers.

---

### Stage 3 — Ternary on CPU: the BitNet path (half a day)

The 2026 frontier of edge inference: models trained ternary (P00 Stage 4) run shockingly fast on plain CPUs because weights are ~1.58 bits and matmuls become add/subtract-dominated.

```bash
git clone https://github.com/microsoft/BitNet && cd BitNet
# Follow repo setup; fetch an official ternary checkpoint (e.g., the 2B-class b1.58 models)
# then benchmark with its CPU inference path and compare against a same-size Q4 GGUF model.
```

What to note: tokens/sec, RAM footprint, and quality on YOUR eval prompts vs a conventional 4-bit peer. Ternary models trade some quality ceiling for radical efficiency — the right call for fixed narrow tasks, wrong for open-ended assistants. This is the technology to track hardest through 2026-27; native ternary + NPUs is where edge is heading.

**Deliverable:** ternary-vs-Q4 comparison table (speed, RAM, quality on 20 prompts).

---

### Stage 4 — Phones & NPUs (survey + one path)

- **ExecuTorch** (PyTorch): export → quantize (int8/int4) → run via Android/iOS runtime with NPU delegates where available
- **LiteRT** (ex-TFLite): mature delegate ecosystem (NNAPI/CoreML/GPU)
- Pragmatic shortcut: several apps wrap llama.cpp on-device (GGUF straight onto the phone) — fine for prototyping before committing to a toolchain
- NPUs (2026 laptops/phones) excel at int8/int4 with vendor toolchains; portability is still rough — budget integration time accordingly

**Deliverable (choose one):** a 1-3B model generating text on an actual phone, whichever path.

---

### Stage 5 — The capstone: end-to-end proof

Combine the entire manual once, small scale, no steps skipped:

1. Pick a real recurring task from your own life/projects (log triage, note tagging, calendar text parsing…)
2. Distill it: teacher generates data (P05) → filter → QLoRA a 1-2B student (P04)
3. Quantize to Q4/IQ3 with imatrix (P00) and needle/eval-test it (P06/P04)
4. Deploy as a systemd endpoint on the smallest box that meets your tok/s floor (P01 math first)
5. Wire one agent or script to call it (P09), with verification
6. Write the one-page postmortem: predicted vs measured at every stage

Finish that and you haven't read about this field — you've done the whole thing, end to end, on hardware you own.

### Iron laws
1. Bandwidth math first, purchase second.
2. Sustained (thermal-throttled) performance is the real number at the edge.
3. On CPU, the fastest quant is not always the smallest — measure dequant overhead.
4. The edge pattern that wins is the always-on specialist endpoint, not chat on a Pi.
5. Ternary + NPU is the trajectory; build the skills now on BitNet-class tools.


---
