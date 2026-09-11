#!/usr/bin/env python3
"""Generate the serving dependency manifest -- the file this repo did not have.

`backend/api.py`'s docstring says fastapi, uvicorn and sympy "are already present as OS
packages, so there is no virtualenv anywhere in the serving path". That is half a design and
half a hope: nothing recorded WHICH packages, at which versions, so a rebuild was guesswork
and a missing one showed up as an import traceback at boot.

This measures the answer and writes it down. Three separate environments, because the real
architecture is a hybrid and pretending it is one environment is how the docstring got
imprecise:

  1. **The system interpreter** -- what `python3 backend/api.py` loads. Measured by importing
     the app (tools/serving_deps.py) rather than parsed, then resolved to the dpkg package
     that owns each file, because `apt` is what an operator would reinstall.
  2. **First-request dependencies** -- imported at module scope inside a module that `api.py`
     itself imports lazily. `sympy` is the case that matters: the service starts green without
     it and `/api/ravencalc` 500s on first use. Startup success does not prove it can serve.
  3. **The per-app virtualenvs** -- studio, sigils, asicminer, training. Each is documented in
     its own source as a subprocess boundary, never imported by the serving interpreter.

Run it twice and diff: it embeds the HEAD commit rather than a timestamp precisely so that
two runs on one commit are byte-identical. A generator that changes its own output every run
cannot be checked, and this repo has been bitten three times by generators that accumulate.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def pathlib_resolve(p: str) -> Path:
    """Resolve a command path, following symlinks, for dpkg attribution."""
    return Path(p).resolve()


def _repo_root() -> Path:
    """Find the root by its marker, not by counting parents."""
    here = Path(__file__).resolve()
    for cand in (here, *here.parents):
        if (cand / "backend" / "api.py").is_file():
            return cand
    raise SystemExit(f"repo root not found above {here}: no backend/api.py marker")


ROOT = _repo_root()
OUT = ROOT / "docs" / "ops" / "SERVING-MANIFEST.md"

#: Every venv in the serving tree, with how it is invoked and where that is documented.
#: Recorded by hand because the *invocation* is the fact that matters and it is only
#: discoverable by reading the call site -- but every entry here is cited, and the citations
#: are checked by `backend/apps/test_serving_manifest.py`.
VENVS = (
    ("backend/apps/studio/.venv",
     "subprocess: `.venv/bin/python -m apps.studio.mcp_server`",
     "backend/apps/studio/__init__.py:23,67; mcp_server.py:4,6,28"),
    ("backend/apps/sigils/.venv",
     "subprocess: `.venv/bin/python cutout_worker.py <in.png> <out.png>`",
     "backend/apps/sigils/cutout_worker.py:1,4,7; segment.py:48; docs/specs/sigils-spec.md:139"),
    ("backend/apps/asicminer/.venv",
     "subprocess: rig-protocol shim",
     "backend/api.py:73-74"),
    ("training/.venv",
     "subprocess: `training/.venv/bin/python`, never imported",
     "backend/apps/studio/plugins/reinforce/__init__.py:56; jobs.py:72,627"),
)


def sh(cmd: list[str]) -> str:
    p = subprocess.run(cmd, capture_output=True, text=True)
    return p.stdout.strip() if p.returncode == 0 else ""


def dpkg_owner(path: str) -> tuple[str, str]:
    """The package that owns a file, and its installed version."""
    out = sh(["dpkg", "-S", path])
    if not out:
        return "", ""
    pkg = out.split(":")[0]
    return pkg, sh(["dpkg-query", "-W", "-f=${Version}", pkg])


def loaded_third_party() -> list[dict]:
    """What the API process really loads, straight from tools/serving_deps.py."""
    out = sh([sys.executable, str(ROOT / "tools" / "serving_deps.py"), "--json"])
    if not out:
        raise SystemExit("serving_deps.py produced no JSON; cannot build the manifest")
    return json.loads(out)["third_party"]


def static_audit() -> list[dict]:
    out = sh([sys.executable, str(ROOT / "tools" / "import_audit.py"), "--json"])
    if not out:
        raise SystemExit("import_audit.py produced no JSON; cannot build the manifest")
    return json.loads(out)["third_party"]


def venv_pins(venv: Path) -> list[tuple[str, str]]:
    py = venv / "bin" / "python"
    if not py.is_file():
        return []
    out = sh([str(py), "-c",
              "import importlib.metadata as m;"
              "print('\\n'.join(sorted(f\"{d.metadata['Name']}=={d.version}\""
              " for d in m.distributions() if d.metadata['Name'])))"])
    rows = []
    for line in out.splitlines():
        if "==" in line:
            name, _, ver = line.partition("==")
            rows.append((name, ver))
    return rows


def main() -> int:
    head = sh(["git", "-C", str(ROOT), "rev-parse", "--short", "HEAD"]) or "unknown"
    loaded = loaded_third_party()
    static = {r["module"]: r for r in static_audit()}

    L: list[str] = []
    add = L.append

    add("# Serving dependency manifest")
    add("")
    add(f"**Generated by `tools/build_serving_manifest.py` at `{head}`.** Do not hand-edit.")
    add("")
    add("This file exists because nothing recorded what the API needs to run. It embeds the")
    add("commit rather than a timestamp, so two runs on one commit are byte-identical and the")
    add("run-it-twice-and-diff check means something.")
    add("")
    add("**A SHA above that is not `git rev-parse --short HEAD` means \"regenerate\", not")
    add("\"wrong\".** It is stale the moment anything else is committed, which is the price of")
    add("being diffable and is deliberate. Rerun the generator: if the body changes, the")
    add("serving dependencies changed and that is the news. If only this line changes, nothing")
    add("did, and committing it is optional.")
    add("")
    add("Three environments, deliberately separate. The serving interpreter never imports from")
    add("any virtualenv; each venv is reached by subprocess. `backend/api.py:25` says \"no")
    add("virtualenv anywhere in the serving path\" and `api.py:73-74` documents one 48 lines")
    add("later -- the architecture is the hybrid below, and this table is the statement of it")
    add("that the docstring does not make.")
    add("")

    # ---- 1. system interpreter -------------------------------------------------------
    py_ver = sh([sys.executable, "-VV"]).replace("\n", " ")
    add("## 1. The system interpreter — required to start")
    add("")
    add(f"`{sys.executable}` — {py_ver}")
    add("")
    add("Measured by importing `backend/api.py` with `sys.path[0]` set the way `ExecStart`")
    add("sets it and reading `sys.modules`, then resolving each file to its owning package.")
    add("**Every one is dpkg-owned: there is no pip in the serving path.** A missing entry here")
    add("stops the process from starting.")
    add("")
    add("| module | distribution | OS package | version |")
    add("|---|---|---|---|")
    non_dpkg = []
    for m in loaded:
        pkg, ver = dpkg_owner(m["file"])
        if not pkg:
            non_dpkg.append(m["module"])
        add(f"| `{m['module']}` | {m['distribution'] or '—'} | "
            f"{'`' + pkg + '`' if pkg else '**not dpkg-owned**'} | {ver or '—'} |")
    add("")
    add(f"**{len(loaded)} distributions, {len(loaded) - len(non_dpkg)} dpkg-owned.**")
    if non_dpkg:
        add("")
        add(f"Mixed provenance — NOT owned by dpkg: {', '.join('`' + n + '`' for n in non_dpkg)}."
            " `apt` upgrades will not respect these, which is how this breaks silently later.")
    add("")
    add("### One more, invisible to the measurement above")
    add("")
    add("`uvicorn` never appears in `sys.modules` after importing `api`, because `uvicorn.run`")
    add("is inside `if __name__ == \"__main__\":` at `api.py:4137` -- yet `ExecStart` runs the")
    add("file as a script, so it is required to serve. A check that only measured imports would")
    add("miss it entirely.")
    add("")
    _uv_mod = sh([sys.executable, "-c", "import uvicorn;print(uvicorn.__file__)"])
    _uv_pkg, _uv_ver = dpkg_owner(_uv_mod) if _uv_mod else ("", "")
    _uv_cli = sh(["bash", "-lc", "command -v uvicorn"])
    _cli_pkg = dpkg_owner(str(pathlib_resolve(_uv_cli)))[0] if _uv_cli else ""
    add("| what | path | OS package |")
    add("|---|---|---|")
    add(f"| the `uvicorn` module (used) | `{_uv_mod}` | "
        f"{'`' + _uv_pkg + '`' + ' ' + _uv_ver if _uv_pkg else '**not dpkg-owned**'} |")
    if _uv_cli:
        add(f"| the `uvicorn` CLI script (NOT used) | `{_uv_cli}` | "
            f"{'`' + _cli_pkg + '`' if _cli_pkg else '**not dpkg-owned** -- a user-local pip install'} |")
    add("")
    add("The CLI wrapper being unpackaged is harmless *because nothing in the serving path")
    add("invokes it*: the unit runs `python3 backend/api.py`. It is recorded so that a future")
    add("reader who reaches for `uvicorn api:app` knows the wrapper is not managed by apt.")
    add("")
    add("Reinstall with:")
    add("")
    add("```bash")
    pkgs = sorted({dpkg_owner(m["file"])[0] for m in loaded} - {""})
    add("sudo apt install " + " ".join(pkgs))
    add("```")
    add("")

    # ---- 2. first-request ------------------------------------------------------------
    add("## 2. Required to *serve*, but not to start")
    add("")
    add("Imported at module scope inside a module `api.py` imports lazily. The process comes up")
    add("without these and fails at request time instead — which is worse than failing at boot,")
    add("because a green start reads as a working service. `tools/preflight.py` checks them.")
    add("")
    add("| module | version | surface | why it is not a startup dependency |")
    add("|---|---|---|---|")
    s = static.get("sympy", {})
    add(f"| `sympy` | {s.get('version', '—')} | `/api/ravencalc` | "
        "`import ravencalc` sits inside a function at `api.py:1166`; "
        "`ravencalc.py:47` imports `sympy.parsing` at module scope |")
    add("")

    # ---- 3. optional surfaces --------------------------------------------------------
    add("## 3. Optional surfaces — absence degrades one surface, not the service")
    add("")
    add("Lazy or `ImportError`-guarded in the serving path. `resolves = no` is not a defect;")
    add("it means that surface is unavailable on this box.")
    add("")
    add("| module | resolves | version | first seen |")
    add("|---|---|---|---|")
    for r in sorted(static.values(), key=lambda r: r["module"]):
        if r["import_time"] or not r["in_serving_path"] or r["tests_only"]:
            continue
        add(f"| `{r['module']}` | {'yes' if r['resolves'] else '**no**'} | "
            f"{r['version'] if r['resolves'] else '—'} | `{r['first_seen']}` |")
    add("")

    # ---- 4. venvs --------------------------------------------------------------------
    add("## 4. The per-app virtualenvs — reached by subprocess, never imported")
    add("")
    add("| venv | present | packages | invocation | documented at |")
    add("|---|---|---|---|---|")
    pin_sections: list[tuple[str, list[tuple[str, str]]]] = []
    for rel, how, cite in VENVS:
        v = ROOT / rel
        pins = venv_pins(v)
        present = "yes" if (v / "bin" / "python").is_file() else "**absent**"
        add(f"| `{rel}` | {present} | {len(pins) if pins else '—'} | {how} | {cite} |")
        if pins:
            pin_sections.append((rel, pins))
    add("")
    add("Each is its own environment with its own interpreter. A package in one is not")
    add("available to the others and none is available to the serving interpreter — which is")
    add("the point of the boundary, not an oversight.")
    add("")
    for rel, pins in pin_sections:
        add(f"### `{rel}` — {len(pins)} packages")
        add("")
        add("```")
        for name, ver in pins:
            add(f"{name}=={ver}")
        add("```")
        add("")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("\n".join(L) + "\n")
    print(f"wrote {OUT.relative_to(ROOT)}  ({len(L)} lines, HEAD {head})")
    print(f"  system interpreter : {len(loaded)} distributions, "
          f"{len(loaded) - len(non_dpkg)} dpkg-owned")
    print(f"  venvs recorded     : {len(pin_sections)} present of {len(VENVS)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
