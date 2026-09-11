#!/usr/bin/env bash
# Production service control: on, off, and what it did.
#
# The surfaces are open and free, which means the important command here is `off`. It stops
# the API, stops whatever holds the GPU, and releases the governor -- after which
# symoneural.com still serves every static page, just without the live surfaces. Nothing
# about turning it off is a rollback or a redeploy.
#
# For boot-start and crash-restart, install the systemd unit instead:
#   sudo scripts/install-service.sh
#
#   symoneural.sh on          start the API (loopback; Caddy proxies /api to it)
#   symoneural.sh off         stop everything, free the card
#   symoneural.sh status      is it up, what is resident, what is queued
#   symoneural.sh log         recent requests
#   symoneural.sh off-at 07:00   turn it off automatically at a wall-clock time
set -uo pipefail

# Repo root is one level up now that this lives in scripts/. This calculation has
# been wrong three times in this repo (the demo/ flatten, the tools/ move, here) and
# it fails silently, because the wrong parent is usually a directory that exists.
# The guard below turns that into an immediate, obvious failure.
. "$(dirname -- "${BASH_SOURCE[0]}")/lib/repo.sh"
HERE="$ROOT"
RUN="$ROOT/run"; mkdir -p "$RUN"
PIDFILE="$RUN/api.pid"
PORT="${SYMONEURAL_PORT:-8800}"

UNIT=symoneural-api.service

# There are TWO ways the API can be up and this script only knew about one of them.
#
# `install-service.sh` installs $UNIT with `Type=exec` and no `PIDFile=`, so a systemd-managed
# API writes nothing to $PIDFILE. Every function here keyed off that file, and the consequences
# were both worse than they look:
#
#   * `status` printed "api        down" while the API had been serving for hours -- and then
#     printed a full, correct /api/status JSON underneath it, which is a readout contradicting
#     itself. A status line that says down about something that is up is the decorative-
#     indicator failure this repo bars, in the operator tool rather than on a page.
#   * `off` -- documented in .claude/CLAUDE.md as THE KILL SWITCH -- found no pidfile, killed
#     nothing, and printed "surfaces off. static pages unaffected; the card is free." A kill
#     switch reporting success without killing is the most expensive lie in the repo. And even
#     had it found a pid, the unit is `Restart=always` / `RestartSec=3`, so the API would be
#     back in three seconds.
#
# So ownership is resolved first and every action is VERIFIED afterwards rather than announced.
# `port_up` is the ground truth: it asks the thing itself instead of asking a file about it.
unit_active() { systemctl is-active --quiet "$UNIT" 2>/dev/null; }
unit_known()  { systemctl cat "$UNIT" >/dev/null 2>&1; }
pid_alive()   { [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; }
port_up()     { curl -sf --max-time 3 -o /dev/null "http://127.0.0.1:$PORT/api/status"; }
running()     { pid_alive || unit_active; }

# systemctl on a system unit needs root. Escalate only non-interactively -- a script that
# blocks on a password prompt inside `off` is a kill switch that hangs -- and when that is not
# available, say the exact command instead of failing in a way that reads as "already off".
sysctl_do() {
  if [ "$(id -u)" -eq 0 ]; then systemctl "$@"; return; fi
  sudo -n systemctl "$@" 2>/dev/null && return
  echo "needs root: sudo systemctl $*" >&2
  return 1
}

case "${1:-status}" in
  on)
    if unit_active; then echo "already up, owned by $UNIT"; exit 0; fi
    if pid_alive; then echo "already up (pid $(cat "$PIDFILE"))"; exit 0; fi
    # Prefer the unit when one is installed. Starting a second copy by hand would race the
    # one systemd is about to restart, and both would fight for :$PORT.
    if unit_known; then
      sysctl_do start "$UNIT" || exit 1
      sleep 2
      if port_up; then echo "symoneural api up on 127.0.0.1:$PORT via $UNIT"; exit 0; fi
      echo "$UNIT started but nothing answers on :$PORT -- journalctl -u $UNIT -n 50" >&2
      exit 1
    fi
    setsid python3 "$ROOT/backend/server.py" >>"$RUN/api.out" 2>&1 &
    echo $! > "$PIDFILE"
    sleep 2
    if pid_alive; then
      echo "symoneural api up on 127.0.0.1:$PORT (pid $(cat "$PIDFILE"))"
      echo "remember: 'symoneural.sh off' ends it whenever you like."
    else
      echo "failed to start -- see $RUN/api.out" >&2; exit 1
    fi
    ;;

  off)
    # The unit first, and `stop` not `kill`: Restart=always means killing the process is a
    # three-second pause, not an off switch.
    if unit_active; then sysctl_do stop "$UNIT" || exit 1; fi
    if pid_alive; then kill "$(cat "$PIDFILE")" 2>/dev/null; sleep 1; fi
    rm -f "$PIDFILE"
    # Whatever the API left holding the card goes too, then the lock is cleared so the
    # next tenant is not left waiting behind a process that no longer exists.
    pkill -f 'bin/symoneural-llm' 2>/dev/null
    pkill -f 'bin/symoneural-diffuse' 2>/dev/null
    # Only our own surfaces -- a fine-tune holding the card is not ours to end.
    "$ROOT/scripts/gpu-governor.sh" release chat >/dev/null 2>&1
    "$ROOT/scripts/gpu-governor.sh" release image >/dev/null 2>&1
    # Verified, not announced. This line used to print unconditionally, which is how a kill
    # switch that killed nothing still read as a success.
    if port_up; then
      echo "STILL UP: something is answering on 127.0.0.1:$PORT -- the surfaces are NOT off" >&2
      unit_active && echo "  $UNIT is still active; try: sudo systemctl stop $UNIT" >&2
      exit 1
    fi
    echo "surfaces off. static pages unaffected; the card is free."
    ;;

  status)
    # Says who owns it as well as whether it is up, because the two answers used to disagree.
    if unit_active; then echo "api        up on 127.0.0.1:$PORT via $UNIT (systemd-managed)"
    elif pid_alive; then echo "api        up (pid $(cat "$PIDFILE")) on 127.0.0.1:$PORT"
    elif port_up; then echo "api        up on 127.0.0.1:$PORT, owner UNKNOWN -- no pidfile and $UNIT inactive"
    else echo "api        down"; fi
    curl -s --max-time 3 "http://127.0.0.1:$PORT/api/status" | python3 -m json.tool 2>/dev/null \
      || "$ROOT/scripts/gpu-governor.sh" status
    ;;

  log)
    tail -n "${2:-40}" "$RUN/api.log" 2>/dev/null || echo "no log yet"
    ;;

  off-at)
    at="${2:?usage: off-at HH:MM}"
    # No at(1) dependency -- a detached sleep is enough and leaves an obvious process.
    secs=$(( $(date -d "$at" +%s) - $(date +%s) ))
    [ "$secs" -lt 0 ] && secs=$(( secs + 86400 ))
    setsid bash -c "sleep $secs; '$ROOT/scripts/symoneural.sh' off" >/dev/null 2>&1 &
    echo "will turn off at $at (in $((secs / 60)) minutes)"
    ;;

  *) echo "usage: $(basename "$0") {on|off|status|log|off-at HH:MM}" >&2; exit 2 ;;
esac
