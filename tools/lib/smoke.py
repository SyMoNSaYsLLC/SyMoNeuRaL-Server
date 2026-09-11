#!/usr/bin/env python3
"""End-to-end smoke test for the SyMoNeuRaL API. Exits non-zero if anything is broken.

    python3 tools/lib/smoke.py              # the standard run, about 60 s
    python3 tools/lib/smoke.py --quick      # skip the slow GPU checks (image render, lease proof)
    python3 tools/lib/smoke.py --json

You do not need to know anything about this repository to run this. It takes no arguments
that matter, reads nothing from your shell environment, and needs no credentials. Run it from
anywhere; it locates the repo from its own path.

## What "pass" means here

Every check reports **PASS**, **FAIL** or **SKIP**, and a SKIP is printed as loudly as a
failure with the reason attached. That is deliberate. This repository has shipped a surface
whose eighteen checks were green while its chat page was dead on arrival, and a silent skip
that leaves a green result is the exact failure the whole commissioning exercise exists to
prevent. A skipped check is never counted as a pass.

The exit code is 1 if any check FAILED. Skips alone do not fail the run -- but they are
listed again at the end so nobody can miss them.

## Two ports, and why both are checked

  * `127.0.0.1:8800` is the API itself.
  * `https://symoneural.com` **resolved to 127.0.0.1** -- the web server, the published
    document root, and the reverse proxy in front of the API.

**Checking only the first is how a broken site passes its own tests.** For five days
`/api/*` returned 502 through the proxy while `:8800` returned 200, because the Caddyfile
routes those paths through a gateway on `:8000` that had stopped. Every local API test
passed throughout. **Resolved 2026-09-09 22:00** by enabling `symoneural-gateway`.

## The limit of the second port, which matters more than it looks

`--resolve symoneural.com:443:127.0.0.1` is still a **loopback** connection; it merely
carries the right hostname so SNI and the site block work. It tells you what this proxy does
with a request. **It cannot tell you whether anyone can reach this box**, and commissioning
mistook the one for the other and published "unreachable from the public internet" on the
strength of it.

That distinction is the whole story. As of 2026-09-09 22:00, `symoneural.com` resolves to
**Cloudflare** (`104.21.22.186`, `172.67.206.158`), and not one of the 15,076 external
requests this proxy has ever logged came from a Cloudflare range -- so Cloudflare has never
successfully proxied a request to this Caddy. **When DNS changed is not known**, so whether
that relates to the 2026-09-04 traffic cliff is open; what is certain is that nothing
external has arrived since. Every green line below can be green while the site is dark to
the public. `check_external_traffic()` reads the access log, which is the closest this
script can get, and it is a record of the past rather than a test.
"""

from __future__ import annotations

import argparse
import datetime
import json
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path


def _repo_root() -> Path:
    here = Path(__file__).resolve()
    for cand in (here, *here.parents):
        if (cand / "backend" / "server.py").is_file():
            return cand
    raise SystemExit(f"repo root not found above {here}: no backend/server.py marker")


ROOT = _repo_root()
API = "http://127.0.0.1:8800"
PUBLIC = "https://symoneural.com"
PUBLIC_IP = "127.0.0.1"

PASS, FAIL, SKIP = "PASS", "FAIL", "SKIP"
results: list[dict] = []


def record(name: str, state: str, detail: str = "") -> str:
    results.append({"check": name, "state": state, "detail": detail})
    mark = {PASS: "PASS", FAIL: "FAIL", SKIP: "SKIP"}[state]
    print(f"  [{mark}] {name}" + (f"\n         {detail}" if detail else ""))
    return state


# --------------------------------------------------------------------- transport
def curl(url: str, timeout: float = 45.0) -> tuple[int, str, int]:
    """Fetch a public URL through curl, pinning DNS to this box.

    Not urllib, and the reason is worth writing down: the web server requires SNI, and a
    Python SSL context with `check_hostname = False` sends no `server_hostname`, so the
    handshake dies with `TLSV1_ALERT_INTERNAL_ERROR`. The first version of this check
    reported that transport failure as "the public site is broken" -- the right conclusion
    for the wrong reason, which is worse than a wrong conclusion because it looks like
    evidence. `curl --resolve` keeps the hostname (so SNI is correct) while pointing the
    connection at 127.0.0.1.

    Returns (http_code, content_type, bytes). code 0 means curl itself could not connect.
    """
    r = subprocess.run(
        # Pipe-delimited, NOT space-delimited. `%{content_type}` is "text/html; charset=utf-8"
        # -- it contains a space, so splitting on whitespace put the charset where the byte
        # count should be and every public check silently reported code 0. An empty
        # content_type on a 502 broke it the other way, by yielding too few fields.
        ["curl", "-sk", "-o", "/dev/null",
         "-w", "%{http_code}|%{content_type}|%{size_download}",
         "--max-time", str(int(timeout)), "--resolve", f"symoneural.com:443:{PUBLIC_IP}", url],
        capture_output=True, text=True, timeout=timeout + 15)
    parts = r.stdout.strip().split("|")
    if len(parts) != 3:
        return 0, "", 0
    try:
        return int(parts[0]), parts[1].split(";")[0].strip(), int(parts[2] or 0)
    except ValueError:
        return 0, "", 0


def curl_body(url: str, timeout: float = 45.0) -> str:
    r = subprocess.run(
        ["curl", "-sk", "--max-time", str(int(timeout)),
         "--resolve", f"symoneural.com:443:{PUBLIC_IP}", url],
        capture_output=True, text=True, timeout=timeout + 15)
    return r.stdout


def http(url: str, method: str = "GET", body: dict | None = None,
         timeout: float = 60.0) -> tuple[int, str, bytes]:
    headers: dict[str, str] = {}
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.headers.get("Content-Type", "").split(";")[0], r.read(200_000)
    except urllib.error.HTTPError as e:
        return e.code, (e.headers.get("Content-Type", "").split(";")[0] if e.headers else ""), b""
    except Exception as exc:
        return 0, f"{type(exc).__name__}", str(exc).encode()


# --------------------------------------------------------------------- checks
def check_preflight() -> None:
    r = subprocess.run([sys.executable, str(ROOT / "tools" / "lib" / "preflight.py"), "--json"],
                       capture_output=True, text=True, timeout=180)
    try:
        hard = json.loads(r.stdout)["hard_failures"]
    except Exception:
        record("preflight runs", FAIL, f"preflight produced no JSON: {r.stderr[-200:]}")
        return
    if hard:
        record("preflight: every hard dependency present", FAIL,
               f"{hard} hard failure(s) -- run: python3 tools/lib/preflight.py")
    else:
        record("preflight: every hard dependency present", PASS)


READY_TIMEOUT = 25.0


def wait_for_api(timeout: float = READY_TIMEOUT) -> tuple[bool, float]:
    """Poll `/api/status` until it answers, and return (ready, seconds waited).

    This exists because `sudo systemctl restart symoneural-api && python3 tools/lib/smoke.py`
    -- the obvious thing to type, and what RUNBOOK §3 tells you to type -- was a race that
    reported nine failures against a perfectly healthy API. Measured on 2026-09-09:

        22:09:55  old process logs "Finished server process"
        22:09:56  systemd marks the unit active; `systemctl restart` returns
        22:09:57  uvicorn logs "Uvicorn running on http://127.0.0.1:8800"

    `systemctl restart` returns at 22:09:56. The port is not bound until 22:09:57. A smoke
    run starting in that ~1 s window got `Connection refused` on every API check and
    printed "SMOKE TEST FAILED" with nine red lines -- while reporting
    `[PASS] symoneural-api.service is active`, because it was. Anyone reading that would
    reasonably conclude they had just broken production by restarting it.

    A smoke test that cannot survive being run immediately after a restart is a smoke test
    that lies at the exact moment it is most likely to be run.
    """
    deadline = time.monotonic() + timeout
    started = time.monotonic()
    while True:
        code, _, _ = http(f"{API}/api/status", timeout=5.0)
        if code == 200:
            return True, time.monotonic() - started
        if time.monotonic() >= deadline:
            return False, time.monotonic() - started
        time.sleep(0.25)


def check_service() -> None:
    """Active AND listening. Either alone misleads, and this repo has been bitten by both.

    `is-active` alone says nothing about whether the port is bound -- see `wait_for_api`.
    The port alone says nothing about whether systemd will bring it back. So both are
    reported, and the readiness wait is folded in here so every later check runs against a
    service that has actually finished starting.
    """
    r = subprocess.run(["systemctl", "is-active", "symoneural-api"],
                       capture_output=True, text=True, timeout=30)
    state = r.stdout.strip()

    # `activating` is a WAIT state, not a failure, and treating it as one would break this
    # check under the very unit change that fixes the underlying defect. Measured on a
    # throwaway --user unit with Type=exec + a polling ExecStartPost: `is-active` reports
    # `activating` with SubState=start-post for the whole startup window and only flips to
    # `active`/`running` once the probe succeeds. So a service that is coming up correctly
    # spends seconds in `activating`, and the first version of this fix would have called
    # that a hard failure -- swapping one wrong answer for another.
    if state == "activating":
        ready, waited = wait_for_api()
        state = subprocess.run(["systemctl", "is-active", "symoneural-api"],
                               capture_output=True, text=True, timeout=30).stdout.strip()
        if ready and state == "active":
            record("symoneural-api.service is active and listening", PASS,
                   f"was still activating when this run began; answered after {waited:.1f}s")
            return
        record("symoneural-api.service is active and listening", FAIL,
               f"stuck in '{state}' -- no answer on {API} after {waited:.0f}s. "
               f"journalctl -u symoneural-api -n 50")
        return

    if state != "active":
        record("symoneural-api.service is active and listening", FAIL,
               f"is-active reported '{state}'. Start it: sudo systemctl start symoneural-api")
        return

    ready, waited = wait_for_api()
    if ready and waited < 0.5:
        record("symoneural-api.service is active and listening", PASS)
    elif ready:
        record("symoneural-api.service is active and listening", PASS,
               f"answered after {waited:.1f}s -- it was still starting when this run began, "
               f"which is normal right after a restart")
    else:
        # Active but never bound: a real fault, and distinguishable from "not active".
        record("symoneural-api.service is active and listening", FAIL,
               f"the unit is active but nothing answered on {API} within {waited:.0f}s. "
               f"That is longer than a normal start (~1.2 s), so it is not a race: the "
               f"process is up and failing to serve, or crash-looping. "
               f"journalctl -u symoneural-api -n 50")


def check_status() -> dict | None:
    code, ctype, body = http(f"{API}/api/status")
    if code != 200:
        hint = ("could not connect at all -- the API stopped serving mid-run"
                if code == 0 else "the API answered, but not with 200")
        record("GET /api/status -> 200", FAIL,
               f"got {code}: {hint}. journalctl -u symoneural-api -n 50")
        return None
    try:
        d = json.loads(body)
    except Exception as exc:
        record("GET /api/status -> 200", FAIL, f"200 but unparseable JSON: {exc}")
        return None
    record("GET /api/status -> 200", PASS, f"{len(d.get('units', []))} units reported")

    drv = d.get("gpu", {}).get("driver")
    if drv is None:
        record("status reports GPU driver health", SKIP,
               "no gpu.driver field -- this service predates that change; restart it to pick "
               "it up (sudo systemctl restart symoneural-api)")
    elif drv == "ok":
        record("status reports GPU driver health", PASS, "gpu.driver = ok")
    elif drv == "persistenced_down":
        record("status reports GPU driver health", PASS,
               "gpu.driver = persistenced_down (surfaces work; cold requests are slower)")
    else:
        record("status reports GPU driver health", FAIL,
               f"gpu.driver = {drv}: {d['gpu'].get('driver_detail')}")
    return d


def check_ravencalc() -> None:
    code, _, body = http(f"{API}/api/ravencalc", "POST",
                         {"expression": "diff(x**3 + 2*x, x)"})
    if code != 200:
        record("POST /api/ravencalc (CPU, no GPU needed)", FAIL, f"got {code}")
        return
    txt = body.decode("utf-8", "replace")
    # The answer, not merely a 200: d/dx(x^3+2x) = 3x^2+2.
    if "3*x**2 + 2" in txt:
        record("POST /api/ravencalc (CPU, no GPU needed)", PASS, "d/dx(x^3+2x) = 3*x**2 + 2")
    else:
        record("POST /api/ravencalc (CPU, no GPU needed)", FAIL,
               f"200 but the wrong answer: {txt[:200]}")


def check_rate_limit() -> None:
    """A published ceiling that is not applied is worse than no ceiling."""
    codes = {}
    for _ in range(280):
        c, _, _ = http(f"{API}/api/ravencalc", "POST", {"expression": "1+1"}, timeout=30)
        codes[c] = codes.get(c, 0) + 1
        if codes.get(429):
            break
    if codes.get(429):
        record("rate limits are enforced, not decorative", PASS,
               f"429 after {codes.get(200, 0)} accepted requests")
    else:
        record("rate limits are enforced, not decorative", FAIL,
               f"280 requests drew no 429: {codes}. Published caps are not being applied.")


def check_chat(driver_ok: bool) -> None:
    if not driver_ok:
        record("POST /api/chat (needs the GPU)", SKIP, "GPU driver is not healthy")
        return
    code, _, body = http(f"{API}/api/chat", "POST",
                         {"prompt": "Say the single word: smoke.", "max_tokens": 8},
                         timeout=300)
    txt = body.decode("utf-8", "replace")
    if code == 200 and '"delta"' in txt:
        record("POST /api/chat (needs the GPU)", PASS, "streamed delta frames")
    else:
        record("POST /api/chat (needs the GPU)", FAIL, f"{code}: {txt[:200]}")


def check_image(driver_ok: bool, quick: bool) -> None:
    if quick:
        record("POST /api/image (needs the GPU, ~20 s)", SKIP, "--quick was passed")
        return
    if not driver_ok:
        record("POST /api/image (needs the GPU, ~20 s)", SKIP, "GPU driver is not healthy")
        return
    code, _, body = http(f"{API}/api/image", "POST",
                         {"prompt": "a grey square", "steps": 4, "size": 256}, timeout=600)
    if code != 200:
        record("POST /api/image (needs the GPU, ~20 s)", FAIL,
               f"{code}: {body[:200].decode('utf-8', 'replace')}")
        return
    try:
        url = json.loads(body)["url"]
    except Exception as exc:
        record("POST /api/image (needs the GPU, ~20 s)", FAIL, f"200 but no url: {exc}")
        return
    c2, t2, b2 = http(API + url)
    if c2 == 200 and t2 == "image/png" and len(b2) > 1000:
        record("POST /api/image (needs the GPU, ~20 s)", PASS,
               f"rendered and served {len(b2)} bytes of image/png")
    else:
        record("POST /api/image (needs the GPU, ~20 s)", FAIL,
               f"render returned a url that does not serve: {c2} {t2}")


def check_remix() -> None:
    code, _, body = http(f"{API}/api/remix", "POST", {"prompt": "dark techno", "count": 3},
                         timeout=300)
    if code == 200 and b"tracks" in body:
        record("POST /api/remix", PASS)
    else:
        record("POST /api/remix", FAIL, f"{code}: {body[:160].decode('utf-8','replace')}")


def check_websocket() -> None:
    try:
        import websockets  # noqa: F401
    except ImportError:
        record("WebSocket /api/ws accepts and greets", SKIP,
               "the `websockets` module is not installed (apt install python3-websockets)")
        return
    import asyncio

    import websockets as ws

    async def go() -> str:
        async with ws.connect("ws://127.0.0.1:8800/api/ws", open_timeout=30) as sock:
            hello = await asyncio.wait_for(sock.recv(), timeout=30)
            return hello

    try:
        hello = asyncio.run(go())
    except Exception as exc:
        record("WebSocket /api/ws accepts and greets", FAIL, f"{type(exc).__name__}: {exc}")
        return
    if '"welcome"' in hello:
        record("WebSocket /api/ws accepts and greets", PASS, "received the welcome frame")
    else:
        record("WebSocket /api/ws accepts and greets", FAIL, f"unexpected first frame: {hello[:160]}")


def check_gpu_lease(driver_ok: bool, quick: bool) -> None:
    """Two concurrent GPU requests must not both load weights onto a 16 GB card."""
    if quick:
        record("GPU lease serialises under concurrency", SKIP, "--quick was passed")
        return
    if not driver_ok:
        record("GPU lease serialises under concurrency", SKIP, "GPU driver is not healthy")
        return
    lock = ROOT / "run" / "gpu.lock.d" / "holder"
    seen: set[str] = set()
    multi = 0
    stop = threading.Event()

    def sample() -> None:
        nonlocal multi
        while not stop.is_set():
            try:
                if lock.is_file():
                    names = {ln.split()[0] for ln in lock.read_text().splitlines() if ln.split()}
                    seen.update(names)
                    if len(names) > 1:
                        multi += 1
            except OSError:
                pass
            stop.wait(0.15)

    t = threading.Thread(target=sample, daemon=True)
    t.start()
    codes: list[int] = []
    lk = threading.Lock()

    def fire(i: int) -> None:
        c, _, _ = http(f"{API}/api/chat", "POST",
                       {"prompt": f"Say the single word: lease{i}.", "max_tokens": 8},
                       timeout=300)
        with lk:
            codes.append(c)

    threads = [threading.Thread(target=fire, args=(i,)) for i in range(2)]
    for th in threads:
        th.start()
    for th in threads:
        th.join()
    stop.set()
    t.join(timeout=5)

    if any(c != 200 for c in codes):
        record("GPU lease serialises under concurrency", FAIL,
               f"concurrent chat requests returned {codes}")
    elif multi:
        record("GPU lease serialises under concurrency", FAIL,
               f"{multi} sample(s) showed more than one holder at once -- holders: {seen}")
    else:
        record("GPU lease serialises under concurrency", PASS,
               f"both served; never more than one holder (saw {sorted(seen) or ['none']})")


def check_models() -> None:
    wanted = [
        "models/llm/symon-1.0-7b-q4_k_m.gguf",
        "models/llm/symon-1.0-draft-0.5b-q4_k_m.gguf",
        "models/image/symoneural-image-unet-q4_k.gguf",
        "models/image/symoneural-image-vae.safetensors",
        "models/image/symoneural-image-clip.safetensors",
    ]
    missing = [w for w in wanted if not (ROOT / w).is_file()]
    if missing:
        record("model weights present", FAIL,
               "absent: " + ", ".join(missing)
               + " -- check the storage ledger before calling it a defect; it may be a "
                 "completed migration")
    else:
        record("model weights present", PASS, f"{len(wanted)}/{len(wanted)} on disk")


def check_public_site() -> None:
    if not shutil.which("curl"):
        record("public site serves HTML", SKIP, "curl is not installed")
        return
    code, ctype, size = curl(f"{PUBLIC}/chat.html")
    if code != 200 or ctype != "text/html":
        record("public site serves HTML", FAIL, f"{code} {ctype}")
        return
    record("public site serves HTML", PASS, f"/chat.html {size} bytes")

    html = curl_body(f"{PUBLIC}/chat.html")
    refs = set(re.findall(r'(?:href|src)="([^"]+)"', html))
    for m in re.findall(r'srcset="([^"]+)"', html):
        for part in m.split(","):
            refs.add(part.strip().split()[0])
    # Strip BOTH the query string and the fragment. Missing the fragment is how an earlier
    # version of this check "passed" while testing nothing: every asset carries ?v=<hash>.
    assets = sorted({r.split("?")[0].split("#")[0] for r in refs
                     if r.startswith("/") and not r.startswith("//")}
                    - {""})
    ext = [a for a in assets if "." in a.rsplit("/", 1)[-1] and not a.endswith(".html")]
    bad = []
    for a in ext:
        c, t, n = curl(PUBLIC + a)
        if c != 200 or not n:
            bad.append(f"{a} -> {c}")
    if bad:
        record("public site assets resolve", FAIL, "; ".join(bad[:6]))
    else:
        record("public site assets resolve", PASS,
               f"{len(ext)} assets, all 200 through the public path")


def check_serving_config() -> None:
    """Do `restart` and `reload` of symoneural-web serve the same Caddyfile?

    A SKIP rather than a FAIL, for the same reason as `check_external_traffic`: it reports
    root-owned installed state that neither this script nor the service user can change, and
    a red run nobody can action trains people to ignore the colour.

    Worth a check anyway, because it is the trap sitting directly in front of the pending
    502 decision: the fix is an edit to the tracked `ops/Caddyfile`, and a `systemctl
    reload` afterwards would load `/etc/caddy/Caddyfile` instead and silently revert it.

    COST NOTE for whoever edits this next: `audit()` is the heaviest check in the script --
    three `systemctl show` calls, a `pgrep`, an admin-API GET and a `caddy adapt`
    subprocess. It measured ~1 s here, which is affordable even in `--quick`. If you add
    work to `audit()`, re-time `--quick` (advertised as about five seconds) rather than
    assuming there is headroom.
    """
    label = "symoneural-web start and reload serve the same config"
    try:
        sys.path.insert(0, str(ROOT / "tools"))
        from serving_config_audit import audit                  # noqa: PLC0415
        r = audit()
    except Exception as exc:
        record(label, SKIP, f"could not audit the serving config: {exc}")
        return
    mismatch = next((f for f in r["findings"]
                     if f["id"] == "reload-start-config-mismatch"), None)
    if mismatch is None:
        record(label, PASS, f"both verbs name {r['start_config']}")
        return
    verb = "ALREADY DIVERGED" if mismatch["files_identical_now"] is False else "identical today"
    record(label, SKIP,
           f"they do NOT ({verb}). start -> {mismatch['start']}, "
           f"reload -> {mismatch['reload']}. After editing the start file, use "
           f"`systemctl restart` (or `sudo scripts/install-caddy.sh` then reload) -- a bare "
           f"reload loads the other file. Root-owned drop-in; see RUNBOOK.md §6 and "
           f"`python3 tools/audit/serving_config_audit.py`.")


def check_public_api() -> None:
    """The proxy's own view of /api/*. NOT a reachability test -- see the SKIP below.

    `curl --resolve symoneural.com:443:127.0.0.1` connects to loopback wearing the public
    hostname as SNI. It answers "what does this Caddy do with such a request", which is a
    real and useful question. It does NOT answer "can a visitor reach us", and commissioning
    conflated the two on 2026-09-09 and published "unreachable from the public internet"
    off the back of it. `check_external_traffic()` is the nearest thing this box has.
    """
    if not shutil.which("curl"):
        record("proxy routes /api/status to the API", SKIP, "curl is not installed")
        return
    code, _, _ = curl(f"{PUBLIC}/api/status")
    if code == 200:
        record("proxy routes /api/status to the API", PASS)
    else:
        record("proxy routes /api/status to the API", FAIL,
               f"got {code} (from loopback via SNI, not from off-box). The Caddyfile routes "
               "/api/* to 127.0.0.1:8000 (symoneural-gateway), which is disabled -- so every "
               "documented surface 502s through the proxy while working fine on :8800. It "
               "worked until 2026-09-04 15:50, when the gateway stopped. "
               "See RUNBOOK.md 'The public API returns 502'.")


# Beyond this, an on-box smoke test is blind: the box has one private interface and
# everything public depends on a NAT forward it cannot see. The access log is the only
# evidence here of what the outside world actually reaches, so it is worth one check.
STALE_TRAFFIC_DAYS = 2
ACCESS_LOG = Path("/var/log/caddy/symoneural.log")


def check_external_traffic() -> None:
    """Has anyone outside reached the proxy lately?

    A SKIP, never a FAIL, and deliberately so: a quiet day is not a defect and this test
    cannot tell "nobody visited" from "nothing can get here". What it can do is refuse to
    let a five-day silence go unmentioned while every other check reports green -- which is
    exactly what happened on 2026-09-09, when the access log had recorded nothing external
    since 09-04 and no test looked.
    """
    label = f"external traffic seen in the last {STALE_TRAFFIC_DAYS} day(s)"
    if not ACCESS_LOG.is_file():
        record(label, SKIP, f"{ACCESS_LOG} absent -- is `log` still in the Caddyfile?")
        return
    try:
        sys.path.insert(0, str(ROOT / "tools"))
        from access_log_audit import audit                     # noqa: PLC0415
        last = audit(ACCESS_LOG)["external"]["last_request_any_path"]
    except Exception as exc:
        record(label, SKIP, f"could not read the access log: {exc}")
        return
    if not last:
        record(label, SKIP, "the log records no external request at all, ever")
        return
    stamp = last[0]
    try:
        age = (datetime.datetime.now(datetime.UTC)
               - datetime.datetime.fromisoformat(stamp)).days
    except ValueError:
        record(label, SKIP, f"unparseable timestamp {stamp!r}")
        return
    if age <= STALE_TRAFFIC_DAYS:
        record(label, PASS, f"last external request {stamp} ({age}d ago): {last[3]}")
    else:
        record(label, SKIP,
               f"NOTHING EXTERNAL FOR {age} DAYS -- last was {stamp} from {last[1]} "
               f"({last[3]}). The proxy is up and answering loopback, so either nobody "
               "visited or nothing can reach this box. NOT TESTABLE FROM HERE: load "
               "https://symoneural.com on a phone with Wi-Fi off, and check "
               "`dig +short symoneural.com`. See RUNBOOK.md section 7.")


def check_gpu_released() -> None:
    """The LEASE must be released. Resident weights are not a leak.

    The first version of this failed any box where an engine was still resident, and that is
    wrong: after a GPU request `symoneural-llm` deliberately stays loaded (measured: 8330 MiB
    with `run/gpu.lock.d` absent) so the next request does not pay the load again. The
    governor is designed to evict a resident-but-idle tenant when another needs the card.
    What would be a real fault is the lock directory outliving the work that took it, because
    then nothing else can ever acquire the card.
    """
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-compute-apps=pid,used_memory", "--format=csv,noheader"],
            capture_output=True, text=True, timeout=30)
    except Exception as exc:
        record("no process left holding VRAM", SKIP, f"nvidia-smi unavailable: {exc}")
        return
    procs = [l for l in out.stdout.strip().splitlines() if l.strip()]
    lockdir = ROOT / "run" / "gpu.lock.d"
    if lockdir.is_dir():
        record("GPU lease released after the work finished", FAIL,
               f"{lockdir} still exists -- nothing else can acquire the card. "
               f"Release it: scripts/gpu-governor.sh release chat")
    else:
        detail = "lock directory gone"
        if procs:
            detail += f"; {len(procs)} engine(s) still resident by design ("
            detail += "; ".join(procs) + ") -- the governor evicts these on demand"
        record("GPU lease released after the work finished", PASS, detail)


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--quick", action="store_true",
                    help="skip the slow GPU checks (image render, lease proof)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    print(f"SyMoNeuRaL API smoke test  ({ROOT})")
    print(f"  API    : {API}")
    print(f"  public : {PUBLIC} (resolved to {PUBLIC_IP})")
    print()

    t0 = time.monotonic()
    check_preflight()
    check_service()
    status = check_status()
    driver = (status or {}).get("gpu", {}).get("driver", "ok")
    driver_ok = driver in ("ok", "persistenced_down")

    check_models()
    check_ravencalc()
    check_remix()
    check_chat(driver_ok)
    check_image(driver_ok, args.quick)
    check_gpu_lease(driver_ok, args.quick)
    check_websocket()
    check_rate_limit()
    check_public_site()
    check_public_api()
    check_external_traffic()
    check_serving_config()
    check_gpu_released()
    elapsed = time.monotonic() - t0

    failed = [r for r in results if r["state"] == FAIL]
    skipped = [r for r in results if r["state"] == SKIP]
    passed = [r for r in results if r["state"] == PASS]

    if args.json:
        print(json.dumps({"results": results, "passed": len(passed),
                          "failed": len(failed), "skipped": len(skipped),
                          "seconds": round(elapsed, 1)}, indent=2))
        return 1 if failed else 0

    print(f"\n{'=' * 70}")
    print(f"  {len(passed)} passed, {len(failed)} FAILED, {len(skipped)} skipped "
          f"in {elapsed:.0f}s")
    if skipped:
        print("\n  SKIPPED -- these were NOT tested and are not passes:")
        for r in skipped:
            print(f"    - {r['check']}: {r['detail']}")
    if failed:
        print("\n  FAILED:")
        for r in failed:
            print(f"    - {r['check']}")
            print(f"      {r['detail']}")
        print("\n  SMOKE TEST FAILED")
        return 1
    print("\n  SMOKE TEST PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
