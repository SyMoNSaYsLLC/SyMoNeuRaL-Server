"""The ten-agent platform: roles, model tiers, and residency budgets.

The platform coordinates ten autonomous agents. The orchestrator does not run
them all at once — it *cannot*, and that constraint drives the whole design.

**The residency problem.** This box has 15.9 GiB of VRAM, of which ~14.2 GiB is
free in practice. Model tiers at Q4:

===========  ========  ====================================================
tier         ~VRAM     what fits alongside it
===========  ========  ====================================================
1.5B         0.9 GB    almost anything
7B           3.9 GB    a 1.5B specialist and comfortable KV headroom
14B          7.7 GB    a 1.5B specialist, tight KV headroom
===========  ========  ====================================================

A realistic steady state is **one heavy resident (7B or 14B) plus the 1.5B
specialist**, roughly 4.8–8.6 GB, leaving 5–9 GB for KV cache and activations.
Agents that need neither model are CPU/IO-bound and cost no VRAM at all.

**Why eviction is expensive here.** Swapping a resident model out and another
in crosses the PCIe link, which this host caps at **Gen 3 x8, ~7 GB/s
measured**. Evicting a 7B (3.9 GB) and loading another costs ~1.1 s of pure
transfer — roughly 560 ms each way. That is not a cache miss, it is a stall
longer than most inference requests. The router therefore treats eviction as a
last resort and prefers queueing behind a resident model.

Compare: once resident, the same model is read at ~752 GB/s. The ratio between
resident and non-resident access on this box is about **107x**.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Tier(str, Enum):
    """Compute class an agent needs."""

    NONE = "none"          # no model; pure CPU/IO work
    SPECIALIST = "1.5b"    # low-latency classification and routing
    RESIDENT = "7b"        # the default workhorse
    HEAVY = "14b"          # deep reasoning, synthesis, fine-tune supervision


#: Approximate VRAM cost per tier at Q4, in bytes. Weights only — KV cache and
#: activations are budgeted separately by the router.
TIER_VRAM: dict[Tier, int] = {
    Tier.NONE: 0,
    Tier.SPECIALIST: int(0.9 * 2**30),
    Tier.RESIDENT: int(3.9 * 2**30),
    Tier.HEAVY: int(7.7 * 2**30),
}


class Workload(str, Enum):
    """What kind of work a request is, independent of which agent handles it."""

    CLASSIFY = "classify"        # short in, short out, latency-critical
    EXTRACT = "extract"          # structured output from a document
    GENERATE = "generate"        # open-ended text
    REASON = "reason"            # multi-step, quality over latency
    TELEMETRY = "telemetry"      # ingest and aggregate; no model
    CONTROL = "control"          # leases, licences, provisioning; no model
    VERIFY = "verify"            # cryptographic / state checks; no model
    TRAIN = "train"              # fine-tune orchestration


@dataclass(frozen=True)
class Agent:
    """One specialised worker."""

    name: str
    role: str
    tier: Tier
    workloads: tuple[Workload, ...]
    #: Requests per second this agent is expected to sustain. Used only for
    #: relative load-shedding decisions, not as a promise.
    nominal_rps: float
    #: True when the agent must run on the local GPU rather than being
    #: eligible for offload to leased capacity.
    gpu_local: bool = False
    #: Agents that must be healthy for this one to function.
    depends_on: tuple[str, ...] = ()
    #: False for agents that are scheduled rather than served on demand. The
    #: router will not hand these an interactive request even when they are
    #: the only match for its workload class -- a fine-tune supervisor is not
    #: a chat backend just because both can be labelled "reasoning".
    interactive: bool = True
    notes: str = ""

    @property
    def vram_bytes(self) -> int:
        return TIER_VRAM[self.tier]

    @property
    def needs_model(self) -> bool:
        return self.tier is not Tier.NONE


#: The ten agents. Order is stable and meaningful: 01–03 are the data plane,
#: 04–06 the control plane, 07–08 the model plane, 09–10 the safety net.
AGENTS: tuple[Agent, ...] = (
    Agent(
        name="telemetry-ingest",
        role="Receives metric and event streams, normalises them, and writes "
             "batched records downstream. Never blocks on a model.",
        tier=Tier.NONE,
        workloads=(Workload.TELEMETRY,),
        nominal_rps=5000.0,
        notes="Highest request rate on the platform. Kept model-free "
              "deliberately so a busy GPU can never stall ingestion.",
    ),
    Agent(
        name="telemetry-classify",
        role="Labels incoming telemetry (severity, subsystem, anomaly/normal) "
             "for routing and alerting.",
        tier=Tier.SPECIALIST,
        workloads=(Workload.CLASSIFY,),
        nominal_rps=200.0,
        gpu_local=True,
        depends_on=("telemetry-ingest",),
        notes="The canonical 1.5B case: short prompts, short outputs, latency "
              "matters more than depth. Runs on the always-resident specialist.",
    ),
    Agent(
        name="telemetry-summarise",
        role="Rolls classified telemetry into periodic digests and incident "
             "narratives.",
        tier=Tier.RESIDENT,
        workloads=(Workload.GENERATE, Workload.EXTRACT),
        nominal_rps=2.0,
        gpu_local=True,
        depends_on=("telemetry-classify",),
        interactive=False,
        notes="Batch-friendly and latency-tolerant, so it queues behind "
              "interactive work rather than triggering an eviction.",
    ),
    Agent(
        name="akash-lease",
        role="Negotiates and renews GPU capacity leases on the Akash network; "
             "tracks bid state, deployment health and spend.",
        tier=Tier.NONE,
        workloads=(Workload.CONTROL,),
        nominal_rps=0.2,
        interactive=False,
        notes="STUB — no network client is implemented. See "
              "docs/06-agent-platform.md for exactly what is and is not built.",
    ),
    Agent(
        name="capacity-planner",
        role="Decides local-versus-leased placement from queue depth, VRAM "
             "headroom and the PCIe transfer budget.",
        tier=Tier.SPECIALIST,
        workloads=(Workload.CLASSIFY, Workload.CONTROL),
        nominal_rps=5.0,
        gpu_local=True,
        depends_on=("akash-lease", "telemetry-ingest"),
        notes="Consumes the live hardware dossier. The 7 GB/s PCIe ceiling is "
              "the dominant term whenever offload is considered.",
    ),
    Agent(
        name="tron-licence",
        role="Validates entitlement against the TRON TVM contract before any "
             "protected checkpoint is unsealed.",
        tier=Tier.NONE,
        workloads=(Workload.VERIFY, Workload.CONTROL),
        nominal_rps=1.0,
        notes="STUB — verification is pluggable and denies by default. No "
              "chain client, no keys. See agents/licensing.py.",
    ),
    Agent(
        name="weight-custodian",
        role="Holds encrypted checkpoints at rest and unseals them into VRAM "
             "only after the licence agent returns a positive verification.",
        tier=Tier.NONE,
        workloads=(Workload.VERIFY,),
        nominal_rps=0.5,
        depends_on=("tron-licence",),
        notes="Fernet envelope. NOTE: Fernet is AES-128-CBC + HMAC-SHA256, "
              "not AES-256; an AES-256-GCM path is provided separately. "
              "Plaintext in VRAM is readable by anyone who can attach to this "
              "process — this raises copying cost, it is not DRM.",
    ),
    Agent(
        name="finetune-orchestrator",
        role="Plans and supervises QLoRA runs: dataset staging, adapter "
             "lifecycle, checkpoint promotion.",
        tier=Tier.HEAVY,
        workloads=(Workload.TRAIN, Workload.REASON),
        nominal_rps=0.05,
        gpu_local=True,
        depends_on=("weight-custodian", "capacity-planner"),
        interactive=False,
        notes="The only agent that legitimately wants the 14B tier and "
              "sustained exclusive VRAM. Scheduled, never interactive.",
    ),
    Agent(
        name="state-verifier",
        role="Writes append-only verification records for every unseal, "
             "lease change and adapter promotion.",
        tier=Tier.NONE,
        workloads=(Workload.VERIFY, Workload.TELEMETRY),
        nominal_rps=50.0,
        depends_on=("weight-custodian",),
        notes="The secure file daemon. Model-free so the audit trail survives "
              "GPU exhaustion — an audit log that fails under load is useless.",
    ),
    Agent(
        name="fallback-router",
        role="Absorbs work when a preferred agent is saturated, evicted or "
             "unhealthy; degrades tier rather than dropping the request.",
        tier=Tier.SPECIALIST,
        workloads=tuple(Workload),
        nominal_rps=100.0,
        gpu_local=True,
        notes="Accepts every workload class by design. Degrading a REASON "
              "request to the 1.5B specialist is better than a 1.1 s eviction "
              "stall or a dropped request.",
    ),
)

AGENTS_BY_NAME: dict[str, Agent] = {a.name: a for a in AGENTS}


def agents_for(workload: Workload) -> list[Agent]:
    """Agents that accept *workload*, best-specialised first.

    ``fallback-router`` accepts everything, so it always sorts last among
    equals — it is the safety net, not a first choice.
    """
    matches = [a for a in AGENTS if workload in a.workloads]
    return sorted(matches, key=lambda a: (len(a.workloads), -a.nominal_rps))


def resident_budget(free_bytes: int, kv_reserve_fraction: float = 0.35
                    ) -> dict[str, int]:
    """Split free VRAM into a weights budget and a KV/activation reserve.

    The reserve is not optional. KV cache grows with context and is the term
    that turns a working configuration into an out-of-memory one mid-session.
    """
    reserve = int(free_bytes * kv_reserve_fraction)
    return {
        "free_bytes": free_bytes,
        "weights_budget": free_bytes - reserve,
        "kv_reserve": reserve,
    }


def plan_residency(free_bytes: int) -> dict[str, object]:
    """Which tiers to keep co-resident in *free_bytes*.

    Priority order, and the reasoning behind it:

    1. **SPECIALIST always.** It is the fallback target. If it has to be paged
       in during a fallback, the fallback itself stalls — which defeats the
       purpose of having one.
    2. **RESIDENT (7B) next.** It is the documented default for general work,
       so it serves the largest share of traffic. Keeping it loaded is worth
       more than keeping a bigger model that most requests will not use.
    3. **HEAVY (14B) only if all three fit.**

    An earlier version picked the largest model that fit and produced
    ``1.5B + 14B``, leaving the *default* tier non-resident. Every ordinary
    ``generate`` request then degraded to the 1.5B specialist — technically
    "no eviction", but the wrong answer for the common case. Greedy-by-size is
    the wrong objective; greedy-by-traffic-share is the right one.
    """
    budget = resident_budget(free_bytes)
    w = budget["weights_budget"]
    spec = TIER_VRAM[Tier.SPECIALIST]
    res = TIER_VRAM[Tier.RESIDENT]
    heavy = TIER_VRAM[Tier.HEAVY]

    if w >= spec + res + heavy:
        plan = [Tier.SPECIALIST, Tier.RESIDENT, Tier.HEAVY]
    elif w >= spec + res:
        plan = [Tier.SPECIALIST, Tier.RESIDENT]
    elif w >= spec + heavy:
        # Odd shape, but possible: room for the big one but not the middle.
        plan = [Tier.SPECIALIST, Tier.HEAVY]
    else:
        plan = [Tier.SPECIALIST]

    used = sum(TIER_VRAM[t] for t in plan)
    return {
        **budget,
        "resident_tiers": [t.value for t in plan],
        "heavy_tier": Tier.HEAVY.value if Tier.HEAVY in plan else None,
        "weights_used": used,
        "weights_headroom": w - used,
        # Whether the heavy tier could be swapped in later, not whether it is
        # loaded now.
        "can_host_heavy": w >= spec + heavy,
    }
