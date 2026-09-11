# Building custom Antminer firmware: is Yocto / meta-cryptocurrency the route?

**Short answer: no, and it would not be easier.** Every claim below was checked against the
files in `references/` or against the live repositories, not recalled.

---

## 1. `meta-cryptocurrency` does not cover this hardware

The layer is `wouterlucas/meta-cryptocurrency`, *"OpenEmbedded/Yocto layer for cryptocurrency
related projects"*. Two facts decide it:

- **Last pushed 2019-10-16.** Six and a half years stale as of today.
- Its 39 recipes are almost entirely **cgminer driver variants**: `cgminer-ants1`,
  `cgminer-ants2`, `cgminer-avalon2/4/7`, `cgminer-bab`, `cgminer-bflsc`, `cgminer-bitfury`,
  `cgminer-bitmine-a1`, `cgminer-cointerra`, and so on.

`ants1` / `ants2` are the **Antminer S1 and S2** — 2013–2014 hardware, back when Bitmain
hashboards were driven by open cgminer drivers. There is no S17, S19 or T17 support in that
layer and there never was.

## 2. The blocker is not the build system

An S17/S19 control board is a Xilinx **Zynq-7007**, and the part that actually drives the
hashboards is closed:

- `bmminer` — Bitmain's proprietary cgminer fork
- the chip initialisation and frequency-setting sequences
- the PIC microcontroller firmware on each hashboard

No build system hands you those. Yocto, OpenWrt and Buildroot would each get you a booting
Linux on the controller that **cannot make the hashboards hash**. That is why Braiins spent
years reverse-engineering it to produce `bosminer`, and why every other "custom firmware"
(Vnish, LuxOS) is a *modified stock image* rather than a from-scratch build.

## 3. Braiins does not use Yocto anyway

This is checkable in the reference already on disk. `references/braiins-os-feeds-master/`
contains `bmminer/`, `cgminer/`, `miner_upgrade/`, `uboot-miner/` — and every Makefile opens:

```make
include $(TOPDIR)/rules.mk
include $(INCLUDE_DIR)/kernel.mk
PKG_NAME:=cgminer
PKG_VERSION:=4.10.0
PKG_RELEASE:=1
```

`TOPDIR/rules.mk`, `PKG_NAME`, `PKG_RELEASE` is **OpenWrt package syntax**. Not BitBake, not
a `.bb` recipe, not Yocto. So choosing Yocto means giving up the one reference you have that
matches a working custom Antminer firmware.

## 4. The Yocto config in the repo targets the wrong SoC

`references/Projects_Crypto/Yocto_Build_Config/local.conf` opens with:

```
MACHINE ??= "kirkwood"
```

Kirkwood is a **Marvell** SoC. The S17/S19 controllers are Xilinx Zynq-7007. That config was
not written for this hardware.

## 5. Several repos in the archive instructions do not exist

`Antminer_Braiins_Zeus_Yocto_Mirror_Instructions.zip` is a *mirroring* procedure, not a build
procedure, and some of its `git clone --mirror` targets 404:

| Repo | Status |
|---|---|
| `bitmaintech/Antminer_firmware` | **200** — exists |
| `bitmaintech/meta-bitmain` | **404** — this is the Yocto layer that would have made the idea viable |
| `bitmaintech/openwrt` | 404 |
| `braiins/braiins-os` | 404 — Braiins host on GitLab, not GitHub |

The layer that would have made a Yocto route plausible is the one that isn't there.

## 6. Even a perfect image still has to get installed

Separately from building it, `/www/pages/cgi-bin/upgrade.cgi` on the rig runs three gates
before `runme.sh` (see `ops/docs/antminer-firmware-upgrade.md`):

1. symlinks in the tarball → rejected
2. `runme.sh.sig` verified against `/etc/bitmain-pub.pem` → *"Installer Not Signtured!!!"*
3. `md5sum runme.sh` looked up in `/etc/blacklist` (27 entries on the 2019 S17 Pro image)

**`/etc/bitmain-pub.pem` is present on the S17 Pro rootfs in `references/`.** So on a rig
running stock firmware, a self-signed package exits 3. The browser path is closed to
self-signed firmware by design.

---

## What actually works, in order of effort

1. **Install Braiins OS+.** It is the solved version of this problem — real hashboard
   control, autotuning, a documented installer. Their installer uses the **SD card path**,
   which bypasses `upgrade.cgi` and its signature gates entirely, because the SoC boots the
   card before it reaches the installed system.

2. **If you want to customise, fork Braiins' OpenWrt feeds**, not a Yocto layer. That is
   what `references/braiins-os-feeds-master/` is for, and its package Makefiles already build
   `bmminer`, `cgminer`, `uboot-miner` and `miner_upgrade`.

3. **The SD card is the route for anything self-signed.** It is also the only recovery path
   from a half-flashed rig, which the browser path can produce — the inner `runme.sh` writes
   `BOOT.bin` and `uImage` *before* it md5-checks the rootfs.

## What is genuinely worth building here, and already is

The control panel (`backend/apps/asicminer/`) talks to rigs over their **network API** —
supported, stable, and vendor-neutral via pyasic across Antminer, Whatsminer and Braiins. It
needs no custom firmware at all. `fwcheck.py` pre-flights a package against every gate above
so a bad flash is caught before it reaches a rig rather than after.

That is the high-value, low-risk half of this, and it does not depend on resolving any of the
above.
