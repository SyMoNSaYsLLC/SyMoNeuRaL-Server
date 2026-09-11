#!/usr/bin/env python3
"""Three dependency layers that are usually conflated, and the provenance of each.

    python3 tools/dependency_inventory.py               # all three layers
    python3 tools/dependency_inventory.py --layer c     # a, b or c
    python3 tools/dependency_inventory.py --json out.json

**This is not a fifth dependency record and must not become one.** The record already exists
and is in three places, each with a job:

    restore/locks/*.lock.txt        the PINS, one file per environment (7 of them)
    restore/manifests/DEPENDENCIES.tsv  the 220-row manifest: licence, class, reinstall method
    backend/DEPENDENCIES.md         the ARGUMENT -- recreate / facade / keep, and why

This computes the two things none of them stores: **provenance** (did this come from dpkg or
from pip, and does it even carry metadata) and **reverse dependency** (what keeps this
installed, and what breaks if it goes). It reads the locks rather than re-deriving pins.

## The class of finding layer C exists for

`symoneural-diffuse` RUNPATHs into `/usr/local/cuda-13.3/targets/x86_64-linux/lib`. That
directory is owned by `cuda-cudart-13-3`, which is marked **auto** and whose only installed
reverse-dependency chain terminates two links up at a single **manual** `-dev` package. So a
`-dev` package nobody thinks of as a runtime dependency is load-bearing for production image
rendering, and **the package manager has no way to know it**: a RUNPATH is invisible to dpkg.
Un-mark that one anchor and `apt autoremove` takes the runtime out from under a working
binary, which then fails at RUN time -- when a visitor asks for an image -- with no build
error anywhere.

That is the class this layer hunts: **installed packages that are load-bearing only through a
RUNPATH or an `ld.so.conf` path, and that the dependency graph therefore believes are
disposable.** `symoneural-llm` supplies a second member via
`/etc/ld.so.conf.d/000_cuda.conf`.
"""
from __future__ import annotations

import argparse
import functools
import json
import os
import pathlib
import re
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
from apps import runtimes  # noqa: E402

LOCKS = ROOT / "restore" / "locks"
MANIFEST = ROOT / "restore" / "manifests" / "DEPENDENCIES.tsv"

#: Production's environment. The engines resolve different libraries with and without it --
#: see docs/ops/RUNTIMES.md -- and layer C must read the one production actually uses.
PROD_ENV = {k: v for k, v in os.environ.items() if k != "LD_LIBRARY_PATH"}


def sh(argv: list[str], timeout: float = 60) -> str:
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, env=PROD_ENV)
    except (OSError, subprocess.SubprocessError):
        return ""
    return p.stdout


# ------------------------------------------------------------------------------------ dpkg

@functools.lru_cache(maxsize=1)
def _dpkg_file_map() -> dict[str, str]:
    """path -> package, built in one pass over `/var/lib/dpkg/info/*.list`.

    `dpkg -S` per path would be a thousand forks for layer A alone. This is the same data
    dpkg itself searches, read once. Falls back to nothing if the directory is unreadable,
    and `owner_of` then degrades to `dpkg -S` rather than lying about ownership.
    """
    out: dict[str, str] = {}
    info = pathlib.Path("/var/lib/dpkg/info")
    if not info.is_dir():
        return out
    for lst in info.glob("*.list"):
        pkg = lst.stem.split(":")[0]
        try:
            for line in lst.read_text(errors="replace").splitlines():
                if line.startswith("/"):
                    out.setdefault(line, pkg)
        except OSError:
            continue
    return out


@functools.lru_cache(maxsize=None)
def owner_of(path: str) -> str | None:
    """Which installed package ships this file, or None.

    Symlinks matter here: `/usr/local/cuda/...` is the `update-alternatives` link and dpkg
    does not own it; the versioned target underneath is what a package ships. So both the
    literal path and its resolved target are tried.
    """
    fmap = _dpkg_file_map()
    real = str(pathlib.Path(path).resolve())
    for candidate in (path, real):
        if candidate in fmap:
            return fmap[candidate]
    if fmap:
        return None
    for candidate in (real, path):  # only if the map could not be built at all
        for line in sh(["dpkg", "-S", candidate]).splitlines():
            if ": " in line:
                return line.split(": ", 1)[0].split(",")[0].strip()
    return None


@functools.lru_cache(maxsize=1)
def manual_packages() -> frozenset[str]:
    return frozenset(sh(["apt-mark", "showmanual"]).split())


@functools.lru_cache(maxsize=None)
def version_of(pkg: str) -> str | None:
    out = sh(["dpkg-query", "-W", "-f=${Version}", pkg])
    return out.strip() or None


@functools.lru_cache(maxsize=None)
def installed_rdeps(pkg: str) -> tuple[str, ...]:
    """Installed packages that depend on this one. The `--installed` filter is the point:
    the full reverse-depends list includes things that are not on this box and would make
    every package look load-bearing."""
    out = sh(["apt-cache", "rdepends", "--installed", pkg])
    seen = []
    for line in out.splitlines()[2:]:
        name = line.strip().lstrip("|").strip()
        if name and name != pkg and name not in seen:
            seen.append(name)
    return tuple(seen)


def anchor_chain(pkg: str, limit: int = 8) -> list[dict]:
    """Walk reverse-dependencies upward until a MANUAL package or a dead end.

    The answer to "what keeps this installed" is the first manually-installed package above
    it. If the walk ends without finding one, nothing anchors it and `apt autoremove` is
    entitled to take it.
    """
    chain: list[dict] = []
    seen: set[str] = set()
    cur = pkg
    manual = manual_packages()
    for _ in range(limit):
        if cur in seen:
            break
        seen.add(cur)
        rd = installed_rdeps(cur)
        node = {"package": cur, "manual": cur in manual, "installed_rdeps": list(rd)}
        chain.append(node)
        if node["manual"]:
            break
        if not rd:
            break
        cur = rd[0]
    return chain


# --------------------------------------------------------------------- layer A: the system

#: The third-party import names the serving code actually uses, as measured by
#: `tools/audit_runtime_dependencies.py` -- the existing tool, not a second list derived by
#: hand. Kept as a literal so this file has no import-time dependency on that tool's internals.
THIRD_PARTY_IMPORTS = (
    "PIL", "anyio", "bs4", "cryptography", "cuda", "cupy", "datasets", "dotenv", "fastapi",
    "fastmcp", "gguf", "httpx", "numpy", "peft", "playwright", "psutil", "pyasic", "pydantic",
    "rembg", "sympy", "torch", "transformers", "trl", "uvicorn", "websockets", "yaml",
)


def _owner_of_dist(dist) -> str | None:
    """Which dpkg package ships this distribution, resolved through its METADATA file.

    **`dist.files` is `None` for every Debian-packaged distribution on this box**, because
    Debian strips `RECORD` from the `.dist-info`. The first version of this function took
    that absence as evidence of pip and reported *"3 dpkg, 193 pip"* — with `PyGObject`,
    `PyQt5` and `Brlapi` in the pip column, which is obviously false and is the only reason
    it was caught. **Absence of a manifest is not evidence of provenance.**

    dpkg also does not own the `.dist-info` DIRECTORY, only the files inside it. So the
    probe is the metadata file itself, which every distribution has by definition.
    """
    base = getattr(dist, "_path", None)
    if base is None:
        return None
    for name in ("METADATA", "PKG-INFO", "RECORD", "entry_points.txt", "top_level.txt"):
        pkg = owner_of(str(pathlib.Path(base) / name))
        if pkg:
            return pkg
    return None


def layer_a() -> dict:
    """Provenance of the serving interpreter's distributions: dpkg, pip, or no metadata.

    The serving API has no virtualenv by policy, so this interpreter IS the serving
    environment. Mixed provenance is how an `apt` upgrade breaks something silently: a
    pip-installed distribution sitting in the same import path as a dpkg one will be
    shadowed, replaced or orphaned by an apt operation that believes it owns the directory.
    """
    import importlib.metadata as md

    rows = []
    for dist in md.distributions():
        name = (dist.metadata or {}).get("Name")
        if not name:
            # A directory on sys.path with no usable METADATA. `audit_runtime_dependencies.py`
            # calls this `no-dist-metadata`; it is worth counting because it is the state in
            # which neither dpkg nor pip can tell you what the thing is.
            rows.append({"name": None, "version": None, "provenance": "no-dist-metadata",
                         "location": str(getattr(dist, "_path", "?"))})
            continue
        loc = dist.locate_file("")
        pkg = _owner_of_dist(dist)
        rows.append({
            "name": name, "version": dist.version,
            "provenance": "dpkg" if pkg else "pip",
            "dpkg_package": pkg, "dpkg_version": version_of(pkg) if pkg else None,
            "location": str(loc),
        })

    by = {"dpkg": 0, "pip": 0, "no-dist-metadata": 0}
    for r in rows:
        by[r["provenance"]] = by.get(r["provenance"], 0) + 1

    # The OTHER direction, and the one §3 actually asks about. A distribution list answers
    # "what is installed"; this answers "what does the serving code import, and can that
    # import even be traced to a package". `PIL` is Pillow, `bs4` is beautifulsoup4, `yaml`
    # is PyYAML and `gi` is PyGObject -- an import name is not a distribution name, and an
    # import that maps to NOTHING is the `no-dist-metadata` case an apt upgrade breaks
    # silently because no package manager believes it is there.
    by_dist = {r["name"].lower(): r for r in rows if r["name"]}
    #: import name -> distribution name, where they differ. There is no mechanical way to
    #: derive these on this box: `importlib.metadata.packages_distributions()` reads the
    #: same stripped RECORD as `dist.files`, so it reported 19 of 26 imports as untraceable
    #: including `fastapi` and `pydantic`, which are plainly installed. That was the SAME
    #: root cause as the "3 dpkg, 193 pip" error one function above, found the same way --
    #: by the answer being obviously false. The module file is the reliable probe.
    ALIASES = {"PIL": "pillow", "bs4": "beautifulsoup4", "yaml": "PyYAML",
               "dotenv": "python-dotenv", "cuda": "cuda-python"}

    import importlib.util
    imports = []
    for imp in THIRD_PARTY_IMPORTS:
        origin = None
        try:
            spec = importlib.util.find_spec(imp)
            origin = spec.origin if spec else None
            if origin in (None, "built-in") and spec and spec.submodule_search_locations:
                origin = next(iter(spec.submodule_search_locations), None)
        except (ImportError, ValueError, AttributeError):
            origin = None
        pkg = owner_of(origin) if origin else None
        row = by_dist.get(ALIASES.get(imp, imp).lower())
        imports.append({
            "import": imp,
            "importable_here": origin is not None,
            "distribution": row["name"] if row else None,
            "version": row["version"] if row else None,
            "provenance": ("dpkg" if pkg else
                           "pip" if row and row["provenance"] == "pip" else
                           "present, untraceable to a package" if origin else
                           "NOT IMPORTABLE in the serving interpreter"),
            "dpkg_package": pkg,
            "origin": origin,
        })

    return {"interpreter": sys.executable, "total": len(rows), "by_provenance": by,
            "pip_installed": sorted(r["name"] for r in rows
                                    if r["provenance"] == "pip" and r["name"]),
            "no_metadata": [r["location"] for r in rows
                            if r["provenance"] == "no-dist-metadata"],
            "imports": imports,
            "rows": rows}


# ---------------------------------------------------------------------- layer B: the venvs

#: What each environment is for, which runtime reaches it, and how. Hand-written because it
#: is a set of DECISIONS -- the counts and the interpreter beside them are measured.
VENV_PURPOSE = {
    "training/.venv": ("the Reinforce training bay", "training", "subprocess",
                       "runner.py runs here, never in the API: cu128 torch for sm_120"),
    "backend/apps/studio/.venv": ("Studio's plugin host", "symoneural-api", "subprocess", ""),
    "backend/apps/sigils/.venv": ("rembg/onnxruntime for photographic matting",
                                  "symoneural-api", "subprocess", ""),
    "backend/apps/asicminer/.venv": ("pyasic, for talking to ASIC rigs",
                                     "symoneural-api", "subprocess", ""),
    "symoneural-ui/.venv": ("ComfyUI's own environment", "symoneural-ui", "subprocess",
                            "hand-started; nothing routes to it"),
    "deploy/bento/.venv": ("the Bento deployment path", "(none measured)", "unknown",
                           "no runtime row in ops/RUNTIMES.tsv points at it"),
}


def layer_b() -> dict:
    """Every Python environment on this box: what it is for, who reaches it, and whether it
    can be rebuilt. A venv nobody can rebuild is a restore-path gap of the same shape as an
    untracked binary tree."""
    found = []
    skip = (".private", "archive", ".claude", "node_modules")
    for venv in sorted(ROOT.glob("**/.venv")):
        rel = str(venv.relative_to(ROOT))
        if any(s in rel.split("/") for s in skip):
            continue
        py = next((p for p in (venv / "bin" / "python3", venv / "bin" / "python")
                   if p.exists()), None)
        if py is None or not os.access(py, os.X_OK):
            found.append({"path": rel, "interpreter": None, "dists": None,
                          "lock": None, "broken": True,
                          "note": "the .venv directory exists but has no usable interpreter"})
            continue
        ver = sh([str(py), "-V"]).strip() or sh([str(py), "--version"]).strip()
        n = sh([str(py), "-c",
                "import importlib.metadata as m; print(len(list(m.distributions())))"]).strip()
        stem = rel.split("/")[-2] if "/" in rel else rel
        lock = None
        for cand in (LOCKS / f"{stem}.lock.txt",
                     LOCKS / f"{pathlib.Path(rel).parent.name}.lock.txt"):
            if cand.is_file():
                lock = str(cand.relative_to(ROOT))
                break
        purpose, used_by, how, note = VENV_PURPOSE.get(
            str(pathlib.Path(rel).parent) + "/.venv",
            VENV_PURPOSE.get(rel, ("(undeclared)", "(unknown)", "(unknown)", "")))
        pinned = None
        if lock:
            pinned = sum(1 for ln in (ROOT / lock).read_text().splitlines()
                         if ln.strip() and not ln.lstrip().startswith("#"))
        found.append({"path": rel, "interpreter": ver, "dists": int(n) if n.isdigit() else None,
                      "lock": lock, "pins_in_lock": pinned, "broken": False,
                      "purpose": purpose, "used_by": used_by, "reached_by": how, "note": note,
                      "lock_matches_live": (pinned == int(n)) if (pinned and n.isdigit()) else None})
    locks_present = sorted(p.stem.replace(".lock", "") for p in LOCKS.glob("*.lock.txt"))
    return {"environments": found, "locks_on_disk": locks_present,
            "system_interpreter_has_no_venv_by_policy": True}


# --------------------------------------------------------------------- layer C: the native

def needed(binary: pathlib.Path) -> list[str]:
    out = sh(["objdump", "-p", str(binary)])
    return re.findall(r"NEEDED\s+(\S+)", out)


def resolved(binary: pathlib.Path) -> dict[str, str]:
    """soname -> resolved path, in PRODUCTION's environment. Not this shell's."""
    out = sh(["ldd", str(binary)])
    return {m.group(1): m.group(2)
            for m in re.finditer(r"^\s*(\S+) => (/\S+)", out, re.M)}


def runpath(binary: pathlib.Path) -> str | None:
    out = sh(["objdump", "-p", str(binary)])
    m = re.search(r"^\s*(?:RUNPATH|RPATH)\s+(\S+)", out, re.M)
    return m.group(1) if m else None


@functools.lru_cache(maxsize=1)
def ld_so_conf_dirs() -> tuple[str, ...]:
    dirs = []
    for conf in sorted(pathlib.Path("/etc/ld.so.conf.d").glob("*.conf")):
        try:
            for ln in conf.read_text().splitlines():
                ln = ln.strip()
                if ln and not ln.startswith("#"):
                    dirs.append(f"{ln}\t({conf.name})")
        except OSError:
            pass
    return tuple(dirs)


def layer_c() -> dict:
    """Every native library every first-party binary loads, and what keeps it installed.

    The output that matters is `invisible_to_dpkg`: packages that production genuinely needs
    but that nothing in the package graph depends on, because the need is expressed as a
    RUNPATH or an `ld.so.conf` entry rather than as a Depends line.
    """
    binaries = []
    seen_paths: set[str] = set()
    for r in runtimes.rows():
        rel = r["ARTEFACT"]
        if rel == "-" or rel in seen_paths:
            continue
        p = ROOT / rel
        if not p.is_file() or b"ELF" not in p.read_bytes()[:4].upper():
            continue
        seen_paths.add(rel)
        binaries.append((r["RUNTIME"], rel, p))
    # The llm engine's own 23 libraries are where its CUDA need actually lives; the shim
    # NEEDs almost nothing, so walking only the shim would miss the whole question.
    extra = ROOT / "symoneural-llm" / "build" / "bin" / "libsymoneural_tensor_cuda.so.0"
    if extra.is_file():
        binaries.append(("symoneural-llm (tensor lib)",
                         str(extra.relative_to(ROOT)), extra))

    pkg_users: dict[str, set[str]] = {}
    per_binary = []
    for name, rel, p in binaries:
        res = resolved(p)
        rp = runpath(p)
        libs = []
        for soname, path in sorted(res.items()):
            pkg = owner_of(path)
            libs.append({"soname": soname, "path": path, "package": pkg})
            if pkg:
                pkg_users.setdefault(pkg, set()).add(name)
        per_binary.append({"runtime": name, "artefact": rel, "runpath": rp,
                           "needed": len(needed(p)), "resolved": libs})

    manual = manual_packages()
    packages = []
    for pkg in sorted(pkg_users):
        chain = anchor_chain(pkg)
        anchor = next((c["package"] for c in chain if c["manual"]), None)
        packages.append({
            "package": pkg, "version": version_of(pkg),
            "manual": pkg in manual,
            "installed_rdeps": list(installed_rdeps(pkg)),
            "anchor": anchor,
            "anchor_depth": next((i for i, c in enumerate(chain) if c["manual"]), None),
            "chain": [c["package"] for c in chain],
            "used_by": sorted(pkg_users[pkg]),
        })

    # The finding. A package is INVISIBLE to the dependency graph when production loads it
    # but it is `auto` and its only anchor is a `-dev` package -- or there is no anchor at
    # all. Either way nothing in `Depends` records that a working binary needs it.
    invisible = [p for p in packages
                 if not p["manual"] and (p["anchor"] is None
                                         or p["anchor"].endswith(("-dev", "-devel"))
                                         or p["anchor_depth"] not in (0, None) and p["anchor_depth"] >= 1)]
    return {"binaries": per_binary, "packages": packages,
            "ld_so_conf": list(ld_so_conf_dirs()),
            "invisible_to_dpkg": invisible}


# ----------------------------------------------------------------------------- presentation

def report(data: dict) -> None:
    if "a" in data:
        a = data["a"]
        print("== LAYER A -- the system interpreter (the serving environment, no venv by policy)")
        print(f"   {a['interpreter']}")
        print(f"   {a['total']} distributions: " +
              ", ".join(f"{v} {k}" for k, v in sorted(a["by_provenance"].items()) if v))
        if a["pip_installed"]:
            print(f"   pip rather than dpkg ({len(a['pip_installed'])}) -- an apt operation "
                  "does not know these are here:")
            for n in a["pip_installed"]:
                print(f"     {n}")
        print(f"   {len(a['imports'])} third-party import names the serving code uses:")
        for i in sorted(a["imports"], key=lambda x: (x["provenance"], x["import"])):
            dist = i["distribution"] or "-"
            alias = f" (dist: {dist})" if dist.lower() != i["import"].lower() else ""
            print(f"     {i['import']:<14} {i['provenance']:<38}"
                  f"{i['dpkg_package'] or ''}{alias}")
        if a["no_metadata"]:
            print(f"   no usable dist metadata ({len(a['no_metadata'])}):")
            for n in a["no_metadata"][:10]:
                print(f"     {n}")
        print()

    if "b" in data:
        b = data["b"]
        print("== LAYER B -- per-application environments")
        for e in b["environments"]:
            if e["broken"]:
                print(f"   [BROKEN] {e['path']}: {e['note']}")
                continue
            lock = e["lock"] or "**NO LOCK**"
            match = {True: "matches", False: "DIFFERS from live", None: "-"}[e["lock_matches_live"]]
            print(f"   {e['path']}")
            print(f"       {e['interpreter']}, {e['dists']} dists; lock {lock} "
                  f"({e['pins_in_lock']} pins, {match})")
            print(f"       for {e['purpose']}; reached by {e['reached_by']} from {e['used_by']}"
                  + (f"; {e['note']}" if e["note"] else ""))
        print()

    if "c" in data:
        c = data["c"]
        print("== LAYER C -- native libraries, and what keeps each package installed")
        for bn in c["binaries"]:
            print(f"   {bn['runtime']:<28} {bn['needed']} NEEDED, "
                  f"RUNPATH {bn['runpath'] or '(none)'}")
        print()
        print("   -- packages production loads, with their anchor --")
        for p in c["packages"]:
            flag = "MANUAL" if p["manual"] else "auto"
            print(f"   {p['package']:<30} {flag:<7} anchor={p['anchor'] or '**NONE**'}"
                  f"  used by {', '.join(p['used_by'])}")
        inv = c["invisible_to_dpkg"]
        print()
        print(f"   -- INVISIBLE TO DPKG: {len(inv)} package(s) production loads that the "
              "dependency graph does not know are needed --")
        for p in inv:
            print(f"   {p['package']} ({p['version']})")
            print(f"       used by: {', '.join(p['used_by'])}")
            print(f"       chain:   {' <- '.join(p['chain'])}")
            print(f"       anchor:  {p['anchor'] or 'NONE -- nothing keeps this installed'}")
        print()
        print("   -- /etc/ld.so.conf.d, which resolves libraries no RUNPATH names --")
        for d in c["ld_so_conf"]:
            path = d.split("\t")[0]
            print(f"   {d}   {'' if pathlib.Path(path).is_dir() else '<- DANGLING'}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--layer", action="append", choices=["a", "b", "c"], default=None)
    ap.add_argument("--json", type=pathlib.Path, default=None)
    args = ap.parse_args()
    want = args.layer or ["a", "b", "c"]
    data = {}
    if "a" in want:
        data["a"] = layer_a()
    if "b" in want:
        data["b"] = layer_b()
    if "c" in want:
        data["c"] = layer_c()
    report(data)
    if args.json:
        args.json.write_text(json.dumps(data, indent=2, default=str))
        print(f"wrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
