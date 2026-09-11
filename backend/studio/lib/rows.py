"""Lifted from server.py, 2026-09-11.

Runtime objects come off `core.context.ctx`; importing server would be a cycle.
"""
from __future__ import annotations

import streamer  # noqa: E402  -- the IPTV surface AND the Guide that filters
from streamer import guide  # noqa: E402  -- the library half: matching, clustering,
import studio  # noqa: E402  -- the local agent and the



def _studio_rows(raw: object) -> list[dict]:
    """Keep the rows that are shaped like rows, drop everything else without comment.

    A row must at least name itself; anything without a string `id` is not a model and is not
    reported as one. Absent and wrong-typed fields become `None` rather than being omitted, so
    the client decodes one stable shape whether or not the writer has caught up with this list.
    """
    if not isinstance(raw, list):
        return []
    out = []
    for row in raw:
        if not isinstance(row, dict) or not isinstance(row.get("id"), str):
            continue
        clean: dict = {}
        for key, want in _STUDIO_FIELDS.items():
            val = row.get(key)
            # `bool` is a subclass of `int` in Python, so an unguarded isinstance(True, int)
            # would let `present: true` through as a byte count.
            if want is not bool and isinstance(val, bool):
                val = None
            clean[key] = val if isinstance(val, want) else None
        out.append(clean)
    return out
