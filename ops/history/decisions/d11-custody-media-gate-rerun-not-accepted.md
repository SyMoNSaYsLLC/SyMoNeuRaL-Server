# D-11 CUSTODY MEDIA NOT ACCEPTED — re-run gate, still 0 of 3 detected

> **REDACTED.** Service names, credential filenames, internal ports, hostnames and web-root
> paths are masked or referred to by role. **No credential or key material exists.**
> Unredacted detail is on the box.

**Date:** 2026-09-02 · **HEAD:** `98326529` (unchanged) · **Repo:** `/home/google/Symoneural`
**Outcome: acceptance FAILED again. Read-only. Zero device writes, zero changes, no commit.**

## Continues from

Previous handoff: `d11-custody-media-arrival-gate-not-accepted.md` (2026-09-02), same HEAD. This
is the **authorized re-run** after the owner reported inserting/connecting the media.

**Acceptance was not inferred from the report.** As instructed, it requires kernel-visible
evidence, and that evidence is absent.

| | Previous gate | This re-run |
|---|---|---|
| Removable devices with media | **0** | **0** |
| USB devices on the bus | **12** | **12 — identical** |
| `sda` size | 0 sectors | **0 sectors** |
| Accepted devices | 0 of 3 | **0 of 3** |
| HEAD | `98326529` | `98326529` |

**The bus is byte-for-byte unchanged between the two gates.** No media was attached in the
interval — this is not a probe timing problem or a stale reading.

## Candidate assessment

| | **Candidate A** | **Candidate B** | **Candidate C** |
|---|---|---|---|
| Kernel device identity | **none detected** | **none detected** | **none detected** |
| Device path | — | — | — |
| Model | — | — | — |
| Serial | — | — | — |
| Transport | — | — | — |
| Capacity | — | — | — |
| Removable status | — | — | — |
| Partition-table state | **not assessable** | not assessable | not assessable |
| Filesystem / signature state | **not assessable** | not assessable | not assessable |
| Existing data present or potentially present | **not assessable** | not assessable | not assessable |
| Current mount state | — | — | — |
| **Accepted for D-11 provisioning** | **NO** | **NO** | **NO** |

**Physical removable-device count: 0.** **Accepted-device count: 0.** Required: **3**.

**Physical independence: NOT ESTABLISHED** — there are no devices to distinguish. No role
mapping is proposed, because role assignment requires accepted media.

## Four independent authorities, all agreeing

| Authority | Evidence |
|---|---|
| **1 — block enumeration** | Non-loop devices: internal NVMe (`removable=0`, model `CT2000P310SSD8`) and `sda` (`removable=1`, **0B**). **`RM=1` disks with nonzero size: 0** |
| **2 — sysfs** | `/sys/block/sda/size` = **0 sectors**; model `Card Reader`. `/sys/block/nvme0n1` `removable=0` |
| **3 — USB bus** | Exactly **one** `usb-storage`-bound device: `058f:6366 Alcor Micro Multi Flash Reader`, serial `058F63666438` — **this device *is* `sda`**, the reader itself, not media. Every other bus entry is a headset, hub, wireless receiver, LED controller or Bluetooth radio |
| **4 — SCSI / MMC** | **1** `scsi_disk` target (`4:0:0:0`, the reader) · **1** LUN, at **0 sectors** · **0** `/dev/mmcblk*` · **0** `/dev/sd[b-z]` |

**Multi-slot check performed:** a multi-format reader often exposes one LUN per slot, so a card
could in principle appear on a LUN other than the first. Measured: **exactly 1 LUN**, reporting
**0 sectors**. No unprobed slot is hiding media.

**One blocked path, reported rather than treated as absence:** a non-destructive SCSI `rescan`
(a re-probe of the reader, not a write to any medium) was **denied — needs elevation**. So the
"no media" conclusion rests on the four authorities above, not on that probe. `sda` still read
**0 sectors** afterwards. If you want the re-probe attempted with elevation, that is a one-line
read-only command; it would only matter if a card were seated but never generated a media-change
event.

## Existing-data assessment

**Not applicable — no candidate media exists to assess.** No partition table, filesystem, LUKS
signature, boot record, EFI content, label, or ownership indicator was read from any removable
device, because none is present.

**Nothing was formatted, wiped, repartitioned, or overwritten.** No signature was removed. Had
media been present and shown any existing data or ambiguous provenance, it would have been marked
**OWNER REVIEW REQUIRED** and left untouched.

## No substitution was made

The topology stands as ruled — **three physically independent removable devices**. I did not
substitute: partitions or logical volumes on one device · internal NVMe storage · loop devices ·
**the empty card-reader device itself** · stale `/media` paths (left untouched, not reused) ·
host, cloud, network, or repository storage.

## Why the media is likely not visible

1. **Card not seated in the reader.** The reader enumerates (so the hardware and driver are
   fine), but reports **0 sectors** — the classic signature of an empty slot. A card that is
   inserted but not fully seated presents exactly this.
2. **Wrong slot on a multi-format reader.** It exposes a single LUN, so only one slot is being
   presented; a card in a different physical slot of the same reader may not appear.
3. **USB stick on an unpowered or faulty hub port.** Several hubs are on the bus, including a
   headset-charging hub. A device on a dead downstream port never enumerates at all.
4. **Media attached to a different machine** than this release host.

**Read-only self-check, safe to run:**

```
lsblk -o NAME,TYPE,RM,SIZE,FSTYPE,LABEL,MODEL,TRAN
```

Three removable entries with **nonzero size** must appear. A device showing `0B` means the card
is not seated. If nothing new appears at all, the device is not enumerating and the port or
reader slot is the thing to change.

## Return

| Item | Value |
|---|---|
| HEAD | `98326529` |
| `git status --short` | ` M ops/docs/EXPORTS.md` (nothing staged) |
| Physical removable-device count | **0** |
| Accepted-device count | **0** |
| Candidate A / B / C | **none detected**, all fields not assessable, **accepted NO** |
| Evidence of physical independence | **not established** — no devices to compare |
| Proposed role mapping | **NONE** — acceptance did not succeed |
| Existing-data assessment | **not applicable** — no media to assess; nothing read, nothing altered |
| **Zero device writes** | **CONFIRMED** — reads only; the single `rescan` write was **denied** and never reached any medium |
| **Zero package installations** | **CONFIRMED** — `cryptsetup` still absent |
| **Zero repository changes** | **CONFIRMED** — HEAD unchanged, nothing staged, no commit |
| Read-write mounts / filesystems created | **0 / 0** |
| LUKS containers / credentials | **0 / 0** |
| Custody account / directory | **NO / NO** |
| GnuPG material / key / fingerprint / revocation cert | **none** |
| Published / signed / archived | **NO / NO / NO** |
| Services changed / reboot | **none / none** |
| Stale `/media` directory | **untouched, not reused** |
| External release | **NOT AUTHORIZED** |

## Resulting D-11 state

```
P1                        COMPLETE
P2                        COMPLETE
P3                        CHANNEL CONFIRMED (key not published)
D-11 CUSTODY PRINCIPAL    DECIDED
D-11 CUSTODY TOPOLOGY     DECIDED - three physically independent media
D-11 ENCRYPTION AT REST   DECIDED - E-2 LUKS
D-11 CREDENTIAL CUSTODY   DECIDED - offline physical recovery records
D-11 MEDIA ACCEPTANCE     NOT ACCEPTED - 0 of 3 devices detected (re-run)
D-11 RELEASE AUTHORITY    NOT ESTABLISHED

open architecture DECISIONS: 0   -- only physical media supply remains
secret keys 0 · fingerprints 0 · credentials 0 · signed tags 0 · archives 0
external release NOT AUTHORIZED
```

Every architectural decision is closed. **The single remaining dependency is physical hardware
becoming visible to this host.** No further architecture or repository work can advance D-11.

## The exact next authorization required

**Re-run the D-11 removable-media acceptance gate**, after three removable devices appear with
nonzero size in the read-only `lsblk` check above. Same read-only gate, unchanged scope — it is
non-destructive and repeatable, and re-running it costs nothing and changes no state.

Optionally, and only if you want to rule out a seated-but-unprobed card: authorize a **read-only
SCSI re-probe with elevation** (a re-probe of the reader; not a write to any medium).

Only after acceptance succeeds does the next step become **`cryptsetup-bin` installation only** —
one package, no service impact, no reboot.

```
repo   /home/google/Symoneural
HEAD   98326529   [D-11] credential custody decided
git status --short:
 M ops/docs/EXPORTS.md
```

# D-11 CUSTODY MEDIA NOT ACCEPTED — OWNER REVIEW REQUIRED
