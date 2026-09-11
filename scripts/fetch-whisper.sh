#!/usr/bin/env bash
# Fetch and build whisper.cpp -- the speech-to-text half of SyMoNeuRaL Stickers.
#
# **This builds a CPU-only binary on purpose, and that is the whole design.**
#
# One RTX 5070 Ti, 15.92 GiB, one tenant at a time. A sticker spoken into a phone is
# ASR -> the existing text path -> a render, and if the ASR were a CUDA tenant that
# sequence would be: take the lock, transcribe, release, wait for the 1.5 GiB drain
# floor, take the lock again, render. The drain wait alone is bounded at 60 s. So the
# transcription is deliberately kept off the card, where it can run *while* another
# surface holds the GPU rather than queueing behind it.
#
# That is not a new idea here -- it is RavenCalc's, which stays off the lock for exactly
# this reason and is the precedent HANDOVER §5 item 12 names for the voice work.
#
#   ./scripts/fetch-whisper.sh              # build + the default model
#   ./scripts/fetch-whisper.sh base.en      # a specific model
#
# Licences, both permissive and both recorded in LICENSES.md in the same commit that
# added this file:
#   whisper.cpp   MIT        (ggerganov/whisper.cpp)
#   ggml weights  MIT        (ggerganov/whisper.cpp model releases on Hugging Face)
set -uo pipefail

# Repo root is one level up from scripts/. The same calculation has been wrong three
# times in this repo and it fails silently, because the wrong parent is usually a
# directory that exists -- so it is asserted rather than assumed.
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$HERE/.." && pwd)"
[ -f "$ROOT/scripts/gpu-governor.sh" ] || { echo "repo root not found at $ROOT" >&2; exit 1; }


# ---------------------------------------------------------------------------------
# SUPERSEDED 2026-09-04, and delegating rather than deleted.
#
# The argument above is still the design and is cited from backend/apps/voice/asr.py and
# from tools/fork_engines.sh, so it stays here where those citations point. What changed is
# that every operative line below it was wrong:
#
#   * it cloned into `contrib/whisper.cpp`, which `/contrib` gitignores and
#     backend/apps/test_references_boundary.py bans outright. Building there is how this
#     capability vanished once already, with nothing in git log to say it had.
#   * it wrote the weight under its UPSTREAM filename, while both call sites load the house
#     name `symoneural-listen-base-en.bin`. So even a successful run left ASR dead, and that
#     is part of why it stayed dead: the script appeared to work. The upstream spelling is
#     deliberately not repeated here -- `apps/test_weight_names.py` bans it from source, and
#     `backend/models/NAMES.md` is the one place that maps house name to upstream name.
#
# The two canonical tools now own the two halves, and both are tracked:
#
#     tools/fork_engines.sh listen     builds symoneural-listen, under our names
#     scripts/fetch-models.sh          fetches the weight under its house name
#
# This wrapper runs them in that order so an old command line still does the right thing.
set -euo pipefail

echo "fetch-whisper.sh is superseded; running the two tools that replaced it."
echo

if [ -x "$ROOT/symoneural-listen/build/bin/symoneural-listen" ]; then
  echo "==> engine already built at symoneural-listen"
else
  echo "==> building the engine"
  "$ROOT/tools/fork_engines.sh" listen
fi

WEIGHT="$ROOT/backend/models/whisper/symoneural-listen-base-en.bin"
if [ -s "$WEIGHT" ]; then
  echo "==> weight already present: $(basename "$WEIGHT") ($(du -h "$WEIGHT" | cut -f1))"
else
  echo "==> fetching the weight via scripts/fetch-models.sh"
  echo "    NOTE: that script fetches every chat-tier payload too, including the 14B"
  echo "    (~8.4 GB) if it is absent. To fetch only this one, copy the speech-surface"
  echo "    line out of scripts/fetch-models.sh -- it carries the upstream URL, which is"
  echo "    kept there rather than repeated here."
  "$ROOT/scripts/fetch-models.sh"
fi

echo
echo "done. Verify with a real transcription rather than a file listing:"
echo "  symoneural-listen/build/bin/symoneural-listen \\"
echo "    -m $WEIGHT \\"
echo "    -f symoneural-listen/samples/jfk.wav -nt"
