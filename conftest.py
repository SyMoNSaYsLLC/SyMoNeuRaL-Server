"""Make `apps`-free component imports resolve the way production resolves them.

`backend/**` imports its siblings as top-level packages -- `from hardware.lib import gpu`,
not `from backend.hardware.lib import gpu`. That works because the running service is

    ExecStart=/usr/bin/python3 .../backend/server.py

and Python puts a script's own directory at `sys.path[0]`. So `backend/` on the path is not
a test convenience: it is the one arrangement under which the imports in this tree mean what
they say.

This file sits at the REPOSITORY root rather than inside backend/, because the tests moved
out of the source tree on 2026-09-11. pytest walks up from each test file collecting
conftest.py, so one here covers tests/ and anything else added later, and there is exactly
one place that knows about sys.path.
"""
import pathlib
import sys

BACKEND = pathlib.Path(__file__).resolve().parent / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

# vendor/ left this tree on 2026-09-11 -- 15,298 third-party SDK files that nothing
# imported. There is no longer anything here to exclude from collection.
collect_ignore_glob: list[str] = []
