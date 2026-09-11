#!/usr/bin/env python3
"""Write the measured half of every backend/<component>/README.md.

    python3 tools/build/build_component_readmes.py            # write
    python3 tools/build/build_component_readmes.py --check     # fail if a write would change

## Why generated, and why only half

Twenty-five components need a README each, and the half that lists routes, modules and
documents is the half that goes stale first -- it is a reading of the tree and the schema, so
it should be read, not typed. This project has published a figure that was never true of the
commit beside it; a route table maintained by hand is the same failure waiting.

The other half is the reason the component exists, and no generator knows that. So this
writes ONLY between the markers below and never touches a line outside them. A new README
gets a stub above the markers saying what to write; filling it in is the job.

    <!-- generated: do not edit below -->
    ...
    <!-- end generated -->

Run it twice and diff. Every generator in this repository re-reads its own output, and one
that does not recognise what it emits accumulates it -- one copy per run, three times now.
"""
from __future__ import annotations

import argparse
import ast
import pathlib
import sys

ROOT = next(p for p in pathlib.Path(__file__).resolve().parents
            if (p / "backend" / "server.py").is_file())
BACKEND = ROOT / "backend"
OPEN, CLOSE = "<!-- generated: do not edit below -->", "<!-- end generated -->"

SKIP = {"__pycache__", "output", "retired"}


def first_line(path: pathlib.Path) -> str:
    """The module's one-line summary, or ''. Never raises on a file that will not parse."""
    try:
        doc = ast.get_docstring(ast.parse(path.read_text(encoding="utf-8", errors="replace")))
    except (SyntaxError, ValueError):
        return ""
    if not doc:
        return ""
    line = doc.strip().split("\n")[0].strip()
    # A docstring that opens "<name>: ..." repeats the filename beside it in the table.
    return line.split(": ", 1)[1] if line.lower().startswith(path.stem.lower() + ": ") else line


def operations(app, component: str) -> list[tuple[str, str, str]]:
    """(method, path, summary) for every route this component mounts, from the app itself."""
    out = []
    for r in app.routes:
        path = getattr(r, "path", "")
        mod = getattr(getattr(r, "endpoint", None), "__module__", "") or ""
        if not mod.split(".")[0] == component:
            continue
        methods = sorted(getattr(r, "methods", None) or ["WS"]) or ["WS"]
        summary = (getattr(r, "summary", "") or
                   (getattr(r, "description", "") or "").strip().split("\n")[0])
        out.append((methods[0], path, summary[:72]))
    return sorted(set(out), key=lambda t: (t[1], t[0]))


def table(rows: list[tuple[str, ...]], head: tuple[str, ...]) -> list[str]:
    if not rows:
        return []
    body = ["| " + " | ".join(head) + " |", "|" + "---|" * len(head)]
    body += ["| " + " | ".join(c.replace("|", r"\|") for c in r) + " |" for r in rows]
    return body


def modules(d: pathlib.Path, sub: str) -> list[tuple[str, str]]:
    p = d / sub
    if not p.is_dir():
        return []
    return [(f"`{f.name}`", first_line(f))
            for f in sorted(p.rglob("*.py")) if f.name != "__init__.py"]


def generated(d: pathlib.Path, app) -> str:
    name = d.name
    out: list[str] = [OPEN, ""]
    ops = operations(app, name)
    if ops:
        out += [f"## Operations — {len(ops)}", ""]
        out += table([(m, f"`{p}`", s) for m, p, s in ops], ("", "path", "what it does"))
        out += [""]
    else:
        out += ["## Operations", "",
                "None. This component is a library for others, or is driven from the "
                "desktop session rather than over HTTP.", ""]
    for sub, title in (("models", "Request and response models"),
                       ("lib", "Library — no routes, no side effects on import"),
                       ("apps", "Programs — runnable, or driven by a route")):
        rows = modules(d, sub)
        if rows:
            out += [f"## {title}", ""] + table(rows, ("file", "")) + [""]
    docs = sorted((d / "docs").glob("*")) if (d / "docs").is_dir() else []
    if docs:
        out += ["## Documents", ""]
        out += [f"- [`{f.name}`](docs/{f.name})" for f in docs] + [""]
    out += [CLOSE]
    return "\n".join(out)


STUB = """# backend/{name}/

> **Write this paragraph.** What is this surface for, who calls it, and what will bite
> someone changing it? The table below is generated and cannot answer any of those.
> Delete this block when you have.

"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()

    sys.path.insert(0, str(BACKEND))
    import server                                                    # noqa: E402

    stale, written = [], 0
    for d in sorted(BACKEND.iterdir()):
        if not d.is_dir() or d.name.startswith((".", "__")) or d.name in SKIP:
            continue
        block = generated(d, server.app)
        readme = d / "README.md"
        old = readme.read_text(encoding="utf-8") if readme.is_file() else ""
        if OPEN in old and CLOSE in old:
            head, _, rest = old.partition(OPEN)
            _, _, tail = rest.partition(CLOSE)
            new = head + block + tail
        else:
            new = (old.rstrip() + "\n\n" if old else STUB.format(name=d.name)) + block + "\n"
        if new == old:
            continue
        if args.check:
            stale.append(str(readme.relative_to(ROOT)))
        else:
            readme.write_text(new, encoding="utf-8")
            written += 1

    if args.check:
        if stale:
            print("stale, regenerate: " + " ".join(stale), file=sys.stderr)
            return 1
        print("  every component README is current")
        return 0
    print(f"  {written} component READMEs written")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
