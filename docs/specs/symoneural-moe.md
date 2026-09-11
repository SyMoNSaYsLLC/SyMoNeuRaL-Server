# SyMoNeuRaL MoE — routing direction, and the thing that does not exist yet

**Scope captured 2026-08-22.** Docs only. **AUDIT until scoped. No implementation, no download,
no training.**

Studio-family / ModelOps concept. Named explicitly so a migration cannot erase it.

## 0. Measured first, because this is the concept most at risk of being claimed

**There is no mixture-of-experts model on this box.** Searched 2026-08-22 across `backend/` and
`docs/`: every occurrence of "MoE" is **educational or third-party**, not an inventory entry —

- `docs/symoneural-manual.md:917` and the reinforce playbook explain *why* MoE models are fast
  for their size ("only some FFN experts read per token → fewer bytes/token"). That is a
  paragraph about how MoE works, not a model we have.
- `backend/apps/news/rank.py:45` has `"moe"` as a **news keyword** for ranking articles.
- `docs/REFERENCE-INDEX.md` mentions fused-MoE microbenchmarks in third-party NVIDIA tooling.

**So: no MoE weights, no expert-routing code, no multi-expert serving.** The current image
baseline is FLUX/Schnell and the LLM path is a single model. **Nothing may claim otherwise.**

## 1. What it would be

> **MoE is the mixture-of-experts / model-composition direction: choosing which model or adapter
> answers, per task.**

Concepts to preserve: expert routing · model routing · adapter routing · task-specialised expert
selection · ensemble and composition workflows.

**Note the useful ambiguity, and keep both readings.** "MoE" here covers two different things
that a migration would be tempted to merge:

1. **A true MoE architecture** — one model whose FFN layers hold many experts, routed per token
   internally. That is a property of a *model file*, and it would arrive through the model
   registry like any other weight.
2. **SyMoNeuRaL-level composition** — routing a job across *several* models or adapters we
   already have. That is a property of the *router*, and it is the half that is actually
   SyMoNeuRaL's to build.

They need different registry fields and different proofs. (2) is buildable on one card; (1)
depends entirely on a file nobody has downloaded.

## 2. Rules

- **Do not claim a current MoE model exists** unless the registry, the files and a test prove it.
  §0 is the current answer.
- **Do not claim multi-expert serving capability** unless a runtime supports it. Of seven runtime
  families, two are built, one is source-only and four are absent (`BOX-REALITY-AUDIT.md` §8).
- **No MoE weight download or training in this scope.**
- **No separate MoE stack outside ModelOps/RuntimeOps.** MoE decisions use the **model registry,
  runtime registry, hardware profiles and the GPU governor** — it is a policy layer over those,
  never a parallel one. `symoneural-runtime-registry.md` §1 already forbids collapsing the
  registries; this forbids growing a third.
- **MoE decisions must be inspectable and provenance-aware.** A router that cannot say *which*
  expert answered and *why* is unauditable, and every artefact in this repo carries provenance.
- **Public users cannot mutate base weights through MoE.** Weight-producing operations are
  owner/admin only and **register a new version rather than editing in place** —
  `symoneural-studio-upgrade-scope.md` §1.2.

## 3. The constraint that shapes this more than any design choice

**One 16 GB consumer card, and chat and image weights do not both fit in 15.92 GiB.**

That is the standing measurement (`api.py:1391-1396`, `BOX-REALITY-AUDIT.md`), and it means
multi-expert *residency* is the expensive assumption, not multi-expert *routing*. Routing across
models that must be **swapped** is a hot-swap problem with an admission check, which is
`symoneural-model-hot-swap.md`'s subject — not a new mechanism.

**Multi-model residency must be measured before being called green.** Any MoE claim that assumes
several experts resident at once is a capacity claim about hardware that has not been measured
that way.

## 4. Possible future Studio nodes

Recorded as direction, **not** authorization: Expert Router · Model Selector · Adapter Selector ·
Confidence/Verifier · Fallback Policy · Cost/Latency Policy · Hardware Target Resolver ·
Ensemble/Merge if scoped later.

Each would need the full node contract from `symoneural-studio-node-system.md` §2 — supported
runtimes, supported targets, required model family, hardware badges, `docs_href`, `api_href`.

## 5. What would promote this from AUDIT

Per the classification rule (*if uncertain, classify AUDIT and say what proof would promote it*):

| To claim | Proof required |
|---|---|
| a MoE model exists | a registry entry with a real local path, provenance and licence, plus a load test |
| multi-expert serving | a runtime at `built` or better that supports it, and a run record |
| expert routing works | a decision log naming the chosen expert and the reason, and a test that a different input routes differently |
| several experts resident | a **measured** VRAM reading on this card, not a projection |

## 6. Not authorized

No MoE implementation · no expert router · no weight download or training · no registry schema
change · no new stack · no folder migration · no deploy.
