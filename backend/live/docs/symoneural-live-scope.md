# SyMoNeuRaL Live — scope, and the import graph that keeps it honest

**Scope captured 2026-08-22.** Docs and scope only. **No implementation, no OBS or ffmpeg started,
no live stream touched, no deploy.**

## 1. What it is, and what it is not

> **SyMoNeuRaL Live is the live / media / OBS / HLS / status surface.**

Live broadcast and watch surface · OBS bridge where implemented · HLS/session output where
implemented · **NET/media surface** unless GPU/NVENC is explicitly implemented and proven ·
watchable while running **and after the stream ends**, where the current code supports that.

**Live is not the Live Stack.** Live is one unit *on* the rack; Live Stack is the rack
(`symoneural-live-stack.md`). Two objects sharing five letters, and conflating them is how a fold
loses a surface.

Classification: **PROD direction only where the OBS/HLS/session paths are proven.** Rack row
`live`, `bus="net"`, `/livestack/live`. `backend/apps/live/` — 9 tracked files.

## 2. The requirement "absent OBS must not break boot" is enforced by architecture

`backend/apps/live/__init__.py:9-13` is the answer, and it is better than a rule because it cannot
be forgotten:

| Module | Role |
|---|---|
| `hls.py` | **the video.** Reads a directory. *"No credentials, no network, no obs import."* |
| `obs.py` | **the readings.** Holds the obs-websocket password, talks to loopback only |

> *"`hls.py` does not import `obs.py` and must not start to. That import graph is the guarantee that
> a wrong password or a stopped OBS takes the telemetry line off the page and leaves the"* video
> playing.

**So the failure mode is already bounded by dependency direction rather than by a try/except
somebody has to remember.** A wrong OBS password costs the telemetry line, not the stream. **Do not
add an `obs` import to `hls.py`** — that single edge would convert a degraded telemetry readout into
a dead video surface.

Consequences: **absent OBS is normal** unless a specific Live mode requires it · API boot must not
fail without it · a reconnect loop must not create an invisible storm · status says *offline / not
connected* rather than silently passing.

## 3. Why `bus` is `net` and not `gpu` — the least obvious cell in the rack

**OBS encodes with NVENC, so a stream genuinely does use the card.** `ROSTER.md` records why the row
still reads `net`:

> it uses the card **outside `scripts/gpu-governor.sh`**, which **cannot see the session, cannot
> evict it, and does not count it against its drain floor.** Writing `gpu` *"would enter this row in
> the rack's 'who holds the card' readout and advertise management that does not exist."*

What the row actually spends is **upstream bandwidth**, and `apps/live/README.md` records the GPU
cost as **unmeasured** — which it is.

**Live becomes a GPU governor tenant only when a GPU/NVENC path is implemented under the governor
and proven**, with its own lease and its own tests. Until then `net` is the honest cell, and
"correcting" it to `gpu` is a regression dressed as accuracy.

## 4. Why Live has no operator power switch, and why that is the right answer

Live is **excluded** from `TOGGLEABLE` in `apps/controlboard/__init__.py`, and the recorded reason is
the sharpest example of the repo's honesty rule:

> the override **could not do what the button would promise** — OBS keeps writing segments whatever
> this rack says, so the row would read *taken offline by operator* while a stream stayed genuinely
> watchable.

**A control that cannot deliver its promise is worse than no control**, because it converts an
honest surface into a lying one. **The exclusion is the feature** and must not be "fixed" by adding
the switch.

## 5. State must distinguish page-ready from actively-live

Two different facts, and one chip cannot carry both:

- **the page and route are ready** — `/livestack/live` serves, `hls.py` can read its directory
- **a live session is active** — segments are being written now

`state` must not report the second when only the first is true. **No fake stream or live claim**, and
**no `ready` unless the page, route, session and bridge state are actually proven.** Detail text
should say which of the two it means.

## 6. Session and process hygiene

Live sessions and stream processes are **cleaned up on shutdown and reload** · stale sessions must
not leak ffmpeg processes · **live output is served only from controlled paths** — no path traversal,
no arbitrary file or URL served on request · **provider credentials and stream keys must not leak**
into logs, into page source, or into a committed config.

`obs.py` holds the obs-websocket password and **talks to loopback only.** That containment is part
of the design, not an accident of configuration.

## 7. Relationship to Streamer

Both are media surfaces and they are not the same thing. **Streamer** is ingestion, playlists,
Xtream channels, guide/EPG and tuning — bound by the provider network
(`symoneural-streamer-scope.md`). **Live** is Garrett's own broadcast, watchable while it runs and
after it ends.

They share `bus="net"` for **different reasons**: Streamer because an IPTV surface is bound by the
provider link, Live because the card it uses is outside the governor. **Do not merge them on the
strength of a shared bus value.**

`tests/live.mjs` is the browser suite (needs `tests/live-harness.py`; no GPU, no OBS) — and it
carries its own lesson, recorded in `apps/coder/SMOKE-surface.md`: it *"sat on disk for a fortnight
satisfying `exists` and `grep` and could not be loaded by `node` at all — a SyntaxError on line 17,
before a single assertion ran."* **A test file's existence is not evidence it runs.**

## 8. Not authorized

No implementation · no `obs` import added to `hls.py` · no `bus` change · no toggle added · no OBS or
ffmpeg started · no live stream, credential or stream key touched · no route change · no folder
migration · no deploy.
