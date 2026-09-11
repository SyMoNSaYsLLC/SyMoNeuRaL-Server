#!/usr/bin/env bash
# Set up photograph background-removal for SyMoNeuRaL Stickers: an isolated venv and one
# permissively licensed segmentation model.
#
# **Two rules this script exists to keep.**
#
# 1. **Nothing is installed into the serving interpreter.** That interpreter is a Debian
#    install carrying only what the API needs, and `.claude/settings.local.json` denies
#    `pip install` against it by design. rembg brings onnxruntime, numba and scikit-image;
#    those live in `backend/sigils/.venv` and are reached across a subprocess boundary
#    by `cutout_worker.py`, the same shape `backend/asicminer/probe.py` already uses.
#
# 2. **The weights are fetched here, not at request time.** rembg's default behaviour is to
#    download a model on first use into `~/.u2net`. A serving path that reaches the network
#    mid-request fails in a way that looks like a slow render, so the download is done once,
#    deliberately, into `models/rembg/`, and `U2NET_HOME` points there.
#
# Licences -- a gate, not a footnote. u2net and isnet are Apache-2.0. **bria-rmbg-2.0 is
# CC BY-NC 4.0 and is deliberately not fetched**: it is the best-known model rembg offers
# and its non-commercial terms disqualify it from a company's product. Recorded in
# LICENSES.md in the same commit as this file.
#
#   ./scripts/fetch-cutout.sh            # venv + u2net
#   ./scripts/fetch-cutout.sh u2netp     # the small one (4.4 MB) instead
set -uo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
[ -f "$ROOT/scripts/gpu-governor.sh" ] || { echo "repo root not found at $ROOT" >&2; exit 1; }

VENV="$ROOT/backend/sigils/.venv"
MODELS="$ROOT/models/rembg"
MODEL="${1:-u2net}"

# The verified subset. `isnet-general-use` and `silueta` were checked and removed rather than
# left in: see the block comment in `backend/sigils/cutout_worker.py` for what each check
# found. Keep this list and that dict identical.
case "$MODEL" in
  u2net|u2netp) ;;
  *) echo "refusing '$MODEL': not in the verified permissively licensed set (u2net, u2netp)" >&2
     exit 1 ;;
esac

say() { printf '\033[36m==>\033[0m %s\n' "$*"; }

if [ -x "$VENV/bin/python" ]; then
  say "venv already at $VENV"
else
  say "creating $VENV"
  python3 -m venv "$VENV" || exit 1
fi

if "$VENV/bin/python" -c "import rembg" 2>/dev/null; then
  say "rembg already installed"
else
  say "installing rembg[cpu] into the venv (never into the system interpreter)"
  "$VENV/bin/pip" install --quiet "rembg[cpu]" || { echo "install failed" >&2; exit 1; }
fi

mkdir -p "$MODELS"
DEST="$MODELS/${MODEL}.onnx"
if [ -s "$DEST" ]; then
  say "model already present: $DEST ($(du -h "$DEST" | cut -f1))"
else
  URL="https://github.com/danielgatis/rembg/releases/download/v0.0.0/${MODEL}.onnx"
  say "downloading ${MODEL}.onnx"
  curl -fL --retry 3 -o "$DEST.part" "$URL" || { rm -f "$DEST.part"; echo "download failed" >&2; exit 1; }
  mv "$DEST.part" "$DEST"
  say "model at $DEST ($(du -h "$DEST" | cut -f1))"
fi

# Apache-2.0 §4(a) obliges the licence text to travel with the Work, and `LICENSES.md` §9
# checks for `models/licenses/`. Same helper shape as `scripts/fetch-models.sh` so
# there is one place a customer build looks. A table row asserting Apache-2.0 while no text
# ships is the obligation restated, not met.
L="$ROOT/models/licenses"; mkdir -p "$L"
lic() { # url dest
  [ -s "$L/$2" ] && { echo "  have $2"; return; }
  if curl -fsSL --retry 3 -o "$L/$2.part" "$1" 2>/dev/null && [ -s "$L/$2.part" ]; then
    mv "$L/$2.part" "$L/$2"; echo "  get  $2"
  else
    rm -f "$L/$2.part"; echo "  MISS $2 (fetch by hand before shipping a build)" >&2
  fi
}
say "licences"
# The .onnx is redistributed by rembg as a release asset and carries no licence file of its
# own, so the text is taken from the architecture's source repository, which is where the
# Apache-2.0 grant actually lives. Both models here come from that one repo and one file.
lic "https://raw.githubusercontent.com/xuebinqin/U-2-Net/master/LICENSE" u2net.LICENSE.txt
# The library that loads it, and the runtime that library brings. Both MIT, both redistributed
# on a customer box that does cutouts.
lic "https://raw.githubusercontent.com/danielgatis/rembg/main/LICENSE.txt" rembg.LICENSE.txt
lic "https://raw.githubusercontent.com/microsoft/onnxruntime/main/LICENSE" onnxruntime.LICENSE.txt

say "checking the worker runs"
U2NET_HOME="$MODELS" "$VENV/bin/python" -c "
from rembg import new_session
new_session('$MODEL')
print('session ok')
" || { echo "the model would not load" >&2; exit 1; }

say "done -- cutouts will use $MODEL from $MODELS"
