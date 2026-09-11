#!/usr/bin/env bash
# Install or migrate the SyMoNeuRaL runtime so it serves from THIS repository and nothing else.
#
#   sudo ops/deploy/install-runtime.sh --dry-run     print every action, change nothing
#   sudo ops/deploy/install-runtime.sh               install, restart, verify, roll back on failure
#   sudo ops/deploy/install-runtime.sh --no-restart  install units only; do not touch running services
#
# ## What this replaces
#
# The migration off /yocto was first done by hand. Hand-run commands are not a deployment:
# they cannot be reviewed, repeated on another box, or rolled back. Garrett, 2026-08-26:
# *"No final production state may rely on commands that were performed manually but not
# represented in the repository."* This script IS that representation, and running it on an
# already-migrated box is a no-op that says so.
#
# ## The boundary
#
# `/yocto` is an authorized BUILD environment -- SDK, toolchains, sysroots, BitBake, caches.
# What is forbidden is a live component REQUIRING it. This script installs only files that
# live under this repository and under /etc, never anything that points into /yocto, and
# `ops/deploy/verify-runtime.sh` is run at the end to prove it rather than assert it.
#
# ## Idempotent, and atomic where it matters
#
# Unit files are rendered to a temporary file and `install`ed over the target, which is an
# atomic rename on the same filesystem -- there is no instant at which a half-written unit
# exists. Re-running with no changes reports "unchanged" and does not restart anything, so
# this is safe to run from a provisioning step.
#
# ## Rollback
#
# Every run backs the current units and environment files up to a timestamped directory under
# /etc/symoneural/unit-backups/ FIRST. If the health check fails after the restart, the backup
# is restored and the services are restarted again, automatically, before this script exits
# non-zero. `ops/deploy/rollback-runtime.sh` does the same thing by hand for a later regret.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
[ -f "$ROOT/backend/server.py" ] || { echo "repo root not found at $ROOT" >&2; exit 1; }

UNITS=(symoneural-api symoneural-gateway symoneural-deploy)
UNIT_DIR=/etc/systemd/system
BACKUP_ROOT=/etc/symoneural/unit-backups
ENV_FILES=(/etc/symoneural/api.env /etc/symoneural/deploy.env)
HEALTH_LOCAL=http://127.0.0.1:8800/api/status
HEALTH_PUBLIC=https://symoneural.com/api/status

DRY=0; RESTART=1
for a in "$@"; do
    case "$a" in
        --dry-run)    DRY=1 ;;
        --no-restart) RESTART=0 ;;
        *) echo "unknown argument: $a" >&2; exit 2 ;;
    esac
done

say()  { printf '  %s\n' "$*"; }
step() { printf '\n== %s ==\n' "$*"; }
run()  { if [ "$DRY" -eq 1 ]; then printf '  DRY  %s\n' "$*"; else eval "$@"; fi; }

if [ "$DRY" -eq 0 ] && [ "$(id -u)" -ne 0 ]; then
    echo "This needs root to write $UNIT_DIR. Re-run with sudo, or use --dry-run." >&2
    exit 1
fi

# ---------------------------------------------------------------- preflight
#
# ## Existence was never the question
#
# This block used to ask whether a file was present at a path written here. That check passed
# on 2026-08-26 while naming the wrong gateway binary, and would have gone on passing forever:
# a promotion leaves the superseded artifact on disk, so "a file exists there" is true of both
# the right one and the wrong one. The paths now come from `ops/manifests/*.json` and the
# artifacts are checked by hash, so installing the wrong build is a refusal rather than a
# success. No hash is written in this file -- the manifest is the only place one lives.
step "preflight: the canonical tree has what the units will point at"
. "$ROOT/ops/manifests/artifact.sh"
PREFLIGHT_OK=1
need() {  # need <relative path> <what it is>
    if [ -e "$ROOT/$1" ]; then say "OK      $1  ($2)"
    else say "MISSING $1  ($2)"; PREFLIGHT_OK=0; fi
}

# manifested <manifest.json> <what it is> -- check identity, not presence.
#
# On a mismatch it prints the custody bundle and the exact restore command from the manifest,
# because "the installer knows how to obtain the right artifact" is the difference between a
# refusal you can act on and one you have to research. It quotes the manifest's own `restore`
# string rather than composing a command here; it does not RUN it. Extracting a bundle over a
# live engine is a binary replacement and is nobody's idea of a preflight check.
manifested() {
    local mf="$1" what="$2" out st
    if ! artifact_load "$mf"; then
        say "MISSING ops/manifests/$mf  ($what) -- the manifest itself is unreadable"
        PREFLIGHT_OK=0; return
    fi
    out="$(artifact_verify)"; st=$?
    case "$st" in
        0) say "OK      $ART_REL  ($what, matches $mf)" ;;
        2) say "MISSING $ART_REL  ($what)"; PREFLIGHT_OK=0 ;;
        *) say "WRONG   $ART_REL  ($what) does not match $mf:"
           printf '          %s\n' "$out"
           PREFLIGHT_OK=0 ;;
    esac
    if [ "$st" -ne 0 ] && [ -n "${ART_RESTORE:-}" ]; then
        say "        a verified copy is kept at ${ART_BUNDLE#$ROOT/}"
        say "        restore it with:  $ART_RESTORE"
    fi
}

need backend/server.py                                          "the API"
need scripts/deploy.sh                                       "the publisher"
need scripts/gpu-governor.sh                                 "governor, called by ExecStartPre"
need site                                                    "what deploy publishes"
manifested gateway-build.json                                "gateway binary"
manifested llm-engine.json                                   "inference engine runtime tree"
# The chat model is 4.6 GB and hashing it would add ten seconds to every run, including
# --dry-run. Its PATH still comes from the manifest, which is the part that goes stale; the
# full hash is one command away and is named here rather than assumed.
if artifact_load llm-chat-model.json; then
    need "$ART_REL"                                          "chat model (hash: ops/manifests/regenerate.sh --check llm-chat-model.json)"
else
    say "MISSING ops/manifests/llm-chat-model.json"; PREFLIGHT_OK=0
fi
for u in "${UNITS[@]}"; do need "ops/$u.service" "unit template"; done
if [ "$PREFLIGHT_OK" -eq 0 ]; then
    echo >&2
    echo "Refusing to install: the canonical tree is not the verified one (see above)." >&2
    echo "A unit pointing at a path that does not exist fails at boot, not now -- and a unit" >&2
    echo "pointing at the WRONG artifact does not fail at all, which is worse." >&2
    echo >&2
    echo "If the gateway line reports MISSING: the rename from symon-gateway to" >&2
    echo "symoneural-gateway is half-complete, and these two still write or check the OLD name:" >&2
    echo "  ops/deploy/build-gateway.sh        OUT=\$SRC/target/release/symon-gateway, and it writes" >&2
    echo "                              ops/manifests/gateway-build.json with that path too --" >&2
    echo "                              so building the gateway RE-STALES the manifest. Run" >&2
    echo "                              ops/manifests/regenerate.sh --check afterwards; the" >&2
    echo "                              unit cross-check catches it." >&2
    echo "  scripts/install-gateway.sh  BIN=\$ROOT/.../release/symon-gateway" >&2
    echo "The unit, the manifest and this script use the new name. apps/test_gateway_unit.py is" >&2
    echo "red on exactly this. Finishing that rename is a separate change; it is not something" >&2
    echo "this script should paper over by accepting whichever file happens to be there." >&2
    exit 1
fi

# Identity is settled above. What is left is the shape of the file: the gateway binary must be
# an independent regular file, not a hardlink into a build tree and never a symlink into
# /yocto. `artifact_load gateway-build.json` above left ART_ABS naming it.
artifact_load gateway-build.json
GW="$ART_ABS"
if [ -L "$GW" ]; then say "REFUSING: the gateway binary is a symlink"; exit 1; fi
case "$(readlink -f "$GW")" in *yocto*) say "REFUSING: the gateway binary resolves into /yocto"; exit 1;; esac
if ldd "$GW" 2>/dev/null | grep -q '/yocto'; then say "REFUSING: gateway links a library from /yocto"; exit 1; fi
say "gateway artifact: $(stat -c '%s bytes, st_nlink=%h' "$GW"), no /yocto linkage"

# ---------------------------------------------------------------- render
step "render unit templates against ROOT=$ROOT"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
CHANGED=()
for u in "${UNITS[@]}"; do
    sed "s|@@ROOT@@|$ROOT|g" "$ROOT/ops/$u.service" > "$TMP/$u.service"
    if grep -q '@@[A-Z_]*@@' "$TMP/$u.service"; then
        say "REFUSING: unsubstituted placeholder in $u.service"; exit 1
    fi
    if grep -qE '^[^#]*=.*/yocto' "$TMP/$u.service"; then
        say "REFUSING: rendered $u.service still references /yocto in a directive"; exit 1
    fi
    if [ -f "$UNIT_DIR/$u.service" ] && cmp -s "$TMP/$u.service" "$UNIT_DIR/$u.service"; then
        say "unchanged  $u.service"
    else
        say "will write $u.service"; CHANGED+=("$u")
    fi
done

if [ "${#CHANGED[@]}" -eq 0 ]; then
    say "every unit is already correct -- nothing to install."
else
    # ------------------------------------------------------------ backup
    step "backup"
    STAMP="$(date +%Y%m%d-%H%M%S)"; BK="$BACKUP_ROOT/$STAMP"
    run "install -d -m 0700 -o root -g root '$BK'"
    for u in "${UNITS[@]}"; do
        [ -f "$UNIT_DIR/$u.service" ] && run "cp -a '$UNIT_DIR/$u.service' '$BK/'"
    done
    [ -d "$UNIT_DIR/symoneural-api.service.d" ] && run "cp -a '$UNIT_DIR/symoneural-api.service.d' '$BK/'"
    for f in "${ENV_FILES[@]}"; do [ -f "$f" ] && run "cp -a '$f' '$BK/'"; done
    run "chmod -R go-rwx '$BK'"
    say "backup: $BK"
    [ "$DRY" -eq 0 ] && echo "$BK" > /etc/symoneural/.last-unit-backup

    # ------------------------------------------------------------ install
    step "install"
    for u in "${CHANGED[@]}"; do
        # `install` replaces atomically and sets ownership/mode deliberately rather than
        # inheriting whatever the temp file had.
        run "install -o root -g root -m 0644 '$TMP/$u.service' '$UNIT_DIR/$u.service'"
        say "installed $u.service"
    done
    run "systemctl daemon-reload"
    say "daemon-reload done"
fi

# ---------------------------------------------------------------- restart
if [ "$RESTART" -eq 0 ]; then
    step "restart skipped (--no-restart)"
elif [ "${#CHANGED[@]}" -eq 0 ]; then
    step "restart skipped (nothing changed)"
else
    step "controlled restart"
    # Gateway first: it is a thin proxy in front of the API, so restarting it while the API is
    # still up is the shorter outage. The API second, because it is the slow one.
    run "systemctl restart symoneural-gateway"
    run "systemctl restart symoneural-api"

    step "health"
    OK=0
    if [ "$DRY" -eq 1 ]; then say "DRY  would poll $HEALTH_LOCAL then $HEALTH_PUBLIC"; OK=1; else
        for i in $(seq 1 30); do
            code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "$HEALTH_LOCAL" 2>/dev/null)"
            [ "$code" = "200" ] && { say "local $HEALTH_LOCAL -> 200 after ~$((i*2))s"; OK=1; break; }
            sleep 2
        done
        if [ "$OK" -eq 1 ]; then
            pub="$(curl -s -o /dev/null -w '%{http_code}' --max-time 15 "$HEALTH_PUBLIC" 2>/dev/null)"
            say "public $HEALTH_PUBLIC -> $pub"
            [ "$pub" = "200" ] || { say "public health is not 200"; OK=0; }
        else
            say "local health never reached 200"
        fi
    fi

    # ------------------------------------------------------------ rollback
    if [ "$OK" -eq 0 ]; then
        step "HEALTH FAILED -- rolling back automatically"
        for u in "${UNITS[@]}"; do
            [ -f "$BK/$u.service" ] && install -o root -g root -m 0644 "$BK/$u.service" "$UNIT_DIR/$u.service" \
                && say "restored $u.service"
        done
        [ -d "$BK/symoneural-api.service.d" ] && cp -a "$BK/symoneural-api.service.d" "$UNIT_DIR/"
        systemctl daemon-reload
        systemctl restart symoneural-gateway || true
        systemctl restart symoneural-api || true
        sleep 5
        back="$(curl -s -o /dev/null -w '%{http_code}' --max-time 10 "$HEALTH_LOCAL" 2>/dev/null)"
        say "after rollback, local health -> $back"
        echo >&2
        echo "INSTALL FAILED AND WAS ROLLED BACK. Units restored from $BK." >&2
        echo "Nothing further was changed. Investigate with:" >&2
        echo "  journalctl -u symoneural-api -n 60 --no-pager" >&2
        exit 1
    fi
fi

# ---------------------------------------------------------------- verify
step "verify the runtime boundary"
if [ "$DRY" -eq 1 ]; then
    say "DRY  would run ops/deploy/verify-runtime.sh"
else
    if "$ROOT/ops/deploy/verify-runtime.sh" --quiet; then
        say "ops/deploy/verify-runtime.sh: clean"
    else
        say "ops/deploy/verify-runtime.sh REPORTED A VIOLATION -- see above"
        exit 1
    fi
fi

echo
printf '\033[32mRUNTIME INSTALLED\033[0m  root=%s\n' "$ROOT"
