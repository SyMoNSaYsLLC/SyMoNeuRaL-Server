#!/usr/bin/env bash
# Start symoneural_dj — the playlist orchestrator on :8090.
#
#   ./run.sh                 serve in the foreground
#   ./run.sh --daemon        background: .run/dj.{pid,log}
#
# Env (see .env.example): SPOTIFY_CLIENT_ID/SECRET, DJ_TOKEN, DJ_HOST, DJ_PORT.
# VLLM_API_KEY must be in .env — ~/.bashrc's export is behind an interactive-
# shell guard and never reaches daemons or scripts. Mirrors symon_llm/run.sh.
set -euo pipefail
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# .env is also read by the app itself (python-dotenv); sourcing it here too
# lets DJ_HOST/DJ_PORT reach the uvicorn command line.
if [[ -f .env ]]; then
    set -a; source .env; set +a
fi

PY="${PY:-$HOME/.venvs/vllm/bin/python}"
if [[ ! -x "$PY" ]]; then
    PY="$(command -v python3)"
fi

HOST="${DJ_HOST:-0.0.0.0}"
PORT="${DJ_PORT:-8090}"

if [[ "${1:-}" == "--daemon" ]]; then
    shift
    mkdir -p .run
    setsid nohup "$PY" -m uvicorn symoneural_dj.main:app \
        --host "$HOST" --port "$PORT" "$@" > .run/dj.log 2>&1 &
    echo $! > .run/dj.pid
    echo "symoneural_dj starting (pid $(cat .run/dj.pid), log .run/dj.log)"
    exit 0
fi

exec "$PY" -m uvicorn symoneural_dj.main:app --host "$HOST" --port "$PORT" "$@"
