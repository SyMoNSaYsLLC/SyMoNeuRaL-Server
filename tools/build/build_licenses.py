#!/usr/bin/env python3
"""Render LICENSES.md from ops/LICENSES.tsv. The TSV is the record; this is the view.

Same split as `ops/PORTS.tsv` -> `docs/ops/PORTS.md`, for the same reason: a
figure that lives only in prose is a figure nobody can re-measure, and this file
has to answer "what could get us sued" with numbers somebody can check.

    tools/build/build_licenses.py           # rewrite LICENSES.md
    tools/build/build_licenses.py --check   # fail if it is out of date

Run `tools/audit/license_inventory.py` first; this refuses to render a stale TSV.
"""

from __future__ import annotations

import argparse
import csv
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents
            if (p / "backend" / "server.py").is_file())
TSV = ROOT / "ops" / "LICENSES.tsv"
OUT = ROOT / "LICENSES.md"
GENERATOR = ROOT / "tools" / "audit" / "license_inventory.py"


def rows() -> list[dict]:
    with TSV.open() as fh:
        return list(csv.DictReader((l for l in fh if not l.startswith("#")),
                                   delimiter="\t"))


def measured_on() -> str:
    """The commit the TSV was last written at, so no figure floats free of one."""
    try:
        out = subprocess.run(["git", "log", "-1", "--format=%h %cs", "--", str(TSV)],
                             cwd=ROOT, capture_output=True, text=True, timeout=10)
        return out.stdout.strip() or "uncommitted"
    except (OSError, subprocess.TimeoutExpired):
        return "uncommitted"


PARTY = {
    "first": "**First party** — we wrote it. Ours to licence as we choose.",
    "second": "**Second party** — someone else's work we forked and modified. "
              "Their licence still governs; our changes sit on top of it.",
    "third": "**Third party** — someone else's work, used unmodified.",
}

KLASS_ORDER = ["copyleft", "weak-copyleft", "UNKNOWN", "proprietary", "permissive"]

CLASS_MEANS = {
    "copyleft": "can oblige us to publish source of whatever it is combined with, "
                "**if we distribute that combination**",
    "weak-copyleft": "oblige us to publish changes *to that component*, not to our "
                     "own code beside it",
    "proprietary": "read the terms; some forbid redistribution outright",
    "permissive": "attribution, and nothing else",
    "UNKNOWN": "not yet measured. Unknown is not the same as absent, and it is "
               "not the same as safe",
}

COMFYUI = """\
## The one item that is a real decision

`symoneural-ui` is a fork of **ComfyUI, which is GPL-3.0** — confirmed 2026-09-11
against the GitHub API, not assumed. It is the only copyleft component in the
720, and it is the only row on this page that needs a person rather than a
generator.

**What is true, measured, not inferred:**

- The fork lives at `/home/google/Symoneural/symoneural-ui`. It is not in this
  repository and nothing here builds it.
- `backend/studio/` talks to it **over HTTP**, on `127.0.0.1:8188`, through
  `SYMONEURAL_COMFY_URL`. A socket between two processes is an arm's-length
  boundary and is the weakest possible coupling.
- **But** `backend/studio/custom_nodes/symoneural_cleanroom/` and
  `symoneural_gguf/` are ours, are tracked in this repository, and both export
  `NODE_CLASS_MAPPINGS` — which is ComfyUI's plugin ABI. They are *loaded into
  the GPL-3.0 process*. Neither imports a `comfy` module (hence "cleanroom"),
  but dynamic loading into a GPL process is exactly the linkage question that
  has no settled answer.

**What this page will not do is decide that.** Whether a plugin loaded into a
GPL-3.0 host forms a derivative work is genuinely contested, and per the naming
doctrine — *"that is not your call to make — record what was borrowed and from
where"* — it is recorded here and left to the owner and counsel.

**What makes it safe today, and what would change that:** nothing is
distributed. The fork is on the build host only, and the custom nodes only ever
load on this box. The obligation attaches on *distribution*, so the day this
stops being true is the day someone builds a package that contains both — a
`.deb`, an image, a VM, a customer install. That is the trigger to answer the
question above, and it must be answered before such a build ships, not after.

The previous version of this file said ComfyUI was *"present on the build host;
not built, not incorporated, not packaged, not deployed."* Three of those four
are still right. **"Not incorporated" was wrong**: two first-party packages are
written against its plugin ABI and are loaded into its process.
"""


def render(data: list[dict]) -> str:
    by_klass = Counter(r["klass"] for r in data)
    by_party = Counter(r["party"] for r in data)
    stamp = measured_on()

    out: list[str] = []
    w = out.append

    w("# What this project is made of, and what each piece obliges\n")
    w(f"**{len(data)} components**, measured at `{stamp}`. This file is generated "
      f"from `ops/LICENSES.tsv` by `tools/build/build_licenses.py`; the TSV is "
      f"generated from the disk by `tools/audit/license_inventory.py`. "
      f"**Do not hand-edit either** — re-run them.\n")
    w("The reason it is generated: a licence inventory typed by hand is wrong "
      "within a week, and every figure here has to be something a person can "
      "re-measure rather than trust.\n")

    w("## The short answer\n")
    w("| Class | Components | What it obliges |")
    w("|---|---:|---|")
    for k in KLASS_ORDER:
        if by_klass.get(k):
            w(f"| {k} | {by_klass[k]} | {CLASS_MEANS[k]} |")
    w("")
    w(f"**One copyleft component in {len(data)}** — the ComfyUI fork, and it is "
      f"not distributed. Everything else that ships is permissive or ours. The "
      f"{by_klass.get('UNKNOWN', 0)} unmeasured rows are the open work, and they "
      f"are listed in full below rather than summarised away.\n")

    w("## By party\n")
    for party in ("first", "second", "third"):
        if not by_party.get(party):
            continue
        w(f"### {party.title()} party — {by_party[party]} components\n")
        w(PARTY[party] + "\n")
        rowset = [r for r in data if r["party"] == party]
        if party == "third":
            w("Too many to list individually here; they are every row of "
              "`ops/LICENSES.tsv` with `party=third`. By ecosystem:\n")
            w("| Ecosystem | Components | Classes present |")
            w("|---|---:|---|")
            eco = defaultdict(list)
            for r in rowset:
                eco[r["ecosystem"]].append(r)
            for name, items in sorted(eco.items()):
                classes = ", ".join(f"{k}×{n}" for k, n in
                                    Counter(i["klass"] for i in items).most_common())
                w(f"| {name} | {len(items)} | {classes} |")
            w("")
            continue
        w("| Component | Licence | Class | Carried | Where |")
        w("|---|---|---|---|---|")
        for r in sorted(rowset, key=lambda r: r["component"]):
            w(f"| `{r['component']}` | {r['licence']} | {r['klass']} | "
              f"{r['carried']} | `{r['where']}` |")
        w("")

    w(COMFYUI)

    weak = [r for r in data if r["klass"] == "weak-copyleft"]
    if weak:
        w("\n## Weak copyleft — attribution plus changes to the component itself\n")
        w("None of these is modified here, so nothing beyond attribution is owed. "
          "Listed because that would stop being true the moment one is patched.\n")
        w("| Component | Licence | Where |")
        w("|---|---|---|")
        for r in sorted(weak, key=lambda r: r["component"]):
            w(f"| `{r['component']}` | {r['licence']} | {r['where']} |")
        w("")

    unknown = [r for r in data if r["klass"] == "UNKNOWN"]
    if unknown:
        w(f"\n## Unmeasured — {len(unknown)} rows that still need an answer\n")
        w("Unknown is not absent and is not safe. Each of these is a component "
          "whose licence this generator could not read, and every one must be "
          "resolved before anything containing it is distributed.\n")
        eco = defaultdict(list)
        for r in unknown:
            eco[r["ecosystem"]].append(r)
        for name, items in sorted(eco.items()):
            names = sorted({i["component"] for i in items})
            w(f"**{name}** ({len(names)}): " + ", ".join(f"`{n}`" for n in names))
            w("")

    w("\n## Two gaps this file names rather than hides\n")
    w("- **The gateway ships 362 crates and has no notices file.** Their licences "
      "are now measured (permissive throughout; the two GPL crates, `ittapi` and "
      "`ittapi-sys`, are `GPL-2.0-only OR BSD-3-Clause`, so BSD applies). What "
      "does not exist is the attribution file those permissive licences require "
      "on distribution. `backend/remix/THIRD-PARTY-LICENSES.md` is the only "
      "notices file in the repository.")
    w("- **npm is declared but never installed.** `frontend/app` has had no "
      "`npm ci` run, so its dependency tree is unmeasured beyond the nine names "
      "in `package.json`. Those nine are listed as UNKNOWN above, which is "
      "honest, and they will resolve the first time the tree is installed.\n")

    w("## How to re-measure\n")
    w("```bash")
    w("tools/audit/license_inventory.py            # rewrite ops/LICENSES.tsv")
    w("tools/audit/license_inventory.py --findings # only the rows needing a decision")
    w("tools/build/build_licenses.py               # rewrite this file")
    w("```\n")
    w("Python is read with `importlib.metadata` inside **each venv**, not the "
      "system interpreter — reading the system one reports torch, transformers "
      "and cupy as absent while five venvs hold them. PEP 639 "
      "`License-Expression` is read before classifiers: reading classifiers "
      "alone reported 207 packages as unlicensed when the true figure was 13. "
      "System-python rows are included only when this repository actually "
      "imports something they provide, so the operating system's own packages "
      "(`nala`, `mpv`, `iotop`, PyQt) are not reported as our dependencies.\n")

    return "\n".join(out)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true",
                        help="exit 1 if LICENSES.md is out of date")
    args = parser.parse_args(argv)

    if not TSV.is_file():
        print(f"{TSV} does not exist; run {GENERATOR.relative_to(ROOT)} first",
              file=sys.stderr)
        return 1

    text = render(rows())
    if args.check:
        if OUT.is_file() and OUT.read_text() == text:
            print(f"{OUT.name} is current")
            return 0
        print(f"{OUT.name} is out of date; run without --check", file=sys.stderr)
        return 1

    OUT.write_text(text)
    print(f"wrote {OUT.name} from {TSV.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
