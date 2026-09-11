# A-3 Committed — Clean Checkpoint

> **REDACTED COPY.** Protected artifact names, credential filenames, customer identifiers, and infrastructure details are masked as `*****`. Unredacted detail stays on the box.

## Continues from

`a3-implemented-awaiting-gate.md` (2026-09-01 20:45). That handoff ended with 8 verified but uncommitted files. This covers 20:45 → 20:55: the isolated commit.

## Control point

| | Before | After |
|---|---|---|
| HEAD | `a5fb0fbb` | **`ef1a4af4`** |
| tracked modifications | 6 | **1** (pre-existing policy doc) |
| staged | 0 | **0** |
| A-3 tests | 35 passing | **35 passing** |
| Regression | 98 passing | **98 passing** |
| Shared accounts | disabled | **disabled** |
| Service restarts | 0 | **0** |

---

## 1. The commit

```
ef1a4af4bdf4ae0f540b1e0a7edbd7f7baa5038c
Add customer entitlement with an explicit authorization seam

  8 files changed, 939 insertions(+), 17 deletions(-)
```

The message records *why* rather than *what*: why a dependency seam instead of prefix middleware (a prefix rule cannot express that logout must survive a dead session without leaving a hole an entitlement route could fall through), why operator and customer entitlement are separate axes, and why an unreachable store must deny.

## 2. Files included — exactly 8

| # | File | Role |
|---|---|---|
| 1 | shared accounts store | entitlement table + functions |
| 2 | shared accounts tests | entitlement suite |
| 3 | authorization seam *(new)* | the class dependency |
| 4 | application routes | 15 class attachments only |
| 5 | application store | column, migration, link/unlink |
| 6 | route authorization tests *(new)* | 22-test suite |
| 7 | Live Stack generator | entitlement filtering hook |
| 8 | operator CLI | 5 new operations |

## 3. Pre-commit verification

| Check | Result |
|---|---|
| Dirty paths classified | 8 A-3 · 2 pre-existing · **0 unrelated** |
| Sabotage markers | **0** across all 8 |
| Debug / TODO / temp-path residue | **0** |
| Private keys or literal passwords added | **0** |
| Test-only secret labelled as such | ✓ |
| Staged set | exactly **8**, both pre-existing paths excluded |

Staged with 8 explicit paths — no `git add .`, no `-A`, no `commit -a`.

## 4. Final test results

**A-3: 35 passed.** Re-run after the commit, against the committed content.
**Regression: 98 passed.** Shared accounts, application, A-1, A-2 suites.

## 5. Shared accounts remains disabled

```
enabled()                 False
enable flag in env        unset
session secret in env     unset
config files modified     0
```

The subsystem reports itself off. Nothing was written to configuration and no secret was created.

## 6. Services were not restarted

```
NRestarts   0
start time  16:28:06   (unchanged since the earlier reboot)
API         active, HTTP 200
```

The start timestamp is the proof: it still reads 16:28, so the process was never replaced.

## 7. Remaining work — separated

```
$ git status --short
 M ops/docs/EXPORTS.md      ← PRE-EXISTING, prior authorization, deliberately not committed
?? (planning document)      ← PRE-EXISTING, untracked
```

Both predate this authorization and were **kept out of the index**. Nothing else is dirty.

---

## Session commit chain

```
1df394f0  (baseline)
728df639  fail-closed snapshot exporter          [A-2]
a5fb0fbb  control/models operator surface        [A-1]
ef1a4af4  customer entitlement + authz seam      [A-3]  ← HEAD
```

Three isolated checkpoints, each verified before commit, none pushed (0 remotes).

---

## Still open from earlier

- **D-1, D-2, D-4, D-6 … D-11** undecided
- **A-4** blocked on four decisions plus A-3 · **A-8** blocked on contaminated units
- Packaging/signing/custody: decisions exist, **zero implementation coverage**
- Production manifest **NOT DEFINED**
- **Runtime prerequisite:** enabling shared accounts is a separate authorization. Until then every entitlement route returns 403 — correct fail-closed behaviour, but the customer surface stays closed

## Scope audit

```
COMMITTED PATHS: 8
UNAUTHORIZED PATHS COMMITTED: NONE
Pre-existing dirty files committed: NONE
Shared accounts enabled: NO
Services restarted: NO
A-4 begun: NO
Packaging / signing / custody / manifest: NOT TOUCHED
PUSHED: NO
```

**NEXT AUTHORIZATION: NONE**
