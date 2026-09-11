#!/usr/bin/env python3
"""Render `run/operator.html` — every capability this box has, in one page.

    python3 tools/build_operator.py            # write the page
    python3 tools/build_operator.py --check     # exit 1 if it is out of date
    python3 tools/build_operator.py --coverage   # just the coverage numbers

Generated, never hand-written. There are 119 decorated routes across 15 router modules; a page
listing them by hand would be wrong within a week. Everything here comes from a record that
already exists -- `apps/appdocs.py`, the live `/openapi.json`, `ops/PORTS.tsv`,
`ops/RUNTIMES.tsv` and `/api/status` -- so the page cannot claim a route the schema does not
have.

## Where it lives, and why not the webroot

`run/operator.html`, along`run/progress.html`, and **not** published. Safety rule 1 says the
console is an operator surface and not public; a static file in `/var/www/symoneural` is public
by construction, and `deploy.sh`'s allow-list would happily publish any `.html` placed in
`site/`. `run/` is the existing precedent for exactly this -- `progress.html` has never been in
the webroot -- so the page is opened locally and no new endpoint is needed to protect it.

That is a deliberate reading of the brief, which said the fixed deploy path means "this can
actually ship". It can; it should not, and the reason is its own rule 1.

## No styling, on purpose

It is a table. The brief is explicit that coverage and the safety rules are the work and the
look-and-feel pass comes after the owner has explored it.

## What it does NOT do

**No button invokes anything.** Not read, not GET, nothing. The rows carry the classification,
the live probe result, the backing runtime, the lease and the credential requirement -- but the
invoke mechanism is deliberately absent, because doing it safely means the page calling routes
**server-side** so the browser never holds a surface token, and that is a new local-only
endpoint on `api.py` that deserves its own commit and its own test rather than riding along
with a generator. The classification is what that commit will consume.

**Nothing here enables a surface.** The miner arms, the TRON settlement and the licence state
appear as state and carry no switch, per safety rule 4.
"""
from __future__ import annotations

import argparse
import html
import json
import pathlib
import subprocess
import sys
import time
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = ROOT / "run" / "operator.html"
API = "http://127.0.0.1:8800"

sys.path.insert(0, str(ROOT / "backend"))

#: A GET whose name says it mutates. Probing one would be a side effect, so they are listed
#: and never called -- and a GET that mutates is a bug, so finding one here is a finding.
MUTATING_GET_WORDS = ("delete", "remove", "stop", "reset", "clear", "kill", "drop", "revoke")


def fetch(path: str, timeout: float = 6.0) -> tuple[int, str]:
    try:
        with urllib.request.urlopen(API + path, timeout=timeout) as r:
            return r.status, r.read(400).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, ""
    except Exception as exc:                                   # noqa: BLE001
        return 0, f"{type(exc).__name__}"


def _full_json(path: str) -> dict:
    """A whole document, not a probe. Returns {} rather than raising: a page that cannot
    read the schema should say UNKNOWN everywhere, not fail to generate."""
    try:
        with urllib.request.urlopen(API + path, timeout=30) as r:
            return json.loads(r.read().decode("utf-8", "replace"))
    except Exception as exc:                                   # noqa: BLE001
        print(f"  could not read {path}: {type(exc).__name__}", file=sys.stderr)
        return {}


def tsv(path: pathlib.Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    lines = [l for l in path.read_text().splitlines() if l.strip() and not l.startswith("#")]
    if not lines:
        return []
    hdr = lines[0].split("\t")
    return [dict(zip(hdr, l.split("\t"))) for l in lines[1:]]


def classify(method: str, path: str, lease: str) -> tuple[str, str]:
    """(class, why). From the schema and the records -- never from the verb alone."""
    m = method.upper()
    if m == "DELETE":
        return "destroy", "DELETE"
    if m == "GET":
        if any(w in path.lower() for w in MUTATING_GET_WORDS):
            return "change", "GET whose path says it mutates -- FINDING, a GET should not"
        return "read", "GET"
    if lease and lease != "-":
        return "spend", f"the backing runtime takes the `{lease}` lease"
    return "change", m


def collect() -> dict:
    from registry import appdocs                                   # noqa: PLC0415

    # `fetch()` reads at most 400 bytes -- it exists to probe status codes, not to pull
    # documents -- so the schema comes through a full read. Trying to parse a truncated
    # body raised JSONDecodeError before the fallback could run, which is why this is not
    # a try/except around fetch().
    spec = _full_json("/openapi.json")

    ports = {r["SURFACE"]: r for r in tsv(ROOT / "ops" / "PORTS.tsv") if r.get("SURFACE")}
    leases: dict[str, str] = {}
    runtimes: dict[str, str] = {}
    for r in tsv(ROOT / "ops" / "RUNTIMES.tsv"):
        s = r.get("SURFACE", "-")
        if s and s != "-":
            leases[s] = r.get("LEASE", "-")
            runtimes[s] = r.get("RUNTIME", "-")

    live = {u["id"]: u for u in _full_json("/api/status").get("units", [])}

    rows = []
    for path, item in sorted(spec.get("paths", {}).items()):
        owner = appdocs.owner_of(path) or "UNKNOWN"
        lease = leases.get(owner, "-")
        for method, op in sorted(item.items()):
            if method.upper() not in ("GET", "POST", "PUT", "PATCH", "DELETE"):
                continue
            cls, why = classify(method, path, lease)
            probe = ("not probed", "only `read` routes are probed; probing anything else "
                                   "would be the side effect")
            if cls == "read" and "{" not in path:
                c, _ = fetch(path)
                probe = (str(c) if c else "unreachable",
                         "401 means it needs a credential this page does not hold"
                         if c == 401 else "")
            rows.append({
                "method": method.upper(), "path": path,
                "summary": op.get("summary") or "",
                "owner": owner, "runtime": runtimes.get(owner, "UNKNOWN"),
                "lease": lease or "UNKNOWN",
                "state": (live.get(owner) or {}).get("state", "UNKNOWN"),
                "cls": cls, "why": why,
                "probe": probe[0], "probe_note": probe[1],
                "templated": "{" in path,
            })
    return {"rows": rows, "apps": list(appdocs.APPLICATIONS), "ports": ports,
            "at": time.strftime("%Y-%m-%d %H:%M:%S")}


def render(data: dict) -> str:
    rows, apps = data["rows"], data["apps"]
    by_cls: dict[str, int] = {}
    for r in rows:
        by_cls[r["cls"]] = by_cls.get(r["cls"], 0) + 1
    probed = sum(1 for r in rows if r["probe"] not in ("not probed", "unreachable"))
    answered = sum(1 for r in rows if r["probe"].isdigit() and r["probe"].startswith("2"))
    needs_cred = sum(1 for r in rows if r["probe"] == "401")
    e = html.escape

    out = [
        "<title>SyMoNeuRaL operator console</title>",
        "<h1>Operator console</h1>",
        f"<p>Generated {e(data['at'])} by <code>tools/build_operator.py</code> from "
        "<code>appdocs</code>, <code>/openapi.json</code>, <code>ops/PORTS.tsv</code>, "
        "<code>ops/RUNTIMES.tsv</code> and <code>/api/status</code>. "
        "<b>Not published to the webroot</b> &mdash; this is an operator surface.</p>",
        "<h2>Coverage</h2><ul>",
        f"<li><b>{len(rows)}</b> operations in the public schema</li>",
        f"<li>by class: " + ", ".join(f"<b>{v}</b> {e(k)}" for k, v in sorted(by_cls.items()))
        + "</li>",
        f"<li>probed: <b>{probed}</b> &mdash; {answered} answered 2xx, "
        f"{needs_cred} returned 401 (needs a credential this page does not hold)</li>",
        f"<li><b>no route is invocable from this page.</b> See the module docstring: "
        "doing it safely means calling server-side so the browser never holds a token, "
        "and that is its own commit</li>",
        "</ul>",
        "<h2>Hierarchy</h2>",
        "<p><code>ops/TREE.tsv</code> does not exist yet, so rows are grouped by "
        "<b>application</b> and no second hierarchy is invented. The governor is the intended "
        "root and has no row in <code>ops/RUNTIMES.tsv</code> &mdash; the one runtime nothing "
        "records while it arbitrates every other.</p>",
        "<h2>Routes</h2>",
        "<table border=1 cellpadding=3><tr>"
        "<th>class<th>method<th>path<th>application<th>runtime<th>lease<th>rack state"
        "<th>probe<th>why / note</tr>",
    ]
    for r in sorted(rows, key=lambda x: (x["owner"], x["path"], x["method"])):
        note = r["probe_note"] or r["why"]
        out.append(
            f"<tr><td>{e(r['cls'])}<td>{e(r['method'])}<td><code>{e(r['path'])}</code>"
            f"<td>{e(r['owner'])}<td>{e(r['runtime'])}<td>{e(r['lease'])}"
            f"<td>{e(r['state'])}<td>{e(r['probe'])}<td>{e(note)}</tr>")
    out.append("</table>")

    out.append("<h2>Applications with no route in the schema</h2><ul>")
    owners = {r["owner"] for r in rows}
    missing = [a.id for a in apps if a.id not in owners]
    out.append("".join(f"<li><code>{e(m)}</code> &mdash; in <code>appdocs</code>, "
                       "no schema route attributed to it</li>" for m in missing)
               or "<li>none</li>")
    out.append("</ul>")
    out.append("<h2>Not switchable here, on purpose</h2><ul>"
               "<li>the miner arms, the TRON settlement and the licence state carry "
               "<b>no switch</b>. They are owner decisions with money and regulation behind "
               "them (safety rule 4)</li></ul>")
    return "\n".join(out) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true")
    ap.add_argument("--coverage", action="store_true")
    args = ap.parse_args()

    data = collect()
    text = render(data)

    if args.coverage:
        rows = data["rows"]
        by: dict[str, int] = {}
        for r in rows:
            by[r["cls"]] = by.get(r["cls"], 0) + 1
        print(f"  schema operations: {len(rows)}")
        for k, v in sorted(by.items()):
            print(f"    {k:<8} {v}")
        print(f"  401 (needs a credential): "
              f"{sum(1 for r in rows if r['probe'] == '401')}")
        print(f"  templated paths (not probed): "
              f"{sum(1 for r in rows if r['templated'])}")
        return 0

    if args.check:
        # The generated page carries a timestamp, so compare everything but that line.
        def strip_stamp(s: str) -> str:
            return "\n".join(l for l in s.splitlines() if "Generated 20" not in l)
        if OUT.is_file() and strip_stamp(OUT.read_text()) == strip_stamp(text):
            return 0
        print(f"{OUT.relative_to(ROOT)} is STALE -- run tools/build_operator.py")
        return 1

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text)
    print(f"  wrote {OUT.relative_to(ROOT)}  ({len(data['rows'])} operations)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
