# A-3 Implemented — Awaiting Authorization Gate

> **REDACTED COPY.** Protected artifact names, credential filenames, customer identifiers, and infrastructure details are masked as `*****`. Unredacted detail stays on the box.

## Continues from

`a3-implementation-plan.md` (2026-09-01 20:10). You authorized implementation and the migration pattern. This covers 20:10 → 20:45.

## Control point

| | Before | After |
|---|---|---|
| HEAD | `a5fb0fbb` | `a5fb0fbb` — **no commits** |
| A-3 tests | — | **35 passing** |
| Regression suites | 98 passing | **98 passing** |
| Shared accounts | disabled | **still disabled** |
| Services restarted | 0 | **0** |

---

## 1. Files changed / created

**Modified (6):**

| File | Change |
|---|---|
| shared accounts store | Entitlement table + 5 functions (+139) |
| application routes | Import + 15 decorator lines only (+16/−16) |
| application store | Column, idempotent migration, link/unlink (+75) |
| operator CLI | 5 new operations (+78) |
| Live Stack generator | Entitlement filtering hook (+30) |
| export policy doc | *(previously authorized)* |

**Created (3):** authorization dependency seam · entitlement tests · route-authorization tests.

**Totals: +363 / −21.** Of the 21 deletions, **16 are the rewritten decorator lines and 1 the import** — no handler body was altered.

---

## 2. Schema changes

**Entitlement table** — `(account_id, application_slug, granted_at)` primary key, `granted_by`, nullable `revoked_at`, plus a lookup index.

`granted_at` is in the key so grant → revoke → re-grant keeps three readable facts instead of overwriting the middle one. "Active" is *the latest row with `revoked_at IS NULL`*, never "the row".

**Identity reference** — one nullable column on the local user table. NULL means no shared identity, therefore not entitled.

---

## 3. Migration — idempotence proven on a real legacy database

Built a database with the pre-column shape and a row in it, then ran the migration three times:

```
run 1: added_column=True
run 2: added_column=False
run 3: added_column=False

columns after:  [... , shared_account_id]
preserved row:  username='keepme'  shared_account_id=None
```

Adds once · no-ops thereafter · existing data intact · **no backfill**. Probe-then-add, exactly the authorized pattern.

---

## 4. Route/class attachment — 15/15

```
PUBLIC_BOOTSTRAP           1
SHARED_AUTH                2
AUTHENTICATED_APPLICATION  1
ENTITLEMENT_REQUIRED       4
OPERATOR_ONLY              7
                          ──
TOTAL                     15
```

Matches the authorized matrix exactly. Both dual-method paths kept their read and write as **separate** entries with independent classes.

---

## 5. Test results — 35 A-3 tests, all passing

| Group | Result |
|---|---|
| Entitlement store (T2, T16, T17, T21) | **13 passed** |
| Route authorization (T1, T4, T6–T10, T15, T18–T22) | **22 passed** |
| **Regression** — accounts, application, A-1, A-2 | **98 passed** |

### Proven by deliberate sabotage

Passing tests prove nothing unless they can fail. Two sabotages, each caught by exactly the right test:

| Sabotage | Caught by |
|---|---|
| Treat "cannot check" as "no restriction" (fail **open**) | **T15** — the single most important test here |
| Revoke by `DELETE` instead of stamping `revoked_at` | **T16 and T17** |

Restored afterwards: **0** sabotage markers, all 35 green.

---

## 6. Fail-closed behaviour — four conditions

| Condition | Result | Verified |
|---|---|---|
| Missing entitlement | 403 | ✅ |
| Missing correspondence (NULL) | 403 | ✅ |
| **Shared accounts unavailable** | **403 — never allow** | ✅ T15 |
| Malformed record | 403 + operator log | ✅ T21 |

401 for missing authentication, 403 for authenticated-but-unentitled — kept distinct, because telling an unentitled user to log in again asks them to fix something they cannot.

A malformed row denies **one** application without poisoning the others.

---

## 7. Boundaries — evidence

| Boundary | Evidence |
|---|---|
| Cookie | Constant unchanged; 0 diff lines |
| Sessions | 0 session functions removed or altered |
| Login | 0 diff lines in the handler body |
| Logout | 0 diff lines; still exempt, still usable with a dead session |
| Roles | 0 role changes |
| Password hashing | Import seam unchanged, 0 diff lines |
| Guards | All 5 still present, 0 removed |
| No auth merge | No session or login symbol imported from shared accounts |
| Licence subsystem | **0** files touched |

The seam **wraps** the existing guards; it does not replace or relax them.

---

## 8. Shared accounts remains disabled

```
enable flag in environment:  unset
session secret in environment: unset
configuration files modified:  0
services restarted:            0
API:                           active, HTTP 200
```

Tests supply a **process-local** temp secret in `setUp` and restore the environment in `tearDown` — the pattern the existing accounts suite already uses. Nothing was written to configuration, and a test asserts the real environment carries neither switch.

**T15 was proven with the subsystem disabled**, which is exactly the condition it guards.

---

## 9. Deviations and findings

**Two test-authoring corrections during the run** (implementation was not changed):

1. First draft called account creation without a session secret — the store correctly refuses to operate without one. Fixed by adopting the existing suite's process-local pattern rather than weakening the store.
2. One assertion expected unsorted output where the function returns sorted. **Test bug, not code bug** — fixed the assertion.

**No blockers discovered. No fallback behaviour was added to make any test pass.**

### Scope not expanded

`site/` `frontend/` `ops/` `control/` `web/` `engines/` `training/` licence subsystem — **0 files each**. No unrelated decision resolved.

---

## Still open from earlier

- **D-1, D-2, D-4, D-6 … D-11** undecided
- **A-4** blocked on four decisions plus A-3 · **A-8** blocked on contaminated units
- Packaging/signing/custody: decisions exist, **zero implementation coverage**
- Production manifest **NOT DEFINED**
- **Runtime prerequisite:** enabling shared accounts is a separate authorization. Until then every entitlement route returns 403 — correct fail-closed behaviour, but the customer surface is closed

## To resume

A-3 is implemented and verified. Nothing staged or committed. Options: commit A-3 as an isolated checkpoint, authorize enabling shared accounts, or return to the open decisions.

**NEXT AUTHORIZATION: NONE**
