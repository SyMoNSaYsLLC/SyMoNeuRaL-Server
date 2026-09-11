# A-4 Regression Repaired — Clean Checkpoint

> **REDACTED COPY.** Protected artifact names, credential filenames, customer identifiers, and infrastructure details are masked as `*****`. Unredacted detail stays on the box.

## Continues from

`a4-record-reconciliation.md`. You authorized the stale-test repair. Regression resolved and committed.

## 1. Commit

```
eaaa9d6ae19e0226ea245e808f961a305d3d5e6c
Provision entitlement in the application test fixtures

  3 files changed, 1692 insertions(+), 2 deletions(-)
```

## 2. Files changed — exactly 3

| File | Change |
|---|---|
| application test suite | fixture provisions a real entitlement (+49) |
| entitlement test suite | one leaking reload removed (+9/−2) |
| planning document | reconciled A-4 record — enters tracking at this commit (+1636) |

**Zero production files.** Routes, authorization module, application store, shared accounts store, exporter, export manifest: **0 changes each**.

## 3. Fixture changes

**The repair.** `Base.setUp` now gives each seeded user a shared identity and an active grant against a throwaway shared store. Provisioning is **real** — the class still guards 4 routes, the lookup is untouched, and nothing is mocked or bypassed, so these tests exercise the authorization path end to end rather than around it. The route-authorization suite that proves the *deny* side is deliberately untouched.

Everything is process-local: temp database, test-only secret, both removed in teardown. No customer provisioned, surface stays off.

**A second defect surfaced during the repair — and it was mine.** Both the new fixture and A-3's own entitlement suite called `importlib.reload` on the shared accounts module. That module is where the application store binds `WeakPassword` and the password helpers **at import time**, so reloading replaced those class objects and left the store raising a `WeakPassword` a later suite's `assertRaises` no longer recognised.

Two tests in a *third* file failed **only when one of these ran first** — passing in isolation, failing in a set. That is the worst shape a test defect can take, because a developer running the file alone sees green. Both reloads removed; the reload was never necessary, since the database path is read per connection. **Order-independence verified in both directions.**

## 4. Before / after

| Scope | Before | After |
|---|---|---|
| Two affected suites | **31 passed, 17 failed** | **48 passed, 0 failed** |
| Pre-A-3 baseline, same suites | 48 passed, 0 failed | **matched exactly** |
| Full set | 157 passed, 2 failed | **159 passed, 0 failed** |
| A-3 authorization suites | 35 passed | **35 passed** |
| Deny-side tests (T3/T15/T18/T21) | passing | **5 passed** |

Reverse ordering: **48 passed**. Post-commit full set re-run: **159 passed**.

## 5. Authorization behaviour preserved

| Check | Result |
|---|---|
| Routes carrying `ENTITLEMENT_REQUIRED` | **4** (unchanged) |
| Entitlement lookup function | intact |
| Mocks or patches of the class in fixtures | **0** |
| 403 for authenticated-but-unentitled | **still passing** |

The class was not weakened, bypassed, mocked away, or removed.

## 6. `git diff --stat` / `git status --short`

```
$ git diff --cached --stat        (pre-commit)
 Sept1.md                    | 1636 +++++
 <entitlement test suite>    |    9 +-
 <application test suite>    |   49 +
 3 files changed, 1692 insertions(+), 2 deletions(-)

$ git status --short              (post-commit)
 M ops/registry/EXPORTS.md      ← pre-existing, prior authorization, untouched
```

## 7. Confirmations

| | |
|---|---|
| Policy document swept in | **NO** — 0 occurrences; still modified and uncommitted |
| Unrelated / untracked files swept in | **NO** |
| Production authorization behaviour changed | **NO** |
| Routes, schemas, application logic changed | **NO** |
| Runtime configuration changed | **NO** |
| Shared accounts enabled | **NO** — `enabled()` = False |
| Customer provisioned | **NO** |
| Entitlement records outside fixtures | **NO** |
| Signing keys / custody / exporter / archives | **NO** — 0 archives produced |
| Services restarted | **NO** — 0 restarts |
| `D-12` implemented | **NO** |
| Commit `94156d39` | **unchanged** |
| Pushed | **NO** |

**D-11 remains OPEN. External release remains NOT authorized.**

## 8. `TEST_PATH` updated

**PRESENT — NOT PASSING** → **PRESENT — PASSING**, on measured evidence: 159/0 across the full set, matching the pre-A-3 baseline, with the deny side still enforced.

## Session commit chain

```
1df394f0  (baseline)
728df639  fail-closed snapshot exporter        [A-2]
a5fb0fbb  control/models operator surface      [A-1]
ef1a4af4  customer entitlement + authz seam    [A-3]
94156d39  customer export scope                [A-4 partial]
eaaa9d6a  test fixtures + reconciled record    [A-4 repair]  ← HEAD
```

---

## Remaining A-4 decision / prerequisite gates

| # | Gate | Type | Blocks |
|---|---|---|---|
| **1** | **Runtime prerequisite** — shared accounts disabled | Separate authorization (config + secret material) | `CUSTOMER_IDENTITY`, `SHARED_SERVICE_MAP`, all provisioning |
| **2** | **Customer account + entitlement provisioning** | Authorization; depends on #1 | `CUSTOMER_IDENTITY`, `ENTITLEMENT_SLOT` → PRESENT |
| **3** | **Configuration / asset boundary** | **Product decision** | `CONFIG_SLOT`, `ASSET_SLOT` |
| **4** | Per-application protected-exclusions statement | Documentation | `PROTECTED_EXCLUSIONS` |
| **5** | `D-11` signing authority | Open decision | External release only |
| **6** | `D-12` mechanical ownership guard | Open decision | Nothing today |
| — | `AUTH_SLOT` | **No gate** — D-3(b) is the intended end state | Nothing |

**Smallest next step:** gate 3 or 4 — both are unblocked and need no runtime change. Gate 1 is the only one that unlocks the remaining indicators, and it is deliberately a separate authorization.

**NEXT AUTHORIZATION: NONE**
