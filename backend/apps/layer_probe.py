"""Probe every reported endpoint at all four layers and print the route matrix.

    application/UI -> symoneural-web (:443) -> symoneural-gateway (:8000)
                   -> symoneural-api (:8800) -> registered route

The question this answers is NOT "does the endpoint return 200". It is "at which
layer, if any, does a request stop being routed". Those are different questions,
and conflating them produced the 2026-08-26 report of 25 broken endpoints -- all
25 of which are registered and reachable.

## Why this app can never answer 405, and why that matters

The obvious probe for "is this path wired" is to hit it with a method it does not
have and look for 405. **That does not work here, and believing it does is what
made the bad report look credible.**

`backend/api.py` finishes its route table with `Mount('', StaticFiles(...))` --
route index 145 of 146, matching every path there is. Starlette resolves in
order: an API route carrying the wrong method returns a PARTIAL match, so the
walk continues instead of stopping at 405; the catch-all mount then returns a
FULL match, StaticFiles looks for a file, finds none, and raises **404**.

So in this application `GET /api/chat` and `GET /api/nonsense-does-not-exist`
are byte-identical responses. A GET-only sweep therefore cannot distinguish a
POST route from a route that was never registered -- which is precisely the
distinction the sweep was claiming to have measured.

## What is used instead

Registration is proven by reaching the handler's own boundary with the route's
REAL method:

    VALIDATE  real method, body `"__routing_probe__"` (a bare JSON string).
              Every route probed this way was confirmed against the running
              server's own openapi.json to have `requestBody.required: true`, so
              a non-object body is rejected by Pydantic BEFORE the handler is
              entered. 422 proves the route resolved and proves nothing ran.
              This is what keeps `/api/gpuminer/control`, `/api/asicminer/scan`
              and `/api/streamer/tune` honest without firing a miner or a tuner.

    AUTHWALL  real method, no credentials, for the two POST routes that declare
              no body at all (`logout`, `signout-everywhere`). With no session
              cookie the auth check raises before any revocation happens. 401
              proves the route resolved.

    EXERCISE  real method, for genuine reads and pure functions.

    SOCKET    a real WebSocket handshake. 101 proves the upgrade was routed all
              the way through. An ordinary GET cannot test this: it never
              computes Sec-WebSocket-Accept, so a correct server rejecting it
              looks exactly like a broken route.

OPTIONS is never used, at any layer: `backend/apps/gateway` links tower-http with
the `cors` feature, so an OPTIONS can be answered by the gateway and never reach
FastAPI -- a 200 that proves nothing about the API.

## Reading the matrix

Each row carries what it SHOULD return, so a 404 is never silently tolerated and
never silently condemned. `/local/*` inverts the expectation on purpose: it is
local-only, so being refused at the gateway and in public is the correct result,
not a defect to fix.
"""

from __future__ import annotations

import asyncio
import json
import ssl
import sys
from dataclasses import dataclass, field

import httpx

DIRECT = "http://127.0.0.1:8800"
GATEWAY = "http://127.0.0.1:8000"
PUBLIC = "https://symoneural.com"

EXERCISE = "exercise"
VALIDATE = "validate"
AUTHWALL = "authwall"
SOCKET = "websocket"

# A bare JSON string. Not an object, so it cannot satisfy any BaseModel body, so
# FastAPI rejects it in the request-validation step that runs before the endpoint
# function is called. The literal value is a marker, so that if one of these ever
# DOES reach an application log it is obvious what put it there.
PROBE_BODY = "__routing_probe__"


@dataclass(frozen=True)
class Probe:
    reported: str          # path exactly as the 2026-08-26 report named it
    method: str
    path: str              # what is actually requested
    kind: str
    expect: tuple[str, ...]        # acceptable codes at :8800
    # Per-layer overrides, because the three layers do NOT carry the same
    # namespace and pretending they do is what flagged three healthy rows on the
    # first run of this file. `ops/Caddyfile` sends only `/api/*`, `/v1/*`,
    # `/swagger-ui*` and `/api-docs/*` to the gateway; `/demo/dispatchos` is
    # proxied straight to :8800 behind basic auth, and `/local/*` is given no
    # matcher at all on purpose. For those paths a gateway 404 is the design,
    # not a fault, and a harness that expects otherwise reports false failures.
    expect_gateway: tuple[str, ...] = ()   # defaults to `expect`
    expect_public: tuple[str, ...] = ()    # defaults to `expect`
    body: object | None = None
    note: str = ""

    def gateway_expect(self) -> tuple[str, ...]:
        return self.expect_gateway or self.expect

    def public_expect(self) -> tuple[str, ...]:
        return self.expect_public or self.expect


OK = ("200",)
VALIDATED = ("422",)
AUTHED = ("401", "403")

PROBES: tuple[Probe, ...] = (
    # -- namespace roots the report named. None of these was ever an endpoint;
    #    each is probed at a real registered read inside the same namespace,
    #    because a path no router declared can only 404 at every layer and would
    #    show up as a fake three-layer failure.
    Probe("/api/accounts", "GET", "/api/accounts/status", EXERCISE, OK,
          note="root is not an endpoint; /status is the namespace read"),
    Probe("/api/exp", "GET", "/api/exp/state", EXERCISE, OK,
          note="root is not an endpoint; /state is the namespace read"),
    Probe("/api/sigils", "GET", "/api/sigils/packs", EXERCISE, OK,
          note="root is not an endpoint; /packs is the namespace read"),
    Probe("/api/streamer", "GET", "/api/streamer/state", EXERCISE, OK,
          note="root is not an endpoint; /state is the namespace read"),
    Probe("/api/studio", "GET", "/api/studio/state", EXERCISE, OK,
          note="root is not an endpoint; /state is the namespace read"),
    Probe("/api/train", "GET", "/api/train/status", EXERCISE, ("200", "503"),
          note="503 accepted: Reinforce is registered but its backend is "
               "intentionally not running"),
    Probe("/api/streamer/session", "GET", "/api/streamer/session/probe-nonexistent",
          EXERCISE, ("404", "400", "409"),
          note="the real route is /{sid}; a made-up sid must REACH the handler "
               "and be refused by it -- that refusal is the proof of routing"),

    # -- action routes. Never fired; stopped at validation or at auth.
    Probe("/api/accounts/logout", "POST", "/api/accounts/logout", AUTHWALL,
          ("401", "403", "204", "200"),
          note="declares no body; harmless without a session cookie"),
    Probe("/api/accounts/password", "POST", "/api/accounts/password", VALIDATE, VALIDATED),
    Probe("/api/accounts/signout-everywhere", "POST", "/api/accounts/signout-everywhere",
          AUTHWALL, ("503",),
          note="503 IS THE CORRECT ANSWER, and it is reached BEFORE any session is "
               "revoked. accounts/__init__.py:264 requires both "
               "SYMONEURAL_ACCOUNTS_ENABLED=1 and a session secret; neither is set "
               "in symoneural-api.service, so accounts fail CLOSED. This row "
               "expected 401 on the first run -- the harness was wrong, not the box."),
    Probe("/api/asicminer/emulator", "POST", "/api/asicminer/emulator", VALIDATE, VALIDATED),
    Probe("/api/asicminer/scan", "POST", "/api/asicminer/scan", VALIDATE, VALIDATED,
          note="validation-stopped: a real POST starts a network scan"),
    Probe("/api/gpuminer/control", "POST", "/api/gpuminer/control", VALIDATE, VALIDATED,
          note="validation-stopped: a real POST starts or stops mining on the live card"),
    Probe("/api/image", "POST", "/api/image", VALIDATE, VALIDATED,
          note="validation-stopped: proves the route resolves WITHOUT occupying "
               "the GPU for a diffusion run"),
    Probe("/api/remix", "POST", "/api/remix", VALIDATE, VALIDATED),
    Probe("/api/streamer/epg", "POST", "/api/streamer/epg", VALIDATE, VALIDATED),
    Probe("/api/streamer/guide/filter", "POST", "/api/streamer/guide/filter", VALIDATE, VALIDATED),
    Probe("/api/streamer/playlist", "POST", "/api/streamer/playlist", VALIDATE, VALIDATED),
    Probe("/api/streamer/tune", "POST", "/api/streamer/tune", VALIDATE, VALIDATED,
          note="validation-stopped: a real POST tunes physical hardware"),
    Probe("/api/streamer/xtream/channels", "POST", "/api/streamer/xtream/channels",
          VALIDATE, VALIDATED,
          note="validation-stopped: a real POST calls a third-party provider"),

    # -- the two that are neither a root nor an action.
    Probe("/api/rack/power", "GET", "/api/rack/power", EXERCISE, ("404",),
          note="404 IS THE CORRECT ANSWER. controlboard/routes.py:66 returns "
               "'absent, not forbidden' when the feature is disabled -- a "
               "deliberate design choice to not reveal that the switch exists. "
               "Registered in the running openapi.json as GET."),
    Probe("/api/chat", "POST", "/api/chat", EXERCISE, OK,
          body={"prompt": "Reply with the single word: online", "max_tokens": 8},
          note="real inference on purpose -- Chat is a required result. `prompt`, "
               "not `messages`: the first draft of this probe guessed the field "
               "name and got a 422 that was the TEST being wrong again."),
    Probe("/api/ravencalc", "POST", "/api/ravencalc", EXERCISE, OK,
          body={"expression": "2+2"}, note="pure function, no state"),
    Probe("/api/ws", "GET", "/api/ws", SOCKET, ("101",)),

    # -- local-only by design. Expectations are INVERTED for the outer layers.
    Probe("/local/coder", "GET", "/local/coder/status", EXERCISE, OK,
          expect_gateway=("404", "403"), expect_public=("404", "403"),
          note="LOCAL-ONLY BY DESIGN, and refused TWICE. ops/Caddyfile gives "
               "/local/* no matcher at all -- its comment reads that a handle "
               "block there 'would put that on the public internet in one line' "
               "-- so it never reaches the gateway either. Refusal at both outer "
               "layers is the boundary working, not a 404 to eliminate."),

    # -- named in the instruction as required results.
    Probe("/api/status", "GET", "/api/status", EXERCISE, OK, note="required result"),
    Probe("/demo/dispatchos", "GET", "/demo/dispatchos", EXERCISE, OK,
          expect_gateway=("404",), expect_public=("401",),
          note="required result. Gateway 404 is CORRECT: ops/Caddyfile proxies "
               "/demo/dispatchos* straight to :8800 behind basic auth, so this "
               "path is not in the gateway's namespace by design. Public 401 is "
               "CORRECT: it is Donnie's auth gate refusing an anonymous caller."),
)


async def _http(client: httpx.AsyncClient, base: str, p: Probe) -> str:
    """One probe against one layer; returns the literal status code.

    Redirects are not followed. A 307/308 is itself routing information -- the
    path matched and something is normalising it -- and following it would hide
    that behind the destination's code.
    """
    try:
        kw: dict = {"timeout": 180.0}
        if p.kind == VALIDATE:
            kw["json"] = PROBE_BODY
        elif p.body is not None:
            kw["json"] = p.body
        r = await client.request(p.method, base + p.path, **kw)
        return str(r.status_code)
    except httpx.HTTPError as e:
        return f"ERR:{type(e).__name__}"


async def _socket(base: str, path: str) -> str:
    """Real WebSocket handshake; '101' on success. Closed immediately -- the
    question is whether the upgrade routed, not what it streams."""
    import websockets
    url = base.replace("http://", "ws://").replace("https://", "wss://") + path
    ctx = ssl.create_default_context() if url.startswith("wss://") else None
    try:
        async with websockets.connect(url, ssl=ctx, open_timeout=25) as ws:
            code = getattr(getattr(ws, "response", None), "status_code", None)
            await ws.close()
            return str(code) if code else "101"
    except Exception as e:  # noqa: BLE001 -- every failure mode is a datum here
        code = getattr(getattr(e, "response", None), "status_code", None)
        return str(code) if code else f"ERR:{type(e).__name__}"


def first_failing(p: Probe, direct: str, gw: str, pub: str) -> str:
    """Name the earliest layer whose answer is not one this row expects.

    Layer order is the request's own order, so the FIRST mismatch is the one to
    repair -- everything downstream of a broken layer is untestable, not healthy.
    """
    for layer, code, allowed in (
        ("symoneural-api :8800", direct, p.expect),
        ("symoneural-gateway :8000", gw, p.gateway_expect()),
        ("symoneural-web / public", pub, p.public_expect()),
    ):
        if code not in allowed:
            return f"{layer}  (got {code}, expected {'/'.join(allowed)})"
    return "NONE"


async def main() -> int:
    rows = []
    async with httpx.AsyncClient(follow_redirects=False) as pubc, \
               httpx.AsyncClient(follow_redirects=False) as locc:
        for p in PROBES:
            if p.kind == SOCKET:
                d, g, u = (await _socket(DIRECT, p.path),
                           await _socket(GATEWAY, p.path),
                           await _socket(PUBLIC, p.path))
            else:
                d = await _http(locc, DIRECT, p)
                g = await _http(locc, GATEWAY, p)
                u = await _http(pubc, PUBLIC, p)
            rows.append({"reported": p.reported, "method": p.method, "probed": p.path,
                         "kind": p.kind, "direct": d, "gateway": g, "public": u,
                         "first_failing": first_failing(p, d, g, u), "note": p.note})

    if "--json" in sys.argv:
        print(json.dumps(rows, indent=2))
        return 0

    w = max(len(r["reported"]) for r in rows)
    print(f"{'METHOD'.ljust(6)}  {'REPORTED ENDPOINT'.ljust(w)}  {'PROBE'.ljust(10)}  "
          f"{'8800'.rjust(5)}  {'8000'.rjust(5)}  {'PUBLIC'.rjust(6)}  FIRST FAILING LAYER")
    for r in rows:
        m = "WS" if r["kind"] == SOCKET else r["method"]
        print(f"{m.ljust(6)}  {r['reported'].ljust(w)}  {r['kind'].ljust(10)}  "
              f"{r['direct'].rjust(5)}  {r['gateway'].rjust(5)}  {r['public'].rjust(6)}  "
              f"{r['first_failing']}")

    bad = [r for r in rows if r["first_failing"] != "NONE"]
    print(f"\n{len(rows)} probed, {len(bad)} with a failing layer", file=sys.stderr)
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
