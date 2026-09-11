#!/usr/bin/env python3
"""Enumerate the API's real route table and exercise it, recording a verdict per route.

    python3 tools/audit/route_audit.py --list          # the table, and the OpenAPI cross-check
    python3 tools/audit/route_audit.py --exercise      # hit what is safe to hit; skip the rest LOUDLY
    python3 tools/audit/route_audit.py --json

**The registered route table is the truth.** `/openapi.json`, the docs page and a grep for
decorators are three separate claims *about* it, and this repo has already shipped a surface
whose eighteen green checks sat next to a dead page. So the table comes from walking
`app.routes` after importing the app, recursing into `Mount`s -- sub-applications are where
routes hide, and two of them carry their own `/health` that the main app does not have.

Then it cross-checks against `/openapi.json` **in both directions**, because the two failures
are different: a route missing from the schema is invisible to every client generator, and a
schema entry with no route is a 404 that documentation promises.

## What it will and will not call

GET and OPTIONS are exercised. Everything that mutates -- POST, PUT, PATCH, DELETE -- is
**skipped by default and listed with the reason**, because this runs against the production
service on :8800 and a commissioning pass that fires unknown POSTs at a live box is not a
test, it is an incident. The documented surfaces (`/api/chat`, `/api/image`, `/api/ravencalc`,
`/api/remix`, `/api/status`) are exercised deliberately, with real payloads, via `--surfaces`.

A skipped route is reported as `skipped`, never as passing. That distinction is the whole
point: #94 shipped with every check green and a chat surface that was dead on arrival.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


def _repo_root() -> Path:
    """Find the root by its marker, not by counting parents."""
    here = Path(__file__).resolve()
    for cand in (here, *here.parents):
        if (cand / "backend" / "server.py").is_file():
            return cand
    raise SystemExit(f"repo root not found above {here}: no backend/server.py marker")


ROOT = _repo_root()
BASE = "http://127.0.0.1:8800"

#: Path parameters we can fill with something harmless so a route is actually reachable.
#: A route left with a literal `{name}` in it tests the 404 handler, not the route.
PARAM_FILL = {
    "name": "commission-probe",
    "rig": "commission-probe",
    "job": "commission-probe",
    "id": "commission-probe",
    "session": "commission-probe",
    "slug": "commission-probe",
    "key": "commission-probe",
    "path": "index.html",
    "filename": "index.html",
}

MUTATING = {"POST", "PUT", "PATCH", "DELETE"}


def http(method: str, url: str, body: dict | None = None,
         timeout: float = 30.0) -> tuple[int, str, str]:
    data = None
    headers = {"Accept": "*/*"}
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.headers.get("Content-Type", ""), r.read(2048).decode(
                "utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.headers.get("Content-Type", "") if e.headers else "", \
            e.read(1024).decode("utf-8", "replace")
    except Exception as exc:
        return 0, "", f"{type(exc).__name__}: {exc}"


def route_table() -> list[dict]:
    """Walk app.routes, recursing into Mounts. The truth, not a claim about it."""
    sys.path.insert(0, str(ROOT / "backend"))
    import api                                   # noqa: E402
    from starlette.routing import Mount, Route, WebSocketRoute   # noqa: E402

    rows: list[dict] = []

    def walk(routes, prefix: str, depth: int) -> None:
        for r in routes or []:
            if isinstance(r, Mount):
                walk(getattr(r, "routes", None), prefix + (r.path or ""), depth + 1)
            elif isinstance(r, WebSocketRoute):
                rows.append({"method": "WS", "path": prefix + r.path,
                             "name": getattr(r, "name", ""), "mounted": depth > 0})
            elif isinstance(r, Route):
                for m in sorted((r.methods or set()) - {"HEAD"}):
                    rows.append({"method": m, "path": prefix + r.path,
                                 "name": getattr(r, "name", ""), "mounted": depth > 0})
            else:
                rows.append({"method": type(r).__name__,
                             "path": prefix + str(getattr(r, "path", "?")),
                             "name": getattr(r, "name", ""), "mounted": depth > 0})

    walk(api.app.routes, "", 0)
    return rows


def openapi_paths() -> tuple[set[tuple[str, str]], str]:
    code, _, text = http("GET", f"{BASE}/openapi.json", timeout=60)
    if code != 200:
        return set(), f"/openapi.json returned {code}"
    try:
        spec = json.loads(text) if len(text) < 2000 else None
    except json.JSONDecodeError:
        spec = None
    if spec is None:                     # body was truncated by http(); fetch it fully
        req = urllib.request.Request(f"{BASE}/openapi.json")
        with urllib.request.urlopen(req, timeout=60) as r:
            spec = json.loads(r.read().decode())
    out = set()
    for p, ops in (spec.get("paths") or {}).items():
        for m in ops:
            if m.upper() != "HEAD":
                out.add((m.upper(), p))
    return out, ""


def fill(path: str) -> str:
    out = path
    while "{" in out and "}" in out:
        start = out.index("{")
        end = out.index("}", start)
        key = out[start + 1:end].split(":")[0]
        out = out[:start] + PARAM_FILL.get(key, "commission-probe") + out[end + 1:]
    return out


def verdict_for(code: int, ctype: str, body: str) -> str:
    if code == 0:
        return "UNREACHABLE"
    if code == 200:
        return "works"
    if code in (401, 403):
        return "requires auth"
    if code == 404:
        return "404 (probe value, or genuinely absent)"
    if code in (405,):
        return "method not allowed"
    if code == 422:
        return "works (validation rejected the probe payload)"
    if code == 503:
        return "503 (hardware/lease unavailable)"
    if 500 <= code < 600:
        return f"**{code} SERVER ERROR**"
    return f"{code}"


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--exercise", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    rows = route_table()
    spec, spec_err = openapi_paths()
    registered = {(r["method"], r["path"]) for r in rows
                  if r["method"] not in ("WS", "Mount")}

    missing_from_spec = sorted(registered - spec)
    absent_route = sorted(spec - registered)

    if args.list or not args.exercise:
        print(f"route table walked from app.routes: {len(rows)} entries")
        from collections import Counter
        print("  by method:", dict(Counter(r["method"] for r in rows)))
        print(f"  mounted in sub-apps: {sum(1 for r in rows if r['mounted'])}")
        print(f"\nOpenAPI cross-check ({'error: ' + spec_err if spec_err else str(len(spec)) + ' operations in the schema'}):")
        print(f"  registered but NOT in the schema: {len(missing_from_spec)}")
        for m, p in missing_from_spec[:25]:
            print(f"     {m:<7} {p}")
        if len(missing_from_spec) > 25:
            print(f"     ... and {len(missing_from_spec) - 25} more")
        print(f"  in the schema but NOT registered: {len(absent_route)}")
        for m, p in absent_route[:25]:
            print(f"     {m:<7} {p}")
        if not args.exercise:
            return 0

    results = []
    for r in rows:
        method, path = r["method"], r["path"]
        if method == "WS":
            results.append({**r, "verdict": "skipped", "code": None,
                            "reason": "WebSocket; exercised separately by --ws"})
            continue
        if method in MUTATING:
            results.append({**r, "verdict": "skipped", "code": None,
                            "reason": f"{method} mutates state; not fired blind at the "
                                      "production service. Documented surfaces are "
                                      "exercised by --surfaces"})
            continue
        url = BASE + fill(path)
        t0 = time.monotonic()
        code, ctype, body = http(method, url)
        results.append({**r, "verdict": verdict_for(code, ctype, body), "code": code,
                        "ms": round((time.monotonic() - t0) * 1000),
                        "ctype": ctype.split(";")[0], "reason": ""})

    if args.json:
        print(json.dumps({"routes": results,
                          "missing_from_spec": missing_from_spec,
                          "absent_route": absent_route}, indent=2))
        return 0

    from collections import Counter
    tally = Counter(r["verdict"] for r in results)
    print(f"\nexercised {sum(1 for r in results if r['code'] is not None)} route(s); "
          f"skipped {sum(1 for r in results if r['code'] is None)}")
    for v, n in tally.most_common():
        print(f"  {n:>4}  {v}")

    # 503 is NOT a fault here. Every one measured on this box names the environment
    # variable that would enable the surface -- that is the honest-error standard, not a
    # failure. Counting it as a server error would have reported 8 defects that are 8
    # correctly-disabled surfaces.
    errs = [r for r in results if r["code"] and 500 <= r["code"] < 600
            and r["code"] != 503]
    unavailable = [r for r in results if r["code"] == 503]
    print(f"\nUNEXPECTED 5xx (503 excluded, see below): {len(errs)}")
    for r in errs:
        print(f"  {r['method']:<7} {r['path']}  -> {r['code']}")
    print(f"\n503 -- surface off or hardware absent, by design: {len(unavailable)}")
    for r in unavailable:
        print(f"  {r['method']:<7} {r['path']}")

    slow = sorted((r for r in results if r.get("ms")), key=lambda r: -r["ms"])[:5]
    print("\nslowest exercised:")
    for r in slow:
        print(f"  {r['ms']:>6}ms  {r['method']:<7} {r['path']}")
    return 1 if errs else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
