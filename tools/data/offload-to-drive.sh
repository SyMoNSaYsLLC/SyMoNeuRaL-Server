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
# offload-to-drive.sh -- move bulk non-first-party material to Google Drive, verified, and
# free the local disk.
#
# THE OWNER'S ACTUAL WORRY, IN HIS WORDS: "be careful moving them and ensure they are not
# still on disk after the move bc it seems when i move them sometimes it actually just
# copys them." So the deletion is gated on a hash read back FROM THE REMOTE, and nothing is
# removed on the strength of a transfer having appeared to succeed.
#
# ---------------------------------------------------------------------------------------
# WHY THIS TARS FIRST, WHICH LOOKS LIKE AN EXTRA STEP
#
# Measured on 2026-09-08:
#
#     external/                    3,149,423 files   149 GB
#     archive/workspace-archives/    459,329 files   253 GB
#
# 3.6 million objects. Google Drive charges an API round trip per file and the mount here
# runs --tpslimit 8, so uploading them individually is not slow, it is infeasible -- at 8
# transactions per second that is over five days of API calls before a single byte of
# throughput is considered. One tar per subtree turns 3.6 million objects into a few dozen,
# and Drive is fast at large objects.
#
# The tar is NOT compressed for trees that are already compressed archives (.tar.gz, .zip,
# GGUF) -- gzip on incompressible input costs CPU and saves nothing. Source trees get -z.
#
# ---------------------------------------------------------------------------------------
# THE VERIFICATION, AND WHY IT IS MD5
#
# Google Drive's native checksum is MD5 and nothing else -- `rclone backend features
# gdrive:` reports Hashes: ['md5']. `rclone hashsum sha256` therefore returns EMPTY for this
# remote, which is exactly the shape of a verification that looks like it passed because it
# produced no complaint. MD5 read back from the remote is a real content check; a size
# comparison is not, and neither is reading the file back through the FUSE mount, which can
# be served out of the local vfs cache and prove only that the cache exists.
#
# So every object is: uploaded -> remote MD5 fetched -> compared to the local MD5 -> and
# only then is anything deleted.
#
# ---------------------------------------------------------------------------------------
# RESUMABLE AND IDEMPOTENT
#
# Each subtree records its state in a ledger. A subtree already marked VERIFIED is skipped,
# so an interrupted run continues rather than restarting, and re-running after completion
# does nothing. This will take hours; it must survive being interrupted.
#
#     tools/data/offload-to-drive.sh --plan          # what would move, and how big
#     tools/data/offload-to-drive.sh --run           # do it
#     tools/data/offload-to-drive.sh --status        # ledger
#
set -uo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REMOTE="gdrive:Symoneural/offload"
STAGE="$ROOT/.private/offload-stage"
LEDGER="$ROOT/.private/offload-ledger.tsv"
LOG="$ROOT/.private/offload.log"

mkdir -p "$STAGE" && chmod 700 "$STAGE"
mkdir -p "$(dirname "$LEDGER")"
[ -f "$LEDGER" ] || { printf 'SUBTREE\tSTATE\tLOCAL_MD5\tREMOTE_MD5\tBYTES\tWHEN\n' > "$LEDGER"; chmod 600 "$LEDGER"; }

say() { printf '%s %s\n' "$(date +%H:%M:%S)" "$*" | tee -a "$LOG"; }

# ---------------------------------------------------------------------------------------
# WHAT MOVES.
#
# Everything here is material this server does not need to run: reference source trees whose
# upstreams are pinned and reacquirable, and historical archives nothing references. What is
# NOT here is as important: no first-party source, no models the runtime loads, no training
# adapters or corpus, no .private/, and nothing under the owner's personal directories.
SUBTREES=(
    "external/oss"
    "external/ENGINEERING"
    "external/referencestochatgpt.tar.gz"
    "external/openai"
    "external/ComfyUI (1)"
    "external/ComfyUI-Installs"
    "external/Projects_Crypto"
    "external/Projects_Crypto.tar.gz"
    "external/symoneural"
    "external/TensorRT-LLM"
    "external/contrib"
    "external/ComfyUI-Shared"
    "external/IPTV"
    "archive/workspace-archives/training.tar.gz"
    "archive/workspace-archives/claude-home.tar.gz.part-000"
    "archive/workspace-archives/run.tar.gz"
    "archive/workspace-archives/Symoneural-Extended"
    "archive/workspace-archives/symoneural-repo-2026-08-19.tar.gz"
    "archive/workspace-backups"
    "archive/workspace-builds"
    "archive/workspace-source-candidates"
)

# `external/referencestochatgpt` is DELIBERATELY ABSENT from that list while the reset is in
# progress: it holds the five pinned upstream checkouts, and although they are provably
# reacquirable from public remotes, keeping them until the final archive is verified means a
# rebuild does not depend on GitHub being reachable on the day. It is offloaded last, by
# name, once the owner is satisfied.
#
# `archive/workspace-archives/yocto` (248 GB, 459k files) is also absent: it is the single
# largest object on this disk and needs its own decision from the owner, because a 248 GB
# tar cannot be staged in the 204 GB currently free. See --plan.

# ---------------------------------------------------------------------------------------
# THE /yocto TARGET SET -- the owner's policy, 2026-09-08:
#
#   "/yocto should only contain build material, thats where we build. Once its built it
#    either gets put in symoneural to run or gets put in /mnt/gdrive to use later if
#    needed"
#
# So build INPUTS and the build tree stay; build OUTPUTS and historical material leave.
# Measured: 75.9 GiB stays, 280.7 GiB moves, /yocto goes 65% -> ~15% full.
#
# KEPT on /yocto and deliberately not listed here:
#   downloads sstate-cache build-symoneural matrix-run bitbake openembedded-core
#   meta-openembedded meta-symoneural meta-symoneural-bsp meta-cryptocurrency src
#   controlboard dispatchos blackwell build-audit
#
# artifacts/ FIRST and alone in its urgency: it is the ONLY surviving copy of the 248 GB
# that was de-duplicated out of /home earlier today. Its upload is verified against the
# remote MD5 before a single byte is removed, exactly like every other subtree -- but if
# any entry in this whole tool deserves a second look before deletion, it is that one.
# Everything left loose in /home/google. The owner's rule: "/home/google is just stuff im
# working on right now and havent found a home for it yet... that should be minimal when you
# get done bc i am not working on anything."
#
# NOT listed, each for a stated reason:
#   Symoneural                 the canonical root itself
#   Desktop, Documents         the owner's active desktop; left for him
#   go                         Go module + toolchain cache. Regenerable, but it is BUILD
#                              MATERIAL for symoneural-web and must sit at $GOPATH -- the
#                              same class as /yocto/sstate-cache, which also stays.
#   claude-* control files     the finalizer and its two lists run AFTER Claude exits and
#                              after the repo may be archived; they must be readable from
#                              outside the repository at that moment.
#   lockdown-*.log             ROOT-OWNED; needs one sudo command, reported to the owner.
HOME_SUBTREES=(
    "/home/google/experiments"
    # Symoneural-Performance was SPLIT, not moved wholesale: its first-party half
    # (PERFORMANCE-POLICY.md, benchmarks, harness, results, manifests -- under 1 MB) is now
    # performance/ in the repository, and its 2.5 GB of third-party benchmark `sources/`
    # plus build output goes to Drive. Its 7 commits are preserved as a bundle in
    # .private/git-backup/Symoneural-Performance.bundle first, because moving files out of
    # a git repository leaves the history behind.
    "/home/google/SyMoNeuRaL-Projects"
    "/home/google/ia.Wallpapers"
    "/home/google/Platforms.tar.gz"
    "/home/google/Music"
    "/home/google/Videos"
)

# CORRECTED 2026-09-09 after reading the actual trees rather than the directory names.
#
# /yocto/Antminer_firmware was queued for MOVE and is now KEPT. Measured: it contains
# conf/bblayers.conf, conf/local.conf, scripts/ and sources/meta-antminer -- it is an
# OpenEmbedded build environment and layer, not an archive of firmware blobs. Its NAME
# says firmware; its CONTENT says build material, and the content is what matters. Moving
# it would have taken a working build environment off the build machine.
#
# cgminer and cgminer-master both MOVE, for a measured reason rather than by default:
# meta-cryptocurrency/recipes-miners/cgminer/*.bb fetch from upstream --
# SRC_URI = "git://github.com/{vthoang,dmaxl,ckolivas}/cgminer.git" -- so NEITHER local
# tree is a build source. They are reference snapshots. They are also NOT duplicates of
# each other: cgminer is 22 MB / 286 files with git history at 93db9b54e3, cgminer-master
# is 8 MB / 258 files with no git at all. Two different things, so both are preserved
# rather than one being discarded as a copy of the other.
#
# /yocto/dispatchos is added: it holds only release .tar.gz/.zip/.MANIFEST.txt sets, which
# is completed output, not build-system input.
YOCTO_SUBTREES=(
    "/yocto/artifacts"
    "/yocto/sendtodrive"
    "/yocto/Archives"
    "/yocto/dispatchos"
    "/yocto/cgminer"
    "/yocto/cgminer-master"
)

ledger_state() { awk -F'\t' -v s="$1" '$1==s{print $2}' "$LEDGER" | tail -1; }

ledger_write() { # subtree state local_md5 remote_md5 bytes
    printf '%s\t%s\t%s\t%s\t%s\t%s\n' "$1" "$2" "$3" "$4" "$5" "$(date -Is)" >> "$LEDGER"
}

safe_name() { printf '%s' "$1" | tr '/ ' '__'; }

do_plan() {
    local total=0
    printf '%-52s %10s %10s %s\n' SUBTREE SIZE FILES STATE
    for s in "${SUBTREES[@]}"; do
        [ -e "$ROOT/$s" ] || { printf '%-52s %10s %10s %s\n' "$s" - - ABSENT; continue; }
        local b n st
        b=$(du -sb "$ROOT/$s" 2>/dev/null | cut -f1)
        n=$(find "$ROOT/$s" -type f 2>/dev/null | wc -l)
        st=$(ledger_state "$s"); st=${st:-PENDING}
        total=$((total + b))
        printf '%-52s %10s %10s %s\n' "$s" "$(numfmt --to=iec "$b")" "$n" "$st"
    done
    echo
    printf 'TOTAL TO MOVE : %s\n' "$(numfmt --to=iec "$total")"
    printf 'FREE ON /home : %s\n' "$(df -h /home | tail -1 | awk '{print $4}')"
    echo
    echo "NOT in this list, and each for a stated reason:"
    echo "  external/referencestochatgpt   the five pinned upstreams; kept until the final"
    echo "                                 archive is verified, then offloaded by name"
    echo "  archive/workspace-archives/yocto  248 GB / 459k files -- cannot be staged in the"
    echo "                                 space free; needs the owner's decision"
    echo "  Downloads, Pictures, Desktop   the owner's personal files; not this tool's call"
}

do_one() {
    local s="$1"
    # Absolute targets (the /yocto set) live outside the repository; relative ones are
    # repo-relative. Deriving `src` from the shape of the path keeps ONE implementation of
    # the verified move rather than a second copy that can drift from this one.
    local src base_dir
    case "$s" in
        /*) src="$s";        base_dir="/" ;;
        *)  src="$ROOT/$s";  base_dir="$ROOT" ;;
    esac
    [ -e "$src" ] || { say "SKIP   $s (absent)"; return 0; }
    local st; st=$(ledger_state "$s")
    if [ "$st" = "VERIFIED" ] || [ "$st" = "REMOVED" ]; then say "SKIP   $s (already $st)"; return 0; fi

    local base tar dest
    base="$(safe_name "$s")"
    tar="$STAGE/$base.tar"
    local relpath="${s#/}"
    dest="$REMOTE/$(dirname "$relpath")"

    # An already-compressed payload gains nothing from gzip and costs an hour of CPU.
    case "$s" in
        *.tar.gz|*.zip|*.part-*) tar="$STAGE/$base.tar" ;;
    esac

    # COMPRESS, because the bottleneck is bandwidth and the CPU is idle.
    #
    # Measured on this box 2026-09-08: upload to Drive runs at 5.1 MB/s while 20 cores sit
    # at 10% and 80 GB of RAM is free. A 400 MB sample of external/oss compressed 5.17x
    # with `zstd -3 -T0` at 400 MB/s, so compression is effectively free and multiplies the
    # scarce resource: 5.1 MB/s of wire becomes ~26 MB/s of content.
    #
    # An earlier version skipped compression reasoning "these are already compressed". That
    # was true of the .tar.gz and .zip entries and WRONG about the source trees, which are
    # the bulk of the bytes. The test is now per-subtree rather than a blanket rule.
    case "$s" in
        *.tar.gz|*.zip|*.part-*|*.tgz|*.xz|*.zst) COMPRESS=0 ;;
        *) COMPRESS=1 ;;
    esac
    if [ "$COMPRESS" = 1 ] && command -v zstd >/dev/null; then
        tar="$STAGE/$base.tar.zst"
    fi

    say "PACK   $s ($([ "$COMPRESS" = 1 ] && echo 'zstd -3 -T0' || echo 'store'))"
    rm -f "$tar"
    if [ "$COMPRESS" = 1 ] && command -v zstd >/dev/null; then
        if ! tar -cf - -C "$base_dir" "$relpath" 2>>"$LOG" | zstd -3 -T0 -q -o "$tar" 2>>"$LOG"; then
            say "FAIL   $s: tar|zstd failed"; ledger_write "$s" TAR_FAILED - - 0; return 1
        fi
    elif ! tar -cf "$tar" -C "$base_dir" "$relpath" 2>>"$LOG"; then
        say "FAIL   $s: tar failed"; ledger_write "$s" TAR_FAILED - - 0; return 1
    fi
    chmod 600 "$tar"
    local bytes lmd5 raw
    bytes=$(stat -c%s "$tar")
    raw=$(du -sb "$src" | cut -f1)
    lmd5=$(md5sum "$tar" | cut -d' ' -f1)
    say "       $(numfmt --to=iec "$raw") -> $(numfmt --to=iec "$bytes") md5 $lmd5"

    say "UPLOAD $s"
    # Tuned for this box, measured: 20 cores, 94 GB RAM, 65 GB available, load ~2.
    # The defaults (--transfers 4, 8 MB chunks) leave almost all of that idle. A 256 MB
    # chunk size costs transfers*chunk of RAM -- 16 x 256 MB = 4 GB, which is nothing
    # against 65 GB free -- and is the single biggest lever on Drive upload speed for
    # multi-gigabyte objects.
    if ! rclone copy "$tar" "$dest/" --checksum \
            --transfers 16 --checkers 32 --drive-chunk-size 256M \
            --drive-upload-cutoff 256M --buffer-size 128M \
            --stats 2m --stats-one-line --retries 5 >>"$LOG" 2>&1; then
        say "FAIL   $s: upload failed"; ledger_write "$s" UPLOAD_FAILED "$lmd5" - "$bytes"
        rm -f "$tar"; return 1
    fi

    # THE GATE. Hash from the remote, not from the mount, not from a size.
    local rmd5
    rmd5=$(rclone hashsum md5 "$dest/$(basename "$tar")" 2>/dev/null | awk '{print $1}')
    if [ -z "$rmd5" ] || [ "$rmd5" != "$lmd5" ]; then
        say "FAIL   $s: remote md5 '$rmd5' != local '$lmd5' -- NOTHING DELETED"
        ledger_write "$s" MD5_MISMATCH "$lmd5" "${rmd5:-none}" "$bytes"
        rm -f "$tar"; return 1
    fi
    say "VERIFY $s  remote md5 matches"
    ledger_write "$s" VERIFIED "$lmd5" "$rmd5" "$bytes"

    rm -f "$tar"
    say "REMOVE $s (verified on the remote)"
    rm -rf -- "$src"
    if [ -e "$src" ]; then
        say "WARN   $s still present after rm"
        ledger_write "$s" REMOVE_INCOMPLETE "$lmd5" "$rmd5" "$bytes"
    else
        ledger_write "$s" REMOVED "$lmd5" "$rmd5" "$bytes"
        say "FREED  $s  $(numfmt --to=iec "$bytes")   /home now $(df -h /home | tail -1 | awk '{print $5}') full"
    fi
}

case "${1:---plan}" in
    --plan)   do_plan ;;
    --status) column -t -s$'\t' "$LEDGER" ;;
    --external-rest)
        # EVERYTHING left in external/ except the deferred upstreams, as ONE object.
        #
        # Why a catch-all instead of more list entries: the hand-enumerated SUBTREES list
        # covered 13 of 82 directories and missed 69 of them -- 31.9 GiB including
        # external/anthropics at 5.2 GiB. A queue somebody types will always drift from a
        # directory that grows. This enumerates the disk instead, so nothing can be missed
        # by omission.
        #
        # external/referencestochatgpt is excluded BY NAME: it holds the five pinned
        # upstream checkouts. They are provably reacquirable -- the pins are verified and a
        # bundle-only clone rebuilt whisper.cpp byte-identically from GitHub -- but keeping
        # them until the owner's final archive is verified means a rebuild does not depend
        # on GitHub being reachable on the day.
        say "=== external remainder start"
        REST="$STAGE/external_rest.tar.zst"
        LIST="$STAGE/.external_rest.list"
        : > "$LIST"
        n=0
        for e in "$ROOT"/external/*; do
            [ -e "$e" ] || continue
            b="$(basename "$e")"
            [ "$b" = "referencestochatgpt" ] && continue
            printf 'external/%s\n' "$b" >> "$LIST"
            n=$((n+1))
        done
        if [ "$n" -eq 0 ]; then
            say "external remainder: nothing left"
        else
            say "PACK   external remainder ($n entries, zstd -3 -T0)"
            rm -f "$REST"
            if tar -cf - -C "$ROOT" -T "$LIST" 2>>"$LOG" | zstd -3 -T0 -q -o "$REST" 2>>"$LOG"; then
                chmod 600 "$REST"
                lm=$(md5sum "$REST" | cut -d' ' -f1)
                say "       $(numfmt --to=iec "$(stat -c%s "$REST")")  md5 $lm"
                say "UPLOAD external remainder"
                if rclone copy "$REST" "$REMOTE/external/" --checksum --transfers 16 \
                        --checkers 32 --drive-chunk-size 256M --drive-upload-cutoff 256M \
                        --buffer-size 128M --retries 5 --stats 2m --stats-one-line \
                        >>"$LOG" 2>&1; then
                    rm5=$(rclone hashsum md5 "$REMOTE/external/$(basename "$REST")" \
                          2>/dev/null | awk '{print $1}')
                    if [ -n "$rm5" ] && [ "$rm5" = "$lm" ]; then
                        say "VERIFY external remainder  remote md5 matches"
                        ledger_write "external/<remainder>" VERIFIED "$lm" "$rm5" \
                            "$(stat -c%s "$REST")"
                        rm -f "$REST"
                        while IFS= read -r rel; do
                            [ -n "$rel" ] && rm -rf -- "$ROOT/$rel"
                        done < "$LIST"
                        ledger_write "external/<remainder>" REMOVED "$lm" "$rm5" 0
                        say "REMOVE external remainder ($n entries) -- /home now $(df -h /home | tail -1 | awk '{print $5}')"
                    else
                        say "FAIL   external remainder: remote md5 '${rm5:-none}' != '$lm' -- NOTHING DELETED"
                        ledger_write "external/<remainder>" MD5_MISMATCH "$lm" "${rm5:-none}" 0
                    fi
                else
                    say "FAIL   external remainder: upload failed -- NOTHING DELETED"
                fi
            else
                say "FAIL   external remainder: tar|zstd failed"
            fi
            rm -f "$LIST"
        fi
        say "=== external remainder end"
        ;;
    --one)
        # Move exactly one named subtree. Added so the absolute-path branch could be
        # PROVEN on a 4.6 MB target before 192 GB was committed to it -- and it stays,
        # because retrying a single failed subtree from the ledger should not require
        # running the whole queue.
        [ -n "${2:-}" ] || { echo "usage: $0 --one <path>" >&2; exit 2; }
        say "=== single: $2"
        do_one "$2"
        ;;
    --yocto-plan)
        for s in "${YOCTO_SUBTREES[@]}"; do
            [ -e "$s" ] || { printf '%-40s ABSENT\n' "$s"; continue; }
            printf '%-40s %10s %10s %s\n' "$s" \
                "$(numfmt --to=iec "$(du -sb "$s" | cut -f1)")" \
                "$(find "$s" -type f | wc -l)" "$(ledger_state "$s" || echo PENDING)"
        done ;;
    --home)
        say "=== home offload start; /home $(df -h /home | tail -1 | awk '{print $5}') full"
        for s in "${HOME_SUBTREES[@]}"; do do_one "$s"; done
        say "=== home offload end;   /home $(df -h /home | tail -1 | awk '{print $5}') full"
        ;;
    --yocto)
        say "=== yocto offload start; /yocto $(df -h /yocto | tail -1 | awk '{print $5}') full"
        for s in "${YOCTO_SUBTREES[@]}"; do do_one "$s"; done
        say "=== yocto offload end;   /yocto $(df -h /yocto | tail -1 | awk '{print $5}') full"
        ;;
    --run)
        say "=== offload start; free before: $(df -h /home | tail -1 | awk '{print $4}')"
        for s in "${SUBTREES[@]}"; do do_one "$s"; done
        say "=== offload end;   free after:  $(df -h /home | tail -1 | awk '{print $4}')"
        ;;
    *) echo "usage: $0 [--plan|--run|--status|--yocto-plan|--yocto]" >&2; exit 2 ;;
esac
