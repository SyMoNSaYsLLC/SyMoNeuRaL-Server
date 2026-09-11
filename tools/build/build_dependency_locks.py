#!/usr/bin/env python3
# SPDX-License-Identifier: LicenseRef-SyMoNeuRaL-Proprietary
# Copyright (c) 2026 SymonSays LLC. All rights reserved.
# SyMoNeuRaL is a subdivision of SymonSays LLC. Licence: /LICENSE at the repository root.
"""Write one pinned dependency lock per Python environment on this box.

`backend/DEPENDENCIES.md` states the constraint this tool exists to respect:

    "There is no single environment here and pretending there is would make the table
     wrong: the serving path is the system interpreter (Debian, 212 packages, no
     virtualenv on purpose), and training, sigils, asicminer and studio each have
     their own venv."

So there is no such thing as *the* lock file for this project, and a single
`requirements.lock.txt` at the repository root would be a confident description of an
environment that does not exist. This writes one lock per environment, each naming the
interpreter it was read from.

## Why a lock at all, when the venvs are sitting right there

The owner's restore spec, Target 11: *"Do not archive a venv as the only way to restore
it."* A venv is a directory of compiled artefacts built against one interpreter, one libc
and one CPU; it is evidence of what was installed, not a means of reinstalling it. The lock
is the means. The venv may still be preserved privately as fallback, and it is -- but the
service must be reconstructable without it, and that is what these files make true.

## What is pinned, and what is honestly not

Every distribution found in the environment is pinned to an exact `==` version. What is NOT
recorded is a hash for each artefact: these environments were populated over months from
PyPI and Debian both, and a hash line that was never verified against the wheel it claims to
pin is decoration. `pip install --require-hashes` would reject the file anyway unless every
transitive dependency carried one. Where hashes exist they come from the package manager, and
the manifest says which manager -- rather than this tool inventing a column it cannot fill.

    python3 tools/build/build_dependency_locks.py            # write the locks
    python3 tools/build/build_dependency_locks.py --check    # fail if any lock is out of date
"""
from __future__ import annotations

import datetime
import pathlib
import subprocess
import sys


def find_root(start: pathlib.Path) -> pathlib.Path:
    for cand in (start, *start.parents):
        if (cand / "backend" / "server.py").is_file():
            return cand
    raise SystemExit("build_dependency_locks: no repository root found")


ROOT = find_root(pathlib.Path(__file__).resolve().parent)
OUT = ROOT / "restore" / "locks"

# (lock name, interpreter, what this environment is for).
#
# The serving interpreter is FIRST and is the one that matters most: it is what
# `ops/units/symoneural-api.service` execs, measured from the running unit as
# `/usr/bin/python3 /home/google/Symoneural/backend/server.py`.
ENVIRONMENTS: list[tuple[str, str, str]] = [
    ("serving-system", "/usr/bin/python3",
     "The API. Debian system interpreter, deliberately not a virtualenv -- "
     "ops/units/symoneural-api.service execs it directly."),
    ("training", "training/.venv/bin/python3",
     "LoRA training and evaluation (torch, transformers, peft, trl, datasets)."),
    ("sigils", "backend/sigils/.venv/bin/python3", "The Sigils render path."),
    ("studio", "backend/studio/.venv/bin/python3",
     "Studio and its reinforce/exp/discovery plugins."),
    ("asicminer", "backend/asicminer/.venv/bin/python3",
     "ASIC-side miner telemetry (pyasic)."),
    ("symoneural-ui", "symoneural-ui/.venv/bin/python3",
     "The GPL-3.0 ComfyUI fork. DISABLED for the reset; the lock is recorded for "
     "completeness, not because the component is being carried."),
]

PROBE = (
    "import importlib.metadata as m, sys;"
    "print('#PY', sys.version.split()[0]);"
    "print('\\n'.join(sorted(f'{d.metadata[\"Name\"]}=={d.version}'"
    " for d in m.distributions() if d.metadata['Name'])))"
)


def read_environment(interp: pathlib.Path) -> tuple[str, list[str]] | None:
    if not interp.exists():
        return None
    try:
        p = subprocess.run([str(interp), "-c", PROBE], capture_output=True, text=True,
                           timeout=120)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if p.returncode != 0:
        return None
    lines = [ln for ln in p.stdout.splitlines() if ln.strip()]
    if not lines or not lines[0].startswith("#PY"):
        return None
    version = lines[0].split(None, 1)[1]
    # De-duplicate: a name can appear twice when a dist-info and an egg-info coexist,
    # which happens on a box where pip and apt have both installed the same package.
    seen, pins = set(), []
    for ln in lines[1:]:
        name = ln.split("==")[0].lower().replace("_", "-")
        if name in seen:
            continue
        seen.add(name)
        pins.append(ln)
    return version, pins


def render(name: str, interp: str, purpose: str, version: str, pins: list[str]) -> str:
    stamp = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
    head = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "--short=8", "HEAD"],
                          capture_output=True, text=True).stdout.strip() or "unknown"
    return (
        f"# SyMoNeuRaL dependency lock -- {name}\n"
        f"#\n"
        f"# {purpose}\n"
        f"#\n"
        f"# Interpreter : {interp}\n"
        f"# Python      : {version}\n"
        f"# Distributions: {len(pins)}\n"
        f"# Measured    : {stamp} at HEAD {head}\n"
        f"#\n"
        f"# GENERATED by tools/build/build_dependency_locks.py -- do not hand-edit. This is a\n"
        f"# reading of an environment, not a wish list: every line was read from the\n"
        f"# interpreter above with importlib.metadata, not copied from another file.\n"
        f"#\n"
        f"# Restore:\n"
        f"#     python3 -m venv <path>/.venv\n"
        f"#     <path>/.venv/bin/pip install -r restore/locks/{name}.lock.txt\n"
        f"#\n"
        f"# The serving environment is the exception -- it is the Debian system\n"
        f"# interpreter on purpose, so its lock is installed into the system interpreter\n"
        f"# (or a venv the unit is repointed at), never into a venv that nothing execs.\n"
        f"#\n"
        f"# No hashes: these environments were populated from PyPI and apt both over\n"
        f"# months, and a hash never verified against the wheel it claims to pin is\n"
        f"# decoration. See the module docstring.\n"
        + "".join(f"{p}\n" for p in pins)
    )


def main(argv: list[str]) -> int:
    check = "--check" in argv
    OUT.mkdir(parents=True, exist_ok=True)
    stale, written, missing = [], [], []

    for name, interp_rel, purpose in ENVIRONMENTS:
        interp = pathlib.Path(interp_rel) if interp_rel.startswith("/") \
            else ROOT / interp_rel
        got = read_environment(interp)
        if got is None:
            missing.append((name, str(interp)))
            print(f"  {name:<16} ABSENT ({interp})")
            continue
        version, pins = got
        body = render(name, str(interp), purpose, version, pins)
        target = OUT / f"{name}.lock.txt"

        if check:
            # Compare the PIN LINES only. The header carries a timestamp, so a whole-file
            # comparison would report every lock as stale one second after writing it --
            # a check that always fires is a check nobody reads.
            def pins_of(text: str) -> list[str]:
                return [ln for ln in text.splitlines() if ln and not ln.startswith("#")]
            if not target.exists() or pins_of(target.read_text()) != pins:
                stale.append(name)
                print(f"  {name:<16} STALE ({len(pins)} distributions in the environment)")
            else:
                print(f"  {name:<16} OK ({len(pins)} distributions)")
            continue

        target.write_text(body, encoding="utf-8")
        written.append((name, len(pins)))
        print(f"  {name:<16} wrote {len(pins):>3} pins  <- {interp}")

    if check:
        if stale:
            print(f"\nSTALE: {', '.join(stale)}")
            print("Run: python3 tools/build/build_dependency_locks.py")
            return 1
        print("\nall locks match their environments")
        return 0

    print(f"\nwrote {len(written)} lock file(s) to restore/locks/")
    if missing:
        print("environments not present on this host (recorded as absent, not guessed):")
        for name, interp in missing:
            print(f"  {name}: {interp}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
