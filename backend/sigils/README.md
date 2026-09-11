# backend/sigils/

> **Write this paragraph.** What is this surface for, who calls it, and what will bite
> someone changing it? The table below is generated and cannot answer any of those.
> Delete this block when you have.

<!-- generated: do not edit below -->

## Operations — 5

|  | path | what it does |
|---|---|---|
| POST | `/api/sigils/from-audio` | A sticker from speech: say what it should be of |
| POST | `/api/sigils/from-image` | A sticker from a picture: background removed, or re-drawn |
| GET | `/api/sigils/packs` | Themed starting prompts |
| POST | `/api/sigils/render` | Render one sticker with a transparent background |
| GET | `/api/sigils/state` | What this surface can do, and what it last did |

## Library — no routes, no side effects on import

| file |  |
|---|---|
| `cutout_worker.py` | Background removal for a photograph. **Runs inside `backend/sigils/.venv`, never |
| `listen.py` | Speech to a subject line. The audio half of SyMoNeuRaL Stickers. |
| `render.py` | Drive one render, and give the card straight back. |
| `segment.py` | The serving side of the photograph matte. Execs `cutout_worker.py` in its own venv. |
| `upload.py` | A picture in, a sticker out. The image half of SyMoNeuRaL Stickers. |

## Programs — runnable, or driven by a route

| file |  |
|---|---|
| `matte.py` | Make the fourth channel. Standard library only. |
| `png.py` | A PNG reader and writer in nothing but the standard library. |

## Documents

- [`README.md`](docs/README.md)
- [`sigils-spec.md`](docs/sigils-spec.md)
- [`symoneural-sigils-scope.md`](docs/symoneural-sigils-scope.md)

<!-- end generated -->
