# A-1 Committed — Clean Checkpoint

> **REDACTED COPY.** Protected artifact names, credential filenames, customer identifiers, and infrastructure details are masked as `*****`. Unredacted detail stays on the box.

## Continues from

`a1-control-models-implemented.md` (2026-09-01 18:25). That handoff ended with 19 verified but **untracked** files. This covers 18:25 → 18:35: the isolated commit.

## Control point

| | Before | After |
|---|---|---|
| HEAD | `728df639` | **`a5fb0fbb`** |
| tracked modifications | 0 | **0** |
| staged | 0 | **0** |
| untracked | planning file + 19 A-1 files | **planning file only** |
| learned-model payloads | 0 | **0** — unchanged |
| API | active, HTTP 200, 0 restarts | active, HTTP 200, 0 restarts |

---

## The commit

```
a5fb0fbbf7616ce8e51b0fe144fd97ca9fd4e8ad
Add control/models operator surface

  19 files changed, 581 insertions(+)
```

**One commit. 19 files. No deletions, no modifications to existing files.**

---

## Boundary proof before staging

The risk in a 19-file checkpoint is sweeping in something unintended. Proven, not assumed:

| Check | Result |
|---|---|
| Enumerated untracked set, excluding the planning file | **19** |
| Every path within the two authorized locations | ✓ all 19 |
| Files on disk in the control dir vs. in the set | 18 = 18 |
| Stray artifacts (zips, backups, caches, fixtures) | **0** |
| Staged set vs. enumerated set | **exact match** — `diff` clean |
| Planning file staged | **NO** |
| Unrelated dirty files | **0** |

Staged with two explicit paths. Did **not** use `git add .`, `git add -A`, or `git commit -a`.

---

## Verification re-run on the committed content

| Check | Result |
|---|---|
| Shell syntax, all 17 scripts | ✓ pass |
| Test suite | **21 passed** |
| Sabotage residue | 0 |
| Hardcoded temp paths | 0 |
| Real secrets / private keys | 0 |
| Absolute home paths | 0 |

---

## Model-state invariants — all six hold

| Invariant | Measured |
|---|---|
| Learned-model payloads = 0 | measured **0**, reported **0** — they agree |
| Six states distinct in the vocabulary | payload · metadata · provenance · configuration · absent · unknown |
| ABSENT does not collapse into UNKNOWN | readable dir → `0` · missing dir → `UNKNOWN` |
| No acquisition launcher | **ABSENT** ✓ |
| No conversion launcher | **ABSENT** ✓ |
| No quantization launcher | **ABSENT** ✓ |

The third row is the one worth keeping: `0` means *I looked and there is nothing*; `UNKNOWN` means *I could not look*. A tool that answers `0` for both would report an uninspected box as a verified-empty one.

---

## No forbidden side effects

Service restarts **0** · API **active / HTTP 200** · network calls in launcher code **0** · payloads acquired **0** · converted **0** · quantized **0** · build tree **0 files** · customer application **0 files** · A-2 files **unmodified** · planning file **unchanged** · commits made **1** · pushed **NO** (0 remotes) · tagged **NO** · amended **NO**.

---

## Session commit chain

```
1df394f0  (baseline)
728df639  fail-closed snapshot exporter        [A-2]
a5fb0fbb  control/models operator surface      [A-1]   ← HEAD
```

Two isolated checkpoints, each verified before commit, neither pushed.

---

## Still open from earlier

- **D-1 … D-11** all undecided
- **A-3** blocked — unresolved decision *plus* a wrong-generator defect in the assignment
- **A-8** blocked — installed units are contaminated rewrites from the earlier outage
- Three A-item check lines are **already green** and prove nothing
- **No A-item covers packaging, signing, or custody** — three delivery-blocking decisions uncovered
- Two policy documents still describe different export architectures
- Production manifest remains **NOT DEFINED**

---

## Scope audit

```
COMMITTED PATHS: 19
  control/models/                      (18 files)
  backend/apps/test_control_models.py  (1 file)

UNAUTHORIZED PATHS COMMITTED: NONE
Planning file COMMITTED:      NO
PUSHED:                       NO
SECOND COMMIT MADE:           NO
```

## To resume

A-1 and A-2 are both clean checkpoints. The remaining A-items are all blocked on decisions or on prior work — the shortest paths forward are resolving a D-series decision to unblock A-3/A-4, or addressing the uncovered packaging/signing/custody gap.

**NEXT AUTHORIZATION: NONE**
