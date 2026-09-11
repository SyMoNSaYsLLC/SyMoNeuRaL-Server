# A-1 control/models — IMPLEMENTED AND VERIFIED

> **REDACTED COPY.** Protected artifact names, credential filenames, customer identifiers, and infrastructure details are masked as `*****`. Unredacted detail stays on the box.

## Continues from

`a2-committed-clean-checkpoint.md` (2026-09-01 18:05). This covers 18:05 → 18:25.

## Control point

| | Before | After |
|---|---|---|
| HEAD | `728df639` | `728df639` — **no commits** |
| tracked modifications | 0 | **0** |
| staged | 0 | **0** |
| untracked | planning file | planning file + **19 A-1 files** |
| learned model payloads | 0 | **0** — unchanged |
| API | active, HTTP 200 | active, 0 restarts, HTTP 200 |

---

## What was built — 19 files, all new, all additive

`control/models/` — 16 launchers + a shared preamble + README, plus one test suite. Nothing existing was modified.

**Read-only (10):** list · active · loaded · provenance · license · checksums · compat · adapters · rebrand · gpu
**Write-mode (6):** stage · verify · activate · rollback · release · finetune — all refuse without explicit intent

---

## Deliberately absent

**No acquisition launcher.** Its semantics depend on an unresolved decision, and the instruction preferred omission over a non-operational stub. A launcher that looked real but refused would be worse than none. Acquisition stays with the existing fetch tooling, separately authorized.

**No conversion or quantization.** No CLI authority exists to wrap; excluded by decision. A test asserts these files do not exist, so a future contributor cannot quietly add them.

---

## The property that actually matters

The box has **zero learned-model payloads**. The provenance record file holds **11 entries**. A tool that counts records and calls them models reports eleven installed models on a machine with none — and this repo has already published a model figure that was never true of the machine it described.

So every launcher prints, in one fixed wording:

```
LEARNED MODEL PAYLOADS: 0
  no model installed -- this is a valid state, not an error
```

Six distinct states are kept apart: **payload** (bytes that can serve a request) · **metadata** (scaffolding) · **provenance** (a historical origin record) · **configuration** (which model a surface *selects*) · **absent** (measured, nothing here) · **unknown** (could not look).

`ABSENT` and `UNKNOWN` never collapse into each other. "I looked and there is nothing" and "I could not look" are different answers, and a caller acts differently on each.

---

## Verification — 21 tests, proven real by sabotage

Passing tests prove nothing unless they can fail. I broke the implementation twice and checked the *right* test caught each:

| Sabotage | Result |
|---|---|
| Collapse `UNKNOWN` into `0` | **caught** — the unknown-state test |
| Report the 11 records as 11 payloads | **caught** — the record-vs-payload test |
| Restore | **21/21 pass**, 0 sabotage markers |

**Three real defects were found and fixed during verification**, all by the tests rather than by inspection:

1. Eight launchers referenced their authority only through a shell *variable*, so a reader could not tell what they wrapped. Now each names it literally.
2. `payload_count` returned empty instead of `UNKNOWN` when the model directory was unreadable.
3. **The fine-tune launcher crashed** with "unbound variable" instead of refusing cleanly — and the test passed anyway because *any* non-zero exit satisfied it. Found by reading the output, not the exit code. Fixed, and the test now asserts the refusal is deliberate rather than a crash.

That third one is the sharpest lesson: a non-zero exit is not proof of a safety guarantee.

---

## Every launcher exercised

All 16 run against the live box. 10 read launchers exit 0; write launchers refuse (1/1/2). **Zero crash indicators** across all of them.

---

## Restrictions honoured

```
MODEL PAYLOADS ACQUIRED:  0
MODEL PAYLOADS CONVERTED: 0
MODEL PAYLOADS QUANTIZED: 0
```

No network calls in any launcher · acquisition launcher absent · no convert/quantize files · A-2 unmodified · planning file unchanged · build tree 0 files changed · customer application 0 files changed · services untouched, HTTP 200.

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
AUTHORIZED SCOPE TOUCHED:
  control/models/                      (new, 18 files)
  backend/apps/test_control_models.py  (new)

UNAUTHORIZED SCOPE TOUCHED: NONE
```

Nothing staged, nothing committed.

## To resume

19 files are **untracked** — committing was not authorized. Options: commit A-1 as an isolated checkpoint, resolve a D-series decision, or address the uncovered packaging/signing/custody gap.

**NEXT AUTHORIZATION: NONE**
