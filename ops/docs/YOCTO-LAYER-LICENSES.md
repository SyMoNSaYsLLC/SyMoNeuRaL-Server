# Yocto layer licence and SBOM compliance

**Opened 2026-08-22.** Docs only. **No Yocto build, no recipe edited, no layer added, no image or
SDK produced by this document.**

**Classification: AUDIT — required before any appliance or embedded distribution.**

## 0. The fact that shapes everything below

**No image and no SDK has ever been built from these layers.**
`ops/docs/REPOSITORY-PURPOSE.md`'s measured platform table, and `ops/docs/BOX-REALITY-AUDIT.md` §9:
twelve `meta-symoneural-*` layers **parse**, and nothing has been built from them.

**So there is no licence manifest, no SPDX output, no package manifest and no source archive — and
there cannot be.** Those are *build outputs*. Recording them as "missing" would misdescribe the
state: they are **not yet producible**, which is a different problem with a different fix.

That is the honest headline, and it is the reason this file is an inventory of *metadata
readiness* rather than of artefacts.

## 1. Layer inventory — twelve layers, all with complete `layer.conf` metadata

Measured 2026-08-22 from each `conf/layer.conf`:

| Layer | `LAYERSERIES_COMPAT` | `BBFILE_PRIORITY` |
|---|---|---|
| `meta-symoneural-core` | blacksail | 10 |
| `meta-symoneural-kernel` | blacksail | 11 |
| `meta-symoneural-python` | blacksail | 12 |
| `meta-symoneural-networking` | blacksail | 13 |
| `meta-symoneural-filesystem` | blacksail | 14 |
| `meta-symoneural-initramfs` | blacksail | 15 |
| `meta-symoneural-extended` | blacksail | 16 |
| `meta-symoneural-bsp` | blacksail | 17 |
| `meta-symoneural-mingw` | blacksail | 20 |
| `meta-symoneural-darwin` | blacksail | 21 |
| `meta-symoneural-quail` | blacksail | 22 |
| `meta-symoneural-aws` | blacksail | 23 |

**Every layer has a `layer.conf`, a `LAYERSERIES_COMPAT` and a distinct priority.** No layer is
missing metadata and no two share a priority. **This is better than the brief assumes** and is
recorded so an audit does not re-derive it.

**Priorities 18 and 19 are unused.** Not a defect — a gap in a priority sequence is free — but
worth knowing before someone "fixes" it.

## 2. Recipe inventory — ten files, and all nine `.bb` carry licence metadata

**Nine `.bb` recipes and one `.bbappend`.** Every `.bb` has both `LICENSE` and
`LIC_FILES_CHKSUM`:

| Recipe | `LICENSE` |
|---|---|
| `meta-symoneural-core/…/images/symoneural-image.bb` | MIT |
| `meta-symoneural-core/…/packagegroups/packagegroup-symoneural.bb` | MIT |
| **`meta-symoneural-core/…/symoneural/symoneural-stack_git.bb`** | **`LicenseRef-symoneural-stack-CLOSED`** |
| `meta-symoneural-python/…/packagegroup-symoneural-python.bb` | MIT |
| `meta-symoneural-networking/…/packagegroup-symoneural-networking.bb` | MIT |
| `meta-symoneural-filesystem/…/symoneural-layout/symoneural-layout.bb` | MIT |
| `meta-symoneural-initramfs/…/images/symoneural-initramfs.bb` | MIT |
| `meta-symoneural-extended/…/packagegroup-symoneural-extended.bb` | MIT |
| `meta-symoneural-darwin/…/packagegroup-symoneural-apple-bridge.bb` | MIT |

**The `.bbappend`** is `meta-symoneural-kernel/recipes-kernel/linux/linux-yocto_%.bbappend` — a
`.bbappend` inherits the appended recipe's licence and correctly declares none of its own.

### The `symoneural-stack` recipe is already the fixed form

```
LICENSE = "LicenseRef-symoneural-stack-CLOSED"
LIC_FILES_CHKSUM = "file://LICENSES.md;md5=016512c94fb7b74a60da5fb6e40337be"
NO_GENERIC_LICENSE[LicenseRef-symoneural-stack-CLOSED] = "LICENSES.md"
```

Changed in **`97b92770`**. Its own comment records why: the bare `LICENSE = "CLOSED"` *"used to say
the same thing and warned as deprecated"*, so this is the `LicenseRef-` form the warning asked for,
`NO_GENERIC_LICENSE` points the ref at a real file in this tree, and **`LIC_FILES_CHKSUM` carries
that file's md5 so the build stops if the terms change.** No `LICENSE_FLAGS` gate is added, because
the distro sets no `LICENSE_FLAGS_ACCEPTED`.

**This makes `AUDIT.md` Q1's premise stale** — it asks about a recipe that *"declares
`LICENSE = "CLOSED"`"*, and it no longer does. See `ops/docs/LICENSE-AUDIT.md` LA-1.

## 3. Required per-recipe fields — the gap is depth, not licence

`LICENSE` and `LIC_FILES_CHKSUM` are present everywhere. The fields **not** systematically present,
and needed before an appliance ships:

`SUMMARY` · `DESCRIPTION` · `HOMEPAGE` · `SRC_URI` · `SRCREV` (git sources) · `S` / `B` ·
`DEPENDS` · `RDEPENDS` · `PACKAGECONFIG` · `inherit` classes · installed files · service files ·
config files · patches · **`CVE_PRODUCT`** · SPDX output support

**`CVE_PRODUCT` is the one to prioritise.** Without it a recipe is invisible to `cve-check`, and an
appliance that cannot answer *"which CVEs apply to this image"* is not shippable to anyone who asks
— which is exactly the customer an appliance is for.

**Eight of nine recipes are packagegroups or images**, which legitimately need less of this list
than a source recipe does. `symoneural-stack_git.bb` is the one real source recipe and the one to
audit field-by-field first.

## 4. Required build outputs — none exist, and none can yet

| Output | State |
|---|---|
| licence manifest | **not producible** — no build has run |
| SPDX / SBOM artefacts | not producible |
| image package manifest | not producible |
| source archive | no policy set; `ARCHIVER` class not configured |
| layer source archive | not producible |
| patch inventory | no patches present to inventory |
| binary redistribution notes | not written |

**The first build is the gate.** Every row above becomes measurable the moment one image builds,
and none of them is knowable before that. **Do not write a licence manifest by hand** — a
hand-typed manifest is exactly the unverifiable artefact this project's honesty rules exist to
prevent, and `bitbake` produces the real one.

## 5. Rules

- **Do not claim "Yocto Compatible"** or use official Yocto branding unless the programme's
  requirements are actually met. That is a trademark claim, and it is one nobody here has earned
  yet. `ops/docs/IDENTITY.md` and `LICENSES.md` govern branding.
- **Do not ship a layer without licence metadata.** Currently satisfied — §2.
- **Do not ship a binary image without understanding its source and licence obligations.**
  `LICENSES.md` §8 lists the obligations; §9 is the customer-build checklist.
- **No model weights in a Yocto image unless the licence permits redistribution.** Note the live
  blocker: **three of eleven weights have no licence text on disk**
  (`ops/docs/MODEL-LICENSES.md` ML-1), so those three cannot go into an image today.
- **No secrets, private keys, cloud tokens or generated credentials in an image.** The
  contract-signing private key is already ignored three ways and chmodded 0600 by `issue.py`, and
  **there is no wallet, private key or signing code in the web process.**
- **No unlicensed fonts or assets.** `LICENSES.md` §1 covers shipped static assets.
- **No GPL source-offer gap.** `LICENSES.md` §8 records the obligation; **no offer mechanism
  exists** (`LICENSE-AUDIT.md` LA-3), so this is open.

## 6. `yocto/oematch/` — in-tree, and not part of the layer question

**21 tracked files, in-tree and load-bearing**: the licence-detection tool #97's spec-mediated
pipeline calls. `.gitignore` carries three `yocto/oematch_*.deb` rules for its Debian build
products, because `dpkg-buildpackage` writes them one directory up — into `yocto/` — where they read
as new source files and go stale the moment anything under `oematch/` changes.

**#97 recorded two real defects in how it was used, and both are fixed:** oematch answers
`unsupported artifact` for a single `.c` file, so a GPL-3.0-or-later file reported
`copyleft: false` until the file's own header became the primary signal; and a licence paragraph
wrapped so the licence name straddled a line break was invisible to a substring search — *"which is
where an 80-column GPL header wraps about half the time."*

**Both are worth keeping in view here**, because this is the tool a licence audit would lean on, and
its failure mode was to under-report copyleft.

## 7. What promotes this from AUDIT

| To claim | Proof |
|---|---|
| layers are compliant | §2 complete — **already true** |
| recipes are complete | §3 fields present on `symoneural-stack_git.bb`, `CVE_PRODUCT` included |
| an image is licence-clean | a **real build**, its generated licence manifest, and no `unknown-blocked` entry |
| SBOM exists | SPDX output from that build, for a named commit |
| source offer satisfiable | `ARCHIVER` configured and an archive produced |
| an appliance may ship | all of the above, plus `SECURITY-AUDIT.md` BLOCKER/HIGH closed |

## 8. Not authorized

No Yocto build · no recipe or `layer.conf` edit · no layer added · no SDK built · no image produced ·
no `ARCHIVER` configured · no firmware, embedded or appliance implementation · no deploy.

Related: `ops/docs/LICENSE-AUDIT.md` · `ops/docs/SBOM.md` · `ops/docs/PROVENANCE.md` ·
`ops/backend/authority/docs/symoneural-appliance.md` · `ops/backend/authority/docs/symoneural-platform-targets.md` ·
`yocto/README.md` (the SDK and target matrix, and the authority on reachability).
