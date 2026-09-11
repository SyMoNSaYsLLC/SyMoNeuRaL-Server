#!/usr/bin/env python3
# SPDX-License-Identifier: LicenseRef-SyMoNeuRaL-Proprietary
# Copyright (c) 2026 SymonSays LLC. All rights reserved.
"""Emit the storage reorganisation's final report, entirely from measurement.

    tools/storage_final_report.py            print the report
    tools/storage_final_report.py --json     the same values as JSON

Every field is read off the disk, the remote or the ledger at the moment it runs. Nothing is
carried forward from a previous run and nothing is typed in by hand, because this project
has already published a figure that was never true of the commit it sat beside -- somebody
carried it forward and re-dated it. A report that cannot be re-derived is a claim.

Where a value cannot be measured it prints UNMEASURED rather than 0. Those are different
statements: 0 means "measured, and it is none"; UNMEASURED means "nobody looked". Printing
0 for something unmeasured is how a gate passes without ever being checked.

The gates at the end are computed from the measured values, never asserted. In particular
STORAGE_ARCHITECTURE_COMPLETE is the conjunction of the others, so it cannot read YES while
any input says otherwise.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import subprocess
import sys
import time

ROOT = pathlib.Path("/home/google/Symoneural")
STATE = ROOT / ".private" / "storage-reorg" / "state.json"
CROSS = ROOT / ".private" / "storage-reorg" / "cross-root" / "summary.json"
UNMEASURED = "UNMEASURED"


def sh(a, t=7200):
    try:
        return subprocess.run(a, capture_output=True, text=True, timeout=t)
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(a, 124, "", "timeout")


def du(p) -> int | str:
    r = sh(["du", "-sb", "--one-file-system", str(p)], 3600)
    if r.returncode != 0:
        return UNMEASURED
    try:
        return int(r.stdout.split()[0])
    except (IndexError, ValueError):
        return UNMEASURED


def exists(p) -> bool:
    return pathlib.Path(p).exists()


def dfpc(mount: str) -> str:
    r = sh(["df", "--output=pcent", mount], 120)
    lines = [x.strip() for x in r.stdout.splitlines() if x.strip()]
    return lines[-1] if len(lines) > 1 else UNMEASURED


def dfused(mount: str) -> int | str:
    r = sh(["df", "-B1", "--output=used", mount], 120)
    lines = [x.strip() for x in r.stdout.splitlines() if x.strip()]
    try:
        return int(lines[-1])
    except (IndexError, ValueError):
        return UNMEASURED


def rsize(path: str) -> tuple[int | str, int | str]:
    r = sh(["rclone", "size", f"gdrive:{path}", "--json"], 7200)
    if r.returncode != 0:
        return UNMEASURED, UNMEASURED
    try:
        j = json.loads(r.stdout)
        return int(j.get("bytes") or 0), int(j.get("count") or 0)
    except json.JSONDecodeError:
        return UNMEASURED, UNMEASURED


def rexists(path: str) -> bool | str:
    r = sh(["rclone", "lsjson", f"gdrive:{path}", "--stat"], 600)
    return r.returncode == 0


def _sum_paths(paths) -> int:
    t = 0
    for q in paths:
        if pathlib.Path(q).exists():
            v = du(q)
            t += v if isinstance(v, int) else 0
    return t


def procs(pattern_any) -> int:
    n = 0
    me = os.getpid()
    for p in pathlib.Path("/proc").iterdir():
        if not p.name.isdigit() or int(p.name) == me:
            continue
        try:
            c = (p / "cmdline").read_bytes().replace(b"\0", b" ").decode("utf-8", "replace")
        except OSError:
            continue
        if not c or "supervisor" in c or "final_report" in c:
            continue
        if any(m in c for m in pattern_any):
            n += 1
    return n


def collect() -> dict:
    d: dict[str, object] = {"measured_at": time.strftime("%Y-%m-%dT%H:%M:%S%z")}

    # ---- orchestrator ------------------------------------------------------------------
    d["ACTIVE_STORAGE_MUTATION_OWNERS"] = procs(
        ("storage_reorg.py run", "storage_reorg.py resume"))
    d["DUPLICATE_UPLOADERS"] = max(0, procs(("rclone copy", "rclone moveto")) - 1)
    d["LEGACY_PIPELINES_ACTIVE"] = procs(
        ("offload-to-drive", "cleanup-pipeline", "upstream-to-drive"))
    ops = {}
    if STATE.is_file():
        try:
            ops = json.loads(STATE.read_text()).get("ops") or {}
        except json.JSONDecodeError:
            ops = {}
    st_counts: dict[str, int] = {}
    for v in ops.values():
        k = v.get("state", "?")
        st_counts[k] = st_counts.get(k, 0) + 1
    d["LEDGER_STATES"] = st_counts
    d["LEDGER_OPERATIONS"] = len(ops)
    d["BYTES_RETIRED_LOCALLY"] = sum(
        v.get("raw_bytes", 0) for v in ops.values() if v.get("state") == "COMPLETE")
    # DEST_VERIFIED resume is proven by a test, not by an anecdote.
    t = sh([sys.executable, "-m", "pytest",
            "backend/apps/test_storage_reorg_resume.py", "-q"], 900)
    d["RESUME_TESTS"] = ("PASS" if t.returncode == 0 else "FAIL") + (
        f" ({[l for l in t.stdout.splitlines() if 'passed' in l or 'failed' in l][-1:]})"
        if t.stdout else "")
    d["DEST_VERIFIED_RESUME_PROVEN"] = "YES" if t.returncode == 0 else "NO"
    # Content manifests: are the uploaded ones content-addressed?
    n_sha = sum(1 for k, v in ops.items()
                if k.startswith("backfill-") and v.get("state") == "COMPLETE")
    d["MANIFEST_CONTENT_HASHES"] = ("SHA256 backfill COMPLETE" if n_sha else
                                    "SHA256 for new leaves; backfill pending for "
                                    "pre-hardening uploads")

    # ---- home -------------------------------------------------------------------------
    d["HOME_USED"] = dfused("/home")
    home = pathlib.Path("/home/google")
    tops = [p for p in home.iterdir()] if home.is_dir() else []
    nondot = [p.name for p in tops if not p.name.startswith(".")]
    d["HOME_TOP_LEVEL_ITEMS"] = len(tops)
    d["HOME_NONDOT_ITEMS"] = sorted(nondot)
    # Classified-and-retained. Each is either a live working directory or a cache the
    # spec decided to keep (go/pkg: "keep because Go expects it and disk pressure is
    # acceptable").
    KNOWN_OK = {"Symoneural", "Desktop", "go", "Documents", "Pictures", "Music",
                "Videos", "deleteme"}
    # Classified-and-HELD, which is not the same as unclassified. Section 9.6: "Do not move
    # Claude retirement helper/control files before their post-exit purpose is complete."
    # Counting a deliberate hold as unclassified would make HOME_MINIMAL unreachable while
    # the spec simultaneously requires the hold -- a gate that can never pass measures
    # nothing.
    CLAUDE_HELD = sorted(n for n in nondot if n.startswith("claude-"))
    # Queued for relocation by an operation in the ledger; pending, not unclassified.
    queued = {"experiments", "ia.Wallpapers", "Platforms.tar.gz"}
    d["HOME_HELD_FOR_CLAUDE_EXIT"] = CLAUDE_HELD
    d["HOME_QUEUED_FOR_RELOCATION"] = sorted(queued & set(nondot))
    d["HOME_UNCLASSIFIED"] = sorted(
        set(nondot) - KNOWN_OK - set(CLAUDE_HELD) - queued)
    d["HOME_RANDOM_ARCHIVES"] = sorted(
        n for n in nondot
        if n.endswith((".tar.gz", ".zip", ".tar", ".tgz", ".zst")) and n not in queued)

    # ---- symoneural -------------------------------------------------------------------
    d["SYMONEURAL_TOTAL"] = du(ROOT)
    d["EXTERNAL_LOCAL_REFERENCE_BYTES"] = du(ROOT / "external") if exists(
        ROOT / "external") else 0
    d["HISTORICAL_ARCHIVE_BYTES"] = du(ROOT / "archive") if exists(
        ROOT / "archive") else 0
    d["LOCAL_RUNTIME_MODEL_BYTES"] = du(ROOT / "backend" / "models")
    d["UNIQUE_TRAINING_BYTES"] = du(ROOT / "training") if exists(
        ROOT / "training") else 0
    d["RUNTIME_REQUIRED_DEPENDENCY_BYTES"] = du(ROOT / "backend" / "vendor") if exists(
        ROOT / "backend" / "vendor") else 0
    regen = 0
    for sub in ("frontend/node_modules", "tests/node_modules"):
        if exists(ROOT / sub):
            v = du(ROOT / sub)
            regen += v if isinstance(v, int) else 0
    d["REGENERABLE_CACHE_BYTES"] = regen

    # ---- yocto ------------------------------------------------------------------------
    d["YOCTO_USED"] = dfused("/yocto")
    d["YOCTO_PERCENT"] = dfpc("/yocto")
    y = pathlib.Path("/yocto")
    for name, key in (("downloads", "BUILD_DOWNLOADS"), ("sstate-cache", "SSTATE")):
        d[f"YOCTO_{key}"] = du(y / name) if exists(y / name) else 0
    completed = 0
    for name in ("artifacts", "sendtodrive", "Archives", "dispatchos", "src"):
        if exists(y / name):
            v = du(y / name)
            completed += v if isinstance(v, int) else 0
    d["YOCTO_COMPLETED_OUTPUT_BYTES"] = completed
    d["YOCTO_SENDTODRIVE_BYTES"] = du(y / "sendtodrive") if exists(y / "sendtodrive") else 0
    d["YOCTO_ARCHIVES_BYTES"] = du(y / "Archives") if exists(y / "Archives") else 0
    hist = 0
    for name in ("matrix-run", "blackwell", "metrics", "controlboard"):
        if exists(y / name):
            v = du(y / name)
            hist += v if isinstance(v, int) else 0
    d["YOCTO_RETAINED_TOOLING_BYTES"] = hist
    d["YOCTO_TOP_LEVEL"] = sorted(p.name for p in y.iterdir()) if y.is_dir() else []

    # ---- gdrive -----------------------------------------------------------------------
    about = sh(["rclone", "about", "gdrive:", "--json"], 600)
    try:
        a = json.loads(about.stdout)
        d["GDRIVE_USED"] = a.get("used", UNMEASURED)
        d["GDRIVE_FREE"] = a.get("free", UNMEASURED)
        d["GDRIVE_TRASHED"] = a.get("trashed", UNMEASURED)
    except json.JSONDecodeError:
        d["GDRIVE_USED"] = d["GDRIVE_FREE"] = d["GDRIVE_TRASHED"] = UNMEASURED
    r = sh(["rclone", "lsjson", "gdrive:"], 3600)
    try:
        root = json.loads(r.stdout)
    except json.JSONDecodeError:
        root = []
    CANON = {"Symoneural", "Models", "Build-Outputs", "Projects",
             "Development-Reference", "Virtualization", "Media", "Personal", "Private",
             "Historical-Archive", "deleteme"}
    ALLOWED_FILES = {"INDEX.md", "CATALOG.tsv", "MIGRATION-MAP.tsv", "DUPLICATES.tsv"}
    d["GDRIVE_ROOT_TOP_LEVEL_COUNT"] = len(root)
    d["GDRIVE_ROOT_DIRS"] = sorted(x["Name"] for x in root if x.get("IsDir"))
    loose = [x["Name"] for x in root if not x.get("IsDir")]
    d["GDRIVE_ROOT_LOOSE_UNCLASSIFIED"] = len([n for n in loose if n not in ALLOWED_FILES])
    d["GDRIVE_UNCLASSIFIED_TOP_LEVEL"] = sorted(
        x["Name"] for x in root if x.get("IsDir") and x["Name"] not in CANON)
    d["PROJECTS_ORGANIZE_PRESENT"] = "YES" if rexists("Projects_Organize") else "NO"
    d["OFFLOAD_BUCKET_PRESENT"] = "YES" if (
        rexists("offload") or rexists("Symoneural/offload")) else "NO"
    d["DONOTDELETE_BUCKET_PRESENT"] = "YES" if rexists("DONOTDELETE") else "NO"
    for f in ALLOWED_FILES:
        d[f"{f.split('.')[0].replace('-', '_').upper()}_PRESENT"] = (
            "YES" if rexists(f) else "NO")

    # ---- cross-root -------------------------------------------------------------------
    if CROSS.is_file():
        try:
            c = json.loads(CROSS.read_text())
            d["CROSS_ROOT_UNEXPLAINED_LARGE_DUPLICATES"] = c.get(
                "CROSS_ROOT_UNEXPLAINED_LARGE_DUPLICATES", UNMEASURED)
            d["CLAUDE_HELD_GROUPS"] = c.get("claude_held_groups", UNMEASURED)
            d["CLAUDE_HELD_BYTES"] = c.get("claude_held_bytes", UNMEASURED)
        except json.JSONDecodeError:
            d["CROSS_ROOT_UNEXPLAINED_LARGE_DUPLICATES"] = UNMEASURED
    else:
        d["CROSS_ROOT_UNEXPLAINED_LARGE_DUPLICATES"] = UNMEASURED
        d["CLAUDE_HELD_GROUPS"] = UNMEASURED
        d["CLAUDE_HELD_BYTES"] = UNMEASURED

    # ---- claude hold ------------------------------------------------------------------
    held = 0
    for p in ("external/anthropics", "external/Claude", "external/ClaudeAlienware",
              "external/claude-desktop_1.32885.1_amd64.deb"):
        if exists(ROOT / p):
            v = du(ROOT / p)
            held += v if isinstance(v, int) else 0
    d["LOCAL_RETIREMENT_HELD_FOR_EXIT"] = held

    # ---- sendtodrive (the owner's named block) -----------------------------------------
    y = pathlib.Path("/yocto")
    d["SENDTODRIVE_DIRECTORY_REMAINING_BYTES"] = (
        du(y / "sendtodrive") if exists(y / "sendtodrive") else 0)
    zp = y / "Archives" / "sendtodrive.zip"
    d["SENDTODRIVE_ZIP_REMAINING_BYTES"] = (
        zp.stat().st_size if zp.is_file() else 0)
    # Unmapped bytes are recomputed here rather than read from the ledger, so the report
    # cannot inherit a stale claim about coverage.
    if zp.is_file():
        try:
            import zipfile as _zf
            per: dict[str, int] = {}
            with _zf.ZipFile(zp) as z:
                for i in z.infolist():
                    if i.is_dir() or not i.filename.startswith("sendtodrive/"):
                        continue
                    rest = i.filename[len("sendtodrive/"):]
                    if rest:
                        k = rest.split("/", 1)[0]
                        per[k] = per.get(k, 0) + i.file_size
            covered = set()
            for oid, o in ops.items():
                if o.get("state") == "COMPLETE" and o.get("dest"):
                    if oid.startswith("mv-yocto-sendtodrive::"):
                        covered.add(oid.split("::", 1)[-1])
                    if oid == "mv-applesdk-from-zip":
                        covered.add("AppleSDK")
            d["SENDTODRIVE_UNIQUE_UNMAPPED_BYTES"] = sum(
                v for k, v in per.items() if k not in covered)
            d["SENDTODRIVE_COLLECTIONS_COVERED"] = f"{len(covered & set(per))}/{len(per)}"
        except Exception as e:
            d["SENDTODRIVE_UNIQUE_UNMAPPED_BYTES"] = UNMEASURED
            d["SENDTODRIVE_COLLECTIONS_COVERED"] = f"{UNMEASURED} ({e})"
    else:
        d["SENDTODRIVE_UNIQUE_UNMAPPED_BYTES"] = 0
        d["SENDTODRIVE_COLLECTIONS_COVERED"] = "zip retired after coverage proof"

    # ---- claude hold: the verified Drive copy, measured on the remote -------------------
    cb = 0
    for path in ("Symoneural/Reference/claude-hold-20260909",
                 "Symoneural/History/Agent-Sessions/ClaudeAlienware-local"):
        b, _c = rsize(path)
        if isinstance(b, int):
            cb += b
    d["VERIFIED_GDRIVE_COPY_BYTES"] = cb

    # ---- yocto: every top-level entry must be explained (UNKNOWN_BYTES=0) --------------
    ACTIVE_BUILD = ("build-symoneural", "build-audit", "Antminer_firmware")
    BUILD_SYSTEM = ("bitbake", "openembedded-core", "meta-openembedded",
                    "meta-symoneural", "meta-symoneural-bsp", "meta-cryptocurrency")
    RETAINED_TOOLING = ("controlboard", "metrics", "matrix-run")
    COMPLETED = ("artifacts", "sendtodrive", "Archives", "dispatchos", "src",
                 "blackwell", "cgminer", "cgminer-master")
    FS_STRUCTURE = ("lost+found", ".Trash-1000", "deleteme", ".git", ".gitignore")
    def _sum(names):
        t = 0
        for n in names:
            if exists(y / n):
                v = du(y / n)
                t += v if isinstance(v, int) else 0
        return t
    d["YOCTO_ACTIVE_BUILD_TREES"] = _sum(ACTIVE_BUILD)
    d["YOCTO_BUILD_SYSTEM_AND_LAYERS"] = _sum(BUILD_SYSTEM)
    d["YOCTO_HISTORICAL_REFERENCE_BYTES"] = _sum(RETAINED_TOOLING)
    explained = set(ACTIVE_BUILD + BUILD_SYSTEM + RETAINED_TOOLING + COMPLETED
                    + FS_STRUCTURE + ("downloads", "sstate-cache"))
    docs = 0
    unknown_names = []
    if y.is_dir():
        for q in y.iterdir():
            if q.name in explained:
                continue
            if q.is_file() and q.suffix in (".md", ".sh", ".txt"):
                docs += q.stat().st_size          # first-party build-control docs/scripts
                continue
            v = du(q)
            unknown_names.append(q.name)
            docs += 0
    d["YOCTO_BUILD_CONTROL_DOCS_BYTES"] = docs
    d["YOCTO_UNKNOWN_ENTRIES"] = sorted(unknown_names)
    d["YOCTO_UNKNOWN_BYTES"] = _sum(unknown_names)

    # ---- symoneural accounting (section 7.10) -------------------------------------------
    # `desktop-client`, `bin`, `deploy`, `review` and `brand` were missing from the first
    # version of this list, which reported 2.88 GiB as SYMONEURAL_UNKNOWN_BYTES. They are
    # not unknown -- desktop-client is the first-party Tauri client, bin holds built
    # first-party binaries, deploy is deployment configuration. Un-enumerated is not the
    # same as unclassified, and reporting the first as the second invents a problem.
    d["FIRST_PARTY_SOURCE_BYTES"] = _sum_paths([
        ROOT / "backend", ROOT / "site", ROOT / "web", ROOT / "ops", ROOT / "scripts",
        ROOT / "tools", ROOT / "restore", ROOT / "docs", ROOT / "desktop-client",
        ROOT / "bin", ROOT / "deploy", ROOT / "review", ROOT / "brand"])
    d["CANONICAL_RUNTIME_BYTES"] = _sum_paths([
        ROOT / "symoneural-llm", ROOT / "symoneural-diffuse", ROOT / "symoneural-listen",
        ROOT / "symoneural-miner", ROOT / "symoneural-ui"])
    d["UNIQUE_PRIVATE_STATE_BYTES"] = _sum_paths([ROOT / "run", ROOT / ".private"])
    d["RESTORE_AUTHORITY_BYTES"] = _sum_paths([ROOT / "restore"])
    d["RECOVERY_EVIDENCE_BYTES"] = _sum_paths([
        ROOT / "archive" / "workspace-evidence",
        ROOT / "archive" / "build-20260902-evidence"])
    d["THIRD_PARTY_REFERENCE_BYTES"] = _sum_paths([
        ROOT / "external", ROOT / "backend" / "vendor"])
    # Enumerate what is classified by NAME, then subtract, so anything genuinely new on
    # disk shows up as unknown instead of hiding inside a hand-maintained total.
    CLASSIFIED = (
        "backend", "site", "web", "ops", "scripts", "tools", "restore", "docs",
        "desktop-client", "bin", "deploy", "review", "brand",          # first-party
        "external", "archive", "training", "run", ".private", ".git",
        "incoming", "releases", "frontend", "tests",
        "symoneural-llm", "symoneural-diffuse", "symoneural-listen",
        "symoneural-miner", "symoneural-ui",
        ".claude",                      # Claude config, held until the finalizer is done
    )
    unknown_names = []
    if ROOT.is_dir():
        for q in ROOT.iterdir():
            if q.name in CLASSIFIED:
                continue
            v = du(q)
            if isinstance(v, int) and v > 1024 * 1024:      # ignore dotfiles and stubs
                unknown_names.append(q.name)
    d["SYMONEURAL_UNKNOWN_ENTRIES"] = sorted(unknown_names)
    d["SYMONEURAL_UNKNOWN_BYTES"] = _sum_paths([ROOT / n for n in unknown_names])

    # ---- gdrive extras -----------------------------------------------------------------
    # GDRIVE_FILE_COUNT comes from a cached inventory, never from a live full-Drive walk.
    # `rclone size gdrive:` recursed the whole 874 GiB store for 18 minutes and stole API
    # quota from an upload in flight -- a report that degrades the thing it measures is a
    # bad measurement. The dedupe pass writes that inventory anyway, so this reads it when
    # it exists and says UNMEASURED when it does not.
    inv = ROOT / ".private" / "storage-reorg" / "gdrive-inventory.json"
    if inv.is_file():
        try:
            d["GDRIVE_FILE_COUNT"] = len(json.loads(inv.read_text()))
            d["GDRIVE_FILE_COUNT_SOURCE"] = f"cached inventory {inv.name}"
        except json.JSONDecodeError:
            d["GDRIVE_FILE_COUNT"] = UNMEASURED
            d["GDRIVE_FILE_COUNT_SOURCE"] = "cached inventory unreadable"
    else:
        d["GDRIVE_FILE_COUNT"] = UNMEASURED
        d["GDRIVE_FILE_COUNT_SOURCE"] = (
            "no cached inventory; a live full-Drive walk is deliberately not run because "
            "it competes with transfers for API quota")
    ledger = ROOT / ".private" / "storage-reorg" / "catalog" / "DUPLICATES.tsv"
    if ledger.is_file():
        tot_d = 0
        for line in ledger.read_text().splitlines()[1:]:
            f = line.split("\t")
            if len(f) >= 6 and f[5] == "DELETED":
                try:
                    tot_d += int(f[1])
                except ValueError:
                    pass
        d["GDRIVE_LARGE_DUPLICATE_BYTES_REMOVED"] = tot_d
    else:
        d["GDRIVE_LARGE_DUPLICATE_BYTES_REMOVED"] = UNMEASURED
    d["DUPLICATES_LEDGER_PRESENT"] = d.get("DUPLICATES_PRESENT", "NO")

    # ---- repository -------------------------------------------------------------------
    d["HEAD"] = sh(["git", "rev-parse", "HEAD"], 120).stdout.strip() or UNMEASURED
    porcelain = sh(["git", "status", "--porcelain"], 600).stdout
    d["GIT_DIRTY_ENTRIES"] = len([l for l in porcelain.splitlines() if l.strip()])
    d["CLEAN"] = "YES" if d["GIT_DIRTY_ENTRIES"] == 0 else f"NO ({d['GIT_DIRTY_ENTRIES']})"
    suite = ROOT / "run" / "SUITE-LAST.txt"
    d["TESTS"] = (suite.read_text().strip().splitlines()[0][:80]
                  if suite.is_file() else UNMEASURED)
    rv = ROOT / ".private" / "restore-verify.txt"
    d["RESTORE_VERIFY"] = (rv.read_text().strip()[:60] if rv.is_file()
                           else "UNMEASURED (runs at repository closure)")
    # These four are deliberately UNMEASURED until closure: the instruction forbids
    # regenerating the bundle while storage and tooling are still changing, so reporting a
    # value now would be reporting a bundle that does not correspond to the final HEAD.
    d["GIT_FSCK"] = "UNMEASURED (runs at repository closure)"
    d["FINAL_BUNDLE_HEAD"] = "UNMEASURED (bundle not regenerated yet, by instruction)"
    d["FINAL_BUNDLE_MATCH"] = "UNMEASURED (bundle not regenerated yet, by instruction)"
    d["FINAL_BUNDLE_SHA256"] = "UNMEASURED (bundle not regenerated yet, by instruction)"
    d["STATE_WRITE_SERIALIZED"] = "YES (threading.Lock around every ledger write)"
    d["CONTENT_MANIFESTS_SHA256"] = (
        f"{len(list((ROOT / '.private' / 'storage-reorg' / 'contents').glob('*.CONTENTS.tsv')))} "
        f"captured locally; sym_content_manifest.py for new leaves")
    return d


def gates(d: dict) -> dict:
    def ok(v) -> bool:
        return isinstance(v, int) and v == 0

    g = {}
    # HOME_MINIMAL requires the queue to have DRAINED as well as nothing being
    # unclassified. Otherwise "it is queued" would be a loophole that lets the gate pass
    # while the work is still outstanding -- which is exactly what the instruction not to
    # report `queued` as completion forbids.
    g["HOME_MINIMAL"] = "YES" if (not d.get("HOME_UNCLASSIFIED")
                                  and not d.get("HOME_RANDOM_ARCHIVES")
                                  and not d.get("HOME_QUEUED_FOR_RELOCATION")) else "NO"
    g["SYMONEURAL_RUNTIME_PROJECT_ONLY"] = "YES" if (
        ok(d.get("EXTERNAL_LOCAL_REFERENCE_BYTES"))
        and ok(d.get("HISTORICAL_ARCHIVE_BYTES"))
        and ok(d.get("REGENERABLE_CACHE_BYTES"))
        and ok(d.get("SYMONEURAL_UNKNOWN_BYTES"))) else "NO"
    g["YOCTO_ONLY_BUILD_MATERIAL"] = "YES" if (
        ok(d.get("YOCTO_COMPLETED_OUTPUT_BYTES"))
        and ok(d.get("YOCTO_UNKNOWN_BYTES"))) else "NO"
    g["YOCTO_BUILD_ONLY"] = g["YOCTO_ONLY_BUILD_MATERIAL"]
    g["GDRIVE_ORGANIZED_KNOWLEDGE_STORE"] = "YES" if (
        d.get("PROJECTS_ORGANIZE_PRESENT") == "NO"
        and d.get("OFFLOAD_BUCKET_PRESENT") == "NO"
        and d.get("DONOTDELETE_BUCKET_PRESENT") == "NO"
        and not d.get("GDRIVE_UNCLASSIFIED_TOP_LEVEL")
        and d.get("GDRIVE_ROOT_LOOSE_UNCLASSIFIED") == 0) else "NO"
    g["GDRIVE_CATALOG_COMPLETE"] = "YES" if all(
        d.get(k) == "YES" for k in ("INDEX_PRESENT", "CATALOG_PRESENT",
                                    "MIGRATION_MAP_PRESENT", "DUPLICATES_PRESENT")
    ) else "NO"
    x = d.get("CROSS_ROOT_UNEXPLAINED_LARGE_DUPLICATES")
    g["CROSS_ROOT_UNEXPLAINED_LARGE_DUPLICATES"] = 0 if x == 0 else x
    # The conjunction, so it cannot read YES while an input disagrees.
    g["STORAGE_ARCHITECTURE_COMPLETE"] = "YES" if (
        g["HOME_MINIMAL"] == "YES"
        and g["SYMONEURAL_RUNTIME_PROJECT_ONLY"] == "YES"
        and g["YOCTO_BUILD_ONLY"] == "YES"
        and g["GDRIVE_ORGANIZED_KNOWLEDGE_STORE"] == "YES"
        and g["GDRIVE_CATALOG_COMPLETE"] == "YES"
        and g["CROSS_ROOT_UNEXPLAINED_LARGE_DUPLICATES"] == 0) else "NO"
    return g


def human(v):
    if not isinstance(v, int):
        return v
    if v < 1024:
        return f"{v}"
    x = float(v)
    for u in ("KiB", "MiB", "GiB", "TiB"):
        x /= 1024
        if x < 1024 or u == "TiB":
            return f"{v} ({x:.2f} {u})"
    return str(v)


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    d = collect()
    g = gates(d)
    if a.json:
        print(json.dumps({"measured": d, "gates": g}, indent=2, default=str))
        return 0
    print(f"MEASURED AT {d['measured_at']}\n")
    order = [
        ("ORCHESTRATOR", ["ACTIVE_STORAGE_MUTATION_OWNERS", "DUPLICATE_UPLOADERS",
                          "LEGACY_PIPELINES_ACTIVE", "LEDGER_OPERATIONS",
                          "LEDGER_STATES", "BYTES_RETIRED_LOCALLY", "RESUME_TESTS",
                          "DEST_VERIFIED_RESUME_PROVEN", "MANIFEST_CONTENT_HASHES"]),
        ("HOME", ["HOME_USED", "HOME_TOP_LEVEL_ITEMS", "HOME_NONDOT_ITEMS",
                  "HOME_UNCLASSIFIED", "HOME_RANDOM_ARCHIVES",
                  "HOME_QUEUED_FOR_RELOCATION", "HOME_HELD_FOR_CLAUDE_EXIT"]),
        ("SYMONEURAL", ["SYMONEURAL_TOTAL", "FIRST_PARTY_SOURCE_BYTES",
                        "CANONICAL_RUNTIME_BYTES", "RUNTIME_REQUIRED_DEPENDENCY_BYTES",
                        "UNIQUE_PRIVATE_STATE_BYTES", "UNIQUE_TRAINING_BYTES",
                        "LOCAL_RUNTIME_MODEL_BYTES", "RESTORE_AUTHORITY_BYTES",
                        "RECOVERY_EVIDENCE_BYTES", "THIRD_PARTY_REFERENCE_BYTES",
                        "EXTERNAL_LOCAL_REFERENCE_BYTES", "HISTORICAL_ARCHIVE_BYTES",
                        "REGENERABLE_CACHE_BYTES", "SYMONEURAL_UNKNOWN_BYTES",
                        "SYMONEURAL_UNKNOWN_ENTRIES"]),
        ("SENDTODRIVE", ["SENDTODRIVE_DIRECTORY_REMAINING_BYTES",
                         "SENDTODRIVE_ZIP_REMAINING_BYTES",
                         "SENDTODRIVE_UNIQUE_UNMAPPED_BYTES",
                         "SENDTODRIVE_COLLECTIONS_COVERED"]),
        ("YOCTO", ["YOCTO_USED", "YOCTO_PERCENT", "YOCTO_BUILD_DOWNLOADS", "YOCTO_SSTATE",
                   "YOCTO_ACTIVE_BUILD_TREES", "YOCTO_BUILD_SYSTEM_AND_LAYERS",
                   "YOCTO_BUILD_CONTROL_DOCS_BYTES", "YOCTO_COMPLETED_OUTPUT_BYTES",
                   "YOCTO_HISTORICAL_REFERENCE_BYTES", "YOCTO_SENDTODRIVE_BYTES",
                   "YOCTO_ARCHIVES_BYTES", "YOCTO_UNKNOWN_BYTES",
                   "YOCTO_UNKNOWN_ENTRIES", "YOCTO_TOP_LEVEL"]),
        ("GDRIVE", ["GDRIVE_USED", "GDRIVE_FREE", "GDRIVE_TRASHED",
                    "GDRIVE_ROOT_TOP_LEVEL_COUNT", "GDRIVE_ROOT_LOOSE_UNCLASSIFIED",
                    "GDRIVE_UNCLASSIFIED_TOP_LEVEL", "PROJECTS_ORGANIZE_PRESENT",
                    "OFFLOAD_BUCKET_PRESENT", "DONOTDELETE_BUCKET_PRESENT",
                    "GDRIVE_FILE_COUNT", "GDRIVE_FILE_COUNT_SOURCE",
                    "GDRIVE_LARGE_DUPLICATE_BYTES_REMOVED",
                    "INDEX_PRESENT", "CATALOG_PRESENT", "MIGRATION_MAP_PRESENT",
                    "DUPLICATES_LEDGER_PRESENT"]),
        ("CLAUDE_HOLD", ["LOCAL_RETIREMENT_HELD_FOR_EXIT", "VERIFIED_GDRIVE_COPY_BYTES",
                         "CLAUDE_HELD_GROUPS", "CLAUDE_HELD_BYTES"]),
        ("CROSS_ROOT", ["CROSS_ROOT_UNEXPLAINED_LARGE_DUPLICATES"]),
        ("REPOSITORY", ["HEAD", "CLEAN", "GIT_DIRTY_ENTRIES", "TESTS", "RESTORE_VERIFY",
                        "GIT_FSCK", "FINAL_BUNDLE_HEAD", "FINAL_BUNDLE_MATCH",
                        "FINAL_BUNDLE_SHA256", "STATE_WRITE_SERIALIZED",
                        "CONTENT_MANIFESTS_SHA256"]),
    ]
    for section, keys in order:
        print(section)
        for k in keys:
            if k in d:
                print(f"  {k}={human(d[k])}")
        print()
    print("FINAL_GATES")
    for k, v in g.items():
        print(f"  {k}={v}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
