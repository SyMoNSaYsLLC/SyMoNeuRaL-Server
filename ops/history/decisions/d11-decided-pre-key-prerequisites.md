# D-11 DECIDED — controlling signing architecture recorded; pre-key prerequisites characterized

> **REDACTED.** Customer names, credential filenames, security/lockdown tooling names, internal
> ports and infrastructure-posture details are masked or referred to by role. Meaning is
> preserved. No key material and no secret values appear in this file. Unredacted detail is on
> the box in `Sept1.md` §22 at HEAD `5063b480`.

**Date:** 2026-09-02 · **HEAD:** `5063b480` · **Repo:** `/home/google/Symoneural`
**Nature:** owner ruling recorded. **Architecture only — no implementation.**

## Continues from

Previous handoff: `d11-signing-authority-key-custody-decision.md` (2026-09-02), which ended
`D-11 READY FOR OWNER DECISION` at HEAD `2def42b9` with no commit. The owner accepted the
recommendation in full. This window records it and turns the analysis findings into
authorization-sized work items.

| Control point | At `2def42b9` (prev) | Now at `5063b480` |
|---|---|---|
| HEAD | `2def42b9` | `5063b480` |
| **D-11** | **OPEN** (ready for decision) | **DECIDED — architecture only** |
| Controlling record | none | **`Sept1.md` §22**, 223 lines |
| A-4 | COMPLETE 19/19 | **COMPLETE 19/19 — unchanged** |
| Signing keys on box | 0 | **0 — none generated** |
| Signed artifacts | 0 | **0** |
| Tracked mods | `ops/registry/EXPORTS.md` | `ops/registry/EXPORTS.md` — untouched |

## 1. D-11 decision record change

Single file, `Sept1.md`. `236 insertions(+), 13 deletions(-)`.

**Six scattered state assertions updated** — 44, 854, 927, 995, 1042, 1082 — each of which said
"D-11 remains OPEN". This is the same defect commit `2def42b9` fixed for A-4: a ruling recorded
in one place while nine others still say OPEN is a record that argues with itself.

**§18 register entry replaced** by the owner ruling, with re-measured evidence (48 feed indexes,
9 `Release` files, 0 signatures, GnuPG 2.4.7 present, minisign/cosign/age absent, 0 keys, 0
signed commits, 6 unsigned tags, no git remote). `*Decision:* **RULED — (b)**`.

**New §22** — the controlling architecture, preserved state, P1/P2/P3, ordered prerequisites,
remaining release gates. Numbered 22 because §21 was already "Definition of Done".

**Deliberately NOT touched, to protect A-4:**
- All 19 indicator states. `AUTHORIZED (A-4 only)` on `RELEASE_IDENTITY` / `CUSTODY_RECORD` is
  **byte-identical** across the diff — verified by grepping both diff sides.
- L853 / L1081 / L1411 — "D-11 = (d) for A-4 only" is **still true**; editing it would reopen A-4.
- L1016 / L1047 — release gating statements, still true.
- `ops/registry/EXPORTS.md` — pre-existing unstaged modification, never staged (verified at commit).

## 2. Exact final D-11 state

| Dimension | Ruling |
|---|---|
| Scope | **D-11(b)** — sign externally distributed artifacts; feed signing **mandatory when feeds are externally distributed** |
| Authority | **A-4** — one organization-level **SymonSays LLC** release authority, operator-held custody |
| Hierarchy | **H-2** — offline **certify-only** OpenPGP primary + long-lived release-signing subkey |
| Custody | **C-2** — primary offline/removable; subkey host-held **only** in an operator-owned protected location, **never service-readable, never in the repository** |
| Mechanism | **OpenPGP / GnuPG** |
| Identifier of record | **Full 40-hex** primary/subkey fingerprints. Short/long key IDs collidable — never alone |
| Rotation | Rotate **signing subkeys under the existing primary** |
| Revocation | Revocation certificate at the **future** ceremony, **held separately** |
| Expiry | **Finite** signing-subkey expiry |
| Runtime-secret separation | **Absolute** — session secrets and entitlement keys **never** reused or derived into signing material |
| Archive signing | **Detached OpenPGP signature** over the final customer archive |
| Release identity | `source-sha` **must correspond to a signed release tag** |
| Custody/provenance | **Signed release record**: signer + fingerprint, UTC time, source SHA, archive SHA-256, licence/provenance, export scope |
| Feeds | **Clearsigned `InRelease`** when DEB/IPK feeds are externally distributed |

**Status: DECIDED — architecture only.** No key exists. No artifact is signed. No custody record
exists. **External release is NOT authorized.** A ruling on *how* to sign is not permission to
sign, and not permission to ship.

## 3. P1 — exporter signing-material exclusions (scope + tests, NOT implemented)

**The crux, and why a blanket rule would be wrong:** `.asc` and `.gpg` **cannot be discriminated
by name**. `gpg --export-secret-keys --armor` emits `.asc` (must never leave). But
`build-apt-repo.sh:105` runs `gpg --armor --export > symoneural-archive-keyring.asc` — a
**publishable** artifact, and P3 publishes exactly that class. A blanket `\.asc$` rule would
refuse the public keyring and violate the requirement not to block legitimate verification
material. So P1 splits three ways.

**P1-a — unambiguously private by path/name** (pattern additions; same architecture as today)

| Rule | Refuses | Sabotage / regression test |
|---|---|---|
| `\.kbx$` | GPG keybox | Manifest a `pubring.kbx` → non-zero exit, **no archive written** |
| `(^|/)private-keys-v1\.d/` | GPG private key store | Manifest a file under it → refusal names the class |
| `(^|/)\.gnupg/` | whole GPG home | Manifest any path under it → refusal |
| `\.minisig$` | minisign material | Manifest one → refusal |
| `(^|/)ops/(keys\|signing)/` | custody dirs **by location** | Manifest a file in each → refusal for both |

**P1-b — ambiguous by name, resolved by CONTENT.** This is an **architectural addition**, not
another pattern: stage 2 is currently path-regex-only, so a content sniff is a new kind of check.

| Rule | Refuses | Tests |
|---|---|---|
| Sniff for `-----BEGIN .*PRIVATE KEY BLOCK-----`, `-----BEGIN OPENSSH PRIVATE KEY-----`, `-----BEGIN .*PRIVATE KEY-----` on every candidate | Armored private keys **whatever they are named** — including `ops/keys/release.asc`, `release.gpg`, and the **extensionless** `ops/signing/release_ed25519` that no name pattern can reach | One test per header form, each at a **different filename** (`.asc`, `.gpg`, extensionless) to prove detection is name-independent. Plus a binary/large-file case proving the sniff can't be evaded by a leading NUL or huge file |

**P1-c — the carve-out, and the test that protects it**

| Requirement | Test |
|---|---|
| The **public** keyring `.asc` must remain **exportable** | Manifest it → **exit 0**, and assert it **is** present in the archive. This test is what stops P1 over-blocking, and must fail loudly if anyone later adds a blanket `\.asc$` |

**Measured gap this closes** (hypothetical paths vs the live 17 patterns):

```
PASSES   ops/keys/release.asc            <-- NOT COVERED
PASSES   .gnupg/pubring.kbx              <-- NOT COVERED
PASSES   ops/release.gpg                 <-- NOT COVERED
PASSES   ops/release.minisig             <-- NOT COVERED
PASSES   ops/signing/release_ed25519     <-- NOT COVERED
PASSES   ops/signing/release_ed25519.pub <-- NOT COVERED
BLOCKED  *.pem *.key *.p12  id_ed25519  secrets/*  run/*   (already covered)
```

**Blast radius:** stage 2 only ever sees *manifested* candidates, so the four third-party vendor
`.asc` files under `references/` are unreachable unless someone manifests them. P1 is about the
**future** key. **No exporter change was made.**

## 4. P2 — non-forgeable release identity (scope + tests, NOT implemented)

**Two fail-closed cases, not one.**

**Case 1 — `source-sha: UNKNOWN`.** `SOURCE_SHA="$(... git rev-parse HEAD 2>/dev/null || echo
UNKNOWN)"` writes the literal `UNKNOWN` and continues. Required: **refuse**, non-zero, no
archive, message naming release identity as unresolvable. A signature over `UNKNOWN` is a *valid
signature on an unidentifiable release* — worse than none, because it looks authoritative.

**Case 2 — working-tree drift. This one is live right now.** The exporter copies from the
**working tree** (`cp -p "$ROOT/$path"`) but labels the archive with `git rev-parse HEAD`. A
modified-uncommitted manifested file therefore ships content that **does not correspond to the
stated `source-sha`**. This session has carried ` M ops/registry/EXPORTS.md` throughout; the current
7-entry manifest happens not to overlap it — **luck, not a guarantee**. Required: **refuse if any
candidate differs from HEAD.**

| Requirement | Test |
|---|---|
| Refuse on `git rev-parse` failure | Run `--root` at a non-git dir → non-zero, no archive, `UNKNOWN` never accepted |
| Refuse on drift | Modify a manifested file → refusal naming the drifted path; restore → exit 0, proving drift-sensitive not permanently broken |
| Signed release tag | Verification asserts `source-sha` == commit of a tag verifying against the release authority |
| Cross-check | `git verify-tag <tag>` → tag commit == manifest `source-sha`; either failing fails the release |

**Is commit signing necessary? NO — signed release tags are sufficient for D-11(b).** A signed
tag signs the commit SHA, which is a Merkle root over the whole tree, so signing the tag
transitively commits to exact tree content. Per-commit signing is a **development-process
attribution control**, not a release-identity control, and adopting it would imply something
retroactively about 504 existing unsigned commits. Recommend `tag.gpgsign` for release tags;
**do not** make `commit.gpgsign` a D-11 requirement. **No git signing config changed, no tag
created or signed.**

## 5. P3 — trusted public-key distribution (options + recommendation, NOTHING published)

**Constraint measured, not assumed: there is no git remote.** No remote-based distribution
option exists. The authoritative channel the project **does** control is the published site —
`scripts/deploy.sh` publishes `site/` to the web root at `/var/www/*****`, served at the
project's public site over HTTPS.

**Three measured mechanics of that channel:**
1. `PUBLISH` allow-list is `html css jpeg jpg js png svg ico webp woff2 txt xml` — **`asc` is NOT
   included.** A `release-key.asc` in `site/` is **silently skipped** ("skipped: not a web
   asset"). **`txt` IS allowed.**
2. Publication is **`-maxdepth 1`** → **`.well-known/` cannot work**; subdirectories never publish.
3. The orphan check is **source-presence-based, not link-based** (`deploy.sh:103`) → a published
   file no page links is **kept, not pruned**. **No linking page required.**

| Option | Mechanism | Tradeoffs |
|---|---|---|
| **P3-1** | `site/release-key.txt` — armored public key, `.txt` extension | **Works today, zero deploy change.** HTTPS, project-controlled, no remote. Extension cosmetically wrong for OpenPGP tooling; armored content is what matters |
| **P3-2** | Add `asc` to `PUBLISH`, publish `release-key.asc` | Correct extension/content-type. Requires a **deploy.sh change = own authorization**; widens the publish allow-list |
| **P3-3** | Public keyserver | Standard discovery, but hands an external service a trust-path role and cannot be retracted. Rejected as *primary* |
| **P3-4** | Out-of-band only — fingerprint in contract/onboarding, key with the archive | Strongest binding to a real business relationship; no public infrastructure. Doesn't scale, no public verification path |

**Recommendation: P3-1 for the key + P3-4 for the fingerprint.** Publish the armored **public**
key at `site/release-key.txt` (no deploy change), and restate the **40-hex primary fingerprint
through a second independent path** — contract/onboarding material delivered with the archive.
Rotation and revocation publish the same way, **primary fingerprint unchanged**, which is exactly
why H-2 was chosen.

**On the apparent circularity:** hosting the public key on the same box that may hold the signing
subkey looks self-certifying, and **C-2's offline primary is what makes it survivable.** A host
compromise lets an attacker replace the published file; it does **not** let them produce a subkey
certification chaining to a primary fingerprint the customer already holds out-of-band. The
second fingerprint path is therefore load-bearing, not belt-and-braces.

## 6. Ordered prerequisites before key generation

1. **P1** — exclusions + tests. **Must precede key generation**: until it lands, a private key at
   `ops/keys/release.asc` is exportable.
2. **P3 channel confirmed** — verification is impossible without a trusted out-of-band fingerprint.
3. **P2** — refuse `UNKNOWN` and refuse drift; adopt signed release tags.
4. **Key ceremony** (separately authorized) — primary offline, subkey, revocation cert, 40-hex
   fingerprint recorded, expiry, custody media. Report only *that* it succeeded plus fingerprint,
   location class, ownership, mode — **never** key material.
5. **Custody documentation** — permitted/forbidden locations, backup/recovery, rotation,
   revocation, who may sign.
6. **Signing step** — separate signer *after* the exporter, never inside it; exporter must stay
   runnable with no key, refusal paths independent of signing. Fail-closed: no signature, no release.
7. **Custody-record schema** — does not exist.
8. **Recipient verification procedure** — commands, expected output, failure meaning, plus the
   independent `EXPORTS.md` acceptance grep.
9. **`EXPORTS.md` signing rule** — note its pre-existing unstaged modification resolves on its own
   authorization first.
10. **Feeds, only on moving to (a)** — re-index 6 cells, clearsigned `InRelease` each, keyring published.

## 7. What remains before external release can EVER be authorized

1. **Explicit external-release authorization** — the ruling settles *how* to sign, not *whether* to ship.
2. **Implementation authorization** for P1/P2/P3 and items 4–10; none authorized.
3. **Key ceremony authorization.**
4. **Per-archive production authorization**, naming recipient and scope manifest.
5. **Export-scope re-confirmation** — 7 entries were authorized for A-4; what a customer receives
   is a fresh decision.
6. **Licence/provenance terms** for the custody record — legal/business input.
7. **Recipient verification path in place** — otherwise the signature is decorative.
8. **D-12 — separate hardening, NOT required before release.** Guards against a future
   contributor manifesting shared-platform source; today the manifest is 7 reviewed entries.
   Revisit before *routine* customer exports.

## Still open from earlier

- **External release: NOT authorized.** Unchanged.
- **D-12: unimplemented, separate.** Unchanged.
- **`ops/registry/EXPORTS.md`** remains modified-and-unstaged from an earlier authorization; must
  never be swept into a commit. Verified unstaged at this commit.
- **F-1/F-2/F-3** from the prior handoff are now recorded in §22 as P1/P2 work items. F-2 (my own
  depth-capped `/yocto` mis-measurement, corrected to 48 indexes) is folded into the §18 evidence.
- `LIVE_STACK_ENTRY` not entitlement-aware; `WORKFLOW_SLOT` not exercised end-to-end; zero model
  payloads (valid baseline).

## Verification — measured

```
HEAD                       5063b480
git status --short          M ops/registry/EXPORTS.md   (pre-existing, untouched, never staged)
staged at commit           Sept1.md only            policy doc staged: 0
backend/ tools/ control/ site/ ops/ run/            0 changes each
secret keys on box         0        public keys       0
signing infrastructure     none     artifacts signed  0
tags created/signed        0        published files   0
custody records            none     archives          0
A-4 indicator states       unchanged (AUTHORIZED (A-4 only) byte-identical in diff)
A-4                        COMPLETE, 19 of 19
```

## To resume

```
repo   /home/google/Symoneural
HEAD   5063b480   [D-11] record owner ruling as controlling signing architecture
prev   2def42b9   [A-4] reconcile stale pre-A-series claims
git status --short:
 M ops/registry/EXPORTS.md
```

Next authorization would be **P1** (exporter signing-material exclusions + tests) — it must land
before any key is generated. P3 channel confirmation and P2 follow. The key ceremony is separately
authorized and comes after all three.

# D-11 DECIDED — PRE-KEY PREREQUISITES READY
