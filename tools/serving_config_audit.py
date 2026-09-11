#!/usr/bin/env python3
"""Which Caddyfile is the web server actually serving, and would a reload change it?

Written 2026-09-09, after the commissioning report cited the wrong file. It said the fix for
the `/api/*` 502 goes in `/etc/caddy/Caddyfile:51,88,94,97`. The running service does not
read that file. It reads `<root>/ops/Caddyfile`, because a root-owned drop-in overrides
`ExecStart` to point there -- and the two happen to be byte-identical, so citing either one
looked equally right.

They are not equally right, and the difference is not cosmetic:

  * `ops/Caddyfile` is **tracked in git**. An edit there is reviewable and revertable.
  * `/etc/caddy/Caddyfile` is root-owned and untracked. Editing it changes nothing until
    something restarts the service from it -- and nothing does.

Worse, the drop-in overrides `ExecStart` and **not** `ExecReload`, so the two verbs name
different files:

    systemctl restart symoneural-web   ->  serves <root>/ops/Caddyfile
    systemctl reload  symoneural-web   ->  loads /etc/caddy/Caddyfile

Today that is invisible, because `scripts/install-caddy.sh` copies the former over the
latter and they are byte-identical. It stops being invisible the moment somebody edits
`ops/Caddyfile` -- to fix the 502, say -- and reloads: the reload pushes the older `/etc`
copy into the running instance and silently reverts the edit. Which config is live then
depends on which verb was used last, which is not a property a web server should have.

This is the third instance in this repo of one shape of defect: a control that looks like it
is in force and is not. `StartLimitIntervalSec` under `[Service]`, where systemd ignores it.
A `systemctl stop` believed to be a hold on an `enabled` unit. And now a `reload` that
reloads a file you did not edit.

    python3 tools/serving_config_audit.py
    python3 tools/serving_config_audit.py --json

Read-only. It queries Caddy's admin API with GET and adapts files to JSON; it never posts a
config, never reloads, and never writes.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request

UNIT = "symoneural-web"
ADMIN = "http://127.0.0.1:2019/config/"
CONFIG_FLAG = re.compile(r"--config\s+(\S+)")


def _repo_root() -> pathlib.Path:
    here = pathlib.Path(__file__).resolve()
    for cand in (here, *here.parents):
        if (cand / "backend" / "server.py").is_file():
            return cand
    raise SystemExit(f"repo root not found above {here}: no backend/server.py marker")


ROOT = _repo_root()
BINARY = ROOT / "web" / "symoneural-web" / "build" / "symoneural-web"


def _show(prop: str) -> str:
    r = subprocess.run(["systemctl", "show", UNIT, "-p", prop, "--value"],
                       capture_output=True, text=True, timeout=30)
    return r.stdout.strip()


def _config_from(prop: str) -> str | None:
    """The --config path systemd would pass for this Exec property.

    `systemctl show` renders Exec lines as `{ path=... ; argv[]=... ; ... }`, so the flag is
    read out of the rendered argv rather than off a clean field.
    """
    m = CONFIG_FLAG.search(_show(prop))
    return m.group(1) if m else None


def _running_config() -> str | None:
    """What the live process was actually started with, read from /proc.

    `systemctl show` reports what systemd *would* run. This reports what is running, which
    can differ across a daemon-reload that has not been followed by a restart.
    """
    r = subprocess.run(["pgrep", "-af", "symoneural-web"], capture_output=True, text=True,
                       timeout=30)
    for line in r.stdout.splitlines():
        if "/symoneural-web run" not in line:
            continue
        m = CONFIG_FLAG.search(line)
        if m:
            return m.group(1)
    return None


def _adapt(path: str) -> dict | None:
    """Adapt a Caddyfile to JSON without contacting the running server."""
    if not BINARY.is_file():
        return None
    r = subprocess.run([str(BINARY), "adapt", "--config", path],
                       capture_output=True, text=True, timeout=60)
    if r.returncode != 0:
        return None
    try:
        return json.loads(r.stdout)
    except json.JSONDecodeError:
        return None


def _normalise(cfg: dict | None) -> dict | None:
    """Strip the one field that differs purely because of where the file lives.

    Caddy's `file_server` auto-hides the config file it was adapted from, so the adapted
    JSON embeds its own source path in `hide`. A naive comparison of two byte-identical
    Caddyfiles at different paths therefore reports a difference -- I hit exactly that and
    briefly believed the live and installed configs had diverged. The paths ARE the thing
    under audit here, so they are compared separately and removed from the content compare.
    """
    if cfg is None:
        return None

    def scrub(node):
        if isinstance(node, dict):
            return {k: (["<config-path>"] if k == "hide" else scrub(v))
                    for k, v in node.items()}
        if isinstance(node, list):
            return [scrub(v) for v in node]
        return node

    return scrub(cfg)


def _live_config() -> dict | None:
    """GET the running instance's config from the admin API. Never POSTs."""
    try:
        with urllib.request.urlopen(ADMIN, timeout=10) as resp:
            return json.loads(resp.read())
    except (urllib.error.URLError, json.JSONDecodeError, OSError):
        return None


def classify_verb_mismatch(start_path: str | None, reload_path: str | None,
                           read: "callable[[str], bytes | None]") -> dict | None:
    """Decide whether the start/reload config paths constitute a finding, and how bad.

    Split out from `audit()` so it can be tested against synthetic inputs -- the live
    version reads root-owned systemd state and a 644 file in /etc, neither of which a test
    may alter. `read` returns the file's bytes, or None if it cannot be read.

    Three outcomes:
      * None      -- the verbs name the same file, or one of them is unknown. Nothing wrong.
      * latent    -- different paths, identical content. Wrong today only in that it is a
                     trap: edit one, reload, and the edit is gone.
      * active    -- different paths AND different content. A reload changes what is served.
    """
    if not start_path or not reload_path or start_path == reload_path:
        return None
    a, b = read(start_path), read(reload_path)
    same_content = None if (a is None or b is None) else a == b
    return {
        "id": "reload-start-config-mismatch",
        # An unreadable side is NOT treated as identical: unknown content is a reason to
        # look, not a reason to relax. Only a proven byte match earns "latent".
        "severity": "latent" if same_content is True else "active",
        "start": start_path,
        "reload": reload_path,
        "files_identical_now": same_content,
        "what_it_means": (
            "`systemctl reload` loads a different file than `systemctl restart` serves. "
            + ("Identical right now, so nothing is wrong yet -- but an edit to the start "
               "file followed by a reload silently reverts it."
               if same_content is True else
               "THE FILES ALREADY DIFFER: a reload would change the served config."
               if same_content is False else
               "One of the two could not be read, so whether they agree is unknown.")),
    }


def _read_bytes(path: str) -> bytes | None:
    p = pathlib.Path(path)
    try:
        return p.read_bytes() if p.is_file() else None
    except OSError:
        return None


def audit() -> dict:
    start_path = _config_from("ExecStart")
    reload_path = _config_from("ExecReload")
    proc_path = _running_config()
    live = _live_config()

    result: dict = {
        "unit": UNIT,
        "active": _show("ActiveState"),
        "start_config": start_path,
        "reload_config": reload_path,
        "running_config": proc_path,
        "admin_api_reachable": live is not None,
        "findings": [],
    }

    # 1. Do the two verbs name the same file? This is the finding.
    mismatch = classify_verb_mismatch(start_path, reload_path, _read_bytes)
    if mismatch:
        result["findings"].append(mismatch)
        result["same_content"] = mismatch["files_identical_now"]

    # 2. Is the running process serving what systemd currently says it would?
    if proc_path and start_path and proc_path != start_path:
        result["findings"].append({
            "id": "running-differs-from-unit",
            "severity": "active",
            "running": proc_path, "unit_says": start_path,
            "what_it_means": ("the unit was edited since this process started; a restart "
                              "would change which file is served"),
        })

    # 3. Is the live config really the one that file produces? The only end-to-end check
    #    here -- everything above is about what systemd intends, not what is being served.
    if live is not None and proc_path:
        adapted = _normalise(_adapt(proc_path))
        result["live_matches_running_config_file"] = (
            None if adapted is None else _normalise(live) == adapted)
        if adapted is not None and _normalise(live) != adapted:
            result["findings"].append({
                "id": "live-config-not-from-file",
                "severity": "active",
                "what_it_means": (
                    f"the running instance is not serving what {proc_path} adapts to. "
                    "Something pushed a config through the admin API, or the file changed "
                    "since the last (re)start."),
            })

    return result


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    if not shutil.which("systemctl"):
        print("systemctl not available -- nothing to audit", file=sys.stderr)
        return 0

    r = audit()
    if args.json:
        print(json.dumps(r, indent=2))
        return 0

    print(f"{UNIT} ({r['active']})")
    print(f"  ExecStart  --config  {r['start_config']}")
    print(f"  ExecReload --config  {r['reload_config']}")
    print(f"  running process      {r['running_config']}")
    print(f"  admin API (GET only) {'reachable' if r['admin_api_reachable'] else 'unreachable'}")
    if r.get("live_matches_running_config_file") is True:
        print("  live config matches that file's adaptation: yes")
    elif r.get("live_matches_running_config_file") is False:
        print("  live config matches that file's adaptation: NO")

    if not r["findings"]:
        print("\n  no config-path incoherence found")
        return 0

    print(f"\n  {len(r['findings'])} finding(s):")
    for f in r["findings"]:
        print(f"\n  [{f['severity']}] {f['id']}")
        print(f"      {f['what_it_means']}")
    # Deliberately exit 0: every finding here is installed root state this cannot fix, and a
    # non-zero exit would make an unrelated caller's CI red for something it cannot action.
    # `tools/smoke.py` surfaces it as a loud SKIP instead, the same call made for the
    # external-traffic check.
    print("\n  exit 0: these are root-owned facts, reported not enforced. See RUNBOOK.md §6.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
