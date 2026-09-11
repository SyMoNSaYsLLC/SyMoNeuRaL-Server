#!/usr/bin/env python3
# SPDX-License-Identifier: LicenseRef-SyMoNeuRaL-Proprietary
# Copyright (c) 2026 SymonSays LLC. All rights reserved.
# SyMoNeuRaL is a subdivision of SymonSays LLC. Licence: /LICENSE at the repository root.
"""Populate `.private/` -- the half of a bare-metal restore that Git cannot hold.

Six jobs, each of which fails loudly rather than partially:

    upstream-patches   uncommitted local changes to a pinned upstream. A revision pin
                       restores the upstream; it cannot restore edits nobody committed.
    host-snapshot      the installed systemd units, the Caddy configuration and the
                       root-owned helpers. Configuration, NOT first-party source -- and
                       labelling it source would be the relabelling this project refuses.
    git-bundle         every ref in one verifiable file, so history survives a working
                       tree that restores badly.
    source-bundles     one tar.gz per first-party component. Redundancy only: Git stays
                       the source authority, and these exist for the case where it does
                       not survive.
    runtime-artifacts  the built binaries actually running today, with their checksums,
                       architectures and link tables. Fallback and evidence, never
                       source authority -- the preferred restore is always a rebuild.
    claude-backups     a second PATH to the owner's retirement backup, by hard link.

## Why the Claude backup is linked and not copied

The standing instruction on that checkpoint is: *preserve unchanged; never delete,
overwrite, rename, reuse or mutate it.* A move renames it and breaks the finalizer's
preserve list, which references the original path. A copy duplicates 11.7 GB for no
recovery benefit. `/home/google` and the repository are the same filesystem (device 66308,
measured), so a hard link gives `.private/claude-backups/` a real path to the identical
inode: the original is untouched, no space is consumed, and GNU tar stores the second path
as a link rather than a second copy. If the link cannot be made the script COPIES and says
so, rather than silently doing something else.

    python3 tools/build/build_recovery_root.py --release r20260908 --dry-run
    python3 tools/build/build_recovery_root.py --release r20260908 --only git-bundle
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import pathlib
import shutil
import subprocess
import sys


def find_root(start: pathlib.Path) -> pathlib.Path:
    for cand in (start, *start.parents):
        if (cand / "backend" / "server.py").is_file():
            return cand
    raise SystemExit("build_recovery_root: no repository root found")


ROOT = find_root(pathlib.Path(__file__).resolve().parent)
sys.path.insert(0, str(ROOT / "restore"))
from lib import registry as R          # noqa: E402
from lib import measure as M           # noqa: E402

PRIVATE = ROOT / ".private"


def sha256(p: pathlib.Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def secure(p: pathlib.Path, mode: int = 0o700) -> pathlib.Path:
    """Create a directory and every parent at 0700 -- not just the leaf.

    `mkdir(parents=True)` applies the process umask to the INTERMEDIATE directories and
    only the leaf gets chmod'd. That left .private/source-bundles and four siblings at
    0775 while their contents were 0600, which is the shape of a permission bug that
    looks fixed. .private itself is 0700 so nothing was reachable, but a rule enforced
    only at the leaf is a rule that will be wrong the next time the tree grows a level.
    """
    p.mkdir(parents=True, exist_ok=True)
    for anc in [p, *p.parents]:
        if anc == PRIVATE.parent:
            break
        try:
            os.chmod(anc, mode)
        except OSError:
            pass
    return p


def sh(args: list[str], cwd: pathlib.Path | None = None, timeout: int = 3600):
    return subprocess.run(args, cwd=cwd or ROOT, capture_output=True, text=True,
                          timeout=timeout)


# =========================================================================================
def job_upstream_patches(dry: bool) -> dict:
    out = secure(PRIVATE / "upstream-patches")
    result = {}
    for c in R.COMPONENTS:
        if c.upstream_local_path == "-":
            continue
        tree = ROOT / c.upstream_local_path
        if not (tree / ".git").exists():
            result[c.component_id] = {"status": "NOT_A_GIT_REPO"}
            continue
        dirty = sh(["git", "status", "--porcelain"], cwd=tree).stdout.strip()
        if not dirty:
            result[c.component_id] = {"status": "CLEAN (pin alone restores it)"}
            continue
        # `git diff` covers TRACKED modifications only. Untracked build directories
        # (.hunter/, build-stockarch/) are deliberately NOT captured: they are build
        # output, not source, and carrying them would be exactly the "installed-only
        # artefact standing in for source" the reset is trying to eliminate.
        diff = sh(["git", "diff"], cwd=tree).stdout
        modified = [ln for ln in dirty.splitlines() if ln[:2].strip() in ("M", "MM")]
        untracked = [ln for ln in dirty.splitlines() if ln.startswith("??")]
        name = f"{tree.name}-local.patch"
        if not dry:
            f = out / name
            f.write_text(diff, encoding="utf-8")
            os.chmod(f, 0o600)
        result[c.component_id] = {
            "status": "PATCH_WRITTEN" if not dry else "DRY_RUN",
            "patch": f".private/upstream-patches/{name}",
            "sha256": sha256(out / name) if not dry else None,
            "tracked_modifications": len(modified),
            "untracked_paths_NOT_captured": [u[3:] for u in untracked],
            "note": "Untracked entries are build output, not source; they are named here "
                    "so their omission is a recorded decision rather than an oversight.",
        }
    return result


# =========================================================================================
HOST_PATHS = [
    "/etc/systemd/system/symoneural-api.service",
    "/etc/systemd/system/symoneural-web.service",
    "/etc/systemd/system/symoneural-gateway.service",
    "/etc/caddy/Caddyfile",
    "/usr/local/sbin/symoneural-root",
    "/etc/symoneural",
]


def job_host_snapshot(dry: bool) -> dict:
    out = secure(PRIVATE / "host-snapshot" / "rootfs")
    result = {}
    for src_s in HOST_PATHS:
        src = pathlib.Path(src_s)
        if not src.exists():
            result[src_s] = {"status": "ABSENT"}
            continue
        dst = out / src_s.lstrip("/")
        try:
            if not dry:
                dst.parent.mkdir(parents=True, exist_ok=True)
                if src.is_dir():
                    shutil.copytree(src, dst, dirs_exist_ok=True)
                else:
                    shutil.copy2(src, dst)
                    os.chmod(dst, 0o600)
            st = src.stat()
            result[src_s] = {
                "status": "CAPTURED" if not dry else "DRY_RUN",
                "source_mode": oct(st.st_mode & 0o777),
                "source_uid": st.st_uid, "source_gid": st.st_gid,
                "sha256": sha256(src) if src.is_file() else "DIRECTORY",
                "restored_as": f".private/host-snapshot/rootfs{src_s}",
            }
        except PermissionError:
            result[src_s] = {"status": "UNREADABLE (root-owned; needs sudo to capture)"}
    # User-scope units live in the owner's own config and are readable.
    user_units = pathlib.Path.home() / ".config/systemd/user"
    if user_units.is_dir():
        found = sorted(p.name for p in user_units.glob("symoneural-*"))
        if not dry and found:
            d = out / "home/google/.config/systemd/user"
            d.mkdir(parents=True, exist_ok=True)
            for n in found:
                shutil.copy2(user_units / n, d / n)
                # copy2 preserves the SOURCE mode, and these units are 0664 on disk.
                # Preserving it here would put a 0664 file in a 0600-only tree; the
                # original mode is recorded in the manifest instead, which is what a
                # restore actually needs.
                os.chmod(d / n, 0o600)
        result["~/.config/systemd/user/symoneural-*"] = {
            "status": "CAPTURED" if not dry else "DRY_RUN", "units": found}
    return result


# =========================================================================================
def job_git_bundle(dry: bool) -> dict:
    out = secure(PRIVATE / "git-backup")
    bundle = out / "Symoneural-all.bundle"
    if dry:
        return {"status": "DRY_RUN", "would_write": str(bundle)}

    fsck = sh(["git", "fsck", "--full"], timeout=3600)
    # git fsck writes progress and "dangling" notices to stderr and still exits 0. Only a
    # non-zero exit is a failure; treating any stderr as failure would report a healthy
    # repository as broken.
    fsck_ok = fsck.returncode == 0

    b = sh(["git", "bundle", "create", str(bundle), "--all"], timeout=3600)
    if b.returncode != 0:
        return {"status": "BUNDLE_FAILED", "error": b.stderr.strip()[:400],
                "git_fsck": "PASS" if fsck_ok else "FAIL"}
    os.chmod(bundle, 0o600)
    v = sh(["git", "bundle", "verify", str(bundle)], timeout=1800)
    refs = sh(["git", "bundle", "list-heads", str(bundle)], timeout=600).stdout
    return {
        "status": "OK" if v.returncode == 0 else "VERIFY_FAILED",
        "path": ".private/git-backup/Symoneural-all.bundle",
        "sha256": sha256(bundle),
        "bytes": bundle.stat().st_size,
        "mode": oct(bundle.stat().st_mode & 0o777),
        "git_fsck": "PASS" if fsck_ok else "FAIL",
        "git_fsck_detail": (fsck.stderr.strip().splitlines() or ["clean"])[-1][:200],
        "bundle_verify": (v.stdout + v.stderr).strip().splitlines()[-1][:200]
        if (v.stdout or v.stderr) else "-",
        "ref_count": len([ln for ln in refs.splitlines() if ln.strip()]),
        "refs": [ln.split(None, 1)[-1] for ln in refs.splitlines() if ln.strip()][:40],
    }


# =========================================================================================
def job_source_bundles(release: str, dry: bool) -> dict:
    """One source-only tar.gz per first-party component.

    Only components whose source is genuinely OURS get a bundle. A "source bundle" of a
    GPL-3.0 fork would be redistribution of somebody else's code under our recovery
    directory, and the pin plus the patch already restore those trees properly.
    """
    out = secure(PRIVATE / "source-bundles" / release)
    result = {}
    for c in R.COMPONENTS:
        if c.first_party_status in (R.DERIV_PERMISSIVE, R.DERIV_COPYLEFT):
            result[c.component_id] = {
                "status": "SKIPPED",
                "reason": f"{c.first_party_status} -- restored from its upstream pin plus "
                          f"our patch, not from a bundle of somebody else's source"}
            continue
        files = sh(["git", "ls-files", "-z", "--", c.source_root]).stdout.split("\0")
        files = [f for f in files if f]

        # A bundle labelled first-party must BE first-party. 15,297 of the 15,704 tracked
        # files under backend/ are vendored Anthropic and OpenAI SDKs; shipping those
        # inside `symoneural-api.tar.gz` would make the bundle 97% somebody else's code
        # with our name on the file. They stay in Git -- that is a separate decision, made
        # elsewhere and recorded in LICENSES.md -- but they do not travel in a bundle that
        # claims to be our source.
        VENDOR = ("archive/vendor-sdks/", "external/", "/node_modules/", "/.venv/",
                  "/target/release/", "/target/debug/")
        kept = [f for f in files if not any(v in "/" + f for v in VENDOR)]
        excluded = len(files) - len(kept)
        files = kept
        if not files:
            result[c.component_id] = {"status": "NO_TRACKED_FILES",
                                      "source_root": c.source_root}
            continue
        tgz = out / f"{c.component_id}.tar.gz"
        if dry:
            result[c.component_id] = {"status": "DRY_RUN", "file_count": len(files),
                                      "vendored_files_excluded": excluded}
            continue
        listfile = out / f".{c.component_id}.files"
        listfile.write_text("\0".join(files), encoding="utf-8")
        # --null -T reads NUL-separated names, so a path with a space or a newline in it
        # cannot split into two arguments.
        t = sh(["tar", "-czf", str(tgz), "--null", "-T", str(listfile),
                "--owner=0", "--group=0", "--mtime=@0"], timeout=1800)
        listfile.unlink()
        if t.returncode != 0:
            result[c.component_id] = {"status": "TAR_FAILED",
                                      "error": t.stderr.strip()[:300]}
            continue
        os.chmod(tgz, 0o600)
        digest = sha256(tgz)
        side = out / f"{c.component_id}.tar.gz.sha256"
        side.write_text(f"{digest}  {tgz.name}\n", encoding="utf-8")
        os.chmod(side, 0o600)
        result[c.component_id] = {
            "status": "OK", "bundle": f".private/source-bundles/{release}/{tgz.name}",
            "sha256": digest, "bytes": tgz.stat().st_size, "file_count": len(files),
            "vendored_files_excluded": excluded,
            "source_root": c.source_root, "source_revision": M.head(),
        }
    return result


# =========================================================================================
def job_runtime_artifacts(release: str, dry: bool) -> dict:
    """Preserve the built binaries as FALLBACK. Rebuild from source stays the restore."""
    out = secure(PRIVATE / "runtime-artifacts" / release)
    result = {}
    for c in R.COMPONENTS:
        if c.primary_artifact == "-":
            continue
        src = ROOT / c.primary_artifact
        if not src.is_file():
            result[c.component_id] = {"status": "NOT_A_FILE", "path": c.primary_artifact}
            continue
        if not (src.stat().st_mode & 0o111):
            result[c.component_id] = {"status": "NOT_EXECUTABLE (nothing to preserve as a "
                                                "runtime artefact)", "path": c.primary_artifact}
            continue
        dst = out / c.component_id / src.name
        if not dry:
            secure(dst.parent)
            shutil.copy2(src, dst)
            os.chmod(dst, 0o600)
        result[c.component_id] = {
            "status": "PRESERVED" if not dry else "DRY_RUN",
            "build_output": c.primary_artifact,
            "sha256": sha256(src),
            "bytes": src.stat().st_size,
            "file_type": M.file_type(src),
            "arch": M.elf_arch(src),
            "dynamic_dependencies": M.dynamic_deps(src, limit=40),
            "source_revision": M.head(),
            "build_recipe": c.build_command,
            "toolchain": c.toolchain,
            "preferred_restore": "REBUILD FROM SOURCE -- this copy is fallback and "
                                 "evidence, never the source authority",
        }
    return result


# =========================================================================================
CLAUDE_BACKUPS = [
    "/home/google/claude-backup-20260908-035459.zip",
    "/home/google/claude-backup-20260908-035459.zip.sha256",
]


def job_claude_backups(dry: bool) -> dict:
    out = secure(PRIVATE / "claude-backups" / "20260908-035459")
    result = {}
    for s in CLAUDE_BACKUPS:
        src = pathlib.Path(s)
        if not src.exists():
            result[s] = {"status": "ABSENT"}
            continue
        dst = out / src.name
        if dry:
            result[s] = {"status": "DRY_RUN", "would_link": str(dst)}
            continue
        if dst.exists():
            if dst.stat().st_ino == src.stat().st_ino:
                result[s] = {"status": "ALREADY_LINKED", "inode": src.stat().st_ino}
                continue
            dst.unlink()
        method = "hardlink"
        try:
            os.link(src, dst)
        except OSError:
            shutil.copy2(src, dst)
            os.chmod(dst, 0o600)
            method = "copy (hard link refused -- different filesystem)"
        result[s] = {
            "status": "LINKED", "method": method,
            "path": f".private/claude-backups/20260908-035459/{src.name}",
            "inode": src.stat().st_ino,
            "bytes": src.stat().st_size,
            "mode": oct(src.stat().st_mode & 0o777),
            "sha256": sha256(src) if src.stat().st_size < (200 << 20) else
                      "NOT_RECOMPUTED (11.7 GB; the original sidecar carries the digest "
                      "and the inode is identical, so a re-hash would prove only that "
                      "hashing is deterministic)",
            "note": "Original left in place and unmodified, as instructed.",
        }
    return result


# =========================================================================================
JOBS = {
    "upstream-patches": lambda rel, dry: job_upstream_patches(dry),
    "host-snapshot": lambda rel, dry: job_host_snapshot(dry),
    "git-bundle": lambda rel, dry: job_git_bundle(dry),
    "source-bundles": job_source_bundles,
    "runtime-artifacts": job_runtime_artifacts,
    "claude-backups": lambda rel, dry: job_claude_backups(dry),
}


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--release", required=True)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--only", action="append", choices=sorted(JOBS))
    a = ap.parse_args(argv)

    if not a.dry_run:
        secure(PRIVATE)

    report = {"release_id": a.release,
              "created_at": datetime.datetime.now().astimezone().isoformat(
                  timespec="seconds"),
              "repository_head": M.head()}

    for name in (a.only or list(JOBS)):
        print(f"\n=== {name} " + "=" * (70 - len(name)))
        res = JOBS[name](a.release, a.dry_run)
        report[name] = res
        for k, v in res.items():
            st = v.get("status", "?") if isinstance(v, dict) else str(v)
            extra = ""
            if isinstance(v, dict):
                if v.get("sha256") and len(str(v["sha256"])) == 64:
                    extra = f"sha256 {v['sha256'][:16]}…"
                elif v.get("file_count") is not None:
                    extra = f"{v['file_count']} files"
                elif v.get("reason"):
                    extra = v["reason"][:70]
                elif v.get("ref_count") is not None:
                    extra = f"{v['ref_count']} refs"
            print(f"  {str(k)[:52]:<52} {st:<22} {extra}")

    if a.dry_run:
        print("\nDRY RUN -- nothing was written.")
        return 0

    man = PRIVATE / f"RECOVERY-ROOT-{a.release}.json"
    man.write_text(json.dumps(report, indent=2, sort_keys=True, default=str) + "\n",
                   encoding="utf-8")
    os.chmod(man, 0o600)
    print(f"\nwrote {man.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
