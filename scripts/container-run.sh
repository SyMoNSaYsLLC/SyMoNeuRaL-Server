#!/usr/bin/env bash
# Run the SyMoNeuRaL API in a rootless container with the GPU attached via CDI.
#
#   scripts/container-run.sh                 # foreground, port 8800 (conflicts with the service)
#   scripts/container-run.sh --port 8801     # foreground on another port, safe to test alongside
#   scripts/container-run.sh --detach        # background, named symoneural-api
#   scripts/container-run.sh --stop
#
# No sudo. Rootless podman maps the container's root to your host user, so files the API
# writes into run/ and site/ come out owned by you rather than by root.
set -euo pipefail

. "$(dirname -- "${BASH_SOURCE[0]}")/lib/repo.sh"
IMAGE="${SYMONEURAL_IMAGE:-symoneural-api}"
NAME="symoneural-api"
PORT=8800
DETACH=0

while [ $# -gt 0 ]; do
  case "$1" in
    --port)   PORT="$2"; shift 2;;
    --detach|-d) DETACH=1; shift;;
    --stop)   podman rm -f "$NAME" 2>/dev/null && echo "stopped $NAME" || echo "not running"; exit 0;;
    *) echo "unknown option: $1" >&2; exit 2;;
  esac
done

command -v podman >/dev/null || { echo "podman is not installed" >&2; exit 1; }
podman image exists "$IMAGE" || {
  echo "image '$IMAGE' not built. Run:" >&2
  echo "  podman build -t $IMAGE -f ops/deploy/Containerfile ." >&2; exit 1; }

# --- why each of these flags is here -----------------------------------------
#
# --device nvidia.com/gpu=all
#     CDI. Injects the driver, libcuda.so.1 and nvidia-smi from the host. The CUDA
#     *runtime* libraries (libcublas etc.) come from the image, not from here.
#
# -v $ROOT:/app
#     The repo, bind-mounted at a fixed path *inside* the container. The host location is
#     irrelevant -- move the checkout anywhere and this still works -- because api.py derives
#     its root from __file__ and the engines were repointed to $ORIGIN, so nothing depends on
#     an absolute host path. Verified: with the tree at /app, models, site, run, both engine
#     binaries, the adapter and the governor all resolve.
#     This mount is the important one and it is doing four jobs at once:
#       1. run/gpu.lock.d -- gpu-governor.sh is a mkdir lock, and that directory *is* the
#          mutex. Without this mount the container creates its own copy, the host and the
#          container both acquire successfully, both load weights, and ~12 GB of models hit
#          a 16 GB card. The failure is a silent OOM at step 0 that looks like a CUDA fault,
#          not a deadlock -- a deadlock would at least stop and be noticed.
#       2. models/ -- 40 GB, mounted rather than copied.
#       3. llama.cpp/build/bin and stable-diffusion.cpp/build/bin -- the engines, already
#          repointed to $ORIGIN so they find their own .so files wherever the tree lives.
#       4. site/ -- renders are written there and served from there.
#     Mounting at the identical path means every HERE/ROOT calculation in api.py,
#     gpu-governor.sh and the generators resolves the same inside and out. Nothing has to
#     know it is in a container.
#
# --network host
#     api.py binds 127.0.0.1 on purpose -- Caddy is the only thing that should reach it.
#     With host networking, that loopback is the host's, so the existing Caddy config keeps
#     working untouched and the API stays off the public interface.
#
# --ipc host
#     CUDA uses shared memory; the default 64 MB /dev/shm is not enough for the image
#     surface and shows up as an opaque allocation failure mid-render.
ARGS=(
  --rm
  --name "$NAME"
  --device nvidia.com/gpu=all
  --network host
  --ipc host
  -v "$ROOT:/app"
  -w /app
  -e "SYMONEURAL_PORT=$PORT"
)
[ "$DETACH" = "1" ] && ARGS+=(-d)

echo "image   $IMAGE"
echo "repo    $ROOT -> /app (host location does not matter)"
echo "lock    $ROOT/run/gpu.lock.d -> /app/run/gpu.lock.d (one lock, shared)"
echo "port    127.0.0.1:$PORT"
echo

podman run "${ARGS[@]}" "$IMAGE"

if [ "$DETACH" = "1" ]; then
  sleep 4
  if curl -fsS -m 10 "http://127.0.0.1:$PORT/api/status" >/dev/null 2>&1; then
    echo "up: http://127.0.0.1:$PORT/api/status is answering"
  else
    echo "started, but /api/status did not answer yet -- podman logs $NAME" >&2
  fi
fi
