#!/usr/bin/env bash
# SPDX-License-Identifier: LicenseRef-SyMoNeuRaL-Proprietary
# Copyright (c) 2026 SymonSays LLC. All rights reserved.
# SyMoNeuRaL is a subdivision of SymonSays LLC. Licence: /LICENSE at the repository root.
#
# Every root change commissioning concluded is needed, in one reviewable script.
#
#     ops/deploy/commission-apply.sh                  # DRY RUN -- the default, prints and changes nothing
#     sudo ops/deploy/commission-apply.sh --apply     # actually do it
#     sudo ops/deploy/commission-apply.sh --apply --with-cuda-pin
#     sudo ops/deploy/commission-apply.sh --apply --with-readiness-probe
#     sudo ops/deploy/commission-apply.sh --apply --with-caddy-reload-fix
#     sudo ops/deploy/commission-apply.sh --apply --with-surface-template
#     sudo ops/deploy/commission-apply.sh --apply --with-site-deploy
#
# Commissioning ran as `google` and has no sudo. `systemctl start|stop|restart` is
# polkit-gated here -- it hangs waiting for an authentication that cannot arrive
# non-interactively -- so none of this could be applied or verified in place. It was
# collected instead of being handed over one change at a time.
#
# Design rules, because a script that half-applies is worse than one that refuses:
#
#   * --dry-run is the DEFAULT. --apply is explicit and requires root; without root it
#     refuses up front rather than failing part-way through.
#   * Every step is idempotent: it checks the current state and skips when already correct.
#     Run it twice; the second run should report every step as already done.
#   * Ordered least-disruptive first. Steps 1-3 write inert configuration that changes
#     nothing until the next apt run. Step 4 is the only one that touches the running
#     service, and it is last -- so a failure anywhere earlier leaves a working box.
#   * Each step states what it does, why, the command that verifies it took, and how to
#     revert it. Backups of every replaced file go to $BACKUP.
#
# What this script deliberately does NOT do:
#
#   * reboot. That is the owner's call and the owner said so.
#   * touch the storage run, /mnt/gdrive, rclone, or .private/.
#   * rotate or read any credential.
#   * decide the drop-in question. Step 5 explains why it cannot.

set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
BACKUP="/var/backups/symoneural-commission"
APPLY=0
CUDA_PIN=0
FAILED=0
READINESS=0
RELOADFIX=0
SURFTMPL=0
SITEDEPLOY=0
STEPS_DONE=0
STEPS_SKIPPED=0

for arg in "$@"; do
  case "$arg" in
    --apply)         APPLY=1 ;;
    --dry-run)       APPLY=0 ;;
    --with-cuda-pin) CUDA_PIN=1 ;;
    --with-readiness-probe) READINESS=1 ;;
    --with-caddy-reload-fix) RELOADFIX=1 ;;
    --with-surface-template) SURFTMPL=1 ;;
    --with-site-deploy) SITEDEPLOY=1 ;;
    -h|--help)       sed -n '6,33p' "${BASH_SOURCE[0]}" | sed 's/^# \?//'; exit 0 ;;
    *) printf 'unknown argument: %s (try --help)\n' "$arg" >&2; exit 2 ;;
  esac
done

if [ "$APPLY" -eq 1 ] && [ "$(id -u)" -ne 0 ]; then
  cat >&2 <<'EOF'
REFUSING: --apply needs root, and this is not root.

Every step below writes under /etc or acts on a systemd unit. Starting without root would
apply nothing and fail on the first write, which is the half-applied state this script is
written to avoid.

    sudo ops/deploy/commission-apply.sh --apply
EOF
  exit 1
fi

mode() { [ "$APPLY" -eq 1 ] && printf 'APPLY' || printf 'DRY-RUN'; }
say()  { printf '%s\n' "$*"; }
hdr()  { printf '\n%s\n%s\n' "== $* ==" "$(printf '%.0s-' {1..70})"; }

# run <description> <command...> -- executed only with --apply; printed either way.
run() {
  local desc="$1"; shift
  if [ "$APPLY" -eq 1 ]; then
    say "    + $desc"
    if ! "$@"; then
      say "    !! FAILED: $desc"
      FAILED=$((FAILED + 1))
      return 1
    fi
  else
    say "    would: $desc"
    say "           \$ $*"
  fi
}

# write_file <path> <mode> <<<content -- idempotent: skips when byte-identical.
write_file() {
  local path="$1" fmode="$2" content
  content="$(cat)"
  if [ -f "$path" ] && [ "$(cat -- "$path")" = "$content" ]; then
    say "    already correct: $path"
    STEPS_SKIPPED=$((STEPS_SKIPPED + 1))
    return 0
  fi
  if [ "$APPLY" -eq 1 ]; then
    mkdir -p "$(dirname "$path")" "$BACKUP"
    [ -f "$path" ] && cp -a -- "$path" "$BACKUP/$(basename "$path").$(date +%Y%m%d%H%M%S).bak"
    printf '%s\n' "$content" >"$path"
    chmod "$fmode" "$path"
    say "    + wrote $path (mode $fmode)"
    STEPS_DONE=$((STEPS_DONE + 1))
  else
    say "    would write $path (mode $fmode), $(printf '%s\n' "$content" | wc -l) lines"
    say "    would back up any existing copy to $BACKUP/"
  fi
}

say "commission-apply  [$(mode)]   repo: $ROOT"
[ "$APPLY" -eq 0 ] && say "  Nothing will be changed. Re-run with --apply (as root) to act."

# =====================================================================  STEP 0
hdr "0. THE ROOT QUEUE -- everything blocked on sudo, in one list"
say "  Consolidated 2026-09-10. Ten steps had accumulated across five days of instructions;"
say "  this is the order to run them in and which are independent, so it is one sitting."
say ""
say "  ONE COMMAND does the whole default queue:"
say ""
say "      sudo ops/deploy/commission-collect.sh                       # read-only, FIRST"
say "      sudo ops/deploy/commission-apply.sh --apply \\"
say "           --with-readiness-probe --with-caddy-reload-fix --with-site-deploy"
say ""
say "  Why collect first: /etc/systemd/system/symoneural-api.service.d/10-surfaces.conf"
say "  overrides the API unit, is root-owned, and has never been read. Until dropins.txt"
say "  exists, step 4 reinstalls a unit whose effective configuration is unknown."
say ""
say "  ---------------------------------------------------------------------------"
say "  #   step  what                              flag                        dep"
say "  ---------------------------------------------------------------------------"
say "  1   0     read the drop-in                  (commission-collect.sh)     none"
say "  2   4     StartLimit* reinstall, api+gw     always on with --apply      after 1"
say "  3   6     readiness probe drop-in           --with-readiness-probe      with 2"
say "  4   7     ExecReload -> ops/Caddyfile       --with-caddy-reload-fix     none"
say "  5   10    publish the rack LED fix          --with-site-deploy          none"
say "  6   1,2   needrestart + the apt GPU hook    always on with --apply      none"
say "  7   3     CUDA 13.3 pin for diffuse         --with-cuda-pin             none"
say "  8   9     surface@ template                 --with-surface-template     needs a surface"
say "  ---------------------------------------------------------------------------"
say ""
say "  INDEPENDENT of each other: 4, 5, 6, 7. Any order, any sitting."
say "  COUPLED: 2 and 3 both change the API unit, so run them together -- one"
say "           daemon-reload and one restart instead of two."
say "  ORDERED: 1 before 2. And 4 before any edit to ops/Caddyfile, because until it"
say "           lands \`reload\` reads /etc/caddy/Caddyfile while \`restart\` reads"
say "           ops/Caddyfile -- so an edit takes effect or not depending on the verb."
say ""
say "  WHAT THIS UNBLOCKS:"
say "    step 4  -> the sigils gateway route (any Caddyfile edit is unsafe before it)"
say "    step 5  -> the sigils delegation (an honest API behind a page that renders a"
say "               dead surface as POWERED is worse than the monolith)"
say "    step 2  -> crash-loop protection, which has never been in force: all three"
say "               units report StartLimitIntervalUSec=10s against a template of 120s"
say ""
say "  NOT IN THE QUEUE, and why -- so they are not mistaken for omissions:"
say "    step 5 (drop-in decision)  yours. Needs dropins.txt read first; the script"
say "                               deliberately does not choose."
say "    step 8 (installer edits)   repo changes, no root. Proposed with exact line"
say "                               numbers; I apply them when you say."
say "    step 9a (Caddy block)      proposed, not applied: ops/Caddyfile IS the live"
say "                               config, so editing it points production at a port"
say "                               with nothing on it until the surface runs."
say "    the API restart            DONE, 2026-09-10 05:33:28. Not needed again."
say "    the manifest regeneration  no root. One run on main at merge."


# =====================================================================  STEP 1
hdr "1. needrestart -- restart services whose libraries changed"
# WHAT: install needrestart and configure it to restart changed services automatically.
# WHY:  on 2026-09-09 a dist-upgrade replaced libraries under running services and nothing
#       restarted them. needrestart is the standard answer and IS NOT INSTALLED here --
#       measured: `dpkg-query -W needrestart` returns nothing and /etc/needrestart does not
#       exist. So dropping a config file in alone would have been inert.
# VERIFY: needrestart -v 2>&1 | head -1   ;   needrestart -l   (lists, changes nothing)
# REVERT: apt remove needrestart   (and rm the conf.d file below)
#
# MODE RECOMMENDATION -- 'a', on measured grounds rather than preference.
#   The worry with 'a' is that it restarts symoneural-api mid-generation. Commissioning
#   measured what SIGTERM actually does instead of trusting TimeoutStopSec=140: an image
#   render was started, SIGTERM sent 6 s in, and the render COMPLETED -- HTTP 200 after
#   11.9 s, with uvicorn logging "Waiting for connections to close". In-flight work drains.
#   The residual cost is a ~3-6 s window where new connections are refused (Restart=always,
#   RestartSec=3), which Caddy will surface as a brief 502.
#   'i' would be right if someone were reliably at the keyboard. The box runs unattended and
#   the alternative to a brief blip is serving indefinitely against a stale library, which is
#   the failure this whole item exists to prevent. Hence 'a'.
if command -v needrestart >/dev/null 2>&1; then
  say "    needrestart present: $(needrestart -v 2>&1 | head -1)"
else
  say "    needrestart is NOT installed (measured 2026-09-09)"
  run "apt-get install -y needrestart" apt-get install -y needrestart
fi
write_file /etc/needrestart/conf.d/99-symoneural.conf 0644 <<'EOF'
# Installed by ops/deploy/commission-apply.sh. See that script for why 'a' rather than 'i'.
#
# 'a' restarts services whose libraries changed, without asking. Commissioning measured that
# symoneural-api drains in-flight work on SIGTERM -- an image render begun 6 s earlier still
# returned HTTP 200 -- so an automatic restart does not discard a job someone is waiting on.
# It does cost a ~3-6 s window of refused connections while the unit comes back.
$nrconf{restart} = 'a';

# Kernel and driver changes are NOT fixed by restarting anything, so keep the loud hint.
# That is the exact case that broke this box: the driver was replaced under a running
# kernel and no restart could have reconciled it.
$nrconf{kernelhints} = 1;
EOF

# =====================================================================  STEP 2
hdr "2. apt hook -- say so when a driver upgrade needs a reboot"
# WHAT: a DPkg::Post-Invoke hook that tests whether nvidia-smi still works after an apt run.
# WHY:  it tests the real condition rather than guessing from package names.
# VERIFY: apt-get -s install --reinstall hello   (watch for the hook running; -s is a sim)
# REVERT: rm /etc/apt/apt.conf.d/99-symoneural-gpu
#
# TWO CORRECTIONS to the proposed hook, both measured:
#
#   1. `/var/run/reboot-required` IS the Debian convention and /var/run is a symlink to /run,
#      so the path is right -- but NOTHING ON THIS BOX READS IT. Measured: the file does not
#      exist, and update-notifier-common, needrestart, unattended-upgrades and debian-goodies
#      are all absent. Touching it is therefore a note to future tooling, not a signal an
#      operator will see. Kept because it is conventional and harmless, and because step 1
#      installs needrestart, which DOES read kernel/driver hints.
#   2. The visible signal has to be the stderr line and /api/status. The API now reports
#      `gpu.driver: "mismatch"` with "REBOOT REQUIRED" in `gpu.driver_detail`, which is the
#      operator-facing half of this item and is already committed.
#
# The fragment ends in `; true` so a failure inside it can never abort or wedge an apt run.
# A non-zero Post-Invoke is treated as an error by apt; this cannot return non-zero.
# It is also a no-op on a box with no GPU: `command -v nvidia-smi` fails and nothing happens.
write_file /etc/apt/apt.conf.d/99-symoneural-gpu 0644 <<'EOF'
// Installed by ops/deploy/commission-apply.sh.
//
// Tests the real condition -- can we still talk to the driver -- rather than inferring it
// from package names. Ends in `; true` so it can never abort an apt run, and is a no-op
// where nvidia-smi is not installed.
DPkg::Post-Invoke {
  "if command -v nvidia-smi >/dev/null 2>&1; then \
     if ! nvidia-smi >/dev/null 2>&1; then \
       touch /var/run/reboot-required 2>/dev/null || true; \
       echo 'SYMONEURAL: nvidia-smi FAILED after this upgrade. The kernel module and the' >&2; \
       echo 'SYMONEURAL: userspace driver disagree. REBOOT REQUIRED -- restarting services' >&2; \
       echo 'SYMONEURAL: will not fix it. CPU surfaces (ravencalc) keep serving meanwhile.' >&2; \
       echo 'SYMONEURAL: /api/status will report gpu.driver = mismatch.' >&2; \
     fi; \
   fi; true";
};
EOF

# =====================================================================  STEP 3
hdr "3. CUDA runtime pin for symoneural-diffuse  [$([ "$CUDA_PIN" -eq 1 ] && echo REQUESTED || echo SKIPPED, pass --with-cuda-pin)]"
# WHAT: give the unit an explicit LD_LIBRARY_PATH so the image engine resolves the same CUDA
#       under systemd as it does in an interactive shell.
# WHY:  measured -- symoneural-diffuse carries RUNPATH=/usr/local/cuda-13.3/targets/x86_64-linux/lib
#       and the unit sets no LD_LIBRARY_PATH, so under systemd it loads CUDA 13.3. An
#       interactive shell here has LD_LIBRARY_PATH=/usr/local/cuda/lib64, which OVERRIDES
#       RUNPATH, so the same binary loads 13.4 by hand. The same binary, two runtimes,
#       depending on how it is invoked -- so hand-testing that surface does not test what
#       production runs.
# VERIFY: systemctl show symoneural-api -p Environment
#         sudo -u google env -u LD_LIBRARY_PATH ldd .../symoneural-diffuse | grep cudart
# REVERT: rm /etc/systemd/system/symoneural-api.service.d/20-cuda.conf && systemctl daemon-reload
#
# THIS IS A DECISION, NOT A FIX, WHICH IS WHY IT IS OPT-IN. It converges the two paths on
# 13.4 by override, leaving a binary whose recorded RUNPATH still says 13.3. The real fix is
# to rebuild diffuse against the alternative; that is a build, it belongs on a schedule, and
# it must NOT be wired to apt -- a build triggered by an upgrade can fail and leave the box
# with no working engine at a moment nobody planned to debug it.
if [ "$CUDA_PIN" -eq 1 ]; then
  write_file /etc/systemd/system/symoneural-api.service.d/20-cuda.conf 0644 <<'EOF'
# Installed by ops/deploy/commission-apply.sh --with-cuda-pin.
# Makes the service resolve CUDA the way an interactive shell does, so the image engine
# stops loading a different runtime depending on how it was started. See that script.
[Service]
Environment=LD_LIBRARY_PATH=/usr/local/cuda/lib64
EOF
else
  say "    skipped -- pass --with-cuda-pin to write it. Read the block above first:"
  say "    it changes which CUDA the image engine loads, and the durable fix is a rebuild."
fi

# =====================================================================  STEP 4
hdr "4. Reinstall the API and gateway units -- the crash-loop fix that never landed"
# WHAT: render ops/*.service with @@ROOT@@ substituted, install, daemon-reload, restart.
# WHY:  MEASURED -- the installed units still carry StartLimitIntervalSec under [Service],
#       where systemd ignores it and says so ("Unknown key 'StartLimitIntervalSec' in
#       section [Service], ignoring"). `systemctl show` reports
#       StartLimitIntervalUSec=10s -- the built-in default -- not the 120s the template
#       intends. The repo template was fixed on 2026-09-03 and its comment describes the fix
#       in the past tense; the running system never received it. The installed copies are
#       also missing Before=symoneural-web.service.
#       The restart additionally puts the new /api/status GPU-driver reporting into service.
# VERIFY: systemctl show symoneural-api -p StartLimitIntervalUSec -p StartLimitBurst
#           expect StartLimitIntervalUSec=2min  (NOT 10s)
#         systemd-analyze verify /etc/systemd/system/symoneural-api.service   (expect silence)
#         curl -fsS localhost:8800/api/status | python3 -c 'import json,sys;print(json.load(sys.stdin)["gpu"]["driver"])'
# REVERT: cp $BACKUP/symoneural-api.service.<stamp>.bak /etc/systemd/system/symoneural-api.service
#         systemctl daemon-reload && systemctl restart symoneural-api
#
# LAST on purpose: it is the only step that interrupts service. Anything that fails above
# leaves the running system untouched.
for unit in symoneural-api symoneural-gateway; do
  src="$ROOT/ops/$unit.service"
  dst="/etc/systemd/system/$unit.service"
  if [ ! -f "$src" ]; then
    say "    !! missing template: $src"; FAILED=$((FAILED + 1)); continue
  fi
  rendered="$(sed "s|@@ROOT@@|$ROOT|g" -- "$src")"
  if [ -f "$dst" ] && [ "$(cat -- "$dst")" = "$rendered" ]; then
    say "    already correct: $dst"
    STEPS_SKIPPED=$((STEPS_SKIPPED + 1))
    continue
  fi
  if [ "$APPLY" -eq 1 ]; then
    mkdir -p "$BACKUP"
    [ -f "$dst" ] && cp -a -- "$dst" "$BACKUP/$unit.service.$(date +%Y%m%d%H%M%S).bak"
    printf '%s\n' "$rendered" >"$dst"
    chmod 0644 "$dst"
    say "    + installed $dst (backup in $BACKUP)"
    STEPS_DONE=$((STEPS_DONE + 1))
  else
    say "    would install $dst from ops/$unit.service with @@ROOT@@ -> $ROOT"
    say "    would back up the current copy to $BACKUP/"
  fi
done

run "systemctl daemon-reload" systemctl daemon-reload
# The gateway is disabled by design (no contract, no wallet, no key material) -- reinstalling
# its unit file must not start it, so only the API is restarted.
run "systemctl restart symoneural-api" systemctl restart symoneural-api

if [ "$APPLY" -eq 1 ]; then
  sleep 4
  hdr "verification (effective values, not the file)"
  systemctl show symoneural-api -p StartLimitIntervalUSec -p StartLimitBurst -p Restart \
                                -p ActiveState -p SubState --no-pager
  say ""
  say "  systemd-analyze verify (expect no 'Unknown key' line):"
  systemd-analyze verify /etc/systemd/system/symoneural-api.service 2>&1 | sed 's/^/    /' || true
  say ""
  say "  /api/status:"
  curl -fsS --max-time 20 http://127.0.0.1:8800/api/status 2>/dev/null \
    | python3 -c 'import json,sys; d=json.load(sys.stdin); print("    gpu.driver =", d["gpu"]["driver"]); print("    units      =", {u["id"]: u["state"] for u in d["units"] if u["id"] in ("chat","image","ravencalc")})' \
    || say "    !! /api/status did not answer -- see: journalctl -u symoneural-api -n 50"
fi

# =====================================================================  STEP 5
hdr "5. The drop-in -- NOT decided here, and why"
# /etc/systemd/system/symoneural-api.service.d/10-surfaces.conf overrides the API unit and
# appears nowhere in this repository. Commissioning could not read it (`systemctl cat` says
# "Permission denied"), so its contents are unknown and no correct action can be chosen.
#
# It must not stay invisible: the installed configuration of the API is currently not
# reproducible from the repo, which for a commissioning exercise is the more serious half of
# the drift story.
say "    Run ops/deploy/commission-collect.sh (read-only, needs sudo) to capture its contents."
say "    Then ONE of:"
say "      a) bring it into the repo as ops/units/symoneural-api.service.d/10-surfaces.conf.tmpl"
say "         and have the installer render it, if it is real configuration; or"
say "      b) fold its contents into run/config/api.env, which the API already reads and"
say "         which is neither root-owned nor invisible; or"
say "      c) document in ops/ why it is legitimately host-local and must stay out of Git."
say "    Not chosen here: choosing without reading it would be a guess in a script that runs"
say "    as root."

# =====================================================================  STEP 6
hdr "6. Readiness probe drop-in  [$([ "$READINESS" -eq 1 ] && echo REQUESTED || echo SKIPPED, pass --with-readiness-probe)]"
# THE DEFECT
# ----------
# symoneural-api.service is Type=exec, so systemd reports the unit `active` the instant the
# binary execs -- before api.py imports, before runtimeconfig.load(), before uvicorn binds.
# Measured 2026-09-09:
#
#   22:09:55.961563  old process logs "Finished server process"
#   22:09:56         systemd marks the unit active; `systemctl restart` RETURNS
#   22:09:57.367066  uvicorn logs "Uvicorn running on http://127.0.0.1:8800"
#
# ~1.4 s during which is-active says `active` and every connection to :8800 is refused. The
# owner ran the sequence RUNBOOK section 3 prescribes -- `systemctl restart symoneural-api &&
# python3 tools/lib/smoke.py` -- landed in that window, and got nine failures against a healthy
# API with `[PASS] symoneural-api.service is active` printed above them.
#
# WHY ExecStartPost AND NOT Type=notify
# -------------------------------------
# Measured on a throwaway --user unit imitating the delay, Type=exec plus a polling
# ExecStartPost:
#
#   during startup:  is-active = activating   (SubState=start-post)  for the whole window
#   after the probe: is-active = active       (SubState=running)
#   `systemctl start` returned after 3.20 s with the port already listening
#
# So the start job becomes synchronous with readiness and is-active stops lying. Cost: a
# restart takes ~1.4 s longer to RETURN -- the delay was always there, it is just no longer
# hidden. No code change, no new dependency.
#
# Type=notify is more precise in principle -- READY=1 from the process itself rather than a
# probe from outside -- and python3-systemd (235-1+b6) is already installed. But backend/server.py
# has no sd_notify call anywhere (grepped for sd_notify, NOTIFY_SOCKET, sdnotify) and uvicorn
# has no built-in support, so it needs a hook written into the SERVING PATH plus
# python3-systemd promoted to a hard start dependency in tools/lib/preflight.py. A port probe also
# tests what clients actually need. RECOMMENDATION: ExecStartPost, which is what this writes.
#
# TimeoutStartSec must exceed the probe timeout, because ExecStartPost time counts against it.
# Both are set together below for that reason.
if [ "$READINESS" -eq 1 ]; then
  write_file /etc/systemd/system/symoneural-api.service.d/20-readiness.conf 0644 <<EOF
# Installed by ops/deploy/commission-apply.sh --with-readiness-probe.
# Makes \`systemctl start/restart\` block until the API answers on :8800, so \`is-active\`
# cannot report \`active\` while connections are refused. See that script's step 6.
#
# ExecStartPost is ADDITIVE across drop-ins -- this does not override 10-surfaces.conf.
[Service]
ExecStartPost=$ROOT/ops/deploy/api-readiness-probe.sh
TimeoutStartSec=120
EOF
  run "systemctl daemon-reload" systemctl daemon-reload
  say ""
  say "  VERIFY (after the next restart, which is yours to choose):"
  say "    systemctl show symoneural-api -p ExecStartPost -p TimeoutStartUSec"
  say "    time sudo systemctl restart symoneural-api   # should now take ~1.4s longer to return"
  say "    systemctl is-active symoneural-api           # must be 'active', not 'activating'"
  say "    curl -s -o /dev/null -w '%{http_code}\\n' localhost:8800/api/status   # expect 200"
  say "    journalctl -u symoneural-api -n 5 | grep readiness   # the probe logs its wait"
  say ""
  say "  REVERT (one file, nothing else touched):"
  say "    sudo rm /etc/systemd/system/symoneural-api.service.d/20-readiness.conf"
  say "    sudo systemctl daemon-reload"
  say "    # the running service is unaffected until the next restart either way"
  say ""
  say "  RISK, stated plainly: ExecStartPost exiting non-zero FAILS THE START JOB and systemd"
  say "  tears the service down. That is the intended contract -- a service that cannot serve"
  say "  should not be reported active -- but it converts 'up but not answering' from a silent"
  say "  state into a hard start failure. The probe allows 45 s against a measured ~1.4 s"
  say "  start, so a slow-but-healthy boot is not killed. If you would rather it never be"
  say "  able to fail a start, do not install this and keep the fix in tools/lib/smoke.py only,"
  say "  which is already in place and needs no root."
else
  say "    skipped -- pass --with-readiness-probe to write it. Read the block above first;"
  say "    it can fail a start job, which is a real behaviour change to the unit."
  say "    tools/lib/smoke.py already waits for readiness on its own, so nothing is broken"
  say "    without this. This closes the hole at the systemd layer rather than in one caller."
fi

# =====================================================================  STEP 7
hdr "7. Caddy ExecReload drop-in  [$([ "$RELOADFIX" -eq 1 ] && echo REQUESTED || echo SKIPPED, pass --with-caddy-reload-fix)]"
# THE DEFECT
# ----------
# symoneural-web's two verbs name different config files, because the root-owned drop-in
# 10-first-party-config.conf overrides ExecStart and NOT ExecReload:
#
#   systemctl restart symoneural-web  ->  <root>/ops/Caddyfile      (tracked; being served)
#   systemctl reload  symoneural-web  ->  /etc/caddy/Caddyfile      (a copy)
#
# Byte-identical today, so invisible. Edit ops/Caddyfile and then reload, and the reload
# pushes the older /etc copy into the running instance through the admin API on
# 127.0.0.1:2019 -- silently reverting the edit. Which config is live becomes a function of
# which verb was used last, which is not a property a web server should have.
#
# Verified that a reload really would take effect rather than failing safe: main.go:134
# intercepts only --version/--license before caddycmd.Main(); the admin API is listening on
# 127.0.0.1:2019 (no `admin` directive and no global block in the Caddyfile, so it is on by
# default); /etc/caddy/Caddyfile is mode 644 and readable by User=caddy; and
# `symoneural-web adapt --config /etc/caddy/Caddyfile` exits 0.
#
# THE DECISION, WHICH IS THE OWNER'S AND IS MADE
# ----------------------------------------------
# Owner, 2026-09-09: "ops/Caddyfile is authoritative. Not close. It is tracked, reviewable and
# revertable; /etc/caddy/Caddyfile is a copy that exists only because the vendor unit template
# named it. Extend the drop-in to override ExecReload as well as ExecStart."
#
# So this points the reload verb at the tracked file. After it lands, install-caddy.sh copying
# ops/ -> /etc/ is belt-and-braces rather than load-bearing.
#
# `ExecReload=` is listed EMPTY first and then set. That reset is required, not stylistic:
# drop-ins APPEND to Exec* lists, so without it the unit would carry two ExecReload commands
# and run both -- reloading from the tracked file and then immediately from the copy, which is
# the current bug with an extra step.
if [ "$RELOADFIX" -eq 1 ]; then
  write_file /etc/systemd/system/symoneural-web.service.d/20-execreload.conf 0644 <<EOF
# Installed by ops/deploy/commission-apply.sh --with-caddy-reload-fix.
# 10-first-party-config.conf points ExecStart at the tracked ops/Caddyfile but leaves
# ExecReload on the template's /etc/caddy/Caddyfile, so the two verbs served different files.
# The owner decided ops/Caddyfile is authoritative (2026-09-09). See that script's step 7.
#
# The empty ExecReload= is a RESET and is required: drop-ins append to Exec* lists.
[Service]
ExecReload=
ExecReload=$ROOT/web/symoneural-web/build/symoneural-web reload --config $ROOT/ops/Caddyfile --force
EOF
  run "systemctl daemon-reload" systemctl daemon-reload
  say ""
  say "  VERIFY (no restart needed -- reload config is read at reload time):"
  say "    python3 tools/audit/serving_config_audit.py     # expect: no config-path incoherence found"
  say "    systemctl show symoneural-web -p ExecReload | grep -o '\\-\\-config [^ ]*'"
  say "    # then prove it end to end, on a change you can see and revert:"
  say "    #   1. edit a comment in ops/Caddyfile"
  say "    #   2. sudo systemctl reload symoneural-web"
  say "    #   3. curl -s 127.0.0.1:2019/config/ | grep -c 'ops/Caddyfile'   # non-zero"
  say ""
  say "  REVERT (one file):"
  say "    sudo rm /etc/systemd/system/symoneural-web.service.d/20-execreload.conf"
  say "    sudo systemctl daemon-reload"
  say ""
  say "  RISK: low. It changes which file a reload reads, and the two files are"
  say "  byte-identical right now, so applying it today is a no-op you can verify. It does"
  say "  not touch the running process and needs no restart."
else
  say "    skipped -- pass --with-caddy-reload-fix to write it."
  say "    Until it lands: after editing ops/Caddyfile use \`systemctl restart\`, or"
  say "    \`sudo scripts/install-caddy.sh\` and then reload. A bare reload reverts you."
fi

# =====================================================================  STEP 8
hdr "8. Two changes to ops/deploy/install-runtime.sh -- PROPOSED, NOT APPLIED"
# Neither of these needs root and neither is applied here. They are edits to a tracked repo
# script, and the owner asked for them as proposals so the installer does not change under
# them: "Propose the change to the installer in commission-apply.sh; keep the RUNBOOK section 2
# warning until it lands."
say "  (a) BACK UP symoneural-web.service.d, the way the API's is already backed up."
say "      Owner: \"An install that can silently change which Caddyfile is served, with no"
say "      backup, is a hole regardless of which file wins.\" Independent of step 7."
say ""
say "      ops/deploy/install-runtime.sh:185   in the backup block, after the API line:"
say "        [ -d \"\$UNIT_DIR/symoneural-api.service.d\" ] && run \"cp -a ... '\$BK/'\""
say "      +   [ -d \"\$UNIT_DIR/symoneural-web.service.d\" ] && run \"cp -a '\$UNIT_DIR/symoneural-web.service.d' '\$BK/'\""
say ""
say "      ops/deploy/install-runtime.sh:239   in the ROLLBACK block, alongside the API line:"
say "        [ -d \"\$BK/symoneural-api.service.d\" ] && cp -a \"\$BK/symoneural-api.service.d\" \"\$UNIT_DIR/\""
say "      +   [ -d \"\$BK/symoneural-web.service.d\" ] && cp -a \"\$BK/symoneural-web.service.d\" \"\$UNIT_DIR/\""
say ""
say "      Both halves are needed. Backing up without restoring on rollback would leave a"
say "      failed install having deleted the drop-in that decides which Caddyfile is served."
say ""
say "  (b) STOP INSTALLING symoneural-deploy as a side effect."
say "      Owner: it stays uninstalled, and \"it should not be a side effect of"
say "      install-runtime.sh ... the only unit whose activation writes to a public directory.\""
say ""
say "      ops/deploy/install-runtime.sh:41"
say "        - UNITS=(symoneural-api symoneural-gateway symoneural-deploy)"
say "        + UNITS=(symoneural-api symoneural-gateway)"
say ""
say "      Two consequences worth deciding at the same time, both at your discretion:"
say "        * :44  ENV_FILES still lists /etc/symoneural/deploy.env. Harmless -- it is only"
say "               backed up -- but it now refers to a unit the installer does not install."
say "        * :112,114  \`need scripts/deploy.sh\` and \`need site\` become preconditions for"
say "               something no longer installed, so a box without site/ would be refused"
say "               an API install for no reason."
say ""
say "      NOT proposed: deleting ops/units/symoneural-deploy.service. It is a working unit file and"
say "      the decision is that it is not installed automatically, not that it is unwanted."
say ""
say "  Neither edit is made. RUNBOOK section 2 keeps its warning until they land."

# =====================================================================  STEP 9
hdr "9. The surface template, for the RavenCalc pilot  [$([ "$SURFTMPL" -eq 1 ] && echo REQUESTED || echo SKIPPED, pass --with-surface-template)]"
# The split's first process. Scoped in review/commissioning-20260909/SPLIT-SCOPING.md and
# accepted at nine processes, not twelve: chat, image, remix and /api/ws stay together as one
# GPU core because they share one card and one mkdir lock.
#
# What is already built and needs no root:
#   ops/PORTS.tsv                          the registry -- the only place a port is named
#   backend/ports.py                  its reader, and the safety rule
#   backend/ravencalc/service.py      the surface: /api/ravencalc + /healthz
#   backend/server.py                         registers its inline route ONLY while the registry
#                                          says the surface is not delegated, and polls
#                                          /healthz in the background for delegated ones
#   tools/lib/surface_pilot_proof.py           9 checks, incl. killing the surface and proving
#                                          the rack reports `unreachable` with a reason
#
# What needs root is this: the unit file, and the proxy route.
if [ "$SURFTMPL" -eq 1 ]; then
  if [ -f "$ROOT/ops/units/symoneural-surface@.service" ]; then
    # @@ROOT@@ substituted the same way install-runtime.sh does it, and refused if any
    # placeholder survives -- an unsubstituted unit starts and then cannot find the repo.
    tmpl="$(sed "s|@@ROOT@@|$ROOT|g" "$ROOT/ops/units/symoneural-surface@.service")"
    if printf '%s' "$tmpl" | grep -q '@@ROOT@@'; then
      say "    !! REFUSING: @@ROOT@@ survived substitution"
      FAILED=$((FAILED + 1))
    else
      write_file /etc/systemd/system/symoneural-surface@.service 0644 <<EOF
$tmpl
EOF
      run "systemctl daemon-reload" systemctl daemon-reload
      say ""
      say "    Then, and ONLY then, flip the registry:"
      say "      ops/PORTS.tsv   symoneural-ravencalc  ...  DELEGATED  no -> yes"
      say "      sudo systemctl enable --now symoneural-surface@ravencalc"
      say "      sudo systemctl restart symoneural-api     # to drop its inline route"
      say ""
      say "    ORDER MATTERS and the wrong order is a visible outage: flipping DELEGATED"
      say "    before the unit runs makes the monolith drop /api/ravencalc while nothing"
      say "    else answers. backend/ports.py refuses the no-port case but it cannot"
      say "    tell whether the process is actually up -- that is what the rack's"
      say "    \`unreachable\` state is for."
    fi
  else
    say "    !! ops/units/symoneural-surface@.service is missing"
    FAILED=$((FAILED + 1))
  fi
  say ""
  say "  VERIFY:"
  say "    systemctl status symoneural-surface@ravencalc"
  say "    curl -s localhost:8811/healthz | python3 -m json.tool"
  say "    curl -s localhost:8800/api/status | python3 -c 'import json,sys; print([u for u in json.load(sys.stdin)[\"units\"] if u[\"id\"]==\"ravencalc\"])'"
  say "    python3 tools/lib/surface_pilot_proof.py      # 9 checks, uses scratch ports only"
  say "    curl -s -o /dev/null -w '%{http_code}\\n' localhost:8800/api/ravencalc   # expect 404 once delegated"
  say ""
  say "  REVERT (in this order):"
  say "    ops/PORTS.tsv   DELEGATED  yes -> no"
  say "    sudo systemctl restart symoneural-api          # the inline route comes back"
  say "    sudo systemctl disable --now symoneural-surface@ravencalc"
  say "    sudo rm /etc/systemd/system/symoneural-surface@.service && sudo systemctl daemon-reload"
  say "    # Registry first: it is what decides who answers. Reversing the order leaves a"
  say "    # window with two answerers, which is the state the design does not allow."
else
  say "    skipped -- pass --with-surface-template to install the unit."
  say "    Nothing about the pilot is live without it: ops/PORTS.tsv ships DELEGATED=no, so"
  say "    the monolith still answers /api/ravencalc and the surface process is spare"
  say "    capacity nobody routes to. Proven on scratch ports by"
  say "    tools/lib/surface_pilot_proof.py -- 9 passed, production :8800 untouched."
fi

# ---------------------------------------------------------------- the proxy route, PROPOSED
hdr "9a. Routing /api/ravencalc to the surface -- PROPOSED, NOT APPLIED"
# ops/Caddyfile IS the live config -- ExecStart points at it, not at /etc/caddy/Caddyfile
# (step 7). So editing it here would change production on the next restart, and if the
# surface were not up that is a 502 on a path that works today. It is therefore a proposal.
#
# The gateway cannot do this without a rebuild: backend/gateway/src/router.rs:50 routes
# `/api/{*path}` to one upstream verbatim. cargo IS available on this box, so a gateway-side
# route is possible -- but it is a Rust build plus a binary install for what a four-line Caddy
# block does, and the block is revertable by an operator reading one file.
say "  Add to ops/Caddyfile, BEFORE the existing \`handle /api/*\` block:"
say ""
say "      # RavenCalc runs as its own process (ops/PORTS.tsv). More specific than"
say "      # /api/* so Caddy matches it first; everything else still goes to the gateway."
say "      handle /api/ravencalc {"
say "          reverse_proxy 127.0.0.1:8811"
say "      }"
say ""
say "  Then: sudo systemctl restart symoneural-web    # restart, NOT reload -- see step 7"
say ""
say "  A dead surface behind this block returns Caddy's own 502. That is the shape of the"
say "  outage the commissioning pass spent a day on, so the rack matters more than the proxy"
say "  here: /api/status reports \`unreachable\` naming the port and the systemctl command,"
say "  which is the thing an operator can act on. Measured: tools/lib/surface_pilot_proof.py"
say "  check 8 -- the API itself returns 404 for a delegated surface it does not own, and a"
say "  404 is honest. Making Caddy return something friendlier is a later refinement and is"
say "  NOT proposed here, because a custom error page that lies about which component failed"
say "  would be worse than the 502."

# =====================================================================  STEP 10
hdr "10. Publish the rack LED fix to the webroot  [$([ "$SITEDEPLOY" -eq 1 ] && echo REQUESTED || echo SKIPPED, pass --with-site-deploy)]"
# WHY THIS IS A ROOT ITEM AND NOT COSMETIC
#
# `Unit.state` gained a fifth value, `unreachable`, in d40f14fe. `site/console.js`'s `leds()`
# lit a plate for any state it did not recognise, so a dead surface rendered with its POWER
# LED ON. Fixed in 0f949990 and verified by executing the function under node across six
# inputs -- including an unknown state, which now renders dark, so the bug CLASS is closed and
# not just the instance.
#
# The repo is fixed. The webroot is not:
#     site/console.js                     43ed86c2  (4 mentions of `unreachable`)
#     /var/www/symoneural/console.js      b1045bbe  (0)
#
# The API can already emit `unreachable`. Until this lands, an honest API sits behind a page
# that renders a dead process as powered -- which is worse than the monolith, because the page
# is what a person looks at. This is sigils' second gate.
if [ "$SITEDEPLOY" -eq 1 ]; then
  if [ ! -x "$ROOT/scripts/deploy.sh" ] && [ ! -f "$ROOT/scripts/deploy.sh" ]; then
    say "    !! $ROOT/scripts/deploy.sh is missing"
    FAILED=$((FAILED + 1))
  else
    # NO --prune, deliberately. Two measured reasons:
    #
    # 1. The webroot holds `index.prev-20260901-010235.html`, the rollback copy of the last
    #    deploy. deploy.sh exempts only `index.prev-$STAMP.html` -- THIS run's backup (:104) --
    #    so an old one is an orphan and `--prune` deletes it. The run creates a fresh rollback
    #    point, so the net effect is trading the 09-01 undo for a 09-10 one. That may be what
    #    you want; it is not something this step should decide silently.
    # 2. Nothing needs pruning for this fix. The 19 `site/*.json` files absent from the webroot
    #    are absent BY DESIGN: `PUBLISH` (:61) allows html/css/js/png/svg/ico/txt/xml/webp/
    #    woff2/jpg only, and `.json` is not a web asset here -- `openapi.json` is proxied to
    #    FastAPI and the `art-*.json` are build-time metadata. I recorded them as drift; they
    #    are not.
    run "publish site/ to /var/www/symoneural (no --prune)" bash "$ROOT/scripts/deploy.sh"
  fi
  say ""
  say "  VERIFY -- the page, not the repo:"
  say "    md5sum $ROOT/frontend/site/js/console.js /var/www/symoneural/console.js   # must match"
  say "    grep -c unreachable /var/www/symoneural/console.js            # expect 4"
  say "    # and the behaviour, not the string:"
  say "    node -e \"\$(sed -n '/var LIVE = {/,/function powered/p' /var/www/symoneural/console.js); console.log(powered('unreachable'), powered('ready'))\"   # false true"
  say ""
  say "  REVERT:"
  say "    sudo install -o www-data -g www-data -m 644 \\"
  say "      /var/www/symoneural/index.prev-<STAMP>.html /var/www/symoneural/index.html"
  say "    # deploy.sh writes a fresh index.prev-<stamp>.html on every run; that is the undo"
  say "    # for index.html. For console.js specifically, revert the repo file and re-run:"
  say "    git -C $ROOT checkout 0f949990^ -- site/console.js && sudo $ROOT/scripts/deploy.sh"
  say ""
  say "  RISK: low. It copies web assets into a directory the API does not read. It does not"
  say "  restart anything -- Caddy serves from disk, so the change is live on the next request."
else
  say "    skipped -- pass --with-site-deploy."
  say "    Until it runs the webroot renders a dead surface as POWERED. No surface is"
  say "    delegated yet, so nothing can currently reach that state -- which is exactly why"
  say "    this must land before the sigils delegation flips, not after."
fi

# =====================================================================  summary
hdr "summary  [$(mode)]"
if [ "$APPLY" -eq 1 ]; then
  say "  changed: $STEPS_DONE   already-correct: $STEPS_SKIPPED   failed: $FAILED"
  say "  backups: $BACKUP"
  say ""
  say "  Run this script again -- every step should now report 'already correct', which is"
  say "  the idempotence check."
  [ "$FAILED" -gt 0 ] && say "  SOMETHING FAILED. Read the '!!' lines above before continuing."
else
  say "  Nothing was changed. $STEPS_SKIPPED step(s) are already correct."
  say ""
  say "  To act:  sudo ops/deploy/commission-apply.sh --apply"
  say "  Reboot is NOT part of this script and is deliberately left to the owner."
fi
exit "$([ "$FAILED" -gt 0 ] && echo 1 || echo 0)"
