# ops/gateway/ — symon-gateway

A Go service on :8000 between Caddy and FastAPI. It **validates payloads** before they can
reach anything that takes the GPU lease, and relays `/api/ws` as a real WebSocket.

```
internet -> Caddy :443 -> symon-gateway :8000 -> FastAPI :8800
```

## What it does not do

**It makes no routing decision.** It rewrites no path: `/api/dispatchos/board` arrives at
FastAPI as `/api/dispatchos/board`. FastAPI does all the routing, and a rewrite here would be
a routing decision made outside the API.

Measured 2026-09-11: it does **not** forward `/v1/*` to the language engine.
`POST /v1/chat/completions` on :8000 answers 405 with a FastAPI error body, which means it
reached FastAPI — which has no `/v1` routes. An OpenAI-compatible surface is not reachable
from outside today, and building one is new work, not wiring.

```
build.mjs            the build
setup.sh             install it
gateway.conf.example the config, with every field commented
middleware/limiter.go
contracts/           the TRON licence and settlement contracts
test_contracts.mjs
artifacts/           built output
```

`DEPLOY.md` is the procedure. `X-Forwarded-For` is load-bearing — the API keys its rate
limiter on it — and the handling is Caddy's default on purpose.
