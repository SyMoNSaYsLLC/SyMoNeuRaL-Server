# A-4 Runtime Prerequisite — Enablement Boundary Characterized

> **REDACTED COPY.** Protected artifact names, credential filenames, customer identifiers, and infrastructure details are masked as `*****`. **No secret value appears in this document** — existence, source and constraints only.

## Continues from

`a4-protected-exclusions-recorded.md`. Read-only inspection from HEAD `9b7f828a`. **Nothing changed.**

## Control point

```
HEAD                9b7f828a
tracked mods        1  (pre-existing policy doc, untouched)
subsystem enabled   False
service restarts    0
shared accounts DB  absent
```

---

## 1. Current enablement mechanism

**Two conditions, both required.** The gate is a single function in the shared module:

```
enabled() == (enable-flag == "1")  AND  (len(session-secret) >= 32)
```

Its own docstring: *"Off unless switched on AND given a secret… a misconfiguration on a box with a public IP fails closed rather than open."*

| Item | Measured |
|---|---|
| Where read | one function in the shared module |
| Controlling keys | **two** — an enable flag and a session secret; **both** participate |
| Current effective value | **`False`** |
| Consuming process | the API service, PID 1506, running since the reboot |
| Where config is supplied | **nowhere at present** — see below |
| Additional runtime condition | the secret length check *is* the second condition, not a separate flag |

**Live confirmation, from the ungated status route:**
```
{"enabled": false, "signup_open": false, "session_ttl_s": null,
 "note": "This box has not been given a session secret, so accounts are closed."}
```
A gated route returns **503** — verified.

**Gate is per-request, not per-mount.** The router is mounted unconditionally in the API; each protected handler calls a `_require_enabled()` helper that raises 503. Consequence: **flipping the flag changes behaviour without remounting anything**, but the process must re-read its environment (§4).

### ⚠️ Correction to my own earlier reporting

I previously referred to an operator-owned env file at a specific path as the place these are set. **Measured now: that file does not exist, and `/etc/symoneural/` is empty (0 entries).** My earlier statement came from the runbook's description, not from measurement — the same class of error this session has already recorded twice.

**Also measured:** the installed unit has **no `EnvironmentFile`** and **no drop-in directory**. The `10-surfaces.conf` drop-in that existed earlier in this session is gone — consistent with the unit having been restored from the pristine template after the outage.

**The sanctioned supply mechanism exists** in the surface-enabling script, which documents why: a drop-in survives re-running the installer, and secrets go in a root-owned mode-0600 env file *outside the repo* so they "can never be committed by accident."

## 2. Required secret material

| Item | Finding |
|---|---|
| Secrets required | **one** — the session secret |
| Where consumed | a `_secret()` accessor in the shared module, used for session verifier HMACs |
| Currently exists | **No.** Not in the environment, and no env file exists to hold it |
| Source | **Unresolved** — must be operator-generated |
| Constraint enforced in code | **≥ 32 characters**, checked in both `enabled()` and `_secret()` |
| Fails closed if missing/invalid | **Yes, twice over** — `enabled()` returns False, and `_secret()` raises rather than substituting |

The module refuses fallbacks explicitly: *"There is no fallback. Not a hardcoded default, not `secrets.token_bytes()` at import… a per-process generated secret would look like it worked — until the first restart, which silently logs every user out; and a hardcoded one is a forgeable session for anybody who reads this file."*

**No secret was created, rotated, copied, printed or modified.** A privileged read of the live process environment was attempted and correctly **denied** — appropriate, since that path can expose values.

## 3. Database / persistence prerequisite

| Item | Finding |
|---|---|
| Expected store | a SQLite database under the runtime directory |
| Exists now | **No** |
| Creation | **automatic** — the schema is applied on *every* connection via `CREATE TABLE IF NOT EXISTS` |
| Explicit init needed | No. An `init_db()` exists but is only "open it once so the file exists" |
| Tables required | **9** — 6 in the core module, 3 in the metering module |
| Location / ownership | under `run/`, owned by the service user |
| **Can starting the service create persistent state?** | **Not by starting alone** — the API does not call the shared `init_db()` at startup. **But the first request that touches the store creates the file and all 9 tables.** |

> **This is the single most important finding for rollback.** Persistent state is created by *first use*, not by enablement. So enablement is reversible **until a request touches the store**; after that, a database exists.
>
> Note also that this path lands **inside the protected runtime-state class** — so the new database is, correctly, never exportable.

**No database created, no migration run, no persistent state initialized.**

## 4. Runtime consumers

Three non-test consumers:

| Consumer | Imports? | Behaviour changes on flag flip? | Restart needed? | New route active? | Auth/session/cookie change? |
|---|---|---|---|---|---|
| The API service | yes | Its accounts routes stop returning 503 | **Yes** — see below | No new mount; existing gated routes begin answering | **No** |
| Application store | yes — password primitives only | **No** | n/a | No | **No** |
| Application authz | yes — entitlement lookup | **Yes** — the lookup can now reach a live store | n/a | No | **No** |

**Restart/reload is required.** systemd passes environment at process start; the running PID cannot acquire a new variable in place. So enablement needs a service restart — which is itself a gated action and *not* authorized by this task.

**D-3(b) separation is preserved by construction.** The application keeps its own login, logout, session store and cookie; only *entitlement* crosses. Verified: no session or login symbol is imported from the shared module — only password primitives. **No authentication merge occurs on enablement.**

## 5. Customer-identity bridge — reconfirmed

| Item | Measured |
|---|---|
| Application-side reference | a nullable column on the local user row |
| Shared-account key | the shared account id |
| Create / read / remove | three functions in the application store |
| **Production correspondences** | **0** — and the live application database **has not been migrated**, so the column does not yet exist there |
| **Does enablement create any correspondence?** | **No** |

**Verified rather than assumed.** I grepped every non-test call site: the only hit was the *definition* of the unlink function matching my pattern. **There is no auto-link code path anywhere.**

**Note for the enablement plan:** the live application database predates the column. The idempotent probe-then-add migration runs inside `init_db()`, which the API *does* call for the application at startup — so a restart will add the column. That is a schema change to a live database and should be named explicitly in any enablement authorization.

## 6. Entitlement effects of enablement alone

| Question | Answer | Evidence |
|---|---|---|
| Grants any entitlement? | **No** | 0 non-test call sites for the grant function |
| Creates entitlement records? | **No** | same |
| Changes the four entitlement-required routes? | **No** | classes are attached at definition, independent of the flag |
| Changes authenticated-but-unentitled 403? | **No** | with a NULL reference the lookup returns 403 before consulting the store |

**Separation is real, and I verified it rather than assuming.** With enablement but no provisioning, an authenticated user with no shared identity still receives **403** — the NULL-reference branch fires first. **Enablement and provisioning are genuinely separate operations.**

## 7. Failure and rollback

**Smallest safe rollback:** remove the enable flag from the drop-in (or remove the drop-in) and restart. `enabled()` returns to `False` and every gated route returns 503 again.

| Aspect | Behaviour on rollback |
|---|---|
| Configuration | Fully reversible — delete the drop-in line or file |
| Secret material | **Leave it in place.** Removing it is unnecessary for rollback, and re-generating later would invalidate any session issued in the interim. Rotation is a separate decision |
| Database / state | **Survives rollback if any request touched the store.** An empty 9-table database would remain. Harmless — but it is persistent state, so rollback is not byte-for-byte |
| Application column migration | **Survives, irreversibly in practice.** A nullable column with no backfill is harmless and there is no `DROP COLUMN` pattern in this repo |
| Service action | restart required (same as enablement) |
| Restores disabled behaviour without data loss? | **Yes** — nothing is deleted; the surface simply closes again |

## 8. Verification plan for a future authorization

```
 1. subsystem state          enabled() → True; status route reports enabled:true
 2. service health           active, NRestarts stable, API HTTP 200
 3. shared store readiness   database present with the 9 expected tables
 4. application login        existing users still authenticate (own cookie/session)
 5. D-3(b) separation        no session/login symbol imported from the shared module;
                             application cookie name unchanged
 6. no customer created      shared accounts table row count == 0
 7. no entitlement granted   entitlement table row count == 0
 8. unentitled still 403     authenticated user, no link → 403 on all four routes
 9. regression               A-3 (35) + application (48) + exporter + control suites
10. exporter/release         manifest still 7 entries, stage 2 passes, 0 archives,
                             D-11 still OPEN
```

Steps 6–8 are the ones that matter: they prove enablement did **not** silently provision.

## 9. Proposed implementation scope

Smallest scope needing authorization, separated as requested:

**A. Configuration changes**
- create the drop-in directory and a drop-in setting the enable flag
- create the root-owned mode-0600 env file holding the session secret
- reference it via `EnvironmentFile=` in the drop-in

**B. Secret-material actions** — ⚠️ **operator-only**
- generate one ≥32-character session secret and write it to the env file
- **irreversible in effect:** once sessions are issued against it, replacing it invalidates them

**C. Persistence initialization** — *no explicit step required*
- the store self-creates on first use
- ⚠️ **creates persistent state**, and it will happen on the first request that touches the store
- ⚠️ the application database will also gain the nullable column via the startup migration — **a schema change to a live database**

**D. Service action**
- `daemon-reload` + restart of the API service
- ⚠️ brief downtime on the only active service

**E. Verification only** — §8, no state change

### Irreversible or state-creating actions

| Action | Nature |
|---|---|
| Secret generation | Effectively irreversible once sessions exist |
| Shared store creation on first use | **Creates persistent state**; survives rollback |
| Application column migration on restart | **Schema change to a live database**; no `DROP COLUMN` pattern exists |
| Service restart | Reversible, but causes downtime |

Everything else — the flag, the drop-in, the `EnvironmentFile` reference — is fully reversible.

## 10. Decision

# READY WITH SPECIFIC PREREQUISITES

The mechanism is fully characterized, fails closed at two independent points, and enablement is verified **not** to provision anything. Three prerequisites must be settled by you first, because none can be resolved from repository evidence:

1. **Session secret generation and custody.** None exists; it is operator-only material. Where it is generated and how it is held is your decision — I did not create, read or print one.
2. **Accept that enablement creates persistent state.** The shared store self-creates on first use, and the live application database gains a column on restart. Both survive rollback. Neither is harmful; both should be named in the authorization rather than discovered.
3. **Accept a restart of the only active service.** Environment cannot be injected into a running process, so this cannot be avoided.

**One factual correction carried forward:** my earlier reports named an operator env file as the config source. **It does not exist**, and the config directory is empty — the drop-in and env file would both be *created*, not edited. That correction came from measuring rather than re-reading the runbook.

## Gates preserved

```
shared accounts enabled  NO (False, live-confirmed)   customer account        NO
identity correspondence  NO (0; column not yet live)  entitlement provisioned NO
D-11                     OPEN                          D-12                    unimplemented
external release         NOT authorized                exporter/manifest       unchanged
archive produced         NO                            service restart/reload  NO (0 restarts)
runtime config changed   NO                            secret created/exposed  NO
database created         NO (absent)                   migrations run          NO
policy document          untouched                     committed / pushed      NO
```

**NEXT AUTHORIZATION: NONE** — awaiting a ruling on the three prerequisites.
