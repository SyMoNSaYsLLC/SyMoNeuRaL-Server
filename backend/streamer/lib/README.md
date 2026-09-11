# `backend/streamer/lib/` — Library for `streamer`

No routes. **No side effects on import** -- a module here may be imported by a test, a
tool, or another component, and one that opens a socket or reads a config file at import
time makes all three unpredictable.

Anything that needs the app, the lease or a request belongs in `../streamer.py`.

| file |  |
|---|---|
| `epg.py` | Electronic programme guide for the Streamer. Two sources, one shape out. |
| `safefetch.py` | The one door out. Every outbound byte caused by a visitor-supplied URL goes through here. |
| `sessions.py` | Tuning sessions: one upstream stream, one ffmpeg, a bounded number of both. |
| `xtream.py` | Xtream Codes panel client. Protocol only -- no credential outlives the request. |

See [`../README.md`](../README.md) for what `streamer` is and why.
