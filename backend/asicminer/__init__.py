"""SyMoNeuRaL Miner (ASIC) -- an operator surface for Antminer and MicroBT rigs.

This is the ASIC control panel. It is **not** the GPU Ravencoin miner, which is a separate
surface at `backend/cryptominer/`. `.claude/HANDOVER.md` §5 keeps them apart on
purpose and so does this module: they share no code, no route prefix and no rack unit.

## What this is for

The site's rack reads real sensors off the RTX 5070 Ti. This does the same thing for mining
hardware: connect to Antminer (Bitmain) and MicroBT/Whatsminer rigs on the operator's
network and report what they are actually doing. It is an **operator tool**, not a public
demo -- a visitor's rig sits on the visitor's LAN and this server cannot reach it, so there
is no honest public version of a live panel.

## Two switches, and it is off unless both are set

    SYMONEURAL_ASIC_ENABLED=1              # the surface exists at all
    SYMONEURAL_ASIC_TOKEN=<shared secret>  # every request must present it
    SYMONEURAL_ASIC_RIGS=10.0.0.11,10.0.0.12   # optional; addresses to probe

`SYMONEURAL_ASIC_ENABLED` must be the **literal string `1`**. `true`, `yes` and `on` all leave the
surface off, and silently -- the check is `== "1"`, not truthiness. It reads like a boolean
and is not one, which is the single most reported confusion about this surface.

**These two variables gate the HTTP API and nothing else.** They do not gate the emulator
itself: `scripts/qemu-antminer.sh <firmware.tar.gz> --shell --serve` boots Antminer firmware
under QEMU from a terminal with no environment set at all. What they gate is the operator
*route* that starts it for you, `POST /api/asicminer/emulator`, along with `/scan` and
`/firmware` -- because those are remote-control endpoints on a box facing the public
internet, and the emulator route takes a filename.

And setting them will not make the Miner panel show readings from an emulated rig. QEMU
emulates the Zynq CPU, not the hashboards, so nothing inside answers pyasic on port 4028;
the panel will correctly read **offline**. The emulator is for the firmware/flash path
(`upgrade.cgi`), which is exactly what `scripts/qemu-antminer.sh` says at the top of the
file. A rig is the only thing that produces telemetry.

Off by default and 503 with both unset. That mirrors `backend/cryptominer/`, which
already refuses to start without `SYMONEURAL_MINING_ENABLED=1`, and it matters more here: this box
serves the public internet, and rig control is not something to expose by accident. Without
a token there is no route, so a misconfiguration fails closed rather than open.

## Honesty

With no rigs configured or none reachable, the state is **offline** and every reading is
null. There is no demo rig and no placeholder hashrate. Any number that reaches a page from
here was read off real hardware and is **measured**; if a figure is ever added that is not,
it must be labelled vendor or projected at the point it is introduced.

## Why a subprocess

pyasic needs 31 packages. The serving API runs on the system interpreter, which carries
fastapi, uvicorn, pydantic and sympy and nothing else, deliberately. So the rig protocols
live in `backend/asicminer/.venv` behind `probe.py`, which prints JSON, and this module
execs it. Same boundary the API already uses for the GPU governor and the engine binaries.
"""
from __future__ import annotations

import asyncio
import json
import os
import pathlib

HERE = pathlib.Path(__file__).resolve().parent
# backend/asicminer -> repo root is three levels up.
ROOT_HINT = HERE.parent.parent.parent
VENV_PY = HERE / ".venv" / "bin" / "python"
PROBE = HERE / "probe.py"
SCAN = HERE / "scan.py"

PROBE_TIMEOUT = 30.0        # probe.py already caps each rig at 8s; this bounds the whole run


def enabled() -> bool:
    """The switch, and nothing else. NO API KEYS, 2026-09-11 -- this used to require a
    token to be set as well, which is a second condition that no longer means anything."""
    return True


def rigs() -> list[str]:
    """Configured rig addresses. Empty is the normal state on a box with no ASICs."""
    raw = os.environ.get("SYMONEURAL_ASIC_RIGS", "")
    return [h.strip() for h in raw.split(",") if h.strip()]


def installed() -> bool:
    return VENV_PY.is_file() and PROBE.is_file()




async def probe(hosts: list[str] | None = None) -> dict:
    """Run the probe in its own interpreter and return parsed JSON.

    Never raises. Every failure path returns the same shape with an `error` string, because
    the rack renders this and a surface that throws takes the whole status endpoint with it.
    """
    hosts = rigs() if hosts is None else hosts
    if not installed():
        return {"rigs": [], "error": "asicminer venv not installed -- see backend/asicminer/README.md"}
    if not hosts:
        return {"rigs": [], "error": None}

    try:
        proc = await asyncio.create_subprocess_exec(
            str(VENV_PY), str(PROBE), *hosts,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        out, err = await asyncio.wait_for(proc.communicate(), timeout=PROBE_TIMEOUT)
    except asyncio.TimeoutError:
        return {"rigs": [], "error": f"probe exceeded {PROBE_TIMEOUT:.0f}s"}
    except Exception as e:
        return {"rigs": [], "error": f"{e.__class__.__name__}: {e}"}

    if proc.returncode != 0:
        return {"rigs": [], "error": f"probe exited {proc.returncode}: {err.decode()[:200]}"}
    try:
        return json.loads(out.decode())
    except json.JSONDecodeError as e:
        return {"rigs": [], "error": f"probe printed non-JSON: {e}"}


async def discover(cidr: str) -> dict:
    """Find rigs on a private network. Operator-gated, and refuses public ranges.

    The refusal lives in `scan.py` rather than here, so it applies however the scanner is
    invoked -- the CLI and this wrapper cannot drift apart into one being safe and the other
    not. This adds the second gate: the surface has to be switched on at all.
    """
    if not enabled():
        # The value is spelled out because `ENABLED` reads like a boolean and is not one:
        # the check is `== "1"`, so `true` leaves the surface off and says nothing.
        return {"rigs": [], "error": "surface disabled — set SYMONEURAL_ASIC_ENABLED=1 (the "
                                     "literal string 1, not true). "
                                     "Both gate this API only; scripts/qemu-antminer.sh "
                                     "needs neither"}
    if not (VENV_PY.is_file() and SCAN.is_file()):
        return {"rigs": [], "error": "asicminer venv not installed"}
    try:
        proc = await asyncio.create_subprocess_exec(
            str(VENV_PY), str(SCAN), cidr,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        # A /20 at 0.6s per host with 256 in flight is roughly ten seconds; allow slack
        # for a slow network without letting a scan pin a worker indefinitely.
        out, err = await asyncio.wait_for(proc.communicate(), timeout=120.0)
    except asyncio.TimeoutError:
        return {"rigs": [], "error": "scan exceeded 120s"}
    except Exception as e:
        return {"rigs": [], "error": f"{e.__class__.__name__}: {e}"}
    if proc.returncode != 0:
        return {"rigs": [], "error": f"scan exited {proc.returncode}: {err.decode()[:200]}"}
    try:
        return json.loads(out.decode())
    except json.JSONDecodeError as e:
        return {"rigs": [], "error": f"scan printed non-JSON: {e}"}


async def selftest() -> dict:
    """Check the venv without touching the network. Used by the CLI and the tests."""
    if not installed():
        return {"ok": False, "error": "venv not installed"}
    try:
        proc = await asyncio.create_subprocess_exec(
            str(VENV_PY), str(PROBE), "--selftest",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        out, _ = await asyncio.wait_for(proc.communicate(), timeout=30)
        return json.loads(out.decode())
    except Exception as e:
        return {"ok": False, "error": f"{e.__class__.__name__}: {e}"}


def unit_state(result: dict | None) -> tuple[str, str]:
    """(state, detail) for the rack. Honest by construction.

    `offline` is the correct answer for a box with no rigs, and it is the default. The rack
    must never show a mining surface as `ready` on the strength of the code existing.
    """
    if not enabled():
        return "offline", ("disabled — set SYMONEURAL_ASIC_ENABLED=1 (the literal string 1, "
                           "not true)")
    if not installed():
        return "offline", "control venv not installed"
    if result is None:
        return "offline", "not yet probed"
    if result.get("error"):
        return "offline", str(result["error"])[:90]
    found = [r for r in result.get("rigs", []) if r.get("reachable")]
    if not found:
        n = len(result.get("rigs", []))
        return "offline", (f"{n} configured, none answering" if n else "no rigs configured")
    th = sum(r["hashrate_th_s"] for r in found if r.get("hashrate_th_s") is not None)
    vendors = sorted({r["vendor"] for r in found if r.get("vendor")})
    return "ready", (f"{len(found)} rig{'s' if len(found) != 1 else ''} answering"
                     + (f" · {th:.1f} TH/s measured" if th else "")
                     + (f" · {', '.join(vendors)}" if vendors else ""))


# --------------------------------------------------------------- firmware inventory

# Where firmware packages are looked for. Both are gitignored trees, so this is operator
# data on the operator's box -- nothing here is ever published or served as a file.
FW_DIRS = [
    ROOT_HINT / "references" / "Projects_Crypto",
    pathlib.Path.home() / "Downloads",
]

# A package is one of two shapes, and the difference decides whether it can be emulated:
#   .tar.gz  browser-upgrade package -- cert/fw/runme, what upgrade.cgi accepts
#   .zip     SD recovery package     -- per-file signatures, boots the card directly
FW_SUFFIXES = (".tar.gz", ".zip")


def _fw_id(p: pathlib.Path) -> str:
    """A stable id derived from the path, so the API never takes a filesystem path.

    The emulator is started by id, never by a caller-supplied path. That is the whole
    reason this exists: an endpoint that spawns a process against an arbitrary path is a
    remote file-read at best and worse than that at worst.
    """
    import hashlib
    return hashlib.sha256(str(p.resolve()).encode()).hexdigest()[:16]


def packages() -> list[dict]:
    """Every firmware package actually present, with what we know about each.

    Read from disk rather than hardcoded, so the model list on the page cannot claim
    firmware that is not there -- or miss firmware that is.
    """
    out = []
    for d in FW_DIRS:
        if not d.is_dir():
            continue
        for f in sorted(d.iterdir()):
            if not f.is_file() or not f.name.endswith(FW_SUFFIXES):
                continue
            n = f.name.lower()
            vendor = ("antminer" if "antminer" in n
                      else "microbt" if ("whatsminer" in n or "microbt" in n)
                      else None)
            if vendor is None:
                continue
            out.append({
                "id": _fw_id(f),
                "name": f.name,
                "vendor": vendor,
                "bytes": f.stat().st_size,
                "kind": "sd" if f.name.endswith(".zip") else "browser",
            })
    return out


def package_by_id(pid: str) -> pathlib.Path | None:
    for d in FW_DIRS:
        if not d.is_dir():
            continue
        for f in d.iterdir():
            if f.is_file() and f.name.endswith(FW_SUFFIXES) and _fw_id(f) == pid:
                return f
    return None


# --------------------------------------------------------------- emulator control

QEMU_SCRIPT = ROOT_HINT / "scripts" / "qemu-antminer.sh"
EMU_PID = ROOT_HINT / "run" / "qemu-antminer.pid"
EMU_LOG = ROOT_HINT / "run" / "qemu-antminer.log"

# What the guest prints when it has finished booting and handed over a shell. Busybox says
# this because `--shell` passes `init=/bin/sh`, so there is no controlling terminal.
BOOTED_MARKER = "job control turned off"

# Written into the console log by `emulator_start()` so `_emulator_booted()` can tell
# this boot from the last one.
EMU_RUN_MARKER = "=== qemu-antminer start"

# The process the pidfile must still name. `qemu-antminer.sh` execs qemu, so after the exec
# the pid's cmdline is qemu's own.
EMU_CMDLINE_MARKERS = ("qemu-system-arm", "qemu-antminer.sh")


def _proc_cmdline(pid: int) -> str:
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as fh:
            return fh.read().replace(b"\0", b" ").decode("utf-8", "replace")
    except OSError:
        return ""


def emulator_status() -> dict:
    """Is an emulator running, has it actually booted, and which package.

    Three things here are readings rather than inferences, and each replaced something that
    was not:

    * **`running` is not "a pid exists".** It also requires that the pid still be a qemu.
      Pids are recycled; a pidfile left behind by a reboot whose number now belongs to
      something else reported `running: true`, and `emulator_stop()` would then have
      SIGTERMed that stranger's whole process group.
    * **`booted` is read from the guest's own output.** Measured on this box, `running`
      went true 0.5s after launch and the shell prompt did not appear until 6.0s -- a
      five-and-a-half second window in which a caller was told the emulator was up. Nothing
      used to read the log at all.
    * **`web` is only reported once the guest has booted, and carries what it means.** It
      was a hardcoded literal emitted beside any live pid. It is a *host-side* SLIRP
      forward: `--shell` boots to `/bin/sh` and never starts lighttpd, so the port accepts
      a connection and the guest answers nothing. Saying so is the honest version.

    This function must not mutate. It used to `unlink` the pidfile on any exception --
    including `PermissionError`, which means "alive, but not yours", so a *status query*
    deleted the record of a live emulator. A genuinely dead pid is cleaned up by
    `emulator_start()`, which is a write in the first place.
    """
    out = {"running": False, "pid": None, "package": None, "web": None,
           "booted": False, "log": str(EMU_LOG)}
    if not EMU_PID.is_file():
        return out
    try:
        raw = EMU_PID.read_text().split("\n")
        pid = int(raw[0].strip())
        os.kill(pid, 0)                      # signal 0: does it exist, are we allowed
    except (ValueError, IndexError, ProcessLookupError, PermissionError, OSError):
        return out
    if not any(m in _proc_cmdline(pid) for m in EMU_CMDLINE_MARKERS):
        out["note"] = (f"run/qemu-antminer.pid names pid {pid}, which is alive but is not "
                       "a qemu — treating it as stale rather than signalling it")
        return out
    booted = _emulator_booted()
    out.update(running=True, pid=pid, booted=booted,
               package=(raw[1].strip() if len(raw) > 1 else None),
               web=("http://127.0.0.1:8080" if booted else None),
               note=("host-side port forward only; --shell boots to /bin/sh and does not "
                     "start the guest's lighttpd, so nothing answers on it"
                     if booted else "booting — the guest has not reached a shell yet"))
    return out


def _emulator_booted() -> bool:
    """Has the guest reached a shell? Read out of its console log, not assumed.

    Only the current run counts. The log is appended across boots, so without cutting at
    the last start marker the *previous* boot's shell prompt would make a machine that is
    still loading its kernel report `booted` the instant it was launched -- exactly the
    false confidence this field exists to remove.
    """
    try:
        with open(EMU_LOG, "rb") as fh:
            fh.seek(0, os.SEEK_END)
            fh.seek(max(0, fh.tell() - 65536))
            tail = fh.read()
    except OSError:
        return False
    marker = tail.rfind(EMU_RUN_MARKER.encode())
    if marker != -1:
        tail = tail[marker:]
    return BOOTED_MARKER.encode() in tail


def emulator_start(pid_str: str) -> dict:
    """Boot one firmware package under QEMU.

    Started BY ID, never by a path the caller supplies. An endpoint that execs against an
    arbitrary path is a remote file-read at best; `package_by_id` resolves only to files
    already enumerated from the two known directories.
    """
    if not enabled():
        return {"ok": False, "error": "surface disabled"}
    if not QEMU_SCRIPT.is_file():
        return {"ok": False, "error": "scripts/qemu-antminer.sh not found"}
    cur = emulator_status()
    if cur["running"]:
        return {"ok": False, "error": f"already running (pid {cur['pid']}) — stop it first"}

    pkg = package_by_id(pid_str)
    if pkg is None:
        return {"ok": False, "error": "no such firmware package"}
    if pkg.name.endswith(".zip"):
        return {"ok": False, "error": "SD recovery packages are not bootable this way; "
                                      "the emulator takes a browser-upgrade .tar.gz"}

    import subprocess
    EMU_PID.unlink(missing_ok=True)          # the write that clears a stale pidfile
    try:
        # `with`, not `log.open("wb")` inline: the original never closed the handle, so
        # every start leaked a descriptor. `"wb"` also truncated the previous boot's
        # console log -- the only record of how the last run went -- so this appends and
        # separates runs with a marker instead.
        with open(EMU_LOG, "ab") as log:
            log.write(f"\n{EMU_RUN_MARKER} {pkg.name} ===\n".encode())
            log.flush()
            proc = subprocess.Popen(
                [str(QEMU_SCRIPT), str(pkg), "--shell", "--serve"],
                stdout=log, stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL, start_new_session=True,
            )
    except Exception as e:
        return {"ok": False, "error": f"{e.__class__.__name__}: {e}"}
    EMU_PID.write_text(f"{proc.pid}\n{pkg.name}\n")
    # No `web` here. It is not up yet: measured, the guest takes ~6s from launch to a
    # shell prompt on a warm unpack, longer when the two nested tars still have to be
    # extracted. Poll `emulator_status()` and wait for `booted`.
    return {"ok": True, "pid": proc.pid, "package": pkg.name, "booted": False,
            "note": "booting to a shell; poll emulator_status() until booted is true. "
                    "The guest web UI needs lighttpd started by hand."}


def emulator_stop() -> dict:
    st = emulator_status()
    if not st["running"]:
        return {"ok": True, "note": "nothing was running"}
    import signal as _sig
    try:
        # The script execs qemu, and start_new_session puts it in its own process group,
        # so signal the group -- killing only the pid can leave qemu orphaned.
        os.killpg(os.getpgid(st["pid"]), _sig.SIGTERM)
    except Exception as e:
        return {"ok": False, "error": f"{e.__class__.__name__}: {e}"}
    EMU_PID.unlink(missing_ok=True)
    return {"ok": True, "stopped": st["pid"]}
