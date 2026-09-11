"""The ten-agent platform: registry, orchestrator prompt, router, licensing."""

from .licensing import (
    Aes256GcmSealer,
    DenyAllVerifier,
    Entitlement,
    FernetSealer,
    LicenceError,
    LicenceVerifier,
    SealError,
    StaticAllowVerifier,
    WeightCustodian,
)
from .prompt import build_routing_hint, build_system_prompt, hardware_facts
from .registry import (
    AGENTS,
    AGENTS_BY_NAME,
    TIER_VRAM,
    Agent,
    Tier,
    Workload,
    agents_for,
    plan_residency,
    resident_budget,
)
from .routing import Decision, Router, swap_cost_ms

__all__ = [
    "AGENTS", "AGENTS_BY_NAME", "Agent", "Tier", "Workload", "TIER_VRAM",
    "agents_for", "plan_residency", "resident_budget",
    "build_system_prompt", "build_routing_hint", "hardware_facts",
    "Router", "Decision", "swap_cost_ms",
    "WeightCustodian", "FernetSealer", "Aes256GcmSealer", "Entitlement",
    "LicenceVerifier", "DenyAllVerifier", "StaticAllowVerifier",
    "LicenceError", "SealError",
]
