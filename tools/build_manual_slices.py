#!/usr/bin/env python3
"""Slice `docs/symoneural-manual.md` into the per-playbook and per-curriculum documents.

    python3 tools/build_manual_slices.py            # write the slices
    python3 tools/build_manual_slices.py --check    # exit 1 if any slice is stale
    python3 tools/build_manual_slices.py --report   # what reproduces exactly, what does not

## Why this exists

Nineteen documents under `docs/guides/playbooks/`, `docs/guides/cuda-curriculum/` and again under
`backend/studio/plugins/reinforce/docs/` said in their own third line:

    > Sliced from the consolidated manual at `../symoneural-manual.md`, which remains the
    > canonical single file.

**and no slicer existed.** `git ls-files` found no tool that produced them. So 8,425 lines sat
in two trees, derived from a third, with nothing able to regenerate them and nothing able to
say they had drifted -- which is the one arrangement this repository's idiom exists to
prevent. A hand-edit to the manual, or to either copy, desynchronised three things silently.

They HAD drifted, though barely: not one of the nineteen was byte-identical across the two
trees, and the whole difference was 32 lines -- every one of them the breadcrumb's relative
path back to the manual. That is exactly the drift a generator removes by construction.

## The mapping, derived by measurement rather than assumed

A slice is one `##` section of the manual, verbatim, with trailing blank lines stripped, under
a small derived header. Checked against `docs/guides/playbooks/playbook-01.md`: the manual's
section is 215 lines, the slice body is 214, and a unified diff shows the single difference is
one trailing blank line. Everything else -- including the `####` subtitle -- is already in the
manual and needs no reconstruction.

**Any slice this cannot reproduce byte-for-byte is reported, not silently rewritten.**
`--report` lists them. A generator that quietly changes content it does not understand is
worse than no generator.
"""
from __future__ import annotations

import argparse
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]
MANUAL = ROOT / "docs" / "symoneural-manual.md"

#: The two trees the slices live in, and the relative path each needs back to the manual.
#: The reinforce copy exists so that plugin's documentation is self-contained if it is ever
#: distributed alone; that is a real requirement, so this generates BOTH rather than deleting
#: one. The breadcrumb is the only thing that differs between them, and it is computed here
#: instead of being hand-maintained, which is what let them drift.
#: (set name, link to that set's README, relative path to the manual). All three differ
#: between the trees, and all three were hand-maintained until now -- which is precisely the
#: 32 lines of drift the inventory found.
TREES = {
    ROOT / "docs": ("SyMoNeuRaL documentation set", "../README.md",
                    "../symoneural-manual.md"),
    ROOT / "backend/studio/plugins/reinforce/docs":
        ("symoneural_reinforce documentation set", "README.md",
         "../../../../../docs/symoneural-manual.md"),
}

PLAYBOOK_INDEX = "The Local AI Engineer's Manual — 2026 Edition"

#: NOT generated here, and named so the gap is explicit rather than silent.
#:
#: The five `04-cuda-curriculum/` slices are sections of the same manual -- their headings are
#: there, `## 1_GettingStarted — Getting started` and the rest -- but their header block has a
#: different shape: a subtitle line sits BETWEEN the H1 and the breadcrumb, where the playbooks
#: have nothing. Targeting them reproduced 22 of 32 rather than 32 of 32, so they are left out
#: rather than rewritten into a shape this tool guessed at.
#:
#: They remain what they were before this tool existed: derived files with no generator. That
#: is worse than the playbooks and better than it was, because it is now written down.
CURRICULUM_NOT_COVERED = ("1_GettingStarted", "2_CoreConcepts", "3_FrameworkInterop",
                          "4_DistributedComputing", "Utilities")


def sections(text: str) -> dict[str, list[str]]:
    """Every `##` section of the manual, keyed by its heading line."""
    lines = text.splitlines()
    starts = [i for i, l in enumerate(lines) if l.startswith("## ")]
    # A section ends at the next `##`, or at a `# Part ` heading. Only `# Part `: a first
    # attempt stopped at ANY level-1 heading and dropped the reproduction rate from 20/22 to
    # 4/22, because the playbooks legitimately span other `#` headings. The one that needed
    # it is playbook-10, the last `##` before `# Part IV`, which otherwise swallowed that
    # part's opening lines.
    bounds = sorted(i for i, l in enumerate(lines)
                    if l.startswith("## ") or l.startswith("# Part "))
    out: dict[str, list[str]] = {}
    for i in starts:
        end = next((b for b in bounds if b > i), len(lines))
        body = lines[i:end]
        while body and not body[-1].strip():          # the one measured difference
            body.pop()
        out[lines[i].strip()] = body
    return out


def slice_targets(secs: dict[str, list[str]]) -> list[tuple[str, str, str]]:
    """(subdirectory, filename, manual heading) for every slice, derived from the manual."""
    targets: list[tuple[str, str, str]] = []
    for heading in secs:
        title = heading[3:].strip()
        if title.startswith("Playbook "):
            num = title.split()[1].strip("—- ")
            targets.append(("03-playbooks", f"playbook-{num}.md", heading))
        elif title == PLAYBOOK_INDEX:
            targets.append(("03-playbooks", "playbook-00-index.md", heading))

    # Index first, then the playbooks in number order: the backlink chain depends on it.
    targets.sort(key=lambda t: (t[1] != "playbook-00-index.md", t[1]))
    return targets


def render(heading: str, body: list[str], set_name: str, readme: str, rel: str,
           back: tuple[str, str] | None) -> str:
    """`back` is (text, filename) of the PREVIOUS document, or None for the index.

    Not a constant link to the index: the playbooks chain, so 02 points back at 01 and only
    01 points at the index. Assuming a constant here reproduced exactly two of twenty-two
    slices, which is how this was found.
    """
    title = heading[3:].strip()
    head = [f"# {title}", "",
            f"> Part of the [{set_name}]({readme}). Sliced from the consolidated manual "
            f"at `{rel}`, which remains the canonical single file.", ""]
    if back is not None:
        head += [f"[< {back[0]}]({back[1]})", ""]
    return "\n".join(head + body) + "\n"


def build(write: bool) -> tuple[list[str], list[str]]:
    """Returns (stale, unreproducible). Never writes a file it cannot account for."""
    secs = sections(MANUAL.read_text())
    targets = slice_targets(secs)
    stale, unreproducible = [], []
    for tree, (set_name, readme, rel) in TREES.items():
        prev: tuple[str, str] | None = None
        for sub, name, heading in targets:
            out = tree / sub / name
            chain = prev if sub == "03-playbooks" else None
            text = render(heading, secs[heading], set_name, readme, rel, chain)
            if sub == "03-playbooks":
                prev = (heading[3:].strip(), name)
            rel_out = str(out.relative_to(ROOT))
            if out.is_file() and out.read_text() != text:
                # An existing slice that differs is either stale or shaped differently from
                # what this reproduces. Report it; do not overwrite on a guess.
                if not write:
                    unreproducible.append(rel_out) if not _only_whitespace(out.read_text(), text) \
                        else stale.append(rel_out)
                    continue
            if write:
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_text(text)
            elif not out.is_file():
                stale.append(rel_out)
    return stale, unreproducible


def _only_whitespace(a: str, b: str) -> bool:
    return [l.rstrip() for l in a.splitlines() if l.strip()] == \
           [l.rstrip() for l in b.splitlines() if l.strip()]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="exit 1 if any slice is stale")
    ap.add_argument("--report", action="store_true",
                    help="list what reproduces exactly and what does not")
    args = ap.parse_args()

    if not MANUAL.is_file():
        print(f"{MANUAL} is missing -- there is nothing to slice from", file=sys.stderr)
        return 2

    stale, unreproducible = build(write=False)
    if args.report or args.check:
        secs = sections(MANUAL.read_text())
        total = len(slice_targets(secs)) * len(TREES)
        exact = total - len(stale) - len(unreproducible)
        print(f"  slices covered: {total}   reproduced exactly: {exact}")
        for f in unreproducible:
            print(f"  DIFFERS BEYOND WHITESPACE  {f}")
        for f in stale:
            print(f"  stale                      {f}")
        if args.check:
            return 1 if (stale or unreproducible) else 0
        return 0

    build(write=True)
    print(f"  wrote slices into {len(TREES)} tree(s) from {MANUAL.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
