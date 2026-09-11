#!/usr/bin/env python3
"""Render `ops/RUNTIMES.tsv` into `ops/registry/RUNTIMES.md`, measuring the volatile half fresh.

    python3 tools/build/build_runtimes.py            # writes the doc
    python3 tools/build/build_runtimes.py --check    # exit 1 if the doc is stale

Same split as `tools/build/build_ports.py`: the TSV is the record, this is the view. The extra job
here is that **half of what a runtime map should tell you is a measurement, not a decision** —
how big the artefact is, when it was built, which CUDA minor it actually links. Those must not
sit in a hand-maintained file, because a stale reading there is the carried-forward figure this
repository has published before. So they are read off the disk here, every run.

There is deliberately **no wall-clock stamp** in the output. A `--check` that fails once a day
teaches people to ignore it. The date of these measurements is the date of the commit that
carries the file: `git log -1 ops/registry/RUNTIMES.md`.

Run it twice and diff. This repository has had a generator accumulate its own output three
times, and two clean runs is the check that catches it.
"""
from __future__ import annotations

import pathlib
import re
import subprocess
import sys

ROOT = next(_p for _p in pathlib.Path(__file__).resolve().parents if (_p / "backend" / "server.py").is_file())
sys.path.insert(0, str(ROOT / "backend"))
from registry.lib import runtimes  # noqa: E402

OUT = ROOT / "ops" / "registry" / "RUNTIMES.md"

#: The environment a runtime is started in decides which of the two installed CUDA trees it
#: links, because `LD_LIBRARY_PATH` outranks `DT_RUNPATH` in the dynamic loader's search order.
#: An interactive shell here exports the first; systemd exports neither.
SHELL_LD_PATH = "/usr/local/cuda/lib64"


def _run(argv: list[str], env: dict[str, str] | None = None) -> str:
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=30, env=env)
    except (OSError, subprocess.SubprocessError) as exc:
        return f"(could not run {argv[0]}: {exc})"
    return p.stdout + p.stderr


def _tracked(rel: str) -> bool:
    p = subprocess.run(["git", "ls-files", "--error-unmatch", rel],
                       cwd=ROOT, capture_output=True, text=True)
    return p.returncode == 0


def _human(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{n} B"
        n /= 1024.0
    return str(n)


def _nvcc() -> str:
    m = re.search(r"release ([\d.]+), V([\d.]+)", _run(["nvcc", "--version"]))
    return f"{m.group(1)} (V{m.group(2)})" if m else "not on PATH"


def _driver() -> str:
    out = _run(["nvidia-smi", "--query-gpu=driver_version", "--format=csv,noheader"]).strip()
    return out.splitlines()[0] if out else "unreadable"


def _alt_ctime() -> str:
    """When the CUDA alternative was last switched. `lstat`, so the symlink not its target."""
    try:
        st = pathlib.Path("/etc/alternatives/cuda").lstat()
    except OSError:
        return "absent"
    return __import__("datetime").datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d")


def _runpath(path: pathlib.Path) -> str:
    out = _run(["objdump", "-p", str(path)])
    hits = re.findall(r"^\s*(?:RUNPATH|RPATH)\s+(\S+)", out, re.M)
    return hits[0] if hits else "—"


def _cuda_libs(path: pathlib.Path, with_ld_path: bool) -> list[str]:
    """Where this binary's CUDA libraries resolve to, in one of the two environments."""
    import os
    env = {k: v for k, v in os.environ.items() if k != "LD_LIBRARY_PATH"}
    if with_ld_path:
        env["LD_LIBRARY_PATH"] = SHELL_LD_PATH
    out = _run(["ldd", str(path)], env=env)
    return sorted({m.group(1) for m in
                   re.finditer(r"=>\s+(\S*cuda\S*/\S+)", out)})


def _cuda_version(paths: list[str]) -> str:
    """13.3, 13.4, or the honest answer when the path does not say."""
    vers = sorted({m.group(1) for p in paths for m in [re.search(r"cuda-(\d+\.\d+)", p)] if m})
    if vers:
        return " + ".join(vers)
    if any("/usr/local/cuda/" in p for p in paths):
        real = pathlib.Path("/usr/local/cuda").resolve()
        m = re.search(r"cuda-(\d+\.\d+)", str(real))
        return f"{m.group(1)} (via the `/usr/local/cuda` alternative)" if m else "unresolved"
    return "—"


def measure(rel: str) -> dict[str, object]:
    """Everything about an artefact that changes when somebody rebuilds it."""
    path = ROOT / rel
    if not path.exists():
        return {"present": False}
    st = path.stat()
    kind = _run(["file", "-bL", str(path)]).strip().split(",")[0]
    d: dict[str, object] = {
        "present": True,
        "bytes": st.st_size,
        "size": _human(st.st_size),
        "built": __import__("datetime").datetime.fromtimestamp(st.st_mtime)
                 .strftime("%Y-%m-%d %H:%M"),
        "tracked": _tracked(rel),
        "kind": kind,
        "symlink": path.is_symlink(),
    }
    if "ELF" in kind:
        d["runpath"] = _runpath(path)
        withp = _cuda_libs(path, True)
        without = _cuda_libs(path, False)
        d["cuda_shell"] = _cuda_version(withp) if withp else "—"
        d["cuda_systemd"] = _cuda_version(without) if without else "—"
        d["cuda_diverges"] = bool(withp or without) and d["cuda_shell"] != d["cuda_systemd"]
        d["needed"] = len(re.findall(r"NEEDED", _run(["objdump", "-p", str(path)])))
    return d


def render() -> str:
    rows = runtimes.rows()
    L: list[str] = [
        "# The runtime map",
        "",
        "**Generated by `tools/build/build_runtimes.py` from `ops/RUNTIMES.tsv`. Do not hand-edit.**",
        "",
        "`ops/PORTS.tsv` records where a surface *listens*. Until 2026-09-10 nothing recorded",
        "what runs behind it, what invokes it, what it loads, or whether it takes the GPU lease —",
        "those answers lived in `api.py`'s argv builders, `gpu-governor.sh`'s `case` arms,",
        "`restore/manifests/BUILD-RECIPES.tsv` and nowhere respectively.",
        "",
        "The **decisions** are in `ops/RUNTIMES.tsv`. The **measurements** below are read off the",
        "disk by the generator on every run, because a size or a build date in a hand-maintained",
        "file goes stale silently. There is no timestamp in this file on purpose: its date is the",
        "date of the commit that carries it — `git log -1 ops/registry/RUNTIMES.md`.",
        "",
        "**Not to be confused with `backend/hardware/docs/RUNTIME-PROFILES.md`**, whose name is one word away",
        "and whose first line says *\"Status: stub. A contract for something not yet built.\"* That",
        "file is a maturity ladder for runtimes that mostly do not exist here, written against the",
        "old `engines/symoneural-*` layout. This file is a reading of what is on this disk today.",
        "Neither supersedes the other; they answer different questions, and reading one as the",
        "other is the mistake their names invite.",
        "",
        "The key is **(runtime, surface)**, not runtime. `symoneural-diffuse` serves `image` and",
        "`sigil` from the same binary and the same weights under two governor surfaces with two",
        "eviction arms; one row would hide the sigil surface from the eviction logic.",
        "",
        "## Every runtime",
        "",
        "| runtime | surface | kind | invoked by | how | port | lease | state |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        dash = lambda v: v if v != "-" else "—"  # noqa: E731
        L.append(f"| `{r['RUNTIME']}` | {dash(r['SURFACE'])} | {r['KIND']} | "
                 f"{dash(r['INVOKED_BY'])} | {r['INVOCATION']} | {dash(r['PORT'])} | "
                 f"{dash(r['LEASE'])} | {r['STATE']} |")

    L += ["", "## Artefacts, measured", "",
          "`tracked` is `git ls-files`, not a guess: four of these are untracked build output and",
          "come back only through `restore/manifests/BUILD-RECIPES.tsv`.",
          "",
          "| artefact | size | built | tracked | type |", "|---|---|---|---|---|"]
    seen: set[str] = set()
    for r in rows:
        rel = r["ARTEFACT"]
        if rel == "-" or rel in seen:
            continue
        seen.add(rel)
        m = measure(rel)
        if not m["present"]:
            L.append(f"| `{rel}` | **ABSENT** | — | — | — |")
            continue
        L.append(f"| `{rel}` | {m['size']} | {m['built']} | "
                 f"{'yes' if m['tracked'] else '**no**'} | {m['kind']} |")
    L += ["",
          "The `type` column is `file -bL`'s answer verbatim, including where it is wrong:",
          "`file(1)` content-sniffs and calls `backend/server.py` JavaScript. That is a property of",
          "`file`, not of the repository, and it is left uncorrected because a generator that",
          "quietly overrides its own measurement is worse than one that reports an odd one.",
          "`symoneural-llm` at 17 KB is the other reading to distrust on sight: it is a shim, and",
          "the engine is the 86 MB of shared libraries beside it."]

    L += ["", "## Which CUDA each engine actually links, and why it depends on who starts it", "",
          "`LD_LIBRARY_PATH` outranks `DT_RUNPATH` in the loader's search order. An interactive",
          f"shell on this box exports `LD_LIBRARY_PATH={SHELL_LD_PATH}`; **the systemd units export",
          "no `LD_LIBRARY_PATH` at all** (measured from `/proc/<pid>/environ` of the running API).",
          "So the same binary can link a different CUDA depending on whether a person or the unit",
          "started it — which means *where you test an engine changes what you are testing*.",
          "",
          "| binary | RUNPATH | in a shell | under systemd | same? |", "|---|---|---|---|---|"]
    # Scoped to THIS table. The first version of this guard tested membership against the
    # whole document, which the Artefacts table above had already populated with every
    # artefact -- so the loop skipped all of them and the section rendered as a bare header.
    # An empty table reads as "nothing to report" rather than as a bug, which is why it
    # nearly shipped.
    charted: set[str] = set()
    for r in rows:
        rel = r["ARTEFACT"]
        if rel == "-" or rel in charted:
            continue
        m = measure(rel)
        if not m.get("present") or "runpath" not in m:
            continue
        if m["cuda_shell"] == "—" and m["cuda_systemd"] == "—":
            continue
        charted.add(rel)
        L.append(f"| `{rel}` | `{m['runpath']}` | {m['cuda_shell']} | {m['cuda_systemd']} | "
                 f"{'no — **they differ**' if m['cuda_diverges'] else 'yes'} |")
    if not charted:
        L.append("| *(nothing here links CUDA — if that is a surprise, the generator is "
                 "broken, not the box)* | | | | |")
    L += ["",
          "Binaries with no row above link no CUDA at all: `symoneural-listen` is CPU-only by",
          "design, and `symoneural-web` and `symoneural-gateway` are a Go and a Rust service.",
          "",
          "Four things follow from that table, and none of them was written down anywhere:",
          "",
          "1. **`symoneural-diffuse` is the only one that diverges, and testing it in a shell",
          "   tests the wrong thing.** Its RUNPATH pins CUDA 13.3 — the version it was compiled",
          "   against — and production, started by systemd with no `LD_LIBRARY_PATH`, gets 13.3. A",
          "   person running it from a terminal gets 13.4, because `LD_LIBRARY_PATH` outranks the",
          "   RUNPATH. `restore/manifests/BUILD-RECIPES.tsv` already warns that a restored machine",
          "   needs CUDA at that exact absolute path; this is the same fact from the other end.",
          "2. **`symoneural-llm` was built with nvcc 13.3 and links 13.4 in both environments.**",
          "   Nothing pins it: its `$ORIGIN` RUNPATH covers only the libraries beside it, and",
          "   `libcudart`/`libcublas`/`libcublasLt` come from `/etc/ld.so.conf.d/000_cuda.conf`,",
          "   which points at `/usr/local/cuda` → `/etc/alternatives/cuda` → 13.4. So",
          "   `update-alternatives --set cuda` silently changes which CUDA the chat engine links,",
          "   with no rebuild and no warning. That is worth knowing before anyone tidies up the",
          "   two CUDA installs.",
          "3. **The toolkit moved after the engines were built, and nothing recorded it.**",
          f"   `nvcc` is now `{_nvcc()}` and the driver is `{_driver()}`; the",
          f"   `/etc/alternatives/cuda` symlink that decides all of the above was last written",
          f"   `{_alt_ctime()}` and points at `{pathlib.Path('/usr/local/cuda').resolve()}`. The four",
          "   engine binaries were built before that (their dates are in the artefacts table), so",
          "   `symoneural-llm` and `symoneural-miner` are running on a CUDA minor newer than the",
          "   one they were compiled with — silently, because nothing pins them.",
          "   `symoneural-diffuse` is the one that is not, and only because its absolute RUNPATH",
          "   holds it to 13.3. `restore/manifests/` still records the older pair; regenerating",
          "   it is an eleven-minute whole-disk job and is nobody's side effect.",
          "4. **The build recipe's note about `$ORIGIN` overstates it.** It says of the llm engine",
          "   that *\"RUNPATH is $ORIGIN so every library it loads is one this build produced\"*.",
          "   True of its own 23 libraries; not true of its three CUDA libraries, which come from",
          "   the system tree. Recorded here rather than edited there — that file is generated",
          "   from `restore/lib/registry.py` and is not this section's to change.",
          ""]

    L += ["## Call sites — file and line, read now rather than stamped", "",
          "The registry stores a file and a literal fragment; the line below is found by reading",
          "the file. A pinned line number would go red on the next unrelated edit above it, and",
          "the fix would be somebody re-stamping the number.",
          "",
          "| runtime | surface | invoked at | lease taken at |", "|---|---|---|---|"]
    for r in rows:
        try:
            p, n = runtimes.resolve_site(r["CALL_SITE"], "CALL_SITE")
            call = f"`{p.relative_to(ROOT)}:{n}`"
        except runtimes.RegistryError as exc:
            call = f"**unresolved** — {exc}"
        if r["LEASE_SITE"] == "-":
            lease = "—"
        else:
            try:
                p, n = runtimes.resolve_site(r["LEASE_SITE"], "LEASE_SITE")
                lease = f"`{p.relative_to(ROOT)}:{n}`"
            except runtimes.RegistryError as exc:
                lease = f"**unresolved** — {exc}"
        L.append(f"| `{r['RUNTIME']}` | {r['SURFACE'] if r['SURFACE'] != '-' else '—'} | "
                 f"{call} | {lease} |")

    L += ["", "## Models, and whether they are on this box", "",
          "Taken from the argv the invoker builds. The two GPU engines' lists were also captured",
          "live from `/proc` while each was running, and matched.",
          "",
          "| runtime | surface | model | size |", "|---|---|---|---|"]
    for r in rows:
        for p in runtimes.models(r["RUNTIME"], r["SURFACE"]):
            rel = p.relative_to(ROOT)
            size = _human(p.stat().st_size) if p.exists() else "**ABSENT**"
            L.append(f"| `{r['RUNTIME']}` | {r['SURFACE']} | `{rel}` | {size} |")

    lh = runtimes.leaseholders()
    L += ["", "## The GPU lease", "",
          f"{len(lh)} of {len(rows)} rows acquire the card: "
          f"**{', '.join(sorted({s for _, _, s in lh}))}**.",
          "",
          "Every one of them must be known to `scripts/gpu-governor.sh` — probeable for liveness",
          "(a `surface_pattern()` arm, or `surface_live()`'s explicit `miner` case) *and*",
          "stoppable (an `evict()` arm, or `train`'s deliberate refusal to be evicted).",
          "`backend/test_runtimes_registry.py` asserts both, and that assertion exists because",
          "the two-process lease proof established the cost of getting it wrong: `drain()` with no",
          "pattern reads **every** compute context against `DRAIN_FLOOR_MIB=1024`, so a surface the",
          "governor does not recognise falls to the `*)` default and its first acquire behind a",
          "resident tenant is refused — correctly, and it presents as a lock bug.",
          "",
          "Rows with no lease are design decisions, not omissions. `symoneural-listen` stays on the",
          "CPU so a spoken sticker can transcribe while another surface holds the card;",
          "`symoneural-ravencalc` takes no lease so it can answer while the card is loading.",
          ""]

    never = [r for r in rows if r["INVOCATION"] == "never"]
    if never:
        L += ["## Runtimes nothing invokes", "",
              "A blank cell here would read as an omission. These are findings:", ""]
        for r in never:
            L.append(f"- **`{r['RUNTIME']}`** — {r['NOTE']}")
        L.append("")

    L += ["## What this map does not say, and why", "",
          "A blank cell that is not explained is indistinguishable from one nobody looked at.",
          "",
          "- **`MODELS` is `—` for `symoneural-miner`, `symoneural-ui` and `training`, and each",
          "  for a different reason.** The miner has no model file at all — kawpow generates its",
          "  DAG. ComfyUI loads whatever a submitted graph names, at request time, so there is no",
          "  fixed list to record. A training job's base model is chosen per job from the",
          "  Reinforce catalogue. Only the four rows with a fixed argv can honestly name weights.",
          "- **The live command lines were captured for two of the six leaseholders.** `chat` and",
          "  `image` were read from `/proc` while they were actually running, and they matched the",
          "  argv their invokers build. `miner`, `comfy` and `train` were not running and starting",
          "  them is a deliberate act, not a measurement — that is section 2's job. Their MODELS",
          "  and argv here are read from the call site, not from a running process.",
          "- **No build commands.** `restore/manifests/BUILD-RECIPES.tsv` is the build authority",
          "  and this registry names a `COMPONENT_ID` in it. Copying the command here would create",
          "  the second copy the whole arrangement exists to prevent;",
          "  `test_runtimes_registry.py` fails if one appears.",
          "- **`training` has no `BUILD_RECIPE`.** It is a virtualenv, not a build product, and",
          "  `restore/manifests/BUILD-RECIPES.tsv` has no row for it. Whether that venv is",
          "  rebuildable is a restore-path question and belongs to the dependency inventory.",
          "- **Nothing here says a runtime *works*.** Every cell is a fact about what is on disk",
          "  and what calls it. `exists` and `grep` cannot ask whether a thing runs — that is",
          "  exactly the gap the per-runtime tests are for.",
          ""]

    L += ["## Notes, per row", ""]
    for r in rows:
        if r["NOTE"] and r["NOTE"] != "-":
            key = f"`{r['RUNTIME']}`" + (f" / {r['SURFACE']}" if r["SURFACE"] != "-" else "")
            L.append(f"- **{key}** — {r['NOTE']}")
    L.append("")
    return "\n".join(L)


def main() -> int:
    text = render()
    if "--check" in sys.argv:
        current = OUT.read_text() if OUT.is_file() else ""
        if current == text:
            print(f"{OUT.relative_to(ROOT)} is current")
            return 0
        print(f"{OUT.relative_to(ROOT)} is STALE -- run tools/build/build_runtimes.py",
              file=sys.stderr)
        return 1
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text)
    print(f"wrote {OUT.relative_to(ROOT)} ({len(runtimes.rows())} rows)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
