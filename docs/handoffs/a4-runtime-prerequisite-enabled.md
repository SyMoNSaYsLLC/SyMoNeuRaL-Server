# A-4 Runtime Prerequisite — ENABLED AND VERIFIED

> **REDACTED COPY.** Paths, credential filenames and infrastructure details are masked as `*****`. **No secret value was read or printed** at any point.

## Continues from

`a4-enablement-verification-failed.md`. The refusal was resolved by inspecting first, then appending rather than overwriting. Enablement is now live and verified.

## How the refusal was resolved

The env file already held **live tokens for three other surfaces** (three other named surfaces plus one application flag — 7 keys). The legacy-prefixed names are promoted at startup with a deprecation warning, so they are working configuration.

**Overwriting would have disabled three working surfaces.** The installer's refuse-if-exists guard is the only thing that prevented it.

Resolution: inspect key names → confirm the session secret was genuinely absent → **append only** the two missing keys, with a backup taken first. Result: **7 of 7 pre-existing keys intact**, 13 → 17 lines.

---

## Verification — all 16

| # | Check | Result |
|---|---|---|
| 1 | `enabled()` True | ✅ **True (service)** — see note |
| 2 | Status reports enabled | ✅ `{"enabled":true,"signup_open":true,"session_ttl_s":43200}` |
| 3 | Gated surface no longer 503 | ✅ **503 → 401** (needs auth, not disabled) |
| 4 | Service active and stable | ✅ active/running, API HTTP 200 |
| 5 | PID / restarts / start | PID **1506 → 69132**, restarts **0**, start **02:17:53** |
| 6 | Store created by first use | ✅ created by a **read-only failed lookup** |
| 7 | Expected tables | ✅ **5 of 5** — see correction |
| 8 | Account rows = 0 | ✅ **0** |
| 9 | Correspondences = 0 | ✅ **0** |
| 10 | Entitlement grants = 0 | ✅ **0** (sessions also 0) |
| 11 | App identity column present | ✅ **present**, 5 users preserved |
| 12 | D-3(b) intact | ✅ 0 shared session/login imports · cookie constant unchanged · 0 files modified |
| 13 | Four routes 403, authenticated + no correspondence | ✅ **all four 403** |
| 14 | Regression | ✅ **159 passed** |
| 15 | Export boundary | ✅ 7 entries · stage 2 passes · exporter 0 changes · 0 archives · D-11 **OPEN** |
| 16 | Repository | ✅ only the pre-existing policy-doc modification |

### Note on item 1 — whose `enabled()`?

My shell reports `False`; **the service reports `True`**. That difference is correct and worth stating: my shell has no access to the root-owned mode-0600 env file, so it *should not* be able to see the secret. The authoritative reading is the service's own status route, which reports enabled.

If my shell had reported `True`, that would mean the secret was readable by an unprivileged account — a finding, not a success.

### Correction — 5 tables, not the 9 I predicted

I previously stated 9 expected tables. **That was wrong twice over:**

1. My grep counted a `CREATE INDEX` as a table (6 vs the actual 5 in the core module).
2. The other 3 belong to the **metering module, which uses a separate store** — they were never expected in this database.

The core module defines exactly **5**, and all 5 are present: accounts, sessions, attempts, entitlements, meta. **5 of 5 is the correct pass.**

### How first use was triggered without writing anything

The store is created on first access. Two attempts:
- a read-only session listing → **401 before touching the store** (correct fail-fast ordering, no creation)
- a login attempt for a **nonexistent** address → reached the lookup, **created the store and schema, wrote no record**

Confirmed by rows: accounts **0**, sessions **0**, entitlements **0**.

---

## What was created — and what was not

| Created | |
|---|---|
| Two env keys, appended | enable flag + one generated session secret (≥32) |
| Backup of the env file | root-owned, mode 0600, taken before any modification |
| systemd drop-in | mode 0644, `EnvironmentFile=-` with the deliberate leading `-` panic button |
| Shared store | 5 tables, all rows **0** |
| App identity column | nullable, no backfill, 5 users preserved |

| **Not** created | |
|---|---|
| Customer account | **0** |
| Identity correspondence | **0** |
| Entitlement grant | **0** |
| Archive | **0** |

**Enablement provisioned nothing.** That separation was verified, not assumed — item 13 proves an authenticated user with no correspondence is still refused on all four protected routes.

## A recurring error I caught this time

Before the restart, my glob of the drop-in directory returned 0 files — and I nearly recorded it as absent. The directory is mode **700 root:root**; the read was denied, not empty.

That is the **fourth** instance today of an unprivileged read returning nothing and me being tempted to read it as absence. This time I checked systemd's own view instead, which confirmed the drop-in was present without needing filesystem access. Asking an authority that does not require the blocked permission is the general fix.

---

## Disposition

# RUNTIME PREREQUISITE ENABLED AND VERIFIED

All 16 mandatory verifications pass. No rollback needed. **No repository commit warranted** — nothing in the repository changed; the new database sits under a gitignored runtime path.

## Gates preserved

```
customer account         NO (0)      identity correspondence  NO (0)
entitlement granted      NO (0)      route classifications    unchanged
authentication merged    NO          cookies/session          unchanged
exporter code/policy     unchanged   export manifest          unchanged (7)
D-11                     OPEN        D-12                     unimplemented
signing/custody infra    NO          archive produced         NO (0)
secret regenerated       NO          env file overwritten     NO (appended)
pre-existing surface keys 7 of 7 intact
persistent state deleted NO          policy document          untouched
committed                NO          pushed                   NO
```

**Customer account, identity correspondence, and entitlement provisioning remain a separate authorization.** The customer surface is reachable but still correctly closed: with no correspondence, all four protected routes refuse.
