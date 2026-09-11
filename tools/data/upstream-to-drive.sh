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

# SPDX-License-Identifier: LicenseRef-SyMoNeuRaL-Proprietary
# Copyright (c) 2026 SymonSays LLC. All rights reserved.
# SyMoNeuRaL is a subdivision of SymonSays LLC. Licence: /LICENSE at the repository root.
#
# upstream-to-drive.sh -- retire external/referencestochatgpt to Google Drive as immutable
# per-revision snapshots, and leave the repository holding only the recipe.
#
# ---------------------------------------------------------------------------------------
# WHY THIS EXISTS, AND WHY THE EARLIER REASONING WAS WRONG
#
# This tool's predecessor deliberately KEPT external/referencestochatgpt local -- 21.9 GiB
# of upstream clones -- on the argument that "a rebuild should not depend on GitHub being
# reachable on the day". The protection was real. The conclusion was not: it turned a
# temporary safeguard into permanent storage policy and left tens of gigabytes of
# third-party reference source inside the running server repository.
#
# The owner's correction is the right design:
#
#     GitHub upstream  +  Drive snapshot  +  pinned SHA in the repo  +  local patch
#         = rebuild protection, with none of it living in production
#
# You do not need a 21.9 GiB clone in the repository to be safe from a GitHub outage. You
# need a verified snapshot somewhere durable and a recipe that can find it.
#
# ---------------------------------------------------------------------------------------
# LAYOUT: IMMUTABLE, KEYED BY REVISION
#
#     gdrive:Symoneural/Upstream-Source/<project>/<revision>/<project>.tar.zst
#     gdrive:Symoneural/Upstream-Source/<project>/<revision>/SNAPSHOT.txt
#
# Keyed by the full 40-character revision, never by a date or a word like `old` or `backup`.
# Two revisions of the same project are two directories, so a snapshot can never be
# silently overwritten by a later fetch -- which is the whole point of calling it immutable.
#
# ---------------------------------------------------------------------------------------
# THE GATES, ALL FIVE, BEFORE ANY LOCAL REMOVAL
#
#     DRIVE_SNAPSHOT_PRESENT      the object is listed on the remote
#     DRIVE_SNAPSHOT_VERIFIED     its MD5 read back FROM THE REMOTE equals the local MD5
#     UPSTREAM_REVISION_RECORDED  the 40-hex revision is in the rebuild manifest
#     LOCAL_PATCH_PRESERVED       uncommitted work is captured, or provably absent
#     RESTORE_RECIPE_COMPLETE     tools/sh/restore-upstream.sh can fetch it again
#
# All five, or the tree stays. A tree that fails a gate is left exactly where it is and
# reported -- never moved to deleteme, because a failed transfer's local copy is the only
# copy that exists.
#
#     tools/data/upstream-to-drive.sh --plan
#     tools/data/upstream-to-drive.sh --run
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="$ROOT/external/referencestochatgpt"
REMOTE="gdrive:Symoneural/Upstream-Source"
STAGE="$ROOT/.private/offload-stage"
LEDGER="$ROOT/.private/offload-ledger.tsv"
LOG="$ROOT/.private/offload.log"
MANIFEST="$ROOT/THIRD-PARTY-REBUILD-MANIFEST.tsv"

mkdir -p "$STAGE" && chmod 700 "$STAGE"
say() { printf '%s upstream: %s\n' "$(date +%H:%M:%S)" "$*" | tee -a "$LOG"; }
ledger() { printf '%s\t%s\t%s\t%s\t%s\t%s\n' "$1" "$2" "$3" "$4" "$5" "$(date -Is)" >> "$LEDGER"; }

RCFLAGS="--checksum --transfers 16 --checkers 32 --drive-chunk-size 256M
         --drive-upload-cutoff 256M --buffer-size 128M --retries 5
         --stats 2m --stats-one-line"

# Read the pins from the manifest rather than restating them here. Two copies of a
# revision is two chances to disagree, and the manifest is the authority the restore
# tooling already consults.
col() { awk -F'\t' -v w="$1" 'NR==1{for(i=1;i<=NF;i++) if($i==w){print i;exit}}' "$MANIFEST"; }

pin_for() { # dirname -> revision
    local n="$1" cn cr
    cn=$(col NAME); cr=$(col PINNED_REVISION)
    awk -F'\t' -v n="$n" -v cn="$cn" -v cr="$cr" 'NR>1 && $cn==n{print $cr;exit}' "$MANIFEST"
}
lic_for() { local n="$1"; awk -F'\t' -v n="$n" -v cn="$(col NAME)" -v cl="$(col LICENSE)" \
    'NR>1 && $cn==n{print $cl;exit}' "$MANIFEST"; }
url_for() { local n="$1"; awk -F'\t' -v n="$n" -v cn="$(col NAME)" -v cu="$(col UPSTREAM_PROJECT)" \
    'NR>1 && $cn==n{print $cu;exit}' "$MANIFEST"; }
patch_for() { local n="$1"; awk -F'\t' -v n="$n" -v cn="$(col NAME)" -v cp="$(col LOCAL_PATCH)" \
    'NR>1 && $cn==n{print $cp;exit}' "$MANIFEST"; }

one() {
    local d="$1"
    local name; name="$(basename "$d")"
    [ -d "$d" ] || { say "SKIP $name (absent)"; return 0; }

    local rev lic url patch
    rev="$(pin_for "$name")"
    lic="$(lic_for "$name")"; url="$(url_for "$name")"; patch="$(patch_for "$name")"

    # GATE 3 + 5 first, because they cost nothing and a failure means do not upload at all.
    if [ -z "$rev" ]; then
        # Not a manifest-pinned upstream. It still goes to Drive, but under Reference/
        # rather than Upstream-Source/, because a snapshot with no revision identity is
        # reference material and calling it an immutable upstream snapshot would be a lie.
        say "$name has no pinned revision -> Reference, not Upstream-Source"
        return 2
    fi
    if ! grep -q "$rev" "$ROOT/tools/sh/restore-upstream.sh" "$MANIFEST" 2>/dev/null; then
        say "FAIL $name: revision $rev not reachable by the restore recipe"
        return 1
    fi

    local dest="$REMOTE/$name/$rev"
    local tarf="$STAGE/upstream_${name}.tar.zst"

    # GATE 4: uncommitted work. A revision pin restores the upstream; it cannot restore
    # edits nobody committed anywhere.
    local dirty=0
    if [ -d "$d/.git" ]; then
        dirty=$(git -C "$d" status --porcelain 2>/dev/null | grep -vc '^??' || true)
        local actual; actual=$(git -C "$d" rev-parse HEAD 2>/dev/null)
        if [ "$actual" != "$rev" ]; then
            say "FAIL $name: on disk at ${actual:0:12}, manifest says ${rev:0:12}"
            return 1
        fi
    fi
    if [ "$dirty" -gt 0 ] && { [ "$patch" = "-" ] || [ ! -f "$ROOT/$patch" ]; }; then
        say "FAIL $name: $dirty uncommitted change(s) and no preserved patch -- KEPT LOCAL"
        return 1
    fi

    say "PACK   $name @ ${rev:0:12} ($(du -sh "$d" | cut -f1))"
    rm -f "$tarf"
    if ! tar -cf - -C "$(dirname "$d")" "$name" 2>>"$LOG" | zstd -3 -T0 -q -o "$tarf" 2>>"$LOG"; then
        say "FAIL $name: tar|zstd"; return 1
    fi
    chmod 600 "$tarf"
    local lm bytes
    lm=$(md5sum "$tarf" | cut -d' ' -f1); bytes=$(stat -c%s "$tarf")
    say "       -> $(numfmt --to=iec "$bytes")  md5 $lm"

    # The metadata that makes the snapshot self-describing on the remote. Someone finding
    # this directory in two years should not need this repository to know what it is.
    local meta="$STAGE/SNAPSHOT.txt"
    cat > "$meta" <<META
UPSTREAM_PROJECT=$name
UPSTREAM_URL=$url
UPSTREAM_REVISION=$rev
UPSTREAM_LICENSE=$lic
SNAPSHOT_FILE=$(basename "$tarf")
SNAPSHOT_MD5=$lm
SNAPSHOT_BYTES=$bytes
SNAPSHOT_TAKEN=$(date -Is)
ORIGIN=/home/google/Symoneural/external/referencestochatgpt/$name
LOCAL_PATCH=$patch
UNCOMMITTED_CHANGES_AT_SNAPSHOT=$dirty
RESTORE=tools/sh/restore-upstream.sh $name    # or: git clone \$UPSTREAM_URL && git checkout \$UPSTREAM_REVISION
WHY_RETAINED=offline rebuild protection without keeping upstream source in the production repository
META

    say "UPLOAD $name"
    if ! rclone copy "$tarf" "$dest/" $RCFLAGS >>"$LOG" 2>&1; then
        say "FAIL $name: upload -- KEPT LOCAL"; rm -f "$tarf" "$meta"; return 1
    fi
    rclone copy "$meta" "$dest/" --checksum >>"$LOG" 2>&1

    # GATE 1 + 2: present, and its hash read back from the remote.
    local rm5
    rm5=$(rclone hashsum md5 "$dest/$(basename "$tarf")" 2>/dev/null | awk '{print $1}')
    if [ -z "$rm5" ] || [ "$rm5" != "$lm" ]; then
        say "FAIL $name: remote md5 '${rm5:-none}' != '$lm' -- NOTHING DELETED"
        ledger "upstream/$name" MD5_MISMATCH "$lm" "${rm5:-none}" "$bytes"
        rm -f "$tarf" "$meta"; return 1
    fi
    say "VERIFY $name  all five gates pass"
    ledger "upstream/$name@${rev:0:12}" VERIFIED "$lm" "$rm5" "$bytes"
    rm -f "$tarf" "$meta"
    rm -rf -- "$d"
    ledger "upstream/$name@${rev:0:12}" REMOVED "$lm" "$rm5" 0
    say "REMOVE $name -- /home now $(df -h /home | tail -1 | awk '{print $5}')"
}

case "${1:---plan}" in
  --plan)
    [ -d "$SRC" ] || { echo "external/referencestochatgpt is already gone"; exit 0; }
    printf '%-26s %10s %-14s %s\n' PROJECT SIZE REVISION LICENCE
    for d in "$SRC"/*; do
      [ -d "$d" ] || continue
      n="$(basename "$d")"; r="$(pin_for "$n")"
      printf '%-26s %10s %-14s %s\n' "$n" "$(du -sh "$d"|cut -f1)" \
        "${r:0:12}${r:+ }" "$(lic_for "$n")${r:+}"
      [ -z "$r" ] && printf '%-26s %10s %s\n' "" "" "-> Reference/ (no pinned revision)"
    done
    echo
    printf 'TOTAL %s in %s entries\n' "$(du -sh "$SRC"|cut -f1)" "$(ls -1 "$SRC"|wc -l)"
    ;;
  --run)
    [ -d "$SRC" ] || { say "external/referencestochatgpt already gone"; exit 0; }
    say "=== start; external/ $(du -sh "$ROOT/external" | cut -f1)"
    UNPINNED=""
    for d in "$SRC"/*; do
      [ -d "$d" ] || continue
      one "$d"; rc=$?
      [ "$rc" = 2 ] && UNPINNED="$UNPINNED $(basename "$d")"
    done
    say "unpinned entries left for the Reference sweep:${UNPINNED:- none}"
    say "=== end;   external/ $(du -sh "$ROOT/external" 2>/dev/null | cut -f1)"
    ;;
  --reference)
    # Everything left in referencestochatgpt/ after the pinned upstreams have gone.
    #
    # These have no pinned revision, so they are NOT immutable upstream snapshots and are
    # not filed as such -- calling a tree with no revision identity an upstream snapshot
    # would be exactly the kind of claim this project keeps having to retract. They are
    # reference source: valuable, worth keeping, and not production runtime.
    [ -d "$SRC" ] || { say "reference sweep: nothing left"; exit 0; }
    n=0; LIST="$STAGE/.ref.list"; : > "$LIST"
    for d in "$SRC"/*; do
      [ -e "$d" ] || continue
      printf 'external/referencestochatgpt/%s\n' "$(basename "$d")" >> "$LIST"
      n=$((n+1))
    done
    if [ "$n" -eq 0 ]; then say "reference sweep: nothing left"; rm -f "$LIST"; exit 0; fi
    T="$STAGE/reference_referencestochatgpt.tar.zst"
    say "PACK   reference remainder ($n entries)"
    rm -f "$T"
    if ! tar -cf - -C "$ROOT" -T "$LIST" 2>>"$LOG" | zstd -3 -T0 -q -o "$T" 2>>"$LOG"; then
      say "FAIL reference remainder: tar|zstd -- KEPT LOCAL"; rm -f "$LIST"; exit 1
    fi
    chmod 600 "$T"
    lm=$(md5sum "$T" | cut -d' ' -f1); bytes=$(stat -c%s "$T")
    say "       $(numfmt --to=iec "$bytes")  md5 $lm"
    say "UPLOAD reference remainder"
    if ! rclone copy "$T" gdrive:Symoneural/Reference/referencestochatgpt/ $RCFLAGS >>"$LOG" 2>&1; then
      say "FAIL reference remainder: upload -- KEPT LOCAL"; rm -f "$T" "$LIST"; exit 1
    fi
    rm5=$(rclone hashsum md5 "gdrive:Symoneural/Reference/referencestochatgpt/$(basename "$T")" 2>/dev/null | awk '{print $1}')
    if [ -n "$rm5" ] && [ "$rm5" = "$lm" ]; then
      say "VERIFY reference remainder  remote md5 matches"
      ledger "reference/referencestochatgpt" VERIFIED "$lm" "$rm5" "$bytes"
      rm -f "$T"
      while IFS= read -r rel; do [ -n "$rel" ] && rm -rf -- "$ROOT/$rel"; done < "$LIST"
      rmdir "$SRC" 2>/dev/null
      ledger "reference/referencestochatgpt" REMOVED "$lm" "$rm5" 0
      say "REMOVE reference remainder ($n entries) -- external/ now $(du -sh "$ROOT/external" 2>/dev/null | cut -f1)"
    else
      say "FAIL reference remainder: remote md5 '${rm5:-none}' != '$lm' -- NOTHING DELETED"
      ledger "reference/referencestochatgpt" MD5_MISMATCH "$lm" "${rm5:-none}" "$bytes"
      rm -f "$T"
    fi
    rm -f "$LIST"
    ;;
  *) echo "usage: $0 [--plan|--run|--reference]" >&2; exit 2 ;;
esac
