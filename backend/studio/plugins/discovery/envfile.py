"""Load `symoneural-discovery.env` into `os.environ` without adding a dependency.

Garrett asked for the script to load a `.env` automatically so that setting the keys up is a
one-time file edit rather than a re-export every session, and the instructions that came with
that ask said `pip install python-dotenv`. **That install did not happen and must not.** Two
separate reasons, either one sufficient:

- The system interpreter is the serving path. `.claude/CLAUDE.md` forbids installing into it,
  because a package that breaks an import breaks `symoneural-api`, not a script.
- New dependencies are Garrett's call, not mine.

What python-dotenv is being asked to do here is parse `KEY=value` lines. That is the function
below, in stdlib, and it is *better* for this use than the library would be in one respect
that matters: **it never returns a value, only the key names it set.** Every other function in
this package can be quoted into a log line, a commit message or a test failure without
thinking about it, because there is nothing here that could carry a credential outward.

## The shell wins over the file, deliberately

`load()` skips any name already present in `os.environ`. So

    GOOGLE_CSE_API_KEY=... python3 -m ...symoneuraldiscovery.discovery search "q"

overrides the file for one run, and — the case that actually motivates it — a systemd unit's
`EnvironmentFile=/etc/symoneural/api.env` is not silently overwritten by a file sitting in the
repo. An env loader that clobbers the process environment turns a deployment secret into
whatever a checkout happens to contain.

## Where it looks

1. `$SYMONEURAL_DISCOVERY_ENV`, if set — an explicit path always wins, and the file need
   not be named `symoneural-discovery.env`.
2. `symoneural-discovery.env` beside this package. One env file per app, named
   `symoneural-<extension>.env` after the app it belongs to, which is Garrett's rule and the
   reason this is not a single shared `.env` at the repo root: an app's credentials and an
   app's `.gitignore` line should be findable from the app's own directory. That is the path
   the README documents and the one `.gitignore:135` excludes.

There is no walk up the directory tree. A loader that searches parent directories will one day
find a different project's file, and a credential loaded from a path nobody named is worse than
a missing one, which at least fails loudly.
"""
from __future__ import annotations

import os
from pathlib import Path

__all__ = ["DEFAULT_PATH", "parse", "resolve_path", "load"]

# Beside the package, not beside the caller's working directory. `discovery.py` can be invoked
# as `python3 -m`, through `bin/symoneural-discovery`, or from a cron line whose cwd is `/`,
# and all three must read the same file.
DEFAULT_PATH = Path(__file__).resolve().parent / "symoneural-discovery.env"


def parse(text: str) -> dict[str, str]:
    """`KEY=value` lines to a dict, tolerating the four shapes a hand-edited file has.

    Blank lines and `#` comments are skipped; a leading `export ` is tolerated because that is
    what a shell user's muscle memory produces; one matching pair of surrounding quotes is
    stripped; whitespace around both name and value goes.

    A line with no `=` is skipped rather than raising. This file is edited by hand with a key
    pasted from a browser, and the failure mode to avoid is the whole tool refusing to start —
    including `stats`, which needs no key at all — because line 9 has a stray word on it.

    An empty value is kept as `""` rather than dropped, and that distinction is load-bearing:
    the tracked template ships every name with an empty value, so "present but empty" is the
    normal state of an unconfigured install. `build_backend` in `discovery.py` tests the value
    for truth, not the name for presence, which is why an empty line here still produces the
    "set GOOGLE_CSE_API_KEY to use the google backend" message rather than a 401 from Google.
    """
    out: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        name = name.strip()
        if name.startswith("export "):
            name = name[len("export "):].strip()
        if not name:
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        out[name] = value
    return out


def resolve_path(explicit: str | os.PathLike[str] | None = None) -> Path:
    """The file that `load()` would read, whether or not it exists."""
    if explicit is not None:
        return Path(explicit).expanduser()
    from_env = os.environ.get("SYMONEURAL_DISCOVERY_ENV")
    if from_env:
        return Path(from_env).expanduser()
    return DEFAULT_PATH


def load(explicit: str | os.PathLike[str] | None = None) -> list[str]:
    """Set every name in the file that is not already set. Returns the **names** it set.

    Never the values, and never a count of how many were non-empty either — a caller that
    prints "3 of 6 keys configured" beside a list of names has published which three.

    A missing file is not an error and returns `[]`. `stats`, `export` and the `duckduckgo`
    backend all work with no credentials at all, so refusing to run without the file would
    make the no-key path harder than it needs to be for no gain.
    """
    path = resolve_path(explicit)
    try:
        text = path.read_text(encoding="utf-8")
    except (FileNotFoundError, NotADirectoryError, IsADirectoryError, PermissionError):
        return []
    applied = []
    for name, value in parse(text).items():
        if name in os.environ:
            continue
        os.environ[name] = value
        applied.append(name)
    return applied
