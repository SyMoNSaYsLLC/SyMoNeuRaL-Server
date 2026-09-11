# A-3 Plan Revised — 15 Pairs, Dependency Seam, Test Matrix

> **REDACTED COPY.** Protected artifact names, credential filenames, customer identifiers, and infrastructure details are masked as `*****`. Unredacted detail stays on the box.

## Continues from

`a3-route-classification.md` (2026-09-01 19:10). You resolved the two design decisions; this covers 19:10 → 19:30. **Planning revision only — no implementation.**

## Control point

| | Before | After |
|---|---|---|
| HEAD | `a5fb0fbb` | `a5fb0fbb` — no commits |
| implementation files changed | 0 | **0** — hashes verified unchanged |
| tests | 28 passing | **28 passing** |
| modified | export policy doc | export policy doc + planning doc |

---

## 1. What was revised

**§9.4 replaced entirely** — five class definitions, decided precedence, the 15-pair matrix, enumerated exemptions, the dependency seam, and the bridge analysis.

**A-3 assignment rewritten** — revised dependencies, 14-test matrix, explicit exclusions, remaining blockers.

**Three stale count claims reconciled** elsewhere in the document (the reference-slot section still said 13 routes in three places).

---

## 2. The authorization matrix — 15 method+path pairs

| # | Method | Route | Guard today | Class | Entitlement |
|---|---|---|---|---|---|
| 1 | GET | `/status` | none | `PUBLIC_BOOTSTRAP` | no |
| 2 | POST | `/login` | enabled-check | `SHARED_AUTH` | no |
| 3 | POST | `/logout` | **none** | `SHARED_AUTH` | no |
| 4 | GET | `/me` | signed-in | `AUTHENTICATED_APPLICATION` | no |
| 5 | GET | `/board` | signed-in + scope | `ENTITLEMENT_REQUIRED` | **yes** |
| 6 | POST | `/bookings` | signed-in | `ENTITLEMENT_REQUIRED` | **yes** |
| 7 | GET | `/bookings/{bid}` | signed-in + ownership | `ENTITLEMENT_REQUIRED` | **yes** |
| 8 | POST | `/ask` | signed-in + scope | `ENTITLEMENT_REQUIRED` | **yes** |
| 9 | POST | `/bookings/{bid}/quote` | operator | `OPERATOR_ONLY` | no |
| 10 | POST | `/bookings/{bid}/advance` | operator | `OPERATOR_ONLY` | no |
| 11 | POST | `/bookings/{bid}/message` | operator | `OPERATOR_ONLY` | no |
| 12 | **GET** | `/rules` | operator | `OPERATOR_ONLY` | no |
| 13 | **PUT** | `/rules` | operator | `OPERATOR_ONLY` | no |
| 14 | **GET** | `/drivers` | operator | `OPERATOR_ONLY` | no |
| 15 | **POST** | `/drivers` | operator | `OPERATOR_ONLY` | no |

```
PUBLIC_BOOTSTRAP  1 · SHARED_AUTH  2 · AUTHENTICATED_APPLICATION  1
ENTITLEMENT_REQUIRED  4 · OPERATOR_ONLY  7 · TOTAL  15
```

Entries 12–13 and 14–15 are separate on purpose. **Collapsing either pair to a path applies one privilege rule to a read and a write — that is how a read-only identity silently gains write access.**

### Precedence — decided

```
1. authentication            (or the route is exempt)
2. route authorization class (fixed per method+path)
3. ENTITLEMENT_REQUIRED -> customer entitlement
   OPERATOR_ONLY        -> operator role
4. ownership scoping        (row-level, unchanged)
```

Operator authority and customer entitlement are **separate axes**. An operator is never denied an operator-only route for lacking a customer entitlement — conflating them would lock the operator out of the surface they administer.

Ownership stays a distinct step: entitlement asks *may this identity use this application*; ownership asks *is this row yours*.

### Exemptions — enumerated, never a wildcard

| Route | Exempt from | Why |
|---|---|---|
| `GET /status` | auth + entitlement | An operator diagnosing a switched-off surface must be able to ask. Exposes no customer data |
| `POST /login` | entitlement | Identity must exist before an entitlement can be looked up for it |
| `POST /logout` | **auth + entitlement** | **Must succeed with an absent, expired, or already-invalidated session.** Any enforcement that made logout fail would strand a session token in the browser |
| `GET /me` | entitlement | An unentitled-but-authenticated caller legitimately needs to know who they are to be told *why* they are unentitled |

A wildcard exemption is how an entitlement-required route silently becomes exempt. The list is explicit.

---

## 3. Enforcement model

**Explicit dependency seam.** Not prefix middleware; not scattered per-handler logic.

Measured constraint: **no route in this router uses dependency injection today** — all guards are called inside handler bodies. The seam must be *introduced*; the earlier plan assumed an interception point that does not exist.

Proposed shape (**PROPOSED, not implemented**): one authorization dependency parameterised by class, attached per route at its definition.

| Property | Why it matters |
|---|---|
| **Explicit** | A route's class is visible at its declaration, not inferred from a prefix |
| **Reviewable** | The matrix can be diffed against the code mechanically |
| **Testable** | Exercisable without driving a full request |
| **Exemption-preserving** | Exemptions are named routes, not pattern holes |

**Existing authentication and role behaviour remain unchanged.** The seam *wraps* the existing guards rather than replacing or relaxing them.

### The bridge already has a seam

D-3 chose **(b)**: keep the application's own authentication, bridge entitlement.

**A partial bridge already exists.** The application's store imports password primitives from the shared accounts module while keeping its own session store and cookie. So (b) is narrower than "build a bridge" — it is **extend an existing import seam from password hashing to entitlement lookup**.

Unchanged: the app's session cookie, session store, login/logout endpoints, and two roles.
Added: an entitlement lookup consulted by the entitlement-required class only.

---

## 4. Required test matrix — 14 tests

| # | Test | Must prove |
|---|---|---|
| T1 | Matrix conformance | All 15 pairs carry exactly their assigned class — enumerated, so **a new route with no class fails the suite** |
| T2 | Entitled customer | 200 on all 4 entitlement-required pairs |
| T3 | Authenticated, unentitled | **403 on all 4** |
| T4 | **Operator without customer entitlement** | **200 on all 7 operator pairs** — the precedence decision, and the likeliest regression |
| T5 | Customer on operator routes | 403 on all 7 |
| T6 | `/status` exemption | 200 with no session **and** while the surface is off |
| T7 | `/login` exemption | Reachable unauthenticated and unentitled |
| T8 | **`/logout` exemption** | **204 with absent, expired, and already-invalidated sessions** — three cases |
| T9 | `/me` exemption | 200 for authenticated-but-unentitled; entitlement never consulted |
| T10 | Method separation | GET and PUT/POST on the two dual-method paths resolve independently |
| T11 | Ownership preserved | Existing not-yours behaviour unchanged |
| T12 | No auth regression | Both existing suites green |
| T13 | Live Stack | Unentitled catalogue omits the card; generator run twice, no diff |
| T14 | **Negative-control sabotage** | Removing the entitlement check makes **T3 fail** — proves T3 tests enforcement, not coincidence |

T14 exists because this session has twice seen tests pass for the wrong reason.

---

## 5. Remaining blockers — two, both real

**① The shared entitlement store is undefined.** Where the customer→application mapping lives, its schema, and who writes it. Nothing on disk defines it.

**② Identity correspondence is undefined.** How an identity in the application's own session store maps to an identity in shared accounts. Because D-3(b) deliberately keeps the two auth systems **separate**, this mapping is load-bearing — and it does not exist.

Neither is a classification gap. Both must be settled before the entitlement lookup can be written, **because the lookup's signature depends on them.**

---

## 6. Recommendation

# NOT READY for A-3 implementation authorization

**Reason:** the classification, precedence, enforcement model, exemptions and test matrix are complete and measured. But the entitlement lookup cannot be implemented without knowing *where the mapping lives* and *how the two identities correspond*. Writing it now would mean inventing both — a schema decision and an identity-model decision — which is the class of improvisation that produced the earlier defects in this plan.

**Smallest unblocking decision:** define the entitlement store location and schema, and the identity correspondence rule. Both are small decisions; neither is implementable by inference.

---

## Scope audit

```
AUTHORIZED SCOPE TOUCHED:
  planning document  (§9.4 replaced, A-3 assignment revised, 3 stale counts reconciled)

UNAUTHORIZED SCOPE TOUCHED: NONE
```

Handlers **0** · authentication **0** · authorization **0** · entitlement logic **0** · routes **0** · tests **0** · services **0** · packaging/signing/custody **0** · frontend **0**. Handler hashes verified unchanged. Nothing staged or committed.

## Still open from earlier

- **D-1, D-2, D-4, D-6 … D-11** undecided; **+2 new** (entitlement store shape, identity correspondence)
- **A-4** blocked on four decisions plus A-3 · **A-8** blocked on contaminated units
- Packaging/signing/custody: decisions exist, **zero implementation coverage**
- Production manifest **NOT DEFINED**

**NEXT AUTHORIZATION: NONE** — awaiting the two new definitions.
