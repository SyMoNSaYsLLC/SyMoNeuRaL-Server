# scripts/ — operational procedure

Bash, run by a person or by a systemd unit. **Nothing here is imported by the API.** If a
thing needs to run inside a request, it belongs in `backend/`; if it needs to build an
artefact, it belongs in `tools/`.

```
lib/                sourced by everything here. See lib/README.md.
model-staging/      stage, smoke, promote and roll back a model bundle.
gpu-governor.sh     THE GPU lease. Every surface that wants the card goes through it.
symoneural.sh       start, stop and inspect the API by hand.
setup.sh            first-run: dependencies, directories, permissions.
deploy.sh           publish frontend/site to the webroot.
fetch-*.sh          weights, whisper, the cutout model.
install-*.sh        caddy, gateway, the systemd units, the CLI.
build-*.sh          the .deb and the apt repo.
enable-surfaces.sh  turn delegated surfaces on, one per PORTS.tsv row.
```

## Before anything else

Every script here sources `lib/repo.sh` first and it **walks up for `backend/server.py`**.
That means all of them run from anywhere:

```bash
cd /tmp && /path/to/repo/scripts/gpu-governor.sh status      # works
```

If one refuses with *"not inside a SyMoNeuRaL checkout"*, that is the marker missing, not a
path bug. See `lib/README.md` for why this is a library and what it replaced.

## The governor is not optional

`gpu-governor.sh` holds the GPU **lease**. One job at a time, globally — not per-IP, not per
surface. The card cannot do two things, so the queue is a property of the hardware.

```bash
scripts/gpu-governor.sh status              # who holds it, and how much VRAM is free
scripts/gpu-governor.sh acquire chat        # take it, evicting the resident surface
scripts/gpu-governor.sh acquire chat --new-engine   # evict even a resident `chat`
scripts/gpu-governor.sh release chat        # drain below the floor, then unlock
```

`--new-engine` exists because `acquire chat` over a resident `chat` used to evict nothing
and the next spawn hit `cudaMalloc failed` on a card that already held 12 GB.

**Release drains.** It waits for VRAM to fall below `DRAIN_FLOOR_MIB` before unlocking,
because a CUDA context that has not finished tearing down still holds memory the next
surface would allocate into. The arithmetic on the readings is in Python on purpose —
shell arithmetic on `nvidia-smi` CSV caused R-171.

**A training run is never evicted.** Chat, image and remix queue behind it until it finishes
or is stopped deliberately. That is architectural.

### The one deadlock that is still open

Restarting the API while a request is in flight can deadlock: the in-flight request spawns
`gpu-governor.sh acquire chat`, which blocks on the lock the shutting-down API still holds.
It has happened and it will happen again. Clear it by killing the acquire shell:

```bash
pkill -f 'gpu-governor.sh acquire'
```

## First run on a new box

```bash
scripts/setup.sh                    # directories, permissions, python deps
scripts/fetch-models.sh             # ~50 GB. Idempotent, resumable, verified
sudo ops/deploy/install-runtime.sh
sudo scripts/install-service.sh
sudo systemctl enable --now symoneural-api.service
```

Then check it actually answers, rather than that systemd says `active`:

```bash
ops/deploy/api-readiness-probe.sh
scripts/symoneural.sh status
```

## Publishing the site

```bash
python3 tools/build/build_pages.py       # regenerate
python3 tools/build/build_cachebust.py   # stamp the asset query strings
sudo scripts/deploy.sh                   # publish to /var/www/symoneural
```

`deploy.sh` **refuses when it matches no pages.** It walks `frontend/site/pages/` to the
webroot root and `css/ js/ assets/` into same-named subdirectories — which is what the HTML
expects, since every page links `/js/app.js` absolutely. Before that refusal existed it
printed *"staged: (0 files)"* followed by *"deployed"*, which is the worst possible pair of
lines: a deploy that reports success and publishes nothing. It had been in that state since
the site was restructured, and running the script from `/tmp` is what found it.

It **copies and never deletes**, so every rename leaves its old file in the webroot. The
orphan report at the end is printed every run; act on it deliberately.

## Swapping the model

Read `models/README.md` first. Short version — every mode is safe on a live box, and nothing
is downloaded, activated, moved or deleted without an explicit flag:

```bash
scripts/model-staging/symoneural-model-stage.sh --inventory
scripts/model-staging/symoneural-model-stage.sh --dry-run
scripts/model-staging/symoneural-model-stage.sh --smoke-candidate
scripts/model-staging/symoneural-model-stage.sh --activate-candidate
scripts/model-staging/symoneural-model-stage.sh --rollback
```

## Environment

Scripts read the same environment as the service. There is no separate config file here.

| variable | default | effect |
|---|---|---|
| `SYMONEURAL_PORT` | `8800` | the API port |
| `SYMONEURAL_LLM_ENGINE` | `symoneural-llm/build/bin/symoneural-llm` | chat engine binary |
| `SYMONEURAL_DIFFUSE_ENGINE` | `symoneural-diffuse/build/bin/symoneural-diffuse` | image engine |
| `SYMONEURAL_GOVERNOR_LOG` | `run/governor.log` | overridable **only** so a test can run the governor for real without writing fake readings into the real log |
| `DRY_RUN` | `0` | `1` makes `run()` describe instead of execute |
| `NO_COLOR` | unset | any value disables colour |

Legacy `SYM_*` spellings are promoted to `SYMONEURAL_*` before any module reads them. A name
already in the environment is never overridden.

**Never print `run/config/api.env` or `miner.env`.** They are mode 600 and stay that way.

## Writing a new script

```bash
#!/usr/bin/env bash
set -euo pipefail
. "$(dirname -- "${BASH_SOURCE[0]}")/lib/repo.sh"
. "$ROOT/scripts/lib/say.sh"
. "$ROOT/scripts/lib/require.sh"
```

- never compute the root yourself — `lib/repo.sh` is the answer, and there were eight
  answers before it
- `bash -n` must pass; `set -euo pipefail` is not optional
- anything destructive goes behind `confirm`, which takes a typed word and refuses without
  a terminal
- state the reason in the header. `git log` is where this repository keeps "why is the code
  like this", and a script's header is where it keeps "what will this do to my box"
