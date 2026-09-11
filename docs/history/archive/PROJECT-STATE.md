# SyMoNeuRaL — project state

> **Weight filenames in this document predate the 2026-08-20 house-name migration.**
> The files themselves were not modified, only renamed: `Qwen2.5-7B-Instruct-Q4_K_M.gguf`
> is now `symon-1.0-7b-q4_k_m.gguf`, and so on. `backend/models/PROVENANCE.json` is the
> full mapping. This is a dated record of what was observed at the time, so the names in
> it are left as they were read rather than rewritten to match today's disk.

> **⚠ SUPERSEDED by `HANDOVER.md` (2026-08-16, ~19:10). Read that instead.**
> Everything here is folded into it, plus a request-by-request audit, the ten-item work queue,
> and the unattended-run setup. Where the two disagree, **HANDOVER.md wins.**
> This file is kept only as the earlier snapshot.

Written 2026-08-16 as a durable record, because the working context is about to be compacted.

---

## THE ONE BLOCKER

**Everything visible is gated on a `sudo` command that only the user can run.** The webroot is
`www-data`-owned and `sudo` requires a password; the assistant's shell has no TTY, so this
cannot be worked around — it has been attempted and fails with
`sudo: a terminal is required to read the password`.

```bash
sudo /home/google/MIT_AI_Training/MIT_AI_Training/deploy.sh
```

That single command publishes everything below, **including `/docs`**, which was reworked into
static files specifically so it needs no Apache change.

As of the last check the live site was still the 15:53 build: `live 25,554 bytes` vs
`staged 41,715 bytes`; `/docs`, `/console.js`, `/training.html` all 404; zero rack markers on
the live homepage. Every user complaint about "the rack doesn't exist" and "/docs isn't set up"
traces to this and nothing else.

Optional second command — only needed for boot-start/crash-restart, not for the site to work:

```bash
sudo .../ops/deploy/install-service.sh     # systemd unit
sudo .../ops/install-apache.sh      # adds /api/ws + live /docs proxy (static /docs works without it)
```

---

## What exists and is verified

### Site — `site/`, 49 files + `docs/`
| page | contents |
|---|---|
| `index.html` | control board, live rack, NVIDIA stack map, cost comparison, 6 folded detail sections |
| `chat.html` `image.html` `calc.html` `remix.html` | the four API surfaces |
| `training.html` | the manual, rebranded, 750 anchors, 0 MIT references |
| `docs/index.html` | **static** branded Swagger UI + `openapi.json` snapshot |

Generators (all idempotent, all rerunnable):
`build_pages.py` `build_rack.py` `build_console.py` `build_stack.py` `build_cost.py`
`build_training.py`. They rewrite `site/`, so **never run two in parallel**.

### Engines — built for `sm_120`
- `llama.cpp/build/bin/` — `llama-server`, `llama-cli`, `llama-speculative`
- `stable-diffusion.cpp/build/bin/` — `sd-cli`, `sd-server`

### Models — `models/`
- `Qwen2.5-7B-Instruct-Q4_K_M.gguf` (4.68 GB) — served
- `Qwen2.5-14B-Instruct-Q4_K_M.gguf` (8.99 GB) — heavy tier
- `Qwen2.5-0.5B-Instruct-Q4_K_M.gguf` (398 MB) — speculative draft
- `flux1-schnell-q4_k.gguf` + `ae` + `clip_l` + `t5xxl-Q8_0` (12.7 GB) — image
- `training/adapter/symoneural-lora.gguf` (80.7 MB) — the fine-tune

### Measured numbers (all reproduced on this box)
| what | value |
|---|---|
| chat decode, 7B Q4 | 149.6 tok/s baseline · ~104–114 via API with adapter |
| speculative decode, draft depth 2 | **157.4 tok/s, 43.8% accept (+5.2%)** |
| speculative, library default | 139.1 tok/s (−7%) — **default is a net loss here** |
| speculative, depth 5 | 121.4 tok/s (−19%) |
| q8_0 KV cache | 142.7 tok/s (−5%) — a memory win, not a speed win |
| FLUX 768², 4 steps | 9.3–11.1 s |
| RavenCalc | ~0.1 s, self-verifying |
| GPU handoff drain | ~1 s to the 1.5 GB floor, 3/3 cycles no OOM |

### LoRA
Loss 2.51 → 1.25, 3 epochs, 354 s, 40.4 M trainable (0.53%). Refuses to invent pricing;
says "No" with arithmetic when pushed on a 70B/16 GB question. **Do not merge-and-requantize** —
it measurably degraded the refusal; the adapter is served at runtime instead, costing ~25%
throughput, which is the correct trade for a bot that must not fabricate prices.

---

## Open items, in the order I would do them

1. **CUDA occupancy bug** — real, found against the CUDA guide.
   `symoneural_reinforce/symoneural/compute/ops.py:259` hardcodes `sm_count * 2` for the
   cooperative grid. Guide (~p.36990) requires computing it via
   `cudaOccupancyMaxActiveBlocksPerMultiprocessor × multiProcessorCount`, because occupancy
   depends on the kernel's register/shared-memory use. If a kernel edit drops occupancy to
   1 block/SM, `grid.sync()` fails to launch or hangs. `cuOccupancyMaxActiveBlocksPerMultiprocessor`
   IS available in the installed bindings. Blocked on: `KernelCache(arch: str)` takes an arch
   string, not a context — construction shape needs sorting before the fix can be tested.
   *Verified correct by contrast:* cc 12.0 max shared memory is 100 KB/SM (sizes 0/8/16/32/64/100),
   matching the site's `102,400 B per SM`.
2. **NVIDIA skills catalog** — cloned at `skills/`, 337 skills, official + verified.
   ~15 match this stack (`tilegym-improve-cutile-kernel-perf`, `warp-compile-time-optimizer`,
   `nemo-mbridge-perf-cuda-graphs`, the `dynamo-*` set). Install via
   `npx skills@latest add nvidia/skills`, then `/reload-skills`.
3. **Instrument-style hardware panels** — push the spec/status readouts further toward the
   control-room look.
4. **Nemotron** at `Nemotron-main/` — for the multi-agent MoE routing work.

## Assessed and rejected, with reasons

- **NVFP4** — hardware supports it (Blackwell sm_120, `cuda_fp4.h` ships in CUDA 13.3) but
  **GGML has no FP4 path**, so the serving runtime cannot reach it. Would require TensorRT-LLM
  (drags torch into the serving path) or hand-written CUTLASS FP4 kernels. Marked
  "not implemented" on the site rather than quietly omitted.
- **Qwen3-Next-80B-A3B** — does not fit. 80 B at Q4 ≈ 44 GB, at IQ2 ≈ 24 GB, against 15.92 GiB.
  Sparse activation (3 B/token) does not help: all 80 B must be *resident* to route into.
  Its 512-expert routing also assumes NVLink at 1.8 TB/s; this box has PCIe Gen 3 ×8 at ~7 GB/s.
  **The transferable idea is the architecture, not the model** — routing between specialist
  agents (chat / calc / image / remix) is already a coarse MoE, and RavenCalc-as-expert is
  exactly that pattern.
- **NVLink / distributed serving / NCCL / NIXL / disaggregated serving / KV-aware routing** —
  all coordinate multiple GPUs. There is one GPU.

## Rules that must not be re-broken

- Lock the GPU **per job, never for a process lifetime**. Residency ≠ work. See `CLAUDE.md`.
- Never call a bare `gpu-governor.sh release` — always name the surface.
- Base Python interpreter stays at exactly 7 packages. The API runs on the system interpreter
  (fastapi/uvicorn/sympy are OS packages); training has its own venv.
- Label every published figure measured / vendor / projected. Never present a projection as a
  result. Publish the negatives — they are the credibility.
