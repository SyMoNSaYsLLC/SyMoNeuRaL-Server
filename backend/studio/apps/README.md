# `backend/studio/apps/` — Programs for `studio`

Runnable, or driven by a route. **Not imported by the router** -- these may spawn a
subprocess, hold a file, or run for minutes, none of which belongs on a request path.

A program invoked by a route is invoked as a subprocess or a task, never imported and
called inline.

| file |  |
|---|---|
| `mcpframework.py` | Facade over the upstream MCP framework (fastmcp). |
| `workflows.py` | Stock workflows, in ComfyUI's prompt format, built for the weights actually on this disk. |

See [`../README.md`](../README.md) for what `studio` is and why.
