# D-11 OFFLINE CUSTODY MEDIA — topology decided, provisioning blocked

> **REDACTED.** Service names, credential filenames, internal ports, hostnames and web-root
> paths are masked or referred to by role. **No key material, no passphrase, no recovery secret
> appears here — none exists.** Unredacted detail is on the box in `Sept1.md` §22.3c.

**Date:** 2026-09-02 · **HEAD:** `16ea27ca` · **Previous HEAD:** `4108bef4`
**Repo:** `/home/google/Symoneural` · **Nature:** topology decision. **No media prepared.**

## Continues from

Previous handoff: `d11-custody-principal-decided.md` (2026-09-02), HEAD `4108bef4`, which
resolved **Blocker 1** (custody principal). This window resolves **Blocker 2's architecture**
but **could not provision it** — no suitable removable media is physically present.

| Control point | At `4108bef4` (prev) | Now at `16ea27ca` |
|---|---|---|
| HEAD | `4108bef4` | `16ea27ca` |
| Blocker 1 — custody principal | DECIDED | **DECIDED** |
| Blocker 2 — media **topology** | OPEN | **DECIDED** |
| Blocker 2 — media **provisioning** | OPEN | **BLOCKED — 0 media present** |
| D-11 release authority | NOT ESTABLISHED | **NOT ESTABLISHED** |
| Secret keys / fingerprints | 0 / 0 | **0 / 0** |
| Tracked mods | `docs/ops/EXPORTS.md` | `docs/ops/EXPORTS.md` — untouched |

## Removable media inventory (read-only; nothing modified)

| Device | Class | RM | Size | FS | UUID | Label | Mounted | Verdict |
|---|---|---|---|---|---|---|---|---|
| `sda` | **USB `Multiple Card Reader`** | **1** | **0B** | none | none | none | no | **EMPTY SLOT — not media** |
| `nvme0n1` (8 parts) | internal NVMe | 0 | 1.8T | vfat/ext4/ntfs | various | ESP · yocto · symon · WINRETOOLS · Image · DELLSUPPORT | yes | **internal disk** |
| `loop0`–`loop3` | squashfs snap mounts | 0 | 20K–105M | squashfs | — | — | yes | **loop devices** |

**Suitable custody media available: 0.**

Confirmed independently of `lsblk`, so the blocker rests on more than one read:
`/sys/block/sda/size` = **0** (no media), `removable` = **1**, model **`Multiple Card Reader`**,
**0** partitions in `/proc/partitions`.

### Existing-data findings and the safety gate

**`/media/google/A533-850E` — left completely untouched.** It is a **stale root-owned
`drwxr-xr-x` directory**, **not a mountpoint**, with **no mount entry**, containing an `EFI`
directory, and its UUID **matches no currently attached device**. Residue of a detached
FAT32/EFI volume. Under the safety gate it is not positively identifiable as dedicated D-11
custody media, so **no format, no erase, no repartition, no signature overwrite** — reported
for owner review instead.

`/media/root` is empty. `/etc/fstab` contains **no** removable custody entry.

## Topology ruling

| Role | Contents | Requirement |
|---|---|---|
| **Medium A** | primary offline authority + required recovery material | independent physical medium |
| **Medium B** | independent backup of primary + recovery material | independent physical medium |
| **Medium C** | revocation-certificate custody | separate from routine signing-subkey custody **and** from the ordinary A/B access path |

- **Primary custody copies: 1 (Medium A)** · **Backups: 1 (Medium B)** ·
  **Revocation custody: Medium C, separate**
- **Minimum controlling requirement:** 2 independent removable copies + revocation held
  separately. **Preferred: the three-medium topology.**
- **Physical media required: 3** (or 2 under the fallback below). **Currently present: 0.**
- **Physical separation status: NOT achievable** — zero media.

**Two-medium fallback — characterized but NOT adopted.** Returned for owner ruling rather than
silently collapsing revocation separation. Sharing a medium with one primary backup is
acceptable **only** under a meaningfully separate access mechanism (e.g. a separately-encrypted
container with a distinct credential), explicitly documented. **A different folder on the same
medium does not satisfy separation.**

**Explicitly rejected as substitutes:** cloud backup, network storage, repository backup,
home-directory backup, service-host backup. None used or configured.

**One physical device is one failure domain** — two partitions on a single device are **not**
physical separation, and this record does not claim otherwise.

## Media preparation

| Item | Result |
|---|---|
| Media prepared | **NONE** |
| Media untouched | **ALL** — `sda` (empty slot), internal NVMe, loop devices, and the stale `/media` directory |
| Formatting performed | **NO** |
| Partitioning performed | **NO** |
| Labels assigned | **NONE** |
| UUIDs of record | **NONE** — no media accepted, so no identity record established |
| Mounted at completion | **NO removable media mounted.** The only vfat mount is `/boot/efi` on the internal NVMe (`RM=0`), which is the system's own EFI partition and unrelated to custody |

### Second, independent blocker found

**This host has no filesystem-creation tooling.** `mkfs.vfat`, `mkfs.exfat`, `mkfs.ext4` are
**all ABSENT**. Formatting media would require installing packages — a new dependency outside
this authorization. So even once media arrives, either it must be supplied **with a usable blank
filesystem already present**, or package installation must be separately authorized.

**Format decision (deferred to provisioning):** single partition, single filesystem, mountable
without network services, mounted only on demand, **never** beneath repository, export or
customer-staging roots. No partition complexity beyond one volume per role. An existing blank
suitable filesystem should be **retained rather than needlessly reformatted**.

## Encryption-at-rest ruling — **UNRESOLVED, returned for owner decision**

**Mechanism available on this host: NONE.** Measured: `cryptsetup` **ABSENT**, `veracrypt`
**ABSENT**, `gocryptfs` **ABSENT**, `fscrypt` **ABSENT**, no `dm-crypt` module loaded.

The two protections are distinct and **neither replaces the other**:
- **OpenPGP secret-key passphrase** — protects the key material itself, travels with the key.
- **Whole-media / filesystem encryption** — protects everything on the medium, including
  recovery material and the revocation certificate, against simple physical loss of a medium.

Adopting media encryption would also create a **new recovery-secret problem D-11 has not
defined**: a media passphrase whose loss destroys the offline backup, and which cannot be stored
in the repository, in documentation, or in any handoff. **No credential was improvised.**

| Option | Trade-off |
|---|---|
| **E-1 — no media encryption** | Zero new dependencies; relies on the OpenPGP passphrase plus physical control. Weaker against physical loss of a medium |
| **E-2 — LUKS media encryption** | Strongest against loss. Requires authorizing `cryptsetup` installation **and** an owner ruling on where the media passphrase itself is held |

## Mounting discipline (future ceremony behaviour)

- Mounted **only** for authorized custody operations
- **Automatic mount configured: NO** — none was configured, `fstab` untouched
- Not exposed to application services
- **Never** beneath repository, export, or customer-staging roots
- **Unmounted** after each custody operation

## §13 return — confirmations

| Item | Value |
|---|---|
| HEAD | `16ea27ca` |
| Previous HEAD | `4108bef4` |
| Commit subject | `[D-11] Sept1.md: offline custody topology decided; provisioning blocked on media` |
| Files changed | **`Sept1.md` only** — `+122`, pure insertion (new §22.3c) |
| `git status --short` | ` M docs/ops/EXPORTS.md` |
| `git diff --cached --name-only` | `Sept1.md` (at commit); EXPORTS.md staged **0** |
| `docs/ops/EXPORTS.md` | **untouched and unstaged** |
| Custody system account | **NOT created** |
| Final custody GnuPG home | **NOT created** |
| Service changed / restarted | **NO / NO** |
| Key generated | **NO** |
| Fingerprint created | **NO** |
| Revocation certificate created | **NO** |
| Public key published | **NO** |
| Release tag signed | **NO** |
| Artifact signed | **NO** |
| Customer archive created | **NO** |
| External release | **NOT AUTHORIZED** |

**Exporter suite:** 43 passed (7 A-2 + 15 P1 + 21 P2) — unaffected by a documentation-only
change. **Staged-diff scan:** 0 private-key blocks, 0 passphrase/recovery secrets.

## Current state

```
P1                        COMPLETE
P2                        COMPLETE
P3                        CHANNEL CONFIRMED (key not published)
D-11 CUSTODY PRINCIPAL    DECIDED    (Blocker 1 resolved)
D-11 CUSTODY TOPOLOGY     DECIDED    (Blocker 2 architecture resolved)
D-11 MEDIA PROVISIONING   BLOCKED    - 0 suitable media present
D-11 RELEASE AUTHORITY    NOT ESTABLISHED

secret keys 0 · public signing keys 0 · fingerprints 0 · release key published NO
signed release tags 0 · signed artifacts 0 · customer archives 0
external release NOT AUTHORIZED
```

## What must be supplied to clear this blocker

1. **Three removable media** (preferred), or two plus an owner ruling on the two-medium
   fallback. The host has a **card-reader slot** and USB transport, so SD cards or USB devices
   both fit.
2. Each either **pre-formatted with a usable blank filesystem**, or authorization to install
   filesystem tooling (`mkfs.*` are absent).
3. An **encryption-at-rest ruling** — E-1 or E-2; if E-2, also a decision on media-passphrase
   custody and authorization to install `cryptsetup`.
4. An owner disposition for the **stale `/media` directory**, left untouched under the safety
   gate.

## To resume — each its own authorization

1. **Media provisioning** once the four items above are supplied.
2. **Custody-principal implementation** — dedicated system UID, dedicated group, `0700` custody
   root, fresh custody-owned GnuPG home, custody-owned `gpg-agent` boundary, ACL-free
   verification. (Still separate from the offline side.)
3. **Re-run the ceremony gate**, then the ceremony.
4. **Post-ceremony verification** that the real custody path cannot enter the customer-export
   path.

Then still separately gated: public-key publication (P3-1, never hand-placed in the web root),
signed release tags (P2 mechanism), release-record signing, external release.

```
repo   /home/google/Symoneural
HEAD   16ea27ca   [D-11] offline custody topology decided; provisioning blocked
prev   4108bef4   [D-11] custody principal decided
git status --short:
 M docs/ops/EXPORTS.md
```

# D-11 OFFLINE CUSTODY MEDIA DECIDED — PROVISIONING BLOCKED ON PHYSICAL MEDIA
