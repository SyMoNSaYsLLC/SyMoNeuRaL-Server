"""Filesystem tools.

Every path argument goes through `workspace.resolve`, so a relative path means "relative to
the project root" no matter what directory the API process happens to be started from -- the
systemd unit and a hand-run `uvicorn` disagree about cwd, and a tool whose meaning changed
between them would be worse than useless.

There is no path containment check and that is deliberate: the operator asked for host-wide
access and the guard on this surface is the two-switch token gate in `__init__.py`. What is
here instead is *truthfulness* -- every result reports what actually happened, including the
cases people usually paper over: a truncated read says it truncated and how many bytes it
skipped, a write reports the byte count and whether it created or replaced, and a binary file
is refused as binary rather than returned as mojibake.
"""
from __future__ import annotations

import authority

import os
import pathlib
import shutil
import signal
import subprocess
import threading

from ..lib import workspace
from ..lib.registry import tool

# Reading a whole 125 KB api.py into a 7B model's context is a legitimate thing to want and
# an easy way to blow the window by accident. The cap is a default, not a ceiling -- the
# caller can raise it -- and the result always says whether it bit.
DEFAULT_MAX_BYTES = 200_000


def _stat(p: pathlib.Path) -> dict:
    try:
        st = p.lstat()
    except OSError as e:
        return {"name": p.name, "error": str(e)}
    kind = ("symlink" if p.is_symlink() else
            "dir" if p.is_dir() else
            "file" if p.is_file() else "other")
    row = {"name": p.name, "kind": kind, "bytes": st.st_size, "mode": oct(st.st_mode & 0o777),
           "mtime": int(st.st_mtime)}
    if p.is_symlink():
        try:
            row["target"] = os.readlink(p)
        except OSError:
            pass
    return row


#: Wall-clock ceiling on one `search` or `find_files`. A bound on the result count does not
#: bound a grep that matches nothing across a large tree, so both limits are needed.
SEARCH_TIMEOUT_S = 60


def _bounded(cmd: list[str], want: int, timeout: int) -> tuple[list[str], bool, str | None]:
    """Run `cmd`, read at most `want + 1` output lines, then kill it. -> (lines, expired, error)

    Slicing the output afterwards is what this replaces, and the slice bounded the reply
    without bounding the work in exactly the way `read_file`'s did before it started reading
    `want + 1` bytes: `search("def", "/")` ran grep over the whole host and brought every match
    into this process before cutting the list. The extra line is how `truncated` stays honest
    without a second pass.

    `start_new_session=True` plus `killpg`, for the reason `host.run_command` documents at
    length: a kill that reaches only the child leaves grandchildren holding the stdout pipe and
    the read that follows never returns. `grep` and `find` do not fork, but the deadline timer
    has to be able to end whatever is on the other end of that pipe.

    `expired` is reported separately from truncation because they mean different things to the
    caller: truncated says "there is more", expired says "we stopped looking before we knew".
    """
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                text=True, start_new_session=True)
    except OSError as e:
        return [], False, str(e)

    expired = False

    def kill_group() -> None:
        try:
            os.killpg(os.getpgid(proc.pid), signal.SIGKILL)
        except (ProcessLookupError, PermissionError, OSError):
            proc.kill()                     # group already gone, or never got one

    def on_deadline() -> None:
        nonlocal expired
        expired = True
        kill_group()

    timer = threading.Timer(max(1, timeout), on_deadline)
    timer.start()
    lines: list[str] = []
    try:
        for raw in proc.stdout:
            raw = raw.rstrip("\n")
            if raw:
                lines.append(raw)
            if len(lines) > want:
                break
    finally:
        timer.cancel()
        proc.stdout.close()
        # Unconditional. The loop above normally leaves the child mid-tree with a closed pipe;
        # a child that already exited on its own makes this a no-op.
        kill_group()
        proc.wait()
    return lines, expired, None


@tool("workspace")
def workspace_root() -> dict:
    """Where the agent is working: the project root, how it was found, and what is in it.

    Call this first when you are unsure what project you are in. The root is discovered at
    startup by looking for scripts/gpu-governor.sh and backend/server.py together.
    """
    info = workspace.describe()
    root = workspace.ROOT
    if root is not None:
        try:
            info["entries"] = sorted(d.name for d in root.iterdir())
        except OSError as e:
            info["entries_error"] = str(e)
    return info


@tool("workspace")
def list_dir(path: str = ".", show_hidden: bool = False) -> dict:
    """List one directory. Not recursive -- use `search` to go deep.

    Args:
        path: Absolute, or relative to the project root.
        show_hidden: Include dotfiles.
    """
    p = workspace.resolve(path)
    if not p.is_dir():
        return {"error": "not_a_directory", "path": str(p), "exists": p.exists()}
    try:
        kids = sorted(p.iterdir(), key=lambda d: (not d.is_dir(), d.name.lower()))
    except OSError as e:
        return {"error": "unreadable", "path": str(p), "detail": str(e)}
    if not show_hidden:
        kids = [d for d in kids if not d.name.startswith(".")]
    return {"path": str(p), "count": len(kids), "entries": [_stat(d) for d in kids]}


@tool("workspace")
def read_file(path: str, max_bytes: int = DEFAULT_MAX_BYTES, start_line: int = 0,
              end_line: int = 0) -> dict:
    """Read a text file. Reports truncation instead of hiding it.

    Args:
        path: Absolute, or relative to the project root.
        max_bytes: Stop after this many bytes. The result says whether it truncated.
        start_line: 1-based first line to return. 0 means from the beginning.
        end_line: 1-based last line, inclusive. 0 means to the end.
    """
    p = workspace.resolve(path)
    if not p.is_file():
        return {"error": "not_a_file", "path": str(p), "exists": p.exists()}
    size = p.stat().st_size
    want = max(0, max_bytes)
    try:
        with p.open("rb") as fh:
            # `read(want + 1)`, not `read_bytes()[:want]`. Slicing after the read means the whole
            # file comes into the interpreter first: `read_file("/proc/kcore")` or any of the
            # multi-GB `.gguf` files under `backend/models/` would OOM the serving process, and
            # `max_bytes` -- documented above as "stop after this many bytes" -- bounded only the
            # return value. The extra byte is how truncation is detected without trusting
            # `st_size`, which is 0 for most of `/proc` and 128 TiB for `/proc/kcore`.
            raw = fh.read(want + 1)
    except OSError as e:
        return {"error": "unreadable", "path": str(p), "detail": str(e)}
    truncated = len(raw) > want
    raw = raw[:want]
    # A NUL in the first block is the cheap, reliable binary test. Returning the replacement
    # character soup from a .safetensors would waste the model's context and teach it nothing.
    if b"\x00" in raw[:8192]:
        return {"error": "binary_file", "path": str(p), "bytes": size,
                "detail": "contains NUL bytes; not decoded as text"}
    text = raw.decode("utf-8", errors="replace")

    lines_total = text.count("\n") + (0 if text.endswith("\n") or not text else 1)
    if start_line or end_line:
        lines = text.splitlines()
        lo = max(0, start_line - 1) if start_line else 0
        hi = min(len(lines), end_line) if end_line else len(lines)
        text = "\n".join(lines[lo:hi])
    return {"path": str(p), "bytes": size, "bytes_returned": len(raw),
            "truncated": truncated, "lines": lines_total, "text": text}


@tool("workspace", dangerous=True)
def write_file(path: str, content: str, append: bool = False, make_parents: bool = True) -> dict:
    """Write a text file. Creates or replaces; reports which, and the previous size.

    Args:
        path: Absolute, or relative to the project root.
        content: The full new contents (or the text to append).
        append: Append instead of replacing.
        make_parents: Create missing parent directories.
    """
    # AUTHORITY GATE. Studio admission ('workspace' effect) is not authority: passing
    # `enabled() + token_ok()` makes a caller admitted, not an owner. A write can replace source the release is built from.
    # No bound task -> NoTask -> refused, so this stays disabled until a surface is
    # converted to establish one. That default is the containment.
    authority.enforce('workspace', 'write_file')

    p = workspace.resolve(path)
    existed = p.is_file()
    was = p.stat().st_size if existed else 0
    if make_parents:
        p.parent.mkdir(parents=True, exist_ok=True)
    try:
        with open(p, "a" if append else "w", encoding="utf-8") as fh:
            fh.write(content)
    except OSError as e:
        return {"error": "write_failed", "path": str(p), "detail": str(e)}
    return {"path": str(p), "action": "appended" if append else
            ("replaced" if existed else "created"),
            "bytes_before": was, "bytes_after": p.stat().st_size}


@tool("workspace", dangerous=True)
def delete_path(path: str, recursive: bool = False) -> dict:
    """Delete a file, or a directory tree when recursive is set.

    Args:
        path: Absolute, or relative to the project root.
        recursive: Required to remove a non-empty directory.
    """
    # AUTHORITY GATE. Studio admission ('workspace' effect) is not authority: passing
    # `enabled() + token_ok()` makes a caller admitted, not an owner. A recursive delete is the least recoverable effect on this surface.
    # No bound task -> NoTask -> refused, so this stays disabled until a surface is
    # converted to establish one. That default is the containment.
    authority.enforce('workspace', 'delete_path')

    p = workspace.resolve(path)
    if not p.exists() and not p.is_symlink():
        return {"error": "not_found", "path": str(p)}
    try:
        if p.is_dir() and not p.is_symlink():
            if recursive:
                shutil.rmtree(p)
            else:
                p.rmdir()
            return {"path": str(p), "action": "removed_directory", "recursive": recursive}
        p.unlink()
        return {"path": str(p), "action": "removed_file"}
    except OSError as e:
        return {"error": "delete_failed", "path": str(p), "detail": str(e)}


@tool("workspace")
def search(pattern: str, path: str = ".", glob: str = "", regex: bool = False,
           max_results: int = 100) -> dict:
    """Search file contents recursively. Uses grep, so it is fast on a large tree.

    Args:
        pattern: The text to find.
        path: Directory to search under. Relative paths are against the project root.
        glob: Restrict to matching filenames, e.g. "*.py".
        regex: Treat the pattern as an extended regular expression rather than a literal.
        max_results: Stop after this many matching lines. grep is killed once one more than
            this has arrived, so this bounds the search and not just the reply.
    """
    p = workspace.resolve(path)
    if not p.exists():
        return {"error": "not_found", "path": str(p)}
    cmd = ["grep", "-rnI", "-E" if regex else "-F", "--", pattern, str(p)]
    if glob:
        cmd[2:2] = [f"--include={glob}"]
    want = max(0, max_results)
    # grep's exit code is never consulted: it exits 1 for "no matches", which is a result and
    # not a failure, and an empty `matches` list already says so truthfully.
    lines, expired, failure = _bounded(cmd, want, SEARCH_TIMEOUT_S)
    if failure is not None:
        return {"error": "search_failed", "detail": failure}
    truncated = len(lines) > want
    hits = []
    for ln in lines[:want]:
        parts = ln.split(":", 2)
        hits.append({"file": parts[0], "line": int(parts[1]), "text": parts[2]}
                    if len(parts) == 3 and parts[1].isdigit() else {"raw": ln})
    out = {"pattern": pattern, "root": str(p), "count": len(hits),
           "truncated": truncated, "matches": hits}
    if expired:
        out["timed_out_after_s"] = SEARCH_TIMEOUT_S
        out["detail"] = ("grep was still running at the deadline and was killed; these are the "
                         "matches it had produced, not all of them")
    return out


@tool("workspace")
def find_files(name: str, path: str = ".", max_results: int = 200) -> dict:
    """Find files by name pattern, e.g. "build_*.py".

    Args:
        name: A shell glob matched against the filename only.
        path: Directory to search under.
        max_results: Stop after this many. find is killed once one more than this has arrived,
            so this bounds the walk and not just the reply.
    """
    p = workspace.resolve(path)
    if not p.is_dir():
        return {"error": "not_a_directory", "path": str(p)}
    # Pruning the heavy directories is what makes this usable here: an unpruned find over
    # this tree walks .git, three .venvs and the HF cache, and times out.
    cmd = ["find", str(p),
           "(", "-name", ".git", "-o", "-name", "node_modules", "-o", "-name", ".venv",
           "-o", "-name", "__pycache__", ")", "-prune", "-o",
           "-name", name, "-print"]
    want = max(0, max_results)
    lines, expired, failure = _bounded(cmd, want, SEARCH_TIMEOUT_S)
    if failure is not None:
        return {"error": "find_failed", "detail": failure}
    truncated = len(lines) > want
    found = lines[:want]
    # `count` is the length of `files`, which is what it was not before: it used to report the
    # total found while `files` was sliced, so the two disagreed on every truncated result.
    out = {"name": name, "root": str(p), "count": len(found),
           "truncated": truncated, "files": found}
    if expired:
        out["timed_out_after_s"] = SEARCH_TIMEOUT_S
        out["detail"] = ("find was still walking at the deadline and was killed; these are the "
                         "paths it had produced, not all of them")
    return out
