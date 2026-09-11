# A-3 Route Classification + Two Documentation Corrections

> **REDACTED COPY.** Protected artifact names, credential filenames, customer identifiers, and infrastructure details are masked as `*****`. Unredacted detail stays on the box.

## Continues from

`a-series-decision-gate.md` (2026-09-01 18:50). You resolved three decisions; this covers 18:50 → 19:10.

## Control point

| | Before | After |
|---|---|---|
| HEAD | `a5fb0fbb` | `a5fb0fbb` — **no commits** |
| tracked modifications | 0 | **1** — the export policy doc only |
| implementation files changed | 0 | **0** |
| tests | 28 passing | **28 passing** |

---

## 1. Generator correction — 4 references

All four now name the measured owner. Verified: **0** stale ownership claims remain.

```
-  *Affected:* ... tools/build/build_stack.py (livestack is generated).
+  *Affected:* ... tools/build/build_split.py (livestack is generated).

-  check: grep entitle -- tools/build/build_stack.py
+  check: grep entitle -- tools/build/build_split.py

-  | 3 | ... `accounts/`, `build_stack.py` | ...
+  | 3 | ... `accounts/`, `build_split.py` | ...

-  | livestack.html | `build_stack.py` | none identified — REQUIRED |
+  | livestack.html | `build_split.py` | none identified — REQUIRED |
```

**Evidence:** the correct generator declares its outputs on line 4 and carries the page-table entry on line 56; the previously-named one has **0** references to that page and generates the documentation page instead.

**One reference deliberately left alone:** a fifth mention exists in a *collective* generator list (not a per-page ownership claim). It is outside the four you authorized. Worth noting it also omits the correct generator — a separate inaccuracy for a future pass.

## 2. Export policy reconciliation

Rule 4 rewritten to state allow-list construction, the two-stage model, and the refusal conditions. It now records that the earlier "excludes the above" wording described a deny-list and was the stale text.

A second stale element was corrected in the same conflict: a section headed *"until the script exists"* — the script now exists.

**The exporter was not modified.**

## 3. No implementation files changed

```
M  ops/registry/EXPORTS.md      ← documentation only
?? (planning file)          ← pre-existing, untracked

exporter: 0    A-2 test: 0    control/: 0    backend/apps: 0    tools/*.py: 0
28 tests still pass
```

---

## 4. Route classification — all routes

**First contradiction: the count.** The plan says 13 routes. Measured: **13 distinct paths but 15 method+path pairs.** Two paths carry two methods each at *different privilege levels*, so a path-level classification would under-count the surface. Classified below as 15.

**The auth model, measured.** There is **no `Depends()` on any route.** Every guard is called inside the handler body. Three helpers do the work: one asserts the surface is switched on (503), one asserts a session (401), one asserts the operator role (403). Two further helpers scope data by ownership.

Identity comes from an app-local session cookie. Roles are **customer** and **operator**.

| # | Route | Method | Guard invoked | Current auth behaviour | Identity source | Entitlement dependency | Class | Reason |
|---|---|---|---|---|---|---|---|---|
| 1 | `/status` | GET | **none** | Always answers | none | none | `PUBLIC_BOOTSTRAP` | Returns only on/off, assistant-connected, rates-configured, state list. No customer data. Needed to discover the surface is off |
| 2 | `/login` | POST | enabled-check | 503 if off; sets session cookie | credentials → app store | none | `SHARED_AUTH` | Establishes identity. **Must never be entitlement-gated** |
| 3 | `/logout` | POST | **none** | Always 204; clears cookie | cookie (optional) | none | `SHARED_AUTH` | Deliberately unguarded — logout must succeed even with a dead session |
| 4 | `/me` | GET | signed-in | 401 without session | session cookie | none | `AUTHENTICATED_APPLICATION` | Identity echo, not customer payload |
| 5 | `/board` | GET | signed-in + visibility scope | 401; rows scoped by role | session cookie | **yes** | `ENTITLEMENT_REQUIRED` | Returns customer booking data |
| 6 | `/bookings` | POST | signed-in | 401 | session cookie | **yes** | `ENTITLEMENT_REQUIRED` | Creates customer data |
| 7 | `/bookings/{bid}` | GET | signed-in + ownership | 401; 403 if not yours | session cookie | **yes** | `ENTITLEMENT_REQUIRED` | Per-record customer data |
| 8 | `/bookings/{bid}/quote` | POST | **operator** | 401 then 403 unless operator | session cookie | **yes** | `OPERATOR_ONLY` | Operator action against rate rules |
| 9 | `/bookings/{bid}/advance` | POST | **operator** | 401 then 403 | session cookie | **yes** | `OPERATOR_ONLY` | Mutates workflow state |
| 10 | `/bookings/{bid}/message` | POST | **operator** | 401 then 403 | session cookie | **yes** | `OPERATOR_ONLY` | Composes customer-facing text |
| 11 | `/rules` | GET | **operator** | 401 then 403 | session cookie | **yes** | `OPERATOR_ONLY` | Exposes pricing configuration |
| 12 | `/rules` | PUT | **operator** | 401 then 403 | session cookie | **yes** | `OPERATOR_ONLY` | Writes pricing configuration |
| 13 | `/drivers` | GET | **operator** | 401 then 403 | session cookie | **yes** | `OPERATOR_ONLY` | Personnel data |
| 14 | `/drivers` | POST | **operator** | 401 then 403 | session cookie | **yes** | `OPERATOR_ONLY` | Adds personnel |
| 15 | `/ask` | POST | signed-in + visibility scope | 401 | session cookie | **yes** | `ENTITLEMENT_REQUIRED` | AI over the customer's own board |

**Distribution:** 1 public bootstrap · 2 shared auth · 1 authenticated · 4 entitlement-required · 7 operator-only.

---

## 5. Contradictions between the plan and the actual handlers

**Four. All material.**

**① Route count is wrong.** Plan says 13; there are 15 method+path pairs. `/rules` and `/drivers` each pair a read with a write, and both writes are operator-only. A path-level rule would mis-scope them.

**② The plan has no `OPERATOR_ONLY` assignments — measured, there are seven.** The plan mapped `/rules`, `/drivers`, `/ask` and the booking sub-routes to `ENTITLEMENT_REQUIRED`. Measured, all of `/rules`, `/drivers` and three booking sub-routes already enforce an **operator role check**. Nearly half the surface is operator-only, and the plan classified none of it that way.

**③ `/logout` is unguarded, and correctly so.** The plan grouped it with shared auth without noting it deliberately runs no enabled-check and no session check — logout must succeed even when the session is already dead. An entitlement middleware applied by prefix would break it.

**④ Auth is in-body, not dependency-injected.** No route uses `Depends()`. The plan's model of adding entitlement middleware assumes an interception point that **does not exist** in this router. Entitlement must either be added per-handler or a dependency layer introduced first — a design question the plan does not address.

**A fifth finding that helps D-3(b):** the app already **imports password primitives from the shared accounts module** while keeping its own session store. A partial bridge exists. D-3(b) is therefore narrower than "build a bridge" — it is "extend an existing seam from password hashing to entitlement lookup."

---

## 6. Is A-3 ready for implementation authorization?

**Not yet — but it is closer, and for a documented reason.**

| Prerequisite | Status |
|---|---|
| Auth architecture decided (D-3) | ✅ option (b) |
| Generator defect corrected | ✅ 4 references |
| Export-architecture authority settled | ✅ allow-list |
| Route classification complete | ✅ 15 routes |
| **Entitlement injection point** | ❌ **no `Depends()` exists — undesigned** |
| **Operator-vs-entitlement precedence** | ❌ **undecided** — 7 operator-only routes |
| **Plan's route count and classes** | ❌ **stale** — 13 vs 15, zero operator-only |

**Two new decisions surfaced by reading the handlers:**

1. **How is entitlement enforced given there is no dependency-injection point?** Per-handler calls, a new dependency layer, or router-level middleware with an explicit exemption list. This is a design decision the plan assumed away.
2. **Does entitlement precede or follow the operator role check?** An operator without a customer entitlement — is that 403 on entitlement, or permitted as an internal role? Seven routes turn on this answer.

**Recommendation:** A-3 should not be authorized for implementation until those two are decided. The classification above is the input they need.

---

## Scope audit

```
AUTHORIZED SCOPE TOUCHED:
  planning document  (4 factual generator references)
  export policy doc  (rule 4 + one stale section header)

UNAUTHORIZED SCOPE TOUCHED: NONE
```

No handler modified · no auth modified · no entitlement bridge implemented · no routes added or renamed · no A-3/A-4 implementation · signing, packaging, custody, manifests, frontend slot and route naming all untouched · nothing staged or committed.

## Still open from earlier

- **D-1, D-2, D-4, D-6 … D-11** undecided; **+2 new** (entitlement injection point, operator/entitlement precedence)
- **A-4** blocked on four decisions plus A-3 · **A-8** blocked on contaminated units
- Packaging/signing/custody: decisions exist, **zero implementation coverage**
- Production manifest **NOT DEFINED**

**NEXT AUTHORIZATION: NONE** — awaiting the two new design decisions.
