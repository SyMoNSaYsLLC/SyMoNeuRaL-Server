# `backend/voice/lib/` — Library for `voice`

No routes. **No side effects on import** -- a module here may be imported by a test, a
tool, or another component, and one that opens a socket or reads a config file at import
time makes all three unpredictable.

Anything that needs the app, the lease or a request belongs in `../voice.py`.

| file |  |
|---|---|
| `asr.py` | Speech to text: ffmpeg to 16 kHz mono, then `symoneural-listen`, then two failure checks. |
| `tts.py` | Text to speech: the half that is NOT built, written so it reports that rather than faking it. |

See [`../README.md`](../README.md) for what `voice` is and why.
