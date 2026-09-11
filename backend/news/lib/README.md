# `backend/news/lib/` — Library for `news`

No routes. **No side effects on import** -- a module here may be imported by a test, a
tool, or another component, and one that opens a socket or reads a config file at import
time makes all three unpredictable.

Anything that needs the app, the lease or a request belongs in `../news.py`.

| file |  |
|---|---|
| `fetch.py` | One outbound GET, with the three limits that make it safe to run on a public box. |

See [`../README.md`](../README.md) for what `news` is and why.
