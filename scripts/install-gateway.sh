#!/usr/bin/env bash
# Install the SyMoNeuRaL HTTP gateway as a system service.
#
#     sudo ./scripts/install-gateway.sh    (from the repo root)
#
# After this the gateway starts on boot and restarts on crash, the same way the API does.
# It does NOT touch Caddy; run `sudo systemctl reload caddy` yourself after the Caddyfile is
# in place, so that the two changes fail independently and are diagnosable apart.
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
UNIT=/etc/systemd/system/symoneural-gateway.service

[ "$(id -u)" -eq 0 ] || { echo "run me with sudo" >&2; exit 1; }
[ -f "$ROOT/backend/api.py" ] || { echo "repo root not found at $ROOT (expected backend/api.py)" >&2; exit 1; }

# ---------------------------------------------------------------- which binary
#
# From the manifest, not from a literal here. This line read
# `.../target/release/symon-gateway` and went on doing so after the 2026-08-26 rename, so this
# script would have installed a unit whose ExecStart names `symoneural-gateway` while
# refusing-or-not based on whether the SUPERSEDED file existed. Both were on disk, so the
# guard on the next block passed while guarding the wrong file -- which is the exact thing
# that guard was added to prevent.
#
# `ops/manifests/artifact.sh` is the only reader of the manifests; see its header for why a
# path repeated across scripts is what went stale in the first place.
. "$ROOT/ops/manifests/artifact.sh"
# `set -e` is on, so the status has to be captured rather than tested in place, or a failed
# load aborts at the assignment and the message below is never printed.
if artifact_load gateway-build.json; then LOADED=1; else LOADED=0; fi
[ "$LOADED" -eq 1 ] || { echo "cannot read ops/manifests/gateway-build.json -- it names the binary to install" >&2; exit 1; }
[ "$ART_ROOT" = "$ROOT" ] || { echo "artifact.sh resolves to $ART_ROOT, not $ROOT; refusing to install another checkout's artifact" >&2; exit 1; }
BIN="$ART_ABS"

# Refuse rather than install a unit that will crash-loop on ENOENT. Restart=always means a
# missing binary is five restarts and then a silent dead unit, which is a poor way to find
# out you forgot to build.
if [ ! -x "$BIN" ]; then
  echo "gateway binary not found at $BIN" >&2
  echo "build it first:  cd $ROOT/backend/apps/gateway && cargo build --release" >&2
  exit 1
fi

echo "installing unit -> $UNIT"
sed "s|@@ROOT@@|$ROOT|g" "$ROOT/ops/symoneural-gateway.service" > "$UNIT.tmp"
install -m 644 -o root -g root "$UNIT.tmp" "$UNIT"
rm -f "$UNIT.tmp"
echo "  unit points at $ROOT"

# Anything started by hand has to go, or two processes fight over port 8000.
#
# Matched on /proc/<pid>/exe -- the kernel's resolved path to the running image -- and NOT on
# the command line. This used to be `pkill -x -f "$BIN"`, which missed the very case the line
# above describes: a gateway started by hand from the repo root has the command line
# `./backend/apps/gateway/target/release/symon-gateway`, and -x demands the pattern EQUAL the
# command line, so an absolute pattern never matches a relative invocation. Found live on this
# box, holding :8000 while the unit sat in a 203/EXEC restart loop.
#
# That miss is worse than it sounds, because it makes this script's own healthcheck lie: the
# unit would fail to bind, crash-loop, and `curl /healthz` at the bottom would still return 200
# -- answered by the orphan -- so the install reports success over a dead unit. A check that can
# pass without the work being done is the failure mode this repo keeps producing.
#
# /proc/<pid>/exe cannot match an editor, a build, or the shell running this script, because
# their executable is vim/cargo/bash. That was the reason for the original `-f`, and a bare
# `pkill -f` on this path once killed the invoking shell (an unexplained exit 144); resolving
# the image sidesteps both problems rather than trading one for the other.
#
# ## THE `pgrep` PRE-FILTER IS GONE, AND MUST NOT COME BACK
#
# It was `pgrep -x symon-gateway`. `-x` matches `comm`, and the kernel caps `comm` at 15
# characters (TASK_COMM_LEN). `symoneural-gateway` is 18, so the live gateway's `comm` is
# `symoneural-gate` -- measured on this box, pid 1877. Renaming the literal to the new binary
# name would therefore have matched NOTHING, silently, and the "obvious" fix would have
# disabled the orphan-killer entirely while looking like it had completed the rename.
# `symoneural-gate` would work and is a landmine: it is a truncation, not a name, and the next
# person to correct it "back" breaks this again.
#
# So the loop walks /proc directly and compares resolved images, which is what the paragraph
# above already argued the check should be. `pgrep` was only ever a cheap pre-filter, and
# there is no spelling of it that is correct here.
BIN_REAL="$(readlink -f "$BIN")"
for procdir in /proc/[0-9]*; do
  # readlink needs root for another user's pid; we are root, checked above.
  [ "$(readlink -f "$procdir/exe" 2>/dev/null || true)" = "$BIN_REAL" ] || continue
  pid="${procdir#/proc/}"
  # Never the unit's own process: systemctl restart below owns that one, and killing it here
  # would race the restart.
  [ "$pid" = "$(systemctl show -p MainPID --value symoneural-gateway.service 2>/dev/null)" ] && continue
  echo "  stopping hand-started gateway (pid $pid) holding the port"
  kill "$pid" 2>/dev/null || true
done
sleep 1

# Whatever we killed, the port has to actually be free before systemctl tries to bind, or the
# restart below fails on EADDRINUSE and Restart=always turns that into a crash loop.
for _ in $(seq 20); do
  ss -lnt 2>/dev/null | grep -q '127\.0\.0\.1:8000 ' || break
  sleep 0.5
done
if ss -lnt 2>/dev/null | grep -q '127\.0\.0\.1:8000 '; then
  echo "port 8000 is still held by something this script did not start:" >&2
  ss -lntp 2>/dev/null | grep '127\.0\.0\.1:8000 ' >&2
  echo "free it before installing, or the unit will crash-loop on EADDRINUSE" >&2
  exit 1
fi

systemctl daemon-reload
systemctl enable symoneural-gateway.service
systemctl restart symoneural-gateway.service

sleep 2
echo
systemctl --no-pager --lines=0 status symoneural-gateway.service || true
echo

# Health, then a real proxied request. The first proves the process is up; only the second
# proves it can reach the API, and they fail for different reasons.
if ! curl -sf --max-time 8 http://127.0.0.1:8000/healthz >/dev/null; then
  echo "gateway is NOT answering on :8000 -- check: journalctl -u symoneural-gateway -n 50" >&2
  exit 1
fi
echo "gateway is answering on 127.0.0.1:8000"

# ...but by WHOM. A 200 on /healthz says something is listening, not that this unit is. An
# orphan answering here is precisely how :8000 stayed up for hours while the unit was in a
# 203/EXEC loop and nothing went red. MainPID is the discriminating reading, so take it.
MAINPID="$(systemctl show -p MainPID --value symoneural-gateway.service)"
PORTPID="$(ss -lntpH 2>/dev/null | sed -n 's/.*127\.0\.0\.1:8000 .*pid=\([0-9]*\).*/\1/p' | head -1)"
if [ -z "$MAINPID" ] || [ "$MAINPID" = "0" ] || [ "$MAINPID" != "$PORTPID" ]; then
  echo "the unit is NOT the process serving :8000 (MainPID=$MAINPID, port held by pid=${PORTPID:-none})" >&2
  echo "something outside systemd is answering; the unit is dead and the site will 502 on reboot" >&2
  systemctl --no-pager --lines=20 status symoneural-gateway.service >&2 || true
  exit 1
fi
echo "  and it is this unit serving it (MainPID $MAINPID)"

if curl -sf --max-time 10 http://127.0.0.1:8000/api/status >/dev/null; then
  echo "and it can reach the API through /api/status"
else
  echo "WARNING: /healthz is up but /api/status did not answer through it." >&2
  echo "         That is the API, not the gateway: systemctl status symoneural-api" >&2
fi

cat <<'EOF'

managing it from here:
  systemctl status symoneural-gateway      what it is doing
  systemctl restart symoneural-gateway     after cargo build --release
  systemctl stop symoneural-gateway        take the gateway offline
  journalctl -u symoneural-gateway -f      follow the log (JSON records)

the Caddy half is a separate, deliberate step:
  sudo caddy validate --config /etc/caddy/Caddyfile
  sudo systemctl reload caddy
EOF
