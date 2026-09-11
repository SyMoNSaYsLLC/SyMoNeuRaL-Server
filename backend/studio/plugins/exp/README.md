# SyMoNeuRaL Exp

A plugin runtime, and a page that shows it running. Every other app in `backend/apps/` is a
capability — chat, image, remix, reinforce, studio. This one is the thing capabilities get mounted
*into*: a service container with a lifecycle, where mounting is reversible and the unit of change
is a manifest entry rather than the process.

Live at **`/exp`**. Reads are open; writes need two environment variables.

```
backend/apps/studio/plugins/exp/
  context.py    the container: services, events, provide/inject/isolate/intercept
  fiber.py      one mounted plugin instance -- states, effects, reverse teardown, rebind
  registry.py   what counts as a plugin, and config validation
  loader.py     YAML manifests, presets, groups, hot-plug, hot-reload
  trace.py      the append-only record everything else is debugged from
  gate.py       the two switches, and one read that is behind them
  routes.py     the HTTP surface (the only module that imports FastAPI)
  cli.py        mount a manifest, print the table, tear it down -- no HTTP, no gate
  plugins/      one worked example per shape and per mechanism
  presets/      dev, sessions, failures
  docs/         architecture, isolation, writing plugins
  page.html     the surface fragment, built into site/exp.html
  page.js       the surface behaviour, copied to site/exp.js
  test_exp.py   stdlib-only, collected by the suite
```

## Try it without the API

```bash
cd backend
python3 -m apps.studio.plugins.exp.cli                    # the dev preset
python3 -m apps.studio.plugins.exp.cli --preset sessions   # two isolated sessions, one shared bus
python3 -m apps.studio.plugins.exp.cli failures --strict   # every failure mode; exits 1
python3 -m apps.studio.plugins.exp.cli --json --trace 20   # the same structure /api/exp/state returns
```

`--preset sessions` is the fastest way to see what `isolate()` does: two services named `llm`,
different realms, different objects, one `bus` shared between them.

## The gate

| Variable | Effect |
|---|---|
| `SYMONEURAL_EXP_ENABLED=1` | turns the write half on. Absent → every write is `503` |
| `SYMONEURAL_EXP_TOKEN=<secret>` | required with it. A request without it is `401` |
| `SYMONEURAL_EXP_PRESET` | mounted at first use. Defaults to `dev`; `""` mounts nothing |

Both switches are needed; `SYMONEURAL_EXP_ENABLED` accepts `1` only. The token is read from
`X-Symoneural-Token` (or `X-Sym-Token`, the name it replaced — `gate.present_token`
reads both, new first), `Authorization: Bearer …` or `?token=`, compared with
`hmac.compare_digest`.

Reads are deliberately open — the whole argument for this runtime is that its state is
inspectable, and a plugin table nobody can see without a secret is a plugin table nobody looks at.
The one exception is an entry's **`config`**, which is omitted entirely for a tokenless reader
(not emptied — `config: {}` reads as "this plugin has no config", which is a different and false
statement) because that is where a plugin's credentials would live.

**None of this is a sandbox.** `docs/isolation.md` says so at length, with measurements from this
box rather than citations, and explains what containment would actually cost.

## HTTP surface

Mounted by `api.py` as `app.include_router(exp.router, prefix="/api/exp")`.

| Method | Path | Token | Returns |
|---|---|---|---|
| GET | `/state` | no¹ | everything the page needs for one render |
| GET | `/plugins` | no¹ | entries + fibers |
| GET | `/services` | no | every service in every realm, with epochs, owners and methods |
| GET | `/events` | no | the trace from a `since` cursor |
| GET | `/catalogue` | no | what can be mounted, described without mounting it |
| POST | `/preset` | yes | mount a named preset |
| POST | `/apply` | yes | reconcile against a manifest posted inline |
| POST | `/add` | yes | add one entry |
| POST | `/remove` | yes | remove one entry |
| POST | `/patch` | yes | replace one entry's config |
| POST | `/enable` | yes | enable or disable an entry |
| POST | `/reload` | yes | re-import the module and restart the fiber |
| POST | `/call` | yes | call a method on a mounted service |

¹ answers without a token, but omits each entry's `config`.

`/events` takes a sequence cursor rather than a timestamp, because two events can share a
millisecond and a timestamp cursor either re-delivers one or drops one. As of 2026-08-20
`/call` implements no method allow-list: any public method on any mounted service. That is a
deliberate pre-launch state, not a cleared posture — see request ledger R-98, held.

## The page

`page.html` + `page.js` → `python3 tools/build/build_exp.py` → `site/exp.html` + `site/exp.js`, then
`python3 tools/build/build_cachebust.py` **last** (every generator run strips the stamps). Reached from
the rack row on the dashboard; there is no sitewide NAV entry, following studio and reinforce —
`NAV` is baked into every page at generation time, so editing it makes every already-generated
page stale.

It shows the entry table with live states, the services table with realms and epochs, and the
trace. Where there is no reading, nothing is drawn: no decorative spinner, and `503` (off) is
distinguished from `401` (refused) because they are different conditions and a page that conflates
them sends you looking for the wrong thing.

## Reading order

1. `plugins/bus.py` — the smallest complete plugin: provide one thing, clean it up.
2. `presets/dev.yaml` — the default manifest, with `clock` disabled on purpose.
3. `docs/writing-plugins.md` — the shapes, `inject`, `schema`, `isolate`, and what to do when it
   does not work.
4. `docs/architecture.md` — what was taken from Cordis, what was left, and **where the plateau
   is**.
5. `docs/isolation.md` — why `isolate()` is not containment, and what containment would cost.
6. `presets/failures.yaml` with `plugins/explode.py` — four failure modes mounted rather than
   described.

## Tests

```bash
cd backend && python3 -m pytest apps/studio/plugins/exp/test_exp.py -q
```

Standard library and `unittest` only, so it is collected by the suite rather than needing an
`--ignore`. It measures the claims this package makes rather than asserting them in prose: reverse
teardown as `[3, 2, 1]`, hot-plug in both directions, two realms yielding two `probe` services
with different values, a second provider in one realm failing with `isolate` named in the message,
`snapshot(with_config=False)` having no `config` key at all, and every `getElementById` in
`page.js` existing in `page.html`.

## Known limits

* Not isolation, in-process, by design and by necessity — `docs/isolation.md`.
* A plugin can take the process down (`os._exit`, or a segfault in a native extension), and then
  there is no fiber state to look at because there is no process.
* GPU leases are not integrated. One card, one mutex, `scripts/gpu-governor.sh`; a plugin that
  loads a model resident locks out chat, image and train. `plugins/gpu.py` reads and takes nothing.
* Reload is a stop and a start. Instance state does not migrate.
* Settling is bounded at `Runtime.MAX_PASSES = 32`; a manifest whose fibers oscillate raises with
  a message naming the likely cause rather than wedging the API.
* The trace redacts nothing, in memory or in `run/exp-events.jsonl`.
