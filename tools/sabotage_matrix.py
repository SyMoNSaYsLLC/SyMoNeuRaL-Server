#!/usr/bin/env python3
"""Break each Control Plane Matrix assertion on purpose, prove it goes red, restore.

    python3 tools/sabotage_matrix.py            # run every case
    python3 tools/sabotage_matrix.py --list     # print the cases, mutate nothing

**Why this is a tracked tool and not a note in a commit message.** The matrix branch originally
claimed "verified by sabotage, nine mutations, all caught" and the harness that did it lived in a
scratch directory that no longer exists. A proof nobody can re-run is an assertion, and this repo's
rule is that a rule with a test behind it beats a rule in a document. So the harness ships.

It earns its keep rather than decorating: on the first run it found that **two of the assertions it
was checking were decoration** -- "every figure appears in both files" passed while a table cell
read 999.9, because that figure also occurs in prose two sections down; and the SHA check accepted
the section heading's copy of the SHA, so deleting the attribution line entirely still passed. A
mutation that leaves the suite green is reported as a FAILURE OF THIS RUN, because that is the
finding, not a pass.

Safety, in order:

  * mutates **documents only** -- never app code, never a weight, never a service;
  * refuses to start if any target file has uncommitted changes, so a crash mid-run cannot eat
    somebody's edits;
  * restores every file in a `finally:` and asserts the restore was byte-exact;
  * runs `pytest` on **one test id at a time**, so a mutation cannot be credited to an unrelated
    failure.

`backend/test_sabotage_matrix.py` checks this file stays honest -- every anchor still present,
every test id still real -- without mutating anything, so the suite stays side-effect free.
"""
from __future__ import annotations

import argparse
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
SUITE = "apps/test_control_plane_matrix.py"

MATRIX = "docs/specs/symoneural-control-plane-matrix.md"
BOOTCAMP = "docs/specs/symoneural-bootcamp.md"
CAPABILITY = "docs/ops/APPLICATION-MODEL-CAPABILITY-MATRIX.md"
BENCHMARKS = "docs/ops/MODEL-BENCHMARKS.md"
PARITY = "docs/ops/VLLM-BENCH-PARITY.md"

#: (label, file, find, replace, test id it must turn red)
CASES: list[tuple[str, str, str, str, str]] = [
    ("a 4th option added to a depth chart",
     BOOTCAMP,
     "**Option 3 — Future / Advanced / Blocked**",
     "**Option 3 — Future / Advanced / Blocked**\n- **Option 4 — sabotage**",
     "DepthChartsKeepExactlyThreeOptions"),

    ("a benchmark cell changed in the ledger only",
     BENCHMARKS,
     "| **generation** | **166.3 tok/s** | 147.6 tok/s |",
     "| **generation** | **999.9 tok/s** | 147.6 tok/s |",
     "BenchmarkFiguresAgreeWithTheirSource::"
     "test_every_benchmark_row_matches_its_narrative_source_cell_for_cell"),

    ("the SHA attribution line deleted",
     BENCHMARKS,
     "**SHA `96366d93` · 2026-08-22 · runtime `symoneural-llm`",
     "**(attribution deleted)** · 2026-08-22 · runtime symoneural-llm",
     "BenchmarkFiguresAgreeWithTheirSource::"
     "test_each_benchmark_section_attributes_its_figures_to_a_sha"),

    ("the instance count desynced from its own table",
     MATRIX,
     "**20 instances across 20 app modules.**",
     "**21 instances across 20 app modules.**",
     "CountsMatchTheTables::test_the_stated_instance_count_equals_the_number_of_matrix_rows"),

    ("off-the-record offered as available",
     MATRIX,
     "| bypass audit / security / provenance | **FORBIDDEN.**",
     "| bypass audit / security / provenance | **available**",
     "ForbiddenModeStaysForbidden"),

    ("vLLM called 'not installed' again, outside a blockquote",
     PARITY,
     "## 2. What parity would have to mean",
     "vLLM is not installed on this box.\n\n## 2. What parity would have to mean",
     "ClaimsContradictedByTheDiskFail::test_no_document_calls_vllm_absent_while_it_is_installed"),

    ("ASR re-claimed as serving in the depth chart",
     BOOTCAMP,
     "**1/1 manifested.** **proof** — **the weight loads nothing",
     "**1/1 manifested.** **proof** serving — **the weight loads nothing",
     "ClaimsContradictedByTheDiskFail::"
     "test_no_document_claims_asr_is_serving_while_its_runtime_is_absent"),

    ("a nonexistent app module named in a capability cell",
     CAPABILITY,
     "| **`sigils`** |",
     "| **`nosuchapp`** |",
     "CapabilityCellsNameRealThings::"
     "test_every_app_module_named_in_the_capability_matrix_exists"),

    ("the unaudited-range caveat dropped",
     BENCHMARKS,
     "- **404 commits between 2026-08-17 and `7a4e5c98` are not audited.**",
     "- (caveat removed)",
     "CaveatsAreCarriedForward::test_every_new_document_carries_the_unaudited_commit_caveat"),

    # Added after the review that found four hand-typed Safety cells. This is the mutation the
    # first version of the suite could not have caught, because nothing recomputed the ratings.
    ("a Safety cell hand-typed against the derivation table",
     MATRIX,
     "| **RavenCalc** | RavenCalc | CPU deterministic, **no model** | n/a | public · none · read | `S-med`¹¹",
     "| **RavenCalc** | RavenCalc | CPU deterministic, **no model** | n/a | public · none · read | `S-low`¹¹",
     "SafetyRatingsAreDerivedNotTyped::test_every_safety_cell_matches_the_derivation_table"),

    # Added after the post-merge failure. That bug was in the test's *filter* rather than in a
    # document, so the harness (documentation-only by contract) cannot reproduce it directly -- the
    # three unit tests around `is_app_module_dir` cover that side. What this case does cover is the
    # other half: the published module count drifting away from the tree.
    ("the app-module count desynced from the tree",
     MATRIX,
     "**20 instances across 20 app modules.**",
     "**20 instances across 21 app modules.**",
     "CountsMatchTheTables::test_the_stated_app_module_count_equals_the_tree"),

    ("an exposure cell contradicting the mount table in api.py",
     MATRIX,
     "| **Voice — ASR** | Voice | weight present, **runtime unusable** | `whisper.cpp` **absent** | public · token · read",
     "| **Voice — ASR** | Voice | weight present, **runtime unusable** | `whisper.cpp` **absent** | none · token · read",
     "SafetyRatingsAreDerivedNotTyped::test_exposure_agrees_with_the_mount_table_and_the_caddyfile"),
]


def one(test_id: str) -> tuple[int, str]:
    target = f"{SUITE}::{test_id}" if test_id else SUITE
    p = subprocess.run([sys.executable, "-m", "pytest", target, "-q"],
                       cwd=BACKEND, capture_output=True, text=True)
    tail = (p.stdout + p.stderr).strip().splitlines()
    return p.returncode, (tail[-1] if tail else "(no output)")


def dirty(paths: list[str]) -> list[str]:
    p = subprocess.run(["git", "status", "--porcelain", "--", *paths],
                       cwd=ROOT, capture_output=True, text=True)
    return [l for l in p.stdout.splitlines() if l.strip()]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--list", action="store_true", help="print the cases and exit")
    args = ap.parse_args()

    if args.list:
        for label, rel, _, _, test_id in CASES:
            print(f"  {label}\n      file {rel}\n      test {test_id}")
        print(f"\n{len(CASES)} cases")
        return 0

    targets = sorted({rel for _, rel, _, _, _ in CASES})
    if unclean := dirty(targets):
        print("REFUSING: uncommitted changes in a file this tool mutates.\n  "
              + "\n  ".join(unclean)
              + "\n\nCommit or stash them first -- this tool rewrites these files in place.")
        return 2

    print(f"{len(CASES)} mutations, one test id each\n")
    caught = 0
    for label, rel, find, repl, test_id in CASES:
        path = ROOT / rel
        original = path.read_text(encoding="utf-8")
        if find not in original:
            print(f"  STALE ANCHOR  {label}\n      not found in {rel} -- this harness needs updating")
            continue
        try:
            path.write_text(original.replace(find, repl, 1), encoding="utf-8")
            rc, last = one(test_id)
            if rc != 0:
                caught += 1
                print(f"  RED (good)    {label}\n      {last}")
            else:
                print(f"  *** STILL GREEN -- THE ASSERTION IS DECORATION ***  {label}\n      {last}")
        finally:
            path.write_text(original, encoding="utf-8")
            assert path.read_text(encoding="utf-8") == original, f"failed to restore {rel}"

    rc, last = one("")
    print(f"\nrestored; full suite: {last}")
    ok = caught == len(CASES) and rc == 0
    print(f"{caught}/{len(CASES)} mutations caught -- "
          + ("ALL CAUGHT" if ok else "REVIEW THE LINES ABOVE"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
