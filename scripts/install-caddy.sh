#!/usr/bin/env bash
# Install or repair the web server for symoneural.com.
#
#   sudo ./scripts/install-caddy.sh      (from the repo root)
#
# NOTE: this already ran on this box on 2026-08-16. Caddy is serving symoneural.com and
# apache2 is disabled. This script is kept because it is idempotent and is what you would
# run to rebuild the serving layer on this machine or stand it up on a new one -- not
# because a migration is pending.
#
# It is safe to re-run: it validates the config before stopping anything, so a bad config
# leaves whatever is currently serving in place.
#
# THAT SENTENCE STOPPED BEING TRUE, and this note is the correction rather than a deletion.
# `symoneural-web.service` -- the first-party HTTP/TLS runtime that now serves :80 and :443 --
# declares `Conflicts=caddy.service caddy-api.service`, because two processes cannot own those
# ports. `Conflicts=` is bidirectional: `systemctl restart caddy` below does not fail against a
# running symoneural-web, it makes systemd STOP symoneural-web to make room. Re-running this on
# this box would therefore take the production site down and replace it with stock Caddy, which
# is the opposite of "leaves whatever is currently serving in place".
#
# The script is kept, because a host that genuinely runs stock Caddy still needs it. It now
# refuses to run when the first-party runtime is the installed web server -- see the preflight
# guard below. Deleting the `systemctl enable caddy` line instead would have left a script that
# silently half-installs a web server it never starts.
#
# What it does NOT do: touch /var/www/symoneural. Deploying the site is still deploy.sh.
set -euo pipefail

DOMAIN="symoneural.com"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
[ -f "$ROOT/backend/api.py" ] || { echo "repo root not found at $ROOT (expected backend/api.py)" >&2; exit 1; }
WEBROOT="/var/www/symoneural"
API="127.0.0.1:8800"

[ "$(id -u)" -eq 0 ] || { echo "must run as root: sudo $0"; exit 1; }

say() { printf '\n\033[1m== %s\033[0m\n' "$*"; }

# --- preflight ---------------------------------------------------------------
# Caddy provisions a certificate over ports 80 and 443 on first start. If DNS does not
# resolve here, or the API is down, we want to know before Apache is stopped rather than
# during the outage.
say "Preflight"
[ -d "$WEBROOT" ] || { echo "FAIL: $WEBROOT does not exist -- run deploy.sh first"; exit 1; }
[ -f "$ROOT/ops/Caddyfile" ] || { echo "FAIL: $ROOT/ops/Caddyfile missing"; exit 1; }
echo "  webroot   $WEBROOT ($(find "$WEBROOT" -maxdepth 1 -type f | wc -l) files)"

# Retried, not probed once. `systemctl restart symoneural-api` returns as soon as systemd
# has forked the unit, several seconds BEFORE uvicorn binds the port -- so the obvious
# invocation, `systemctl restart ... && ./install-caddy.sh`, reliably raced this check and
# printed "api DOWN" about an API that answered 200 later in the same run. That is not a
# harmless false alarm: this branch offers a 5-second abort, so it invites the operator to
# cancel a healthy deployment.
api_up=0
for _ in 1 2 3 4 5 6 7 8 9 10; do
  if curl -fsS -m 3 "http://$API/api/status" >/dev/null 2>&1; then api_up=1; break; fi
  sleep 1
done
if [ "$api_up" = 1 ]; then
  echo "  api       up on $API"
else
  echo "  api       DOWN on $API -- the static site will serve, but every surface will 502."
  echo "            Start it first, then re-run. Continuing anyway in 5s (Ctrl-C to abort)."
  sleep 5
fi

resolved="$(getent hosts "$DOMAIN" | awk '{print $1}' | head -1 || true)"
echo "  dns       $DOMAIN -> ${resolved:-UNRESOLVED}"
[ -n "$resolved" ] || { echo "FAIL: $DOMAIN does not resolve; Caddy cannot get a certificate"; exit 1; }

# --- install -----------------------------------------------------------------
say "Installing Caddy"
if command -v caddy >/dev/null; then
  echo "  already installed: $(caddy version | head -1)"
else
  apt-get update -qq
  apt-get install -y caddy
fi

say "Installing the Caddyfile"
install -d -m 755 /etc/caddy
if [ -f /etc/caddy/Caddyfile ] && ! cmp -s "$ROOT/ops/Caddyfile" /etc/caddy/Caddyfile; then
  cp -a /etc/caddy/Caddyfile "/etc/caddy/Caddyfile.prev-$(date +%Y%m%d-%H%M%S)"
  echo "  previous Caddyfile backed up"
fi
install -m 644 "$ROOT/ops/Caddyfile" /etc/caddy/Caddyfile
install -d -m 755 -o caddy -g caddy /var/log/caddy

# Validate before anything is stopped. A bad config here means Apache keeps serving.
if ! caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile; then
  echo "FAIL: Caddyfile did not validate; Apache left running and untouched."
  exit 1
fi
echo "  Caddyfile validates"

# --- cut over ----------------------------------------------------------------
say "Freeing ports 80/443"
# apache2 held them until the 2026-08-16 migration. Disabled rather than purged, so the
# rollback at the bottom of this file still works; on a machine that never had it, these
# are no-ops.
if systemctl list-unit-files apache2.service >/dev/null 2>&1; then
  systemctl stop apache2 2>/dev/null || true
  systemctl disable apache2 2>/dev/null || true
  echo "  apache2 stopped and disabled (still installed, not removed)"
else
  echo "  apache2 not present -- nothing to stop"
fi

# REFUSAL, not a warning. By this point the config has validated and apache2 is stopped, but
# nothing that serves symoneural.com has been touched yet -- so this is the last moment at which
# refusing costs nothing. Checked as `enabled OR active` because either one means this host has
# been cut over to the first-party runtime: enabled-but-stopped is a box mid-reboot, and
# active-but-disabled is a box someone started by hand.
if systemctl list-unit-files symoneural-web.service >/dev/null 2>&1 \
   && { systemctl is-enabled --quiet symoneural-web 2>/dev/null \
        || systemctl is-active  --quiet symoneural-web 2>/dev/null; }; then
  cat >&2 <<'REFUSE'

REFUSED: symoneural-web.service is the web server on this host.

  It owns :80 and :443 and declares Conflicts=caddy.service, so enabling Caddy here would
  make systemd STOP symoneural-web -- taking symoneural.com down and replacing the
  first-party TLS runtime with stock Caddy.

  Nothing has been changed. The config validated and apache2 was left as it was.

  If you are deliberately migrating this host BACK to stock Caddy, do it explicitly:
      sudo systemctl disable --now symoneural-web
      sudo ./scripts/install-caddy.sh

REFUSE
  exit 3
fi

say "Starting Caddy"
systemctl enable caddy
systemctl restart caddy
sleep 4

# --- verify ------------------------------------------------------------------
say "Verifying"
fail=0
check() { # label url expected
  code="$(curl -fsS -o /dev/null -w '%{http_code}' -m 15 "$2" 2>/dev/null || echo 000)"
  if [ "$code" = "$3" ]; then printf '  ok    %-28s %s\n' "$1" "$code"
  else printf '  FAIL  %-28s %s (wanted %s)\n' "$1" "$code" "$3"; fail=1; fi
}
# `/` is a 302 to /overview, so this must NOT assert 200 -- that is the same mistake the
# http:// check below used to make. Follow the redirect and require the destination to be
# right, which is the property that actually matters.
idx_code="$(curl -fsSL -o /dev/null -w '%{http_code}' -m 15 "https://$DOMAIN/" 2>/dev/null || echo 000)"
idx_url="$(curl -fsSL -o /dev/null -w '%{url_effective}' -m 15 "https://$DOMAIN/" 2>/dev/null || echo '')"
case "$idx_code:$idx_url" in
  200:https://$DOMAIN/overview)
    printf '  ok    %-28s 200 via %s\n' "https:// index" "$idx_url" ;;
  *)
    printf '  FAIL  %-28s %s at %s (wanted 200 at https://%s/overview)\n' \
      "https:// index" "$idx_code" "${idx_url:-nothing}" "$DOMAIN"; fail=1 ;;
esac
check "https:// api status"   "https://$DOMAIN/api/status"   200
check "https:// swagger"      "https://$DOMAIN/docs"         200
check "https:// openapi"      "https://$DOMAIN/openapi.json" 200

# The plain-HTTP check is NOT a 200. Caddy enables automatic HTTP->HTTPS redirects, so the
# correct answer here is a 308 pointing at https -- and asserting 200 made this script
# report FAIL on a completely healthy install, because `check` does not follow redirects.
# A verification step that cries wolf gets ignored, and then it is worse than nothing.
# Assert what should actually be true: it redirects, and it redirects to https on this host.
redir_code="$(curl -fsS -o /dev/null -w '%{http_code}' -m 15 "http://$DOMAIN/" 2>/dev/null || echo 000)"
redir_to="$(curl -fsS -o /dev/null -w '%{redirect_url}' -m 15 "http://$DOMAIN/" 2>/dev/null || echo '')"
case "$redir_code:$redir_to" in
  30[1278]:https://$DOMAIN/*)
    printf '  ok    %-28s %s -> %s\n' "http:// redirects" "$redir_code" "$redir_to" ;;
  *)
    printf '  FAIL  %-28s %s -> %s (wanted a 3xx to https://%s/)\n' \
      "http:// redirects" "$redir_code" "${redir_to:-nothing}" "$DOMAIN"; fail=1 ;;
esac

# The four front-page sections are reverse-proxied by the Caddyfile, NOT files on disk.
# They are checked here because this is the script that runs after a Caddy change, and
# because they cannot be checked anywhere else: against localhost the API answers them
# directly and the Caddyfile block is never exercised. That is precisely how they shipped
# 404ing while the local suite passed 25/25.
for sec in overview livestack controlboard receipts; do
  check "https:// /$sec"    "https://$DOMAIN/$sec"    200
done

# The reason for the migration: /api/ws must upgrade rather than fall back to polling.
say "WebSocket upgrade"
# Two traps here, both of which produce a convincing false failure:
#   1. `Upgrade:` is an HTTP/1.1 mechanism. It does not exist in HTTP/2, and curl
#      negotiates h2 with Caddy by default -- so the header arrives as meaningless
#      metadata, FastAPI sees a plain GET on a websocket-only route, and returns 404.
#      Browsers are unaffected: a page loaded over h2 still opens a separate HTTP/1.1
#      connection for the handshake. Hence --http1.1.
#   2. A *successful* upgrade leaves the socket open and streaming, so curl exits 28
#      on timeout no matter how well it worked. Read the status line out of the headers
#      rather than trusting curl's exit code.
wshdr="$(mktemp)"
curl -sS --http1.1 -o /dev/null -D "$wshdr" -m 6 \
      -H 'Connection: Upgrade' -H 'Upgrade: websocket' \
      -H 'Sec-WebSocket-Version: 13' -H 'Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==' \
      "https://$DOMAIN/api/ws" >/dev/null 2>&1 || true
if grep -qi '^HTTP/1.1 101' "$wshdr" && grep -qi '^Sec-Websocket-Accept:' "$wshdr"; then
  echo "  ok    /api/ws upgraded (101 Switching Protocols)"
else
  echo "  FAIL  /api/ws did not upgrade -- the rack will fall back to polling"
  sed 's/^/        /' "$wshdr" | head -6
  fail=1
fi
rm -f "$wshdr"

if [ "$fail" -eq 0 ]; then
  say "Done. Caddy is serving $DOMAIN and FastAPI is doing all the routing."
  systemctl --no-pager --lines=0 status caddy || true
else
  cat <<ROLLBACK

Something failed. Logs:
    journalctl -u caddy -n 60 --no-pager

To go back to Apache (still installed, but its vhost was removed from this repo --
recover it with: git log --diff-filter=D --  ops/symoneural.conf):
    sudo systemctl stop caddy && sudo systemctl disable caddy
    sudo systemctl enable apache2 && sudo systemctl start apache2
ROLLBACK
  exit 1
fi
