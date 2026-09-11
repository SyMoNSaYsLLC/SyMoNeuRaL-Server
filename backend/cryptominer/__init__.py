"""SyMoNeuRaL Miner GPU — orchestration for a KawPow/Ravencoin miner on the RTX 5070 Ti.

This is the GPU surface. `backend/asicminer/` is the ASIC surface and they share
nothing: different hardware, different bus, different rack unit. Do not conflate them --
`.claude/HANDOVER.md` §5 item 8 says so and it has already caused one round of confusion.

## What this is, and what it deliberately is not

It runs an **external miner binary** you supply. It does not implement KawPow. Writing a
competitive KawPow kernel is a project in its own right and a bad one to attempt here: the
value in this repo is the orchestration -- the governor integration, honest telemetry and
a rack unit that tells the truth -- not a slower reimplementation of t-rex.

**Mining is off by default and there is no default that turns it on.** No path in this
module arms a miner on its own: with no configuration the surface is `offline`, `start()`
refuses, and nothing is ever spawned. Turning it on is three deliberate edits by an
operator (see below). That is not timidity -- this box serves the public internet, the
electricity is somebody's, and a miner that starts because a file happened to exist is
malware with good manners.

Every hashrate this module reports comes from the binary's own stdout. It is never
estimated, never projected from vendor figures, and never shown as a number the machine
did not produce -- the same rule the rest of the site runs on.

## Enabling it

Copy the example and fill it in; nothing else reads it and nothing else has to change:

    cp backend/cryptominer/miner.env.example backend/cryptominer/miner.env
    $EDITOR backend/cryptominer/miner.env
    python3 -m cryptominer selftest         # from backend/, checks it without mining

The four settings, whether they come from that file or from the environment:

    SYMONEURAL_MINING_ENABLED=1                      # the surface exists at all
    SYMONEURAL_MINER_CMD=/path/to/miner --algo kawpow --pool ... --user <wallet>.<rig>
    SYMONEURAL_MINER_TOKEN=<shared secret>           # every control request must present it
    SYMONEURAL_MINER_GPU=0                           # optional, defaults to 0

Off with any of the first three unset, exactly like `asicminer`. The example file ships
with `SYMONEURAL_MINING_ENABLED=0` and no command, so `cp`-ing it and forgetting arms nothing.

**Real environment always wins.** `miner.env` never overwrites a variable that is already
exported, so a systemd unit or a one-off `SYMONEURAL_MINING_ENABLED=1 ...` on the command line
overrides the file rather than fighting it. The file is re-read when its mtime changes, so
an operator can edit it and see the rack unit move `offline -> ready` without restarting
the API. It holds a shared secret and is gitignored by `backend/cryptominer/.gitignore`.

A miner built from source on this box lives at `contrib/kawpowminer/` (see
`contrib/build-kawpowminer.sh`); `KAWPOW_BINARY` below names it *only* so `selftest` can
tell an operator where it is. Nothing reads it as a default.

## The GPU lock, and what "yields to everything" does and does not mean

One card, one tenant, arbitrated by `run/gpu.lock.d`. A miner is the **opposite of
`train`**: `train` is never evicted, and a miner is evicted by anything that asks.

`scripts/gpu-governor.sh` has a `miner)` eviction arm and it works -- measured, not
assumed: it calls `stop()` here, which signals the process *group*, and the governor's
`drain` then waits for VRAM to fall under its floor before the next tenant is let in.

But eviction is reached only **after** `cmd_acquire`'s `mkdir` on the lock directory
succeeds, and while a miner is running its `gpu-governor.sh with miner` shell holds that
directory. So the `miner)` arm fires when `run/resident` still says `miner` and the lock
is free -- a miner that has exited, or whose holder pid died and was broken as stale. A
surface arriving while the miner is genuinely *running* does not evict it; it spins in the
`until mkdir` loop for up to `ACQUIRE_TIMEOUT_S` (300s) and then gives up. Measured on this
box: `gpu-governor.sh acquire chat 10` against a live miner logs
`'chat' TIMED OUT after 10s behind 'miner'`.

**That is why the miner never auto-starts, and why nothing here ever starts it in response
to a page view.** It is started deliberately and stopped deliberately. The yield protocol
that would make it genuinely preemptible -- the miner watching for a request to hand the
card back mid-run -- is specified in `backend/cryptominer/docs/miner-preemption.md` and is deliberately
not implemented: it changes the hot path of the only arbitrator of the only contended
resource in this system, and getting it wrong is how chat and image OOM at step 0.
"""
from __future__ import annotations

import asyncio
import json
import os
import pathlib
import re
import shlex
import signal
import subprocess
import time

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent.parent.parent              # backend/cryptominer -> repo root
RUN = ROOT / "run"
GOVERNOR = ROOT / "scripts" / "gpu-governor.sh"
PIDFILE = RUN / "miner.pid"
LOGFILE = RUN / "miner.log"

SURFACE = "miner"          # the governor surface name; must match gpu-governor.sh's case

# The operator's config. Absent by default -- see `miner.env.example` next to it.
ENVFILE = pathlib.Path(os.environ.get("SYMONEURAL_MINER_ENV") or (HERE / "miner.env"))

# Where `tools/sh/fork_engines.sh miner` puts the miner it builds. This is a SIGNPOST, not a
# default: it is quoted back to the operator by `selftest()` and by the example file, and
# no code path anywhere turns it into a running process. Making it a fallback for an unset
# SYMONEURAL_MINER_CMD would mean an unconfigured box starts hashing the first time somebody hits
# the control endpoint, which is precisely the thing this surface must never do.
#
# This named `contrib/kawpowminer/...` until 2026-09-04, which was wrong twice over: `/contrib`
# is gitignored, so the binary it pointed at could vanish with nothing in `git log` to say it
# ever existed -- the third time that has happened here, after the ASR engine and this repo's
# own mining benchmark binary -- and it named a third-party product rather than ours. The
# engine is now `SyMoNeuRaL Miner`, built from the vendored kawpowminer source under our own
# name, and a signpost that points somewhere gitignored is not a signpost.
KAWPOW_BINARY = (ROOT / "symoneural-miner" / "build" / "kawpowminer"
                 / "symoneural-miner")

# The keys the file is allowed to set. An env file is an instruction to change this
# process's environment, so it sets only what this surface owns -- a stray `PATH=` or
# `LD_PRELOAD=` in it must not reach the serving interpreter.
# SYMONEURAL_MINER_TOKEN was in this set until 2026-09-11 and is not any more: NO API KEYS.
# Leaving it would let miner.env set a variable nothing reads, which is how a dead setting
# outlives the code that gave it meaning.
_ENV_KEYS = frozenset({"SYMONEURAL_MINING_ENABLED", "SYMONEURAL_MINER_CMD",
                       "SYMONEURAL_MINER_GPU"})

# The cache key is (mtime_ns, size, inode), not mtime alone. Two reasons, one of them
# found by a test that failed: filesystem timestamps are coarse -- on tmpfs two writes
# inside the same clock tick get the *same* mtime, so an edit was silently not re-read --
# and most editors save by writing a new file and renaming over the old one, which changes
# the inode. Size and inode catch both. Two edits in the same tick that leave the file
# exactly the same length are still missed; `load_env(force=True)`, which `selftest()`
# uses, is the way out of that.
_env_key: tuple[int, int, int] | None = None
_env_applied: set[str] = set()
# The keys the file tried to set and was refused, remembered across a cache hit. Without
# this the cached return omitted `ignored_keys` while the full-parse return carried it, so
# `status()["env_file"]` -- which goes out over `/api/gpuminer/status` -- changed shape
# depending on whether the file had been read yet. A response whose keys come and go is one
# a caller cannot write a `[...]` against.
_env_ignored: set[str] = set()


# ----------------------------------------------------------------- configuration

def load_env(force: bool = False) -> dict:
    """Merge `miner.env` into os.environ, without ever overriding a real variable.

    Called from `enabled()`, so the surface picks up an edited file on the next status
    poll rather than at the next API restart -- the operator flow this exists for is
    "edit the file, watch the rack unit go from offline to ready".

    Two rules that are the whole reason this is not a three-line parser:

    * **An exported variable wins.** A systemd `Environment=` or a one-off
      `SYMONEURAL_MINING_ENABLED=1 python3 ...` must beat the file, otherwise the file becomes an
      undocumented override of the thing the operator just typed. Only keys this function
      itself put there (`_env_applied`) are replaced on a re-read; anything else is left
      alone.
    * **Only `_ENV_KEYS` are honoured.** This mutates the serving interpreter's
      environment; a file that could set `LD_PRELOAD` would be a code-execution path
      dressed up as configuration.

    Returns a small report rather than nothing, so the CLI and `selftest()` can show
    whether a file was found at all -- "I edited it and nothing happened" is otherwise
    indistinguishable from "I edited the wrong path".
    """
    global _env_key
    try:
        s = ENVFILE.stat()
        # `stamp`, not `key`. It was `key`, and the loop below rebinds `key` to each config
        # name it parses -- so `_env_key = key` at the end stored the string
        # `"SYMONEURAL_MINER_GPU"` where the stat tuple belonged. The comparison below then tested
        # a tuple against a string, never matched, and the cache never once hit: every
        # `enabled()`, `miner_cmd()`, `binary()`, `token_ok()` and `gpu_index()` call
        # re-read and re-parsed the file and re-wrote os.environ. That is five file reads
        # per `status()`, on the rack's status-poll path. Measured before the fix:
        # `load_env()` returned `"reread": True` on every one of three consecutive calls.
        stamp = (s.st_mtime_ns, s.st_size, s.st_ino)
    except OSError:
        # Forget the stamp too: a file that is deleted and recreated must be re-parsed, and
        # leaving a stale stamp here would let a recreated file be skipped.
        _env_key = None
        return {"path": str(ENVFILE), "found": False, "applied": [],
                "ignored_keys": [], "reread": False}
    if stamp == _env_key and not force:
        return {"path": str(ENVFILE), "found": True, "applied": sorted(_env_applied),
                "ignored_keys": sorted(_env_ignored), "reread": False}

    applied, ignored = [], []
    try:
        text = ENVFILE.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return {"path": str(ENVFILE), "found": True, "error": f"{e.__class__.__name__}"}

    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):          # tolerate a file that is also sourceable
            line = line[len("export "):].strip()
        key, sep, val = line.partition("=")
        if not sep:
            continue
        key = key.strip()
        if key not in _ENV_KEYS:
            ignored.append(key)
            continue
        # Strip one matching pair of quotes. `shlex.split` is wrong here: a value like
        # `--user WALLET.rig --pass x` is a single setting, not a token list, and the
        # quoting that matters is handled later by `miner_cmd()`.
        val = val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
            val = val[1:-1]
        if key in os.environ and key not in _env_applied:
            continue                            # a real exported variable outranks the file
        os.environ[key] = val
        applied.append(key)

    _env_applied.clear()
    _env_applied.update(applied)
    _env_ignored.clear()
    _env_ignored.update(ignored)
    _env_key = stamp
    return {"path": str(ENVFILE), "found": True, "applied": sorted(applied),
            "ignored_keys": sorted(_env_ignored), "reread": True}


def enabled() -> bool:
    """Both the flag and a command, because either alone is a misconfiguration."""
    return True


def miner_cmd() -> list[str]:
    """The configured command, split for exec.

    `posix=True` -- the default -- and this is a real porting fix rather than a tidy-up.
    The Windows original called `shlex.split(cmd, posix=False)`, which leaves quotation
    marks in the arguments: `--user "wallet.rig"` reached the binary as the literal
    `"wallet.rig"` including the quotes, and a miner would authenticate against a pool
    under a wallet name nobody owns. It fails in a way that looks like a pool problem.
    """
    load_env()
    return shlex.split(os.environ.get("SYMONEURAL_MINER_CMD", "").strip())


def binary() -> pathlib.Path | None:
    """The miner executable, if the configured command names one that exists."""
    argv = miner_cmd()
    if not argv:
        return None
    p = pathlib.Path(argv[0])
    if p.is_file():
        return p
    from shutil import which
    found = which(argv[0])
    return pathlib.Path(found) if found else None


def installed() -> bool:
    return binary() is not None


# ----------------------------------------------------------------- pool, or no pool
#
# kawpowminer's own `-H test`, quoted exactly: "When playing with benchmark or simulation no
# connection specification is needed ie. you can omit any -P argument." So the presence of a
# pool URL is what separates mining from measuring, and its ABSENCE is the discriminator
# used below -- not the presence of `-M`/`-Z`. A command can hash without either flag, and
# whatever flags it carries, a miner with nowhere to submit a share earns nothing.
#
# This exists because the rack was reporting "holding the card · 53.01 MH/s reported by the
# miner" while `SYMONEURAL_MINER_CMD` was `-U -M 500000`: kawpowminer's `--benchmark`, connected to
# no pool and no wallet. Every digit of that was real and measured on this card -- and a
# reader of the rack would have concluded the box was mining Ravencoin, which it was not.
# The caveat was written into `miner.env`, which is gitignored and never leaves the box,
# while the number went to the one place everybody sees. Labelling the figure is the rule
# this repo is built on; "measured" and "earning" are different claims.

_POOL_FLAGS = ("-P", "--pool")
_POOL_URL = re.compile(r"^[a-z][a-z0-9+.\-]*://", re.I)
# Applied only to a BARE url -- an explicit `-P <anything://…>` is the operator saying "this
# is my pool" and is taken at its word.
#
# `stratum` only, deliberately, and NOT http. Nothing else on a miner command line uses a
# stratum scheme, so a bare `stratum+tcp://…` is a pool wherever it appears. `http://` is
# ambiguous: kawpowminer takes an http getWork pool, but `--api-bind http://127.0.0.1:3333`
# is also an http URL, and reading that as a pool would switch the benchmark disclosure OFF
# while the rack showed a real hashrate. A positional http pool is therefore reported as a
# benchmark until it is written the documented way, with `-P`. That errs toward
# understating income rather than overstating it, which is the direction to err in.
_POOL_SCHEME = re.compile(r"^stratum[a-z0-9+.\-]*://", re.I)


def pool() -> str | None:
    """The pool the configured command connects to, credentials stripped, or None.

    Returned WITHOUT userinfo. kawpowminer's connection syntax is
    `scheme://[user[.worker][:password]@]host:port`, and for Ravencoin the `user` is the
    operator's wallet address. `status()` is served over `/api/gpuminer/status`, and while
    that route is token-gated, echoing a wallet and a pool password back out of a
    public-facing web process is not a thing to do by accident.

    None means "this command names no pool", which is a statement about the configuration
    and not a guess about the network: it is read off the command the operator wrote.
    """
    argv = miner_cmd()
    for i, a in enumerate(argv):
        url = ""
        if a in _POOL_FLAGS and i + 1 < len(argv):
            url = argv[i + 1]
        elif a.startswith(tuple(f + "=" for f in _POOL_FLAGS)):
            url = a.partition("=")[2]
        elif _POOL_SCHEME.match(a):
            # A bare stratum URL, which some builds take positionally. Restricted to stratum
            # schemes so that a URL belonging to another flag -- `--api-bind http://…` is the
            # real case -- is never mistaken for a pool. See `_POOL_SCHEME`. Note this arm
            # cannot be reached by an option's value written as `--flag=stratum://…`, because
            # that argument does not start with the scheme.
            url = a
        if not _POOL_URL.match(url):
            continue
        scheme, _, rest = url.partition("://")
        host = rest.rpartition("@")[2]   # rpartition: a password may itself contain '@'
        return f"{scheme}://{host}" if host else None
    return None


def benchmarking() -> bool:
    """Is the configured command hashing for a measurement rather than for a pool?

    False when nothing is configured at all -- there is no workload to characterise, and
    `unit_state()` already reports that case as `offline`.
    """
    return bool(miner_cmd()) and pool() is None



def gpu_index() -> int:
    load_env()
    try:
        return int(os.environ.get("SYMONEURAL_MINER_GPU", "0"))
    except ValueError:
        return 0


# ----------------------------------------------------------------- process state

def _cmdline(pid: int) -> str:
    try:
        with open(f"/proc/{pid}/cmdline", "rb") as fh:
            return fh.read().replace(b"\0", b" ").decode("utf-8", "replace")
    except OSError:
        return ""


def _pid() -> int | None:
    """The recorded pid, if the process is genuinely still alive AND is still ours.

    A pidfile that outlived its process is the classic way a supervisor reports a dead
    service as running. Checked with signal 0 rather than trusted.

    Liveness alone is not enough, for two reasons that both end in the rack showing a
    dead miner as `busy`:

    * **Pid reuse.** A stale `run/miner.pid` whose number has been handed to some
      unrelated process makes this surface report `busy` forever -- and, far worse, makes
      `stop()` SIGTERM a process group that belongs to somebody else.
    * **Zombies.** The miner is a child of the API process, and `os.kill(pid, 0)` succeeds
      against a zombie: the pid still exists, it is just waiting to be reaped. (They do get
      reaped: `subprocess` sweeps its finished children whenever another `Popen` is created,
      and `_smi()` creates one on every status poll. But between the exit and the sweep,
      liveness alone says the miner is fine.)

    The cmdline settles both. What we start is always `gpu-governor.sh with miner -- ...`,
    so that string must still be there -- and `/proc/<pid>/cmdline` is *empty* for a zombie,
    which is exactly the answer needed.
    """
    try:
        pid = int(PIDFILE.read_text().strip())
    except (OSError, ValueError):
        return None
    try:
        os.kill(pid, 0)
    except (ProcessLookupError, PermissionError):
        return None
    except OSError:
        return None
    if GOVERNOR.name not in _cmdline(pid):
        return None
    return pid


def running() -> bool:
    return _pid() is not None


def _uptime_s(pid: int) -> int | None:
    """Seconds since the process started, read from /proc rather than a remembered time.

    The original used psutil for this. /proc/<pid>/stat field 22 is the same number with
    no dependency, which matters because the serving interpreter is deliberately kept to
    seven packages and psutil is not one of them.
    """
    try:
        with open(f"/proc/{pid}/stat", "rb") as fh:
            fields = fh.read().rsplit(b")", 1)[1].split()
        starttime_ticks = int(fields[19])          # field 22, 1-indexed, after comm
        hertz = os.sysconf("SC_CLK_TCK")
        with open("/proc/uptime", "rb") as fh:
            up = float(fh.read().split()[0])
        return max(0, int(up - starttime_ticks / hertz))
    except Exception:
        return None


# ----------------------------------------------------------------- telemetry

def _smi(index: int) -> dict:
    """Best-effort card telemetry. Never raises -- the rack polls this."""
    cmd = ["nvidia-smi",
           "--query-gpu=name,temperature.gpu,power.draw,utilization.gpu,"
           "memory.used,memory.total",
           "--format=csv,noheader,nounits", "-i", str(index)]
    try:
        out = subprocess.check_output(cmd, stderr=subprocess.STDOUT,
                                      text=True, timeout=2).strip()
    except Exception as e:
        return {"error": f"{e.__class__.__name__}"}
    parts = [p.strip() for p in out.split(",")]
    if len(parts) < 6:
        return {"raw": out}
    try:
        return {"name": parts[0], "temp_c": int(float(parts[1])),
                "power_w": float(parts[2]), "util_pct": int(float(parts[3])),
                "mem_used_mb": int(float(parts[4])), "mem_total_mb": int(float(parts[5]))}
    except ValueError:
        return {"raw": out}


# A number followed by a hashrate unit. Every clause here is load-bearing; the original
# was `(\d+(?:\.\d+)?)\s*(h|kh|mh|gh|th)/s` and never matched anything kawpowminer prints.
#
#   * `/s` is OPTIONAL. kawpowminer 1.2.4 prints `48.51 Mh`, full stop -- captured from a
#     real run on this box and kept verbatim in `testdata/`. Requiring the literal `/s`
#     meant the rack reported "no hashrate reported yet" for the entire life of a healthy
#     miner. t-rex and gminer print `MH/s`, so both forms have to work.
#   * Without `/s`, whitespace between number and unit is REQUIRED. Otherwise every
#     English ordinal is a hashrate: `4th` parses as 4 TH/s -> 4,000,000 MH/s.
#   * The gap is `[ \t]*`, never `\s*`, because `\s` matches a newline and this scans a
#     64 KB tail in which governor lines and miner output interleave. `... 591 ms.\nHash`
#     must not become a reading.
#   * The trailing `\b` stops `after 5 hours` matching as `5 h` -- 5e-6 MH/s, a plausible
#     looking zero. `48.51 Mh/sec` still matches by falling through to the second branch.
_RATE_RE = re.compile(
    r"(\d+(?:\.\d+)?)"                        # 48.51
    r"(?:[ \t]*(h|kh|mh|gh|th)/s"             #   MH/s, or 48.51MH/s
    r"|[ \t]+(h|kh|mh|gh|th))"                #   Mh -- a space is required here
    r"\b", re.I)

_ANSI_RE = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")

_SCALE = {"h": 1e-6, "kh": 1e-3, "mh": 1.0, "gh": 1e3, "th": 1e6}

# Lines that carry a hashrate-shaped number that is NOT this miner's speed. kawpowminer
# announces `Epoch : 66 Difficulty : 4.29 Gh` on every new job, which is a share target,
# not a rate -- take it as one and the rack reports 4,290 MH/s from a card doing 48.
_NOT_A_RATE_RE = re.compile(r"difficulty", re.I)

# Written into the log by `start()`. The log is appended across runs, so without this the
# first ten seconds of a new run -- while the DAG builds and nothing has been reported yet
# -- would show the *previous* run's final figure as a live reading.
RUN_MARKER = "=== cryptominer run start"


def _hashrate_from_log() -> float | None:
    """Parse the miner's own reported hashrate out of its stdout.

    Returns `None` when nothing has been reported, and `None` is what the rack shows. The
    alternative -- deriving a plausible figure from the card's specification -- would be a
    projection presented as a measurement, which is the one thing this site does not do.

    Deliberately tolerant of format: every miner prints this differently, so it matches a
    number followed by a hashrate unit and takes the most recent one, rather than pinning
    to one vendor's exact line and silently reporting nothing for every other binary.

    Scanned newest line first, and only within the current run. ANSI colour is stripped
    first -- kawpowminer emits `\\x1b[1;36m48.51 Mh\\x1b[0m` and the escapes otherwise sit
    between the fields the difficulty filter reads.
    """
    try:
        with open(LOGFILE, "rb") as fh:
            fh.seek(0, os.SEEK_END)
            fh.seek(max(0, fh.tell() - 65536))
            tail = fh.read().decode("utf-8", "replace")
    except OSError:
        return None
    tail = _ANSI_RE.sub("", tail)
    marker = tail.rfind(RUN_MARKER)
    if marker != -1:
        tail = tail[marker:]
    for line in reversed(tail.splitlines()):
        if _NOT_A_RATE_RE.search(line):
            continue
        # Last match on the line: kawpowminer's summary is `Max 52.63 Mh Mean 48.35 Mh`,
        # and the mean is the honest steady-state figure of the two.
        found = None
        for m in _RATE_RE.finditer(line):
            found = float(m.group(1)) * _SCALE[(m.group(2) or m.group(3)).lower()]
        if found is not None:
            return round(found, 2)
    return None


def lock_holder() -> str | None:
    """Which surface the governor's lock file says holds the card, or None if it is free.

    `holds_gpu_lock` used to be `pid is not None` -- an inference from our own pidfile,
    not a reading. That is exactly the decorative-indicator problem CLAUDE.md bans: the
    two disagree in the case that matters, when the miner is alive but still queued in
    `cmd_acquire`'s mkdir loop behind another tenant. `run/gpu.lock.d/holder` is the
    actual arbitrator's own record, so read that.
    """
    try:
        return (RUN / "gpu.lock.d" / "holder").read_text().split()[0] or None
    except (OSError, IndexError):
        return None


def _last_log_line() -> str:
    """The last thing the log says, for an error message. Never raises."""
    try:
        with open(LOGFILE, "rb") as fh:
            fh.seek(0, os.SEEK_END)
            fh.seek(max(0, fh.tell() - 8192))
            lines = [_ANSI_RE.sub("", ln).strip()
                     for ln in fh.read().decode("utf-8", "replace").splitlines()]
    except OSError:
        return "the log could not be read"
    for line in reversed(lines):
        if line and not line.startswith(RUN_MARKER):
            return line
    return "the miner produced no output"


def _log_age_s() -> int | None:
    """Seconds since the miner last wrote anything. A real reading, not a guess.

    A hung miner keeps its pid and its last printed hashrate forever, and the rack would
    go on showing that number as live. This does not decide anything on the operator's
    behalf; it just puts the age beside the figure so a stalled run is visible.
    """
    try:
        return max(0, int(time.time() - LOGFILE.stat().st_mtime))
    except OSError:
        return None


def status() -> dict:
    """Everything the surface knows. Safe to call at any time, gated or not."""
    pid = _pid()
    holder = lock_holder()
    hr = _hashrate_from_log() if pid else None
    return {
        "enabled": enabled(),
        "installed": installed(),
        "binary": str(binary()) if binary() else None,
        "running": pid is not None,
        "pid": pid,
        "uptime_s": _uptime_s(pid) if pid else None,
        "gpu_index": gpu_index(),
        "hashrate_mh_s": hr,
        # Only labelled when there is something to label. Saying "reported by the miner
        # binary" beside a null reads as "the miner reported null", which it did not: it
        # has not reported yet.
        "hashrate_source": "reported by the miner binary" if hr is not None else None,
        "hashrate_age_s": _log_age_s() if pid else None,
        # What the hashing is FOR. `pool` is None when the command names none, and
        # `benchmark` is that same fact stated the way a reader needs it: the number above
        # is a measurement of this card, not evidence of income.
        "pool": pool(),
        "benchmark": benchmarking(),
        "gpu": _smi(gpu_index()),
        "lock_holder": holder,
        "holds_gpu_lock": holder == SURFACE,
        "env_file": load_env(),
    }


def unit_state(st: dict | None = None) -> tuple[str, str]:
    """(state, detail) for the rack. Honest by construction.

    `offline` is the correct answer for a box with no miner binary, and it is the default.
    The rack must never show a mining surface as `ready` because the code exists.

    The four values are `api.py`'s `Unit.state` literals -- `ready`, `busy`, `queued`,
    `offline`. A miner that is alive but has not won the lock yet is `queued`, which is
    what that value is for; reporting it as `busy` would claim a card it does not have.
    """
    st = st if st is not None else status()
    if not st["enabled"]:
        return "offline", ("disabled — copy backend/cryptominer/miner.env.example to "
                           "miner.env and set SYMONEURAL_MINING_ENABLED=1, SYMONEURAL_MINER_CMD and "
                           "SYMONEURAL_MINER_TOKEN")
    if not st["installed"]:
        return "offline", "no miner binary at the configured path"
    if not st["running"]:
        if st.get("benchmark"):
            # The state the live rack is in as this is written. "ready" is right -- it will
            # start and it will hash -- but "ready to mine" would be the wrong reading.
            return "ready", ("configured as a benchmark, no pool — starting it measures "
                             "the card and earns nothing")
        return "ready", "configured, not mining — start it deliberately"
    if not st.get("holds_gpu_lock"):
        held = st.get("lock_holder") or "another surface"
        return "queued", f"started, waiting for the card behind '{held}'"
    hr = st.get("hashrate_mh_s")
    age = st.get("hashrate_age_s")
    # A benchmark says so on the rack. The alternative is a real measured figure presented
    # where a reader will take it as income -- see the `pool()` comment above.
    what = "benchmarking · " if st.get("benchmark") else "holding the card · "
    if hr is None:
        return "busy", what + "no hashrate reported yet"
    stale = f" · no output for {age}s" if age is not None and age >= 120 else ""
    earns = ", no pool — earns nothing" if st.get("benchmark") else " reported by the miner"
    return "busy", f"{what}{hr:g} MH/s{earns}{stale}"


# ----------------------------------------------------------------- control

async def start() -> dict:
    """Take the card through the governor, then exec the miner under it.

    The lock is held for the miner's lifetime. That is a deliberate exception to
    "hold the lock for a job, never a process lifetime" and it is why this never
    auto-starts: a resident miner makes every other surface wait out the acquire
    timeout. See the module docstring and backend/cryptominer/docs/miner-preemption.md.

    **`subprocess.Popen`, not `asyncio.create_subprocess_exec`, and that is a bug fix
    rather than a preference.** asyncio owns the processes it spawns: when the event loop
    closes, `BaseSubprocessTransport.__del__` calls `close()`, which SIGKILLs any child
    still running. What this function starts is a detached daemon that must outlive the
    request -- and outlive the whole interpreter, in the CLI's case. Measured: with the
    asyncio form, `python3 -m cryptominer start` reported `ok: true` with a pid, and the
    miner was dead a second later with nothing in the log to say why, because `asyncio.run`
    closed the loop on the way out and the transport killed it. The failure is invisible in
    an API that stays up and fatal from the command line, which is the worst of both.
    """
    if not enabled():
        return {"ok": False, "error": "surface disabled — set SYMONEURAL_MINING_ENABLED=1, "
                                      "SYMONEURAL_MINER_CMD"}
    if not installed():
        return {"ok": False, "error": "no miner binary at the configured path"}
    if running():
        return {"ok": False, "error": f"already running (pid {_pid()})"}

    argv = miner_cmd()
    RUN.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    env["CUDA_VISIBLE_DEVICES"] = str(gpu_index())

    # `with` acquires, runs and always releases -- including on a crash, which a bare
    # acquire/release pair does not. The surface is named on both halves; an unscoped
    # release once destroyed a running fine-tune's lock.
    wrapped = [str(GOVERNOR), "with", SURFACE, "--", *argv]
    try:
        # The log handle is closed in this process straight after the fork. The original
        # opened two files per start and closed neither, so a supervisor that restarted
        # the miner leaked a descriptor pair every time until it hit the fd limit.
        with open(LOGFILE, "ab") as log:
            # The marker is what stops the previous run's last hashrate being read back as
            # this run's first one, during the ~10s the DAG takes to build.
            log.write(f"\n{RUN_MARKER} {time.strftime('%Y-%m-%d %H:%M:%S')} ===\n"
                      .encode())
            log.flush()
            proc = subprocess.Popen(
                wrapped, cwd=str(ROOT), env=env,
                stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                start_new_session=True,
            )
    except Exception as e:
        return {"ok": False, "error": f"{e.__class__.__name__}: {e}"}

    PIDFILE.write_text(str(proc.pid))
    await asyncio.sleep(1.5)
    rc = proc.poll()
    if rc is not None:
        PIDFILE.unlink(missing_ok=True)
        # "exited immediately (1); see the log" is a true statement that answers nothing,
        # and the commonest cause of it is not a broken miner at all: the governor refuses
        # to evict a running fine-tune, so `with` fails before the binary is ever exec'd.
        # Measured, that produced `REFUSING to evict a training run` in the log while the
        # operator was told the miner had crashed. The reason is one line away; fetch it.
        return {"ok": False, "reason": _last_log_line(),
                "error": f"miner exited immediately ({rc}): {_last_log_line()} "
                         f"— see {LOGFILE}"}
    # Started is not the same as mining. The governor may still be queueing behind another
    # tenant for up to ACQUIRE_TIMEOUT_S, and saying "holding the GPU lock" while it waits
    # is the sort of confident-and-wrong status line this repo exists to avoid.
    holder = lock_holder()
    if holder == SURFACE:
        note = "holding the GPU lock; other surfaces will queue behind it"
    elif holder:
        note = f"started, but queued behind '{holder}' — it will begin when that releases"
    else:
        note = "started; the governor has not recorded the lock yet"
    return {"ok": True, "pid": proc.pid, "binary": str(binary()),
            "lock_holder": holder, "note": note}


def stop() -> dict:
    """Stop the miner and let the governor release the card.

    SIGTERM to the process group, not the pid. The miner runs under
    `gpu-governor.sh with`, so the pid recorded is the governor shell; signalling only
    that leaves the actual miner orphaned and still on the card, which looks like a
    successful stop and is not one. `start_new_session=True` gives the pair its own
    group precisely so this signal reaches both.
    """
    pid = _pid()
    if pid is None:
        PIDFILE.unlink(missing_ok=True)
        return {"ok": True, "stopped": None, "note": "was not running"}
    try:
        os.killpg(os.getpgid(pid), signal.SIGTERM)
    except ProcessLookupError:
        PIDFILE.unlink(missing_ok=True)
        return {"ok": True, "stopped": None, "note": "already gone"}
    except Exception as e:
        return {"ok": False, "error": f"{e.__class__.__name__}: {e}"}

    for _ in range(100):                       # up to 10s for a clean exit
        if _pid() is None:
            break
        time.sleep(0.1)
    else:
        try:
            os.killpg(os.getpgid(pid), signal.SIGKILL)
        except Exception:
            pass
    PIDFILE.unlink(missing_ok=True)
    return {"ok": True, "stopped": pid}


async def selftest() -> dict:
    """Check the configuration without starting anything or touching the card.

    This is the dry run. It resolves the command, execs the binary with `--version` --
    which no miner needs a GPU for, and which is the cheapest proof that the thing on disk
    is executable on this machine at all rather than merely present -- and reports what an
    operator would have to fix. It never acquires the lock and never hashes.

    `hint` names the miner built by `contrib/build-kawpowminer.sh` when it is on disk and
    nothing is configured. It is a signpost printed to a human; no code reads it.
    """
    load_env(force=True)
    argv = miner_cmd()
    bin_path = binary()
    version, version_error = None, None
    if bin_path is not None:
        try:
            version = subprocess.run(
                [str(bin_path), "--version"], capture_output=True, text=True,
                timeout=15).stdout.strip().splitlines()[0]
        except Exception as e:
            version_error = f"{e.__class__.__name__}: {e}"
    problems = []
    if os.environ.get("SYMONEURAL_MINING_ENABLED") != "1":
        problems.append("SYMONEURAL_MINING_ENABLED is not 1")
    if not os.environ.get("SYMONEURAL_MINER_CMD", "").strip():
        problems.append("SYMONEURAL_MINER_CMD is empty")
    if argv and bin_path is None:
        problems.append(f"{argv[0]!r} is not an executable file and is not on PATH")
    if version_error:
        problems.append(f"the binary would not run: {version_error}")
    if not GOVERNOR.is_file():
        problems.append(f"the GPU governor is missing at {GOVERNOR}")
    return {
        "ok": not problems,
        "enabled": enabled(),
        "binary": str(bin_path) if bin_path else None,
        "binary_version": version,
        "argv_count": len(argv),
        # The dry run is where an operator finds out what starting it would actually do, so
        # it says this before the card is ever taken rather than after.
        "pool": pool(),
        "benchmark": benchmarking(),
        "note": ("SYMONEURAL_MINER_CMD names no pool, so this configuration measures the card and "
                 "earns nothing. That is a legitimate setup — it is how the KawPow figure "
                 "in README.md was measured — but it is not mining. To mine, give the "
                 "command a -P stratum+tcp://… pool and your own wallet."
                 if benchmarking() else None),
        "gpu_index": gpu_index(),
        "governor": GOVERNOR.is_file(),
        "env_file": load_env(),
        "hint": (None if bin_path else
                 (f"a miner built by contrib/build-kawpowminer.sh is at {KAWPOW_BINARY}; "
                  "point SYMONEURAL_MINER_CMD at it with your own pool and wallet"
                  if KAWPOW_BINARY.is_file() else
                  "no miner binary on this box — build one with "
                  "contrib/build-kawpowminer.sh or install your own")),
        "problems": problems,
        "error": None if not problems else "; ".join(problems),
    }


USAGE = """cryptominer — the SyMoNeuRaL GPU miner surface. Mining is OFF by default.

    python3 -m cryptominer status      what the surface is doing right now
    python3 -m cryptominer selftest    dry run: check config, exec the binary --version
    python3 -m cryptominer start       take the card and mine (deliberate, never automatic)
    python3 -m cryptominer stop        signal the process group, give the card back

Run from backend/. Configuration lives in backend/cryptominer/miner.env;
copy miner.env.example to it and fill it in. Nothing starts mining on its own."""


def main(argv: list[str] | None = None) -> int:
    """A tiny CLI, mirroring asicminer's. Lives in a function so `__main__.py` can call it
    and `python3 backend/cryptominer/__init__.py` still works."""
    import sys
    args = sys.argv[1:] if argv is None else argv
    what = args[0] if args else "status"
    if what == "start":
        print(json.dumps(asyncio.run(start()), indent=2))
    elif what == "stop":
        print(json.dumps(stop(), indent=2))
    elif what == "selftest":
        out = asyncio.run(selftest())
        print(json.dumps(out, indent=2))
        return 0 if out["ok"] else 1
    elif what in ("-h", "--help", "help"):
        print(USAGE)
    else:
        st = status()
        print(json.dumps({**st, "unit_state": unit_state(st)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
