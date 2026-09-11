#!/usr/bin/env bash
# Copy this box's runtime configuration out of /etc/symoneural and into the repository's own
# gitignored run/config, so that /etc/symoneural can be deleted.
#
#     sudo ./scripts/adopt-runtime-config.sh plan     # what would move. NAMES ONLY.
#     sudo ./scripts/adopt-runtime-config.sh adopt    # copy it, mode 600, owned by the user
#     ./scripts/adopt-runtime-config.sh verify        # prove the API can see it without /etc
#
# WHY THIS EXISTS. `symoneural-api.service` took every surface switch and token from
# `/etc/symoneural/api.env`, attached through a drop-in that `systemctl cat` does not display,
# declared `ignore_errors=yes`. Delete the directory and the service still starts -- with
# accounts, coder, studio, project and dispatchos all silently off and no error anywhere. A
# stripped box that reports healthy is worse than one that refuses to boot.
#
# VALUES ARE NEVER PRINTED. Not by `plan`, not by `adopt`, not on failure. `docs/ops/EXPORTS.md`
# is explicit that a credential which has been displayed is spent, and this repo has already had
# a session-signing secret reach a transcript through a tool that printed what it was reading.
# Every report below is a count and a list of NAMES.
#
# VALUES ARE NEVER CHANGED. This copies bytes. If the API misbehaves afterwards the cause is
# unambiguously the plumbing, never the secret -- the same separation `scripts/migrate-api-env.sh`
# argues for at length, and for the same reason: two candidate causes and no way to tell them
# apart is not a debuggable state. Rotation is a separate operation, through
# `scripts/accounts-runtime.sh`, against a runtime already proven to work with the values it had.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
# The root calculation has been wrong four times in this repo and it fails silently, because
# the wrong parent is usually a directory that exists. Asserted, not assumed.
[ -f "$ROOT/backend/server.py" ] || { echo "repo root not found at $ROOT" >&2; exit 1; }

SRC=/etc/symoneural
DST="$ROOT/run/config"
PROG="$(basename "$0")"

# The account the service actually runs as, so an adopt performed under sudo leaves files the
# serving process can read. Hard-coding the invoking user would be wrong here: this script is
# meant to be run with sudo, and $USER under sudo is root.
OWNER="$(systemctl show symoneural-api.service -p User --value 2>/dev/null || true)"
OWNER="${OWNER:-${SUDO_USER:-$(id -un)}}"

names_in() { # file -- NAMES only, never values
    sed -n 's/^[[:space:]]*\(export[[:space:]]\+\)\?\([A-Za-z_][A-Za-z0-9_]*\)=.*/\2/p' "$1" 2>/dev/null | sort -u
}

case "${1:-plan}" in

plan)
    [ -d "$SRC" ] || { echo "$PROG: $SRC does not exist -- nothing to adopt."; exit 0; }
    echo "source:      $SRC"
    echo "destination: ${DST#"$ROOT"/}   (gitignored; a secret here cannot be committed)"
    echo "owner:       $OWNER"
    echo
    total=0
    for f in "$SRC"/*.env; do
        [ -f "$f" ] || continue
        n="$(names_in "$f" | wc -l)"
        total=$((total + n))
        printf '  %-24s %s name(s)\n' "$(basename "$f")" "$n"
        names_in "$f" | sed 's/^/      /'
    done
    echo
    echo "$total name(s) would be copied. No values were printed and none will be."
    ;;

adopt)
    [ -d "$SRC" ] || { echo "$PROG: $SRC does not exist -- nothing to adopt."; exit 0; }
    mkdir -p "$DST"
    copied=0
    for f in "$SRC"/*.env; do
        [ -f "$f" ] || continue
        dest="$DST/$(basename "$f")"
        if [ -e "$dest" ]; then
            # Never overwrite. A destination that already exists may be the newer of the two,
            # and this script cannot tell -- it may not read the values to compare them.
            echo "$PROG: $dest already exists; refusing to overwrite. Move it aside first." >&2
            exit 1
        fi
        # Copy, then lock down, then hand over -- in that order, so the file is never readable
        # by other users even for the instant between creation and chmod.
        install -m 600 -o "$OWNER" -g "$OWNER" "$f" "$dest"
        printf '  adopted %-24s %s name(s), mode 600, owner %s\n' \
            "$(basename "$f")" "$(names_in "$dest" | wc -l)" "$OWNER"
        copied=$((copied + 1))
    done
    chown "$OWNER:$OWNER" "$DST" 2>/dev/null || true
    chmod 700 "$DST"
    echo
    echo "$copied file(s) adopted into ${DST#"$ROOT"/}."
    echo "NOTHING has been deleted. Verify first:"
    echo "    ./scripts/$PROG verify"
    echo "Then $SRC may be removed."
    ;;

verify)
    # Proves the claim that matters: the API can see its configuration WITHOUT /etc. Done by
    # asking the loader, with the EnvironmentFile path deliberately not involved.
    [ -d "$DST" ] || { echo "$PROG: $DST does not exist -- run adopt first." >&2; exit 1; }
    cd "$ROOT/backend"
    python3 - <<'PY'
import os
import sys
# `backend/apps`, exactly as api.py:75 puts it there. Importing it any other way would test a
# different module resolution from the one production uses, which is the class of mistake that
# makes a green check meaningless.
sys.path.insert(0, "apps")
# A clean environment, so nothing that happens to be exported in this shell can make the test
# pass. This is the whole question: does the file alone carry the configuration?
for k in [k for k in os.environ if k.startswith(("SYM_", "SYMONEURAL_"))]:
    del os.environ[k]
from runtime.lib import runtimeconfig
names = runtimeconfig.load(warn=False)
bad = runtimeconfig.rejected()
print(f"  config dir: {runtimeconfig.config_dir()}")
print(f"  loaded {len(names)} name(s): {', '.join(sorted(names)) or '(none)'}")
if bad:
    print(f"  refused {len(bad)}: {', '.join(sorted(bad))}")
required = {"SYMONEURAL_SESSION_SECRET"}
missing = sorted(required - set(names))
if missing:
    print(f"  MISSING and required: {', '.join(missing)}")
    raise SystemExit(1)
print("  OK -- the API can read its configuration without /etc/symoneural.")
PY
    ;;

*)
    echo "usage: $PROG [plan|adopt|verify]" >&2
    exit 2
    ;;
esac
