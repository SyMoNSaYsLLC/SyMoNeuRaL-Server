"""The rack roster, read from `ROSTER.md`.

One parser, so that `tools/build_rack.py` and `apps/test_roster.py` are reading the same
thirteen rows off the same file instead of each carrying its own copy. `ROSTER.md` explains
why the file exists and what it is deliberately not; this module is only the reader.

It is a module and not a package member on purpose: there is no `backend/apps/__init__.py`,
so `apps` is a namespace package and `from apps import roster` has no package-level side
effects -- no rate limiters built, no GPU governor resolved, no `site/` mounted. That is what
lets a generator under `tools/` import it with one `sys.path` insert and get nothing else.
`apps/symoneuralenv.py` is the precedent.

**A malformed row raises.** It does not warn and it does not skip. A roster parser that
silently drops a line it does not understand turns the roster into a fourth disagreeing list,
which is the whole thing this file was written to stop -- and it would do it invisibly, since
the symptom is a row quietly missing from the rack rather than an error anybody sees.
"""

from __future__ import annotations

import pathlib
import re

ROSTER = pathlib.Path(__file__).resolve().parent / "ROSTER.md"

FIELDS = ("id", "label", "slot", "bus", "href", "implementation", "toggle")

# Deliberately narrow. Every one of these has a reason a looser pattern would cost us:
# an id is used as a CSS hook and a websocket key, a slot is arithmetic against the
# one-screen budget, a bus names one of exactly three real buses on this box, and an href
# is a site path -- an off-site URL on a rack row would be a link out of the product.
_ID = re.compile(r"^[a-z][a-z0-9]*$")
_SLOT = re.compile(r"^[1-9][0-9]*U$")
_BUSES = ("gpu", "cpu", "net")
_TOGGLE = {"yes": True, "no": False}

_HEADER = re.compile(r"^\|\s*id\s*\|")
_EXCLUDED_HEADING = "## What is under `backend/apps/` and is deliberately not a rack row"
_BOLD_NAME = re.compile(r"\*\*`([a-z0-9_]+)`\*\*")


class RosterError(ValueError):
    """`ROSTER.md` says something this parser will not guess at."""


def _fail(path: pathlib.Path, lineno: int, line: str, why: str) -> None:
    raise RosterError(f"{path}:{lineno}: {why}\n  {line.strip()}")


def rows(path: pathlib.Path | None = None) -> list[dict]:
    """The rack rows, in the order `build_status()` emits them.

    Each row is a dict over FIELDS with `toggle` narrowed to a bool. Order is the file's
    order and is load-bearing: it is the order the rack renders, so the fallback markup and
    the live markup agree only if this list is not sorted on the way out.

    `path` overrides the file, and exists so the tests can hand this parser a malformed
    roster and watch it raise. Nothing in the product passes it.
    """
    path = path or ROSTER
    text = path.read_text(encoding="utf-8")
    out: list[dict] = []
    seen: dict[str, int] = {}
    in_table = False
    header_at = 0

    for lineno, line in enumerate(text.splitlines(), 1):
        if not in_table:
            if _HEADER.match(line):
                in_table, header_at = True, lineno
            continue
        if not line.startswith("|"):
            break                                    # one table; the first blank line ends it
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if all(set(c) <= set("-: ") for c in cells):
            continue                                 # the markdown separator row
        if len(cells) != len(FIELDS):
            _fail(path, lineno, line, f"expected {len(FIELDS)} columns, found {len(cells)}")
        row = dict(zip(FIELDS, cells))
        if not _ID.match(row["id"]):
            _fail(path, lineno, line, f"id {row['id']!r} is not lowercase alphanumeric")
        if row["id"] in seen:
            _fail(path, lineno, line, f"id {row['id']!r} already used on line {seen[row['id']]}")
        if not _SLOT.match(row["slot"]):
            _fail(path, lineno, line, f"slot {row['slot']!r} is not a unit count like 2U")
        if row["bus"] not in _BUSES:
            _fail(path, lineno, line, f"bus {row['bus']!r} is not one of {_BUSES}")
        if not row["href"].startswith("/"):
            _fail(path, lineno, line, f"href {row['href']!r} is not a site-absolute path")
        if not row["label"]:
            _fail(path, lineno, line, "label is empty")
        if not row["implementation"]:
            _fail(path, lineno, line, "implementation is empty")
        if row["toggle"] not in _TOGGLE:
            _fail(path, lineno, line, f"toggle {row['toggle']!r} is not yes or no")
        row["toggle"] = _TOGGLE[row["toggle"]]
        seen[row["id"]] = lineno
        out.append(row)

    if not in_table:
        raise RosterError(f"{path}: no roster table found (no row starting `| id |`)")
    if not out:
        raise RosterError(f"{path}:{header_at}: the roster table has a header and no rows")
    return out


def slots(path: pathlib.Path | None = None) -> int:
    """Total rack units the roster occupies -- what the one-screen budget is spent on."""
    return sum(int(r["slot"][:-1]) for r in rows(path))


def excluded(path: pathlib.Path | None = None) -> set[str]:
    """Directories under `backend/apps/` that `ROSTER.md` says are deliberately not rows.

    Parsed rather than duplicated so a NEW directory that is neither a row nor written up in
    that section fails a test instead of sitting there ambiguous. The names are the bolded,
    backticked ones -- `**`voice`**` -- so an ordinary backticked mention in the prose around
    them is not mistaken for a declaration.
    """
    path = path or ROSTER
    text = path.read_text(encoding="utf-8")
    if _EXCLUDED_HEADING not in text:
        raise RosterError(f"{path}: the not-a-rack-row section is missing or was renamed")
    section = text.split(_EXCLUDED_HEADING, 1)[1].split("\n## ", 1)[0]
    names = {m.group(1) for m in _BOLD_NAME.finditer(section)}
    if not names:
        raise RosterError(f"{path}: the not-a-rack-row section names nothing")
    return names
