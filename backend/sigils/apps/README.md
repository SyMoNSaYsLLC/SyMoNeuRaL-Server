# `backend/sigils/apps/` — Programs for `sigils`

Runnable, or driven by a route. **Not imported by the router** -- these may spawn a
subprocess, hold a file, or run for minutes, none of which belongs on a request path.

A program invoked by a route is invoked as a subprocess or a task, never imported and
called inline.

| file |  |
|---|---|
| `matte.py` | Make the fourth channel. Standard library only. |
| `png.py` | A PNG reader and writer in nothing but the standard library. |

See [`../README.md`](../README.md) for what `sigils` is and why.
