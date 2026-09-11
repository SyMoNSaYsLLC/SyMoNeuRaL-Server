# API wiring verification — 2026-08-26

**Result: `API WIRING VERIFIED`. Nothing in production was changed, because nothing in
production was broken.** 27 endpoints probed at four layers, 0 failing layers.

The trigger was a report of 25 broken endpoints. All 25 are registered and reachable. The
report was produced by a bad test, and the rest of this file is mostly about *why the bad
test looked so convincing*, because that is the part worth keeping.

Re-run the evidence:

```bash
cd backend
python3 -m apps.route_matrix              # the real 146-route table, read from the router
python3 -m apps.route_matrix --classify   # the 25 reported endpoints against it
python3 -m apps.layer_probe               # the four-layer matrix; exit 0 means clean
```

## 1. Root cause

**This application can never return `405`, so a GET-only sweep cannot tell a POST route from
a route that does not exist.**

`backend/api.py` ends its route table with `Mount('', StaticFiles(...))` — route index 145 of
146, matching every path there is. Starlette resolves in order:

1. `GET /api/chat` reaches the `POST /api/chat` route, which returns a **partial** match
   (path yes, method no). A partial match does not stop the walk.
2. The walk continues to the catch-all mount, which returns a **full** match.
3. `StaticFiles` looks for a file called `api/chat`, finds none, and raises **404**.

So `GET /api/chat` and `GET /api/there-is-no-such-route` produce byte-identical responses.
The original sweep sent GET to 25 mostly-POST endpoints, collected 25 identical 404s, and
reported them as 25 broken endpoints. The measurement was real; the interpretation was not.

This is a property of the app's shape, not a defect — the catch-all mount is how the static
site is served — but it means **405-based route probing is invalid here** and any future
harness that relies on it will produce the same false alarm.

## 2. Files and configuration changed

**None in production.** No application code, no unit file, no Caddyfile, no gateway config.

Two new files, both test harness, neither imported by the running application
(`api.py` includes its routers explicitly — there is no `pkgutil`/`walk_packages`
auto-discovery of `apps/*`, which was checked before adding them):

| File | What it is |
|---|---|
| `backend/apps/route_matrix.py` | Reads the real route table off `app.routes`, including WebSocket and `include_in_schema=False` routes that `openapi.json` omits. Classifies a reported endpoint list against it. |
| `backend/apps/layer_probe.py` | Probes each endpoint at :8800, :8000 and public with its real method, and names the first layer whose answer is not the one that row expects. |

## 3. Processes restarted or reloaded

**None.** `symoneural-api` has been up continuously since 15:52:08 EDT; `symoneural-web`,
`symoneural-gateway` and `symoneural-ui` were not touched. There was nothing to restart.

## 4. Before/after hashes

**Not applicable — no file was modified.** The two files in §2 are new, and their hashes are
recorded here as their creation state rather than as a change:

```
sha256  backend/apps/route_matrix.py   bbbad3a39bc4f11a8240ce4d679044c61f1ddac30ea6e8c46057ce901c54a32c
sha256  backend/apps/layer_probe.py    a4c1fde43d1c2bf5ff94c89a53d60a084227612b46a469540fba6ad062b70909
```

## 5. Route registry — the 25 reported endpoints

Read from the running router. **Not one is `NOT REGISTERED`.**

| Verdict | Count | Which |
|---|---|---|
| `REGISTERED EXACTLY` | 17 | the endpoints that really are endpoints |
| `REGISTERED UNDER DIFFERENT PATH` | 7 | `/api/accounts`, `/api/exp`, `/api/sigils`, `/api/streamer`, `/api/streamer/session`, `/api/studio`, `/api/train` |
| `WEBSOCKET` | 1 | `/api/ws` |
| `NOT REGISTERED` | **0** | — |

The 7 "different path" entries are **namespace roots that were never endpoints**. No router
ever declared `/api/sigils`; it declares `/api/sigils/packs`, `/api/sigils/render`,
`/api/sigils/state`, `/api/sigils/from-audio`, `/api/sigils/from-image`. The report guessed a
collection root that does not exist and counted its absence as a broken feature. Each is
probed below at a real registered read inside the same namespace, because a path no router
declared can only 404 at every layer and would otherwise show as a fake three-layer failure.

`/api/streamer/session` is the same shape with a twist: the route is `/{sid}`, so it is probed
with a made-up session id. The handler **refusing** that id is the proof it was reached.

## 6. The four-layer route matrix

Probe kinds, and why each is safe:

- **`validate`** — real method, body `"__routing_probe__"` (a bare JSON string). Every route
  probed this way was confirmed against the running server's own `openapi.json` to declare
  `requestBody.required: true`, so Pydantic rejects a non-object **before the handler is
  entered**. `422` proves the route resolved and proves nothing ran. This is what keeps
  `/api/gpuminer/control`, `/api/asicminer/scan` and `/api/streamer/tune` honest without
  starting a miner, a network scan, or tuning physical hardware.
- **`authwall`** — real method, no credentials, for the two POST routes that declare no body.
- **`exercise`** — real method, for genuine reads and pure functions.
- **`websocket`** — a real handshake. An ordinary GET cannot test this: it never computes
  `Sec-WebSocket-Accept`, so a correct server rejecting it looks exactly like a broken route.

`OPTIONS` is never used at any layer: the gateway links `tower-http` with the `cors` feature,
so an OPTIONS can be answered at :8000 and never reach FastAPI — a 200 that proves nothing.

| Method | Reported endpoint | Probe | :8800 | :8000 | Public | First failing layer |
|---|---|---|---:|---:|---:|---|
| GET | `/api/accounts` | exercise | 200 | 200 | 200 | NONE |
| GET | `/api/exp` | exercise | 200 | 200 | 200 | NONE |
| GET | `/api/sigils` | exercise | 200 | 200 | 200 | NONE |
| GET | `/api/streamer` | exercise | 200 | 200 | 200 | NONE |
| GET | `/api/studio` | exercise | 200 | 200 | 200 | NONE |
| GET | `/api/train` | exercise | 503 | 503 | 503 | NONE |
| GET | `/api/streamer/session` | exercise | 404 | 404 | 404 | NONE |
| POST | `/api/accounts/logout` | authwall | 204 | 204 | 204 | NONE |
| POST | `/api/accounts/password` | validate | 422 | 422 | 422 | NONE |
| POST | `/api/accounts/signout-everywhere` | authwall | 503 | 503 | 503 | NONE |
| POST | `/api/asicminer/emulator` | validate | 422 | 422 | 422 | NONE |
| POST | `/api/asicminer/scan` | validate | 422 | 422 | 422 | NONE |
| POST | `/api/gpuminer/control` | validate | 422 | 422 | 422 | NONE |
| POST | `/api/image` | validate | 422 | 422 | 422 | NONE |
| POST | `/api/remix` | validate | 422 | 422 | 422 | NONE |
| POST | `/api/streamer/epg` | validate | 422 | 422 | 422 | NONE |
| POST | `/api/streamer/guide/filter` | validate | 422 | 422 | 422 | NONE |
| POST | `/api/streamer/playlist` | validate | 422 | 422 | 422 | NONE |
| POST | `/api/streamer/tune` | validate | 422 | 422 | 422 | NONE |
| POST | `/api/streamer/xtream/channels` | validate | 422 | 422 | 422 | NONE |
| GET | `/api/rack/power` | exercise | 404 | 404 | 404 | NONE |
| POST | `/api/chat` | exercise | 200 | 200 | 200 | NONE |
| POST | `/api/ravencalc` | exercise | 200 | 200 | 200 | NONE |
| WS | `/api/ws` | websocket | **101** | **101** | **101** | NONE |
| GET | `/local/coder` | exercise | 200 | 404 | 404 | NONE (local-only, enforced) |
| GET | `/api/status` | exercise | 200 | 200 | 200 | NONE |
| GET | `/demo/dispatchos` | exercise | 200 | 404 | **401** | NONE (auth at the web layer) |

**Negative control.** A clean matrix proves nothing unless the harness can fail, so an
undeclared path was run through it: `/api/there-is-no-such-route` returned `404 / 404 / 404`
and was correctly flagged `symoneural-api :8800 (got 404, expected 200)`.

### The harness was wrong three more times, and each is recorded rather than quietly fixed

The first run of `layer_probe.py` flagged three rows. All three were the harness, not the box:

1. **`/api/accounts/signout-everywhere` expected 401, got 503.** Accounts fail **closed**:
   `apps/accounts/__init__.py:264` requires both `SYMONEURAL_ACCOUNTS_ENABLED=1` and a
   session secret, and `symoneural-api.service` sets neither. 503 is correct and is reached
   before any session could be revoked.

   **Read that row as the whole feature, not one endpoint: accounts are switched OFF on this
   box.** The other two accounts rows look healthier than they are. `/api/accounts/status`
   returns 200 *because* it reports the disabled state — it never calls `_require_enabled()`.
   `logout` returning 204 is a no-op on a caller who has no session. So `200 / 204 / 422`
   across those three rows means **the namespace routes correctly through all three layers**,
   and nothing more; login does not work, because it is not turned on. That is a fact about
   the box's configuration, not a routing defect, and turning it on is outside this task.
2. **`/local/coder` and `/demo/dispatchos` expected the gateway to answer.** It should not.
   `ops/Caddyfile` sends only `/api/*`, `/v1/*`, `/swagger-ui*` and `/api-docs/*` to :8000.
   Expectations are now per-layer.

That is the same class of error as the original report — assuming a uniform namespace and
reading the resulting 404 as a fault — which is why it is written down here instead of edited
away.

## 7. Remaining genuine 404s, and why each is correct

There are four. **None is a routing defect and none should be "fixed".**

| Path | 404 at | Why it is correct |
|---|---|---|
| `/api/rack/power` | all three | Deliberate. `apps/controlboard/routes.py:66` returns *absent, not forbidden* when the feature is switched off — the surface refuses to reveal that the switch exists. It is registered as GET in the running `openapi.json`. |
| `/api/streamer/session/<made-up-id>` | all three | The handler was reached and refused an unknown session id. That is the route working. |
| `/local/coder/*` | :8000 and public | **Security boundary.** `ops/Caddyfile` gives `/local/*` no matcher at all; its own comment says a `handle /local*` block there *"would put that on the public internet in one line."* It is 200 on the loopback API, where it belongs. Not weakened. |
| `/demo/dispatchos` | :8000 only | Not in the gateway's namespace by design — `ops/Caddyfile` proxies it straight to :8800 behind basic auth. Public correctly answers 401. |

## 8. Chat

Real inference through public HTTPS, streamed:

```
POST https://symoneural.com/api/chat  {"prompt":"Reply with the single word: online","max_tokens":8}
data: {"delta": "Online"} …
data: {"done": true, "tokens": 8, "seconds": 0.09, "tok_per_s": 84.7,
       "model": "symon-1.0-7b-q4_k_m", "adapter": true}
```

## 9. Image

Route verified without spending the card, per instruction: `422` at all three layers is
FastAPI rejecting the probe body before `api.image` is entered, which proves the route
resolves and proves no render was started.

The handler's own readiness was then checked directly — these are the exact conditions its
`503 "Image surface is still warming up"` branch tests, and all five are true, so that branch
cannot fire:

```
FLUX[unet] symoneural-image-unet-q4_k.gguf        present
FLUX[vae]  symoneural-image-vae.safetensors       present
FLUX[clip] symoneural-image-clip.safetensors      present
FLUX[t5]   symoneural-image-t5-q8_0.gguf          present
engines/symoneural-diffuse/build/bin/symoneural-diffuse  present
```

**No image was generated.** A real render evicts the chat weights from the card, and the
instruction asked for the handler to be reached without generating one unnecessarily.

## 10. WebSocket

`/api/ws` completed a real handshake and returned **`101 Switching Protocols` at all three
layers** — loopback API, gateway, and public `wss://`. The gateway carries the upgrade, which
is the thing `Cargo.toml`'s `ws` feature exists for.

## 11. DispatchOS

Reachable and gated. `200` on the loopback API, `401` in public — `symoneural-web` holds the
basic-auth gate for `/demo/dispatchos` and `/demo/dispatchos/*`, with four accounts
configured (donnie, garrett, ben, and a preview test account; credentials not reproduced
here). An anonymous caller is refused before the page is ever served, which is the required
behaviour for a customer URL that is about to be emailed out.

## 12. Public surface

All 19 pages `200`; `/` redirects `302` to `/overview`; `/demo/dispatchos` `401`.

```
symoneural-web        active    owns :80 and :443
symoneural-gateway    active    :8000
symoneural-api        active    :8800, up since 15:52:08 EDT
symoneural-deploy     active    (exited — correct for a oneshot)
caddy                 inactive  retired
```
