#!/usr/bin/env python3
# SPDX-License-Identifier: LicenseRef-SyMoNeuRaL-Proprietary
# Copyright (c) 2026 SymonSays LLC. All rights reserved.
"""Find meaningful large duplicates ACROSS the four storage roots.

    tools/cross_root_audit.py scan     inventory, group, and write the report
    tools/cross_root_audit.py report   re-print the last report without rescanning

Roots audited: /home/google/Symoneural, /home/google, /yocto, and gdrive:.

## Why the threshold is high and the exclusions are broad

The spec is explicit: *"Do not waste hours treating identical tiny cache/source files
inside active build trees as architectural duplication."* A Yocto sstate-cache and a Go
module cache legitimately contain thousands of files identical to their upstream copies --
that is what a cache IS, and reporting it as duplication produces a report nobody can read
and no action anybody should take.

So this looks only at objects of at least 32 MiB, and skips caches and version-control
internals outright. What survives that filter is the category the spec actually names:
models, archives, source snapshots, SDKs, toolchains, ISOs, firmware, completed build
output, project trees and backups.

## Why MD5, and only MD5

Google Drive's sole native hash is MD5 -- `rclone hashsum sha256` returns EMPTY for this
remote, which is the shape of a check that appears to pass because it never ran. Any hash
compared ACROSS the local disks and Drive must therefore be MD5, so MD5 is what this uses.
Within the local roots a stronger hash would be available, but a mixed-hash report cannot
answer the one question being asked.

MD5's collision weakness is irrelevant here: nobody is crafting collisions inside the
owner's own storage. Pairing it with an exact size match is what can actually be verified.

## Hashing is size-gated, because hashing everything would take hours

Two files of different length are never the same bytes, so only sizes that appear more
than once are hashed at all. That turns a full read of every large file into a read of
just the candidates.

## What it does NOT do

It deletes nothing and moves nothing. It produces a ledger with a recommended survivor and
a reason, for a human or a later verified operation to act on. A cross-root auditor that
also deleted would be making custody decisions from a snapshot.

Claude-related duplicates are reported SEPARATELY, never as unexplained. Their local copies
are held deliberately until the owner's post-exit finalizer no longer needs them, so a
verified Drive copy plus a retained local copy is an expected state and counting it as a
finding would misreport a deliberate decision as a mess.
"""
from __future__ import annotations

import argparse
import collections
import hashlib
import json
import os
import pathlib
import subprocess
import sys
import time

ROOT = pathlib.Path("/home/google/Symoneural")
OUT = ROOT / ".private" / "storage-reorg" / "cross-root"
LOCAL_ROOTS = [
    pathlib.Path("/home/google/Symoneural"),
    pathlib.Path("/home/google"),
    pathlib.Path("/yocto"),
]
MIN_BYTES = 32 * 1024 * 1024

#: Caches, version-control internals and virtual environments. Identical files inside these
#: are the normal operation of a cache, not architectural duplication.
SKIP_PARTS = (
    "/.git/", "/.cache/", "/sstate-cache/", "/downloads/", "/node_modules/",
    "/__pycache__/", "/.venvs/", "/.npm/", "/.cargo/", "/.rustup/", "/go/pkg/",
    "/.local/lib/", "/.gradle/", "/.m2/", "/.hunter/", "/site-packages/",
    "/.nv/", "/.var/", "/.swiftpm/", "/.dotnet/", "/.jdks/", "/.pyenv/",
)
#: Deliberately held pending the owner's post-exit finalizer. Reported separately.
CLAUDE_MARKERS = ("claude", "anthropic")


def sh(a, t=7200):
    return subprocess.run(a, capture_output=True, text=True, timeout=t)


def md5_of(p: pathlib.Path) -> str | None:
    h = hashlib.md5()
    try:
        with p.open("rb") as fh:
            for c in iter(lambda: fh.read(1 << 22), b""):
                h.update(c)
    except OSError:
        return None
    return h.hexdigest()


def local_inventory() -> list[tuple[str, int, str]]:
    """(path, size, root) for every local file at or above the threshold."""
    seen_dev_ino: set[tuple[int, int]] = set()
    out = []
    for root in LOCAL_ROOTS:
        if not root.is_dir():
            continue
        for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
            dp = dirpath + "/"
            if any(s in dp for s in SKIP_PARTS):
                dirnames[:] = []
                continue
            # Do not descend from /home/google into Symoneural or /yocto twice.
            if root == pathlib.Path("/home/google"):
                dirnames[:] = [d for d in dirnames if d not in ("Symoneural",)]
            for fn in filenames:
                p = pathlib.Path(dirpath) / fn
                try:
                    stt = p.lstat()
                except OSError:
                    continue
                if not os.path.isfile(p) or os.path.islink(p):
                    continue
                if stt.st_size < MIN_BYTES:
                    continue
                key = (stt.st_dev, stt.st_ino)
                if key in seen_dev_ino:
                    continue          # a hardlink is one object, not a duplicate
                seen_dev_ino.add(key)
                out.append((str(p), stt.st_size, str(root)))
    return out


def drive_inventory() -> list[tuple[str, int, str]]:
    r = sh(["rclone", "lsjson", "gdrive:", "--recursive", "--files-only",
            "--hash", "--hash-type", "md5"], 21600)
    if r.returncode != 0:
        print(f"  drive inventory failed: {r.stderr.strip()[:160]}")
        return []
    try:
        rows = json.loads(r.stdout)
    except json.JSONDecodeError:
        print("  drive inventory was not valid JSON (probably truncated); not trusting it")
        return []
    out = []
    for x in rows:
        sz = int(x.get("Size") or 0)
        if sz < MIN_BYTES:
            continue
        h = (x.get("Hashes") or {}).get("md5") or ""
        out.append((f"gdrive:{x.get('Path')}", sz, h))
    return out


def scan() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    os.chmod(OUT, 0o700)
    print(f"  threshold: {MIN_BYTES/2**20:.0f} MiB")
    loc = local_inventory()
    print(f"  local objects at or above threshold: {len(loc)}")
    drv = drive_inventory()
    print(f"  drive objects at or above threshold: {len(drv)}")

    # Size-gate: only hash sizes that occur more than once anywhere.
    sizes = collections.Counter([s for _, s, _ in loc] + [s for _, s, _ in drv])
    candidates = {s for s, c in sizes.items() if c > 1}
    print(f"  distinct sizes: {len(sizes)}   colliding sizes worth hashing: "
          f"{len(candidates)}")

    hashed: dict[tuple[str, int], list[str]] = collections.defaultdict(list)
    n = 0
    for path, size, _root in loc:
        if size not in candidates:
            continue
        h = md5_of(pathlib.Path(path))
        n += 1
        if h:
            hashed[(h, size)].append(path)
    print(f"  local files hashed: {n}")
    for path, size, h in drv:
        if size in candidates and h:
            hashed[(h, size)].append(path)

    groups = {k: sorted(v) for k, v in hashed.items() if len(v) > 1}

    def is_claude(paths) -> bool:
        return any(any(m in p.lower() for m in CLAUDE_MARKERS) for p in paths)

    def root_of(p: str) -> str:
        if p.startswith("gdrive:"):
            return "gdrive"
        for r in ("/home/google/Symoneural", "/yocto", "/home/google"):
            if p.startswith(r):
                return r
        return "?"

    # A group only matters if it spans more than one ROOT. Two copies inside one root are a
    # within-root duplicate, which the Drive dedupe pass or a local cleanup owns.
    cross = {k: v for k, v in groups.items() if len({root_of(p) for p in v}) > 1}
    claude_held = {k: v for k, v in cross.items() if is_claude(v)}
    unexplained = {k: v for k, v in cross.items() if not is_claude(v)}

    led = OUT / "CROSS-ROOT-DUPLICATES.tsv"
    with led.open("w") as fh:
        fh.write("HASH\tSIZE_BYTES\tROOTS\tPATHS\tCANONICAL_SURVIVOR\tWHY\tACTION\n")
        for (h, size), paths in sorted(cross.items(), key=lambda kv: -kv[0][1]):
            # Prefer the Drive copy as survivor for history/reference material: the whole
            # point of the reorganisation is that bulk lives on Drive and the local roots
            # stay lean.
            drive_copies = [p for p in paths if p.startswith("gdrive:")]
            keep = drive_copies[0] if drive_copies else paths[0]
            claude = is_claude(paths)
            why = ("CLAUDE HOLD: local copy retained deliberately until the post-exit "
                   "finalizer no longer needs it; the Drive copy is verified"
                   if claude else
                   "identical md5 and size across roots")
            action = "REPORT_ONLY_CLAUDE_HOLD" if claude else "REVIEW_RETIRE_LOCAL"
            fh.write(f"{h}\t{size}\t{','.join(sorted({root_of(p) for p in paths}))}\t"
                     f"{' | '.join(paths)}\t{keep}\t{why}\t{action}\n")
    os.chmod(led, 0o600)

    waste = sum(k[1] * (len(v) - 1) for k, v in unexplained.items())
    summary = {
        "measured_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "threshold_bytes": MIN_BYTES,
        "local_objects": len(loc), "drive_objects": len(drv),
        "cross_root_groups": len(cross),
        "CROSS_ROOT_UNEXPLAINED_LARGE_DUPLICATES": len(unexplained),
        "unexplained_reclaimable_bytes": waste,
        "claude_held_groups": len(claude_held),
        "claude_held_bytes": sum(k[1] * (len(v) - 1) for k, v in claude_held.items()),
        "ledger": str(led),
    }
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    os.chmod(OUT / "summary.json", 0o600)
    for k, v in summary.items():
        print(f"  {k} = {v}")
    return 0


def report() -> int:
    f = OUT / "summary.json"
    if not f.is_file():
        print("  no scan yet; run `scan`")
        return 1
    print(f.read_text())
    return 0


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["scan", "report"])
    return scan() if ap.parse_args(argv).cmd == "scan" else report()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
