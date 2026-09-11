# A-3 Implementation Plan — Derived from Fixed Decisions

> **REDACTED COPY.** Protected artifact names, credential filenames, customer identifiers, and infrastructure details are masked as `*****`. Unredacted detail stays on the box.

## Continues from

`a3-architecture-decisions-ready.md` (2026-09-01 19:50). You authorized both recommendations. This covers 19:50 → 20:10. **Plan only — nothing implemented.**

## Control point

```
HEAD                          a5fb0fbb   (no commits)
implementation files changed  0          (4 hashes verified unchanged)
tables / migrations created   0
config or environment changed 0
services restarted            0
```

**Decisions recorded** as fixed architecture in the planning document (§9.4.6a).

---

## 1. Files and components that would change

| # | Component | Change | Why |
|---|---|---|---|
| 1 | Shared accounts store | Add entitlement table to the schema constant; add read + grant/revoke functions | D-A3-1 puts the mapping here |
| 2 | Application store | Add nullable shared-account reference column to the local user table; expose it on user reads | D-A3-2 correspondence |
| 3 | Application routes | Attach the class dependency to all 15 pairs; **no guard logic altered** | §9.4.5 dependency seam |
| 4 | **New** — authorization dependency module | The `require(class)` seam | No dependency-injection point exists today |
| 5 | Operator provisioning CLI | Add grant / revoke / list-entitlements / link-identity | D-A3-1 names it the sole writer |
| 6 | Live Stack generator | Filter the catalogue by entitlement | Page is generated; never hand-edit it |
| 7 | **New** — entitlement tests | Shared-store side | T2, T3, T14 |
| 8 | **New** — route authorization tests | Application side | T1, T4–T11 |

**Explicitly unchanged:** login, logout, session creation/validation, cookie name and attributes, password hashing, the two roles, ownership scoping, and the licence-entitlement module (different concern).

---

## 2. Schema changes

### 2a. Entitlement table — shared accounts store

```
entitlements
  account_id        TEXT NOT NULL REFERENCES accounts(id) ON DELETE CASCADE
  application_slug  TEXT NOT NULL
  granted_at        REAL NOT NULL
  granted_by        TEXT NOT NULL      -- operator identity, for audit
  revoked_at        REAL               -- NULL = active
  PRIMARY KEY (account_id, application_slug, granted_at)
```

**Why `granted_at` is in the key:** a customer may be granted, revoked, then re-granted. A two-column key would force the re-grant to overwrite the revoked row, destroying the audit trail your decision requires. The active-grant query is *"latest row for this pair where `revoked_at IS NULL`"*.

**Revocation sets `revoked_at`. Nothing is ever deleted.**

### 2b. Identity reference — application store

```
users
  ...existing columns unchanged...
  shared_account_id  TEXT            -- nullable; NULL = no shared identity
```

Nullable with **no default and no backfill**. Existing rows start `NULL`, which is correct: they genuinely have no shared identity.

---

## 3. Migration and backward compatibility

**Measured mechanics:** both stores run their schema constant through `executescript` on **every connection**, using `CREATE TABLE IF NOT EXISTS`.

| Change | Self-migrating? | Reason |
|---|---|---|
| **New table** (2a) | **Yes** | `CREATE TABLE IF NOT EXISTS` on every connection creates it on first use |
| **New column** (2b) | **No** | `CREATE TABLE IF NOT EXISTS` does **not** add a column to a table that already exists |

**This is the plan's most important technical finding.** Measured: **zero `ALTER TABLE` statements exist in either store.** There is no migration precedent to copy, so 2b needs one established.

Smallest pattern consistent with the existing code: on connection, probe the table's columns and `ALTER TABLE ... ADD COLUMN` only when absent — idempotent, matching the self-healing intent already documented in the shared store.

**Backward compatibility:**
- A database predating the change gains an empty entitlement table and a `NULL`-valued column
- `NULL` and "no row" both mean **not entitled** — so an un-migrated database fails closed, not open
- Both schema-version constants should increment for traceability, though neither store branches on the value today

---

## 4. Operator CLI changes

The CLI is the **only** authorized writer. Proposed additions:

| Command | Effect | Guard |
|---|---|---|
| `--link-identity <app-user> <account-id>` | Sets the nullable reference | Refuse if the shared account does not exist; refuse if already linked, unless `--force` |
| `--grant <account-id> <app-slug>` | Inserts an active grant | Refuse if the account does not exist; refuse if an active grant already exists |
| `--revoke <account-id> <app-slug>` | Sets `revoked_at` on the active grant | Refuse if no active grant; **never delete** |
| `--list-entitlements [<account-id>]` | Shows grants incl. revoked, with timestamps | Read-only; prints no secrets |
| `--unlink-identity <app-user>` | Sets the reference back to `NULL` | Fails closed by construction — the user loses entitlement |

Constraints from your decision: **no self-service path**, **no new privileged admin API**. Every write is an operator-run CLI action, matching how user provisioning already works.

---

## 5. Read paths

### Entitlement read
```
require(ENTITLEMENT_REQUIRED)
  → session → local user record
  → shared_account_id            (NULL → 403)
  → shared store: latest entitlements row for (account_id, app_slug)
  → row exists AND revoked_at IS NULL   → allow
  → anything else                        → 403
```

### Identity-link read
```
local user record → shared_account_id
  NULL     → no shared identity      → not entitled
  non-NULL → key for the entitlement lookup
```
No fallback. No matching on username or email. **No heuristics** — per D-A3-2.

Both reads are consulted **only** by `require(ENTITLEMENT_REQUIRED)`. The other four classes never touch them.

---

## 6. Fail-closed behaviour — four conditions

| Condition | Result | Rationale |
|---|---|---|
| **Missing entitlement** (no row, or latest is revoked) | **403** | Your decision: no row = not entitled |
| **Missing correspondence** (`NULL` reference) | **403** | No shared identity = no entitlement. Free from the nullable design |
| **Shared accounts unavailable** (switched off, DB missing, unreadable) | **403 — never allow** | An authorization check that cannot run has **not passed**. This is the single most important line in the plan: the tempting failure is to treat "cannot check" as "no restriction" |
| **Malformed record** (bad slug, unparseable timestamp, orphaned reference) | **403 + operator-visible log** | Refuse and make it diagnosable. Never coerce a malformed row into a grant |

**Distinguish 401 from 403:** no session → 401 (authenticate). Session but no entitlement → 403 (authenticated, not authorized). Conflating them tells an unentitled user to log in again, which they cannot fix.

The four exempt routes are unaffected by all four conditions — including when shared accounts is unavailable.

---

## 7. Tests required

The 14-test matrix from §9.4 stands, with these additions from the fixed decisions:

| # | Test | Must prove |
|---|---|---|
| T15 | **Shared accounts unavailable** | All 4 entitlement routes **403**; all 4 exemptions still reachable; all 7 operator routes still reachable |
| T16 | Revocation auditable | After revoke, the historical grant row **still exists** with `granted_at`, `granted_by`, `revoked_at` |
| T17 | Re-grant after revoke | Both rows persist; only the later one is active |
| T18 | `NULL` reference | Un-linked user gets 403 on all 4 entitlement routes |
| T19 | Migration idempotence | Applying schema twice is a no-op; a pre-existing database gains table and column without data loss |
| T20 | No heuristic matching | A local username identical to a shared account email grants **nothing** |
| T21 | Malformed record | Orphaned reference and bad slug both 403, both logged |
| T22 | CLI is the only writer | No HTTP route can create, update or revoke a grant |

**T20 and T15 are the two that matter most.** T20 guards the explicit rejection of inference; T15 guards against the fail-open reading of an unavailable dependency.

---

## 8. Runtime prerequisite — separate authorization required

**Shared accounts is switched off on this box.** Measured gate: it requires an enable flag set to `1` **and** a session secret of at least 32 characters. Neither is set in the environment file.

Consequences:

| | |
|---|---|
| Can A-3 be **implemented** with it off? | **Yes** — schema, CLI, dependency seam and tests are all writable and testable against a temporary database |
| Can entitlement **function at runtime** with it off? | **No** |
| What happens if A-3 ships while it is off? | Every entitlement-required route returns **403** — correct fail-closed behaviour, but the customer surface is effectively closed |

**This is a separate authorization.** Enabling it means setting an environment flag and generating a session secret — a configuration and secret-material change, outside this plan. I have not enabled it, not generated a secret, and not modified any configuration.

**Recommended sequencing:** implement A-3 with the subsystem off and prove fail-closed behaviour first (T15). Enabling it is then a small, independently reversible step with the safety property already demonstrated.

---

## 9. Boundaries — what stays unchanged

Proof obligations, each mechanically checkable:

| Boundary | How A-3 respects it | Check |
|---|---|---|
| **Cookies** | Name and attributes untouched | Cookie constant unchanged |
| **Sessions** | Local session table, creation and validation untouched | Session functions unchanged |
| **Login** | No change; class `SHARED_AUTH`, exempt | Handler body unchanged |
| **Logout** | No change; stays usable with absent/expired/invalidated sessions | Handler body unchanged; T8 |
| **Roles** | Both roles unchanged; operator check unchanged | Role guard unchanged; T4, T5 |
| **Authentication ownership** | The application keeps its own authentication. **No merge.** Only entitlement is bridged | No new import of session or login code from shared accounts |

The dependency seam **wraps** existing guards; it does not replace or relax them. The only new authorization check is the entitlement lookup, and only on the 4 entitlement-required pairs.

---

## Scope audit

```
AUTHORIZED SCOPE TOUCHED:
  planning document  (§9.4.6a — fixed decisions recorded)

UNAUTHORIZED SCOPE TOUCHED: NONE
```

No tables · no migrations · no code · no configuration · no environment · no services restarted · shared accounts **not enabled** · no secret generated · nothing staged or committed. Four implementation-file hashes verified unchanged.

## Still open from earlier

- **D-1, D-2, D-4, D-6 … D-11** undecided
- **A-4** blocked on four decisions plus A-3 · **A-8** blocked on contaminated units
- Packaging/signing/custody: decisions exist, **zero implementation coverage**
- Production manifest **NOT DEFINED**
- **New:** no `ALTER TABLE` precedent exists in either store — the column migration needs a pattern established

## To resume

The plan is complete and derives strictly from the fixed decisions. Two things need your ruling before implementation:

1. **Authorize A-3 implementation** against this plan.
2. **Accept the column-migration pattern** (probe-then-add-column on connection), since no precedent exists to follow.

The runtime prerequisite — enabling shared accounts — remains a separate authorization and is not requested here.

**NEXT AUTHORIZATION: NONE**
