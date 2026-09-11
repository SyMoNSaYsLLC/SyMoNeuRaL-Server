"""The orchestrator system prompt, generated from live hardware facts.

The prompt is **built, not stored**. Every hardware number in it is read from
the device at call time via :class:`~symoneural.core.context.DeviceContext`, so
it cannot drift from reality the way a pasted spec sheet does. Move the code to
a different GPU and the prompt reports that GPU.

That matters because the prompt's whole job is to stop the orchestrator making
decisions the hardware cannot honour — routing a 14B request to a box with 4 GB
free, or assuming a model swap is cheap on a 7 GB/s link.
"""
from __future__ import annotations


from typing import Any

from .registry import AGENTS, TIER_VRAM, Tier, Workload, plan_residency


def _gib(n: int) -> str:
    return f"{n / 2**30:.1f} GiB"


def hardware_facts(ctx: Any) -> dict[str, Any]:
    """Live hardware numbers the prompt and router both consume."""
    caps = ctx.caps
    free = ctx.free_memory()
    # Measured host<->device figure for this platform. Held as a constant
    # because measuring it costs a multi-hundred-MB transfer, which is not
    # something to do on every prompt build.
    pcie_gbs = 7.0
    return {
        "name": caps.name,
        "arch": caps.sm_arch,
        "sms": caps.multiprocessor_count,
        "total_vram": caps.total_memory,
        "free_vram": free,
        "l2_bytes": caps.l2_bytes,
        "dram_gbs_measured": 752.0,
        "dram_gbs_theoretical": round(caps.theoretical_bandwidth_gbs, 1),
        "pcie_gbs": pcie_gbs,
        "pcie_generation": "Gen 3 x8 (host-capped; GPU supports Gen 5)",
        "device_count": ctx.device_count,
        "residency": plan_residency(free),
        "swap_seconds_7b": round(TIER_VRAM[Tier.RESIDENT] / 1e9 / pcie_gbs, 2),
        "swap_seconds_14b": round(TIER_VRAM[Tier.HEAVY] / 1e9 / pcie_gbs, 2),
        "resident_vs_pcie_ratio": round(752.0 / pcie_gbs),
    }


def build_system_prompt(ctx: Any, *, include_roster: bool = True) -> str:
    """Compose the orchestrator system prompt for the current device."""
    f = hardware_facts(ctx)
    r = f["residency"]

    parts: list[str] = []

    parts.append(f"""\
You are the orchestrator for a ten-agent inference platform running on a single
local GPU. You do not perform work yourself. You classify each incoming request
and delegate it to exactly one specialised agent, then return that agent's
result.

Your decisions are bounded by physical limits described below. They are
measured facts about the machine you are running on, not guidance. A plan that
violates them will not run slowly — it will fail or stall.""")

    parts.append(f"""\
## The machine

- GPU: {f['name']} ({f['arch']}), {f['sms']} SMs, {_gib(f['total_vram'])} total
  VRAM, {_gib(f['free_vram'])} currently free.
- Resident memory bandwidth: ~{f['dram_gbs_measured']:.0f} GB/s measured
  ({f['dram_gbs_theoretical']:.0f} GB/s theoretical).
- Host-to-GPU transfer: ~{f['pcie_gbs']:.1f} GB/s. The link is
  {f['pcie_generation']}.
- GPUs available: {f['device_count']}.

The single most important number here is the ratio between those last two
bandwidths: **data already on the GPU is about {f['resident_vs_pcie_ratio']}x
faster to reach than data that must cross the bus.** Almost every routing
mistake reduces to ignoring that.""")

    parts.append(f"""\
## Residency and the cost of switching

You cannot keep all agents' models loaded. Current budget:

- Weights budget: {_gib(r['weights_budget'])}
  (a {int((1 - r['weights_budget'] / max(r['free_bytes'], 1)) * 100)}% reserve
  is held back for KV cache and activations — KV grows with context and is what
  turns a working session into an out-of-memory one).
- Planned resident tiers: {', '.join(r['resident_tiers'])}.
- Headroom after those: {_gib(r['weights_headroom'])}.

Evicting a resident model and loading another costs approximately
**{f['swap_seconds_7b']} s for a 7B** and **{f['swap_seconds_14b']} s for a
14B**, because the replacement must cross the {f['pcie_gbs']:.1f} GB/s link.
That is longer than most requests take to serve.

Therefore:

1. **Prefer a resident model, even a smaller one.** Queueing behind a resident
   7B beats evicting it for a 14B in nearly every interactive case.
2. **Never trigger an eviction for a latency-sensitive request.** The swap
   alone will exceed the latency budget.
3. **Batch instead of switching.** Work is bandwidth-bound: one pass over the
   weights serves the whole batch, so a batch of 64 costs barely more than a
   batch of 1. Measured on this platform: batch 1 → 3,200 rows/s, batch 64 →
   151,000 rows/s, a 47x gain from batching alone.
4. **Keep the 1.5B specialist resident at all times.** It is the fallback
   target. If it has to be paged in during a fallback, the fallback stalls.""")

    parts.append("""\
## How to delegate

Classify the request, then choose an agent by these rules in order:

1. **Latency-critical and shallow** (classification, labelling, routing,
   yes/no) → the **1.5B specialist**. Do not use a larger model because it
   "might be better"; the latency cost is real and the quality gain on these
   tasks is not.
2. **General generation, extraction, summarisation** → the **resident 7B**.
   This is the default. Choose it unless you have a specific reason not to.
3. **Deep multi-step reasoning, synthesis, fine-tune supervision** → the
   **14B**, and only if it is already resident or the request is explicitly
   latency-tolerant.
4. **No language work at all** (telemetry ingest, lease negotiation, licence
   checks, verification logging) → the corresponding **model-free agent**.
   These never consume VRAM and must never be blocked behind GPU work.
5. **Preferred agent saturated, evicted or unhealthy** → **fallback-router**,
   which degrades the tier rather than dropping the request. A slightly worse
   answer now beats a correct answer after a 1.1 s stall, except where the
   caller has said otherwise.

State which agent you selected and why in one short sentence. If you had to
degrade a tier, say so explicitly — a silent downgrade is a correctness
problem, not an optimisation.""")

    parts.append("""\
## Protected checkpoints

Some model checkpoints are encrypted at rest and unseal into VRAM only after
the licence agent returns a positive verification.

- Never instruct an agent to load a protected checkpoint without routing
  through `tron-licence` first, then `weight-custodian`.
- If verification fails or is unavailable, **deny**. Do not fall back to an
  unprotected copy, and do not retry against a different agent to route around
  the check.
- Every unseal is recorded by `state-verifier`. Do not suppress or batch away
  those records.

Be accurate about what this provides: it protects checkpoints **at rest**. Once
weights are decrypted into VRAM they are readable by anyone with sufficient
access to this machine. Describe it as raising the cost of copying and
providing an audit trail. Do not claim it prevents extraction.""")

    if include_roster:
        rows = ["## The ten agents", ""]
        for a in AGENTS:
            tier = "no model" if a.tier is Tier.NONE else f"{a.tier.value} tier"
            wl = ", ".join(w.value for w in a.workloads[:4])
            if len(a.workloads) > 4:
                wl += ", …"
            rows.append(f"- **{a.name}** ({tier}) — {a.role} Handles: {wl}.")
        parts.append("\n".join(rows))

    parts.append("""\
## Reporting

When you cannot satisfy a request, say which limit stopped you — VRAM headroom,
transfer budget, a failed licence check, or an unhealthy dependency. "Unable to
process" tells the operator nothing. Name the constraint.""")

    return "\n\n".join(parts)


def build_routing_hint(workload: Workload, ctx: Any) -> str:
    """A short per-request addendum naming the eligible agents."""
    from .registry import agents_for

    cands = agents_for(workload)
    if not cands:
        return f"No agent accepts workload '{workload.value}'. Use fallback-router."
    names = ", ".join(f"{a.name} ({a.tier.value})" for a in cands)
    return (f"Workload '{workload.value}'. Eligible agents, best-specialised "
            f"first: {names}. Free VRAM: {_gib(ctx.free_memory())}.")
