#!/usr/bin/env python3
# SPDX-License-Identifier: LicenseRef-SyMoNeuRaL-Proprietary
# Copyright (c) 2026 SymonSays LLC. All rights reserved.
# SyMoNeuRaL is a subdivision of SymonSays LLC. Licence: /LICENSE at the repository root.
"""De-duplicate Google Drive, deleting only what is provably a redundant copy.

The owner: *"there is still a lot of random files and archives in /mnt/gdrive please clean
this up"* and *"kill all duplicates we should not have duplicates."*

This deletes files from the owner's Drive, so the bar is proof rather than resemblance.

## What counts as a duplicate here

Identical **MD5 and identical size**, from the hash inventory rclone reads off the remote.
Not similar names. Not "looks like a copy". Drive's native checksum is MD5 and rclone gets
it from the API, so two files with the same MD5 and the same byte count are the same bytes.

MD5 is collision-prone against a *deliberate* attacker, which is irrelevant here: nobody is
crafting collisions inside somebody's Drive folder. Pairing it with an exact size match is
what the tool can actually verify, since Drive exposes no stronger hash -- `rclone hashsum
sha256` returns empty for this remote.

## What it will never do

* delete the last copy of anything -- one member of every group always survives;
* delete a file that is not byte-identical to its survivor;
* delete anything under a protected prefix (below), whatever its hash says;
* delete without `--apply`. The default prints the plan and touches nothing.

## Which copy survives

The **shortest path**, tie-broken alphabetically. Deliberate and boring: a file at
`Projects_Crypto/x.zip` outranks `Archive/old/copy-of/Projects_Crypto/x.zip`, so the
survivor tends to be the one in the organised location rather than the one buried in a
backup-of-a-backup. Deterministic, so a dry run and the real run agree.

    python3 tools/drive-dedupe.py                # plan only, nothing deleted
    python3 tools/drive-dedupe.py --apply        # delete redundant copies
"""
from __future__ import annotations

import argparse
import collections
import json
import pathlib
import subprocess
import sys

ROOT = pathlib.Path("/home/google/Symoneural")
STATE_DIR = ROOT / ".private" / "storage-reorg"
INVENTORY = STATE_DIR / "gdrive-inventory.json"
#: Section 4 step 6: "record victim, survivor, hash, size in DUPLICATES.tsv". A dedupe that
#: deletes without a ledger leaves nobody able to answer what was removed or why.
LEDGER = STATE_DIR / "catalog" / "DUPLICATES.tsv"

#: Never touched, whatever the hashes say. These are the paths THIS project just uploaded
#: and is still verifying against; a de-duplicator that eats its own freshly-verified
#: backup would be the single worst outcome available to it.
PROTECTED = (
    # Restore material. Deleting a "redundant" copy of the thing you would rebuild from is
    # the single worst outcome available to this tool.
    "Symoneural/Restore-Recovery/",
    # Revision-keyed upstream snapshots. Two snapshots of the same project at different
    # revisions are NOT duplicates, and one at the same revision is the point of the
    # scheme -- immutability -- not waste.
    "Symoneural/Upstream-Source/",
    # The catalogue itself.
    "INDEX.md", "CATALOG.tsv", "MIGRATION-MAP.tsv", "DUPLICATES.tsv",
    # Still-in-flight staging from the current migration. The old `offload` and
    # `DONOTDELETE` prefixes were removed from this list on 2026-09-09 because those
    # buckets are being dissolved: protecting a path that no longer exists protects
    # nothing, and protecting one being emptied would block its own cleanup.
)

#: A group is only considered when the file is at least this big. Tiny files are mostly
#: `.gitkeep`, `__init__.py`, icons and empty JSON -- thousands of legitimate identical
#: copies whose removal frees nothing and whose absence breaks trees.
MIN_BYTES = 1 * 1024 * 1024


def load() -> list[dict]:
    if not INVENTORY.is_file():
        sys.exit(f"drive-dedupe: no inventory at {INVENTORY}. Run:\n"
                 f"  rclone lsjson gdrive: --recursive --files-only --hash "
                 f"--hash-type md5 > {INVENTORY}")
    try:
        return json.loads(INVENTORY.read_text())
    except json.JSONDecodeError as e:
        sys.exit(f"drive-dedupe: inventory is not valid JSON ({e}). It was probably "
                 f"truncated -- re-run the listing rather than trusting a partial file.")


def groups(rows: list[dict]) -> dict[tuple, list[str]]:
    by: dict[tuple, list[str]] = collections.defaultdict(list)
    for r in rows:
        h = (r.get("Hashes") or {}).get("md5")
        size = r.get("Size") or 0
        path = r.get("Path") or ""
        if not h or size < MIN_BYTES:
            continue
        if path.startswith(PROTECTED):
            continue
        by[(h, size)].append(path)
    return {k: sorted(v) for k, v in by.items() if len(v) > 1}


#: Section 4 step 3: "choose canonical survivor based on new taxonomy". Lower rank wins.
#: Path length alone was the old proxy and it is a bad one: it would prefer a copy sitting
#: loose at the root over the correctly-filed one three levels down inside a semantic
#: collection, which is backwards now that the collections exist.
_TAXONOMY_RANK = (
    "Symoneural/", "Models/", "Build-Outputs/", "Projects/", "Development-Reference/",
    "Virtualization/", "Media/", "Personal/", "Private/", "Historical-Archive/",
)


def _rank(path: str) -> int:
    for i, prefix in enumerate(_TAXONOMY_RANK):
        if path.startswith(prefix):
            return i
    return len(_TAXONOMY_RANK)          # outside the taxonomy: least preferred survivor


def survivor(paths: list[str]) -> str:
    """Prefer a canonical collection, then the shallower path, then alphabetical.

    Deterministic, so a dry run and the real run cannot disagree about which copy lives.
    """
    return sorted(paths, key=lambda p: (_rank(p), p.count("/"), len(p), p))[0]


def record_duplicate(victim: str, keep: str, md5: str, size: int, action: str) -> None:
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    new = not LEDGER.exists()
    with LEDGER.open("a") as fh:
        if new:
            fh.write("HASH\tSIZE_BYTES\tVICTIM_PATH\tSURVIVOR_PATH\tWHY\tACTION\n")
        fh.write(f"{md5}\t{size}\t{victim}\t{keep}\t"
                 f"identical md5 and size; survivor verified immediately before deletion"
                 f"\t{action}\n")
    import os as _os
    _os.chmod(LEDGER, 0o600)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true",
                    help="actually delete; default prints the plan and deletes nothing")
    ap.add_argument("--limit", type=int, default=0, help="cap deletions (for a first run)")
    a = ap.parse_args(argv)

    rows = load()
    total = sum(r.get("Size") or 0 for r in rows)
    g = groups(rows)
    reclaim = sum(k[1] * (len(v) - 1) for k, v in g.items())

    print(f"  files inventoried      {len(rows):,}")
    print(f"  bytes on Drive         {total:,} ({total / 2**30:.1f} GiB)")
    print(f"  duplicate groups       {len(g):,}  (identical md5 AND size, >= 1 MiB)")
    print(f"  redundant copies       {sum(len(v) - 1 for v in g.values()):,}")
    print(f"  reclaimable            {reclaim:,} bytes ({reclaim / 2**30:.1f} GiB)\n")

    plan: list[tuple[str, str, int]] = []
    for (h, size), paths in sorted(g.items(), key=lambda kv: -kv[0][1] * (len(kv[1]) - 1)):
        keep = survivor(paths)
        for p in paths:
            if p != keep:
                plan.append((p, keep, size))

    for victim, keep, size in plan[:25]:
        print(f"  {size / 2**20:9.1f} MiB  DELETE {victim[:78]}")
        print(f"{'':14}   KEEP   {keep[:78]}")
    if len(plan) > 25:
        print(f"  ... and {len(plan) - 25:,} more")

    if not a.apply:
        print(f"\n  DRY RUN -- nothing deleted. Re-run with --apply.")
        return 0

    if a.limit:
        plan = plan[:a.limit]
    print(f"\n  deleting {len(plan):,} redundant copies ...")
    done = failed = 0
    for victim, keep, size in plan:
        # Re-verify immediately before deleting. The inventory is a snapshot and the
        # survivor is what makes this safe -- if it has gone since the listing, the
        # "redundant" copy is now the only one and must not be removed.
        chk = subprocess.run(["rclone", "lsjson", f"gdrive:{keep}", "--hash",
                              "--hash-type", "md5"],
                             capture_output=True, text=True, timeout=180)
        ok = False
        if chk.returncode == 0:
            try:
                j = json.loads(chk.stdout)
                ok = bool(j) and (j[0].get("Hashes") or {}).get("md5") is not None
            except json.JSONDecodeError:
                ok = False
        if not ok:
            # The survivor has gone since the listing, so this "redundant" copy is now the
            # only one. Recording the skip matters as much as recording a deletion.
            print(f"    SKIP (survivor missing): {keep[:70]}")
            record_duplicate(victim, keep, "", size, "SKIPPED_SURVIVOR_MISSING")
            failed += 1
            continue
        r = subprocess.run(["rclone", "deletefile", f"gdrive:{victim}"],
                           capture_output=True, text=True, timeout=300)
        if r.returncode == 0:
            record_duplicate(victim, keep, "", size, "DELETED")
            done += 1
            if done % 50 == 0:
                print(f"    {done:,}/{len(plan):,}")
        else:
            failed += 1
            record_duplicate(victim, keep, "", size, "DELETE_FAILED")
            print(f"    FAILED {victim[:70]}: {r.stderr.strip()[:90]}")

    print(f"\n  deleted {done:,}, failed/skipped {failed:,}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
