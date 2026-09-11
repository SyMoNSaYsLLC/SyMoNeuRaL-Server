# A-4 Customer Provisioned — Entitlement Verified End to End

> **REDACTED COPY.** Customer identifiers, paths and infrastructure details are masked as `*****`. **No password, hash, token or secret value was printed** at any point.

## Continues from

`a4-runtime-prerequisite-enabled.md`. One provisioning chain: account → correspondence → entitlement → verification.

---

## 1. Target application user — and the evidence

**Selected: application user id 5, the customer-role account labelled for the reference customer.**

Not chosen from row order, display name, or a hunch. Three independent lines of evidence:

| Evidence | Finding |
|---|---|
| **Role** | The only `customer`-role user that is **not** part of the seeded test set |
| **Seed exclusion** | The seeding helper creates exactly four fixed accounts — two operators, two customer-view — and its docstring names them as the accounts "asked to test". The target appears **0 times** in that helper, so it was created deliberately, not seeded |
| **Architecture** | The slotting architecture names this customer **15 times** as *the reference customer slot* |

The other four users are documented test accounts at two tiers. The target is the only real customer identity present.

**Preconditions, all clean before any write:**

```
existing shared reference    NULL
shared accounts              0
accounts matching customer   0
existing entitlements        0
existing sessions            0
```

## 2. Shared account created — exactly one

```
id           a3ee3403421c12599d66f694df56e755
display      Donnie
disabled     False
```

**Provisioning seam — a real constraint worth recording.** The operator CLI has link/grant/revoke but **no shared-account creation**. The library function exists, but it requires the session secret, which my shell deliberately cannot read (mode-0600 root-owned). So the account was created through the shared authority's own route, executing **inside the service**, which holds the secret.

`signup_open` was **already `True`** — no setting was changed to enable this. Password generated locally, used once, never printed, never stored by me.

No second account authority invented · no authentication architecture change · exactly one account · no test/demo accounts.

## 3. Correspondence — exactly one

| user | shared reference |
|---|---|
| 1 operator | — |
| 2 operator | — |
| 3 customer-view | — |
| 4 customer-view | — |
| **5 target** | **a3ee3403…e755** |

**Correspondence count: 1.** The other four remain unlinked. No backfill, no inference.

## 4. Entitlement — exactly one active grant

```
account a3ee3403421c...   app <this application>   ACTIVE
granted_by operator-provisioning-2026-09-02
```

Total grants **1** · active for this application **1** · grants for other applications **0** · no wildcard · no duplicate · no route-classification change.

## 5. End-to-end verification — both sides

### Provisioned customer — authorized on all four

| Route | Result |
|---|---|
| `GET /board` | **200** authorized |
| `POST /bookings` | **201** authorized — created a booking owned by the target user |
| `GET /bookings/{own}` | **200** authorized |
| `POST /ask` | **200** authorized |

**Entitlement-denied 403s: 0 of 4.**

**Two results needed distinguishing from authorization failure**, per the instruction:

- A first pass showed `422` on two routes — **my malformed test payload**, not a refusal. Corrected payloads returned 201 and 200.
- `GET /bookings/1` returned `403 "that booking is not yours"` — **ownership scoping, not entitlement.** Booking 1 belongs to a different user. Re-tested against a booking the customer *does* own: **200**. Ownership and entitlement are separate axes and both work.

### Unprovisioned user — still refused (mandatory)

Authenticated as a customer-view user with correspondence `NULL`:

| Route | Result |
|---|---|
| `GET /board` · `POST /bookings` · `GET /bookings/{id}` · `POST /ask` | **403 on all four** |

Reason returned: *"this account is not entitled to this application"* — the entitlement branch, not authentication.

## 6. Production counts

| Metric | Count |
|---|---|
| Shared customer/accounts | **1** |
| Shared sessions | **1** |
| Application users | **5** (unchanged) |
| Identity correspondences | **1** |
| Entitlement grants total | **1** |
| Active grants, this application | **1** |

No unexpected pre-existing records. Nothing normalized or deleted.

**The 1 shared session is from signup**, not app login — the shared route issues a session on account creation. App-side sessions live in a separate table (2 rows). **Two independent session stores** is exactly D-3(b).

## 7. Regression — 159 passed

Authorization, application, control-model and exporter suites all green. Both invariants preserved: authenticated+unlinked → 403, authenticated+linked+entitled → authorized.

## 8. Export / release boundary — unchanged

```
manifest entries          7
stage 1 / stage 2         7 selected / 0 protected -- passed
exporter or manifest mod  0
archives produced         0
customer data in entries  0
shared database           refused by stage 2 as PROTECTED [runtime state]
D-11                      OPEN
```

**One check needed correcting:** a grep for customer data in the manifest returned `1`. That match was **line 34 — a comment** documenting the runtime-state exclusion, not an entry. Stripping comments: **0 of 7 entries** carry customer data. Reported rather than glossed, since an uninvestigated `1` is exactly the kind of thing that becomes a false claim.

## 9. D-3(b) verification

```
shared session/login imported by app   0   (must be 0)
app cookie constant                    unchanged
app source modified                    0 files
session stores                         2 independent (1 shared, 2 app rows)
```

Application login, logout, session store and cookie identity all unchanged. No merge.

## 11–12. Repository

```
$ git status --short
 M ops/docs/EXPORTS.md      ← pre-existing, prior authorization, untouched
```

**No repository source modified** — no defect blocked the provisioning path. **No commit. No push.** All writes were runtime data under gitignored paths.

---

## Disposition

# CUSTOMER PROVISIONED AND ENTITLEMENT VERIFIED

One account, one correspondence, one active grant. The provisioned customer reaches normal authorized behaviour on all four protected routes; an authenticated unprovisioned user is still refused on all four with the entitlement reason.

## Gates preserved

```
accounts created         1 (exactly the intended customer)
correspondences          1 (target only; other 4 untouched)
entitlement grants       1 active, correct application, no wildcard
routes altered           NO      authentication merged      NO
cookies/session          unchanged   schemas changed         NO
enablement modified      NO      session secret rotated     NO
env file rewritten       NO      systemd altered            NO
exporter/manifest        unchanged   archive produced        NO (0)
D-11                     OPEN    D-12                       unimplemented
signing/custody infra    NO      committed / pushed         NO
policy document          untouched   records deleted         NO
```

**D-11 and D-12 remain separate gates. External release remains NOT authorized.**
