#!/usr/bin/env python3
# SPDX-License-Identifier: LicenseRef-SyMoNeuRaL-Proprietary
# Copyright (c) 2026 SymonSays LLC. All rights reserved.
"""Keep exactly ONE storage_reorg owner alive until there is no work left.

    tools/storage_reorg_supervisor.py            run until quiescent
    tools/storage_reorg_supervisor.py --status    report without changing anything

## Why this exists

`storage_reorg.py` loads its operation table once, at import. Operations added to the file
while a run is in flight are therefore invisible to that run -- correctly so, since editing
a live table mid-transfer is how the shell pipelines used to corrupt themselves. But it
means a long unattended session needs something to notice "that run finished, and there are
now more operations than it knew about" and start the next one.

That is all this does. It is not a second mutation owner: it starts no rclone, packs no
archive and touches no file outside its own log. It waits, checks, and relaunches.

## The invariant it protects

    ACTIVE_STORAGE_MUTATION_OWNERS == 1   whenever there is work
    ACTIVE_STORAGE_MUTATION_OWNERS == 0   once quiescent

Before launching anything it scans /proc for a live owner and for the lock file's pid. If
either says an owner is alive it waits rather than starting a second. It never kills the
owner: the spec forbids killing a running owner merely to install newer tooling, and a
transfer interrupted at UPLOADING costs the whole upload again unless the remote already
holds it.

## When it stops

* no operation is left in a non-terminal state -- the work is genuinely done;
* or the same set of non-terminal operations survives several consecutive runs, which
  means relaunching is no longer making progress and a human should look. Spinning on a
  stuck operation forever would look like progress in the log while achieving nothing.

FAILED operations are terminal here on purpose. `storage_reorg` fails closed: a FAILED
operation is one whose source is untouched and whose cause nobody has diagnosed, so
relaunching into it repeatedly is exactly the destructive retry the state machine refuses.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import subprocess
import sys
import time

ROOT = pathlib.Path("/home/google/Symoneural")
STATE = ROOT / ".private" / "storage-reorg" / "state.json"
LOCK = ROOT / ".private" / "storage-reorg" / "owner.lock"
LOGDIR = ROOT / ".private" / "storage-reorg"
SUP_LOG = LOGDIR / "supervisor.log"

TERMINAL = {"COMPLETE", "FAILED"}
POLL = 60                 # seconds between liveness checks
MAX_STALLED_ROUNDS = 3    # identical pending set this many times => stop and report
MARKERS = ("storage_reorg.py run", "storage_reorg.py resume")


def log(msg: str) -> None:
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S%z')}  {msg}"
    print(line, flush=True)
    LOGDIR.mkdir(parents=True, exist_ok=True)
    with SUP_LOG.open("a") as fh:
        fh.write(line + "\n")
    os.chmod(SUP_LOG, 0o600)


def live_owners() -> list[tuple[int, str]]:
    """Every live storage_reorg run/resume other than this supervisor."""
    me = os.getpid()
    out = []
    for p in pathlib.Path("/proc").iterdir():
        if not p.name.isdigit() or int(p.name) == me:
            continue
        try:
            cmd = (p / "cmdline").read_bytes().replace(b"\0", b" ").decode(
                "utf-8", "replace").strip()
        except OSError:
            continue
        if not cmd or "supervisor" in cmd:
            continue
        if any(m in cmd for m in MARKERS):
            out.append((int(p.name), cmd))
    return sorted(out)


def lock_owner() -> int | None:
    """The lock file's pid, if it is still alive. A stale lock is not an owner."""
    if not LOCK.is_file():
        return None
    try:
        pid = int(LOCK.read_text().strip())
        os.kill(pid, 0)
        return pid
    except (ValueError, OSError):
        return None


def pending() -> set[str]:
    if not STATE.is_file():
        return {"<no ledger yet>"}
    try:
        ops = json.loads(STATE.read_text()).get("ops") or {}
    except json.JSONDecodeError:
        return {"<ledger unreadable>"}
    return {k for k, v in ops.items() if v.get("state") not in TERMINAL}


def total_operations() -> int:
    """How many operations the CURRENT file defines, which is what a fresh run would see."""
    r = subprocess.run(
        [sys.executable, "-c",
         "import importlib.util;"
         "s=importlib.util.spec_from_file_location('m','tools/storage_reorg.py');"
         "m=importlib.util.module_from_spec(s);s.loader.exec_module(m);"
         "print(len(m.OPERATIONS))"],
        cwd=ROOT, capture_output=True, text=True, timeout=300)
    try:
        return int(r.stdout.strip())
    except ValueError:
        return -1


def launch() -> int:
    stamp = time.strftime("%Y%m%d-%H%M%S")
    logf = LOGDIR / f"run-{stamp}.log"
    with logf.open("w") as fh:
        p = subprocess.Popen(
            [sys.executable, "-u", "tools/storage_reorg.py", "resume"],
            cwd=ROOT, stdout=fh, stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL, start_new_session=True)
    latest = LOGDIR / "latest.log"
    try:
        if latest.is_symlink() or latest.exists():
            latest.unlink()
        latest.symlink_to(logf.name)
    except OSError:
        pass
    log(f"launched storage_reorg resume pid={p.pid} log={logf.name}")
    return p.pid


def status() -> int:
    owners = live_owners()
    log(f"live owners: {len(owners)}")
    for pid, cmd in owners:
        log(f"  pid {pid}: {cmd[:120]}")
    lo = lock_owner()
    log(f"lock pid alive: {lo if lo else 'no'}")
    pend = pending()
    log(f"operations defined now: {total_operations()}")
    log(f"non-terminal in ledger: {len(pend)}")
    for k in sorted(pend)[:12]:
        log(f"  pending: {k}")
    return 0


def main(argv) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--status", action="store_true")
    ap.add_argument("--max-hours", type=float, default=14.0)
    a = ap.parse_args(argv)
    if a.status:
        return status()

    log(f"supervisor start; {total_operations()} operations defined")
    deadline = time.monotonic() + a.max_hours * 3600
    last_pending: set[str] | None = None
    stalled = 0
    cycles = 0

    while time.monotonic() < deadline:
        owners = live_owners()
        if owners or lock_owner():
            # An owner is working. Wait. Never start a second, never kill this one.
            time.sleep(POLL)
            continue

        pend = pending()
        if not pend:
            log("no non-terminal operations remain; supervisor exiting cleanly")
            return 0

        if pend == last_pending:
            stalled += 1
            log(f"same {len(pend)} operations pending after a completed run "
                f"(stall {stalled}/{MAX_STALLED_ROUNDS})")
            if stalled >= MAX_STALLED_ROUNDS:
                log("relaunching is no longer making progress; stopping for review")
                for k in sorted(pend):
                    log(f"  still pending: {k}")
                return 2
        else:
            stalled = 0
        last_pending = set(pend)

        cycles += 1
        log(f"cycle {cycles}: {len(pend)} pending, {total_operations()} defined")
        launch()
        time.sleep(POLL)          # let it take its lock before the next liveness check

    log(f"reached the {a.max_hours}h limit; leaving any running owner alone")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
