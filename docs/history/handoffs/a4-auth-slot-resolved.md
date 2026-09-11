# A-4 AUTH_SLOT Resolved — One Blocker Remains

> **REDACTED COPY.** Customer identifiers, paths and infrastructure details masked as `*****`. No secret material printed.

## Continues from

`a4-record-reconciled-post-provisioning.md` (HEAD was `cb425290`). Documentation/evidence reconciliation only. **No authentication behaviour changed.**

## 1. Commit

```
698bef87e06b60262e33e11d676a0a8a52b22bab
Correct the auth slot record: separation is the design, not a gap

  1 file changed, 1 insertion(+), 1 deletion(-)
```

**Exactly 1 file:** the A-4 record. No runtime files, databases, or secrets.

## 2. Old state and wording

```
AUTH_SLOT | **Own** login/logout/me + provisioning CLI
          | EXISTING-INCOMPLETE
          | "Parallel to shared accounts, not consuming it. Architecture requires
             accounts/auth as a shared consumed service → D-3"
```

That reason was written **while D-3 was still open**. It described an unresolved question, not a measured gap.

## 3. New state and wording

```
AUTH_SLOT | Own login/logout/me + own session table + own cookie + provisioning CLI;
            bridge limited to correspondence + entitlement
          | VERIFIED
          | Resolved under D-3(b) with measured and runtime evidence (below)
```

## 4. Evidence

### The authorized architecture

D-3 resolved to **(b) keep separate, bridge entitlement** — recorded twice in the plan (§12.3 area and the A-3 assignment's *Decided* line). Under (b), separation is the **intended end state**.

Worth noting for the record: my original *recommendation* was (a) migrate. **Your ruling was (b)**, and the D-3 record still shows the recommendation alongside the decision — which is how I initially mis-read the slot as incomplete.

### Structural measurement — the three categories kept distinct

| Category | Measured |
|---|---|
| **Application authentication** — must be its own | login **1** · logout **1** · current-user **1** · session create **1** · validate **1** · revoke **1** · own sessions table **1** · cookie unchanged. **All 7 present and owned.** |
| **Shared authentication** — must not be imported | shared session/login imports: **0**. Only password primitives cross (`WeakPassword`, `check_password_or_dummy`, `hash_password`, `validate_password`) — a seam that predates this work |
| **Authorization / entitlement bridge** — the only permitted crossing | correspondence functions **3** · entitlement lookup **1** · shared import in the authz module **1**, entitlement only |

### Runtime verification — all six checks

| # | Check | Result |
|---|---|---|
| a | Provisioned customer authenticates via **application** login | **200** |
| b | Application issues its **own** cookie | `set-cookie: <app cookie>` |
| c | App login creates **no** shared session | shared **1** (from signup) vs app **2** — two independent stores |
| d | Correspondence resolves separately | `a3ee3403…` |
| e | Entitlement authorization succeeds | **200** |
| f | **Unlinked user** | login **200**, protected route **403** *"not entitled to this application"* |

**Check (f) is the decisive one.** An unlinked user authenticates successfully and is then refused by **entitlement, not authentication**. That is the separation working exactly as designed — the two layers reach different verdicts on the same request.

No accounts, sessions, correspondences or entitlements were created for this task; existing provisioned evidence sufficed.

## 5. §10 requirement — satisfied

Required state: **`Wired`** — *"connected into the running system (mounted route, loaded module)."*

All three routes are mounted and serving (200 on valid credentials, 401 on invalid), the session store is loaded, the cookie is issued. **`Wired` is met.**

Recorded as **`VERIFIED`** rather than `Wired`, because the vocabulary defines that as *"observed working at runtime this pass"* — which the six checks above did. Not a new state; the next one up the same scale, and the strongest the evidence supports.

## 6. Updated 19-indicator summary

| State | Indicators |
|---|---|
| **VERIFIED** (5) | `CUSTOMER_IDENTITY` · **`AUTH_SLOT`** ← new · `ENTITLEMENT_SLOT` · `FRONTEND_SLOT` · `API_SLOT` |
| **POPULATED, VERIFIED** (1) | `EXPORT_SCOPE` |
| **PRESENT — PASSING** (1) | `TEST_PATH` |
| **WIRED** (3) | `APPLICATION_SLUG` · `CUSTOMER_ROUTE` · `LIVE_STACK_ENTRY` |
| **PRESENT** (3) | `APPLICATION_IDENTITY` · `BACKEND_SLOT` · `WORKFLOW_SLOT` |
| **AUTHORIZED (A-4 only)** (2) | `RELEASE_IDENTITY` · `CUSTODY_RECORD` |
| **DEFINED — satisfied** (3) | `CONFIG_SLOT` · `ASSET_SLOT` · `PROTECTED_EXCLUSIONS` |
| **EXISTING-INCOMPLETE** (1) | `SHARED_SERVICE_MAP` |

## 7. Remaining A-4 blocker — exactly one

Checked all 19 against their §10 requirements. **One shortfall:**

**`SHARED_SERVICE_MAP`** — required `Defined`, currently `EXISTING-INCOMPLETE`. **2 of 8** services runtime-verified; the other six are unconsumed: web and gateway services **disabled**, inference **offline with 0 model payloads**, credits store **absent**, release custody **blocked on D-11**, shared project services **partial**.

**Not altered during this task**, per instruction. And it is not an A-4 problem — it is held there by other subsystems being disabled or empty.

**No other indicator is below its required state.**

## 8–9. Diff and status

```
$ git diff --cached --stat        (pre-commit)
 <A-4 record> | 2 +-
 1 file changed, 1 insertion(+), 1 deletion(-)

$ git status --short              (post-commit)
 M docs/ops/EXPORTS.md      ← pre-existing, NOT swept in
```

---

## Gates preserved

```
application auth code    0 changes    shared auth code       0 changes
authentication merged    NO           cookies/session        unchanged
accounts created/revoked NO (1)       correspondence altered NO (1)
entitlement altered      NO (1)       enablement modified    NO
session secret rotated   NO           env config modified    NO
services restarted       NO (0)       routes/schemas         unchanged
exporter/manifest        unchanged (7 entries)
D-11                     OPEN         D-12                   unimplemented
archive produced         NO (0)       policy document        untouched
runtime/db/secrets committed  NO      pushed                 NO
SHARED_SERVICE_MAP altered    NO      shared services enabled NO
```

**D-11 remains OPEN. D-12 remains unimplemented. External release remains NOT authorized.**
