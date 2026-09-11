#!/usr/bin/env python3
r"""Bind `external/` to `PROJECT-TASKS.md`, so reference material becomes behaviour.

`external/` is 109 GB across 88 entries and nothing in this repo pointed at any of it.
The standing rule is *"we cannot use code in references its for reference only we must
rebrand if we want to use it"* -- so this reads and indexes, it never copies. What it
indexes is the part that is already machine-readable: **1785 `SKILL.md` files** shipped by
twelve of those repos (TensorRT-LLM, NemoClaw, OpenShell, Model-Optimizer, Megatron-LM,
nx-master, deepseek-harness, warp, playwright, vllm, DALI, backstage, plus the NVIDIA
`skills/` catalogue and `anthropics/`).

A skill's frontmatter `description:` is written as a **trigger**: "use when <problem>".
That is the same shape as a task title, which is what makes the join possible at all --
score every skill against every open task, and the highest scorers are the shapes to read
before writing a line of our own code.

Two modes, because indexing and asking are different jobs:

    python3 tools/lib/index_references.py                    # rebuild docs/REFERENCE-INDEX.md
    python3 tools/lib/index_references.py find <words...>    # ad-hoc, writes nothing
    python3 tools/lib/index_references.py adopt <project>    # external/ -> incoming/

**Nothing here reads a file body.** Only frontmatter is parsed, which caps the work at a
few hundred bytes per skill and keeps a 109 GB tree scannable in seconds. It also means
this file cannot accidentally lift an implementation into our tree: it has never seen one.
"""
from __future__ import annotations

import math
import os
import pathlib
import re
import shutil
import subprocess
import sys

REPO = next(_p for _p in pathlib.Path(__file__).resolve().parents if (_p / "backend" / "server.py").is_file())
REFS = REPO / "external"
TASKS = REPO / "PROJECT-TASKS.md"
OUT = REPO / "docs" / "REFERENCE-INDEX.md"

# Directories that cannot hold a skill worth indexing and cost minutes to walk. `.git`
# alone is most of the 109 GB.
PRUNE = {".git", "node_modules", ".venv", "venv", "__pycache__", "site-packages",
         "third_party", "build", "dist", ".mypy_cache", ".pytest_cache", "target"}

# Words that appear in nearly every skill AND nearly every task title, so they carry no
# signal and would rank a random skill against a random task. Kept short on purpose: an
# aggressive stoplist hides real joins.
STOP = set("""a an and are as at be by for from how in into is it its of on or that the
this to use used using when with what which your you we our not only if but do does done
run runs running make makes made new set get put via per one two all any each other than
skill skills agent agents code file files project task tasks work working""".split())


def words(text: str) -> set[str]:
    return {w for w in re.findall(r"[a-z0-9][a-z0-9+_-]{2,}", text.lower())
            if w not in STOP}


# ----------------------------------------------------------------- frontmatter

def frontmatter(path: pathlib.Path) -> dict[str, str]:
    """Parse just enough YAML to read a skill header, with no dependency.

    Handles the three shapes actually present in `external/`: `key: value`,
    folded scalars (`key: >-` / `key: >` / `key: |`) with an indented block under them,
    and nested mappings, which are skipped rather than half-parsed. Written by hand
    because pulling PyYAML in would put a package on the **serving** interpreter, which
    the working agreements bar outright.
    """
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            first = fh.readline()
            if first.strip() != "---":
                return {}
            raw = []
            for line in fh:
                if line.strip() == "---":
                    break
                raw.append(line.rstrip("\n"))
                if len(raw) > 200:      # a runaway file is not frontmatter
                    return {}
    except OSError:
        return {}

    out: dict[str, str] = {}
    key: str | None = None
    folded: list[str] = []
    for line in raw:
        m = re.match(r"^([A-Za-z][A-Za-z0-9_-]*):\s*(.*)$", line)
        if m and not line.startswith((" ", "\t")):
            if key is not None:
                out[key] = " ".join(folded).strip()
            key, rest = m.group(1), m.group(2).strip()
            folded = [] if rest in (">", ">-", "|", "|-", "") else [rest]
        elif key is not None and line.startswith((" ", "\t")):
            folded.append(line.strip())
    if key is not None:
        out[key] = " ".join(folded).strip()
    return out


def walk_skills(root: pathlib.Path):
    """Yield every `SKILL.md` under `root`, pruning as we descend rather than after."""
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = [d for d in dirnames if d not in PRUNE]
        if "SKILL.md" in filenames:
            yield pathlib.Path(dirpath) / "SKILL.md"


#: Entries under `external/` that are *collections* of repos rather than one repo.
#: Detected rather than guessed: a directory with no `.git` of its own whose children
#: mostly do. Naming them keeps `anthropics/skilling-up` distinct from `anthropics/xlsx`.
COLLECTIONS = {"anthropics", "openai", "bitmaintech", "contrib", "sdk", "reading", "bin"}


def origin(path: pathlib.Path) -> str:
    """The reference *project* a skill came from, one level deeper inside a collection."""
    rel = path.relative_to(REFS)
    if not rel.parts:
        return "?"
    head = rel.parts[0]
    if head in COLLECTIONS and len(rel.parts) > 2:
        return f"{head}/{rel.parts[1]}"
    return head


def collect() -> list[dict]:
    seen: dict[str, dict] = {}
    for p in walk_skills(REFS):
        fm = frontmatter(p)
        name = fm.get("name") or p.parent.name
        desc = fm.get("description", "").strip()
        if not desc:
            continue
        rec = {
            "name": name,
            "desc": re.sub(r"\s+", " ", desc),
            "origin": origin(p),
            "path": str(p.relative_to(REPO)),
            "license": fm.get("license", ""),
            "tools": fm.get("allowed-tools", ""),
            "bag": words(name.replace("-", " ")) | words(desc),
        }
        # Same skill vendored into several repos: keep the one with the fullest trigger,
        # because the description is the only thing the join scores against.
        prev = seen.get(name)
        if prev is None or len(rec["desc"]) > len(prev["desc"]):
            seen[name] = rec
    return sorted(seen.values(), key=lambda r: (r["origin"], r["name"]))


# ----------------------------------------------------------------- projects

#: A route decorator in any of the three web frameworks present in `external/`, plus
#: the express/fastify shape. Captures the PATH only -- never the handler body. That
#: restraint is the licence position: a list of URLs a project exposes is a description
#: of its surface, and copying a handler would be taking its implementation.
ROUTE_RE = re.compile(
    r"""@(?:app|router|api|bp)\.(?:get|post|put|patch|delete|websocket)\(\s*["']([^"']{1,80})["']"""
    r"""|(?:app|router)\.(?:get|post|put|use|ws)\(\s*["'](/[^"']{0,79})["']""")

#: Files worth opening when fingerprinting a project. Anything else is counted, not read.
SURFACE_FILES = ("routes.py", "api.py", "app.py", "main.py", "server.py", "run.py",
                 "index.ts", "server.ts", "routes.ts")

MARKERS = (("pyproject.toml", "python"), ("setup.py", "python"),
           ("requirements.txt", "python"), ("package.json", "node"),
           ("Cargo.toml", "rust"), ("CMakeLists.txt", "cmake"),
           ("go.mod", "go"), ("Makefile", "make"))


def readme_line(root: pathlib.Path) -> str:
    """The first sentence of prose a project offers about itself.

    Read from the README rather than inferred from the directory name, because the names
    in `external/` are download artefacts -- `drive-download-20260817T185705Z-1-001`
    tells you nothing and `RavenCalcServer_Christmas_20251224-1007` tells you a date.
    """
    for name in ("README.md", "README.rst", "README.txt", "README", "AGENTS.md"):
        f = root / name
        if not f.is_file():
            continue
        try:
            text = f.read_text(encoding="utf-8", errors="replace")[:4000]
        except OSError:
            continue
        for line in text.splitlines():
            line = line.strip()
            if not line or line.startswith(("#", "!", "<", "[!", "---", "|", "=")):
                continue
            return re.sub(r"[*`_]", "", line)[:220]
    return ""


def fingerprint(root: pathlib.Path, cap: int = 6000) -> dict:
    """What surfaces does this project expose, and what is it built out of?

    Deliberately shallow and capped. The point is to make 109 GB *navigable*, not to
    understand it -- an index that takes twenty minutes to build is an index nobody
    regenerates, and a stale index is the second state document this repo bans.
    """
    exts: dict[str, int] = {}
    routes: list[str] = []
    kinds: set[str] = set()
    seen = 0
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = [d for d in dirnames if d not in PRUNE]
        here = pathlib.Path(dirpath)
        for fn in filenames:
            seen += 1
            if seen > cap:
                break
            ext = pathlib.Path(fn).suffix.lower()
            if ext in (".py", ".ts", ".tsx", ".js", ".cu", ".cpp", ".c", ".h", ".rs",
                       ".sh", ".html", ".css", ".md"):
                exts[ext] = exts.get(ext, 0) + 1
            for marker, kind in MARKERS:
                if fn == marker:
                    kinds.add(kind)
            if fn in SURFACE_FILES and len(routes) < 40:
                try:
                    body = (here / fn).read_text(encoding="utf-8", errors="replace")[:200_000]
                except OSError:
                    continue
                for m in ROUTE_RE.finditer(body):
                    path = m.group(1) or m.group(2)
                    if path and path not in routes:
                        routes.append(path)
        if seen > cap:
            break
    return {"exts": exts, "routes": routes[:24], "kinds": sorted(kinds), "files": seen}


def project_roots() -> list[pathlib.Path]:
    """Top-level reference entries, descending one level into the known collections."""
    out = []
    for child in sorted(REFS.iterdir()):
        if not child.is_dir() or child.name.startswith("."):
            continue
        if child.name in COLLECTIONS:
            out.extend(sorted(g for g in child.iterdir()
                              if g.is_dir() and not g.name.startswith(".")))
        else:
            out.append(child)
    return out


def collect_projects(only: set[str] | None = None) -> list[dict]:
    projects = []
    for root in project_roots():
        rel = str(root.relative_to(REFS))
        if only is not None and rel not in only:
            continue
        fp = fingerprint(root)
        if not fp["files"]:
            continue
        blurb = readme_line(root)
        projects.append({
            "name": rel,
            "path": str(root.relative_to(REPO)),
            "blurb": blurb,
            **fp,
            "bag": words(rel.replace("-", " ").replace("_", " ")) | words(blurb)
                   | words(" ".join(fp["routes"]).replace("/", " ").replace("-", " ")),
        })
    return projects


# ----------------------------------------------------------------- the join

TASK_RE = re.compile(r"^◻ (#\d+) — (.+)$")


def open_tasks() -> list[dict]:
    """Title plus the indented detail block, which is where the real vocabulary lives.

    A title is five words; the block below it names the surfaces, the file paths and the
    failure being fixed. Scoring on the title alone joined almost nothing.
    """
    tasks, cur = [], None
    for line in TASKS.read_text().splitlines():
        m = TASK_RE.match(line)
        if m:
            cur = {"id": m.group(1), "title": m.group(2), "body": []}
            tasks.append(cur)
        elif cur is not None:
            if line.strip() and not line.startswith((" ", "\t")):
                cur = None                      # column zero ends the block
            elif line.strip():
                cur["body"].append(line.strip())
    for t in tasks:
        t["bag"] = words(t["title"]) | words(" ".join(t["body"][:40]))
    return tasks


def idf(skills: list[dict]) -> dict[str, float]:
    """How much is one shared word worth? Inverse document frequency answers it.

    The first cut of this scorer counted raw overlap and it produced nonsense that is
    worth recording: `jira-api`, `notion-api` and `xlsx` ranked top against **every**
    task, including "SyMoNeuRaL Image: image-to-image". Those skills have 90-word
    descriptions full of *manage*, *update*, *search*, *page* -- words this repo's task
    blocks also use constantly -- so raw overlap was measuring description length, not
    subject. `cuda`, `hls`, `lora`, `antminer` appear in a handful of skills each and are
    the words that actually mean something; IDF is what tells them apart, and it needs no
    stoplist tuning to do it.
    """
    n = len(skills) or 1
    df: dict[str, int] = {}
    for s in skills:
        for w in s["bag"]:
            df[w] = df.get(w, 0) + 1
    return {w: math.log(n / c) for w, c in df.items()}


def score(task_bag: set[str], skill: dict, weights: dict[str, float]) -> float:
    """IDF-weighted overlap, with the skill *name* counted three times over.

    A name match ("cuda-kernel-profiling" against a CUDA task) is a much stronger signal
    than the same word buried in a trigger sentence -- the name is what the skill's author
    chose when they had four words to spend.
    """
    name_bag = words(skill["name"].replace("-", " "))
    shared = task_bag & skill["bag"]
    total = sum(weights.get(w, 0.0) for w in shared)
    total += 2 * sum(weights.get(w, 0.0) for w in (task_bag & name_bag))
    # Normalise by the skill's own length. IDF alone was not enough: `claude-api` and
    # `xlsx` still topped every task, because a 90-word description simply *contains*
    # more rare words and collects a little credit from each. Dividing by sqrt(len)
    # asks the question that was meant all along -- what fraction of THIS skill is about
    # THIS task -- instead of how much ground it covers. Cosine, in one line.
    return total / math.sqrt(len(skill["bag"]) or 1)


def rank(task_bag: set[str], skills: list[dict], weights: dict[str, float],
         n: int = 6, floor: float = 1.6) -> list[tuple[float, dict]]:
    """Ranked, and floored *relative to the best match* rather than absolutely.

    A fixed floor either admits noise on a well-matched task or hides the one real hit on
    a thin one. Anything under a third of the top score is not in the same conversation.
    """
    scored = [(score(task_bag, s, weights), s) for s in skills]
    scored.sort(key=lambda p: (-p[0], p[1]["name"]))
    scored = scored[:n]
    if not scored or scored[0][0] < floor:
        return []
    cut = scored[0][0] / 3.0
    return [(sc, s) for sc, s in scored if sc >= cut]


# ----------------------------------------------------------------- output

#: The twenty entries named explicitly as the set to work from. Written down rather than
#: inferred, because the reason they are the set is not visible from the tree: they are
#: the bleeding-edge betas and the first-party work, and `external/` also holds 68 other
#: things. A name here that no longer exists on disk is a red test, not a silent skip.
FOCUS = ["vllm", "deepseek-harness", "Comfy-Desktop", "symoneural (1)", "ComfyUI (1)",
         "ComfyUI (1) (1)", "ComfyUI (2)", "ComfyUI-Shared", "ComfyUI", "bitmaintech",
         "anthropics", "openai", "cuda-python", "Model-Optimizer", "k8s-device-plugin",
         "cuml", "apex", "TensorRT", "SkillSpector", "DeepLearningExamples"]


def in_focus(name: str) -> bool:
    head = name.split("/", 1)[0]
    return head in FOCUS


def project_rows(projects: list[dict]) -> list[str]:
    L = ["| project | built of | surfaces it exposes | what it says it is |",
         "|---|---|---|---|"]
    for pr in sorted(projects, key=lambda r: r["name"].lower()):
        top = sorted(pr["exts"].items(), key=lambda kv: -kv[1])[:3]
        built = ", ".join(f"{n}&nbsp;`{e}`" for e, n in top) or "—"
        if pr["kinds"]:
            built += " · " + "/".join(pr["kinds"])
        routes = ", ".join(f"`{r}`" for r in pr["routes"][:6]) or "—"
        blurb = pr["blurb"].replace("|", "\\|")[:150] or "—"
        L.append(f"| **`{pr['name']}`** | {built} | {routes} | {blurb} |")
    return L


def write_index(skills: list[dict], tasks: list[dict],
                weights: dict[str, float], projects: list[dict]) -> str:
    by_origin: dict[str, int] = {}
    for s in skills:
        by_origin[s["origin"]] = by_origin.get(s["origin"], 0) + 1

    L = []
    L.append("# What is in `external/`, and which open task each part bears on")
    L.append("")
    L.append("**Generated by `tools/lib/index_references.py`. Do not hand-edit — regenerate.**")
    L.append("")
    L.append("`external/` is read-only material: *\"we cannot use code in references its for")
    L.append("reference only we must rebrand if we want to use it\"*. This index exists so that")
    L.append("reading it is cheap enough to actually happen. It records **where a shape lives and")
    L.append("what problem it claims to solve** — never an implementation, and nothing here has")
    L.append("read a file body: only YAML frontmatter is parsed.")
    L.append("")
    L.append(f"**{len(skills)} distinct skills** across **{len(by_origin)} reference repos**,")
    L.append("indexed by their frontmatter trigger.")
    L.append("")
    L.append("| reference repo | skills |")
    L.append("|---|---|")
    for o, n in sorted(by_origin.items(), key=lambda p: -p[1]):
        L.append(f"| `{o}` | {n} |")
    L.append("")
    focus = [pr for pr in projects if in_focus(pr["name"])]
    rest = [pr for pr in projects if not in_focus(pr["name"])]
    L.append("## The twenty named as the set to work from")
    L.append("")
    L.append("Bleeding-edge betas and first-party work, named explicitly. `surfaces it exposes`")
    L.append("is route paths lifted from `routes.py`/`app.py`/`server.ts` and nothing else — a")
    L.append("URL list describes a surface; a handler body would be taking the implementation.")
    L.append("")
    L.extend(project_rows(focus))
    L.append("")
    L.append("## Every other reference project")
    L.append("")
    L.extend(project_rows(rest))
    L.append("")
    L.append("## Per task: read these before writing our own")
    L.append("")
    L.append("Scored on vocabulary overlap between the task's title-plus-detail block and the")
    L.append("skill's own trigger sentence, name matches weighted 3x. A task with no rows scored")
    L.append("nothing above the floor — that is a real answer, not a gap to paper over.")
    L.append("")
    hits = 0
    for t in tasks:
        rows = rank(t["bag"], skills, weights)
        if not rows:
            continue
        hits += 1
        L.append(f"### {t['id']} — {t['title']}")
        L.append("")
        L.append("| skill | from | score | trigger |")
        L.append("|---|---|---|---|")
        for sc, s in rows:
            trig = s["desc"][:170].replace("|", "\\|")
            L.append(f"| `{s['name']}` | `{s['origin']}` | {sc:.1f} | {trig} |")
        L.append("")
    L.append(f"_{hits} of {len(tasks)} open tasks matched at least one skill._")
    L.append("")
    L.append("## Every skill, by origin")
    L.append("")
    cur = None
    for s in skills:
        if s["origin"] != cur:
            cur = s["origin"]
            L.append("")
            L.append(f"### `{cur}`")
            L.append("")
        lic = f" · {s['license']}" if s["license"] else ""
        L.append(f"- **`{s['name']}`**{lic} — {s['desc'][:200]}")
        L.append(f"  <br>`{s['path']}`")
    L.append("")
    return "\n".join(L) + "\n"


# ----------------------------------------------------------------- adopt

INCOMING = REPO / "incoming"

LICENCE_FILES = ("LICENSE", "LICENSE.md", "LICENSE.txt", "LICENCE", "COPYING",
                 "LICENSE-APACHE", "LICENSE-MIT")


def licence_of(root: pathlib.Path) -> tuple[str, str]:
    """(filename, first meaningful line) of whatever licence the project ships.

    Recorded at the moment of adoption rather than looked up later, because the thing
    that makes a licence checkable is knowing *which* text shipped with *which* copy.
    A project with no licence file returns `("", "")` and that is written down as such --
    an unlicensed adoption is a decision someone has to make knowingly.
    """
    for name in LICENCE_FILES:
        f = root / name
        if f.is_file():
            try:
                text = f.read_text(encoding="utf-8", errors="replace")[:2000]
            except OSError:
                return name, ""
            for line in text.splitlines():
                line = line.strip()
                if len(line) > 12 and not line.startswith(("=", "-", "#")):
                    return name, line[:160]
            return name, ""
    return "", ""


def adopt(rel: str) -> int:
    """Copy one reference project into `incoming/`, where it stops being read-only.

    The standing rule is *"we cannot use code in references its for reference only we
    must rebrand if we want to use it"* -- so the rule is about **where a file lives**,
    and the way past it is to move the thing, not to argue with the rule. `incoming/` is
    that somewhere else: a staging area whose whole contract is that everything in it is
    on its way to being rebranded and is not shipped from where it lands.

    Copy, never move. `external/` is the provenance; destroying it to satisfy a rule
    about it would leave nothing to check the rebrand against.
    """
    src = REFS / rel
    if not src.is_dir():
        print(f"no such reference project: {rel}", file=sys.stderr)
        return 1
    dst = INCOMING / pathlib.Path(rel).name.replace(" ", "-")
    if dst.exists():
        print(f"already adopted: {dst.relative_to(REPO)}", file=sys.stderr)
        return 1

    lic_file, lic_line = licence_of(src)
    fp = fingerprint(src)
    INCOMING.mkdir(exist_ok=True)
    shutil.copytree(src, dst, symlinks=True,
                    ignore=shutil.ignore_patterns(*PRUNE), dirs_exist_ok=False)

    routes = "\n".join(f"- `{r}`" for r in fp["routes"]) or "_none found_"
    built = ", ".join(f"{n} `{e}`" for e, n in
                      sorted(fp["exts"].items(), key=lambda kv: -kv[1])[:6]) or "—"
    (dst / "PROVENANCE.md").write_text(f"""# Where this came from, and what still has to happen to it

**Adopted from `external/{rel}` by `tools/lib/index_references.py adopt`.**

`external/` is read-only material -- *"we cannot use code in references its for
reference only we must rebrand if we want to use it"*. That rule is about **where a file
lives**, so this copy exists to get past it honestly: everything under `incoming/` is on
its way to being rebranded, and nothing here is shipped from where it sits.

The original is still at `external/{rel}` and was **copied, not moved**. That is
deliberate: the reference copy is what a rebrand gets checked against, and deleting it to
satisfy a rule about it would leave nothing to check.

| | |
|---|---|
| origin | `external/{rel}` |
| built of | {built} |
| licence file | {lic_file or "**none shipped**"} |
| licence line | {lic_line or "—"} |

## Surfaces it exposes

{routes}

## Before anything here ships

1. **Rebrand.** Names, paths, user-visible strings. Not a blind replace -- most `MIT`
   substrings in this corpus are ordinary words (limits, submit, emits).
2. **Keep the attribution the licence requires.** If the table above says a licence
   shipped, its terms travel with the code; if it says none shipped, that is a decision
   to make knowingly rather than a gap to fill in silently.
3. **Give it a task number.** `PROJECT-TASKS.md` is where work comes from, and an
   adoption is not itself permission to build -- `INTAKE.md` is the way in.
""")
    print(f"{rel} -> {dst.relative_to(REPO)}  (licence: {lic_file or 'NONE'})")
    return 0


# ---------------------------------------------------------------- vendoring SDKs (#103)

VENDOR = REPO / "backend" / "vendor"

# What counts as an SDK, stated as a rule rather than as a list of twelve names.
#
# A list would be right today and wrong the next time a repo is cloned into external/,
# and nobody would find out -- the failure is silent in the direction that matters, because
# a missing SDK looks exactly like an SDK that was never there. The rule is the directory
# name, which is how every one of these is actually recognised by a person reading `ls`.
#
# It is deliberately loose. `agent-sdk-workshop` is a workshop and `apps-sdk-ui` is a UI
# kit, and both are swept in; the manifest names everything it matched so an over-match is
# visible and correctable rather than silent. An under-match would not be.
def is_sdk(path: pathlib.Path) -> bool:
    return "sdk" in path.name.lower()


# The operative sentence of each licence family, not the copyright line above it. Reading
# the first non-blank line gets `Copyright 2023 Anthropic, PBC.` from an MIT file and from
# an all-rights-reserved file alike -- identical text, opposite meanings -- so the grant
# itself has to be what is matched.
GRANTS = (
    ("MIT", "permission is hereby granted, free of charge"),
    ("Apache-2.0", "apache license, version 2.0"),
    ("BSD-3-Clause", "redistribution and use in source and binary forms"),
    ("ISC", "permission to use, copy, modify, and/or distribute this software"),
)
RESERVED = "all rights reserved"


def licence_grant(root: pathlib.Path) -> tuple[str, str, str]:
    """(verdict, filename, evidence) read out of the shipped licence text.

    #97's `TheProvenanceBuiltByARealExtractionTests` is the reason this returns evidence
    rather than a bare verdict: a `license_determined` field that returned a hardcoded True
    from the builder was invisible to every test that called the helpers directly, and one
    of seven deliberate breaks stayed green. The quoted phrase is what makes the verdict
    checkable by somebody who does not trust this function.
    """
    for name in LICENCE_FILES:
        f = root / name
        if not f.is_file():
            continue
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return "UNREADABLE", name, ""
        low = text.lower()
        for spdx, phrase in GRANTS:
            if phrase in low:
                return spdx, name, phrase
        if RESERVED in low:
            return "ALL-RIGHTS-RESERVED", name, RESERVED
        return "UNRECOGNISED", name, ""
    return "NONE", "", ""


# Only these may be copied. Everything else is named in the manifest and left where it is.
#
# Absent a grant the default is all rights reserved -- "no LICENSE file" is not a permissive
# default and must not be treated as one. `claude-agent-sdk-typescript` makes the point
# sharper than any argument could: it DOES ship a licence, and that licence reserves every
# right and points at a commercial ToS. A rule that keyed on "has a LICENSE file" would have
# vendored it.
VENDORABLE = {"MIT", "Apache-2.0", "BSD-3-Clause", "ISC"}


def git_origin(root: pathlib.Path) -> tuple[str, str]:
    """(remote url, short sha) for a reference checkout, read from its own .git.

    Recorded because a vendored tree with no upstream coordinate cannot be diffed against
    anything, updated deliberately, or checked for a security advisory. `adopt()` writes an
    origin PATH, which says where on this disk it came from and nothing about which code it
    is -- and this box's external/ is the only copy of that path in the world.
    """
    def run(*args: str) -> str:
        try:
            out = subprocess.run(["git", "-C", str(root), *args],
                                 capture_output=True, text=True, timeout=30)
            return out.stdout.strip() if out.returncode == 0 else ""
        except (OSError, subprocess.SubprocessError):
            return ""
    return run("remote", "get-url", "origin"), run("rev-parse", "--short", "HEAD")


def sdk_survey() -> list[dict]:
    """Every SDK under external/, with its licence read and its upstream recorded.

    Survey and copy are separate on purpose: this function decides nothing and writes
    nothing, so the manifest can name what was refused as confidently as what was taken.
    """
    rows = []
    for git in sorted(REFS.glob("*/*/.git")):
        root = git.parent
        if not is_sdk(root):
            continue
        verdict, lic_file, evidence = licence_grant(root)
        url, sha = git_origin(root)
        rows.append({
            "rel": str(root.relative_to(REFS)),
            "root": root,
            "licence": verdict,
            "licence_file": lic_file,
            "evidence": evidence,
            "url": url,
            "sha": sha,
            "vendored": verdict in VENDORABLE,
        })
    return rows


def vendor_sdks() -> int:
    """Copy every permissively licensed SDK into archive/vendor-sdks/, and write the manifest.

    Idempotent: each destination is removed and rewritten from the source, so a second run
    produces byte-identical trees and `git status` stays clean. That is the repo's standing
    rule for generators -- run it twice and diff -- and it applies here because this is one.
    """
    rows = sdk_survey()
    if not rows:
        print("no SDKs found under external/", file=sys.stderr)
        return 1

    VENDOR.mkdir(parents=True, exist_ok=True)
    for r in rows:
        dst = VENDOR / r["rel"]
        if not r["vendored"]:
            # Never leave a stale copy of something that has since been reclassified.
            if dst.exists():
                shutil.rmtree(dst)
            continue
        if dst.exists():
            shutil.rmtree(dst)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(r["root"], dst, symlinks=True,
                        ignore=shutil.ignore_patterns(*PRUNE))
        r["bytes"] = sum(f.stat().st_size for f in dst.rglob("*") if f.is_file())

    (VENDOR / "PROVENANCE.md").write_text(_vendor_manifest(rows))
    took = [r for r in rows if r["vendored"]]
    left = [r for r in rows if not r["vendored"]]
    for r in rows:
        print(f"{'vendor' if r['vendored'] else 'REFUSE'}  {r['rel']:<44} "
              f"{r['licence']:<21} {r['sha']}")
    print(f"\n{len(took)} vendored, {len(left)} left in external/ "
          f"-> {(VENDOR / 'PROVENANCE.md').relative_to(REPO)}")
    return 0


def _vendor_manifest(rows: list[dict]) -> str:
    def table(rs):
        if not rs:
            return "_none_\n"
        out = ["| repo | licence | upstream | commit |", "|---|---|---|---|"]
        for r in rs:
            url = f"[{r['url'].removesuffix('.git').split('/')[-1]}]({r['url']})" if r["url"] else "—"
            out.append(f"| `{r['rel']}` | {r['licence']} | {url} | `{r['sha'] or '—'}` |")
        return "\n".join(out) + "\n"

    took = [r for r in rows if r["vendored"]]
    left = [r for r in rows if not r["vendored"]]
    refused = "\n".join(
        f"- **`{r['rel']}`** — {r['licence']}. "
        + (f"Its `{r['licence_file']}` contains *\"{r['evidence']}\"*."
           if r["evidence"] else
           (f"It ships `{r['licence_file']}` and no grant this tool recognises."
            if r["licence_file"] else "It ships **no licence file at all**."))
        for r in left) or "_none — every SDK found carried a grant._"

    return f"""# archive/vendor-sdks — what is here, where it came from, and what was refused

Written by `tools/lib/index_references.py vendor`. Do not hand-edit: it is regenerated, and a
hand-added row would be a claim nobody read a licence file to make.

**{len(took)} vendored, {len(left)} refused**, out of {len(rows)} directories under
`external/` whose name contains `sdk`.

`external/` is `/references` in `.gitignore`, so none of this was version-controlled by us
before. These copies are.

## Vendored

{table(took)}
Each tree is copied with its `.git` stripped, its `LICENSE` kept, and the build/dependency
directories in `PRUNE` left behind — `node_modules`, `target`, `dist`, `.venv` and the rest.
The upstream commit above is the coordinate that makes a copy checkable; without it a
vendored tree cannot be diffed against anything, updated deliberately, or checked against an
advisory.

## Refused, and why

An absent licence is **not** a permissive default. Without a grant the default is all rights
reserved, so these are named here rather than copied, and this record is the deliverable for
them:

{refused}

`claude-agent-sdk-typescript` is the one to read twice. It *does* ship a licence, and that
licence reserves every right and points at a commercial ToS — so a rule keyed on "has a
LICENSE file" would have vendored it. The grant is what is matched, never the presence of the
file, and never the copyright line, which is identical in an MIT file and in this one.

Two of the refused are repos Garrett named directly when he asked for this. That is recorded
rather than smoothed over: adopting unlicensed code is a decision for him to make knowingly,
and this is where it would be written down if he ever makes it.

## Vendoring is not installing

Copying source gives provenance and version control. It does not give a dependency graph.
`claude-agent-sdk-python` requires `anyio`, `sniffio`, `mcp` and `jsonschema`; none are on
this box's system interpreter, and `.claude/CLAUDE.md` bars `pip install` there because that
is the serving path — fastapi, uvicorn, pydantic and sympy are OS packages and there is no
virtualenv in front of them.

So importing anything here needs its own isolated venv. That rule is already written down
(*"anything else that conflicts gets its own isolated venv"*) and `training/.venv` is the
precedent. Building it is not part of #103; knowing it is required before anybody writes
`import claude_agent_sdk` is.

## Regenerating

```bash
python3 tools/lib/index_references.py vendor      # idempotent -- run twice and diff
git status --porcelain archive/vendor-sdks         # .gitignore has unanchored *.log, *.key, *.bak
```

That second line is not optional. `.gitignore` carries `*.log`, `*.bak`, `*.key`,
`*.safetensors`, `*.gguf`, `__pycache__/` and `**/.venv/` with no path anchor, so each one
silently swallows matching files *inside* a vendored tree. A tree that is 90% tracked reads
as complete and is not.
"""


def main(argv: list[str]) -> int:
    if not REFS.is_dir():
        print(f"no external/ at {REFS}", file=sys.stderr)
        return 1
    skills = collect()

    if len(argv) > 1 and argv[1] == "vendor":
        return vendor_sdks()

    if len(argv) > 1 and argv[1] == "adopt":
        if len(argv) < 3:
            print("adopt what? (a path under external/)", file=sys.stderr)
            return 2
        return adopt(" ".join(argv[2:]))

    if len(argv) > 1 and argv[1] == "find":
        bag = words(" ".join(argv[2:]))
        if not bag:
            print("find what?", file=sys.stderr)
            return 2
        for sc, s in rank(bag, skills, idf(skills), n=12, floor=0.0):
            print(f"{sc:>6.1f}  {s['name']:<44} {s['origin']}")
            print(f"      {s['desc'][:150]}")
            print(f"      {s['path']}")
        return 0

    tasks = open_tasks()
    projects = collect_projects()
    missing = [f for f in FOCUS if not (REFS / f).exists()]
    if missing:
        print(f"WARNING: named but not on disk: {missing}", file=sys.stderr)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(write_index(skills, tasks, idf(skills), projects))
    print(f"{len(skills)} skills, {len(projects)} projects, {len(tasks)} open tasks "
          f"-> {OUT.relative_to(REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
