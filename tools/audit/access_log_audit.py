#!/usr/bin/env python3
"""What has the outside world actually received from this box?

Written 2026-09-09 during commissioning, to settle a claim I had already published and
could not support. The Phase 5 report said the public API "returns 502, and has been all
along". The 502 was measured -- but through `curl --resolve symoneural.com:443:127.0.0.1`,
which is a loopback connection wearing an SNI header. It proves what the local Caddy does
with such a request. It says nothing about what a real client ever got, and "all along" was
an inference with no evidence under it at all.

Caddy keeps the evidence: `/etc/caddy/Caddyfile` logs every request as JSON to
`/var/log/caddy/symoneural.log`. That file is world-readable and contains `remote_ip`,
so the question is answerable by measurement rather than by reasoning, and the answer
turned out to be the opposite of what I published: the public path *worked*.

Run it:

    python3 tools/audit/access_log_audit.py            # summary
    python3 tools/audit/access_log_audit.py --json     # machine-readable, for the evidence dir

Loopback and LAN requests are separated from external ones throughout, because on the day
this was written 13 of the 18 recorded 502s were mine -- my own route audit hitting the
public hostname minutes earlier. Counting those as an outage would have been a second
error on top of the first.
"""

from __future__ import annotations

import argparse
import collections
import datetime
import ipaddress
import json
import pathlib
import sys

LOG = pathlib.Path("/var/log/caddy/symoneural.log")

# The four families `/etc/caddy/Caddyfile` routes to 127.0.0.1:8000 -- the gateway hop.
# These are the paths the 502 finding is about; everything else is served by the static
# site or proxied elsewhere and is not evidence either way.
GATEWAY_FAMILIES = ("/api/", "/v1/", "/swagger", "/api-docs")

# 101 is a WebSocket upgrade and 304 a validated cache hit; both mean the upstream was
# reachable and answered, which is the thing being measured. Anything else is either an
# application-level answer (401/404/405/503) or a proxy failure (502/504).
SUCCESS = (200, 101, 304)
PROXY_FAILURE = (502, 504)


def _is_local(ip: str) -> bool:
    """Loopback, link-local, or this box's own LAN segment.

    A request from 127.0.0.1 to the public hostname is a test -- mine or somebody's --
    not a member of the public. RFC1918 counts as local here because the only things on
    this segment are the box itself and the owner's own machines.
    """
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return addr.is_loopback or addr.is_private or addr.is_link_local


def _stamp(ts: float | None) -> str | None:
    if ts is None:
        return None
    return datetime.datetime.fromtimestamp(ts, datetime.UTC).isoformat(timespec="seconds")


def _entries(path: pathlib.Path):
    """Yield (ts, ip, status, uri, local) per parseable line.

    Truncated final lines and rotation artefacts are skipped rather than raised on: the
    log is being appended to while this reads it, so the last line is routinely half
    written. Skipped lines are counted and reported, so a log that is mostly unparseable
    cannot masquerade as a log that is mostly clean.
    """
    skipped = 0
    with path.open(errors="replace") as handle:
        for line in handle:
            try:
                rec = json.loads(line)
            except (json.JSONDecodeError, ValueError):
                skipped += 1
                continue
            req = rec.get("request") or {}
            ip = req.get("remote_ip", "")
            yield (
                rec.get("ts"),
                ip,
                rec.get("status"),
                (req.get("uri") or "").split("?")[0],
                _is_local(ip),
            )
    _entries.skipped = skipped  # type: ignore[attr-defined]


def audit(path: pathlib.Path = LOG) -> dict:
    if not path.is_file():
        return {"error": f"{path} does not exist -- is `log` still configured in the Caddyfile?"}

    total = 0
    first_ts = last_ts = None
    ext_last = None                                   # last external request of any kind
    gw_ext_ok: list[tuple] = []
    gw_ext_fail: list[tuple] = []
    gw_local_fail: list[tuple] = []
    codes: collections.Counter = collections.Counter()
    ext_per_day: collections.Counter = collections.Counter()

    for ts, ip, status, uri, local in _entries(path):
        total += 1
        if ts is not None:
            first_ts = ts if first_ts is None else min(first_ts, ts)
            last_ts = ts if last_ts is None else max(last_ts, ts)
        row = (_stamp(ts), ip, status, uri)
        if not local:
            ext_last = row
            if row[0]:
                ext_per_day[row[0][:10]] += 1
        if not uri.startswith(GATEWAY_FAMILIES):
            continue
        codes[f"{'local' if local else 'external'}/{status}"] += 1
        if status in PROXY_FAILURE:
            (gw_local_fail if local else gw_ext_fail).append(row)
        elif status in SUCCESS and not local:
            gw_ext_ok.append(row)

    return {
        "log": str(path),
        "lines_parsed": total,
        "lines_unparseable": getattr(_entries, "skipped", 0),
        "window": {"first": _stamp(first_ts), "last": _stamp(last_ts)},
        "gateway_families": list(GATEWAY_FAMILIES),
        "external": {
            "gateway_success": len(gw_ext_ok),
            "gateway_proxy_failure": len(gw_ext_fail),
            "first_gateway_success": gw_ext_ok[0] if gw_ext_ok else None,
            "last_gateway_success": gw_ext_ok[-1] if gw_ext_ok else None,
            "proxy_failures": gw_ext_fail,
            "last_request_any_path": ext_last,
            "requests_per_day": dict(sorted(ext_per_day.items())),
        },
        "local": {
            "gateway_proxy_failure": len(gw_local_fail),
            "proxy_failures": gw_local_fail,
        },
        "status_breakdown": dict(sorted(codes.items())),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--log", type=pathlib.Path, default=LOG)
    ap.add_argument("--json", action="store_true", help="dump the full result")
    args = ap.parse_args()

    result = audit(args.log)
    if args.json:
        print(json.dumps(result, indent=2))
        return 1 if "error" in result else 0
    if "error" in result:
        print(f"ERROR: {result['error']}", file=sys.stderr)
        return 1

    ext, loc = result["external"], result["local"]
    print(f"{result['log']}")
    print(f"  window        {result['window']['first']} .. {result['window']['last']}")
    print(f"  lines         {result['lines_parsed']} parsed, "
          f"{result['lines_unparseable']} unparseable")
    print()
    print("EXTERNAL clients, on the four families Caddy sends to the :8000 gateway hop:")
    print(f"  succeeded     {ext['gateway_success']}")
    if ext["first_gateway_success"]:
        print(f"    first       {ext['first_gateway_success'][0]}  "
              f"{ext['first_gateway_success'][3]}")
        print(f"    last        {ext['last_gateway_success'][0]}  "
              f"{ext['last_gateway_success'][3]}")
    print(f"  502/504       {ext['gateway_proxy_failure']}")
    for stamp, ip, status, uri in ext["proxy_failures"]:
        print(f"    {stamp}  {ip:<16} {status} {uri}")
    if ext["last_request_any_path"]:
        stamp, ip, status, uri = ext["last_request_any_path"]
        print(f"\n  last external request of ANY kind: {stamp}  {ip}  {status} {uri}")
    print("\n  external requests per day:")
    for day, count in ext["requests_per_day"].items():
        print(f"    {day}  {count}")
    print(f"\nLOCAL (loopback/LAN) 502/504 on those families: {loc['gateway_proxy_failure']}"
          "  -- test traffic, including this commissioning session's own")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
