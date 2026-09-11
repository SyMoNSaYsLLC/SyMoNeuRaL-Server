# SyMoNeuRaL Appliance — FUTURE, and blocked on a build that has never run

**Scope captured 2026-08-22.** Docs only. **FUTURE/AUDIT. Not implementation authorization. No
Yocto build, no firmware, no device work.**

## 1. The bet

**A signed, provenanced, offline local-AI box.** Yocto/embedded, license-manifested, hardware-
profiled — a productized edge deployment for a customer who cannot or will not send data anywhere.

It is a coherent bet because it monetises the two things this repo is unusually good at: **running
locally**, and **being able to say what it is made of.**

## 2. The blocking fact, stated first

> **No image and no SDK has ever been built from these layers.**

`business/REPOSITORY-PURPOSE.md`'s measured platform table and `BOX-REALITY-AUDIT.md` §9: twelve
`meta-symoneural-*` layers **parse**, and nothing has been built from them.

**So there is no licence manifest, no SPDX output, no package manifest and no source archive — and
there cannot be, because those are build outputs.** `YOCTO-LAYER-LICENSES.md` §4 states it as the
distinction that matters: they are **not yet producible**, which is different from missing.

**The first successful image build is the gate.** Everything below becomes measurable then and is
unknowable before.

## 3. What is already in place, and it is more than expected

| Piece | State |
|---|---|
| twelve layers | **all** with `layer.conf`, `LAYERSERIES_COMPAT=blacksail`, distinct priorities 10–23 |
| nine `.bb` recipes | **all** carry `LICENSE` **and** `LIC_FILES_CHKSUM` |
| the one real source recipe | `symoneural-stack_git.bb`, using the correct `LicenseRef-` form with `NO_GENERIC_LICENSE` and a real md5, so **the build stops if the terms change** |
| model provenance | `PROVENANCE.json`, with **measured, test-checked** byte counts |
| obligations | `LICENSES.md` §8, and §9 is already a *customer-build checklist* |
| what may leave the box | `ops/registry/EXPORTS.md` |

**§9 of `LICENSES.md` being a customer-build checklist is the tell that this bet was anticipated.**
The groundwork is deliberate, not accidental.

## 4. What blocks an appliance beyond the build itself

| Blocker | Source |
|---|---|
| **three weights cannot be redistributed** — `license_text: null` on the unsloth/Qwen3.x files, so Apache-2.0 §4 attribution has nothing to travel | `MODEL-LICENSES.md` ML-1 |
| **commercial-use and redistribution fields unrecorded for all eleven** weights | ML-2 |
| **no `NOTICE.md` / `THIRD-PARTY-NOTICES.md`** — an obligation is discharged by delivering the notice | `LICENSE-AUDIT.md` LA-3 |
| **no GPL source-offer mechanism** — the obligation is recorded, the mechanism is not | LA-3 |
| **no SBOM, no build provenance** | `SBOM.md`, `PROVENANCE.md` |
| **no signing story** — and the signing credential is structurally Garrett's | `symoneural-platform-targets.md` §3 |
| **`CVE_PRODUCT` not set** — an image that cannot answer "which CVEs apply" is unshippable to the customer an appliance is for | `YOCTO-LAYER-LICENSES.md` §3 |
| **Linux app packaging direction is open** | `symoneural-platform-targets.md` §4 |

**The weight blockers are the sharpest**, because an offline AI appliance with no model is not the
product. **Three of eleven models cannot legally travel today**, and that is a fetch-and-record
task, not a research project.

## 5. Rules

- **No claim of a production appliance until one is built and tested.**
- **No "Yocto Compatible" or official Yocto branding** unless the programme's requirements are met.
  That is a trademark claim nobody here has earned.
- **No model weights in an image unless the licence permits redistribution** — see §4.
- **No secrets, private keys, cloud tokens or generated credentials in an image.** Already the
  posture: the contract-signing private key is gitignored three ways, chmodded 0600 by `issue.py`,
  and there is **no wallet, private key or signing code in the web process.**
- **No unlicensed fonts or assets.**
- **The appliance is a distribution channel**, so `EXPORTS.md` governs every byte, and the trade-
  secret boundary is absolute: `training/corpus.jsonl` and `training/build_dataset.py` **never
  ship.** Publish the numbers, keep the methods.

## 6. What promotes this from FUTURE

| To claim | Proof |
|---|---|
| an image exists | a real `bitbake` run producing one |
| it is licence-clean | that build's **generated** licence manifest, no `unknown-blocked` entry, and a shippable model set |
| it is describable | SPDX/SBOM for a named commit |
| it is signable | a signing story with a credential holder, and a signed artefact |
| it is a product | all of the above, plus `SECURITY-AUDIT.md` BLOCKER/HIGH closed, plus notices delivered |

## 7. Not authorized

No Yocto build · no recipe or layer edit · no SDK · no firmware · no device or appliance work · no
signing · no model download · no export or distribution · no deploy.

**FUTURE means captured, not queued.** No `PROJECT-TASKS.md` row, and per `GUARDRAILS.md` no
platform or embedded work starts on inference — only on Garrett naming it.
