"""Make `symoneural_dj` importable however pytest was invoked.

`apps/remix/tests/conftest.py` imports `symoneural_dj.config` directly, which works
when pytest's rootdir is this directory -- `python3 -m pytest tests` from here collects
28 passing tests. It failed for a repository-wide run: collection from `backend/`
never puts `backend/remix` on `sys.path`, so the package that sits right here
was reported as `ModuleNotFoundError: No module named 'symoneural_dj'` -- a missing
path, not missing code.

Putting this file at the package's own level fixes it for both invocations, because
pytest imports the conftest of every collected directory before the tests under it.
Prepending is deliberate: the name is first-party and must not be shadowed by an
installed distribution that happens to share it.
"""
from __future__ import annotations

import sys
from pathlib import Path

_HERE = str(next(_p for _p in Path(__file__).resolve().parents if (_p / "backend" / "server.py").is_file()))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
