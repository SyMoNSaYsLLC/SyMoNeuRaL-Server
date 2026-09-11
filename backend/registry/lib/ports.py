"""The port registry, read once. Nothing in this repository hardcodes a surface port.

`ops/PORTS.tsv` is the record; this is the reader. Four consumers use it — the API, each
split surface process, the unit template's env file, and `tools/lib/smoke.py` — and the whole
point is that adding a surface edits one file.

Written 2026-09-10 for the RavenCalc pilot. Before it, `:8800` appeared as a literal in
`api.py`, `ops/Caddyfile`, `tools/lib/smoke.py` and the unit, and the split would have added
nine more ports to each of those.

## The one safety rule in here

`delegated(surface)` returns True only when the registry marks the surface delegated **and**
gives it a port. A row that says `DELEGATED yes` with no port is a configuration error, not
an instruction: honouring it would make `backend/server.py` drop the inline route while nothing
else answered, taking the surface down with a 404 that looks like a routing bug. So the
reader refuses it and says so.
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
REGISTRY = ROOT / "ops" / "PORTS.tsv"

#: Overridable for tests and for running a scratch instance beside production. A comma list
#: of surface ids, e.g. SYMONEURAL_DELEGATE=ravencalc. It can only ever ADD delegation for a
#: surface the registry already gives a port, for the reason in the module docstring.
DELEGATE_ENV = "SYMONEURAL_DELEGATE"

FIELDS = ("SERVICE", "PORT", "BIND", "SURFACE", "DELEGATED", "STATE", "NOTE")


class RegistryError(RuntimeError):
    """The registry is unreadable or malformed. Never raised for a merely absent surface."""


@functools.lru_cache(maxsize=1)
def rows() -> tuple[dict[str, str], ...]:
    """Every registry row, comments and blanks dropped. Cached: this is read per request."""
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
        # A short row is a real error and not paddable: a missing DELEGATED cell would read
        # as falsy and silently un-delegate a surface.
        if len(cells) != len(header):
            raise RegistryError(
                f"{REGISTRY}: row {cells[0]!r} has {len(cells)} cells, header has "
                f"{len(header)}. Tab-separated, and every column present.")
        out.append(dict(zip(header, (c.strip() for c in cells))))
    if header is None:
        raise RegistryError(f"{REGISTRY} has no header row")
    return tuple(out)


def _env_delegated() -> set[str]:
    import os
    raw = os.environ.get(DELEGATE_ENV, "")
    return {s.strip() for s in raw.split(",") if s.strip()}


def port_of(surface: str) -> int | None:
    """The port a surface's own process listens on, or None if it has no row."""
    for r in rows():
        if r["SURFACE"] == surface:
            try:
                return int(r["PORT"])
            except ValueError:
                raise RegistryError(
                    f"{REGISTRY}: surface {surface!r} has PORT {r['PORT']!r}, not a number")
    return None


def base_url(surface: str) -> str | None:
    """`http://<bind>:<port>` for a surface, or None. Loopback binds stay loopback."""
    for r in rows():
        if r["SURFACE"] == surface:
            bind = r["BIND"] if r["BIND"] not in ("0.0.0.0", "*", "-") else "127.0.0.1"
            return f"http://{bind}:{r['PORT']}"
    return None


def delegated(surface: str) -> bool:
    """Does a separate process own this surface?

    True only if it is marked delegated (registry or env) **and** has a port. See the module
    docstring for why the port is a precondition rather than a detail.
    """
    marked = surface in _env_delegated()
    if not marked:
        for r in rows():
            if r["SURFACE"] == surface and r["DELEGATED"].lower() in ("yes", "true", "1"):
                marked = True
                break
    if not marked:
        return False
    if port_of(surface) is None:
        raise RegistryError(
            f"surface {surface!r} is marked delegated but has no PORT in {REGISTRY}. "
            "Refusing: the monolith would drop its inline route while nothing answered, "
            "and the surface would 404 as if it were a routing bug.")
    return True


def delegated_surfaces() -> tuple[str, ...]:
    """Every surface a separate process owns. Sorted, so callers are deterministic."""
    seen = {r["SURFACE"] for r in rows() if r["SURFACE"] != "-"} | _env_delegated()
    return tuple(sorted(s for s in seen if delegated(s)))


def describe() -> str:
    """One line per row, for `python3 -m apps.ports` and for the runbook."""
    out = [f"{'SERVICE':<24}{'PORT':>6} {'BIND':<12}{'SURFACE':<12}{'DEL':<5}STATE"]
    for r in rows():
        out.append(f"{r['SERVICE']:<24}{r['PORT']:>6} {r['BIND']:<12}{r['SURFACE']:<12}"
                   f"{r['DELEGATED']:<5}{r['STATE']}")
    d = delegated_surfaces()
    out.append("")
    out.append(f"delegated surfaces: {', '.join(d) if d else '(none -- the monolith answers everything)'}")
    return "\n".join(out)


if __name__ == "__main__":
    print(describe())
