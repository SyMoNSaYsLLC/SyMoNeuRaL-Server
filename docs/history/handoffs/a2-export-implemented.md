# A-2 Export Tool — IMPLEMENTED AND VERIFIED

> **REDACTED COPY.** Protected artifact names, credential filenames, customer identifiers, and infrastructure details are masked as `*****`. Unredacted detail stays on the box.

## Continues from

`a2-export-blocked-on-manifest.md` (2026-09-01 17:45). That handoff was blocked pending a manifest policy decision. You authorized the fixture-only manifest. This covers 17:45 → 17:55.

## Control point

| | Before | After |
|---|---|---|
| HEAD | `1df394f0` | `1df394f0` (no commits) |
| tracked modifications | 0 | **0** |
| untracked | `Sept1.md` | `Sept1.md` + 2 new A-2 files |
| Sept1.md sha256 | `d36d7258e43e…` | `d36d7258e43e…` **unmodified** |
| API | active, HTTP 200 | active, 0 restarts, HTTP 200 |

---

## What was built — 2 files, both new

**`tools/data/export_snapshot.sh`** — the exporter. Named by policy rule 4 as the only sanctioned way a snapshot leaves the box. Did not exist before.

**`backend/apps/test_export_snapshot.py`** — 7 tests. Repo convention is `unittest` (48 of 49 suites).

Nothing else was created or modified.

---

## The architecture

Two independent stages, both must pass:

```
stage 1  CONSTRUCT   start from the empty set; add only manifest-named paths
stage 2  ENFORCE     re-scan the constructed set for protected classes; abort on any
```

Stage 2 is not redundant — it catches an over-broad manifest entry, e.g. a directory that later gains a protected file. Stage 1 trusts the manifest; stage 2 trusts nothing.

**Refusal emits no archive.** Files are assembled in a staging directory and the archive is only sealed after stage 2 passes. A tool that detects a violation *after* writing the archive has already produced the artifact that must not exist.

---

## Policy behaviour proved

| Case | Result |
|---|---|
| Explicitly allowed path | **EXPORTED** |
| Unclassified path | **EXCLUDED** |
| Prohibited path | **REFUSED** (exit 3, no archive) |
| Unknown classification | **FAIL CLOSED** |
| No manifest supplied | **REFUSED** — no implicit whole-repo export exists |
| Path traversal in manifest | **REFUSED** |
| Manifest names a missing path | **REFUSED** — never silently ships less than authorized |

---

## Verification — tests proven real by sabotage

7/7 passed. But passing tests prove nothing unless they can fail, so I broke the exporter deliberately and checked the *right* tests caught it:

| Sabotage | Result |
|---|---|
| Neutralize stage 2 refusal | **2 tests failed** — exactly the refusal tests |
| Make stage 1 sweep everything (deny-list behaviour) | **1 test failed** — the unclassified-path test, with *"unclassified path leaked — this is deny-list behaviour"* |
| Restore | **7/7 pass**, 0 sabotage markers remaining |

That middle row is the important one. Allow-list and deny-list agree on the easy cases and give **opposite** answers for an unclassified path. That test is what actually distinguishes the implemented architecture from the one the contract forbids — and it caught the forbidden one immediately.

The unclassified test also proves absence is caused by the allow-list, not an ignore rule: naming the same file in the manifest ships it.

**Manual end-to-end** against a synthetic tree confirmed only the named file shipped, with a manifest carrying source SHA and a per-file SHA256. The legacy acceptance check from the policy doc reports **safe export**.

**Against the real repository** (dry-run, read-only) a manifest naming a runtime-state directory was refused, naming the class and path but never contents.

---

## Everything synthetic

No test touches a real protected artifact. Fixtures are built in fresh temp dirs and contain files this repo has never had — the marker string is `SYNTHETIC-FIXTURE-NOT-REAL-DATA`. Planting a sentinel into a real protected path to see whether the exporter notices would be the same mistake the exporter exists to prevent.

Cleanup verified: **0** fixture directories remain, backup removed.

---

## Production boundary — deliberately not crossed

The manifest format is newline-delimited repo-relative paths, `#` comments ignored. This is the **minimum interface needed to consume an explicit allow-list**, documented in the script as explicitly *not* a production schema.

**Not decided, per your restriction:** which application files belong in a customer export · which customer files ship · final manifest storage location · final syntax · ownership/lifecycle · entitlement-driven generation · per-customer semantics. All remain **A-4**.

**PRODUCTION MANIFEST STATUS: NOT DEFINED**

---

## Still open from earlier

- **D-1 … D-11** all undecided
- **A-3** blocked — unresolved decision *plus* a wrong-generator defect in the assignment
- **A-8** blocked — installed units are contaminated rewrites from the earlier outage
- Three A-item check lines are **already green** and prove nothing
- **No A-item covers packaging, signing, or custody** — three delivery-blocking decisions uncovered
- Two policy documents still describe different export architectures (doc edit, unauthorized)

---

## Scope audit

```
AUTHORIZED SCOPE TOUCHED:
  tools/data/export_snapshot.sh              (new)
  backend/apps/test_export_snapshot.py  (new)

UNAUTHORIZED SCOPE TOUCHED: NONE
```

Nothing staged, nothing committed. No service restart, no reboot, no build-tree write, no customer-application change, no signing, no custody mutation, no model operations.

## To resume

Both files are **untracked** — nothing was committed, per your restriction. Options: commit A-2, authorize **A-1** (additive, no blockers), or resolve a D-series decision to unblock A-3/A-4.

**NEXT AUTHORIZATION: NONE**
