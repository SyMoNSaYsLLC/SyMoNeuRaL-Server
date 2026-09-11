"""Host tools -- running commands, reading and setting configuration, looking at the machine.

This is the group the brief meant by "configure existing apps, tools etc and have full access
to host system". `run_command` runs what it is given, `env_set` writes to the process
environment and optionally to a persisted env file, and `service_status` reads systemd. As of
2026-08-20 no command blocklist and no argument sanitiser are implemented here -- a deliberate
pre-launch state, not a cleared posture (request ledger R-98, held, being re-scoped per
surface).

Three things *are* enforced, and none of them is a filter on what may be done:

- **A timeout, on the process group.** A command that hangs would hold an HTTP request open
  until the client gives up and would leave the agent loop waiting on a future that never
  resolves. The default is 120 s, the caller can raise it, and a timeout is reported as a
  timeout rather than as an empty result. The bound is on the *group*: `subprocess.run`'s
  timeout kills only the shell and then waits on the inherited pipes with no timeout at all,
  so `run_command("nohup sleep 99999 &")` blocked that call forever -- and since sync tools
  dispatch through `anyio.to_thread.run_sync`, enough of those stall the whole serving API and
  not just this app. See `run_command` for the mechanism.
- **Output truncation.** A `find /` returning 40 MB into a 7B context window helps nobody.
  Truncation is reported with the character count that was dropped. Characters, not bytes:
  `Popen(text=True)` hands back decoded `str`, so `MAX_OUTPUT` and the dropped figure are both
  measured in what the model will actually be charged for, and the keys say `chars` so nobody
  reads a UTF-8 byte total off them.
- **`sudo` is passed through, not injected.** If a command needs root it will fail with the
  real permission error. Silently prefixing `sudo` would make the tool's behaviour differ
  from what the model was told it asked for.

`run_command` uses `shell=True` deliberately. The model writes shell -- pipes, redirects,
globs, `&&` -- and a `shlex.split` into `execve` would break every one of those in ways that
are hard for it to diagnose. There is no injection boundary being crossed here: the string
*is* the intended command, from a caller that already has `write_file`.

**This surface is off unless `SYMONEURAL_STUDIO_ENABLED=1` and `SYMONEURAL_STUDIO_TOKEN` are both set.**
`/api/*` is delegated wholly to FastAPI on a box with a public IP, so an ungated route here
would be an unauthenticated shell for anyone who found the port. That gate is the repo's own
convention (`apps/voice`, `apps/asicminer`), applied to the endpoint rather than to the tool:
nothing in this file inspects or refuses what it is asked to do.
"""
from __future__ import annotations

import authority

import json
import os
import pathlib
import shutil
import signal
import subprocess

from ..lib import workspace
from ..lib.registry import tool

MAX_OUTPUT = 100_000
DEFAULT_TIMEOUT = 120

# Names whose *values* are echoed as a fingerprint rather than in the clear. Not a refusal --
# the operator can read any of these off disk with `read_file` -- but this result is fed back
# into an LLM context that is rendered into a browser and may be written to the API log, and
# a token that leaks there leaks to a different audience than the one that asked.
#: Substring match against the UPPER-cased name. COOKIE and SIGNING were added 2026-09-03:
#: a session cookie and a signing key are bearer material exactly like a token, and the
#: sibling leak in `scripts/enable-surfaces.sh` was caused by a list that stopped one name
#: short. Broad-and-slightly-over-inclusive is the right error here -- masking a harmless
#: variable costs a length instead of a value; missing one costs the credential.
_SECRETISH = ("TOKEN", "SECRET", "PASSWORD", "PASSWD", "KEY", "CREDENTIAL", "APIKEY",
              "COOKIE", "SIGNING")


def _clip(s: str) -> tuple[str, int]:
    """(kept, dropped). Both measured in characters -- `s` is already decoded text, and
    `MAX_OUTPUT` is a context-window budget rather than a wire limit."""
    if len(s) <= MAX_OUTPUT:
        return s, 0
    return s[:MAX_OUTPUT], len(s) - MAX_OUTPUT


@tool("host", dangerous=True)
def run_command(command: str, cwd: str = "", timeout: int = DEFAULT_TIMEOUT) -> dict:
    """Run a shell command on the host and return its stdout, stderr and exit code.

    The command runs through the shell, so pipes, redirection and globs work. It runs as the
    API user; commands needing root report a real permission error rather than being silently
    elevated.

    Args:
        command: The shell command line.
        cwd: Working directory. Defaults to the project root.
        timeout: Seconds before the whole process group is killed and reported as timed out.
    """
    # AUTHORITY GATE. Studio admission ('service' effect) is not authority: passing
    # `enabled() + token_ok()` makes a caller admitted, not an owner. A shell here can restart units, edit files and read any secret this process holds.
    # No bound task -> NoTask -> refused, so this stays disabled until a surface is
    # converted to establish one. That default is the containment.
    authority.enforce('service', 'run_command')

    where = workspace.resolve(cwd) if cwd else (workspace.ROOT or pathlib.Path.cwd())
    if not pathlib.Path(where).is_dir():
        return {"error": "bad_cwd", "cwd": str(where)}
    try:
        # `start_new_session=True` puts the shell in its own process group, which is what makes
        # the timeout below able to kill everything the command started. Without it the kill
        # reaches `/bin/sh` only, its children keep the stdout pipe open, and the read that
        # follows never returns.
        proc = subprocess.Popen(command, shell=True, cwd=str(where), text=True,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                start_new_session=True)
    except OSError as e:
        return {"error": "spawn_failed", "command": command, "detail": str(e)}
    try:
        out_text, err_text = proc.communicate(timeout=max(1, timeout))
    except subprocess.TimeoutExpired:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            proc.kill()                     # group already gone, or never got one
        try:
            # Bounded, and second. The group is dead, so this drains what it wrote and returns;
            # the timeout is here for the one case that survives the kill -- a grandchild that
            # called `setsid()` itself and so is in neither group.
            partial_out, partial_err = proc.communicate(timeout=5)
        except subprocess.TimeoutExpired:
            partial_out = partial_err = ""
            for pipe in (proc.stdout, proc.stderr):
                if pipe is not None:
                    pipe.close()            # give up the fd rather than the thread
        clipped, _ = _clip(partial_out)
        clipped_err, _ = _clip(partial_err)
        return {"error": "timeout", "command": command, "timeout_s": timeout,
                "killed": "process_group", "stdout": clipped, "stderr": clipped_err}

    out, out_dropped = _clip(out_text)
    err, err_dropped = _clip(err_text)
    return {"command": command, "cwd": str(where), "exit_code": proc.returncode,
            "stdout": out, "stderr": err,
            "stdout_chars_dropped": out_dropped, "stderr_chars_dropped": err_dropped}


def _show(key: str, value: str) -> str:
    if any(t in key.upper() for t in _SECRETISH):
        return f"<set, {len(value)} chars, ends {value[-4:]!r}>" if len(value) > 8 else "<set>"
    return value


@tool("host")
def env_get(name: str = "") -> dict:
    """Read environment variables of the running API process.

    Values whose name looks like a secret come back as a length and a short fingerprint
    instead of in the clear, because this result is fed into an LLM context that is rendered
    into a browser and may be logged.

    That is transcript hygiene and not a confidentiality boundary, which matters because this
    docstring used to imply the second. `run_command` is in this same module at `:70`, in the
    same registry group, and it returns whatever a shell prints. Measured with
    `SYMONEURAL_STUDIO_TOKEN=s3cret-token-abcdefgh` set: this tool answered
    `<set, 21 chars, ends 'efgh'>` and `run_command("printenv SYMONEURAL_STUDIO_TOKEN")` answered
    `s3cret-token-abcdefgh`. So the mask keeps a secret out of a context window that did not
    ask for one; it does not keep it from an agent that asks. No blocklist is implemented on
    `run_command` for it as of 2026-08-20 -- a deliberate pre-launch state, not a cleared
    posture (R-98, held) -- and the gate in front of the surface is what stands between the two.

    Args:
        name: A single variable to read. Empty returns every name currently set.
    """
    if name:
        raw = os.environ.get(name)
        return {"name": name, "set": raw is not None,
                "value": _show(name, raw) if raw is not None else None}
    return {"count": len(os.environ),
            "vars": {k: _show(k, v) for k, v in sorted(os.environ.items())}}


@tool("host", dangerous=True)
def env_set(name: str, value: str, persist_to: str = "") -> dict:
    """Set an environment variable for the running process, and optionally persist it.

    A process-level set affects tools called from here onwards. It does NOT retroactively
    change settings the API already read at import, and it does not survive a restart -- pass
    persist_to to also write a KEY=value line into an env file that systemd reads.

    Args:
        name: Variable name.
        value: Variable value.
        persist_to: Path to an env file to update as well. An existing line is replaced.
    """
    # AUTHORITY GATE. Studio admission ('environment' effect) is not authority: passing
    # `enabled() + token_ok()` makes a caller admitted, not an owner. Setting an env var can flip a surface switch or a credential for the whole process.
    # No bound task -> NoTask -> refused, so this stays disabled until a surface is
    # converted to establish one. That default is the containment.
    authority.enforce('environment', 'env_set')

    os.environ[name] = value
    result: dict = {"name": name, "process_env": "set", "persisted": None,
                    "note": "already-imported settings are not re-read; restart to apply"}
    if not persist_to:
        return result

    p = workspace.resolve(persist_to)
    try:
        lines = p.read_text(encoding="utf-8").splitlines() if p.is_file() else []
    except OSError as e:
        return {**result, "error": "unreadable_env_file", "detail": str(e)}
    prefix = f"{name}="
    replaced = False
    for i, ln in enumerate(lines):
        if ln.startswith(prefix):
            lines[i] = f"{name}={value}"
            replaced = True
            break
    if not replaced:
        lines.append(f"{name}={value}")
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    except OSError as e:
        return {**result, "error": "write_failed", "detail": str(e)}
    result["persisted"] = {"file": str(p),
                           "action": "replaced" if replaced else "appended",
                           "note": "a service restart is required for this to take effect"}
    return result


@tool("host")
def service_status(name: str = "") -> dict:
    """Read systemd unit state.

    Args:
        name: Unit name, e.g. "symoneural-api". Empty lists the project's own units.
    """
    if not shutil.which("systemctl"):
        return {"error": "no_systemctl", "detail": "systemd is not available on this host"}
    try:
        if not name:
            p = subprocess.run(["systemctl", "list-units", "--type=service", "--all",
                                "--no-legend", "--no-pager", "symoneural*"],
                               capture_output=True, text=True, timeout=30)
            return {"units": [ln.strip() for ln in p.stdout.splitlines() if ln.strip()]}
        p = subprocess.run(
            ["systemctl", "show", name, "--no-pager",
             "--property=LoadState,ActiveState,SubState,MainPID,"
             "ExecMainStartTimestamp,Restart,FragmentPath"],
            capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.TimeoutExpired) as e:
        return {"error": "systemctl_failed", "detail": str(e)}
    fields = dict(ln.split("=", 1) for ln in p.stdout.splitlines() if "=" in ln)
    return {"unit": name, **fields}


@tool("host")
def gpu_status() -> dict:
    """The GPU, and who currently holds the governor lock.

    The lock matters more than the free-memory figure: this box has one 15.9 GiB card and the
    weight sets do not co-fit, so a surface that wants the GPU waits for whoever holds it.
    """
    info: dict = {}
    if shutil.which("nvidia-smi"):
        keys = ["name", "memory.total", "memory.used", "memory.free", "utilization.gpu",
                "temperature.gpu", "power.draw", "driver_version"]
        try:
            p = subprocess.run(["nvidia-smi", f"--query-gpu={','.join(keys)}",
                                "--format=csv,noheader,nounits"],
                               capture_output=True, text=True, timeout=30)
            info["gpu"] = dict(zip(keys, [v.strip() for v in p.stdout.strip().split(",")]))
        except (OSError, subprocess.TimeoutExpired) as e:
            info["gpu"], info["gpu_detail"] = None, str(e)
    else:
        info["gpu"], info["gpu_detail"] = None, "nvidia-smi not found"

    root = workspace.ROOT
    gov = (root / "scripts" / "gpu-governor.sh") if root else None
    if gov is not None and gov.is_file():
        try:
            p = subprocess.run(["bash", str(gov), "status"], capture_output=True,
                               text=True, timeout=30)
            parsed = {}
            for ln in p.stdout.splitlines():
                parts = ln.split(None, 1)
                if len(parts) == 2:
                    parsed[parts[0].strip()] = parts[1].strip()
            info["governor"] = parsed
            info["governor_raw"] = p.stdout.strip()
        except (OSError, subprocess.TimeoutExpired) as e:
            info["governor"], info["governor_detail"] = None, str(e)
    return info


@tool("host")
def disk_usage(path: str = ".") -> dict:
    """Free space on the filesystem holding a path, plus the size of that path.

    Args:
        path: Absolute, or relative to the project root.
    """
    p = workspace.resolve(path)
    if not p.exists():
        return {"error": "not_found", "path": str(p)}
    total, used, free = shutil.disk_usage(p)
    out: dict = {"path": str(p),
                 "filesystem": {"total_bytes": total, "used_bytes": used, "free_bytes": free,
                                "used_pct": round(used / total * 100, 1)}}
    # `du` on a large tree is slow enough to deserve a timeout and an honest "did not finish"
    # rather than a number that is really a guess.
    try:
        d = subprocess.run(["du", "-sb", str(p)], capture_output=True, text=True, timeout=60)
        out["path_bytes"] = int(d.stdout.split()[0]) if d.returncode == 0 else None
    except (OSError, subprocess.TimeoutExpired, ValueError, IndexError):
        out["path_bytes"] = None
        out["path_bytes_detail"] = "du did not finish inside 60s"
    return out


@tool("host")
def python_packages(venv: str = "") -> dict:
    """List installed Python packages, for the system interpreter or a specific venv.

    Args:
        venv: Path to a venv directory. Empty means the interpreter running the API.
    """
    exe = str(workspace.resolve(venv) / "bin" / "python") if venv else "python3"
    if venv and not pathlib.Path(exe).is_file():
        return {"error": "no_such_venv", "python": exe}
    try:
        p = subprocess.run([exe, "-m", "pip", "list", "--format=json"],
                           capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.TimeoutExpired) as e:
        return {"error": "pip_failed", "python": exe, "detail": str(e)}
    if p.returncode != 0:
        return {"error": "pip_failed", "python": exe, "stderr": p.stderr[:2000]}
    try:
        pkgs = json.loads(p.stdout)
    except json.JSONDecodeError:
        return {"error": "unparseable", "python": exe, "stdout": p.stdout[:2000]}
    return {"python": exe, "count": len(pkgs),
            "packages": {d["name"]: d["version"] for d in pkgs}}
