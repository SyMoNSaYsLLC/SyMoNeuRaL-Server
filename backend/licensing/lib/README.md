# `backend/licensing/lib/` — Library for `licensing`

No routes. **No side effects on import** -- a module here may be imported by a test, a
tool, or another component, and one that opens a socket or reads a config file at import
time makes all three unpredictable.

Anything that needs the app, the lease or a request belongs in `../licensing.py`.

| file |  |
|---|---|
| `issue.py` | Mint and inspect SyMoNeuRaL contract keys. |

See [`../README.md`](../README.md) for what `licensing` is and why.
