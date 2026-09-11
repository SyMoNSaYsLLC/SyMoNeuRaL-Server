#!/usr/bin/env bash
# Runs the whole remaining cleanup unattended, in the only order that makes sense:
# bandwidth is the single constraint at ~5 MB/s, so stages run one at a time rather
# than competing for the same pipe.
cd /home/google/Symoneural
L=.private/offload.log
say(){ printf '%s PIPELINE: %s\n' "$(date +%H:%M:%S)" "$*" | tee -a "$L"; }

# 1. wait out whatever offload is already running
while pgrep -f 'offload-to-drive\.sh --(run|home|yocto)$' >/dev/null; do sleep 60; done
say "external set done"

# 1b. everything else in external/ that the hand-written list missed
say "starting external remainder"
tools/data/offload-to-drive.sh --external-rest >> "$L" 2>&1
say "external remainder done -- /home now $(df -h /home | tail -1 | awk '{print $5}')"

# 2. the rest of /home
say "starting home set"
tools/data/offload-to-drive.sh --home >> "$L" 2>&1
say "home set done -- /home now $(df -h /home | tail -1 | awk '{print $5}')"

# 3. /yocto built output
say "starting yocto set"
tools/data/offload-to-drive.sh --yocto >> "$L" 2>&1
say "yocto set done -- /yocto now $(df -h /yocto | tail -1 | awk '{print $5}')"

# 4. Drive de-duplication, once the hash inventory has landed
INV=/tmp/claude-1000/-home-google/0d019856-dbe0-49b4-ad80-0c3d9779a69b/scratchpad/gdrive-inventory.json
ERR=${INV%.json}.err
for i in $(seq 1 240); do grep -q DONE "$ERR" 2>/dev/null && break; sleep 60; done
if [ -f .private/dedupe-run-by-owner.marker ]; then
  say "drive dedupe SKIPPED -- the owner ran it manually at 22:45; a second concurrent"
  say "  deleter would race the first for the same victims and log spurious not-founds"
elif grep -q DONE "$ERR" 2>/dev/null; then
  say "starting drive dedupe"
  python3 tools/data/drive-dedupe.py --apply >> "$L" 2>&1
  say "drive dedupe done"
else
  say "drive inventory never completed; dedupe SKIPPED (nothing deleted)"
fi
say "ALL STAGES COMPLETE"
say "final: / $(df -h / | tail -1 | awk '{print $5}')  /home $(df -h /home | tail -1 | awk '{print $5}')  /yocto $(df -h /yocto | tail -1 | awk '{print $5}')"
