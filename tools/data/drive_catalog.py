#!/usr/bin/env python3
# SPDX-License-Identifier: LicenseRef-SyMoNeuRaL-Proprietary
# Copyright (c) 2026 SymonSays LLC. All rights reserved.
"""Generate the Drive knowledge authority: INDEX.md, CATALOG.tsv, MIGRATION-MAP.tsv.

    tools/data/drive_catalog.py build     write the four files locally
    tools/data/drive_catalog.py upload    push them to the Drive root and verify by MD5

Why these files exist, from the spec's catalog section: a future engineer must be able to
answer "where are the original Qwen/OpenAI models", "where are old SyMoNeuRaL source/build
snapshots", "where are Yocto package/image outputs", "where are Apple/CUDA SDK references",
"where are old miner/firmware projects", "where are prior UI/screenshots/task histories",
"where are VM/host setup resources" and "where are archived projects by domain" -- without
this session, without the ledger, and without asking anyone.

`MIGRATION-MAP.tsv` is generated from the storage-reorg ledger rather than hand-written, so
it cannot claim a move that did not happen. Only operations recorded COMPLETE with a
destination appear in it.

The running server must not depend on any of this. These files are documentation of an
archive, not an input to the product -- which is why the tracked local pointer is a
markdown file and not a code path.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import subprocess
import time

ROOT = pathlib.Path("/home/google/Symoneural")
STATE = ROOT / ".private" / "storage-reorg" / "state.json"
OUT = ROOT / ".private" / "storage-reorg" / "catalog"
REMOTE = "gdrive:"

CATALOG_COLUMNS = [
    "COLLECTION_ID", "CANONICAL_PATH", "CATEGORY", "SUBCATEGORY", "DESCRIPTION",
    "KEYWORDS", "ORIGIN_PATHS", "SIZE_BYTES", "FILE_COUNT", "IMPORTANT_FORMATS",
    "RELATED_SYMONEURAL_COMPONENTS", "UPSTREAM_PROJECT", "UPSTREAM_REVISION",
    "HISTORICAL_PERIOD", "PROBLEM_DOMAIN", "KNOWN_WORKING_COMPONENTS", "KNOWN_FAILURES",
    "RELEVANT_DOCS", "WHY_RETAINED", "REACQUIRABLE", "UNIQUE", "NOTES",
]

#: Hand-authored semantics per top-level collection. Sizes and counts are MEASURED and
#: filled in at build time -- only the meaning is written here, because meaning is the one
#: thing a directory listing cannot supply.
SEMANTICS: dict[str, dict[str, str]] = {
    "Symoneural": dict(
        CATEGORY="project", SUBCATEGORY="first-party history and recovery",
        DESCRIPTION="Everything belonging to the SyMoNeuRaL project that is not the running "
                    "server: documentation, agent and task history, source and build "
                    "snapshots, restore material, release artefacts, brand assets, pinned "
                    "upstream source and general reference.",
        KEYWORDS="symoneural;history;restore;snapshots;documentation;brand",
        PROBLEM_DOMAIN="project history and disaster recovery",
        WHY_RETAINED="Restore authority and the record of what was built and why.",
        REACQUIRABLE="no", UNIQUE="yes"),
    "Models": dict(
        CATEGORY="models", SUBCATEGORY="upstream distributions and historical",
        DESCRIPTION="Original and upstream public model distributions, conversion inputs, "
                    "historical models and model cards. The RUNNING weights are NOT here: "
                    "they live locally at backend/models/ under house names, because the "
                    "runtime must work with Drive unavailable.",
        KEYWORDS="qwen;openai;gpt-oss;gguf;safetensors;weights;conversion",
        PROBLEM_DOMAIN="model provenance and re-derivation",
        WHY_RETAINED="Conversion inputs and originals for artefacts that were renamed.",
        REACQUIRABLE="mostly, from Hugging Face", UNIQUE="no"),
    "Build-Outputs": dict(
        CATEGORY="build output", SUBCATEGORY="yocto and symoneural",
        DESCRIPTION="Completed build output. Yocto package trees by architecture "
                    "(arm, arm64, x86, x86-64; deb and ipk), images, SDKs, firmware, "
                    "manifests, and SyMoNeuRaL release output including DispatchOS.",
        KEYWORDS="yocto;bitbake;deb;ipk;firmware;dispatchos;packages",
        PROBLEM_DOMAIN="embedded build output",
        WHY_RETAINED="Rebuildable in principle, but only from a working build environment; "
                     "cheaper to keep than to reproduce.",
        REACQUIRABLE="by rebuild only", UNIQUE="yes"),
    "Projects": dict(
        CATEGORY="projects", SUBCATEGORY="active, archived and by domain",
        DESCRIPTION="Project trees organised by domain: active work, archived projects, "
                    "crypto and mining, database, host, GitHub mirrors, streaming, "
                    "web/ML, utilities and experimental.",
        KEYWORDS="projects;crypto;mining;streaming;database;utilities",
        PROBLEM_DOMAIN="project archive", WHY_RETAINED="Prior and adjacent project work.",
        REACQUIRABLE="partly", UNIQUE="mixed"),
    "Development-Reference": dict(
        CATEGORY="reference", SUBCATEGORY="SDKs, toolchains and research",
        DESCRIPTION="Third-party engineering reference: Apple SDKs and OSXCross, "
                    "NVIDIA/CUDA samples and libraries, cross-platform tooling, "
                    "toolchains, hardware profiles, Linux system material, networking, "
                    "security and AI research captures.",
        KEYWORDS="apple;xcode;osxcross;cuda;nvidia;tensorrt;sdk;toolchain",
        PROBLEM_DOMAIN="third-party engineering reference",
        WHY_RETAINED="Reference for builds that target other platforms.",
        REACQUIRABLE="yes, from upstream", UNIQUE="no"),
    "Virtualization": dict(
        CATEGORY="infrastructure", SUBCATEGORY="VM images and scripts",
        DESCRIPTION="Virtual machine images, provisioning scripts and documentation.",
        KEYWORDS="vm;qemu;image;rootfs;provisioning",
        PROBLEM_DOMAIN="host and VM setup", WHY_RETAINED="Host rebuild material.",
        REACQUIRABLE="partly", UNIQUE="mixed"),
    "Media": dict(
        CATEGORY="media", SUBCATEGORY="images, video and audio",
        DESCRIPTION="Images, wallpapers, imported albums, screenshots not tied to "
                    "SyMoNeuRaL UI history, video and audio.",
        KEYWORDS="images;screenshots;wallpapers;video;audio",
        PROBLEM_DOMAIN="personal and project media", WHY_RETAINED="Owner's media.",
        REACQUIRABLE="no", UNIQUE="yes"),
    "Personal": dict(
        CATEGORY="personal", SUBCATEGORY="documents, employment, HR, logistics",
        DESCRIPTION="The owner's personal documents, employment and HR material, "
                    "logistics and gaming settings. Not project material.",
        KEYWORDS="personal;documents;resume;hr;logistics",
        PROBLEM_DOMAIN="personal records", WHY_RETAINED="Owner's records.",
        REACQUIRABLE="no", UNIQUE="yes"),
    "Private": dict(
        CATEGORY="private", SUBCATEGORY="network configs and credential archive",
        DESCRIPTION="Network configuration and credential-bearing material, filed by path "
                    "and metadata only. Values are never printed, logged or catalogued.",
        KEYWORDS="vpn;wireguard;certificate;credential;token",
        PROBLEM_DOMAIN="secrets custody",
        WHY_RETAINED="Recovery of network and service access.",
        REACQUIRABLE="no", UNIQUE="yes",
        NOTES="Historical world-readable exposure is flagged for ROTATION separately; "
              "organising a secret is not remediating it."),
    "Historical-Archive": dict(
        CATEGORY="archive", SUBCATEGORY="machine backups and reviewed unclassified",
        DESCRIPTION="Whole-machine backups and the catalogued Unclassified-Reviewed "
                    "collection for objects that were inspected and found genuinely "
                    "ambiguous but worth keeping.",
        KEYWORDS="backup;archive;unclassified;reviewed",
        PROBLEM_DOMAIN="last-resort recovery",
        WHY_RETAINED="Whole-machine state that predates the current layout.",
        REACQUIRABLE="no", UNIQUE="yes"),
}


def sh(a, t=3600):
    return subprocess.run(a, capture_output=True, text=True, timeout=t)


def measure(path: str) -> tuple[int, int]:
    r = sh(["rclone", "size", f"{REMOTE}{path}", "--json"], 7200)
    if r.returncode != 0:
        return 0, 0
    try:
        j = json.loads(r.stdout)
        return int(j.get("bytes") or 0), int(j.get("count") or 0)
    except json.JSONDecodeError:
        return 0, 0


def formats(path: str, limit: int = 8) -> str:
    r = sh(["rclone", "lsf", f"{REMOTE}{path}", "--recursive", "--files-only"], 7200)
    if r.returncode != 0:
        return ""
    import collections
    c = collections.Counter(
        (pathlib.PurePath(x).suffix.lower() or "<none>") for x in r.stdout.splitlines())
    return ";".join(f"{e}:{n}" for e, n in c.most_common(limit))


def migration_rows() -> list[tuple[str, str, str, str, str]]:
    """Only operations the ledger records COMPLETE with a destination. A migration map that
    lists intentions rather than completions is worse than none."""
    if not STATE.is_file():
        return []
    ops = (json.loads(STATE.read_text()).get("ops") or {})
    rows = []
    for oid, o in sorted(ops.items()):
        if o.get("state") != "COMPLETE":
            continue
        dest = o.get("dest")
        src = o.get("src") or ""
        if not dest:
            continue
        rows.append((oid, src, dest, str(o.get("raw_bytes") or ""),
                     o.get("remote_md5") or ""))
    return rows


def build() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    os.chmod(OUT, 0o700)
    r = sh(["rclone", "lsjson", REMOTE], 3600)
    root = json.loads(r.stdout) if r.returncode == 0 else []
    dirs = sorted(x["Name"] for x in root if x.get("IsDir"))
    loose = [x["Name"] for x in root if not x.get("IsDir")]

    print(f"  root: {len(dirs)} collections, {len(loose)} loose objects")

    rows = []
    for d in dirs:
        b, c = measure(d)
        sem = SEMANTICS.get(d, {})
        rows.append({
            "COLLECTION_ID": d.replace(" ", "-").lower(),
            "CANONICAL_PATH": f"gdrive:{d}",
            "CATEGORY": sem.get("CATEGORY", "UNCLASSIFIED"),
            "SUBCATEGORY": sem.get("SUBCATEGORY", ""),
            "DESCRIPTION": sem.get("DESCRIPTION", ""),
            "KEYWORDS": sem.get("KEYWORDS", ""),
            "ORIGIN_PATHS": sem.get("ORIGIN_PATHS", "see MIGRATION-MAP.tsv"),
            "SIZE_BYTES": b, "FILE_COUNT": c,
            "IMPORTANT_FORMATS": formats(d),
            "RELATED_SYMONEURAL_COMPONENTS": sem.get("RELATED_SYMONEURAL_COMPONENTS", ""),
            "UPSTREAM_PROJECT": sem.get("UPSTREAM_PROJECT", ""),
            "UPSTREAM_REVISION": sem.get("UPSTREAM_REVISION",
                                         "per-snapshot; see Upstream-Source path"),
            "HISTORICAL_PERIOD": sem.get("HISTORICAL_PERIOD", "2025-12..2026-09"),
            "PROBLEM_DOMAIN": sem.get("PROBLEM_DOMAIN", ""),
            "KNOWN_WORKING_COMPONENTS": sem.get("KNOWN_WORKING_COMPONENTS", ""),
            "KNOWN_FAILURES": sem.get("KNOWN_FAILURES", ""),
            "RELEVANT_DOCS": sem.get("RELEVANT_DOCS",
                                     "ops/ops/backend/authority/docs/reference/EXTERNAL-KNOWLEDGE-CATALOG.md"),
            "WHY_RETAINED": sem.get("WHY_RETAINED", ""),
            "REACQUIRABLE": sem.get("REACQUIRABLE", "unknown"),
            "UNIQUE": sem.get("UNIQUE", "unknown"),
            "NOTES": sem.get("NOTES", ""),
        })

    cat = OUT / "CATALOG.tsv"
    with cat.open("w") as fh:
        fh.write("\t".join(CATALOG_COLUMNS) + "\n")
        for row in rows:
            fh.write("\t".join(str(row[c]).replace("\t", " ").replace("\n", " ")
                               for c in CATALOG_COLUMNS) + "\n")

    mm = OUT / "MIGRATION-MAP.tsv"
    mr = migration_rows()
    with mm.open("w") as fh:
        fh.write("OPERATION_ID\tOLD_PATH\tNEW_PATH\tSIZE_BYTES\tREMOTE_MD5\n")
        for a, b_, c_, d_, e in mr:
            fh.write(f"{a}\t{b_}\t{c_}\t{d_}\t{e}\n")

    dup = OUT / "DUPLICATES.tsv"
    if not dup.exists():
        dup.write_text("HASH\tSIZE_BYTES\tVICTIM_PATH\tSURVIVOR_PATH\tWHY\tACTION\n")

    unclassified = [r for r in rows if r["CATEGORY"] == "UNCLASSIFIED"]
    idx = OUT / "INDEX.md"
    idx.write_text(f"""# SyMoNeuRaL Drive — what is here and where to look

Generated {time.strftime('%Y-%m-%d')} from a measured inventory. `CATALOG.tsv` carries one
row per collection with sizes, formats and provenance; `MIGRATION-MAP.tsv` records every
completed move old path to new path with its verified MD5; `DUPLICATES.tsv` records every
redundant copy removed and the survivor that was verified first.

**The running server does not depend on this Drive.** Its weights, state and source are all
local. Everything here is history, reference and recovery material.

## The questions this store exists to answer

**Where are the original Qwen/OpenAI models?**
`Models/` — upstream distributions, conversion inputs and historical models, with
`Models/Historical/` holding earlier staging. The *running* weights are not here: they are
local at `backend/models/` under house names (`symon-1.0-*`, `symoneural-image-*`,
`symoneural-listen-*`), because the runtime must work with Drive unavailable.
`backend/models/PROVENANCE.json` maps every house name to its upstream repo and file.

**Where are old SyMoNeuRaL source and build snapshots?**
`Symoneural/History/Source-Snapshots/` and `Symoneural/History/Build-History/`. Pinned
third-party upstreams are separate, under `Symoneural/Upstream-Source/<project>/<revision>/`
— revision-keyed so a snapshot is identifiable rather than merely dated.

**Where are Yocto package and image outputs?**
`Build-Outputs/Yocto/` — `Packages/` by architecture (arm, arm64, x86, x86-64; deb and
ipk), plus `Images/`, `SDKs/`, `Firmware/`, `Manifests/` and `Historical/`. SyMoNeuRaL's own
release output, including DispatchOS, is under `Build-Outputs/Symoneural/`.

**Where are Apple and CUDA SDK references?**
`Development-Reference/Apple/` (SDKs, OSXCross, ML research) and
`Development-Reference/NVIDIA-CUDA/`. Toolchains sit under
`Development-Reference/Toolchains/`.

**Where are old miner and firmware projects?**
`Projects/Crypto/` — including `Reference-Source/` for cgminer trees and `Research/` for
blockchain proofs of concept. Miner firmware images are under
`Build-Outputs/Yocto/Firmware/`.

**Where are prior UI, screenshots and task histories?**
`Symoneural/History/Screenshots-and-UI-History/` and
`Symoneural/History/Task-and-Terminal-History/`. Agent sessions are under
`Symoneural/History/Agent-Sessions/`.

**Where are VM and host setup resources?**
`Virtualization/` for images and scripts; `Development-Reference/Linux-System/Host-Setup/`
for host provisioning.

**Where are archived projects by domain?**
`Projects/Archived/`, plus the domain collections `Projects/Crypto`, `Projects/Database`,
`Projects/Streaming`, `Projects/Web-ML`, `Projects/Utilities`, `Projects/Experimental` and
`Projects/GitHub-Mirrors`.

## Collections

| Collection | Size | Files | Category |
|---|---:|---:|---|
""" + "\n".join(
        f"| `{r['CANONICAL_PATH']}` | {r['SIZE_BYTES']/2**30:.2f} GiB | "
        f"{r['FILE_COUNT']} | {r['CATEGORY']} |" for r in rows) + f"""

## Conventions worth knowing before you go looking

**Large collections travel as one archive per semantic leaf, each beside a
`.CONTENTS.tsv`.** A 105,851-file package tree cannot be uploaded file-by-file against an
8-request/second API limit, so `/yocto/artifacts` is six objects keyed by architecture
rather than one blob or a hundred thousand objects. The sibling manifest records TYPE,
RELPATH, SIZE_BYTES, SHA256, MODE and LINK_TARGET for everything inside, so you can see
what an archive contains without downloading it — and dedupe can compare contents rather
than guessing from filenames.

**Symlinks are recorded, never followed.** A manifest row of type `SYMLINK` carries its
`LINK_TARGET` as the identity.

**`Historical-Archive/Unclassified-Reviewed/<date>/` means inspected, not ignored.**
Objects land there only after being examined and found genuinely ambiguous but worth
keeping. It is catalogued, which is what separates it from a folder called `misc`.

**Nothing here is named `misc`, `stuff`, `organize`, `offload`, `old2` or `backup2`.** Those
buckets existed and were dissolved into the collections above; `MIGRATION-MAP.tsv` records
where each of their children went.

{"**Unclassified collections remaining: " + ", ".join('`'+r['COLLECTION_ID']+'`' for r in unclassified) + "** — these have no semantic row yet and are a gap, not a category." if unclassified else "Every top-level collection has a catalogued meaning."}
""")
    for f in (cat, mm, dup, idx):
        os.chmod(f, 0o600)
    print(f"  CATALOG.tsv        {len(rows)} collections, {len(CATALOG_COLUMNS)} columns")
    print(f"  MIGRATION-MAP.tsv  {len(mr)} completed moves")
    print(f"  INDEX.md           {len(idx.read_text().splitlines())} lines")
    print(f"  unclassified       {len(unclassified)}")
    return 0


def upload() -> int:
    rc = 0
    for name in ("INDEX.md", "CATALOG.tsv", "MIGRATION-MAP.tsv", "DUPLICATES.tsv"):
        f = OUT / name
        if not f.is_file():
            print(f"  {name}: not built"); rc = 1; continue
        local = hashlib.md5(f.read_bytes()).hexdigest()
        r = sh(["rclone", "copy", str(f), REMOTE, "--checksum"], 1800)
        if r.returncode != 0:
            print(f"  {name}: upload failed {r.stderr.strip()[:100]}"); rc = 1; continue
        h = sh(["rclone", "hashsum", "md5", f"{REMOTE}{name}"], 900)
        remote = h.stdout.split()[0] if h.stdout.strip() else None
        ok = remote == local
        print(f"  {name}: {'VERIFIED' if ok else f'MISMATCH local={local} remote={remote}'}")
        rc = rc or (0 if ok else 1)
    return rc


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["build", "upload"])
    a = ap.parse_args(argv)
    return build() if a.cmd == "build" else upload()


if __name__ == "__main__":
    raise SystemExit(main(__import__("sys").argv[1:]))
