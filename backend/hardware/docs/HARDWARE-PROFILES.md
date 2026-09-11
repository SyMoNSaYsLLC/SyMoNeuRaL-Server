# SyMoNeuRaL Hardware Profiles — the contract

**Status: stub. A contract for something not yet built, not a description of current state.**

The other two files in this directory — `EXPORTS.md` and `MEASUREMENTS.md` — are rules in
force. This one is a target. Studio's target resolution depends on it; see
`backend/studio/docs/symoneural-studio-upgrade-scope.md` §5-6 and the planned
`GET /api/studio/hardware/profiles`.

---

## `cloud` — SyMoNeuRaL-hosted worker/GPU

Fields: profile id · `target: cloud` · `queue_required: true` · GPU vendor/name · VRAM ·
CUDA/ROCm/Metal availability · model allowlist · timeout and admission policy.

The customer never gets raw ComfyUI, raw CUDA, raw filesystem or raw GPU access. Admission is
refused **before** the job is admitted, with the arithmetic, rather than killed part-way.

## `local_customer` — unknown customer hardware

**Browser-only detection is approximate. A real probe requires a local helper or agent.** The
two tiers are never conflated in the UI, because a browser reading presented as a measurement
is the labelling failure this repo already bans.

| Tier | Can know | Label |
|---|---|---|
| Browser-only | WebGL/WebGPU adapter strings, rough device class. No VRAM, no driver version, no CUDA. | **approximate** |
| Local helper/agent/CLI/desktop companion | A real probe — it is a process on the machine. | **measured** |

Probe report fields: OS · CPU · RAM · GPU vendor/name · VRAM · driver version ·
CUDA/ROCm/Metal availability · Python/runtime availability · disk space.

An unknown profile resolves to `NEEDS_LOCAL_AGENT`. That is a **state, not an error**, and not
a licence to guess.

## `local_owner_nvidia` — Garrett's known NVIDIA worker

```
profile id: rtx5070ti-16gb
```

- NVIDIA/CUDA path. Current class: RTX 5070 Ti, 16 GB.
- **No CPU fallback for GPU workloads unless explicitly authorized.** A silent fallback turns
  a four-second render into a twenty-minute one and reports success.
- **Same queue contract as cloud**, marked owner/local.
- **Owner/local is not a raw GPU endpoint.** It inherits the single-card lock every surface on
  this box holds (`ENGINEERING.md`): 16303 MiB, one card, and a Studio job queues behind
  chat, training and the miner. RavenCalc stays the exception it already is — CPU symbolic
  algebra, never takes the lock.

**Treated as a known profile rather than probed every time.** It is the one machine whose
numbers are measured rather than reported by a helper.

## `auto`

Not a profile. A request for the resolver to choose one of the three, resolved once and
**recorded on the job** — a run that silently went to cloud because local was busy is a figure
without its label. Cloud fallback is explicit, never automatic billing or automatic execution.

## The honesty rule

**A badge or gauge comes from registry metadata, probe data, or an explicit unknown state.**
Nothing else may light it. No decorative readiness indicators: `.claude/CLAUDE.md` bans them
sitewide and a hardware badge is the easiest place on this surface to break that, because a
missing field renders as green unless something stops it.
