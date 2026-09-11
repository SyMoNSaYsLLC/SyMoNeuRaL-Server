#!/usr/bin/env bash
# archive-guard.sh -- the one leak check every archive path calls.
#
#     source "$ROOT/scripts/lib/archive-guard.sh"
#     archive_guard shareable        "$STAGE_ROOT"   # refuse outright on any hit
#     archive_guard local-authorized "$STAGE_ROOT"   # allow, but the manifest must name them
#
# WHY THIS IS A LIBRARY AND NOT A BLOCK IN build-deb.sh
#
# It was a block in build-deb.sh, and build-deb.sh was one of three packaging paths. The
# other two -- the repo tar.gz and the shareable allv3 archives -- had no check at all,
# because a check that lives inside one script protects one script. A copied check is a
# check that drifts: the .deb's list was updated when `training/project-history/` landed and
# a copy elsewhere would not have been.
#
# THE TWO MODES ARE NOT A STYLE CHOICE
#
# `shareable`        -- the artifact leaves the box. Any hit is fatal. No override exists,
#                       because the override is what gets used at 2am.
# `local-authorized` -- the artifact stays on the box and is ALLOWED to contain the
#                       protected material (the owner's own backup of his own trade secret
#                       is not a leak). The obligation is different, not absent: every hit
#                       must be named in SECRETS-INSIDE.txt at the archive root. An
#                       unlabelled backup is how a local archive becomes a shared one six
#                       months later.
#
# WHY `.git/` IS ON THE SHAREABLE LIST
#
# Rotating a secret does not touch history. `backend/remix/.env` was tracked from
# `9b5da84` until it was untracked at `d453c65`, so the pre-rotation values are in a blob
# that any clone of this repo carries -- including SPOTIFY_CLIENT_SECRET, which is
# provider-issued, was never rotated, and is still live. A tarball containing `.git` is
# therefore a tarball containing a live credential, and the original v1 leak was exactly
# that shape. `build-deb.sh` is immune by construction because it builds its manifest from
# `git ls-files`, which never lists `.git` itself; a `tar czf` of the working tree has no
# such protection, which is why the rule lives here rather than in the one script that did
# not need it.
#
# WHY THERE IS A CONTENT SCAN AND NOT JUST A PATH LIST
#
# A path list catches `backend/remix/.env`. It does not catch `remix.env.backup`,
# `.env.old`, or a vault file named `remix.env.pre-rotation-20260820`. The values are what
# matter, so the scan looks for the assignment shape of the keys this repo actually defines.
# Key NAMES appear below; no value is ever read into a variable, printed, or logged.

# `.claude/` is retained in the table below after the 2026-09-08 neutralisation. The
# authority moved to ops/authority/ and HANDOFF.md and the path was untracked -- but
# it is still PHYSICALLY present, holding settings and a pasted transcript, until the
# owner's retirement purge. A rule protecting a path that still exists is not stale, and
# deleting it because the tracking changed would let that directory into a tarball.
#
# The note is HERE and not beside the entry because the table is a backslash-continued
# argument list: a `#` inside it comments out the continuation and silently empties the
# path list. Doing exactly that broke 21 of this guard's own tests, which is the only
# reason it was caught.
# The protected paths, relative to the archive root. Extended-regex, anchored at the root.
# Keep the reason beside the pattern -- an exclusion whose reason is not written down is an
# exclusion the next person deletes.
# Fields are TAB-separated, NOT `|`-separated: the patterns are extended-regex and contain
# `|` themselves, so splitting on it truncates `(^|/)\.env$` to `(^` and grep then dies with
# "Unmatched ( or \(" -- silently scanning nothing, which reads as "clean".
_ag_forbidden_paths() {
  printf '%s\n' \
    'training/corpus\.jsonl$	the corpus: 327 hand-authored examples, trade secret' \
    'training/build_dataset\.py$	the method that produces the corpus' \
    'training/project-history/	corpus-adjacent tooling' \
    'training/adapter(-[a-z0-9]+)?/	adapter configs name the rank and target modules' \
    '\.claude/	internal working documents, including HANDOVER.md' \
    '(^|/)[^/]*\.env([^A-Za-z0-9]|$)	a real env file; the .example files are deliberately fine'
}

# `.git/` is shareable-only: a local backup SHOULD contain history, that is the point of a
# backup. Kept separate from the list above rather than flagged inside it.
_AG_GIT_PATTERN='(^|/)\.git/'

# Key names only. Never a value.
#
# `SYMONEURAL_OBS_PASSWORD` joined the list on 2026-08-21 with #96. The path list above
# already refuses `backend/live/symoneural-live.env`, so this entry is not for the file
# the rule names -- it is for `live.env.old`, `symoneural-live.env.pre-rotation`, and the copy
# somebody pastes into a scratch note. That gap is the whole reason a content scan exists
# beside a path list, and adding the key at the same time as the app is the only moment
# anybody is thinking about it.
_AG_SECRET_KEYS='SPOTIFY_CLIENT_ID|SPOTIFY_CLIENT_SECRET|SPOTIFY_REDIRECT_URI|SYMON_URL|VLLM_API_KEY|DJ_TOKEN|DJ_TOKEN_PATH|DJ_HOST|DJ_PORT|SYMONEURAL_OBS_PASSWORD'

# Bulk directories the content scan may skip -- and ONLY in local-authorized mode.
#
# The content scan reads bytes. `grep -I` skips binary files, but it must read a file to
# decide it is binary, so "skip" costs a full read. On this box the working tree is 158 GiB
# (models 115G, references 12G, engines 9.5G, training/.venv 7.2G, contrib 6.9G), and
# #15 hardlinks all of it. Scanning that unpruned takes hours; pruning it takes 0.33 s.
#
# WHY THIS IS SAFE FOR local-authorized AND NOT FOR shareable
#
# A shareable archive is built from `git ls-files`, so none of these directories can be in one
# -- every entry here is gitignored bulk data. The scan therefore prunes NOTHING in shareable
# mode: the archive is ~23 MiB, a full scan is cheap, and the mode whose failure ships a
# credential is not the mode to take a shortcut in. In local-authorized mode the tree is the
# whole 158 GiB and the material is authorized to be there anyway.
#
# Pruning is never silent. Every entry that exists under the root is printed on the summary
# line as "not scanned", because a scan that quietly skipped 115 GiB reads as "clean".
# `engines` is here and `ComfyUI` is not, and that swap is the whole of a 2026-08-21 fix.
# The render UI was a clone at the repo root called `ComfyUI/`; it is now `symoneural-ui`,
# beside the two forked C++ engines, all three produced by scripts in `tools/` and all three
# gitignored under `/engines/`. An entry here that matches no directory prunes nothing and says
# nothing about it -- the summary line only names entries that exist -- so the scan silently
# went back to reading 9.5 GiB it had been skipping since this list was written. Slow, not
# wrong; but "slow enough that nobody runs it" is how a credential scan stops being run.
_AG_PRUNE_DIRS='models	references	engines	contrib	.venv	node_modules	__pycache__	run'

# archive_guard <shareable|local-authorized> <root> [label]
# Returns 0 if the archive may be built, 1 if it may not. Prints findings to stderr.
archive_guard() {
  local mode="$1" root="$2" label="${3:-archive}"
  local hits=() n_path=0 n_content=0

  case "$mode" in
    shareable|local-authorized) ;;
    *) echo "archive_guard: unknown mode '$mode'" >&2; return 2 ;;
  esac
  [ -d "$root" ] || { echo "archive_guard: '$root' is not a directory" >&2; return 2; }

  # --- path scan -------------------------------------------------------------------
  # One `find` and one `grep` over the whole path list, then reasons are attached in bash.
  # The obvious shape -- a grep per pattern per path -- is 7 x N subprocesses and took
  # minutes on this repo. Directories are emitted with a trailing slash so `.claude/` and
  # `training/adapter/` match the directory itself and not merely files beneath it.
  # `.git` is pruned here (40k objects, nothing inside it is individually interesting) and
  # judged as a single finding below.
  local combined rel line pat why
  combined="$(_ag_forbidden_paths | cut -f1 | paste -sd'|' -)"
  while IFS= read -r rel; do
    case "$rel" in *.env.example) continue ;; esac   # documents the keys, carries no values
    why="protected path"
    while IFS= read -r line; do
      pat="$(printf '%s' "$line" | cut -f1)"
      if printf '%s\n' "$rel" | grep -Eq "$pat"; then
        why="$(printf '%s' "$line" | cut -f2-)"; break
      fi
    done < <(_ag_forbidden_paths)
    hits+=("$rel  --  $why"); n_path=$((n_path + 1))
  done < <(cd "$root" \
             && find . -name .git -prune -o -type d -printf '%p/\n' -o -type f -printf '%p\n' 2>/dev/null \
             | sed 's|^\./||' | grep -E "$combined" | sort -u)

  # `.git/` -- only fatal for a shareable artifact, and reported as one finding, not 40,000.
  if [ "$mode" = shareable ] && [ -e "$root/.git" ]; then
    hits+=(".git/  --  history carries the pre-rotation secrets from 9b5da84; SPOTIFY_CLIENT_SECRET was never rotated")
    n_path=$((n_path + 1))
  fi

  # --- content scan ----------------------------------------------------------------
  # Any file assigning one of this repo's secret keys a non-empty, non-placeholder value.
  # Binary files are skipped by grep -I. The match is reported by PATH ONLY.
  local f
  while IFS= read -r f; do
    hits+=("${f#./}  --  assigns a secret key a non-empty value"); n_content=$((n_content + 1))
  done < <(cd "$root" && grep -rIlE "^[[:space:]]*(${_AG_SECRET_KEYS})=[^[:space:]\"']" . \
             --exclude-dir=.git --exclude='*.env.example' --exclude='*.md' 2>/dev/null | sort -u)

  local total=$(( n_path + n_content ))
  if [ "$total" -eq 0 ]; then
    echo "archive_guard[$mode]: $label clean -- 0 protected paths, 0 secret-bearing files" >&2
    return 0
  fi

  # --- verdict ---------------------------------------------------------------------
  if [ "$mode" = shareable ]; then
    echo "archive_guard[shareable]: REFUSING to build $label -- $total finding(s):" >&2
    printf '  LEAK: %s\n' "${hits[@]}" >&2
    echo "  A shareable archive may contain none of these. There is no override." >&2
    return 1
  fi

  # local-authorized: the material may be present, but the manifest must name it.
  local manifest="$root/SECRETS-INSIDE.txt"
  if [ ! -f "$manifest" ]; then
    echo "archive_guard[local-authorized]: REFUSING to build $label -- $total protected item(s) present and no SECRETS-INSIDE.txt at the archive root." >&2
    printf '  UNDECLARED: %s\n' "${hits[@]}" >&2
    return 1
  fi

  local undeclared=() h p
  for h in "${hits[@]}"; do
    p="${h%%  --  *}"
    grep -qF -- "$p" "$manifest" || undeclared+=("$p")
  done
  if [ "${#undeclared[@]}" -gt 0 ]; then
    echo "archive_guard[local-authorized]: REFUSING to build $label -- SECRETS-INSIDE.txt does not name ${#undeclared[@]} of $total protected item(s):" >&2
    printf '  UNDECLARED: %s\n' "${undeclared[@]}" >&2
    echo "  An unlabelled local archive is how a local archive becomes a shared one." >&2
    return 1
  fi

  echo "archive_guard[local-authorized]: $label carries $total protected item(s), all named in SECRETS-INSIDE.txt" >&2
  return 0
}
