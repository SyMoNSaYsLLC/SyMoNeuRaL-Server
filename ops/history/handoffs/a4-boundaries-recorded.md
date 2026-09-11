# A-4 Boundaries Recorded — Clean Checkpoint

> **REDACTED COPY.** Protected artifact names, credential filenames, customer identifiers, and infrastructure details are masked as `*****`. Unredacted detail stays on the box.

## Continues from

`a4-config-asset-boundary-decisions.md`. You authorized both as Option A. Documentation-only; committed.

## 1. Commit

```
c5685867b6dcb41e91a4b1877269dac23d10b9fe
Record the customer configuration and asset boundaries

  1 file changed, 36 insertions(+), 2 deletions(-)
```

**Exactly 1 file:** the A-4 record. Nothing else.

## 2. `CONFIG_SLOT` recorded

Five categories, from measurement:

| Category | Content | Export position |
|---|---|---|
| **Customer-specific** | Operator's rate rules — **one key** in the application settings table | **Not exportable** — resides in the runtime database, which stage 2 refuses |
| **Application defaults** | **None.** Unconfigured renders blank by design | Nothing to export |
| **Shared / platform** | Shared subsystem enable flag + session secret | Platform-owned |
| **Runtime / operator** | Surface flag + database path, operator-owned env file | Operator-owned |
| **Protected internal** | Secrets, `.env`, credentials, private keys, signing material, api keys, runtime state, restricted ledgers, internal review material, repository history, infrastructure config | **Never exportable** — stage 2, independent of any manifest |

**Resulting position: no configuration of any category enters the customer export.**

The record states explicitly that no export path was built, rate rules were not extracted, and **no exception was added to the runtime-state refusal** — noting that whether customer configuration may ever leave that database is a *separate safety decision*, because carving a hole in a refusal for convenience is the failure shape this project keeps guarding against.

## 3. `ASSET_SLOT` recorded

| Category | Content | Export position |
|---|---|---|
| **Customer-owned** | **None exist** — no asset directory, no upload path, no binary storage | Class is **empty**, not unknown |
| **Application-default** | **None.** Page self-contained: 1 inline style, 1 inline script, **0** external references | Presentation is source, travels as source |
| **Shared platform** | Shared brand directory + shared site CSS/JS | Platform-owned, never per-customer |
| **Protected internal** | Adapter weights, signing material, secrets, model payloads | **Never exportable** — stage 2 |
| **Generated / transient** | **None** — no output directory, no generated media | — |

**Resulting position: no asset of any category enters the customer export.**

Recorded explicitly: **the static preview page is not a customer asset.** D-4 measured that the live route renders from the page module and that file is unreferenced by the backend — exporting it would ship a **stale duplicate that can silently diverge** from what the customer actually sees.

## 4. Exporter and manifest unchanged

```
exporter:  0 changes    0 occurrences in this commit
manifest:  0 changes    0 occurrences in this commit

Re-verified: stage 1 selected 7, stage 2 passed, no archive written
```

Neither decision required a manifest change, and none was made.

## 5. No production or runtime files changed

```
backend/ 0   tools/ 0   control/ 0   site/ 0   frontend/ 0
ops/ 0       web/ 0     engines/ 0   run/ 0
```

## 6–7. Diff and status

```
$ git diff --cached --stat        (pre-commit)
 <A-4 record> | 38 ++++--
 1 file changed, 36 insertions(+), 2 deletions(-)

$ git status --short              (post-commit)
 M ops/docs/EXPORTS.md      ← pre-existing, prior authorization, NOT swept in
```

---

## On the slot state — why `DEFINED — satisfied`

The instruction was to use the satisfied state *only if the evidence standard permits*, otherwise the strongest evidence-supported state.

Checked both: §10 requires **`Defined`** for these two indicators, and the vocabulary defines `DEFINED` as *"named in the architecture or a document; no implementation claim."*

So `DEFINED` **is** the satisfied state here — the requirement is a definition, and the definition now exists from measurement. I did **not** promote either to `PRESENT`: a boundary is not an on-disk artifact, so `PRESENT` would be a claim the evidence does not carry. Both rows read `DEFINED — satisfied` with the reasoning recorded inline.

## Final A-4 slot states — 19 indicators

| State | Indicators |
|---|---|
| **VERIFIED** (2) | `FRONTEND_SLOT`, `API_SLOT` |
| **POPULATED, VERIFIED** (1) | `EXPORT_SCOPE` |
| **PRESENT — PASSING** (1) | `TEST_PATH` |
| **WIRED** (3) | `APPLICATION_SLUG`, `CUSTOMER_ROUTE`, `LIVE_STACK_ENTRY` |
| **WIRED — no record provisioned** (1) | `ENTITLEMENT_SLOT` |
| **PRESENT** (3) | `APPLICATION_IDENTITY`, `BACKEND_SLOT`, `WORKFLOW_SLOT` |
| **AUTHORIZED (A-4 only)** (2) | `RELEASE_IDENTITY`, `CUSTODY_RECORD` |
| **DEFINED — satisfied** (2) | `CONFIG_SLOT`, `ASSET_SLOT` ← this commit |
| **DEFINED** (2) | `CUSTOMER_IDENTITY` (not PRESENT), `PROTECTED_EXCLUSIONS` |
| **EXISTING-INCOMPLETE** (2) | `AUTH_SLOT` (by design — D-3(b)), `SHARED_SERVICE_MAP` |

**A-4 is not complete**, and this commit does not claim otherwise. Two boundaries moved from undocumented to recorded.

## Regression intact

**68 passed** post-commit across the application, authorization and exporter suites.

## Session commit chain

```
728df639 [A-2] → a5fb0fbb [A-1] → ef1a4af4 [A-3]
94156d39 [A-4 export scope] → eaaa9d6a [A-4 repair] → c5685867 [A-4 boundaries]  ← HEAD
```

---

## Remaining A-4 gates

| # | Gate | Type | Blocks |
|---|---|---|---|
| **1** | **Runtime prerequisite** — shared accounts disabled | Separate authorization (config + secret material) | `CUSTOMER_IDENTITY`, `SHARED_SERVICE_MAP`, all provisioning |
| **2** | Customer account + entitlement provisioning | Authorization; depends on #1 | `CUSTOMER_IDENTITY`, `ENTITLEMENT_SLOT` → PRESENT |
| **3** | Per-application protected-exclusions statement | Documentation | `PROTECTED_EXCLUSIONS` |
| **4** | `D-11` signing authority | **OPEN** | External release only |
| **5** | `D-12` mechanical ownership guard | **OPEN**, unimplemented | Nothing today |
| — | `AUTH_SLOT` | **No gate** — D-3(b) is the intended end state | Nothing |

**Smallest next step:** gate 3 — documentation only, unblocked, needs no runtime change. Gate 1 is the only one unlocking the remaining indicators and is deliberately separate.

## Gates preserved

```
shared accounts enabled  NO (False)   customer account        NO
entitlement provisioned  NO           D-11                    OPEN
D-12                     unimplemented external release       NOT authorized
exporter behaviour       unchanged    export manifest         unchanged
runtime/configuration    unchanged    services restarted      NO (0)
archive produced         NO (0)       policy document         NOT swept in
asset directory created  NO           assets moved/copied     NO
pushed                   NO
```

**NEXT AUTHORIZATION: NONE**
