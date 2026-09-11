# `backend/vendor` classification — measured 2026-09-09

Required by the storage reorganisation spec, section 1.8: *"It is large (~16k tree entries).
Do not move/delete until actual imports/runtime dependency are measured. Classify every
major vendor subtree."*

## The headline: it is 131M, and nothing imports it

The spec expected an ambiguous multi-gigabyte tree. Measured, `backend/vendor` is **131M**
in two subtrees holding ten public SDK source repositories. The import measurement is the
part that decides its fate, and it is unambiguous:

* **No `__init__.py` exists** at `backend/vendor/`, `backend/vendor/openai/` or
  `backend/vendor/anthropics/`. The tree is not a Python package, so `import` cannot reach
  it regardless of `sys.path`.
* **Nothing manipulates `sys.path` or `PYTHONPATH` to add it** — grepped across
  `backend/*.py` and `backend/apps/*.py`.
* The only `grep -rn vendor` hit in first-party Python is
  `backend/apps/cryptominer/__init__.py:22`, and it is prose about not projecting figures
  "from vendor figures" — a false positive, not an import.
* `scripts/build-deb.sh` already excludes it from the shipped package via
  `NONPROD_RE='^(backend/vendor/|...)'`, annotated *"adopted SDK/reference source; no
  serving module imports it"*.

Four independent measurements, one conclusion.

## Classification — every subtree, no `UNKNOWN`

Section 1.8's vocabulary is `RUNTIME_REQUIRED_LOCAL`, `BUILD_ONLY_REACQUIRABLE`,
`REFERENCE_ONLY`, `UNKNOWN`.

| Subtree | Version pin | Size | Files | Licence | Class |
|---|---|---|---|---|---|
| `anthropics/anthropic-sdk-java` | 2.57.0 | 39M | 2927 | permissive | `REFERENCE_ONLY` |
| `anthropics/anthropic-sdk-csharp` | 12.42.0 | 27M | 2734 | permissive | `REFERENCE_ONLY` |
| `anthropics/anthropic-sdk-ruby` | 1.65.0 | 21M | 3827 | permissive | `REFERENCE_ONLY` |
| `anthropics/anthropic-sdk-php` | 0.43.0 | 15M | 2231 | permissive | `REFERENCE_ONLY` |
| `anthropics/anthropic-sdk-python` | 1.0.0 | 12M | 1495 | permissive | `REFERENCE_ONLY` |
| `anthropics/anthropic-sdk-go` | 1.66.0 | 6.5M | 332 | permissive | `REFERENCE_ONLY` |
| `openai/apps-sdk-ui` | 0.2.2 | 5.8M | 1059 | permissive | `REFERENCE_ONLY` |
| `anthropics/anthropic-sdk-typescript` | 0.120.0 | 5.6M | 468 | permissive | `REFERENCE_ONLY` |
| `anthropics/claude-agent-sdk-python` | 0.2.143 | 2.2M | 144 | MIT | `REFERENCE_ONLY` |
| `anthropics/agent-sdk-workshop` | **UNPINNED** | 536K | 73 | Apache-2.0 | `REFERENCE_ONLY` |

```
RUNTIME_REQUIRED_LOCAL   = 0 bytes
BUILD_ONLY_REACQUIRABLE  = 0 bytes
REFERENCE_ONLY           = 131M  (all ten subtrees)
UNKNOWN                  = 0 bytes
```

`UNKNOWN=0`, which section 7.10 requires.

## What this does NOT license

These are the **public, permissively licensed SDK repositories** published on GitHub. They
are not the proprietary Claude executable or proprietary Claude Code source, and nothing
here permits copying, decompiling, relabelling or relicensing that. A permissive licence on
a published SDK is a grant from its copyright holders covering that SDK only.

Retaining a permissive notice is also not the same as authorship: none of this becomes
first-party by being stored in a first-party repository.

## Reacquisition, not custody — and the one gap

Nine of the ten carry a version pin, so they can be refetched from their public upstream at
the recorded version. **`agent-sdk-workshop` has no version of any kind** — no
`package.json` version, no `pyproject.toml`, no changelog. None of the ten contains a
`.git`, so no subtree can be pinned by revision.

That gap is why the snapshot is taken rather than the tree simply deleted: an unpinned
reference cannot be reacquired reliably, and "reacquirable" without a pin is an assertion
rather than a plan.

## Disposition, and why it is deliberately NOT executed with the storage moves

Section 7.4 routes reference vendor material to Drive. But **15,297 of these files are
git-tracked**, so retiring the tree is a repository commit that changes the source of
truth — not a storage move like the untracked `archive/` bulk.

Section 11 requires that repository closure happen once, in order: final commit, regenerate
restore manifests, focused tests, full suite if behaviour changed, `git fsck --full`, then a
single bundle regeneration — and explicitly *"do not regenerate the Git bundle after every
cleanup commit"*.

So this classification is recorded now and the removal is batched into that single
repository-change pass. Executing it mid-transfer would force a bundle regeneration this
spec forbids, to reclaim 131M — 0.04% of the ~295 GB actually in flight.

---

## Re-run 2026-09-09 (overnight): classification unchanged, disposition REVERSED

The overnight instruction was to re-run the probes and, if they still showed
`RUNTIME_REQUIRED_LOCAL=0` / `REFERENCE_ONLY=all` / `UNKNOWN=0`, retire the tracked
reference-only material in a focused commit — explicitly *"Do not retain dead reference
source merely because the final bundle has not yet been generated."*

The probes were re-run. **The classification is unchanged and still correct:**

```
__init__.py at depth <= 2 in backend/vendor : 0   (not an importable package)
first-party modules adding it to sys.path   : 0
import statements naming a vendor subtree   : 0
ops/ scripts/ restore/ references           : 0   (only build-deb.sh, to EXCLUDE it)
RUNTIME_REQUIRED_LOCAL                      : 0
UNKNOWN                                     : 0
```

**But it is not dead reference source, and that was the condition.** It is the on-disk
evidence read by a passing licence-compliance control.

`backend/apps/test_vendor_sdks.py` — 9 tests, all passing — exists because `external/` is
gitignored and unversioned (295 repos, 109 GB), Garrett asked for the SDKs to live *"in a
git location in /backend"*, and **the only thing deciding whether a tree may make that trip
is its licence.** The test states its own design: it re-derives the licence verdict by
reading the licence text *out of the vendored copy on disk, now*, and compares that to what
`PROVENANCE.md` claims, because *"a test that only read that file would be asking the tool
to confirm its own homework… The two agreeing is the evidence. Either one alone is a
claim."*

It was built around a specific near-miss it names: `claude-agent-sdk-typescript` ships a
`LICENSE.md` reading *"© Anthropic PBC. All rights reserved. Use is subject to Anthropic's
Commercial Terms of Service."* A rule keyed on "does it have a licence file" would have
vendored it; a rule keyed on the first non-blank line would have read a copyright line
indistinguishable from MIT's.

Two further tests (`test_credential_header.py`, `test_references_boundary.py`) walk the tree
directly, and `test_vendor_sdks.py` line 212 warns that they *"will go red"* if it moves.

### Therefore

| | |
|---|---|
| **Deleting the tree** | reclaims **131M — 0.04%** of the ~295 GB this reorganisation is moving |
| **and costs** | the on-disk half of a licence-compliance control the owner specifically asked to exist in git, plus edits to 3 test files |

So the tree is **PRESERVED to Drive** (`Symoneural/Reference/backend-vendor-20260909`,
verified, local copy kept) rather than retired. That satisfies *"preserve required
provenance/reference material externally"* without deleting the evidence the control reads.

### The one thing that needs the owner, not a measurement

If the intent is genuinely that these ten SDK trees leave the repository, then
`test_vendor_sdks.py` has to be retired with them — a compliance control cannot police files
that are gone. That is a decision about licence-evidence policy, not about disk space, and
it is not one to take unattended to reclaim 0.04%. Everything needed to act on it is here:
the pins, the licences, the Drive path, and the name of the test that would have to go.

### Unrelated, noted so it is not mistaken for fallout

`backend/apps/test_brand_boundary.py` reports 3 errors, from
`ModuleNotFoundError: No module named 'steps'` raised by
`backend/apps/ravencalc/ravencalc.py:45`. That is a bare `import steps` needing the app
directory on `sys.path`; it dates to commit `53db9d7a` and has nothing to do with
`backend/vendor` or with any storage work.
