# `symon-gateway`

The front-door HTTP gateway. Axum + Tokio + Reqwest, with payload validation in a Wasmtime
sandbox.

```
client ──▶ Caddy :443 (TLS, static) ──▶ symon-gateway :8000 ──▶ FastAPI :8800 ──▶ gpu-governor.sh
```

## Why it is here and not in `ops/gateway/`

**`ops/gateway/` is the blockchain licence gateway** — Solidity contracts, `gateway-cli.py`,
and the half of that system that holds a TRON signing key. `backend/apps/gateway/` is its
web-process half. Neither has anything to do with HTTP routing. Writing a Rust crate over
either would have destroyed working, key-bearing code.

"Gateway" now means three things in this repo. When you write it down, say which:

| Path | What it is |
|---|---|
| `symon-gateway/` | **this** — the HTTP front door |
| `ops/gateway/` | blockchain licensing, operator side (holds the key) |
| `backend/apps/gateway/` | blockchain licensing, web side (cannot sign anything) |

## Build and run

```bash
cd symon-gateway && cargo build --release
./target/release/symon-gateway
```

| Variable | Default | Meaning |
|---|---|---|
| `SYMON_GATEWAY_BIND` | `127.0.0.1:8000` | listen address |
| `SYMON_API_UPSTREAM` | `http://127.0.0.1:8800` | where `/api/*` goes |
| `SYMON_ENGINE_UPSTREAM` | `http://127.0.0.1:8800` | where `/v1/*` goes — see below |
| `SYMON_WASM_LIMITER` | `ops/gateway/middleware/limiter.wasm` | validator module |
| `SYMON_MAX_TOKENS` | `100000` | ceiling, estimated by whitespace |
| `SYMON_MAX_CHAT_BODY` | `8388608` | byte ceiling on `/v1/chat/completions` **only** |
| `SYMON_TRUST_FORWARDED` | `0` | set to `1` **only** when Caddy is in front — see below |
| `SYMON_LOG` / `SYMON_LOG_JSON` | `info` / unset | filter; set the second for JSON records |

### `SYMON_TRUST_FORWARDED` decides who gets rate limited

`api.py:505` and `api.py:1771` both key the rate limiter on the **first** entry of
`X-Forwarded-For`, so whichever process writes that entry decides who gets throttled.

- **`0` (default) — this process is the front door.** Any inbound `X-Forwarded-For` is
  client-supplied, so it is replaced with the peer address. Without this a client sends
  `X-Forwarded-For: <anything>` and gets a brand new rate-limit bucket per request.
- **`1` — Caddy is in front.** The first entry was written by Caddy and is the real client;
  the chain is preserved and this hop is appended.

The default is the fail-closed one: getting it wrong that way puts everyone in one shared
bucket and throttles too much, rather than removing the limiter for anyone who reads this file.

### Only one route has a body limit, on purpose

`/v1/chat/completions` is the single route that reads a body whole, because it validates
before forwarding. Everything else streams straight through with no cap, which is deliberate:
`backend/apps/voice/routes.py:43` records that every size cap on uploads was removed and that
the route reads in 64 KiB chunks so a long recording is never resident. A blanket body limit
on this process would silently undo that.

## Routes

| Route | Behaviour |
|---|---|
| `GET /healthz` | this process only — deliberately does **not** poll the upstream |
| `ANY /api`, `/api/{*path}` | forwarded verbatim to FastAPI, streamed both ways |
| `GET /api/ws` (upgrade) | **relayed as a real WebSocket** — see below |
| `POST /v1/chat/completions` | validated, then forwarded to the engine upstream |
| `ANY /v1/{*path}` | forwarded to the engine upstream |
| `GET /swagger-ui/` | Swagger UI, assets vendored into the binary |
| `GET /api-docs/openapi.json` | the OpenAPI document |

## Measured on this box, 2026-08-18

| Check | Result |
|---|---|
| `/api/status` through the gateway vs direct | **3818 B both**, same keys |
| `/api/chat` SSE through the gateway | deltas ~10 ms apart, **not batched** — passthrough confirmed |
| oversized payload (100,001 words) | **413** before anything reached the GPU |
| `/swagger-ui/` | **200**, `text/html`, vendored assets |
| GPU lock after a streamed chat | released; `run/gpu.lock.d` absent |
| graceful SIGTERM | logged `symon-gateway stopped`; `:8000` freed |
| `/api/ws` handshake | **101**, `sec-websocket-accept` correct |
| `/api/ws` protocol | `welcome` → `rack` (same 4 keys as direct) → `pong` → 4 deltas over 22 ms → `done` |
| 200 MB upload | all 209,715,200 bytes arrived; gateway RSS 23.6 → **27.4 MB** |
| 9 MB chat body | **413** at the read, before parsing |
| spoofed `X-Forwarded-For` as front door | replaced with the peer address |
| `X-Forwarded-For` with `TRUST_FORWARDED=1` | `203.0.113.7, 127.0.0.1` — chain kept, hop appended |

## The WebSocket relay, and why it is not `reqwest`

`backend/server.py:1697` serves `/api/ws`, and `console.js` falls back to polling if it cannot
open it. That fallback is the exact regression that got Apache dropped for Caddy:
`mod_proxy_wstunnel` was never enabled, so the rack's "pushed live over one socket" claim
degraded to polling while still being displayed.

**The first version of this gateway rebuilt that bug**, and it is worth recording how quietly.
`Connection` and `Upgrade` are hop-by-hop headers (RFC 9110 §7.6.1) and are correctly stripped
by the proxy, so the request reached FastAPI as an ordinary GET, missed the WebSocket route,
and came back **404** — which reads like a missing upstream route, not a broken proxy. Even
unstripped it could not have worked: reqwest returns a response body stream and never surfaces
the upgraded socket underneath.

So `ws.rs` is two WebSocket endpoints glued together — axum's server-side upgrade facing the
client, `tokio-tungstenite` facing FastAPI — with a task pumping frames each way. Both
directions run concurrently, because `/api/ws` is not request/response: the API pushes `rack`
frames unprompted while the client sends `chat` frames, so a half-duplex relay would stall the
rack the moment a chat started.

Test it the way `.claude/CLAUDE.md` specifies (`curl --http1.1`, read the status line from
`-D`) — but note that a 101 alone proves very little. A handshake that upgrades and then
delivers nothing is indistinguishable from a working proxy at that level. Assert on the
protocol: `welcome`, the seeded `rack` snapshot, a ping/pong round trip, and chat deltas
arriving spread out in time rather than batched at the end.

## Two things that are NOT done, and you should know before trusting this

### 1. There is no `/v1/chat/completions` upstream to forward to

`SYMON_ENGINE_UPSTREAM` defaults to the FastAPI control plane, which has **no OpenAI-compatible
surface**. `POST /v1/chat/completions` therefore currently returns **405** — that is FastAPI's
static mount answering, not a route.

The reason it cannot simply point at llama.cpp is the important part. On this machine
`llama-server` is **not a service**: `backend/server.py:113` spawns it as a child process per job,
while holding the mutex in `scripts/gpu-governor.sh`. Nothing listens on :8080 or :9001 between
jobs. A gateway forwarding straight to :8080 would connect to nothing most of the time, and
when it did connect it would be using the GPU **without the lock** — which `.claude/CLAUDE.md`
forbids outright, and which would contend with a QLoRA run for VRAM that cannot be shared.

The fix is a `/v1/chat/completions` route in `backend/server.py` that wraps the existing governed
chat path in the OpenAI response shape. The governor is Python's; the gateway should not learn
to take the lock.

### 2. The WASM validator is not compiled

Go is not installed here, so `ops/gateway/middleware/limiter.wasm` does not exist. The gateway loads it
if present and otherwise enforces the same ceiling natively, reporting
`"validator": "native-fallback"` on `/healthz` rather than quietly appearing to be sandboxed.

Build it with **`GOOS=wasip1`**, not `GOOS=js`:

```bash
GOOS=wasip1 GOARCH=wasm go build -o ops/gateway/middleware/limiter.wasm ./ops/middleware
```

`GOOS=js GOARCH=wasm` emits a module that imports the `gojs` namespace and expects
`wasm_exec.js`; Wasmtime has no JavaScript to give it, so that build fails at *instantiation*
with unknown-import errors rather than at build time. `//go:wasmexport` also needs **Go 1.24+**.

## The open topology question

Whether Caddy stays in front of this or is replaced by it is **not decided**, and nothing here
assumes either answer. Replacing Caddy means this process takes on:

- **ACME/TLS** with automatic renewal (Caddy does this with no configuration and no cron),
- **static file serving** from `/var/www/symoneural`,
- ~~the WebSocket upgrade on `/api/ws`~~ — **done**, see the relay section above. This was the
  easiest of the three to miss and the only one that fails silently, so it was built first.

The two that remain are the reason Caddy is still in front. Neither is hard in isolation;
together they are a working web server, and there is a working web server here already.

Until that is settled, the safe deployment is Caddy in front, which is also the only shape that
does not risk the live site.
