# `backend/cryptominer/apps/` — Programs for `cryptominer`

Runnable, or driven by a route. **Not imported by the router** -- these may spawn a
subprocess, hold a file, or run for minutes, none of which belongs on a request path.

A program invoked by a route is invoked as a subprocess or a task, never imported and
called inline.

| file |  |
|---|---|
| `__main__.py` | `python3 -m cryptominer <cmd>`, run from backend/. |

See [`../README.md`](../README.md) for what `cryptominer` is and why.
