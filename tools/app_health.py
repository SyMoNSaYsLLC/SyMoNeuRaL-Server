#!/usr/bin/env python3
"""Which surfaces are actually neglected? Measure it out of git, do not guess.

"The apps that don't work or have hardly anything done to them" is answerable from the
repository itself, and answering it by reading code is how you get an opinion instead of
a reading. Four numbers per app, all of them cheap:

- **commits** touching the app, and **days since** the last one -- git is the record of
  what has had attention.
- **lines** of Python/JS/HTML the app is made of.
- **tests** it carries, counted by collecting them, not by grepping for `def test_`.
  A file full of tests that cannot import collects zero, and that is the finding.
- whether it is **wired**: does anything outside the app import or mount it? An app no
  router reaches is shipped in name only.

The output ranks by neglect so the top of the list is where the work is. Nothing here
edits anything.

    python3 tools/app_health.py
"""
from __future__ import annotations

import json
import pathlib
import re
import subprocess
import sys
import time

REPO = pathlib.Path(__file__).resolve().parents[1]
BACKEND = REPO / "backend"
APPS = BACKEND / "apps"

CODE = (".py", ".js", ".mjs", ".ts", ".html", ".css")
SKIP = {"__pycache__", ".venv", "node_modules", ".git", "dist", "build"}


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=REPO, capture_output=True,
                          text=True).stdout.strip()


def commit_history(path: pathlib.Path) -> tuple[int, float, str]:
    """(commits, days since last, subject of last) for everything under `path`."""
    rel = str(path.relative_to(REPO))
    log = git("log", "--format=%ct%x09%s", "--", rel)
    if not log:
        return 0, float("inf"), ""
    lines = log.splitlines()
    newest = int(lines[0].split("\t", 1)[0])
    subject = lines[0].split("\t", 1)[1] if "\t" in lines[0] else ""
    return len(lines), (time.time() - newest) / 86400.0, subject


def size(path: pathlib.Path) -> tuple[int, int]:
    """(code lines, test lines). Test files are counted separately, never in the total."""
    code = tests = 0
    for f in path.rglob("*"):
        if not f.is_file() or f.suffix not in CODE:
            continue
        if any(part in SKIP for part in f.parts):
            continue
        try:
            n = sum(1 for _ in f.open("r", encoding="utf-8", errors="replace"))
        except OSError:
            continue
        if f.name.startswith("test_") or "/tests/" in str(f):
            tests += n
        else:
            code += n
    return code, tests


def collected(rel: str) -> int:
    """Ask pytest to collect, and take the number it reports.

    Grepping for `def test_` counts tests that cannot run. This repo has published a
    reading of a suite that collected nothing at all -- "no number, wearing the costume
    of a broken suite" -- so the count has to come from a collection.
    """
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", rel, "-q", "--collect-only",
         "-p", "no:cacheprovider"],
        cwd=BACKEND, capture_output=True, text=True, timeout=180)
    if "error" in proc.stdout.lower() and "collected" not in proc.stdout:
        return -1                                   # collection aborted: no reading
    m = re.search(r"(\d+) tests? collected", proc.stdout)
    if m:
        return int(m.group(1))
    m = re.search(r"^(\d+) tests? collected", proc.stdout, re.M)
    return int(m.group(1)) if m else -1


def wired(name: str) -> bool:
    """Does anything outside the app reach it? A router nobody mounts is not shipped."""
    hits = git("grep", "-l", "-E", f"apps[./]{re.escape(name)}", "--",
               "backend/api.py", "backend/apps", "tools", "tests")
    external = [h for h in hits.splitlines() if f"apps/{name}/" not in h]
    return bool(external)


def browser_coverage(name: str) -> tuple[str, str]:
    """(page it renders, browser suite that asserts on it) -- or "none".

    This is the column that matters and the reason this tool exists. Every app below
    carries pytest tests and every one of them is green; that says nothing about whether
    a visitor sees anything. #94 shipped a desktop client whose eighteen checks went
    green over a chat surface that was dead on arrival, and Studio's editor was 4% of
    the first viewport with a 16/16 suite passing over it. `exists` and `grep` ask what
    is written on disk. Only a browser asks whether it works.
    """
    site = REPO / "site"
    pages = [f.name for f in site.glob("*.html")
             if name in f.name or name in f.read_text(errors="replace")[:40000]]
    suites = [f.name for f in (REPO / "tests").glob("*.mjs")
              if name in f.name or name in f.read_text(errors="replace")]
    return (", ".join(sorted(pages)[:2]) or "none"), (", ".join(sorted(suites)[:2]) or "none")


def main() -> int:
    rows = []
    for app in sorted(p for p in APPS.iterdir() if p.is_dir() and p.name not in SKIP):
        commits, days, subject = commit_history(app)
        code, test_lines = size(app)
        rows.append({
            "app": app.name,
            "commits": commits,
            "days": days,
            "last": subject[:60],
            "code": code,
            "test_lines": test_lines,
            "tests": collected(f"apps/{app.name}"),
            "wired": wired(app.name),
        })
        rows[-1]["page"], rows[-1]["browser"] = browser_coverage(app.name)

    # Neglect, ranked: no tests at all outranks few tests, unwired outranks wired, and a
    # small app that nothing has touched in a week outranks a large one under active work.
    def neglect(r: dict) -> tuple:
        # An app with no browser suite ranks above one with few pytest tests: a green
        # pytest suite over a dead page is the failure this repo keeps repeating.
        return (r["browser"] != "none", r["tests"] > 0, r["wired"], r["tests"])

    rows.sort(key=neglect)
    w = max(len(r["app"]) for r in rows)
    print(f"{'app':<{w}}  {'tests':>6} {'code':>6} {'age':>6}  wired  {'page':<22} browser suite")
    for r in rows:
        tests = "ABORT" if r["tests"] < 0 else str(r["tests"])
        age = "never" if r["days"] == float("inf") else f"{r['days']:.1f}d"
        print(f"{r['app']:<{w}}  {tests:>6} {r['code']:>6} {age:>6}  "
              f"{'yes' if r['wired'] else 'NO ':>5}  {r['page'][:22]:<22} {r['browser']}")
    (REPO / "run").mkdir(exist_ok=True)
    (REPO / "run" / "app-health.json").write_text(json.dumps(rows, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
