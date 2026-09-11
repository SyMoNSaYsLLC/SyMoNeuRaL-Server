# `backend/dispatchos/lib/` — Library for `dispatchos`

No routes. **No side effects on import** -- a module here may be imported by a test, a
tool, or another component, and one that opens a socket or reads a config file at import
time makes all three unpredictable.

Anything that needs the app, the lease or a request belongs in `../dispatchos.py`.

| file |  |
|---|---|
| `ai.py` | SyMon AI for DispatchOS -- the managed assistant layer, and what it refuses to do. |
| `store.py` | DispatchOS persistence: users, bookings, the lifecycle, and the record trail. |

See [`../README.md`](../README.md) for what `dispatchos` is and why.
