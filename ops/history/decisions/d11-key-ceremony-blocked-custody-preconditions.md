# D-11 KEY CEREMONY BLOCKED — custody preconditions unsatisfiable

> **REDACTED.** Service names, credential filenames, internal ports, hostnames and web-root
> paths are masked or referred to by role. **No key material exists — none was generated.**
> Unredacted detail is on the box.

**Date:** 2026-09-02 · **HEAD:** `1f6b3ca9` (unchanged) · **Repo:** `/home/google/Symoneural`
**Outcome: BLOCKED at the pre-generation gate. Nothing was created. No commit.**

## Continues from

Previous handoff: `p2-complete-non-forgeable-release-identity.md` (2026-09-02), HEAD `1f6b3ca9`,
which completed P2 and reported all three pre-key prerequisites settled. This window attempted
the key ceremony and **stopped before generating any material.**

| Control point | At `1f6b3ca9` (prev) | Now |
|---|---|---|
| HEAD | `1f6b3ca9` | `1f6b3ca9` — **unchanged, no commit** |
| Secret signing keys | 0 | **0 — none generated** |
| Release fingerprints | 0 | **0** |
| Tracked mods | `ops/docs/EXPORTS.md` | `ops/docs/EXPORTS.md` — untouched |

## Why this stopped

**Two of the authorization's own stop clauses fired.** §13 requires stopping if separation from
services cannot be established without changing service configuration. §7 requires provisioning
offline custody media, and §16 requires `primary secret routine host = NO`.

Both are unsatisfiable on this box right now, and every remedy is outside what this
authorization permits.

**No partial authority was created.** Generating the primary now and holding it pending media
would be the exact error the P1 ordering argument rejected — except worse, because private key
material is irreversible, the custody arrangement is unapproved, and the API shares the
custody UID. The custody directory was not even created, because **who should own it is one of
the blocked decisions.** Nothing was written to disk.

---

## BLOCKER 1 — service UID co-tenancy (§13)

**Measured:**

```
symoneural API service   User=google   Group=google
                         ProtectHome=no
                         InaccessiblePaths=   (empty)
                         PrivateUsers=no
operator account         uid 1000 (google)
```

The service runs as **the same UID** that would own the signing-subkey custody directory.

**Unix DAC cannot separate a process from files owned by its own UID.** `chmod 700` on a
`google`-owned directory is fully readable by **any** process running as `google` — including
the API. So §16's required `service-readable NO` **cannot be achieved by ownership and mode
alone**, which is precisely the condition §13 says to stop and report rather than work around.

This is not a hypothetical: the service has unrestricted read of the operator home
(`ProtectHome=no`, no `InaccessiblePaths`, no user namespacing).

**Every available remedy is out of scope for this authorization:**

| Remedy | Why blocked |
|---|---|
| systemd hardening (`ProtectHome=`, `InaccessiblePaths=`) | Modifies the unit and needs `daemon-reload`. §13 forbids modifying or restarting services |
| **Dedicated non-login custody UID** | Strongest option that touches **no service** — but it creates a system account and reworks the operator signing workflow, a custody-architecture decision D-11 does not currently express |
| Root-owned custody | Operator cannot sign routinely without `sudo`; contradicts C-2's "operator-owned" |
| Hardware token (C-4) | No token evidence on this host; new hardware, explicitly out of scope |

### The question that resolves this — owner decision

**Does D-11's "never service-readable" mean *not readable* literally (ownership and mode), or is
*readable but unusable without a passphrase* acceptable?**

A passphrase-protected signing subkey is still **byte-readable** by a same-UID process but
**cannot be used to sign**. That is the minimum-change path and is likely the real resolution —
but it is a **weaker guarantee** than §16's `service-readable NO`, so accepting it is the
owner's call, not a substitution I should make silently.

- **Option A — passphrase-only separation.** No new accounts, no service changes. Custody
  directory `700`, subkey passphrase-protected, no `gpg-agent` cache persistence. Guarantee:
  *unusable* by the service, not *unreadable*. §16 would need rewording.
- **Option B — dedicated custody UID (recommended if the literal reading holds).** A non-login
  system account owns custody `700`; the operator reaches it via an explicit elevation step.
  Achieves literal non-readability by the service UID. Touches no service. Requires D-11 to
  express a custody principal it currently does not.
- **Option C — defer until systemd hardening is separately authorized.** Keeps the literal
  guarantee and the current single-operator workflow, at the cost of another gate.

---

## BLOCKER 2 — no offline custody media (§7)

**Measured, and verified beyond a single read:**

```
removable disks with nonzero size    0
sda                                  RM=1, SIZE=0B, no filesystem  (empty slot)
/media/root                          empty
/media/google/A533-850E              STALE root-owned directory, NOT a mountpoint,
                                     no mount entry, UUID matches no current device
                                     (residue of a FAT32 volume last seen 2026-07-09)
```

C-2 requires the **primary in offline/removable custody**, and §6 says *"do not silently leave
the full primary secret key host-resident."* With no media present, there is nowhere for the
primary to go. Generating it would leave the full primary secret **host-resident on the box that
also runs the API as the same UID** — the opposite of the required end state, and a
`primary secret routine host = YES` outcome that §16 forbids.

§7 also asks for a copy count and separation status. With zero media, the minimum safe ceremony
arrangement cannot be constructed at all — so the unresolved custody-policy decision is
reported rather than invented:

**Unresolved custody-policy decision:** D-11 does not yet define a backup **copy count** or
**media topology**. Minimum safe arrangement would be **2 copies on separate removable media**,
physically separated, with the **revocation certificate on a third** (or on one of the two but
in separately-protected form), since §5 requires it held apart from routine signing-subkey
custody. Confirming that topology is an owner decision, not a technical default.

---

## Additional finding — an explained pre-existing GnuPG artifact, NOT a discrepancy

The gate found a **second GnuPG home** I had not previously accounted for:

```
~/.gnupg               0 secret keys, 0 public keys, mode 755
~/.repoconfig/gnupg    0 secret keys, 1 PUBLIC key, mode 700
```

The single public key is **fully explained and unrelated to D-11**: DSA-1024 created 2008,
uid `Repo Maintainer <repo@android.kernel.org>`, installed by the Android `repo` tool
(`/usr/bin/repo`, keyring-version 2.3) to verify **its own** updates. Third-party verification
material with **zero secret keys**. There is **no existing SymonSays release authority, no
candidate release key, and no release fingerprint.** Nothing was overwritten, imported, deleted,
or merged.

**Worth carrying forward:** `~/.gnupg` is mode **755** — not custody-grade. Current GnuPG
posture on this box is unprepared for a release authority, which reinforces that the custody
directory must be created `700` **before** any material exists, and must not be the default
GnuPG home.

**Accuracy correction to my earlier reporting:** a `-maxdepth 2` scan returned 0 `.asc`/`.sig`
files, which I should have scoped. Correct statement: **0 SyMoNeuRaL release signatures**;
**721** unrelated third-party vendor signature files exist elsewhere in the tree (under
`references/`, `run/`), none of them SyMoNeuRaL release artifacts.

---

## §17 return — every item, with key-dependent rows marked N/A

| Item | Value |
|---|---|
| HEAD | `1f6b3ca9` |
| Previous HEAD | `1f6b3ca9` — **unchanged** |
| Commit subject | **none — no commit created** |
| Files changed | **none** |
| `git status --short` | ` M ops/docs/EXPORTS.md` |
| `git diff --cached --name-only` | *(empty — nothing staged)* |
| Ceremony UTC timestamp | **N/A — ceremony not performed** |
| Primary fingerprint | **N/A — no primary created** |
| Signing-subkey fingerprint | **N/A — no subkey created** |
| Primary algorithm/capabilities | N/A |
| Subkey algorithm/capabilities | N/A |
| Primary creation/expiry | N/A |
| Subkey creation/expiry | N/A |
| Primary secret material | **does not exist**; routine host present **NO** |
| Signing-subkey secret material | **does not exist**; service-readable **N/A (nothing exists)** |
| Revocation certificate | created **NO** |
| Offline custody | provisioned **NO** — **no media present** (Blocker 2); copies **0** |
| Public export | prepared privately **NO**; published **NO** |
| **P1/P2 full test count** | **43 passed** (7 A-2 + 15 P1 + 21 P2) |
| Test command | `python3 -m pytest backend/apps/test_export_snapshot.py -q` |
| Test results | **43 passed**, 0 failed |
| Real customer-manifest dry-run | **PASS** — stage 1/2/2b/3 green, 7 candidates correspond to HEAD, identity resolved, **no archive written** |
| `site/release-key.txt` | **ABSENT** |
| Signed release tags created | **0** |
| Signed artifacts created | **0** |
| Archives created | **0** |
| `ops/docs/EXPORTS.md` | **untouched and unstaged** |
| No private material entered repository | **CONFIRMED — none exists anywhere** |
| No private material entered export staging | **CONFIRMED — none exists** |
| No service granted signing-key access | **CONFIRMED — no key exists; and see Blocker 1, which is why none was created** |
| `commit.gpgsign` enabled as D-11 requirement | **NO — not enabled**; git signing config still **0 entries** |
| Production release tag created | **NO** |
| Public key published | **NO** |
| External release | **NOT AUTHORIZED** |

**§9 note:** the post-key P1 exclusion verification could not be performed as specified, because
it requires a real custody arrangement to exist. The suite was re-run at the gate (43 passing)
and the real manifest dry-run is green, but the *materially different* test — proving the actual
custody location cannot enter the customer-export path — remains **pending the ceremony**. P1's
`ops/keys/` and `ops/signing/` location patterns already refuse by location, so once the custody
class is decided, that verification is a short follow-on.

---

## Current state

```
P1                        COMPLETE
P2                        COMPLETE
P3                        CHANNEL CONFIRMED (key not published)
D-11 RELEASE AUTHORITY    NOT ESTABLISHED — ceremony blocked

secret signing keys       0
public signing keys       0        (1 unrelated third-party tool key, explained above)
release fingerprints      0
site/release-key.txt      ABSENT
signed release tags       0
signed release artifacts  0
customer archives         0
external release          NOT AUTHORIZED
```

## To resume — ordered prerequisites, each authorization-sized

1. **Decide the custody principal** (Blocker 1): Option A passphrase-only / **Option B dedicated
   custody UID (recommended if the literal reading of "never service-readable" holds)** /
   Option C defer for systemd hardening. This decides **who owns the custody directory**, which
   is why no directory was created.
2. **Provision offline custody media** (Blocker 2): removable media physically present, plus an
   owner ruling on **copy count and topology** — minimum safe is 2 separated copies with the
   revocation certificate held apart.
3. **Re-run the ceremony gate**, then perform the ceremony under the decided arrangement.
4. **Post-ceremony §9 verification** — prove the real custody path cannot enter the
   customer-export path.

Then, each still separately gated: public-key publication (P3-1 via `site/release-key.txt`,
never hand-placed in the web root), signed release tags (P2 mechanism), release-record signing,
and external release authorization.

```
repo   /home/google/Symoneural
HEAD   1f6b3ca9   [P2] non-forgeable release identity
git status --short:
 M ops/docs/EXPORTS.md
```

# D-11 KEY CEREMONY BLOCKED — SERVICE UID CO-TENANCY (§13) AND NO OFFLINE CUSTODY MEDIA (§7)
