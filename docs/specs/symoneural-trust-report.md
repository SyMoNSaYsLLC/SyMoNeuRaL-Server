# SyMoNeuRaL Trust Report — FUTURE, and it must not render what does not exist

**Scope captured 2026-08-22.** Docs only. **FUTURE/AUDIT. Not implementation authorization.**

## 1. The bet

**A downloadable audit report per model, runtime, job or build** — SBOM, model licence, runtime
licence, hardware profile, and job metadata as far as policy allows. A compliance and export feature
a customer can hand to their own reviewer.

**Why it is credible here specifically.** This repo already refuses to publish a number without
saying how it was measured. `PROVENANCE.json`'s byte counts are checked against the real file by
`test_weight_names.py`, *"so a truncated or substituted download fails a test instead of serving
quietly."* Every figure is labelled `measured` / `vendor` / `projected`. **A trust report is that
habit, rendered for somebody else.**

## 2. Why it is FUTURE — it is a rendering, and the inputs are not all there

**A trust report generates nothing. It renders.** So it is exactly as trustworthy as its inputs, and
the inputs are:

| Input | State |
|---|---|
| model licence + provenance | **strong** — `PROVENANCE.json`, but **three of eleven have no licence text on disk** (ML-1) and the commercial-use fields are unrecorded for all eleven (ML-2) |
| runtime licence | recorded in `LICENSES.md` §3, §5, §6 |
| runtime provenance | **partial** — the build script is the tracked provenance, but nothing records which binary served a job |
| SBOM | **none exists** |
| build provenance | **none exists** |
| hardware profile | `docs/ops/HARDWARE-PROFILES.md` |
| job metadata | partial — the meter has a ledger; surface/model/runtime/target fields are not in it |
| notices | **`NOTICE.md` and `THIRD-PARTY-NOTICES.md` do not exist** |

**The one rule this feature lives or dies by:**

> **It must never render a field it does not have.** No "N/A" standing in for a licence, no blank
> where a provenance record should be, no absent SBOM implied by a heading.

**A trust report with gaps presented as a complete document is worse than no report**, because its
whole value is that a reviewer can rely on it. If a field is unknown it says **unknown**, and an
unknown licence says `unknown-blocked` in the vocabulary `LICENSE-AUDIT.md` already defines.

## 3. Scopes — four, matching the SBOM scopes

**Per model** — id, house name, upstream repo and file, licence + text, measured bytes,
`modified_by_us`, redistribution and commercial-use answers.

**Per runtime** — id, family, maturity from the `absent`/`source-only`/`built`/`running`/`measured`
ladder, licence, build provenance.

**Per job** — job id, surface, model, runtime, target, hardware profile, timings, and **units
charged**. Bounded by policy: a job report must not leak a prompt, an input, or another tenant's
anything.

**Per build** — commit, SBOM, licence manifest, attestation. **Not producible today** for the image
scope, because no image has been built.

## 4. What it must never do

- **Never leak the trade secret.** `training/corpus.jsonl` and `training/build_dataset.py` never
  appear, and neither does anything derived closely enough to reconstruct them. **Publish the
  numbers, keep the methods.** `docs/ops/EXPORTS.md` governs every field.
- **Never leak another tenant's data**, and never a prompt or input unless policy explicitly allows.
- **Never leak a local path, a token, or a `file://` / `vscode://` / `pycharm://` link.** The same
  prohibition the security audit puts on public API responses applies with more force to a document
  designed to be sent outside.
- **Never imply legal clearance.** It reports licences; it does not opine that a use is permitted.
  Same boundary Sigils has about trademarks: recording provenance is not issuing an opinion.
- **Never be hand-assembled.** Generated from the artefacts, naming the commit, or it is a
  carried-forward figure with a cover page.

## 5. What promotes this from FUTURE

| To claim | Proof |
|---|---|
| a per-model report | eleven entries, `license_text` non-null, ML-2's fields recorded |
| a per-runtime report | each served engine traceable to a script **and** a commit |
| a per-job report | the ledger carrying surface, model, runtime, target and units |
| a per-build report | an SBOM and an attestation for a named commit |
| it is exportable | an `EXPORTS.md` review of every field, and a test that the forbidden ones cannot appear |

**That last row is the one to build first if this is ever scoped** — a test asserting the report
cannot contain a protected path or a token is the difference between a compliance feature and a leak
with a letterhead.

## 6. Not authorized

No report implemented · no export format chosen · no artefact generated · no field added to any
ledger or manifest · no export or distribution · no deploy.

Related: `docs/ops/PROVENANCE.md` · `docs/ops/SBOM.md` · `docs/ops/LICENSE-AUDIT.md` ·
`docs/ops/MODEL-LICENSES.md` · `docs/ops/EXPORTS.md` · `docs/specs/symoneural-appliance.md`.
