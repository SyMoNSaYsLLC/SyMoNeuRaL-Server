# A-4 — Three Decisions Recorded + Export-Scope Content Decision

> **REDACTED COPY.** Protected artifact names, credential filenames, customer identifiers, and infrastructure details are masked as `*****`. Unredacted detail stays on the box.

## Continues from

`a4-decision-gate.md` (2026-09-01 21:15). You authorized three decisions plus the export-scope *mechanism*. This covers 21:15 → 2026-09-02 — recording, then the content decision.

## Control point

```
HEAD          ef1a4af4   (no commits — A-4 implementation commit deliberately withheld)
tracked mods  1          (pre-existing policy doc, untouched)
staged        0
```

---

# Part 1 — Decisions recorded

Four slot rows updated in the reference-slot table. **10 diff lines, documentation only.**

| Indicator | Recorded value | Status |
|---|---|---|
| `FRONTEND_SLOT` | **backend package page module** (served by the UI router) | **VERIFIED** — D-4 = (a) |
| `CUSTOMER_ROUTE` | existing `/demo/` route retained | **WIRED** — D-5 = (a) |
| `RELEASE_IDENTITY` | A-2 manifest: source commit + per-file SHA-256 | **AUTHORIZED (A-4 only)** — D-11 = (d) |
| `CUSTODY_RECORD` | **UNSIGNED — external release NOT authorized** | **AUTHORIZED (A-4 only)**, D-11 remains **OPEN** |
| `EXPORT_SCOPE` | per-application tracked manifest beside the app | **MECHANISM AUTHORIZED, CONTENT UNDECIDED** |

Each row carries its evidence. `CUSTODY_RECORD` records explicitly that no key generation, key storage, signing infrastructure, artifact signing, or external distribution is authorized, and that **A-4 completion must never be represented as external-release readiness.**

No migration, no serving-path change, no alias, no rename, no proxy or catalogue change.

---

# Part 2 — Export-scope content decision

## 1. Candidate deliverable artifacts — inventoried

| Group | Artifacts | Size |
|---|---|---|
| **Backend package** | 8 source modules incl. store, routes, page, authz, quotes, assistant | ~110 KB |
| **Tests** | route-authorization suite (in-package), 2 further app suites elsewhere, 1 frontend slice test | ~30 KB |
| **Smoke record** | in-package | 10.9 KB |
| **Rendered page** | static customer-facing page in the site tree | 59 KB |
| **Docs preview** | share-preview copy of the same page | — |
| **Next.js files** | 2 files (page + error) | 2.3 KB |
| **Runtime state** | application database + WAL/SHM | ~106 KB |
| **Operator tooling** | provisioning CLI, launcher | — |
| **Prior archives** | **4 existing export archives with manifests** | — |

## 2. Classification against the existing policy

**The prior archives are the most useful evidence here — and they answer in the negative.** Two of the four carry, in their own manifests:

```
customer_deliverable=no
internal_archive_only=yes
```

And their contents include internal infrastructure config (the reverse-proxy configuration). **These are not precedent for customer delivery.** They are internal snapshots, and reusing their content set would ship infrastructure configuration to a customer.

| Candidate | Class | Exportable? |
|---|---|---|
| Rendered customer page | customer-facing output | **Yes** |
| Docs preview copy | duplicate of the above | Yes, redundant |
| Smoke record | internal verification evidence | Questionable — internal |
| Backend source modules | **first-party proprietary source** | Policy-dependent |
| Test suites | first-party source | Policy-dependent |
| Next.js files | first-party source, **serves nothing** (D-4) | Policy-dependent, low value |
| Operator CLI / launcher | **internal operator tooling** | **No** |
| Runtime database | **runtime state — prohibited (policy rule 3)** | **No** |
| Prior archives | **internal-only, contain infrastructure config** | **No** |

## 3. Technically exportable through the A-2 mechanism

The exporter is allow-list constructed with independent protected-class enforcement. **Verified live this pass:** a manifest naming the runtime-state directory is refused —

```
PROTECTED [runtime state] run/state.db
REFUSED -- 1 protected path(s) in the candidate set; no archive written
```

So the runtime database is **unexportable regardless of any policy you choose** — the mechanism refuses it. Everything else in the inventory is technically exportable if named; the question is entirely policy.

## 4. Smallest explicit content-policy options

| | Option | Includes | Excludes |
|---|---|---|---|
| **A** | **Rendered page only** | The customer-facing page | All source, tests, smoke, tooling, runtime state, archives |
| **B** | **Page + application source** | Page + the 8 backend modules | Tests, smoke, tooling, runtime state, archives, other customers |
| **C** | **Page + source + tests** | B plus the app's test suites | Smoke, tooling, runtime state, archives |
| **D** | **Documentation-only** | Page + a customer-facing README written for the purpose | Everything else, including all source |

## 5. What each option means concretely

- **A** — the customer receives what they already see in a browser. Zero proprietary source leaves the box. Smallest possible surface; arguably little value beyond a page they can already load.
- **B** — the customer receives the application built for them. This is the "GitHub-like download" originally described. **It ships first-party proprietary source**, which is a genuine ownership decision, not a technical one.
- **C** — B plus evidence the application is tested. Tests are often the most instructive artifact for a recipient, and also the most revealing of internal practice.
- **D** — no source at all; a deliberately authored customer document. Requires writing something that does not yet exist.

## 6. Prohibited independently of the chosen option

These remain excluded under **every** option, enforced by the exporter's stage 2 rather than by manifest discipline:

- protected training material (corpus, dataset builder, adapter weights)
- credentials, secrets, tokens, `.env` files, private keys
- **signing material** — none exists, and D-11 remains open
- **internal infrastructure configuration** — including the reverse-proxy config the prior archives contained
- custody and internal audit material, mode-restricted ledgers, internal review material
- **runtime state** — proven refused above
- **any other customer's data**
- canonical repository source history

Two additions specific to this application, from the inventory:
- **the operator provisioning CLI** — it is the sole entitlement writer; shipping it to a customer would hand over the grant mechanism
- **the four prior archives** — self-labelled internal-only and containing infrastructure config

## 7. Recommendation

**Option B**, with two caveats I would rather state than bury:

It is the only option matching the original request — a customer downloading "a zipped version of what we are allowing them to have." A and D deliver something the customer already has or has to be newly written; C adds internal test practice for marginal benefit.

**Caveat 1 — this is an ownership decision, not a technical one.** B ships first-party proprietary source. The architecture separates *customer-specific* from *shared platform* responsibility, and the application's modules are first-party work. Whether the customer receives them is yours alone.

**Caveat 2 — verify the module boundary before populating.** Some modules may import shared platform code. If a module pulls in shared infrastructure, naming it in the manifest could pull that in too. The exporter's stage 2 catches *protected classes*, not *shared-but-unprotected* platform source. That check belongs in the populate step, not here.

**Not selected.** Per your instruction, the option remains yours.

---

## Scope audit

```
AUTHORIZED SCOPE TOUCHED:
  planning document  (4 slot rows recorded, 10 diff lines)

UNAUTHORIZED SCOPE TOUCHED: NONE
```

No manifest created · no file exported · `EXPORT_SCOPE` not implemented · no customer distribution · shared accounts not enabled · no secrets or credentials created · authentication, sessions, cookies, entitlement semantics, routes, services, runtime config, signing and release infrastructure all unchanged · pre-existing dirty files untouched · **no A-4 implementation commit**.

## Stop conditions met

- ✅ D-4 recorded · ✅ D-5 recorded · ✅ A-4-specific D-11 ruling recorded
- ✅ Export-scope content decision ready for authorization

## Still open

- **D-1, D-2, D-6 … D-11** undecided (**D-11 explicitly still open**)
- **A-8** blocked on contaminated units
- Packaging/signing/custody: decisions exist, **zero implementation coverage**
- **Runtime prerequisite:** shared accounts remains disabled — every entitlement route returns 403, so no customer can reach the application

**NEXT AUTHORIZATION: NONE** — awaiting the export-scope content policy ruling.
