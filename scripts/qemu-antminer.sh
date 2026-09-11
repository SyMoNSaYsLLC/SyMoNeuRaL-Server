#!/usr/bin/env bash
# Boot Antminer firmware under QEMU, so the control panel has something to talk to.
#
#   scripts/qemu-antminer.sh <firmware.tar.gz> [--shell] [--serve]
#
#   --shell        boot straight to /bin/sh instead of the miner's own init (see WHY below)
#   --serve        forward guest :80 -> host :8080 and :4028 -> host :14028
#   --dtb <path>   supply the devicetree explicitly (see DEVICETREE below)
#   --prepare      unpack and validate only, do not boot
#
# Ctrl-A X quits QEMU.  Ctrl-A C gets the QEMU monitor.
#
# ---------------------------------------------------------------------------------------
# WHAT THIS IS AND IS NOT GOOD FOR
#
# QEMU emulates the Zynq-7007's ARM cores. It does NOT emulate the FPGA fabric or the SPI
# links to the hashboards, and no amount of configuration will change that -- the hashboards
# are the part that does not exist here.
#
# So, measured on a real S17 Pro package rather than assumed:
#
#   WORKS      the kernel (Linux 4.6.0-xilinx), the 100 MB ext2 rootfs, userspace, lighttpd
#              and therefore /www/pages/cgi-bin/* -- including upgrade.cgi, which is the
#              firmware flash path and the single most valuable thing to test without
#              risking a rig.
#
#   DOES NOT   bmminer. It needs the hashboards. With the miner's own init the firmware
#              detects that they are missing and REBOOT-LOOPS, which is correct behaviour
#              for real firmware and useless as a test target -- hence --shell.
#
# That means this is a good target for the upgrade/flash work and NOT a substitute for a rig
# when testing telemetry: nothing here will answer pyasic on 4028 with real readings.
#
# ---------------------------------------------------------------------------------------
# YOU DO NOT NEED SYMONEURAL_ASIC_ENABLED TO RUN THIS
#
# Asked directly, so it is answered here rather than in a doc somewhere else. This script
# needs no environment at all -- it is qemu-system-arm and a firmware package.
#
#   SYMONEURAL_ASIC_ENABLED=1 and SYMONEURAL_ASIC_TOKEN gate the HTTP API: /api/asicminer/scan,
#   /firmware, and the /emulator route that starts THIS script for you from the panel.
#   They exist because those are remote-control endpoints on a box that faces the public
#   internet. They have nothing to do with booting firmware from your own terminal.
#
# And setting them will not make the Miner panel show readings from what this boots. See
# the DOES NOT block above: no hashboards means no bmminer means nothing answers on 4028,
# so the panel reads `offline`, correctly. That is not a misconfiguration to chase.
#
# `SYMONEURAL_ASIC_ENABLED` also has to be the literal string `1`. The check is `== "1"`, so
# `true`, `yes` and `on` all leave the surface off without saying so.
# ---------------------------------------------------------------------------------------
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$HERE")"
[ -f "$ROOT/backend/server.py" ] || { echo "repo root not found at $ROOT" >&2; exit 1; }

PKG="${1:-}"
[ -n "$PKG" ] && [ -f "$PKG" ] || {
  echo "usage: $0 <firmware.tar.gz> [--shell] [--serve]" >&2
  echo "  e.g. $0 external/Projects_Crypto/Antminer-S17Pro-user-OM-201912250947-sig_5073.tar.gz --shell --serve" >&2
  exit 1
}
shift

SHELL_INIT=0; SERVE=0; DTB_ARG=""; PREPARE=0
while [ $# -gt 0 ]; do
  case "$1" in
    --shell) SHELL_INIT=1 ;;
    --serve) SERVE=1 ;;
    --dtb)   DTB_ARG="${2:-}"; shift ;;
    --prepare) PREPARE=1 ;;
    *) echo "unknown option: $1" >&2; exit 1 ;;
  esac
  shift
done

for t in qemu-system-arm debugfs; do
  command -v "$t" >/dev/null || command -v "/sbin/$t" >/dev/null || {
    echo "missing $t. apt install qemu-system-arm e2fsprogs u-boot-tools" >&2; exit 1; }
done

WORK="${SYMONEURAL_QEMU_WORK:-${SYM_QEMU_WORK:-$ROOT/run/qemu-antminer}}"
mkdir -p "$WORK"
echo "workdir: $WORK"

# ---- unpack. See docs/antminer-firmware-upgrade.md for why each layer is what it is.
if [ ! -f "$WORK/zImage" ]; then
  echo "unpacking $(basename "$PKG") ..."
  rm -rf "$WORK/x"; mkdir -p "$WORK/x"
  tar xzf "$PKG" -C "$WORK/x"
  [ -f "$WORK/x/fw.tar.gz" ] || { echo "no fw.tar.gz -- is this an SD package?" >&2; exit 1; }
  tar xzf "$WORK/x/fw.tar.gz" -C "$WORK/x"

  # uImage and uramdisk are both u-boot legacy images: a flat 64-byte header, then the
  # payload. dd is used rather than dumpimage because Debian's dumpimage takes -o (not the
  # newer -i) and the two were compared byte-for-byte -- the header really is just 64 bytes.
  # Two package generations, and they differ in more than paths.
  #
  #   S17 / S17+ / T17 ("OM"):  uImage + uramdisk.image.gz at the top of fw.tar.gz.
  #                             Rootfs is a u-boot-wrapped ext2 RAMDISK.
  #   S9 / T9 ("xilinx"):       everything under xilinx/, and the rootfs is rootfs.jffs2 --
  #                             a FLASH filesystem, which cannot be an initrd. It needs an
  #                             emulated MTD device instead. These also ship their own
  #                             devicetree.dtb, which is preferred over a scavenged one.
  #
  # The same packages often also carry a c5/ tree: that is an Altera Cyclone V control
  # board, a different SoC family, and qemu-system-arm has no machine for it. Only the
  # xilinx/ side is usable here.
  SRC="$WORK/x"; [ -d "$WORK/x/xilinx" ] && SRC="$WORK/x/xilinx"
  [ -f "$SRC/uImage" ] || { echo "no uImage in this package (looked in $SRC)" >&2; exit 1; }
  dd if="$SRC/uImage" of="$WORK/zImage" bs=64 skip=1 status=none

  if [ -f "$SRC/uramdisk.image.gz" ]; then
    ROOTKIND=ramdisk
    dd if="$SRC/uramdisk.image.gz" of="$WORK/ramdisk.gz" bs=64 skip=1 status=none
    gunzip -kfc "$WORK/ramdisk.gz" > "$WORK/rootfs.img"
  elif [ -f "$SRC/rootfs.jffs2" ]; then
    ROOTKIND=jffs2
    cp "$SRC/rootfs.jffs2" "$WORK/rootfs.jffs2"
    # The Zynq machine's pflash is exactly 64 MB and QEMU refuses any other size:
    # "requires 67108864 bytes, pflash0 block backend provides ...".
    truncate -s 64M "$WORK/rootfs.jffs2"
  else
    echo "no uramdisk.image.gz and no rootfs.jffs2 in $SRC" >&2; exit 1
  fi
  echo "$ROOTKIND" > "$WORK/rootkind"
  echo "  kernel  $(file -b "$WORK/zImage" | cut -c1-52)"
  echo "  rootfs  $ROOTKIND"
fi
ROOTKIND="$(cat "$WORK/rootkind" 2>/dev/null || echo ramdisk)"

# ---- DEVICETREE
#
# One must be supplied and QEMU will not make one: `-machine dumpdtb` on xilinx-zynq-a9
# answers "This machine doesn't have an FDT". The browser-upgrade packages (S17 Pro, T17, S9)
# do not ship a .dtb either -- only BOOT.bin, uImage, uramdisk and the scripts.
#
# The SD-card recovery packages DO ship one, and it boots this kernel fine. So: use --dtb if
# given, else one from the unpacked package, else scavenge one out of any SD zip sitting in
# external/. All three are just a Zynq-7000 devicetree.
DTB="${DTB_ARG:-}"
if [ -z "$DTB" ]; then
  DTB="$(find "$WORK/x" -name '*.dtb' -print -quit 2>/dev/null || true)"
fi
if [ -z "$DTB" ] && [ ! -f "$WORK/zynq.dtb" ]; then
  for z in "$ROOT"/external/Projects_Crypto/*sd2nand*.zip; do
    [ -f "$z" ] || continue
    if unzip -o -j -q "$z" 'devicetree.dtb' -d "$WORK" 2>/dev/null && [ -s "$WORK/devicetree.dtb" ]; then
      mv "$WORK/devicetree.dtb" "$WORK/zynq.dtb"
      echo "  devicetree scavenged from $(basename "$z")"
      break
    fi
  done
fi
[ -z "$DTB" ] && [ -f "$WORK/zynq.dtb" ] && DTB="$WORK/zynq.dtb"
[ -n "$DTB" ] && [ -f "$DTB" ] || {
  echo "no devicetree. Pass one with --dtb <file>: any Zynq-7000 dtb works, and the" >&2
  echo "sd2nand recovery zips in external/Projects_Crypto/ contain devicetree.dtb." >&2
  exit 1
}
echo "  devicetree $DTB"

if [ "$PREPARE" = "1" ]; then
  echo "prepared. boot it with:  $0 $PKG --shell --serve"
  exit 0
fi

# ---- the two kernel arguments that actually matter
#
# ramdisk_size: the kernel's default ramdisk buffer is 4 MB and this rootfs is 100 MB.
# Without this you get "RAMDISK: incomplete write", the image is silently truncated, ext2
# then fails to read inodes, and every init candidate dies with error -5 ending in
# "No working init found". That looks like a corrupt firmware image and is not one.
#
# init=/bin/sh: with the miner's own init, the firmware finds no hashboards and reboot-loops.
if [ "$ROOTKIND" = "jffs2" ]; then
  APPEND="console=ttyPS0,115200 root=/dev/mtdblock0 rootfstype=jffs2 rw earlyprintk"
  ROOTDEV=(-drive "file=$WORK/rootfs.jffs2,if=pflash,format=raw")
else
  APPEND="console=ttyPS0,115200 root=/dev/ram0 rw ramdisk_size=131072 earlyprintk"
  ROOTDEV=(-initrd "$WORK/ramdisk.gz")
fi
[ "$SHELL_INIT" = "1" ] && APPEND="$APPEND init=/bin/sh"

NET=()
if [ "$SERVE" = "1" ]; then
  # -nic, not -netdev/-device: the Zynq machine has its two cadence_gem controllers built
  # in, so `-device cadence_gem` fails with "expects a pluggable device type". -nic attaches
  # user networking to the onboard NIC instead of trying to add another.
  NET=(-nic "user,hostfwd=tcp:127.0.0.1:8080-:80,hostfwd=tcp:127.0.0.1:14028-:4028")
  echo "forwarding  http://127.0.0.1:8080  ->  guest :80   (lighttpd, /cgi-bin/upgrade.cgi)"
  echo "            127.0.0.1:14028        ->  guest :4028 (miner API -- will not answer, see header)"
fi

if [ "$SHELL_INIT" = "1" ]; then
  cat <<'TIP'

booting to a shell. the miner's init is bypassed, so start things by hand:
    mount -t proc proc /proc && mount -t sysfs sys /sys
    /etc/init.d/lighttpd start
    ps
TIP
fi
echo "Ctrl-A X quits."
echo

exec qemu-system-arm -M xilinx-zynq-a9 -m 1024 -nographic -serial mon:stdio \
  -kernel "$WORK/zImage" -dtb "$DTB" "${ROOTDEV[@]}" \
  -append "$APPEND" "${NET[@]}"
