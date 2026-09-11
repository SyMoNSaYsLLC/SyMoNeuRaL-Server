#!/usr/bin/env python3
"""The watchdog. Six checks, one state file, non-zero exit on any failure.

    python3 tools/lib/watch.py            # run the checks, print a table
    python3 tools/lib/watch.py --json     # machine-readable
    python3 tools/lib/watch.py --quiet    # only transitions and failures

## Why this is not `tools/lib/smoke.py`

`smoke.py` already has `check_public_site()`, and reusing it would have inherited the defect
this file exists to catch. `smoke.py:79` sets `PUBLIC_IP = "127.0.0.1"` and curls
`https://symoneural.com` **with `--resolve` pointed at loopback**. It therefore tests Caddy, not
the public path. Measured 2026-09-10: `smoke.py` reported *"17 passed, 0 FAILED"* including
*"public site serves HTML"* and *"13 assets, all 200 through the public path"* -- at a moment
when `https://symoneural.com/` returned **522** to the actual internet and had been dark since
29 August.

That is the vacuous-guard failure at the operations layer: a check that returns the answer you
expected without testing the thing you meant. `smoke.py` is not wrong to do it -- it is a
deployment smoke test and loopback is the right scope for one -- but it must not be mistaken
for reachability, and nothing said so until now.

**So check 1 uses real DNS and no `--resolve`.** It is the only check here that can fail for a
reason outside this machine, and it is the one that matters.

## What check 1 actually proves from this box, honestly

It resolves `symoneural.com` through real DNS and fetches it. On this box DNS answers with
Cloudflare's anycast addresses, so the request leaves the network, reaches Cloudflare, and
Cloudflare attempts the origin -- which is the full path, and a 522 from Cloudflare is a
truthful report that the origin is unreachable *from outside*.

It would NOT be trustworthy if DNS resolved to this LAN, because the request could hairpin at
the router and succeed while the outside world could not reach us. `_public_target()` detects
exactly that and returns `UNVERIFIABLE` rather than a false green.
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import shutil
import socket
import subprocess
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parents[1]
STATE = ROOT / "run" / "watch-state.json"
PUBLIC_HOST = "symoneural.com"
LOCAL_API = "http://127.0.0.1:8800/api/status"
UNITS = ("symoneural-api", "symoneural-web", "symoneural-gateway")
CERT_ALERT_DAYS = 21

OK, FAIL, UNKNOWN = "ok", "FAIL", "UNVERIFIABLE"


# ----------------------------------------------------------------- notification hook
def notify(subject: str, body: str) -> None:
    """Where an alert goes. **No-op by default, and deliberately.**

    The destination is the owner's decision. Nothing here signs up for a service, adds a
    dependency, or sends anything outbound -- a watchdog that quietly starts talking to a
    third party is a worse problem than the one it watches for.

    Every result already reaches the journal (stdout under systemd) and `run/watch-state.json`.
    When a destination is chosen this becomes a few lines here and nothing else changes.
    """
    return None


# ----------------------------------------------------------------- helpers
def _run(*argv: str, timeout: int = 30) -> tuple[int, str]:
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout + p.stderr).strip()
    except Exception as exc:                                  # noqa: BLE001
        return 1, f"{type(exc).__name__}: {exc}"


def _is_local(ip: str) -> bool:
    return ip.startswith(("127.", "10.", "192.168.")) or ip.startswith(
        tuple(f"172.{n}." for n in range(16, 32)))


def _public_target() -> tuple[list[str], bool]:
    """Where real DNS says the public name lives, and whether that is off this network."""
    try:
        ips = sorted({r[4][0] for r in socket.getaddrinfo(PUBLIC_HOST, 443, socket.AF_INET)})
    except Exception:                                          # noqa: BLE001
        return [], False
    return ips, bool(ips) and not all(_is_local(i) for i in ips)


# ----------------------------------------------------------------- the six checks
def check_public() -> dict:
    """1. The public URL, over real DNS. The one that was dark for two weeks."""
    ips, external = _public_target()
    if not ips:
        return {"state": UNKNOWN, "detail": f"{PUBLIC_HOST} does not resolve"}
    if not external:
        return {"state": UNKNOWN,
                "detail": f"{PUBLIC_HOST} resolves to {', '.join(ips)} on this network -- a "
                          "fetch could hairpin at the router and succeed while the outside "
                          "world cannot reach us. Not reported as up."}
    if not shutil.which("curl"):
        return {"state": UNKNOWN, "detail": "curl is not installed"}
    rc, out = _run("curl", "-s", "-o", "/dev/null", "-m", "25",
                   "-w", "%{http_code} %{time_total}", f"https://{PUBLIC_HOST}/", timeout=40)
    code = out.split()[0] if out.split() else "000"
    served_by = _run("curl", "-s", "-I", "-m", "25", f"https://{PUBLIC_HOST}/", timeout=40)[1]
    edge = "cloudflare" if "cloudflare" in served_by.lower() else "direct"
    if code in ("200", "301", "302", "308"):
        return {"state": OK, "detail": f"HTTP {code} via {edge} ({', '.join(ips)})"}
    hint = ""
    if code == "522":
        hint = " -- Cloudflare reached, origin did not answer it. The box is not the fault."
    return {"state": FAIL, "detail": f"HTTP {code} via {edge}{hint}"}


def check_local_api() -> dict:
    """2. Separates 'origin broken' from 'path broken'. That distinction IS the diagnosis."""
    rc, out = _run("curl", "-s", "-o", "/dev/null", "-m", "15", "-w", "%{http_code}", LOCAL_API)
    return ({"state": OK, "detail": "200"} if out.strip() == "200"
            else {"state": FAIL, "detail": f"local /api/status returned {out.strip() or 'nothing'}"})


def check_units() -> dict:
    """3. The gateway was disabled for five days and nobody noticed."""
    bad = []
    for u in UNITS:
        rc, out = _run("systemctl", "is-active", u)
        if out.strip() != "active":
            bad.append(f"{u}={out.strip() or 'unknown'}")
    return ({"state": OK, "detail": f"{len(UNITS)} active"} if not bad
            else {"state": FAIL, "detail": "; ".join(bad)})


def check_rack() -> dict:
    """4. The honest rack, put to use: any surface unreachable is a failure."""
    rc, out = _run("curl", "-s", "-m", "20", LOCAL_API)
    try:
        units = json.loads(out).get("units", [])
    except Exception:                                          # noqa: BLE001
        return {"state": UNKNOWN, "detail": "could not read the rack"}
    unreachable = [u.get("id") for u in units if u.get("state") == "unreachable"]
    if unreachable:
        return {"state": FAIL, "detail": f"unreachable: {', '.join(unreachable)}"}
    offline = [u.get("id") for u in units if u.get("state") == "offline"]
    return {"state": OK,
            "detail": f"{len(units)} rows, {len(offline)} offline"
                      + (f" ({', '.join(offline)})" if offline else "")}


def check_cert() -> dict:
    """5. Days until the origin certificate expires.

    Read from the origin with SNI rather than from the public URL: the public name is served
    by Cloudflare's own edge certificate, which says nothing about ours.
    """
    if not shutil.which("openssl"):
        return {"state": UNKNOWN, "detail": "openssl is not installed"}
    rc, out = _run("bash", "-c",
                   f"echo | openssl s_client -connect 127.0.0.1:443 -servername {PUBLIC_HOST} "
                   "2>/dev/null | openssl x509 -noout -enddate -issuer", timeout=40)
    m = re.search(r"notAfter=(.+)", out)
    if not m:
        return {"state": UNKNOWN, "detail": "could not read the origin certificate"}
    try:
        exp = time.mktime(time.strptime(m.group(1).strip(), "%b %d %H:%M:%S %Y %Z"))
    except ValueError:
        return {"state": UNKNOWN, "detail": f"unparsed expiry: {m.group(1).strip()}"}
    days = int((exp - time.time()) // 86400)
    issuer = "Let's Encrypt" if "Let's Encrypt" in out else "other"
    if days <= CERT_ALERT_DAYS:
        return {"state": FAIL,
                "detail": f"{days} days left ({issuer}). Renewal needs this box reachable "
                          "from the internet -- see HANDOFF bite 12"}
    return {"state": OK, "detail": f"{days} days left ({issuer})"}


def check_capacity() -> dict:
    """6. Slow failures nobody is watching for."""
    parts, bad = [], False
    rc, out = _run("df", "--output=avail,pcent", "-BG", str(ROOT))
    line = out.splitlines()[-1] if out.splitlines() else ""
    m = re.search(r"(\d+)G\s+(\d+)%", line)
    if m:
        free_g, used_pct = int(m.group(1)), int(m.group(2))
        parts.append(f"/home {free_g}G free ({used_pct}% used)")
        if used_pct >= 90:
            bad = True
    rc, out = _run("nvidia-smi", "--query-gpu=memory.used,memory.total",
                   "--format=csv,noheader,nounits")
    if rc == 0 and "," in out:
        used, total = (int(x.strip()) for x in out.splitlines()[0].split(","))
        parts.append(f"VRAM {total - used} MiB free of {total}")
    return {"state": FAIL if bad else OK, "detail": " · ".join(parts) or "no readings"}


CHECKS = (
    ("public URL (real DNS)", check_public),
    ("local /api/status", check_local_api),
    ("units active", check_units),
    ("rack rows", check_rack),
    ("origin certificate", check_cert),
    ("disk and VRAM", check_capacity),
)


# ----------------------------------------------------------------- state and transitions
def load_state() -> dict:
    try:
        return json.loads(STATE.read_text())
    except Exception:                                          # noqa: BLE001
        return {}


def save_state(results: dict) -> None:
    STATE.parent.mkdir(parents=True, exist_ok=True)
    STATE.write_text(json.dumps(results, indent=1, sort_keys=True) + "\n")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--quiet", action="store_true",
                    help="print only failures and transitions")
    args = ap.parse_args()

    previous = load_state().get("checks", {})
    results, failed, transitions = {}, 0, []
    for name, fn in CHECKS:
        try:
            r = fn()
        except Exception as exc:                               # noqa: BLE001
            r = {"state": UNKNOWN, "detail": f"check raised {type(exc).__name__}: {exc}"}
        results[name] = r
        was = previous.get(name, {}).get("state")
        # A transition is what gets alerted on. Alerting on every failure is how a dark site
        # produces 4,000 identical messages and nobody reads the 4,001st.
        if was is not None and was != r["state"]:
            transitions.append(f"{name}: {was} -> {r['state']}")
        if r["state"] == FAIL:
            failed += 1

    payload = {"at": time.strftime("%Y-%m-%d %H:%M:%S"), "failed": failed,
               "transitions": transitions, "checks": results}
    save_state(payload)

    if args.json:
        print(json.dumps(payload, indent=1))
    else:
        for name, r in results.items():
            if args.quiet and r["state"] == OK and not transitions:
                continue
            print(f"  [{r['state']:^13}] {name:<24} {r['detail']}")
        for t in transitions:
            print(f"  TRANSITION  {t}")

    if transitions or failed:
        notify(f"symoneural: {failed} failing, {len(transitions)} transition(s)",
               json.dumps(payload, indent=1))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
