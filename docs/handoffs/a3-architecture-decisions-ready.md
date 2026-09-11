# D-A3-1 & D-A3-2 — Evidence, Options, Recommendations

> **REDACTED COPY.** Protected artifact names, credential filenames, customer identifiers, and infrastructure details are masked as `*****`. Unredacted detail stays on the box.

## Continues from

`a3-plan-revised.md` (2026-09-01 19:30). That handoff returned NOT READY on two missing definitions. This covers 19:30 → 19:50 — **decision resolution only, nothing implemented.**

## Control point

```
HEAD                          a5fb0fbb   (no commits)
implementation files changed  0          (hashes verified unchanged)
tracked modifications         1          (export policy doc, previously authorized)
schema created                0
```

---

# D-A3-1 — Entitlement store

## Evidence

**No entitlement-shaped schema exists anywhere.** Searched every application package for a table matching entitlement / grant / permission / access / application. **Zero matches.**

**Existing stores (candidate seams):**

| Store | Owner | Relevance |
|---|---|---|
| Shared accounts DB | shared accounts | `accounts`, `sessions`, `attempts`, `meta` — the natural home for a customer→application mapping |
| Customer app DB | the customer application | `users`, `sessions`, `bookings`, `drivers`, `login_attempts` — app-local |
| Money store | shared accounts | `balances`, `holds`, `ledger` — separate concern |
| Two unrelated stores | other surfaces | not applicable |

**Does an existing schema satisfy the requirement? No.**

The licence-entitlement module was the plausible candidate and **does not fit**. It keys on:

```
workspace  = keccak of a build configuration
payer      = a settlement address
nonce      = quote nonce, 1:1 with an on-chain licence
network    = which chain it settled on
```

It answers *"was this licence paid for"*. It carries **no customer identity and no application identity**, so it cannot answer *"may this customer open this application"*. Different question, different keys — it must not be overloaded.

**Two useful precedents exist in shared accounts:**
- A `meta` table carrying a schema-version key — an established migration path
- An optional **opaque link column** on the account record, documented as an opaque reference and never a value — precedent for linking an account to something owned elsewhere

## Options — smallest first

**Option A — one join table in the shared accounts store**
```
(account_id, application_slug, granted_at, revoked_at NULL)
PRIMARY KEY (account_id, application_slug)
```
Three or four columns. Revocation by timestamp, not deletion, so a revoked grant remains auditable.

- **For:** smallest thing that answers the question; lives with the identity it references; foreign-key integrity to the account row; naturally multi-application and multi-customer; revocation is a write, not a delete
- **Against:** requires a schema addition to the shared store; couples the app's authorization path to a store that is **currently switched off on this box**

**Option B — an opaque entitlement column on the existing account row**
Reuse the established opaque-link pattern; store a slug list.

- **For:** no new table; uses a documented precedent
- **Against:** a list in a column cannot express per-grant timestamps or revocation history; every read parses; concurrent grants race. Does not scale past one application per customer without becoming the join table anyway

**Option C — entitlement table in the customer application's own store**
- **For:** no shared-store change; works with shared accounts switched off
- **Against:** **defeats the purpose.** The mapping is *shared* infrastructure by definition — one per application means every future customer application reinvents it, which is the duplication the platform architecture forbids. Also contradicts D-3(b), which bridges *to* the shared authority

**Option D — a third, dedicated entitlement store**
- **For:** clean ownership boundary
- **Against:** a third database for one small table; no foreign-key integrity to accounts; another file to back up, migrate and reason about

## Write authority

Measured: shared accounts exposes **eight endpoints** — status, signup, login, logout, me, sessions, password, signout-everywhere. **None grants, updates, or revokes anything application-scoped.** No admin or operator write surface exists there.

One high-privilege mechanism does exist: a **single environment-supplied bearer token** used as an owner-level credential.

Candidates for the authorized writer:

| Candidate | Assessment |
|---|---|
| **Operator CLI tool** (the pattern already used to provision app users) | **Smallest and most consistent.** Provisioning is already an operator-run CLI action, not an API call. No new authenticated write surface, so no new attack surface |
| New authenticated admin API on shared accounts | More capable, but adds a privileged write endpoint that does not exist today — a larger security decision |
| Existing high-privilege bearer | Available, but it is a single coarse credential; using it for per-customer grants gives one token authority over all entitlement |
| Self-service | **Rejected on its face** — a customer granting their own entitlement is not entitlement |

## Recommendation — D-A3-1

**Option A** (join table in the shared accounts store), with the **operator CLI** as the authorized writer.

Reasons: it is the smallest schema that answers the actual question; it keeps the mapping with the identity it references and gains referential integrity; revocation is auditable; and choosing the CLI writer adds **no** new privileged endpoint, matching how user provisioning already works here.

**Caveat you should weigh:** shared accounts is **switched off on this box** (it wants an enable flag and a session secret, and neither is set). Option A therefore couples the app's authorization path to a currently-inactive subsystem. That is a sequencing question — enabling it is a separate authorization — not an argument against the schema.

---

# D-A3-2 — Identity correspondence

## Evidence

**Identity keys available on each side:**

| Side | Primary key | Unique natural key | Notes |
|---|---|---|---|
| Shared accounts | `id` — TEXT | **`email`** — UNIQUE, normalised (NFKC, lowercased, trimmed) | also stores the email exactly as typed |
| Customer app | `id` — INTEGER | **`username`** — UNIQUE, **case-insensitive collation** | **no email column** |

**Does a stable correspondence already exist? No — and the absence is deliberate.**

Three measured facts:

1. **No shared field.** The app's user table has **no email column** and **no account-reference column**. Zero overlap between the two key sets.
2. **The existing seam carries no identity.** The app imports only *pure password functions* from shared accounts — hashing, verification, validation. Function imports, not data linkage. Nothing correlates a row on one side to a row on the other.
3. **Non-correspondence is documented.** The app's store states its roles *"are not the site's roles and do not map onto them."* The separation is intentional, and D-3(b) preserves it.

`username` and `email` are also **not interchangeable**: one is a case-insensitive handle, the other a normalised address. Treating a handle as an address would be an inference, not a mapping.

## Options — smallest first

**Option A — explicit link column on the app's user row**
Add a nullable reference to the shared account id. Populated at provisioning; `NULL` means "no shared identity, therefore no entitlement".

- **For:** explicit, one column, no ambiguity; `NULL` is a **safe fail-closed default**; keeps both auth systems untouched; matches the opaque-link precedent already used in shared accounts
- **Against:** requires a schema addition to the app store; provisioning must set it; existing rows start `NULL` (correct — they have no shared identity)

**Option B — a correspondence table in the shared store**
`(app_user_ref, account_id)` alongside the entitlement table.

- **For:** the app schema is untouched; both mappings live together
- **Against:** two lookups per authorization; a second table to keep consistent; **stores a foreign application's primary key in shared infrastructure**, inverting the dependency direction

**Option C — match on email**
- **Against:** **the app does not store email.** This option cannot be implemented without first adding the column — at which point Option A is strictly simpler and more explicit

**Option D — match `username` to `email`**
- **Against:** **reject.** Different types, different normalisation, different uniqueness semantics. A silent identity collision here is an authorization bypass — precisely the inference this task forbids

## Recommendation — D-A3-2

**Option A** — one nullable explicit link column on the app's user row, populated at provisioning.

Reasons: it is the only option that adds no lookup indirection, keeps the dependency pointing the right way (application references shared infrastructure, not the reverse), and gives a **fail-closed default for free** — an unlinked user has no shared identity and therefore no entitlement, with no special-casing.

Unchanged under this option: the app's cookie, session store, login and logout endpoints, and both roles. No authentication systems are merged.

---

## Summary

| Decision | Recommendation | Writer | Fail-closed default |
|---|---|---|---|
| **D-A3-1** entitlement store | Join table in the shared accounts store | Operator CLI | No row = not entitled |
| **D-A3-2** identity correspondence | Nullable explicit link column on the app user row | Set at provisioning | `NULL` = no shared identity = not entitled |

Both defaults deny. Neither requires merging authentication.

**One sequencing dependency to note:** shared accounts is currently switched off on this box. Enabling it is a separate authorization and is a prerequisite for the entitlement lookup to function at runtime — though not for deciding the schema.

---

## Scope audit

```
AUTHORIZED SCOPE TOUCHED: NONE — read-only evidence gathering
UNAUTHORIZED SCOPE TOUCHED: NONE
```

No tables · no migrations · no models · no routes · no code · no schema created · no authentication merged · cookies, sessions, login/logout and roles all untouched · handler and store hashes verified unchanged · nothing staged or committed.

## Still open from earlier

- **D-1, D-2, D-4, D-6 … D-11** undecided
- **A-4** blocked on four decisions plus A-3 · **A-8** blocked on contaminated units
- Packaging/signing/custody: decisions exist, **zero implementation coverage**
- Production manifest **NOT DEFINED**
- **New:** shared accounts is switched off — a runtime prerequisite for entitlement

## To resume

Both decisions are **ready for authorization**. Accept or amend each recommendation; A-3 becomes implementable once both are fixed.

**NEXT AUTHORIZATION: NONE** — awaiting your ruling on D-A3-1 and D-A3-2.
