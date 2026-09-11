"""The routing engine.

Picks one agent per request from workload class, live VRAM headroom, current
residency and agent load. Every decision carries a reason string, because a
router that cannot explain itself cannot be debugged.

**The rule that does the most work:** never evict for a latency-sensitive
request. On this host a 7B swap costs ~560 ms each way at 7 GB/s, which
exceeds the entire latency budget of an interactive call. Degrading the tier is
almost always the better trade, and the router says so when it does.
"""
from __future__ import annotations


import threading
import time
from dataclasses import dataclass, field

from ..core.errors import SchedulerError
from .registry import (
    AGENTS_BY_NAME,
    TIER_VRAM,
    Agent,
    Tier,
    Workload,
    agents_for,
    plan_residency,
)

#: Measured host<->device bandwidth, bytes/s. Governs swap cost estimates.
PCIE_BYTES_PER_SEC = 7.0e9

#: A request is latency-sensitive below this budget, in milliseconds.
INTERACTIVE_BUDGET_MS = 500.0


@dataclass
class Decision:
    """The outcome of routing one request."""

    agent: str
    tier: Tier
    reason: str
    degraded: bool = False
    would_evict: bool = False
    estimated_swap_ms: float = 0.0
    considered: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        return {
            "agent": self.agent,
            "tier": self.tier.value,
            "reason": self.reason,
            "degraded": self.degraded,
            "would_evict": self.would_evict,
            "estimated_swap_ms": round(self.estimated_swap_ms, 1),
            "considered": self.considered,
        }


@dataclass
class AgentHealth:
    """Live state the router consults."""

    inflight: int = 0
    completed: int = 0
    failures: int = 0
    healthy: bool = True
    last_error: str = ""

    @property
    def saturated(self) -> bool:
        return self.inflight >= 8


def swap_cost_ms(tier: Tier) -> float:
    """Time to bring *tier*'s weights across PCIe, in milliseconds."""
    return TIER_VRAM[tier] / PCIE_BYTES_PER_SEC * 1e3


class Router:
    """Selects an agent per request. Thread-safe."""

    def __init__(self, ctx, resident: set[Tier] | None = None) -> None:
        self.ctx = ctx
        self._lock = threading.Lock()
        self.health: dict[str, AgentHealth] = {
            n: AgentHealth() for n in AGENTS_BY_NAME
        }
        plan = plan_residency(ctx.free_memory())
        self.resident: set[Tier] = resident or {
            Tier(t) for t in plan["resident_tiers"]
        }
        self.resident.add(Tier.NONE)     # model-free agents are always available
        self._decisions = 0
        self._degradations = 0
        self._evictions_avoided = 0

    # -- state -------------------------------------------------------------
    def mark_unhealthy(self, name: str, error: str) -> None:
        with self._lock:
            h = self.health.setdefault(name, AgentHealth())
            h.healthy = False
            h.failures += 1
            h.last_error = error

    def mark_healthy(self, name: str) -> None:
        with self._lock:
            self.health.setdefault(name, AgentHealth()).healthy = True

    def begin(self, name: str) -> None:
        with self._lock:
            self.health.setdefault(name, AgentHealth()).inflight += 1

    def end(self, name: str) -> None:
        with self._lock:
            h = self.health.setdefault(name, AgentHealth())
            h.inflight = max(0, h.inflight - 1)
            h.completed += 1

    def _available(self, a: Agent) -> bool:
        h = self.health.get(a.name, AgentHealth())
        return h.healthy and not h.saturated

    # -- routing -----------------------------------------------------------
    def route(self, workload: Workload,
              latency_budget_ms: float = INTERACTIVE_BUDGET_MS,
              allow_evict: bool = False) -> Decision:
        """Choose an agent for *workload*.

        *latency_budget_ms* below :data:`INTERACTIVE_BUDGET_MS` marks the
        request interactive, which forbids eviction outright regardless of
        *allow_evict*.
        """
        # Coerce and validate first. Passing a bare string used to surface as
        # an AttributeError from deep inside the router, which tells a caller
        # nothing about what they got wrong.
        if not isinstance(workload, Workload):
            try:
                workload = Workload(workload)
            except ValueError:
                raise SchedulerError(
                    f"unknown workload {workload!r}; expected one of "
                    f"{[w.value for w in Workload]}") from None

        all_candidates = agents_for(workload)
        if not all_candidates:
            raise SchedulerError(f"no agent accepts workload {workload.value!r}")

        considered = [a.name for a in all_candidates]
        interactive = latency_budget_ms <= INTERACTIVE_BUDGET_MS

        # `preferred` is computed from the UNFILTERED list on purpose. Deriving
        # it after filtering made a settle look like a clean hit: filtering out
        # the batch-only summariser promoted fallback-router to "preferred", so
        # a degraded route reported degraded=False.
        preferred = all_candidates[0]

        # Scheduled agents are not on-demand backends. finetune-orchestrator
        # accepts REASON because it reasons about training plans, not because
        # it should answer a 100 ms interactive question.
        candidates = all_candidates
        if interactive:
            eligible = [a for a in candidates if a.interactive]
            if eligible:
                candidates = eligible

        with self._lock:
            self._decisions += 1

        def _settle_reason(a: Agent) -> str:
            if preferred.tier not in self.resident:
                why = "not resident"
            elif not preferred.interactive and interactive:
                why = "scheduled-only and this request is interactive"
            else:
                why = "unavailable"
            return (f"preferred agent {preferred.name} ({preferred.tier.value}) "
                    f"is {why}; using resident {a.name} at the {a.tier.value} "
                    f"tier instead of paying a "
                    f"~{swap_cost_ms(preferred.tier):.0f} ms load")

        # 1. The preferred agent itself, resident and available.
        if preferred in candidates and preferred.tier in self.resident \
                and self._available(preferred):
            return Decision(
                agent=preferred.name, tier=preferred.tier, considered=considered,
                reason=(f"{preferred.name} handles {workload.value} at the "
                        f"{preferred.tier.value} tier and is already resident"),
            )

        # 2. Pay for the preferred agent when the caller allows it and the
        #    swap fits. Checked BEFORE degrading -- an earlier version returned
        #    any resident agent first, so allow_evict=True never had an effect.
        if allow_evict and not interactive and self._available(preferred):
            cost = swap_cost_ms(preferred.tier)
            if cost <= latency_budget_ms:
                return Decision(
                    agent=preferred.name, tier=preferred.tier,
                    considered=considered, would_evict=True,
                    estimated_swap_ms=cost,
                    reason=(f"{preferred.name} is not resident; paying "
                            f"~{cost:.0f} ms to load the {preferred.tier.value} "
                            f"tier, within the {latency_budget_ms:.0f} ms budget"),
                )
        if preferred.tier not in self.resident:
            with self._lock:
                self._evictions_avoided += 1

        # 3. Any other resident, available agent -- a real degradation.
        for a in candidates:
            if a.tier in self.resident and self._available(a):
                with self._lock:
                    self._degradations += 1
                return Decision(
                    agent=a.name, tier=a.tier, considered=considered,
                    degraded=True, reason=_settle_reason(a),
                )

        # 4. The safety net.
        fb = AGENTS_BY_NAME["fallback-router"]
        with self._lock:
            self._degradations += 1
        return Decision(
            agent=fb.name, tier=fb.tier, considered=considered, degraded=True,
            reason=("all specialised agents unavailable; fallback-router "
                    f"absorbing at the {fb.tier.value} tier"),
        )

    # -- introspection -----------------------------------------------------
    def residency_report(self) -> dict[str, object]:
        plan = plan_residency(self.ctx.free_memory())
        return {
            **{k: v for k, v in plan.items()},
            "resident_now": sorted(t.value for t in self.resident),
            "swap_cost_ms": {t.value: round(swap_cost_ms(t), 1)
                             for t in (Tier.SPECIALIST, Tier.RESIDENT, Tier.HEAVY)},
            "pcie_bytes_per_sec": PCIE_BYTES_PER_SEC,
        }

    def stats(self) -> dict[str, object]:
        with self._lock:
            return {
                "decisions": self._decisions,
                "degradations": self._degradations,
                "evictions_avoided": self._evictions_avoided,
                "agents": {
                    n: {"inflight": h.inflight, "completed": h.completed,
                        "failures": h.failures, "healthy": h.healthy}
                    for n, h in self.health.items()
                },
            }
