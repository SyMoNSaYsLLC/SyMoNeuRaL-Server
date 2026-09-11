# SyMoNeuRaL Marketplace — FUTURE, and gated on a plugin contract that does not exist

**Scope captured 2026-08-22.** Docs only. **FUTURE. Not implementation authorization.**

## 1. The bet

**Sell workflows, plugins, adapters, templates, parameter packs, sigil packs and local/cloud
profiles — not only raw generation.**

The argument for it: generation is a commodity and a *composition* is not. A workflow that reliably
produces a usable badge on 16 GB of VRAM is worth more than the render it triggers, and it is the
kind of thing a person will pay once for and reuse.

## 2. Why it is FUTURE and not scheduled

**Studio has no extension contract.** `symoneural-studio-upgrade-scope.md` §1.3 measured it:
`plugins/__init__.py` has a registration list (`PLUGINS = ("discovery", "exp", "reinforce")`), a
`load()` that refuses unknown names, and `missing()` / `describe()` conformance helpers — **but
nothing describing what a plugin may *do***: no node contribution, no route contribution, no
lifecycle, no capability declaration.

**A marketplace for an extension point with no contract is a shop with no shelves.** So the
dependency is strict and stated: **plugin interface first, then tenants, then — much later — a
marketplace.**

Three further prerequisites, each already its own AUDIT:

| Prerequisite | Why it blocks |
|---|---|
| **Entitlements** | a purchase is an entitlement. Without one, "bought" has nowhere to live — `symoneural-entitlements.md` |
| **Provenance** | a sold artefact needs traceable origin and licence. Selling an adapter of unknown lineage is the licence audit's nightmare — `docs/ops/PROVENANCE.md` |
| **Meter** | **built**, and the only one of the three that is — `accounts/meter.py` |

## 3. What a sellable unit has to carry

Recorded as direction. Each unit needs, at minimum: an id · a version · **provenance** · a
**licence** · what it requires (model family, runtime, VRAM, target) · what it does not work with ·
**hardware badges** from `symoneural-studio-upgrade-scope.md` §8 · and docs/API links.

**The `NEEDS_MODEL_DOWNLOAD` and `UNSUPPORTED` badges are the commercially important ones.** A
marketplace that sells someone a workflow their hardware cannot run has sold them a refund.

## 4. The rule that would make this defensible, and the one that would sink it

**Defensible:** every unit carries provenance and a licence, and the platform refuses to list one
that does not. That is the same discipline `PROVENANCE.json` already applies to weights, and it is
the thing that would distinguish this from every other model-sharing site.

**Sinking it:** listing third-party content without licence review. `references/` is untracked
precisely so somebody else's code cannot ship, and **`@symoneural code.tar.gz` is a live example of
why** — it contains eleven third-party Anthropic projects, one of them all-rights-reserved
(`symoneural-coder-project-cli-scope.md` §1). **A marketplace is a distribution channel, and
distribution is where licence mistakes become liabilities** rather than mistakes.

**No user-supplied Python executed as a node.** `symoneural-studio-upgrade-scope.md` §1.3 already
forbids arbitrary public custom Python nodes; a marketplace makes that a *supply chain* rather than
a setting. A sold unit must be **declarative** — a graph, a parameter set, a weight with
provenance — not code.

## 5. Not authorized

No marketplace · no listing, catalogue or purchase flow · no payment · no plugin loader change · no
third-party content ingested · no folder migration · no deploy.

**FUTURE means captured, not queued.** There is no `PROJECT-TASKS.md` row for this and there should
not be one until the plugin contract exists — queueing it would present gated work as cleared, which
is the same rule `GUARDRAILS.md` applies to platform builds.
