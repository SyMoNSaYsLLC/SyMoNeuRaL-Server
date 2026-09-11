# D-11 CREDENTIAL CUSTODY DECIDED — offline physical recovery records

> **REDACTED.** Service names, credential filenames, internal ports, hostnames and web-root
> paths are masked or referred to by role. **No credential, passphrase, or key material appears
> here — none exists.** Unredacted detail is on the box in `Sept1.md` §22.3e.

**Date:** 2026-09-02 · **HEAD:** `98326529` · **Previous HEAD:** `66af2891`
**Repo:** `/home/google/Symoneural` · **Nature:** policy recording only. **Nothing generated.**

## Continues from

Previous handoff: `d11-offline-custody-decisions-complete.md` (2026-09-02), HEAD `66af2891`,
which adopted the three-media topology and E-2 LUKS and left **one** decision open: where the
three credentials are held. This window closes it.

| Control point | At `66af2891` (prev) | Now at `98326529` |
|---|---|---|
| Credential custody | **OPEN** | **DECIDED — offline physical recovery records** |
| Open D-11 offline-custody decisions | 1 | **0** |
| Media provisioning | BLOCKED (0 media) | **BLOCKED (0 media)** — unchanged |
| Credentials generated | 0 | **0** |
| D-11 release authority | NOT ESTABLISHED | **NOT ESTABLISHED** |
| Tracked mods | `ops/registry/EXPORTS.md` | `ops/registry/EXPORTS.md` — untouched |

## The ruling

**Mechanism: OFFLINE PHYSICAL RECOVERY RECORDS.** Each LUKS credential is recorded on a separate
offline physical recovery record under operator custody, held **apart from the medium it
unlocks**.

| Medium | Credential | Recovery record |
|---|---|---|
| **A** `D11-PRIMARY-A` | credential A | **record A — stored separately from Medium A** |
| **B** `D11-PRIMARY-B` | credential B | **record B — stored separately from Medium B** |
| **C** `D11-REVOCATION-C` | credential C | **record C — stored separately from Medium C** |

**Recovery-record count: ONE per credential**, initially.

| Question | Answer |
|---|---|
| Electronic credential store controlling? | **NO** |
| Password manager controlling? | **NO** — optional convenience later, never the authority or a sole recovery path |
| Manual unlock required? | **YES** |
| Automatic/unattended unlock permitted? | **NO** |
| Command-line credential exposure permitted? | **NO** |
| Shell-history credential exposure permitted? | **NO** |
| Host keyfile permitted? | **NO** |

Excluded as controlling custody: repository · host filesystem · home directory · customer
archive · application/service configuration · cloud storage · email · chat and handoff documents
· browser storage · shell history · environment variables · plaintext notes · password-manager
account · network share.

## Physical-separation invariant

> **A credential record must not share the same immediate physical custody location as the medium
> it unlocks.**

Separation is **NOT** established by: different **folders**; different **envelopes inside the
same unlocked container**; a **digital copy on another partition**. Two items in one drawer are
one custody location, whatever the packaging.

**Purpose:** loss or theft of any single custody item must not yield **both** the encrypted
medium **and** its credential.

## Recovery-record form

Opaque/sealed · **human-readable** (transcribable by hand, no tooling) · identified by **ROLE
ONLY** · no private-key material · tamper-evident where practical.

**Deliberately excluded from the record:** system details, repository paths, hostnames,
usernames, infrastructure information, UUIDs, unlock commands. The record exists to recover one
LUKS credential, not to document the system — **a record that also describes the system turns a
single theft into reconnaissance.**

## Credential-generation requirements (nothing generated)

Unique · **CSPRNG-generated** · not human-derived · not based on company names or user passwords
· not reused · **not derived from** signing-key passphrases, runtime/session/entitlement secrets,
or another media credential.

**Entropy/length target: ≥ 128 bits**, in a transcription-safe encoding — a random string over an
unambiguous alphabet, grouped for hand-copying (e.g. base32-style at 5 bits/character, so 26+
characters clears the target). **No example value recorded, here or in the repository.**

*Why 128 bits:* the credential protects data at rest against an attacker who may hold the medium
indefinitely, so it must resist offline brute force on its own merits rather than relying on rate
limiting. LUKS applies a KDF on top, which raises cost but is **not** a substitute for input
entropy.

**Generation source already available — no new dependency:** `/dev/urandom`, `getrandom(2)`, and
`openssl rand` are all present.

## No circular dependency — verified

Recovery requires **only the separate physical record**, never the medium itself.

**Explicitly rejected:** credential stored **inside the LUKS container it unlocks** · credential
stored **only on the associated device** · derivation requiring material held **inside the same
encrypted volume**.

"Store the passphrase on the drive" is named explicitly because it reads as convenient and is
**equivalent to no encryption**.

## Failure-domain analysis

| Loss event | Consequence |
|---|---|
| **Medium A only** | Authority **intact** — B is a complete independent copy; re-provision A from B |
| **Record A only** | Medium A permanently unopenable; authority **intact** via B; re-provision A with a fresh credential and record |
| **Medium A + record A** | Copy A lost entirely; authority **intact** via B. **This is what the two-copy topology is for** |
| **Medium B only** | Authority intact via A |
| **Record B only** | Medium B unopenable; authority intact via A |
| **Medium B + record B** | Copy B lost entirely; authority intact via A |
| **Medium C only** | Revocation *certificate copy* lost; ability to revoke survives if the primary authority is still recoverable |
| **Record C only** | Medium C unopenable; same position — replace from the primary while it remains recoverable |
| **Medium C + record C** | **That revocation copy is destroyed.** Recoverable only while the primary authority is still recoverable. **If the primary is already lost, the ability to revoke is gone** |

**A and B provide authority redundancy.** **Medium C is different** — the compound case *(primary
lost **and** C lost)* is the one with no recovery path, so **record C receives the strongest
physical custody of the three.**

**No additional secret copies were invented** to eliminate every conceivable loss scenario. Each
extra copy is another secret-bearing object and another place to be stolen from.

### Option C-2 — presented, not adopted

> A **second recovery record for credential C only**, held in a **third distinct physical
> location**. Rationale: C is the single failure domain whose compound loss has no recovery path,
> so it is the one credential where a second record buys something the topology doesn't already
> provide. Cost: one more secret-bearing object. A duplicate in the *same* location adds exposure
> and no resilience. **Returned for owner ruling if desired.**

## Relationship to OpenPGP passphrases — kept separate

| Class | Status |
|---|---|
| **LUKS media credentials** | **decided here** |
| **OpenPGP secret-key passphrase(s)** | **NOT decided here** — remains part of the future ceremony/custody procedure |

They must **not** be identical, **not** be derived from one another, and **not** be recorded as
one combined secret. A combined secret would collapse media encryption and key protection into a
single failure domain — exactly what the §22.3d layering rejects.

## Operational unlock sequence (conceptual)

```
1. authorized custody operation begins
2. retrieve the required physical medium
3. retrieve its SEPARATELY held credential record
4. unlock LUKS INTERACTIVELY
5. perform the authorized custody operation
6. unmount and close the LUKS mapping
7. return medium and record to SEPARATE custody
```

No script embeds or auto-retrieves the credential. No unattended unlocking. **No host keyfile** —
that would place the credential on the very machine whose services this architecture exists to
exclude.

## Shell-history requirement (for later provisioning)

Credentials must never appear in **command-line arguments · shell history · process listings ·
environment variables · logs · repository files.** Use **`cryptsetup`'s interactive secret-input
path**.

A credential passed as an argument is visible in `/proc` process listings to any local user for
the process lifetime **and** is persisted by shell history — two exposures that no later file
permission repairs. **This is a requirement on the later implementation, not an action taken
now.**

## §13 return

| Item | Value |
|---|---|
| HEAD | `98326529` |
| Previous HEAD | `66af2891` |
| Commit subject | `[D-11] Sept1.md: credential custody decided - offline physical recovery records` |
| Files changed | **`Sept1.md` only** — `+197`, pure insertion (new §22.3e) |
| `git status --short` | ` M ops/registry/EXPORTS.md` |
| `git diff --cached --name-only` | `Sept1.md` (at commit); EXPORTS.md staged **0** |

**Confirmations:** `ops/registry/EXPORTS.md` **untouched and unstaged** · **no credentials
generated** · no packages installed · no media modified · **no LUKS container created** · no
custody account created · no custody directory created · no GnuPG material created · no key
generated · no fingerprint created · no revocation certificate created · no public key published
· no tag signed · no artifact signed · no archive created · **external release remains NOT
AUTHORIZED**.

**Exporter suite:** 43 passed (7 A-2 + 15 P1 + 21 P2). **Staged-diff scan:** 0 private-key
blocks, 0 credential examples, 0 secret-shaped strings.

## Current state

```
P1                        COMPLETE
P2                        COMPLETE
P3                        CHANNEL CONFIRMED (key not published)
D-11 CUSTODY PRINCIPAL    DECIDED
D-11 CUSTODY TOPOLOGY     DECIDED - three physically independent media
D-11 ENCRYPTION AT REST   DECIDED - E-2 LUKS
D-11 CREDENTIAL CUSTODY   DECIDED - offline physical recovery records
D-11 MEDIA PROVISIONING   BLOCKED - 0 physical media present
D-11 RELEASE AUTHORITY    NOT ESTABLISHED

open D-11 offline-custody DECISIONS: 0
secret keys 0 · public signing keys 0 · fingerprints 0 · credentials 0
release key published NO · signed release tags 0 · signed artifacts 0
customer archives 0 · external release NOT AUTHORIZED
```

**Every D-11 offline-custody decision is now closed.** What remains is physical supply and
implementation, not architecture.

## To resume — each its own authorization

1. **Supply 3 removable media.** No pre-formatting needed; the host has a card-reader slot and
   USB transport. **This is the only remaining external dependency.**
2. **Authorize `cryptsetup-bin` installation** — one package, no service impact, no reboot.
3. **Media provisioning** — LUKS containers, `ext4` inside, role labels, identity of record
   (role · LUKS UUID · FS UUID · label · capacity/class · UTC), credentials generated at
   provisioning under the rules above and transcribed to their physical records.
4. **Custody-principal implementation** — dedicated system UID/group, `0700` custody root, fresh
   custody-owned GnuPG home, custody-owned `gpg-agent` boundary, ACL-free verification.
5. **Re-run the ceremony gate**, then the ceremony (including the **OpenPGP passphrase custody
   decision**, deliberately left open), then post-ceremony export-path verification.

Optional, independent of D-11: removal of the stale `/media` directory (already ruled safe under
separate authorization).

```
repo   /home/google/Symoneural
HEAD   98326529   [D-11] credential custody decided
prev   66af2891   [D-11] three-media topology + LUKS at rest
git status --short:
 M ops/registry/EXPORTS.md
```

# D-11 CREDENTIAL CUSTODY DECIDED — OFFLINE PHYSICAL RECOVERY RECORDS
