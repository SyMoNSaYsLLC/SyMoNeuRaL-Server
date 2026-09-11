# fetch.sh -- download to a .part, verify, then promote. Never the other way round.
#
# Source it:  . "$ROOT/scripts/lib/say.sh"; . "$ROOT/scripts/lib/fetch.sh"
#
# Two scripts fetch large files -- fetch-models.sh (50 GB of weights) and fetch-cutout.sh --
# and they had the same three-step shape written twice, with different retry counts and one
# of them missing the verify. The shape is not incidental: `tests/models/test_weight_names.py`
# has four cases named after what goes wrong without it, including
# `test_same_size_corrupt_download_is_not_promoted`. A truncated download that happens to
# match the expected byte count will load, and produce noise.
#
# Three rules, and each one is a test:
#
#   1. The download lands at `<dest>.part`, never at `<dest>`. An interrupted run leaves
#      no file that looks complete.
#   2. It is verified BEFORE the rename. A corrupt `.part` is removed, not promoted.
#   3. An existing `<dest>` is re-verified rather than trusted. "Already there" is a claim
#      about bytes, and the whole point of the manifest is that such claims are checkable.

# `< "$file"` rather than `sha256sum "$file"`: the filename form puts the path in the output
# and every caller then has to strip it. Reading from stdin gives the digest and a dash.
verify_sha256() { # file expected-hex   (an empty expectation passes -- not every source pins)
  local file="$1" want="${2:-}" got
  [ -n "$want" ] || return 0
  got="$(sha256sum < "$file")" || return 1
  got="${got%% *}"
  [ "$got" = "$want" ] && return 0
  warn "SHA-256 mismatch for $file"
  dim  "expected $want"
  dim  "got      $got"
  return 1
}

# -C - resumes a partial transfer, which on a 12 GB weight file is the difference between a
# retry and a re-download. mkdir -p because curl does not create parents and fails with a
# write error that reads like a network problem -- the wrong diagnosis to hand an installer.
fetch_verified() { # url dest [expected-sha256]
  local url="$1" dest="$2" want="${3:-}"
  if [ -s "$dest" ]; then
    verify_sha256 "$dest" "$want" || return 1
    dim "have $(basename -- "$dest")"
    return 0
  fi
  dim "get  $(basename -- "$dest")"
  mkdir -p -- "$(dirname -- "$dest")"
  if ! curl -fL --retry 5 --retry-delay 3 -C - -o "$dest.part" "$url"; then
    rm -f -- "$dest.part"
    warn "download failed: $url"
    return 1
  fi
  verify_sha256 "$dest.part" "$want" || { rm -f -- "$dest.part"; return 1; }
  mv -- "$dest.part" "$dest"
}

# Licence texts are small, unpinned, and their absence must not stop a build -- but it must
# be SAID. Apache-2.0 §4(a) obliges the text to travel with the work, and a table row
# claiming Apache-2.0 while no text ships is the obligation restated, not met.
fetch_licence() { # url dest
  local url="$1" dest="$2"
  [ -s "$dest" ] && { dim "have $(basename -- "$dest")"; return 0; }
  mkdir -p -- "$(dirname -- "$dest")"
  if curl -fsSL --retry 3 -o "$dest.part" "$url" 2>/dev/null && [ -s "$dest.part" ]; then
    mv -- "$dest.part" "$dest"; dim "get  $(basename -- "$dest")"
  else
    rm -f -- "$dest.part"
    warn "MISS $(basename -- "$dest") -- fetch by hand before shipping a build"
  fi
}
