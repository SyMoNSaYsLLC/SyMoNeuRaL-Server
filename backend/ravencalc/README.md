# backend/ravencalc/

> **Write this paragraph.** What is this surface for, who calls it, and what will bite
> someone changing it? The table below is generated and cannot answer any of those.
> Delete this block when you have.

<!-- generated: do not edit below -->

## Operations — 1

|  | path | what it does |
|---|---|---|
| POST | `/api/ravencalc` | Exact symbolic mathematics. No GPU, no lock, no queue. |

## Library — no routes, no side effects on import

| file |  |
|---|---|
| `math.py` | Lifted from server.py, 2026-09-11. |
| `service.py` | RavenCalc as its own process — the split pilot. |
| `symbolic.py` | Facade over the upstream symbolic engine (sympy). |

## Programs — runnable, or driven by a route

| file |  |
|---|---|
| `ravencalc.py` | The calculus engine itself -- sympy, and nothing above it. |
| `steps.py` | Why the derivative is what it is -- the rules, in the order they fire. |

## Documents

- [`README.md`](docs/README.md)
- [`symoneural-ravencalc-scope.md`](docs/symoneural-ravencalc-scope.md)

<!-- end generated -->
