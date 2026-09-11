#!/usr/bin/env python3
"""SyMoNeuRaL Bootcamp -- the SCOUT. Measures the roster so the depth charts cannot drift.

## Why this exists

`docs/specs/symoneural-bootcamp.md` declares, for every app instance, which model is
the STARTER and which are CANDIDATES. That document is worthless the moment it disagrees with
the disk -- a depth chart claiming Qwen is the chat starter after somebody edited `CHAT_MODEL` is
worse than no matrix, because it reads authoritative.

So the depth chart does not hand-write its facts. This script reads them:

  * routes            parsed from the AST of api.py and every backend/*/ module
  * models on disk    scanned, with `general.architecture` read out of each GGUF header
  * serving defaults  read from the assignments in api.py, not from memory
  * env flags         grepped from the modules that gate on them

Anything this script cannot measure is a JUDGEMENT -- captain policy, team priority, risk
scores, recommendations -- and those live in the document, written by a person, clearly
separated from the measured spine. The split is the point: **a figure in a depth chart is either
measured here or labelled as an opinion there.**

Run:
    python3 tools/lib/bootcamp_scout.py            # human-readable
    python3 tools/lib/bootcamp_scout.py --json     # for the doc generator / progress page
"""
from __future__ import annotations

import ast
import json
import pathlib
import re
import struct
import sys

ROOT = next(_p for _p in pathlib.Path(__file__).resolve().parents if (_p / "backend" / "server.py").is_file())
BACKEND = ROOT / "backend"
APPS = BACKEND / "apps"
API_PY = BACKEND / "api.py"
MODELS = BACKEND / "models"

# GGUF metadata value type -> byte width, for scalars we only need to skip over.
_GGUF_SCALAR = {0: 1, 1: 1, 2: 2, 3: 2, 4: 4, 5: 4, 6: 4, 7: 1, 10: 8, 11: 8, 12: 8}


def gguf_arch(path: pathlib.Path) -> str | None:
    """`general.architecture` from a GGUF header, or None.

    Same contract as `api.py:_gguf_arch` and deliberately a separate copy: this is a
    measurement tool and must not import the serving module to take a reading. Total by
    design -- a non-GGUF file, a truncated one or a directory all return None.
    """
    try:
        with open(path, "rb") as fh:
            if fh.read(4) != b"GGUF":
                return None
            _ver, _nt, n_kv = struct.unpack("<IQQ", fh.read(20))

            def skip(vtype: int) -> None:
                if vtype == 8:
                    (n,) = struct.unpack("<Q", fh.read(8))
                    fh.seek(n, 1)
                elif vtype == 9:
                    (elem,) = struct.unpack("<I", fh.read(4))
                    (n,) = struct.unpack("<Q", fh.read(8))
                    for _ in range(n):
                        skip(elem)
                else:
                    fh.seek(_GGUF_SCALAR[vtype], 1)

            for _ in range(min(n_kv, 4096)):
                (klen,) = struct.unpack("<Q", fh.read(8))
                key = fh.read(klen)
                (vtype,) = struct.unpack("<I", fh.read(4))
                if key == b"general.architecture" and vtype == 8:
                    (n,) = struct.unpack("<Q", fh.read(8))
                    return fh.read(n).decode("utf-8", "replace")
                skip(vtype)
    except Exception:
        return None
    return None


def routes_in(path: pathlib.Path) -> list[dict]:
    """Every HTTP/WS route declared in one module, from the AST rather than a grep.

    A grep over decorator text misses `@router.get` when the router is aliased and cannot
    tell a route from a string that looks like one in a docstring. Walking the tree gets the
    method and the literal path together, which is what the depth chart needs.
    """
    out: list[dict] = []
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except Exception:
        return out
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for dec in node.decorator_list:
            if not (isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute)):
                continue
            method = dec.func.attr
            if method not in {"get", "post", "put", "patch", "delete", "websocket"}:
                continue
            if not (dec.args and isinstance(dec.args[0], ast.Constant)
                    and isinstance(dec.args[0].value, str)):
                continue
            out.append({"method": method.upper(), "path": dec.args[0].value,
                        "handler": node.name})
    return out


def serving_defaults() -> dict:
    """The model constants api.py actually assigns, read from its AST."""
    wanted = {"CHAT_MODEL", "DRAFT_MODEL", "CHAT_ADAPTER", "CHAT_MODEL_LABEL",
              "ASR_MODEL", "IMAGE_UNET", "IMAGE_T5", "IMAGE_CLIP", "IMAGE_VAE"}
    found: dict[str, str] = {}
    tree = ast.parse(API_PY.read_text(encoding="utf-8"))
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        for t in node.targets:
            if isinstance(t, ast.Name) and t.id in wanted:
                found[t.id] = ast.unparse(node.value)
    return found


def weights_on_disk() -> list[dict]:
    """Every weight file under backend/models, with its measured size and architecture."""
    exts = {".gguf", ".safetensors", ".bin", ".pt", ".onnx"}
    rows = []
    if not MODELS.is_dir():
        return rows
    for p in sorted(MODELS.rglob("*")):
        if not p.is_file() or p.suffix not in exts:
            continue
        rows.append({
            "path": str(p.relative_to(ROOT)),
            "bytes": p.stat().st_size,
            "arch": gguf_arch(p) if p.suffix == ".gguf" else None,
            "staged": "staging" in p.parts,
        })
    return rows


def manifested() -> set[str]:
    """Paths PROVENANCE.json claims to describe -- the provenance-covered set."""
    man = MODELS / "PROVENANCE.json"
    if not man.is_file():
        return set()
    try:
        data = json.loads(man.read_text(encoding="utf-8"))
    except Exception:
        return set()
    rows = data if isinstance(data, list) else data.get("weights", data.get("models", []))
    return {f"backend/models/{r['path']}" for r in rows if isinstance(r, dict) and "path" in r}


#: Path segments that mean "somebody else's code vendored into this tree".
#:
#: Without this the survey is nonsense in a way that looks authoritative: the first run
#: reported `sigils` at 4,185 Python files and `studio` at 3,442, which are the vendored
#: site-packages under each, and it attributed env flags like XDG_CONFIG_HOME, PIP_NO_COLOR
#: and NUMBA_DUMP_LLVM to SyMoNeuRaL apps. A depth chart built on that would claim the Studio app
#: gates on `ANTHROPIC_API_KEY` when it is an SDK inside it that does.
VENDOR_MARKERS = {"site-packages", "vendor", "vendored", ".venv", "venv", "node_modules",
                  "__pycache__", ".pytest_cache", "dist-packages", "third_party", "_vendor"}


def is_vendored(path: pathlib.Path) -> bool:
    return any(part in VENDOR_MARKERS or part.endswith((".dist-info", ".egg-info"))
               for part in path.parts)


ENV_RE = re.compile(r'os\.environ(?:\.get\(|\[)["\']([A-Z0-9_]+)["\']')


def env_flags(path: pathlib.Path) -> set[str]:
    try:
        return set(ENV_RE.findall(path.read_text(encoding="utf-8")))
    except Exception:
        return set()


def survey() -> dict:
    """One measured record for the whole surface."""
    apps: dict[str, dict] = {}
    for d in sorted(APPS.iterdir()):
        if not d.is_dir() or d.name.startswith("__") or d.name.startswith("."):
            continue
        routes: list[dict] = []
        flags: set[str] = set()
        own = [py for py in sorted(d.rglob("*.py")) if not is_vendored(py)]
        for py in own:
            routes.extend(routes_in(py))
            flags |= env_flags(py)
        vendored = sum(1 for py in d.rglob("*.py") if is_vendored(py))
        apps[d.name] = {
            "module": str(d.relative_to(ROOT)),
            "routes": routes,
            "route_count": len(routes),
            # Only flags the app's OWN code reads. Anything a vendored SDK reads is that
            # SDK's business and must not be attributed to the app.
            "env_flags": sorted(f for f in flags if f.startswith("SYMONEURAL")
                                or f.startswith("SYMON_") or f.startswith("DJ_")),
            "foreign_env_flags": sorted(f for f in flags if not (
                f.startswith("SYMONEURAL") or f.startswith("SYMON_") or f.startswith("DJ_"))),
            "py_files": len(own),
            "vendored_py_files": vendored,
        }

    disk = weights_on_disk()
    cov = manifested()
    return {
        "apps": apps,
        "api_py_routes": routes_in(API_PY),
        "serving_defaults": serving_defaults(),
        "weights": disk,
        "weight_count": len(disk),
        "weight_bytes": sum(w["bytes"] for w in disk),
        "unmanifested": [w["path"] for w in disk if w["path"] not in cov and not w["staged"]],
        "architectures": sorted({w["arch"] for w in disk if w["arch"]}),
    }


def main() -> int:
    s = survey()
    if "--json" in sys.argv:
        print(json.dumps(s, indent=2))
        return 0

    print("SyMoNeuRaL Bootcamp -- SCOUT REPORT (measured roster)\n")
    print(f"app modules            : {len(s['apps'])}")
    print(f"routes in api.py       : {len(s['api_py_routes'])}")
    print(f"routes in app modules  : {sum(a['route_count'] for a in s['apps'].values())}")
    tot = len(s["api_py_routes"]) + sum(a["route_count"] for a in s["apps"].values())
    print(f"TOTAL declared routes  : {tot}")
    print(f"weight files on disk   : {s['weight_count']}  "
          f"({s['weight_bytes'] / 2**30:.2f} GiB)")
    print(f"architectures present  : {', '.join(s['architectures']) or 'none readable'}")
    print(f"unmanifested weights   : {len(s['unmanifested'])}  "
          f"(excludes staging, which is a candidate tree by definition)")
    print("\nserving defaults, read from api.py:")
    for k, v in sorted(s["serving_defaults"].items()):
        print(f"  {k:18} = {v}")
    print("\nper app:")
    for name, a in sorted(s["apps"].items()):
        print(f"  {name:14} {a['route_count']:>3} routes  {a['py_files']:>2} py"
              f"  {'flags: ' + ','.join(a['env_flags']) if a['env_flags'] else ''}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
