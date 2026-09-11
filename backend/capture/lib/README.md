# `backend/capture/lib/` — Library for `capture`

No routes. **No side effects on import** -- a module here may be imported by a test, a
tool, or another component, and one that opens a socket or reads a config file at import
time makes all three unpredictable.

Anything that needs the app, the lease or a request belongs in `../capture.py`.

| file |  |
|---|---|
| `store.py` | The append-only JSONL capture store. |

See [`../README.md`](../README.md) for what `capture` is and why.
