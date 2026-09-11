# backend/controlboard/

> **Write this paragraph.** What is this surface for, who calls it, and what will bite
> someone changing it? The table below is generated and cannot answer any of those.
> Delete this block when you have.

<!-- generated: do not edit below -->

## Operations — 2

|  | path | what it does |
|---|---|---|
| GET | `/api/rack/power` | Which units an operator has taken off the rack |
| POST | `/api/rack/power/{unit_id}` | Take one unit off the rack, or put it back |

## Library — no routes, no side effects on import

| file |  |
|---|---|
| `gate.py` | Lifted from server.py, 2026-09-11. |

## Documents

- [`README.md`](docs/README.md)
- [`symoneural-control-board.md`](docs/symoneural-control-board.md)
- [`symoneural-control-plane-matrix.md`](docs/symoneural-control-plane-matrix.md)

<!-- end generated -->
