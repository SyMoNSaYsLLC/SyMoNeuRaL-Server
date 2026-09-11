# `backend/ravencalc/apps/` — Programs for `ravencalc`

Runnable, or driven by a route. **Not imported by the router** -- these may spawn a
subprocess, hold a file, or run for minutes, none of which belongs on a request path.

A program invoked by a route is invoked as a subprocess or a task, never imported and
called inline.

| file |  |
|---|---|
| `ravencalc.py` | The calculus engine itself -- sympy, and nothing above it. |
| `steps.py` | Why the derivative is what it is -- the rules, in the order they fire. |

See [`../README.md`](../README.md) for what `ravencalc` is and why.
