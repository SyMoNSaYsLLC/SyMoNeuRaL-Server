# `backend/ravencalc/lib/` — Library for `ravencalc`

No routes. **No side effects on import** -- a module here may be imported by a test, a
tool, or another component, and one that opens a socket or reads a config file at import
time makes all three unpredictable.

Anything that needs the app, the lease or a request belongs in `../ravencalc.py`.

| file |  |
|---|---|
| `math.py` | Lifted from server.py, 2026-09-11. |
| `service.py` | RavenCalc as its own process — the split pilot. |
| `symbolic.py` | Facade over the upstream symbolic engine (sympy). |

See [`../README.md`](../README.md) for what `ravencalc` is and why.
