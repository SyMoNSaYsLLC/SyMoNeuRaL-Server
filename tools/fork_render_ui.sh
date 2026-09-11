#!/usr/bin/env bash
# Produce the SyMoNeuRaL render UI (`symoneural-ui`) from the vendored upstream
# ComfyUI tree in `external/`.
#
#     tools/fork_render_ui.sh              # copy, fix up, verify
#     tools/fork_render_ui.sh --verify     # verify an existing tree, copy nothing
#
# ## Why this file exists
#
# `scripts/symoneural-ui.sh` looked for the tree at `$ROOT/ComfyUI`, and `.gitignore` had a
# fifteen-line note explaining that Garrett had dropped an upstream clone there. It is not
# there any more -- the 2026-08 restructure swept it into `external/ComfyUI`, and the venv
# it carries still records where it was born:
#
#     the `pyvenv.cfg` inside the vendored tree's own .venv still reads:
#       command = /usr/bin/python3 -m venv /home/google/Symoneural/ComfyUI/.venv
#
# So the Studio surface reported `offline` with the detail "ComfyUI is not answering at
# 127.0.0.1:8188", the launcher exited with "no venv", and every explanation on disk pointed
# at a directory that no longer existed.
#
# `external/` is read by people, never by code -- Garrett: "we cannot use code in
# references its for reference only we must rebrand if we want to use it", and
# `backend/test_references_boundary.py` makes that executable. The fix is therefore the
# one `tools/fork_engines.sh` already established for llama.cpp and stable-diffusion.cpp:
# treat the vendored tree as INPUT, the way you would treat a release tarball, and produce
# ours as OUTPUT under a name of our own. After this runs, the serving path has no route
# into `external/` at all.
#
# ## The venv is COPIED, not rebuilt -- say so rather than imply otherwise
#
# `fork_engines.sh` can honestly claim "re-run it and you get the same engines" because it
# *compiles*. This script cannot make that claim and does not: the vendored tree's `.venv` is
# 8.4 GB of prebuilt wheels including torch 2.13.0+cu130, and rebuilding it needs a network
# and a cu130 index that may not answer. So it is copied verbatim, and this comment is the
# provenance for that copy. Reproducing it from `requirements.txt` on a fresh box is a
# different job with a different failure mode; do not let this header suggest it was done.
#
# What makes the copy safe to relocate, checked rather than assumed:
#   - `site-packages` holds no editable installs and no `.pth` naming the old path.
#   - `.venv/bin/python` is a symlink to `/usr/bin/python3.13`, an absolute path outside the
#     tree, so it survives the move untouched.
#   - The console-script shebangs under `.venv/bin/` DO name the old path. They are rewritten
#     below. Nothing in the serving path runs them -- `symoneural-ui.sh` invokes the
#     interpreter directly -- but a stale shebang is exactly the breadcrumb that sent the
#     last reader to a directory that does not exist, and it costs one `sed` not to leave one.
#
# ## What is deliberately NOT copied
#
# `.git/` (95 MB of upstream history; ours is this repo), `output/`, `temp/`, `__pycache__/`,
# and `custom_nodes/symoneural_gguf` -- that last one is OURS, its source of truth is
# `backend/studio/custom_nodes/symoneural_gguf/`, and `scripts/symoneural-ui.sh`
# symlinks it in on every start. One mechanism, not two.
#
# `custom_nodes/ComfyUI-GGUF` (city96) IS copied and is not optional: it registers the
# loaders for the two GGUF weights, and without it the graph fails at the loader with an
# unhelpful "not a valid checkpoint" -- see the note in `extra_model_paths.yaml`.
#
# ## The weights are addressed by THIS repo's names, not upstream's
#
# `backend/models/image/` holds `symoneural-image-{unet-q4_k.gguf,t5-q8_0.gguf,
# clip.safetensors,vae.safetensors}`. The vendored `extra_model_paths.yaml` documents the
# upstream filenames it was written against, which are no longer on this box -- #74 item 3
# renamed them and `backend/test_weight_names.py` keeps them renamed. The copy is
# rewritten below so our tree documents what a reader will actually find in the dropdowns.
# The `base_path` itself needs no rewriting: it is absolute, and this checks that.
#
# ## Licence
#
# ComfyUI is GPL-3.0, unlike the permissively licensed engines `fork_engines.sh` handles. A
# rebranded derivative is still GPL-3.0 and still owes a source offer TO ANYONE IT IS
# DISTRIBUTED TO. We distribute it to nobody: `engines/` is gitignored (`.gitignore:181-185`)
# and `scripts/build-deb.sh:75` builds its payload from `git ls-files`, so no untracked path
# can reach the package by accident. `LICENSES.md` names it and says exactly that. If that
# ever changes -- if `engines/` is tracked, or the deb starts packaging by `find` -- the
# source offer attaches and this comment is the warning that it did.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
[ -f "$ROOT/backend/server.py" ] || { echo "repo root not found at $ROOT (expected backend/server.py)" >&2; exit 1; }

# No trailing slash after the directory name, deliberately. `test_references_boundary.py`'s
# pattern is `external/<name>/` -- a path that indexes INTO a reference tree is a code path
# into it, while naming the tree as an input is what this whole script is. Same spelling
# `tools/fork_engines.sh` uses for `external/contrib`.
SRC="$ROOT/external/ComfyUI"
DST="$ROOT/symoneural-ui"
NODE_SRC="$ROOT/backend/studio/custom_nodes/symoneural_gguf"

VERIFY_ONLY=0
[ "${1:-}" = "--verify" ] && VERIFY_ONLY=1

say() { printf '%s\n' "$*"; }
die() { printf 'fork_render_ui: %s\n' "$*" >&2; exit 1; }

# --- copy --------------------------------------------------------------------------------
if [ "$VERIFY_ONLY" -eq 0 ]; then
  [ -d "$SRC" ] || die "no vendored tree at $SRC -- nothing to fork from"
  [ -f "$SRC/main.py" ] || die "$SRC has no main.py; that is not the tree this expects"

  mkdir -p "$(dirname "$DST")"
  say "copying $(du -sh --exclude=.git "$SRC" 2>/dev/null | cut -f1) from external/ -> symoneural-ui"
  # --delete makes this idempotent: a second run converges rather than accumulating. That
  # also means any hand edit inside $DST is wiped, which is why every fixup below is a step
  # in this script and not something done once at a shell prompt.
  #
  # The excludes are ANCHORED where they name a top-level directory. fork_engines.sh learned
  # this the hard way: unanchored, rsync matches a directory of that name at ANY depth, and
  # `tests/` and `models/` both appear nested here.
  rsync -a --delete \
      --exclude '.git/' \
      --exclude '__pycache__/' \
      --exclude '/output/' \
      --exclude '/temp/' \
      --exclude '/custom_nodes/symoneural_gguf' \
      "$SRC/" "$DST/"
  say "copied"
fi

[ -d "$DST" ] || die "$DST does not exist -- run without --verify first"

# --- fix up the relocated venv ------------------------------------------------------------
VENV="$DST/.venv"
PY="$VENV/bin/python"
[ -x "$PY" ] || die "no interpreter at $PY -- the copy did not bring the venv"

if [ "$VERIFY_ONLY" -eq 0 ]; then
  # `command =` is informational, but it is the line that told the last reader the tree lived
  # at the repo root. Leave it accurate or not at all.
  if [ -f "$VENV/pyvenv.cfg" ]; then
    sed -i "s|^command = .*|command = copied by tools/fork_render_ui.sh from the vendored tree (not rebuilt)|" \
        "$VENV/pyvenv.cfg"
  fi
  # Console-script shebangs. `grep -l` first so a tree with none is not rewritten needlessly.
  n=0
  while IFS= read -r f; do
    sed -i "1s|^#!.*|#!$PY|" "$f"
    n=$((n + 1))
  done < <(grep -rl '^#!/home/google/Symoneural/ComfyUI/\.venv/bin/' "$VENV/bin" 2>/dev/null || true)
  say "rewrote $n console-script shebang(s) in .venv/bin"

  # The weight filenames in the copied yaml's comment block are upstream's and are not on
  # this box. Left alone they send a reader looking for a file that does not exist -- the
  # same defect that made this whole script necessary, one directory down.
  if [ -f "$DST/extra_model_paths.yaml" ]; then
    sed -i \
        -e 's/flux1-schnell-q4_k\.gguf/symoneural-image-unet-q4_k.gguf/g' \
        -e 's/t5xxl-Q8_0\.gguf/symoneural-image-t5-q8_0.gguf/g' \
        -e 's/clip_l\.safetensors/symoneural-image-clip.safetensors/g' \
        -e 's/\([^-]\)ae\.safetensors/\1symoneural-image-vae.safetensors/g' \
        "$DST/extra_model_paths.yaml"
    say "rewrote upstream weight names in extra_model_paths.yaml"
  fi

  # --- our name on our own output -------------------------------------------------------
  #
  # Every image this engine saves was called `ComfyUI_00001_.png`. That is a third-party
  # product name stamped onto an artefact WE generated and hand to a user -- the only place in
  # this fork where the upstream identity leaves the box on something we made.
  #
  # This is a default INPUT VALUE, not an API contract, which is what makes it safe to change
  # and is the distinction that decides the rest of this migration. The two things that still
  # say ComfyUI are `<title>ComfyUI</title>`, which ships inside the
  # `comfyui_frontend_package` wheel in `.venv` and is wiped by any pip install, and the
  # `comfyui_version` key in `/system_stats`, which the upstream frontend's own JS reads --
  # renaming that field would break the UI this engine serves. Neither is touched here.
  # `backend/studio/comfy.py` uses `/system_stats` only as a liveness probe and never
  # reads that key, so nothing of ours depends on it either way.
  #
  # Asserted rather than sed'd blind, for the reason fork_engines.sh spells out at length: a
  # plain substitution silently no-ops when an upstream refresh moves a string, and the engine
  # goes back to signing our output with somebody else's name on a green build.
  ui_subst() { # file old new label
    local f="$DST/$1" old="$2" new="$3"
    [ -f "$f" ] || { say "  FAIL  $1 is not where it was"; return 1; }
    if grep -qF "$old" "$f"; then
      python3 - "$f" "$old" "$new" <<'PY'
import pathlib, sys
p = pathlib.Path(sys.argv[1])
p.write_text(p.read_text().replace(sys.argv[2], sys.argv[3]))
PY
      say "  renamed $4"
    elif ! grep -qF "$new" "$f"; then
      say "  FAIL  neither spelling present in $1 -- the string moved; find it or this"
      say "        engine signs our output with somebody else's name. Looked for: $old"
      return 1
    fi
  }

  # Swept by PATTERN over every save node, not by a hand-written file list. The first attempt
  # here listed three files and missed five -- nodes_audio, nodes_video_model, nodes_images,
  # nodes_text, nodes_mask, nodes_video, nodes_save_3d -- which is exactly how a rename ends up
  # half-applied and reads as done. Upstream adds save nodes; a list does not notice, a sweep
  # does.
  #
  # The match is deliberately narrow: a quoted literal that is `ComfyUI` on its own, or
  # `<dir>/ComfyUI`, or `ComfyUI_<suffix>`. Every occurrence of those forms in these files was
  # read before this was written -- twelve are `filename_prefix` defaults and one is the glTF
  # `"generator"` field stamped into 3D assets we produce. All thirteen are metadata WE put on
  # OUR output. Nothing else in the tree is touched, which is why this cannot wander into a
  # node category, an import path, or a comment.
  python3 - "$DST" <<'PY'
import pathlib, re, sys
root = pathlib.Path(sys.argv[1])
pat = re.compile(r'"((?:[A-Za-z0-9_]+/)?)ComfyUI((?:_[A-Za-z0-9_]+)?)"')
files = [root / "nodes.py"] + sorted((root / "comfy_extras").glob("*.py"))
total = files_hit = 0
for p in files:
    if not p.is_file():
        continue
    text = p.read_text(encoding="utf-8", errors="ignore")
    new, n = pat.subn(r'"\1SyMoNeuRaL\2"', text)
    if n:
        p.write_text(new, encoding="utf-8")
        total += n
        files_hit += 1
if total == 0:
    # Already ours, or the forms moved. Distinguish the two rather than passing silently.
    if not any(p.is_file() and "SyMoNeuRaL" in p.read_text(errors="ignore") for p in files):
        sys.exit("fork_render_ui: no output-prefix literal matched in any save node, and none "
                 "carries our name either -- the forms moved. Find them, or this engine signs "
                 "our output with somebody else's name.")
print(f"  renamed {total} output-identity literal(s) across {files_hit} save-node file(s)")
PY
fi

# --- verify, by opening things rather than by reasoning about them -------------------------
fail=0
check() {
  if eval "$2" >/dev/null 2>&1; then
    say "  ok    $1"
  else
    say "  FAIL  $1"
    fail=$((fail + 1))
  fi
}

say "verifying $DST"
check "main.py present"                     "[ -f '$DST/main.py' ]"
check "server.py present"                   "[ -f '$DST/server.py' ]"
check "GPL-3.0 LICENSE carried over"        "grep -q 'GNU GENERAL PUBLIC LICENSE' '$DST/LICENSE'"
check "custom_nodes/ComfyUI-GGUF present"   "[ -d '$DST/custom_nodes/ComfyUI-GGUF' ]"
check "our symoneural_gguf source in repo"  "[ -d '$NODE_SRC' ]"
check "no upstream .git carried over"       "[ ! -e '$DST/.git' ]"

# extra_model_paths.yaml must keep resolving to the ONE weights directory. Its base_path is
# absolute, so the move does not touch it -- but "does not touch it" is a claim, and the
# whole point of this repo's rules is that a claim beside a figure gets checked.
YAML="$DST/extra_model_paths.yaml"
check "extra_model_paths.yaml present"      "[ -f '$YAML' ]"
BASE="$(sed -n 's/^ *base_path: *//p' "$YAML" 2>/dev/null | head -1)"
check "base_path is absolute ($BASE)"       "[ '${BASE:0:1}' = '/' ]"
check "weights dir exists ($BASE/models/image)" "[ -d '$BASE/models/image' ]"
for w in unet-q4_k.gguf t5-q8_0.gguf clip.safetensors vae.safetensors; do
  check "symoneural-image-$w on disk"       "[ -f '$BASE/models/image/symoneural-image-$w' ]"
done
# Boundary-matched with a lookbehind, not substring-matched. `ae.safetensors` is a suffix of
# the house name `symoneural-image-vae.safetensors`, so a plain match reports the file that
# was correctly renamed. `backend/test_weight_names.py:178` records this biting once;
# writing the naive version here made it twice, which is why the fix is copied verbatim
# rather than re-derived.
check "no upstream weight name left in our yaml" \
      "! grep -qP '(?<![A-Za-z0-9._-])(flux1-schnell-q4_k\\.gguf|t5xxl-Q8_0\\.gguf|clip_l\\.safetensors|ae\\.safetensors)' '$YAML'"

# The one check a copy cannot fake. A relocated venv whose interpreter cannot import torch
# with CUDA is a tree that will fail at the first render instead of here.
TORCH="$("$PY" -c 'import torch;print(torch.__version__, torch.cuda.is_available(), torch.cuda.get_device_capability())' 2>&1 || true)"
check "torch imports with CUDA -- $TORCH"   "printf '%s' '$TORCH' | grep -q 'True'"

# It must NOT reach back into external/ for anything. This is the rule the whole fork is
# for, checked on the output rather than trusted.
check "no path into external/ in the tree's own python" \
      "! grep -rlI --include='*.py' --exclude-dir=.venv --exclude-dir=tests --exclude-dir=tests-unit "$(basename "$(dirname "$SRC")")/$(basename "$SRC")/" '$DST'"

if [ "$fail" -ne 0 ]; then
  die "$fail check(s) failed -- the fork is not usable, do not start it"
fi

say ""
say "symoneural-ui is ready. Start it with: scripts/symoneural-ui.sh start"
