# repo.sh -- find the repository, once, correctly.
#
# Source it:  . "$(dirname "${BASH_SOURCE[0]}")/lib/repo.sh"
#
# ## Why this is a library and not four lines in each script
#
# Sixteen scripts under scripts/ resolved the repository root and did it EIGHT different
# ways -- `$(dirname "$0")/..`, `$HERE/..`, `$(dirname "${BASH_SOURCE[0]}")/..`, `$(pwd)`,
# `git rev-parse --show-toplevel`, and three more. Fourteen then guarded on a marker, two of
# them on a DIFFERENT marker.
#
# All but one counted parents, and parent-counting is the failure this repository has paid
# for more than any other: it broke on the demo/ flatten, on the tools/ move, on the
# backend/ move, and on 2026-09-11 it broke 63 Python anchors at once when every tool moved
# one level deeper. It fails SILENTLY, because the wrong parent is usually a directory that
# exists.
#
# `$(pwd)` is worse than parent-counting and it was in the highest-consequence script here:
# scripts/model-staging/symoneural-model-stage.sh, which swaps the model a live surface
# loads, worked only if you happened to be standing in the repository root and refused from
# anywhere else.
#
# `git rev-parse` is wrong for a different reason: it answers about a git checkout, and this
# tree is also installed and run from places that are not one.
#
# So: WALK UP FOR THE MARKER. It survives any move of the script, needs no git, and the one
# thing it depends on -- backend/server.py -- is the thing whose absence means this is not
# the repository.

repo_root() {
  local d
  d="$(cd -- "$(dirname -- "${BASH_SOURCE[1]:-$0}")" && pwd -P)"
  while [ "$d" != "/" ]; do
    [ -f "$d/backend/server.py" ] && { printf '%s\n' "$d"; return 0; }
    d="$(dirname -- "$d")"
  done
  return 1
}

# The message names the FILE, not a conclusion about the root. Commissioning moved
# gpu-governor.sh aside to see what an operator would read and got "repo root not found at
# /home/google/Symoneural" -- which was the one thing that was not wrong.
require_repo() {
  ROOT="$(repo_root)" || {
    printf '%s: not inside a SyMoNeuRaL checkout -- no backend/server.py above %s\n' \
           "${PROG:-${0##*/}}" "$(dirname -- "${BASH_SOURCE[1]:-$0}")" >&2
    exit 1
  }
  readonly ROOT
  export ROOT
}

require_repo
