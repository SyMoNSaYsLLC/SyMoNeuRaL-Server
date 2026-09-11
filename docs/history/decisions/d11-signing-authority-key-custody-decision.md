# D-11 — Signing authority and key custody: decision analysis

> **REDACTED.** Customer names, credential filenames, security/lockdown tooling names,
> internal ports and infrastructure-posture details are masked with `*****` or referred to by
> role. Meaning is preserved. Unredacted detail is on the box.

**Date:** 2026-09-02 · **HEAD:** `2def42b9` · **Repo:** `/home/google/Symoneural`
**Nature:** read-only decision analysis. **No implementation. No keys generated. No commit.**
**External release remains NOT authorized.**

## Continues from

Previous handoff: `a4-complete-shared-service-map-reconciliation.md` (2026-09-02), ended at
HEAD `2def42b9` with **A-4 COMPLETE, 19 of 19**. A-4 is not reopened or extended by this pass.

| Control point | At `2def42b9` (prev) | Now |
|---|---|---|
| HEAD | `2def42b9` | `2def42b9` — **unchanged, no commit** |
| Tracked mods | `docs/ops/EXPORTS.md` only | `docs/ops/EXPORTS.md` only, untouched |
| A-4 | COMPLETE, 19/19 | **COMPLETE, 19/19 — unchanged** |
| Keys on box | 0 | **0 — none generated** |
| Signed artifacts | 0 | **0 — none signed** |
| Archives | 0 | **0** |

---

## 1. Signing-object inventory

What would require identity/signature protection, and what actually binds each.

| # | Release object | Needs cryptographic signature? | SHA-256 alone sufficient? | What binds it to release identity |
|---|---|---|---|---|
| 1 | **Source/release commit identity** | **YES** | **No** | A **signed release tag** over the commit. Today `source-sha` is an *assertion by an unsigned tool about an unsigned commit* — see finding F-3 |
| 2 | **Individual exported files** | **No** | **Yes** | Already bound: per-file SHA-256 in `EXPORT-MANIFEST`, emitted by the exporter |
| 3 | **Export manifest** | **Indirectly — yes** | No | It is the root of the file-integrity chain, so it must be signed. Because it ships *inside* the archive, a detached signature over the archive covers it |
| 4 | **Archive/package artifact** | **YES — this is the load-bearing signature** | No | One **detached signature over the archive**. Signing this one object transitively covers 2 and 3 |
| 5 | **Checksums** | No, if inside the signed archive | Yes | Contained in `EXPORT-MANIFEST`; covered by object 4 |
| 6 | **Package/feed metadata** (DEB/IPK) | **YES, separately** | No | `Release` → `InRelease` clearsigned; the mechanism already exists in `scripts/build-apt-repo.sh --sign`. **Measured: 48 index files across 6 arch/format cells, 9 `Release` files, 0 signatures** |
| 7 | **Custody/provenance record** | **YES** | No | A signed release record naming signer, key ID, UTC time, source SHA, archive SHA-256, licence/provenance. **Does not exist today** |

**Minimum viable signature count: 2** — one detached signature over the customer archive
(covers 1–5 once the tag exists), one clearsigned `InRelease` per feed (object 6). Plus a
signed custody record (object 7), which can be the same signed release record.

**No artifact was created.** Nothing above exists.

---

## 2. Signing-authority options

| Option | Model | Tradeoffs |
|---|---|---|
| **A-1** | **One offline release authority** — a single keypair, private half off-box, signs everything | Smallest to operate; one key to protect. Compromise means re-keying *everything* including the feed trust root. No separation between "this is our release" and "this is our custody attestation" |
| **A-2** | **Separate release and custody authorities** — one signs artifacts, another signs the custody/provenance record | Compromise of the artifact key does not let an attacker forge provenance. Two keys, two custody procedures for a one-operator shop; the second key's marginal value is low while the same person holds both |
| **A-3** | **Operator key** — signs as the individual operator | Zero ceremony; already the de-facto identity (504 commits under one identity, `.mailmap` maps 4 addresses). But it binds *company* releases to a *person*; recipients must re-trust on personnel change, and it mixes personal and organizational trust |
| **A-4** | **Organization-level signing key** — `SymonSays LLC` release key, operator holds custody | Correct trust semantics: recipients trust the org, not an individual. Survives personnel change. Requires a real custody procedure, since it is now a company asset |
| **A-5** | **Delegated per-release key** signed by a root | Best compromise containment. Substantial ceremony: a root authority, a delegation record, and per-release key generation, for a shop currently producing zero external releases |

**Recommendation: A-4** — one organization-level release authority, operator-held custody.

Rationale, and explicitly *not* "because tooling exists": the trust semantics have to match who
is actually shipping. A customer receiving an archive is trusting **SymonSays LLC**, not a
named individual, so A-3 encodes the wrong relationship and creates a re-trust event on any
personnel change. A-2 and A-5 buy compromise containment that has no one to contain — the same
single operator holds every key, so key separation is procedural theatre until there are
distinct humans or machines. A-4 is the smallest model with correct semantics.

**Precedent for the custody *posture*, in-repo and already tested:** `gateway/entitlement.py`
implements operator-mints-offline / server-verifies-with-public-key-only, and
`test_settlement.py` asserts the serving path can reach no private key. That is exactly the
asymmetry D-11 needs. **Reuse the posture, never the key** — the entitlement authority ("this
licence was paid for") and the release authority ("this artifact is ours, unmodified") are
distinct authorities and must remain distinct keys.

---

## 3. Key-hierarchy options

| Option | Hierarchy | Verdict |
|---|---|---|
| **H-1** | **Single long-lived release key**, no root | Smallest. Rotation = publish a new key and re-trust; no cryptographic continuity across rotation |
| **H-2** | **Offline primary + release-signing subkey** (native to OpenPGP) | **Recommended.** Primary certifies, never signs artifacts, stays offline; a signing subkey does the work. Subkey rotation/revocation happens *under the same primary*, so recipient trust survives rotation. No extra tooling — this is stock OpenPGP |
| **H-3** | Per-release keys under a root | Rejected for now: ceremony without a threat model at zero releases |

**Recommended: H-2.**

| Property | Decision |
|---|---|
| Root/offline authority | Yes — OpenPGP **primary key, certify-only**, offline custody |
| Release-signing key | A **signing subkey** of that primary |
| Long-lived vs per-release | **Long-lived subkey**; rotate on schedule or on compromise, not per release |
| Key identifiers | Full **40-hex fingerprint** is the identifier of record. Short/long key IDs are collidable and must not appear alone in any policy or verification instruction |
| Rotation | Rotate the **subkey**; primary unchanged, so recipient trust is not re-established. Record each subkey fingerprint and its validity window in the release record |
| Revocation | Generate the **revocation certificate at creation time** and store it separately from the key — a revocation you cannot issue after losing the key is not a revocation. Distribute revocation by the same channel as the public key |
| Expiration | Finite expiry on the subkey (e.g. 1–2 years); primary expiry longer or none with a stored revocation cert. Expiry is a dead-man's switch, not a formality |
| Separation from runtime secrets | **Absolute.** No serving process ever holds signing material. Signing happens off the serving host, matching the `entitlement.py` asymmetry |

**Mandatory statement (§3):** the **shared-accounts session secret is entirely unrelated to
release signing and must NEVER be reused as, or derived into, signing material.** Different
purpose (session authentication vs artifact provenance), different lifetime (rotatable at will
vs long-lived recipient trust), different blast radius. It lives in the runtime environment
file on the serving host — precisely where signing material must never be. Its value was not
read for this analysis and must not be.

**No keys were generated.**

---

## 4. Key-custody options

| Option | Private key location | Assessment |
|---|---|---|
| **C-1** | Host-held in operator home under `.gnupg/` | Lowest friction, weakest posture: the signing key sits on the same box as the serving process. A host compromise becomes a release-forgery compromise |
| **C-2** | **Host-held for the subkey; primary offline on removable media** | **Recommended.** Routine signing works without ceremony; the certifying authority — the thing that makes rotation survivable — is not on the box |
| **C-3** | Fully offline / removable for all material | Strongest. Every signature needs the media present; realistic at low release volume, and worth revisiting if release cadence stays near zero |
| **C-4** | Hardware token | Best key-extraction resistance. **No token evidence on this host** → new hardware, out of scope |

**Custody boundary — permitted and forbidden**

*May hold private key material:* removable/offline media for the primary; a mode-`0700`
operator-owned directory for the signing subkey under C-2; an encrypted offline backup.

*Must NEVER hold private key material:* the git repository (any branch, any history); any
export archive; the runtime environment file or any systemd unit/drop-in; any serving-process
working directory; any directory a service account can read; any cloud-synced or off-box
location; shell history; commit messages; documentation; this handoff.

*Filesystem requirements if host-held:* directory `0700`, private key file `0600`, owned by the
operator account, **not** the service account; never group- or world-readable; not inside the
repository tree; excluded from any backup that leaves the box unless separately encrypted.

*Repository may contain public verification material:* **yes** — the public key / keyring
`.asc` and the fingerprint of record are *meant* to be published, and a recipient needs them to
verify. Precedent: `build-apt-repo.sh` already does `gpg --armor --export` to a keyring `.asc`.

*Private signing material in the repository:* **never, under any circumstance.** There is no
exception, including "temporarily", "encrypted", or "in a branch that won't be pushed" — note
there is **no git remote at all**, and that is a protection, not a gap.

### F-1 (finding) — the exporter's protected patterns do NOT cover signing material

Measured by matching hypothetical paths against the **live 17 patterns** parsed out of
`tools/data/export_snapshot.sh`:

```
BLOCKED  ops/keys/release.pem                by \.(pem|key|p12|pfx)$
BLOCKED  ops/keys/release.key                by \.(pem|key|p12|pfx)$
BLOCKED  ops/keys/id_ed25519                 by (^|/)id_(rsa|ed25519|ecdsa)$
BLOCKED  ops/keys/backup.p12                 by \.(pem|key|p12|pfx)$
BLOCKED  secrets/release.asc                 by (^|/)secrets?/
BLOCKED  run/release.asc                     by (^|/)run/
BLOCKED  .gnupg/private-keys-v1.d/1234.key   by \.(pem|key|p12|pfx)$

PASSES   ops/keys/release.asc                <-- NOT COVERED
PASSES   .gnupg/pubring.kbx                  <-- NOT COVERED
PASSES   ops/release.gpg                     <-- NOT COVERED
PASSES   ops/release.minisig                 <-- NOT COVERED
PASSES   ops/signing/release_ed25519         <-- NOT COVERED
PASSES   ops/signing/release_ed25519.pub     <-- NOT COVERED
```

An **ascii-armored GPG secret key** (`.asc` — the default output of `gpg --export-secret-keys
--armor`), a **`.gnupg/` keyring**, and a **bare Ed25519 private key named without an
extension** all pass stage 2 today. The patterns catch `.pem`/`.key`/`.p12`/`.pfx` and
`id_ed25519` exactly, and miss the formats GPG actually produces.

This is harmless *only* because zero keys exist. It becomes live the moment one is generated.
**Extending stage-2 patterns is therefore a prerequisite that must land BEFORE any key is
generated, not after.** Listed in §9; **no exporter change was made.**

---

## 5. Available signing mechanisms — measured on this host

| Mechanism | Present? | Path | Signs archive? | Signs DEB/IPK feed? | New dependency? |
|---|---|---|---|---|---|
| **GPG / OpenPGP** | **YES** — GnuPG **2.4.7**, libgcrypt 1.11.0 | `/usr/bin/gpg`, `gpgconf`, `gpg-agent` | Yes (detached `.asc`) | **Yes** (clearsign → `InRelease`) | **No** |
| **Sequoia `sq`** | **YES** | `/usr/bin/sq` | Yes | Indirectly | No |
| **`ssh-keygen -Y`** | **YES** (`-Y sign` accepted) | `/usr/bin/ssh-keygen` | Yes | **No apt interop** | No |
| **OpenSSL** | **YES** — 3.5.7 | `/usr/bin/openssl` | Raw sigs only; no release format | No | No |
| **`apt-ftparchive`** | **YES** | `/usr/bin/apt-ftparchive` | n/a | Generates the `Release` that gets signed | No |
| **In-repo Ed25519 signer** | **YES** — `gateway/entitlement.py` (`cryptography` lib) | — | Purpose-built for licence tokens, **not** artifacts | No | No |
| **`rpmsign`** | YES | `/usr/bin/rpmsign` | n/a | **Irrelevant** — targets are DEB/IPK | No |
| minisign · signify · cosign · age · dpkg-sig · debsigs · reprepro · aptly | **ABSENT** | — | — | — | **Yes → excluded** ("do not install anything") |

**Existing project precedent:** `scripts/build-apt-repo.sh --sign` already implements
`gpg --clearsign` → `InRelease`, plus `gpg --armor --export` → `symoneural-archive-keyring.asc`,
**and refuses rather than silently falling back to unsigned** (lines 102–112) — the same
fail-closed posture as the A-2 exporter. It has never been applied to the Yocto tree.

**Measured current signing state:** 0 secret keys · 0 public keys · no `user.signingkey` ·
no `commit.gpgsign` · **0 signed commits** in the last 200 · 6 tags, **0 signed** ·
**0 signatures across 76,208 `/yocto/artifacts` packages** and 9 `Release` files.

**The mechanism decision turns on one question:** *must one authority cover both the customer
archive and the DEB/IPK feeds?*

- **If yes → OpenPGP is the only mechanism present that does both.** Everything else that
  could sign a feed is absent and would be a new dependency.
- **If no** (archive signing only, feeds deferred) → `ssh-keygen -Y` has genuinely simpler
  custody, but you would then own two mechanisms the moment feeds need signing.

Given 48 feed indexes already built across 6 arch/format cells, feeds are a real near-term
target, so the answer is **yes**, and **OpenPGP is the smallest mechanism compatible with the
required custody model.**

---

## 6. Verification-chain design

**Topology follows from a measured fact:** `EXPORT-MANIFEST` is written *inside* the archive
(exporter line ~186, staged then zipped). So a single detached signature over the archive
transitively covers the manifest and, through it, every file.

```
  TRUSTED PUBLIC KEY  (org release primary, 40-hex fingerprint, out-of-band)
          |
          |  certifies
          v
  RELEASE SIGNING SUBKEY  (fingerprint recorded in the release record)
          |
          |  detached signature  release.zip.asc
          v
  ARCHIVE  release.zip            <-- archive integrity
          |
          |  contains
          v
  EXPORT-MANIFEST                 <-- manifest integrity (covered by the sig above)
      source-sha:  <commit>       --> release identity, verifiable against a SIGNED TAG
      file-count:  <n>
      sha256  path                --> per-file integrity
          |
          v
  EXPORTED FILES                  <-- file integrity
```

| What the recipient verifies | How |
|---|---|
| **Signer identity** | `gpg --verify release.zip.asc release.zip` → subkey fingerprint chains to the trusted primary fingerprint, obtained out-of-band |
| **Archive integrity** | Same command; the detached signature is over the archive bytes |
| **Manifest integrity** | Transitive — the manifest is inside the signed archive |
| **File integrity** | Recompute `sha256sum` per `EXPORT-MANIFEST`; every path must match, and the file set must be exactly `file-count` |
| **Release identity** | `source-sha` in the manifest must equal the commit of a **signed release tag** verified against the same authority. Without the signed tag this step is an unverified assertion — **F-3** |
| **Custody / provenance** | Signed release record: signer, key fingerprint, UTC timestamp, source SHA, archive SHA-256, licence/provenance, scope manifest name |
| **Feed metadata** (if delivered) | `InRelease` clearsigned; recipient installs the keyring `.asc` to `/etc/apt/trusted.gpg.d/` |

An operator adds: the archive must have been produced by the sanctioned exporter, and the
independent acceptance grep from `EXPORTS.md` must report `safe export`.

**No external publication is authorized.** The out-of-band public-key distribution channel is
itself an unresolved decision — see §10.

### F-3 (finding) — `source-sha: UNKNOWN` is a signable state today

Exporter: `SOURCE_SHA="$(cd "$ROOT" && git rev-parse HEAD 2>/dev/null || echo UNKNOWN)"`.
On any failure it writes the literal `UNKNOWN` and continues. Signing an archive whose release
identity is `UNKNOWN` produces a **verifiable signature over an unidentifiable release** — the
signature is valid and the chain to §1 object 1 is broken. Combined with **0 signed commits and
0 signed tags**, release identity currently has *no* cryptographic binding at all. Prerequisite
in §9. **No exporter change was made.**

---

## 7. D-11 options and tradeoffs

| | **D-11(a)** Full authority now | **D-11(b)** Sign only externally distributed artifacts | **D-11(c)** Defer | **D-11(d)** *current* — assert identity, don't sign |
|---|---|---|---|---|
| **Authority** | Org primary + subkey, both scopes | Org primary + subkey, archive first; feeds when they ship | none | none |
| **Custody** | C-2 (offline primary, host subkey) | C-2 | n/a | n/a |
| **Hierarchy** | H-2 | H-2 | none | none |
| **Mechanism** | OpenPGP (present) | OpenPGP (present) | none | SHA-256 only |
| **Objects signed** | archive · release tag · custody record · every feed `InRelease` | archive · release tag · custody record; feeds when distributed | none | none |
| **Verification** | full chain incl. feeds | full chain for archive; feeds unverifiable until signed | none | integrity only vs a manifest of unproven origin |
| **Operational burden** | Highest: key ceremony + re-index and re-sign 6 feed cells / 76,208 pkgs | **Moderate**: one key ceremony, one signing step per release | zero | zero |
| **Compromise / rotation** | Subkey rotation under primary; feed re-sign required | Subkey rotation under primary; smaller surface | n/a | n/a |
| **Blocks external release?** | No | No | **Yes, permanently** | **Yes** |

**Recommendation: D-11(b), architected as H-2/C-2 so that (a) is a later configuration change
rather than a re-keying event.**

Why (b) over (a): the deliverable actually in front of us is one customer archive, not a public
package feed. (a) additionally requires re-indexing and signing 6 arch/format cells and 76,208
packages — real work that gates nothing today, and none of it is required to hand a customer a
verifiable archive. Why not (c): untenable before any external distribution; it is the status
quo wearing a decision's clothes. Why not staying at (d): unsigned means a recipient can verify
the archive is *internally consistent* but cannot verify it came from us — the manifest and the
checksums are asserted by the same unsigned tool that built the archive, so an attacker who
substitutes both is undetectable.

This matches, and now supplies evidence for, the §18 register's earlier `(b)` recommendation.

---

## 8. Recommendation — consolidated

| Dimension | Decision |
|---|---|
| Authority | **A-4** — one organization-level release authority, operator-held custody |
| Hierarchy | **H-2** — offline certify-only primary + long-lived signing subkey; revocation cert at creation; finite subkey expiry; 40-hex fingerprint as identifier of record |
| Custody | **C-2** — primary offline/removable; subkey host-held `0700`/`0600`, operator-owned, never service-readable, never in the repo |
| Mechanism | **OpenPGP / GnuPG 2.4.7** — present, no new dependency, only present mechanism covering both archive and DEB/IPK feeds; reuses the `build-apt-repo.sh --sign` precedent |
| Objects signed | Detached sig over the archive · signed release tag · signed custody/provenance record. Feed `InRelease` when feeds are distributed |
| Verification | Trusted primary fingerprint → subkey → detached sig → archive → `EXPORT-MANIFEST` → per-file SHA-256 → files; `source-sha` cross-checked against the signed tag |
| Scope | **D-11(b)** now, structured so **(a)** is later configuration, not re-keying |

Explicitly **not** recommended: reusing the entitlement Ed25519 key; reusing the shared-accounts
session secret in any form; a personal operator key as the release authority; any absent
mechanism.

**Not implemented.** This is analysis for owner decision only.

---

## 9. Implementation prerequisites — IF this recommendation were later authorized

Ordered. Items 1–3 must land **before** any key exists.

1. **Extend exporter stage-2 protected patterns to cover signing material** (F-1) — at minimum
   `\.asc$`, `\.gpg$`, `\.kbx$`, `(^|/)\.gnupg/`, `(^|/)private-keys-v1\.d/`, `\.minisig$`,
   `(^|/)ops/(keys|signing)/`, and bare `*_ed25519`-style names. Requires an authorized
   exporter change plus a sabotage test per pattern. **Must precede key generation** — until it
   lands, a private key placed at `ops/keys/release.asc` is exportable.
2. **Decide the public-key distribution channel** (§10) — verification is impossible without a
   trusted out-of-band fingerprint path, and there is **no git remote**.
3. **Make release identity non-forgeable**: exporter must **refuse** rather than emit
   `source-sha: UNKNOWN` (F-3); adopt signed release tags (`user.signingkey` + `tag.gpgsign`,
   `gpg.format` = `openpgp`); decide whether commit signing is also required.
4. **Key ceremony, explicitly authorized and separate**: generate primary offline, generate
   subkey, generate revocation certificate, record the 40-hex fingerprint, set expiry,
   provision custody media. Report only *that* it succeeded plus fingerprint, location class,
   ownership and mode — **never** key material.
5. **Custody documentation**: where material lives, permitted/forbidden locations, backup and
   recovery, rotation and revocation procedure, and who may sign.
6. **Signing step**: a separate signer invoked *after* the exporter, never inside it — the
   exporter must remain able to run with no key present, and its refusal paths must not depend
   on signing. Fail-closed: no signature, no release.
7. **Custody-record format** (§1 object 7) — the schema does not exist.
8. **Verification procedure for recipients**: exact commands, expected output, and what a
   failure means, plus the independent `EXPORTS.md` acceptance grep.
9. **`EXPORTS.md` policy update** adding the signing requirement as a rule. Note its
   pre-existing unstaged modification must be resolved on its own authorization first.
10. **Test coverage**: signature verifies; **tampered archive fails**; expired subkey fails;
    wrong key fails; `UNKNOWN` source-sha refused; each new protected pattern refuses.
11. **Feeds only if moving to (a)**: `apt-ftparchive` re-index of the 6 cells and clearsigned
    `InRelease` per cell, keyring `.asc` published.

---

## 10. Remaining release gates AFTER D-11 is decided

Resolving D-11 **does not** authorize external release. Still required:

1. **Explicit external-release authorization** — a separate owner decision. D-11 settles *how*
   to sign, not *whether* to ship.
2. **Implementation authorization** for each §9 item; none is authorized now.
3. **Key ceremony authorization** — separate from the architectural decision.
4. **Public-key distribution channel decision** — unresolved, and no remote exists.
5. **Per-archive production authorization**, naming the recipient and the scope manifest.
6. **Export-scope re-confirmation** at production time: the 7-entry manifest was authorized for
   A-4; whether that exact scope is what a customer receives is a fresh decision.
7. **Licence/provenance terms** for the custody record — a legal/business input, not technical.
8. **D-12 — separate hardening, NOT required before release.** It guards against a *future
   contributor* adding shared-platform source to a manifest. Today the manifest is 7 reviewed
   entries. Recommendation stands: not before ownership is machine-readable. It should be
   revisited before *routine* customer exports.
9. **Recipient verification path** must exist before shipping, or the signature is decorative.

**No A-4 state changes as a result of this analysis.** A-4 remains **COMPLETE, 19 of 19**.
`RELEASE_IDENTITY` and `CUSTODY_RECORD` remain `AUTHORIZED (A-4 only)` under D-11 = (d); that
scope limit is unaffected by analyzing what (a)/(b) would require. **D-11 remains OPEN until
the owner decides.**

**What D-11 blocks today:** all external distribution of any artifact — customer archives,
packages, feeds, SDKs. Nothing internal. A-4 completed with it open, by explicit ruling.

---

## Findings summary

| ID | Finding |
|---|---|
| **F-1** | Exporter's 17 protected patterns **do not** cover `.asc`, `.gpg`, `.kbx`, `.gnupg/`, `private-keys-v1.d/`, `.minisig`, or extensionless private keys. Empirically tested against the live patterns. Harmless only because 0 keys exist. **Must be fixed before key generation.** |
| **F-2** | **Corrects my own earlier measurement this session.** I reported 0 `/yocto` feed indexes using `find -maxdepth 4`. Re-measured without the cap: **48** index files + 9 `Release` files across 6 arch/format cells. This **confirms** `Sept1.md:1246`. Signature count **0** holds either way. Same error class as the modelops glob that missed one directory down. |
| **F-3** | Exporter emits `source-sha: UNKNOWN` on `git rev-parse` failure and continues. With 0 signed commits and 0 signed tags, release identity has no cryptographic binding today. |
| **F-4** | `gateway/entitlement.py` already implements the operator-mints / server-verifies-public-key-only asymmetry, asserted by `test_settlement.py`. Reuse the **posture**; the keys must stay distinct authorities. |
| **F-5** | `scripts/build-apt-repo.sh --sign` already implements clearsign → `InRelease` + public keyring export, and **refuses rather than silently going unsigned**. Never applied to the Yocto tree. |
| **F-6** | **No git remote.** History cannot leave the box via git. Rules out CI/cloud signers in the trust path and makes public-key distribution an open question. |

## Preserved state — verified, nothing modified

```
HEAD                      2def42b9  (unchanged, no commit)
git status --short         M docs/ops/EXPORTS.md   (pre-existing, untouched)
keys generated            0        signing infrastructure created  none
artifacts signed          0        custody records altered         none
archives produced         0        exporter / manifest changed     no
A-4 runtime state         unchanged     customer account            unchanged
correspondence            unchanged     entitlement                 unchanged
shared-account enablement unchanged     runtime secrets             not read, not rotated
systemd / services        unchanged     D-12                        untouched
```

Session-secret value was never read. No key material appears in this document.

## To resume

```
repo   /home/google/Symoneural
HEAD   2def42b9
git status --short:
 M docs/ops/EXPORTS.md
```

Awaiting owner decision on D-11: authority **A-4**, hierarchy **H-2**, custody **C-2**,
mechanism **OpenPGP**, scope **D-11(b)**.

Not offered and not done: the §18 D-11 register entry in `Sept1.md` was **not** updated,
because no commit is authorized and an uncommitted edit would break the clean-tree invariant.
That update is available as a follow-on authorization.

# D-11 READY FOR OWNER DECISION
