# D-11 CUSTODY MEDIA NOT ACCEPTED — no removable media detected

> **REDACTED.** Service names, credential filenames, internal ports, hostnames and web-root
> paths are masked or referred to by role. **No credential or key material exists.**
> Unredacted detail is on the box.

**Date:** 2026-09-02 · **HEAD:** `98326529` (unchanged) · **Repo:** `/home/google/Symoneural`
**Outcome: media acceptance FAILED at the gate. Read-only. Nothing changed, no commit.**

## Continues from

Previous handoff: `d11-credential-custody-decided.md` (2026-09-02), HEAD `98326529`, which closed
the last offline-custody architecture decision. The owner reported that the three media were
physically supplied. **This gate could not detect them.**

| Control point | At `98326529` (prev) | Now |
|---|---|---|
| HEAD | `98326529` | `98326529` — **unchanged, no commit** |
| Architecture decisions | all closed | **all closed** |
| Physical removable media detected | 0 | **0** |
| Media accepted | — | **0 of 3** |
| Tracked mods | `ops/registry/EXPORTS.md` | `ops/registry/EXPORTS.md` — untouched |

## Block-device inventory (read-only)

| Device | Type | RM | RO | Size | Model | Transport | FS / UUID / Label | Mounted | Classification |
|---|---|---|---|---|---|---|---|---|---|
| `sda` | disk | **1** | 0 | **0B** | **`Card Reader`** | usb | none / none / none | no | **card-reader slot, NO MEDIA INSERTED** |
| `nvme0n1` | disk | 0 | 0 | 1.8T | `CT2000P310SSD8` | nvme | — | — | **internal NVMe — not custody media** |
| `nvme0n1p1` | part | 0 | 0 | 500M | — | nvme | vfat / `8ECE-13C2` / ESP | `/boot/efi` | internal partition |
| `nvme0n1p2` | part | 0 | 0 | 500G | — | nvme | ext4 / `8b28fc0c…` / yocto | `/yocto` | internal partition |
| `nvme0n1p4` | part | 0 | 0 | 441.9G | — | nvme | ext4 / `81f1e268…` / symon | `/` | internal partition |
| `nvme0n1p5` | part | 0 | 0 | 902.9G | — | nvme | ext4 / `8ae3fbb6…` | `/home` | internal partition |
| `nvme0n1p6/7/8` | part | 0 | 0 | 1.4G/15G/1.4G | — | nvme | ntfs / WINRETOOLS · Image · DELLSUPPORT | no | internal recovery partitions |
| `loop0`–`loop3` | loop | 0 | **1** | 20K–105M | — | — | squashfs | `/snap/*` | **loop devices — not custody media** |

**Physical removable device count (media present): 0.**

### Confirmed through three independent authorities

Because a single read is not evidence, and because `dmesg` was **not readable** without
elevation — a blocked read is not proof of absence:

1. **`/sys/block` enumeration** — exactly two non-loop devices: `nvme0n1` (`removable=0`) and
   `sda` (`removable=1`, **`size=0` sectors**). `size=0` means **no media in the slot**.
2. **USB bus enumeration** — **no mass-storage device present.** The only storage-capable entry
   is an `Alcor Micro Multi Flash Reader`, which *is* `sda`. Every other device on the bus is a
   headset, hub, wireless receiver, LED controller, or Bluetooth radio.
3. **SCSI / MMC subsystems** — one `scsi_disk` target (the reader itself), and **no `/dev/mmcblk*`
   devices**, so no SD card is detected either.

## Candidate assessment

| | **Candidate A** | **Candidate B** | **Candidate C** |
|---|---|---|---|
| Device | **none detected** | **none detected** | **none detected** |
| Model | — | — | — |
| Serial | — | — | — |
| Transport | — | — | — |
| Capacity | — | — | — |
| Existing partition table | not assessable | not assessable | not assessable |
| Existing filesystem/signatures | not assessable | not assessable | not assessable |
| Existing data | not assessable | not assessable | not assessable |
| Mounted | — | — | — |
| **Accepted for D-11 provisioning** | **NO** | **NO** | **NO** |

**Physical independence verified: NO** — there are no devices to compare.
**Proposed role mapping: NONE** — role assignment requires accepted media.

The existing-data safety gate (§3) and physical-independence proof (§4) could not be executed:
both require the devices to be enumerated by the kernel. **Nothing was formatted, wiped,
repartitioned, mounted, or modified** — there was nothing to act on, and no action would have
been taken regardless.

## Why this is a STOP and not a workaround

§2 requires **three physically independent removable devices** and forbids compensating by
weakening the topology. I did not, and will not:

- treat three partitions or logical volumes on one device as three media;
- use internal disks, loop devices, or the empty card-reader slot;
- reuse the stale `/media` directory as a custody path (**left untouched**, and not reused);
- substitute host storage, cloud, network, or repository storage.

The topology stands as ruled: **three physically independent devices.**

## Most likely explanations, in order

1. **Media not yet inserted or connected.** The host has a **USB-attached multi-format card
   reader** currently **empty**, plus free USB ports. An SD/microSD card must be seated in the
   reader; a USB stick must be plugged into a port.
2. **Inserted into a non-functioning port or an unpowered hub.** The bus shows several hubs; a
   device on an unpowered or faulty downstream port may not enumerate at all.
3. **Connected after this measurement.** The inventory reflects the moment it ran. If the media
   were attached afterwards, re-running the gate will detect them.
4. **Media attached to a different machine** than this release host.

## What to do next

Insert or connect the three media, then re-run this same read-only gate. No repository or system
change is needed first — the gate is non-destructive and repeatable.

A quick operator self-check before re-running (read-only, safe):

```
lsblk -o NAME,TYPE,RM,SIZE,FSTYPE,LABEL,MODEL,TRAN
```

Three removable devices with **nonzero size** should appear. If a device is present but shows
`0B`, the card is not seated in the reader.

## §11 return

| Item | Value |
|---|---|
| HEAD | `98326529` |
| `git status --short` | ` M ops/registry/EXPORTS.md` (nothing staged) |
| **Physical removable device count** | **0** |
| Candidate A / B / C | **none detected** — all fields not assessable |
| Accepted A / B / C | **NO / NO / NO** |
| Physical independence verified | **NO** |
| Proposed role mapping | **NONE** |
| `cryptsetup-bin` installed | **NO** (executable absent, package not installed) |
| **Filesystem tooling available** | **YES** — `mkfs.ext4` present at `/usr/sbin` (per the correction in §22.3d; only `cryptsetup-bin` is still needed) |
| Packages installed this task | **0** |
| Device writes | **0** |
| Read-write mounts created | **0** |
| Service change / reboot | **NONE / NONE** |
| Stale `/media` directory | **untouched, not reused as a custody path** |
| `ops/registry/EXPORTS.md` | **untouched and unstaged** |
| LUKS containers created | **0** |
| Credentials generated | **0** |
| Custody account / directory created | **NO / NO** |
| GnuPG material / key / fingerprint / revocation cert | **none created** |
| Public key published / tag signed / artifact signed / archive | **NO / NO / NO / NO** |
| External release | **NOT AUTHORIZED** |

## Current state

```
P1                        COMPLETE
P2                        COMPLETE
P3                        CHANNEL CONFIRMED (key not published)
D-11 CUSTODY PRINCIPAL    DECIDED
D-11 CUSTODY TOPOLOGY     DECIDED - three physically independent media
D-11 ENCRYPTION AT REST   DECIDED - E-2 LUKS
D-11 CREDENTIAL CUSTODY   DECIDED - offline physical recovery records
D-11 MEDIA ACCEPTANCE     NOT ACCEPTED - 0 of 3 devices detected
D-11 RELEASE AUTHORITY    NOT ESTABLISHED

open architecture DECISIONS: 0        (only physical supply remains)
secret keys 0 · fingerprints 0 · credentials 0 · signed tags 0 · archives 0
external release NOT AUTHORIZED
```

## To resume

```
repo   /home/google/Symoneural
HEAD   98326529   [D-11] credential custody decided
git status --short:
 M ops/registry/EXPORTS.md
```

1. **Insert/connect the three removable media** and **re-run this acceptance gate** (read-only,
   repeatable, no authorization state changes).
2. On acceptance: **authorize `cryptsetup-bin` installation only** — one package, no service
   impact, no reboot.
3. **Media provisioning** — LUKS containers, `ext4` inside, role labels, identity of record,
   credentials generated interactively and transcribed to their separate physical records.
4. **Custody-principal implementation** — dedicated system UID/group, `0700` custody root, fresh
   custody-owned GnuPG home, custody-owned agent boundary, ACL-free verification.
5. **Ceremony gate**, then the ceremony — including the still-open **OpenPGP passphrase custody**
   decision — then post-ceremony export-path verification.

# D-11 CUSTODY MEDIA NOT ACCEPTED — OWNER REVIEW REQUIRED
