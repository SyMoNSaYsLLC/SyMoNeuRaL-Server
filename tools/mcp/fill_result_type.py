#!/usr/bin/env python3
"""Add the ``resultType`` field that an older MCP server omits, so a current client accepts it.

The defect
----------
MCP protocol revision 2026-07-28 made ``resultType`` mandatory on every result.
Earlier revisions had no such field, and a client talking to an earlier-revision
server applies a bridge: absent means ``"complete"``.

github-mcp-server 1.6.0 gets no benefit from that bridge, because it echoes back
whichever revision the client asked for instead of naming the one it implements.
Measured 2026-09-11 against the binary shipped in claude-desktop::

    client asks 2026-07-28  ->  server echoes 2026-07-28, omits resultType
    client asks 2025-06-18  ->  server echoes 2025-06-18, omits resultType
    client asks 2024-11-05  ->  server echoes 2024-11-05, omits resultType

So the client believes it is speaking to a 2026-07-28 server, declines to apply
the bridge, and rejects a tool list that is otherwise perfectly good::

    Invalid result for tools/list: missing required resultType

Why this shim and not a version pin
-----------------------------------
The first attempt rewrote the echoed ``protocolVersion`` down to 2025-06-18 to
re-arm the bridge. The client kept enforcing the newer rule anyway, so that fix
did not work, and it was the wrong shape besides: it made the server *claim*
less rather than *do* more. This one supplies the missing field, which is what
the bridge would have supplied anyway. The wire result is identical to what a
conforming server sends.

``"complete"`` is the correct value. The client accepts exactly two:
``"complete"``, and ``"input_required"`` for a result that is still waiting on
the caller — which requires ``inputRequests`` or ``requestState`` alongside it,
neither of which this server has any notion of. Anything else is rejected as
``UnsupportedResultType``. A result that already carries the field is left alone,
so this keeps working unchanged on the day upstream starts sending it.

Usage
-----
    fill_result_type.py -- <server-command> [args...]

Retire it when this prints nothing on a session:
    fill_result_type.py --verbose -- <server-command>
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import threading
from typing import BinaryIO

# The client accepts "complete" and "input_required". Only the former can be
# synthesised: "input_required" is a claim about pending caller input, and
# asserting it for a server that has finished its work would be a lie that the
# client would then act on.
COMPLETE = "complete"


def _forward(src: BinaryIO, dst: BinaryIO, rewrite=None) -> None:
    """Copy newline-delimited frames, optionally rewriting each.

    A frame that is not JSON, or that `rewrite` declines, is forwarded byte for
    byte. This filter must never be the reason a message fails to arrive.
    """
    try:
        for line in src:
            dst.write(rewrite(line) if rewrite else line)
            dst.flush()
    except (BrokenPipeError, ValueError):
        pass          # the far end went away; the wait() in main() reports why
    finally:
        try:
            dst.close()
        except (BrokenPipeError, ValueError):
            pass


def _fill(counter: dict, verbose: bool):
    """Return a rewriter that adds resultType to results that lack one."""

    def rewrite(line: bytes) -> bytes:
        if not line.lstrip().startswith(b"{"):
            return line
        try:
            msg = json.loads(line)
        except (ValueError, UnicodeDecodeError):
            return line
        result = msg.get("result")
        # Errors carry "error", not "result", and must not be touched.
        if not isinstance(result, dict) or "resultType" in result:
            return line
        result["resultType"] = COMPLETE
        counter["filled"] = counter.get("filled", 0) + 1
        if verbose:
            print(f"fill_result_type: id={msg.get('id')} filled resultType",
                  file=sys.stderr)
        return json.dumps(msg, separators=(",", ":")).encode() + b"\n"

    return rewrite


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--verbose", action="store_true",
                        help="report each result the shim had to repair")
    parser.add_argument("command", nargs=argparse.REMAINDER,
                        help="-- followed by the server command to wrap")
    args = parser.parse_args(argv)

    command = args.command[1:] if args.command[:1] == ["--"] else args.command
    if not command:
        parser.error("no server command given; use: fill_result_type.py -- server args")

    server = subprocess.Popen(command, stdin=subprocess.PIPE,
                              stdout=subprocess.PIPE)
    counter: dict = {}
    for src, dst, rw in (
        # Client -> server: untouched. The request is the client's business.
        (sys.stdin.buffer, server.stdin, None),
        # Server -> client: results gain the field the server forgot.
        (server.stdout, sys.stdout.buffer, _fill(counter, args.verbose)),
    ):
        threading.Thread(target=_forward, args=(src, dst, rw), daemon=True).start()

    rc = server.wait()
    if args.verbose:
        print(f"fill_result_type: repaired {counter.get('filled', 0)} result(s)",
              file=sys.stderr)
    return rc


if __name__ == "__main__":
    sys.exit(main())
