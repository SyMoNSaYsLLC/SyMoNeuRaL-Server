# GPU Governor — responsibilities, and the contract for what it grows into

**Status: stub for the Studio/Runtime upgrade scope. Not a description of current behaviour.**

**Read the authority first, not this file.** Two things already own this subject and neither is
superseded here:

1. **`ENGINEERING.md`, "The GPU is a single, contended resource"** — the rules in force.
   R-180 moved them there verbatim; they are not restated here, because a second copy is the
   drift `.claude/CLAUDE.md` bans second state documents to prevent.
2. **`scripts/gpu-governor.sh`** — what the machine actually does. Where this file and the
   script disagree, **the script is right and this file is a wish.**

This document exists only to name the responsibilities the runtime router and hot-swap manager
will need from the governor, so `backend/hardware/docs/symoneural-model-hot-swap.md` has something to
point at. Contracts, not behaviour.

---

## What is already true and must not be re-litigated

From `ENGINEERING.md`, summarised as pointers rather than copied:

- One RTX 5070 Ti, 15.92 GiB. Chat ~5 GB, image ~7 GB, a QLoRA run ~12 GB — **they cannot
  coexist.** Any multi-model residency claim starts from that sentence.
- Everything touching the GPU goes through the governor, ideally
  `gpu-governor.sh with <surface> -- <cmd>`, which releases even on crash.
- **Hold the lock for a job, never for a process lifetime.** Residency and work are separate.
- **Never call a bare `release`** — name the surface.
- Drain waits on **compute** memory (`--query-compute-apps`), not `--query-gpu=memory.used`,
  with a 1 GB floor. The whole-card reading includes this box's desktop session; measuring it
  card-wide once made `/api/chat` answer 500 for an afternoon (R-171).
- `train` is never evicted to serve a page view.
- RavenCalc never takes the lock.

## Measured state of the governor, 2026-08-22 at `41524770`

Read from `./scripts/gpu-governor.sh status`, not asserted:

```
resident surface   image (not running -- stale marker)
lock               free
vram used          959 MiB  (whole card, desktop included)
  of which compute 0 MiB  (CUDA contexts -- what drain waits on, floor 1024 MiB)
vram free          14900 MiB
```

Two things worth reading twice. `run/resident` says `image`, and **no image process exists** —
and the governor *says so itself*, in the same line, unprompted. That is R-172's fix working:
`SMOKE-governor-evict.md` records the earlier behaviour, where an eviction over a dead marker
reported success having freed nothing. **This is the honest-failure machinery working, not a
defect.** And `run/gpu.lock.d` is absent, which is what a free lock looks like.

## Responsibilities the runtime layer needs

Contracts. Several already exist in the script; none is re-implemented by this document.

| Responsibility | Status |
|---|---|
| **VRAM admission check** — refuse *before* admitting, with the arithmetic | partly exists (`plan_residency`); **mandatory** for the owner profile |
| **Process lease** — one job, released on crash | **exists** (`with <surface> -- <cmd>`) |
| **Timeout** | exists on acquire |
| **Queue / admission control** | needed — the job queue is not the governor's today |
| **Runtime health checks** | needed, per `backend/hardware/docs/RUNTIME-PROFILES.md` `health_endpoint` |
| **`nvidia-smi` metrics** | exists — and must stay `--query-compute-apps`, per R-171 |
| **Model load/unload accounting** | needed — the governor knows about *surfaces*, not models |
| **Concurrency classes** — `llm`, `image`, `asr`, `embedding`, `utility` | needed; today the unit is the surface |

## Rules for the contract

- **No CPU fallback for owner GPU workloads unless explicitly authorized.** A silent fallback
  turns a four-second render into a twenty-minute one and reports success. The audit confirms
  the code has none today: all eight CPU-device sites are in `training/` and are deliberate
  shard offload.
- **VRAM admission is mandatory on `local_owner_nvidia`.** Not advisory.
- **Large image + large LLM concurrency is not assumed.** It must be *measured* before it is
  called green — see the ladder in `RUNTIME-PROFILES.md`.
- **A model-level accounting layer does not replace the surface lease.** The governor's unit is
  the process holding the card; the hot-swap manager's unit is the model. Both are needed, and
  conflating them loses the crash-safety the lease provides.
- **CUDA graphs / MPS / TensorRT experiments only after benchmark proof.** NVIDIA samples and
  tools are diagnostic and benchmark references; sample source is not imported into product
  logic without a license and security review (`test_references_boundary.py:70` enforces the
  `references/` boundary already).

## A defect this scope found in the authority document

`ENGINEERING.md`, "Python environments", pins the CUDA sample venv and gives the check:

```bash
contrib/cuda-samples/python/.venv/bin/pip freeze | wc -l    # expect exactly 7
```

**`contrib/` does not exist on this box.** The command cannot run, so the rule cannot be
verified. The passage is otherwise careful — it corrects an earlier, wronger version of itself
in the same paragraph — which is why this is worth naming rather than quietly working around.
Recorded in `ops/audits/BOX-REALITY-AUDIT.md` §8.3. **Not fixed here:** `ENGINEERING.md` is the
authority document and editing it is outside this scope's allowed file list.
