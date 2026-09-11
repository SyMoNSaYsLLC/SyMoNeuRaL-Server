# Server ready — every roster row, asked on its own address

This is a **measured** reading, not an assertion. Task #73's title promises "every application
online", and twenty-four greps for symbols cannot prove that: a symbol can be present in a file
the server never imports. So the claim is settled the only way it can be — by starting the
server and asking every row in `backend/apps/ROSTER.md` for the address the roster gives it.

It is also the report owed since *"let me know when the server is complete"*, which cannot be
answered out of a task percentage.

## How this reading was taken

**Commit `428e3bb`, 2026-08-20, and the `live` row re-measured at `a616168`, 2026-08-21 —
the same two-run method on ports 8878 and 8877.** Two uvicorns on spare ports, never the live
service on `:8800` — pointing a probe at the running service measures what is *deployed*, not what is on
disk, which is the same rule `tests/frontend.mjs` is run under.

| run | port | environment |
|---|---|---|
| default | 8878 | every `SYMONEURAL_*_ENABLED` switch unset — **what a visitor gets** |
| switches on | 8877 | STUDIO, PROJECT, CODER, GATEWAY, MINING, ASIC, EXP, NEWS, RACK on, tokens `devtest` |

Each row was asked for two things: the page at its `href`, and one **read-only** API endpoint.
Three rows are `POST only` (chat, image, remix) and were not exercised, because a POST to any
of them takes the GPU; `coder` has **no route by design** — `ops/Caddyfile` delegates the whole
`/api/*` subtree to the internet, so an `/api/coder/...` route would be publicly reachable the
instant it existed (`backend/api.py:1712-1726`).

Reproduce with `tests/../` — see `backend/apps/test_server_ready.py`, which asserts this
document covers every roster row and can re-take the live half on demand.

## The reading

`page` is the HTTP status of the row's `href`. `api` is its read-only endpoint. `state` is what
the row renders on the rack, straight out of `/api/status`.

| id | href | page | api | api read | state |
|---|---|---|---|---|---|
| chat | /chat.html | 200 | POST only | - | ready |
| image | /image.html | 200 | POST only | - | ready |
| remix | /remix.html | 200 | POST only | - | ready |
| ravencalc | /ravencalc.html | 200 | POST only | - | ready |
| miner | /miner.html | 200 | /api/gpuminer/status | 503 | offline |
| streamer | /streamer.html | 200 | /api/streamer/state | 200 | ready |
| coder | /livestack/coder | 200 | no route by design | - | offline |
| project | /project.html | 200 | /api/project/state | 503 | offline |
| sigils | /sigils.html | 200 | /api/sigils/state | 200 | ready |
| studio | /studio | 200 | /api/studio/state | 200 | offline |
| live | /livestack/live | 200 | /api/live/state | 200 | ready |
| dispatchos | /demo/dispatchos | 200 | /api/dispatchos/status | 200 | offline |

**All twelve roster rows answer 200 on their own href.** That is the sentence #73 asked for,
and it is measured rather than believed. Re-taken 2026-08-29 on `de73110d` against a server on
port 8899 -- a spare port, so the reading did not require restarting the live service and did
not disturb it.

**THE TABLE LOST TWO COLUMNS AND THAT IS A CORRECTION, NOT A TRIM.** It carried
`api default / state default / api on / state on`: two environments, switches off and
switches on. This reading was taken in ONE environment, so filling four columns from it would
have been the carry-forward-and-re-date failure this repository has a rule about -- two of the
four numbers would have been copied from a measurement nobody re-took. One reading, one pair
of columns, and the environment is named above.

`ravencalc` moved from `/api/ravencalc | 200` to `POST only`. `/api/ravencalc` accepts POST
and nothing else, so a GET measures the StaticFiles mount at `/` 404ing rather than the
surface -- the same fact chat, image and remix have always been recorded with. The old `200`
was a reading of something, but not of that row's endpoint.

It said thirteen rows until 2026-08-29 and fourteen until 2026-08-22. `gateway` left on the
earlier date, folded into the miner row as a third `sub` (R-175, commit `c779e2cb`).
`train` and `exp` left on the later one, folded under `studio`; `dispatchos` joined, having
been a built row since #95 that no description of the rack carried. None of the three that
left lost its readings: `/gateway.html`, `/reinforce.html` and `/exp` all still answer 200 and
all still render their own state out of `/api/status`, now from a `sub` list rather than a
top-level row. **Folded is not deleted, and a table that stops carrying a row has to say
which of the two happened.**

**`live` is the one row whose two `state` columns are identical for a reason that is not a
defect** — read the `train` section below before assuming otherwise, because that row is
identical across the columns *because* it ignores its switch, and this one is not.
`apps/live/routes.py::enabled()` **defaults ON**, uniquely among the togglable surfaces, and
the argument is in that function: every other gated surface costs the GPU or an outbound
fetcher the moment it is switched on, while this one serves files out of a directory that is
empty until OBS has been configured to write into it, so default-off could only produce a tab
that was broken on arrival. Its row reads the switch and would publish `offline` with
`SYMONEURAL_LIVE_ENABLED=0` set; neither run above sets it, so both read `ready`. The reading
was taken with the recording directory empty, and the row says exactly that in its detail
line — `nothing recorded yet — point OBS's Recording output at
backend/output/live` — which is the honest state of this box on 2026-08-21 and not a fault.
`busy` is reserved for a playlist actually growing on disk and is not reachable from a probe.

`ravencalc` was asked to do real work rather than merely answer: `integrate(x**2, x)` returned
`x**3/3` in **262 ms** (default run) and **289 ms** (switches-on run) — SymPy on the CPU, no
GPU lease, which is the row's whole claim.

The OpenAPI schema on the switches-on run carries **87 paths across 17 tags**.

A 503 in the `api` columns is not a fault. Every switched surface answers 503 with a body that
names its own switch — `gateway`, `project`, `miner`, `studio` all do, and that is the designed
behaviour: off by default, and say so.

## What this reading found — one row disagrees with itself

**`train` publishes `ready` on the rack while every request to it returns 503, in both
environments and on the live service.**

```
/api/status   train → state "ready", detail "adapter loaded · for model/adapter tuning"
/api/train/status → HTTP 503
  "SyMoNeuRaL Reinforce is off. Set SYMONEURAL_REINFORCE_ENABLED=1 and
   SYMONEURAL_REINFORCE_TOKEN to enable it. It is off by default because a never-evicted
   GPU route open to the internet takes the whole rack offline for one request."
```

Confirmed on `:8800` as well, so this is what visitors to the live site see today.

The cause is at `backend/api.py:1671-1678`. The row's state is derived from a file existing:

```python
state="busy" if holder == "train" else
      ("ready" if CHAT_ADAPTER.exists() else "offline"),
```

`SYMONEURAL_REINFORCE_ENABLED` is never consulted. The adapter file is on disk, so the row
reports `ready` forever, whatever the switch says. Note that `train` is identical in both
columns above *because* of this — it is the one row the environment could not move.

**It is the only row that does this.** The comparison is worth stating precisely, because the
obvious reading — "api.py-built rows report installed capability, delegated rows report
enablement" — is wrong, and it was checked:

- `chat`, `image` and `remix` also report installed capability (`gpu_unit(name, ok)` over
  `CHAT_MODEL.exists()` / `FLUX` / engine paths). But those three surfaces **have no enable
  switch at all**, so installed capability is the whole truth about them. They are not
  outliers; they have nothing to disagree with.
- `miner`, `coder` and `gateway` are built inline in `build_status()` too, and all three take
  their state from the app's own `unit_state()`, which reads the switch first.
- `streamer`, `project`, `sigils`, `studio` and `exp` delegate wholesale to `status()`.

So of the rows that **have** a switch, twelve read it and `train` does not.

The repo already states the rule this breaks, in its own voice, in
`backend/apps/coder/__init__.py:961-972`:

> `offline` is the honest default: this surface is off unless an operator switched it on, and
> **the rack must never show it as ready on the strength of the code existing.**

And `.claude/CLAUDE.md`: *"No decorative status indicators. Every LED and gauge on the site
reflects a real reading."*

**This is recorded, not fixed.** What a visitor-facing LED ought to mean is a judgement call,
and unlisted work does not start here on an agent's opinion that it is obviously useful — the
way in is `INTAKE.md` and the gate is Garrett ticking a box. It has been filed there. Fixing it
also obliges a re-read of `tests/frontend.mjs`, which asserts on what `/api/status` renders and
is itself already in the past tense.

## What this reading did not cover

- **chat, image, remix** were not exercised end-to-end. Their pages answer and their rack rows
  read installed capability correctly; whether a generation *succeeds* is what
  `tests/frontend.mjs` and `tests/studio.mjs` measure, and both take the card.
- **coder** has no endpoint to probe, by design. Only its page and its rack row were read.
- `state on` for `gateway` stays `offline` with the switch on because
  `SYMONEURAL_GATEWAY_NETWORK` is unset — the surface is enabled but unconfigured, and the row
  says so. That is correct behaviour, not a second instance of the `train` defect.
