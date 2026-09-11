# A-4 EXPORT_SCOPE Committed — Clean Checkpoint

> **REDACTED COPY.** Protected artifact names, credential filenames, customer identifiers, and infrastructure details are masked as `*****`. Unredacted detail stays on the box.

## Continues from

`a4-export-scope-populated.md`. You ruled on the shared dependency and authorized the commit. This covers the ruling record + commit.

## 1. Commit

```
94156d39937893a7c4c0ce0599be814b29b1734c
Add customer export scope for the reference application

  1 file changed, 51 insertions(+)
```

## 2. Committed file list — exactly 1

```
<app>/EXPORT-SCOPE.manifest
```

Nothing else. Staged with one explicit path; verified before commit that the policy document, planning document, shared platform source, tests, and exporter were all absent from the index.

## 3. Post-commit `git status --short`

```
 M docs/ops/EXPORTS.md      ← pre-existing, prior authorization, untouched
?? (planning document)      ← pre-existing, remains untracked
```

## 4. Required confirmations

| Confirmation | Result |
|---|---|
| Pre-existing policy-document modification untouched | ✅ still modified, **0** occurrences in this commit |
| Planning document remains uncommitted | ✅ untracked; **0** appearances in any commit, ever |
| No customer archive produced | ✅ **0** archives — dry-run verification only |
| No external release occurred | ✅ **0** remotes configured; release is not mechanically possible |
| **D-11 remains OPEN** | ✅ recorded in the register |
| Shared accounts remain disabled | ✅ `enabled()` = **False**, 0 config changes |
| Exporter unmodified | ✅ **0** changes — stage-2 rejection left intact |
| Services not restarted | ✅ **0** restarts |
| Post-commit tests | ✅ **42 passed** |

## 5. Rulings recorded

**Shared platform dependency — excluded, consequence recorded.** The manifest header now states that the shared accounts module stays category 2, that the authorized export **references shared platform functionality it does not contain**, and therefore that the export is **not a self-contained or buildable distribution and is not meant to be**. It states explicitly that the consequence must not be resolved by copying, vendoring, duplicating, exposing or exporting shared platform source.

**Enforcement gap — recorded, no guard built.** The manifest also records the verified finding: adding a shared platform module to a manifest **passes the protected-class stage unflagged**, because such source is neither secret nor training material nor runtime state. Protection rests on manifest discipline and review, not on the tool.

**New decision item created — D-12.** *Should manifest ownership boundaries receive mechanical enforcement?* Three options with tradeoffs; recommendation is to build a guard only once application-vs-platform ownership is expressed somewhere machine-readable, because a guard built on a guessed ownership model would reject correct manifests and train people to bypass it. Safe default: documented review. **Blocks nothing today** — A-4 shipped without it by your explicit ruling.

## 6. A-4 completion status — measured

| Indicator | State |
|---|---|
| `APPLICATION_IDENTITY` · `BACKEND_SLOT` · `WORKFLOW_SLOT` | PRESENT |
| `APPLICATION_SLUG` · `CUSTOMER_ROUTE` · `LIVE_STACK_ENTRY` | WIRED |
| `FRONTEND_SLOT` · `API_SLOT` | **VERIFIED** |
| **`EXPORT_SCOPE`** | **POPULATED, VERIFIED** ← this commit |
| `RELEASE_IDENTITY` · `CUSTODY_RECORD` | AUTHORIZED (A-4 only) |
| `CUSTOMER_IDENTITY` · `CONFIG_SLOT` · `ASSET_SLOT` · `PROTECTED_EXCLUSIONS` | DEFINED only |
| `AUTH_SLOT` · `SHARED_SERVICE_MAP` | EXISTING-INCOMPLETE |
| `ENTITLEMENT_SLOT` · `TEST_PATH` | MISSING **(stale — see below)** |

**Two rows are out of date and I did not edit them**, because doing so exceeds this authorization: A-3 delivered the entitlement seam and the application's first test file, so `ENTITLEMENT_SLOT` and `TEST_PATH` are no longer MISSING in fact. Correcting them is a documentation change worth a separate authorization rather than something to slip into a commit gate.

**A-4 is not complete**, and completion was never claimed here. `EXPORT_SCOPE` moved from MISSING to POPULATED/VERIFIED; the remaining indicators are unchanged by this commit.

> **A-4 completion is not external-release readiness.** Custody is unsigned, D-11 is open, and no distribution is authorized.

## 7. Session commit chain

```
1df394f0  (baseline)
728df639  fail-closed snapshot exporter          [A-2]
a5fb0fbb  control/models operator surface        [A-1]
ef1a4af4  customer entitlement + authz seam      [A-3]
94156d39  customer export scope                  [A-4 partial]  ← HEAD
```

Four isolated checkpoints, each verified before commit, none pushed.

## Scope audit

```
COMMITTED PATHS: 1
UNAUTHORIZED PATHS COMMITTED: NONE
Policy document committed:  NO
Planning document committed: NO
Shared platform source committed: NO
Tests committed: NO
Exporter changed: NO
Archive produced: NO
External release: NO
Shared accounts enabled: NO
Mechanical guard implemented: NO (excluded by ruling; tracked as D-12)
PUSHED: NO
```

## Next decision / authorization gate

Three candidates, in the order I would take them:

1. **Correct the two stale slot rows** — smallest, documentation only, removes a factual error from the record.
2. **Remaining A-4 indicators** — `CUSTOMER_IDENTITY` still DEFINED-not-PRESENT (no customer account exists in the shared authority), `AUTH_SLOT` and `SHARED_SERVICE_MAP` still EXISTING-INCOMPLETE.
3. **The runtime prerequisite** — shared accounts is disabled, so every entitlement route returns 403 and no customer can reach the application regardless of the slot state.

**NEXT AUTHORIZATION: NONE** — stopping at the clean checkpoint as instructed.
