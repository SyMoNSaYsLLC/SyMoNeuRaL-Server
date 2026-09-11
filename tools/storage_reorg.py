#!/usr/bin/env python3
# SPDX-License-Identifier: LicenseRef-SyMoNeuRaL-Proprietary
# Copyright (c) 2026 SymonSays LLC. All rights reserved.
# SyMoNeuRaL is a subdivision of SymonSays LLC. Licence: /LICENSE at the repository root.
r"""The single checkpointed owner of the storage reorganisation.

    tools/storage_reorg.py plan      what would happen, and why, per operation
    tools/storage_reorg.py run       execute from the last verified checkpoint
    tools/storage_reorg.py resume    alias for run; a restart is always a resume
    tools/storage_reorg.py status    the operation ledger
    tools/storage_reorg.py verify    re-check completed operations against reality

## Why this replaces the shell pipelines (spec section 0)

The shell pipelines moved data but kept reproducing the same two failures, recorded here so
the replacement is judged against them rather than against a preference for Python:

**Orphaned children.** Killing a pipeline left its `rclone` child alive. Twice. One orphan
held 16.8 GB of RSS while re-uploading a 27 GB tar a second pipeline was also uploading.
The cause is structural: a shell script's children are not its responsibility, so there is
nowhere to record "this operation is in flight" that survives the parent.

**Editing a script while bash was reading it.** Bash reads a script incrementally by byte
offset, so an edit under a running interpreter shifts the remaining bytes and can make it
execute garbage. That happened once; the workaround was a whole new file per revision,
which does not scale.

Both are solved by the same thing: **state lives in a file, not in a process.** Every
operation has a stable ID and a persisted state, so a restart resumes rather than replays,
and this file can be edited freely between runs because nothing is remembered in the
interpreter.

## The state machine, and why two states rather than one

    PLANNED -> PACKING -> UPLOADING -> DEST_VERIFIED -> SOURCE_RETIRED -> COMPLETE
                                    \-> FAILED (source left exactly where it is)

`DEST_VERIFIED` and `SOURCE_RETIRED` are deliberately separate. The gap between them is the
only moment when the data exists in two places, and therefore the only moment when a crash
is harmless. Collapsing them into a single "moved" state is how a tool ends up having
deleted a source whose destination it never actually confirmed.

`FAILED` never advances and never retires a source. A failed operation's local copy may be
the only copy.

## Tar at the semantic leaf, never at the tree root

The first draft packed each source tree into one opaque `.tar.zst`. That is the exact
failure the spec opens by naming -- "moved data but did not complete the required semantic
reorganization" -- and it makes four requirements unsatisfiable:

* section 4 groups files ">=1 MiB by exact size + Drive MD5". Drive sees one object per
  tarball, so duplicates *inside* it can never be found.
* section 5's `CATALOG.tsv` wants `FILE_COUNT` and `IMPORTANT_FORMATS` per collection. A
  tarball yields one uninspectable row.
* section 4 calls a generic migration tar a *temporary safety container, not permanent
  authority*, and forbids keeping one beside the organised collections.
* section 12 gates on a future engineer answering "where are the old snapshots?" Nobody
  browses into `sendtodrive.tar.zst`.

The opposite extreme fails too: `/yocto/artifacts` is 105,851 files and the Drive mount runs
`--tpslimit 8`, so per-file upload is hours of API calls before any bytes move. The rule
that resolves it:

    one archive per SEMANTIC LEAF, each with a sibling .manifest.tsv listing every
    path and size inside it.

`/yocto/artifacts` becomes six objects keyed by architecture -- which is what section 1.4
means by "preserve architecture/package-manager layout" -- and `/yocto/sendtodrive` becomes
one object per collection at the destination section 3.2 routes it to, which is what
section 1.5 means by "do not simply put the whole mess under one folder called
sendtodrive". The manifests restore browsability without 353,182 Drive objects.

## The verification rule

Google Drive's only native hash is MD5 -- `rclone backend features gdrive:` reports
`Hashes: ['md5']`, and `rclone hashsum sha256` returns EMPTY for this remote, which is the
shape of a check that appears to pass because it produced no complaint. So:

    local md5  ->  upload  ->  md5 read back FROM THE REMOTE  ->  compare

Never from the `/mnt/gdrive` FUSE mount, which can answer out of its own vfs cache and so
proves only that the cache exists.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import threading
import time
import zipfile

ROOT = pathlib.Path("/home/google/Symoneural")
STATE_DIR = ROOT / ".private" / "storage-reorg"
STATE = STATE_DIR / "state.json"
OPS = STATE_DIR / "operations.tsv"
VERIFY_DIR = STATE_DIR / "verification"
LOCK = STATE_DIR / "owner.lock"
STAGE = ROOT / ".private" / "offload-stage"

REMOTE = "gdrive:"
SENDTODRIVE_ZIP = pathlib.Path("/yocto/Archives/sendtodrive.zip")

#: Measured on this box: 20 cores, ~94 GB RAM, ~5 MB/s upload ceiling. Chunk size is the
#: single biggest lever on Drive throughput for multi-gigabyte objects.
RCLONE = ["--checksum", "--transfers", "8", "--checkers", "16",
          "--drive-chunk-size", "256M", "--drive-upload-cutoff", "256M",
          "--buffer-size", "128M", "--retries", "5",
          "--stats", "5m", "--stats-one-line"]

#: Already-compressed payloads gain nothing from zstd and cost CPU for ~0%.
NO_COMPRESS = (".tar.gz", ".tgz", ".zip", ".xz", ".zst", ".bz2", ".7z", ".gz",
               ".gguf", ".safetensors", ".deb", ".rpm", ".iso", ".img", ".ipk")


# =========================================================================================
# Route tables. Declarative on purpose: the plan is data, so `plan` and `run` cannot
# disagree about what will happen, and a new destination is a row rather than a code path.
# =========================================================================================

#: /yocto/sendtodrive is a dismembered copy of the pre-2026-08-20 Symoneural repo, one
#: directory per top-level folder of that repo. Section 3.2 routes by TYPE, not by
#: container, so each lands where a future engineer would actually look.
_SNAP = "Symoneural/History/Source-Snapshots/symoneural-repo-20260820"
_BUILDS = "Symoneural/History/Build-History/symoneural-repo-20260820"
SENDTODRIVE_ROUTES: dict[str, str] = {
    "models":                 "Models/Historical/sendtodrive-models-20260820",
    "old-backend":            _SNAP,
    "old-symoneural":         _SNAP,
    "old-engines":            _SNAP,
    "old-site":               _SNAP,
    "old-tools":              _SNAP,
    "old-tests":              _SNAP,
    "old-deploy":             _SNAP,
    "old-ops":                _SNAP,
    "old-training":           _SNAP,
    "old-incoming":           _SNAP,
    "old-meta-symoneural":    _SNAP,
    "old-desktop-app":        _SNAP,
    "old-desktop-client":     _SNAP,
    "old-bin":                _BUILDS,
    "old-SyMoNeuRaL-Builds":  _BUILDS,
    "old-run":                "Symoneural/History/Task-and-Terminal-History/repo-20260820-run",
    "old-review":             "Symoneural/History/Task-and-Terminal-History/repo-20260820-review",
    "old-docs":               "Symoneural/Documentation/Historical/repo-20260820",
    "old-brand":              "Symoneural/Brand-Assets/Historical/repo-20260820",
    "RESTORE.md":             "Symoneural/Restore-Recovery/Historical/repo-20260820",
    # AppleSDK is deliberately ABSENT. The local directory copy is PARTIAL: the zip holds
    # 38,310 additional AppleSDK files totalling 21.5 GB that were deleted from disk at
    # some point. Uploading the partial copy would enshrine the lossy one as authority, so
    # AppleSDK is handled by op `mv-applesdk-from-zip`, which takes it from the zip.
}

#: Section 1.4: preserve the architecture / package-manager layout. One object per
#: architecture does exactly that, and caps staging at the largest single arch (48G)
#: instead of the whole 149G tree.
ARTIFACT_ROUTES: dict[str, str] = {
    "arm":            "Build-Outputs/Yocto/Packages",
    "arm64":          "Build-Outputs/Yocto/Packages",
    "x86":            "Build-Outputs/Yocto/Packages",
    "x86-64":         "Build-Outputs/Yocto/Packages",
    "baseline":       "Build-Outputs/Yocto/Manifests",
    "Symoneural.zip": "Build-Outputs/Symoneural/Yocto-Image",
}

OPERATIONS: list[dict] = [
    # ------------------------------------------------------- section 7.3: regenerable
    # These run FIRST: instant disk relief at zero bandwidth cost.
    dict(id="drop-frontend-node-modules", kind="drop", src="frontend/node_modules",
         why="Regenerable from frontend/package-lock.json. Section 7.3 is explicit that "
             "caches are removed rather than uploaded -- archiving a node_modules tree "
             "would pay Drive storage for what npm rebuilds from a lockfile.",
         guard="frontend/package-lock.json"),
    dict(id="drop-tests-node-modules", kind="drop", src="tests/node_modules",
         why="Same, against tests/package-lock.json.",
         guard="tests/package-lock.json"),
    dict(id="drop-pycache", kind="drop_glob", src="__pycache__",
         why="Python bytecode caches. Regenerated on import; carrying them is noise."),

    # ------------------------------------------------------- section 6.2: /yocto output
    dict(id="mv-yocto-sendtodrive", kind="move_leaves", src="/yocto/sendtodrive",
         routes=SENDTODRIVE_ROUTES,
         why="Section 1.5: 'do not simply put the whole mess under one new folder called "
             "sendtodrive'. It is a dismembered copy of the pre-2026-08-20 repo, so each "
             "collection is routed by type per section 3.2. MEASURED: all 353,182 files "
             "are CRC32-identical to entries in Archives/sendtodrive.zip (25 differ, all "
             "of them .git/index stat caches), so nothing here is a sole copy.",
         evidence=".private/storage-reorg/verification/sendtodrive-containment.txt"),
    dict(id="mv-applesdk-from-zip", kind="extract_upload", src=str(SENDTODRIVE_ZIP),
         member_prefix="sendtodrive/AppleSDK/",
         dest="Development-Reference/Apple/SDKs/AppleSDK-20260820",
         why="Section 3.3 routes AppleSDK to Development-Reference/Apple/SDKs. Taken from "
             "the ZIP rather than from disk because the disk copy is PARTIAL: the zip has "
             "38,310 more AppleSDK files (21.5 GB) than /yocto/sendtodrive/AppleSDK. "
             "Uploading the disk copy would make the lossy version authority."),
    dict(id="mv-yocto-artifacts", kind="move_leaves", src="/yocto/artifacts",
         routes=ARTIFACT_ROUTES,
         why="Section 1.4: completed package output (arm/arm64/x86/x86-64 deb and ipk "
             "trees plus baseline manifests), 149G across 105,851 files. Split by "
             "architecture so the layout survives on Drive. THIS IS NOW THE ONLY COPY -- "
             "the 248G duplicate under archive/workspace-archives/yocto was already "
             "retired against it -- so its verification gate matters more than any other."),
    dict(id="mv-yocto-dispatchos", kind="move_out", src="/yocto/dispatchos",
         dest="Build-Outputs/Symoneural/DispatchOS",
         why="Section 1.3 MEASURED: only .tar.gz/.zip/.MANIFEST.txt release sets -- "
             "completed output, not build-system input."),
    dict(id="mv-yocto-cgminer", kind="move_out", src="/yocto/cgminer",
         dest="Projects/Crypto/Reference-Source",
         why="Section 1.2/6.3 MEASURED: meta-cryptocurrency/recipes-miners/cgminer/*.bb "
             "fetch upstream (SRC_URI git://github.com/{vthoang,dmaxl,ckolivas}/"
             "cgminer.git), so no local tree is a build source. 22M / 286 files, git at "
             "93db9b54e3."),
    dict(id="mv-yocto-cgminer-master", kind="move_out", src="/yocto/cgminer-master",
         dest="Projects/Crypto/Reference-Source",
         why="Same measurement. NOT a duplicate of cgminer: 8M / 258 files with no git at "
             "all, against 22M / 286 with history. Section 1.2 says compare rather than "
             "assume, and the comparison says these are two different things."),

    # ------------------------------------------------------- section 7.2: archive/ history
    dict(id="mv-workspace-source-candidates", kind="move_out",
         src="archive/workspace-source-candidates",
         dest="Symoneural/History/Source-Snapshots",
         why="Section 7.2: 3.2G of historical source snapshots (~116k tree entries). Git "
             "carries the real history; this does not belong inside the running project."),
    dict(id="mv-build-20260902-src", kind="move_out", src="archive/build-20260902-src",
         dest="Symoneural/History/Source-Snapshots",
         why="Section 7.2: 2.9G snapshot dated 2026-09-02."),
    dict(id="mv-build-20260902-src-b", kind="move_out", src="archive/build-20260902-src-b",
         dest="Symoneural/History/Source-Snapshots",
         why="Section 7.2: 234M second snapshot. Preserved separately rather than assumed "
             "a duplicate of the first -- they are distinct worktrees and were never "
             "compared byte for byte."),
    dict(id="mv-workspace-builds", kind="move_out", src="archive/workspace-builds",
         dest="Symoneural/History/Build-History",
         why="Section 7.2: 4.4G of historical build output."),
    dict(id="mv-workspace-archives", kind="move_out", src="archive/workspace-archives",
         dest="Symoneural/History/Build-History",
         why="Section 7.2 lists this as a MOVE target: 238M remaining after the 248G "
             "yocto duplicate inside it was retired. The earlier hard-stop forbade "
             "DELETING it; verified-relocation-then-retire is not deletion, and the "
             "DEST_VERIFIED -> SOURCE_RETIRED gap is what earns that distinction."),
    dict(id="mv-workspace-backups", kind="move_out", src="archive/workspace-backups",
         dest="Symoneural/Restore-Recovery/Historical",
         why="Section 7.2: 16G of historical backups. Restore-relevant, so Restore-"
             "Recovery rather than generic History."),
    dict(id="mv-transcripts", kind="move_out", src="archive/transcripts",
         dest="Symoneural/History/Task-and-Terminal-History",
         why="Section 7.2: agent session transcripts."),
    dict(id="mv-from-desktop", kind="move_out", src="archive/from-desktop",
         dest="Symoneural/History/Storage-Audit/2026-09-09",
         why="Section 7.2/9.1: material swept off the Desktop in the earlier pass."),
    dict(id="mv-from-home", kind="move_out", src="archive/from-home",
         dest="Symoneural/History/Storage-Audit/2026-09-09",
         why="Section 7.2/9.1: material swept out of /home/google, including the owner's "
             "task prompts and session histories -- the record of what was asked and why."),
    dict(id="mv-tree-dumps", kind="move_out", src="archive/tree-dumps",
         dest="Symoneural/History/Storage-Audit/2026-09-09",
         why="98M of filesystem tree dumps from prior audits."),
    dict(id="mv-lora-staging", kind="move_out",
         src="archive/symoneural-lora-restore-staging-20260903",
         dest="Models/Historical",
         why="Section 7.2: 40M of old LoRA restore staging. Model-adjacent, so Models/"
             "Historical rather than generic history."),
    dict(id="mv-model-downloads", kind="move_out",
         src="archive/symoneural-model-downloads-20260902",
         dest="Models/Historical",
         why="Section 7.2: old model download staging."),

    # ------------------------------------------------------- sections 7.5 / 7.6
    dict(id="mv-incoming", kind="move_out", src="incoming",
         dest="Projects/Archived/Incoming-Symoneural",
         why="Section 7.5: examples and old project candidates (fullstack-example, "
             "RavenCalc Christmas tree, SyMoNeuRaL_TV, symv2-parallel), not active "
             "source authority."),
    dict(id="mv-releases", kind="move_out", src="releases",
         dest="Symoneural/Release-Artifacts",
         why="Section 7.6: binary release archives. Nothing in the deployment path reads "
             "them from here -- verified by grepping ops/ and scripts/ for the path."),

    # ------------------------------------------------------- section 9: /home/google
    dict(id="mv-home-experiments", kind="move_out", src="/home/google/experiments",
         dest="Projects/Experimental",
         why="Section 9.3: not active project work; owner states there is no other "
             "active work."),
    dict(id="mv-home-wallpapers", kind="move_out", src="/home/google/ia.Wallpapers",
         dest="Media/Images/Wallpapers", why="Section 9.5: media worth retaining."),
    dict(id="mv-home-platforms", kind="move_out", src="/home/google/Platforms.tar.gz",
         dest="Development-Reference/SDKs/Platforms",
         why="Platform SDK tarball; reference material, not runtime."),
    dict(id="mv-home-music", kind="move_out", src="/home/google/Music",
         dest="Media/Audio", why="Section 9.5."),
    dict(id="mv-home-videos", kind="move_out", src="/home/google/Videos",
         dest="Media/Video", why="Section 9.5."),
]

# =========================================================================================
# section 7.1 -- external/ reference warehouse
# =========================================================================================
#
#: HARD-STOP PROTECTED. The standing rule is "do not delete or purge any Claude file,
#: directory, session, runtime, cache, socket, configuration, worktree, or backup", and
#: section 9.6 adds "keep [Claude retirement control files] outside the repo until the
#: post-exit finalizer no longer requires them. Do not move early merely for cosmetic
#: cleanup." These four entries (~5.75 GB) therefore stay exactly where they are, and
#: `EXTERNAL_LOCAL_REFERENCE_BYTES` will not reach 0 while they do -- which is the correct
#: reported outcome, not a failure to finish.
EXTERNAL_PROTECTED = {
    "anthropics", "Claude", "ClaudeAlienware",
    "claude-desktop_1.32885.1_amd64.deb",
}

_NV = "Development-Reference/NVIDIA-CUDA"
_TC = "Development-Reference/Toolchains"
_AI = "Development-Reference/AI-Research"
_REF = "Symoneural/Reference"
_STUB = "Symoneural/Reference/external-symoneural-stubs"

#: Everything else at the top of external/, routed by DOMAIN rather than by the accident of
#: which download directory it landed in.
EXTERNAL_ROUTES: dict[str, str] = {
    # NVIDIA / CUDA reference collections
    "apex": _NV, "cosmos": _NV, "cudf": _NV, "cuml": _NV, "DALI": _NV,
    "DeepLearningExamples": _NV, "FasterTransformer": _NV, "Megatron-LM": _NV,
    "Nemotron-main": _NV, "nim-deploy": _NV, "nvidia-aws-samples": _NV,
    "nvidia-azure-samples": _NV, "nvidia-gcp-samples": _NV, "nvidia-oci-samples": _NV,
    "open-gpu-kernel-modules": _NV, "TransformerEngine": _NV, "vid2vid": _NV,
    "ninjatraining": _NV,
    # toolchains and platform SDKs
    "Toolchains": _TC, "Toolchains.tar.gz": _TC,
    "Platforms": "Development-Reference/SDKs/Platforms",
    "Platforms.tar.gz": "Development-Reference/SDKs/Platforms",
    # AI research / agent tooling reference
    "skills": _AI, "SkillSpector": _AI, "bentoml": _AI,
    "DeepSeek Harness developer preview_ Everything is a plugin.mhtml": _AI,
    "DeepSeek Harness.mhtml": _AI,
    "qwen3.6-27b _ NVIDIA NGC.mhtml": _AI, "qwen3.6-27b _ NVIDIA NGC.pdf": _AI,
    "SyMoN_ML (1).pdf": "Symoneural/Documentation/Historical",
    # linux / shell reference
    "OpenShell": "Development-Reference/Linux-System",
    "simpy": "Development-Reference/Linux-System", 
    "simpy.tar.gz": "Development-Reference/Linux-System",
    # archived projects
    "RavenCalcServer_Christmas_20251224-1007": "Projects/Archived/RavenCalc-Christmas-2025",
    # SyMoNeuRaL-NAMED SCAFFOLD STUBS. These are NOT runtime authority: the standing rule
    # is "do not modify or execute source under reference, external, vendor, archive, or
    # evidence trees as first-party runtime code", and a scan of 3,149,423 files under
    # external/ earlier in this work found ZERO first-party-licensed files. The real
    # runtimes live at the repository root (web/symoneural-web, etc), not here.
    "symoneural-browser": _STUB, "symoneural-chat": _STUB, "symoneural-coin": _STUB,
    "symoneural-desktop": _STUB, "symoneuraldesktop.py": _STUB, "symoneural-dj": _STUB,
    "symoneural-image": _STUB, "symoneural-iptv": _STUB, "symoneural-ravencalc": _STUB,
    "symoneural-reinforce": _STUB, "symoneural-studio": _STUB,
    "symoneural-support": _STUB, "symoneural-tv": _STUB, "symoneural-web": _STUB,
    "symoneuralweb.py": _STUB, "symoneural-browser.tar.gz": _STUB,
    "symoneural code": "Symoneural/History/Source-Snapshots/external-symoneural-code",
    "symoneural code.tar.gz": "Symoneural/History/Source-Snapshots/external-symoneural-code",
    "symoneural_tbd": _REF, "Symoneural_OE": _REF, "Symoneural_OE.tar.gz": _REF,
    # miscellaneous reference material and captures
    "reading": _REF, "oematch": _REF, "oematch.tar.gz": _REF,
    "referencesforchatgpt": _REF, "referencesforchatgpt.tar.gz": _REF,
    "drive-download-20260817T185705Z-1-001": _REF,
    "drive-download-20260826T005724Z-1-001": _REF,
    "clone-oss.sh": _REF, "q.json": _REF, "bin": _REF,
}


def _refchatgpt_routes() -> dict[str, str]:
    """Build the referencestochatgpt route table FROM docs/reference/UPSTREAM-PINS.tsv.

    The manifest is the single authority for provenance, so the destinations are derived
    from it rather than retyped. Section 7.1 wants pinned upstreams at
    `Symoneural/Upstream-Source/<project>/<revision>/`, so the revision is part of the
    path -- which is what makes the snapshot immutable and identifiable.
    """
    tsv = ROOT / "docs" / "reference" / "UPSTREAM-PINS.tsv"
    routes: dict[str, str] = {}
    if not tsv.is_file():
        return routes
    for line in tsv.read_text().splitlines()[1:]:
        f = line.split("\t")
        if len(f) < 8:
            continue
        name, rev, cls = f[0], f[3], f[7]
        if cls == "PINNED_CLEAN":
            routes[name] = f"Symoneural/Upstream-Source/{name}/{rev[:12]}"
        elif cls == "PINNED_DIRTY":
            # A dirty tree is not the upstream revision, so it must not be filed as if it
            # were. The suffix keeps it from ever being mistaken for a clean snapshot.
            routes[name] = f"Symoneural/Upstream-Source/{name}/{rev[:12]}-dirty"
        else:
            routes[name] = f"Symoneural/Reference/referencestochatgpt/{name}"
    # Loose entries the manifest does not cover (it enumerates directories only).
    routes["deepseek-harness.tar.gz"] = "Symoneural/Reference/referencestochatgpt"
    # `claude-desktop` is PROTECTED and deliberately absent, so it stays local.
    return routes


OPERATIONS.extend([
    dict(id="mv-external-refchatgpt", kind="move_leaves",
         src="external/referencestochatgpt", routes=_refchatgpt_routes(),
         why="Section 7.1: pinned upstreams become immutable revision-keyed snapshots at "
             "Symoneural/Upstream-Source/<project>/<revision>/. MEASURED across 30 "
             "subtrees: 18 PINNED_CLEAN (18.05 GB), 2 PINNED_DIRTY (0.48 GB, patches "
             "preserved under .private/storage-reorg/patches/), 10 with NO git provenance "
             "at all (2.65 GB) which therefore need a real snapshot rather than a pin. "
             "`claude-desktop` inside is PROTECTED and stays.",
         evidence="docs/reference/UPSTREAM-PINS.tsv"),
    dict(id="mv-external-rest", kind="move_leaves", src="external",
         routes=EXTERNAL_ROUTES,
         why="Section 7.1: the remaining reference warehouse, routed by domain. The four "
             "Claude-related entries (~5.75 GB) are UNROUTED on purpose -- the hard-stop "
             "rule and section 9.6 both keep them local until the owner's retirement "
             "backup is taken, so they stay and are reported rather than moved."),
])


#: Sections 3.1-3.9. Server-side Drive reorganisation: metadata work inside one Drive, so a
#: 700+ GiB store reorganises in minutes instead of re-uploading. These run BEFORE the local
#: moves because they are effectively free and they fix the most visible section 12 gates
#: (top-level count; `Projects_Organize` / `offload` not surviving as buckets).
DRIVE_MOVES: list[tuple[str, str, str]] = [
    ("Projects_Active",         "Projects/Active",                          "3.1"),
    ("Projects_Crypto",         "Projects/Crypto",                          "3.1"),
    ("Projects_Database",       "Projects/Database",                        "3.1"),
    ("Projects_ForHost",        "Projects/Host",                            "3.1"),
    ("Projects_Github",         "Projects/GitHub-Mirrors",                  "3.1"),
    ("Projects_helperscripts",  "Projects/Utilities/Helper-Scripts",        "3.1"),
    ("Projects_Streamer",       "Projects/Streaming",                       "3.1"),
    ("Projects_WebandML",       "Projects/Web-ML",                          "3.1"),
    ("SymoneuralSeptBuilds",    "Symoneural/History/Build-History/Sept-Builds", "3.2"),
    ("symon-backups",           "Symoneural/Restore-Recovery/Historical/symon-backups", "3.2"),
    ("SyOsML_Documentation",    "Symoneural/Documentation/SyOsML",           "3.2"),
    ("SyMoNeuRaL_Runtime_Engineering_Guide",
     "Symoneural/Documentation/Runtime-Engineering-Guide",                  "3.2"),
    ("ClaudeAlienware",         "Symoneural/History/Agent-Sessions/ClaudeAlienware", "3.2"),
    ("AppleSDK",                "Development-Reference/Apple/SDKs/AppleSDK-drive", "3.3"),
    ("Apple Machine Learning Research_files",
     "Development-Reference/Apple/ML-Research",                             "3.3"),
    ("Cross-Platform Development", "Development-Reference/Cross-Platform",   "3.3"),
    ("Source Code and SDK Matrix",
     "Development-Reference/SDKs/Source-and-SDK-Matrix",                    "3.3"),
    ("Hardware Profiles",       "Development-Reference/Hardware",            "3.3"),
    ("System Optimization Reference",
     "Development-Reference/Linux-System/Optimization",                     "3.3"),
    ("System Security",         "Development-Reference/Security",            "3.3"),
    ("Backstage Templates",     "Development-Reference/SDKs/Backstage-Templates", "3.3"),
    ("VMScripts",               "Virtualization/Scripts",                    "3.4"),
    ("Blockchain Proofs of Concept",
     "Projects/Crypto/Research/Blockchain-Proofs-of-Concept",               "3.5"),
    ("Yocto Firmware",          "Build-Outputs/Yocto/Firmware",              "3.5"),
    ("HR MEETING",              "Personal/HR/HR-Meeting",                    "3.6"),
    ("Logistics",               "Personal/Logistics",                        "3.6"),
    ("resumes",                 "Personal/Employment/Resumes",               "3.6"),
    ("Documents",               "Personal/Documents/Drive-Documents",        "3.6"),
    ("Imagesandvideos",         "Media/Imported-Albums",                     "3.7"),
    ("MITModel",                "Models/Historical/MITModel",                "9"),
    ("yocto",                   "Build-Outputs/Yocto/Historical/yocto-root", "3.5"),
    ("Markdown Dialect Tool",   "Projects/Utilities/Markdown-Dialect-Tool",  "2"),
    ("Spotify API Documentation",
     "Development-Reference/AI-Research/Spotify-API",                        "2"),
    ("spotify-integration",     "Projects/Archived/Spotify-Integration",     "2"),
    ("hiranktesting",           "Projects/Experimental/hiranktesting",       "2"),
    ("Archive",                 "Historical-Archive/Drive-Archive",          "2"),
    ("Saved from the Google app",
     "Historical-Archive/Saved-From-Google-App",                             "3.9"),
]



# =========================================================================================
# section 6.1 / 6.3 -- the remaining /yocto entries, each resolved by measurement
# =========================================================================================
#
# MEASURED FACTS THAT DECIDED THESE, none of them inferred from a directory name:
#
# * `/yocto` is ITSELF a git repository -- 11 commits, 254 tracked files, branch main,
#   NO REMOTE and NO BUNDLE. That made it an unprotected sole copy of first-party build
#   authority, which is why `mv-yocto-git-bundle` exists and runs before anything that
#   retires a tracked file.
# * Zero bitbake `EXTERNALSRC` / `SRC_URI` / `FILESEXTRAPATHS` references point at src,
#   blackwell, matrix-run, controlboard, metrics, artifacts, sendtodrive, Archives or
#   dispatchos. None of them is a build input.
#   An earlier scan appeared to find references for `src` and `metrics`; those were false
#   positives, matching the bare words inside unrelated upstream patches (nginx referring
#   to `src/`, Go CVE patches mentioning "metrics"). Only absolute `/yocto/<name>`
#   references count, and there are none outside HANDOFF.md prose.
#
# KEPT, against the spec's own initial reading, because measurement contradicted it:
#
# * `metrics/` (116K) -- section 6.3 calls it "readouts, not build source". It is neither:
#   15 first-party `readout` SCRIPTS plus a README stating "Nothing here invents a metric:
#   every field rendered comes from the Status model in backend/server.py". It is operator
#   tooling and it is tracked in /yocto's git. Kept.
# * `controlboard/` (964K) -- the counterpart: 119 authored `launch` entry points, each
#   saying "Edit freely; this is the entry point, not a wrapper", plus `_dispatch` and a
#   README. 121 tracked files. Generated once, then authored. Kept.

OPERATIONS.extend([
    dict(id="mv-yocto-git-bundle", kind="move_out",
         src=".private/storage-reorg/yocto-git", keep_source=True,
         dest="Symoneural/Restore-Recovery/Yocto-Git",
         why="/yocto is a git repository with 11 commits and 254 tracked files, no remote "
             "and no bundle -- an unprotected sole copy of first-party build authority "
             "(121 controlboard files, 15 metrics readouts, matrix-run's driver.sh and "
             "finalize.sh, blackwell, src, dispatchos). This uploads a verified "
             "`git bundle --all` plus the recorded pre-existing dirty state. The local "
             "copy is KEPT: it is a backup, so retiring it would defeat its purpose."),
    dict(id="mv-yocto-src", kind="move_out", src="/yocto/src",
         dest="Build-Outputs/Symoneural/Source-Archives",
         why="Section 6.1 keeps src/ only for archives used by active recipes or build "
             "scripts. MEASURED: three archives (fwupd-main.zip, Symoneural_OE.tar.gz, "
             "SyMon_MinerGPUWorker_PROD_20260102-1818.tar.gz) and zero recipe references "
             "to any of them. They are completed output, and they are tracked in /yocto's "
             "git so the history retains them after the working copy retires."),
    dict(id="mv-yocto-blackwell", kind="move_out", src="/yocto/blackwell",
         dest="Development-Reference/NVIDIA-CUDA/blackwell-cutlass-samples",
         why="Section 6.1: keep only if used by an active build or benchmark workflow, "
             "otherwise Drive development reference. MEASURED: six CUTLASS Blackwell "
             "GEMM sample .cu files (nvfp4/mxfp8 kernels), zero references from any "
             "recipe, script or config. Reference material."),
    dict(id="mv-yocto-matrix-run-logs", kind="move_files", src="/yocto/matrix-run",
         patterns=["*.log", "prev-*/*", "prev-*/**/*"],
         dest="Build-Outputs/Yocto/Manifests-and-Metrics/matrix-run-logs",
         why="Section 6.1: 'keep active driver/finalize scripts; move old historical logs "
             "to Drive'. MEASURED: 29 .log files plus a prev-2026-08-26-0905 directory, "
             "against exactly two scripts -- driver.sh and finalize.sh -- which are live "
             "build control and are DELIBERATELY RETAINED. A whole-tree move would have "
             "taken them too."),
    dict(id="mv-yocto-root-readouts", kind="move_files", src="/yocto",
         patterns=["workersrunning.txt", "embedded-host-evidence.txt"],
         dest="Build-Outputs/Yocto/Manifests-and-Metrics/root-readouts-20260909",
         why="Section 6.3 asks these be classified as current operational state or "
             "historical evidence. Both are dated 2026-08-25/26 and nothing reads them: "
             "historical evidence, so preserved on Drive rather than deleted."),
    dict(id="drop-yocto-wget-log", kind="drop", src="/yocto/wget-log",
         why="Section 6.3: a stale wget transfer log from 2026-08-26 recording one "
             "download's progress. It is not evidence of anything and nothing reads it. "
             "4K, untracked in /yocto's git. Removed rather than archived."),
])



# =========================================================================================
# archive/buildv2 -- a lopsided split, not a wholesale removal
# =========================================================================================
#
# MEASURED: buildv2 is 5.0G and 4.99G of it is `.local` (4.8G / 64,572 files) plus `vendor`
# (197M). The first-party build authority the spec says to keep is about 23M. Nothing in
# the repository reads either directory: the only references to `buildv2/.local` or
# `buildv2/vendor` anywhere in the tree are two prose mentions in
# docs/handoffs/TOTAL-SYMONEURAL-HISTORY*.md. No code, no recipe, no script.
#
# Full identity, licence and reacquire method for every offloaded collection is recorded in
# docs/reference/BUILDV2-OFFLOAD-RECORD.md, as the buildv2 section requires.
#
# `vendor/checksums/` and `.local/project-native/` are UNROUTED on purpose:
#   * checksums/ (24K) is four .sha256 files naming every offloaded wheel and archive by
#     exact version and hash. It IS the reacquisition authority -- offloading it would
#     destroy the ability to verify what comes back. Keeping 24K to release 4.99G with
#     verification intact is the entire trade.
#   * project-native/ (5.8M) is dependency analysis, inventory and test baselines for the
#     retained native-project. Evidence about a kept thing is kept.

BUILDV2_LOCAL_ROUTES: dict[str, str] = {
    # Apple SDK / Xcode / OSXCross. NOT redistributable under Apple's terms, which is a
    # further reason it is held as a private archive and reacquired from Apple rather than
    # treated as project material.
    "apple":   "Development-Reference/Apple/OSXCross-and-SDK/buildv2-20260909",
    "jvm":     "Development-Reference/Toolchains/JVM/buildv2-20260909",
    "ai-sdk":  "Development-Reference/AI-Research/buildv2-ai-sdk-20260909",
    "cuda":    "Development-Reference/NVIDIA-CUDA/buildv2-cuda-20260909",
    # `project-native` deliberately absent -- see above.
}

BUILDV2_VENDOR_ROUTES: dict[str, str] = {
    "jvm":     "Development-Reference/Toolchains/JVM/buildv2-vendor-20260909",
    "python":  "Development-Reference/SDKs/buildv2-vendor-python-20260909",
    "rust":    "Development-Reference/Toolchains/buildv2-vendor-20260909",
    "go":      "Development-Reference/Toolchains/buildv2-vendor-20260909",
    # `checksums` deliberately absent -- it is the reacquisition authority.
}

OPERATIONS.extend([
    dict(id="mv-buildv2-local", kind="move_leaves", src="archive/buildv2/.local",
         routes=BUILDV2_LOCAL_ROUTES,
         why="4.8G of reacquirable third-party build inputs -- Apple SDK/Xcode/OSXCross "
             "(4.4G), JVM (151M), AI SDK wheels (289M), CUDA (1.1M). Identity, licence "
             "and reacquire method recorded in docs/reference/BUILDV2-OFFLOAD-RECORD.md. "
             "project-native (5.8M) stays: it is evidence about the retained "
             "native-project.",
         evidence="docs/reference/BUILDV2-OFFLOAD-RECORD.md"),
    dict(id="mv-buildv2-vendor", kind="move_leaves", src="archive/buildv2/vendor",
         routes=BUILDV2_VENDOR_ROUTES,
         why="197M of vendored third-party source: gradle-9.5.1-bin.zip (134M, sha256 "
             "bafc141b619ad6350fd975fc903156dd5c151998cc8b058e8c1044ab5f7b031f) and "
             "Python wheels for antigravity/openai/anthropic (63M), every one already "
             "recorded by version and hash in vendor/checksums/. checksums/ itself STAYS.",
         evidence="docs/reference/BUILDV2-OFFLOAD-RECORD.md"),
])



# =========================================================================================
# section 9 -- /home/google minimalisation
# =========================================================================================
#
# Routes are DERIVED from the directory listing rather than retyped, because these
# filenames include spaces, an em dash ("Live stack - SyMoNeuRaL.html" uses U+2014) and
# mixed case. A hand-typed table would silently miss an entry whose name it got wrong, and
# a missed entry looks identical to a deliberate exclusion.

#: Held back deliberately. Two different reasons, and both matter:
#:  * The storage prompts and the helper toolkit are the instructions being executed RIGHT
#:    NOW. Relocating them mid-run would move the work order off the desk mid-job.
#:  * `claudesetup` / `claudeworktocheck.txt` are Claude control material, and section 9.6
#:    says keep those "until the post-exit finalizer no longer requires them. Do not move
#:    early merely for cosmetic cleanup."
HOME_KEEP = {
    "fullprompt.md",
    "CODER_STORAGE_CONTINUE_SIMPLIFIED.md",
    "SYMONEURAL_TOTAL_STORAGE_REORGANIZATION_FROM_ACTUAL_TREES.md",
    "symoneural-storage-helper-toolkit",
    "symoneural-storage-helper-toolkit.tar.gz",
    "symoneural-storage-helper-toolkit.tar.gz.sha256",
    ".directory",
    "claudesetup",
    "claudeworktocheck.txt",
}

_AUDIT = "Symoneural/History/Storage-Audit/2026-09-09"
_TASKS = "Symoneural/History/Task-and-Terminal-History/desktop-20260909"
_UTIL = "Projects/Utilities/desktop-scripts"
_APPLE = "Development-Reference/Apple/sdk-audit-20260909"


def _classify_desktop(name: str) -> str | None:
    """Route one Desktop entry, or None to leave it alone."""
    if name in HOME_KEEP:
        return None
    n = name.lower()
    if n.startswith("trees") or n == "fakedesktop" or n.startswith("run-these-commands"):
        return _AUDIT
    if "apple" in n or "darwinsdk" in n:
        return _APPLE
    if n.startswith("antigravity-sdk"):
        return "Development-Reference/AI-Research/antigravity-sdk-python"
    if n.endswith((".py", ".sh")) or "shortcuts" in n or "htop" in n:
        return _UTIL
    if n.startswith(("garrett_testing", "massivetaskflow")):
        return _TASKS
    if n.endswith((".md", ".txt")):
        return _TASKS
    return "Symoneural/History/Home-Archive/desktop-20260909"


def _classify_documents(name: str) -> str | None:
    if name in HOME_KEEP:
        return None
    n = name.lower()
    if n.startswith("garrettpersonal"):
        return "Personal/Documents/GarrettPersonalNoProject"
    if n == "codex":
        return "Symoneural/History/Agent-Sessions/Codex"
    if "nsight" in n or "nvidia" in n:
        return "Development-Reference/NVIDIA-CUDA/Nsight-Compute"
    if n.endswith(".py"):
        return "Projects/Utilities/document-agents"
    if n.endswith((".html", ".tar.gz")):
        return "Symoneural/History/Screenshots-and-UI-History/documents-20260909"
    if n.endswith((".docx", ".pdf")) or "console-extraction" in n or n == "webscrape.md":
        return "Symoneural/Documentation/Historical/documents-20260909"
    if n.startswith("aipurge") or "reboot" in n:
        return "Symoneural/History/Task-and-Terminal-History/documents-20260909"
    if n == "references.txt":
        return "Symoneural/Reference/documents-references"
    if n.startswith(("slice3", "symoneural-vllm")):
        return "Symoneural/History/Build-History/documents-20260909"
    return "Symoneural/Documentation/Historical/documents-20260909"


def _home_routes(base: str, fn) -> dict[str, str]:
    d = pathlib.Path(base)
    if not d.is_dir():
        return {}
    out = {}
    for q in sorted(d.iterdir()):
        r = fn(q.name)
        if r:
            out[q.name] = r
    return out


OPERATIONS.extend([
    dict(id="mv-home-desktop", kind="move_leaves", src="/home/google/Desktop",
         routes=_home_routes("/home/google/Desktop", _classify_desktop),
         why="Section 9.1: classify Desktop into Drive and 'leave Desktop only with "
             "genuinely current convenience files'. The storage prompts and the helper "
             "toolkit are UNROUTED because they are the instructions currently being "
             "executed, and claudesetup/claudeworktocheck.txt because section 9.6 holds "
             "Claude control material until the post-exit finalizer is done."),
    dict(id="mv-home-documents", kind="move_leaves", src="/home/google/Documents",
         routes=_home_routes("/home/google/Documents", _classify_documents),
         why="Section 9.2: project docs to Drive categories, personal documents to "
             "Personal/Documents. credential_setup.py was ALREADY removed from this tree "
             "separately: it was mode 664, and it now sits at 0600 under "
             ".private/secrets/ with rotation flagged, because section 3.8 requires "
             "credential material move by path only and treats past exposure as needing "
             "remediation rather than tidying."),
    dict(id="mv-home-pictures", kind="move_out", src="/home/google/Pictures",
         dest="Media/Images/Screenshots",
         why="Section 9.5: screenshots worth retaining."),
    dict(id="drop-home-deleteme", kind="drop", src="/home/google/deleteme",
         why="The owner created /home/google/deleteme as a drop box for verified-retired "
             "material. MEASURED: 0 entries -- everything routed through it has already "
             "been retired after verification, so the empty container goes too."),
])

# NOTE on /home/google/go (1.6G): section 9.4 says decide, and the decision is KEEP.
# MEASURED: it contains only `pkg` (with pkg/mod present), NO `go/src`, and an empty
# `go/bin` -- a pure Go module cache with no unique source in it. Section 9.4: "If pure
# cache, do not upload it just to make Home look clean; either keep because Go expects it
# and disk pressure is acceptable, or remove as regenerable after verifying build
# lockfiles". /home is at 31% with 616G free, so there is no disk pressure, and the Go
# toolchain expects the cache where it is. Uploading a cache is explicitly forbidden;
# deleting it would cost a 1.6G re-download against a 5 MB/s link for no benefit.



# =========================================================================================
# sections 3.1 / 3.2 / 3.9 -- the Drive buckets that must not survive, and the loose root
# =========================================================================================
#
# MEASURED at the Drive root: 260 entries -- 14 directories and 246 loose files totalling
# only 0.25 GiB. The size is not the problem; the count is. Four directories are still
# non-canonical, and one of them is enormous:
#
#   Projects_Organize   247.7 GiB across 234 children (200 .zip, 26 .gz, 2 .pkg, 1 .tar)
#   offload             105 MiB across 2 subdirectories (a SECOND, larger `offload` lives
#                       inside Symoneural/ and is handled separately)
#   DONOTDELETE         137 KiB, 2 children
#   Blockchain Proofs of Concept -- see the note on the twin, below
#
# Projects_Organize is full of duplicate-upload families: SyMoNeuRaL_Windows_Bootstrap has
# fifteen variants (" 2".." 7" and " (1)"), symoneural_frontend eight, caddy_scaffold
# eight, Source_PROD_20260102-* thirteen timestamps. Those are NOT resolved here on
# purpose. Section 4 runs dedupe AFTER organization, by exact size + Drive MD5, and a
# name-based guess about which of fifteen near-identical archives is redundant is precisely
# the guess that deletes the wrong one. Organise first, then let the hashes decide.

_PO_SRC = "Symoneural/History/Source-Snapshots/projects-organize-20260909"
_PO_BUILD = "Symoneural/History/Build-History/projects-organize-20260909"
_PO_PROJ = "Projects/Archived/projects-organize-20260909"
_PO_NV = "Development-Reference/NVIDIA-CUDA/projects-organize"
_PO_AI = "Development-Reference/AI-Research/projects-organize"
_PO_DATA = "Development-Reference/Datasets/wordlists-and-tries"


def _classify_projects_organize(name: str, is_dir: bool) -> str | None:
    """Route one Projects_Organize child by what it is, not by where it happened to land."""
    n = name.lower()

    # Whole-machine backups. Large, unique, and not project material.
    if n in ("energencybackup.zip", "backupvault.tar.gz", "windowsbackup.zip"):
        return "Historical-Archive/Machine-Backups"

    # Directories, each already semantically named.
    if is_dir:
        if "oecore" in n or "yoctoextract" in n:
            return "Build-Outputs/Yocto/Historical/projects-organize"
        if "emscripten" in n:
            return "Build-Outputs/projects-organize-emscripten"
        if "nsight" in n or "nvidia" in n:
            return _PO_NV
        return _PO_PROJ

    # Gaming settings. Personal, and unmistakably not SyMoNeuRaL.
    if n.startswith("bo7_") or n.startswith("cod_"):
        return "Personal/Gaming-Settings"

    # Language wordlists, tries and pickled generators -- reference datasets.
    if n.endswith((".txt.gz", ".trie.gz", ".pkl.gz")):
        return _PO_DATA

    # IDE and tool installers, all version-pinned in their filenames.
    if n.startswith(("pycharm-", "phpstorm-", "ripgrep-")) or "vcpkgheaders" in n:
        return "Development-Reference/Toolchains/IDEs-and-Tools"

    # NVIDIA reference packages.
    if "nvidia" in n or "dlss" in n or "gpustatus" in n:
        return _PO_NV

    # Third-party upstream projects, distinguishable by the -main/-master suffix GitHub
    # zipballs carry.
    if n.endswith(("-main.zip", "-master.zip")) or n.startswith("datasketches-"):
        return _PO_AI

    # IPTV / TV.
    if "iptv" in n or "tivimate" in n or "_tv_" in n:
        return "Projects/Archived/IPTV-and-TV"

    # Host and OS setup material.
    if "plasma setup" in n or "image sd c" in n or "universal_os_hardware" in n:
        return "Development-Reference/Linux-System/Host-Setup"
    if n.startswith("tl-sg"):
        return "Development-Reference/Networking"

    # SyMoNeuRaL deploy / bootstrap / scaffold / fix tooling -- build history, not source.
    if any(t in n for t in ("bootstrap", "scaffold", "deploy_helper", "docker_bundle",
                            "clean_fix", "bb_fix", "motd", "busybox", "tinyinit",
                            "oepkdiff", "gemmadisable", "gdrive-to-aistore",
                            "claudeupdate")):
        return _PO_BUILD

    # Audit sweeps, dated.
    if n.startswith("audit_files_"):
        return "Symoneural/History/Storage-Audit/projects-organize-20260102"

    # Everything else SyMoNeuRaL-named is a source or app snapshot.
    if n.startswith(("symoneural", "symon", "symoneral", "allsymonapps", "apps-symon",
                     "source_prod", "source_removed", "apirev", "multiservice")):
        return _PO_SRC

    # Named, non-SyMoNeuRaL, unclassified-by-pattern: archived project material rather
    # than a new dumping ground.
    return _PO_PROJ


def _classify_drive_root_file(name: str, is_dir: bool) -> str | None:
    """Route one loose Drive-root object. 246 of these, 0.25 GiB total."""
    if is_dir:
        return None                     # directories are handled by their own operations
    n = name.lower()
    ext = pathlib.PurePath(n).suffix

    # Canonical catalogue files belong at the root and must never be moved.
    if name in ("INDEX.md", "CATALOG.tsv", "MIGRATION-MAP.tsv", "DUPLICATES.tsv"):
        return None

    # Icons and vector brand assets.
    if ext == ".svg":
        return "Symoneural/Brand-Assets/loose-root-20260909"

    # Images. Section 3.7: SyMoNeuRaL UI/history screenshots are distinguished from
    # everything else, which goes to a loose-imports collection.
    if ext in (".png", ".heic", ".jpg", ".jpeg", ".gif", ".webp"):
        if any(t in n for t in ("symoneural", "symon", "livestack", "screenshot_2026",
                                "ui", "terminal", "progress")):
            return "Symoneural/History/Screenshots-and-UI-History/loose-root-20260909"
        return "Media/Images/Loose-Imports"

    # Web captures and search-result saves are reference, not history.
    if ext in (".mhtml", ".html"):
        return "Development-Reference/AI-Research/web-captures-20260909"

    # Office documents. Personal unless SyMoNeuRaL-named.
    if ext in (".docx", ".odt", ".doc", ".pdf"):
        if "symoneural" in n or "symon" in n:
            return "Symoneural/Documentation/Historical/loose-root-20260909"
        return "Personal/Documents/loose-root-20260909"

    # Release packages.
    if ext in (".deb", ".rpm", ".pkg", ".appimage"):
        return "Symoneural/Release-Artifacts/loose-root-20260909"

    # Archives: recovery sets are restore material, the rest are source snapshots.
    if ext in (".zip", ".gz", ".tgz", ".xz", ".zst", ".tar", ".7z"):
        if any(t in n for t in ("recover", "backup", "restore")):
            return "Symoneural/Restore-Recovery/loose-root-20260909"
        return "Symoneural/History/Source-Snapshots/loose-root-20260909"

    # Logs and diffs are evidence.
    if ext in (".log", ".diff", ".patch"):
        return "Symoneural/History/Task-and-Terminal-History/loose-root-20260909"

    if ext in (".py", ".js", ".sh"):
        return "Projects/Utilities/loose-root-20260909"

    # Prompts, notes and histories.
    if ext in (".md", ".txt"):
        return "Symoneural/History/Task-and-Terminal-History/loose-root-20260909"

    # Section 3.9's genuinely ambiguous singletons -- File_000, ensureithappens, laststeps,
    # response, clauderesumehere and friends. They must not remain at root, and the spec
    # names the destination for exactly this case: a CATALOGUED reviewed collection, not an
    # eternal root singleton and not a bucket called misc.
    return "Historical-Archive/Unclassified-Reviewed/2026-09-09"


OPERATIONS.extend([
    dict(id="drive-projects-organize", kind="drive_children", src="Projects_Organize",
         classify=_classify_projects_organize,
         why="Section 3.1: 'Projects_Organize is not allowed to survive as a final "
             "bucket.' MEASURED 247.7 GiB across 234 children. Distributed server-side by "
             "type -- whole-machine backups, SyMoNeuRaL source snapshots, build/deploy "
             "tooling, NVIDIA reference, IDE installers, wordlist datasets, gaming "
             "settings, IPTV, Yocto output. Its duplicate-upload families are left for "
             "section 4's MD5 dedupe: guessing which of fifteen near-identical archives "
             "is redundant from its name is how the wrong one gets deleted."),
    dict(id="drive-root-offload", kind="drive_children", src="offload",
         classify=lambda n, d: ("Symoneural/History/Home-Archive/offload-downloads"
                                if n.lower() == "downloads" else
                                "Symoneural/Reference/offload-references"),
         why="Section 3.2: 'offload must not remain a final category.' The ROOT offload is "
             "105 MiB in two subdirectories, Downloads and references. A second, larger "
             "offload lives inside Symoneural/ and is handled by its own operation."),
    dict(id="drive-donotdelete", kind="drive_children", src="DONOTDELETE",
         classify=lambda n, d: "Symoneural/Restore-Recovery/DONOTDELETE-contents",
         why="Section 3.2: 'DONOTDELETE must be opened/inventoried. Preserve any genuinely "
             "required recovery material under Symoneural/Restore-Recovery; do not retain "
             "a folder whose only semantics are an imperative name.' MEASURED: 137 KiB, "
             "two children -- SyMoNeuRaL_Runtime_Engineering_Guide.zip and a NeverDelete "
             "directory. The content is preserved; the imperative name is not."),
    dict(id="drive-blockchain-twin", kind="drive_children",
         src="Blockchain Proofs of Concept",
         classify=lambda n, d: "Projects/Crypto/Research/Blockchain-Proofs-of-Concept",
         why="Google Drive permits two folders with the SAME NAME at one path, and there "
             "were two of these. The first moved and its operation is recorded COMPLETE "
             "with 8 objects verified -- yet 7 objects still sit at the root under that "
             "name, which is the twin. A top-level rename could not see it; distributing "
             "children merges it into the same destination."),
    dict(id="drive-root-loose", kind="drive_children", src="",
         classify=_classify_drive_root_file,
         why="Section 3.9: 246 loose root objects, 0.25 GiB. The count is the problem, not "
             "the size. Routed by type; the genuinely ambiguous singletons the spec names "
             "(File_000, ensureithappens, laststeps, response) go to a CATALOGUED "
             "Historical-Archive/Unclassified-Reviewed/2026-09-09 rather than staying at "
             "root forever or landing in a bucket called misc. Directories are skipped "
             "here -- each has its own operation."),
])



# =========================================================================================
# section 3.2 -- the SECOND, larger `offload` bucket, inside Symoneural/
# =========================================================================================
#
# MEASURED: 75.5 GiB across three subdirectories -- archive/, external/ and yocto/. This is
# where the retired shell pipelines deposited everything, and section 3.2 is explicit:
# "offload must not remain a final category. Its contents must be merged into their real
# destinations."
#
# The external/ subtree holds 13 per-collection tarballs, and one of them matters for
# section 4: external_referencestochatgpt.tar.gz.tar (12.83 GiB) is named there as "a
# TEMPORARY migration safety container, not automatically permanent authority", to be
# deleted once the organised collections prove equivalent coverage. It is MOVED here rather
# than deleted, because that coverage proof depends on external/referencestochatgpt being
# fully filed under Symoneural/Upstream-Source first -- which has not happened yet.
# Deleting a safety container before the thing it is a safety net for exists is the whole
# mistake it guards against.

def _classify_offload_external(name: str, is_dir: bool) -> str:
    n = name.lower()
    if "comfyui" in n:
        return "Development-Reference/AI-Research/ComfyUI-archives"
    if "tensorrt" in n:
        return "Development-Reference/NVIDIA-CUDA/offload-archives"
    if "openai" in n or "anthropic" in n:
        return "Development-Reference/AI-Research/offload-archives"
    if "projects_crypto" in n:
        return "Projects/Crypto/offload-archives"
    if "iptv" in n:
        return "Projects/Archived/IPTV-and-TV"
    return "Symoneural/Reference/offload-external-20260909"


OPERATIONS.extend([
    dict(id="drive-symoneural-offload-external", kind="drive_children",
         src="Symoneural/offload/external",
         classify=_classify_offload_external,
         why="Section 3.2: offload is not a final category. 13 per-collection tarballs "
             "routed by domain. external_referencestochatgpt.tar.gz.tar is moved, not "
             "deleted: section 4 only permits removing that migration container once the "
             "organised Upstream-Source collections prove equivalent coverage, and they do "
             "not exist yet."),
    dict(id="drive-symoneural-offload-archive", kind="drive_children",
         src="Symoneural/offload/archive",
         classify=lambda n, d: "Symoneural/History/Build-History/offload-archive-20260909",
         why="Section 3.2: the archive/ leg of the offload bucket -- historical build "
             "material, filed under Build-History where the rest of it already lives."),
    dict(id="drive-symoneural-offload-yocto", kind="drive_children",
         src="Symoneural/offload/yocto",
         classify=lambda n, d: "Build-Outputs/Yocto/Historical/offload-20260909",
         why="Section 3.2/6.2: the yocto leg of the offload bucket -- completed build "
             "output, filed under Build-Outputs/Yocto/Historical."),
])



OPERATIONS.append(dict(
    id="backfill-sendtodrive-manifests", kind="backfill_zip_manifests",
    zip="/yocto/Archives/sendtodrive.zip", member_prefix="sendtodrive/",
    ledger_prefix="mv-yocto-sendtodrive::",
    why="The manifest rule requires content identity -- TYPE, RELPATH, SIZE_BYTES, SHA256, "
        "MODE, LINK_TARGET -- and forbids returning to path+size-only manifests. 21 "
        "sendtodrive collections were uploaded by an orchestrator process that started at "
        "05:50:13, before that code landed, so their manifests are RELPATH+SIZE_BYTES "
        "only. Their local sources are retired, but every file was MEASURED present in "
        "sendtodrive.zip, which is still on disk precisely because the coverage gate "
        "refuses to retire it early. Only manifests are re-uploaded; the archives are "
        "untouched, and the superseded size-only manifest is removed so two manifests "
        "cannot disagree."))



OPERATIONS.append(dict(
    id="preserve-backend-vendor", kind="move_out", src="archive/vendor-sdks",
    keep_source=True, dest="Symoneural/Reference/backend-vendor-20260909",
    why="PRESERVED, NOT RETIRED, and the reversal is deliberate. The re-run probes still "
        "show RUNTIME_REQUIRED_LOCAL=0 and UNKNOWN=0, but the instruction to retire was "
        "conditional on this being DEAD reference source and it is not: "
        "backend/test_vendor_sdks.py (9 passing tests) is a licence-compliance "
        "control that re-derives each tree's licence verdict by reading the licence text "
        "out of the vendored copy ON DISK and comparing it to PROVENANCE.md, because a "
        "test that only read the manifest would be asking the tool to confirm its own "
        "homework. Two more tests walk the tree. Deleting it reclaims 131M -- 0.04% of "
        "what this reorganisation moves -- and costs the on-disk half of a control the "
        "owner asked to exist in git. So the bytes go to Drive and the tree stays. See "
        "docs/reference/VENDOR-CLASSIFICATION.md.",
    evidence="docs/reference/VENDOR-CLASSIFICATION.md"))



OPERATIONS.extend([
    dict(id="drop-partial-applesdk", kind="drop", src="/yocto/sendtodrive/AppleSDK",
         why="RETIRED ONLY NOW THAT THE PROOF EXISTS, which is the order the instruction "
             "requires: retire the partial copy after the complete collection's "
             "destination verifies. The complete AppleSDK -- 137,971 files, 47,409,731,694 "
             "bytes raw -- is on Drive at Development-Reference/Apple/SDKs/"
             "AppleSDK-20260820/AppleSDK.tar.zst with local md5 == remote md5 == "
             "a3d29e6ceeff29d1e6f7684f3316231e, verified 2026-09-09T08:05:25. This local "
             "copy is a STRICT SUBSET of it: 132,656 files, every one CRC32-matched to the "
             "same zip the complete version was extracted from. Nothing unique is lost, "
             "and it is not uploaded again because a superset of it already verified."),
    dict(id="publish-artifact-manifests", kind="publish_manifests",
         **{"from": ".private/storage-reorg/contents"},
         ledger_prefix="mv-yocto-artifacts::",
         why="Publish the SHA256 content manifests captured locally before the artifact "
             "sources were retired. The uploading process predates the content-manifest "
             "code and writes size-only manifests, and killing it to load newer code is "
             "forbidden and would cost the transfer. Capturing locally -- reading only, no "
             "Drive mutation, no second owner -- preserved TYPE/RELPATH/SIZE_BYTES/SHA256/"
             "MODE/LINK_TARGET for all 105,851 files including 53,585 symlinks recorded by "
             "target rather than followed. Runs repeatedly: a leaf whose archive has not "
             "uploaded yet is PENDING, not failed."),
])



# =========================================================================================
# gaps closed after a line-by-line re-audit of the owner's prompt
# =========================================================================================

OPERATIONS.extend([
    # "Claude-related material MAY be copied and verified on Drive now, but respect the
    # active-session local-retirement hold." So: copy and verify, keep local. The report
    # then has a real VERIFIED_GDRIVE_COPY_BYTES instead of an assertion, and the held
    # bytes are reported separately from unexplained duplicates.
    dict(id="copy-claude-anthropics", kind="move_out", src="external/anthropics",
         keep_source=True, dest="Symoneural/Reference/claude-hold-20260909",
         why="The prompt permits copying and verifying Claude-related material on Drive "
             "now while the local retirement stays held. This is the 5.4G of it. Copied "
             "and verified; the local copy is KEPT because the hard-stop rule and section "
             "9.6 both retain it until the post-exit finalizer no longer needs it."),
    dict(id="copy-claude-alienware", kind="move_out", src="external/ClaudeAlienware",
         keep_source=True, dest="Symoneural/History/Agent-Sessions/ClaudeAlienware-local",
         why="Same hold, same treatment: verified Drive copy, local copy retained."),
    dict(id="copy-claude-small", kind="move_out", src="external/Claude",
         keep_source=True, dest="Symoneural/Reference/claude-hold-20260909",
         why="Same hold, same treatment."),
    dict(id="copy-claude-desktop-deb", kind="move_out",
         src="external/claude-desktop_1.32885.1_amd64.deb", keep_source=True,
         dest="Symoneural/Reference/claude-hold-20260909",
         why="Same hold, same treatment. An installer package, version-pinned in its "
             "filename."),

    # /yocto's last unclassified entries. YOCTO_UNKNOWN_BYTES=0 requires every entry to be
    # explained, and a filesystem trash directory is not build material.
    dict(id="drop-yocto-trash", kind="drop", src="/yocto/.Trash-1000",
         why="A desktop trash directory on the build volume. Not build material and not "
             "evidence of anything -- anything genuinely needed would not have been "
             "deleted into it. Required for YOCTO_UNKNOWN_BYTES=0."),
    dict(id="drop-yocto-deleteme", kind="drop", src="/yocto/deleteme",
         why="The owner's drop box for verified-retired material. Everything routed "
             "through it has already been retired after verification, so the empty "
             "container goes too."),

    # Coverage proof, then retirement. LAST, because it depends on every other
    # sendtodrive/AppleSDK operation having verified first.
    dict(id="prove-and-retire-sendtodrive-zip", kind="zip_coverage",
         zip="/yocto/Archives/sendtodrive.zip", member_prefix="sendtodrive/",
         ledger_prefixes=("mv-yocto-sendtodrive::", "backfill-sendtodrive-manifests::"),
         applesdk_op="mv-applesdk-from-zip",
         why="Steps 6-8 of the sendtodrive plan, in the order given: prove every useful "
             "ZIP collection has canonical coverage, retire the ZIP only when "
             "ZIP_UNIQUE_UNMAPPED_BYTES=0, then remove the emptied Archives container. "
             "This zip has earned that caution twice -- it held the only COMPLETE "
             "AppleSDK after the disk copy lost 38,310 files, and it was the only source "
             "able to rebuild SHA256 manifests for 21 collections whose local sources had "
             "already retired. Every covered destination is RE-VERIFIED on the remote "
             "before the ledger is trusted."),
])


# =========================================================================================
# State
# =========================================================================================
def load_state() -> dict:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    os.chmod(STATE_DIR, 0o700)
    VERIFY_DIR.mkdir(parents=True, exist_ok=True)
    os.chmod(VERIFY_DIR, 0o700)
    if STATE.is_file():
        try:
            return json.loads(STATE.read_text())
        except json.JSONDecodeError:
            # A truncated state file is recoverable only by refusing to trust it: better to
            # re-plan than to resume from half a JSON document.
            print("  state.json unreadable; re-planning (completed work is re-verified, "
                  "not replayed)")
    return {"ops": {}}


def save_state(st: dict) -> None:
    # Do not assume load_state() ran first. `record()` is called from two threads and from
    # tests, and a writer that depends on call order to have its directory is a writer that
    # will one day lose a checkpoint.
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    VERIFY_DIR.mkdir(parents=True, exist_ok=True)
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(st, indent=2, sort_keys=True) + "\n")
    os.chmod(tmp, 0o600)
    tmp.replace(STATE)          # atomic: a crash leaves the old state, never a partial one


#: Phase 2 (Drive API walks) and phase 3 (uploads) run concurrently, so every state write
#: is serialised. The ledger is the only shared mutable thing between them.
_STATE_LOCK = threading.Lock()


def record(st: dict, op_id: str, **kw) -> None:
    with _STATE_LOCK:
        _record_locked(st, op_id, **kw)


def _record_locked(st: dict, op_id: str, **kw) -> None:
    st["ops"].setdefault(op_id, {})
    st["ops"][op_id].update(kw)
    st["ops"][op_id]["updated"] = time.strftime("%Y-%m-%dT%H:%M:%S%z")
    save_state(st)
    hdr = not OPS.exists()
    with OPS.open("a") as fh:
        if hdr:
            fh.write("WHEN\tOP_ID\tSTATE\tDETAIL\n")
        fh.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')}\t{op_id}\t"
                 f"{kw.get('state','?')}\t{str(kw.get('detail',''))[:200]}\n")
    os.chmod(OPS, 0o600)


def state_of(st: dict, op_id: str) -> str:
    return st["ops"].get(op_id, {}).get("state", "PLANNED")


def take_lock() -> bool:
    """One owner. A stale lock from a dead pid is reclaimed; a live one is respected."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    if LOCK.is_file():
        try:
            pid = int(LOCK.read_text().strip())
            os.kill(pid, 0)
            print(f"  another storage_reorg owner is live (pid {pid}); refusing to be a "
                  f"second. ACTIVE_STORAGE_MUTATION_OWNERS must stay 1.")
            return False
        except (ValueError, ProcessLookupError, PermissionError):
            print("  reclaiming a stale lock from a dead pid")
    LOCK.write_text(str(os.getpid()))
    os.chmod(LOCK, 0o600)
    return True


# =========================================================================================
# Helpers
# =========================================================================================
def sh(args: list[str], timeout: int = 43200) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout)


def md5_of(p: pathlib.Path) -> str:
    h = hashlib.md5()
    with p.open("rb") as fh:
        for c in iter(lambda: fh.read(1 << 22), b""):
            h.update(c)
    return h.hexdigest()


def remote_md5(remote_path: str) -> str | None:
    r = sh(["rclone", "hashsum", "md5", f"{REMOTE}{remote_path}"], timeout=1800)
    if r.returncode != 0 or not r.stdout.strip():
        return None
    return r.stdout.split()[0]


def local_path(src: str) -> pathlib.Path:
    return pathlib.Path(src) if src.startswith("/") else ROOT / src


def du_bytes(p: pathlib.Path) -> int:
    r = sh(["du", "-sb", str(p)], timeout=3600)
    try:
        return int(r.stdout.split()[0])
    except (IndexError, ValueError):
        return 0


def human(n: float) -> str:
    for u in ("B", "K", "M", "G", "T"):
        if n < 1024 or u == "T":
            return f"{n:.0f}{u}" if u == "B" else f"{n:.1f}{u}"
        n /= 1024
    return str(n)


def write_manifest(src: pathlib.Path, out: pathlib.Path) -> tuple[int, int]:
    """Write a CONTENT manifest for `src` via tools/sym_content_manifest.py.

    Columns are TYPE, RELPATH, SIZE_BYTES, SHA256, MODE, LINK_TARGET, and symlinks are
    recorded by their target rather than dereferenced. Returns (file_count, total_bytes).

    This replaces an earlier path+size-only manifest. Size is not content identity: two
    files of equal length are routinely different, so a size-only manifest cannot support
    section 4's dedupe or prove that an archived collection is what it claims to be. The
    SHA256 pass costs one sequential read of the leaf, which on NVMe is cheap next to the
    upload it precedes.
    """
    helper = ROOT / "tools" / "sym_content_manifest.py"
    if helper.is_file():
        r = sh(["python3", str(helper), "make", str(src), str(out)], timeout=43200)
        if r.returncode == 0:
            n = tot = 0
            try:
                with out.open() as fh:
                    next(fh, None)
                    for line in fh:
                        f = line.rstrip("\n").split("\t")
                        if len(f) >= 3 and f[0] == "FILE":
                            n += 1
                            tot += int(f[2] or 0)
            except OSError:
                pass
            os.chmod(out, 0o600)
            return n, tot
        print(f"      content manifest helper failed rc={r.returncode}: "
              f"{r.stderr.strip()[:160]}")
        # Fall through: a missing manifest must not silently become a missing check.
        raise RuntimeError(f"content manifest failed for {src}")
    raise RuntimeError(f"tools/sym_content_manifest.py absent; refusing a size-only manifest")


# =========================================================================================
# The single destructive primitive
# =========================================================================================
def _artifact_names(src: pathlib.Path) -> tuple[str, bool, bool]:
    """(artifact filename, compress?, upload-in-place?) for a leaf. Pure, so resume derives
    exactly the same names the original attempt used."""
    single = src.is_file()
    compress = not src.name.endswith(NO_COMPRESS)
    if single and not compress:
        return src.name, False, True
    return f"{src.name}.tar" + (".zst" if compress else ""), compress, False


def _retire_source(op_id: str, src: pathlib.Path, raw: int, st: dict) -> bool:
    """The only destructive step. Never called before DEST_VERIFIED."""
    if src.is_dir():
        shutil.rmtree(src, ignore_errors=True)
    else:
        src.unlink(missing_ok=True)
    if src.exists():
        record(st, op_id, state="FAILED", detail="source still present after retire")
        print(f"      {op_id}: source would not retire")
        return False
    record(st, op_id, state="SOURCE_RETIRED", detail=f"retired {human(raw)}")
    record(st, op_id, state="COMPLETE", detail=f"retired {human(raw)}", raw_bytes=raw)
    print(f"      {op_id}: COMPLETE -- freed {human(raw)}")
    return True


def _pack_upload_retire(op_id: str, src: pathlib.Path, dest_dir: str, why: str, st: dict,
                        retire: bool = True) -> bool:
    """Pack, upload, confirm from the remote, and only then retire.

    Resume enters at whichever state the ledger records, and never redoes verified work:

      COMPLETE        -> return immediately; a completed transfer is never replayed
      FAILED          -> fail closed; no silent destructive retry
      SOURCE_RETIRED  -> re-confirm the destination, then close out as COMPLETE
      DEST_VERIFIED   -> re-read the remote hash; if it still matches, retire the source
                         directly with NO repack and NO re-upload
      UPLOADING       -> ask the remote whether it already holds the recorded MD5; if so
                         promote to DEST_VERIFIED instead of sending the bytes again
      PACKING         -> reuse a staged artifact whose MD5 matches the recorded one

    Each of those is a real interruption this work has hit, and each one re-sending
    gigabytes over a 5 MB/s link is the cost of getting it wrong.
    """
    rec = st["ops"].get(op_id, {})
    cur = rec.get("state", "PLANNED")
    rec_md5 = rec.get("local_md5")
    raw = rec.get("raw_bytes") or 0

    if cur == "COMPLETE":
        print(f"      {op_id}: COMPLETE already -- not replayed")
        return True

    if cur == "FAILED":
        # Fail closed. A previous attempt failed for a reason nobody has looked at yet, and
        # retrying destructively is how a bad diagnosis becomes data loss.
        print(f"      {op_id}: previously FAILED ({str(rec.get('detail'))[:90]}) -- "
              f"failing closed, source untouched")
        return False

    dest = rec.get("dest")

    if cur == "SOURCE_RETIRED":
        rm = remote_md5(dest) if dest else None
        if rm and rm == rec.get("remote_md5"):
            record(st, op_id, state="COMPLETE", detail="destination re-confirmed on resume")
            print(f"      {op_id}: source already retired, destination re-confirmed -> COMPLETE")
            return True
        record(st, op_id, state="FAILED",
               detail=f"source retired but destination no longer verifies (remote={rm})")
        print(f"      {op_id}: SOURCE RETIRED BUT DESTINATION LOST -- needs owner attention")
        return False

    if cur == "DEST_VERIFIED" and dest:
        rm = remote_md5(dest)
        if rm and rm == rec.get("remote_md5"):
            print(f"      {op_id}: DEST_VERIFIED on resume, remote hash still {rm[:12]} "
                  f"-- retiring source without repack or re-upload")
            if not src.exists():
                record(st, op_id, state="COMPLETE", detail="source already absent")
                return True
            if not retire:
                record(st, op_id, state="COMPLETE", detail="uploaded, source kept")
                return True
            return _retire_source(op_id, src, raw or du_bytes(src), st)
        record(st, op_id, state="FAILED",
               detail=f"DEST_VERIFIED but remote hash now {rm} != {rec.get('remote_md5')}")
        print(f"      {op_id}: remote changed since verification -- source untouched")
        return False

    if not src.exists():
        record(st, op_id, state="COMPLETE", detail="source already absent")
        return True

    raw = du_bytes(src)
    STAGE.mkdir(parents=True, exist_ok=True)
    os.chmod(STAGE, 0o700)
    name, compress, in_place = _artifact_names(src)
    art = src if in_place else STAGE / name
    dest = f"{dest_dir}/{name}"
    mani = STAGE / f"{src.name}.CONTENTS.tsv"

    # ---- UPLOADING resume: is the object already complete on the remote? --------------
    if cur == "UPLOADING" and rec_md5:
        rm = remote_md5(dest)
        if rm == rec_md5:
            print(f"      {op_id}: interrupted at UPLOADING, but the remote already holds "
                  f"{rm[:12]} -- promoting to DEST_VERIFIED, not re-uploading")
            record(st, op_id, state="DEST_VERIFIED", detail=f"remote md5 {rm} (resume)",
                   remote_md5=rm)
            if not in_place:
                art.unlink(missing_ok=True)
            if not retire:
                record(st, op_id, state="COMPLETE", detail="uploaded, source kept")
                return True
            return _retire_source(op_id, src, raw, st)
        print(f"      {op_id}: interrupted at UPLOADING; remote holds {rm} not {rec_md5[:12]}"
              f" -- will re-send")

    # ---- PACKING resume: is a valid staged artifact already on disk? ------------------
    reuse = False
    if not in_place and art.is_file() and rec_md5:
        staged = md5_of(art)
        if staged == rec_md5:
            print(f"      {op_id}: reusing staged artifact {name} "
                  f"({human(art.stat().st_size)}, md5 {staged[:12]}) -- not repacking")
            reuse = True
        else:
            print(f"      {op_id}: staged artifact md5 {staged[:12]} != recorded "
                  f"{rec_md5[:12]} -- discarding it and repacking")
            art.unlink(missing_ok=True)

    if not mani.is_file():
        fcount, fbytes = write_manifest(src, mani)
    else:
        fcount = sum(1 for i, l in enumerate(mani.open()) if i and l.startswith("FILE\t"))
        fbytes = 0
    print(f"      {op_id}: {human(raw)}  {fcount} files -> {dest_dir}/")
    record(st, op_id, state="PACKING", detail=f"{raw} raw, {fcount} files",
           src=str(src), dest=dest, file_count=fcount, raw_bytes=raw, why=why)

    if not in_place and not reuse:
        art.unlink(missing_ok=True)
        base, leaf = str(src.parent), src.name
        if compress:
            tar = subprocess.Popen(["tar", "-cf", "-", "-C", base, leaf],
                                   stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
            z = subprocess.run(["zstd", "-3", "-T0", "-q", "-o", str(art)], stdin=tar.stdout)
            tar.stdout.close()
            tar.wait()
            rc = z.returncode or tar.returncode
        else:
            rc = sh(["tar", "-cf", str(art), "-C", base, leaf]).returncode
        if rc != 0 or not art.is_file():
            record(st, op_id, state="FAILED", detail=f"pack rc={rc}")
            print(f"      {op_id}: PACK FAILED -- source untouched")
            return False
        os.chmod(art, 0o600)

    packed = art.stat().st_size
    lm = md5_of(art)
    record(st, op_id, state="UPLOADING", detail=f"{packed} packed",
           local_md5=lm, packed_bytes=packed)

    # Even on a first pass, ask the remote first: an earlier owner may have completed it.
    if remote_md5(dest) == lm:
        print(f"      {op_id}: remote already holds {lm[:12]} -- skipping the upload")
    else:
        print(f"      {op_id}: packed {human(packed)}  md5 {lm[:12]}  uploading ...")
        r = sh(["rclone", "copy", str(art), f"{REMOTE}{dest_dir}/"] + RCLONE)
        if r.returncode != 0:
            record(st, op_id, state="FAILED",
                   detail=f"upload rc={r.returncode}: {r.stderr.strip()[:150]}")
            print(f"      {op_id}: UPLOAD FAILED -- source untouched")
            return False

    # Read the hash back FROM THE REMOTE, never from the FUSE mount.
    rm = remote_md5(dest)
    if rm != lm:
        record(st, op_id, state="FAILED",
               detail=f"remote md5 {rm} != local {lm} -- NOTHING RETIRED")
        print(f"      {op_id}: MD5 MISMATCH (remote={rm} local={lm}) -- source untouched")
        return False

    # The manifest is part of the deliverable, so it is verified too.
    sh(["rclone", "copy", str(mani), f"{REMOTE}{dest_dir}/"] + RCLONE)
    mani_local = md5_of(mani)
    mani_remote = remote_md5(f"{dest_dir}/{mani.name}")
    if mani_remote != mani_local:
        record(st, op_id, state="FAILED",
               detail=f"manifest md5 {mani_remote} != {mani_local} -- NOTHING RETIRED")
        print(f"      {op_id}: MANIFEST VERIFY FAILED -- source untouched")
        return False

    record(st, op_id, state="DEST_VERIFIED", detail=f"remote md5 {rm}", remote_md5=rm,
           manifest_md5=mani_local, manifest_remote=f"{dest_dir}/{mani.name}")
    (VERIFY_DIR / f"{op_id.replace('/', '_').replace(':', '-')}.txt").write_text(
        f"op={op_id}\nsrc={src}\ndest={REMOTE}{dest}\nfile_count={fcount}\n"
        f"manifest={REMOTE}{dest_dir}/{mani.name}\nmanifest_md5={mani_local}\n"
        f"raw_bytes={raw}\npacked_bytes={packed}\nlocal_md5={lm}\nremote_md5={rm}\n"
        f"verified_at={time.strftime('%Y-%m-%dT%H:%M:%S%z')}\nwhy={why}\n")

    if not in_place:
        art.unlink(missing_ok=True)
    mani.unlink(missing_ok=True)

    if not retire:
        record(st, op_id, state="COMPLETE", detail=f"uploaded {human(raw)}, source kept")
        print(f"      {op_id}: COMPLETE (source intentionally kept)")
        return True
    return _retire_source(op_id, src, raw, st)


# =========================================================================================
# Operation kinds
# =========================================================================================
def do_drop(op: dict, st: dict, apply: bool) -> None:
    p = local_path(op["src"])
    if not p.exists():
        if apply:
            record(st, op["id"], state="COMPLETE", detail="already absent")
        else:
            print(f"  {op['id']:<34} already absent")
        return
    guard = op.get("guard")
    if guard and not (ROOT / guard).is_file():
        # The guard is the whole point: without its lockfile the tree is not regenerable,
        # so dropping it would destroy something unrecoverable.
        if apply:
            record(st, op["id"], state="FAILED",
                   detail=f"guard {guard} absent -- not regenerable, refusing to drop")
        print(f"  {op['id']}: GUARD MISSING ({guard}) -- NOT dropped")
        return
    n = du_bytes(p)
    if not apply:
        print(f"  {op['id']:<34} would drop {human(n):>8}  ({op['src']})")
        return
    record(st, op["id"], state="RETIRING", detail=f"{n} bytes", why=op["why"])
    if p.is_dir():
        shutil.rmtree(p, ignore_errors=True)
    else:
        p.unlink(missing_ok=True)
    ok = not p.exists()
    record(st, op["id"], state="COMPLETE" if ok else "FAILED",
           detail=f"dropped {human(n)}" if ok else "still present", raw_bytes=n)
    print(f"  {op['id']}: {'dropped' if ok else 'FAILED'} {human(n)}")


def do_drop_glob(op: dict, st: dict, apply: bool) -> None:
    """__pycache__ everywhere except trees that must not be walked or are themselves
    queued for relocation."""
    skip = ("/external/", "/archive/", "/.private/", "/node_modules/", "/.git/")
    hits = [d for d in ROOT.rglob(op["src"])
            if d.is_dir() and not any(s in f"{d}/" for s in skip)]
    total = sum(du_bytes(d) for d in hits)
    if not apply:
        print(f"  {op['id']:<34} would drop {human(total):>8}  ({len(hits)} trees)")
        return
    for d in hits:
        shutil.rmtree(d, ignore_errors=True)
    left = len([d for d in ROOT.rglob(op["src"])
                if d.is_dir() and not any(s in f"{d}/" for s in skip)])
    record(st, op["id"], state="COMPLETE", raw_bytes=total,
           detail=f"dropped {len(hits)} trees {human(total)}, {left} remain",
           why=op["why"])
    print(f"  {op['id']}: dropped {len(hits)} trees, {human(total)}")


def do_move_out(op: dict, st: dict, apply: bool) -> None:
    src = local_path(op["src"])
    if not apply:
        cur = state_of(st, op["id"])
        if not src.exists():
            print(f"  {op['id']:<34} absent ({cur})")
            return
        print(f"  {op['id']:<34} would move {human(du_bytes(src)):>8} -> {op['dest']}/  "
              f"[{cur}]")
        return
    print(f"  {op['id']}")
    _pack_upload_retire(op["id"], src, op["dest"], op["why"], st,
                        retire=not op.get("keep_source"))


def do_move_leaves(op: dict, st: dict, apply: bool) -> None:
    """One archive per semantic leaf, each routed independently. A failing leaf does not
    block its siblings, and the parent container is removed only when every leaf is gone."""
    src = local_path(op["src"])
    if not src.exists():
        if apply:
            record(st, op["id"], state="COMPLETE", detail="source already absent")
        else:
            print(f"  {op['id']:<34} absent")
        return
    routes: dict[str, str] = op["routes"]
    leaves = sorted(src.iterdir())
    unrouted = [p.name for p in leaves if p.name not in routes]

    if not apply:
        print(f"  {op['id']}  ({len(leaves)} leaves, {human(du_bytes(src))} total)")
        for p in leaves:
            d = routes.get(p.name)
            print(f"        {p.name:<26} {human(du_bytes(p)):>8}  -> "
                  f"{d if d else '*** UNROUTED: stays local ***'}")
        if unrouted:
            print(f"        NOTE {len(unrouted)} unrouted: {', '.join(unrouted)}")
        return

    print(f"  {op['id']}  ({len(leaves)} leaves)")
    for p in leaves:
        d = routes.get(p.name)
        if not d:
            # Never move what the route table does not name. An unrouted leaf is an
            # unclassified one, and section 12 counts unclassified items as incomplete --
            # which is the correct visible outcome, not a silent default bucket.
            print(f"        {p.name}: UNROUTED -- left in place deliberately")
            continue
        _pack_upload_retire(f"{op['id']}::{p.name}", p, d, op["why"], st)

    remaining = [q.name for q in src.iterdir()] if src.exists() else []
    if not remaining:
        src.rmdir()
        record(st, op["id"], state="COMPLETE", detail="all leaves retired, parent removed")
        print(f"  {op['id']}: COMPLETE -- parent container removed")
    else:
        record(st, op["id"], state="PARTIAL",
               detail=f"{len(remaining)} leaves remain: {','.join(remaining[:8])}")
        print(f"  {op['id']}: PARTIAL -- {len(remaining)} leaves remain: "
              f"{', '.join(remaining[:8])}")


def do_extract_upload(op: dict, st: dict, apply: bool) -> None:
    """Take a subtree out of a zip, upload it, and retire only the staged copy.

    Used where the ZIP holds the complete collection and the on-disk copy is lossy. The
    zip itself is NOT retired here: that decision belongs to a separate coverage proof.
    """
    op_id = op["id"]
    zp = pathlib.Path(op["src"])
    prefix = op["member_prefix"]
    if state_of(st, op_id) == "COMPLETE":
        print(f"  {op_id}: already COMPLETE")
        return
    if not zp.is_file():
        if apply:
            record(st, op_id, state="COMPLETE", detail="zip absent")
        else:
            print(f"  {op_id:<34} zip absent")
        return

    with zipfile.ZipFile(zp) as z:
        members = [i for i in z.infolist()
                   if i.filename.startswith(prefix) and not i.is_dir()]
        total = sum(i.file_size for i in members)
    if not apply:
        print(f"  {op_id:<34} would extract {len(members)} members "
              f"({human(total)}) from {zp.name} -> {op['dest']}/")
        return

    print(f"  {op_id}: extracting {len(members)} members ({human(total)}) from {zp.name}")
    work = STAGE / "extract" / prefix.rstrip("/").split("/")[-1]
    if work.exists():
        shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True, exist_ok=True)
    record(st, op_id, state="EXTRACTING", detail=f"{len(members)} members, {total} bytes",
           why=op["why"])
    # zipfile matches member names EXACTLY -- unlike `unzip`, which treats [ ] * in stored
    # paths as glob wildcards and matched nothing at all in these Xcode SDK trees (rc=11).
    with zipfile.ZipFile(zp) as z:
        for i in members:
            rel = i.filename[len(prefix):]
            if not rel:
                continue
            out = work / rel
            out.parent.mkdir(parents=True, exist_ok=True)
            with z.open(i) as fh, out.open("wb") as w:
                shutil.copyfileobj(fh, w, 1 << 20)
    got = sum(1 for p in work.rglob("*") if p.is_file())
    if got != len(members):
        record(st, op_id, state="FAILED",
               detail=f"extracted {got} of {len(members)} members")
        print(f"  {op_id}: EXTRACT INCOMPLETE ({got}/{len(members)}) -- nothing retired")
        return
    print(f"  {op_id}: extracted {got} members cleanly")
    ok = _pack_upload_retire(op_id, work, op["dest"], op["why"], st, retire=True)
    shutil.rmtree(STAGE / "extract", ignore_errors=True)
    if ok:
        print(f"  {op_id}: uploaded; the source zip is deliberately KEPT pending the "
              f"coverage proof")



def do_move_files(op: dict, st: dict, apply: bool) -> None:
    """Move only the files matching `patterns` out of a tree, keeping everything else.

    Needed because section 6.1 splits `/yocto/matrix-run` rather than moving it: "keep
    active driver/finalize scripts; move old historical logs to Drive". A whole-tree move
    would take driver.sh and finalize.sh with the logs, and those two are live build
    control. Matching files are staged into one archive under their original relative
    paths, verified, and only then removed individually -- the retained files are never
    touched.
    """
    src = local_path(op["src"])
    op_id = op["id"]
    if state_of(st, op_id) == "COMPLETE":
        print(f"  {op_id}: COMPLETE already")
        return
    if not src.is_dir():
        if apply:
            record(st, op_id, state="COMPLETE", detail="source absent")
        else:
            print(f"  {op_id:<34} absent")
        return

    hits: list[pathlib.Path] = []
    for pat in op["patterns"]:
        hits.extend(q for q in src.rglob(pat) if q.is_file() and not q.is_symlink())
    hits = sorted(set(hits))
    keep = [q for q in src.rglob("*")
            if q.is_file() and not q.is_symlink() and q not in set(hits)]
    total = sum(q.stat().st_size for q in hits)

    if not apply:
        print(f"  {op_id:<34} would move {len(hits)} file(s) {human(total)} -> "
              f"{op['dest']}/  (keeping {len(keep)})")
        for q in keep[:6]:
            print(f"        KEEP {q.relative_to(src)}")
        return
    if not hits:
        record(st, op_id, state="COMPLETE", detail="no matching files remain")
        print(f"  {op_id}: nothing left to move")
        return

    # Stage a tree of just the matching files so the existing verified primitive can carry
    # it. Hardlinks where possible: no second copy of the bytes on disk.
    work = STAGE / "subset" / op_id
    if work.exists():
        shutil.rmtree(work, ignore_errors=True)
    for q in hits:
        d = work / q.relative_to(src)
        d.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.link(q, d)
        except OSError:
            shutil.copy2(q, d)
    print(f"  {op_id}: staged {len(hits)} file(s), {human(total)}; keeping {len(keep)}")

    ok = _pack_upload_retire(op_id, work, op["dest"], op["why"], st, retire=True)
    shutil.rmtree(STAGE / "subset", ignore_errors=True)
    if not ok:
        print(f"  {op_id}: not verified -- ORIGINALS UNTOUCHED")
        return
    removed = 0
    for q in hits:
        try:
            q.unlink()
            removed += 1
        except OSError:
            pass
    # Prune directories emptied by the removal, never the tree root.
    for d in sorted((x for x in src.rglob("*") if x.is_dir()),
                    key=lambda x: len(x.parts), reverse=True):
        try:
            d.rmdir()
        except OSError:
            pass
    record(st, op_id, state="COMPLETE",
           detail=f"moved {removed} file(s) {human(total)}, kept {len(keep)}",
           raw_bytes=total)
    print(f"  {op_id}: COMPLETE -- moved {removed}, kept {len(keep)}, freed {human(total)}")




def do_backfill_zip_manifests(op: dict, st: dict, apply: bool) -> None:
    """Rebuild SHA256 CONTENT manifests for collections already uploaded with size-only ones.

    WHY THIS OPERATION EXISTS. The owner's manifest rule is explicit: manifests must carry
    actual content identity -- TYPE, RELPATH, SIZE_BYTES, SHA256, MODE, LINK_TARGET -- and
    "Do not return to path+size-only manifests." Twenty-one sendtodrive collections were
    uploaded before that requirement landed, by an orchestrator process that had already
    loaded the older code, so their sibling manifests are `RELPATH  SIZE_BYTES` only.

    Their local sources are retired, so the manifests cannot be regenerated from disk. They
    CAN be regenerated from `/yocto/Archives/sendtodrive.zip`, which was measured to
    contain every one of those files and is deliberately still present -- retiring it
    before the collections it backs were fully verified is exactly the mistake the coverage
    gate guards against. This is the second time that decision has paid for itself.

    Size is not identity: two files of equal length are routinely different, so a size-only
    manifest can neither support dedupe nor prove an archived collection is what it claims.

    Nothing is re-uploaded except the manifests themselves -- the archives are untouched.
    """
    op_id = op["id"]
    zp = pathlib.Path(op["zip"])
    if state_of(st, op_id) == "COMPLETE":
        print(f"  {op_id}: COMPLETE already")
        return
    if not zp.is_file():
        # Not a failure: if the zip is gone the collections were verified some other way.
        record(st, op_id, state="FAILED",
               detail=f"{zp} absent; cannot rebuild content manifests from it")
        print(f"  {op_id}: recovery zip absent -- size-only manifests remain, reported")
        return

    # Which collections went where, read from the ledger rather than assumed.
    targets: list[tuple[str, str]] = []
    for oid, o in sorted(st["ops"].items()):
        if o.get("state") != "COMPLETE" or not o.get("dest"):
            continue
        if not oid.startswith(op["ledger_prefix"]):
            continue
        leaf = oid.split("::", 1)[-1]
        targets.append((leaf, str(pathlib.PurePosixPath(o["dest"]).parent)))

    if not apply:
        print(f"  {op_id}: would rebuild SHA256 manifests for {len(targets)} collection(s) "
              f"from {zp.name}")
        for leaf, dest in targets[:6]:
            print(f"        {leaf:<26} -> {dest}/{leaf}.CONTENTS.tsv")
        return

    print(f"  {op_id}: rebuilding SHA256 manifests for {len(targets)} collection(s)")
    record(st, op_id, state="PACKING", detail=f"{len(targets)} collections", why=op["why"])

    prefix = op["member_prefix"]
    with zipfile.ZipFile(zp) as z:
        infos = z.infolist()
        by_leaf: dict[str, list[zipfile.ZipInfo]] = {}
        for i in infos:
            n = i.filename
            if not n.startswith(prefix):
                continue
            rest = n[len(prefix):]
            if not rest:
                continue
            leaf = rest.split("/", 1)[0]
            by_leaf.setdefault(leaf, []).append(i)

        ok = failed = 0
        for leaf, dest_dir in targets:
            child = f"{op_id}::{leaf}"
            if state_of(st, child) == "COMPLETE":
                ok += 1
                continue
            members = by_leaf.get(leaf, [])
            if not members:
                record(st, child, state="FAILED", detail="no members under this leaf in zip")
                failed += 1
                continue
            out = STAGE / f"{leaf}.CONTENTS.tsv"
            STAGE.mkdir(parents=True, exist_ok=True)
            base = f"{prefix}{leaf}"
            rows = 0
            with out.open("w") as fh:
                fh.write("TYPE\tRELPATH\tSIZE_BYTES\tSHA256\tMODE\tLINK_TARGET\n")
                for i in sorted(members, key=lambda x: x.filename):
                    rel = i.filename[len(base):].lstrip("/") or pathlib.PurePath(leaf).name
                    mode = (i.external_attr >> 16) & 0o7777
                    ftype = (i.external_attr >> 16) & 0o170000
                    if i.is_dir():
                        fh.write(f"DIR\t{rel}\t0\t\t{mode:04o}\t\n")
                    elif ftype == 0o120000:
                        # A symlink's stored bytes ARE its target. Record it; never follow
                        # it, and never hash the target's content as if it were this file.
                        with z.open(i) as fhz:
                            tgt = fhz.read().decode("utf-8", "replace")
                        fh.write(f"SYMLINK\t{rel}\t{i.file_size}\t\t{mode:04o}\t{tgt}\n")
                    else:
                        h = hashlib.sha256()
                        with z.open(i) as fhz:
                            for chunk in iter(lambda: fhz.read(1 << 20), b""):
                                h.update(chunk)
                        fh.write(f"FILE\t{rel}\t{i.file_size}\t{h.hexdigest()}\t"
                                 f"{mode:04o}\t\n")
                    rows += 1
            os.chmod(out, 0o600)
            lm = md5_of(out)
            up = sh(["rclone", "copy", str(out), f"{REMOTE}{dest_dir}/"] + RCLONE)
            rm = remote_md5(f"{dest_dir}/{out.name}") if up.returncode == 0 else None
            if rm != lm:
                record(st, child, state="FAILED",
                       detail=f"manifest upload/verify failed (remote={rm})")
                failed += 1
                out.unlink(missing_ok=True)
                continue
            # Retire the superseded size-only manifest so two manifests cannot disagree.
            sh(["rclone", "deletefile", f"{REMOTE}{dest_dir}/{leaf}.manifest.tsv"],
               timeout=600)
            record(st, child, state="COMPLETE",
                   detail=f"{rows} rows, sha256, md5 {rm}", dest=f"{dest_dir}/{out.name}",
                   remote_md5=rm)
            print(f"      {leaf}: {rows} rows with SHA256 -> {dest_dir}/{out.name}")
            out.unlink(missing_ok=True)
            ok += 1

    record(st, op_id, state="COMPLETE" if not failed else "PARTIAL",
           detail=f"{ok} rebuilt, {failed} failed")
    print(f"  {op_id}: {ok} rebuilt, {failed} failed")



def do_publish_manifests(op: dict, st: dict, apply: bool) -> None:
    """Upload pre-captured SHA256 content manifests, replacing size-only ones on Drive.

    WHY THESE WERE CAPTURED OUT OF BAND. The orchestrator process that uploaded
    /yocto/artifacts started at 05:50:13, before the content-manifest code existed, and
    Python binds a module's functions at import -- so it writes `RELPATH  SIZE_BYTES` and
    then retires the source. For 191 GB across 105,851 files that would have been
    unrecoverable without re-downloading everything.

    Killing the owner to load newer code was not an option: the instruction forbids killing
    a running owner to install tooling, and an interrupted upload costs the whole transfer
    again. So the SHA256 data was captured LOCALLY while the sources still existed -- pure
    reading, no rclone, no Drive mutation, no second mutation owner -- into
    .private/storage-reorg/contents/. This operation publishes it.

    The capture won its race: all six leaves were hashed before the first source retired.
    """
    op_id = op["id"]
    src_dir = ROOT / op["from"]
    if state_of(st, op_id) == "COMPLETE":
        print(f"  {op_id}: COMPLETE already")
        return
    captured = sorted(src_dir.glob("*.CONTENTS.tsv")) if src_dir.is_dir() else []
    if not captured:
        if apply:
            record(st, op_id, state="FAILED", detail=f"no captured manifests in {src_dir}")
        else:
            print(f"  {op_id:<34} no captured manifests")
        return

    # Destinations come from the ledger, so a manifest cannot be filed beside the wrong
    # archive.
    dests: dict[str, str] = {}
    for oid, o in st["ops"].items():
        if o.get("state") != "COMPLETE" or not o.get("dest"):
            continue
        if not oid.startswith(op["ledger_prefix"]):
            continue
        dests[oid.split("::", 1)[-1]] = str(pathlib.PurePosixPath(o["dest"]).parent)

    if not apply:
        print(f"  {op_id}: would publish {len(captured)} manifest(s); "
              f"{len(dests)} destination(s) known from the ledger")
        for f in captured:
            leaf = f.name[:-len(".CONTENTS.tsv")]
            print(f"        {leaf:<18} -> {dests.get(leaf, '<destination not yet in ledger>')}")
        return

    ok = pend = failed = 0
    for f in captured:
        leaf = f.name[:-len(".CONTENTS.tsv")]
        child = f"{op_id}::{leaf}"
        if state_of(st, child) == "COMPLETE":
            ok += 1
            continue
        dest_dir = dests.get(leaf)
        if not dest_dir:
            # Its archive has not uploaded yet. Not an error -- try again next cycle.
            pend += 1
            continue
        lm = md5_of(f)
        up = sh(["rclone", "copy", str(f), f"{REMOTE}{dest_dir}/"] + RCLONE)
        rm = remote_md5(f"{dest_dir}/{f.name}") if up.returncode == 0 else None
        if rm != lm:
            record(st, child, state="FAILED", detail=f"manifest verify failed remote={rm}")
            failed += 1
            continue
        sh(["rclone", "deletefile", f"{REMOTE}{dest_dir}/{leaf}.manifest.tsv"], timeout=600)
        record(st, child, state="COMPLETE", detail=f"published, md5 {rm}",
               dest=f"{dest_dir}/{f.name}", remote_md5=rm)
        print(f"      {leaf}: SHA256 manifest published -> {dest_dir}/{f.name}")
        ok += 1

    state = "COMPLETE" if (pend == 0 and failed == 0) else "PARTIAL"
    record(st, op_id, state=state,
           detail=f"{ok} published, {pend} awaiting their archive, {failed} failed",
           why=op["why"])
    print(f"  {op_id}: {ok} published, {pend} awaiting their archive, {failed} failed")




#: Depth limit for recursive Drive directory merges. Deep enough for any real collection
#: here (the deepest observed is an Xcode SDK at ~14), shallow enough that a pathological
#: or cyclic structure cannot spin forever against a rate-limited API.
MERGE_MAX_DEPTH = 24


def _rls(path: str) -> list[dict] | None:
    """One level of a Drive path, with hashes. None means the path does not exist."""
    r = sh(["rclone", "lsjson", f"{REMOTE}{path}", "--hash"], timeout=1800)
    if r.returncode != 0:
        return None
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return None


def _md5_of_remote_entry(e: dict) -> str:
    return ((e.get("Hashes") or {}).get("md5") or "")


def _merge_dirs(src: str, dest: str, st: dict, op_id: str, depth: int = 0) -> dict:
    """Recursively merge Drive directory `src` INTO existing Drive directory `dest`.

    `rclone moveto` on a directory whose destination already exists does not implement the
    merge policy this project needs, and relying on its semantics is exactly what the owner
    asked not to do. So the tree is walked explicitly, one level at a time:

        child missing at destination      -> server-side move
        both directories                  -> RECURSE
        both files, same size + same MD5  -> verified duplicate; keep the survivor,
                                             delete the source copy
        both files, content differs or a
        hash is unavailable               -> preserve BOTH under
                                             `__from_<src>/<name>.__src_<tag>`
        type mismatch (dir vs file)       -> preserve both; a directory and a file sharing
                                             a name are not versions of each other

    "Hash unavailable" is treated as "differs" on purpose. Google Docs-native objects and
    some uploads expose no MD5, and deleting one of two objects because neither could be
    hashed would be deciding by absence of evidence.

    The source directory is removed only after it is empty AND the destination verifies.
    """
    out = {"moved": 0, "dupes": 0, "conflicts": 0, "recursed": 0, "failed": 0}
    if depth > MERGE_MAX_DEPTH:
        print(f"        merge depth limit {MERGE_MAX_DEPTH} reached at {src}; "
              f"leaving it in place rather than recursing further")
        out["failed"] += 1
        return out

    kids = _rls(src)
    if kids is None:
        return out
    dst_kids = _rls(dest) or []
    by_name = {k.get("Name"): k for k in dst_kids}

    for k in kids:
        name = k.get("Name")
        s_is_dir = bool(k.get("IsDir"))
        sp, dp = f"{src}/{name}", f"{dest}/{name}"
        d = by_name.get(name)

        if d is None:                                   # unique -> plain server-side move
            mv = sh(["rclone", "moveto", f"{REMOTE}{sp}", f"{REMOTE}{dp}", "--checksum"],
                    timeout=21600)
            if mv.returncode != 0:
                out["failed"] += 1
                print(f"        MOVE FAILED {sp}: {mv.stderr.strip()[:90]}")
            else:
                out["moved"] += 1
            continue

        d_is_dir = bool(d.get("IsDir"))

        if s_is_dir and d_is_dir:                       # nested collision -> recurse
            out["recursed"] += 1
            sub = _merge_dirs(sp, dest=dp, st=st, op_id=op_id, depth=depth + 1)
            for key in out:
                out[key] += sub.get(key, 0)
            continue

        if s_is_dir != d_is_dir:
            # A directory and a file sharing a name are not two versions of one thing.
            tag = f"dir{depth}" if s_is_dir else str(k.get("Size") or 0)
            alt = f"{dest}/__from_{_slug(src)}/{name}.__src_{tag}"
            mv = sh(["rclone", "moveto", f"{REMOTE}{sp}", f"{REMOTE}{alt}"], timeout=21600)
            out["conflicts" if mv.returncode == 0 else "failed"] += 1
            continue

        # both files
        s_md5, d_md5 = _md5_of_remote_entry(k), _md5_of_remote_entry(d)
        s_sz, d_sz = int(k.get("Size") or -1), int(d.get("Size") or -2)
        if s_md5 and d_md5 and s_md5 == d_md5 and s_sz == d_sz:
            rm = sh(["rclone", "deletefile", f"{REMOTE}{sp}"], timeout=900)
            out["dupes" if rm.returncode == 0 else "failed"] += 1
            continue
        tag = (s_md5[:12] if s_md5 else str(s_sz))
        alt = f"{dest}/__from_{_slug(src)}/{name}.__src_{tag}"
        mv = sh(["rclone", "moveto", f"{REMOTE}{sp}", f"{REMOTE}{alt}"], timeout=21600)
        out["conflicts" if mv.returncode == 0 else "failed"] += 1

    # Retire the source container only when it is genuinely empty and the destination is
    # actually there. "The move returned 0" is not the same as "the bytes arrived".
    left = _rls(src)
    if left is not None and not left:
        if _rls(dest) is not None:
            sh(["rclone", "rmdir", f"{REMOTE}{src}"], timeout=900)
        else:
            print(f"        NOT removing {src}: destination {dest} does not verify")
            out["failed"] += 1
    return out


def _slug(s: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", s).strip("_") or "source"


def do_zip_coverage(op: dict, st: dict, apply: bool) -> None:
    """Prove every useful ZIP collection has canonical Drive coverage, then retire the ZIP.

    The instruction is strict about the order: prove coverage first, retire only when
    ZIP_UNIQUE_UNMAPPED_BYTES=0, then remove the emptied container. This zip has earned
    that caution twice -- it held the only COMPLETE AppleSDK after the disk copy lost
    38,310 files, and it was the only source able to rebuild SHA256 manifests for 21
    collections whose local sources had already retired.

    Coverage means: for each top-level collection inside the zip, an operation in the
    ledger is COMPLETE with a destination, and that destination still verifies. Anything
    not covered contributes its bytes to UNMAPPED, and while UNMAPPED > 0 the zip stays.
    """
    op_id = op["id"]
    zp = pathlib.Path(op["zip"])
    if state_of(st, op_id) == "COMPLETE":
        print(f"  {op_id}: COMPLETE already")
        return
    if not zp.is_file():
        record(st, op_id, state="COMPLETE", detail="zip already retired")
        return

    prefix = op["member_prefix"]
    with zipfile.ZipFile(zp) as z:
        per: dict[str, int] = {}
        for i in z.infolist():
            if i.is_dir() or not i.filename.startswith(prefix):
                continue
            rest = i.filename[len(prefix):]
            if not rest:
                continue
            per[rest.split("/", 1)[0]] = per.get(rest.split("/", 1)[0], 0) + i.file_size

    # Which collections are covered, read from the ledger and RE-VERIFIED on the remote.
    covered: dict[str, str] = {}
    for oid, o in st["ops"].items():
        if o.get("state") != "COMPLETE" or not o.get("dest"):
            continue
        for pre in op["ledger_prefixes"]:
            if oid.startswith(pre):
                covered[oid.split("::", 1)[-1]] = o["dest"]
    # AppleSDK was uploaded under its own operation id, not as a sendtodrive leaf.
    for oid, o in st["ops"].items():
        if oid == op.get("applesdk_op") and o.get("state") == "COMPLETE" and o.get("dest"):
            covered["AppleSDK"] = o["dest"]

    unmapped = {k: v for k, v in per.items() if k not in covered}
    unmapped_bytes = sum(unmapped.values())

    print(f"  {op_id}: {len(per)} collection(s) in the zip, {len(covered)} covered, "
          f"{len(unmapped)} unmapped ({human(unmapped_bytes)})")
    for k in sorted(unmapped):
        print(f"        UNMAPPED {k:<24} {human(unmapped[k])}")

    if not apply:
        print(f"        ZIP_UNIQUE_UNMAPPED_BYTES={unmapped_bytes}; "
              f"{'would retire the zip' if unmapped_bytes == 0 else 'zip STAYS'}")
        return

    # Re-verify each covered destination on the remote before trusting the ledger.
    stale = []
    for leaf, dest in sorted(covered.items()):
        if leaf not in per:
            continue
        if remote_md5(dest) is None:
            stale.append(leaf)
    if stale:
        record(st, op_id, state="PARTIAL",
               detail=f"{len(stale)} covered destination(s) no longer verify: "
                      f"{','.join(stale[:6])}; zip RETAINED")
        print(f"  {op_id}: {len(stale)} destination(s) no longer verify -- zip RETAINED")
        return

    if unmapped_bytes != 0:
        record(st, op_id, state="PARTIAL",
               detail=f"ZIP_UNIQUE_UNMAPPED_BYTES={unmapped_bytes} "
                      f"({len(unmapped)} collections); zip RETAINED")
        print(f"  {op_id}: unmapped bytes remain -- zip RETAINED, which is correct")
        return

    (VERIFY_DIR / f"{op_id}.txt").write_text(
        f"op={op_id}\nzip={zp}\ncollections_in_zip={len(per)}\n"
        f"covered={len(covered)}\nZIP_UNIQUE_UNMAPPED_BYTES=0\n"
        f"destinations_reverified={len([l for l in covered if l in per])}\n"
        f"proved_at={time.strftime('%Y-%m-%dT%H:%M:%S%z')}\nwhy={op['why']}\n")
    size = zp.stat().st_size
    zp.unlink()
    record(st, op_id, state="COMPLETE",
           detail=f"coverage proven, zip retired ({human(size)})", raw_bytes=size)
    print(f"  {op_id}: coverage proven -- zip retired, freed {human(size)}")
    # Remove the container only if it is now genuinely empty.
    parent = zp.parent
    try:
        if parent.is_dir() and not any(parent.iterdir()):
            parent.rmdir()
            print(f"  {op_id}: empty container {parent} removed")
    except OSError as e:
        print(f"  {op_id}: container not removed ({e})")


def do_drive_children(op: dict, st: dict, apply: bool) -> None:
    """Classify the children of a Drive folder and distribute them server-side.

    Needed because the spec forbids `Projects_Organize`, `offload` and `DONOTDELETE`
    surviving as buckets, and the first is 247.7 GiB across 234 children. Re-uploading that
    to reorganise it would take days against a 5 MB/s link; a server-side `moveto` inside
    one Drive is metadata work and costs nothing, which is exactly what the spec means by
    "Do NOT re-upload data already on Drive merely to rename/reorganize it."

    Verification is aggregate per child: the destination must exist with the same byte count
    and the source must be gone. A child whose classifier returns None is left in place and
    reported, never swept into a default bucket.
    """
    src = op["src"]
    op_id = op["id"]
    classify = op["classify"]
    r = sh(["rclone", "lsjson", f"{REMOTE}{src}"], timeout=3600)
    if r.returncode != 0:
        if apply:
            record(st, op_id, state="COMPLETE", detail="source bucket absent")
        else:
            print(f"  {op_id:<34} bucket absent")
        return
    try:
        kids = json.loads(r.stdout)
    except json.JSONDecodeError:
        record(st, op_id, state="FAILED", detail="lsjson output unparseable")
        return

    plan: list[tuple[str, str, int, bool]] = []
    unrouted: list[str] = []
    for k in kids:
        name = k.get("Name") or k.get("Path")
        dest = classify(name, bool(k.get("IsDir")))
        if not dest:
            unrouted.append(name)
            continue
        plan.append((name, dest, int(k.get("Size") or 0), bool(k.get("IsDir"))))

    if not apply:
        print(f"  {op_id}  ({len(kids)} children, {len(plan)} routed, "
              f"{len(unrouted)} unrouted)")
        by: dict[str, int] = {}
        for _, d, sz, _i in plan:
            by[d] = by.get(d, 0) + sz
        for d in sorted(by, key=lambda x: -by[x])[:14]:
            print(f"        {human(by[d]):>9}  -> {d}")
        for u in unrouted[:8]:
            print(f"        UNROUTED: {u}")
        return

    print(f"  {op_id}: {len(plan)} of {len(kids)} children routed server-side")
    done = failed = 0
    for name, dest, sz, isdir in plan:
        child_id = f"{op_id}::{name}"
        if state_of(st, child_id) == "COMPLETE":
            done += 1
            continue
        sp, dp = f"{src}/{name}", f"{dest}/{name}"
        record(st, child_id, state="MOVING", detail=f"{sp} -> {dp}", raw_bytes=sz)

        # COLLISION HANDLING, required by the Drive-merge rules:
        #   same name + same size + same MD5 -> verified duplicate; keep the survivor
        #   same name + different content    -> preserve BOTH, provenance-aware naming
        #   unique                            -> plain server-side move
        # A bare `moveto` into an occupied path is how one of two same-named objects
        # silently becomes the only one. Drive also allows two entries with the SAME NAME
        # at one path, so "the destination exists" is not the same question as "this is
        # the same object".
        occupied = sh(["rclone", "lsjson", f"{REMOTE}{dp}", "--stat", "--hash"],
                      timeout=600)
        if occupied.returncode == 0 and isdir:
            # DIRECTORY-DIRECTORY collision. rclone moveto onto an existing directory does
            # not implement this project's merge policy, so the tree is walked explicitly
            # and merged entry by entry, recursing into nested collisions.
            print(f"      {name}: destination directory exists -- recursive merge")
            res = _merge_dirs(sp, dp, st, child_id)
            state = "COMPLETE" if res["failed"] == 0 else "PARTIAL"
            record(st, child_id, state=state, dest=dp, raw_bytes=sz,
                   detail=f"recursive merge: moved={res['moved']} "
                          f"duplicates={res['dupes']} conflicts={res['conflicts']} "
                          f"nested={res['recursed']} failed={res['failed']}")
            print(f"      {name}: merged moved={res['moved']} dup={res['dupes']} "
                  f"conflict={res['conflicts']} nested={res['recursed']} "
                  f"failed={res['failed']}")
            done += 1 if res["failed"] == 0 else 0
            failed += 0 if res["failed"] == 0 else 1
            continue
        if occupied.returncode == 0 and not isdir:
            try:
                ex = json.loads(occupied.stdout) or {}
            except json.JSONDecodeError:
                ex = {}
            ex_size = int(ex.get("Size") or -1)
            ex_md5 = ((ex.get("Hashes") or {}).get("md5") or "")
            mine = sh(["rclone", "lsjson", f"{REMOTE}{sp}", "--stat", "--hash"],
                      timeout=600)
            try:
                mj = json.loads(mine.stdout) or {}
            except json.JSONDecodeError:
                mj = {}
            my_md5 = ((mj.get("Hashes") or {}).get("md5") or "")
            if ex_size == sz and ex_md5 and my_md5 and ex_md5 == my_md5:
                # Byte-identical. The destination copy is the canonical survivor, so the
                # source copy is redundant -- delete it rather than move it on top.
                rm = sh(["rclone", "deletefile", f"{REMOTE}{sp}"], timeout=900)
                if rm.returncode != 0:
                    record(st, child_id, state="FAILED",
                           detail=f"duplicate delete failed: {rm.stderr.strip()[:120]}")
                    failed += 1
                    continue
                record(st, child_id, state="COMPLETE", dest=dp, raw_bytes=sz,
                       detail=f"verified duplicate of destination (md5 {ex_md5}); "
                              f"source copy removed, survivor kept")
                print(f"      {name}: duplicate of destination -- survivor kept")
                done += 1
                continue
            # Same name, different (or unverifiable) content. Preserving both is the only
            # safe answer: a differing object under a shared name is not a duplicate.
            tag = (my_md5[:12] if my_md5 else str(sz))
            dp = f"{dest}/__from_{src.replace('/', '_') or 'root'}/{name}.__src_{tag}"
            print(f"      {name}: name collision, content differs -- preserving both")
        mv = sh(["rclone", "moveto", f"{REMOTE}{sp}", f"{REMOTE}{dp}",
                 "--checksum"], timeout=21600)
        if mv.returncode != 0:
            record(st, child_id, state="FAILED", detail=mv.stderr.strip()[:160])
            failed += 1
            continue
        # Confirm arrival and departure rather than trusting the exit status.
        chk = sh(["rclone", "size", f"{REMOTE}{dp}", "--json"], timeout=3600)
        gone = sh(["rclone", "lsjson", f"{REMOTE}{sp}", "--stat"], timeout=600)
        ok = chk.returncode == 0 and gone.returncode != 0
        if ok and sz and not isdir:
            try:
                ok = json.loads(chk.stdout).get("bytes") == sz
            except json.JSONDecodeError:
                ok = False
        record(st, child_id, state="COMPLETE" if ok else "FAILED",
               detail=f"{chk.stdout.strip()[:70]}" if ok else "post-move verify failed",
               dest=dp, raw_bytes=sz)
        done += 1 if ok else 0
        failed += 0 if ok else 1

    left = sh(["rclone", "lsjson", f"{REMOTE}{src}"], timeout=1800)
    remaining = []
    if left.returncode == 0:
        try:
            remaining = [x.get("Name") for x in json.loads(left.stdout)]
        except json.JSONDecodeError:
            pass
    if not remaining:
        sh(["rclone", "rmdir", f"{REMOTE}{src}"], timeout=900)
        record(st, op_id, state="COMPLETE",
               detail=f"distributed {done} children, bucket removed")
        print(f"  {op_id}: COMPLETE -- {done} moved, bucket {src} removed")
    else:
        record(st, op_id, state="PARTIAL",
               detail=f"{done} moved, {failed} failed, {len(remaining)} remain")
        print(f"  {op_id}: PARTIAL -- {done} moved, {failed} failed, "
              f"{len(remaining)} remain")


def do_drive_moves(st: dict, apply: bool) -> None:
    for srcname, destpath, sect in DRIVE_MOVES:
        op_id = f"drivemv-{srcname.replace(' ', '_').replace('/', '_')}"
        if state_of(st, op_id) == "COMPLETE":
            continue
        chk = sh(["rclone", "lsjson", f"{REMOTE}{srcname}", "--stat"], timeout=600)
        if chk.returncode != 0:
            if apply:
                record(st, op_id, state="COMPLETE",
                       detail="source absent (already moved, or never existed)")
            continue
        if not apply:
            print(f"  {op_id:<46} {srcname}  ->  {destpath}   [{sect}]")
            continue
        before = sh(["rclone", "size", f"{REMOTE}{srcname}", "--json"], timeout=3600)
        record(st, op_id, state="MOVING", detail=f"{srcname} -> {destpath}",
               before=before.stdout.strip()[:120])
        r = sh(["rclone", "moveto", f"{REMOTE}{srcname}", f"{REMOTE}{destpath}",
                "--checksum", "--transfers", "8", "--stats", "5m", "--stats-one-line"])
        if r.returncode != 0:
            record(st, op_id, state="FAILED", detail=r.stderr.strip()[:180])
            print(f"  {op_id}: FAILED -- {r.stderr.strip()[:110]}")
            continue
        after = sh(["rclone", "size", f"{REMOTE}{destpath}", "--json"], timeout=3600)
        record(st, op_id, state="COMPLETE",
               detail=f"{before.stdout.strip()[:70]} -> {after.stdout.strip()[:70]}",
               after=after.stdout.strip()[:120])
        print(f"  {op_id}: moved  {srcname} -> {destpath}")


# =========================================================================================
# Commands
# =========================================================================================
KINDS = {"drop": do_drop, "drop_glob": do_drop_glob, "move_out": do_move_out,
         "move_leaves": do_move_leaves, "extract_upload": do_extract_upload,
         "move_files": do_move_files, "drive_children": do_drive_children,
         "backfill_zip_manifests": do_backfill_zip_manifests,
         "publish_manifests": do_publish_manifests,
         "zip_coverage": do_zip_coverage}
#: Kinds that cost no upload bandwidth. `drive_children` belongs here even though it
#: mutates Drive: a server-side `moveto` inside one Drive is metadata work, so distributing
#: 247.7 GiB of Projects_Organize takes minutes and competes with the uploads for nothing
#: but API calls. Leaving it in the bandwidth phase meant the most visible section 12 gates
#: -- root entry count, `Projects_Organize`/`offload`/`DONOTDELETE` not surviving -- waited
#: behind roughly eight hours of transfers for no reason.
FREE_KINDS = ("drop", "drop_glob")
API_BOUND_KINDS = ("drive_children",)


def cmd_plan() -> int:
    st = load_state()
    print("STORAGE REORGANISATION PLAN")
    print("=" * 78)
    print("\nPHASE 1 -- FREE, no bandwidth: drop regenerable caches\n")
    for op in OPERATIONS:
        if op["kind"] in FREE_KINDS:
            KINDS[op["kind"]](op, st, False)
    print("\nPHASE 2 -- FREE, server-side: Drive reorganisation\n")
    do_drive_moves(st, False)
    for op in OPERATIONS:
        if op["kind"] in API_BOUND_KINDS:
            KINDS[op["kind"]](op, st, False)
    print("\nPHASE 3 -- BANDWIDTH-BOUND: local -> Drive, verified then retired\n")
    for op in OPERATIONS:
        if op["kind"] not in FREE_KINDS and op["kind"] not in API_BOUND_KINDS:
            KINDS[op["kind"]](op, st, False)
    return 0


def cmd_status() -> int:
    st = load_state()
    if not st["ops"]:
        print("  no operations recorded yet -- run `plan`")
        return 0
    by: dict[str, int] = {}
    freed = 0
    for oid, o in sorted(st["ops"].items()):
        s = o.get("state", "?")
        by[s] = by.get(s, 0) + 1
        if s == "COMPLETE":
            freed += o.get("raw_bytes", 0)
        print(f"  {oid:<54} {s:<14} {str(o.get('detail',''))[:50]}")
    print("\n  " + "   ".join(f"{k}={v}" for k, v in sorted(by.items())))
    print(f"  bytes retired locally: {human(freed)}")
    return 0


def cmd_verify() -> int:
    st = load_state()
    checked = bad = 0
    for oid, o in sorted(st["ops"].items()):
        if o.get("state") != "COMPLETE" or "remote_md5" not in o or not o.get("dest"):
            continue
        checked += 1
        rm = remote_md5(o["dest"])
        ok = rm == o["remote_md5"]
        if not ok:
            bad += 1
        print(f"  {oid:<54} {'OK' if ok else 'REMOTE CHANGED OR GONE'}")
    print(f"\n  re-verified {checked} completed operation(s); mismatches: {bad}")
    return 1 if bad else 0


def cmd_run() -> int:
    if not take_lock():
        return 1
    st = load_state()
    try:
        print("PHASE 1 -- drop regenerable caches (instant, no bandwidth)")
        for op in OPERATIONS:
            if op["kind"] in FREE_KINDS:
                KINDS[op["kind"]](op, st, True)
        # Phase 2 is API-bound (recursive Drive walks at 8 requests/second); phase 3 is
        # bandwidth-bound (~5 MB/s of upload). They contend for almost nothing, and run
        # sequentially phase 2 simply delays the 15-hour pole for no reason. So phase 2
        # goes to a worker thread and phase 3 proceeds immediately in this one.
        def _phase2() -> None:
            do_drive_moves(st, True)
            for o in OPERATIONS:
                if o["kind"] in API_BOUND_KINDS:
                    KINDS[o["kind"]](o, st, True)

        print("\nPHASE 2 -- Drive server-side reorganisation (background, API-bound)")
        t = threading.Thread(target=_phase2, name="drive-server-side", daemon=True)
        t.start()

        print("PHASE 3 -- local -> Drive (foreground, bandwidth-bound)\n")
        for op in OPERATIONS:
            if op["kind"] not in FREE_KINDS and op["kind"] not in API_BOUND_KINDS:
                KINDS[op["kind"]](op, st, True)

        print("\n  phase 3 done; waiting on the phase 2 Drive walks to finish ...")
        t.join()
    finally:
        LOCK.unlink(missing_ok=True)
    print("\n  run finished; `status` for the ledger, `verify` to re-check destinations")
    return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("cmd", choices=["plan", "run", "resume", "status", "verify"])
    a = ap.parse_args(argv)
    return {"plan": cmd_plan, "status": cmd_status, "verify": cmd_verify,
            "run": cmd_run, "resume": cmd_run}[a.cmd]()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
