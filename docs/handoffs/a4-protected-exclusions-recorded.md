# A-4 PROTECTED_EXCLUSIONS Recorded — Clean Checkpoint

> **REDACTED COPY.** Protected artifact names, credential filenames, customer identifiers, and infrastructure details are masked as `*****`. Unredacted detail stays on the box.

## Continues from

`a4-boundaries-recorded.md` (HEAD was `c5685867`). Documentation-only; committed.

## 1. Commit and file changed

```
9b7f828a0836cca7658db9029dd31e34feabe875
Record what must never enter this application's customer export
```

**Exactly 1 file:** the A-4 record. Nothing else.

## 2. The statement — 12 classes, two enforcement tiers

**The distinction that carries the weight:** nine classes are refused *mechanically* whatever a manifest says. Three are not — tested this pass, a manifest naming them **passes the protected-class stage unflagged**, because none is a secret, training material, or runtime state. The statement says so **per class**, rather than implying uniform enforcement.

### Mechanically enforced — 9 classes

| # | Class | This application's artifacts |
|---|---|---|
| 1 | Secrets and credentials | Credential files; the app stores password hashes, never plaintext |
| 2 | Operator environment configuration | The operator-owned env file supplying the surface flag and DB path |
| 3 | Private keys and signing material | **None exist** — D-11 open, no signing authority |
| 4 | API keys and tokens | Session tokens hashed in the runtime store |
| 5 | Runtime databases and state | The app database + WAL/SHM — **and the customer's rate rules live inside it** |
| 6 | Restricted ledgers / custody | No custody record exists (unsigned per D-11) |
| 7 | Internal review / audit material | Internal review directory |
| 8 | Repository history / dev metadata | History, build caches |
| 9 | Model payloads / adapter weights | App loads none, but the assistant layer can reach shared inference |

### Manifest discipline only — 3 classes

| # | Class | Evidence |
|---|---|---|
| 10 | Internal infrastructure configuration | The prior internal archive carried **5** such paths |
| 11 | Shared platform assets / configuration | Shared brand directory (135 files), shared site CSS/JS, and the shared accounts module — category 2, already ruled not exportable |
| 12 | **Application-specific** | **(a)** the 4 prior archives — own manifests read `customer_deliverable=no` / `internal_archive_only=yes` and they carry infrastructure config · **(b)** the operator provisioning CLI — **sole entitlement writer**, shipping it hands over the grant mechanism · **(c)** the static preview page — unreferenced, would ship a stale duplicate · **(d)** test suites — excluded by the page-plus-source ruling |

Class 12 is the part that could not have been inferred; each item rests on measured evidence.

## 3. Evidence per class

Classes 1–9: the **17 global stage-2 patterns**, verified enforcing this pass (runtime state refusal demonstrated live).
Class 10: measured — 5 infrastructure paths inside a prior archive.
Class 11: measured — 135 shared brand files, 3 shared CSS/JS, plus the earlier category-2 ruling.
Class 12: measured — 4 archives with self-labelling manifests; the CLI is the only entitlement writer; the static page is unreferenced by the backend (D-4); tests excluded by your Option B ruling.

## 4. Manifest compliance — verified, 0 violations

The authorized 7-entry manifest was checked against **15 patterns** covering every class:

```
runtime state · .env · credentials · keys · tokens · review material ·
repository history · infrastructure config · prior archives · operator tooling ·
static site tree · shared brand assets · training material · tests · smoke records

→ 0 occurrences of each
```

**No currently authorized export entry conflicts with any exclusion.** No manifest change was required and none was made.

## 5. Exporter behaviour — unchanged

```
exporter code:            0 changes,  0 occurrences in the commit
exporter policy classes:  unchanged
export manifest:          0 changes,  0 occurrences in the commit

Re-verified: stage 1 selected 7, stage 2 passed, no archive written
```

The record states explicitly that this task **created no new exporter rules**, that global protections **remain the mechanical enforcement authority**, and that the statement **documents** the boundary without replacing or narrowing global enforcement — where the two overlap, global enforcement wins.

## 6. No production or runtime file changed

```
backend/ 0   tools/ 0   control/ 0   site/ 0   frontend/ 0
ops/ 0       web/ 0     engines/ 0   run/ 0
```

## 7–8. Diff and status

```
$ git diff --cached --stat        (pre-commit)
 <A-4 record> | 42 +++++++++-
 1 file changed

$ git status --short              (post-commit)
 M docs/ops/EXPORTS.md      ← pre-existing, prior authorization, NOT swept in
```

---

## Final `PROTECTED_EXCLUSIONS` state

**`DEFINED — satisfied`**

Same reasoning as the two prior boundary slots: §10 requires `Defined`, and the vocabulary defines that as *"named in the architecture or a document; no implementation claim."* The statement is a definition, not an on-disk artifact, so `PRESENT` would be a claim the evidence does not carry. I did not promote it.

## Verification result

| Check | Result |
|---|---|
| Manifest verifies through the exporter | **stage 1: 7 · stage 2: passed** |
| Manifest complies with all 12 classes | **0 violations / 15 checks** |
| Regression | **68 passed** |
| Exporter / manifest / production files | **0 changes** |

## A-4 slot summary — 19 indicators

**VERIFIED** (2) · **POPULATED, VERIFIED** (1) · **PRESENT — PASSING** (1) · **WIRED** (3) · **WIRED — no record provisioned** (1) · **PRESENT** (3) · **AUTHORIZED (A-4 only)** (2) · **DEFINED — satisfied** (3 ← now including this one) · **DEFINED** (1, `CUSTOMER_IDENTITY` not PRESENT) · **EXISTING-INCOMPLETE** (2)

**A-4 remains incomplete**; this commit does not claim otherwise.

## Session commit chain

```
728df639 [A-2] → a5fb0fbb [A-1] → ef1a4af4 [A-3] → 94156d39 [A-4 scope]
eaaa9d6a [A-4 repair] → c5685867 [A-4 boundaries] → 9b7f828a [A-4 exclusions]  ← HEAD
```

---

## Remaining A-4 gates

| # | Gate | Type | Blocks |
|---|---|---|---|
| **1** | **Runtime prerequisite** — shared accounts disabled | Separate authorization (config + secret material) | `CUSTOMER_IDENTITY`, `SHARED_SERVICE_MAP`, all provisioning |
| **2** | Customer account + entitlement provisioning | Authorization; depends on #1 | `CUSTOMER_IDENTITY`, `ENTITLEMENT_SLOT` → PRESENT |
| **3** | `D-11` signing authority | **OPEN** | External release only |
| **4** | `D-12` mechanical ownership guard | **OPEN**, unimplemented | Nothing today — but now explicitly relevant to classes 10–12 |
| — | `AUTH_SLOT` | **No gate** — D-3(b) is the intended end state | Nothing |

**All documentation gates are now closed.** Every remaining gate needs either a runtime change or an open decision — there is no further documentation-only step available.

## Gates preserved

```
shared accounts enabled  NO (False)      customer provisioned    NO
entitlement outside tests NO             D-11                    OPEN
D-12                     unimplemented   external release        NOT authorized
exporter code/policy     unchanged       export manifest         unchanged
runtime/configuration    unchanged       services restarted      NO (0)
archive produced         NO (0)          policy document         NOT swept in
routes/schemas/services  unchanged       signing/custody infra   unchanged
pushed                   NO
```

**NEXT AUTHORIZATION: NONE**
