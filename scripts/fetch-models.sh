#!/usr/bin/env bash
# Fetch the GGUF weight sets for the SyMoNeuRaL surfaces, and the licences that must
# travel with them.
#
# Every source here is ungated and commercially licensed, all Apache-2.0:
#   Qwen2.5-7B / 14B / 0.5B-Instruct     chat, heavy tier, speculative draft
#   FLUX.1-schnell (+ VAE, T5-XXL, CLIP-L)  image
#
# FLUX.1-schnell ONLY. FLUX.1-dev is non-commercial and must never be substituted into
# anything customer-facing. See LICENSES.md.
#
# HOUSE NAMES. Nothing under models/ keeps an upstream filename. What lands on disk
# is symon-1.0-* for the language tiers and symoneural-image-* / symoneural-listen-* for the
# rest; models/PROVENANCE.json records which upstream artefact each one came from,
# and backend/test_weight_names.py fails if a file appears that is not in the manifest
# or not named to the rule. The upstream URLs below are the one thing that cannot be
# rebranded -- you cannot fetch from a repository without naming it -- and the manifest is
# where that mapping is kept honest.
#
# `adopt` below is what makes this safe to run on a box that already downloaded the old
# names: it renames in place. A rename is not a re-quantisation and not a merge, so the
# bytes are untouched and 40 GB is not re-transferred. On a fresh clone the adopt calls are
# all no-ops and the house name is simply what gets downloaded.
set -euo pipefail
# Repo root is one level up now that this lives in scripts/. This calculation has
# been wrong three times in this repo (the demo/ flatten, the tools/ move, here) and
# it fails silently, because the wrong parent is usually a directory that exists.
# The guard below turns that into an immediate, obvious failure.
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
[ -f "$ROOT/backend/server.py" ] || { echo "repo root not found at $ROOT (expected backend/server.py)" >&2; exit 1; }
M="$ROOT/models"
verify_sha256() { # file expected; an empty expectation preserves legacy non-image behavior
  local file="$1" expected="${2:-}" actual
  [ -n "$expected" ] || return 0
  actual="$(sha256sum < "$file")" || return 1
  actual="${actual%% *}"
  if [ "$actual" != "$expected" ]; then
    echo "SHA-256 mismatch for $file: expected $expected, got $actual" >&2
    return 1
  fi
}
get() { # url dest [expected-sha256]
  local url="$1" dest="$2" expected="${3:-}"
  [ -s "$dest" ] && {
    verify_sha256 "$dest" "$expected" || return 1
    echo "  have $(basename "$dest")"; return
  }
  echo "  get  $(basename "$dest")"
  # The destination directory may not exist. `llm/` and `image/` happen to, because they were
  # created by hand long ago, so nothing has ever exercised this -- but `whisper/` does not,
  # and on a fresh clone or a fresh install NONE of them do. curl does not create parents and
  # fails with a write error that reads like a network problem, which is the wrong diagnosis
  # to hand the person running an installer.
  mkdir -p "$(dirname "$dest")"
  curl -fL --retry 5 --retry-delay 3 -C - -o "$dest.part" "$url"
  verify_sha256 "$dest.part" "$expected" || return 1
  mv "$dest.part" "$dest"
}
adopt() { # legacy-path house-path [expected-sha256]
  local old="$1" new="$2" expected="${3:-}"
  if [ -s "$new" ]; then              # already adopted; verify before accepting
    verify_sha256 "$new" "$expected"; return $?
  fi
  [ -s "$old" ] || return 0            # never downloaded under the old name
  verify_sha256 "$old" "$expected" || return 1
  mv "$old" "$new"
  echo "  adopt $(basename "$new") <- $(basename "$old")"
}
image_model() { # adopt|get manifest-path; pins are mandatory for these four payloads
  local action="$1" path="$2" record repo file revision digest
  record="$(python3 -B - "$M/PROVENANCE.json" "$path" <<'PY'
import json
import re
import sys

with open(sys.argv[1], encoding="utf-8") as manifest:
    matches = [w for w in json.load(manifest)["weights"] if w["path"] == sys.argv[2]]
if len(matches) != 1:
    sys.exit(f"image provenance requires exactly one entry for {sys.argv[2]}")
w = matches[0]
for field, pattern in (("upstream_revision", r"[0-9a-f]{40}"), ("sha256", r"[0-9a-f]{64}")):
    value = w.get(field)
    if not isinstance(value, str) or not re.fullmatch(pattern, value):
        sys.exit(f"invalid or missing image provenance {field}: {sys.argv[2]}")
fields = [w["upstream_repo"], w["upstream_file"], w["upstream_revision"], w["sha256"]]
if any(not isinstance(value, str) or not value or any(c in value for c in "\t\r\n") for value in fields):
    sys.exit(f"invalid image provenance fields: {sys.argv[2]}")
print("\t".join(fields))
PY
  )" || return 1
  IFS=$'\t' read -r repo file revision digest <<< "$record"
  case "$action" in
    adopt) adopt "$M/image/$file" "$M/$path" "$digest" ;;
    get) get "$HF/$repo/resolve/$revision/$file" "$M/$path" "$digest" ;;
    *) echo "unknown image operation: $action" >&2; return 1 ;;
  esac
}
# Unconditional, and deliberately above the opt-in gate below: a 27B that was fetched under
# its upstream name must be renamed whether or not this run would fetch it.
echo "house names:"
adopt "$M/llm/Qwen2.5-7B-Instruct-Q4_K_M.gguf"   "$M/llm/symon-1.0-7b-q4_k_m.gguf"
adopt "$M/llm/Qwen2.5-14B-Instruct-Q4_K_M.gguf"  "$M/llm/symon-1.0-14b-q4_k_m.gguf"
adopt "$M/llm/Qwen2.5-0.5B-Instruct-Q4_K_M.gguf" "$M/llm/symon-1.0-draft-0.5b-q4_k_m.gguf"
adopt "$M/llm/Qwen3.6-27B-UD-Q2_K_XL.gguf"       "$M/llm/symon-1.0-27b-q2_k_xl.gguf"
adopt "$M/llm/mmproj-F16.gguf"                   "$M/llm/symon-1.0-27b-vision-f16.gguf"
image_model adopt image/symoneural-image-unet-q4_k.gguf
image_model adopt image/symoneural-image-t5-q8_0.gguf
image_model adopt image/symoneural-image-clip.safetensors
image_model adopt image/symoneural-image-vae.safetensors
adopt "$M/whisper/ggml-base.en.bin"              "$M/whisper/symoneural-listen-base-en.bin"
HF=https://huggingface.co
echo "chat surface:"
# 7B is the resident workhorse and the base the SyMoNeuRaL LoRA is trained against -- the
# adapter is rank-compatible with these weights and with nothing else. 14B is the heavy tier,
# loaded only when it is the whole job.
get "$HF/bartowski/Qwen2.5-7B-Instruct-GGUF/resolve/main/Qwen2.5-7B-Instruct-Q4_K_M.gguf"   "$M/llm/symon-1.0-7b-q4_k_m.gguf"
get "$HF/bartowski/Qwen2.5-14B-Instruct-GGUF/resolve/main/Qwen2.5-14B-Instruct-Q4_K_M.gguf" "$M/llm/symon-1.0-14b-q4_k_m.gguf"
get "$HF/bartowski/Qwen2.5-0.5B-Instruct-GGUF/resolve/main/Qwen2.5-0.5B-Instruct-Q4_K_M.gguf" "$M/llm/symon-1.0-draft-0.5b-q4_k_m.gguf"

# The speech surface. This script has carried the `adopt` line for the house name since the
# whisper work began -- and never carried a `get`, so the rename had nothing to rename and
# the weight was never fetched by the one script that is supposed to fetch weights. That is
# why `voice` and `sigils` have reported ASR unavailable for weeks while every other payload
# arrived: not a broken download, an absent one. NAMES.md has described this file the whole
# time, which is the reminder that a manifest entry is a description and not a fetch.
#
# base.en, English-only, ~142 MB. Big enough for the utterance these surfaces actually take
# -- a handful of words describing a sticker -- and a larger model is a straight swap,
# because both call sites pass the path and neither parses the name. MIT twice over: MIT at
# ggerganov for the conversion, MIT at OpenAI for what it is a conversion OF, and both texts
# are already in models/licenses/.
echo "speech surface:"
#
# NOT pinned here, deliberately, and the reason is worth stating because pinning it was the
# obvious-looking thing and was wrong. A digest passed to `get` is enforced against whatever
# comes back, and `apps/test_weight_names.py` exercises this script with a stubbed curl -- so
# a literal pin turns every run of that harness into a mismatch on a payload it never meant
# to check. The four image payloads ARE pinned, through `image_model`, which reads the digest
# out of PROVENANCE.json and whose entries the harness controls; the chat tiers above are not
# pinned at all. This follows the chat tiers, which is the convention for everything that is
# not one of those four.
#
# The digest is still RECORDED -- PROVENANCE.json carries sha256
# a03779c8... as measured on 2026-09-04. Recording what we got and enforcing it on the way in
# are different jobs, and only the first one belongs to the manifest.
get "$HF/ggerganov/whisper.cpp/resolve/main/ggml-base.en.bin" "$M/whisper/symoneural-listen-base-en.bin"
# The 27B tier is opt-in, not part of a default install: it is 11.85 GB on its own and is
# still being evaluated as a chat base, so a fresh clone should not pay for it silently.
#   SYMONEURAL_FETCH_27B=1 ./scripts/fetch-models.sh
#
# The gate used to be called SYM_FETCH_QWEN36, which put an upstream company name in an
# environment variable this repo owns. It is accepted as a legacy fallback below so an old
# command line or a stale shell export does not silently stop fetching.
#
# UD-Q2_K_XL is 11,849,779,424 bytes, which is where the "under 12" figure comes from, and it
# has been loaded here: fully GPU-resident at -ngl 99, 12,354 MiB of 16,303 at ctx 8192 / f16
# KV. UD-IQ2_M (10.85 GB) and UD-IQ2_XXS (9.39 GB) are smaller and have NOT been tested here --
# those are content-length readings, not load attempts, and this repo does not call a file size
# a fit. UD-Q4_K_XL (17.61 GB) exceeds the card and would need CPU offload against the 94 GB of
# system RAM in this box; also untested.
#
# Do NOT confuse this with the 11.87 GB on the NGC page for the NIM container. That is a
# compressed registry image size and the near-identical number is a coincidence -- see the
# header of scripts/nim-qwen36.sh. Only the figure here is a weights-on-disk measurement.
#
# The engine already understands these: the GGUF header declares
# general.architecture = qwen35, and contrib/llama.cpp carries LLM_ARCH_QWEN35. No build
# work was needed. The vision tower is fetched but not required -- text inference works
# without it.
if [ "${SYMONEURAL_FETCH_27B:-${SYM_FETCH_27B:-${SYM_FETCH_QWEN36:-0}}}" = "1" ]; then
  echo "chat surface (27B tier, opt-in):"
  get "$HF/unsloth/Qwen3.6-27B-GGUF/resolve/main/Qwen3.6-27B-UD-Q2_K_XL.gguf" "$M/llm/symon-1.0-27b-q2_k_xl.gguf"
  get "$HF/unsloth/Qwen3.6-27B-GGUF/resolve/main/mmproj-F16.gguf"             "$M/llm/symon-1.0-27b-vision-f16.gguf"
else
  echo "chat surface (27B tier): skipped -- set SYMONEURAL_FETCH_27B=1 to fetch 12.8 GB"
fi
# The 32B tier, also opt-in:
#   SYMONEURAL_FETCH_32B=1 ./scripts/fetch-models.sh
#
# UD-Q2_K_XL is 12,797,352,608 bytes. That is a content-length reading taken 2026-08-20, not
# a load attempt, and this repo does not call a file size a fit -- the arithmetic that made it
# worth fetching is: the 27B is 11,849,779,424 bytes and measures 12,354 MiB resident at
# -ngl 99, ctx 8192, f16 KV, so 12.80 GB of weights should land near 13.3 GB resident and
# leave roughly 2.9 GB of the card for KV and CUDA context. Near, should, roughly. Whether it
# actually holds is a llama-bench run, and until that run exists no tok/s or context figure
# from this tier goes on a page.
#
# The other quants were read at the same time and are recorded here so nobody re-measures
# them: UD-IQ2_M 11,553,366,688 B (smaller than the 27B already resident here, so near-certain
# to fit), UD-IQ2_XXS 9,277,096,608 B, UD-Q3_K_XL 16,403,102,368 B (exceeds the 16,303 MiB
# card outright and is not a candidate).
#
# This is NOT the NIM container route. nvcr.io/nim/qwen/qwen3-32b:1.0.0 is refused on three
# independent grounds -- it does not fit, NGC marks it end-of-support, and NVIDIA AI
# Enterprise licenses it for use rather than redistribution. See ops/docs/nim-on-one-card.md.
# The GGUF here is Apache-2.0 and carries none of those problems.
if [ "${SYMONEURAL_FETCH_32B:-${SYM_FETCH_32B:-0}}" = "1" ]; then
  echo "chat surface (32B tier, opt-in):"
  get "$HF/unsloth/Qwen3-32B-GGUF/resolve/main/Qwen3-32B-UD-Q2_K_XL.gguf" "$M/llm/symon-1.0-32b-q2_k_xl.gguf"
else
  echo "chat surface (32B tier): skipped -- set SYMONEURAL_FETCH_32B=1 to fetch 12.80 GB"
fi
echo "image surface:"
image_model get image/symoneural-image-unet-q4_k.gguf
image_model get image/symoneural-image-vae.safetensors
image_model get image/symoneural-image-clip.safetensors
image_model get image/symoneural-image-t5-q8_0.gguf
# Licences travel with the weights. models/ is gitignored (40 GB), so these files exist
# on disk beside what they cover rather than in git -- and they must be included in any
# customer image. Apache-2.0 obliges shipping the licence text with the artefact.
#
# These filenames keep the upstream name on purpose, and they are the one exception to the
# house-name rule. A licence text is an attribution artefact: a file called
# symon-1.0-7b.LICENSE.txt would be asserting that we licensed those weights, which is not
# what the document says. PROVENANCE.json points each house name at the licence covering it.
echo "licences:"
L="$M/licenses"; mkdir -p "$L"
lic() { # url dest
  [ -s "$L/$2" ] && { echo "  have $2"; return; }
  if curl -fsSL --retry 3 -o "$L/$2.part" "$1" 2>/dev/null && [ -s "$L/$2.part" ]; then
    mv "$L/$2.part" "$L/$2"; echo "  get  $2"
  else
    rm -f "$L/$2.part"; echo "  MISS $2 (fetch by hand before shipping a build)" >&2
  fi
}
lic "$HF/Qwen/Qwen2.5-7B-Instruct/resolve/main/LICENSE"   Qwen2.5-7B-Instruct.LICENSE.txt
lic "$HF/Qwen/Qwen2.5-14B-Instruct/resolve/main/LICENSE"  Qwen2.5-14B-Instruct.LICENSE.txt
lic "$HF/Qwen/Qwen2.5-0.5B-Instruct/resolve/main/LICENSE" Qwen2.5-0.5B-Instruct.LICENSE.txt
# black-forest-labs ships no LICENSE file; the apache-2.0 declaration is in the model card,
# so the card is the artefact worth keeping.
lic "$HF/black-forest-labs/FLUX.1-schnell/resolve/main/README.md" FLUX.1-schnell.MODEL-CARD.md

echo "done."
