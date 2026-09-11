"""Testing and benchmarking, read from the tree and from recorded results. Never asserted.

Owner, 2026-09-11: *"make sure to bring all testing and benchmarking also"*.

## Why this counts the tree instead of reading the counts out of MEASUREMENTS.md

`ops/docs/MEASUREMENTS.md` is the one home for suite counts and it is careful, dated prose --
which makes it the wrong thing to scrape. Its own first rule is the reason:

> *"A number with no SHA cannot be checked, only believed; a count carried forward and
> re-dated is the disease this ladder exists to cure."*

A parser that lifted "1758" out of a paragraph and put it on a live dashboard would strip the
SHA, the date and the three qualifying sentences around it, and would then show that number
forever -- which is precisely the failure the file is warning about, automated. The file
records that a published 1063 *"turned out never to have been true of the commit it sat beside"*.

So this module **counts what is on disk right now**, by parsing test files with `ast` and
tallying `test_*` functions. That is a live reading of the current tree, stamped with the
current HEAD, and it is honest about what it is: an inventory, **not a result**. Nothing here
claims anything passed.

## The distinction the page must keep visible

* **inventory** -- how many tests exist. Counted here, cheap, always current.
* **result** -- how many passed. Requires *running* them, and this module never does.

Those are different questions and a dashboard that blurs them is worse than one that answers
neither. `commands()` publishes the exact invocations from MEASUREMENTS.md so an operator can
get a result; `blockers()` says why some of them cannot run on this host today.

## Benchmarks are the opposite case, and are read rather than counted

`performance/results/*.json` are finished, dated, commit-pinned measurements with their own
comparability grades -- real results somebody produced deliberately. Those are read and
published as they stand, including the grades, because a benchmark number without its
comparability grade is the same class of half-truth as a count without a SHA.
"""
from __future__ import annotations

import ast
import json
import pathlib
import shutil
from typing import Any

REPO = next(_p for _p in pathlib.Path(__file__).resolve().parents if (_p / "backend" / "server.py").is_file())
BACKEND = REPO / "backend"
MEASUREMENTS = REPO / "ops" / "docs" / "MEASUREMENTS.md"
RESULTS = REPO / "performance" / "results"

#: Vendored third-party suites. Excluded from OUR inventory for the same reason
#: `backend/conftest.py` excludes them from our result: 15,297 tracked files with their own
#: tests, including e2e suites wanting network and provider credentials.
EXCLUDE = ("/vendor/", "/.venv/", "/node_modules/", "/external/", "/archive/")


def _is_ours(p: pathlib.Path) -> bool:
    s = p.as_posix()
    return not any(x in s for x in EXCLUDE)


def inventory() -> dict[str, Any]:
    """Count `test_*` functions and files on disk now. An INVENTORY, never a result."""
    files = 0
    tests = 0
    unreadable = 0
    by_area: dict[str, int] = {}
    for p in BACKEND.rglob("test_*.py"):
        if not _is_ours(p):
            continue
        files += 1
        try:
            tree = ast.parse(p.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            unreadable += 1
            continue
        n = sum(1 for node in ast.walk(tree)
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name.startswith("test"))
        tests += n
        # Area = the first path segment under backend/apps, so the page can show where the
        # coverage actually sits rather than one undifferentiated total.
        try:
            rel = p.relative_to(BACKEND / "apps").parts
            area = rel[0] if len(rel) > 1 else "(apps root)"
        except ValueError:
            area = "(backend root)"
        by_area[area] = by_area.get(area, 0) + n

    js = [p for p in (REPO / "tests").glob("*.mjs")] if (REPO / "tests").is_dir() else []
    return {
        "python_test_files": files,
        "python_test_functions": tests,
        "unparseable_files": unreadable,
        "browser_suites": len(js),
        "browser_suite_names": sorted(p.name for p in js),
        "by_area": dict(sorted(by_area.items(), key=lambda kv: -kv[1])),
        "source": f"ast walk of {BACKEND.relative_to(REPO)}/**/test_*.py, excluding "
                  f"{', '.join(EXCLUDE)}",
        "is_a_result": False,
        "note": ("this is how many tests EXIST, not how many pass. Passing requires running "
                 "them; see commands below. ops/docs/MEASUREMENTS.md is the record of "
                 "results, each with the commit it was read on."),
    }


def commands() -> list[dict[str, str]]:
    """The declared invocations, lifted from MEASUREMENTS.md's own command block.

    Read rather than restated, so a suite added to that file appears here without an edit --
    `backend/test_streamer_migration.py` already parses the same block for the same
    reason, and two parsers of one record is the shape this repo prefers to two records.
    """
    try:
        text = MEASUREMENTS.read_text(encoding="utf-8")
    except OSError:
        return []
    out = []
    for raw in text.splitlines():
        line = raw.strip()
        if not (line.startswith("node tests/") or line.startswith("python3 -m pytest")):
            continue
        cmd, _, comment = line.partition("#")
        out.append({"command": cmd.strip(), "note": comment.strip(),
                    "source": "ops/docs/MEASUREMENTS.md"})
    return out


def blockers() -> list[dict[str, Any]]:
    """What cannot run on this host, measured now rather than quoted from a doc.

    MEASUREMENTS.md states the browser blocker as of 2026-09-03. A dashboard quoting a dated
    blocker would keep showing it after somebody installed Chrome, so this checks.
    """
    found = next((b for b in ("google-chrome", "chromium", "chromium-browser")
                  if shutil.which(b)), None)
    chrome_path = pathlib.Path("/opt/google/chrome/chrome")
    playwright = pathlib.Path.home() / ".cache" / "ms-playwright"
    have_pw = playwright.is_dir() and any(playwright.iterdir())
    ok = bool(found) or chrome_path.exists() or have_pw
    return [{
        "what": "browser suites (every tests/*.mjs)",
        "blocked": not ok,
        "reason": ("no system Chrome and no Playwright browser cache on this host, so every "
                   "suite launching channel:'chrome' aborts" if not ok else
                   f"a browser is present ({found or chrome_path if chrome_path.exists() else playwright})"),
        "source": "shutil.which + path checks, run at request time",
    }]


def benchmarks() -> list[dict[str, Any]]:
    """Finished benchmark results, read as they stand with their comparability grades."""
    if not RESULTS.is_dir():
        return []
    out = []
    for p in sorted(RESULTS.glob("*.json")):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            out.append({"file": p.name, "error": f"unreadable ({type(exc).__name__})"})
            continue
        measurements = d.get("measurements") or []
        out.append({
            "file": p.name,
            "pass": d.get("pass"),
            "measured_on": d.get("measured_on"),
            "question": d.get("question") or d.get("purpose"),
            "answer": d.get("answer"),
            "measurement_count": len(measurements),
            # The grade travels with the number, always. See the module docstring.
            "measurements": [{
                "id": m.get("id"),
                "metric": m.get("metric") or m.get("testcase"),
                "unit": m.get("unit"),
                "mean": (m.get("stats") or {}).get("mean"),
                "median": (m.get("stats") or {}).get("median"),
                "comparability": m.get("comparability") or m.get("comparability_vs_historical"),
                "delta_pct": m.get("delta_mean_pct") or m.get("delta_vs_historical_pct"),
            } for m in measurements[:12]],
            "host": d.get("host_prerun") or {},
            "source": f"performance/results/{p.name}",
        })
    return out


def snapshot() -> dict[str, Any]:
    """Inventory, commands, blockers and finished benchmarks. All reads; nothing is executed."""
    return {
        "inventory": inventory(),
        "commands": commands(),
        "blockers": blockers(),
        "benchmarks": benchmarks(),
        "contract": ("nothing on this panel was executed to build it. Counts are an "
                     "inventory of what exists; benchmark figures are finished results read "
                     "from disk with their comparability grades attached."),
    }
