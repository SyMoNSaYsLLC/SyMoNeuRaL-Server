# A-4 Decision Gate — Four Blocking Decisions

> **REDACTED COPY.** Protected artifact names, credential filenames, customer identifiers, and infrastructure details are masked as `*****`. Unredacted detail stays on the box.

## Continues from

`a3-committed-clean-checkpoint.md` (2026-09-01 20:55). This covers 20:55 → 21:15 — read-only decision gate. **Nothing modified.**

## Boundary confirmed

```
HEAD            ef1a4af4bdf4ae0f540b1e0a7edbd7f7baa5038c   ✓ matches stated boundary
tracked mods    1  (pre-existing policy doc, untouched)
staged          0
```

---

# A-4 Dependency Identification

The plan's own A-4 entry lists `A-2, A-3, D-3, D-4`. Measured against the repository, **that list is now stale**:

| Named | Actual status |
|---|---|
| A-2 | **COMPLETE** — committed `728df639` |
| A-3 | **COMPLETE** — committed `ef1a4af4` |
| D-3 | **RESOLVED** — option (b) recorded as fixed architecture |
| D-4 | **UNRESOLVED** — still blocks |

So one written dependency remains, and three further decisions block A-4 that its own entry does not name. Derived from decision records that *self-declare* A-4 as blocked, plus A-4's five missing slot indicators:

| # | Decision | Blocks which indicator | Evidence |
|---|---|---|---|
| **1** | **D-4** — frontend slot location | `FRONTEND_SLOT` | Decision record states `Blocks: A-4` |
| **2** | **D-5** — production route naming | `CUSTOMER_ROUTE` | Decision record states `Blocks: A-4 route naming` |
| **3** | **D-11** — signing authority & key custody | `RELEASE_IDENTITY`, `CUSTODY_RECORD` | Record states `Blocks: any external distribution`; A-4 requires both indicators and neither exists |
| **4** | **NEW — customer export scope** | `EXPORT_SCOPE` | The A-2 exporter is deliberately manifest-driven and documents scope content as an A-4 question; **zero** scope manifests exist |

**Confirmation:** no additional blocker was silently inferred. `TEST_PATH` and `ENTITLEMENT_SLOT` — the other two missing indicators — are **not** decision-blocked: A-3 delivered the entitlement seam, and A-3 added the app package's first test file, so both are implementable work rather than open questions.

---

# Decision 1 — D-4: frontend slot location

**Question:** Which path is the authoritative `FRONTEND_SLOT` for the reference customer application?

**Evidence — and this reframes the decision.** The plan offered two candidates. Measurement finds **three** locations, and the live route uses none of the two named:

| Location | State | Serves the live route? |
|---|---|---|
| Static page in the site tree | present, 59,016 bytes, **not generated** | **No** — not referenced by the backend at all |
| Next.js app directory | present, **2 files** (`page.tsx`, `error.tsx`) | **No** |
| **Backend package page module** | present, 17,413 bytes | **YES** |

The live handler's own comment states why: the path is extensionless, and the site publisher copies the site tree at `-maxdepth 1`, so an extensionless path cannot be a file there.

**Existing seams:** the UI router in the app package; the page module; the reverse proxy, which fronts the route behind basicauth.

**Does the repository already answer it? Yes — de facto.** The backend page module is what serves customers today. Adopting it requires **no new architecture**.

**Options**

| | Option | Repository impact | Components | A-1/A-2/A-3 compat | Operational |
|---|---|---|---|---|---|
| **A** | Record the backend page module as `FRONTEND_SLOT` | Documentation only | none | Full — A-3's seam already guards this router | No change; matches what runs |
| **B** | Migrate to the Next.js directory | Large — new build/deploy path for a live customer app | frontend build, proxy, deploy | A-3 classes are on the API router; a new frontend needs its own guarding | New build dependency in the serving path |
| **C** | Declare the static page authoritative | Moderate | publisher, proxy | Neutral | **Contradicts the extensionless-path constraint the code documents** |

**Tradeoffs:** A is free and true. B is the only option that materially changes customer-visible behaviour and would touch a working customer application. C fights a constraint the code already explains.

**Recommendation: Option A.** The architecture document states the tree expresses ownership, *not* a requirement to move working paths. Two of the three locations appear to be unused scaffolding — worth a separate cleanup decision, not an A-4 blocker.

**Authorization required:** record `FRONTEND_SLOT` = backend page module in the planning document. Documentation-only; no code change.

---

# Decision 2 — D-5: production route naming

**Question:** Does the customer application keep the `/demo/` route, or gain a production route now that entitlement exists?

**Evidence:** the slot template permits `/demo/<slug>` *"or approved production customer route."* Measured: 4 references to the demo path in the API, one of them the live handler. The decision record notes *"demo may misdescribe a paid deliverable."*

**Existing seams:** the UI router path; the reverse proxy mapping; catalogue links.

**Does the repository answer it? No.** This is a product-naming decision with no technical answer on disk.

**Options**

| | Option | Impact | A-3 compat | Security | Operational |
|---|---|---|---|---|---|
| **A** | Keep `/demo/` | None | Full | Neutral | Nothing to change |
| **B** | Add a production route, keep `/demo/` as alias | Moderate — two paths | Both need the same class attachment | **Two paths must not diverge in authorization** | Proxy + catalogue update |
| **C** | Rename to production-only | Moderate | Attachment moves with it | Neutral | **Breaks any existing bookmark or shared link** |

**Tradeoffs:** A costs nothing but leaves a paid deliverable labelled a demo. B is the safest transition but creates the risk that one path gets a class and the other does not. C is cleanest semantically and the only one that breaks existing links.

**Recommendation: Option A now, revisit at customer launch.** Entitlement now gates the surface regardless of its name, so the naming question is cosmetic until launch. **If B is ever chosen, an A-3-style matrix test must cover both paths** — divergent authorization on an alias is exactly the silent bypass A-3 was built to prevent.

**Authorization required:** record `CUSTOMER_ROUTE`. Documentation-only for A; B or C would need separate implementation authorization plus a route-matrix test update.

---

# Decision 3 — D-11: signing authority and key custody

**Question:** What is the signing authority and key-custody model, and must a customer deliverable be signed before release?

**Evidence:** 76,208 built packages, **zero signed** — no signature or release-index artifacts anywhere in the artifact tree. The repo's APT publication script references signing primitives but was never applied to that tree. **No signing authority, key custody, or verification authority exists.** A-4 requires `RELEASE_IDENTITY` and `CUSTODY_RECORD`; measured, the app has **0** of either.

The one signing-key artifact on disk sits inside a vendored third-party reference tree — not a project authority.

**Existing seams:** the APT publication script's signing references; the A-2 exporter, which already emits a manifest naming the source commit and a per-file digest.

**Does the repository answer it? Partially — and this is the useful finding.** A-2 already produces *release identity* for an export: source commit plus per-file SHA-256. What it does **not** produce is a **signature**, which is what makes identity verifiable by a recipient rather than merely asserted.

**Options**

| | Option | Impact | A-2 compat | Security | Operational |
|---|---|---|---|---|---|
| **A** | Full signing authority + key custody, sign at release | Large — key generation, storage, rotation, verification | Signature layer over the existing manifest | **Strongest** — recipient can verify | Ongoing key custody burden |
| **B** | Sign only externally distributed artifacts | Moderate | Same layer, narrower trigger | Strong where it matters | Requires a clear internal/external boundary |
| **C** | Defer; treat manifest + digest as sufficient identity | None | Already satisfied | **Weakest** — digests in the same archive prove nothing against tampering | No burden |
| **D** | Accept unsigned for A-4 only, blocking external release | None now | Satisfied | Acceptable **only** if release is genuinely blocked | Needs an enforced gate |

**Tradeoffs:** C's flaw is concrete — a digest shipped inside the archive it describes is not tamper-evidence, since an attacker who alters a file recomputes the digest. A is correct and carries real custody burden. **D is the honest minimum**: it lets A-4 complete its other four indicators while stating plainly that no external release is authorized.

**Recommendation: Option D for A-4, with A as the eventual target.** Populate `RELEASE_IDENTITY` from the A-2 manifest, mark `CUSTODY_RECORD` as *unsigned — external release not authorized*, and keep D-11 open as the gate on actual distribution. **Do not let A-4 completion imply release readiness.**

**Authorization required:** a ruling on whether A-4 may record an unsigned release identity. Key generation and custody would each need separate authorization — key material is operator-only and outside every authorization issued so far.

---

# Decision 4 — NEW: customer export scope

**Question:** Which artifacts is a customer allowed to receive, and where does the scope manifest live?

**Evidence:** the A-2 exporter is manifest-driven by authorized design and documents its manifest format as *"deliberately not a production manifest schema,"* explicitly deferring ownership, location, per-customer semantics and **content policy** to A-4. Measured: **zero** scope manifests exist anywhere. A-4 requires `EXPORT_SCOPE`; it has no input.

**Existing seams:** the A-2 exporter's manifest interface (newline-delimited repo-relative paths, allow-list construction, independent protected-class enforcement, fail-closed); the export policy document's protected classes.

**Does the repository answer it? No.** The *mechanism* is complete and tested; the *policy* — which files this customer may receive — exists nowhere. It is a business decision.

**Options**

| | Option | Impact | A-2 compat | Security | Operational |
|---|---|---|---|---|---|
| **A** | Per-application manifest committed beside the app | One new file | Native — exactly what the exporter consumes | Reviewable in diff; **fail-closed by construction** | Operator edits a tracked file |
| **B** | Manifest generated from entitlement records | Moderate — generator + schema extension | Compatible | Couples export scope to A-3 records; **a schema bug becomes an export bug** | Less operator control |
| **C** | Manifest supplied per-invocation by the operator | None | Native | **No reviewable record of what was authorized** | Highest flexibility, lowest auditability |
| **D** | Defer `EXPORT_SCOPE`; complete A-4's other indicators | None | n/a | Neutral — no export possible | A-4 completes partially |

**Tradeoffs:** A is the smallest thing that works and its content is visible in review — which matters, because the whole point is constraining what leaves the box. B is elegant but makes an entitlement-schema error into a data-disclosure path. C has no audit trail. D is honest but leaves the slot incomplete.

**Recommendation: Option A**, with content decided by you rather than proposed here. Determining *which* files a customer may receive is a business judgment, and inventing it is exactly what this gate forbids.

**Authorization required:** two rulings — the manifest **location/convention** (Option A or another), and the **content policy** for the reference customer. The second is a business decision no repository evidence can supply.

---

# Gate Status

## A-4 DECISIONS READY FOR AUTHORIZATION

All four blocking decisions have: an identifier, a precise question, cited repository evidence, an inventory of existing seams, a determination of whether the repository already answers it, smallest viable options with impact/compatibility/security/operational analysis, a recommendation, and the exact authorization required.

**Two decisions are effectively answerable from evidence** (D-4 de facto; D-11 via the A-2 manifest for identity-without-signature). **Two require your judgment** and cannot be resolved from the repository: D-5 is product naming, and Decision 4's content policy is a business decision.

**Shared-accounts enablement remains separate.** Not enabled, no secret created, no configuration modified — and **not** implied by any recommendation here. Note the standing consequence: until it is enabled, every entitlement-required route returns 403, so a customer cannot reach the application regardless of these four decisions.

## Scope audit

```
AUTHORIZED SCOPE TOUCHED:   NONE — read-only inspection only
UNAUTHORIZED SCOPE TOUCHED: NONE
```

No source, schema, migration, or configuration modified · no credentials or secrets created · shared accounts not enabled · no services restarted · runtime unchanged · A-4 not begun · nothing staged, committed, or pushed · pre-existing dirty files untouched · no decision resolved by assumption.

**NEXT AUTHORIZATION: NONE** — awaiting rulings on D-4, D-5, D-11, and the export-scope decision.
