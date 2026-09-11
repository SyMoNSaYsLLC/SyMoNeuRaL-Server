# A-4 Record Reconciliation — and a Regression I Introduced

> **REDACTED COPY.** Protected artifact names, credential filenames, customer identifiers, and infrastructure details are masked as `*****`. Unredacted detail stays on the box.

## Continues from

`a4-export-scope-committed.md`. Documentation-only reconciliation. **Nothing implemented, nothing committed.**

## ⚠️ Read this first — 17 test failures traced to A-3

Reconciling `TEST_PATH` required running the application's test suites. They do not pass.

| Commit | Result |
|---|---|
| `a5fb0fbb` — pre-A-3 baseline | **48 passed, 0 failed** |
| `94156d39` — now | **31 passed, 17 failed** |

Measured by checking out the baseline in a temporary worktree and running the same two suites.

**Cause.** A-3 attached `ENTITLEMENT_REQUIRED` to four routes. Those suites predate entitlement and provision none, so the routes now return **403** and assertions fail — `KeyError: 'bookings'` where a board payload was expected.

**The behaviour is correct; the tests are stale.** 403 for an authenticated-but-unentitled caller is exactly what A-3 was authorized to do, and what its own T3 asserts.

**Why I missed it.** My A-3 regression set was `test_accounts.py`, the in-package test path, `test_export_snapshot.py`, `test_control_models.py`. The the in-package test path path matched only the *in-package* suite. The two most affected suites live **outside** the package directory and were never in the set. A regression set that misses the suites most affected by the change is the defect — I reported "98 passed" and it was true of the set I chose, which is precisely the problem.

**Not fixed here.** Updating them means provisioning entitlement in their fixtures — a behavioural change to committed tests, outside a documentation-only authorization.

---

## 1. The two corrected records

### `ENTITLEMENT_SLOT` — MISSING → **WIRED, no record provisioned**

**Seam supplied by A-3** (`ef1a4af4`): the application's authorization module defines `ENTITLEMENT_REQUIRED` and `_entitlement_or_403`, which consults the shared accounts store's `is_entitled`, keyed by the identity reference held in the application store.

| Evidence | Measured |
|---|---|
| Authorization module tracked at HEAD | yes |
| Routes carrying the class | **4** |
| Entitlement functions in the shared store | **5** |
| Identity-link functions in the app store | **3** |
| **App users with a shared link** | **0 of 5** |
| **Live app DB migrated for the column** | **no** |
| **Accounts DB exists** | **no** |

**Not PRESENT, and deliberately not.** The mechanism is wired; **no entitlement is granted to anyone.** Provisioning is separately authorized and gated on the runtime prerequisite.

### `TEST_PATH` — MISSING → **PRESENT, not passing**

**Seam:** the in-package route-authorization suite (22 tests) added by A-3, plus three pre-existing suites — two backend, one frontend.

The slot standard requires *"passing before release."* **That is not met** — 17 failures above. `PRESENT` records existence only; the honest state is not "satisfied".

---

## 2. Remaining A-4 indicators — measured

| Indicator | State | Seam | Satisfied but undocumented? | Implementation missing? | Decision needed? | Blocked by |
|---|---|---|---|---|---|---|
| `CUSTOMER_IDENTITY` | **DEFINED, not PRESENT** | Name in the architecture; provisioning CLI exists | **No** | **Yes** — no customer account exists in the shared authority | No | **Runtime prerequisite** (shared accounts disabled) + provisioning authorization |
| `CONFIG_SLOT` | **DEFINED** | No boundary artifact found | No | **Yes** — no declared configuration boundary | **Yes** — what constitutes customer configuration vs application default | Nothing |
| `ASSET_SLOT` | **DEFINED** | No boundary artifact found | No | **Yes** — no declared asset boundary | **Yes** — same question for branding/content | Nothing |
| `PROTECTED_EXCLUSIONS` | **DEFINED** | Export policy classes + exporter stage 2 (verified enforcing) | **Arguably yes** — the classes are enumerated in policy and mechanically enforced; what is absent is a per-application *statement* | Partially | No | Nothing |
| `AUTH_SLOT` | **EXISTING-INCOMPLETE** | The application's own login/logout/me endpoints; password primitives imported from shared accounts | No | By design — D-3 chose **(b)**, keep separate and bridge | **Already decided** (D-3 = b) | Nothing; the state is the intended end state |
| `SHARED_SERVICE_MAP` | **EXISTING-INCOMPLETE** | Only one shared service is runtime-verified; the rest are architecturally required but not consumed | No | **Yes** — several services not wired | No | **Runtime prerequisite**, and the services' own disabled state |

**No indicator was upgraded without evidence.** `PROTECTED_EXCLUSIONS` is the one arguable case, and I left it `DEFINED` rather than claim satisfaction — the policy classes are enforced globally, but no per-application statement exists, and the ruling forbids converting DEFINED to PRESENT without evidence.

---

## 3. Decisions and prerequisites required

| # | Requirement | Type | Blocks |
|---|---|---|---|
| **1** | **Fix the 17 stale tests** — provision entitlement in their fixtures | Implementation authorization | `TEST_PATH` reaching *passing*; and it is a live regression today |
| **2** | **Runtime prerequisite** — shared accounts disabled | Separate authorization (config + secret) | `CUSTOMER_IDENTITY`, `SHARED_SERVICE_MAP`, any provisioning |
| **3** | **Customer account + entitlement provisioning** | Authorization; depends on #2 | `CUSTOMER_IDENTITY`, `ENTITLEMENT_SLOT` reaching PRESENT |
| **4** | **NEW — configuration/asset boundary** | Product decision | `CONFIG_SLOT`, `ASSET_SLOT` |
| **5** | Per-application protected-exclusions statement | Documentation | `PROTECTED_EXCLUSIONS` |
| — | `AUTH_SLOT` | **None** — D-3(b) is the intended end state | Nothing |

`D-11` remains **OPEN**; `D-12` (mechanical ownership guard) remains open and blocks nothing.

---

## 4. Smallest next sequence

**1 → 2 → 3**, then 4 and 5 in any order.

**Item 1 first, and not only for tidiness:** it is a *live regression*. 17 committed tests fail at HEAD. Everything else here is incomplete-but-honest; this one is broken. It is also the smallest — the behaviour is right, so only fixtures change — and it needs no decision.

Item 2 is a configuration and secret-material change and must stay a separate authorization. Item 3 depends on it. Items 4 and 5 are independent and unblocked.

---

## 5. Repository status

```
$ git status --short
 M ops/registry/EXPORTS.md      ← pre-existing, prior authorization, untouched
?? (planning document)      ← the only file modified this pass; untracked
```

**14 diff lines**, all in the planning document: two indicator rows plus the regression record. **Zero implementation files touched.**

| Boundary | Confirmed |
|---|---|
| Shared accounts enabled | **NO** |
| Customer account created | **NO** |
| Entitlement provisioned | **NO** |
| Auth / authorization behaviour changed | **NO** |
| Routes changed | **NO** |
| Exporter or export manifest changed | **NO** |
| D-12 implemented | **NO** |
| Signing keys / custody infrastructure | **NO** |
| Archive produced or distributed | **NO** |
| Services restarted | **NO** |
| Runtime configuration changed | **NO** |
| Policy document touched | **NO** |
| Commit `94156d39` | **unchanged** |
| Committed or pushed | **NO** |

**D-11 remains OPEN. External release remains NOT authorized.**

---

## 6. Proposed commit scope

**None — no documentation commit is warranted yet.**

The planning document has been untracked for the whole session and deliberately excluded from all four commits. Committing it now would be a larger decision than this reconciliation, and would also commit a record stating that 17 tests fail — which reads better as a fixed problem than a recorded one.

**Recommendation:** authorize item 1 (fix the stale tests), then commit the corrected tests and the reconciled record together, so the record and the repository agree at the same commit.

If you would rather commit the record now, the scope is exactly the planning document alone.

**NEXT AUTHORIZATION: NONE** — awaiting a ruling on the stale-test regression.
