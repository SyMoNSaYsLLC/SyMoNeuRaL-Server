#!/usr/bin/env python3
"""Break the derivation on purpose and watch the suite go red. Red first, as code.

`apps/ravencalc/test_steps.py` is nine assertions about a step list, and a step list is
exactly the kind of output that looks right while being wrong -- every rule name in it is
a true sentence about calculus regardless of whether it was fired by the node it is
attached to. So the tests have to be shown failing, and the cheapest honest way to show
that is to introduce the specific defect each one exists to catch.

Each break is applied to a snapshot of the file's text and rolled back in `finally`. The
run ends by comparing every target byte-for-byte against the snapshot taken at start --
against the snapshot and not against git HEAD, because uncommitted work in the same file
would otherwise read as residue this script left behind.

    python3 tools/audit/prove_ravencalc_steps.py     # exit 0 iff every break went red
"""
from __future__ import annotations

import pathlib
import subprocess
import sys

REPO = next(_p for _p in pathlib.Path(__file__).resolve().parents if (_p / "backend" / "server.py").is_file())
BACKEND = REPO / "backend"
STEPS = BACKEND / "apps" / "ravencalc" / "steps.py"

BREAKS = [
    (STEPS,
     "a constant multiple is narrated as a product rule",
     '''            if constant and len(varying) == 1:
                self.add("Constant multiple: the factor comes out front", node)
                self.walk(varying[0])
                return
''',
     ""),
    (STEPS,
     "the walk never enters a composite's argument -- chain rule in name only",
     "            if inner != x:\n                self.walk(inner)\n",
     "            if False:\n                self.walk(inner)\n"),
    (STEPS,
     "each step reports the WHOLE expression's derivative, not the part's",
     '            "gives": _render(symbolic.diff(node, self.variable, 1)),',
     '            "gives": _render(symbolic.diff(node, self.variable, 1)) if False else "0",'),
    (STEPS,
     "truncation stops silently instead of saying it stopped",
     "            self.truncated = True\n            return\n",
     "            return\n"),
    (STEPS,
     "a second derivative re-walks the ORIGINAL instead of the first derivative",
     "        walk.walk(current)\n        truncated = truncated or walk.truncated\n"
     "        current = symbolic.diff(current, variable, 1)\n",
     "        walk.walk(expression)\n        truncated = truncated or walk.truncated\n"
     "        current = symbolic.diff(current, variable, 1)\n"),
]


def run() -> tuple[bool, str]:
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", "ravencalc/test_steps.py", "-q"],
        cwd=BACKEND, capture_output=True, text=True)
    tail = [ln for ln in proc.stdout.splitlines() if ln.strip()]
    return proc.returncode == 0, (tail[-1] if tail else "no output")


def main() -> int:
    snapshot = {STEPS: STEPS.read_text()}
    ok, line = run()
    print(f"BASELINE {'green' if ok else 'RED  '}  {line}")
    if not ok:
        print("the suite must be green before a break means anything", file=sys.stderr)
        return 1

    failures = 0
    for path, label, find, replace in BREAKS:
        original = snapshot[path]
        if find not in original:
            print(f"SKIP     stale anchor  {label}")
            failures += 1
            continue
        try:
            path.write_text(original.replace(find, replace, 1))
            broke, line = run()
            print(f"BREAK    {'GREEN' if broke else 'RED  '}  {label}")
            if broke:
                print(f"         ^ the break survived the suite: {line}")
                failures += 1
        finally:
            path.write_text(original)

    ok, line = run()
    print(f"RESTORED {'green' if ok else 'RED  '}  {line}")
    failures += 0 if ok else 1

    for path, text in snapshot.items():
        if path.read_text() != text:
            print(f"TREE     DIRTY  {path.relative_to(REPO)} was not restored")
            failures += 1
    if not failures:
        print("TREE     clean  every file byte-identical to where it started")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
