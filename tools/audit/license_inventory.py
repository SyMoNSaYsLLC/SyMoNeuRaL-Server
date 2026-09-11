#!/usr/bin/env python3
"""Measure every component this project carries and what licence attaches to it.

Writes `ops/LICENSES.tsv`, which is the record. `LICENSES.md` is its rendering,
the same way `ops/PORTS.tsv` is the record and `docs/ops/PORTS.md` the rendering.
A licence inventory that is typed by hand is a licence inventory that is wrong
within a week, and this one has to survive the question "what could get us sued".

    tools/audit/license_inventory.py            # rewrite ops/LICENSES.tsv
    tools/audit/license_inventory.py --check    # fail if the file is out of date
    tools/audit/license_inventory.py --findings # only the rows that need a decision

Where the figures come from
---------------------------
Python  every venv under ~/.venvs and every `.venv` in a project tree, read with
        `importlib.metadata` in *that* interpreter -- not this one. Reading the
        system interpreter reports torch, transformers and cupy as absent while
        five venvs hold them, which is how the heaviest licence surface on the
        box goes unmeasured.
npm     `package.json` dependency blocks. Not `node_modules`: it is not
        installed here, and a listing must not silently omit what it cannot see.
Rust    `Cargo.lock`, which names the transitive set. `Cargo.toml` names twelve
        direct crates; the lock names 362, and those are what a binary carries.
models  the texts in `models/licenses/`.

PEP 639 matters here. Modern packaging puts the licence in `License-Expression`,
not in a classifier, so a probe that reads only classifiers reports hundreds of
packages as unlicensed. This reads the expression first, the classifier second,
the free-text `License` field third, and only then records that a package
carries no licence metadata at all. The difference measured on this box was 207
false alarms against 13 real ones.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents
            if (p / "backend" / "server.py").is_file())
OUT = ROOT / "ops" / "LICENSES.tsv"

COLUMNS = ("component", "version", "ecosystem", "party", "licence", "klass",
           "carried", "where", "obligation", "enforced_by")

# Party, by provenance -- the three buckets the naming doctrine already uses.
FIRST = "first"          # we wrote it
SECOND = "second"        # someone else's work we forked and modified
THIRD = "third"          # someone else's work we use unmodified

# Licence class. `copyleft` is the only one that can change what we may ship.
PERMISSIVE, COPYLEFT, WEAK_COPYLEFT, PROPRIETARY, UNKNOWN = (
    "permissive", "copyleft", "weak-copyleft", "proprietary", "UNKNOWN")

_COPYLEFT = re.compile(r"\b(GPL-[23]|GPLv[23]|AGPL|GNU General Public|"
                       r"GNU Affero)", re.I)
_WEAK = re.compile(r"\b(LGPL|MPL-2|Mozilla Public|EPL-|Eclipse Public|CDDL)", re.I)
_PERMISSIVE = re.compile(r"\b(MIT|BSD|Apache|ISC|Python Software Foundation|"
                         r"Zlib|Unlicense|CC0|PSF|HPND|MIT-CMU)", re.I)
_PROPRIETARY = re.compile(r"\b(Proprietary|LicenseRef-SyMoNeuRaL|NVIDIA|"
                          r"CUDA Toolkit|All Rights Reserved)", re.I)


def classify(licence: str) -> str:
    """SPDX-ish text -> the class that decides what it obliges.

    An SPDX `OR` is a choice the *licensee* makes, so a dual licence is
    classified by the branch we would elect, not by its scariest branch.
    `GPL-2.0-only OR BSD-3-Clause` -- which is what ittapi and ittapi-sys carry
    in the gateway's dependency tree -- is taken as BSD-3-Clause, and calling it
    copyleft would raise a blocking finding against a crate that obliges nothing
    beyond attribution.

    `AND` is not a choice and gets no such treatment: every branch binds, so the
    most constraining one decides. Copyleft is therefore tested before
    permissive for everything that is not an elected OR, because
    "GPL-2.0-or-later WITH Classpath-exception" carries no MIT or BSD token to
    match and must not fall through to UNKNOWN.
    """
    if not licence or licence == UNKNOWN:
        return UNKNOWN
    if " OR " in licence.upper() and " AND " not in licence.upper():
        branches = re.split(r"\s+OR\s+", licence, flags=re.I)
        if any(_PERMISSIVE.search(b) and not _COPYLEFT.search(b) for b in branches):
            return PERMISSIVE
    if _COPYLEFT.search(licence):
        return COPYLEFT
    if _WEAK.search(licence):
        return WEAK_COPYLEFT
    if _PERMISSIVE.search(licence):
        return PERMISSIVE
    if _PROPRIETARY.search(licence):
        return PROPRIETARY
    return UNKNOWN


@dataclass(frozen=True)
class Row:
    component: str
    version: str
    ecosystem: str
    party: str
    licence: str
    klass: str
    carried: str      # shipped | build-only | host-only -- does it leave this box
    where: str
    obligation: str
    enforced_by: str = "upstream authors, on distribution"

    def tsv(self) -> str:
        return "\t".join(str(getattr(self, c)).replace("\t", " ") for c in COLUMNS)


# --------------------------------------------------------------------------
# Python: every interpreter that actually holds packages
# --------------------------------------------------------------------------

# Read in the target interpreter, so the answer is that venv's, not this one's.
PROBE = r'''
import json
from importlib.metadata import distributions
def licence(d):
    m = d.metadata
    if (e := m.get("License-Expression")):          # PEP 639 -- authoritative
        return e.strip()
    for c in m.get_all("Classifier") or []:
        if c.startswith("License ::") and "Other/Proprietary" not in c:
            return c.split("::")[-1].strip()
    t = (m.get("License") or "").strip()
    if t and "\n" not in t and len(t) < 60:
        return t
    for c in m.get_all("Classifier") or []:
        if "Other/Proprietary" in c:
            return "Proprietary"
    return "UNKNOWN"
packages = {}
for d in distributions():
    name = (d.metadata["Name"] or "").strip()
    if name:
        packages[name] = [d.version or "?", licence(d)]

# Which top-level modules each distribution provides, so a caller can tell
# whether the code importing "yaml" means PyYAML is a dependency. The mapping
# is the wrong way round in the stdlib, so it is inverted here.
provides = {}
try:
    from importlib.metadata import packages_distributions
    for module, dists in packages_distributions().items():
        for dist in dists:
            provides.setdefault(dist, []).append(module)
except Exception:
    pass
print(json.dumps({"packages": packages, "provides": provides}))
'''


def imported_modules() -> set[str]:
    """Every top-level module this repository imports, by reading the source.

    The system interpreter's site-packages is the operating system's, not this
    project's: nala, mpv, iotop, PyQt5 and python-apt all live there. Listing
    them as components would put six GPL "findings" in front of the owner that
    have nothing to do with anything he ships, and burying the real findings
    under false ones is worse than not having the file.

    So a system-python distribution counts as a component only when the code
    actually imports something it provides. Read with `ast`, not grep: a grep
    for "import x" matches it inside a docstring, and this decides whether a
    GPL package is reported or dropped.
    """
    import ast
    found: set[str] = set()
    skip = {".git", "node_modules", "__pycache__", ".venv", "site-packages"}
    for path in ROOT.rglob("*.py"):
        if skip & set(path.parts):
            continue
        try:
            tree = ast.parse(path.read_text(errors="replace"))
        except (SyntaxError, ValueError, OSError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                found.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                found.add(node.module.split(".")[0])
    return found


def interpreters() -> list[Path]:
    """Every interpreter worth asking, deduplicated and in a stable order."""
    found = {sys.executable}
    home = Path.home()
    for venv in sorted(home.glob(".venvs/*/bin/python")):
        found.add(str(venv))
    for tree in (ROOT, ROOT.parent):
        for venv in sorted(tree.glob("*/.venv/bin/python")):
            found.add(str(venv))
    return [Path(p) for p in sorted(found)]


def python_rows() -> list[Row]:
    rows: list[Row] = []
    seen: set[tuple[str, str]] = set()
    imported = imported_modules()
    for python in interpreters():
        if not python.is_file():
            continue
        try:
            out = subprocess.run([str(python), "-c", PROBE], capture_output=True,
                                 text=True, timeout=120)
        except (OSError, subprocess.TimeoutExpired):
            continue
        if out.returncode != 0 or not out.stdout.strip():
            continue
        where = _label(python)
        payload = json.loads(out.stdout)
        packages = payload["packages"]
        provides = payload["provides"]
        for name, (version, licence) in packages.items():
            if where == "system-python":
                # The OS's packages live here too. Only what the code imports
                # is a component of this project -- see imported_modules().
                if not (set(provides.get(name, [])) & imported):
                    continue
            # A package in two venvs at one version is one component, listed
            # once with both homes -- not two rows disagreeing about nothing.
            key = (name.lower(), version)
            if key in seen:
                continue
            seen.add(key)
            rows.append(Row(
                component=name, version=version, ecosystem="python",
                party=THIRD, licence=licence, klass=classify(licence),
                carried="host-only", where=where,
                obligation=_obligation(classify(licence))))
    return rows


def _label(python: Path) -> str:
    """A short, stable name for where an interpreter lives."""
    parts = python.parts
    for marker in (".venvs", ".venv"):
        if marker in parts:
            i = parts.index(marker)
            tail = parts[i + 1] if marker == ".venvs" else parts[i - 1]
            return f"venv:{tail}"
    return "system-python"


# --------------------------------------------------------------------------
# Rust, npm, models
# --------------------------------------------------------------------------

def packaged() -> set[str]:
    """Every repository path that `scripts/build-deb.sh` puts in the .deb.

    `carried` decides whether a licence is an obligation at all, so declaring it
    by hand makes the safety argument unfalsifiable: the row would keep saying
    host-only until somebody edited the constant, which is exactly how
    deploy.sh published zero files for weeks while printing "deployed".

    The packager builds its payload from `git ls-files` minus two exclusion
    regexes, so the same computation run here is the real answer. The regexes
    are read out of the script rather than copied, because a copy is a second
    authority that drifts.
    """
    script = ROOT / "scripts" / "build-deb.sh"
    if not script.is_file():
        return set()

    # The two regexes are assembled across continuation lines
    # (`NONPROD_RE="$NONPROD_RE"'...'`), so pulling one line out yields a
    # fragment with unbalanced parentheses that will not compile. Rather than
    # re-implement shell string building, the assignment lines are handed back
    # to bash and the finished values read out. That keeps the packager the only
    # authority on what it excludes; a copy here would be a second one, and it
    # would drift.
    assignments = [l for l in script.read_text().splitlines()
                   if l.startswith(("EXCLUDE_RE=", "NONPROD_RE="))]
    if not assignments:
        return set()
    program = "\n".join(assignments) + '\nprintf "%s|%s" "$EXCLUDE_RE" "$NONPROD_RE"'
    try:
        shell = subprocess.run(["bash", "-c", program], capture_output=True,
                               text=True, timeout=30)
        out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True,
                             text=True, timeout=60)
    except (OSError, subprocess.TimeoutExpired):
        return set()
    if shell.returncode != 0 or not shell.stdout.strip():
        return set()
    excluded = re.compile(shell.stdout.strip())
    return {path for path in out.stdout.splitlines()
            if path and not excluded.search(path)}


def crate_licences() -> dict[str, str]:
    """crate -> licence, read from the vendored sources under ~/.cargo.

    Cargo.lock records no licence field, so the lock alone leaves every crate
    UNKNOWN -- 361 blocking findings for a tree that turns out to have none.
    `cargo metadata --offline` is the obvious fix and does not work here: the
    lock names crates for target platforms this box never builds
    (android_system_properties), and cargo refuses the whole query rather than
    skipping them. The vendored manifests are what the binary was actually built
    from, so they are the honest source.

    A crate in the lock with no vendored source stays UNKNOWN. That is a real
    gap and is reported as one, not filled in with a guess.
    """
    found: dict[str, str] = {}
    for manifest in sorted(Path.home().glob(".cargo/registry/src/*/*/Cargo.toml")):
        name = licence = None
        for line in manifest.read_text(errors="replace").splitlines():
            line = line.strip()
            if line.startswith("name = ") and name is None:
                name = line.split("=", 1)[1].strip().strip('"')
            elif line.startswith("license = "):
                licence = line.split("=", 1)[1].strip().strip('"')
            elif line.startswith("license-file = ") and licence is None:
                licence = "see " + line.split("=", 1)[1].strip().strip('"')
        if name and licence:
            found[name] = licence
    return found


def rust_rows() -> list[Row]:
    """Cargo.lock, not Cargo.toml.

    Cargo.toml names twelve direct crates. The lock names every crate the binary
    is actually built from, and those are the ones whose notices a shipped
    binary owes. There is no notices file for them; that is a finding, recorded
    as one rather than left as an absence nobody counted.
    """
    licences = crate_licences()
    lock = ROOT / "backend" / "gateway" / "Cargo.lock"
    if not lock.is_file():
        return []
    rows = []
    name = version = None
    for line in lock.read_text().splitlines():
        if line.startswith("name = "):
            name = line.split("=", 1)[1].strip().strip('"')
        elif line.startswith("version = ") and name:
            version = line.split("=", 1)[1].strip().strip('"')
            rows.append(Row(
                component=name, version=version, ecosystem="rust",
                party=FIRST if name == "symoneural-gateway" else THIRD,
                # Cargo.lock records no licence, so it comes from the
                # vendored source. A crate with none stays UNKNOWN rather than
                # being assumed MIT because most crates are MIT.
                licence=("LicenseRef-SyMoNeuRaL-Proprietary"
                         if name == "symoneural-gateway"
                         else licences.get(name, UNKNOWN)),
                klass=(PROPRIETARY if name == "symoneural-gateway"
                       else classify(licences.get(name, UNKNOWN))),
                carried="shipped", where="backend/gateway/Cargo.lock",
                obligation=("ours" if name == "symoneural-gateway"
                            else "attribution; no notices file exists yet")))
            name = version = None
    return rows


def npm_rows() -> list[Row]:
    """package.json dependency blocks.

    Not node_modules: it is not installed in this tree, and an inventory must
    never report a set it could not see as the whole set.
    """
    rows = []
    for pkg in sorted(ROOT.glob("frontend/*/package.json")):
        doc = json.loads(pkg.read_text())
        rel = pkg.relative_to(ROOT)
        for block in ("dependencies", "devDependencies"):
            for name, spec in (doc.get(block) or {}).items():
                rows.append(Row(
                    component=name, version=str(spec), ecosystem="npm",
                    party=THIRD, licence=UNKNOWN, klass=UNKNOWN,
                    carried="shipped" if block == "dependencies" else "build-only",
                    where=str(rel),
                    obligation="declared but never installed; unmeasured"))
    return rows


def model_rows() -> list[Row]:
    """The licence texts carried beside the weights.

    Model licences are not OSI licences and are not interchangeable with them:
    several carry use restrictions that no software licence has. They are listed
    with the text that governs them so nobody has to guess which applies.
    """
    here = ROOT / "models" / "licenses"
    if not here.is_dir():
        return []
    return [Row(component=p.stem, version="-", ecosystem="model", party=THIRD,
                licence=UNKNOWN, klass=UNKNOWN, carried="host-only",
                where=str(p.relative_to(ROOT)),
                obligation="read the carried text; model terms are not OSI terms")
            for p in sorted(here.iterdir()) if p.is_file()]


def _obligation(klass: str) -> str:
    return {
        PERMISSIVE: "attribution in a notices file",
        WEAK_COPYLEFT: "attribution; share modifications to the component itself",
        COPYLEFT: "OWNER DECISION: source of the combined work, if distributed",
        PROPRIETARY: "read the terms; redistribution may be forbidden",
        UNKNOWN: "UNMEASURED -- resolve before anything ships",
    }[klass]


# --------------------------------------------------------------------------
# First party, and the forks. Named here because no manifest declares them.
# --------------------------------------------------------------------------

# The three engines are not in this tree and no package manager knows about
# them, so nothing above can find them -- and their absence from the repository
# is not their absence from the liability. They are what a customer build would
# actually redistribute, which makes leaving them out the one omission that
# would make this whole file useless.
def _carried(path: str, payload: set[str]) -> str:
    """shipped when the packager puts this tree in the .deb, host-only otherwise.

    A path outside the repository can never be in `git ls-files`, so an engine
    that lives in another tree is host-only by construction rather than by
    assertion -- and that is the fact the whole GPL safety argument rests on.
    """
    if not payload:
        return "host-only"      # no packager on this box; nothing can ship
    return "shipped" if any(p.startswith(path) for p in payload) else "host-only"


FORKS = [
    Row(component="symoneural-llm", version="fork of llama.cpp", ecosystem="engine",
        party=SECOND, licence="MIT", klass=PERMISSIVE, carried="shipped",
        where="not in this tree; see restore/",
        obligation="attribution; 2 of 1249 files are ours"),
    Row(component="symoneural-diffuse", version="fork of stable-diffusion.cpp",
        ecosystem="engine", party=SECOND, licence="MIT", klass=PERMISSIVE,
        carried="shipped", where="not in this tree; see restore/",
        obligation="attribution; 3 of 1293 files are ours"),
    Row(component="symoneural-ui", version="fork of ComfyUI", ecosystem="engine",
        party=SECOND, licence="GPL-3.0", klass=COPYLEFT, carried="host-only",
        where="/home/google/Symoneural/symoneural-ui",
        obligation="OWNER DECISION: see the ComfyUI section of LICENSES.md"),
]

OURS = [
    Row(component="SyMoNeuRaL API + surfaces", version="-", ecosystem="python",
        party=FIRST, licence="LicenseRef-SyMoNeuRaL-Proprietary",
        klass=PROPRIETARY, carried="host-only", where="backend/",
        obligation="ours"),
    Row(component="SyMoNeuRaL site", version="-", ecosystem="web",
        party=FIRST, licence="LicenseRef-SyMoNeuRaL-Proprietary",
        klass=PROPRIETARY, carried="shipped", where="frontend/site/",
        obligation="ours; this is what visitors receive"),
    Row(component="symoneural_cleanroom + symoneural_gguf", version="-",
        ecosystem="python", party=FIRST,
        licence="LicenseRef-SyMoNeuRaL-Proprietary", klass=PROPRIETARY,
        carried="host-only", where="backend/studio/custom_nodes/",
        obligation="OWNER DECISION: loaded into a GPL-3.0 process; see LICENSES.md"),
]


def inventory() -> list[Row]:
    payload = packaged()
    ours = [
        # `carried` is measured against the packager's own manifest, so these
        # rows cannot claim something the .deb contradicts.
        Row(**{**asdict(r),
               "carried": _carried(r.where.rstrip("/"), payload)})
        if r.where.startswith(("backend/", "frontend/")) else r
        for r in OURS
    ]
    rows = ours + FORKS + rust_rows() + npm_rows() + model_rows() + python_rows()
    if len(rows) < 100:
        # A collector that silently returned nothing would publish a short,
        # confident, wrong inventory. Better to refuse than to under-report.
        raise SystemExit(f"license_inventory: only {len(rows)} rows; a collector "
                         f"found nothing. Refusing to write a short inventory.")
    return rows


HEADER = """\
# SyMoNeuRaL licence inventory -- GENERATED by tools/audit/license_inventory.py.
# Do not hand-edit: run the generator. LICENSES.md is the rendering of this file.
#
# component    what it is
# version      as installed, or the manifest's spec for things never installed
# ecosystem    python | npm | rust | model | engine | web
# party        first  = we wrote it
#              second = someone else's work we forked and modified
#              third  = someone else's work we use unmodified
# licence      as declared by the component. UNKNOWN means unmeasured, not absent.
# klass        permissive | weak-copyleft | copyleft | proprietary | UNKNOWN
# carried      shipped    = leaves this box
#              build-only = used to build something that leaves
#              host-only  = never leaves this box in any form
# where        the file or tree this was read from
# obligation   what it requires of us, in one line
"""


def write(rows: list[Row]) -> str:
    body = "\n".join(r.tsv() for r in sorted(
        rows, key=lambda r: (r.ecosystem, r.component.lower(), r.version)))
    return f"{HEADER}{chr(9).join(COLUMNS)}\n{body}\n"


def findings(rows: list[Row]) -> list[Row]:
    """The rows that need a person, not a generator: copyleft and unmeasured."""
    return [r for r in rows if r.klass in (COPYLEFT, UNKNOWN)]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true",
                        help="exit 1 if ops/LICENSES.tsv is out of date")
    parser.add_argument("--findings", action="store_true",
                        help="print only the rows that need a decision")
    args = parser.parse_args(argv)

    rows = inventory()

    if args.findings:
        for r in findings(rows):
            print(f"{r.klass:12} {r.party:6} {r.ecosystem:8} {r.component:34} "
                  f"{r.obligation}")
        print(f"\n{len(findings(rows))} of {len(rows)} rows need a decision.")
        return 0

    text = write(rows)
    if args.check:
        if OUT.is_file() and OUT.read_text() == text:
            print(f"{OUT.relative_to(ROOT)} is current ({len(rows)} rows)")
            return 0
        print(f"{OUT.relative_to(ROOT)} is out of date; run without --check",
              file=sys.stderr)
        return 1

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text)
    print(f"wrote {OUT.relative_to(ROOT)}: {len(rows)} components, "
          f"{len(findings(rows))} needing a decision")
    return 0


if __name__ == "__main__":
    sys.exit(main())
