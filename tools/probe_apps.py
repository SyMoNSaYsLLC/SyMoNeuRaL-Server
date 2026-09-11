#!/usr/bin/env python3
"""Sweep every application on the live API: coverage, boundaries, latency, limits.

Four questions per application, asked of the running service rather than of the
files that describe it:

  1. **Coverage.** Does every route the router will actually match have a declared
     owner? The route table is read with `apps.route_matrix.collect`, which walks
     `app.routes` -- the structure Starlette matches against -- and NOT the OpenAPI
     schema. That distinction is load-bearing here: `/local/*` and every WebSocket
     route are absent from `openapi.json` entirely (41 parameterless GETs and 105
     path items in the schema against a router that carries more), so a
     schema-driven sweep would report the loopback surfaces as nonexistent and
     declare full coverage of a set it never saw. `apps/route_matrix.py` exists
     because that exact false negative was once published as "25 broken endpoints".

  2. **Boundary: declared versus enforced.** `apps/appdocs.py` declares each
     application's `auth` and names its `operator_only` routes. This probes them
     UNAUTHENTICATED and records what comes back. That comparison is the app-side
     twin of the requested-versus-active check that found speculative decoding
     switched off in the chat engine: a claim in a registry is not a control.

  3. **Latency.** Measured per route, on the surfaces where a measurement means
     something, reported as samples rather than one number.

  4. **Limits: declared versus enforced.** `appdocs.py` publishes per-surface rate
     limits. `api.py:_rate_for` reads them from `SYMONEURAL_RATE_<SURFACE>` and
     returns `(0, 0)` -- no bucket at all -- when unset. Whether anything enforces
     the published figures is a question with a measurable answer, so it is asked
     by bursting rather than assumed either way.

## What this does not do, deliberately

**It never exercises a write endpoint that could create or alter user data.**
GUARDRAILS requires preserving user data, and a booking or an account this tool
invented would have to be cleaned up afterwards -- a mutation to undo a
measurement. Every write route on a protected surface is probed with an EMPTY
JSON body, so that even in the failure case the probe is proving -- a request that
gets past authentication still cannot satisfy a required field, and answers 422
without touching state.

    401 / 403 / 404  the boundary held
    2xx              the boundary is absent -- FINDING
    422              says NOTHING about the boundary

That last line was wrong in the first version of this tool and is worth stating
plainly, because it produced four false findings before it was checked. FastAPI
validates the request model BEFORE the handler runs, so a gate written inside the
handler -- `_guard(request)` at `apps/controlboard/routes.py:88`, and the same shape
elsewhere -- has not been consulted when the 422 is generated. A 422 is a fact about
validation order. It is reported as a *disclosure* only where the route's own module
argues that concealment matters, which `disclosure_matters()` decides by asking the
route's sibling.

Public write endpoints (`/api/accounts/signup`) are recorded as reachable and are
not called at all: there is no boundary to test and calling one creates an account.

**It does not start, enable or configure anything.** Surfaces that are off --
miner, studio, the gateway -- are reported off, with the reason the rack gives.
Enabling them is a service mutation and needs its own authorization.

**GPU order is not incidental.** `POST /api/image` calls `stop_llama()`
(`api.py:2916`), and a cold chat reload measured 113 s on this box. So every
language-runtime surface is probed first, CPU surfaces next, and the diffusion
surfaces last -- and the eviction is recorded as a platform measurement rather
than left to look like an unexplained latency spike halfway down the report.

    python3 tools/probe_apps.py                  # full sweep
    python3 tools/probe_apps.py --no-gpu         # skip chat/image/sigils entirely
    python3 tools/probe_apps.py --no-limits      # skip the rate-limit burst
"""

from __future__ import annotations

import argparse
import dataclasses
import importlib
import json
import re
import statistics
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))

BASE = "http://127.0.0.1:8800"

#: Refusal codes. 404 counts because the loopback surfaces are DESIGNED to answer
#: 404 rather than 403 to an off-box caller -- an application that admits it exists
#: and then refuses has told an unauthenticated stranger it is there. Treating 404
#: as "route missing" would have reported those refusals as broken routing.
REFUSED = (401, 403, 404)

#: Routes on a protected surface that must stay open, because they are the door.
#: Named individually rather than pattern-matched: `/login` is the endpoint whose
#: whole job is to be reachable unauthenticated, and a pattern like "anything
#: ending in login" is a rule nobody can audit against the registry.
#:
#: The two `logout` routes are here on evidence, not on the strength of the name.
#: `apps/accounts/routes.py:182-195` clears the cookie and answers 204 whether or
#: not a session existed, with the reason written beside it -- *"a logout that
#: leaves the cookie in place because the row was already gone is a logout the
#: visitor cannot trust"*. An unauthenticated 204 there is the designed behaviour,
#: so reporting it as an unguarded write would be this tool crying wolf on a
#: deliberate decision. Every entry below was read before it was added.
DOORS = frozenset({
    "/api/accounts/login", "/api/accounts/signup", "/api/accounts/status",
    "/api/accounts/logout",
    "/api/dispatchos/login", "/api/dispatchos/status", "/api/dispatchos/logout",
    # `/state`, not `/status`. Both spellings were guessed here first and neither
    # existed on `studio`; `backend/apps/test_probes.py` checks every entry in this
    # set against the live router for that reason, and caught it.
    "/api/studio/state",
})

#: The header set a request that crossed a reverse proxy might realistically carry.
#: `_require_local` (`api.py:3743-3744`) treats the PRESENCE of a forwarded header as
#: proof the request crossed a proxy, and refuses on it -- its docstring calls this
#: "the belt to its braces" against a future `handle /local*` block in `ops/Caddyfile`
#: that would make the socket loopback while the request came from outside. The list
#: it checks is three names long. So this probes the full realistic set and reports
#: which are caught and which are not, rather than asserting either.
#:
#: `X-Forwarded-For: 127.0.0.1` is in here on purpose and is the sharpest of them: it
#: is what an off-box caller would send to impersonate the very peer the gate looks
#: for, so a gate reading the header instead of the socket fails on that one alone.
SPOOF_HEADERS = (
    {"X-Forwarded-For": "203.0.113.9"},
    {"X-Forwarded-For": "127.0.0.1"},
    {"X-Real-IP": "203.0.113.9"},
    {"X-Forwarded-Host": "symoneural.com"},
    # RFC 7239, the standardised replacement for the X- headers above.
    {"Forwarded": "for=203.0.113.9;proto=https"},
    # Caddy sets this on everything it proxies, beside the two it does check.
    {"X-Forwarded-Proto": "https"},
    {"Via": "1.1 caddy"},
    # Added when `_require_local` grew to seven headers: a header the guard checks and the
    # probe never sends is a gate nobody is testing.
    {"X-Forwarded-Port": "443"},
)

#: Query strings tried, in order, when a probe needs a request that VALIDATES.
#: Necessary because FastAPI validates path and query parameters before the handler
#: body runs, so a route whose gate lives inside the handler answers 422 to a
#: parameterless probe and the gate is never reached. A 422 is then evidence about
#: this tool, not about the boundary -- see `spoof_probe`.
VALIDATING_QUERIES = ("", "?path=.", "?path=README.md", "?n=1", "?path=.&recursive=false")

#: The compute surfaces worth a latency measurement, with the smallest request that
#: does real work. Bodies are built from the live OpenAPI schema's own `examples`
#: where one exists (see `example_body`) and overridden here only to keep the
#: measurement small -- an unbounded `max_tokens` would measure the model, not the
#: surface.
COMPUTE = {
    "/api/chat": {"prompt": "Say READY.", "max_tokens": 16},
    "/api/remix": {"prompt": "late-night drive through a rainy city", "count": 3},
    "/api/ravencalc": None,       # body derived from the schema
}

#: Diffusion surfaces, probed LAST because taking the card evicts the language
#: model. `steps` and `size` are the smallest the surface accepts, because the
#: question here is whether it renders at all and what it costs, not image quality.
#:
#: The method is NOT assumed. An earlier revision posted to `/api/sigils` and logged
#: `405 Method Not Allowed` as though the surface were broken -- it was this tool
#: guessing a verb the route does not have, which is the same mistake the
#: "25 broken endpoints" report made and which `apps/route_matrix.py` exists to stop
#: anyone repeating. `method_for` reads the verb off the router.
GPU_LAST = {
    "/api/image": {"prompt": "a grey cube on a white background", "steps": 1,
                   "size": 256},
    # `/api/sigils` is a PREFIX with no route of its own; `render` is the verb that
    # does the work. Probing the prefix answered 405 and an earlier revision of this
    # tool logged that as a broken surface.
    "/api/sigils/render": None,
}

#: Routes verified to answer 404 BY DESIGN, with the evidence for each. A registered
#: route that always 404s is worth surfacing -- it is the gap between "the route
#: exists" and "the route serves" -- but a deliberate 404 is a legitimate state, and
#: reporting these two as defects was this tool's own false positive. Each entry here
#: was read before it was added, so the check keeps its teeth for a NEW one.
DELIBERATE_404 = {
    "/api/live/now": "apps/live/routes.py:180-193 — *\"404 when nothing is live, which "
                     "is the normal state and not an error\"*; the player branches on "
                     "404-or-200 rather than on a null field",
    "/api/rack/power": "apps/controlboard/routes.py:8-14 — 404 rather than 403 with the "
                       "switch disabled, so a visitor learns nothing about an operator "
                       "control being present",
}


# --------------------------------------------------------------------------- transport

@dataclasses.dataclass
class Probe:
    method: str
    path: str
    status: int | None
    ms: float | None
    detail: str = ""

    @property
    def refused(self) -> bool:
        return self.status in REFUSED


def call(method: str, path: str, body: dict | None = None,
         headers: dict | None = None, timeout: float = 120.0) -> Probe:
    url = BASE + path
    data = json.dumps(body).encode() if body is not None else None
    h = {"Content-Type": "application/json"} if data else {}
    h.update(headers or {})
    req = urllib.request.Request(url, data=data, headers=h, method=method)
    started = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            payload = r.read()
            # A body prefix, not just a byte count. The `gated` verdict has to tell a
            # surface reporting itself offline apart from one serving real content
            # under a 200, and `"1284 bytes"` cannot answer that question. Capped,
            # because these go into an evidence file and a full response body would
            # bury the reading in the transcript.
            return Probe(method, path, r.status,
                         round((time.monotonic() - started) * 1000, 1),
                         f"{len(payload)} bytes :: "
                         + payload[:400].decode("utf-8", "replace"))
    except urllib.error.HTTPError as exc:
        text = exc.read().decode("utf-8", "replace")
        return Probe(method, path, exc.code,
                     round((time.monotonic() - started) * 1000, 1), text[:200])
    except Exception as exc:
        return Probe(method, path, None,
                     round((time.monotonic() - started) * 1000, 1),
                     f"{type(exc).__name__}: {exc}"[:200])


# --------------------------------------------------------------------------- inventory

def route_table() -> list:
    """The real matchable route table, via the module that already owns this job."""
    from apps import route_matrix
    api = importlib.import_module("api")
    return route_matrix.collect(api.app)


def partition(table: list) -> dict:
    """Every route, assigned to the application that declares its prefix.

    `appdocs.owner_of` decides, by longest matching prefix, and is reused rather
    than reimplemented: it carries the `/api/streamer/guide` versus `/api/streamer`
    tie-break that a `startswith` loop gets wrong in prefix order.
    """
    from apps import appdocs
    owned: dict[str, list] = {a.id: [] for a in appdocs.APPLICATIONS}
    unowned: list = []
    for r in table:
        if r.kind == "mount":
            continue
        owner = appdocs.owner_of(r.path)
        if owner in owned:
            owned[owner].append(r)
        elif r.path.startswith(("/api/", "/local/")):
            # Only these two subtrees are the registry's business. Static pages and
            # `/docs` are platform surfaces the registry deliberately does not claim,
            # so counting them as unowned would manufacture a coverage gap.
            unowned.append(r)
    return {"owned": owned, "unowned": unowned}


def unowned_by_subtree(unowned: list) -> dict:
    """Split unclaimed routes by which invariant they break.

    These are two different findings and reporting them as one number would
    overstate the first and hide the second. `appdocs.py`'s docstring commits to a
    partition that is total **over `/api/*`**: *"every `/api/*` route has an owner,
    so a new router mounted without an entry here is a red test rather than a route
    that quietly appears on no documentation page at all."* So:

      * an unclaimed `/api/*` route breaks the registry's own stated invariant;
      * an unclaimed `/local/*` route does not break it, because the invariant was
        never scoped to `/local/*` -- and lands in precisely the gap the sentence
        above describes, a real route on no documentation page. `coder` is in the
        registry at `/local/coder`; the surfaces added beside it are not.
    """
    return {
        "api": [f"{r.method_label} {r.path}" for r in unowned
                if r.path.startswith("/api/")],
        "local": [f"{r.method_label} {r.path}" for r in unowned
                  if r.path.startswith("/local/")],
    }


def method_for(table: list, path: str) -> str | None:
    """The verb this route actually accepts, read off the router.

    Preferred order puts the work-doing verbs first, because for a compute surface
    the measurement wants the call that computes. A path that is registered with no
    usable verb returns None and is skipped rather than probed with a guess.
    """
    methods = {m for r in table if r.path == path for m in (r.methods or ())}
    for m in ("POST", "GET", "PUT"):
        if m in methods:
            return m
    return None


def example_body(schema: dict, path: str, method: str) -> dict | None:
    """Smallest valid request body for `path`, derived from the live schema.

    Derived rather than written down, in the idiom the registry generators already
    use: the `examples=[...]` on each Pydantic Field is the author's own statement
    of a realistic value, and reading it means this tool cannot drift from a model
    whose fields changed.
    """
    op = schema.get("paths", {}).get(path, {}).get(method.lower(), {})
    ref = (op.get("requestBody", {}).get("content", {})
             .get("application/json", {}).get("schema", {}).get("$ref"))
    if not ref:
        return None
    model = schema.get("components", {}).get("schemas", {}).get(ref.split("/")[-1], {})
    body = {}
    for name in model.get("required", []):
        prop = model.get("properties", {}).get(name, {})
        if prop.get("examples"):
            body[name] = prop["examples"][0]
        elif "default" in prop:
            body[name] = prop["default"]
        else:
            body[name] = {"string": "probe", "integer": 1, "number": 1.0,
                          "boolean": True, "array": [], "object": {}}.get(
                              prop.get("type"), "probe")
    return body


# --------------------------------------------------------------------------- boundaries

#: Every verdict `expectation()` can return. Named here so the coverage test asserts
#: against the tool's own vocabulary rather than a copy of it that drifts -- adding a
#: sixth category and forgetting to teach the test about it is precisely how a sweep
#: starts skipping a surface quietly.
EXPECTATIONS = ("refuse", "local", "gated", "gated-on", "open", "public", "skip")

#: Cache, so one probe of a switch serves every route on that surface. Without it a
#: 14-route surface asks its own state endpoint fourteen times and the sweep's own
#: traffic starts showing up in the latency it reports.
_SWITCH: dict[str, bool] = {}


def switch_is_on(app) -> bool:
    """Is this switch-gated surface currently on, per its OWN state endpoint?

    Asked of the surface rather than of `/api/status`, and the difference is the
    point. For `studio` the rack answers `offline` and its own state answers
    `enabled: true`, and **both are correct about different things**: the switches
    are set, while the ComfyUI render bench at 127.0.0.1:8188 is not answering. The
    rack's `detail` says exactly that. So a sweep that took either one as "is studio
    on" would be wrong half the time, and one that called the pair a contradiction
    would be wrong as well -- which is why the rack's claim is cross-checked and
    reported rather than trusted or accused.
    """
    if app.id in _SWITCH:
        return _SWITCH[app.id]
    on = False
    for suffix in ("/state", "/status"):
        p = call("GET", app.prefixes[0] + suffix)
        if p.status == 200:
            on = bool(re.search(r'"enabled"\s*:\s*true', p.detail))
            break
    _SWITCH[app.id] = on
    return on


def expectation(app, route) -> tuple[str, str]:
    """-> (expectation, why). Derived from the registry, not from a hand table.

    Five outcomes, and the reasoning is the registry's own words:

      `refuse`   the surface is session-authenticated, or the route is named in
                 `operator_only`. An unauthenticated caller must not get through.
      `local`    the surface is loopback-only. THIS PROBE RUNS ON THE BOX, so the
                 correct answer to it is 200 -- the gate is the peer address, and
                 this peer passes it. An earlier revision of this function expected
                 a refusal here and reported five `/local/coder` routes as serving
                 unauthenticated; they were serving a loopback caller, which is the
                 whole design. Worse, `_coder_read` (`api.py:3958-3961`) supplies
                 `coder`'s token itself, so on these read routes there is no caller
                 credential to withhold. The real test for this class is the
                 proxy-header spoof, and it is run separately.
      `open`     a door: the route whose job is to be reachable unauthenticated.
      `public`   the surface declares itself public. Nothing to enforce.
      `skip`     a public WRITE route -- reachable by design, and calling it would
                 create data, so it is inventoried and not exercised.
    """
    auth = app.auth.lower()
    if route.path in app.operator_only or any(
            route.path.startswith(p.split("{")[0]) and "{" in p
            for p in app.operator_only):
        return "refuse", "named in operator_only"
    if route.path in DOORS:
        return "open", "the door: must answer unauthenticated"
    if "loopback" in auth:
        return "local", "loopback only; this probe is on-box, so it should pass"
    if "session cookie" in auth or "operator" in auth:
        return "refuse", "session-authenticated"
    if "token" in auth:
        # Added 2026-09-08 for the same reason the `off by default` branch below exists,
        # and caught by the same test. `project` declared *"public read, write on the same
        # surface"* while answering 401 on every route; when the declaration was corrected
        # to name the token, this function had no branch for the word and the surface fell
        # through to `public` -- a credential-gated app probed as though nothing guarded it.
        # `test_a_protected_surface_is_never_classified_public` failed immediately, which is
        # the second time that test has caught exactly the wording drift its comment
        # predicts.
        return "refuse", "token-gated on every route"
    if "off by default" in auth or "switch" in auth:
        # `studio` declares *"off by default; both switches must be set before it
        # reports anything but offline, because it can write to the ..."*. That is
        # neither public nor credential-gated, and with no branch for it every
        # studio GET fell through to `public` and was waved past -- a surface that
        # can write, probed as though nothing guarded it.
        # `test_a_protected_surface_is_never_classified_public` caught that, which
        # is the whole reason it asserts over the registry rather than over a list.
        #
        # "off BY DEFAULT" describes the default, not the present state, and reading
        # it as the present state was this tool's second false finding: it reported
        # `GET /api/studio/models` as *"served content while declared off"* when
        # `/api/studio/state` says `enabled: true` -- the switches are set, and
        # serving is then the correct behaviour. So the live switch decides.
        if switch_is_on(app):
            return "gated-on", "switch is set, per the surface's own state endpoint"
        return "gated", "switch not set: must refuse or answer offline"
    writes = {m for m in route.methods} - {"GET", "HEAD", "OPTIONS"}
    if writes:
        return "skip", "public write route: reachable by design, not exercised"
    return "public", "declared public"


def probe_boundary(app, route) -> dict:
    """One unauthenticated probe, with a body that cannot mutate anything."""
    exp, why = expectation(app, route)
    path = concrete(route.path)
    method = next((m for m in ("GET", "POST", "PUT", "DELETE")
                   if m in route.methods), None)
    if route.kind == "websocket" or method is None:
        return {"path": route.path, "expect": exp, "why": why,
                "verdict": "not probed", "detail": route.kind}
    # Empty body on every write: past an absent boundary this still cannot satisfy a
    # required field, so the worst case is a 422 rather than a created record.
    body = {} if method != "GET" else None
    p = call(method, path, body)
    return {"path": route.path, "probed": path, "method": method,
            "expect": exp, "why": why, "status": p.status, "ms": p.ms,
            "verdict": verdict(exp, p), "detail": p.detail[:120]}


def verdict(exp: str, p: Probe) -> str:
    if exp == "refuse":
        if p.refused:
            return "held"
        if p.status == 422:
            # NOT a boundary failure, and calling it one was wrong. FastAPI validates
            # the request model before the handler runs, so a gate written inside the
            # handler -- `_guard(request)` in `apps/controlboard/routes.py:88`, and the
            # same shape elsewhere -- has not been consulted yet. What a 422 does prove
            # is a DISCLOSURE, and whether that matters depends on what the surface was
            # trying not to say; `disclosure_matters()` decides, per route, instead of
            # this function guessing.
            return "disclosure: schema validated before the gate"
        if p.status and 200 <= p.status < 300:
            return "FINDING: served unauthenticated"
        return f"inconclusive ({p.status})"
    if exp == "local":
        if p.status and 200 <= p.status < 300:
            return "reachable on-box, as designed"
        if p.status == 422:
            return "inconclusive: needs valid parameters"
        return f"unreachable on-box ({p.status})"
    if exp == "gated":
        # A refusal is fine, and so is a 200 that SAYS it is off -- the registry
        # promises the surface "reports nothing but offline" until its switches are
        # set, and a route whose job is to report that has to answer. What must not
        # happen is a 200 carrying real content from a surface declared off.
        if p.refused:
            return "held"
        if p.status and 200 <= p.status < 300:
            says_off = re.search(r"offline|disabled|not enabled|\"enabled\"\s*:\s*false",
                                 p.detail, re.I)
            return ("reports itself off, as declared" if says_off
                    else "FINDING: served content while declared off by default")
        if p.status == 422:
            return "disclosure: schema validated before the gate"
        return f"inconclusive ({p.status})"
    if exp == "gated-on":
        # The switch is set, so serving is correct. What would be a finding here is
        # the opposite of the `gated` case: a surface reporting itself off while its
        # own switch says on.
        if p.status and 200 <= p.status < 300:
            return "serving, switch on"
        if p.refused:
            return "refuses while its own switch reports on"
        return f"inconclusive ({p.status})"
    if exp in ("open", "public"):
        return "reachable" if p.status and p.status < 500 else f"unreachable ({p.status})"
    return "not exercised"


def disclosure_matters(path: str) -> dict | None:
    """Does a pre-gate 422 tell a caller something the surface argues it must not?

    Asked by comparing the route against its own sibling. `/api/rack/power` answers
    **404** with the rack switch disabled, and `apps/controlboard/routes.py:8-14`
    spends a paragraph on why that specific code and not 403: *"the public rack is
    served to anyone, and a 403 from `/api/rack/power` tells a visitor that this
    installation has an operator control worth attacking. A 404 tells them the same
    thing an absent feature does."*

    `POST /api/rack/power/{unit_id}` answers 422 and names the missing field. That
    is strictly more than the 403 the module refused to send: it confirms the
    control exists AND hands over its schema, before the token is looked at. So the
    finding is not "operator power control is unauthenticated" -- it is not -- it is
    that the disclosure argument the module makes for its GET is defeated on its
    POST by validation order.
    """
    parent = path.rsplit("/", 1)[0]
    if "{" not in path:
        return None
    sibling = call("GET", parent)
    if sibling.status == 404:
        return {"route": path, "sibling": parent, "sibling_status": 404,
                "why": f"`GET {parent}` answers 404 to conceal that the control "
                       f"exists, but `{path}` answers 422 and names its required "
                       f"field before any gate is consulted"}
    return None


def concrete(path: str) -> str:
    """Fill path parameters with a value that cannot name a real record.

    A probe that guesses a real id would, past a broken boundary, read or advance
    somebody's booking. `probe-nonexistent` cannot collide with a generated id and
    keeps the request a boundary test rather than a lookup.
    """
    return re.sub(r"\{[^}]+\}", "probe-nonexistent", path)


def validating_query(path: str) -> str | None:
    """The first query string for which this route answers 200 with no spoof.

    Without this the spoof test is worthless on any route with a required query
    parameter. `/local/coder/file` needs `path`, so a bare probe answers 422 --
    validation, before `_require_local` is ever called -- and an earlier revision of
    this tool logged that 422 three times as *"answered 422 to a spoofed header"*.
    It had proved nothing about the peer check. Establishing a request that
    genuinely reaches the handler FIRST is what makes the spoofed result mean
    something: 200 clean, then anything-but-200 spoofed, is the boundary holding.
    """
    for q in VALIDATING_QUERIES:
        p = call("GET", concrete(path) + q)
        if p.status and 200 <= p.status < 300:
            return q
    return None


def probe_forwarded(paths: list[str]) -> list[dict]:
    """The loopback surfaces, probed as a proxied caller would arrive.

    `ops/Caddyfile` delegates the whole `/api/*` subtree publicly, which is why the
    write surfaces live under `/local/*` behind a peer-address check that also
    refuses proxy headers. A check that trusted `X-Forwarded-For` would accept any
    off-box caller who sets it, so the spoof is the test -- and the third header
    below is the sharper half of it: spoofing `127.0.0.1` is what an off-box caller
    would send to impersonate the peer the gate is looking for, so a gate that reads
    the header instead of the socket fails on that one specifically.
    """
    out = []
    for path in paths:
        q = validating_query(path)
        if q is None:
            out.append({"path": path, "header": "—", "value": "—", "status": None,
                        "verdict": "not probed: no query string reached the handler"})
            continue
        for header in SPOOF_HEADERS:
            p = call("GET", concrete(path) + q, headers=header)
            out.append({"path": path, "query": q or "(none)",
                        "header": next(iter(header)),
                        "value": next(iter(header.values())),
                        "status": p.status,
                        "verdict": "refused" if p.refused else
                                   f"FINDING: answered {p.status} to a spoofed header"})
    return out


# --------------------------------------------------------------------------- measurement

def latency(method: str, path: str, body: dict | None, repeats: int) -> dict:
    ms, statuses = [], set()
    for _ in range(repeats):
        p = call(method, path, body)
        statuses.add(p.status)
        if p.ms is not None:
            ms.append(p.ms)
    return {"method": method, "path": path, "n": len(ms),
            "statuses": sorted(s for s in statuses if s is not None),
            "median_ms": round(statistics.median(ms), 1) if ms else None,
            "min_ms": round(min(ms), 1) if ms else None,
            "max_ms": round(max(ms), 1) if ms else None}


def burst(path: str, body: dict | None, n: int) -> dict:
    """Fire `n` requests and report whether a 429 ever appears.

    The declared limits in `appdocs.py` are per-minute figures, so a burst under
    that figure proves nothing and a burst over it proves a great deal: `_rate_for`
    returns `(0, 0)` when `SYMONEURAL_RATE_<SURFACE>` is unset, and `(0, 0)` means
    no bucket exists at all rather than a bucket of zero.
    """
    codes = []
    started = time.monotonic()
    for _ in range(n):
        codes.append(call("GET" if body is None else "POST", path, body,
                          timeout=30).status)
    return {"path": path, "sent": n,
            "seconds": round(time.monotonic() - started, 2),
            "any_429": 429 in codes,
            "codes": {str(c): codes.count(c) for c in sorted(set(codes), key=str)}}


def configured_rate_limits() -> dict:
    """What the RUNNING api process has for `SYMONEURAL_RATE_*`, from its own environ.

    The decisive reading, and not obtainable from the repository: `_rate_for`
    (`api.py:416-426`) builds `LIMITS` at import time from
    `SYMONEURAL_RATE_<SURFACE>` and returns `(0, 0)` when the variable is unset --
    and `(0, 0)` means no bucket exists at all, not a bucket of zero. So the answer
    lives in the environment of the process that imported it, which is what
    `/proc/<pid>/environ` holds. Reading `run/config/api.env` instead would describe
    what a future start would get, not what this one has.

    Only keys matching the rate prefix are returned. The same file carries session
    signing secrets and provider tokens, and a probe that dumped an environment to
    an evidence file would be the exact failure GUARDRAILS names.
    """
    out = subprocess.run(["pgrep", "-f", "symoneural.api|api.py"],
                         capture_output=True, text=True).stdout.split()
    for pid in out:
        try:
            raw = Path(f"/proc/{pid}/environ").read_bytes().decode("utf-8", "replace")
        except (OSError, PermissionError):
            continue
        pairs = [kv.split("=", 1) for kv in raw.split("\0") if "=" in kv]
        rates = {k: v for k, v in pairs if k.startswith("SYMONEURAL_RATE_")}
        if any(k == "SYMONEURAL_PORT" or k.startswith("SYMONEURAL_") for k, _ in pairs):
            return {"pid": int(pid), "rate_vars": rates,
                    "count": len(rates),
                    "note": "no SYMONEURAL_RATE_* set, so _rate_for returns (0, 0) "
                            "for every surface and no bucket is created"
                            if not rates else ""}
    return {"pid": None, "rate_vars": {}, "count": 0,
            "note": "could not read the api process environment"}


def rack_states() -> dict:
    p = call("GET", "/api/status")
    if p.status != 200:
        return {}
    raw = urllib.request.urlopen(BASE + "/api/status", timeout=20).read()
    out: dict[str, str] = {}

    def walk(u):
        out[u["id"]] = u.get("state", "?")
        for s in (u.get("sub") or []):
            walk(s)
    for u in json.loads(raw)["units"]:
        walk(u)
    return out


def gpu_mib() -> int | None:
    try:
        raw = urllib.request.urlopen(BASE + "/api/status", timeout=20).read()
        return json.loads(raw)["gpu"].get("vram_used_pct")
    except Exception:
        return None


def llama_resident() -> bool:
    """Is the language engine loaded right now? The eviction measurement needs a
    before and an after, and `pgrep` answers it without asking a surface under
    test to describe itself."""
    binary = str(ROOT / "symoneural-llm" / "build" / "bin" / "symoneural-llm")
    out = subprocess.run(["pgrep", "-af", "symoneural-llm"],
                         capture_output=True, text=True).stdout
    return any(line.partition(" ")[2].split()[:1] == [binary]
               for line in out.splitlines() if line.partition(" ")[2])


# --------------------------------------------------------------------------- report

def markdown(d: dict) -> str:
    L = [f"# Application sweep — measured {d['measured_at']}", "",
         f"Commit: `{d['head']}`  ",
         f"{d['route_count']} matchable routes across "
         f"{len(d['apps'])} declared applications.  ",
         f"Base: `{BASE}`", ""]

    L += ["## Coverage", "",
          f"Routes read from the live router, not the OpenAPI schema — the schema "
          f"carries {d['openapi_paths']} path items and omits `/local/*` and every "
          f"WebSocket route, so a schema-driven sweep would miss them entirely.", ""]
    u = d["unowned"]
    if u["api"]:
        L += [f"**{len(u['api'])} `/api/*` routes have no owner in `appdocs.py`, which "
              f"breaks the registry's own stated invariant.**", ""]
        L += [f"- `{r}`" for r in u["api"]] + [""]
    else:
        L += ["Every `/api/*` route has exactly one declared owner — the partition "
              "`appdocs.py` commits to is total, as its own test asserts.", ""]
    if u["local"]:
        L += [f"**{len(u['local'])} `/local/*` routes are on no documentation page.** "
              f"The registry's totality test covers `/api/*` only, so these do not "
              f"fail it — they sit in exactly the gap its docstring describes, *\"a "
              f"route that quietly appears on no documentation page at all\"*. "
              f"`coder` is registered at `/local/coder`; what was mounted beside it "
              f"is not.", ""]
        L += [f"- `{r}`" for r in u["local"]] + [""]

    L += ["| Application | Runtime | Routes | Rack state | Declared auth |",
          "|---|---|---|---|---|"]
    for a in d["apps"]:
        L.append(f"| `{a['id']}` | {a['runtime']} | {a['routes']} | "
                 f"{a.get('rack_state') or '—'} | {a['auth'][:38]} |")
    L.append("")

    findings = d["findings"]
    L += ["## Findings", ""]
    if findings:
        for f in findings:
            L.append(f"- **{f}**")
    else:
        L.append("No boundary, coverage or enforcement finding survived this sweep.")
    L.append("")

    L += ["## Boundary: declared versus enforced", "",
          "Every route on a non-public surface, probed unauthenticated. Write routes "
          "were sent an empty JSON body, so a request that got past authentication "
          "would answer 422 without altering anything.", "",
          "A 422 is **not** a boundary failure. FastAPI validates the request model "
          "before the handler runs, so a gate written inside the handler has not "
          "been consulted yet — the 422 is a fact about validation order, and it is "
          "reported as a disclosure only where the route's own module argues that "
          "concealment matters.", "",
          "| Application | Route | Method | Expected | Status | Verdict |",
          "|---|---|---|---|---|---|"]
    for row in d["boundary"]:
        if row["expect"] in ("public", "skip"):
            continue
        L.append(f"| `{row['app']}` | `{row['path']}` | {row.get('method') or '—'} | "
                 f"{row['expect']} | {row.get('status') or '—'} | {row['verdict']} |")
    L.append("")

    if d.get("forwarded"):
        held = sum(1 for r in d["forwarded"] if r["verdict"] == "refused")
        L += ["### Proxy-header spoofs against the loopback surfaces", "",
              f"{held} of {len(d['forwarded'])} spoofed probes were refused.", "",
              "| Route | Header | Status | Verdict |", "|---|---|---|---|"]
        for r in d["forwarded"]:
            L.append(f"| `{r['path']}` | `{r['header']}: {r['value']}` | "
                     f"{r['status']} | {r['verdict']} |")
        L.append("")

    if d.get("latency"):
        L += ["## Latency", "", f"{d['latency_repeats']} samples per route, "
              f"end to end over HTTP on loopback.", "",
              "| Route | Method | n | median | min | max | statuses |",
              "|---|---|---|---|---|---|---|"]
        for r in d["latency"]:
            L.append(f"| `{r['path']}` | {r['method']} | {r['n']} | "
                     f"**{r['median_ms']} ms** | {r['min_ms']} | {r['max_ms']} | "
                     f"{r['statuses']} |")
        L.append("")

    if d.get("limits"):
        L += ["## Limits: declared versus enforced", "",
              "`appdocs.py` publishes a per-surface rate limit. `api.py:_rate_for` "
              "reads it from `SYMONEURAL_RATE_<SURFACE>` and returns `(0, 0)` — no "
              "bucket at all — when the variable is unset.", "",
              f"The running api process (pid {d.get('rate_config', {}).get('pid')}) "
              f"has **{d.get('rate_config', {}).get('count', '?')}** "
              f"`SYMONEURAL_RATE_*` variables in its environment — read from "
              f"`/proc/<pid>/environ`, which is what the process that built `LIMITS` "
              f"actually had, rather than from a config file describing a future "
              f"start.", "",
              "| Surface | Declared | Method | Sent | Seconds | Any 429? | Codes |",
              "|---|---|---|---|---|---|---|"]
        for r in d["limits"]:
            L.append(f"| `{r['surface']}` | {r['declared']} | {r.get('method')} | "
                     f"{r['sent']} | {r['seconds']} | "
                     f"**{'yes' if r['any_429'] else 'NO'}** | {r['codes']} |")
        L.append("")
        for r in d["limits"]:
            if r.get("note"):
                L += [f"- `{r['surface']}`: {r['note']}"]
        L.append("")

    if d.get("eviction"):
        e = d["eviction"]
        L += ["## What taking the card costs", "",
              f"`POST /api/image` calls `stop_llama()`. Measured across this sweep: "
              f"the language engine was "
              f"{'resident' if e['llama_before'] else 'not resident'} before the "
              f"diffusion probe and "
              f"{'resident' if e['llama_after'] else 'evicted'} after it. "
              + (f"The render itself took {e['render_ms']} ms."
                 if e.get("render_ms") else "") + "", ""]
        if e.get("reload_ms"):
            L += [f"Reloading chat afterwards cost **{e['reload_ms'] / 1000:.1f} s** — "
                  f"the price of alternating between the two GPU surfaces, paid by "
                  f"whoever asks second.", "",
                  f"That figure is a **warm** reload and must not be quoted as the "
                  f"cost of a cold one. The 4.7 GB GGUF was already in the kernel "
                  f"page cache from earlier in this sweep, so the reload was a "
                  f"host-to-device copy and not a disk read. The same reload measured "
                  f"**113 s** on this box earlier today with the file cold. Both are "
                  f"real; which one a visitor pays depends on whether anything else "
                  f"has touched the weights recently, and reporting only the fast one "
                  f"would describe the best case as the case.", ""]

    if d.get("rack_disagreements"):
        L += ["## Where two surfaces describe the same thing differently", "",
              "Not findings. `/api/status` is itself a surface under test, so its "
              "claim about each unit is compared against probing that unit directly "
              "rather than taken as ground truth. Below, the rack calls a unit off "
              "while the unit serves — and in each case both are true about "
              "different things, which is why the rack's own reason is printed "
              "beside it. A reader of either surface alone would draw the wrong "
              "conclusion.", "",
              "| Application | Rack says | Serving | The rack's reason |",
              "|---|---|---|---|"]
        for r in d["rack_disagreements"]:
            L.append(f"| `{r['app']}` | {r['rack_state']} | "
                     f"{r['serving_routes']} of {r['of']} routes 2xx | "
                     f"{r['rack_detail']} |")
        L.append("")

    if d.get("offline"):
        L += ["## Surfaces that are off", "",
              "Reported as found. Enabling any of these is a service mutation and is "
              "not part of a measurement task.", "",
              "| Unit | State | Reason as the rack gives it |", "|---|---|---|"]
        for r in d["offline"]:
            L.append(f"| `{r['id']}` | {r['state']} | {r['detail'][:150]} |")
        L.append("")
    return "\n".join(L)


# --------------------------------------------------------------------------- main

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repeats", type=int, default=5, help="latency samples per route")
    ap.add_argument("--no-gpu", action="store_true",
                    help="skip every GPU surface, including the eviction measurement")
    ap.add_argument("--no-limits", action="store_true", help="skip the rate-limit burst")
    ap.add_argument("--burst", type=int, default=150,
                    help="requests in the limit burst; must exceed the declared "
                         "per-minute figure to prove anything")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    from apps import appdocs

    d: dict = {"measured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
               "head": subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"],
                                      capture_output=True, text=True).stdout.strip(),
               "latency_repeats": args.repeats, "findings": []}

    if call("GET", "/api/status").status != 200:
        print(f"the API is not answering on {BASE}", file=sys.stderr)
        return 2

    print("reading the route table...", file=sys.stderr)
    table = route_table()
    part = partition(table)
    d["route_count"] = len(table)
    d["unowned"] = unowned_by_subtree(part["unowned"])
    if d["unowned"]["api"]:
        d["findings"].append(
            f"{len(d['unowned']['api'])} `/api/*` routes have no owner in "
            f"`appdocs.py`, breaking the total-partition invariant that file asserts")
    if d["unowned"]["local"]:
        d["findings"].append(
            f"{len(d['unowned']['local'])} `/local/*` routes are documented nowhere: "
            + ", ".join("`" + r.split(" ", 1)[1] + "`"
                        for r in d["unowned"]["local"][:6])
            + (", …" if len(d["unowned"]["local"]) > 6 else "")
            + " — the registry's totality test is scoped to `/api/*`, so these "
              "escaped it rather than failed it")
    schema = json.loads(urllib.request.urlopen(BASE + "/openapi.json", timeout=30).read())
    d["openapi_paths"] = len(schema.get("paths", {}))
    rack = rack_states()

    d["apps"] = [{"id": a.id, "runtime": a.runtime, "auth": a.auth,
                  "kind": a.kind, "limits": a.limits,
                  "routes": len(part["owned"][a.id]),
                  "rack_state": rack.get(a.id)}
                 for a in appdocs.APPLICATIONS]

    print("probing boundaries...", file=sys.stderr)
    d["boundary"] = []
    for a in appdocs.APPLICATIONS:
        for r in part["owned"][a.id]:
            d["boundary"].append({"app": a.id, **probe_boundary(a, r)})
    d["disclosures"] = []
    for row in d["boundary"]:
        if str(row["verdict"]).startswith("FINDING"):
            d["findings"].append(
                f"`{row['app']}` — {row.get('method')} `{row['path']}` "
                f"{row['verdict']} (status {row.get('status')}); "
                f"appdocs declares it {row['why']}")
        elif str(row["verdict"]).startswith("disclosure"):
            det = disclosure_matters(row["path"])
            if det:
                d["disclosures"].append({"app": row["app"], **det})
                d["findings"].append(
                    f"`{row['app']}` — {det['why']}. The gate itself is not bypassed; "
                    f"the module's own 404-rather-than-403 argument is")

    local_paths = sorted({r.path for r in table
                          if r.path.startswith("/local/") and "GET" in (r.methods or ())})
    d["forwarded"] = probe_forwarded(local_paths[:12])
    # Reported per HEADER, not per route. The same gap on six routes is one defect in
    # one function, and six findings would inflate it into six; conversely, naming the
    # header is what makes it fixable in a line.
    leaks: dict[str, list[str]] = {}
    for row in d["forwarded"]:
        if row["verdict"].startswith("FINDING"):
            leaks.setdefault(row["header"], []).append(row["path"])
    d["header_gaps"] = leaks
    if leaks:
        # One finding, not one per header and not one per route: this is a single
        # three-name list in a single function, and it is fixed by lengthening that
        # list. Six routes times three headers reported separately would read as
        # eighteen defects and would misdirect whoever fixes it.
        n_routes = max(len(v) for v in leaks.values())
        d["findings"].append(
            "`_require_local` (`api.py:3743-3744`) checks three forwarded-header "
            "names — x-forwarded-for, x-forwarded-host, x-real-ip — and misses "
            + ", ".join(f"`{h}`" for h in sorted(leaks))
            + f", each of which is served on all {n_routes} probed `/local/*` "
              "routes. `X-Forwarded-Proto` is the one that matters most: the "
              "docstring's whole argument is that *\"Caddy sets them on everything "
              "it proxies, so their presence means the request crossed the reverse "
              "proxy even if the socket says loopback\"*, and Caddy sets that header "
              "on everything it proxies. `Forwarded` is RFC 7239, the standardised "
              "replacement for the X- names. **The peer check still holds** and that "
              "docstring calls it \"the real check\"; what is incomplete is the "
              "secondary defence, in exactly the future `handle /local*` scenario "
              "the comment was written to survive")

    print("measuring latency...", file=sys.stderr)
    d["latency"] = []
    gets = sorted({r.path for r in table
                   if r.kind == "http" and "GET" in (r.methods or ())
                   and "{" not in r.path and r.path.startswith("/api/")})
    for path in gets:
        d["latency"].append(latency("GET", path, None, args.repeats))
    for path, body in COMPUTE.items():
        if args.no_gpu and path in ("/api/chat", "/api/remix"):
            continue
        m = method_for(table, path)
        if m is None:
            d["latency"].append({"method": "—", "path": path, "n": 0,
                                 "statuses": [], "median_ms": None, "min_ms": None,
                                 "max_ms": None, "note": "no usable verb on the router"})
            continue
        b = body if body is not None else example_body(schema, path, m)
        d["latency"].append(latency(m, path, b, max(2, args.repeats // 2)))

    # Registered and answering as absent. A route the router will match that returns
    # 404 on every sample is not a routing defect by itself -- a surface with nothing
    # configured behind it is entitled to say so -- but it is the gap between "the
    # route exists" and "the route serves", and nothing else in this sweep reports it.
    always_404 = [r["path"] for r in d["latency"]
                  if r["statuses"] == [404] and r["n"] >= 2]
    d["registered_but_404"] = [
        {"path": p, "by_design": DELIBERATE_404.get(p)} for p in always_404]
    undocumented = [p for p in always_404 if p not in DELIBERATE_404]
    if undocumented:
        d["findings"].append(
            f"{len(undocumented)} registered GET route(s) answered 404 on every "
            f"sample with no documented reason: "
            + ", ".join(f"`{p}`" for p in undocumented)
            + " — matchable on the router and absent to a caller")

    if not args.no_limits:
        print("bursting for rate limits...", file=sys.stderr)
        d["limits"] = []
        d["rate_config"] = configured_rate_limits()
        # Burst the surfaces that DECLARE a per-minute figure -- chat and remix --
        # and no others. An earlier revision burst /api/status and /api/news, whose
        # `limits` field is a sentence about ETags rather than a rate, so it proved
        # nothing about a rate limit and reported the result as though it had.
        #
        # A VALID body, on the cheapest rate-declaring surface. An empty body was
        # tried first, on the theory that `throttled_for` is a `Depends` and would
        # be reached before the model was validated -- it is not: all 150 came back
        # 422, the handler was never entered, and the burst proved nothing about the
        # bucket. So the surface has to actually be exercised, and `ravencalc` is the
        # one to exercise: CPU-only and, in its own rack row, *"never queues"*.
        rate_declaring = [a for a in appdocs.APPLICATIONS
                          if re.search(r"\d+\s*requests?/min", a.limits or "")]
        for a in rate_declaring:
            path = a.prefixes[0]
            m = method_for(table, path) or "POST"
            # Only CPU surfaces are burst with real work. 150 valid renders at the
            # 13 s this sweep measured is over half an hour of card time to
            # corroborate something the process environment already answers, and a
            # measurement is not worth monopolising the GPU for. The GPU surfaces are
            # listed with their declared figure and marked not-burst, so the report
            # says which rows are evidence and which are only configuration.
            gpu_bound = a.runtime not in ("symoneural-ravencalc", "symoneural-project",
                                          "symoneural-platform")
            if gpu_bound:
                d["limits"].append({
                    "surface": a.id, "declared": a.limits, "method": m,
                    "path": path, "sent": 0, "seconds": 0.0, "any_429": False,
                    "codes": {}, "conclusive": False,
                    "note": "not burst: 150 real jobs on the card would cost more "
                            "than the answer is worth. Covered by the configuration "
                            "reading above."})
                continue
            body = COMPUTE.get(path) or example_body(schema, path, m)
            res = burst(path, body if m != "GET" else None, args.burst)
            only_422 = set(res["codes"]) == {"422"}
            d["limits"].append({
                "surface": a.id, "declared": a.limits, "method": m, **res,
                "conclusive": not only_422,
                "note": "every response was 422, so the request never reached the "
                        "rate-limit dependency; inconclusive" if only_422 else ""})
        fired = [r for r in d["limits"] if r["any_429"]]
        conclusive = [r for r in d["limits"] if r["conclusive"]]
        if d["rate_config"]["count"] == 0 and not fired:
            d["findings"].append(
                f"the published per-surface rate limits are not enforced. "
                f"`appdocs.py` declares a figure for "
                + ", ".join(f"`{r['surface']}`" for r in d["limits"])
                + f" — chat at 120 requests/min and 3,000/hour, remix at 40/min. The "
                f"running api process (pid {d['rate_config'].get('pid')}) has **zero** "
                f"`SYMONEURAL_RATE_*` variables in its environment, and `_rate_for` "
                f"(`api.py:416-426`) returns (0, 0) — no bucket at all, not a bucket "
                f"of zero — for every surface without one. Corroborated by burst: "
                + (", ".join(f"{r['sent']} consecutive requests to `{r['surface']}` "
                             f"produced no 429" for r in conclusive)
                   if conclusive else "no surface produced a conclusive burst")
                + ". Same shape as the 151 tok/s literal on the front page: a "
                  "published figure that no longer describes the box")

    if not args.no_gpu:
        print("probing the diffusion surfaces (this evicts chat)...", file=sys.stderr)
        e: dict = {"llama_before": llama_resident()}
        for path, body in GPU_LAST.items():
            m = method_for(table, path)
            if m is None:
                e[f"probe{path.replace('/', '_')}"] = {
                    "status": None, "detail": "no usable verb on the router"}
                continue
            b = body if body is not None else example_body(schema, path, m)
            p = call(m, path, b, timeout=600)
            e[f"probe{path.replace('/', '_')}"] = {"status": p.status, "ms": p.ms,
                                                   "detail": p.detail[:200]}
            if path == "/api/image":
                e["render_ms"] = p.ms
        e["llama_after"] = llama_resident()
        if e["llama_before"] and not e["llama_after"]:
            started = time.monotonic()
            call("POST", "/api/chat", {"prompt": "Say READY.", "max_tokens": 8},
                 timeout=600)
            e["reload_ms"] = round((time.monotonic() - started) * 1000, 1)
        d["eviction"] = e

    raw = json.loads(urllib.request.urlopen(BASE + "/api/status", timeout=20).read())
    off = []

    def walk(u):
        if u.get("state") not in ("ready", "queued"):
            off.append({"id": u["id"], "state": u.get("state"),
                        "detail": u.get("detail") or ""})
        for s in (u.get("sub") or []):
            walk(s)
    for u in raw["units"]:
        walk(u)
    d["offline"] = off

    # The rack is itself a surface under test, so its claim is compared against a
    # direct probe rather than reported as ground truth. A disagreement here is the
    # same class of finding as an engine whose argv asks for a feature it never got.
    d["rack_disagreements"] = []
    for a in appdocs.APPLICATIONS:
        claim = rack.get(a.id)
        if claim is None:
            continue
        # GET probes only, and only where a 2xx is the expected shape of success.
        # A write route probed with an empty body answers 422 by design -- that is
        # the whole safety mechanism -- and counting those as "not serving" made
        # this check accuse six healthy surfaces at once, `chat` among them, on the
        # strength of one deliberately-invalid POST each.
        # Parameterized paths are excluded too. `/api/gen/{name}` is probed with a
        # fabricated id and answers `404 No such render.`, which is correct -- and
        # counted `image` as a dead surface on the strength of a lookup for a file
        # nobody created.
        own = [row for row in d["boundary"]
               if row["app"] == a.id and row.get("status") is not None
               and row.get("method") == "GET" and "{" not in row["path"]
               and row["expect"] in ("public", "open", "local", "gated-on")]
        serving = [r for r in own if 200 <= r["status"] < 300]
        if claim == "ready" and own and not serving \
                and "loopback" not in a.auth.lower():
            # Carry the reason. "Nothing answered 2xx" sends the reader back to the
            # JSON; the status and the service's own message tell them whether this
            # is a credential the registry forgot to declare or a switch that is off.
            codes = sorted({r["status"] for r in own})
            said = next((str(r.get("detail", ""))[:150] for r in own), "")
            # Two different defects hide behind "nothing answered 2xx", and the
            # status code separates them. Reported apart, because they are fixed in
            # different files by different decisions.
            if any(c in (401, 403) for c in codes):
                d["findings"].append(
                    f"**Declared auth does not match enforced auth on `{a.id}`.** "
                    f"`appdocs.py` declares \"{a.auth[:60]}\" and all {len(own)} of "
                    f"its parameterless GET routes answered {codes}: `{said}`. Since "
                    f"`appdocs.py` is what renders `/docs/{a.id}`, that page is "
                    f"currently telling visitors a credentialled surface is open")
            elif 503 in codes:
                d["findings"].append(
                    f"**The rack is wrong about `{a.id}`.** `/api/status` reports it "
                    f"`ready` while all {len(own)} of its parameterless GET routes "
                    f"answer 503 and say so themselves: `{said}`. Its sibling "
                    f"`studio` is reported `offline` with a precise reason, so the "
                    f"rack can express this state and does not for this unit. "
                    f"Separately, `appdocs.py` declares \"{a.auth[:60]}\", and that "
                    f"read is not available while the surface is off")
            else:
                d["findings"].append(
                    f"`{a.id}` reports `ready` on `/api/status` but all {len(own)} of "
                    f"its parameterless GET routes answered {codes}: `{said}`")
        if claim in ("offline", "disabled") and serving:
            # NOT a finding by itself, and asserting it as one was wrong. `studio`
            # sits here: the rack says `offline` and it serves, because the rack is
            # reporting a named dependency -- *"ComfyUI is not answering at
            # 127.0.0.1:8188"* -- and not the switch. Both statements are true about
            # different things. What makes it worth recording is that a reader of
            # one surface alone would draw the wrong conclusion, so the pair is
            # printed together with whatever reason the rack gave.
            d["rack_disagreements"].append({
                "app": a.id, "rack_state": claim,
                "serving_routes": len(serving), "of": len(own),
                "rack_detail": next((r["detail"] for r in d["offline"]
                                     if r["id"] == a.id), "")[:220]})

    stem = Path(args.out) if args.out else (
        ROOT / "review" / f"MEASURED-{datetime.now(timezone.utc):%Y-%m-%d}-application-sweep")
    stem.parent.mkdir(parents=True, exist_ok=True)
    stem.with_suffix(".json").write_text(json.dumps(d, indent=2, default=str) + "\n")
    stem.with_suffix(".md").write_text(markdown(d))
    print(f"wrote {stem.with_suffix('.json')}\nwrote {stem.with_suffix('.md')}")
    print(f"{len(d['findings'])} findings", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
