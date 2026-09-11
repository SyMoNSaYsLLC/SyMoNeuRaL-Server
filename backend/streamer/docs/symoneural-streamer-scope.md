# SyMoNeuRaL Streamer — scope, and the fold that is already done

**Scope captured 2026-08-22.** Docs and scope only. **No implementation, no OBS or ffmpeg started,
no live stream or provider touched, no `@symoneural streamer.tar.gz` import, no deploy.**

## 1. What it is

> **SyMoNeuRaL Streamer is the combined media surface**: stream ingestion · playlist/M3U handling ·
> Xtream-style channel listing where implemented · guide/EPG filtering · session playback and
> control · tuning · HLS/restream where implemented · OBS bridge where implemented.

**Streamer is not the old Tuner page renamed, and it is not Guide.** It is the folded product
surface that carries both.

Classification: **PROD direction**; preserve the routed surface, audit before migration. Rack row
`streamer`, `bus="net"`, `/streamer.html`.

## 2. The fold is done, and the routing requirement is already satisfied

Garrett's instruction is recorded in `backend/apps/streamer/__init__.py:3-4`: *"symon guide and
symon tuner should be migrated together"*, then *"you need to migrate tuner and guide to be 1."*

`__init__.py:9-11` records the split that resulted: the streamer half owns **HLS sessions, playlist
parsing and SSRF-pinned fetches**; `guide/` is **the library half**, and it **owns no weights** —
*"see `guide/__init__.py` for why that is the architecture and not a"* convenience.

**And the nesting the brief asks for is already in place**, `__init__.py:18`:

```python
app.include_router(streamer.guide_router, prefix="/api/streamer/guide")
```

with the reason recorded at `:28-30`: guide is nested at `/api/streamer/guide`, **not** given a
sibling prefix and **not** flattened — because a flat mount would leave *"a second registration
shadowed by the first and the guide's capability probe would have started"* answering the wrong
thing.

**That is exactly the decorative-indicator failure the brief predicts**: both surfaces expose
`/state`-like routes, so a flat mount lets Guide's readiness resolve against Streamer's answer and
the rack reports Guide ready because *Streamer* replied. The nesting is the fix and it must not be
undone.

## 3. Measured route surface

`backend/apps/streamer/routes.py`, under `/api/streamer`:

`POST /playlist` · `POST /xtream/info` · `POST /xtream/channels` · `POST /epg` · `POST /epg/xmltv` ·
`POST /tune` · `GET /session/{sid}` · `POST /session/{sid}/stop` · `GET /stream/{sid}/{name}` ·
`GET /state` — plus the nested guide router at `/api/streamer/guide/*`.

**Being mounted is not the same as producing media.** A `400` on bad input or a `404` on a fake
session still proves the route exists, and **that is the only claim such a response supports.** Do
not claim successful media output unless a test proves it.

## 4. Rules carried forward

- **Tuner is retired as a top-level product name.** One public Streamer name, **one** rack row.
- **Guide is preserved, not dropped** — `apps.streamer.guide` remains and
  `/api/streamer/guide/*` continues to serve guide/filter behaviour.
- **Guide must not take the GPU governor lock.** It is CPU/network/data work and answers while the
  card is busy. Hiding that property would be a regression.
- **No permanent `/api/tuner/*` alias** unless explicitly authorized.
- Old page names `/tuner.html` and `/tuner-watch.html` **redirect** to `/streamer.html` and
  `/streamer-watch.html` where the redirect layer exists; users must not land on retired Tuner
  branding.
- **No duplicate rack rows pointing at the same page.** This is not hypothetical — the rack once
  showed one page twice because Tuner and Guide both used `/tuner.html`.

## 5. The webroot correction — absent is not the same as stale

The known failure was: `/streamer.html` missing or stale on the public origin while `/tuner.html`
still answered.

**So do not diagnose Streamer as absent merely because the public webroot is stale.** Regenerate
pages and cache-bust only in a scoped page/build task, ensure `/streamer.html` and (if part of the
current product) `/streamer-watch.html` exist in the generated site, and ensure the old names
redirect where route code supports it.

Open task **#86** is the general form of this: *a page can ship to `site/` and never reach the
webroot, and nothing goes red.* **Localhost success does not prove deployed-webroot success.**

## 6. GPU relationship — `net`, and why that is deliberate

**Streamer is not a GPU model surface by default.** Guide is CPU/network/data; tuning and streaming
are CPU/network/ffmpeg work unless NVENC or GPU transcode is explicitly implemented and proven.

Note the recorded disagreement: `apps/streamer.status()` returns `bus="cpu"` and `api.py` overrides
it at the call site with `bus="net"`. **`net` is the truth about the row** — an IPTV surface is bound
by the network, not by this box's cores — and `test_roster.py` knows about the override **by name**
rather than skipping the row (`ROSTER.md`; `symoneural-live-stack.md` §3).

So: **do not make Streamer acquire the GPU lock for guide/filter work**, and **do not make it queue
behind Chat or Image** unless it is genuinely using the GPU. **If NVENC/GPU transcode arrives later,
it registers as a governor tenant with its own lease and its own tests** — and never uses GPU
acceleration silently, without status reporting.

## 7. OBS, ffmpeg and sessions

**Absent OBS is normal** unless a specific mode requires it. API boot **must not fail** without it,
a reconnect loop must not create an invisible storm, and status must say *offline / not connected*
rather than silently passing.

If ffmpeg sessions are used: the process/session manager **cleans up on shutdown and reload**, stale
sessions must not leak ffmpeg processes, output paths are controlled, **no arbitrary URL or file
execution from public users**, and **no credential leakage in logs.**

Related surfaces — SyMoNeuRaL TV, a restream worker, HLS outputs, an OBS bridge, live-stack pages, a
session manager, watch pages — **are not claimed as production without current tests or logs.**

## 8. Provider credentials

Streamer handles sensitive provider data: M3U URLs · Xtream credentials · provider usernames and
passwords · API keys · stream tokens · OBS credentials · private URLs · `.env` · session secrets.

**Do not print secrets into logs · do not expose provider URLs in public page source · do not commit
stream or provider configs · do not use real accounts in tests** — fixtures carry fake URLs and
credentials only. Public endpoints validate input and reject unsafe paths and URLs; the fetches are
**SSRF-pinned** already (§2). **Any operator route that starts a stream, writes files, or controls
OBS/ffmpeg is gated.**

## 9. Archive mapping

`references/IPTV/symoneural streamer.tar.gz` — **284,011,213 B (271 MiB)**, the largest of the five
references, **unopened**, **AUDIT until inspected.**

Inspect structure first · extract requirements before code · compare against the current
Streamer/Tuner/Guide implementation · normalise useful pieces into docs and tasks · **do not import
blindly, do not commit it, and do not replace the current Streamer from it.**

## 10. Not authorized

No implementation · no route added, removed or aliased · no page regenerated · no redirect added · no
OBS or ffmpeg started · no provider, stream, M3U source or account touched · no archive import · no
folder migration · no deploy.
