"""Tests for the ten-agent platform: registry, prompt, router, licensing."""

from __future__ import annotations

import pytest

from symoneural.agents import (
    AGENTS,
    AGENTS_BY_NAME,
    TIER_VRAM,
    Aes256GcmSealer,
    DenyAllVerifier,
    FernetSealer,
    LicenceError,
    Router,
    SealError,
    StaticAllowVerifier,
    Tier,
    WeightCustodian,
    Workload,
    agents_for,
    build_system_prompt,
    hardware_facts,
    plan_residency,
    swap_cost_ms,
)
from symoneural.agents.routing import INTERACTIVE_BUDGET_MS, PCIE_BYTES_PER_SEC


class TestRegistry:
    def test_exactly_ten_agents(self):
        assert len(AGENTS) == 10
        assert len({a.name for a in AGENTS}) == 10, "duplicate agent names"

    def test_every_workload_has_an_agent(self):
        for wl in Workload:
            assert agents_for(wl), f"no agent accepts {wl.value}"

    def test_dependencies_resolve(self):
        for a in AGENTS:
            for dep in a.depends_on:
                assert dep in AGENTS_BY_NAME, f"{a.name} depends on unknown {dep}"

    def test_no_dependency_cycles(self):
        seen: dict[str, int] = {}

        def visit(name: str, stack: tuple[str, ...]) -> None:
            if name in stack:
                pytest.fail(f"dependency cycle: {' -> '.join(stack + (name,))}")
            if seen.get(name):
                return
            for d in AGENTS_BY_NAME[name].depends_on:
                visit(d, stack + (name,))
            seen[name] = 1

        for a in AGENTS:
            visit(a.name, ())

    def test_fallback_accepts_every_workload(self):
        fb = AGENTS_BY_NAME["fallback-router"]
        assert set(fb.workloads) == set(Workload)

    def test_fallback_sorts_last(self):
        """The safety net must never be the first choice for a workload."""
        for wl in Workload:
            ranked = agents_for(wl)
            if len(ranked) > 1:
                assert ranked[-1].name == "fallback-router", (
                    f"fallback-router is not last for {wl.value}: "
                    f"{[a.name for a in ranked]}")

    def test_audit_and_ingest_are_model_free(self):
        """These must survive GPU exhaustion, so they cannot need a model."""
        for name in ("state-verifier", "telemetry-ingest"):
            assert AGENTS_BY_NAME[name].tier is Tier.NONE

    def test_finetune_is_not_interactive(self):
        assert AGENTS_BY_NAME["finetune-orchestrator"].interactive is False


class TestResidency:
    def test_specialist_always_resident(self):
        for free in (2 * 2**30, 8 * 2**30, 15 * 2**30, 80 * 2**30):
            assert "1.5b" in plan_residency(free)["resident_tiers"]

    def test_default_tier_preferred_over_bigger_one(self):
        """Regression: greedy-by-size left the 7B default non-resident.

        With ~10 GiB of weights budget both (1.5B+14B) and (1.5B+7B) fit, but
        only the latter keeps the documented default loaded.
        """
        plan = plan_residency(15 * 2**30)
        tiers = plan["resident_tiers"]
        if "14b" in tiers:
            assert "7b" in tiers, "14B resident while the 7B default is not"

    def test_kv_reserve_is_held_back(self):
        p = plan_residency(16 * 2**30)
        assert p["kv_reserve"] > 0
        assert p["weights_budget"] + p["kv_reserve"] == p["free_bytes"]

    def test_never_overcommits(self):
        for free in (2 * 2**30, 6 * 2**30, 15 * 2**30, 40 * 2**30):
            p = plan_residency(free)
            assert p["weights_used"] <= p["weights_budget"]

    def test_tiny_gpu_gets_specialist_only(self):
        p = plan_residency(2 * 2**30)
        assert p["resident_tiers"] == ["1.5b"]


class TestSwapCost:
    def test_derived_from_measured_pcie(self):
        """Swap cost must track the real link, not a guess."""
        expected = TIER_VRAM[Tier.RESIDENT] / PCIE_BYTES_PER_SEC * 1e3
        assert swap_cost_ms(Tier.RESIDENT) == pytest.approx(expected)

    def test_seven_b_swap_exceeds_interactive_budget(self):
        """The fact the whole routing policy rests on."""
        assert swap_cost_ms(Tier.RESIDENT) > INTERACTIVE_BUDGET_MS

    def test_ordering(self):
        assert (swap_cost_ms(Tier.SPECIALIST) < swap_cost_ms(Tier.RESIDENT)
                < swap_cost_ms(Tier.HEAVY))


class TestRouter:
    def test_resident_preferred_agent_is_clean(self, ctx):
        d = Router(ctx).route(Workload.CLASSIFY, latency_budget_ms=200)
        assert d.agent == "telemetry-classify"
        assert not d.degraded and not d.would_evict

    def test_model_free_work_never_needs_vram(self, ctx):
        d = Router(ctx).route(Workload.TELEMETRY, latency_budget_ms=50)
        assert AGENTS_BY_NAME[d.agent].tier is Tier.NONE

    def test_interactive_never_evicts(self, ctx):
        """Even with allow_evict=True, an interactive budget forbids a swap."""
        r = Router(ctx, resident={Tier.SPECIALIST, Tier.NONE})
        d = r.route(Workload.TRAIN, latency_budget_ms=100, allow_evict=True)
        assert not d.would_evict
        assert d.degraded

    def test_eviction_allowed_when_budget_permits(self, ctx):
        r = Router(ctx, resident={Tier.SPECIALIST, Tier.NONE})
        d = r.route(Workload.TRAIN, latency_budget_ms=60_000, allow_evict=True)
        assert d.would_evict
        assert d.estimated_swap_ms == pytest.approx(swap_cost_ms(Tier.HEAVY))

    def test_eviction_refused_when_swap_exceeds_budget(self, ctx):
        r = Router(ctx, resident={Tier.SPECIALIST, Tier.NONE})
        # 14B swap is ~1181 ms; a 700 ms budget is non-interactive but too small.
        d = r.route(Workload.TRAIN, latency_budget_ms=700, allow_evict=True)
        assert not d.would_evict
        assert d.degraded

    def test_settling_is_reported_as_degraded(self, ctx):
        """Regression: choosing a less-specialised resident agent looked clean.

        A silent downgrade is a correctness bug -- the orchestrator prompt
        says so explicitly, so the router must not commit one.
        """
        r = Router(ctx, resident={Tier.SPECIALIST, Tier.NONE})
        d = r.route(Workload.REASON, latency_budget_ms=60_000)
        assert d.degraded
        assert "finetune-orchestrator" in d.reason

    def test_saturation_falls_through(self, ctx):
        r = Router(ctx)
        for _ in range(8):
            r.begin("telemetry-classify")
        d = r.route(Workload.CLASSIFY, latency_budget_ms=200)
        assert d.agent != "telemetry-classify"

    def test_unhealthy_agent_skipped(self, ctx):
        r = Router(ctx)
        r.mark_unhealthy("telemetry-ingest", "simulated")
        d = r.route(Workload.TELEMETRY, latency_budget_ms=50)
        assert d.agent != "telemetry-ingest"

    def test_unknown_workload_rejected(self, ctx):
        from symoneural.core.errors import SchedulerError
        with pytest.raises((SchedulerError, ValueError)):
            Router(ctx).route("not-a-workload")  # type: ignore[arg-type]

    def test_every_decision_has_a_reason(self, ctx):
        r = Router(ctx)
        for wl in Workload:
            d = r.route(wl, latency_budget_ms=5000)
            assert d.reason and len(d.reason) > 20, f"thin reason for {wl.value}"

    def test_stats_track_degradations(self, ctx):
        r = Router(ctx, resident={Tier.SPECIALIST, Tier.NONE})
        r.route(Workload.REASON, latency_budget_ms=60_000)
        assert r.stats()["degradations"] >= 1


class TestSystemPrompt:
    def test_built_from_live_hardware(self, ctx):
        p = build_system_prompt(ctx)
        assert ctx.caps.name in p
        assert ctx.caps.sm_arch in p

    def test_states_the_pcie_constraint(self, ctx):
        p = build_system_prompt(ctx)
        assert "Gen 3" in p
        assert "7.0 GB/s" in p or "7 GB/s" in p

    def test_names_all_ten_agents(self, ctx):
        p = build_system_prompt(ctx, include_roster=True)
        for a in AGENTS:
            assert a.name in p, f"{a.name} missing from the roster section"

    def test_forbids_routing_around_licence_checks(self, ctx):
        p = build_system_prompt(ctx)
        assert "deny" in p.lower()
        assert "route around" in p.lower()

    def test_does_not_overstate_encryption(self, ctx):
        """The prompt must state the limit, and must not claim more."""
        p = build_system_prompt(ctx).lower()
        # States the real limit.
        assert "readable by anyone" in p
        assert "at rest" in p
        # Explicitly tells the orchestrator not to oversell it.
        assert "do not claim it prevents extraction" in p

    def test_reflects_current_free_vram(self, ctx):
        facts = hardware_facts(ctx)
        assert 0 < facts["free_vram"] <= facts["total_vram"]
        assert facts["resident_vs_pcie_ratio"] > 50


class TestLicensing:
    """Sealing needs the `cryptography` package (a hard dependency).

    Skipping rather than erroring keeps a missing optional install
    distinguishable from a real failure in the custody logic.
    """

    @pytest.fixture(autouse=True)
    def _needs_cryptography(self):
        pytest.importorskip("cryptography",
                            reason="pip install 'cryptography>=42.0.0'")

    def test_deny_by_default(self):
        ent = DenyAllVerifier().verify("m1", "u1")
        assert not ent.granted
        assert "stub" in ent.reason.lower()

    def test_unseal_denied_without_licence(self):
        s = Aes256GcmSealer(Aes256GcmSealer.generate_key())
        c = WeightCustodian(sealer=s, verifier=DenyAllVerifier())
        blob = s.seal(b"weights")
        with pytest.raises(LicenceError):
            c.unseal("m1", "u1", blob)

    def test_denial_is_audited(self):
        s = Aes256GcmSealer(Aes256GcmSealer.generate_key())
        c = WeightCustodian(sealer=s, verifier=DenyAllVerifier())
        with pytest.raises(LicenceError):
            c.unseal("m1", "u1", s.seal(b"w"))
        assert c.denial_count == 1
        assert c.audit_trail()[0]["granted"] is False

    def test_unseal_succeeds_when_granted(self):
        s = Aes256GcmSealer(Aes256GcmSealer.generate_key())
        c = WeightCustodian(sealer=s, verifier=StaticAllowVerifier({"m1"}))
        payload = b"model-weights" * 100
        assert c.unseal("m1", "u1", s.seal(payload)) == payload

    def test_unlisted_checkpoint_still_denied(self):
        s = Aes256GcmSealer(Aes256GcmSealer.generate_key())
        c = WeightCustodian(sealer=s, verifier=StaticAllowVerifier({"m1"}))
        with pytest.raises(LicenceError):
            c.unseal("m2", "u1", s.seal(b"w"))

    def test_expired_entitlement_denied(self):
        s = Aes256GcmSealer(Aes256GcmSealer.generate_key())
        c = WeightCustodian(sealer=s,
                            verifier=StaticAllowVerifier({"m1"}, ttl_seconds=-1))
        with pytest.raises(LicenceError, match="expired"):
            c.unseal("m1", "u1", s.seal(b"w"))

    def test_tampered_ciphertext_rejected(self):
        s = Aes256GcmSealer(Aes256GcmSealer.generate_key())
        c = WeightCustodian(sealer=s, verifier=StaticAllowVerifier({"m1"}))
        blob = bytearray(s.seal(b"weights" * 50))
        blob[-1] ^= 0xFF
        with pytest.raises(SealError, match="authentication"):
            c.unseal("m1", "u1", bytes(blob))

    def test_wrong_key_rejected(self):
        a = Aes256GcmSealer(Aes256GcmSealer.generate_key())
        b = Aes256GcmSealer(Aes256GcmSealer.generate_key())
        c = WeightCustodian(sealer=b, verifier=StaticAllowVerifier({"m1"}))
        with pytest.raises(SealError):
            c.unseal("m1", "u1", a.seal(b"weights"))

    def test_aes256_key_length_enforced(self):
        with pytest.raises(SealError, match="32-byte"):
            Aes256GcmSealer(b"short")

    def test_fernet_roundtrip(self):
        s = FernetSealer(FernetSealer.generate_key())
        payload = b"checkpoint" * 200
        assert s.unseal(s.seal(payload)) == payload

    def test_fernet_labelled_accurately(self):
        """Fernet is AES-128-CBC + HMAC-SHA256, not AES-256.

        The distinction matters for anyone matching a compliance requirement
        that names AES-256 specifically.
        """
        assert "AES-128" in FernetSealer.algorithm
        assert "256" not in FernetSealer.algorithm.replace("SHA256", "")
        assert Aes256GcmSealer.algorithm == "AES-256-GCM"

    def test_verify_precedes_decrypt(self):
        """Denial must not decrypt. Order is the whole control."""
        calls: list[str] = []

        class Spy(Aes256GcmSealer):
            def unseal(self, ciphertext: bytes) -> bytes:
                calls.append("decrypt")
                return super().unseal(ciphertext)

        s = Spy(Aes256GcmSealer.generate_key())
        c = WeightCustodian(sealer=s, verifier=DenyAllVerifier())
        with pytest.raises(LicenceError):
            c.unseal("m1", "u1", s.seal(b"w"))
        assert calls == [], "ciphertext was decrypted despite a denied licence"
