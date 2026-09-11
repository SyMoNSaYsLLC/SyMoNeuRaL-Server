# SBOM — the plan, and why there is no bill of materials yet

**Opened 2026-08-22.** Docs only. **No SBOM generated, no dependency added or pinned, no tool
installed by this document.**

**Classification: PROD direction — required before commercial distribution. AUDIT until an
artefact exists.**

## 0. State: none exists

**No SBOM artefact exists for any commit of this repository.** Not partial, not stale — absent.
Recorded plainly because "SBOM planned" and "SBOM stale" and "SBOM absent" are three different
positions and only one of them is true.

What *does* exist is most of the input: `LICENSES.md` (nine sections, obligations in §8),
`backend/models/PROVENANCE.json` (eleven weights with upstream repo, file and licence),
`backend/models/NAMES.md` (attribution), `docs/ops/RUNTIME-PROFILES.md` (the maturity ladder), and
`docs/ops/EXPORTS.md` (what may leave the box). **The knowledge is largely present; the machine-
readable artefact is not.**

## 1. What an SBOM here has to cover, and why it is four SBOMs

This repo is not one shippable thing, so one document cannot describe it. Four scopes, with
genuinely different tooling:

| Scope | Contents | Likely format |
|---|---|---|
| **1. Python / server** | `requirements.txt` sets, per-app venvs, the serving interpreter | SPDX or CycloneDX from a Python resolver |
| **2. Models** | the eleven weights: upstream repo, file, licence, measured bytes | **already structured** — `PROVENANCE.json` maps almost one-to-one onto SBOM package entries |
| **3. Native / engines** | `symoneural-llm`, `symoneural-diffuse`, `whisper.cpp`, the Rust gateway (`Cargo.lock` **is** tracked, deliberately, *"it is a binary that gets deployed, so the exact dependency versions matter"*) | CycloneDX; `cargo` and `bitbake` can each emit |
| **4. Yocto image** | the appliance case | **SPDX from `bitbake`** — and **not producible today**, because no image has ever been built (`YOCTO-LAYER-LICENSES.md` §0) |

**Scope 2 is the cheapest win and should be first.** `PROVENANCE.json` already carries what an SBOM
package entry needs, and its byte counts are **measured and test-checked**
(`test_weight_names.py`), which is a stronger guarantee than most SBOM fields carry anywhere.

**Scope 4 cannot be started.** An SBOM for an image that has never been built would be a document
about a hypothetical, which is the class of artefact this project's rules forbid.

## 2. The rule that governs generation

> **Generate it. Do not write it.**

A hand-authored SBOM is a carried-forward figure with more rows, and this repo has an explicit rule
against exactly that shape: *"never carry a figure forward and re-date it. Re-run it or drop it."*
The failure it prevents is on record — a published test count that *"was never true of the commit it
sat next to, because somebody carried it forward and re-dated it."*

So: **every SBOM artefact names the commit it was generated from**, and a regenerated SBOM replaces
the old one rather than being edited.

## 3. Prerequisites, honestly ordered

| # | Prerequisite | State |
|---|---|---|
| 1 | dependencies pinned where they need to be | partial — `Cargo.lock` tracked; Python pinning per-app varies |
| 2 | no system-pip pollution; isolated venvs | rule in force. `.gitignore` covers `**/.venv/` **and** `**/symoneural-*.venv/` — the second pattern had to be added because a venv named `symoneural-discovery.venv` was **not** matched by `**/.venv/` and *"a venv full of compiled wheels would be committable"* |
| 3 | a licence status per component | `LICENSE-AUDIT.md`; **three model entries are `notice-required` and unsatisfied** (`MODEL-LICENSES.md` ML-1) |
| 4 | provenance per artefact | `PROVENANCE.md`; strong for models, absent for builds |
| 5 | a tool choice: SPDX vs CycloneDX | **not made.** See §4 |
| 6 | somewhere for the artefact to live | not decided. It must be tracked, or it is not evidence |

**Prerequisite 3 gates the whole thing.** An SBOM containing an `unknown-blocked` entry is a
document that says "we do not know", which is useful internally and **not** shippable as compliance
evidence.

## 4. The format decision, not made here

**SPDX** is what `bitbake` emits natively, which makes it the obvious choice for scope 4 and
therefore for the appliance story. **CycloneDX** has better tooling for Python and Rust dependency
trees, i.e. scopes 1 and 3.

**Mixing them is a real option and should be stated as one rather than discovered.** The
alternative — forcing one format across all four scopes — costs either native `bitbake` output or
good language tooling. **Garrett's call**, or an engineering decision recorded with a date; either
way it is written down before an artefact is produced, because retrofitting a format across four
scopes is worse than choosing badly once.

## 5. Beyond an SBOM: build provenance

**SLSA-style build provenance does not exist**, and it is a different claim from an SBOM: an SBOM
says *what is in this*, provenance says *what produced this and can it be reproduced*.

The repo already has the instinct in places — `scripts/deploy.sh`, the `fork_engines.sh` /
`fork_render_ui.sh` scripts being *"the tracked artefact … which is the provenance — re-run it and
you get the same engines"* — but **none of it is attested**. See `docs/ops/PROVENANCE.md`.

## 6. What promotes this from AUDIT

| To claim | Proof |
|---|---|
| an SBOM exists | a tracked artefact naming its commit, for at least one of the four scopes |
| the model SBOM is complete | eleven entries, **none `unknown-blocked`**, `license_text` non-null throughout |
| the server SBOM is trustworthy | generated from a resolved, pinned environment — not from an interpreter's current state |
| the image SBOM exists | **a real Yocto build** producing SPDX |
| it is shippable as evidence | no `unknown-blocked` anywhere, and `LICENSE-AUDIT.md` complete |

## 7. Not authorized

No SBOM generated · no tool installed · no dependency pinned, added or removed · no venv created ·
no Yocto build · no export or distribution · no deploy.

Related: `docs/ops/LICENSE-AUDIT.md` · `docs/ops/MODEL-LICENSES.md` ·
`docs/ops/YOCTO-LAYER-LICENSES.md` · `docs/ops/PROVENANCE.md` · `docs/ops/EXPORTS.md` ·
`docs/specs/symoneural-trust-report.md` · `backend/DEPENDENCIES.md`.
