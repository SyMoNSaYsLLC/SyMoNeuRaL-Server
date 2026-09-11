#!/usr/bin/env bash
#
# Run NVIDIA's Qwen3.6-27B NIM container on this box, or fail with a reason.
#
#   ./scripts/nim-qwen36.sh login          # one-off: podman login nvcr.io
#   ./scripts/nim-qwen36.sh preflight      # every check, pulls nothing
#   ./scripts/nim-qwen36.sh up             # pull + run, serving on :8082
#   ./scripts/nim-qwen36.sh logs           # follow
#   ./scripts/nim-qwen36.sh down           # stop and remove
#
# A second NIM is selectable, because the question "would the bigger one run here" is asked
# more than once and guessing at it is worse than measuring it:
#
#   NIM_MODEL=qwen3-32b ./scripts/nim-qwen36.sh preflight
#
# Default stays qwen3.6-27b, so every existing invocation and every line in HANDOVER.md
# means exactly what it meant before.
#
# ## Why this exists as a script rather than a docker one-liner
#
# There is no `docker` on this box and there is not going to be: podman 5.4.2 is installed,
# rootless, with crun, and /etc/cdi/nvidia.yaml is already generated -- so GPU passthrough is
# `--device nvidia.com/gpu=all`, which is NOT the flag any NVIDIA doc shows. Every published
# NIM example says `docker run --gpus all`. Copying that here fails twice over.
#
# ## What NVIDIA does and does not say about this card
#
# The NGC page for nim/qwen/qwen3.6-27b (pulled 2026-08-18, container updated 2026-04-23)
# carries NO hardware matrix: no GPU list, no VRAM minimum, no example run command. What it
# does say, and what matters here:
#
#   Compressed Size    11.87 GB
#   How to Pull        Automatic (embedded in container)
#   Backend            SGLang
#   Multi-Arch         No
#   Labels             Experimental
#
# 11.87 GB is the COMPRESSED REGISTRY SIZE of the image, not a VRAM figure and not the size
# of the weights on disk. Quantized weights are near-incompressible, so the uncompressed
# layers are larger, and what SGLang then allocates on the card is larger again once the KV
# cache is reserved. Treat 11.87 GB as "what the pull costs", never as "what fits".
#
# NIM's own GeForce support list names the RTX 5090, 5080, 4090 and 4080. The RTX 5070 Ti in
# this machine is NOT on it, and NVIDIA's NVFP4 build of this model is reported at ~18.6 GB
# against this card's 15.92 GiB. NIM selects an optimized profile at startup and refuses when
# none fits. So this script may get all the way to a clean start and still be told no. That
# is a legitimate outcome to record, not a bug to work around -- see `docs/` on publishing
# negative results.
#
# The supported path on this card is the GGUF one: contrib/llama.cpp already carries
# LLM_ARCH_QWEN35, which is the architecture these Qwen3.6 GGUFs declare in their header.
set -euo pipefail

# One table, so adding a NIM is four measured numbers and not a copy of this file. Each row
# carries the two figures preflight needs: PULL_GB is the compressed registry size NGC prints
# (never a VRAM figure -- see the note above), and NEED_MIB is the reported footprint of the
# profile NIM is expected to pick, which is what the card is compared against.
case "${NIM_MODEL:-qwen36}" in
  qwen36)
    IMAGE=nvcr.io/nim/qwen/qwen3.6-27b:latest
    NAME=symon-nim-qwen36
    PORT=8082
    PULL_GB=11.87
    NEED_MIB=19000        # ~18.6 GB NVFP4, third-party report
    ;;
  qwen3-32b)
    # nvcr.io/nim/qwen/qwen3-32b:1.0.0, digest sha256:b1e15025885a..., 20.74 GB compressed,
    # linux/amd64 only, published 2025-08-20. Read off the NGC catalogue page, not measured
    # here -- nothing has been pulled, because nvcr.io answers 401 without an NGC key.
    #
    # The pinned tag is deliberate. NGC serves :1.0.0, :1.0 and :latest from one digest today,
    # so they are the same image; a pin keeps that true after the next publish.
    #
    # NGC's Anchore scan, refreshed 2026-02-16: 493 findings, 0 critical, 21 high, 323 medium,
    # 149 low. The base is Ubuntu 24.04 with python3.12, and the highs are its packages, not
    # NVIDIA's inference code -- gnupg2/CVE-2025-68973 across eight dpkg names, plus urllib3,
    # starlette, aiohttp, protobuf, sentencepiece, xgrammar, pillow and setuptools' vendored
    # wheel. Recorded because it is a decision input and because it would otherwise have to be
    # looked up again: a NIM is somebody else's userland running on our card, and this is what
    # comes with it. Nothing here has been pulled, so nothing here has been scanned by us.
    #
    # THREE INDEPENDENT REASONS THIS ONE DOES NOT SHIP, so that the next person to want a 32B
    # does not have to rediscover them. Selectable anyway, because `preflight` proving it is
    # worth more than this comment claiming it.
    #
    #   1. It does not fit. Measured here 2026-08-20: 16303 MiB total on this card against the
    #      19000 MiB floor below, and the floor is the 27B's number -- a 32B needs more. NIM
    #      picks a profile at startup and refuses when none fits.
    #   2. NGC marks it END OF SUPPORT: "This artifact is no longer supported. NVIDIA strongly
    #      recommends artifacts that are up to date and supported." Building a live surface on
    #      a container the vendor has stopped patching, whose own scan already shows 21 highs,
    #      is a decision to carry those forever.
    #   3. It is not ours to redistribute. NIM is part of NVIDIA AI Enterprise, governed by the
    #      NVIDIA Software License Agreement plus the Product Specific Terms for AI Products,
    #      and the weights by the AI Foundation Models Community License. Same class of
    #      constraint as Apple's SDK in external/: licensed to use, not to bundle. No .deb,
    #      no meta-symoneural-* recipe, and no Symoneural_backups archive may carry this image.
    #
    # What could work is the path the 27B already took: a Q2-class GGUF served by
    # contrib/llama.cpp, which is where the 11.85 GB Qwen3.6-27B on this box came from. Whether
    # a 32B GGUF clears 15.92 GiB with usable KV headroom is a measurement nobody here has
    # taken, so no figure for it appears on any page.
    IMAGE=nvcr.io/nim/qwen/qwen3-32b:1.0.0
    NAME=symon-nim-qwen3-32b
    PORT=8083             # not 8082: both may be defined at once, and two NIMs racing for
                          # one port is a confusing failure on a box with one card anyway.
    PULL_GB=20.74
    NEED_MIB=19000        # floor, not an estimate. 32B is 19% more parameters than the 27B
                          # whose NVFP4 profile is already reported at ~18.6 GB, so the real
                          # figure is higher than this and the comparison below only gets
                          # more certain. Kept at the 27B's number so the check cannot be
                          # accused of being tuned to produce a refusal.
    ;;
  *)
    echo "unknown NIM_MODEL '${NIM_MODEL}' -- known: qwen36, qwen3-32b" >&2
    exit 1
    ;;
esac
# NIM caches the model outside the container so a re-run does not re-extract it. This is
# gitignored space on the big filesystem, not /home root and not the repo's models/ tree --
# NIM owns the layout in here and it is not a GGUF.
CACHE="${SYMONEURAL_NIM_CACHE:-${SYM_NIM_CACHE:-$HOME/.cache/nim}}"

. "$(dirname -- "${BASH_SOURCE[0]}")/lib/repo.sh"

say()  { printf '%s\n' "$*"; }
ok()   { printf '  ok    %s\n' "$*"; }
bad()  { printf '  FAIL  %s\n' "$*"; }
warn() { printf '  warn  %s\n' "$*"; }

preflight() {
  local fatal=0
  say "preflight for $IMAGE"

  command -v podman >/dev/null && ok "podman $(podman --version | awk '{print $3}')" \
    || { bad "podman not installed"; fatal=1; }

  if [ -f /etc/cdi/nvidia.yaml ]; then
    ok "CDI spec /etc/cdi/nvidia.yaml present"
  else
    bad "no /etc/cdi/nvidia.yaml -- run: sudo nvidia-ctk cdi generate --output=/etc/cdi/nvidia.yaml"
    fatal=1
  fi

  # Credentials. nvcr.io answers 401 to an anonymous manifest request, so this is not
  # optional and cannot be worked around from here.
  if podman login --get-login nvcr.io >/dev/null 2>&1; then
    ok "logged in to nvcr.io as $(podman login --get-login nvcr.io 2>/dev/null)"
  else
    bad "not logged in to nvcr.io -- run: $0 login   (needs your NGC API key)"
    fatal=1
  fi

  local free_mib total_mib
  read -r total_mib free_mib < <(nvidia-smi --query-gpu=memory.total,memory.free \
      --format=csv,noheader,nounits | tr -d ',' )
  say "  gpu   ${free_mib} MiB free of ${total_mib} MiB"
  # 18.6 GB is the reported NVFP4 footprint. This card cannot reach it. Stated as a warning
  # rather than a hard stop because the figure is third-party and the profile NIM actually
  # picks here is exactly what we are trying to find out.
  if [ "$total_mib" -lt "$NEED_MIB" ]; then
    warn "this card has ${total_mib} MiB against the ${NEED_MIB} MiB this profile is reported"
    warn "to need; NIM selects a profile at startup and refuses when none fits"
  fi

  local avail_gb
  avail_gb=$(df -BG --output=avail "$(dirname "$CACHE")" 2>/dev/null | tail -1 | tr -dc '0-9')
  if [ "${avail_gb:-0}" -ge 60 ]; then ok "${avail_gb} GB free for the image and model cache"
  else warn "only ${avail_gb} GB free at $CACHE -- the pull is ${PULL_GB} GB compressed and expands"; fi

  [ "$fatal" -eq 0 ] || { say; say "preflight failed -- nothing was pulled."; return 1; }
  say; say "preflight passed."
}

case "${1:-preflight}" in
  login)
    say "Your NGC API key is the password. Username is the literal string \$oauthtoken."
    podman login nvcr.io --username '$oauthtoken'
    ;;

  preflight) preflight ;;

  up)
    preflight
    mkdir -p "$CACHE"
    say "pulling $IMAGE (${PULL_GB} GB compressed) ..."
    podman pull "$IMAGE"
    podman rm -f "$NAME" >/dev/null 2>&1 || true
    say "starting on 127.0.0.1:$PORT ..."
    # Loopback-bound on purpose. This is an unauthenticated OpenAI-compatible endpoint and
    # the box it runs on serves the public internet; the same reasoning that keeps Coder and
    # Rack loopback-only applies here. FastAPI stays the only thing facing outward.
    podman run -d --name "$NAME" \
      --device nvidia.com/gpu=all \
      --shm-size=16g \
      -v "$CACHE:/opt/nim/.cache:z" \
      -p 127.0.0.1:$PORT:8000 \
      "$IMAGE"
    say "started. Follow the profile selection -- that is where it fails if it fails:"
    say "    $0 logs"
    say "Then:  curl -s http://127.0.0.1:$PORT/v1/models | python3 -m json.tool"
    ;;

  logs) podman logs -f "$NAME" ;;

  down) podman rm -f "$NAME" && say "removed $NAME" ;;

  *) say "usage: $0 {login|preflight|up|logs|down}"; exit 1 ;;
esac
