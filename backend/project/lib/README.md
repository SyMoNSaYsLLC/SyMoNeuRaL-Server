# `backend/project/lib/` — Library for `project`

No routes. **No side effects on import** -- a module here may be imported by a test, a
tool, or another component, and one that opens a socket or reads a config file at import
time makes all three unpredictable.

Anything that needs the app, the lease or a request belongs in `../project.py`.

| file |  |
|---|---|
| `store.py` | The store. SQLite via the stdlib, CPU only, and it never asks for the card. |

See [`../README.md`](../README.md) for what `project` is and why.
