# `backend/sigils/lib/` — Library for `sigils`

No routes. **No side effects on import** -- a module here may be imported by a test, a
tool, or another component, and one that opens a socket or reads a config file at import
time makes all three unpredictable.

Anything that needs the app, the lease or a request belongs in `../sigils.py`.

| file |  |
|---|---|
| `cutout_worker.py` | Background removal for a photograph. **Runs inside `backend/sigils/.venv`, never |
| `listen.py` | Speech to a subject line. The audio half of SyMoNeuRaL Stickers. |
| `render.py` | Drive one render, and give the card straight back. |
| `segment.py` | The serving side of the photograph matte. Execs `cutout_worker.py` in its own venv. |
| `upload.py` | A picture in, a sticker out. The image half of SyMoNeuRaL Stickers. |

See [`../README.md`](../README.md) for what `sigils` is and why.
