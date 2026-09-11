# `backend/hardware/apps/` — Programs for `hardware`

Runnable, or driven by a route. **Not imported by the router** -- these may spawn a
subprocess, hold a file, or run for minutes, none of which belongs on a request path.

A program invoked by a route is invoked as a subprocess or a task, never imported and
called inline.

| file |  |
|---|---|
| `overclock.py` | SyMoNeuRaL Local Model Overclocking — GPU / CPU / RAM budgets for this box. |

See [`../README.md`](../README.md) for what `hardware` is and why.
