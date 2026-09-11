#!/usr/bin/env python3
"""Record what the API process really loads, by loading it -- not by parsing it.

`tools/import_audit.py` reads the source, which is the only way to tell a lazy import from
an import-time one. But a static walk has to reimplement Python's resolution rules
(namespace packages, relative imports, the two `sys.path.insert` calls in api.py), and an
approximation of those rules silently under-reports: the first version of that walk missed
every `from . import x` in the tree and so reported four startup dependencies when there
were more.

So this measures the same thing the other way round: it imports `backend/api.py` in a
subprocess set up exactly as the unit sets it up -- `sys.path[0] = backend/` because
`ExecStart` is `python3 backend/api.py` -- and reports the third-party distributions that
ended up in `sys.modules`. `uvicorn.run` is behind `if __name__ == "__main__"`, so importing
builds the app without binding the port.

The two tools disagreeing is the interesting signal, not a nuisance: static says what *can*
be needed, dynamic says what *was* needed on this box for this configuration.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path


def _repo_root() -> Path:
    """Find the root by its marker, not by counting parents.

    `backend/apps/test_path_fragility.py` enforces this and explains why: a `parents[N]`
    root is silent when it is wrong, because the wrong parent usually exists too.
    """
    here = Path(__file__).resolve()
    for cand in (here, *here.parents):
        if (cand / "backend" / "api.py").is_file():
            return cand
    raise SystemExit(f"repo root not found above {here}: no backend/api.py marker")


ROOT = _repo_root()
BACKEND = ROOT / "backend"

# Runs inside the subprocess. Imports the app, then classifies every loaded module.
PROBE = r"""
import json, sys, importlib.metadata as md

before = set(sys.modules)
status = {"imported": False, "error": None}
try:
    import api                      # the module the unit runs as a script
    status["imported"] = True
except BaseException as exc:        # SystemExit/AssertionError are both plausible here
    status["error"] = f"{type(exc).__name__}: {exc}"

ROOT = %(root)r
stdlib = set(sys.stdlib_module_names)

# Interpreter-provided site hooks. Python imports these itself before any application code
# runs, and they ship inside libpython3.13-minimal -- i.e. inside the interpreter, not
# alongside it. Reporting them as third-party dependencies would put "apt install
# libpython3.13-minimal" on a list of things to install to get Python working.
stdlib |= {"sitecustomize", "usercustomize", "apport_python_hook"}

# Map every installed distribution to the top-level names it provides, so a module can be
# attributed to the package an operator would actually have to install.
top2dist = {}
for dist in md.distributions():
    name = dist.metadata["Name"]
    if not name:
        continue
    try:
        tops = (dist.read_text("top_level.txt") or "").split()
    except Exception:
        tops = []
    for t in tops or [name.replace("-", "_")]:
        top2dist.setdefault(t, (name, dist.version))

third, firstparty = {}, set()
for mod in sorted(set(sys.modules) - {None}):
    top = mod.split(".")[0]
    if top in stdlib or top.startswith("_") or mod != top:
        continue
    m = sys.modules.get(mod)
    f = getattr(m, "__file__", None) or ""
    if f.startswith(ROOT) and "/site-packages/" not in f and "/dist-packages/" not in f:
        firstparty.add(top)
        continue
    if m is None:
        continue
    if not f:                        # builtin/frozen with no file
        continue
    dist, ver = top2dist.get(top, (None, None))
    if dist is None:
        try:
            ver = md.version(top); dist = top
        except Exception:
            dist, ver = None, "no-dist-metadata"
    third[top] = {"module": top, "distribution": dist, "version": ver, "file": f}

print("@@JSON@@" + json.dumps({
    "status": status,
    "third_party": sorted(third.values(), key=lambda r: r["module"]),
    "first_party_count": len(firstparty),
    "modules_total": len(sys.modules),
    "new_modules": len(set(sys.modules) - before),
}))
"""


def probe() -> dict:
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)      # the unit sets none; inheriting one would fake success
    proc = subprocess.run(
        [sys.executable, "-c", PROBE % {"root": str(ROOT)}],
        cwd=str(BACKEND), env=env, capture_output=True, text=True, timeout=300,
    )
    payload = None
    for line in proc.stdout.splitlines():
        if line.startswith("@@JSON@@"):
            payload = json.loads(line[len("@@JSON@@"):])
    if payload is None:
        raise SystemExit(
            "probe produced no result\n"
            f"--- exit {proc.returncode} ---\n{proc.stdout[-4000:]}\n{proc.stderr[-4000:]}"
        )
    payload["stderr_tail"] = proc.stderr[-4000:]
    payload["exit"] = proc.returncode
    return payload


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    r = probe()
    if args.json:
        print(json.dumps(r, indent=2))
        return 0 if r["status"]["imported"] else 1

    st = r["status"]
    print(f"imported backend/api.py with sys.path[0]={BACKEND}")
    print(f"  result: {'OK' if st['imported'] else 'FAILED -- ' + str(st['error'])}")
    print(f"  modules in sys.modules: {r['modules_total']}  "
          f"(first-party top-level: {r['first_party_count']})")
    print(f"\n  {'module':<16} {'distribution':<20} {'version':<12} location")
    for m in r["third_party"]:
        loc = m["file"]
        for pre, tag in (("/usr/lib/python3/dist-packages/", "OS dist-packages"),
                         ("/usr/local/lib/", "local"),
                         (str(ROOT), "in-repo")):
            if loc.startswith(pre):
                loc = tag
                break
        print(f"  {m['module']:<16} {str(m['distribution']):<20} "
              f"{str(m['version'])[:12]:<12} {loc}")
    print(f"\n  third-party distributions loaded to serve: {len(r['third_party'])}")
    if r["stderr_tail"].strip():
        print("\n--- stderr ---")
        print(r["stderr_tail"].strip()[-2000:])
    return 0 if st["imported"] else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
