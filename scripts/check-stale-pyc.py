#!/usr/bin/env python3
"""Find `.pyc` files that do not match their source but that Python will trust anyway.

## Why this exists

`backend/apps/studio/plugins/reinforce/test_reinforce.py::PresetTests::test_alpha_is_twice_rank_everywhere`
was red for hours against a source file that was correct. `presets.py` plainly reads
`rank=32, lora_alpha=64`; the imported module reported `lora_alpha=48`. It was recorded as an
open owner decision about a training hyper-parameter. It was not a decision at all -- it was
stale bytecode that Python had no way to notice.

Python validates a timestamp-based `.pyc` against two things: the source's **mtime, truncated
to whole seconds**, and the source's **size in bytes**. Both matched:

* the edit `48` -> `64` changed no bytes -- both are two characters;
* the edit landed in the same clock second as the `.pyc` write, so the truncated mtimes were
  equal.

So the cache looked valid, and every interpreter on this box loaded a preset whose alpha was
one edit out of date. `jobs.py` passes `preset.lora_alpha` to the trainer as `--alpha`, so once
`backend/apps/studio/plugins/reinforce/routes.py` is mounted this stops being a red test and becomes a run
that silently trains at the wrong alpha while the site publishes the right one.

This is not a rare accident. Two-character numeric edits are ordinary, and an agent that edits
a file and runs its tests in the same second is the normal case here, not the unlucky one.

## What it does

For each `.pyc` Python would trust without rechecking, recompile the source in memory and
compare the two code objects' *logical* content -- names, argument counts, bytecode and
constants, recursively. Filenames are deliberately excluded from the comparison: `co_filename`
differs between a module imported as `reinforce.presets` and the same file compiled from a
different working directory, and comparing raw marshalled bytes reports every one of those as
stale. It did, on the first version of this script: 240 false positives against one real one.

`-pytest-*.pyc` files are skipped. Those hold pytest's assertion-rewritten bytecode, which is
*supposed* to differ from the source, and pytest validates them itself.

## Using it

    python3 scripts/check-stale-pyc.py            # report; exit 1 if anything is stale
    python3 scripts/check-stale-pyc.py --fix      # delete the stale ones and exit 0

Run it before believing a test failure that contradicts the source in front of you. Deleting a
`.pyc` is always safe -- it is a cache, and the interpreter rebuilds it on the next import.

Verified both ways on 2026-08-17, which is the standard this repo holds a check to: it reports
0 stale against a healthy tree of 88 trusted files, and it reports the known-bad
`presets.cpython-313.pyc` as stale when that file is put back.
"""

from __future__ import annotations

import argparse
import marshal
import pathlib
import struct
import sys
import types

#: Directories that are somebody else's cache to manage. `contrib/` is vendored source with
#: its own build, the venvs are package installs, and `.claude/worktrees/` belongs to whichever
#: session is working in it -- a scan that walked in there would report another agent's
#: in-progress edits as this tree's problem.
SKIP = {".venv", "node_modules", "contrib", "worktrees", ".git"}


def logical(code: object) -> object:
    """A code object's content with every filename dropped, recursively.

    `co_filename` and `co_firstlineno` are recorded in the bytecode and vary with how a module
    was imported, not with what it says. Comparing them is what makes a byte-for-byte check
    useless here.
    """
    if not isinstance(code, types.CodeType):
        return code
    return (code.co_name, code.co_argcount, code.co_kwonlyargcount, code.co_flags,
            code.co_code, code.co_names, code.co_varnames,
            tuple(logical(k) for k in code.co_consts))


def trusted(pyc: pathlib.Path, src: pathlib.Path) -> bool:
    """Would Python load this `.pyc` without recompiling the source?"""
    head = pyc.read_bytes()[:16]
    if len(head) < 16:
        return False
    _magic, flags, mtime, size = struct.unpack("<4sIII", head)
    if flags & 0b1:
        return False                      # hash-based: immune to this failure entirely
    st = src.stat()
    return int(st.st_mtime) == mtime and st.st_size == size


def scan(root: pathlib.Path) -> tuple[int, list[pathlib.Path]]:
    checked, stale = 0, []
    for pyc in sorted(root.rglob("__pycache__/*.pyc")):
        if any(part in SKIP for part in pyc.parts):
            continue
        if "-pytest-" in pyc.name:
            continue
        src = pyc.parent.parent / (pyc.name.split(".")[0] + ".py")
        if not src.exists():
            continue                      # an orphan cache; harmless, nothing imports it
        if not trusted(pyc, src):
            continue                      # Python will notice this one by itself
        checked += 1
        try:
            fresh = compile(src.read_bytes(), str(src), "exec", dont_inherit=True)
            cached = marshal.loads(pyc.read_bytes()[16:])
        except Exception as exc:          # a source that will not compile is a louder problem
            print(f"  ?? could not compare {src}: {exc}")
            continue
        if logical(cached) != logical(fresh):
            stale.append(pyc)
    return checked, stale


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--fix", action="store_true", help="delete the stale files")
    ap.add_argument("root", nargs="?", default=".", help="tree to scan (default: cwd)")
    args = ap.parse_args()

    checked, stale = scan(pathlib.Path(args.root))
    print(f"{checked} .pyc files Python would trust without rechecking")
    if not stale:
        print("none of them disagree with their source")
        return 0

    print(f"{len(stale)} disagree with their source -- Python cannot detect these:")
    for pyc in stale:
        print(f"  {pyc}")
        if args.fix:
            pyc.unlink()
    if args.fix:
        print("deleted; the interpreter will rebuild them on the next import")
        return 0
    print("re-run with --fix to delete them, then re-run whatever failed")
    return 1


if __name__ == "__main__":
    sys.exit(main())
