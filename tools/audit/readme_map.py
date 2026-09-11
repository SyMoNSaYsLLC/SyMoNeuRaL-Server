#!/usr/bin/env python3
"""Which directories have a README, which do not, and which have one git does not carry.

    python3 tools/audit/readme_map.py              every directory that holds files
    python3 tools/audit/readme_map.py ops          one subtree
    python3 tools/audit/readme_map.py --missing    only the gaps
    python3 tools/audit/readme_map.py --untracked  only READMEs a clone would not get

## Why this exists

A README was reported missing four times in one afternoon and was present every time --
sitting between two other entries in a fifteen-line directory listing, which is exactly
where a file is easiest to miss.

The three that were genuinely wrong were wrong in a way no listing shows: the file was on
disk and **not in git**, because an ignore rule a directory above had swallowed it.
`git status` is clean, `ls` shows the file, and only `git check-ignore -v` says why.

So this prints both facts at once -- present, and carried -- and names the rule when the
answer is no.
"""
from __future__ import annotations

import argparse
import pathlib
import subprocess
import sys

ROOT = next(p for p in pathlib.Path(__file__).resolve().parents
            if (p / "backend" / "server.py").is_file())

SKIP = {".git", ".venv", "node_modules", "__pycache__", ".pytest_cache", ".next"}
#: Directories whose contents are data, not code. A README in each is noise; the level above
#: says what they hold. Listed rather than pattern-matched so the judgement is on the record.
LEAF_DATA = {"assets/art", "assets/brand", "assets/icons", "models/llm",
             "ops/history/decisions", "ops/history/handoffs", "ops/history/archive"}


def tracked() -> set[str]:
    out = subprocess.run(["git", "-C", str(ROOT), "ls-files"],
                         capture_output=True, text=True, check=True).stdout
    return set(out.split())


def why_ignored(rel: str) -> str:
    return subprocess.run(["git", "-C", str(ROOT), "check-ignore", "-v", rel],
                          capture_output=True, text=True).stdout.strip()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("subtree", nargs="?", default=".")
    ap.add_argument("--missing", action="store_true", help="only directories with no README")
    ap.add_argument("--untracked", action="store_true", help="only READMEs git does not carry")
    args = ap.parse_args()

    base = (ROOT / args.subtree).resolve()
    if not base.is_dir():
        print(f"no such directory: {args.subtree}", file=sys.stderr)
        return 2

    have = tracked()
    rows, gaps, untracked_n = [], 0, 0

    for d in sorted([base] + [p for p in base.rglob("*") if p.is_dir()]):
        if SKIP & set(d.parts):
            continue
        files = [f for f in d.iterdir() if f.is_file()]
        if not files:
            continue
        rel_dir = d.relative_to(ROOT).as_posix()
        readme = d / "README.md"
        if readme.is_file():
            rel = readme.relative_to(ROOT).as_posix()
            if rel in have:
                mark, note = "ok  ", ""
            else:
                mark, note = "GIT ", f"  <- on disk, NOT in git: {why_ignored(rel) or 'never added'}"
                untracked_n += 1
        elif any(rel_dir.endswith(x) for x in LEAF_DATA):
            mark, note = "data", "  (data, README deliberately omitted)"
        else:
            mark, note, gaps = "MISS", "", gaps + 1

        if args.missing and mark != "MISS":
            continue
        if args.untracked and mark != "GIT ":
            continue
        rows.append(f"  {mark}  {rel_dir}/ ({len(files)}){note}")

    print("\n".join(rows) if rows else "  nothing to report")
    print(f"\n  {gaps} without a README, {untracked_n} present but not carried by a clone")
    return 1 if untracked_n else 0


if __name__ == "__main__":
    raise SystemExit(main())
