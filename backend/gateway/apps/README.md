# `backend/gateway/apps/` — Programs for `gateway`

Runnable, or driven by a route. **Not imported by the router** -- these may spawn a
subprocess, hold a file, or run for minutes, none of which belongs on a request path.

A program invoked by a route is invoked as a subprocess or a task, never imported and
called inline.

| file |  |
|---|---|
| `__main__.py` | `python3 -m apps.gateway` — read three real TRON networks and print what came back. |
| `record.py` | Turn a verified on-chain settlement into a recorded clearance. The only writer there is. |
| `verify.py` | Decide whether a settled on-chain licence covers a specific request. Fail closed, always. |

See [`../README.md`](../README.md) for what `gateway` is and why.
