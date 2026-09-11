# SyMoNeuRaL Generic — the contract layer, and the registry it must not become

**Scope captured 2026-08-22.** Docs only. **AUDIT until scoped. No implementation.**

Abstraction / contracts layer. Named explicitly so a migration cannot erase it.

## 1. What it is for

> **Generic is the shared shape of a model, a runtime, a job, a node, a parameter, a target and a
> result — so that no app hardcodes one model's or one runtime's assumptions.**

The problem it solves is already visible on this disk. `BOX-REALITY-AUDIT.md` §1.2 records that
the packet's examples assumed SDXL and `CheckpointLoaderSimple` while the actual baseline is
FLUX/Schnell with four differently-shaped files; §4.1 records that **stable `operation_id`s exist
nowhere** — zero, today. Both are the same failure: each surface having its own private idea of
what a model or a route is.

Consumers: Studio · API · RuntimeOps · ModelOps · Local Agent · Cloud · Local · Image · Chat ·
Sigils · Remix · Reinforce.

## 2. The proposed contracts

Recorded as direction, not schema: `GenericModel` · `GenericRuntime` · `GenericNode` ·
`GenericParameter` · `GenericJob` · `GenericTarget` · `GenericHardwareProfile` ·
`GenericArtifact` · `GenericResult` · `GenericProvenance`.

Each **normalises the common fields and allows app-specific extensions.** The extension half is
not a courtesy — a contract with no room for what makes a surface different gets bypassed, and
then the abstraction exists while nothing uses it.

`GenericProvenance` is the one to design first. Every artefact in this repo already carries
provenance obligations — `models/PROVENANCE.json` is the only place the house-name →
upstream-artefact mapping exists, and `NAMES.md` is a **licence obligation** rather than
documentation. A generic artefact type that cannot carry those is not usable here.

## 3. The two hard rules

**Generic must not become a third registry system.** The model registry answers *what can be
served*; the runtime registry answers *what can serve it*; the router joins them
(`symoneural-runtime-registry.md` §1). **Generic describes their shapes. It stores nothing.**

A contracts layer that starts caching model entries "for convenience" is a third registry with a
different name, and `.claude/CLAUDE.md`'s first *never* is the general form of that rule: *"never
create a second state document."*

**Generic is not a product page.** There is no *SyMoNeuRaL Generic* surface, no rack row and no
`/generic` route, and none may be created unless explicitly authorized. It is a library-shaped
concept. A rack row for it would be a decorative tile for an abstraction — the exact thing
`symoneural-live-stack.md` §7 forbids.

## 4. Where a Pydantic-shaped instinct already went wrong

Worth recording because the obvious implementation has a known failure here. #97 wanted a
`pydantic.BaseModel` as the wire between two Studio nodes, and it **could not be used**: a
`BaseModel` renders as an untyped object through `registry._json_type`, so the graph would have
carried a typeless wire. The working version is a **stdlib dataclass**, with the MCP schema
carrying a real `$ref` to it.

So a Generic contract has an extra constraint beyond being well-typed in Python: **it has to
survive the trip into the node registry's JSON schema and out to a client** with its type intact.
Any contract type chosen without checking that is a wire that looks typed and is not.

## 5. What would promote this from AUDIT

| To claim | Proof required |
|---|---|
| the contracts exist | types defined and **two different apps** using the same one — one app is a private class with a public name |
| they survive the schema | a node whose port carries a real `$ref`, per §4 |
| provenance is generic | one artefact type carrying `PROVENANCE.json`'s fields without loss |
| it is not a third registry | no storage, and a test that says so |

## 6. Not authorized

No contract implemented · no schema change · no registry field added · no `/generic` route or rack
row · no folder migration · no deploy.

Related: `symoneural-runtime-registry.md` §1-2 · `ops/docs/MODEL-REGISTRY.md` ·
`symoneural-studio-node-system.md` §2 · `symoneural-parameters.md` ·
`ops/docs/HARDWARE-PROFILES.md`.
