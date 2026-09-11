#!/usr/bin/env bash
# SyMoNeuRaL GPU governor.
#
# One card, 15.92 GiB, two surfaces whose weight sets do not co-fit. This
# serialises them: any surface that wants the GPU takes the lock first, and
# nothing else touches the device until it is released.
#
# The mutex is the easy half. The half that actually bites is the handoff --
# killing a holder returns the lock long before the CUDA context has finished
# tearing down, so the next surface allocates into memory that is still held
# and dies at step 0. Release therefore does not merely unlock: it waits for
# the driver to hand the memory back, and only then lets the next surface in.
#
# The mutex is a mkdir lock, not flock on a file descriptor, because a hold
# has to outlive the shell that took it -- the API server acquires in one
# process and releases in another.
#
#   gpu-governor.sh acquire <surface> [timeout] [--new-engine]
#                                                 take the card. --new-engine says the
#                                                 caller is bringing its OWN engine, so
#                                                 a resident one is evicted even when
#                                                 the surface name is the same. Without
#                                                 it, re-acquiring the resident surface
#                                                 reuses the running engine (the normal
#                                                 api.py path) and evicts nothing.
#   gpu-governor.sh release                       give it back, wait for drain
#   gpu-governor.sh status                        who holds it, how much is free
#   gpu-governor.sh with <surface> -- cmd...      acquire, run, always release
#   gpu-governor.sh drain [proc-substring]        wait for device memory to come back
set -uo pipefail

# Repo root is one level up now that this lives in scripts/. This calculation has
# been wrong three times in this repo (the demo/ flatten, the tools/ move, here) and
# it fails silently, because the wrong parent is usually a directory that exists.
# The guard below turns that into an immediate, obvious failure.
# RUN in particular is the GPU mutex: gpu.lock.d lives in it. Point this at the
# wrong directory and the lock silently stops being shared -- two tenants both acquire,
# both load weights, and ~12 GB of models hit a 16 GB card.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
[ -f "$ROOT/backend/api.py" ] || { echo "repo root not found at $ROOT (expected backend/api.py)" >&2; exit 1; }
# HERE is the repo ROOT, not this script's directory, and the two call sites below spell
# their paths from the root accordingly. They did not until 2026-08-20: they read
# "$HERE/symoneural" and "$HERE/<launcher>.sh", neither of which has ever existed at the
# root, so both graceful stops silently fell through to their `||` pkill fallback --
# and for comfy that fallback is precisely the ungraceful kill the comment on its arm
# argues against. A `||` fallback hides a broken primary; both are checked by
# apps/test_governor_paths.py now.
HERE="$ROOT"
RUN="$ROOT/run"
LOCKDIR="$RUN/gpu.lock.d"
HOLDER="$LOCKDIR/holder"
# Overridable only so a test can run this script for real without writing fake readings
# into the runtime log. R-171 was diagnosed out of this file, and a synthetic
# "drain FAILED: still 9772 MiB" line sitting in it would be a trap laid for the next
# diagnosis. Nothing in service sets it.
LOG="${SYMONEURAL_GOVERNOR_LOG:-$RUN/governor.log}"

# What "drained" means, and why it is not a reading of the whole card.
#
# This floor was 1500 MiB against `--query-gpu=memory.used`, and that reading counts
# EVERY context on the device, graphics included. This box runs its KDE session on the
# same card -- Xorg ~530, kwin ~200, plasmashell ~115, Chrome, OBS, a dozen KDE services;
# 1336-1432 MiB measured with nothing of ours resident. So the floor left 68-164 MiB of
# headroom for the question it was actually asking, and 222 MiB of merely-*resident*
# ComfyUI spent it: drain failed for 60 s, `acquire chat` lost, and /api/chat answered 500
# to every visitor including a real one from 96.37.45.61 at 14:58 on 2026-08-21. Raising
# the number only moves the coin flip -- the reading was measuring the wrong thing.
# R-171; .claude/HANDOVER.md §0a-sexies has the trace.
#
# `--query-compute-apps` reports only CUDA contexts, which is exactly the set of things
# that can hold weights: our llama.cpp, sd.cpp and torch tenants are all C processes, and
# every desktop process is G and so invisible to it -- including OBS, which appears as a
# 49 MiB graphics context while its NVENC session runs. Measured here: compute 8340 MiB
# (llama-server alone) against 9772 card-wide, so the graphics baseline is 1432 MiB and
# none of it is ours to wait for.
#
# The floor is therefore small, and deliberately not zero: a CUDA context with no weights in
# it is not a tenant, and three of those are measured on this box. It is set from the largest
# of them plus headroom, not from a round number:
#
#   666 MiB   symoneural-ui resident with its weights unloaded -- the state `POST /free`
#             produces, and the reading `apps/studio/comfy.py` waits for.
#             .claude/HANDOVER.md §1559 has the curve: 666 idle -> 13,114 peak -> 666
#             again, with 238 MiB being the card after the *process* exits. A floor
#             under this would call a correctly-freed render engine an un-drained
#             tenant, which is the old bug in a new unit.
#   375 MiB   OBS's NVENC session while streaming (backend/apps/live/SMOKE.md).
#   222 MiB   Garrett's own ComfyUI out of external/, holding a context and nothing else.
#
# 1024 MiB clears the largest single one with room, clears the two likeliest pairs, and is an
# order of magnitude below the smallest real tenant (~5 GB, chat). It does NOT clear all three
# at once (1263 MiB), which is deliberate: a card carrying three live CUDA contexts is a card
# where waiting is the right answer.
DRAIN_FLOOR_MIB=1024
# Used ONLY when the compute query cannot be read -- see drain(). Keeping the old value
# here rather than deleting it is the point: the whole-card reading needs a whole-card
# floor, and the two numbers are not interchangeable.
DRAIN_FLOOR_CARDWIDE_MIB=1500
# Overridable for the same reason as LOG: the failure path polls for the whole timeout, and
# two of those in a test suite is two minutes. Nothing in service sets it.
DRAIN_TIMEOUT_S="${SYMONEURAL_DRAIN_TIMEOUT_S:-60}"
ACQUIRE_TIMEOUT_S=300

mkdir -p "$RUN"

vram_used() { nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits 2>/dev/null | head -1 | tr -d ' '; }
vram_free() { nvidia-smi --query-gpu=memory.free --format=csv,noheader,nounits 2>/dev/null | head -1 | tr -d ' '; }

# Device memory held by CUDA contexts, summed across them.
#
# Prints a number and returns 0 on success; prints nothing and returns 1 when the query
# cannot be read. That distinction is the whole reason this is a function: an *empty*
# result is a legitimate reading -- it is what "nothing holds a context" looks like -- and
# must read as 0, while a query that failed must NOT, or an unreadable card silently reads
# as an empty one and gets handed to the next tenant on no evidence.
#
# Summed, not `head -1`: two contexts of 400 and 12000 MiB would otherwise read as 400.
#
# With an argument, sums only contexts whose process path contains that substring. That is
# a different question -- "has THIS process let go" rather than "is the card clear of
# compute" -- and both are asked here; see drain().
#
# ## The arithmetic moved to Python; the contract did not
#
# This was an `awk -F','` block summing nvidia-smi CSV. Parsing CSV and doing arithmetic on
# it is where bash is worst, and the patternless-drain defect lived exactly there. It is now
# `backend/apps/gpu.py compute_mib`, which has tests.
#
# **The lock did NOT move and must not.** `mkdir` is the atomic primitive, bash has no
# runtime dependency, and a shell script can break a stale lock when `api.py` is dead. Only
# the measurement went.
#
# The contract here is unchanged on purpose: print a number and return 0, or print nothing
# and return 1. `drain()` below already branches on exactly that, so its fallback needed no
# edit -- which is what makes this swap small enough to trust.
#
# **An unreadable answer is never a drained answer.** A missing interpreter, a missing module,
# a timeout, a non-numeric line: all return 1, and `drain()` then uses the CARD-WIDE reading
# against the 1500 MiB floor rather than the 1024 MiB compute floor -- a cruder measure with a
# STRICTER threshold. So losing Python makes this wait longer, never hand over sooner.
GPU_PY="$ROOT/backend/apps/gpu.py"
vram_compute_used() {
  local pat="${1:-}" out
  [ -f "$GPU_PY" ] || return 1
  out="$(python3 "$GPU_PY" compute-mib "$pat" 2>/dev/null)" || return 1
  # Validate before printing. A stray line on stdout would otherwise become a number, and a
  # number is what decides whether the card is handed over.
  case "$out" in ''|*[!0-9]*) return 1 ;; esac
  printf '%s\n' "$out"
}
log() { printf '%s  %-8s %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$1" "$2" | tee -a "$LOG" >&2; }

held_surface() { cut -d' ' -f1 "$HOLDER" 2>/dev/null || true; }
held_pid()     { cut -d' ' -f2 "$HOLDER" 2>/dev/null || true; }

# ------------------------------------------------------------------ the engine record
#
# `holder` names the process that took the LEASE. That is not the process holding the card.
# Measured during a live render, `holder` read `image 1509` -- 1509 is symoneural-api, which
# spawned the engine and is still sitting there waiting for it. Killing 1509 to reclaim VRAM
# would stop the API and leave the engine running.
#
# So the engine records itself separately, after it is spawned:
#
#   engine:  <pid> <pgid|->
#
# `-` in the second field is not missing data, it is a measurement: the spawned process is
# NOT a process-group leader, so there is no group that means "this job and its children"
# without also meaning "whatever else shares our group". Signalling that group would signal
# symoneural-api. `cmd_engine` refuses to write a pgid it has not verified, and `evict`
# signals the single pid in that case.
#
# This generalises what the miner has always done -- `run/miner.pid` plus `kill -0 -- -$pgid`
# in surface_live below. The miner was right and was the only one doing it.
#
# ## It lives in $RUN, not in $LOCKDIR, and that is not a filing preference
#
# The first version of this put it in `$LOCKDIR/engine` and every eviction case failed.
# `break_if_stale` reclaims a dead holder's lock with `rm -rf "$LOCKDIR"` -- so the engine
# record was destroyed at exactly the moment it was needed, because "the holder died but
# its engine is still resident" is the case eviction exists for. An engine's lifetime is
# not the lock's lifetime.
#
# It also carries its own surface name rather than relying on `holder`, for a second reason
# the same tests found: `cmd_acquire` writes the NEW surface into `holder` *before* calling
# `evict "$prev"`, so by eviction time `held_surface` is the incoming tenant, not the one
# being evicted. `run/resident` and `run/miner.pid` are both in `$RUN` for these reasons and
# this is the third.
#
#   engine:  <surface> <pid> <pgid|->
ENGINE="$RUN/engine"
engine_surface() { cut -d' ' -f1 "$ENGINE" 2>/dev/null || true; }
engine_pid()     { cut -d' ' -f2 "$ENGINE" 2>/dev/null || true; }
engine_pgid()    { local g; g="$(cut -d' ' -f3 "$ENGINE" 2>/dev/null || true)"; [ "$g" = "-" ] && g=""; printf '%s' "$g"; }
# Does the record describe the surface we are asking about?
engine_is() { [ -n "${1:-}" ] && [ "$1" = "$(engine_surface)" ] && [ -n "$(engine_pid)" ]; }

# Is the recorded engine still alive? Group first when we have a verified one, because a
# group answers for the children too.
#
# A ZOMBIE IS NOT ALIVE, and `kill -0` cannot tell you that: a process that has exited but
# has not been reaped by its parent still accepts signal 0 and still answers `kill -0` with
# success. The engine's parent is symoneural-api, which reaps on `communicate()`/`wait()`,
# so the window is normally short -- but "normally short" is exactly the kind of thing that
# stops being short on the day something wedges. Without this check `evict_by_pid` waits
# out the full grace period, sends SIGKILL to a corpse, and then reports
# "SURVIVED KILL" about a process that died before any of it started.
proc_is_zombie() {
  local st; st="$(awk '{print $3}' "/proc/${1}/stat" 2>/dev/null)" || return 1
  [ "$st" = "Z" ]
}
engine_live() {
  local pid pgid
  pid="$(engine_pid)"; [ -n "$pid" ] || return 1
  proc_is_zombie "$pid" && return 1
  pgid="$(engine_pgid)"
  if [ -n "$pgid" ]; then kill -0 -- "-$pgid" 2>/dev/null && return 0; fi
  kill -0 "$pid" 2>/dev/null
}

# ------------------------------------------------------------------ the resident marker
#
# `run/resident` is the one piece of `run/` state that comes back from a reboot DISHONEST.
# After the 19:11 reboot it read `chat` with no lock directory and nothing running. The
# governor coped -- "recorded but no run is active -- treating as stale" -- but it reached
# that by inference from an absent lock, and every other part of this system is built to be
# honest on read rather than correct by inference.
#
# So the marker is stamped with the boot it was written in. A stamp that does not match the
# running kernel's boot id means the process it named died at power-off, which is a fact,
# not a guess. The boot id is a sidecar file rather than a second field in `run/resident`
# on purpose: `cat run/resident` is something people and scripts do, and a format change
# there would be a silent break for every one of them.
BOOT_ID_SRC="${SYMONEURAL_BOOT_ID_FILE:-/proc/sys/kernel/random/boot_id}"
boot_id() { cat "$BOOT_ID_SRC" 2>/dev/null || true; }
stamp_resident_boot() { local b; b="$(boot_id)"; [ -n "$b" ] && printf '%s\n' "$b" > "$RUN/resident.boot"; }

# True when a marker exists and demonstrably belongs to an earlier boot. An ABSENT stamp is
# not a mismatch: markers written before this change have none, and calling those stale
# would evict a live surface on the first run after an upgrade.
resident_predates_boot() {
  local now stamped
  [ -s "$RUN/resident" ] || return 1
  now="$(boot_id)"; [ -n "$now" ] || return 1
  [ -s "$RUN/resident.boot" ] || return 1
  stamped="$(cat "$RUN/resident.boot" 2>/dev/null || true)"
  [ -n "$stamped" ] && [ "$stamped" != "$now" ]
}

# A holder that died without releasing must not wedge the card forever.
break_if_stale() {
  local pid; pid="$(held_pid)"
  [ -z "$pid" ] && return 1
  if ! kill -0 "$pid" 2>/dev/null; then
    log stale "holder pid $pid is gone -- breaking the lock"
    rm -rf "$LOCKDIR"
    return 0
  fi
  return 1
}

# Wait for the driver to actually give device memory back.
#
# Both figures go in the log, labelled, on every outcome. A single number here is what made
# R-171 cost an afternoon: `drain FAILED: still 1558 MiB` is indistinguishable from a tenant
# that will not let go unless you already know the desktop is on this card.
# With a process-path substring, waits only on THAT process's contexts. The two forms
# answer different questions and both are needed:
#
#   drain              is the card clear of compute -- the eviction handoff, where the
#                      incoming tenant is about to allocate 5-13 GB and a foreign context
#                      (Garrett's desktop ComfyUI, anything out of external/) would OOM
#                      it. Nothing is ignored, because nothing here is safe to ignore.
#   drain <substring>  has this process let go -- what `symoneural-ui.sh stop` asks after
#                      SIGTERM. Aggregate is the wrong reading there: with chat legitimately
#                      warm at 8.1 GiB it logs `drain FAILED` about a card that is doing
#                      exactly what it should, which is the misleading-log failure this
#                      whole change is about.
drain() {
  local pat="${1:-}" waited=0 used compute floor scope said_fallback=0
  while :; do
    used="$(vram_used)"; used="${used:-0}"
    if compute="$(vram_compute_used "$pat")"; then
      scope="compute${pat:+ for '$pat'}"; floor="$DRAIN_FLOOR_MIB"
    else
      # Degraded, and LOUD about it. The old comment here said "fail open", which
      # undersold what it does: the fallback is the card-wide reading against a floor that
      # is HIGHER (1500 vs 1024), so it is cruder and stricter, not more permissive. That is
      # why bash may depend on Python for the precise answer at all -- the degraded path
      # waits longer, and a silent fallback is a fallback nobody knows they are running on.
      [ "$said_fallback" -eq 0 ] && log drain \
        "FALLBACK: no compute reading (gpu.py unavailable or unreadable) -- using the card-wide reading and its stricter ${DRAIN_FLOOR_CARDWIDE_MIB} MiB floor"
      said_fallback=1
      compute="$used"; scope="card-wide"; floor="$DRAIN_FLOOR_CARDWIDE_MIB"
    fi
    if [ "$compute" -lt "$floor" ]; then
      log drain "settled at ${compute} MiB ${scope} after ${waited}s (floor ${floor} MiB; card ${used} MiB incl. desktop)"
      return 0
    fi
    if [ "$waited" -ge "$DRAIN_TIMEOUT_S" ]; then
      log drain "FAILED: still ${compute} MiB ${scope} after ${waited}s (card ${used} MiB) -- refusing to hand over"
      return 1
    fi
    sleep 1; waited=$((waited + 1))
  done
}

# What each surface looks like in the process table.
#
# One place, because `evict` now asks the same question twice -- once to find out whether
# anything is running and once to stop it -- and two copies of a pattern is how one of them
# goes stale.
#
# These are anchored at $ROOT and the `pkill` patterns below are not, deliberately. The two
# are asking different questions. `pkill` is aimed at a process we are about to stop and a
# tail match is the safer, more forgiving end of that; the probe is answering "is OUR
# surface resident", and a bare `symoneural-ui/main.py` would answer yes to any
# other checkout of this repo on the same box. Anchoring can only ever produce a false
# *negative* -- we conclude nothing is running when something is -- and that failure lands
# on `drain`, which reads the card itself and refuses the handoff. A false positive has no
# such backstop: it logs a successful eviction and hands over memory that is still held.
#
# api.py:1151 and :2397 both spawn their engine by absolute path (LLM_ENGINE, DIFFUSE_ENGINE
# are ROOT-relative Paths) and symoneural-ui.sh does the same, so the anchored form is what
# is actually in the process table -- measured here 2026-08-21:
#   /home/google/Symoneural/symoneural-ui/.venv/bin/python \
#       /home/google/Symoneural/symoneural-ui/main.py --listen 127.0.0.1 --port 8188
#
# ## The chat pattern is the manifested runtime, and it is a literal ON PURPOSE
#
# `ops/manifests/llm-engine.json` is the authority on where the inference engine lives. This
# function does NOT read it, and that is a deliberate decision rather than an omission:
#
#   - this runs from `ExecStartPre`, on the path that hands the card over, and a JSON parse
#     there is a dependency the eviction path does not need;
#   - a failed read would yield an EMPTY pattern, and `pgrep -f ""` matches every process on
#     the box. That is the false positive the paragraph above says has no backstop -- the
#     governor would log a successful eviction and hand over memory that is still held. A
#     mechanism whose failure mode is worse than the problem it solves is not an improvement.
#
# So the manifest stays authoritative by TEST instead: `apps/test_governor_paths.py` asserts
# this literal against `llm-engine.json`, so moving the engine fails a test rather than
# silently breaking eviction. That is the same arrangement `tools/page_families.py` uses, and
# it is why there is no second copy of the engine's identity anywhere in this file -- no path
# beyond this one, and no hash at all.
surface_pattern() {
  case "${1:-}" in
    chat)  echo "$ROOT/symoneural-llm/" ;;
    image|sigil) echo "$ROOT/symoneural-diffuse/" ;;
    comfy) echo "$ROOT/symoneural-ui/main.py" ;;
    train) echo '[t]rain_lora.py' ;;
    *)     echo "$ROOT/symoneural-llm/|$ROOT/symoneural-diffuse/" ;;
  esac
}

# Is the named surface actually running? R-172: "`status` and `evict` both treat the marker
# as a hint and the process table as the fact."
#
# This exists because the exit code of a stop command cannot answer it. Two of the arms
# below shell out to a helper script, and both helpers succeed whether or not there was
# anything to stop -- `cmd_stop_chat` ends `return 0` with no branch that reports otherwise,
# and `symoneural-ui.sh stop` reaches its success exit through the not-running path. So
# `<stop> && active=1` reads true over an empty process table, and the governor logs a
# successful eviction of something that was already gone. That log line is the only record
# an eviction leaves; a944fae fixed the three arms whose stop action is a bare `pkill` and
# whose exit code was therefore already honest, and left the two that needed it -- including
# `comfy`, the surface the request was written about.
#
# The miner is the exception and does not have a `-f` pattern: it is a process *group*,
# recorded by pid file, so liveness is a signal-0 to the group.
#
# A recorded engine pid outranks the pattern, for the reason this whole section exists: a
# pattern is not an identity. Demonstrated 2026-09-10 and not hypothetically --
# `pgrep -af 'bin/symoneural-llm|bin/symoneural-diffuse'` matched an interactive *shell*
# whose command line merely contained the string. As `pkill` that is a kill of an unrelated
# process, which is the sixteen-dead-renders failure in `sigils/render.py`'s header.
surface_live() {
  local surface="${1:-}" pgid
  [ -z "$surface" ] && return 1
  # The identity path: this surface recorded what it spawned.
  if engine_is "$surface"; then
    engine_live
    return $?
  fi
  if [ "$surface" = "miner" ]; then
    pgid="$(cat "$RUN/miner.pid" 2>/dev/null || true)"
    [ -n "$pgid" ] || return 1
    kill -0 -- "-$pgid" 2>/dev/null
    return $?
  fi
  pgrep -f "$(surface_pattern "$surface")" >/dev/null 2>&1
}

# Record what we spawned. Refuses unless we hold the lease, because an engine record written
# by a process that does not hold the card names a process nobody is entitled to kill.
#
# The pgid is VERIFIED here rather than trusted: the caller passes it, and we write it only
# if it is a real group whose leader is the pid itself. `api.py:1019`'s `run()` passes
# `start_new_session=True` so its children are leaders; `api.py:1428` (chat) and
# `sigils/render.py:231` do not, and their pgid is symoneural-api's own. Writing that would
# hand `evict` a group kill aimed at the API.
cmd_engine() {
  local pid="${1:?usage: engine <pid> [pgid]}" pgid="${2:-}"
  local surface; surface="$(held_surface)"
  if [ -z "$surface" ]; then
    log engine "REFUSING to record engine pid $pid -- nobody holds the lease"
    return 1
  fi
  if ! kill -0 "$pid" 2>/dev/null; then
    log engine "REFUSING to record engine pid $pid -- no such process"
    return 1
  fi
  if [ -n "$pgid" ] && [ "$pgid" != "-" ] && [ "$pgid" != "$pid" ]; then
    log engine "not recording pgid $pgid for pid $pid -- not a group leader, so the group is not ours alone"
    pgid=""
  fi
  printf '%s %s %s\n' "$surface" "$pid" "${pgid:--}" > "$ENGINE"
  log engine "'$surface' engine pid $pid${pgid:+ pgid $pgid} recorded -- eviction will signal it by identity"
}

# Stop whatever is resident, then wait for the memory back.
evict() {
  local prev="${1:-}"
  [ -z "$prev" ] && return 0

  # `train` is answered before anything else and is never evicted to serve a page view.
  # Its own liveness check is the refusal, so it does not go through the probe below.
  if [ "$prev" = "train" ]; then
    if pgrep -f '[t]rain_lora.py' >/dev/null 2>&1; then
      log evict "REFUSING to evict a training run -- wait for it or stop it deliberately"
      return 1
    fi
    log evict "'train' recorded but no run is active -- treating as stale"
    rm -f "$RUN/resident" "$RUN/resident.boot"
    drain
    return $?
  fi

  # Read the process table BEFORE trying to stop anything. This is the whole fix: what
  # gets logged is a reading, not an inference from an exit code that cannot fail.
  local active=0
  surface_live "$prev" && active=1

  if [ "$active" -eq 1 ]; then
    log evict "stopping '$prev' to make room -- the weight sets do not co-fit"
    # The identity path. Taken whenever a pid was recorded, which a test asserts -- building
    # the new path and then continuing to run the old one is the failure mode this is
    # guarding against as much as the pattern kill itself.
    if engine_is "$prev"; then
      evict_by_pid "$prev"
    else
      log evict "FALLBACK for '$prev': no engine pid recorded, killing by PATTERN -- this can match an unrelated process"
    case "$prev" in
      # Graceful first, ungraceful second. A `||` fallback hides a broken primary, so both
      # halves of each pair are checked by apps/test_governor_paths.py.
      chat)  "$HERE/bin/symoneural-cli" _stop-chat >/dev/null 2>&1 \
               || pkill -f 'bin/symoneural-llm' 2>/dev/null || true ;;
      image|sigil) pkill -f 'bin/symoneural-diffuse' 2>/dev/null || true ;;
      # Never a bare pkill first: symoneural-ui.sh POSTs /free and waits for the drain, and
      # the process exiting is not the memory coming back.
      comfy) "$HERE/scripts/symoneural-ui.sh" stop >/dev/null 2>&1 \
               || pkill -f 'symoneural-ui/main.py' 2>/dev/null || true ;;
      miner) python3 -c 'import sys; sys.path.insert(0, "'"$ROOT"'/backend/apps"); import cryptominer; cryptominer.stop()' \
               >/dev/null 2>&1 \
               || pkill -g "$(cat "$RUN/miner.pid" 2>/dev/null || echo -1)" 2>/dev/null || true ;;
      # An unregistered surface FAILS CLOSED. This arm used to
      # `pkill -f 'bin/symoneural-llm|bin/symoneural-diffuse'`, so a typo in a surface name
      # stopped chat and image together. The card being held by something this script does
      # not recognise is a condition for a person, not for the broadest kill available.
      *)     log evict "REFUSING to evict unknown surface '$prev' -- no recorded engine pid and no known stop action. The card is held by something this script does not recognise; that is for a human."
             return 1 ;;
    esac
    fi
  elif engine_is "$prev"; then
    log evict "'$prev' engine pid $(engine_pid) already exited -- nothing to signal"
    rm -f "$ENGINE"
  else
    log evict "'$prev' recorded but no run is active -- treating as stale"
  fi

  rm -f "$RUN/resident" "$RUN/resident.boot"
  # Drain FOR the surface we just stopped, not for the whole card.
  #
  # This was a bare `drain`, which reads ALL compute against DRAIN_FLOOR_MIB and so asks
  # "is the card empty?" when the question is "did the thing I just killed let go?". The
  # two coincide only because one-tenant-at-a-time is the invariant -- so the moment that
  # invariant is what you are recovering FROM, the aggregate form waits on a tenant that is
  # not the one being evicted and times out having measured the wrong thing. The pattern
  # form is what the header at the top of `drain` describes and was already built for.
  drain "$(surface_pattern "$prev")"
}

# Signal the recorded engine, group first if we verified one. TERM, grace, then KILL.
#
# `kill -0` before and after so what gets logged is a reading rather than an inference from
# an exit code: `kill` succeeds against a process that is already a zombie, and "we sent a
# signal" is not "it went away".
EVICT_GRACE_S="${EVICT_GRACE_S:-10}"
evict_by_pid() {
  local surface="${1:-?}" pid pgid target waited=0
  pid="$(engine_pid)"; pgid="$(engine_pgid)"
  if [ -n "$pgid" ]; then target="-$pgid"; else target="$pid"; fi

  if ! engine_live; then
    log evict "'$surface' engine pid $pid already exited -- nothing to signal"
    rm -f "$ENGINE"
    return 0
  fi

  log evict "'$surface' -> TERM $target (pid $pid${pgid:+, process group $pgid})"
  kill -TERM -- "$target" 2>/dev/null || true
  while [ "$waited" -lt "$EVICT_GRACE_S" ]; do
    engine_live || { log evict "'$surface' engine exited after ${waited}s on TERM"; rm -f "$ENGINE"; return 0; }
    sleep 1; waited=$((waited + 1))
  done

  log evict "'$surface' still alive after ${waited}s -- KILL $target"
  kill -KILL -- "$target" 2>/dev/null || true
  sleep 1
  if engine_live; then
    log evict "'$surface' engine pid $pid SURVIVED KILL -- not clearing the record"
    return 1
  fi
  log evict "'$surface' engine gone after KILL"
  rm -f "$ENGINE"
}

cmd_acquire() {
  # `--new-engine` is accepted in any position, so the timeout stays optional and an
  # existing `acquire chat 300` keeps meaning what it meant.
  local surface="" timeout="" new_engine=0 arg
  for arg in "$@"; do
    case "$arg" in
      --new-engine) new_engine=1 ;;
      *) if [ -z "$surface" ]; then surface="$arg"; elif [ -z "$timeout" ]; then timeout="$arg"; fi ;;
    esac
  done
  : "${surface:?usage: acquire <surface> [timeout] [--new-engine]}"
  timeout="${timeout:-$ACQUIRE_TIMEOUT_S}"
  local waited=0 prev owner

  # Whose pid to record. NOT $$ -- for the standalone `acquire` form this script exits the
  # instant it returns, so $$ names a process that is already dead by the time anyone reads
  # the holder file. Two things then break silently: staleness detection breaks a live lock
  # on its first poll, and callers asking "who holds the card" are told nobody does.
  # The owner is the process that will still be running while the card is held -- the caller
  # (PPID), or an explicit pid via SYMONEURAL_OWNER_PID.
  owner="${SYMONEURAL_OWNER_PID:-$PPID}"
  log wait "'$surface' wants the card"
  until mkdir "$LOCKDIR" 2>/dev/null; do
    break_if_stale && continue
    if [ "$waited" -ge "$timeout" ]; then
      log wait "'$surface' TIMED OUT after ${timeout}s behind '$(held_surface)'"
      return 1
    fi
    sleep 1; waited=$((waited + 1))
  done

  # We own the lock. Whoever was resident before us has to go.
  prev="$(cat "$RUN/resident" 2>/dev/null || true)"
  # ...unless the marker predates this boot, in which case it names nothing and we say so
  # rather than inferring staleness from an absent lock further down.
  if [ -n "$prev" ] && resident_predates_boot; then
    log resident "'$prev' was recorded before this boot -- the process it names cannot exist; discarding the marker"
    rm -f "$RUN/resident" "$RUN/resident.boot"
    prev=""
  fi
  echo "$surface $owner" > "$HOLDER"
  # Whoever was resident before us has to go -- and "before us" is decided by IDENTITY, not
  # by the surface string.
  #
  # `c1cb1007` replaced pattern-matching eviction with eviction by recorded pid, under the
  # heading "a pattern is not an identity". The same confusion lived on one function up:
  # **a surface NAME is not an identity either.** Two processes can legitimately both be
  # `chat` -- the running Qwen engine and a candidate carrying different weights -- and on
  # 2026-09-11 that cost a real OOM, because the names matched so nothing was evicted and
  # 12.8 GiB of gpt-oss met 8.3 GiB of resident Qwen on a 16.3 GiB card.
  #
  # The governor cannot infer which case it is in, because both readings are real and want
  # opposite behaviour:
  #
  #   reuse    api.py acquires `chat` for another request against the engine ALREADY
  #            running. Evicting here kills the engine it is about to use, every request.
  #   replace  a candidate swap brings a different process under the same surface name.
  #            NOT evicting here is the OOM above.
  #
  # Only the caller knows. `--new-engine` is how it says so, and the default is unchanged,
  # so no existing caller acquires a new behaviour by accident.
  if [ -n "$prev" ] && [ "$prev" != "$surface" ]; then
    if ! evict "$prev"; then rm -rf "$LOCKDIR"; return 1; fi
  elif [ "$new_engine" -eq 1 ] && engine_live; then
    log acquire "'$surface' is already resident, but the caller declared a NEW engine (--new-engine) -- evicting recorded engine pid $(engine_pid). A surface name is not an identity."
    if ! evict "${prev:-$(engine_surface)}"; then rm -rf "$LOCKDIR"; return 1; fi
  fi
  echo "$surface" > "$RUN/resident"
  stamp_resident_boot
  log acquire "'$surface' holds the card -- $(vram_free) MiB free, waited ${waited}s"
  return 0
}

cmd_release() {
  local held claimant pid
  held="$(held_surface)"
  claimant="${1:-}"

  # Releasing a lock you do not hold is how one process quietly hands another process's
  # GPU away. The API's shutdown hook did exactly that to a running fine-tune: it called a
  # bare `release`, the lock directory vanished, and the next image request would have
  # allocated on top of an active training run. A release now has to name itself, and a
  # mismatch against a live holder is refused rather than obeyed.
  if [ -n "$held" ] && [ -n "$claimant" ] && [ "$held" != "$claimant" ]; then
    pid="$(held_pid)"
    if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
      log release "REFUSED: '$claimant' tried to release '$held' (pid $pid, alive)"
      return 1
    fi
  fi

  log release "'${held:-none}' releasing"
  rm -rf "$LOCKDIR"
}

cmd_status() {
  local surface compute; surface="$(held_surface)"
  # The marker with its liveness beside it. R-172 names `status` alongside `evict` for the
  # same reason: `resident surface   comfy` over a dead process is not a smaller truth than
  # a wrong one, it is the line somebody reads to decide the card is busy.
  local marker; marker="$(cat "$RUN/resident" 2>/dev/null || true)"
  if [ -z "$marker" ]; then
    echo "resident surface   none"
  elif surface_live "$marker"; then
    echo "resident surface   $marker (running)"
  else
    echo "resident surface   $marker (not running -- stale marker)"
  fi
  # Not a ${x:+..}${x:-..} pair: when x is set, the second form expands to x rather than
  # to the default, so a held lock printed "HELD by train (pid N)train".
  if [ -n "$surface" ]; then
    echo "lock               HELD by $surface (pid $(held_pid))"
  else
    echo "lock               free"
  fi
  echo "vram used          $(vram_used) MiB  (whole card, desktop included)"
  # The split, because it is the reading `drain` acts on and because seeing the two numbers
  # side by side is what turned R-171 from a mystery into a one-line diagnosis. A card
  # reading 1558 MiB with 222 MiB of compute is an idle card; the same 1558 with 1400 of
  # compute is a tenant that has not let go.
  if compute="$(vram_compute_used)"; then
    echo "  of which compute $compute MiB  (CUDA contexts -- what drain waits on, floor ${DRAIN_FLOOR_MIB} MiB)"
  else
    echo "  of which compute unreadable  (drain falls back to the card-wide ${DRAIN_FLOOR_CARDWIDE_MIB} MiB floor)"
  fi
  echo "vram free          $(vram_free) MiB"
}

# The form everything else should use: the card is always given back, even if
# the command inside crashes or the caller is interrupted.
cmd_with() {
  local surface="${1:?usage: with <surface> -- cmd...}"; shift
  [ "${1:-}" = "--" ] && shift
  SYMONEURAL_OWNER_PID=$$ cmd_acquire "$surface" || return 1
  trap "cmd_release $surface" EXIT INT TERM
  local rc=0
  "$@" || rc=$?
  trap - EXIT INT TERM
  cmd_release "$surface"
  return $rc
}

case "${1:-status}" in
  acquire) shift; cmd_acquire "$@" ;;
  release) shift; cmd_release "$@" ;;
  status)  shift; cmd_status  "$@" ;;
  with)    shift; cmd_with    "$@" ;;
  drain)   shift; drain "$@" ;;
  engine)  shift; cmd_engine  "$@" ;;
  *) echo "usage: $(basename "$0") {acquire <surface> [timeout] [--new-engine]|release|status|with|drain [proc-substring]|engine <pid> [pgid]}" >&2; exit 2 ;;
esac
