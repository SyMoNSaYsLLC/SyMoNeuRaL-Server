#!/usr/bin/env bash
# Block until the API actually answers, or fail. Intended as an ExecStartPost= for
# symoneural-api.service.
#
# WHY THIS EXISTS
# ---------------
# The unit is `Type=exec`, so systemd reports the service `active` the moment the binary
# execs -- before `api.py` imports, before `runtimeconfig.load()`, before uvicorn binds the
# port. Measured on 2026-09-09:
#
#     22:09:55.961563  old process logs "Finished server process"
#     22:09:56         systemd marks the unit active; `systemctl restart` RETURNS
#     22:09:57.367066  uvicorn logs "Uvicorn running on http://127.0.0.1:8800"
#
# That is a ~1.4 s window in which `systemctl is-active` says `active` and every connection
# to :8800 is refused. `sudo systemctl restart symoneural-api && python3 tools/smoke.py` --
# the sequence RUNBOOK §3 tells you to run -- landed in it and reported nine failures against
# a healthy API.
#
# With this as ExecStartPost, the start JOB does not complete until the port answers.
# Measured on a throwaway --user unit built to imitate the delay:
#
#     is-active during startup:  activating   (SubState=start-post)  for the whole window
#     is-active after the probe: active       (SubState=running)
#     `systemctl start` returned after 3.20 s, port already listening
#
# So `restart` becomes synchronous with readiness and `is-active` stops lying. The cost is
# that a restart takes ~1.4 s longer to return, which is the delay that was already there --
# it is simply no longer hidden.
#
# WHY NOT Type=notify
# -------------------
# It is the more precise mechanism -- READY=1 sent by the process itself rather than a port
# probe from outside -- but it costs more here. `python3-systemd` (235-1+b6) is installed, so
# `systemd.daemon.notify` is available, but `backend/server.py` contains no sd_notify call
# (grepped: no `sd_notify`, `NOTIFY_SOCKET` or `sdnotify` anywhere under `backend/`) and
# uvicorn has no built-in support, so it would need a startup hook written into the serving
# path plus `python3-systemd` promoted to a hard start dependency in `tools/preflight.py`.
# A port probe also tests the thing clients actually need: that :8800 accepts connections.
#
# SAFETY
# ------
# Read-only: one HTTP GET in a loop. It never writes, never touches the GPU, never restarts
# anything. Exiting non-zero fails the START JOB, which makes systemd tear the service down --
# that is the intended contract (a service that cannot serve should not be reported active),
# but it means the timeout must be generous enough that a slow-but-healthy start is not
# killed. Default 45 s against a measured ~1.4 s start.
#
# Note for the unit: ExecStartPost time counts against TimeoutStartSec=, so that must exceed
# PROBE_TIMEOUT. The drop-in written by ops/commission-apply.sh sets both.

set -uo pipefail

URL="${SYMONEURAL_PROBE_URL:-http://127.0.0.1:8800/api/status}"
PROBE_TIMEOUT="${SYMONEURAL_PROBE_TIMEOUT:-45}"
INTERVAL="${SYMONEURAL_PROBE_INTERVAL:-0.25}"

start=$(date +%s)
attempts=0

while :; do
  attempts=$((attempts + 1))
  # NOT `|| echo 000`. On a refused connection curl writes "000" via -w AND exits non-zero,
  # so the fallback appended a second "000" and the variable became "000000" -- which failed
  # the `= "000"` test and sent a refused port down the "serving but unhealthy" branch,
  # reporting the opposite of the truth. Caught by testing the refused case rather than
  # assuming it; curl already reports 000 itself, so nothing needs substituting.
  code=$(curl -s -o /dev/null -w '%{http_code}' --max-time 5 "$URL" 2>/dev/null) || true
  [ -n "$code" ] || code=000
  if [ "$code" = "200" ]; then
    echo "readiness: ${URL} answered 200 after $(($(date +%s) - start))s (${attempts} attempts)"
    exit 0
  fi
  if [ $(($(date +%s) - start)) -ge "$PROBE_TIMEOUT" ]; then
    # Say what was seen, not just that it timed out: 000 means the port refused the
    # connection (still starting, or dead), anything else means it answered wrongly, and
    # those two want different investigations.
    if [ "$code" = "000" ]; then
      echo "readiness: FAILED -- ${URL} refused connections for ${PROBE_TIMEOUT}s" >&2
      echo "readiness: the process is up but never bound. journalctl -u symoneural-api -n 50" >&2
    else
      echo "readiness: FAILED -- ${URL} answered HTTP ${code}, not 200, for ${PROBE_TIMEOUT}s" >&2
      echo "readiness: it is serving but unhealthy -- a bound port is not the problem" >&2
    fi
    exit 1
  fi
  sleep "$INTERVAL"
done
