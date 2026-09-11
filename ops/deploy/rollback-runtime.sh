#!/usr/bin/env bash
# Put the systemd units back the way they were, from a backup `ops/deploy/install-runtime.sh` took.
#
#   sudo ops/deploy/rollback-runtime.sh --list          which backups exist
#   sudo ops/deploy/rollback-runtime.sh                 restore the most recent backup
#   sudo ops/deploy/rollback-runtime.sh <backup-dir>    restore a specific one
#   sudo ops/deploy/rollback-runtime.sh --dry-run       print what would be restored
#
# `install-runtime.sh` already rolls back BY ITSELF when its health check fails, and that is
# the path that matters during a deployment. This script is for the other case: the install
# succeeded, health passed, and an hour later something is wrong anyway. That is a decision a
# person makes, so it is a separate command rather than an automatic behaviour.
#
# ## It restores units, and deliberately not much else
#
# Unit files, the api drop-in directory, and the environment files -- because those are what
# `install-runtime.sh` changes. It does NOT restore the repository, the model, the engine or
# the gateway binary: none of those are touched by an install, and rolling a service back to
# a previous unit while silently reverting artifacts would make the two disagree.
#
# ## Restoring a unit that names /yocto is ALLOWED here, and is warned about loudly
#
# The whole point of a rollback is to get back to a state that worked, and the state before
# the migration pointed at /yocto. Refusing on principle would make the rollback useless in
# the one situation it exists for. So it restores, and says plainly that the runtime boundary
# is now violated and `ops/deploy/install-runtime.sh` is how to get back.
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
UNIT_DIR=/etc/systemd/system
BACKUP_ROOT=/etc/symoneural/unit-backups
UNITS=(symoneural-api symoneural-gateway symoneural-deploy)
HEALTH_LOCAL=http://127.0.0.1:8800/api/status

DRY=0; WANT=""
for a in "$@"; do
    case "$a" in
        --dry-run) DRY=1 ;;
        --list)
            echo "backups under $BACKUP_ROOT:"
            sudo -n ls -1 "$BACKUP_ROOT" 2>/dev/null | sort | sed 's/^/  /' || echo "  (none, or need sudo)"
            exit 0 ;;
        -*) echo "unknown argument: $a" >&2; exit 2 ;;
        *)  WANT="$a" ;;
    esac
done

say()  { printf '  %s\n' "$*"; }
step() { printf '\n== %s ==\n' "$*"; }
run()  { if [ "$DRY" -eq 1 ]; then printf '  DRY  %s\n' "$*"; else eval "$@"; fi; }

if [ "$DRY" -eq 0 ] && [ "$(id -u)" -ne 0 ]; then
    echo "This needs root. Re-run with sudo, or use --dry-run." >&2; exit 1
fi

# Pick the backup: the argument, else the pointer install-runtime.sh wrote, else the newest
# directory by name (they are timestamped, so lexical order is chronological).
BK="$WANT"
if [ -z "$BK" ] && [ -f /etc/symoneural/.last-unit-backup ]; then
    BK="$(cat /etc/symoneural/.last-unit-backup 2>/dev/null)"
    [ -n "$BK" ] && say "using the pointer left by install-runtime.sh"
fi
if [ -z "$BK" ]; then
    BK="$BACKUP_ROOT/$(ls -1 "$BACKUP_ROOT" 2>/dev/null | sort | tail -1)"
    say "using the newest backup by timestamp"
fi
[ -d "$BK" ] || { echo "no such backup directory: ${BK:-<none found>}" >&2; exit 1; }
step "restoring from $BK"
ls -1 "$BK" | sed 's/^/  /'

RESTORED=0
for u in "${UNITS[@]}"; do
    if [ -f "$BK/$u.service" ]; then
        run "install -o root -g root -m 0644 '$BK/$u.service' '$UNIT_DIR/$u.service'"
        say "restored $u.service"; RESTORED=1
        if grep -qE '^[^#]*=.*/yocto' "$BK/$u.service" 2>/dev/null; then
            say "  WARNING: this unit references /yocto. The runtime boundary is now violated."
        fi
    else
        say "no backup of $u.service in this directory -- left as installed"
    fi
done
[ -d "$BK/symoneural-api.service.d" ] && run "cp -a '$BK/symoneural-api.service.d' '$UNIT_DIR/'" \
    && say "restored api.service.d/"
for f in api.env deploy.env; do
    [ -f "$BK/$f" ] && run "install -o root -g root -m 0600 '$BK/$f' '/etc/symoneural/$f'" \
        && say "restored $f"
done

[ "$RESTORED" -eq 0 ] && { echo "nothing was restored" >&2; exit 1; }

step "reload and restart"
run "systemctl daemon-reload"
run "systemctl restart symoneural-gateway"
run "systemctl restart symoneural-api"

step "health"
if [ "$DRY" -eq 1 ]; then say "DRY  would poll $HEALTH_LOCAL"; else
    OK=0
    for i in $(seq 1 30); do
        code="$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "$HEALTH_LOCAL" 2>/dev/null)"
        [ "$code" = "200" ] && { say "local health 200 after ~$((i*2))s"; OK=1; break; }
        sleep 2
    done
    [ "$OK" -eq 1 ] || { echo "  health did NOT recover after the rollback -- investigate:" >&2
                         echo "    journalctl -u symoneural-api -n 60 --no-pager" >&2; exit 1; }
fi

echo
say "Rolled back. To migrate forward again:  sudo ops/deploy/install-runtime.sh"
