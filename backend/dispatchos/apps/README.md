# `backend/dispatchos/apps/` — Programs for `dispatchos`

Runnable, or driven by a route. **Not imported by the router** -- these may spawn a
subprocess, hold a file, or run for minutes, none of which belongs on a request path.

A program invoked by a route is invoked as a subprocess or a task, never imported and
called inline.

| file |  |
|---|---|
| `authz.py` | Route authorization classes for this application, as an explicit dependency seam. |
| `page.py` | The DispatchOS page, as one self-contained string. |
| `quotes.py` | The quote engine: the operator's own rules, applied to the operator's own jobs. |

See [`../README.md`](../README.md) for what `dispatchos` is and why.
