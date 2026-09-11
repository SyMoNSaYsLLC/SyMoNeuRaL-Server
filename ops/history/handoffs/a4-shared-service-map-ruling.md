# A-4 SHARED_SERVICE_MAP — Ruling

> **REDACTED COPY.** Customer identifiers, paths and infrastructure details masked as `*****`. Read-only inspection.

## Continues from

`a4-auth-slot-resolved.md`. HEAD `698bef87`. **Nothing enabled, started, configured, provisioned, built, initialized, or modified. No edit, no commit.**

---

## 1. Exact §10 requirement

```
| `SHARED_SERVICE_MAP` | Which shared services are consumed | Defined |
```

Identical in the normative architecture:

```
| `SHARED_SERVICE_MAP` | Which SyMoNeuRaL/Symon services are consumed | Defined |
```

**Searched the architecture for any runtime-consumption requirement** — patterns for *must be consumed / active / running / enabled*, *runtime-wired*, *actually consumed*: **zero matches.** No language anywhere requires a mapped service to be running.

## 2. Applicable vocabulary

| State | Definition |
|---|---|
| **`DEFINED`** | *"Named in the architecture or a document. **No implementation claim.**"* |
| `EXISTING-INCOMPLETE` | *"Partially implemented"* |
| `WIRED` | *"Connected into the running system"* |
| `VERIFIED` | *"Observed working at runtime this pass"* |

**The phrase "No implementation claim" is decisive.** `DEFINED` explicitly disclaims implementation. Requiring runtime consumption to satisfy `Defined` applies the standard for `WIRED`/`VERIFIED` — states the specification did **not** ask for.

**The architecture's own completion rule:** *"The slot is complete only when the application has an explicit customer boundary **and** an explicit shared-platform dependency map."* — an **explicit** map, not an active one.

## 3. The eight-service map — measured

| # | Service | Intended relationship | Current state | Seam | Unavailability is |
|---|---|---|---|---|---|
| 1 | Shared API | **Required** — hosts the app's routes | **active**, HTTP 200 | routes mounted | n/a |
| 2 | accounts/auth (identity + entitlement) | **Required** — the D-3(b) bridge | **enabled**, consumed | authz → shared lookup | n/a |
| 3 | Shared web | **Required** per architecture | **defined but disabled** | unit installed, repo template | intentional (disabled unit) |
| 4 | Shared gateway | **Required** per architecture | **defined but disabled** | unit + built Rust crate | intentional (disabled unit) |
| 5 | Inference engine | **Conditional** — *"when required"* | **defined but offline**, 0 payloads | `engines/` present; 9 refs in the app's assistant module | intentional (no payloads acquired) |
| 6 | Credits / metering | **Not in this customer's map** | **defined but absent** | 3 tables defined in the metering module | not yet implemented |
| 7 | Release / custody | **Not in this customer's map** | **defined but blocked** | export manifest + exporter | blocked on D-11 |
| 8 | Shared project services | **Required** per architecture | **ready** | own runtime store | n/a |

**None is `genuinely undefined`.** Every entry has an identified component, a known intended relationship, an accurately recorded state, and a locatable seam. Disabled ≠ undefined, and the instruction to distinguish them is exactly right.

## 4. Which are actually this application's required consumers

**The architecture's own worked example for this customer lists six**, not eight:

```
symon-web · symon-gateway · symon-api
Symon runtime when required
accounts/auth
shared project/application services
```

| Service | Classification from architecture |
|---|---|
| Shared API, accounts/auth, shared web, shared gateway, shared project services | **Required** |
| Inference engine | **Conditional** — *"when required"*, stated three separate times |
| **Credits / metering** | **Platform-shared but not in this customer's map.** Measured consumption: **0** — the one grep hit was the word *"parameters"* inside a scrypt comment matching my `meter` pattern |
| **Release / custody** | **Platform-shared, not consumed by the application.** Measured: **0** references. It governs *delivery*, not runtime |

> **The eight-entry list is over-broad by two.** Credits/metering and release/custody are real platform services but are not part of this application's dependency map. I am not removing them — that needs your ruling — but the "2 of 8" framing measured against the wrong denominator.

## 5. Architectural unknowns

**None.** Every service has a known role, owner, seam, and intended relationship. Nothing about any entry's role is architecturally unresolved.

## 6. Implementation gaps — separately

Real, but **not** map-definition gaps:

| Gap | Nature |
|---|---|
| Shared web / gateway disabled | Enablement prerequisite — each its own authorization |
| Inference engine offline, 0 payloads | Model acquisition — D-2, separately gated |
| Credits store absent | Not implemented; not this application's dependency |
| Release/custody blocked | D-11, external-release gate |

## Answers to Questions A–D

**A. Can `SHARED_SERVICE_MAP` satisfy `Defined` with services disabled, offline, absent, blocked, or unconsumed?**

**Yes.** `DEFINED` is *"named in the architecture or a document. No implementation claim."* A state that disclaims implementation cannot require running services. Confirmed by the architecture's own reference map, which lists services by name — including one qualified *"when required"* — and presents that as the satisfied form.

**B. What evidence is required for `DEFINED — satisfied`?**

Every relevant shared service **identified**; its **intended relationship** to the application defined; its **current runtime state** accurately recorded; its **ownership boundary** known; and unavailable services **explicitly represented rather than silently omitted**. All five hold for all eight entries.

**C. If no, what language requires runtime consumption?**

**None exists.** Neither §10 nor the normative architecture contains any such requirement. The "2 of 8 runtime-verified" framing was **my own stricter standard**, not the specification's — I applied the `VERIFIED` bar to an indicator that asks for `Defined`.

**D. Does the repository already contain enough evidence?**

**Yes.** All eight entries are constructible from existing repository and read-only runtime evidence, with **no runtime change**. §11.1 already holds a four-level per-service table; it needs recasting as a *definition* rather than a consumption scorecard.

---

## 7. Determination

# SHARED_SERVICE_MAP CAN BE DEFINED FROM EXISTING EVIDENCE — DOCUMENTATION UPDATE REQUIRED

Not "already satisfies" — the record genuinely says `EXISTING-INCOMPLETE` and its supporting table is framed as runtime consumption, so a documentation update is needed. But the update is a **recasting**, requiring no service enablement.

**Root cause, and it was mine.** I authored the four-level table (*architecturally required / referenced by source / runtime wired / runtime verified*) and then judged the indicator against its strictest column. The specification asks only for `Defined`.

### Consequences

**Would A-4 be complete if the record were reconciled?**
**Yes.** `SHARED_SERVICE_MAP` is the sole indicator below its §10 requirement. Reconciling it puts all **19 of 19** at or above requirement.

**Is any runtime service enablement actually required for A-4?**
**No.** Not shared web, not gateway, not inference, not credits. All are implementation prerequisites for *other* work, and none is required by any A-4 indicator's stated requirement.

**Does D-11 affect the map definition?**
**Only runtime availability.** It blocks release/custody being *consumable* and gates external release. The map can name and characterize it while it is blocked — and that service isn't in this customer's dependency map anyway.

**Does D-12 affect A-4 completion?**
**No.** Its own record: `Blocks: nothing today`, `Explicitly excluded from A-4`.

## 8–10. Next authorization and state

**Exact next authorization needed:** a documentation-only reconciliation of `SHARED_SERVICE_MAP` — recast §11.1 as a definition (identity, intended relationship, current state, ownership, explicit representation of unavailable services), set the indicator to `DEFINED — satisfied`, and optionally rule on whether credits/metering and release/custody belong in this customer's map at all.

That single commit would make **A-4 complete**.

```
$ git status --short
 M ops/registry/EXPORTS.md      ← pre-existing, untouched
```

**Nothing changed:** 0 restarts · accounts 1 · correspondences 1 · grants 1 · web inactive · gateway inactive · credits absent · **A-4 record edited: 0** · no commit · no push.

**D-11 remains OPEN. D-12 remains unimplemented. External release remains NOT authorized.**
