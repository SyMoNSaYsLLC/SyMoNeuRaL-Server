# SyMoNeuRaL API surface — what is public, what is local, and what the box can actually do

**Scope captured 2026-08-22.** Docs and scope only. **No implementation, no new route, no
`api.py` rewrite, no Caddy change, no deploy.**

## 1. The shape

FastAPI on loopback `:8800`, behind `symon-gateway`, behind Caddy. `ops/Caddyfile:46` records
the rule that matters: **the gateway forwards every `/api` path to FastAPI verbatim and rewrites
nothing, so `backend/server.py` still owns the path.**

| Reading, measured at `api.py:1385-1391` | |
|---|---|
| `openapi_url` | **`/openapi.json`** — live |
| `docs_url`, `redoc_url` | **`None`** — FastAPI's built-ins are off |
| `/docs` | a **custom route**, `api.py:1808`, `include_in_schema=False` |

**`/docs` being off in FastAPI does not mean documentation is off.** It is served by our own
route from **locally vendored** Swagger assets (`site/swagger-ui-bundle.js`, `site/swagger-ui.css`
— both gitignored as third-party). The reason is in the code: *"the assets are local."* A doc
saying "docs are disabled" would be wrong; a doc saying "FastAPI's default docs route is
disabled and replaced" is right.

## 2. The security rule, and it is the whole of §6 of the brief

> **`/api/*` is public. `/local/*` is local-only. Privileged tools go in `/local/*`.**

`ops/Caddyfile:50` handles `/api/*` and delegates the subtree wholesale, so **every `/api` route
is internet-facing the moment it exists** unless separately blocked. `api.py:2075` states the
consequence in one line, and `backend/apps/coder/tests/test_coder_surface.py:172` states it
again as a test: *"an `/api/coder/...` endpoint is remote file read on a public host."*

So:

- **No filesystem or raw coder tools under `/api`.** There is no `/api/coder/*` route at all, and
  a test asserts its absence — see `symoneural-coder-project-cli-scope.md` §4.
- **`/local/*` is the home for developer surfaces**, behind a peer-address check that also
  refuses proxy headers. The write endpoints for the task surface (`/local/intake`) already work
  this way.
- **New `/api` routes for model, runtime, pipeline or agent operations require an explicit
  token/gate design** — not a decision made by adding a decorator.
- **`INTAKE.md` and `GARRETT-REQUESTS.md` are mode 600 and stay that way**, which is the same
  rule one layer down.

**`X-Forwarded-For` is load-bearing**, not incidental: `api.py:505` and `:1771` key the rate
limiter on the *first* value, and Caddy's default handling was kept deliberately after being
tested (`Caddyfile:19-20`, `:60`).

## 3. The API's own description already tells the hardware truth

`api.py:1391-1396`, unchanged and worth preserving verbatim in spirit:

> *"Chat, Image and Remix all want the same GPU, and the chat and image weight sets do not both
> fit in 15.92 GiB. So exactly one holds the card at a time and the others queue. RavenCalc is
> symbolic algebra on the CPU and never queues."*

That is the single-box constraint stated where a consumer of the API will actually read it.
**This is demonstration hardware, not production capacity**, and no doc or page may imply
multi-user throughput, pricing or capacity that has not been measured.

**RavenCalc's CPU use is by design, not a fallback.** The no-CPU-fallback rule forbids silently
downgrading a *GPU* workload; RavenCalc is not one. See `BOX-REALITY-AUDIT.md` §10.4 — the
carve-out exists because a future audit reading §7 alone would mark RavenCalc as violating a
rule it is unrelated to.

## 4. Rate limits — configured is not wired

**A rate bucket that is built but never consulted is red.** The mechanism and its trap are
already documented in the code at `api.py:241-255`:

> *"`LIMITS` is built by iterating this dict, and `check_rate` returns True for any surface it
> does not find. A name absent from here is not 'unlimited by choice', it is **unmeterable**, and
> `SYMONEURAL_RATE_SIGIL` would be read by nothing."*

Current suggested buckets: `ravencalc` 240/6000 · `chat` 120/2000 · `remix` 40/600 ·
`image` 20/300 · `sigil` 20/300 · `voice` (CPU, and the only one where the queue is *not* the
real backstop).

Two rules follow:

- **Router-wide metering for app surfaces.** Sigils is the worked example: the whole
  `/api/sigils` router is throttled so `/packs` and `/state` are metered too, because a phone
  app polls those. `apps/sigils/test_sigils.py:456-475` asserts the router is mounted **with**
  `dependencies=` and that it throttles against **the right surface** — mounting it against the
  wrong one is a distinct bug the test names.
- **A limit here is a monopolisation guard, not a hardware guard.** `api.py:235-238`: on one GPU
  the queue is one job deep and rations the card by itself, so a limit only stops one address
  filling the queue. *"'off' costs capacity nothing."* Nobody should present rate limits as a
  throughput feature.

## 5. GPU governor rules for API work

- **Active generation requires a lease.** Residency is **not** active work — a resident-but-idle
  model must not be reported as holding the card.
- **No silent CPU fallback for GPU workloads.** `BOX-REALITY-AUDIT.md` §2.2 records that the code
  already has none, and it is PROD.
- **Queues and timeouts are reported honestly**, including queue-full.
- **Process-lifetime holders are special.** Miner holds the card for its whole process lifetime,
  is not preemptible, and starts and stops by hand — `symoneural-miner-scope.md` §5.
- **Streamer and Live become GPU tenants only when NVENC/GPU transcode is implemented and
  proven.** Today `live` is `bus="net"` precisely because OBS's NVENC use is *outside* the
  governor, which cannot see or evict it — writing `gpu` would advertise management that does not
  exist (`ROSTER.md`, and `symoneural-live-stack.md` §3).

## 6. Parameter and route hygiene

All parameters **clamped server-side** · generated outputs served from controlled routes with **no
path traversal** · **no stale-webroot assumptions** (open task **#86**: a page can ship to `site/`
and never reach the webroot with nothing going red) · **no unmetered route added by accident**
(§4) · rack and status read from the API, never written down (`symoneural-live-stack.md` §1).

**`RackPowerGate` makes control state real** at the API layer: raw ASGI middleware at
`api.py:1415-1486` refuses HTTP work for a powered-off unit, and `rackpower.unit_for_frame` does
the same for WebSocket frames. See `symoneural-control-board.md` §1.

**`/v1` belongs to the gateway.** No `/v1` route exists in `api.py` today, and any
OpenAI-style compatibility adapter must scope that explicitly rather than colliding. **Do not
claim OpenAI-compatible behaviour unless it is implemented** — none is today.

## 7. Not authorized

No new route · no route removed or aliased · no `/api` filesystem or coder tool · no token or
gate change · no rate-bucket change · no `ops/Caddyfile` edit · no `api.py` rewrite · no deploy.

Related: `symoneural-live-stack.md` · `symoneural-control-board.md` ·
`symoneural-coder-project-cli-scope.md` §4 · `ops/docs/GPU-GOVERNOR.md` ·
`ops/docs/BOX-REALITY-AUDIT.md`.
