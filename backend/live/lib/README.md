# `backend/live/lib/` — Library for `live`

No routes. **No side effects on import** -- a module here may be imported by a test, a
tool, or another component, and one that opens a socket or reads a config file at import
time makes all three unpredictable.

Anything that needs the app, the lease or a request belongs in `../live.py`.

| file |  |
|---|---|
| `hls.py` | The playlist directory: what OBS wrote, and which of it is live. |
| `obs.py` | The obs-websocket v5 bridge: this process is the client, and the password never leaves it. |
| `verify_bridge.py` | Prove the obs-websocket handshake works, without anybody typing or reading the password. |

See [`../README.md`](../README.md) for what `live` is and why.
