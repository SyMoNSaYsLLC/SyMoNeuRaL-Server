"""SyMoNeuRaL Adaptive Fabric — its real status, read from the registries that define it.

Owner, 2026-09-11: *"the symoneural fabric is key"*.

## What the fabric is today, stated plainly

`symoneural-adaptive-fabric/` contains **two files: a README and a LICENSE.** No code.
`docs/architecture/COMPONENT-MAP.tsv:15` records it `PLANNED / NOT_IMPLEMENTED /
NOT_IN_RELEASE`, and `docs/architecture/ALIASES.tsv:7-13` records its seven subcomponents as
`PLANNED_SUBCOMPONENT`, each with "0 tracked matches in source".

This module does not change that and does not pretend to. **It reads those two files and
publishes what they say**, so the dashboard shows the fabric's status as measured rather than
as remembered. If somebody implements a subcomponent and updates the map, this page follows
on the next refresh; if somebody implements one and does *not* update the map, this page keeps
saying PLANNED, which is the correct behaviour -- the map is the record.

## The substitution this module is built to refuse

The fabric's README says the thing to read twice, and it is worth repeating at the one place
that renders the status to a screen:

> **"Symon Memory Governor -- distinct from `scripts/gpu-governor.sh`, which IS implemented."**
> "Anyone who reads 'Memory Governor' and points at `gpu-governor.sh` has found a different
> component that already exists -- which is exactly the kind of substitution that lets a
> planned thing be reported as done."

So `ADJACENT` below names the implemented things that are *near* each subcomponent without
being it, and the page renders them in a visibly different style from the status. A reader who
sees "Residency Manager: PLANNED" beside "`bin/symoneural-cli residency` works today" has the
true picture; a reader who sees only the second one has been misled.

## Where this dashboard sits in the fabric

Honestly and with the limits attached: **the Hardware Profiler is the one subcomponent this
work touches.** `apps/modelmetrics.py` and `apps/hostmetrics.py` read the GPU, the engine, the
CPU, the RAM and the disk, which is profiling hardware by any reasonable reading of the name.

It is **not** promoted to IMPLEMENTED here, for two reasons that are the repo's own rules:
status changes in `COMPONENT-MAP.tsv` on measured evidence, not on a module appearing; and a
profiler that feeds a web page is not the same as a profiler that feeds a Placement Policy,
which is what the fabric's design says it is for. `profiler_evidence()` states what exists so
the claim can be judged rather than believed.
"""
from __future__ import annotations

import pathlib
from typing import Any

REPO = pathlib.Path(__file__).resolve().parent.parent.parent
COMPONENT_MAP = REPO / "docs" / "architecture" / "COMPONENT-MAP.tsv"
ALIASES = REPO / "docs" / "architecture" / "ALIASES.tsv"
FABRIC_DIR = REPO / "symoneural-adaptive-fabric"
COMPONENT_ID = "symoneural-adaptive-fabric"

#: Implemented things that sit NEXT TO a subcomponent without being it. Quoted from the
#: fabric's own README, which lists them for exactly this reason. The page must never let one
#: of these stand in for the status beside it.
ADJACENT = {
    "Symon Memory Governor": "scripts/gpu-governor.sh — GPU residency and eviction, in use. "
                             "A DIFFERENT component that already exists; not this one.",
    "Symon Residency Manager": "bin/symoneural-cli residency — reports residency now.",
    "Symon Placement Policy": "ops/manifests/ — artefact identity, which a Placement Policy "
                              "would need to read.",
    "Symon Hardware Profiler": "backend/modelmetrics.py + hostmetrics.py — this "
                               "dashboard's readings. See profiler_evidence().",
}


def _tsv(path: pathlib.Path) -> tuple[list[str], list[list[str]]]:
    """Header and rows. Returns empty on any read failure -- the caller says so, not this."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return [], []
    rows = [ln.split("\t") for ln in lines if ln.strip()]
    return (rows[0], rows[1:]) if rows else ([], [])


def component_status() -> dict[str, Any]:
    """The fabric's own row in `COMPONENT-MAP.tsv`, field by field, or why it is absent."""
    src = "docs/architecture/COMPONENT-MAP.tsv"
    header, rows = _tsv(COMPONENT_MAP)
    if not header:
        return {"found": False, "source": f"{src} could not be read", "fields": {}}
    for row in rows:
        if row and row[0] == COMPONENT_ID:
            return {"found": True, "source": f"{src}, the {COMPONENT_ID} row",
                    "fields": {h: (row[i] if i < len(row) else "")
                               for i, h in enumerate(header)}}
    return {"found": False, "source": f"{src} has no {COMPONENT_ID} row", "fields": {}}


def subcomponents() -> list[dict[str, Any]]:
    """The seven, read from `ALIASES.tsv`. Never a hardcoded list of seven names.

    If an eighth is added to the registry it appears here without an edit, and if one is
    promoted out of `PLANNED_SUBCOMPONENT` its row changes shape and the page shows that.
    """
    src = "docs/architecture/ALIASES.tsv"
    header, rows = _tsv(ALIASES)
    if not header:
        return []
    idx = {h: i for i, h in enumerate(header)}
    out = []
    for row in rows:
        get = lambda k: row[idx[k]] if k in idx and idx[k] < len(row) else ""   # noqa: E731
        if get("CANONICAL_COMPONENT_ID") != COMPONENT_ID:
            continue
        name = get("ALIAS")
        out.append({
            "name": name,
            "status": get("ALIAS_TYPE"),
            "evidence": get("EVIDENCE"),
            "source": f"{src}, the {name!r} row",
            # Rendered in a distinct style. See the module docstring on substitution.
            "adjacent_but_not_this": ADJACENT.get(name),
        })
    return out


def tree_state() -> dict[str, Any]:
    """What is actually on disk at `symoneural-adaptive-fabric/`. Counted, not remembered."""
    if not FABRIC_DIR.is_dir():
        return {"exists": False, "files": None, "names": [],
                "source": f"{FABRIC_DIR} does not exist"}
    files = sorted(p.relative_to(FABRIC_DIR).as_posix()
                   for p in FABRIC_DIR.rglob("*") if p.is_file())
    return {
        "exists": True,
        "files": len(files),
        "names": files[:40],
        "source": f"walk of {FABRIC_DIR.relative_to(REPO)}/",
        "has_code": any(n.endswith((".py", ".rs", ".c", ".cpp", ".go", ".sh")) for n in files),
    }


def profiler_evidence() -> dict[str, Any]:
    """What this dashboard contributes toward the Hardware Profiler, with its limits attached.

    Deliberately not a boolean and deliberately not a percentage. A percentage would be an
    assertion about a component whose acceptance criteria nobody has written down, and this
    repo has a rule about figures that cannot be checked.
    """
    reads = [
        ("GPU", "nvidia-smi: VRAM total/used/free, utilisation, temperature, power, clocks"),
        ("engine", "llama-server /props: context window per slot, slot count, loaded weights"),
        ("model work", "llama-server timings on every real request: tokens in/out, tok/s, "
                       "prompt-cache hits — captured, not probed for"),
        ("CPU", "/proc/cpuinfo, psutil interval sample"),
        ("RAM", "/proc/meminfo (MemAvailable, not MemFree)"),
        ("disk", "shutil.disk_usage on the repository filesystem"),
    ]
    return {
        "claim": "these readings exist and are served live",
        "not_claimed": ("the Hardware Profiler is NOT marked implemented. COMPONENT-MAP.tsv "
                        "changes on measured evidence against written acceptance criteria, "
                        "and none are written for this component yet. A profiler that feeds a "
                        "web page is also not the same as one that feeds a Placement Policy, "
                        "which is what the fabric design says it is for."),
        "reads": [{"domain": d, "what": w} for d, w in reads],
        "modules": ["backend/modelmetrics.py", "backend/hostmetrics.py"],
    }


def snapshot() -> dict[str, Any]:
    """Everything the page needs about the fabric. Pure reads; no network, no GPU."""
    subs = subcomponents()
    return {
        "component": component_status(),
        "subcomponents": subs,
        "subcomponent_count": len(subs),
        "implemented_count": sum(1 for s in subs if s["status"] != "PLANNED_SUBCOMPONENT"),
        "tree": tree_state(),
        "profiler": profiler_evidence(),
        "headline": ("PLANNED. Two files on disk, no code. This panel reads "
                     "COMPONENT-MAP.tsv and ALIASES.tsv rather than restating them."),
    }
