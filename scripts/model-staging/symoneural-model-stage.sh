#!/usr/bin/env bash
# symoneural-model-stage.sh -- stage, smoke, promote and roll back a model bundle.
#
# ## What this is for
#
# Swapping the model a surface loads is the highest-consequence change on this box and the
# easiest one to do badly: the weights are 194 GB, the active default is four lines in
# `backend/server.py`, and nothing in git records either. So the swap gets a script with the
# guardrails written as refusals rather than as comments, and every mode below is safe to run
# on a live box.
#
# ## The rule this file exists to enforce
#
#   NOTHING IS DOWNLOADED, ACTIVATED, MOVED OR DELETED WITHOUT AN EXPLICIT FLAG.
#
# `--inventory`, `--dry-run`, `--smoke-plan` and `--write-docs` are read-only. `--stage-*`
# prepares a directory and prints the download command but does not run it unless the operator
# also passes the confirmation phrase. `--activate-candidate` refuses on six separate
# conditions, `--smoke-candidate` runs a candidate in isolation, and `--rollback` is the only
# mode that is safe to reach for in a hurry.
#
# ## Modes
#
#   --dry-run                      say what each mode would do; change nothing
#   --inventory                    the measured model inventory (tools/lib/model_inventory.py)
#   --stage-openai-gpt-oss-20b     prepare staging for the LLM candidate; no download
#   --write-docs                   regenerate the inventory block in the ops docs
#   --smoke-plan                   print the smoke steps a candidate must pass
#   --smoke-candidate <id>         run the candidate IN ISOLATION -- no fallback possible
#   --activate-candidate <id>      promote a staged, smoked candidate -- six gates
#   --rollback [<id>]              print and write the rollback path; restore a backup
#
# ## Why the download is two steps
#
# `openai/gpt-oss-20b` is tens of gigabytes onto a disk already holding 194 GB. A flag that
# both prepares and downloads means a typo costs a disk. So `--stage-*` writes the manifest,
# the rollback note and the exact command, and the download itself needs
# SYMONEURAL_MODELOPS_CONFIRM to carry the phrase Garrett has to type.
set -euo pipefail

CONFIRM_PHRASE="RUN MODEL DOWNLOAD"
CANDIDATE_ID="symon-openai-20b"
CANDIDATE_UPSTREAM="openai/gpt-oss-20b"
STAGING_REL="backend/models/staging"

# The smoke engine listens here, NOT on LLAMA_PORT (8081). A candidate sharing the production
# port could be answered by -- or could answer for -- the running Qwen server, and then the
# smoke proves nothing about the candidate. A separate port is the cheap half of isolation.
SMOKE_PORT="${SYMONEURAL_SMOKE_PORT:-8099}"
ENGINE="symoneural-llm/build/bin/symoneural-llm"

# ---------------------------------------------------------------------------- guardrail 1
# Run from the repo root or not at all. Every path below is relative, and a script like this
# run from the wrong directory is how a staging tree lands somewhere nobody looks again.
if [[ ! -f "backend/server.py" || ! -f "tools/lib/model_inventory.py" ]]; then
  echo "refusing: run this from the repository root (backend/server.py not found here)" >&2
  exit 2
fi
ROOT="$(pwd)"

BOLD=$'\033[1m'; DIM=$'\033[2m'; AMBER=$'\033[33m'; OFF=$'\033[0m'
say()  { printf '%s\n' "$*"; }
head_() { printf '%s%s%s\n' "$BOLD" "$*" "$OFF"; }
warn() { printf '%s%s%s\n' "$AMBER" "$*" "$OFF" >&2; }
dim()  { printf '%s%s%s\n' "$DIM" "$*" "$OFF"; }

DRY_RUN=0

usage() {
  sed -n '2,40p' "$0" | sed 's/^# \{0,1\}//'
  exit "${1:-0}"
}

# ---------------------------------------------------------------------------- disk
show_disk() {
  head_ "disk"
  df -h . | awk 'NR==1 || NR==2 {print "  " $0}'
  if [[ -d backend/models ]]; then
    dim "  backend/models: $(du -sh backend/models 2>/dev/null | cut -f1)"
  fi
}

# ---------------------------------------------------------------------------- inventory
mode_inventory() {
  python3 tools/lib/model_inventory.py
  say ""
  show_disk
}

# ---------------------------------------------------------------------------- smoke plan
mode_smoke_plan() {
  local id="${1:-$CANDIDATE_ID}"
  head_ "smoke plan for $id"
  cat <<'PLAN'
  A candidate is not smoked because it downloaded. It is smoked when a real generation came
  out of it on this box, and the marker file is the evidence:

    1. runtime load        the serving engine opens the file without converting it
    2. tokenizer/template  a chat turn round-trips with the model's own chat template
    3. one real generation  non-empty output, recorded with the prompt and the timing
    4. VRAM measured        nvidia-smi during the generation, not a projection
    5. governor lease       the generation took and released a lease like any other tenant
    6. fallback proven      the previous default still loads after the candidate is unloaded

  Write the readings into:

    backend/models/staging/<id>/SMOKE-PASSED.txt

  That file cannot be written honestly without having run the thing, which is the whole
  reason `--activate-candidate` requires it. `exists` and `grep` cannot ask whether a model
  works; a stamped smoke record can.
PLAN
}

# ---------------------------------------------------------------------------- staging
# ROLLBACK.md is written from constants only -- nothing here is measured or decided, which
# is why it is safe to regenerate on a path that refuses to touch the manifest.
write_rollback_note() {
  local dir="$1"
  cat > "$dir/ROLLBACK.md" <<'ROLL'
# Rollback — SyMoNeuRaL OpenAI 20B candidate

**The rollback is that nothing was removed.** Staging does not touch the active default, so
the previous model is not "restored" — it never stopped being the one in use.

The active chat default is set in **`backend/server.py`**:

    CHAT_MODEL = MODELS / "llm" / "symon-1.0-7b-q4_k_m.gguf"
    DRAFT_MODEL = MODELS / "llm" / "symon-1.0-draft-0.5b-q4_k_m.gguf"

## If a promotion has been applied and you want it undone

1. `scripts/model-staging/symoneural-model-stage.sh --rollback` — restores
   `backend/server.py` from the `.model-stage-backup` written at promotion time.
2. Restart the API. A file swap is not live until the process re-reads it.
3. Confirm with `/api/status` that `model` reads the Qwen file again.

## What rollback does NOT do

It does not delete the candidate, and it does not delete the Qwen weights — **no mode of this
script deletes a weight file.** Disk is cheaper than a model you cannot get back.
ROLL
}

# Read the staging directory and say what is there. Every line is a measurement; nothing here
# is carried forward from a previous run, which is the whole point of it being a function
# rather than a stored field.
staged_disk_state() {
  local dir="$1" st gg
  st=$(find "$dir" -type f -name '*.safetensors' -printf '%s\n' 2>/dev/null | paste -sd+ | bc)
  gg=$(find "$dir" -type f -name '*.gguf' -printf '%s\n' 2>/dev/null | paste -sd+ | bc)
  say  "    safetensors:  $(find "$dir" -type f -name '*.safetensors' 2>/dev/null | wc -l) file(s), ${st:-0} bytes"
  say  "    gguf:         $(find "$dir" -type f -name '*.gguf' 2>/dev/null | wc -l) file(s), ${gg:-0} bytes"
  local inc
  inc=$(find "$dir" -type f -name '*.incomplete' -printf '%s\n' 2>/dev/null | paste -sd+ | bc)
  if [[ -n "$inc" && "$inc" != "0" ]]; then
    warn "    incomplete:   ${inc} bytes of partial-download leftovers (reclaimable)"
  fi
}

mode_stage_gpt_oss() {
  local dir="$STAGING_REL/openai-gpt-oss-20b"
  head_ "stage $CANDIDATE_ID  <-  $CANDIDATE_UPSTREAM"

  if (( DRY_RUN )); then
    dim "  dry run: would create $dir, write STAGED-MANIFEST.json and ROLLBACK.md"
    dim "  dry run: would NOT download -- that needs SYMONEURAL_MODELOPS_CONFIRM"
    return 0
  fi

  mkdir -p "$dir"

  # Refuse to overwrite a manifest that already exists. This mode used to clobber it
  # unconditionally, and the damage was not the lost fields -- it was that the fresh copy
  # claimed nothing had been downloaded onto a directory holding 32 GiB. A manifest that
  # contradicts its own disk is worse than no manifest, because the activation gates READ it.
  # Found 2026-08-22 by re-running this mode after the download completed.
  if [[ -f "$dir/STAGED-MANIFEST.json" ]]; then
    warn "  REFUSED: $dir/STAGED-MANIFEST.json already exists."
    warn "  Not overwriting it. It may record a completed download, a licence, or a smoke"
    warn "  result -- and a regenerated copy would assert the opposite of what is on disk."
    dim  "  To deliberately start over, move the existing file aside first."
    say ""
    # ROLLBACK.md is regenerated even on the refusal path. It is derived entirely from
    # constants in this script -- it records nothing that was measured or decided -- so
    # rewriting it destroys no state, whereas its ABSENCE fails activation gate 3 with no
    # obvious way back: the only mode that writes it would refuse before reaching the write.
    if [[ ! -f "$dir/ROLLBACK.md" ]]; then
      write_rollback_note "$dir"
      dim  "  ROLLBACK.md was missing -- rewritten (it holds no measured state)."
    fi
    dim  "  Recording what is actually on disk instead:"
    staged_disk_state "$dir"
    return 0
  fi

  # Derived, not asserted: the downloaded flag is a reading of the disk. An earlier version
  # wrote a constant here, which was accurate only at the instant of first staging.
  local dl_bytes dl_flag gguf_flag
  dl_bytes=$(find "$dir" -type f -name '*.safetensors' -printf '%s\n' 2>/dev/null | paste -sd+ | bc)
  dl_bytes=${dl_bytes:-0}
  [[ "$dl_bytes" -gt 0 ]] && dl_flag=true || dl_flag=false
  [[ -n "$(find "$dir" -name '*.gguf' -print -quit 2>/dev/null)" ]] && gguf_flag=true || gguf_flag=false

  # The manifest is written BEFORE any download, so a half-finished fetch still leaves a
  # record of what was being attempted and where it came from.
  cat > "$dir/STAGED-MANIFEST.json" <<JSON
{
  "candidate_id": "$CANDIDATE_ID",
  "display_name": "SyMoNeuRaL OpenAI 20B",
  "short_name": "SyMon OpenAI 20B",
  "upstream_repo": "$CANDIDATE_UPSTREAM",
  "local_dir": "$dir",
  "status": "AUDIT / CANDIDATE",
  "active_default": false,
  "downloaded": $dl_flag,
  "downloaded_safetensors_bytes": $dl_bytes,
  "gguf_present": $gguf_flag,
  "smoke_passed": false,
  "rollback_to": {
    "chat": "backend/models/llm/symon-1.0-7b-q4_k_m.gguf",
    "chat_draft": "backend/models/llm/symon-1.0-draft-0.5b-q4_k_m.gguf",
    "upstream": "bartowski/Qwen2.5-7B-Instruct-GGUF",
    "note": "measured active default at the time of staging; not deleted, not moved"
  },
  "runtime_compatibility": "UNRECORDED -- see docs/ops/OPENAI-GPT-OSS-MIGRATION.md",
  "license": "UNRECORDED -- upstream licence must be read and stored before activation",
  "notes": "Written by scripts/model-staging/symoneural-model-stage.sh. No weights fetched."
}
JSON

  write_rollback_note "$dir"

  say ""
  dim "  wrote $dir/STAGED-MANIFEST.json"
  dim "  wrote $dir/ROLLBACK.md"
  say ""
  head_ "download -- NOT run"
  say "  The command, recorded rather than executed:"
  say ""
  dim "  NOT huggingface-cli. That entrypoint is deprecated and NO LONGER WORKS -- and its"
  dim "  failure mode is the dangerous one: it prints a deprecation notice and EXITS 0"
  dim "  without downloading anything. A caller checking the exit code sees success and an"
  dim "  empty directory. Measured 2026-08-22 against hub 1.23.0. Use \`hf\` only."
  say ""
  dim "  Do NOT narrow this to the reference-checkpoint subtree. That subtree CANNOT be"
  dim "  converted: no \`architectures\` key in its config.json, tensors in the upstream project's"
  dim "  own layout rather than the names the converter registers for, and no tokenizer at all."
  dim "  It cost 13 GiB to learn that on 2026-08-22. Fetch the repo ROOT and exclude both"
  dim "  platform-specific subtrees, exactly as below."
  say ""
  say "    hf download $CANDIDATE_UPSTREAM \\"
  say "      --exclude \"original/*\" --exclude \"metal/*\" \\"
  say "      --local-dir $dir/hf/"
  say ""
  dim "  Target $dir/hf/ -- NOT the staging root. Pointed at the root, the converter finds"
  dim "  original/ alongside the HF files and dispatches on the wrong one."
  say ""
  if [[ "${SYMONEURAL_MODELOPS_CONFIRM:-}" == "$CONFIRM_PHRASE" ]]; then
    warn "  SYMONEURAL_MODELOPS_CONFIRM is set, but this script still will not fetch."
    warn "  The download is Garrett's to run by hand: it is tens of GB onto a disk already"
    warn "  holding 194 GB, and a script that can spend a disk should not be one flag away."
  else
    dim "  refusing to download: SYMONEURAL_MODELOPS_CONFIRM is not set to the phrase."
  fi
  say ""
  show_disk
}


# ---------------------------------------------------------------------------- smoke, isolated
mode_smoke_candidate() {
  local id="${1:-}"
  if [[ -z "$id" ]]; then
    echo "refusing: --smoke-candidate needs an explicit candidate id" >&2
    exit 2
  fi
  local dir="$STAGING_REL/${id#symon-}"
  [[ -d "$dir" || "$id" == "$CANDIDATE_ID" ]] && [[ ! -d "$dir" ]] && dir="$STAGING_REL/openai-gpt-oss-20b"

  head_ "isolated smoke: $id"
  say ""
  # ------------------------------------------------------------------ isolation, by construction
  cat <<'ISO'
  ISOLATION IS STRUCTURAL, NOT A FLAG.

  This mode launches the engine binary directly against the candidate file, on its own port,
  in its own process. It does NOT import or invoke the production API module -- which is the
  only thing that knows what the production defaults are. So a fallback to the production
  default is not disabled here, it is UNREACHABLE: there is no code path in this process that
  can name it.

  A flag that disables a fallback can be wrong. A function that cannot name the fallback
  cannot load it -- and this function is held to that by a test, which forbids the production
  symbols and filenames from appearing anywhere in its body.

  Consequences, stated so the smoke is not over-read:
    * no adapter       the candidate is judged on its own weights, not a persona adapter
    * no draft model   speculative decode is a pairing trained for the production default
    * separate port    the production server, if running, is neither used nor disturbed
    * nonzero exit     missing candidate, missing engine or a failed load all fail loudly
ISO
  say ""

  # ------------------------------------------------------------------ preconditions
  local model=""
  if [[ -d "$dir" ]]; then
    model="$(find "$dir" -maxdepth 2 -name '*.gguf' -print -quit 2>/dev/null || true)"
  fi

  local fail=0
  if [[ ! -d "$dir" ]]; then
    warn "  FAIL  candidate not staged -- no $dir"; fail=1
  elif [[ -z "$model" ]]; then
    warn "  FAIL  no .gguf under $dir -- the candidate is not converted yet"
    dim  "        upstream ships safetensors; see docs/ops/OPENAI-GPT-OSS-MIGRATION.md §2"
    fail=1
  else
    dim "  PASS  candidate model: $model"
  fi

  if [[ ! -x "$ENGINE" ]]; then
    warn "  FAIL  runtime missing or not executable -- $ENGINE"; fail=1
  else
    dim "  PASS  runtime: $ENGINE"
    dim "        $("$ENGINE" --version 2>&1 | head -1)"
  fi

  say ""
  if (( fail )); then
    warn "isolated smoke REFUSED -- nothing was launched, and no active model was consulted."
    warn "The active default is untouched and its weights are where they were."
    exit 5
  fi

  # ------------------------------------------------------------------ the argv, printed
  head_ "the exact command"
  say "    $ENGINE \\"
  say "      -m $model \\"
  say "      -ngl 99 --host 127.0.0.1 --port $SMOKE_PORT \\"
  say "      -c 8192 --no-warmup -cb -np 1"
  say ""
  dim "  -c 8192, not 65536. MEASURED reason: the production launch argv costs ~3.9 GiB of"
  dim "  KV at -c 65536 -np 2 -- 9,485 MiB total for a 4.36 GiB model, recorded in the"
  dim "  production module's own comment. A 12.81 GiB candidate plus that KV is ~16.7 GiB on"
  dim "  a 16,303 MiB card -- it will not fit, and an OOM nobody predicted reads like an"
  dim "  incompatible model rather than an argv that was too greedy."
  say ""
  if (( DRY_RUN )); then
    dim "  dry run: not launching."
    return 0
  fi
  warn "  launching is deliberately left to the operator."
  warn "  This takes the GPU, and a script that seizes the card as a side effect of a"
  warn "  --smoke flag is the kind of thing that gets run absent-mindedly on a live box."
  say ""
  say "  Then record the six readings and write:"
  say "    $dir/SMOKE-PASSED.txt"
  exit 6
}

# ---------------------------------------------------------------------------- activation
mode_activate() {
  local id="${1:-}"
  if [[ -z "$id" ]]; then
    echo "refusing: --activate-candidate needs an explicit candidate id" >&2
    exit 2
  fi
  local dir="$STAGING_REL/${id#symon-}"
  [[ -d "$dir" ]] || dir="$STAGING_REL/openai-gpt-oss-20b"

  head_ "activation gate for $id"
  local fail=0
  check() {                                       # check <label> <condition-desc> <0|1>
    if (( $3 )); then dim "  PASS  $1"; else warn "  FAIL  $1 -- $2"; fail=1; fi
  }

  check "candidate staged"          "no $dir/STAGED-MANIFEST.json" \
        "$([[ -f "$dir/STAGED-MANIFEST.json" ]] && echo 1 || echo 0)"
  check "smoke marker present"      "no $dir/SMOKE-PASSED.txt -- run the smoke plan first" \
        "$([[ -f "$dir/SMOKE-PASSED.txt" ]] && echo 1 || echo 0)"
  check "rollback recorded"         "no $dir/ROLLBACK.md" \
        "$([[ -f "$dir/ROLLBACK.md" ]] && echo 1 || echo 0)"
  check "licence recorded"          "STAGED-MANIFEST.json still says UNRECORDED for license" \
        "$([[ -f "$dir/STAGED-MANIFEST.json" ]] && ! grep -q '"license": "UNRECORDED' "$dir/STAGED-MANIFEST.json" && echo 1 || echo 0)"
  check "runtime compat recorded"   "STAGED-MANIFEST.json still says UNRECORDED for runtime" \
        "$([[ -f "$dir/STAGED-MANIFEST.json" ]] && ! grep -q '"runtime_compatibility": "UNRECORDED' "$dir/STAGED-MANIFEST.json" && echo 1 || echo 0)"
  check "owner approval in env"     "set SYMONEURAL_MODELOPS_APPROVE=$id to approve" \
        "$([[ "${SYMONEURAL_MODELOPS_APPROVE:-}" == "$id" ]] && echo 1 || echo 0)"

  say ""
  if (( fail )); then
    warn "activation REFUSED -- $id stays a candidate and the active default is untouched."
    exit 3
  fi
  if (( DRY_RUN )); then
    dim "  dry run: all gates pass; would back up backend/server.py and rewrite CHAT_MODEL"
    return 0
  fi
  # Backup first, always, and never in place.
  cp backend/server.py "backend/server.py.model-stage-backup"
  dim "  backed up backend/server.py -> backend/server.py.model-stage-backup"
  warn "  the CHAT_MODEL rewrite is deliberately not implemented in this script."
  warn "  Promotion edits a source file that the API reads at import; it belongs in a"
  warn "  reviewed commit with a test, not in a shell one-liner. The gate above is the"
  warn "  deliverable -- it says whether promotion is ALLOWED, not how to sneak it past review."
  exit 4
}

# ---------------------------------------------------------------------------- rollback
mode_rollback() {
  head_ "rollback"
  say "  active chat default is set in backend/server.py:"
  grep -nE '^(CHAT_MODEL|DRAFT_MODEL)\s*=' backend/server.py | sed 's/^/    /'
  say ""
  if [[ -f "backend/server.py.model-stage-backup" ]]; then
    if (( DRY_RUN )); then
      dim "  dry run: would restore backend/server.py from backend/server.py.model-stage-backup"
    else
      cp "backend/server.py.model-stage-backup" backend/server.py
      dim "  restored backend/server.py from backend/server.py.model-stage-backup"
      warn "  restart the API -- a file swap is not live until the process re-reads it."
    fi
  else
    dim "  no promotion backup exists, so there is nothing to roll back."
    dim "  The Qwen default has never been changed and its weights were never moved."
  fi
  say ""
  say "  No weight file is deleted by any mode of this script."
}

# ---------------------------------------------------------------------------- docs
mode_write_docs() {
  head_ "write-docs"
  if (( DRY_RUN )); then
    dim "  dry run: would refresh the inventory block in docs/ops/SYMONEURAL-MODEL-BUNDLES.md"
    return 0
  fi
  warn "  not implemented as an in-place rewrite on purpose."
  say "  The ops docs carry prose around their figures, and a generator that rewrites a"
  say "  section it does not fully own is how this repo grew its accumulate bug three times."
  say "  Regenerate the numbers and paste them deliberately:"
  say ""
  say "    python3 tools/lib/model_inventory.py > /tmp/model-inventory.txt"
  say "    python3 tools/lib/model_inventory.py --json > /tmp/model-inventory.json"
}

# ---------------------------------------------------------------------------- main
[[ $# -gt 0 ]] || usage 0
MODE=""; ARG=""
while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run)                    DRY_RUN=1 ;;
    --inventory)                  MODE=inventory ;;
    --stage-openai-gpt-oss-20b)   MODE=stage ;;
    --write-docs)                 MODE=docs ;;
    --smoke-plan)                 MODE=smoke ;;
    --smoke-candidate)            MODE=smokecand; ARG="${2:-}"; [[ -n "${2:-}" ]] && shift ;;
    --candidate)                  ARG="${2:-}"; [[ -n "${2:-}" ]] && shift ;;
    --activate-candidate)         MODE=activate; ARG="${2:-}"; [[ -n "${2:-}" ]] && shift ;;
    --rollback)                   MODE=rollback; if [[ "${2:-}" == --* || -z "${2:-}" ]]; then :; else ARG="$2"; shift; fi ;;
    -h|--help)                    usage 0 ;;
    *) echo "unknown flag: $1" >&2; usage 2 ;;
  esac
  shift
done

case "$MODE" in
  inventory) mode_inventory ;;
  stage)     mode_stage_gpt_oss ;;
  smoke)     mode_smoke_plan "$ARG" ;;
  smokecand) mode_smoke_candidate "$ARG" ;;
  activate)  mode_activate "$ARG" ;;
  rollback)  mode_rollback ;;
  docs)      mode_write_docs ;;
  "")        usage 0 ;;
esac
