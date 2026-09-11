#!/usr/bin/env python3
"""Check everything the API needs before it needs it, and say what to do about each gap.

    python3 tools/lib/preflight.py            # human-readable, exits non-zero on any hard failure
    python3 tools/lib/preflight.py --json     # same findings, machine-readable

The failure mode this replaces: `backend/server.py` dies at import with a traceback naming one
module, which tells an operator what Python could not find but not what to install, and stops
at the first problem so a box missing three packages takes three attempts to diagnose. This
checks everything, then reports every gap at once with the `apt` line that fixes it.

Two classes of requirement, and the distinction is the useful part:

  * **start** -- the process cannot come up without it. Measured: these are the distributions
    that end up in `sys.modules` when `backend/server.py` is imported.
  * **serve** -- the process comes up fine and one surface 500s on first request. `sympy` is
    the live case: `import ravencalc` is inside a function at `api.py:1166`, so a box with no
    sympy starts green and fails the moment somebody uses the calculator. Reporting a green
    start on such a box is exactly the overstatement commissioning exists to prevent.

Beyond those two, absence is reported in two SEPARATE lists, because conflating them cost
real confusion on 2026-09-09:

  * **elsewhere** -- installed by design in its own virtualenv and checked against THAT
    interpreter. The reinforce trainer's torch/transformers/peft/trl/datasets all live in
    `training/.venv`; asking the serving interpreter for them answers nothing, and printing
    the answer as UNAVAILABLE made a ready training stack look switched off.
  * **dark** -- absent from every interpreter on the box, so the surface genuinely cannot
    run. `cupy` is the live case.

Neither fails the check. They are not the same thing.

The declared lists below are checked against live measurement by
`backend/test_preflight.py`, so adding an import to the serving path without adding it
here turns that test red rather than silently weakening this one.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path


def _repo_root() -> Path:
    """Find the root by its marker, not by counting parents."""
    here = Path(__file__).resolve()
    for cand in (here, *here.parents):
        if (cand / "backend" / "server.py").is_file():
            return cand
    raise SystemExit(f"repo root not found above {here}: no backend/server.py marker")


ROOT = _repo_root()

#: module -> the Debian package that provides it. Every one of these was measured as
#: dpkg-owned; see ops/registry/SERVING-MANIFEST.md. Keeping the package name here is the point:
#: "No module named 'starlette'" is not an instruction, "apt install python3-starlette" is.
START = {
    "annotated_types": "python3-annotated-types",
    "anyio": "python3-anyio",
    "attr": "python3-attr",
    "bcrypt": "python3-bcrypt",
    "brotli": "python3-brotli",
    "click": "python3-click",
    "cryptography": "python3-cryptography",
    "email_validator": "python3-email-validator",
    "fastapi": "python3-fastapi",
    "httpx": "python3-httpx",
    "idna": "python3-idna",
    "pydantic": "python3-pydantic",
    "pydantic_core": "python3-pydantic-core",
    "pygments": "python3-pygments",
    "python_multipart": "python3-python-multipart",
    "rich": "python3-rich",
    "sniffio": "python3-sniffio",
    "starlette": "python3-starlette",
    "typing_extensions": "python3-typing-extensions",
    "websockets": "python3-websockets",
}

#: `ExecStart` runs api.py as a script, and `uvicorn.run` is inside the `__main__` guard at
#: api.py:4137 -- so uvicorn is needed to serve but never appears in an import of the module.
#: It would be invisible to a check that only measured imports.
START_SCRIPT_ONLY = {"uvicorn": "python3-uvicorn"}

#: Needed to serve a surface, not to start the process.
SERVE = {
    "sympy": ("python3-sympy", "/api/ravencalc",
              "import ravencalc is inside a function at api.py:1166"),
}

# The word "optional" used to cover two incompatible situations and the owner called it out
# on 2026-09-09: "that word is doing two incompatible jobs." It was. A feature deliberately
# built to run in its own interpreter, and a feature that cannot run because nothing installed
# it, both printed as "UNAVAILABLE ... which is not a failure". Reading that, the reinforce
# trainer looked switched off when its whole stack -- torch, transformers, peft, trl, datasets,
# accelerate -- was installed and ready in `training/.venv`.
#
# They are now two dicts, and ELSEWHERE is checked against the interpreter that actually owns
# the package rather than this one.

#: Installed by design in its own virtualenv, NOT in the serving interpreter. Checked against
#: that venv's python. "absent" here means the venv is genuinely missing the package -- a real
#: gap -- not that the serving interpreter lacks it, which is correct and expected.
ELSEWHERE = {
    "transformers": ("training/.venv", "the reinforce trainer"),
    "peft": ("training/.venv", "the reinforce trainer (adapters)"),
    "trl": ("training/.venv", "the reinforce trainer (RL)"),
    "datasets": ("training/.venv", "the reinforce trainer (data)"),
    "torch": ("training/.venv", "the reinforce trainer, and the GGUF custom node"),
    "accelerate": ("training/.venv", "the reinforce trainer (device placement)"),
    "rembg": ("backend/sigils/.venv", "the sigils cut-out worker"),
    "onnxruntime": ("backend/sigils/.venv", "the sigils cut-out worker (inference)"),
    "pyasic": ("backend/asicminer/.venv", "the ASIC rig probe"),
}

#: Genuinely gates a surface: absent everywhere on this box, so the surface cannot run.
#: Still never a hard failure -- the API starts and serves without them -- but "UNAVAILABLE"
#: here means a feature is dark, not that it lives somewhere else.
OPTIONAL = {
    "PIL": "the remix cover art surface",
    "yaml": "the studio exp plugin loader",
    "bs4": "the studio discovery plugin",
    "cupy": "the reinforce CUDA compute engine (compute/ops.py:17 imports it unguarded)",
    "cuda": "the reinforce training bench (CUDA python bindings)",
    "playwright": "the studio discovery crawler",
}


def resolves_in_venv(venv: str, name: str) -> tuple[bool, str]:
    """Does `name` resolve in that virtualenv's interpreter?

    The point of the whole ELSEWHERE table: asking THIS interpreter whether `transformers`
    is importable answers a question nobody has. The serving path has no virtualenv by
    policy, so the answer is always no, and printing that as UNAVAILABLE made a fully
    installed training stack look dark.
    """
    py = ROOT / venv / "bin" / "python3"
    if not py.is_file():
        return False, f"no interpreter at {venv}/bin/python3"
    r = subprocess.run(
        [str(py), "-c",
         "import importlib.util as u,sys;"
         f"s=u.find_spec({name!r});"
         "print(getattr(s,'origin','') or 'present' if s else '')"],
        capture_output=True, text=True, timeout=60)
    out = r.stdout.strip()
    return bool(out), (f"in {venv}" if out else f"MISSING from {venv}")


def resolves(name: str) -> tuple[bool, str]:
    """Resolve without importing -- importing to test importability is what we are replacing."""
    try:
        spec = importlib.util.find_spec(name)
    except Exception as exc:
        return False, f"error: {type(exc).__name__}"
    if spec is None:
        return False, "missing"
    try:
        import importlib.metadata as md
        return True, md.version(name)
    except Exception:
        return True, "present"


def structural() -> list[dict]:
    """The non-package prerequisites, each of which has bitten this repo before."""
    out: list[dict] = []

    gov = ROOT / "scripts" / "gpu-governor.sh"
    out.append({
        "check": "gpu-governor.sh present",
        "ok": gov.is_file(),
        "detail": str(gov),
        "fix": f"restore {gov.relative_to(ROOT)} -- api.py asserts on it at import (api.py:58) "
               "and will not start without it",
    })

    run = ROOT / "run"
    writable = run.is_dir() and os.access(run, os.W_OK)
    out.append({
        "check": "run/ exists and is writable",
        "ok": writable,
        "detail": str(run),
        "fix": f"mkdir -p {run} && chown google:google {run}",
    })

    # RUN must be <root>/run, never backend/run: gpu-governor.sh takes its mkdir lock in
    # <root>/run, and two lock directories would let two tenants each load weights onto a
    # 16 GB card. api.py:59-64 documents this as the reason ROOT is not HERE.
    out.append({
        "check": "run/ resolves beside backend/, not inside it",
        "ok": (ROOT / "run").is_dir() and not (ROOT / "backend" / "run").is_dir(),
        "detail": f"{ROOT / 'run'} present; {ROOT / 'backend' / 'run'} must not exist",
        "fix": "a backend/run directory means something computed ROOT as HERE; the governor "
               "and the API would take different locks and both could load weights",
    })

    cfg = ROOT / "run" / "config"
    out.append({
        "check": "run/config/ present (the real env-file directory)",
        "ok": cfg.is_dir(),
        "detail": f"{cfg} -- NOT /etc/symoneural/api.env, which does not exist on this box",
        "fix": f"mkdir -p {cfg}; runtimeconfig.py:126 resolves here",
    })

    return out


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    findings: dict[str, list] = {"start": [], "serve": [], "optional": [],
                                 "elsewhere": [], "structural": []}

    for name, pkg in sorted({**START, **START_SCRIPT_ONLY}.items()):
        ok, ver = resolves(name)
        findings["start"].append({"module": name, "package": pkg, "ok": ok, "version": ver})

    for name, (pkg, surface, why) in sorted(SERVE.items()):
        ok, ver = resolves(name)
        findings["serve"].append({"module": name, "package": pkg, "ok": ok,
                                  "version": ver, "surface": surface, "why": why})

    for name, surface in sorted(OPTIONAL.items()):
        ok, ver = resolves(name)
        findings["optional"].append({"module": name, "ok": ok, "version": ver,
                                     "surface": surface})

    for name, (venv, surface) in sorted(ELSEWHERE.items()):
        ok, where = resolves_in_venv(venv, name)
        findings["elsewhere"].append({"module": name, "ok": ok, "venv": venv,
                                      "where": where, "surface": surface})

    findings["structural"] = structural()

    bad_start = [f for f in findings["start"] if not f["ok"]]
    bad_serve = [f for f in findings["serve"] if not f["ok"]]
    bad_struct = [f for f in findings["structural"] if not f["ok"]]
    hard = len(bad_start) + len(bad_serve) + len(bad_struct)

    if args.json:
        print(json.dumps({"findings": findings, "hard_failures": hard}, indent=2))
        return 1 if hard else 0

    print(f"preflight for {ROOT}")
    print(f"  interpreter: {sys.executable} {sys.version.split()[0]}")

    print(f"\n== required to START ({len(findings['start'])}) ==")
    for f in findings["start"]:
        print(f"  {'ok ' if f['ok'] else 'NO '} {f['module']:<18} {f['version']}")

    print(f"\n== required to SERVE a surface ({len(findings['serve'])}) ==")
    for f in findings["serve"]:
        print(f"  {'ok ' if f['ok'] else 'NO '} {f['module']:<18} {f['version']:<12} "
              f"{f['surface']}")
        if not f["ok"]:
            print(f"      why it is not a startup failure: {f['why']}")

    print(f"\n== installed in their own venv, NOT here -- by design "
          f"({len(findings['elsewhere'])}) ==")
    print("   absence in THIS list is a real gap; absence from the serving interpreter is not.")
    for f in findings["elsewhere"]:
        state = "ok " if f["ok"] else "GAP"
        print(f"  {state} {f['module']:<14} {f['where']:<34} {f['surface']}")

    print(f"\n== absent everywhere on this box -- these surfaces are dark "
          f"({len(findings['optional'])}) ==")
    for f in findings["optional"]:
        state = "available" if f["ok"] else "DARK"
        print(f"  {state:<12} {f['module']:<14} {f['surface']}")

    print("\n== structural ==")
    for f in findings["structural"]:
        print(f"  {'ok ' if f['ok'] else 'NO '} {f['check']}")
        if not f["ok"]:
            print(f"      {f['detail']}")
            print(f"      fix: {f['fix']}")

    if not hard:
        dark = sum(1 for f in findings["optional"] if not f["ok"])
        gaps = sum(1 for f in findings["elsewhere"] if not f["ok"])
        print("\nPREFLIGHT OK -- every hard requirement to start and serve is present.")
        print(f"  {dark} surface(s) DARK (absent everywhere: a feature that cannot run).")
        print(f"  {gaps} venv GAP(s) (a package missing from the venv that owns it).")
        print("  Neither fails the API. They are not the same thing and are no longer "
              "printed as if they were.")
        return 0

    print(f"\nPREFLIGHT FAILED -- {hard} hard problem(s).")
    pkgs = [f["package"] for f in bad_start + bad_serve]
    if pkgs:
        print("\n  install the missing packages:")
        print(f"    sudo apt install {' '.join(sorted(set(pkgs)))}")
    for f in bad_serve:
        print(f"\n  NOTE: {f['module']} is missing. The service WILL start and "
              f"{f['surface']} will fail on first request. A green start does not mean "
              "this box can serve.")
    for f in bad_struct:
        print(f"\n  {f['check']}: {f['fix']}")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
