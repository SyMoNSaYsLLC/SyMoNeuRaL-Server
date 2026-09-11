# D-11 OFFLINE CUSTODY DECISIONS COMPLETE — three-media topology + LUKS at rest

> **REDACTED.** Service names, credential filenames, internal ports, hostnames and web-root
> paths are masked or referred to by role. **No key material, no passphrase, no credential
> appears here — none exists.** Unredacted detail is on the box in `Sept1.md` §22.3d.

**Date:** 2026-09-02 · **HEAD:** `66af2891` · **Previous HEAD:** `16ea27ca`
**Repo:** `/home/google/Symoneural` · **Nature:** decision recording + prerequisite
characterization. **Nothing installed, formatted, mounted, or created.**

## Continues from

Previous handoff: `d11-offline-custody-media-blocked-on-physical-media.md` (2026-09-02),
HEAD `16ea27ca`. That window decided the topology shape and returned two open decisions. The
owner has now ruled on both, and this window records them plus the prerequisite detail.

| Control point | At `16ea27ca` (prev) | Now at `66af2891` |
|---|---|---|
| Media topology | decided (shape) | **THREE media, controlling; fallback REJECTED** |
| Encryption at rest | **UNRESOLVED** | **E-2 LUKS adopted** |
| Credential relationship | undefined | **three independent credentials** |
| Credential-custody mechanism | — | **STILL REQUIRED — owner decision** |
| `cryptsetup` prerequisite | "absent" | **`cryptsetup-bin` identified; still not installed** |
| Filesystem tooling | *"absent"* | **CORRECTED — already installed** |
| Stale `/media` directory | ambiguous | **SAFE TO REMOVE under separate authorization** |
| D-11 release authority | NOT ESTABLISHED | **NOT ESTABLISHED** |

## Topology — three physically independent media

| Role | Contents |
|---|---|
| **Medium A** | primary offline authority + required recovery material |
| **Medium B** | independent backup of primary authority + required recovery material |
| **Medium C** | revocation-certificate custody |

**Physical media required: 3.** Recorded explicitly: different **partitions** on one device do
**not** count; different **directories** on one device do **not** count;
**cloud / network / repository / home-directory / service-host** storage do **not** count.

**Two-medium fallback: REJECTED** for the controlling configuration.

## Encryption at rest — E-2 adopted

```
PHYSICAL CONTROL              media stored separately, not routinely attached
        +
LUKS MEDIA ENCRYPTION         protects the whole medium - including recovery material
                              and the revocation certificate - against physical loss
        +
OPENPGP SECRET-KEY PASSPHRASE protects the key material itself, travels with the key
```

Recorded explicitly, because conflating these is the failure mode:
- **LUKS does not replace OpenPGP key protection** — a decrypted medium exposes an unprotected key.
- **OpenPGP key protection does not replace media encryption** — the passphrase covers the key
  blob but not the recovery material or revocation certificate beside it, and does nothing about
  a lost medium.

### Credential relationship: three INDEPENDENT credentials

| Medium | Credential | Reasoning |
|---|---|---|
| **A** | **independent** | A and B exist to survive loss or compromise of the other. A shared credential makes them **one failure domain for confidentiality** — one credential compromise exposes both copies, defeating the point of holding two |
| **B** | **independent of A** | as above |
| **C** | **independent of A and B** | revocation custody must be reachable **precisely when** the primary custody path is compromised or unavailable |

**Tradeoff, stated rather than hidden:** independent credentials **minimize correlated
compromise** but **increase the number of individually-unrecoverable credentials**. Accepted
because the topology already provides redundancy against *loss* (A and B are independent copies
of the same authority) — so the residual risk is losing *one copy's* credential, not losing the
authority. A shared credential would trade a loss risk the topology already covers for a
correlation risk it does not.

### Credential boundaries (characterized, not implemented)

Media-encryption credentials **must not**: live in the repository; appear in handoff documents;
be stored **in plaintext on the medium they unlock** (*a credential on the medium it unlocks is
not a credential*); live in application/service configuration; or be **derived from** runtime,
session, entitlement, or signing secrets.

### The one decision still required — credential-custody MECHANISM

**`STILL REQUIRED: YES.`** Adopting E-2 does **not** decide *where the three credentials are
held*, and that is not a technical default to improvise. The boundaries above say where they may
**not** live; they do not say where they **must**. Candidate mechanisms — offline written record
in physical custody, a separate password manager under operator control, split/escrow — carry
different recovery and single-point-of-failure profiles, and the choice determines whether losing
one item destroys an offline copy.

**No credential was generated, and none may be until this is ruled.** This is the precise
stopping point the authorization asked me to identify.

## `cryptsetup` prerequisite

| Item | Finding |
|---|---|
| Installed | **NO** — `cryptsetup`, `cryptsetup-reencrypt`, `integritysetup`, `veritysetup` all absent |
| **Required package** | **`cryptsetup-bin`** — command-line tools only, candidate `2:2.7.5-2` |
| **Expected executable** | `/usr/sbin/cryptsetup` |
| **Service impact** | **NONE** — installs no unit, no daemon, no startup script |
| **Reboot required** | **NO** |
| **initramfs impact** | **NONE for this use case** |

**Why `cryptsetup-bin` and not `cryptsetup`:** the latter is *"disk encryption support — **startup
scripts**"*. It pulls `dmsetup` + `debconf` and **suggests** `cryptsetup-initramfs` — none of
which is needed for removable data custody, and it puts packaging into the boot path for no
benefit. `cryptsetup-bin` depends only on five libraries. `initramfs` integration matters only
for unlocking a **boot/root** device; removable media are unlocked interactively after boot.

**Kernel support already present:** `dm-crypt` ships with the running kernel, `dm_mod` is
loaded, `/dev/mapper` exists. No kernel change.

**Scope guard: removable custody media only. No system-disk encryption** is proposed or implied.

## Filesystem inside each LUKS container

**Recommendation: `ext4`**, one filesystem per physical medium, no extra partitioning. It is
Linux-native, fully offline, and — the deciding factor — **preserves the Unix ownership and
`0600`/`0700` modes custody requires**, which `vfat`/`exfat` **cannot represent**.

**Required tooling: NONE — already installed.**

> ### Correction to my previous handoff
> The prior handoff and §22.3c recorded `mkfs.ext4`, `mkfs.vfat` and `mkfs.exfat` as **ABSENT**
> and concluded that filesystem tooling would need installing. **That was wrong.** All three
> exist under `/usr/sbin/` — `e2fsprogs`, `dosfstools` and `exfatprogs` are **all installed**.
> The operator shell's `PATH` simply omits `/usr/sbin`, so `command -v` reported absence.
> I read a **tool-visibility artifact as system absence** — the same error class as the earlier
> depth-capped `/yocto` scan. **The only package still needed is `cryptsetup-bin`**, and the
> earlier "media must arrive pre-formatted or tooling must be authorized" condition is
> **withdrawn**.

## Future media identities

Role labels (uppercase, hyphenated, within `ext4` label limits):

```
D11-PRIMARY-A      Medium A
D11-PRIMARY-B      Medium B
D11-REVOCATION-C   Medium C
```

**Identity of record, captured at provisioning** (not now — no media exists): physical role ·
**LUKS UUID** · **filesystem UUID** (inside the container) · volume label · capacity/device
class · provisioning UTC timestamp.

**`/dev/sdX` is explicitly NOT identity** — it is assignment-order dependent and changes between
attachments.

## Stale `/media/…/A533-850E` disposition

Narrow read-only provenance check — seven questions, **all negative**:

| Check | Result |
|---|---|
| mountpoint? | **NO** |
| any current block device owns UUID `A533-850E`? | **NO** (0 matches) |
| `/etc/fstab` reference? | **NO** (0) |
| repository script reference (path or UUID)? | **NO** (0) |
| systemd mount unit reference? | **NO** (0 units, 0 `.mount` files) |
| shell/profile reference? | **NO** (0) |
| contents beyond stale residue? | **NO** — exactly 3 entries: the directory, `EFI/`, `EFI/BOOT/` |

**Disposition: `STALE DIRECTORY — SAFE TO REMOVE UNDER SEPARATE AUTHORIZATION`.**

Residue of a detached UEFI-bootable USB volume. **Root-owned**, so removal needs elevation, and
it was **not removed**. No bearing on D-11 custody, and it must **not** be reused as a custody
mountpoint — custody media get their own explicitly chosen path outside repository, export and
customer-staging roots.

## §10 return

| Item | Value |
|---|---|
| HEAD | `66af2891` |
| Previous HEAD | `16ea27ca` |
| Commit subject | `[D-11] Sept1.md: three-media topology + LUKS at rest; credential custody still open` |
| Files changed | **`Sept1.md` only** — `+160`, pure insertion (new §22.3d) |
| `git status --short` | ` M ops/docs/EXPORTS.md` |
| `git diff --cached --name-only` | `Sept1.md` (at commit); EXPORTS.md staged **0** |
| **Physical media required** | **3** |
| Roles | A primary · B independent backup · C revocation |
| Two-medium fallback | **REJECTED** |
| E-2 ruling | **ADOPTED — LUKS-encrypted removable custody** |
| LUKS credential A / B / C | **independent / independent / independent** |
| **Credential-custody decision still required** | **YES** |
| `cryptsetup` installed | **NO** |
| Required package | **`cryptsetup-bin`** |
| Expected executable | `/usr/sbin/cryptsetup` |
| Reboot required | **NO** |
| Service impact | **NONE** |
| initramfs impact (removable data) | **NONE** |
| Recommended filesystem | **`ext4`** |
| Required FS tooling | **NONE — already installed** (correction above) |
| Role labels | `D11-PRIMARY-A`, `D11-PRIMARY-B`, `D11-REVOCATION-C` |
| Identity fields at provisioning | role · LUKS UUID · FS UUID · label · capacity/class · UTC |
| Stale directory disposition | **SAFE TO REMOVE UNDER SEPARATE AUTHORIZATION** |

**Confirmations:** `ops/docs/EXPORTS.md` **untouched and unstaged** · **no packages installed** ·
no media formatted · no media partitioned · **no LUKS container created** · **no credentials
generated** · no custody account · no custody directory · no GnuPG material · no key generated ·
no fingerprint · no revocation certificate · no public key published · no release tag signed ·
no artifact signed · no archive created · no service changed or restarted · stale directory
untouched · **external release remains NOT AUTHORIZED**.

**Exporter suite:** 43 passed (7 A-2 + 15 P1 + 21 P2). **Staged-diff scan:** 0 private-key
blocks, 0 literal credentials.

## Current state

```
P1                        COMPLETE
P2                        COMPLETE
P3                        CHANNEL CONFIRMED (key not published)
D-11 CUSTODY PRINCIPAL    DECIDED
D-11 CUSTODY TOPOLOGY     DECIDED - three physically independent media
D-11 ENCRYPTION AT REST   DECIDED - E-2 LUKS
D-11 CREDENTIAL CUSTODY   OPEN - owner decision required
D-11 MEDIA PROVISIONING   BLOCKED - 0 physical media present
D-11 RELEASE AUTHORITY    NOT ESTABLISHED

secret keys 0 · public signing keys 0 · fingerprints 0 · release key published NO
signed release tags 0 · signed artifacts 0 · customer archives 0
external release NOT AUTHORIZED
```

## To resume — each its own authorization

1. **Credential-custody mechanism ruling** — the only remaining *decision*. Blocks provisioning,
   because provisioning creates the credentials.
2. **Supply 3 removable media.** No pre-formatting needed (correction above); the host has a
   card-reader slot and USB transport.
3. **Authorize `cryptsetup-bin` installation** — one package, no service impact, no reboot.
4. **Media provisioning** — LUKS containers, `ext4` inside, role labels, identity of record.
5. **Custody-principal implementation** — dedicated system UID/group, `0700` custody root, fresh
   custody-owned GnuPG home, custody-owned `gpg-agent`, ACL-free verification.
6. **Re-run the ceremony gate**, then the ceremony, then post-ceremony export-path verification.

Optional housekeeping, independent of D-11: removal of the stale `/media` directory.

```
repo   /home/google/Symoneural
HEAD   66af2891   [D-11] three-media topology + LUKS at rest
prev   16ea27ca   [D-11] offline custody topology decided; provisioning blocked
git status --short:
 M ops/docs/EXPORTS.md
```

# D-11 OFFLINE CUSTODY DECISIONS COMPLETE — THREE-MEDIA TOPOLOGY + LUKS AT REST
