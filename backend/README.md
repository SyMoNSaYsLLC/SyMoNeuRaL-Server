# backend/ — the FastAPI application

One process, one card, bound to loopback. `server.py` builds the app and mounts the
components; **every route lives in the component that owns it.**

```
server.py              builds the app, holds the shared runtime, mounts the components
core/                  shared runtime: config, context, engine, the queue, rate limits
<component>/
  <component>.py       the router. Named for the component -- never router.py
  <component>_pages.py absolute-path page routes, mounted without a prefix
  models/              request and response models
  lib/                 no routes, no side effects on import
  apps/                programs: runnable, or driven by a route
  docs/                the spec and scope for this surface
  README.md            what it is for -- prose, plus a generated route table
```

Every component README carries a generated block. Regenerate and check:

```bash
python3 tools/build/build_component_readmes.py
python3 tools/build/build_component_readmes.py --check
```

## Running it

```bash
python3 backend/server.py          # :8800, foreground
bin/symoneural-api --check         # resolve paths, start nothing
```

System interpreter. **No virtualenv in the serving path** — that is a deliberate constraint,
not an oversight. See `ENGINEERING.md`.

## The imports mean what they say because of one arrangement

`backend/**` imports its siblings as top-level packages — `from hardware.lib import gpu`, not
`from backend.hardware.lib import gpu`. That works because the service runs as

```
ExecStart=/usr/bin/python3 .../backend/server.py
```

and Python puts a script's own directory at `sys.path[0]`. So `backend/` being on the path is
not a test convenience; it is the one arrangement under which these imports resolve. The
repository-root `conftest.py` reproduces it for the suite, in exactly one place.

## The GPU is a queue, globally

One job at a time — not per-IP, not per-surface. The card cannot do two things, so the queue
is a property of the hardware, not a policy. Five components contend for it:

| surface | what it does to the card |
|---|---|
| `chat` | resident by default; evicted by image |
| `image` | evicts chat, renders, releases |
| `remix` | a client of chat, not its own tenant |
| `sigils` | spends the card; the only app router that does |
| `train` | **never evicted.** Everything queues behind it until it finishes |

`ravencalc` is CPU-only and never queues behind anything. `voice` transcribes on the CPU at
284 MiB RSS and 0 VRAM, so a spoken question is transcribed *while* a generation runs.

## Two rules worth knowing before you change anything

**Bounds are enforced here, never trusted from the client.** Out-of-range fields are clamped;
an oversized prompt hard-fails, because answering a truncation is worse than refusing it.

**There are no tokens.** No API key, no header, no `*_ENABLED` flag gates any surface on this
box, and the decision will not be reversed. `tests/structure/test_no_tokens.py` is that rule
as code — and note that it once passed for days while walking a directory that had stopped
existing, so check its walk before trusting its green.

## Config and context

`core/config.py` holds **values**, imported directly. `core/context.py` holds **live
objects**, read at call time. Reading a constant through `ctx` fails at import, because a
default argument evaluates before `configure()` has run. See `core/README.md`.

## Adding a component

1. `backend/<name>/<name>.py` with `router = APIRouter(...)`
2. `models/`, `lib/`, `apps/`, `docs/` as needed — the same four names everywhere
3. mount it in `server.py`
4. `tests/component/<name>/`
5. `python3 tools/build/build_component_readmes.py`

Prove the behaviour changed: break it on purpose, watch a test fail, then fix it. A test that
passes before and after your change tested nothing.
