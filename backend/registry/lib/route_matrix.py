"""Enumerate the REAL registered route table of backend/server.py, and classify a
list of expected endpoints against it.

Why this file exists
--------------------
On 2026-08-26 a "25 broken endpoints" report was produced by sending GET to
every path in a list. Most of those paths are POST-only, so every one of them
answered 404/405 and the report read as a site-wide routing failure. It was a
bad test, not a bad site.

The lesson is not "be more careful" -- it is that a route list must be READ FROM
THE ROUTER, never inferred from a UI label or a curl transcript. That is what
this module does: it imports the app object that `symoneural-api` actually
serves and walks `app.routes`, which is the same structure Starlette matches
requests against. If a path is not in here, no request can ever reach it; if it
is in here, its methods are the only methods that can succeed.

WebSocket routes are included. They never appear in `openapi.json` -- FastAPI's
schema generator skips them -- so an OpenAPI-based inventory would have reported
`/api/ws` as NOT REGISTERED, which is exactly the false negative that started
this. Routes with `include_in_schema=False` are likewise invisible to OpenAPI
and visible here.

Usage:
    python3 -m apps.route_matrix              # dump the full table
    python3 -m apps.route_matrix --classify   # classify EXPECTED against it
"""

from __future__ import annotations

import dataclasses
import importlib
import json
import sys
from typing import Iterable

# The endpoints the 2026-08-26 report claimed were broken. Kept verbatim, in the
# order given, so the classification can be read straight down against it.
EXPECTED: tuple[str, ...] = (
    "/api/accounts",
    "/api/accounts/logout",
    "/api/accounts/password",
    "/api/accounts/signout-everywhere",
    "/api/asicminer/emulator",
    "/api/asicminer/scan",
    "/api/chat",
    "/api/exp",
    "/api/gpuminer/control",
    "/api/image",
    "/api/rack/power",
    "/api/ravencalc",
    "/api/remix",
    "/api/sigils",
    "/api/streamer",
    "/api/streamer/epg",
    "/api/streamer/guide/filter",
    "/api/streamer/playlist",
    "/api/streamer/session",
    "/api/streamer/tune",
    "/api/streamer/xtream/channels",
    "/api/studio",
    "/api/train",
    "/api/ws",
    "/local/coder",
)


@dataclasses.dataclass(frozen=True)
class Route:
    """One entry of the router, flattened.

    `methods` is empty for a WebSocket route -- Starlette's WebSocketRoute has no
    `.methods` attribute at all, and inventing "GET" for it would erase the one
    distinction that matters when classifying `/api/ws`.
    """

    path: str
    methods: tuple[str, ...]
    kind: str  # "http" | "websocket" | "mount" | "other"
    handler: str

    @property
    def method_label(self) -> str:
        if self.kind == "websocket":
            return "WEBSOCKET"
        # HEAD is auto-added by Starlette beside every GET and says nothing about
        # the application; showing it doubles the table for no information.
        shown = [m for m in self.methods if m != "HEAD"]
        return ",".join(sorted(shown)) if shown else "-"


def _handler_name(route: object) -> str:
    """Best available identity for whoever answers this route.

    `endpoint.__module__` is the useful half: it names the file the handler was
    defined in, which is how a route is traced back to the app that registered
    it (`dispatchos.router`, `apps.accounts`, `__main__`/`api`). The
    function name alone would be ambiguous -- half the apps define `status`.
    """
    ep = getattr(route, "endpoint", None) or getattr(route, "app", None)
    if ep is None:
        return "?"
    mod = getattr(ep, "__module__", "?")
    name = getattr(ep, "__name__", type(ep).__name__)
    return f"{mod}.{name}"


def collect(app: object) -> list[Route]:
    """Walk `app.routes`, descending into Mounts.

    Mounts are recursed because a mounted sub-application's routes are real,
    matchable paths -- they are simply stored one level down. A non-recursive
    walk would report the mount prefix and call everything underneath it
    unregistered.
    """
    out: list[Route] = []

    def walk(routes: Iterable[object], prefix: str) -> None:
        for r in routes:
            path = prefix + str(getattr(r, "path", ""))
            cls = type(r).__name__
            if cls == "Mount":
                out.append(Route(path, (), "mount", _handler_name(r)))
                sub = getattr(getattr(r, "app", None), "routes", None)
                if sub:
                    walk(sub, path)
                continue
            if cls in ("WebSocketRoute", "APIWebSocketRoute"):
                out.append(Route(path, (), "websocket", _handler_name(r)))
                continue
            methods = tuple(getattr(r, "methods", ()) or ())
            kind = "http" if methods else "other"
            out.append(Route(path, methods, kind, _handler_name(r)))

    walk(getattr(app, "routes", []), "")
    out.sort(key=lambda r: (r.path, r.method_label))
    return out


# Classification vocabulary, fixed by the 2026-08-26 instruction. The point of
# separating the middle three from NOT REGISTERED is that only the last one is a
# routing defect; the others are a test that asked the wrong question.
EXACT = "REGISTERED EXACTLY"
DIFF_PATH = "REGISTERED UNDER DIFFERENT PATH"
WEBSOCKET = "WEBSOCKET"
NOT_REG = "NOT REGISTERED"


def classify(expected: str, table: list[Route]) -> tuple[str, str, str]:
    """-> (verdict, methods, detail).

    Trailing-slash equivalence is deliberate: Starlette redirects `/x` to `/x/`
    (307) when only the latter is registered, so the request DOES reach the
    handler and calling it "not registered" would be false.
    """
    exact = [r for r in table if r.path.rstrip("/") == expected.rstrip("/")]
    if exact:
        ws = [r for r in exact if r.kind == "websocket"]
        if ws:
            return WEBSOCKET, "WEBSOCKET", ws[0].handler
        methods = sorted({m for r in exact for m in r.methods if m != "HEAD"})
        return EXACT, ",".join(methods), exact[0].handler

    # Not at that exact path. Is it registered as a prefix of one -- i.e. does
    # the feature exist but under a longer path than the report assumed? That is
    # the difference between "Sigils is missing" and "Sigils lives at
    # /api/sigils/packs and the report guessed the collection root".
    under = [r for r in table if r.path.startswith(expected.rstrip("/") + "/")]
    if under:
        sample = ", ".join(
            f"{r.method_label} {r.path}" for r in under[:6]
        ) + (" …" if len(under) > 6 else "")
        return DIFF_PATH, "-", sample
    return NOT_REG, "-", ""


def main(argv: list[str]) -> int:
    sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parents[1]))
    app = importlib.import_module("api").app
    table = collect(app)

    if "--json" in argv:
        print(json.dumps([dataclasses.asdict(r) | {"method_label": r.method_label}
                          for r in table], indent=2))
        return 0

    if "--classify" in argv:
        width = max(len(e) for e in EXPECTED)
        for e in EXPECTED:
            verdict, methods, detail = classify(e, table)
            print(f"{e.ljust(width)}  {verdict.ljust(32)}  {methods.ljust(22)}  {detail}")
        return 0

    for r in table:
        print(f"{r.method_label.ljust(24)}  {r.path.ljust(46)}  {r.handler}")
    print(f"\n{len(table)} routes", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
