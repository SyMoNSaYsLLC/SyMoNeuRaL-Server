# SyMoNeuRaL Security Audit Gate

**Opened 2026-08-22.** Docs and findings only. **No gate changed, no secret read, no secret
rotated, no route added or removed by this document.**

**Classification: PROD direction — required before any commercial or public privileged mode.
AUDIT until complete.**

> **Commercial mode stays disabled until every BLOCKER and HIGH is closed or explicitly
> owner-accepted.** `ops/backend/authority/docs/symoneural-commercial-mode.md` holds the switch; this file holds
> the gate on it.

**No secret value appears in this file.** Token *names* are inventoried; values are not read.
`.claude/CLAUDE.md`'s R-174 rule applies throughout: **do not read a whole process environment to
answer a narrow question**, and never read `/proc/<pid>/environ` — a rotation confirmed that way
puts the new secret in a transcript exactly as the old one got there.

---

## Findings, most severe first

### BLOCKER-1 — Task #88, executed as written, puts ComfyUI's editor on the public internet

**Three facts that are each individually fine and together are not.**

1. **`ops/Caddyfile:150` delegates `/studio` and `/studio/*` to the API.**
   `@studio path /studio /studio/*` → `reverse_proxy 127.0.0.1:8800`. So the whole `/studio`
   subtree is internet-facing, not only `/api`.
2. **`/studio/editor/*` is a same-origin reverse proxy in front of ComfyUI's own editor**
   (`apps/studio/routes.py:7`). Its catch-all handler at `:878` forwards **GET, POST, PUT, PATCH,
   DELETE, HEAD, OPTIONS** to `127.0.0.1:8188`, plus a WebSocket at `:823`. `ui_router` is a bare
   `APIRouter()` with **no `dependencies=`**.
3. **The only thing standing in front of it is `_guard`** (`:90-101`) — 503 when the surface is
   off, **401 when the token is wrong.**

**Open task `◻ #88` asks for exactly that gate to be removed**, and not only for Studio. R-162:
*"symoneural studio does not need to require SYM_STUDIO_TOKEN we are testing everything without
keys and tokens."* (His `SYM_STUDIO_TOKEN` is the pre-rename spelling; the variable is
`SYMONEURAL_STUDIO_TOKEN` today. Both are written here on purpose — `apps/test_credential_header.py`
has a tripwire that fails any file naming a legacy `SYM_*` variable without its modern spelling, and
it caught this quote.) The task text itself notes the scope: *"Standing, not Studio-only: everything,
while testing"*, and that *"the same double gate sits on Reinforce, Exp, Miner, ASIC and
Discovery."*

**Consequence if `_guard` stops requiring a token:** an unauthenticated internet visitor reaches
ComfyUI's full editor API — queue renders, read and write userdata, and use whatever file and
model browsing that API offers — on a box whose GPU is shared with every other surface. The prompt
interception at `_intercept_prompt` protects the **GPU lease**, not access control.

**This is a real conflict between an authorized task and a security boundary, and nothing
currently connects them.** #88's complaint is legitimate — Garrett cannot use his own surfaces
without exporting a secret first. The resolution is a design decision and it is his:

- **(a) loopback-only instead of token-only.** Drop the token for local peers and keep the surface
  refused off-box, reusing `_require_local`'s shape (see MEDIUM-1). Satisfies the complaint with no
  public exposure.
- **(b) exclude `/studio/editor/*` from the token drop.** #88 applies to product surfaces; the raw
  vendor editor keeps its gate.
- **(c) remove Caddy's `/studio/*` delegation** while testing, so the subtree is not reachable off
  the box at all.
- **(d) accept the exposure explicitly**, in writing, with a date.

### CHOSEN AND IMPLEMENTED 2026-08-22 — (a), narrowed to a local-only token bypass

**Garrett chose:** keep `/studio/editor/*` token-gated for any public or non-loopback access, and
add an explicit owner/local bypass for loopback only. **The public gate is not removed.**

**The invariant, and it is the whole design:**

> **The bypass drops the SECRET. It never drops the SWITCH.**

`gate.local_bypass(peer, headers)` returns true only when **all three** hold:

1. `SYMONEURAL_STUDIO_LOCAL_BYPASS == "1"` — **absent means off, which is the default**
2. `gate.switched_on()` — Studio is still deliberately switched on
3. `gate.local_request(peer, headers)` — peer in `LOCAL_PEERS` **and** no proxy header present

**Why `switched_on()` and not `enabled()`.** `enabled()` is two conditions wearing one name — the
switch **and** a non-empty token — so calling it in the bypass would have left the friction exactly
where it was: the operator would still have to invent a secret to get past it. `switched_on()` was
factored out for this, so the code states the invariant instead of hiding it in a string compare.
**A switched-off Studio therefore denies every caller, local or not, bypass flag or not.**

**Why the proxy-header check is not optional.** `ops/Caddyfile` sets `X-Forwarded-For` on everything
it proxies, so a request that crossed the reverse proxy can present a loopback socket. The peer
check alone would wave exactly that through — which is the case a future `handle /studio*` change
would produce. `local_request` requires both, copied in shape from `api.py::_require_local`, the
strictest local test in the repo. **Duplicated rather than imported, because `api.py` imports this
package and the dependency would be a cycle** — and two hand-maintained copies each with a test beat
one copy a refactor can widen for both at once.

**Applied at three call sites, all in `apps/studio/routes.py`:** `_guard` (every `/api/studio/*` and
`/studio/editor/*` HTTP path), the `/api/studio/events` WebSocket, and the `/studio/editor/ws`
WebSocket. In each, the bypass is consulted **first** and can only return early — every line below
it is unchanged, so the public path meets the same `enabled()` + `token_ok()` pair it met before.

**Blast radius: Studio only.** The flag is spelled `SYMONEURAL_STUDIO_LOCAL_BYPASS`. **No token
variable was removed and no tokens were collapsed** — Miner, ASIC, Project, Coder, Exp, Reinforce
and Discovery keep their own `_ENABLED`/`_TOKEN` pairs untouched, which matters because BLOCKER-2
records that the risk type differs per surface.

**Proven by sabotage, not by assertion.** Two deliberate breakages were made and the right tests
failed each time:

| Sabotage | Test that caught it |
|---|---|
| removed the `switched_on()` guard (making it a master allow switch) | `test_disabled_studio_refuses_even_with_the_bypass_flag` — and **only** that one |
| removed the proxy-header rejection | `test_a_loopback_peer_carrying_proxy_headers_is_refused` **and** `test_local_request_is_two_conditions_and_needs_both` |

`StudioLocalBypassTests` in `apps/studio/test_studio.py` carries eleven cases. **402 passed** across
`apps/studio/`.

### What this does and does not close

**BLOCKER-1 is reduced, not closed.** What it was about — *task #88 executed literally* — is now
prevented: the naive token removal is no longer the path, and #88's checks were rewritten to match
the decision so it cannot be greened by dropping the gate.

**What remains open is HIGH-1**, and it is the more durable half: `/studio/editor/*` still proxies
ComfyUI's own editor to authenticated operators over a public hostname. The bypass does not touch
that. **#103 records the ordering that closes it** — *"#88 comes AFTER the raw editor is gone"* — and
that ordering still stands. This implementation is what makes the wait affordable, not a substitute
for it.

**Caddy was not changed.** `/studio` and `/studio/*` are still delegated; the risk is documented, not
altered.

### BLOCKER-2 — the same task would expose rig control and the network scanner

`/api/*` is public (`Caddyfile:50`), and these are public-prefix routes today, protected only by
their own token gates:

`POST /api/gpuminer/control` · `POST /api/asicminer/scan` · `POST /api/asicminer/emulator` ·
`GET /api/asicminer/firmware`

`apps/asicminer/__init__.py:29,40` states the reason those gates exist: these are *"remote-control
endpoints on a box facing the public"*, and *"rig control is not something to expose by
accident."*

**#88's "everything, while testing" would remove the ASIC and Miner tokens too.** That converts a
scanner and a rig-control surface into unauthenticated public endpoints. The scanner does refuse
non-private ranges (`__init__.py:129`), which bounds it — it cannot be turned on the internet — but
it would still let a stranger enumerate and control hardware on Garrett's LAN.

**`SYMONEURAL_MINER_TOKEN` and `SYMONEURAL_ASIC_TOKEN` must remain separate** regardless: one
spends this box's GPU, the other reaches machines on an operator's network.

**The blast radius is wider than Miner and Studio.** The same `_ENABLED` **and** `_TOKEN` double
gate — both required, or the surface does not exist — is what currently protects **eight** surfaces:

| Surface | Gate |
|---|---|
| Studio (**including `/studio/editor/*`**) | `SYMONEURAL_STUDIO_ENABLED` + `_TOKEN` |
| Reinforce (`/api/train`, 7 routes) | double gate |
| Exp (`/api/exp`, 13 routes) | `ENV_ENABLED` + `ENV_TOKEN` — **mutations** specifically |
| Project (`/api/project`, **19 routes**) | `SYMONEURAL_PROJECT_ENABLED` + `_TOKEN` |
| Coder | `SYMONEURAL_CODER_ENABLED` + `_TOKEN` (+ `_ALLOW_REMOTE`) |
| Miner | `SYMONEURAL_MINING_ENABLED` + `SYMONEURAL_MINER_TOKEN` |
| ASIC | `SYMONEURAL_ASIC_ENABLED` + `_TOKEN` |
| Discovery | double gate (no router yet) |

**Project is the one to look at twice, and the finding is narrower than it first appears.**

- `/api/project` has **19 routes on a public prefix**, including `POST`, `PATCH`, `DELETE` and
  file-reference routes.
- **The router declaration shows no `dependencies=`** — `APIRouter(tags=["project"])`,
  `routes.py:45`. So a reader checking only the declaration would conclude it is ungated.
- **It is gated**, twice over: `SYMONEURAL_PROJECT_ENABLED=1` **and** `SYMONEURAL_PROJECT_TOKEN`
  — *"both, or the surface does not exist"* (`project/__init__.py:32-34`) — plus a per-route
  `_deny(request)` call.
- **File references are resolved, contained to the repository root (400 on escape), and
  denylisted after `resolve()`** — so `training/corpus.jsonl`, `training/build_dataset.py` and
  `training/adapter/` return **403 even via a symlink.**

**Therefore: removing the Project token would expose project mutation and write behaviour, but
would not directly expose the protected training artefacts.** Path containment is independent of
the token gate.

**Do not flatten these into one "tokens removed = everything leaked" claim.** The risk type differs
per surface, and #88's real decision depends on which risk applies where:

| Surface | What removing its token actually exposes |
|---|---|
| **Studio** — incl. `/studio/editor/*` | ComfyUI's **full editor API** to the internet, unauthenticated. **The worst case** (BLOCKER-1) |
| **ASIC** | rig control, the firmware emulator and the **network scanner** — bounded to private ranges, so a LAN, not the internet |
| **Miner** | control of the GPU miner, i.e. seizing the card for a process lifetime |
| **Project** | arbitrary project **mutation and writes**. **Not** the training artefacts — containment is separate |
| **Reinforce** (`/api/train`) | `start`/`stop` on training. Currently inert: **torch is not installed**, so every run fails anyway |
| **Exp** | **mutations** specifically — its gate is scoped to those, not to reads |
| **Coder** | the largest filesystem surface — but its root and denylist are also independent of its token |
| **Discovery** | nothing today: **no router, no page, no rack row** |

### HIGH-1 — `/studio/editor/*` as the product surface is unresolved

Independent of #88. `BOX-REALITY-AUDIT.md` §7 already classifies the raw-frontend proxy **AUDIT —
*"unless intentionally retained behind SyMoNeuRaL controls, and that retention has to be an
explicit written decision."*** That decision has not been written.

The product rule is explicit: **ComfyUI look yes, ComfyUI workflow backend yes, raw public ComfyUI
admin/product surface no.** Today an authenticated operator gets vendor UI at a SyMoNeuRaL URL.
**Owner-accept it with a date, or scope its replacement.**

### HIGH-2 — WebSocket origin posture unproven; severity of `/api/ws` depends on the mode

> **Do not call a WebSocket route safe merely because its HTTP route family is gated.** A socket is
> a separate handler with a separate handshake, and here each one gates itself.

#### Three statements this finding must not be misread as

Written as prohibitions because each is a plausible mis-summary of what follows:

- **Do NOT say "all WebSockets are unauthenticated."** One of three is open; two are gated.
- **Do NOT say `/api/studio/events` is missing token checks.** It has them. Verified below.
- **Do NOT say `/studio/editor/ws` is missing token checks.** It has them. Verified below.

**What is true across all three:** **no `Origin` check exists.** Measured —
`grep -n 'origin\|Origin' backend/server.py` finds no request-origin handling. That matters more for
sockets than for ordinary routes, because **a WebSocket handshake is not subject to CORS**: a
third-party page can open one from a visitor's browser with no preflight to stop it.

---

#### 1. `/api/ws` — public, deliberately open, rate-limited. **Severity depends on the mode.**

**Measured** (`api.py:2239`): accepts immediately (`await ws.accept()`) · joins the bus · sends a
`welcome` frame · advertises `caps: ["rack", "chat", "ravencalc", "remix", "ping"]` · **no `Origin`
check** · the active message path **does** carry a rate-limit check for GPU/CPU work —
`check_rate(kind if kind in LIMITS else "chat", key)`, under the comment *"Everything below spends
the GPU or the CPU, so it is rate limited exactly"*.

**It is deliberately open, and it is still security-relevant, because it is not passive
rack-only.** Those two facts sit together: a status feed that can also run chat, ravencalc and
remix is a cost surface.

| Mode | Severity |
|---|---|
| **free / offline demo** | **MEDIUM** — acceptable **only if the rate limiting and queue limits hold.** That is a condition, not an assumption, and it is what the tests below check |
| **commercial / public** | **HIGH** — must be an explicit decision |

**The commercial-mode decision, stated so it cannot be defaulted:** does `/api/ws` **stay open**,
**gain origin checks**, or **require an account/session token**? One of those three, in writing.
`ops/backend/authority/docs/symoneural-commercial-mode.md` is where the switch lives and this is one of its gates.

**Required later tests** — documented only:

- unauthenticated connect behaviour is **intentional** (asserted, not incidental)
- active `chat` / `remix` / `ravencalc` messages over the socket **hit the rate limits**
- **queue limits apply to WebSocket-originated GPU work**, not only to HTTP-originated
- off-origin behaviour is tested, or intentionally documented as accepted
- **malformed frames do not crash the server**
- **`/api/ws` cannot bypass HTTP route gates** — the socket must not become a way round a gate the
  equivalent HTTP route enforces

---

#### 2. `/api/studio/events` — enable-gated **and** token-gated. **VERIFY/HIGH, not a vulnerability.**

**Measured** (`studio/routes.py:669-690`), in order: `accept()` → `if not enabled()` sends
`{"type":"error","error":"studio_disabled"}` and **closes 1008** → `if not
token_ok(present_token(ws.headers, ws.query_params, ws.cookies))` sends
`{"type":"error","error":"bad_token"}` and **closes 1008**.

**So it does not check only `enabled()`.** Recorded explicitly because an earlier partial read of
this handler stopped before the token branch, and the difference between "enable-only" and "enable
plus token" is the entire finding.

**This is not a confirmed vulnerability.** It is **VERIFY/HIGH** — gated, but origin, rate and
abuse behaviour are unverified, and that verification is required before commercial or public mode.

**Required later tests:** disabled Studio closes with **1008** · bad or missing token closes with
**1008** · a valid token connects · origin behaviour documented or tested · **no token value or
local path leaks in a frame.**

---

#### 3. `/studio/editor/ws` — enable- and token-gated. **HIGH on origin and proxy posture.**

**Measured** (`studio/routes.py:823-834`): `accept()` → `if not enabled() or not
token_ok(present_token(ws.headers, ws.query_params, ws.cookies))` → **closes 1008** · then passes
**`clientId` through untouched** to the upstream ComfyUI socket.

**High sensitivity because it bridges the editor socket** to `127.0.0.1:8188`. The `clientId`
pass-through is deliberate and load-bearing — the code records that substituting one *"would
silently blank every progress ring in the UI"* — which is exactly why it needs a test rather than
a reassurance.

Its credential cookie is `HttpOnly`, `SameSite=Strict`, scoped to `/studio/editor`, and the
recorded reason for `Strict` is this concern — *"nothing off-origin has any business loading the
editor"*. **A real mitigation, but not an `Origin` check**: it depends on browser behaviour rather
than server enforcement.

**Relation to BLOCKER-1 is conditional and stated that way on purpose.** This socket is gated
**today**, so it is BLOCKER-1's exposure only if #88 removes the token, or if the editor otherwise
exposes raw ComfyUI or bypasses SyMoNeuRaL controls. **Not safe to expose commercially until
tested.**

**Required later tests:** missing token refused · bad token refused · valid token allowed ·
off-origin behaviour tested · **`clientId` cannot be abused to cross-wire sessions** · **the editor
proxy cannot bypass the queue, the governor, or policy boundaries** · **no local path or token
leaks through a frame.**

---

**None of these tests is implemented, and no authorization to write them has been given.** They are
documented so the work is scoped rather than remembered.

**Close codes get asserted, not inferred**, for the reason `_guard` already gives about HTTP status:
a wrong code *"would be a lie about whether the route exists, and the operator debugging their own
environment variables is the person who suffers for it."*

### MEDIUM-1 — two different local-only checks, and the weaker one is not the one in front

`_require_local` (`api.py:3299-3319`) is the strong check: **two conditions, both must hold** — the
peer address is in `LOCAL_ONLY`, **and** the request carries **no proxy headers**. The code states
why the second is needed: a forwarded header *"the peer check alone would wave through."*

`api.py:3502-3503` records that `_require_local` is a **stricter** peer test than
`coder.peer_ok()` — *"it refuses proxy headers outright and cannot be widened by"* configuration.

**Not a defect today**, because the `/local/*` routes are behind the strict one. It is recorded
because **two checks with the same purpose and different strength is a latent hazard**: a new
`/local/*` route wired to the weaker one would look correct in review. Any resolution of BLOCKER-1
via option (a) must use `_require_local`, not the weaker test.

### MEDIUM-2 — `X-Forwarded-For` is trusted for rate limiting by design

`api.py:598` and `:2331` take the **first** value of `X-Forwarded-For` as the client identity, and
`Caddyfile:19-20,60` records that this is Caddy's default handling, kept deliberately after testing.

**A direct-to-origin request could therefore spoof its rate-limit identity.** The mitigation is
that the origin is not meant to be reachable except through Caddy. **Confirm that, or accept it.**
Rate limits are a monopolisation guard rather than a hardware guard (`api.py:235-238`), which
bounds the impact.

### LOW-1 — `/tuner.html` and `/tuner-watch.html` still answer

Both are live GET routes in `api.py`. Intended as redirect compatibility for the Streamer fold
(`symoneural-streamer-scope.md` §4). **Confirm they redirect rather than serve retired Tuner
branding**, and set a removal date — *"do not keep old aliases forever unless explicitly
authorized."*

---

## A. Public route inventory

Measured 2026-08-22 from `backend/server.py` and the mounted routers.

### Delegated by Caddy — internet-facing

| Path | Target |
|---|---|
| `/api/*` | `127.0.0.1:8000` (gateway → FastAPI verbatim) |
| `/v1/*` | `127.0.0.1:8000` — **gateway-owned**; no `/v1` route exists in `api.py` |
| `/docs*`, `/openapi.json`, `/swagger-ui*`, `/api-docs/*` | FastAPI / vendored assets |
| `/`, `/overview`, `/livestack`, `/controlboard`, `/receipts` | section pages |
| **`/studio`, `/studio/*`** | **see BLOCKER-1** |
| `/exp` | Exp page |
| `/livestack/live`, `/live-stack/live` | Live |
| `/livestack/coder`, `/live-stack/coder` | Coder page |
| `/livestack/image`, `/live-stack/image` | Image |

### `/api/*` — public prefix. **123 routes total, expanded**

**In `backend/server.py` — 32 routes** (`@app.*` decorators):

`GET /` · `GET /api/status` · `GET /api/gen/{name}` · `GET /api/studio/models` ·
`GET /api/gpuminer/status` · `GET /api/asicminer/firmware` · `POST /api/chat` · `POST /api/image` ·
`POST /api/remix` · `POST /api/ravencalc` · **`POST /api/gpuminer/control`** ·
**`POST /api/asicminer/scan`** · **`POST /api/asicminer/emulator`** · **`WebSocket /api/ws`** ·
`GET /docs` · `GET /literal` · `GET /studio` · `GET /exp` · `GET /livestack/coder` ·
`GET /live-stack/coder` · `GET /livestack/live` · `GET /live-stack/live` · `GET /tuner.html` ·
`GET /tuner-watch.html` · the nine `/local/*` below.

**In mounted routers — 91 routes**, measured by parsing each module tree with its plugin
subtrees separated (a recursive glob over `apps/studio` otherwise double-counts Reinforce and Exp,
which is how a first pass of this inventory reported 98):

| Prefix | Routes | Write / control / cost notes |
|---|---|---|
| `/api/accounts` | 8 | `signup`, `login`, `logout`, `password`, `signout-everywhere` — **auth surface** |
| `/api/rack` | 2 | `GET power`, **`POST power/{unit_id}`** — the rack switch. See `RackPowerGate` |
| `/api/gateway` | 1 | `GET state` only |
| `/api/live` | 5 | all `GET`; `hls/{name}` serves media |
| `/api/news` | 1 | `GET ticker` |
| `/api/project` | **19** | `POST`/`PATCH`/`DELETE` on projects, items, files, events; two `draft/*` |
| `/api/sigils` | 5 | 3 `POST` = **GPU cost**; router-wide metered |
| `/api/streamer` | 14 | `tune`, `session/{sid}/stop`, `DELETE session/{sid}`; SSRF-pinned fetches |
| `/api/studio` | 11 (+2 on `/studio/editor`) | `apply`, `add`, `remove`, `patch`, `enable`, `reload`, `call`, `agent`, `queue`, `interrupt` — **control + GPU cost** |
| `/api/train` | 7 | `preflight`, **`start`**, **`stop`** — training; torch absent, so not exercisable today |
| `/api/exp` | 13 | mutations behind enable+token |
| `/api/voice` | 3 | `transcribe`, `speak` — **CPU cost**, and the one surface where the GPU queue is *not* the backstop |

**`BOX-REALITY-AUDIT.md` §7 records "141 shipped routes"; this scan measures 123.** The figure is
**not** reconciled, and neither number is restated as the other. Counting method is the likely
difference (page routes, aliases, and whether `api_route` catch-alls count once or per method).
**Reconcile before either is published.**

### WebSocket inventory — 3, with auth measured per route

**Verified 2026-08-22 by reading each handler**, rather than left as "must be verified":

| Route | Auth posture, measured | Origin |
|---|---|---|
| `/api/ws` | **none by design** — `ws.accept()` then straight into the bus (`api.py:2239-2247`). It is the public rack/status + chat channel, the same posture as `POST /api/chat`. **GPU-spending frames ARE rate-limited**: `check_rate(kind if kind in LIMITS else "chat", key)`, with the comment *"Everything below spends the GPU or the CPU, so it is rate limited exactly"* | **not checked** — HIGH-2 |
| `/api/studio/events` | **gated.** `accept()`, then `enabled()` → close 1008 `studio_disabled`, then `token_ok(present_token(headers, query_params, cookies))` → close 1008 `bad_token` (`studio/routes.py:669-690`) | not checked |
| `/studio/editor/ws` | **gated.** `accept()`, then `if not enabled() or not token_ok(...)` → close 1008 (`studio/routes.py:823-834`) | not checked; **cookie is `SameSite=Strict`** |

**`/studio/editor/ws` is token-gated today** — so it is not currently an open socket. It is
BLOCKER-1's exposure **only if #88 removes the token**, which is precisely why that finding is
about the task rather than about the current state. Its credential cookie is `HttpOnly`,
`SameSite=Strict` and scoped to `/studio/editor`, and the recorded reason for `Strict` is exactly
this concern: *"nothing off-origin has any business loading the editor."*

**`caps` on `/api/ws` advertises `["rack", "chat", "ravencalc", "remix", "ping"]`** — so the socket
can drive GPU work, and the rate limiter is what stands between it and the queue.

### Cursor-polled JSON event route — 1

| Route | What it actually is |
|---|---|
| `GET /api/exp/events` | **cursor-polled JSON.** `exp/routes.py:156`, `?since=<seq>&limit=<n>`, returning `{"events": …, "seq": …, "buffered": …}`. The page polls with the last `seq` it saw. The docstring gives the reason: *"A sequence, not a timestamp: two events can share a millisecond, and a timestamp cursor either re-delivers them or drops one."* |

**It is a public-prefix event/READ route and is classified separately from Exp's mutations**, which
are the part behind `ENV_ENABLED` + `ENV_TOKEN`. A read route and a mutation route on the same
prefix do not share a verdict.

### Four transports, four buckets — do not flatten them

| Bucket | Present here |
|---|---|
| **WebSocket** | 3 routes, above |
| **SSE / `text/event-stream`** | **none. No SSE endpoint exists anywhere in this repo** |
| **`EventSource` client usage** | none, following from the above |
| **cursor-polled JSON** | `GET /api/exp/events` |

**They have different auth, different origin exposure, different failure modes and different
metering needs**, so they get different rows. Two mis-classifications from earlier passes of this
inventory are recorded rather than silently fixed:

- a first pass listed `GET /api/studio/events` as an SSE sibling of the WebSocket. **That route
  does not exist.** `/api/studio/events` is a WebSocket only; the `GET /events` belongs to **Exp**.
  The mis-attribution came from a recursive glob over `apps/studio` picking up its own plugin tree
  — the same glob error that inflated the router count to 98.
- calling the Exp poll "SSE" would have implied a streaming connection with no per-request auth
  check, when it is in fact an ordinary request-per-poll route.

**Metering note:** `GET /api/exp/events` is a **polling** endpoint on a **non-GPU** surface, which
is the exact shape that made Sigils' `/state` and `/packs` worth metering router-wide — and Exp is
CPU work, so **the GPU queue does not ration it.** Confirm it is metered rather than assuming
something else rations it.

### Write / control / admin routes — the set that must never be ungated

**Control:** `POST /api/rack/power/{unit_id}` · `POST /api/gpuminer/control` ·
`POST /api/asicminer/scan` · `POST /api/asicminer/emulator` · `POST /api/studio/{enable,reload,
apply,add,remove,patch,call}` · `POST /api/train/{start,stop}` · `POST /api/streamer/session/{sid}/stop`

**GPU cost:** `POST /api/chat` · `POST /api/image` · `POST /api/remix` · `POST /api/sigils/{render,
from-image,from-audio}` · `POST /api/studio/{agent,queue}` · `POST /studio/editor/api/prompt` ·
`POST /api/train/start`

**Auth/admin:** the eight `/api/accounts/*` · every `_TOKEN` gate in §C

**Write:** the nineteen `/api/project/*` mutations · `POST /local/intake` · `POST /local/tasknote`

### `/local/*` — local-only, behind `_require_local`

`/local/coder` · `/local/coder/status` · `/local/coder/ls` · `/local/coder/file` ·
`/local/coder/history` · `/local/coder/journal` · `/local/intake` · `/local/progress` ·
`/local/tasknote`

**Not delegated by Caddy**, and refused off-box even if it were. **There is no `/api/coder/*` route
and a test asserts its absence** (`apps/coder/tests/test_coder_surface.py:18`).

## B. Caddy exposure — status

**Confirmed:** `/api/*` proxied wholesale, path rewriting nowhere; `/local/*` not delegated and
independently peer-checked; `/v1` gateway-owned with no competing owner.

**Open:** `/studio/*` delegation (BLOCKER-1, HIGH-1) · whether the origin is reachable
direct, bypassing Caddy (MEDIUM-2) · `/tuner*` retirement (LOW-1).

## C. Token and secret inventory — names only

| Name | Authorizes |
|---|---|
| `SYMONEURAL_STUDIO_ENABLED` / `_TOKEN` | Studio, **including the editor proxy** — BLOCKER-1 |
| `SYMONEURAL_MINER_TOKEN` | taking the card — GPU miner |
| `SYMONEURAL_ASIC_ENABLED` / `_TOKEN` | ASIC HTTP controls / rig, scanner, emulator |
| `SYMONEURAL_CODER_ENABLED` / `_TOKEN` / `_ALLOW_REMOTE` | the browser coder |
| `DJ_TOKEN` | Remix + **accounts** break-glass owner bearer — and `AUDIT.md` Q12 |
| `DJ_TOKEN_PATH` | **not a token file** — the Spotify OAuth cache. See `symoneural-remix-scope.md` §6 |
| `VLLM_API_KEY`, `SPOTIFY_CLIENT_ID`/`_SECRET` | engine and provider credentials |
| `SYMONEURAL_OBS_PASSWORD` | obs-websocket, loopback only |

**Do not reuse one token for everything.** User API tokens, owner/admin tokens, Studio, Miner,
ASIC and provider OAuth are distinct authorities.

**State, measured:** no archive is tracked (`git ls-files` finds no `.tar.gz`/`.zip`); `.env`,
`*.env` are gitignored with `!*.env.example`; the two live env files are **mode 600 and untracked**;
`INTAKE.md` and `GARRETT-REQUESTS.md` are mode 600 and gitignored; the contract-signing private key
is ignored three ways and chmodded 0600 by `issue.py`, and **there is no wallet, private key or
signing code in the web process**.

**Open:** #75 is **paused at 0/4** — rotation not done, and the Spotify half is Garrett's
(third-party dashboard). `scripts/lib/archive-guard.sh:74`'s `_AG_SECRET_KEYS` covers the current
names; **any new token name must be added there in the same change that introduces it.** #38 —
extend the leak guard to `review/`, `ops/history/archive/` and the retired-assignment files, which is where
a pasted credential would land unnoticed. **#102** (`owner: garrett`) — the displayed Studio token
is spent and needs a new value.

## D. Filesystem and coder — status

**Implemented and tested** (`symoneural-coder-project-cli-scope.md` §4): no public raw shell · no
public arbitrary Python/Bash · enable flag **and** non-empty token, constant-time compared ·
loopback-only unless `ALLOW_REMOTE` · workspace root configurable · every path `resolve()`d so
symlinks are followed · **denylist on the resolved absolute path** · `pip install` blocked.

**Protected:** `training/corpus.jsonl` · `training/build_dataset.py` · `training/adapter*` · `.env`
and secrets · credentials and SSH keys · private ledgers · model weights · raw archives ·
proprietary references · anything outside the workspace root.

**Keep the regression test.** The denylist matched a path *segment*, so `training/adapter` was denied
while **`training/adapter-qwen36` — 200 MB of real LoRA weights — was readable** and
`/local/coder/file` returned its config with a 200. Now a glob.

**Open:** read-only vs write mode separation, and side-effect logging, need explicit confirmation
against the current code.

## E. GPU and cost abuse — status

Image/Sigils metered (20/300, and Sigils is **router-wide** so its polling routes are covered) ·
Chat/Remix behind the one-deep queue · **no silent CPU fallback anywhere** (PROD) · Miner's
process-lifetime hold is deliberate and not preemptible · `RackPowerGate` refuses HTTP work for a
powered-off unit, and covers WebSocket frames too.

**Open:** Studio render path gating is BLOCKER-1 · Reinforce/training gating (torch absent, so not
exercisable today) · queue-full and timeout behaviour need proof, not assumption · **no
unauthenticated rack-wide outage path** must be demonstrated rather than assumed.

## F–J. Remaining areas — scoped, not yet audited

**F. Upload/input** — bounded uploads, validated types, pixel limits, metadata stripped, no
traversal, no arbitrary URL fetch. Streamer's fetches are already **SSRF-pinned**. Image-to-image
uploads do not exist yet, so their limits are design-time (`symoneural-image-scope.md` §4).

**G. Provider/third-party** — Spotify OAuth isolated, stream and OBS credentials protected, Caddy
config leaking nothing, **no real credentials in tests** (fixtures only).

**H. Headers and browser** — no-cache where sensitive · deliberate CORS · deliberate WebSocket auth
for `/api/ws` · generated pages must not leak file paths · **public API responses must never contain
`file://`, `vscode://` or `pycharm://` links** (`symoneural-coder-project-cli-scope.md` — code-jump
belongs under `/local/*`).

**I. Dependency and supply chain** — pinning, no system-pip pollution, isolated venvs, SBOM,
provenance, SLSA-style build provenance, licence scan. See `ops/registry/SBOM.md`,
`ops/audits/LICENSE-AUDIT.md`, `models/docs/PROVENANCE.md`.

**J. Git and export** — currently clean by measurement: no raw archive, whole-repo zip, weight,
`.venv`, `review/`, private ledger or protected training artefact is tracked. `ops/registry/EXPORTS.md`
governs what may leave the box, and **`.gitignore` records four separate incidents where a bulk
`git add` staged secrets, 7,620 cargo files and an 11.6 MB `.mhtml` — which is why `git add .` is
forbidden.**

## Severity vocabulary

| | Means |
|---|---|
| **BLOCKER** | commercial or public privileged mode must not be enabled until closed or owner-accepted **in writing, with a date** |
| **HIGH** | same gate; may be owner-accepted with a stated reason |
| **MEDIUM** | latent hazard or trusted-by-design choice. Confirm or accept |
| **LOW** | tidy-up; no exposure implied |

**A finding is closed by a change plus a test, or by a written owner-acceptance.** Neither has
happened for anything above — **this file is the opening inventory, not a completed audit.**
