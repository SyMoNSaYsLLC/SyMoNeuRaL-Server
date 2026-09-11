#!/usr/bin/env python3
# SPDX-License-Identifier: LicenseRef-SyMoNeuRaL-Proprietary
# Copyright (c) 2026 SymonSays LLC. All rights reserved.
# SyMoNeuRaL is a subdivision of SymonSays LLC. Licence: /LICENSE at the repository root.
"""Take a consistent backup of every persistent state store into `.private/`.

Git restores source. It cannot restore the account database, the project store, the
operator's ledgers, the trained adapter, or the environment file the API reads its
configuration out of. This is the half of a restore that source control has no opinion
about, and it is the half that is actually irreplaceable.

## The one rule that makes this different from `cp -a run/`

**A live SQLite database must not be copied byte-for-byte.** Two of these stores had a `-wal`
and `-shm` file beside them when this was written, which means a writer was attached; a
plain copy of a database mid-transaction produces a file that passes a checksum, restores
without error, and is corrupt. So every SQLite store goes through `sqlite3 .backup`, which
takes the database's own read lock and writes a consistent image, and the result is then
proved with `PRAGMA integrity_check` before it is recorded. A backup that has not been
opened is a hope.

## Modes

`.private/` is 0700 and every file written into it is 0600, without exception -- these are
session databases, an env file and the owner's private ledgers. The archive that eventually
carries them is 0600 too. The one thing this script will not do is widen a mode to make a
copy easier.

    python3 tools/build/build_private_state.py --release r20260908 --dry-run
    python3 tools/build/build_private_state.py --release r20260908
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
    raise SystemExit("build_private_state: no repository root found")


ROOT = find_root(pathlib.Path(__file__).resolve().parent)
sys.path.insert(0, str(ROOT / "restore"))
from lib import registry as R          # noqa: E402


def sha256(p: pathlib.Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def dir_digest(d: pathlib.Path) -> tuple[str, int]:
    """A stable digest over a directory: sorted relative paths and their content hashes.

    Not a tar checksum -- tar embeds mtimes and ordering, so two identical trees hash
    differently and the value proves nothing about the content.
    """
    h = hashlib.sha256()
    n = 0
    for f in sorted(d.rglob("*")):
        if f.is_file() and not f.is_symlink():
            h.update(str(f.relative_to(d)).encode())
            h.update(sha256(f).encode())
            n += 1
    return h.hexdigest(), n


def secure_dir(p: pathlib.Path) -> None:
    p.mkdir(parents=True, exist_ok=True)
    os.chmod(p, 0o700)


def backup_sqlite(src: pathlib.Path, dst: pathlib.Path, dry: bool) -> dict:
    """Consistent SQLite image via the engine, then prove it opens and passes integrity."""
    if dry:
        return {"method": "sqlite3 .backup", "would_write": str(dst), "status": "DRY_RUN"}
    dst.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(dst.parent, 0o700)
    if dst.exists():
        dst.unlink()
    # `.backup` rather than VACUUM INTO: it copes with a concurrent writer, which is the
    # situation actually observed here, and it does not rewrite page layout.
    p = subprocess.run(["sqlite3", str(src), f".backup '{dst}'"],
                       capture_output=True, text=True, timeout=600)
    if p.returncode != 0:
        return {"method": "sqlite3 .backup", "status": "FAILED",
                "error": p.stderr.strip()[:200]}
    os.chmod(dst, 0o600)
    chk = subprocess.run(["sqlite3", str(dst), "PRAGMA integrity_check;"],
                         capture_output=True, text=True, timeout=600)
    ok = chk.stdout.strip() == "ok"
    return {"method": "sqlite3 .backup", "status": "OK" if ok else "INTEGRITY_FAILED",
            "integrity_check": chk.stdout.strip()[:100],
            "sha256": sha256(dst), "bytes": dst.stat().st_size}


def backup_file(src: pathlib.Path, dst: pathlib.Path, dry: bool) -> dict:
    if dry:
        return {"method": "cp -p", "would_write": str(dst), "status": "DRY_RUN"}
    dst.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(dst.parent, 0o700)
    shutil.copy2(src, dst)
    os.chmod(dst, 0o600)
    return {"method": "cp -p", "status": "OK", "sha256": sha256(dst),
            "bytes": dst.stat().st_size, "source_mode": oct(src.stat().st_mode & 0o777)}


def backup_dir(src: pathlib.Path, dst: pathlib.Path, dry: bool) -> dict:
    if dry:
        return {"method": "rsync -a", "would_write": str(dst), "status": "DRY_RUN"}
    dst.parent.mkdir(parents=True, exist_ok=True)
    os.chmod(dst.parent, 0o700)
    # -a implies -l, so symlinks are preserved as symlinks. `--no-dereference` does NOT
    # exist in rsync 3.4.1 and passing it silently archived 212 files instead of 68,278
    # because the error went to a suppressed stderr. Do not add it.
    p = subprocess.run(["rsync", "-a", "--delete", f"{src}/", f"{dst}/"],
                       capture_output=True, text=True, timeout=7200)
    if p.returncode != 0:
        return {"method": "rsync -a", "status": "FAILED",
                "error": p.stderr.strip()[:300]}
    digest, n = dir_digest(dst)
    return {"method": "rsync -a", "status": "OK", "content_digest": digest,
            "file_count": n}


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--release", required=True)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--digest-carried", action="store_true",
                    help="also content-hash the CARRIED_IN_ARCHIVE stores (slow on the "
                         "17 GB model tree, but proves what the archive is carrying)")
    a = ap.parse_args(argv)

    base = ROOT / ".private" / "application-state" / a.release
    if not a.dry_run:
        secure_dir(ROOT / ".private")
        secure_dir(base)

    report: dict[str, dict] = {}
    print(f"{'store':<20} {'method':<18} {'status':<18} detail")
    print("-" * 88)

    for s in R.STATE_STORES:
        paths = [x.strip() for x in s.live_path.split(",") if x.strip()]
        results = []
        for rel in paths:
            src = ROOT / rel
            if not src.exists():
                results.append({"path": rel, "status": "SOURCE_ABSENT"})
                continue
            if s.backup_policy == "CARRIED_IN_ARCHIVE":
                # Not skipped -- classified. The final tar preserves the repository tree
                # verbatim, so this store is already travelling. A second copy inside
                # .private/ would put the same bytes in the same archive twice.
                digest = None
                if src.is_dir() and a.digest_carried and not a.dry_run:
                    d, n = dir_digest(src)
                    digest = {"content_digest": d, "file_count": n}
                results.append({"path": rel, "method": "carried in the repository tree",
                                "status": "CARRIED_IN_ARCHIVE", **(digest or {})})
                continue
            dst = base / s.state_id / pathlib.Path(rel).name
            if src.is_dir():
                r = backup_dir(src, base / s.state_id / pathlib.Path(rel).name, a.dry_run)
            elif "sqlite" in s.type_.lower():
                r = backup_sqlite(src, dst, a.dry_run)
            else:
                r = backup_file(src, dst, a.dry_run)
            r["path"] = rel
            r["source_bytes"] = src.stat().st_size if src.is_file() else None
            results.append(r)

        report[s.state_id] = {
            "application": s.application,
            "consistency_method": s.consistency_method,
            "contains_secrets": s.contains_secrets,
            "required_for_restore": s.required_for_restore,
            "restore_destination": s.restore_destination,
            "restore_command": s.restore_command,
            "validation_command": s.validation_command,
            "results": results,
        }
        for r in results:
            detail = r.get("integrity_check") or r.get("error") or \
                (f"{r.get('file_count')} files" if r.get("file_count") is not None else "")
            if r.get("sha256"):
                detail = f"sha256 {r['sha256'][:16]}… {detail}".strip()
            print(f"  {s.state_id:<18} {r.get('method','-'):<18} "
                  f"{r.get('status','-'):<18} {detail}")

    if a.dry_run:
        print("\nDRY RUN -- nothing was written.")
        return 0

    manifest = base / "STATE-MANIFEST.json"
    manifest.write_text(json.dumps({
        "release_id": a.release,
        "created_at": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
        "repository_head": subprocess.run(
            ["git", "-C", str(ROOT), "rev-parse", "HEAD"],
            capture_output=True, text=True).stdout.strip(),
        # No secret VALUES here, ever -- only which stores contain secrets, so a restorer
        # knows which files to place with care. Names, not contents.
        "stores": report,
    }, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.chmod(manifest, 0o600)

    failed = [k for k, v in report.items()
              if any(r.get("status") not in ("OK", "SOURCE_ABSENT", "CARRIED_IN_ARCHIVE")
                     and not str(r.get("status", "")).startswith("SKIPPED")
                     for r in v["results"])]
    print(f"\nwrote {manifest.relative_to(ROOT)}")
    if failed:
        print(f"FAILED stores: {', '.join(failed)}")
        return 1
    print("all stores backed up and verified")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
