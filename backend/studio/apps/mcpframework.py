"""Facade over the upstream MCP framework (fastmcp).

This module is the ONLY file in the `studio` package allowed to `import fastmcp`.
Task #74 item 5, and `backend/DEPENDENCIES.md` records the verdict: the vendor name
appears in exactly one file per dependency, so the swap is a one-file change later.
MCP is a protocol with more than one server implementation, which is what makes that
verdict worth anything here.

**It deliberately does not catch `ImportError`.** `mcp_server.py` does, and turns it into
a message telling the reader to build the isolated venv -- because `fastmcp` must never be
installed into the system interpreter, which is the serving path. Catching it here as well
would either duplicate that message or swallow it; letting it propagate keeps the
diagnosis in the one place that can name the entrypoint to re-run.

So this file is trivially thin, and that is the whole of it: the point is not indirection,
it is that `grep -rn fastmcp backend/studio/*.py` returns one file.
"""
from __future__ import annotations

import fastmcp

#: The server class. Bound, not wrapped -- `mcp_server.py` decorates with `@mcp.tool`,
#: `@mcp.resource` and calls `mcp.run(transport=...)`, and a wrapper would have to
#: reimplement all three to add nothing.
FastMCP = fastmcp.FastMCP

__all__ = ["FastMCP", "version"]


def version() -> str:
    """The upstream version, for anything that reports what it is running on.

    Deliberately reads the module bound at the top of this file rather than importing
    it again inside the function. A lazy import here made the facade *look* correct
    under a test that asserts the vendor is imported: the deliberate break
    `FastMCP = object` left the nested `import fastmcp` in place, so the AST scan still
    found it and the break came back green. One import site means one import site.
    """
    return getattr(fastmcp, "__version__", "unknown")
