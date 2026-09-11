# ops/ — how this box is configured, served and recorded

Nothing here runs on its own. These are the files the operating system, the reverse proxy
and the generators read, plus the written record of what has been measured.

```
Caddyfile          TLS and reverse proxy. The public front door.
PORTS.tsv          every listening port on this box. The source of truth.
RUNTIMES.tsv       every runtime: what starts it, what it loads, does it take the lease.
units/             systemd units and timers.
deploy/            install, verify, roll back. Bash, run as root.
gateway/           symon-gateway: payload validation in front of the API.
manifests/         build and model manifests, and the script that regenerates them.
docs/              measurements, audits, serving records. Written, dated, SHA'd.
architecture/      the component / service / artifact / alias maps, as TSV.
authority/         the project rules, glossary and tool policy.
history/           decisions, handoffs, and the pre-restructure archive.
guides/            playbooks and the CUDA curriculum.
```

## The serving path

```
internet -> Caddy :443 -> symon-gateway :8000 -> FastAPI :8800
                       \-> FastAPI :8800   (sections, /docs, /openapi.json)
```

Caddy terminates TLS, serves static files, and reverse-proxies everything else. It makes
**no** routing decision: no rewrites, no aliases, no conditionals. FastAPI does all the
routing. The gateway rewrites no path either — it validates payloads before they can reach
anything that takes the GPU lock, and relays `/api/ws` as a real WebSocket.

`X-Forwarded-For` is load-bearing: the API keys its rate limiter on it.

## PORTS.tsv and RUNTIMES.tsv are records, not documentation

Both are TSV because four consumers read them and none hardcodes a port:

```
tools/build/build_ports.py     -> ops/docs/PORTS.md        (generated; do not hand-edit)
backend/registry/lib/ports.py  -> the API and every surface process
ops/units/symoneural-surface@.service
tools/lib/smoke.py             -> which port to test each surface on
```

The Markdown under `ops/docs/` is the *rendering*. Edit the TSV and regenerate; a figure
that lives only in prose is how this project once published a test count that was never
true of the commit beside it.

`RUNTIMES.tsv` stores a call site as `<file>::<literal fragment>`, never a line number — a
pinned line reddens on any edit above it, and the fix would be somebody re-stamping a
number.

## Installing and starting

```bash
sudo ops/deploy/install-runtime.sh      # dependencies and paths
sudo ops/deploy/install-service.sh      # units into /etc/systemd/system
sudo systemctl enable --now symoneural-api.service
ops/deploy/api-readiness-probe.sh       # does it actually answer
ops/deploy/verify-runtime.sh            # full check
```

Rolling back:

```bash
sudo ops/deploy/rollback-runtime.sh
```

`ops/deploy/SERVICE-HOLD.md` records any unit deliberately held down and why. Read it
before you start something that is stopped — it is usually stopped on purpose.

## Units

| Unit | What it runs |
|---|---|
| `symoneural-api.service` | the FastAPI service on :8800 |
| `symoneural-gateway.service` | symon-gateway on :8000 |
| `symoneural-web.service` | the Next.js frontend |
| `symoneural-surface@.service` | one delegated surface per instance, port from `PORTS.tsv` |
| `symoneural-deploy.service` | publishes the static site |
| `symoneural-progress.{service,timer}` | regenerates the progress page |
| `symoneural-watch.{service,timer}` | the watchdog |

## Reconfiguring

Environment for the API is read in this order, and a name already set always wins:

1. `/etc/symoneural/api.env` — root-owned, attached through a drop-in `systemctl cat`
   does not show, declared `ignore_errors=yes`. Deleting it once disabled every surface
   while the service still reported healthy.
2. the repo's own runtime config, loaded by `backend/runtime/lib/runtimeconfig.py`
3. legacy `SYM_*` names, promoted to `SYMONEURAL_*` before any module reads them

Never commit a secret here. `run/config/api.env` and `miner.env` are not in this
repository and must not be printed.

## Regenerating what is generated

```bash
python3 tools/build/build_ports.py        # PORTS.tsv    -> ops/docs/PORTS.md
python3 tools/build/build_runtimes.py     # RUNTIMES.tsv -> ops/docs/RUNTIMES.md
ops/manifests/regenerate.sh               # build and model manifests
```

Run each twice and diff. These generators re-read their own output, and one that does not
recognise something it emits accumulates it — one copy per run. That has happened three
times in this repository.
