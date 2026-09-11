"""The rack, read off disk: what can be searched and what URL opens it.

The desktop search service must not carry its own copy of the surface list. This
repository has been bitten by a figure that lived in two places and disagreed, so
the twelve rows come from `backend/registry/ROSTER.md` and the ports from
`ops/PORTS.tsv` -- the same two files the rack page, the Caddyfile and the unit
template read. Add a surface to the roster and it becomes searchable with no
change here.

A row this module cannot parse raises. It does not warn and it does not skip: a
surface silently missing from search looks exactly like a surface that was never
added, and that is the failure the roster parser was written to prevent.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents
            if (p / "backend" / "server.py").is_file())
ROSTER = ROOT / "backend" / "registry" / "ROSTER.md"
PORTS = ROOT / "ops" / "PORTS.tsv"

# Every surface not marked DELEGATED answers on the monolith. Named here rather
# than hardcoded as 8800 so the port still comes from PORTS.tsv.
MONOLITH = "symoneural-api"

_ROW = re.compile(r"^\|(?P<cells>.+)\|\s*$")


@dataclass(frozen=True)
class Surface:
    """One rack row, with the URL that opens it resolved."""

    id: str
    label: str
    bus: str            # gpu | cpu | net -- shown so a result says what it costs
    href: str
    port: int

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}{self.href}"

    @property
    def haystack(self) -> str:
        """What a query is matched against. Lowercased once, here, not per query."""
        return f"{self.id} {self.label} {self.bus} {self.href}".lower()


def _rows(path: Path) -> list[list[str]]:
    """Markdown table rows as cell lists, header and separator dropped."""
    out = []
    for line in path.read_text().splitlines():
        m = _ROW.match(line.strip())
        if m is None:
            continue
        cells = [c.strip() for c in m.group("cells").split("|")]
        if cells[0] == "id" or set(cells[0]) <= {"-", ":"}:
            continue
        out.append(cells)
    return out


def ports() -> dict[str, int]:
    """service -> port, for services bound on loopback or everywhere.

    PORTS.tsv carries one row per listening port, so a service with several rows
    (Caddy has three) keeps the first. Search only ever needs a way in, and the
    first row is the one the file lists as the way in.
    """
    found: dict[str, int] = {}
    for line in PORTS.read_text().splitlines():
        if line.startswith("#") or not line.strip():
            continue
        cells = line.split("\t")
        if len(cells) < 2 or cells[0] == "SERVICE":
            continue
        service, port = cells[0].strip(), cells[1].strip()
        if not port.isdigit():
            raise ValueError(f"{PORTS}: {service!r} has a non-numeric port {port!r}")
        found.setdefault(service, int(port))
    return found


def surfaces() -> list[Surface]:
    """Every rack row, with its port resolved. Raises on a row it cannot read."""
    by_service = ports()
    if MONOLITH not in by_service:
        raise ValueError(f"{PORTS} names no {MONOLITH!r} row; nothing can be opened")

    out = []
    for cells in _rows(ROSTER):
        if len(cells) < 7:
            raise ValueError(f"{ROSTER}: row {cells!r} has {len(cells)} cells, want 7")
        sid, label, _slot, bus, href, _impl, _toggle = cells[:7]
        # A delegated surface would answer on its own port; none is delegated yet
        # (PORTS.tsv marks ravencalc `proposed`), so every row is the monolith's.
        # When one flips, look its service up here rather than assuming.
        out.append(Surface(id=sid, label=label, bus=bus, href=href,
                           port=by_service.get(f"symoneural-{sid}", by_service[MONOLITH])
                           if _delegated(sid, by_service) else by_service[MONOLITH]))
    if not out:
        raise ValueError(f"{ROSTER} parsed to zero surfaces; the format changed")
    return out


def _delegated(surface_id: str, by_service: dict[str, int]) -> bool:
    """True when PORTS.tsv marks this surface's own service DELEGATED=yes.

    Read from the file rather than assumed, because the whole point of the
    delegation column is that flipping it moves the surface off the monolith.
    """
    for line in PORTS.read_text().splitlines():
        cells = line.split("\t")
        if len(cells) >= 5 and cells[3].strip() == surface_id:
            return cells[4].strip().lower() == "yes"
    return False


def search(query: str, limit: int = 6) -> list[Surface]:
    """Surfaces matching every whitespace-separated term, best first.

    An id that starts with the query sorts above a mere substring hit, so typing
    "chat" puts SyMoNeuRaL Chat first rather than whatever else mentions chat.
    """
    terms = [t for t in query.lower().split() if t]
    if not terms:
        return []
    hits = []
    for s in surfaces():
        hay = s.haystack
        if not all(t in hay for t in terms):
            continue
        rank = 0 if s.id.startswith(terms[0]) else 1
        hits.append((rank, s.id, s))
    hits.sort()
    return [s for _rank, _id, s in hits[:limit]]
