# `backend/fabric_core/lib/` — Library for `fabric_core`

No routes. **No side effects on import** -- a module here may be imported by a test, a
tool, or another component, and one that opens a socket or reads a config file at import
time makes all three unpredictable.

Anything that needs the app, the lease or a request belongs in `../fabric_core.py`.

| file |  |
|---|---|
| `expertcache.py` | Expert residency simulation: can a small VRAM cache serve a model too big for the card? |

See [`../README.md`](../README.md) for what `fabric_core` is and why.
