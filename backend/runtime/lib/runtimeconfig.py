"""Load this box's runtime configuration from a user-owned directory, not from `/etc`.

## Why this exists

`symoneural-api.service` carried `EnvironmentFile=/etc/symoneural/api.env`, and every surface
switch and token on this box came from that one root-owned file. That made a directory nobody
on the serving side can read or write **load-bearing**, with three consequences that were all
felt in practice:

* **Deleting it silently disables the product.** The unit declares `ignore_errors=yes`, so the
  service still starts -- it just comes up with accounts, coder, studio, project and dispatchos
  all off and no error anywhere. A stripped box that looks healthy is worse than one that
  refuses to boot.
* **Every configuration change needs root**, which is a different authority from the one that
  runs the code, so routine work stalls on an interactive password prompt.
* **`systemctl cat` does not show it.** The `EnvironmentFile` arrives through a drop-in, so
  reading the unit tells you the service takes no configuration, which is false. That cost real
  time here: the coder surface was live on credentials whose origin could not be found by
  reading the unit, and the answer turned out to be a file the unit does not mention.

So the process now loads its own configuration, from a directory owned by the user the service
runs as. `/etc/symoneural` becomes one *optional* source among others rather than the only one,
and deleting it is a supported operation.

## What this is not

**Not a secret store.** These files hold secrets and this module reads them; it does not make
them safe. It refuses to read a file other users can read, because a mode-644 file holding a
session-signing secret is the finding, not the fix.

**Not an override mechanism.** A name already present in `os.environ` is never replaced. What
systemd passes, or what an operator exported before starting the process, outranks any file --
so this can add configuration to a box that had none and can never quietly change the
configuration of a box that already worked. That direction is deliberate and is the same one
`studio/plugins/discovery/envfile.py` chose for the same reason.

## Why the name filter is an allow-list

Only `SYM_*` and `SYMONEURAL_*` are accepted. An env file is an instruction to change this
process's environment, and a stray `PATH=`, `LD_PRELOAD=` or `PYTHONPATH=` in a hand-edited
config must not reach the serving interpreter. `apps/cryptominer` makes exactly this argument
for its own `_ENV_KEYS` and it generalises: the safe direction is to name what may pass, not to
guess at what must not. A rejected name is counted and logged, never silently dropped.
"""
from __future__ import annotations


import logging
import os
import pathlib
import stat

__all__ = ["CONFIG_DIR_ENV", "candidates", "config_dir", "load", "loaded", "parse", "rejected"]

log = logging.getLogger("symoneural.runtimeconfig")

#: An explicit override, for tests and for an operator who keeps configuration elsewhere.
CONFIG_DIR_ENV = "SYMONEURAL_CONFIG_DIR"

#: The names a file here may set. See the module docstring.
_ALLOWED_PREFIXES = ("SYM_", "SYMONEURAL_")

_loaded: list[str] = []
_rejected: list[str] = []


def loaded() -> list[str]:
    """Names this module put into `os.environ`, in the order it set them."""
    return list(_loaded)


def rejected() -> list[str]:
    """Names a config file tried to set and this module refused. Never silently empty."""
    return list(_rejected)


def parse(text: str) -> dict[str, str]:
    """`KEY=value` lines to a dict, tolerating the shapes a hand-edited file has.

    Blank lines and `#` comments are skipped; a leading `export ` is tolerated because that is
    what shell muscle memory produces; one matching pair of surrounding quotes is stripped;
    whitespace around name and value goes.

    A line with no `=` is skipped rather than raising, for the reason the discovery plugin's
    parser gives: these files are hand-edited, and the failure to avoid is the whole API
    refusing to start because line 9 has a stray word on it.

    An empty value is KEPT as `""`. "Present but empty" is a real state -- it is how a template
    ships an unconfigured install -- and every gate on this box tests the value for truth rather
    than the name for presence, so an empty value correctly reads as off.
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


#: The repo root, derived from this file. That calculation has been wrong four times here and
#: it fails silently -- the wrong parent is usually a directory that exists -- so it is asserted
#: at import rather than trusted.
ROOT = pathlib.Path(__file__).resolve().parents[2]

#: Inside the repository, under `run/`, and both halves of that are deliberate.
#:
#: `run/` is gitignored in full, so a file of secrets placed here CANNOT be committed by
#: accident. That is not a convention anyone has to remember -- it is enforced by the same
#: `.gitignore` that already protects `run/coder.log` and the surface databases, and it is the
#: pattern `backend/cryptominer/miner.env` (mode 600, gitignored beside its tracked
#: `.example`) already established here.
#:
#: In the repository rather than `~/.config` because the owner asked for one place that is this
#: project, and because a config directory that travels with the checkout is one the person
#: doing the work can find. The XDG location is still honoured below for anyone who prefers it.
_REPO_CONFIG = ROOT / "run" / "config"


def config_dir() -> pathlib.Path:
    """The directory this box keeps its runtime configuration in.

    `$SYMONEURAL_CONFIG_DIR` wins, which is what tests use and what an operator who keeps
    configuration elsewhere sets. Otherwise the repository's own `run/config`, which is
    gitignored and owned by the account that runs the service -- no root, and no possibility of
    committing a secret. `$XDG_CONFIG_HOME/symoneural` (or `~/.config/symoneural`) is used only
    when the repository directory does not exist, so an existing XDG setup keeps working.
    """
    explicit = os.environ.get(CONFIG_DIR_ENV)
    if explicit:
        return pathlib.Path(explicit).expanduser()
    if _REPO_CONFIG.is_dir():
        return _REPO_CONFIG
    xdg = os.environ.get("XDG_CONFIG_HOME")
    base = pathlib.Path(xdg).expanduser() if xdg else pathlib.Path.home() / ".config"
    fallback = base / "symoneural"
    return fallback if fallback.is_dir() else _REPO_CONFIG


def candidates() -> list[pathlib.Path]:
    """Every `.env` file to read, in a stable order.

    Sorted by name so two files setting the same key resolve the same way on every boot. A
    directory that does not exist yields `[]` and is not an error -- an unconfigured box is a
    normal state, not a fault.
    """
    d = config_dir()
    try:
        return sorted(p for p in d.iterdir() if p.is_file() and p.suffix == ".env")
    except (FileNotFoundError, NotADirectoryError, PermissionError):
        return []


def _readable_by_others(p: pathlib.Path) -> bool:
    """True when anyone but the owner can read this file.

    Checked before the contents are read, not after: these files hold session-signing secrets
    and surface tokens, and the whole reason this module exists is that such a file was
    previously somewhere only root could reach. Moving it somewhere convenient must not also
    move it somewhere world-readable.
    """
    try:
        mode = p.stat().st_mode
    except OSError:
        return True                      # cannot tell: assume the worst and refuse
    return bool(mode & (stat.S_IRGRP | stat.S_IROTH))


def load(*, warn: bool = True) -> list[str]:
    """Read the config directory into `os.environ`. Returns the names actually set.

    Never overrides a name already present, never sets a name outside the allowed prefixes, and
    never raises on a missing, unreadable or malformed file. Returns `[]` on a box with no
    configuration, which is a supported state and not a failure.
    """
    _loaded.clear()
    _rejected.clear()

    for path in candidates():
        if _readable_by_others(path):
            # Refused, loudly, and the file is NOT read. Reporting the mode a person can fix is
            # more useful than reporting that something went wrong.
            if warn:
                log.warning("runtime config %s is readable by other users (mode %o); refusing "
                            "to read it. `chmod 600 %s` and restart.",
                            path, path.stat().st_mode & 0o777, path)
            _rejected.append(f"{path.name}:<file mode>")
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError as e:
            if warn:
                log.warning("runtime config %s could not be read: %s", path, e)
            continue

        for name, value in parse(text).items():
            if not name.startswith(_ALLOWED_PREFIXES):
                _rejected.append(f"{path.name}:{name}")
                continue
            if name in os.environ:
                continue                 # what the process was started with outranks a file
            os.environ[name] = value
            _loaded.append(name)

    if warn and _loaded:
        # Names only. A count and a list of NAMES is what an operator needs to see; the values
        # are exactly what must never reach a log, and `docs/ops/EXPORTS.md` is explicit that a
        # credential which has been displayed is spent.
        log.info("loaded %d runtime config name(s) from %s: %s",
                 len(_loaded), config_dir(), ", ".join(sorted(_loaded)))
    if warn and _rejected:
        log.warning("refused %d runtime config entry(ies): %s. Only %s names are accepted, so "
                    "a stray PATH= or LD_PRELOAD= cannot reach the serving interpreter.",
                    len(_rejected), ", ".join(sorted(_rejected)),
                    " / ".join(_ALLOWED_PREFIXES))
    return list(_loaded)
