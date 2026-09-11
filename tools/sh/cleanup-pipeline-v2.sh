#!/usr/bin/env bash

# ============================================================================
# RETIRED 2026-09-09 -- superseded by tools/data/storage_reorg.py
#
# This script is kept for its recorded reasoning and its route tables, but it
# MUST NOT RUN. Its architecture is the one the storage spec section 0 rejected:
# killing it orphaned its rclone child (twice; one orphan held 16.8 GB of RSS
# re-uploading a tar a second pipeline was also uploading), and editing it while
# bash was still reading it by byte offset made it execute garbage.
#
# Running it now would create a SECOND storage mutation owner alongside
# tools/data/storage_reorg.py, which is exactly what
# ACTIVE_STORAGE_MUTATION_OWNERS=1 forbids -- and two uploaders racing on the
# same source is how a verified destination gets retired against the wrong
# bytes.
#
# Use instead:
#   python3 tools/data/storage_reorg.py plan | run | resume | status | verify
# ============================================================================
if [ "${I_UNDERSTAND_THIS_IS_RETIRED:-}" != "YES" ]; then
    echo "REFUSING: $(basename "$0") was retired 2026-09-09." >&2
    echo "  Superseded by tools/data/storage_reorg.py (checkpointed, resumable)." >&2
    echo "  Running this would create a second storage mutation owner." >&2
    echo "  See the banner at the top of this file for why." >&2
    exit 90
fi

# The single mutation owner for the remaining storage work.
#
# A NEW FILE rather than an edit to cleanup-pipeline.sh: bash reads a script
# incrementally by byte offset, so editing one under a running interpreter shifts the
# remaining content and can make it execute garbage. That happened once already today.
#
# Serialised throughout. Upload bandwidth is the only constraint (~5 MB/s measured), so
# concurrent stages split one pipe, gain nothing, and multiply the ways a partial transfer
# can confuse the ledger.
set -uo pipefail
cd /home/google/Symoneural
L=.private/offload.log
say(){ printf '%s PIPE2: %s\n' "$(date +%H:%M:%S)" "$*" | tee -a "$L"; }
MY=$$
wait_quiet() {
  while ps -eo pid,args --no-headers | awk -v me="$MY" \
      '$1!=me && !/bash -c/ && (/offload-to-drive\.sh --(run|home|yocto|external-rest)/ \
        || /upstream-to-drive\.sh --(run|reference)/)' | grep -q .; do
    sleep 60
  done
}
say "=== start; /home $(df -h /home|tail -1|awk '{print $5}')  /yocto $(df -h /yocto|tail -1|awk '{print $5}')"
wait_quiet; say "prior stage clear"

say "STAGE external remainder";      tools/data/offload-to-drive.sh --external-rest >>"$L" 2>&1; wait_quiet
say "STAGE pinned upstreams";        tools/data/upstream-to-drive.sh --run          >>"$L" 2>&1; wait_quiet
say "STAGE reference remainder";     tools/data/upstream-to-drive.sh --reference    >>"$L" 2>&1; wait_quiet
say "external/ now $(du -sh external 2>/dev/null|cut -f1||echo gone)"
say "STAGE home leftovers";          tools/data/offload-to-drive.sh --home          >>"$L" 2>&1; wait_quiet
say "STAGE yocto";                   tools/data/offload-to-drive.sh --yocto         >>"$L" 2>&1; wait_quiet
say "=== end;   /home $(df -h /home|tail -1|awk '{print $5}')  /yocto $(df -h /yocto|tail -1|awk '{print $5}')"
say "ALL TRANSFER STAGES COMPLETE -- Drive reorganisation and cataloguing are next"
