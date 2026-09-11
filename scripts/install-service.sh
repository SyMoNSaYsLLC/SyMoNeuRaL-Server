#!/usr/bin/env bash
# DEPRECATED, 2026-09-09. Use `sudo ops/deploy/install-runtime.sh` instead.
#
# Install the SyMoNeuRaL API as a system service.
#
#     sudo ./scripts/install-service.sh    (from the repo root)
#
# After this the API starts on boot, restarts on crash, and is managed with systemctl
# rather than a shell script. It replaces symoneural.sh for anything production (that script stays for manual control).
#
# ## Why this refuses to run -- see ops/deploy/INSTALLERS.md for the full adjudication
#
# Commissioning found FOUR installers whose unit headers disagreed about which one owns them.
# This is the oldest and it is superseded in full: it renders the same
# ops/units/symoneural-api.service with the same sed substitution and installs it to the same path,
# but with no --dry-run, no backup, no rollback, and no check that the placeholder was
# actually substituted. `ops/deploy/install-runtime.sh` does all four and refuses rather than
# installing something wrong.
#
# It is not deleted, because deleting tracked content was not commissioning's call. It is
# stopped instead, because the standard being applied is that a second installer which still
# works is worse than one that is gone -- somebody follows the wrong header and gets a unit
# installed without a backup they could roll back to.
#
# Override only if there is a reason nobody has thought of:
#     sudo ./scripts/install-service.sh --i-know-this-is-deprecated
set -euo pipefail

if [ "${1:-}" != "--i-know-this-is-deprecated" ]; then
  cat >&2 <<'DEPRECATED'
REFUSING: scripts/install-service.sh is deprecated (2026-09-09).

Use the authoritative installer, which dry-runs, backs up, verifies the placeholder was
substituted, and rolls back on failure:

    sudo ops/deploy/install-runtime.sh --dry-run     # see what it would do
    sudo ops/deploy/install-runtime.sh

Note before you run it: install-runtime.sh also installs symoneural-deploy.service, which
has never been installed on this box. See ops/deploy/INSTALLERS.md.

For the unit repair commissioning identified specifically (StartLimit* sitting in [Service],
where systemd ignores it), use:

    sudo ops/deploy/commission-apply.sh --apply

To run this deprecated script anyway:
    sudo ./scripts/install-service.sh --i-know-this-is-deprecated
DEPRECATED
  exit 1
fi

HERE="$(cd "$(dirname "$0")" && pwd)"
DEMO="$(dirname "$HERE")"
UNIT=/etc/systemd/system/symoneural-api.service
ROTATE=/etc/logrotate.d/symoneural

[ "$(id -u)" -eq 0 ] || { echo "run me with sudo" >&2; exit 1; }

echo "installing unit -> $UNIT"
# The unit in the repo is a template: systemd cannot express a relative path, so the
# repo root is substituted at install time from where this script actually lives. That
# is what lets the checkout be cloned anywhere and still produce a correct unit.
. "$(dirname -- "${BASH_SOURCE[0]}")/lib/repo.sh"
sed "s|@@ROOT@@|$ROOT|g" "$ROOT/ops/units/symoneural-api.service" > "$UNIT.tmp"
install -m 644 -o root -g root "$UNIT.tmp" "$UNIT"
rm -f "$UNIT.tmp"
echo "  unit points at $ROOT"

# The app writes its own log alongside the journal; rotate it so a busy night cannot fill
# the disk the site is served from.
echo "installing logrotate -> $ROTATE"
cat > "$ROTATE" <<EOF
$DEMO/run/api.log $DEMO/run/governor.log {
    daily
    rotate 14
    size 20M
    compress
    delaycompress
    missingok
    notifempty
    copytruncate
    su google google
}
EOF
chmod 644 "$ROTATE"

# Anything started by hand has to go, or two processes fight over port 8800 and the GPU.
if [ -f "$DEMO/run/api.pid" ]; then
  echo "stopping hand-started instance"
  kill "$(cat "$DEMO/run/api.pid")" 2>/dev/null || true
  rm -f "$DEMO/run/api.pid"
fi
pkill -f "[p]ython3 $ROOT/backend/server.py" 2>/dev/null || true
sleep 1

systemctl daemon-reload
systemctl enable symoneural-api.service
systemctl restart symoneural-api.service

sleep 4
echo
systemctl --no-pager --lines=0 status symoneural-api.service || true
echo
if curl -sf --max-time 8 http://127.0.0.1:8800/api/status >/dev/null; then
  echo "API is answering on 127.0.0.1:8800"
else
  echo "API is NOT answering -- check: journalctl -u symoneural-api -n 50" >&2
  exit 1
fi

cat <<'EOF'

managing it from here:
  systemctl status symoneural-api      what it is doing
  systemctl restart symoneural-api     after changing api.py
  systemctl stop symoneural-api        take inference offline UNTIL THE NEXT BOOT ONLY
  journalctl -u symoneural-api -f      follow the log

a stop is not a hold, and this line used to imply it was: the unit is `enabled`, so a
plain `stop` evaporates at the next boot and the API comes back on its own. Commissioning
watched exactly that happen on 2026-09-09 -- a deliberate hold was in force, the box
rebooted, and the service started itself. For a hold that survives a reboot see
ops/deploy/SERVICE-HOLD.md; the short version is `systemctl disable --now`, or `mask` if it must
not be startable even by hand.
EOF
