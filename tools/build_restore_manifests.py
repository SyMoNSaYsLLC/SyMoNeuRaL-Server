#!/usr/bin/env python3
# SPDX-License-Identifier: LicenseRef-SyMoNeuRaL-Proprietary
# Copyright (c) 2026 SymonSays LLC. All rights reserved.
# SyMoNeuRaL is a subdivision of SymonSays LLC. Licence: /LICENSE at the repository root.
"""Regenerate every restore manifest from the registry joined against measured disk state.

    python3 tools/build_restore_manifests.py
    python3 tools/build_restore_manifests.py --release r20260908

Run it TWICE and diff. Generators in this repository re-read their own output and one that
does not recognise something it emits accumulates a copy per run -- that has happened three
separate times here, so two clean runs is the check, not a courtesy.
"""
from __future__ import annotations

import argparse
import datetime
import pathlib
import sys


def find_root(start: pathlib.Path) -> pathlib.Path:
    for cand in (start, *start.parents):
        if (cand / "backend" / "api.py").is_file():
            return cand
    raise SystemExit("build_restore_manifests: no repository root found")


ROOT = find_root(pathlib.Path(__file__).resolve().parent)
sys.path.insert(0, str(ROOT / "restore"))
from lib import generate as G          # noqa: E402


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--release", default="r20260908")
    a = ap.parse_args(argv)
    stamp = datetime.datetime.now().astimezone().isoformat(timespec="seconds")
    counts = G.generate_all(a.release, {"created_at": stamp})
    for name, n in counts.items():
        print(f"  {name:<34} {n} rows")
    print(f"\nrelease {a.release} at {stamp}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
