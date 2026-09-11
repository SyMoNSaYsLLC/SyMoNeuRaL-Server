# SyMoNeuRaL Server

SyMonSays LLC. Full-stack business servers, intelligent all the way down. One box, one card,
everything measured.

## Layout

Ten directories. Each one is a thing you can name out loud, and each has a `README.md`
saying what belongs in it and what does not.

| Directory | What it is |
|---|---|
| `backend/` | the FastAPI application — `server.py` and one directory per component |
| `frontend/` | both browser surfaces: `app/` (Next.js) and `site/` (static) |
| `models/` | model weights. **Not carried by a clone** — see below |
| `ops/` | how this box is configured, served and recorded |
| `scripts/` | operational procedure: setup, the GPU governor, deploy, model staging |
| `tools/` | generators, benchmarks and audits — none of it runs in production |
| `tests/` | by what they are about: component, structure, ops, site, models, clients |
| `business/` | what this company is and sells. Not operations, not code |
| `bin/` | runtime entry points |
| `run/` | runtime state. Not in git, and all of it reconstructible |

**There is no `docs/`.** Every document lives with the thing it describes: a surface's spec
in `backend/<component>/docs/`, the current operational record in `ops/registry/`, a dated
finding in `ops/audits/`. A document that lives away from what it describes goes stale
without anybody noticing.

```bash
python3 tools/audit/readme_map.py            # which directories have one, and is it in git
python3 tools/audit/readme_map.py --missing
```

## The files at the root, and why each is here

Nothing is at the root that could live in a directory. These eight could not.

| File | What it is |
|---|---|
| `README.md` | this. The map, and the two rules a new arrival needs first |
| `conftest.py` | **the one arrangement every import in this tree depends on** — see below |
| `LICENSE` | the SyMoNeuRaL proprietary licence. `LicenseRef-SyMoNeuRaL-Proprietary` |
| `LICENSES.md` | every third-party component, its licence, and what that licence obliges |
| `ENGINEERING.md` | the build, the card, the environments, the honesty rules |
| `HANDOFF.md` | what is left, and what will bite you |
| `SERVER-READY.md` | what must answer before this box is considered serving |
| `REFERENCE-INDEX.md` | where each external reference lives and what it is for |

### `conftest.py` is load-bearing, not a test convenience

It puts `backend/` on `sys.path`, and **that is the one arrangement under which the imports
in this tree mean what they say.** `backend/**` imports its siblings as top-level packages —
`from hardware.lib import gpu`, not `from backend.hardware.lib import gpu` — which works
because the service runs as

```
ExecStart=/usr/bin/python3 .../backend/server.py
```

and Python puts a script's own directory at `sys.path[0]`. The tests reproduce that, rather
than inventing a different one.

**It is at the repository root, not in `tests/`**, because the tests moved out of `backend/`
on 2026-09-11 and pytest walks up from each test file collecting `conftest.py` — so one here
covers `tests/` and anything added later. There is exactly one place that knows about
`sys.path`, and this is it. Do not add a second.

Two things follow directly from it, and both caught files after that move:

- **`from . import X` in a test has no package to be relative to.** Import the component by
  name: `from chat import chat`.
- **`HERE` and `ROOT` in a test are the repository root**, not the test's directory. Several
  files carried `sys.path.insert(0, str(HERE.parent))`, which pointed one level *above* the
  repository and silently found nothing.

## What is NOT here, and why

**Weights.** Real files under `models/llm/`, ~50 GB, and **not symlinks** — the links were
killed on 2026-09-11 because a link is a claim about a path rather than about bytes. They are
licensed separately from this code and git is the wrong tool for them.

What a clone *does* get is the record: `models/PROVENANCE.json` says which upstream artefact
each house name came from, `models/licenses/` carries the text that obligation requires to
travel, and `scripts/fetch-models.sh` fetches the rest and verifies it before promoting it.

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
