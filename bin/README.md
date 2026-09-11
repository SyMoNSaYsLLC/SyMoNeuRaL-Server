# bin/ — runtime entry points

Five commands. Each one launches something that already exists elsewhere in the tree; none
of them reimplements it. That split is deliberate — two implementations of "start the API"
or "resume a session" drift, and the way that drift shows up is a session you can open one
way and not the other.

| Command | Launches | Language |
|---|---|---|
| `symoneural-api` | the FastAPI service — `backend/server.py` | Python |
| `symoneural-cli` | the whole local stack: chat, image, ravencalc, governor | Python |
| `symoneural-code` | `symoneural-cli repl` under a shorter name | bash |
| `symoneural-discovery` | `backend/studio/plugins/discovery/` | Python |
| `symoneural-audit` | finds code that breaks when a directory moves | Python |

## Setup

Nothing to build. They are executable scripts against the system interpreter — there is no
virtualenv in the serving path, by design (see `ENGINEERING.md`).

```bash
export PATH="$PWD/bin:$PATH"        # or:
scripts/install-cli.sh              # symlinks them into ~/.local/bin
```

## How they find the repo

Every one of them walks **up** from its own location looking for `backend/server.py`, and
stops at the first directory that has it. None counts parents.

```python
ROOT = next(p for p in Path(__file__).resolve().parents
            if (p / "backend" / "server.py").is_file())
```

This is not style. `ROOT = HERE.parent` broke every one of these commands the day the
runtimes were promoted out of `engines/`, silently, because the wrong parent usually
exists and is a real directory. `symoneural-audit` exists to find that pattern, and
`tests/structure/test_path_fragility.py` fails the build if it comes back.

## Running them

```bash
symoneural-api                 # start the API in the foreground on :8800
symoneural-api --check         # resolve paths and report; start nothing

symoneural-cli status          # what holds the card right now
symoneural-cli chat "..."      # one turn
symoneural-cli repl            # interactive session

symoneural-code                # the same session, shorter name
symoneural-discovery search "EU AI Act enforcement 2026"
symoneural-audit               # report fragile path anchors
```

## Reconfiguring

These read the same environment as the service; there is no separate config file.

| Variable | Default | Effect |
|---|---|---|
| `SYMONEURAL_PORT` | `8800` | port the API binds |
| `SYMONEURAL_LLM_ENGINE` | `symoneural-llm/build/bin/symoneural-llm` | chat engine binary |
| `SYMONEURAL_DIFFUSE_ENGINE` | `symoneural-diffuse/build/bin/symoneural-diffuse` | image engine binary |

Legacy `SYM_*` spellings are promoted to `SYMONEURAL_*` at startup by
`backend/runtime/lib/symoneuralenv.py`, before any module that reads the environment is
imported. A name already present in `os.environ` is never overridden.

## The systemd unit still names the script

`ops/units/symoneural-api.service` runs `backend/server.py` directly, not
`bin/symoneural-api`. Repointing it is a one-line drop-in and needs root, so it is the
owner's to apply. Nothing in this directory changes a running service.
