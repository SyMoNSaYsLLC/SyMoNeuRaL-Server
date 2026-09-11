# `backend/streamer/apps/` — Programs for `streamer`

Runnable, or driven by a route. **Not imported by the router** -- these may spawn a
subprocess, hold a file, or run for minutes, none of which belongs on a request path.

A program invoked by a route is invoked as a subprocess or a task, never imported and
called inline.

| file |  |
|---|---|
| `m3u.py` | Extended M3U parsing. Two dialects, deliberately kept apart. |

See [`../README.md`](../README.md) for what `streamer` is and why.
