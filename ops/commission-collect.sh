#!/usr/bin/env bash
# SPDX-License-Identifier: LicenseRef-SyMoNeuRaL-Proprietary
# Copyright (c) 2026 SymonSays LLC. All rights reserved.
# SyMoNeuRaL is a subdivision of SymonSays LLC. Licence: /LICENSE at the repository root.
#
# Gather the root-only facts commissioning could not read, and change NOTHING.
#
#     sudo ops/commission-collect.sh
#
# Commissioning ran as `google`, which cannot read three things that matter:
#
#   * /etc/systemd/system/symoneural-api.service.d/ -- a drop-in that overrides the API unit
#     and appears NOWHERE in this repository. Until it is read, no statement about the
#     service's effective configuration is complete, including the ones in the commissioning
#     report. This is the single most valuable item here.
#   * the installed unit files, byte for byte, rather than a diff computed from what a
#     non-root reader could see.
#   * whether polkit is what makes `systemctl start|stop|restart` hang for a non-root user,
#     as opposed to something else.
#
# Everything below is a read. There is no write, no install, no unit action, no package
# action. It is safe to run at any time, including mid-incident, and safe to run twice.
#
# Output goes to review/commissioning-20260909/root-facts/, owned by the invoking user rather
# than by root so the next non-root session can actually read it.

set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="$ROOT/review/commissioning-20260909/root-facts"
# `sudo` sets SUDO_USER; fall back to the directory's owner so the files land readable.
OWNER="${SUDO_USER:-$(stat -c %U "$ROOT")}"

mkdir -p "$OUT"

say() { printf '%s\n' "$*"; }
cap() {
  # cap <file> <description> <command...> -- run a read-only command into a file.
  local f="$OUT/$1"; shift
  local what="$1"; shift
  { printf '# %s\n# $ %s\n\n' "$what" "$*"; "$@" 2>&1; } >"$f"
  say "  wrote $(basename "$f")  <- $what"
}

say "commission-collect: read-only root facts -> $OUT"
if [ "$(id -u)" -ne 0 ]; then
  say ""
  say "  NOT running as root. Everything below will be collected, but the three items that"
  say "  need root will record 'Permission denied' instead of the answer -- which is still"
  say "  a useful record, just not the one you wanted. Re-run with sudo for the real thing."
  say ""
fi

# ---------------------------------------------------------------- the drop-in
{
  printf '# The drop-in that overrides symoneural-api.service, and is not in this repo.\n\n'
  printf '## ls -la /etc/systemd/system/symoneural-api.service.d/\n'
  ls -la /etc/systemd/system/symoneural-api.service.d/ 2>&1
  printf '\n## every *.conf in it, in full\n'
  for f in /etc/systemd/system/symoneural-api.service.d/*.conf; do
    [ -e "$f" ] || continue
    printf '\n===== %s =====\n' "$f"
    cat -- "$f" 2>&1
  done
  printf '\n## the same question for the other two units\n'
  for u in symoneural-web symoneural-gateway; do
    printf '\n===== /etc/systemd/system/%s.service.d/ =====\n' "$u"
    ls -la "/etc/systemd/system/$u.service.d/" 2>&1
    for f in "/etc/systemd/system/$u.service.d/"*.conf; do
      [ -e "$f" ] || continue
      printf '\n----- %s -----\n' "$f"
      cat -- "$f" 2>&1
    done
  done
} >"$OUT/dropins.txt"
say "  wrote dropins.txt  <- THE item this script exists for"

# ---------------------------------------------------------------- installed units
{
  for u in symoneural-api symoneural-web symoneural-gateway; do
    printf '\n===== /etc/systemd/system/%s.service =====\n' "$u"
    cat -- "/etc/systemd/system/$u.service" 2>&1
  done
  printf '\n===== user units =====\n'
  for u in symoneural-progress.service symoneural-progress.timer; do
    printf '\n----- %s -----\n' "$u"
    cat -- "$HOME/.config/systemd/user/$u" 2>/dev/null \
      || cat -- "/home/$OWNER/.config/systemd/user/$u" 2>&1
  done
} >"$OUT/installed-units.txt"
say "  wrote installed-units.txt"

# ---------------------------------------------------------------- effective state
cap "systemctl-show-api.txt" "every effective property of the API unit" \
    systemctl show symoneural-api --no-pager
cap "systemctl-show-gateway.txt" "every effective property of the gateway unit" \
    systemctl show symoneural-gateway --no-pager
cap "systemctl-cat-api.txt" "unit + drop-ins as systemd assembles them" \
    systemctl cat symoneural-api --no-pager

# ---------------------------------------------------------------- why systemctl hangs
{
  printf '# Commissioning measured `systemctl stop symoneural-api` hanging until timeout as\n'
  printf '# the `google` user (rc=124/143), which is the signature of a polkit prompt that\n'
  printf '# cannot be answered non-interactively. This records whether that is the reason.\n\n'
  printf '## polkit rules mentioning systemd or manage-units\n'
  grep -rlsE 'manage-units|org.freedesktop.systemd1' /etc/polkit-1 /usr/share/polkit-1 2>&1 | head -40
  printf '\n## is a polkit authority running\n'
  systemctl is-active polkit 2>&1
  printf '\n## the invoking user'"'"'s groups\n'
  id "$OWNER" 2>&1
  printf '\n## does the API unit allow non-root control by any explicit mechanism\n'
  systemctl show symoneural-api -p User -p Group -p DynamicUser 2>&1
} >"$OUT/polkit.txt"
say "  wrote polkit.txt"

# ---------------------------------------------------------------- env file, if any
{
  printf '# The unit declares EnvironmentFile=/etc/symoneural/api.env with ignore_errors=yes.\n'
  printf '# Commissioning measured that path as ABSENT and found the real configuration at\n'
  printf '# run/config/api.env. This confirms or refutes that from root.\n'
  printf '#\n'
  printf '# NOTE: file NAMES and modes only. Contents are deliberately NOT read -- these\n'
  printf '# files hold tokens, and this output is written where a non-root user can read it.\n\n'
  ls -la /etc/symoneural/ 2>&1
  printf '\n## modes, no contents\n'
  find /etc/symoneural -maxdepth 1 -type f -printf '%m %u:%g %s %p\n' 2>&1
} >"$OUT/etc-symoneural.txt"
say "  wrote etc-symoneural.txt  (names and modes only -- no secret contents)"

# ---------------------------------------------------------------- driver / CUDA
cap "nvidia.txt" "driver, and whether the modules match the running kernel" \
    bash -c 'nvidia-smi 2>&1; echo; echo "## dkms status"; dkms status 2>&1; echo;
             echo "## running kernel"; uname -r;
             echo; echo "## loaded nvidia modules"; lsmod 2>/dev/null | grep -i nvidia;
             echo; echo "## nvidia-persistenced"; systemctl status nvidia-persistenced --no-pager 2>&1 | head -12'
cap "cuda-marks.txt" "what pins CUDA 13-3, the package the image engine needs" \
    bash -c 'echo "## auto-marked cuda packages"; apt-mark showauto 2>/dev/null | grep -E "^cuda";
             echo; echo "## manually-marked cuda packages"; apt-mark showmanual 2>/dev/null | grep -E "^cuda";
             echo; echo "## simulated autoremove -- MUST report 0 to remove"; apt-get -s autoremove 2>&1 | tail -6;
             echo; echo "## what depends on cuda-cudart-13-3"; apt-cache rdepends --installed cuda-cudart-13-3 2>&1'

# ---------------------------------------------------------------- ownership
chown -R "$OWNER" "$OUT" 2>/dev/null || true

say ""
say "  done. $(find "$OUT" -type f | wc -l) file(s) in $OUT"
say "  Nothing was written outside that directory, and no service, unit or package was touched."
say ""
say "  The one to read first is dropins.txt: until its contents are known, the commissioning"
say "  report's account of the API's effective configuration is incomplete and says so."
