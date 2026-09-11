# SyMoNeuRaL revenue edge — the five bets, and the hooks that already exist

**Scope captured 2026-08-22.** Docs only. **Paid mode is NOT enabled. No pricing, no SLA, no
capacity claim, no payment code.**

**Classification: revenue hooks — PROD direction, disabled by default. The commercial switch —
AUDIT. Compliance/export bundle — PROD direction, staged. Marketplace — FUTURE. Edge/Yocto
appliance — AUDIT/FUTURE.**

## 0. Why this file exists

Garrett is fine with free and offline now. The point is that **the architecture should not need a
rewrite when commercial mode is switched on** — so the hooks get placed while the shape is still
cheap to change. `ops/backend/authority/docs/symoneural-commercial-mode.md` holds the switch; this holds the *bets*
the switch is for.

**The honest headline: more of this exists than a plan would assume.** The meter is built, accounts
are built, provenance is strong for models, and the licence thinking is done. What is missing is
mostly *connection* and *decision*, not construction.

## 1. Agentic local/cloud execution

**The bet:** the user chooses Cloud or Local, and Studio's target resolver picks a valid
runtime/model/hardware path.

| Piece | State |
|---|---|
| four execution targets | specified — `symoneural-studio-upgrade-scope.md` §5 |
| target resolver | specified — §6, and `symoneural-cloud-local-targets.md` |
| hardware badges | specified — §8 |
| **local agent** | **does not exist.** No local-agent directory in this repo |

**The gating fact:** browser-only hardware detection is approximate, so Local's honest default
answer today is `NEEDS_LOCAL_AGENT`. **The differentiator is real** — local-first privacy with cloud
fallback is a genuine product position — **and it is one component away from being claimable.**

## 2. Paid compute, not just paid chat

**The bet:** charge by job, token, image, render, train, eval or runtime lease — not per seat.

**And this is the one that is largely built.** `backend/apps/accounts/meter.py`: balances, holds, a
ledger, `sweep_stale()`, and **reserve-then-resolve** rather than charge-on-success, because
charging at completion is a time-of-check/time-of-use hole that *"costs real money"*. Integer tokens
throughout; owners are free by taking **no hold at all** rather than a zero-amount one.

**So the near-term revenue work is connection, not construction:** it is wired to
`symoneural_dj.pipeline.run_job` and **not** to the main API's GPU surfaces.

**What is missing per the brief's list:** app-specific metering across every surface (currently
**PARTIAL** — one caller) · queue priority · private result retention · model/runtime access tiers ·
adapter training/eval jobs as billable units · owner/admin controls (partly present via the owner
bearer).

**The natural per-surface unit already exists in another form** — `_RATE_SUGGESTED` in `api.py`
already assigns each surface a cost-shaped budget (`image` 20/300 at *"~9 s of exclusive GPU each"*,
`ravencalc` 240/6000 as CPU-only). **That table is a cost model in rate-limit clothing**, and it is
the right starting point for pricing units. **It is not a price list and must not be published as
one.**

## 3. Provenance and compliance as a product feature

**The bet:** enterprises pay for *"prove what ran, where it came from, and whether it is
licensed."*

**This is SyMoNeuRaL's strongest non-obvious asset**, because the repo already does the unglamorous
half: `PROVENANCE.json` with **measured, test-checked** byte counts; `NAMES.md` kept as a licence
obligation rather than documentation; `LICENSES.md` §8 obligations and §9 customer-build checklist;
`EXPORTS.md` governing what may leave the box; and the standing rule that every figure is labelled
`measured` / `vendor` / `projected`.

**What is missing is the artefact, not the discipline:** no SBOM, no build provenance, no
`NOTICE.md`, and three weights whose attribution cannot travel. `ops/registry/SBOM.md`,
`models/docs/PROVENANCE.md`, `ops/audits/LICENSE-AUDIT.md`.

**The product is `ops/backend/authority/docs/symoneural-trust-report.md`.** It is FUTURE because it is a *rendering*
of those artefacts, and rendering something that does not exist yet is the one thing it must not do.

## 4. Studio plugin marketplace

**The bet:** workflows, plugins, adapters, templates, parameter packs and sigil packs become
sellable units — not just raw generation.

`ops/backend/authority/docs/symoneural-marketplace.md`. **FUTURE**, and gated on the plugin interface existing at
all (`symoneural-studio-upgrade-scope.md` §1.3: *define the interface before migrating tenants*).
**A marketplace for an extension point that has no contract is a shop with no shelves.**

The long-term product surfaces the brief names — Parameters, MoE, Sentinel, Reinforce, Exp, Generic
contracts — each have their own spec, and each is AUDIT or FUTURE.

## 5. Local AI appliance / embedded edge

**The bet:** a signed, provenanced, offline local-AI box.

`ops/backend/authority/docs/symoneural-appliance.md`. **AUDIT/FUTURE**, and the blocking fact is plain: **no Yocto
image has ever been built**, so licence manifests and SPDX output are *not yet producible* rather
than missing (`YOCTO-LAYER-LICENSES.md` §0). **No claim of a production appliance until one is built
and tested.**

The metadata groundwork is done and better than expected: twelve layers with complete `layer.conf`
data, and all nine recipes carrying `LICENSE` and `LIC_FILES_CHKSUM`.

## 6. The named future modules

| Module | Classification | Spec |
|---|---|---|
| **Sentinel** — output supervision, drift/contradiction detection, append-only intervention audit | FUTURE/AUDIT | `backend/registry/docs/symoneural-sentinel-spec.md` (exists) |
| **Provenance** — model/runtime/data/build provenance | **PROD direction**, AUDIT implementation | `models/docs/PROVENANCE.md` |
| **Meter** — token/job/credit metering | **BUILT / AUDIT**, disabled by default | `accounts/meter.py`; `symoneural-commercial-mode.md` §1 |
| **Entitlements** — what an account/token may run | AUDIT | `backend/licensing/docs/symoneural-entitlements.md` |
| **Marketplace** | FUTURE | `ops/backend/authority/docs/symoneural-marketplace.md` |
| **Appliance** | FUTURE/AUDIT | `ops/backend/authority/docs/symoneural-appliance.md` |
| **Trust Report** | FUTURE/AUDIT | `ops/backend/authority/docs/symoneural-trust-report.md` |
| **Local Agent** | AUDIT/FUTURE | `symoneural-cloud-local-targets.md` §2 |

**Sentinel is the one worth flagging as commercially interesting**, because "audited AI output" is
a claim almost nobody can make honestly, and this repo's habit of labelling every figure is the
cultural prerequisite for it. It remains FUTURE.

## 7. The rules that apply to all five bets

- **Revenue hooks are disabled by default.** A hook is a place a decision *can* go, not a decision.
- **No pricing, plan names, SLA, capacity, throughput, revenue or "guaranteed" language anywhere** —
  page, spec or API description — until it is real. Pricing questions route to the existing channel.
- **A configured-but-unconsulted meter is red.** Already the rule for rate buckets
  (`symoneural-api-surface.md` §4) and it applies identically to credits.
- **Commercial mode cannot turn on** until `SECURITY-AUDIT.md`'s BLOCKER/HIGH findings are closed or
  owner-accepted in writing with a date — **and** the licence gaps in `symoneural-commercial-mode.md`
  §4a are closed.
- **No revenue feature may widen a security gate.** A mode value is not a credential.

## 8. Not authorized

No payment or billing code · no price stated · no account requirement added · no credits enabled ·
no queue-priority implementation · no marketplace · no appliance build · no local agent · no gate
change · no deploy.
