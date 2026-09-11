#!/usr/bin/env bash
# SPDX-License-Identifier: LicenseRef-SyMoNeuRaL-Proprietary
# Copyright (c) 2026 SymonSays LLC. All rights reserved.
#
# install-cli.sh — make the first-party entry points discoverable from a login shell.
#
# The documented installation mechanism, and the reason it is a SYMLINK rather than a copy:
# a copy is a second source of truth, and this repository has an installed stale copy at
# ~/.symoneural-full/bin/symoneural-cli proving the point -- it diverged and nothing noticed
# until somebody compared hashes. A symlink cannot diverge.
#
#   scripts/install-cli.sh            install into ~/.local/bin
#   scripts/install-cli.sh --check    report only, change nothing
#
# ~/.local/bin is chosen because it is already on PATH in a login shell on this box and
# needs no root. Nothing is written outside it.
set -euo pipefail

find_root() {                       # walk up for the marker; never count parents
    local d; d="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
    while [ "$d" != "/" ]; do
        [ -f "$d/backend/api.py" ] && { printf '%s' "$d"; return 0; }
        d="$(dirname "$d")"
    done
    echo "install-cli: no repo root above ${BASH_SOURCE[0]}" >&2; return 1
}

ROOT="$(find_root)"
DEST="${SYMONEURAL_BIN_DIR:-$HOME/.local/bin}"
ENTRIES=(symoneural-cli symoneural-code symoneural-discovery symoneural-audit
         symoneural-api)

check_only=0
[ "${1:-}" = "--check" ] && check_only=1

printf 'repo   %s\n' "$ROOT"
printf 'dest   %s\n' "$DEST"
printf 'on PATH: %s\n' "$(case ":$PATH:" in *":$DEST:"*) echo yes ;; *) echo "NO — add it to your profile" ;; esac)"

[ "$check_only" -eq 1 ] || mkdir -p "$DEST"

rc=0
for e in "${ENTRIES[@]}"; do
    src="$ROOT/bin/$e"
    if [ ! -e "$src" ]; then
        printf '  %-22s SKIP   no %s in the repo\n' "$e" "bin/$e"
        continue
    fi
    tgt="$DEST/$e"
    want="$(readlink -f "$src")"
    if [ -L "$tgt" ] && [ "$(readlink -f "$tgt")" = "$want" ]; then
        printf '  %-22s ok     -> %s\n' "$e" "$want"
        continue
    fi
    if [ -e "$tgt" ] && [ ! -L "$tgt" ]; then
        # Never clobber a real file somebody put there on purpose.
        printf '  %-22s REFUSE %s exists and is not a symlink\n' "$e" "$tgt"
        rc=1
        continue
    fi
    if [ "$check_only" -eq 1 ]; then
        printf '  %-22s would link -> %s\n' "$e" "$want"
        continue
    fi
    ln -sfn "$want" "$tgt"
    printf '  %-22s linked -> %s\n' "$e" "$want"
done

if [ "$check_only" -eq 0 ]; then
    printf '\nverify from a clean shell:\n'
    printf '  env -i HOME=%s bash -lc "command -v symoneural-cli"\n' "$HOME"
fi
exit "$rc"
