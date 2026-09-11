# Antminer firmware: the two upgrade paths, and what validates each

Written from the actual packages in `references/Projects_Crypto/`, extracted and verified
rather than described from memory. Every exit code and offset below was read out of the
scripts that run on the rig.

Two paths exist and they are **not** the same format. A package built for one will not work
via the other.

---

## Path 1 — Browser (the miner's own web UI)

**Format:** a `.tar.gz` of exactly seven files.

```
cert.pem  cert.pem.sig  fw.tar.gz  fw.tar.gz.sig  runme.sh  runme.sh.sig  version_number
```

`cert.pem` is a bare **RSA-4096 public key**, not an X.509 certificate despite the name, so
`openssl x509` fails on it and that failure means nothing. Signatures are raw RSA over
SHA-256 — 512 bytes each.

Upload through *System → Upgrade* in the miner web UI. The rig untars it and runs the **outer**
`runme.sh`, which is a signature gate, and that then unpacks `fw.tar.gz` into a tmpfs at
`/tmp/mem/fw` and runs the **inner** `runme.sh`, which does the flashing.

### Three gates run before `runme.sh` is reached at all

Read out of `/www/pages/cgi-bin/upgrade.cgi` in the extracted rootfs (see "Opening a
firmware image" below). None of these are in `runme.sh`, and a package can be perfectly
signed and still be refused by all three.

1. **Symlinks are rejected.** `tar ztvf $$.tgz | grep "^l"` — any symlink or hardlink in the
   tarball aborts the upload with *"tarball contains symbol link"*. This is the first thing
   that happens after the body is written to disk.
2. **`runme.sh.sig` is verified against `/etc/bitmain-pub.pem` by the CGI**, not by
   `runme.sh`. This is why `runme.sh.sig` is in the package at all — the installer never
   checks itself. Failure gives *"Installer Not Signtured!!!"*.
3. **The installer is checked against a revocation list.** `md5sum runme.sh` is looked up in
   `/etc/blacklist`; a hit gives *"CANNOT USE THIS RUNME!!!"*. The 2019 S17 Pro rootfs ships
   **27 entries**. This is how Bitmain revokes a known custom-firmware installer, and it is
   independent of signing — a correctly self-signed package whose `runme.sh` is on the list
   is still refused.

`fwcheck.py` reports the symlink gate and the `runme.sh` md5, and evaluates the blacklist if
you give it a copy pulled off your own rig:

```bash
python3 backend/apps/asicminer/fwcheck.py <pkg>.tar.gz --blacklist ./blacklist
```

There is also an **else-branch**: if the tarball contains no `runme.sh` at all, the CGI
treats it as an SD-style payload — copying to `/dev/mmcblk0p1` if `/dev/mmcblk0p3` exists,
and flashing `initramfs.bin.SD` to `mtd8` and `uImage.bin` to `mtd7`. That is a second,
undocumented upgrade mode reachable through the same upload form.

### Outer runme.sh — the signature gate

| Exit | Condition |
|---|---|
| 1 | `cert.pem` missing |
| 2 | `cert.pem.sig` missing |
| 3 | `cert.pem` fails to verify against `/etc/bitmain-pub.pem` |
| 4 | `fw.tar.gz.sig` missing |
| 5 | `fw.tar.gz` fails to verify against the package's own `cert.pem` |

**Step 3 is conditional on `[ -e /etc/bitmain-pub.pem ]`.** This is the whole story for custom
firmware. A rig still holding Bitmain's public key requires the package cert to be
Bitmain-signed, so a self-signed package exits 3. Custom firmware images generally do not ship
that file, so on a rig already running one the step is skipped — but **step 5 always runs**,
against the `cert.pem` inside the package, so a repackager self-signs and the chain is
internally consistent.

Failures write to `/tmp/upgrade_result` and `rm * -rf` the staging directory.

### Inner runme.sh — the version gate and the flash

| Exit | Condition |
|---|---|
| 6 | `/etc/ant_version` exists on the rig but the package has no `version` file |
| 7 | **Downgrade blocked** — `[ ${nVer} -lt ${oVer} ]` |

The version gate is a *numeric* shell comparison of the package's `version` against the rig's
`/etc/ant_version`. On the S17 Pro package these are different files with different contents:

- `version` → `5073` — the number the gate compares, and the one in the filename `…sig_5073`
- `version_number` → `2.08998.0.30` — the display string, **not used by the gate**

Then, in order, with no rollback:

```
BOOT.bin           → flash_erase /dev/mtd0 0x0        0x40  ; nandwrite -p -s 0x0
devicetree.dtb     → flash_erase /dev/mtd0 0x1A00000  0x1   ; nandwrite -p -s 0x1A00000
uImage             → flash_erase /dev/mtd0 0x2000000  0x40  ; nandwrite -p -s 0x2000000
uramdisk.image.gz  → flash_erase /dev/mtd1 0x0        0x100 ; nandwrite -p -s 0x0
                     and /dev/mtd4 as well, if it exists
```

Each block is guarded by `if [ -e <file> ]`, so a package may ship any subset.

### The ordering hazard, which is worth understanding before you flash anything

`uramdisk.image.gz` is checked against `md5_info` **and that check happens after `BOOT.bin`
and `uImage` have already been written to NAND.** On mismatch the script logs to
`/config/md5_error` and skips the rootfs write — leaving the rig with a **new bootloader and
kernel against the old rootfs**, which is exactly the state that needs an SD-card recovery.

There is no transaction and no rollback. `flash_erase` runs before `nandwrite` on every
partition, so a power cut mid-write leaves that partition erased.

**Verify the md5 before uploading, not after.** On the S17 Pro package it is correct:
`md5_info` = `5460747cf9aaa519bb2aedb5d8fcbde7`, and the file matches.

### Pre-flight

`backend/apps/asicminer/fwcheck.py` runs the outer gate offline and reports the exact exit
code the rig would produce:

```bash
python3 backend/apps/asicminer/fwcheck.py "<package>.tar.gz"
python3 backend/apps/asicminer/fwcheck.py "<package>.tar.gz" --bitmain-pub /path/to/pub.pem
```

Verified against four real packages (S17 Pro, T17, S9, S17+) — all pass; appending one byte
to `fw.tar.gz` gives exit 5, and removing `cert.pem` gives exit 1.

---

## Path 2 — SD card (recovery, and the only way back from a bad flash)

**Completely different format.** Not a tarball, not the seven-file layout, and the signatures
are a different size: **256 bytes, RSA-2048**, against the browser path's 512-byte RSA-4096.

`Antminer-S19j-Release-sd2nand-zynq7007-20210523.zip` contains:

```
bin/update.bmu        17.9 MB     the payload the SD boot applies
devicetree.dtb  + .sig
miner.btm       + .sig
uImage          + .sig
update.image.gz + .sig
uramdisk.image.gz               (no .sig of its own)
readme.factory                  a SHA-256 manifest, NOT prose instructions
```

The name `sd2nand` is the mechanism: the Zynq-7007 SoC prefers the SD card as boot device, so
the card boots its own `uImage` + `uramdisk`, and that environment writes NAND. This is why it
recovers a brick — it never needs the installed rootfs to work.

Procedure: write the files to a FAT32-formatted card, insert it in the control board's slot,
power on, wait for the LED pattern, power off, remove the card, power on.

### This particular package fails its own manifest — check before you trust it

`readme.factory` is a `sha256sum` manifest. Running it against a clean extract:

```
./devicetree.dtb        OK          ./uImage                FAILED
./devicetree.dtb.sig    OK          ./uImage.sig            FAILED
./miner.btm             OK          ./update.image.gz       FAILED
./miner.btm.sig         OK          ./update.image.gz.sig   FAILED
                                    ./uramdisk.image.gz     FAILED
```

**Five of nine files do not match.** `unzip -t` reports no CRC errors, so the archive is
intact — the contents genuinely disagree with the manifest shipped inside it. The manifest
also lists `uramdisk.image.gz` and `update.image.gz` with an identical hash, and in the actual
files they differ from each other.

The most likely reading is that the zip was repackaged after the manifest was generated. It
may still flash correctly. But an SD image is the tool you reach for when a rig is *already*
bricked, and one that disagrees with its own integrity manifest is the wrong thing to have
faith in at that moment. Re-obtain it from a known source before relying on it, and check the
manifest first:

```bash
unzip -q <sd-package>.zip -d sd/ && cd sd && sha256sum -c readme.factory
```

---

---

## Opening a firmware image, to see what you are actually flashing

`uramdisk.image.gz` is not a gzip despite the name — it is a **u-boot legacy uImage**
wrapping a gzip, wrapping an ext2 filesystem. Three layers, and `file` tells you so:

```
uramdisk.image.gz: u-boot legacy uImage, Linux/ARM, RAMDisk Image (gzip),
                   13027591 bytes, Load Address: 00000000, Entry Point: 00000000
```

`u-boot-tools` provides `mkimage -l` to read the header and `dumpimage` to strip it. Note
the Debian build's syntax is `-o outfile`, **not** `-i` — `-i` is a newer upstream flag and
gives `invalid option -- 'i'` here:

```bash
sudo apt install u-boot-tools
mkimage -l uramdisk.image.gz                                   # read the 64-byte header
dumpimage -T ramdisk -p 0 -o ramdisk.raw.img uramdisk.image.gz # strip it
dd if=uramdisk.image.gz of=ramdisk.raw.img bs=64 skip=1        # identical result, no tools
gunzip -c ramdisk.raw.img > ramdisk.img
file ramdisk.img        # Linux rev 1.0 ext2 filesystem data, volume name "ramdisk"
```

Both strip methods were compared byte-for-byte here and produce the same file, so the `dd`
fallback is not a degraded option — the header is a flat 64 bytes.

**You do not need `mount` or root.** `debugfs` from `e2fsprogs` reads an ext2 image
unprivileged, which matters because the point is usually to look at one file:

```bash
/sbin/debugfs -R "ls -l /"                            ramdisk.img
/sbin/debugfs -R "cat /etc/ant_version"               ramdisk.img
/sbin/debugfs -R "dump /www/pages/cgi-bin/upgrade.cgi out.cgi" ramdisk.img
```

The loop mount still works if you prefer it — `sudo mount -o loop ramdisk.img /mnt/miner`
— it just costs root for a read.

### What is worth looking at once it is open

| Path | Why |
|---|---|
| `/etc/ant_version` | the number exit 7 compares. `5073` on this image — the same value as the package's `version`, so this package is not a downgrade |
| `/etc/bitmain-pub.pem` | **present on this image**, so outer step 3 *does* run on a rig with this firmware, and a self-signed package exits 3 |
| `/etc/blacklist` | the 27 revoked installer md5s |
| `/www/pages/cgi-bin/upgrade.cgi` | the three gates above, and the upload contract: `multipart/form-data`, field name `file1` |
| `/www/pages/cgi-bin/` | the rest of the API the control panel can drive |

One incidental find: the shipped rootfs contains `/www/pages/cgi-bin/.upgrade.cgi.swp`, a
vim swap file left in production firmware.

---

## Which path for which job

| Situation | Path |
|---|---|
| Rig boots and the web UI answers | Browser |
| Rig bricked, or bootloader/kernel/rootfs mismatched | SD card |
| Downgrading | **Neither, without work** — the browser path exits 7 |
| Installing custom firmware | Browser, *if* the rig has no `/etc/bitmain-pub.pem` |

## What is not in this repo, and must not be

The firmware images themselves live in `references/Projects_Crypto/` (5.3 GB), which is
gitignored wholesale — `/references` is a single rule in `.gitignore` and zero files under it
have ever been tracked. They are proprietary Bitmain, MicroBT and Braiins binaries. **Never
copy one into `site/`, never serve one from an endpoint, and never commit one.** The control
panel talks to rigs over their network API; it does not distribute firmware.


> **Stale paths:** `references/CGMiner-master/` and `references/Pete/` were cited during this work and have since been removed from the tree. pyasic is unaffected — it is installed from PyPI into `backend/apps/asicminer/.venv`.
