# A-4 COMPLETE — SHARED_SERVICE_MAP reconciliation and slot-record cleanup

> **REDACTED.** Customer names, credential filenames, security/lockdown tooling names,
> internal ports and infrastructure-posture details are masked with `*****`. Meaning is
> preserved — only identifiers are blurred. Unredacted detail lives on the box in
> `Sept1.md` at HEAD `2def42b9`.

**Date:** 2026-09-02
**Window covered:** from HEAD `698bef87` (AUTH_SLOT resolution) to HEAD `2def42b9`
**Repo:** `/home/google/Symoneural`

## Continues from

Previous handoff: the AUTH_SLOT resolution pass (2026-09-02), which ended at HEAD `698bef87`
with `SHARED_SERVICE_MAP` as the single remaining `EXISTING-INCOMPLETE` A-4 indicator.

| Control point | At `698bef87` | Now at `2def42b9` |
|---|---|---|
| HEAD | `698bef87` | `2def42b9` |
| A-4 indicators at/above §10 requirement | 18 of 19 | **19 of 19** |
| `SHARED_SERVICE_MAP` | `EXISTING-INCOMPLETE` | **`DEFINED — satisfied`** |
| Tracked mods | `ops/docs/EXPORTS.md` only | `ops/docs/EXPORTS.md` only (untouched) |
| shared API service | active | active — **0 restarts** |
| Archives produced | 0 | 0 |
| Model payloads | 0 | 0 |

## What was attempted and why

Close out A-4 by correcting the last indicator. The read-only ruling from the prior turn had
established that `SHARED_SERVICE_MAP` was mis-scored: §10 of the Customer Application Slotting
Architecture requires this indicator at `Defined`, where the record's own vocabulary defines
`DEFINED` as *"named in the architecture or a document. No implementation claim."*

The `EXISTING-INCOMPLETE` state was **self-inflicted**. I had authored a four-level
runtime-consumption scorecard inside the record, then judged the indicator against its
strictest column. No specification language anywhere requires a mapped service to be active,
enabled, running, wired, or runtime-verified. Documentation-only authorization; no runtime
implementation permitted.

## What was completed

Two commits, both `Sept1.md` alone.

### `20bce542` — SHARED_SERVICE_MAP recast as a dependency map

§11.1 was rewritten from a consumption scorecard into **the application's dependency map**:

**Required shared dependencies (5)**
- shared API
- accounts/auth identity + entitlement bridge
- shared web
- shared gateway
- shared project/application services

**Conditional dependency (1)**
- shared inference / Symon runtime — *when required*. Its offline state and zero model
  payloads do not make the map undefined.

**Platform services explicitly OUTSIDE this application's map (2)**
- credits / metering
- release / custody

These are real platform services. The application does not consume them under the current
architecture, therefore they are outside its `SHARED_SERVICE_MAP`. Their existence is **not**
deleted from the broader platform record — the record distinguishes *platform service exists* /
*application does not consume it* / *therefore outside this map*.

**Runtime status recorded separately**, and explicitly not used to decide whether the map is
defined:

| Service | Measured state |
|---|---|
| shared API | active — runtime verified |
| accounts/auth bridge | enabled, consumed, verified |
| shared web | defined but disabled |
| shared gateway | defined but disabled |
| inference | defined but offline; conditional |
| shared project services | defined / ready per measured evidence |
| credits / metering | platform service, absent / not implemented, **not** an application dependency |
| release / custody | platform delivery service, blocked on D-11, **not** an application runtime dependency |

Disabled, offline, absent and blocked are **never** characterized as undefined.

New §11.7 records the completion determination: **19 of 19 at or above requirement, 0 below.
A-4 IS COMPLETE.** No runtime enablement was required for or performed by A-4.

### `2def42b9` — reconcile stale pre-A-series claims

The first commit set the indicator correctly but left the document **self-contradictory**.
Nine statements written before the A-series still asserted the pre-work state as current —
three of them contradicting the 19-of-19 determination roughly thirty lines below.

| § | Was | Now |
|---|---|---|
| 11.2 | pre-A-series snapshot: `EXISTING-INCOMPLETE (3)`, `MISSING (5)` | regenerated **mechanically from the 19 indicator rows**: EXISTING-INCOMPLETE **0**, MISSING **0** |
| 12.1 | "`tools/data/export_snapshot.sh` DOES NOT EXIST" under a **Hard state** heading | superseded — it exists, A-2 `728df639` |
| 3 | entitlement gap open; exporter absent | both marked delivered with hashes |
| 4.4 / 9.1 | DispatchOS separate login = `EXISTING-INCOMPLETE` | `CURRENT — intended under D-3(b)`; separation is the settled design |
| 4.5 | exporter row "DOES NOT EXIST" | `CURRENT`, `728df639` |
| 9.2 | "There is no customer→application entitlement layer" | **CLOSED** by A-3 `ef1a4af4`; the licence-vs-access distinction it drew remains valid |
| 18 | A-1/A-2/A-3 open; A-4's five indicators "Missing" | DELIVERED with hashes; A-4 COMPLETE; five satisfied, with the D-11 = (d) A-4-only scope limit restated |

Assignment registers keep their original *"as raised"* reasoning — that is the audit trail for
why each was opened — annotated with delivery rather than rewritten.

**Also corrected an overclaim I introduced in `20bce542`.** §11.7 had said A-4 completion means
required capabilities are "wired and verified." Measured reality is **6 of 19 runtime-verified**.
Tightened to the claim actually established: every indicator is at or above the state §10
requires of it. Four are satisfied at `DEFINED` because `Defined` is what §10 asks for.

## Final 19-indicator determination

| Bucket | Count | Indicators |
|---|---|---|
| VERIFIED | 5 | `CUSTOMER_IDENTITY`, `FRONTEND_SLOT`, `API_SLOT`, `AUTH_SLOT`, `ENTITLEMENT_SLOT` |
| POPULATED, VERIFIED | 1 | `EXPORT_SCOPE` |
| WIRED | 3 | `APPLICATION_SLUG`, `CUSTOMER_ROUTE`, `LIVE_STACK_ENTRY` |
| PRESENT | 3 | `APPLICATION_IDENTITY`, `BACKEND_SLOT`, `WORKFLOW_SLOT` |
| PRESENT — PASSING | 1 | `TEST_PATH` |
| DEFINED — satisfied | 4 | `CONFIG_SLOT`, `ASSET_SLOT`, `SHARED_SERVICE_MAP`, `PROTECTED_EXCLUSIONS` |
| AUTHORIZED (A-4 only) | 2 | `RELEASE_IDENTITY`, `CUSTODY_RECORD` |
| **EXISTING-INCOMPLETE** | **0** | — |
| **MISSING** | **0** | — |

**A-4 IS COMPLETE — 19 of 19 indicators at or above required state.**

Two qualifiers that must travel with that sentence:
- `DEFINED — satisfied` is not a shortfall. Those four are boundaries or maps — definitions,
  not on-disk artifacts. §10 requires `Defined`; a stronger state would be a claim the
  evidence does not carry.
- `AUTHORIZED (A-4 only)` is a **scope limit**, not a completion. D-11 = (d) applies *for A-4
  only*. Identity is asserted, **not signed**.

## Errors made this window

1. **Committed before reporting.** The authorization listed 13 items to report *before*
   committing; I committed `20bce542` first and delivered the report after. No scope violation
   resulted — staged scope was verified as `Sept1.md` alone beforehand — but the ordering was
   wrong.
2. **Left the document self-contradictory.** Fixing one indicator while nine older statements
   still asserted the pre-work state produced a record that argued with itself. Caught by
   reading the committed file rather than trusting the edit.
3. **Overclaimed in §11.7** — "wired and verified" against a measured 6-of-19. Same class as
   the original SHARED_SERVICE_MAP error: asserting a stronger state than evidence supports.
4. When regenerating §11.2 I initially reached for recall. Re-derived the buckets
   **mechanically** from the table rows instead — re-scoring 19 indicators from memory is
   precisely how the original mis-scoring happened.

## Still open from earlier

- **D-11 — signing authority and key custody: OPEN.** No key generation, key storage, signing
  infrastructure, artifact signing, or external distribution is authorized.
- **External release: NOT authorized.** Custody is unsigned. A-4 complete is a *different
  claim* and must never be represented as release readiness.
- **D-12 — mechanical ownership guard: unimplemented**, explicitly outside A-4.
- **Shared web / shared gateway / inference / credits implementation: separately gated.** Each
  is a prerequisite for *other* work; none is required by any A-4 indicator.
- **`ops/docs/EXPORTS.md` remains modified-and-unstaged** from an earlier authorization. It must
  never be swept into a commit. Verified unstaged at both commits this window.
- `LIVE_STACK_ENTRY` is not entitlement-aware — the catalogue advertises the surface to
  unentitled viewers.
- `WORKFLOW_SLOT` is `PRESENT` on route coverage; no workflow was individually exercised
  end-to-end.
- Zero learned model payloads on this box. That remains the correct, valid baseline; model
  acquisition requires explicit authorization.

## Verification — measured, not documented

```
backend/ tools/ control/ site/ ops/ run/     0 changes each
docs/                                        1 change (pre-existing EXPORTS.md, unstaged)
shared API service                           active, 0 restarts
archives produced                            0
model payloads                               0
shared accounts / grants                     1 / 1  (unchanged)
export manifest entries                      7      (unchanged)
credits/metering store                       absent (unchanged)
shared web / shared gateway                  inactive (unchanged)
indicator rows extracted for 11.2            19
staged files per commit                      1 (Sept1.md)
ops/docs/EXPORTS.md staged                   no
```

## To resume — exact checkpoint

```
repo   /home/google/Symoneural
HEAD   2def42b9   [A-4] reconcile stale pre-A-series claims with the completion ruling
prev   20bce542   [A-4] SHARED_SERVICE_MAP recast as dependency map; A-4 complete
git status --short:
 M ops/docs/EXPORTS.md
```

Session commit chain: `1df394f0` baseline → `728df639` [A-2 exporter] → `a5fb0fbb` [A-1
control/models] → `ef1a4af4` [A-3 entitlement seam] → `94156d39` [A-4 export scope] →
`eaaa9d6a` [A-4 test repair] → `c5685867` [A-4 boundaries] → `9b7f828a` [A-4 exclusions] →
`cb425290` [post-provisioning reconcile] → `698bef87` [AUTH_SLOT] → `20bce542` → `2def42b9`.

**Stopped here per authorization: "Stop after the A-4 completion checkpoint."** No push.

Next gates, none of them authorized yet: D-11 (signing/custody, blocks external release),
D-12 (mechanical ownership guard), and shared web / gateway / inference / credits enablement.
