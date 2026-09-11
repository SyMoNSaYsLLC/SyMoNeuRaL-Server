# backend/core/

Shared runtime. No routes, and nothing here is a surface.

| file | what it holds |
|---|---|
| `config.py` | every path, limit and tunable. **Values**, imported directly |
| `context.py` | the live objects — `app`, `bus`, `gpu`, the locks. Late-bound |
| `engine.py` | spawning, stopping and streaming from `symoneural-llm` |
| `gpu_queue.py` | the queue in front of the lease |
| `bus.py` | what an agent announces when it does something |
| `lifespan.py` | startup and shutdown, the telemetry loop, the ASIC refresher |
| `ratelimit.py` | per-address budgets, and the one content refusal |

## config vs context — the split, and why it exists

**Values go in `config.py` and are imported.** **Runtime objects go in `context.py` and are
read at call time.** Getting this wrong produces an error that looks unrelated to its cause.

`context.py` exists to break an import cycle: a router cannot import `server`, because
`server` imports the router. So `server.configure(...)` hands it the live objects and routers
read them off `ctx`.

But a **default argument evaluates when the module loads**, which is before `configure()` has
run. Constants read through `ctx` therefore raised `AttributeError: core.context has no
'JOB_TIMEOUT_S'` at import — from a decorator, naming a constant, with nothing in the
traceback pointing at the actual mistake. Splitting values out of the context bag is what
fixed it, and `ctx.__getattr__` now raises a message that says what to do.

## The root anchor

`config.py` walks up for `server.py` rather than counting parents. Parent-counting broke on
the `demo/` flatten, the `tools/` move, the `backend/` move, and on 63 anchors at once when
every tool moved a level deeper. It fails silently, because the wrong parent usually exists.

`ROOT / "run"`, emphatically not `HERE / "run"`: `gpu-governor.sh` takes its mkdir lock
there, and two lock directories means two engines and ~12 GB onto a 16 GB card.

<!-- generated: do not edit below -->

## Operations

None. This component is a library for others, or is driven from the desktop session rather than over HTTP.

## Documents

- [`MODEL-CALL-TRACE-20260911.md`](docs/MODEL-CALL-TRACE-20260911.md)
- [`README.md`](docs/README.md)
- [`RUNTIME-EVENTS.md`](docs/RUNTIME-EVENTS.md)

<!-- end generated -->
