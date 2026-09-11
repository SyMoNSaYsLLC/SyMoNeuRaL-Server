# backend/image/

The diffusion surface. `POST /api/image` **evicts chat**, runs `symoneural-diffuse`, and
returns a URL to a PNG under `backend/output/`.

Eviction is the whole design. Chat weights and image weights cannot both be resident in
15.92 GiB, so an image request takes the card from chat through the governor rather than
waiting for it to be free — it never would be. The governor drains VRAM below the floor
before the diffuse engine allocates, because a CUDA context that has not finished tearing
down still holds memory.

Renders are pruned to `GALLERY_KEEP`. The gallery is a cache of recent output, not storage.

**One refusal, and it is the only one.** A prompt pairing a child term with a sexual term is
denied. It requires **both** halves, so it does not fire on "a child's drawing of a raven" or
on "a naked woman" — only the intersection. It is not a taste filter; it is the one output
that is illegal to produce. Everything else renders.

<!-- generated: do not edit below -->

## Operations — 2

|  | path | what it does |
|---|---|---|
| GET | `/api/gen/{name}` | Serve a render produced by `POST /api/image`. |
| POST | `/api/image` | Render an image with FLUX.1-schnell. |

## Documents

- [`image-spec.md`](docs/image-spec.md)
- [`symoneural-image-scope.md`](docs/symoneural-image-scope.md)

<!-- end generated -->
