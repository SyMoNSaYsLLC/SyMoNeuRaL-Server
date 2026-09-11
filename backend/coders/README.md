# backend/coders/

> **Write this paragraph.** What is this surface for, who calls it, and what will bite
> someone changing it? The table below is generated and cannot answer any of those.
> Delete this block when you have.

<!-- generated: do not edit below -->

## Operations — 7

|  | path | what it does |
|---|---|---|
| GET | `/coders` | The multi-coder page. LOCAL ONLY, like the surface it drives. |
| POST | `/local/coders/ask` | One prompt to every selected coder. Returns when they have all answered  |
| GET | `/local/coders/providers` | Measured readiness, re-read on every call. |
| GET | `/local/coders/session/{sid}` |  |
| POST | `/local/coders/session/{sid}/debate` |  |
| POST | `/local/coders/session/{sid}/decide` | Record which answer the operator chose when the coders disagreed. |
| GET | `/local/coders/sessions` |  |

## Documents

- [`README.md`](docs/README.md)
- [`coder-rotation-launcher-spec.md`](docs/coder-rotation-launcher-spec.md)

<!-- end generated -->
