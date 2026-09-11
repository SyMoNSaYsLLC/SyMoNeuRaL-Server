#!/usr/bin/env python3
"""Find mining rigs on the operator's own network, then identify what they are.

Runs under `backend/apps/asicminer/.venv/bin/python`, like `probe.py`, because the
identification half needs pyasic. Prints JSON on stdout.

    .venv/bin/python scan.py 10.0.0.0/24
    .venv/bin/python scan.py 192.168.1.0/24 --port 4028 --timeout 0.6

## Two things this refuses to do, and why

**It will not scan a public address range.** This code runs on a box that faces the
internet. A scanner that accepts any CIDR is a scanner someone can point at the internet
from our IP -- that is how a legitimate tool becomes an abuse complaint and a null-routed
host. Only RFC1918, carrier-grade NAT, link-local and loopback ranges are accepted; anything
globally routable is rejected before a single packet is sent. The rigs are on the operator's
LAN by definition, so this costs nothing real.

**It will not sweep an unbounded range.** A /8 is sixteen million addresses. The prefix is
floored at /20 (4,096 hosts) and the host count is capped again after expansion, because
"scan my whole network" is usually a typo for a /24 and the cost of the typo should not be
an hour of SYN traffic.

## How it finds things

Two phases, because pyasic's full identification costs seconds per host and a TCP connect
costs milliseconds:

1. **Sweep** port 4028 -- the cgminer/bmminer/btminer API port that Antminer, Whatsminer and
   Braiins all listen on. A refused connection means nothing is there; a timeout means
   nothing answered in time. Neither is an error.
2. **Identify** only the addresses that answered, via pyasic.

Nothing here writes to a rig. Discovery is read-only by construction: it opens a TCP
connection, and `probe.py` does the reading.
"""
from __future__ import annotations

import argparse
import asyncio
import ipaddress
import json
import sys

API_PORT = 4028          # cgminer/bmminer/btminer all listen here
MIN_PREFIX_V4 = 20       # /20 = 4096 addresses; refuse anything broader
MAX_HOSTS = 4096
SWEEP_CONCURRENCY = 256  # open sockets at once; the identify phase is far narrower
IDENTIFY_CONCURRENCY = 16


def allowed_network(cidr: str) -> tuple[ipaddress.IPv4Network | ipaddress.IPv6Network | None, str]:
    """Parse a CIDR and refuse anything that is not the operator's own private network.

    Returns (network, "") when acceptable, or (None, reason). The check is on the parsed
    network object rather than on the string, so `010.0.0.0/24` and other spellings cannot
    slip past a textual test.
    """
    try:
        net = ipaddress.ip_network(cidr, strict=False)
    except ValueError as e:
        return None, f"not a valid CIDR: {e}"

    if net.is_global:
        return None, (f"{net} is globally routable. This scans the operator's own LAN only — "
                      "scanning public address space from this host is refused.")
    if not (net.is_private or net.is_link_local or net.is_loopback):
        return None, f"{net} is neither private, link-local nor loopback"
    if net.version == 4 and net.prefixlen < MIN_PREFIX_V4:
        return None, (f"/{net.prefixlen} is too broad; /{MIN_PREFIX_V4} "
                      f"({2 ** (32 - MIN_PREFIX_V4)} addresses) is the widest accepted")
    return net, ""


async def _open(host: str, port: int, timeout: float) -> bool:
    """True if something accepted a TCP connection. Never raises."""
    try:
        fut = asyncio.open_connection(host, port)
        reader, writer = await asyncio.wait_for(fut, timeout=timeout)
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
        return True
    except Exception:
        # Refused, unreachable, timed out -- all mean "no rig here", none is an error.
        return False


async def sweep(hosts: list[str], port: int, timeout: float) -> list[str]:
    sem = asyncio.Semaphore(SWEEP_CONCURRENCY)

    async def one(h: str) -> str | None:
        async with sem:
            return h if await _open(h, port, timeout) else None

    found = await asyncio.gather(*(one(h) for h in hosts))
    return [h for h in found if h]


async def identify(hosts: list[str]) -> list[dict]:
    """Ask pyasic what each responder actually is. Unidentified is still reported."""
    sem = asyncio.Semaphore(IDENTIFY_CONCURRENCY)

    async def one(h: str) -> dict:
        rec = {"host": h, "identified": False, "vendor": None, "model": None,
               "firmware": None, "error": None}
        async with sem:
            try:
                from pyasic import get_miner
                m = await asyncio.wait_for(get_miner(h), timeout=8.0)
            except Exception as e:
                rec["error"] = f"{e.__class__.__name__}: {e}"
                return rec
            if m is None:
                # Something answered on the API port but pyasic does not recognise it.
                # Reported, not dropped: an unknown responder on 4028 is worth seeing.
                rec["error"] = "answered on the API port but was not recognised"
                return rec
            rec.update(identified=True,
                       vendor=str(getattr(m, "make", "") or "") or None,
                       model=str(getattr(m, "model", "") or "") or None,
                       firmware=str(getattr(m, "fw_ver", "") or "") or None)
            return rec

    return list(await asyncio.gather(*(one(h) for h in hosts)))


async def scan(cidr: str, port: int, timeout: float) -> dict:
    out = {"network": cidr, "port": port, "swept": 0, "responded": 0,
           "rigs": [], "error": None}
    net, why = allowed_network(cidr)
    if net is None:
        out["error"] = why
        return out

    hosts = [str(h) for h in net.hosts()] or [str(net.network_address)]
    if len(hosts) > MAX_HOSTS:
        out["error"] = f"{len(hosts)} addresses exceeds the {MAX_HOSTS} cap"
        return out

    out["swept"] = len(hosts)
    responders = await sweep(hosts, port, timeout)
    out["responded"] = len(responders)
    out["rigs"] = await identify(responders) if responders else []
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Discover mining rigs on a private network.")
    ap.add_argument("cidr", help="e.g. 10.0.0.0/24 — must be a private range")
    ap.add_argument("--port", type=int, default=API_PORT)
    ap.add_argument("--timeout", type=float, default=0.6,
                    help="per-host TCP connect timeout, seconds")
    a = ap.parse_args()
    print(json.dumps(asyncio.run(scan(a.cidr, a.port, a.timeout)), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
