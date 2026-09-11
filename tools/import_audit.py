#!/usr/bin/env python3
"""Derive the serving path's real third-party dependency set from the source, not from a list.

Commissioning found that nothing in this repo records what `backend/api.py` needs to run
(`api.py`'s own docstring calls the absence deliberate: the OS packages are simply expected
to be there). A hand-written list of imports is the same guesswork one step removed -- it
goes stale the first time somebody adds an import. So this parses every module instead.

Two questions matter and only one of them is "what is imported":

  * **Does it resolve on this interpreter, and at what version.** Resolution uses
    `importlib.util.find_spec`, which reads metadata without executing the module. Importing
    to test importability is what the API already does, and it is why a missing optional
    dependency currently kills startup instead of disabling one surface.
  * **Would a missing module break startup, or only one surface.** An import at module scope
    runs when the module loads; an import inside a function runs when that code path is first
    taken. A module-scope import with no `try/except ImportError` around it is load-bearing
    for import, and that is the set that must be present for the process to come up at all.

`--json` emits the same findings for a preflight check to consume, so the answer is
recomputed from the tree rather than pinned in a second file that can drift from it.
"""

from __future__ import annotations

import argparse
import ast
import importlib.metadata
import importlib.util
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path


def _repo_root() -> Path:
    """Find the root by its marker, not by counting parents.

    `backend/apps/test_path_fragility.py` enforces this and explains why: a `parents[N]`
    root is silent when it is wrong, because the wrong parent usually exists too. `api.py`'s
    own header records having got that wrong four separate times.
    """
    here = Path(__file__).resolve()
    for cand in (here, *here.parents):
        if (cand / "backend" / "api.py").is_file():
            return cand
    raise SystemExit(f"repo root not found above {here}: no backend/api.py marker")


ROOT = _repo_root()

# `archive/vendor-sdks/` is 15,297 files of vendored SDKs that nothing imports; `references/` is
# inspiration, never a source. Neither is the serving path. Every dot-directory is pruned as
# a class rather than by name -- the agent worktree directories are full duplicates of the
# tree that double every result with stale copies, and naming that one directly is what
# `test_no_claude_dependency.py` forbids in first-party source.
PRUNE_DIRS = {
    "node_modules", "__pycache__", "vendor", "references",
    "venv", "site-packages", "build", "dist",
}


def _pruned(name: str) -> bool:
    return name in PRUNE_DIRS or name.startswith(".")


# `backend/` is `sys.path[0]` at runtime because the unit runs `python3 backend/api.py`, and
# api.py itself inserts these two. A name resolvable under any of them is first-party.
FIRST_PARTY_ROOTS = ("backend", "backend/apps", "backend/apps/ravencalc", "tools", ".")


@dataclass
class Occurrence:
    path: str
    line: int
    module_scope: bool
    guarded: bool          # wrapped in try/except ImportError (or bare/Exception)
    is_test: bool


@dataclass
class Finding:
    name: str
    occurrences: list[Occurrence] = field(default_factory=list)

    @property
    def import_time(self) -> bool:
        """True when some non-test module-scope import is unguarded: needed to load."""
        return any(o.module_scope and not o.guarded and not o.is_test for o in self.occurrences)

    @property
    def in_serving_path(self) -> bool:
        return any(not o.is_test for o in self.occurrences)

    @property
    def only_tests(self) -> bool:
        return all(o.is_test for o in self.occurrences)


class ImportVisitor(ast.NodeVisitor):
    """Record each import with the two facts a plain grep cannot see: scope and guard."""

    def __init__(self, path: str, is_test: bool) -> None:
        self.path = path
        self.is_test = is_test
        self.found: list[tuple[str, Occurrence]] = []
        self._depth = 0          # >0 means inside a def/lambda/class body: lazy
        self._guard = 0          # >0 means inside a try that handles ImportError

    # -- scope tracking ---------------------------------------------------------------
    def _nested(self, node: ast.AST) -> None:
        self._depth += 1
        self.generic_visit(node)
        self._depth -= 1

    visit_FunctionDef = _nested
    visit_AsyncFunctionDef = _nested
    visit_Lambda = _nested

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        # A class body executes at import, so it is NOT lazy. Depth is unchanged.
        self.generic_visit(node)

    def visit_Try(self, node: ast.Try) -> None:
        handled = any(
            _handler_catches_import_error(h) for h in node.handlers
        )
        if handled:
            self._guard += 1
        for child in node.body:
            self.visit(child)
        if handled:
            self._guard -= 1
        # Imports in the except/else/finally arms are fallbacks; still guarded in spirit.
        for arm in (*node.handlers, *node.orelse, *node.finalbody):
            self._guard += 1
            self.visit(arm) if isinstance(arm, ast.AST) else None
            self._guard -= 1

    # -- the imports themselves -------------------------------------------------------
    def _record(self, name: str, lineno: int) -> None:
        top = name.split(".")[0]
        if not top:
            return
        self.found.append((top, Occurrence(
            path=self.path, line=lineno,
            module_scope=self._depth == 0, guarded=self._guard > 0, is_test=self.is_test,
        )))

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            self._record(alias.name, node.lineno)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node.level:
            return          # relative: first-party by construction
        if node.module:
            self._record(node.module, node.lineno)


def _handler_catches_import_error(h: ast.ExceptHandler) -> bool:
    if h.type is None:
        return True
    names = []
    if isinstance(h.type, ast.Name):
        names = [h.type.id]
    elif isinstance(h.type, ast.Tuple):
        names = [e.id for e in h.type.elts if isinstance(e, ast.Name)]
    elif isinstance(h.type, ast.Attribute):
        names = [h.type.attr]
    return any(n in ("ImportError", "ModuleNotFoundError", "Exception", "BaseException")
               for n in names)


# The API process is `python3 backend/api.py`, so `backend/` is sys.path[0]; api.py then
# inserts `apps/ravencalc` and `apps`. Nothing puts the per-app `.venv` directories on the
# path, which is why a module resolvable inside `apps/studio/.venv` is NOT resolvable to the
# process that serves. These three roots are the serving path, literally.
RUNTIME_PATH = ("backend", "backend/apps/ravencalc", "backend/apps")


def resolve_local(dotted: str) -> Path | None:
    """Resolve a dotted module name the way the running API process would."""
    parts = dotted.split(".")
    for root in RUNTIME_PATH:
        base = ROOT / root
        pkg = base.joinpath(*parts)
        if (pkg / "__init__.py").is_file():
            return pkg / "__init__.py"
        mod = base.joinpath(*parts[:-1]) / f"{parts[-1]}.py"
        if mod.is_file():
            return mod
        # `backend/apps/` carries no __init__.py -- it is a namespace package, and
        # `from apps import streamer` (api.py:112) resolves against it only because
        # `backend/` is sys.path[0]. Treating it as unresolvable reports the repo's own
        # package tree as a missing third-party dependency.
        if pkg.is_dir() and any(pkg.glob("*.py")):
            return pkg
    return None


def reachable_from(entry: Path) -> tuple[dict[str, Path], list[dict]]:
    """Walk module-scope unguarded imports out from an entry point.

    This is the difference between "imported by the process that serves" and "present in the
    backend tree". `backend/` holds surfaces that only ever run as their own subprocess with
    their own interpreter; their dependencies are not startup dependencies, and treating them
    as such is how a dependency manifest ends up demanding torch to serve a calculator.
    """
    seen: dict[str, Path] = {}
    third: list[dict] = []
    queue: list[tuple[str, Path]] = [("__main__", entry)]
    stdlib = set(sys.stdlib_module_names)

    while queue:
        name, path = queue.pop(0)
        if name in seen:
            continue
        seen[name] = path
        if path.is_dir():          # namespace package: no module body to execute
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"), filename=str(path))
        except SyntaxError:
            continue
        v = ImportVisitor(str(path.relative_to(ROOT)), is_test=False)
        v.visit(tree)
        # Re-walk for dotted names: ImportVisitor records top-level only.
        for node in ast.walk(tree):
            targets: list[str] = []
            if isinstance(node, ast.Import):
                targets = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and not node.level and node.module:
                targets = [node.module] + [f"{node.module}.{a.name}" for a in node.names]
            else:
                continue
            # Only module-scope unguarded imports load at startup.
            occ = next((o for t, o in v.found
                        if o.line == node.lineno), None)
            if occ is None or not occ.module_scope or occ.guarded:
                continue
            for dotted in targets:
                top = dotted.split(".")[0]
                if top in stdlib:
                    continue
                local = resolve_local(dotted)
                if local is not None:
                    queue.append((dotted, local))
                elif resolve_local(top) is None:
                    ok, ver = resolve(top)
                    third.append({
                        "module": top, "resolves": ok, "version": ver,
                        "needed_by": str(path.relative_to(ROOT)), "line": node.lineno,
                    })
    return seen, third


def is_test_path(rel: str) -> bool:
    p = Path(rel)
    return (
        p.name.startswith("test_")
        or p.name.endswith("_test.py")
        or p.name == "conftest.py"
        or "tests" in p.parts
    )


def iter_py(base: Path) -> list[Path]:
    out: list[Path] = []
    for p in base.rglob("*.py"):
        if any(_pruned(part) for part in p.relative_to(base).parts[:-1]):
            continue
        out.append(p)
    return sorted(out)


def first_party_names() -> set[str]:
    """Every top-level name importable from the paths the runtime actually has."""
    names: set[str] = set()
    for rel in FIRST_PARTY_ROOTS:
        d = ROOT / rel
        if not d.is_dir():
            continue
        for child in d.iterdir():
            if _pruned(child.name):
                continue
            if child.is_dir() and (child / "__init__.py").exists():
                names.add(child.name)
            elif child.is_dir():
                names.add(child.name)      # namespace package; api.py relies on these
            elif child.suffix == ".py":
                names.add(child.stem)
    return names


def resolve(name: str) -> tuple[bool, str]:
    """Resolve without importing. Returns (found, version-or-reason)."""
    try:
        spec = importlib.util.find_spec(name)
    except (ImportError, ValueError, ModuleNotFoundError) as exc:
        return False, f"unresolvable ({type(exc).__name__})"
    except Exception as exc:                       # a parent package that raises on import
        return False, f"error ({type(exc).__name__}: {exc})"
    if spec is None:
        return False, "MISSING"
    for probe in (name, name.replace("_", "-")):
        try:
            return True, importlib.metadata.version(probe)
        except importlib.metadata.PackageNotFoundError:
            continue
    # Present but no distribution metadata: built-in, OS-packaged, or a local shim.
    origin = spec.origin or "namespace"
    return True, f"no-dist-metadata ({origin})"


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--base", default="backend", help="subtree to scan (default: backend)")
    ap.add_argument("--graph", action="store_true",
                    help="only what backend/api.py transitively loads at import time")
    args = ap.parse_args(argv)

    if args.graph:
        entry = ROOT / "backend" / "api.py"
        mods, third = reachable_from(entry)
        by_name: dict[str, dict] = {}
        for t in third:
            by_name.setdefault(t["module"], t)
        if args.json:
            print(json.dumps({
                "entry": str(entry.relative_to(ROOT)),
                "local_modules_loaded": len(mods),
                "startup_requirements": sorted(by_name.values(), key=lambda r: r["module"]),
            }, indent=2))
            return 0
        print(f"import-time reachability from {entry.relative_to(ROOT)}")
        print(f"  first-party modules loaded at startup: {len(mods)}")
        print(f"\n  {'module':<14} {'resolves':<9} {'version':<12} needed by")
        missing = []
        for r in sorted(by_name.values(), key=lambda r: r["module"]):
            if not r["resolves"]:
                missing.append(r["module"])
            print(f"  {r['module']:<14} {'yes' if r['resolves'] else 'NO':<9} "
                  f"{r['version'][:12]:<12} {r['needed_by']}:{r['line']}")
        print(f"\n  startup third-party requirements: {len(by_name)};  unresolved: {len(missing)}")
        if missing:
            print(f"  MISSING: {', '.join(missing)}")
        return 1 if missing else 0

    base = ROOT / args.base
    findings: dict[str, Finding] = {}
    unparsed: list[str] = []
    files = iter_py(base)

    for path in files:
        rel = str(path.relative_to(ROOT))
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"), filename=rel)
        except SyntaxError as exc:
            unparsed.append(f"{rel}: {exc}")
            continue
        v = ImportVisitor(rel, is_test_path(str(path.relative_to(base))))
        v.visit(tree)
        for top, occ in v.found:
            findings.setdefault(top, Finding(top)).occurrences.append(occ)

    stdlib = set(sys.stdlib_module_names)
    local = first_party_names()
    third = {n: f for n, f in findings.items() if n not in stdlib and n not in local}

    rows = []
    for name, f in sorted(third.items()):
        ok, ver = resolve(name)
        rows.append({
            "module": name,
            "resolves": ok,
            "version": ver,
            "import_time": f.import_time,
            "in_serving_path": f.in_serving_path,
            "tests_only": f.only_tests,
            "files": len({o.path for o in f.occurrences}),
            "first_seen": f"{f.occurrences[0].path}:{f.occurrences[0].line}",
        })

    if args.json:
        print(json.dumps({
            "scanned_files": len(files),
            "unparsed": unparsed,
            "third_party": rows,
        }, indent=2))
        return 0

    print(f"scanned {len(files)} .py files under {args.base}/ "
          f"(pruned: dot-directories, {', '.join(sorted(PRUNE_DIRS))})")
    if unparsed:
        print(f"\n!! {len(unparsed)} file(s) did not parse:")
        for u in unparsed:
            print(f"   {u}")

    def show(title: str, sel) -> None:
        sub = [r for r in rows if sel(r)]
        print(f"\n== {title} ({len(sub)}) ==")
        print(f"  {'module':<14} {'resolves':<9} {'version':<34} files  first seen")
        for r in sub:
            print(f"  {r['module']:<14} {'yes' if r['resolves'] else 'NO':<9} "
                  f"{r['version']:<34} {r['files']:>5}  {r['first_seen']}")

    show("HARD: module-scope, unguarded, serving path -- missing one breaks startup",
         lambda r: r["import_time"])
    show("OPTIONAL: lazy or guarded in the serving path -- missing one degrades a surface",
         lambda r: not r["import_time"] and r["in_serving_path"])
    show("TESTS ONLY -- not needed to serve",
         lambda r: r["tests_only"])

    missing_hard = [r["module"] for r in rows if r["import_time"] and not r["resolves"]]
    print(f"\n  third-party modules: {len(rows)};  "
          f"hard: {sum(1 for r in rows if r['import_time'])};  "
          f"unresolved hard: {len(missing_hard)}")
    if missing_hard:
        print(f"  MISSING AND REQUIRED: {', '.join(missing_hard)}")
    return 1 if missing_hard else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
