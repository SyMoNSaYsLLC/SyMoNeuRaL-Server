# A-4 Record Reconciled — Post-Provisioning

> **REDACTED COPY.** Customer identifiers, paths and infrastructure details masked as `*****`. No secret material printed.

## Continues from

`a4-customer-provisioned.md`. Documentation reconciliation only. **No runtime state changed.**

## 1. Commit

```
cb4252900f8315c30d5388336f8ddcb79350cffe
Reconcile the customer slot record after provisioning

  1 file changed, 3 insertions(+), 3 deletions(-)
```

**Exactly 1 file:** the A-4 record. No runtime files, no databases, no secrets.

## 2–4. The three reconciled indicators

### `CUSTOMER_IDENTITY` — DEFINED → **VERIFIED**

The vocabulary defines `VERIFIED` as *"observed working at runtime this pass."* Measured:

| Evidence | Value |
|---|---|
| Shared accounts | **1** |
| Correspondences | **1** — points only at the intended user |
| Other application users | **4, all unlinked** |
| Correspondence id vs granted account id | **identical** |
| Runtime observation | linked customer authenticates via the application's own login and is authorized |

Promoted past `PRESENT` and `WIRED` because it is not merely on disk or connected — it was **observed working**.

### `ENTITLEMENT_SLOT` — WIRED (no record) → **VERIFIED**

| Evidence | Value |
|---|---|
| Total grants | **1** |
| Active for this application | **1** |
| Grants for any other application | **0** |
| Wildcard / duplicate | none |
| Entitled customer, four routes | **200 / 201 / 200 / 200** |
| Authenticated **unprovisioned** user | **403 on all four** — *"not entitled to this application"* |

§10 requires `Wired`. The measured state **exceeds** it.

### `SHARED_SERVICE_MAP` — **remains EXISTING-INCOMPLETE**

Re-measured rather than assumed, and **not promoted**. **2 of 8** services runtime-verified:

| Service | State |
|---|---|
| Shared API | ✅ **runtime-verified** |
| accounts/auth (identity + entitlement) | ✅ **newly consumed and verified** |
| Shared web service | ❌ disabled / inactive |
| Shared gateway service | ❌ disabled / inactive |
| Shared inference engine | ❌ offline, **0 model payloads** |
| Credits / metering | ❌ store absent |
| Release / custody | ❌ blocked on D-11 |
| Shared project services | ⚠️ partial |

**One service going live does not satisfy a map of eight.** Six remain architecturally required but unconsumed.

## 5. Complete 19-indicator state

| State | Indicators |
|---|---|
| **VERIFIED** (4) | `CUSTOMER_IDENTITY` ← new · `ENTITLEMENT_SLOT` ← new · `FRONTEND_SLOT` · `API_SLOT` |
| **POPULATED, VERIFIED** (1) | `EXPORT_SCOPE` |
| **PRESENT — PASSING** (1) | `TEST_PATH` |
| **WIRED** (3) | `APPLICATION_SLUG` · `CUSTOMER_ROUTE` · `LIVE_STACK_ENTRY` |
| **PRESENT** (3) | `APPLICATION_IDENTITY` · `BACKEND_SLOT` · `WORKFLOW_SLOT` |
| **AUTHORIZED (A-4 only)** (2) | `RELEASE_IDENTITY` · `CUSTODY_RECORD` |
| **DEFINED — satisfied** (3) | `CONFIG_SLOT` · `ASSET_SLOT` · `PROTECTED_EXCLUSIONS` |
| **EXISTING-INCOMPLETE** (2) | `AUTH_SLOT` · `SHARED_SERVICE_MAP` |

## 6. A-4 completion determination

**A-4 is NOT complete.** Exactly **two** indicators fall short of their §10 required state:

| Indicator | Required | Current |
|---|---|---|
| `SHARED_SERVICE_MAP` | `Defined` | `EXISTING-INCOMPLETE` — 6 of 8 services unconsumed |
| `AUTH_SLOT` | `Wired` | `EXISTING-INCOMPLETE` |

**`AUTH_SLOT` is likely a stale label rather than a genuine gap** — flagged, not changed, because it was outside this authorization. Its recorded reason still cites the **unresolved** auth decision, which has since been settled as *keep separate and bridge*. Under that ruling, separation is the **intended end state**, and the application's own login/logout/me routes are live and serving. So the requirement may already be met and only the note is out of date. Correcting it needs its own authorization.

If that reading is accepted, **`SHARED_SERVICE_MAP` becomes the only genuine blocker** — and it is blocked by other subsystems being disabled or empty, not by anything A-4 can do.

### D-11 and D-12 — from the records, not inferred

**D-11 is NOT an A-4 completion requirement.** Its own record states `Blocks: any external distribution`. A-4's two related indicators (`RELEASE_IDENTITY`, `CUSTODY_RECORD`) each require only `Defined`, and both are already satisfied. D-11 is an **external-release gate only**.

**D-12 is NOT an A-4 completion requirement.** Its record states `Blocks: nothing today` and `Explicitly excluded from A-4`. It is a **separate hardening decision**.

## 7. Verification — all confirmed read-only

```
accounts 1 · correspondences 1 · active grants 1 · app users 5
provisioned customer   GET /board  → 200  authorized
unprovisioned user     GET /board  → 403  denied
D-3(b)                 0 shared session/login imports · cookie unchanged
                       2 independent session stores
exporter               7 entries · stage 2 passed · 0 archives · 0 modifications
service restarts       0 · shared accounts enabled True
```

**No runtime data created for verification.** Counts identical before and after.

## 8–9. Diff and status

```
$ git diff --cached --stat        (pre-commit)
 <A-4 record> | 6 +++---
 1 file changed, 3 insertions(+), 3 deletions(-)

$ git status --short              (post-commit)
 M docs/ops/EXPORTS.md      ← pre-existing, NOT swept in
```

---

## Remaining gates, in order

| # | Gate | Type | Blocks |
|---|---|---|---|
| **1** | `AUTH_SLOT` note correction | Documentation | Possibly nothing — likely stale label |
| **2** | `SHARED_SERVICE_MAP` — 6 of 8 unconsumed | Depends on other subsystems | **A-4 completion** |
| **3** | `D-11` signing authority | **OPEN** decision | **External release only** |
| **4** | `D-12` mechanical ownership guard | **OPEN** decision | Nothing today |

Gate 2 is the real A-4 blocker, and it is not an A-4 problem: it needs the web service, gateway, inference engine, credits store and custody authority to become consumable.

## Gates preserved

```
accounts created         NO (1, unchanged)   correspondence changed   NO (1)
entitlement modified     NO (1 active)       enablement modified      NO
session secret rotated   NO                  env file altered         NO
services restarted       NO (0)              authentication altered   NO
routes / schemas         unchanged           exporter / manifest      unchanged
D-11                     OPEN                D-12                     unimplemented
archive produced         NO (0)              policy document          untouched
runtime files committed  NO                  databases committed      NO
secrets committed        NO                  pushed                   NO
```

**D-11 and D-12 remain separate gates. External release remains NOT authorized.**
