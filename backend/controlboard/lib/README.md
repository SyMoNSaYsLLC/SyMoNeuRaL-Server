# `backend/controlboard/lib/` — Library for `controlboard`

No routes. **No side effects on import** -- a module here may be imported by a test, a
tool, or another component, and one that opens a socket or reads a config file at import
time makes all three unpredictable.

Anything that needs the app, the lease or a request belongs in `../controlboard.py`.

| file |  |
|---|---|
| `gate.py` | Lifted from server.py, 2026-09-11. |

See [`../README.md`](../README.md) for what `controlboard` is and why.
