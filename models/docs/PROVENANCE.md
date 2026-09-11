# Provenance — what ran, where it came from, and whether it is licensed

**Opened 2026-08-22.** Docs only. **No manifest field added, no attestation produced, no build
run by this document.**

**Classification: PROD direction (ModelOps / supply-chain). AUDIT for implementation.**

## 0. Four kinds of provenance, and only one of them is solved

The word covers four different claims. Separating them is the point of this file, because "we have
provenance" is true of exactly one row — and even that row is true of 39% of the weight files
rather than of the disk. See §1.

| Kind | Answers | State |
|---|---|---|
| **model provenance** | which upstream artefact is this weight? | **strong for 11 of 28 files; absent for the other 17** — `PROVENANCE.json` + §1 |
| **runtime provenance** | which engine build served this, from what source? | partial |
| **data provenance** | what was this adapter trained on? | protected, and deliberately not exportable |
| **build provenance** | what produced this artefact, reproducibly, attested? | **none** |

## 1. Model provenance — the pattern the others should copy

`backend/models/PROVENANCE.json` is the authority, and it is worth reading as a design rather than
a file. Per weight: `path` · `role` · **`bytes_on_disk`** · `upstream_repo` · `upstream_file` ·
`license` · `license_text` · `modified_by_us`.

Four properties that make it actually load-bearing:

- **It is tracked on purpose.** `.gitignore` excludes `backend/models/*` and then re-includes this
  file, because *"the weights are fetched, so if the manifest is not in git it is not anywhere."*
- **`bytes_on_disk` is measured, not copied from a model card**, and
  `backend/apps/test_weight_names.py` checks it against the real file whenever the file is present —
  *"so a truncated or substituted download fails a test instead of serving quietly."* **That is
  provenance with a tripwire**, which is rarer than provenance with a table.
- **It states its own reasons**, and the middle one is a legal obligation: re-fetching needs the
  upstream URL; **Apache-2.0 §4 obliges attribution to travel with a redistributed artefact**; and
  *"a house name with no recorded origin is an unfalsifiable claim about what the bytes are."*
- **`modified_by_us: false` on every entry**, with the principle stated: *"Renaming the file is not
  modifying the weights."*

**The known gap:** three of eleven entries have `license_text: null` — the unsloth/Qwen3.x files —
so their attribution cannot travel. `models/docs/MODEL-LICENSES.md` ML-1.

**And the larger gap, measured 2026-08-22: the manifest covers 11 of 28 weight files.** The other
**17 — 78.26 GiB, 61% of the weight bytes here — have no provenance at all.** So "model provenance
is strong" was true of what the manifest describes and false as a statement about this disk, which
is a distinction this file of all files should have drawn. `tools/lib/modelops_inventory.py` now
measures it and `models/docs/SYMONEURAL-MODEL-BUNDLES.md` §5 lists them.

**The pattern held; the coverage did not.** Nothing about the manifest's design was wrong — its
fields, its tracked-ness, its byte-count tripwire are all still the thing to copy. It was simply
never asked whether it described everything on the disk, and nothing asked on its behalf.

**And the structural gap:** the manifest records *where a weight came from*, not *whether we may
ship it or sell its output*. Four fields are missing — redistribution, commercial use,
modification permission, output restrictions — which is `MODEL-LICENSES.md` ML-2, and it is the
difference between provenance and entitlement.

## 2. Runtime provenance — partial, and the pattern is a script

The instinct is already here: the **tracked artefact is the build script**, not a copied tree.
`.gitignore` says it for `engines/` — *"the tracked artefact is the script, which is the
provenance — re-run it and you get the same engines. Do not track a derived copy of an untracked
source."* Same for `tools/sh/fork_engines.sh` and `tools/sh/fork_render_ui.sh`.

**That is reproducibility by construction, and it is not attestation.** Nothing records *which*
engine binary served a given job, or which commit of the script built it.

**One concrete hole, already recorded elsewhere:** `contrib/build-kawpowminer.sh` is **not tracked**
— three copies exist and all are outside the repo — so the 52–53 MH/s benchmark's binary cannot be
rebuilt from this tree at all (`backend/cryptominer/docs/symoneural-miner-scope.md` §2). **That is the shape of a
provenance failure**: a real measurement whose producer is unreachable.

`backend/hardware/docs/RUNTIME-PROFILES.md` carries the maturity ladder — `absent` / `source-only` / `built` /
`running` / `measured` — which is the right vocabulary and is about *readiness*, not origin. Both
are needed.

## 3. Data provenance — protected, and it must stay unexportable

`training/corpus.jsonl` and `training/build_dataset.py` are **trade secret, protected only by not
being public**, and `corpus.jsonl` **is currently tracked in git** — with no remote, which is doing
all of the protecting. **If a remote is ever added, that is the first thing to audit.** The standing
rule: **publish the numbers, keep the methods.**

So data provenance here is deliberately asymmetric: a trained adapter must be describable — base
model, method, date, measured result — **without** the corpus being exportable. `ops/registry/EXPORTS.md`
governs, and `dataset_guard.py` exists for this.

**Every filesystem-facing surface already denies these paths**: Coder's denylist and Project's
`link_file` both apply it to the **resolved** absolute path, so a symlink cannot get round it — and
Coder's version carries the regression where `adapter` matched a path *segment* and
`training/adapter-qwen36` was readable until the entry became a glob.

## 4. Build provenance — none, and what it would take

**Nothing is attested.** No signed statement of what produced any artefact.

The pieces that would feed one: `git` (the commit), the generator scripts (already the tracked
provenance for derived trees), `Cargo.lock` (tracked *"because it is a binary that gets deployed, so
the exact dependency versions matter"*), and `bitbake` for an image. **What is missing is the
statement tying them together**, plus somewhere trustworthy to keep it.

**The honest prerequisite is reproducibility, not signing.** An attestation over a build that
cannot be reproduced attests to an event, not to an artefact — and the first thing to establish is
that running the same script on the same commit produces the same bytes. **Nobody has checked
that**, for any engine here.

## 5. The generalisable rule this repo already follows

> **Every figure is labelled `measured`, `vendor` or `projected`.**

From `plugins/reinforce/registry.py`: **scan-never-hardcode, derive-never-look-up, every figure
labelled.** Provenance is that rule applied to artefacts instead of numbers — and the enforcement
mechanism is the same one that works everywhere else here: **a test that fails when the claim and
the disk disagree**, as `test_weight_names.py` does for byte counts.

**A provenance field with no test is a comment.**

## 6. What promotes this from AUDIT

| To claim | Proof |
|---|---|
| model provenance complete | eleven entries, `license_text` non-null throughout, ML-2's four fields recorded |
| runtime provenance exists | each served engine traceable to a script **and** a commit |
| builds are reproducible | same script + same commit → same bytes, **measured** |
| build provenance exists | an attestation over a reproducible build, stored where it can be checked |
| a trust report is possible | all of the above, plus `SBOM.md` and `LICENSE-AUDIT.md` complete |

`ops/backend/authority/docs/symoneural-trust-report.md` is the customer-facing product that would sit on top of
this, and it is FUTURE precisely because none of the four rows above is finished.

## 7. Not authorized

No manifest field added · no licence text fetched · no attestation produced · no build run · no
reproducibility experiment · no export · no deploy.

Related: `backend/models/PROVENANCE.json` · `backend/models/NAMES.md` ·
`models/docs/MODEL-LICENSES.md` · `ops/audits/LICENSE-AUDIT.md` · `ops/registry/SBOM.md` ·
`ops/registry/EXPORTS.md` · `backend/hardware/docs/RUNTIME-PROFILES.md`.
