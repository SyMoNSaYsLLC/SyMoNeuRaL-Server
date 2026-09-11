#!/usr/bin/env bash
# SPDX-License-Identifier: LicenseRef-SyMoNeuRaL-Proprietary
# Copyright (c) 2026 SymonSays LLC. All rights reserved.
# SyMoNeuRaL is a subdivision of SymonSays LLC. Licence: /LICENSE at the repository root.
#
# restore-upstream.sh -- reacquire the pinned engine upstreams on a machine that does not
# have `external/`.
#
# THIS IS THE SCRIPT THAT MAKES THE BACKUP SMALL. `tools/fork_engines.sh` builds the five
# runtimes out of `external/referencestochatgpt/`, which is 149 GB of third-party source
# that the owner does not want to carry through a machine reset -- and should not have to,
# because every one of those trees is a clean clone of a public remote at a known revision.
# So the backup carries a URL and forty hex characters per engine, and this fetches the
# rest.
#
# The claim "external/ may be omitted" is only true while that is true. It is checked, not
# assumed: `--check` re-reads the pin out of THIRD-PARTY-REBUILD-MANIFEST.tsv and compares
# it against whatever is on disk, and a mismatch is an error rather than a warning.
#
#     tools/restore-upstream.sh --check          # what is here, what is missing
#     tools/restore-upstream.sh all              # fetch everything a build needs
#     tools/restore-upstream.sh llama.cpp        # fetch one
#
# WHAT THIS DOES NOT DO. It does not fetch the GPL-3.0 upstreams unless asked for by name.
# symoneural-miner (kawpowminer) and symoneural-ui (ComfyUI) are DISABLED for this reset --
# their licences mean they cannot become first-party, and the reset spec's answer is to
# disable the feature rather than carry the implementation. `all` therefore fetches the
# three MIT engines. Asking for a copyleft one by name works and prints why it is off.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MANIFEST="$ROOT/THIRD-PARTY-REBUILD-MANIFEST.tsv"
DEST_ROOT="${SYMONEURAL_UPSTREAM_ROOT:-$ROOT/external/referencestochatgpt}"

[ -f "$MANIFEST" ] || {
    echo "restore-upstream: $MANIFEST is missing." >&2
    echo "  Regenerate it: python3 tools/build_restore_manifests.py" >&2
    echo "  Refusing to guess an upstream revision." >&2
    exit 2
}

# Column indices are looked up by NAME from the header rather than hard-coded. A manifest
# that grows a column would otherwise silently shift every field by one and this script
# would start checking out whatever now sits in position 9.
col() { awk -F'\t' -v want="$1" 'NR==1{for(i=1;i<=NF;i++) if($i==want){print i; exit}}' "$MANIFEST"; }
C_NAME=$(col NAME); C_UP=$(col UPSTREAM_PROJECT); C_REV=$(col PINNED_REVISION)
C_LIC=$(col LICENSE); C_REQ=$(col REQUIRED); C_PATCH=$(col LOCAL_PATCH)
for v in C_NAME C_UP C_REV C_LIC C_REQ C_PATCH; do
    [ -n "${!v}" ] || { echo "restore-upstream: manifest is missing a required column ($v)" >&2; exit 2; }
done

rows() { awk -F'\t' 'NR>1' "$MANIFEST"; }

field() { echo "$1" | cut -f"$2"; }

is_copyleft() { case "$1" in *GPL*) return 0;; *) return 1;; esac; }

do_check() {
    local rc=0 row name up rev lic present actual
    printf '%-24s %-10s %-14s %s\n' NAME LICENCE STATE DETAIL
    while IFS= read -r row; do
        name=$(field "$row" "$C_NAME"); up=$(field "$row" "$C_UP")
        rev=$(field "$row" "$C_REV");  lic=$(field "$row" "$C_LIC")
        local dir="$DEST_ROOT/$name"
        if [ ! -d "$dir/.git" ]; then
            printf '%-24s %-10s %-14s %s\n' "$name" "$lic" "ABSENT" "fetch: $up @ ${rev:0:12}"
            # Absent is not a failure for a disabled component -- it is the intended state.
            is_copyleft "$lic" || rc=1
            continue
        fi
        actual=$(git -C "$dir" rev-parse HEAD 2>/dev/null || echo unknown)
        if [ "$actual" = "$rev" ]; then
            local dirty; dirty=$(git -C "$dir" status --porcelain | wc -l)
            if [ "$dirty" -gt 0 ]; then
                printf '%-24s %-10s %-14s %s\n' "$name" "$lic" "PIN_OK" "$dirty uncommitted change(s) -- see LOCAL_PATCH"
            else
                printf '%-24s %-10s %-14s %s\n' "$name" "$lic" "PIN_OK" "${rev:0:12}"
            fi
        else
            printf '%-24s %-10s %-14s %s\n' "$name" "$lic" "PIN_MISMATCH" "want ${rev:0:12} have ${actual:0:12}"
            rc=1
        fi
    done < <(rows)
    return $rc
}

fetch_one() {
    local row="$1" name up rev lic patch dir
    name=$(field "$row" "$C_NAME"); up=$(field "$row" "$C_UP")
    rev=$(field "$row" "$C_REV");   lic=$(field "$row" "$C_LIC")
    patch=$(field "$row" "$C_PATCH")
    dir="$DEST_ROOT/$name"

    echo
    echo "=== $name  ($lic)"
    echo "    upstream: $up"
    echo "    revision: $rev"

    if [ -d "$dir/.git" ]; then
        local actual; actual=$(git -C "$dir" rev-parse HEAD)
        if [ "$actual" = "$rev" ]; then
            echo "    already at the pinned revision -- nothing to do"
            return 0
        fi
        echo "    present at ${actual:0:12}; fetching the pinned revision"
        git -C "$dir" fetch --quiet origin "$rev" || git -C "$dir" fetch --quiet origin
        git -C "$dir" checkout --quiet --detach "$rev"
    else
        mkdir -p "$(dirname "$dir")"
        # Full clone, not --depth 1: submodules are pinned by commit and a shallow clone
        # cannot always resolve them. kawpowminer has two (cmake/cable, Hunter).
        echo "    cloning"
        git clone --quiet "$up" "$dir"
        git -C "$dir" checkout --quiet --detach "$rev"
    fi

    if [ -f "$dir/.gitmodules" ]; then
        echo "    initialising submodules"
        git -C "$dir" submodule update --init --recursive --quiet
    fi

    # VERIFY. The whole point of a pin is that it is checkable, so check it rather than
    # trusting that checkout did what it was told.
    local got; got=$(git -C "$dir" rev-parse HEAD)
    if [ "$got" != "$rev" ]; then
        echo "    ERROR: after checkout HEAD is $got, expected $rev" >&2
        return 1
    fi
    echo "    verified at $rev"

    if [ "$patch" != "-" ] && [ -n "$patch" ]; then
        if [ -f "$ROOT/$patch" ]; then
            echo "    applying preserved local patch: $patch"
            echo "      (a revision pin restores the upstream; it cannot restore edits"
            echo "       that were never committed anywhere)"
            git -C "$dir" apply --check "$ROOT/$patch" \
                && git -C "$dir" apply "$ROOT/$patch" \
                && echo "    patch applied"
        else
            echo "    WARNING: LOCAL_PATCH names $patch and it is not present." >&2
            echo "             This tree had uncommitted local changes. Without the patch" >&2
            echo "             the build may fail or silently differ from what ran here." >&2
            return 1
        fi
    fi
}

main() {
    local want="${1:-}"
    case "$want" in
        --check) do_check; exit $?;;
        "" | -h | --help)
            sed -n '5,30p' "$0" | sed 's/^# \{0,1\}//'
            exit 0;;
    esac

    local matched=0 row name lic req
    while IFS= read -r row; do
        name=$(field "$row" "$C_NAME"); lic=$(field "$row" "$C_LIC")
        req=$(field "$row" "$C_REQ")
        if [ "$want" = "all" ]; then
            if is_copyleft "$lic"; then
                echo
                echo "=== $name  ($lic)  SKIPPED"
                echo "    Component is DISABLED for this reset. A copyleft upstream cannot"
                echo "    be made first-party, and the reset's rule is to disable the"
                echo "    feature rather than carry the implementation. Ask for it by name"
                echo "    if you deliberately want it back."
                matched=1
                continue
            fi
        elif [ "$want" != "$name" ]; then
            continue
        fi
        fetch_one "$row"
        matched=1
    done < <(rows)

    if [ "$matched" -eq 0 ]; then
        echo "restore-upstream: no upstream named '$want' in the manifest." >&2
        echo "known:" >&2
        rows | cut -f"$C_NAME" | sed 's/^/  /' >&2
        exit 2
    fi
    echo
    echo "Now build:  tools/fork_engines.sh <llm|diffuse|listen>"
}

main "$@"
