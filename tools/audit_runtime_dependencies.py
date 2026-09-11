#!/usr/bin/env python3
"""Read-only inventory of dependency declarations, imports, and runtime homes.

This does not install, copy, build, or delete anything.  It gives Coder and reviewers one
repeatable report before a shipping cleanup:

    python3 tools/audit_runtime_dependencies.py
    python3 tools/audit_runtime_dependencies.py --json

The import inventory is evidence, not an automatic package resolver: Python import names
and distribution names are not always identical (``PIL`` is Pillow, ``bs4`` is
beautifulsoup4, and so on).
"""
from __future__ import annotations

import argparse
import ast
import functools
import json
import pathlib
import re
import sys
import tomllib
from typing import Iterable

ROOT = pathlib.Path(__file__).resolve().parents[1]

REQUIREMENTS = (
    "backend/remix/requirements.txt",
    "backend/studio/requirements.txt",
    "backend/studio/plugins/discovery/symoneural-discovery.requirements.txt",
    "backend/studio/plugins/reinforce/requirements.txt",
    "backend/cryptominer/SyMon_MinerGPUWorker_PROD_20260102-1818/requirements.txt",
)

PYPROJECTS = (
    "backend/remix/pyproject.toml",
    "backend/studio/plugins/reinforce/pyproject.toml",
    "yocto/oematch/pyproject.toml",
)

LOCKS = (
    "backend/gateway/Cargo.lock",
    "desktop-client/src-tauri/Cargo.lock",
    "tests/package-lock.json",
)

RUNTIME_HOMES = (
    "symoneural-llm",
    "symoneural-diffuse",
    "symoneural-ui",
    "symoneural-listen",
)

IMPORT_AREAS = {
    "serving_apps": (ROOT / "backend" / "apps",),
    "training": (ROOT / "training",),
}

# Explicit repository safety boundary: these files are outside this inventory's scope.
PROTECTED = {
    ROOT / "training" / "corpus.jsonl",
    ROOT / "training" / "build_dataset.py",
}

SKIP_PARTS = {".git", ".venv", "node_modules", "__pycache__", "vendor", "external", "tests"}
FIRST_PARTY = {"apps", "backend", "tools", "training", "tests", "yocto"}


def requirement_names(path: pathlib.Path) -> list[str]:
    names: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or line.startswith(("-r", "--")):
            continue
        match = re.match(r"([A-Za-z0-9_.-]+)", line)
        if match:
            names.append(match.group(1))
    return sorted(set(names), key=str.lower)


def pyproject_names(path: pathlib.Path) -> list[str]:
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    project = data.get("project", {})
    values = list(project.get("dependencies", []))
    for group in project.get("optional-dependencies", {}).values():
        values.extend(group)
    own_name = str(project.get("name", "")).lower().replace("_", "-")
    names = []
    for value in values:
        match = re.match(r"([A-Za-z0-9_.-]+)", value)
        if match:
            name = match.group(1)
            if name.lower().replace("_", "-") != own_name:
                names.append(name)
    return sorted(set(names), key=str.lower)


def python_files(roots: Iterable[pathlib.Path]) -> Iterable[pathlib.Path]:
    for root in roots:
        if root.is_file() and root.suffix == ".py":
            candidates = (root,)
        elif root.is_dir():
            candidates = root.rglob("*.py")
        else:
            continue
        for path in candidates:
            if (path in PROTECTED or path.name == "conftest.py" or
                    path.name.startswith("test_") or
                    any(part in SKIP_PARTS for part in path.parts)):
                continue
            yield path


@functools.lru_cache(maxsize=1)
def first_party_import_names() -> frozenset[str]:
    """Names this tree can resolve locally, including its short sibling imports."""
    names = set(FIRST_PARTY)
    roots = (ROOT / "backend", ROOT / "tools", ROOT / "training", ROOT / "yocto")
    for path in python_files(roots):
        names.add(path.stem)
        parent = path.parent
        if (parent / "__init__.py").exists():
            names.add(parent.name)
    return frozenset(names)


def imports_for(roots: Iterable[pathlib.Path]) -> dict[str, list[str]]:
    found: dict[str, set[str]] = {}
    local_names = first_party_import_names()
    for path in python_files(roots):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            names: list[str] = []
            if isinstance(node, ast.Import):
                names = [item.name.split(".", 1)[0] for item in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                names = [node.module.split(".", 1)[0]]
            for name in names:
                if name in sys.stdlib_module_names or name in local_names:
                    continue
                found.setdefault(name, set()).add(str(path.relative_to(ROOT)))
    return {name: sorted(paths) for name, paths in sorted(found.items())}


def asr_path_references() -> list[dict[str, object]]:
    hits: list[dict[str, object]] = []
    for rel in ("backend/voice/asr.py", "backend/sigils/listen.py",
                "scripts/fetch-whisper.sh"):
        path = ROOT / rel
        if not path.exists():
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if "contrib" in line or "symoneural-listen" in line:
                hits.append({"path": rel, "line": number, "text": line.strip()})
    return hits


def collect() -> dict[str, object]:
    requirements = {
        rel: requirement_names(ROOT / rel)
        for rel in REQUIREMENTS if (ROOT / rel).exists()
    }
    pyprojects = {
        rel: pyproject_names(ROOT / rel)
        for rel in PYPROJECTS if (ROOT / rel).exists()
    }
    return {
        "requirements": requirements,
        "pyprojects": pyprojects,
        "locks": {rel: (ROOT / rel).exists() for rel in LOCKS},
        "training_lock_present": any(
            (ROOT / "training" / name).exists()
            for name in ("requirements.txt", "pyproject.toml", "uv.lock", "poetry.lock")),
        "imports": {name: imports_for(roots) for name, roots in IMPORT_AREAS.items()},
        "runtime_homes": {rel: (ROOT / rel).exists() for rel in RUNTIME_HOMES},
        "reference_inputs_present": (ROOT / "external").exists(),
        "asr_path_references": asr_path_references(),
    }


def render_text(report: dict[str, object]) -> str:
    lines = ["SyMoNeuRaL dependency/runtime inventory", ""]
    for kind in ("requirements", "pyprojects"):
        lines.append(f"{kind}:")
        for path, names in report[kind].items():
            lines.append(f"  {path}: {', '.join(names) or '(none)'}")
        lines.append("")
    lines.append("locks:")
    for path, present in report["locks"].items():
        lines.append(f"  {'present' if present else 'MISSING':7} {path}")
    lines.append(f"  {'present' if report['training_lock_present'] else 'MISSING':7} training declaration/lock")
    lines.append("")
    lines.append("runtime homes:")
    for path, present in report["runtime_homes"].items():
        lines.append(f"  {'present' if present else 'absent':7} {path}")
    lines.append(f"  {'present' if report['reference_inputs_present'] else 'absent':7} external/ build inputs")
    lines.append("")
    for area, imports in report["imports"].items():
        lines.append(f"non-stdlib import names in {area} ({len(imports)}):")
        lines.append("  " + (", ".join(imports) if imports else "(none)"))
        lines.append("")
    lines.append("ASR runtime path references:")
    for hit in report["asr_path_references"]:
        lines.append(f"  {hit['path']}:{hit['line']}: {hit['text']}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="emit machine-readable JSON")
    args = parser.parse_args()
    report = collect()
    if args.json:
        print(json.dumps(report, indent=2, sort_keys=True))
    else:
        print(render_text(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
