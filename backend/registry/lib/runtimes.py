"""The runtime registry, read once. What runs behind each surface, and what it loads.

`ops/RUNTIMES.tsv` is the record; this is the reader, built to the same shape as
`apps/ports.py` so that a consumer needing both learns one idiom. Written 2026-09-10.

`ports.py` answers "where does this surface listen". This answers the four questions nothing
in the repository answered: **what is the runtime, what invokes it, what does it load, and
does it take the GPU lease.** Before it, the chat engine's argv lived in `api.py`, its
eviction arm in `gpu-governor.sh`, its rebuild in `restore/manifests/BUILD-RECIPES.tsv` and
its port in `ops/PORTS.tsv`, and nothing asserted that those four agreed.

## Two things this reader will not do

**It stores no measurements.** Sizes, build dates and resolved library paths are readings
that go stale on the next rebuild or `update-alternatives`, and a stale reading in a
hand-maintained file is the carried-forward figure this repository has been bitten by.
`tools/build/build_runtimes.py` measures those fresh and dates them in the generated Markdown.

**It stores no line numbers.** A call site is a file plus a literal fragment, and
`call_site()` resolves the current line by reading the file. A pinned line number would go
red on the next unrelated edit above it, and the fix would be somebody re-stamping it.

## The key is (RUNTIME, SURFACE), not RUNTIME

`symoneural-diffuse` serves `image` and `sigil` with the same binary and the same weights,
under two different governor surfaces with two different eviction arms. Collapsing that into
one row is precisely what would hide the sigil surface from the eviction logic, so
`get()` takes both and `for_runtime()` returns every row for a name.
"""
from __future__ import annotations


import functools
import pathlib


def _repo_root() -> pathlib.Path:
    here = pathlib.Path(__file__).resolve()
    for cand in (here, *here.parents):
        if (cand / "backend" / "server.py").is_file():
            return cand
    raise RuntimeError(f"repo root not found above {here}: no backend/server.py marker")


ROOT = _repo_root()
REGISTRY = ROOT / "ops" / "RUNTIMES.tsv"

FIELDS = ("RUNTIME", "KIND", "ARTEFACT", "MODELS", "INVOKED_BY", "CALL_SITE", "INVOCATION",
          "PORT", "SURFACE", "LEASE", "LEASE_SITE", "BUILD_RECIPE", "STATE", "NOTE")

#: The separator inside CALL_SITE and LEASE_SITE: `<repo-relative file>::<literal fragment>`.
SITE_SEP = "::"

#: The separator inside MODELS.
LIST_SEP = ";"

#: Where the build commands live. This file names a COMPONENT_ID and stops; duplicating the
#: command here would create the second copy the registry exists to prevent.
BUILD_RECIPES = ROOT / "restore" / "manifests" / "BUILD-RECIPES.tsv"


class RegistryError(RuntimeError):
    """The registry is unreadable or malformed. Never raised for a merely absent runtime."""


@functools.lru_cache(maxsize=1)
def rows() -> tuple[dict[str, str], ...]:
    """Every registry row, comments and blanks dropped."""
    try:
        text = REGISTRY.read_text()
    except OSError as exc:
        raise RegistryError(f"{REGISTRY} is unreadable: {exc}") from exc
    out: list[dict[str, str]] = []
    header: list[str] | None = None
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        cells = line.split("\t")
        if header is None:
            header = [c.strip() for c in cells]
            missing = [f for f in FIELDS if f not in header]
            if missing:
                raise RegistryError(f"{REGISTRY} header is missing {missing}")
            continue
        # A short row is a real error and not paddable: a missing LEASE cell would read as
        # "takes no lease", and a leaseholder with no eviction arm is refused the card the
        # first time it queues behind a resident tenant.
        if len(cells) != len(header):
            raise RegistryError(
                f"{REGISTRY}: row {cells[0]!r}/{cells[8] if len(cells) > 8 else '?'!r} has "
                f"{len(cells)} cells, header has {len(header)}. Tab-separated, every column.")
        out.append(dict(zip(header, (c.strip() for c in cells))))
    if header is None:
        raise RegistryError(f"{REGISTRY} has no header row")
    return tuple(out)


def get(runtime: str, surface: str = "-") -> dict[str, str] | None:
    """One row by its (RUNTIME, SURFACE) key, or None."""
    for r in rows():
        if r["RUNTIME"] == runtime and r["SURFACE"] == surface:
            return r
    return None


def for_runtime(runtime: str) -> tuple[dict[str, str], ...]:
    """Every row for a runtime name -- more than one where it serves two surfaces."""
    return tuple(r for r in rows() if r["RUNTIME"] == runtime)


def for_surface(surface: str) -> tuple[dict[str, str], ...]:
    """Every runtime behind a surface. `sigil` has two: the engine and the transcriber."""
    return tuple(r for r in rows() if r["SURFACE"] == surface)


def artefact(runtime: str, surface: str = "-") -> pathlib.Path | None:
    """The absolute path to what is executed, or None where the row records no artefact."""
    r = get(runtime, surface)
    if r is None or r["ARTEFACT"] == "-":
        return None
    return ROOT / r["ARTEFACT"]


def models(runtime: str, surface: str = "-") -> tuple[pathlib.Path, ...]:
    """Absolute paths to the weights this runtime is handed. Empty where it needs none."""
    r = get(runtime, surface)
    if r is None or r["MODELS"] == "-":
        return ()
    return tuple(ROOT / p for p in r["MODELS"].split(LIST_SEP) if p)


def leaseholders() -> tuple[tuple[str, str, str], ...]:
    """`(runtime, surface, governor surface)` for every row that acquires the card.

    The consumer that matters is the test asserting each of these is known to
    `scripts/gpu-governor.sh`. A leaseholder the governor does not know about falls to the
    `*)` default, gets a patternless `drain()`, and is refused the card the first time it
    queues behind a resident tenant -- which presents as a lock bug and is not one.
    """
    return tuple((r["RUNTIME"], r["SURFACE"], r["LEASE"])
                 for r in rows() if r["LEASE"] != "-")


def _split_site(value: str, field: str) -> tuple[str, str]:
    if SITE_SEP not in value:
        raise RegistryError(
            f"{field} {value!r} is not '<file>{SITE_SEP}<pattern>'. The pattern is what lets "
            f"the line number be a fresh reading instead of a stamped one.")
    path, _, pattern = value.partition(SITE_SEP)
    return path.strip(), pattern.strip()


def resolve_site(value: str, field: str = "CALL_SITE") -> tuple[pathlib.Path, int]:
    """`<file>::<pattern>` -> `(absolute path, 1-indexed line)`, read from the file now.

    Raises if the file is gone, if the pattern matches nothing, or if it matches more than
    once -- an ambiguous pattern has stopped identifying a call site even though it still
    "passes", which is the failure mode a bare `in` check would let through.
    """
    rel, pattern = _split_site(value, field)
    path = ROOT / rel
    try:
        lines = path.read_text(errors="replace").splitlines()
    except OSError as exc:
        raise RegistryError(f"{field} names {rel}, which is unreadable: {exc}") from exc
    hits = [i for i, line in enumerate(lines, 1) if pattern in line]
    if not hits:
        raise RegistryError(
            f"{field} {value!r}: no line in {rel} contains that fragment. Either the call "
            f"site moved and this registry is now wrong, or the runtime is no longer invoked.")
    if len(hits) > 1:
        raise RegistryError(
            f"{field} {value!r}: matches {len(hits)} lines in {rel} ({hits}). A pattern that "
            f"matches twice no longer names a call site; make it more specific.")
    return path, hits[0]


def call_site(runtime: str, surface: str = "-") -> str | None:
    """`<file>:<line>` as the owner asked for it -- with the line read, not stored."""
    r = get(runtime, surface)
    if r is None:
        return None
    path, line = resolve_site(r["CALL_SITE"], "CALL_SITE")
    return f"{path.relative_to(ROOT)}:{line}"


@functools.lru_cache(maxsize=1)
def build_recipe_ids() -> frozenset[str]:
    """Every COMPONENT_ID in restore/manifests/BUILD-RECIPES.tsv.

    Read rather than copied. BUILD-RECIPES.tsv is the build authority; this registry names a
    row in it and stops, so a changed build command has exactly one place to change.
    """
    try:
        text = BUILD_RECIPES.read_text()
    except OSError as exc:
        raise RegistryError(f"{BUILD_RECIPES} is unreadable: {exc}") from exc
    out: set[str] = set()
    for i, line in enumerate(text.splitlines()):
        if i == 0 or not line.strip():
            continue
        out.add(line.split("\t")[0].strip())
    return frozenset(out)


def describe() -> str:
    """One line per row, for `python3 -m apps.runtimes` and for the runbook."""
    out = [f"{'RUNTIME':<22}{'SURFACE':<11}{'KIND':<16}{'PORT':>5} {'LEASE':<8}{'STATE':<10}INVOCATION"]
    for r in rows():
        out.append(f"{r['RUNTIME']:<22}{r['SURFACE']:<11}{r['KIND']:<16}{r['PORT']:>5} "
                   f"{r['LEASE']:<8}{r['STATE']:<10}{r['INVOCATION']}")
    lh = leaseholders()
    out.append("")
    out.append(f"{len(rows())} runtime rows; {len(lh)} take the GPU lease: "
               f"{', '.join(sorted({s for _, _, s in lh}))}")
    never = [r for r in rows() if r["INVOCATION"] == "never"]
    if never:
        out.append(f"{len(never)} nothing invokes: "
                   f"{', '.join(r['RUNTIME'] for r in never)} -- a finding, not a blank cell")
    return "\n".join(out)


if __name__ == "__main__":
    print(describe())
