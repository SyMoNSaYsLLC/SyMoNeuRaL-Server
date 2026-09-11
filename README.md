# SyMoNeuRaL Server

SyMonSays LLC. Full-stack business servers, intelligent all the way down. One box, one card,
everything measured.

## Layout

Seven directories. Each one is a thing you can name out loud.

| Directory | What it is |
|---|---|
| `backend/` | the FastAPI application — `api.py` and the `apps/` modules behind it |
| `frontend/` | the Next.js application |
| `models/` | model weights. **Not carried by a clone** — see below |
| `docs/` | the rules, the decisions, the operational procedure |
| `scripts/` | operational scripts: setup, the GPU governor, deploy |
| `tools/` | build, audit and evidence generators — these do not run in production |
| `bin/` | runtime entry points |

## What is NOT here, and why

**Weights.** `models/llm` is a symlink to the machine's weight store. They are ~190 GB,
licensed separately from this code, and git is the wrong tool for both. A clone gets the
symlink and points it wherever that machine keeps its weights.

**Vendored SDKs.** The tree this replaces carried 15,298 tracked third-party SDK files in
nine languages -- **91% of every tracked file in the repository** -- that nothing imported.
They poisoned every search and every clone. They are not here and will not come back.

**Build output, virtualenvs, caches.** `backend/apps` was 6.0 GB on disk and 432 tracked
files. Only the 432 came across.

## Where this came from

Migrated from `/home/google/Symoneural`, which reached **35 top-level directories and 196 GB**.
Browser code was split across four folders, operations across five, testing across four, and
nine directories were engine runtimes carrying one to three tracked files each.

    old tree   196 GB   16,843 tracked files   35 top-level directories
    this tree   24 MB      865 tracked files    7 top-level directories

Same system, same rules, laid out so a person can find something.

## Status

**Migrated, not yet serving.** The live API is still the old tree. Nothing here has been
started, deployed, or pointed at by a systemd unit. Do not assume a file here is the one in
production until that cutover is done and recorded.
