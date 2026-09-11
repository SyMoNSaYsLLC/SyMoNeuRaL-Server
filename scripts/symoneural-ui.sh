#!/usr/bin/env bash
# Render-UI process control for the SyMoNeuRaL Studio surface.
#
#   symoneural-ui.sh start     start the server on 127.0.0.1:8188 (loopback only)
#   symoneural-ui.sh stop      unload the weights, then stop it, then wait for the VRAM back
#   symoneural-ui.sh status    up/down, pid, port, and what the card looks like
#   symoneural-ui.sh log       recent server output
#
# The server is `symoneural-ui`, produced by `tools/fork_render_ui.sh` from the
# vendored upstream tree in `external/`. It is a derived tree and gitignored, exactly like
# the two engines beside it: the tracked artefact is the script that makes it. If it is not
# on disk, `tools/fork_render_ui.sh` puts it there -- do not go looking for it in
# `external/`, which is read by people and never by code.
#
# Loopback only, deliberately. The public surface is FastAPI's -- the Studio page reaches
# this server through `/studio/comfy/*`, which is proxied by `backend/studio`.
# Binding 0.0.0.0 here would put an unauthenticated node editor with filesystem access on a
# box with a public IP.
#
# ## This does NOT take the GPU lock
#
# Deliberate, and the single most important thing to understand about this script.
# CLAUDE.md: "Hold the lock for a job, never for a process lifetime." This is a long-lived
# HTTP server that is idle most of the time; taking `gpu-governor.sh acquire comfy` at start
# and holding it until `stop` would lock chat, image and train out of the card for as long as
# the editor happened to be open. The lock is taken per *render*, inside `comfy.lease()`, and
# given back with `POST /free` the moment the job finishes.
#
# The consequence is that a running-but-idle server holds no lock and, once `/free` has run,
# no meaningful VRAM either. `evict()` in the governor stops it properly when another surface
# needs the card.
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
[ -f "$ROOT/backend/server.py" ] || { echo "repo root not found at $ROOT (expected backend/server.py)" >&2; exit 1; }
COMFY="$ROOT/symoneural-ui"
VENV="$COMFY/.venv/bin/python"
RUN="$ROOT/run"; mkdir -p "$RUN"
PIDFILE="$RUN/symoneural-ui.pid"
LOG="$RUN/symoneural-ui.log"
PORT="${SYMONEURAL_COMFY_PORT:-${SYM_COMFY_PORT:-8188}}"
HOST="127.0.0.1"

running() { [ -f "$PIDFILE" ] && kill -0 "$(cat "$PIDFILE")" 2>/dev/null; }

# Ask the server to hand the card back before we signal it. SIGTERM during CUDA teardown
# returns the process before the driver returns the memory, and the next tenant OOMs at
# step 0 -- which is exactly the failure `gpu-governor.sh drain` exists to catch.
free_vram() {
  curl -fsS --max-time 10 -X POST "http://$HOST:$PORT/free" \
       -H 'Content-Type: application/json' \
       -d '{"unload_models":true,"free_memory":true}' >/dev/null 2>&1 || true
}

case "${1:-status}" in
  start)
    if running; then echo "already up (pid $(cat "$PIDFILE")) on $HOST:$PORT"; exit 0; fi
    [ -x "$VENV" ] || { echo "no server at $COMFY -- run tools/fork_render_ui.sh" >&2; exit 1; }
    # Relink our custom node before every start. engines/ is gitignored in full, so the
    # source of truth for `symoneural_gguf` lives in the repo and this is what puts it where
    # the server looks. Delete symoneural-ui and re-fork it and the node comes back
    # on the next start rather than having to be remembered.
    # A loop over the directory rather than a named pack: `symoneural_cleanroom` was added
    # second and a hardcoded name would have left it unlinked, which fails as "the node is
    # not in the menu" with nothing anywhere to read.
    for NODE_SRC in "$ROOT"/backend/studio/custom_nodes/*; do
      [ -d "$NODE_SRC" ] || continue
      NODE_DST="$COMFY/custom_nodes/$(basename "$NODE_SRC")"
      if [ ! -e "$NODE_DST" ]; then
        ln -s "$NODE_SRC" "$NODE_DST" && echo "linked $(basename "$NODE_SRC") into custom_nodes/"
      fi
    done
    # --disable-auto-launch: this is a headless server behind a proxy; opening a browser on
    # a box being driven over SSH is noise at best.
    setsid "$VENV" "$COMFY/main.py" \
        --listen "$HOST" --port "$PORT" \
        --disable-auto-launch \
        >>"$LOG" 2>&1 &
    echo $! > "$PIDFILE"
    # It imports torch and scans custom nodes before it binds, which is seconds not
    # milliseconds. Poll the port rather than sleeping a guessed constant.
    for _ in $(seq 1 60); do
      curl -fsS --max-time 2 "http://$HOST:$PORT/system_stats" >/dev/null 2>&1 && break
      running || { echo "died during startup -- see $LOG" >&2; rm -f "$PIDFILE"; exit 1; }
      sleep 1
    done
    if curl -fsS --max-time 2 "http://$HOST:$PORT/system_stats" >/dev/null 2>&1; then
      echo "symoneural-ui up on $HOST:$PORT (pid $(cat "$PIDFILE"))"
      echo "the editor is served through the stack at /studio -- not from this port directly."
    else
      echo "started (pid $(cat "$PIDFILE")) but not answering yet -- see $LOG" >&2; exit 1
    fi
    ;;

  stop)
    if running; then
      free_vram
      kill "$(cat "$PIDFILE")" 2>/dev/null
      for _ in $(seq 1 20); do running || break; sleep 1; done
      running && kill -9 "$(cat "$PIDFILE")" 2>/dev/null
    else
      # Started outside this script, or the pidfile was lost.
      pkill -f "$COMFY/main.py" 2>/dev/null
    fi
    rm -f "$PIDFILE"
    # The process exiting is not the memory coming back: SIGTERM returns the process before the
    # driver returns the device allocation, and the next tenant OOMs at step 0. The loop above
    # waited for the pid; this waits for the memory, against the governor's own floor so there
    # is one definition of "drained" in this repo rather than two.
    #
    # Scoped to this process, and that argument is load-bearing. The bare form asks whether the
    # whole card is clear of CUDA contexts, which is the right question for an eviction handoff
    # and the wrong one here: chat is often legitimately warm at ~8.1 GiB, and stopping the
    # render UI would then report `drain FAILED` about a card behaving exactly as intended.
    # What this needs to know is narrower -- did OUR server's ~12 GB come back.
    if "$ROOT/scripts/gpu-governor.sh" drain "$COMFY/main.py"; then
      echo "symoneural-ui stopped"
    else
      echo "symoneural-ui stopped, but its VRAM did not come back -- see gpu-governor.sh status" >&2
      exit 1
    fi
    ;;

  status)
    if running; then
      echo "symoneural-ui  up (pid $(cat "$PIDFILE")) on $HOST:$PORT"
    elif curl -fsS --max-time 2 "http://$HOST:$PORT/system_stats" >/dev/null 2>&1; then
      echo "symoneural-ui  up on $HOST:$PORT but NOT started by this script (no pidfile)"
    else
      echo "symoneural-ui  down"
    fi
    "$ROOT/scripts/gpu-governor.sh" status
    ;;

  log) tail -n "${2:-40}" "$LOG" 2>/dev/null || echo "no log at $LOG" ;;

  *) echo "usage: $(basename "$0") {start|stop|status|log}" >&2; exit 2 ;;
esac
