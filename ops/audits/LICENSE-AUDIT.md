# SyMoNeuRaL Licence + Provenance Upgrade — the audit, and what is already done

**Opened 2026-08-22.** Docs only. **No distribution change, no dependency added or removed, no
licence text edited by this document.**

**Classification: PROD direction — required before commercial distribution. AUDIT until
complete.**

## This is a gap analysis, not a second licence file

**`LICENSES.md` is the authority** and it is already substantial — nine sections, including §8
*"Obligations by licence, in one place"* and §9 *"Checklist for a customer build"*. A second file
restating its verdicts would drift from it on the first dependency change, which is the failure
`.claude/CLAUDE.md`'s first *never* exists to prevent.

So this file holds **status, gaps and the promotion path**. Verdicts stay in `LICENSES.md`.

| Question | File |
|---|---|
| what is the licence of a shipped thing? | **`LICENSES.md`** |
| what may leave this box? | **`ops/registry/EXPORTS.md`** |
| which weight came from where? | **`backend/models/PROVENANCE.json`** (+ `NAMES.md`) |
| per-model licence status | `models/docs/MODEL-LICENSES.md` |
| Yocto layers and recipes | `backend/asicminer/docs/YOCTO-LAYER-LICENSES.md` |
| SBOM plan | `ops/registry/SBOM.md` |
| provenance plan | `models/docs/PROVENANCE.md` |
| what is the audit state? | **this file** |

## Licence status vocabulary

`first-party` · `permissive-ok` · `copyleft-ok-with-obligations` · `source-offer-required` ·
`notice-required` · `attribution-required` · `no-commercial-use` · `redistribution-restricted` ·
`proprietary-reference-only` · `unknown-blocked` · `removed`

**`unknown` is `unknown-blocked`.** An unrecorded licence is not a small gap — it is a blocker
until provenance exists, because you cannot ship what you cannot describe.

## What is already true — measured 2026-08-22

- **`LICENSES.md` exists** with the nine sections above, and it carries the decision rule at the
  top rather than only a table.
- **`backend/models/PROVENANCE.json` exists** — `{schema, note, weights}` — and is **tracked
  deliberately**: `.gitignore` re-includes it through the `backend/models/*` exclusion because *the
  weights are fetched, so if the manifest is not in git it is not anywhere.*
- **`backend/models/NAMES.md` is tracked as a licence obligation, not documentation.** `.gitignore`
  says it plainly: Apache-2.0 and MIT let us rename what we redistribute and **do not** let us drop
  the notice, so *"untracking it is the one way to lose the notice without deleting it."*
- **Two items are already retired from distribution**, and recorded as retired rather than deleted:
  Swagger UI 5.17.14 (Apache-2.0, retired 2026-08-21) and **ComfyUI (GPL-3.0)** — the latter being
  the one that would otherwise put a copyleft tree inside a repo whose `LICENSES.md` says nothing
  shipped is copyleft.
- **NVIDIA CUDA is named as "the one genuinely restrictive item"** (§6), which is the right posture
  for the component most likely to be waved through.
- **No archive is tracked anywhere.** `git ls-files | grep -E '\.(tar\.gz|tgz|zip)$'` returns
  nothing, and `/references` is excluded wholesale.
- **`yocto/oematch/` is the licence-detection tool** #97 depends on, and #97 fixed two real defects
  in how it was used — see §Findings.

## Gaps — the reason this is AUDIT

| Gap | State |
|---|---|
| **`NOTICE.md`** | **does not exist** |
| **`THIRD-PARTY-NOTICES.md`** | **does not exist** |
| generated third-party notices | not generated; §8 of `LICENSES.md` is hand-maintained. **Partial exception:** each of the ten vendored trees retains its own `LICENSE` in-tree, which discharges that notice at the file level even though no aggregate notice exists |
| SBOM | none produced. `ops/registry/SBOM.md` is the plan |
| SLSA-style build provenance | not started |
| per-model licence status table | `models/docs/MODEL-LICENSES.md`, opened, incomplete |
| Yocto licence manifest / SPDX output | **cannot exist yet** — see `YOCTO-LAYER-LICENSES.md`: no image has ever been built |
| source-offer obligations | recorded in `LICENSES.md` §8; **no offer mechanism exists** |

**`LICENSES.md` §8 and §9 already carry the obligations and a customer-build checklist**, so the
gap is machinery and artefacts, not knowledge. That is the honest framing: the thinking is done,
the generated evidence is not.

## Findings

### LA-1 — `AUDIT.md` Q1's premise is stale; the recipe was already fixed

**Q1 asks what licence `symoneural-stack` carries, on the stated basis that the recipe *"declares
`LICENSE = "CLOSED"`"*.** It no longer does. Measured at
`yocto/meta-symoneural-core/recipes-symoneural/symoneural/symoneural-stack_git.bb:7-9`:

```
LICENSE = "LicenseRef-symoneural-stack-CLOSED"
LIC_FILES_CHKSUM = "file://LICENSES.md;md5=016512c94fb7b74a60da5fb6e40337be"
NO_GENERIC_LICENSE[LicenseRef-symoneural-stack-CLOSED] = "LICENSES.md"
```

Changed in **`97b92770`**, and the recipe's own comment explains it: the bare `CLOSED` *"used to
say the same thing and warned as deprecated"*, so this is the `LicenseRef-` form the warning asked
for, `NO_GENERIC_LICENSE` points the ref at the file in this tree, and **`LIC_FILES_CHKSUM` carries
that file's real md5 so the build stops if the terms change.**

**That is Q1 option (a), already implemented.** What may still stand is Q1's second half — whether
this contradicts the claim that the stack is *"off-the-shelf and permissively licensed"*, a
sentence that has since moved out of `.claude/CLAUDE.md` into `ENGINEERING.md` under R-180.
**Recorded on Q1 in `AUDIT.md` rather than answered here** — the question is Garrett's, but it
should not be answered against a premise that has changed.

### LA-2 — the reference archives are third-party source, and one is proprietary

`@symoneural code.tar.gz` was **inspected** (listing only) and contains **no first-party code**:
3,598 entries across eleven Anthropic projects. Licence readings taken from inside the archive:

- **`claude-code` — `© Anthropic PBC. All rights reserved.`**, use subject to Anthropic's
  Commercial Terms of Service. Status: **`proprietary-reference-only`.**
- **`anthropic-sdk-python` — MIT.** Status: `permissive-ok`.
- the remaining nine each carry a `LICENSE` file; **not individually read from the archive.**

**CORRECTION 2026-08-22 — an earlier draft of this row said `anthropic-sdk-python` was "still not
vendored". That was wrong, and it was wrong because I asserted it without looking.**

**`backend/vendor/` is tracked: 15,297 files**, and it holds ten deliberately vendored third-party
SDK trees. `backend/vendor/PROVENANCE.md` is the record, it is **generated** by
`tools/lib/index_references.py vendor`, and it says so in its own opening: *"Do not hand-edit: it is
regenerated, and a hand-added row would be a claim nobody read a licence file to make."*

| Vendored tree | Licence | Tracked files |
|---|---|---|
| `anthropics/agent-sdk-workshop` | Apache-2.0 | 73 |
| `anthropics/anthropic-sdk-csharp` | MIT | 2,734 |
| `anthropics/anthropic-sdk-go` | MIT | 332 |
| `anthropics/anthropic-sdk-java` | MIT | 2,927 |
| `anthropics/anthropic-sdk-php` | MIT | 2,231 |
| `anthropics/anthropic-sdk-python` | MIT | 1,495 |
| `anthropics/anthropic-sdk-ruby` | MIT | 3,827 |
| `anthropics/anthropic-sdk-typescript` | MIT | 474 |
| `anthropics/claude-agent-sdk-python` | MIT | 144 |
| `openai/apps-sdk-ui` | MIT | 1,059 |

Each is copied with its `.git` stripped, **its `LICENSE` kept**, build directories pruned, and **the
upstream commit recorded** — which the record explains is the point: *"without it a vendored tree
cannot be diffed against anything, updated deliberately, or checked against an advisory."*

**And two were refused, which is the part that shows the rule is real:**

- **`anthropics/claude-agent-sdk-demos` — NO licence file at all.** *"An absent licence is not a
  permissive default. Without a grant the default is all rights reserved."*
- **`anthropics/claude-agent-sdk-typescript` — ALL-RIGHTS-RESERVED.** Its `LICENSE.md` contains those
  words and points at a commercial ToS.

The record's own note on the second is the sharpest sentence in this audit and it belongs here:
*"a rule keyed on 'has a LICENSE file' would have vendored it. The grant is what is matched, never
the presence of the file, and never the copyright line, which is identical in an MIT file and in
this one."*

**So this correction cuts both ways.** My "not vendored" was false — ten trees are in the
repository. And my `unknown-blocked` for "the remaining nine" was lazier than the repo already is:
two of those names had already been read and classified, and one of them is **all-rights-reserved**,
which is a materially different answer from "not yet read".

**What the archive-versus-vendor distinction actually is**, stated so it is not conflated again:
`references/symoneural code.tar.gz` is an **unimported reference archive** (§LA-2 above);
`backend/vendor/` is a **separate, deliberate, licence-checked vendoring** drawn from `references/`
directories whose name contains `sdk`. They overlap in subject and are not the same act. `claude-code`
— all-rights-reserved — is in the archive and is **not** vendored, which is the rule working.

**Guarded by tests.** `backend/apps/test_vendor_sdks.py` carries nine, including one worth naming:
`test_gitignore_does_not_silently_swallow_vendored_files` asks **git itself** whether any file under
a vendored tree is ignored, because `.gitignore` carries `*.log`, `*.key`, `*.safetensors`, `*.gguf`,
`__pycache__/` and `**/.venv/` with no path anchor, and *"a tree that is 90% tracked reads as
complete in `ls` and is not in the repository."* **Note for anyone running the suite:** a bare
`pytest --collect-only` from `backend/` imports these trees and leaves `__pycache__` bytecode inside
them, which fails that test until the bytecode is removed. Nothing is wrong with the repo when that
happens — the canonical invocation in `ops/registry/MEASUREMENTS.md` scopes to `apps/` and does not
import them.

**Status change:** the ten vendored trees are `permissive-ok` / `notice-required` (nine MIT, one
Apache-2.0), each with its `LICENSE` retained in-tree, which is what discharges the notice. **They
are not `unknown-blocked`.** The two refused names are `proprietary-reference-only` and
`unknown-blocked` respectively — and neither is in the tree.

**Behaviour may be reimplemented. Source may not be copied.** Full reading:
`backend/coder/docs/symoneural-coder-project-cli-scope.md` §1, §5.

The other four archives are **unopened** and therefore `unknown-blocked`:
`simpy.tar.gz` (3.8 MiB) · `symoneural streamer.tar.gz` (271 MiB) · `miner.tar.gz` (**ambiguous —
two files match**) · `oematch.tar.gz` (16 KiB).

### LA-3 — `NOTICE.md` and `THIRD-PARTY-NOTICES.md` are missing, and one obligation depends on them

`LICENSES.md` §8 records notice and attribution obligations, but **there is no notice artefact to
ship.** For a repo that currently distributes little this is latent; **for a customer build or an
appliance it is a blocker**, because a notice obligation is discharged by delivering the notice, not
by having written down that one is owed.

`NAMES.md`'s existence shows the pattern is understood — it exists *because* renaming a
redistributed weight does not remove the attribution duty.

### LA-4 — no SBOM, and no build provenance

Neither exists. Both are prerequisites for `ops/backend/authority/docs/symoneural-trust-report.md` and for
`ops/backend/authority/docs/symoneural-appliance.md`, which is why those are FUTURE rather than scheduled.

## Inventory areas, and where each stands

| Area | Where | State |
|---|---|---|
| **A. repo code** | `LICENSES.md` §7 *"What is ours"* | recorded |
| **B. models/weights** | §2 + `PROVENANCE.json` + `MODEL-LICENSES.md` | partly; per-model status table incomplete |
| **C. engines/runtimes** | §3, §5, §6 | recorded; `RUNTIME-PROFILES.md` carries maturity |
| **D. frontend/static** | §1 | recorded; two items retired |
| **E. reference archives** | LA-2 | one inspected, four unopened |

**Per-model fields required** before any model is called ready or commercial: model id · source ·
licence · provenance · local path · **redistribution allowed?** · **commercial use allowed?** ·
**modification allowed?** · **output restrictions?** · attribution required? · gated access?

**An unknown licence blocks that model**, and blocks the build that includes it.

## Promotion path — what closes this audit

| To claim | Proof |
|---|---|
| "licence clean" | every shipped dependency, source, model and runtime has a status from the vocabulary above — **and none is `unknown-blocked`** |
| notices discharged | `NOTICE.md` and `THIRD-PARTY-NOTICES.md` exist **and are generated**, not hand-typed |
| model licences recorded | `MODEL-LICENSES.md` complete, cross-checked against `PROVENANCE.json` |
| Yocto ready | `YOCTO-LAYER-LICENSES.md` complete **and a licence manifest produced by a real build** |
| SBOM | an SBOM artefact exists for a specific commit |
| source-offer satisfiable | a mechanism exists, not only a recorded obligation |

**No "licence clean" claim until the audit completes.** And per `EXPORTS.md`, nothing leaves the
box on this document's authority.

## Not authorized

No dependency added or removed · no licence text edited · no notice file generated · no model
downloaded · no archive imported · no distribution or deploy · no Yocto build.
