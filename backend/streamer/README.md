# SyMoNeuRaL Streamer

An IPTV surface. The visitor brings their own subscription; this box brings a validated fetch,
a stream-copy transcode and a bounded number of slots. **No playlist, credential or channel is
stored here** — the browser holds all of it in `localStorage` and sends what it needs per
request.

Standard library plus `fastapi` and `pydantic`, which the system interpreter already has.
Nothing was installed, no venv was created. `ffmpeg` 7.1.5 is the transcoder.

```
backend/apps/streamer/
  __init__.py     exports `router` and `status` — the whole contract with api.py
  safefetch.py    the SSRF door: validate, pin, connect, redirect, redact
  m3u.py          M3U/EXTINF channel parser + a separate HLS playlist parser
  xtream.py       Xtream Codes protocol client
  sessions.py     ffmpeg HLS sessions: the pump, the caps, the reaper
  epg.py          the programme guide: get_short_epg and XMLTV, on one clock
  routes.py       the APIRouter and the rack `status()`
  test_epg.py     34 tests against a scripted panel, offline
  test_streamer.py   108 tests, offline, no provider needed. Includes a local repro
                  harness: ffmpeg synthesises the failure modes (HTML at 200, a 403
                  page, a User-Agent gate, AES-128 HLS, HEVC) so every fix is falsifiable
                  without a provider account.
```

---

## Wiring — what the API needs to do

```python
# backend/server.py — the whole of it
from apps.streamer import router as router, status as status

app.include_router(router, prefix="/api/streamer")
```

and in `build_status()`:

```python
Unit(**status()),
```

Points that matter:

- **`backend/` must be on `sys.path`.** It already is when `api.py` runs, and `apps` is an
  implicit namespace package, so `import apps.streamer` works with no `__init__.py` in `apps/`.
  This module is *not* added to `sys.path` the way `ravencalc` is — it is a package, imported
  as one.
- **The prefix is assumed to be `/api/streamer` but not hardcoded.** The router declares relative
  paths only. The one place the prefix leaks is `Session.public()["playlist"]`, which is the
  **relative** string `stream/<id>/live.m3u8`; the page must resolve it against the tune
  endpoint's own URL. It is relative precisely so this module never has to know its mount point.
- **`status()` is synchronous, cheap and safe to call on every rack poll.** It reads a dict of
  live sessions and touches no filesystem and takes no lock.
- **`status()` returns a plain dict, not a `Unit`.** Its keys match `api.py`'s `Unit` fields so
  `Unit(**status())` works. It deliberately does not import `Unit` — that would put this
  module inside `api.py`'s import graph, which is outside the scope this was built in. If you
  prefer the import, the change is yours to make.
- **Shutdown hook:** call `apps.streamer.sessions.MANAGER.shutdown()` from the API's lifespan
  teardown. Without it, a reload leaves ffmpeg processes running until their lifetime cap.
  Not fatal, but untidy on a box with a contended GPU. Note this takes no governor lock and
  must never take one — see below.
- **No config file, no secrets, no new deploy step.** Everything tunable is an environment
  variable with a safe default (table below).
- **The page needs `hls.js`** — see "Frontend" below. That is the one thing this module cannot
  do for you.

### The GPU governor is deliberately not involved

The Streamer never takes the GPU lock. It is `-c copy` — a demux and a remux, no decoding, no
encoding, no CUDA — so it is a CPU surface like RavenCalc, and the rack unit reports
`bus: "cpu"`. Making it queue behind chat or image would be a lie about what it uses.

### The rack unit is the Streamer AND the Guide

Garrett: *"symon guide and symon streamer should be migrated together"*, then *"you need to migrate
streamer and guide to be 1"*. The rack used to carry two units whose `href` was the same page,
which is a rack disagreeing with itself about how many things this box runs. `status()` now
returns one unit, labelled *SyMoNeuRaL Streamer & Guide*, and `api.py` no longer builds a `guide`
unit.

**Nothing was deleted to achieve it.** `backend/apps/streamer/guide/` is untouched and its filter
still serves the page — the fold is in what the rack claims, not in what runs. It answered at
`/api/guide/*` when that was written; the later namespace half of the same merge moved it to
`/api/streamer/guide/*`, nested rather than flat because both routers declare `/state`. The
guide half's own claim is carried in the streamer unit's detail line in every state, because it is
the thing a visitor cannot check by looking: *guide filtering on the CPU, never takes the GPU
lock*. That is the same claim RavenCalc makes and it is worth as much here.

Note what `offline` now means: without ffmpeg the streaming half cannot work but the guide half
still answers perfectly, so the offline detail names the part that is missing rather than
implying the whole surface is dead.

### Environment variables (all optional)

| Variable | Default | Meaning |
|---|---|---|
| `SYMONEURAL_STREAMER_MAX_SESSIONS` | `2` | Concurrent ffmpeg processes (clamped 1–8) |
| `SYMONEURAL_STREAMER_IDLE_TIMEOUT` | `45` s | No player request for this long → reaped |
| `SYMONEURAL_STREAMER_MAX_LIFETIME` | `1800` s | Hard ceiling on a session |
| `SYMONEURAL_STREAMER_MAX_BYTES` | `4096` MB | Per-session upstream data cap |
| `SYMONEURAL_STREAMER_DIR` | a fresh `mkdtemp` | Where HLS segments are written |
| `SYMONEURAL_STREAMER_USER_AGENT` | `VLC/3.0.20 LibVLC/3.0.20` | What upstream requests identify as |

There is deliberately **no variable that relaxes the SSRF policy.** The user-agent override is
the *only* environment variable `safefetch.py` reads, a test enforces that line by line, and a
second test starts a fresh interpreter with `SYMONEURAL_STREAMER_ALLOW_PRIVATE=1` and friends set
and asserts `Policy().allow_private` is still `False`.

### Why the default agent is VLC and not our own name

A provider's edge is a paywall, and the cheapest filter any panel applies is on `User-Agent`:
the paying customer runs VLC, Kodi, TiviMate or a set-top box, so an unknown agent is assumed to
be a scraper or a reseller. A large share of providers refuse one — and often **not** with an
honest 403, but with HTTP 200 and an HTML "player not supported" page, which used to arrive at
the pump as the stream body. That is the blank-screen-with-everything-green failure. The old
default, `SyMoNeuRaL-Streamer/1`, was the polite and correct thing for a bot to send and was
costing streams. This is not defeating a security control: the credential is the visitor's own
and the request is the one their own player would make.

---

## Endpoints

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/playlist` | `{url}` or `{text}` → parsed channels, groups, `truncated` |
| `POST` | `/xtream/info` | `{server, username, password}` → account status, expiry, connection limits |
| `POST` | `/xtream/channels` | `+ {kinds: ["live","vod","series"]}` → catalogue |
| `POST` | `/epg` | `+ {stream_id}` or `{stream_ids: [...], limit}` → the guide for a grid |
| `POST` | `/epg/xmltv` | `+ {ids, max_per_channel}` → the whole account's guide in one request |
| `POST` | `/tune` | `{url, label}` → starts a session, waits up to 25 s for real output |
| `GET` | `/session/{sid}` | session state (also a heartbeat) |
| `DELETE` | `/session/{sid}` | stop and free the slot |
| `GET` | `/stream/{sid}/{name}` | the HLS playlist and its segments (also the heartbeat) |
| `GET` | `/state` | slots, active sessions, whether ffmpeg exists |

**Every credential arrives in a POST body.** There is no `GET` that takes one and there never
may be: uvicorn logs the full request line, so a credential in a query string or path segment
is a credential written to `run/api.log` on every request. A test enforces this structurally
against the route table.

`POST /tune` waits for ffmpeg to actually write a playlist before returning success, because
ffmpeg on a source it cannot stream-copy exits several seconds after starting — returning "ok"
on `Popen` succeeding would be a status the box has not earned.

**The wait is 25 s, and that number was measured, not chosen.** Feeding a 1.9 Mb/s H.264/AAC
transport stream into the exact argv `_spawn` builds, timing the appearance of `live.m3u8`:

| upstream rate | time to first playlist |
|---|---|
| unthrottled | 0.1 s |
| 8 Mb/s | 2.5 s |
| 2 Mb/s | **9.7 s** |
| 0.8 Mb/s | 24.1 s |

The old deadline was 10 s, which an ordinary 2 Mb/s stream — what a provider pacing at real
time gives you — misses by a fraction of a second, returning "no playable output yet" on a
request that was about to succeed. The same measurement repeated at `-probesize`/
`-analyzeduration` of 2M, 5M and 10M produced times identical to within 0.1 s at every rate, so
**the probe sizes were left alone**: time to first playlist is bounded by how much data the HLS
muxer needs to close its first segment, not by the probe. Raising them would have been a guess
dressed as a fix.

---

## The programme guide — `epg.py`

Garrett: *"you need to pull epg do you know how to do it?"*, and then, of the tick-grid that
was the only way to look at live TV: *"update the damn streamer guide with epg and not that
terrible tiny select and deselect shit."*

Two sources, and they are not alternatives — they answer different questions:

| | `get_short_epg` (`POST /epg`) | `xmltv.php` (`POST /epg/xmltv`) |
|---|---|---|
| shape | JSON, one channel per request | one XML document, the whole account |
| keyed on | `stream_id` | `tvg_id` / `epg_channel_id` |
| titles | base64 | plain text |
| times | `start_timestamp` epoch | `20260817140000 +0000` |
| cost | one request per channel | one request, tens of MB |

**There is no `get_live_movies` or `get_live_vod` action.** That was asked directly and the
answer is that neither exists in Xtream Codes; a film has no schedule, and the honest answer
for VOD is the catalogue.

What the module refuses to do, and each refusal is a decision:

* **A timestamp with no UTC offset is dropped, not guessed.** XMLTV permits a bare
  `20260817140000`, and the only way to place it on a clock is to assume the provider's
  timezone is yours. A guide that is silently three hours wrong is worse than one that says it
  has nothing — so those rows are counted into `dropped_no_clock` and the count is published.
  `calendar.timegm` is used rather than `time.mktime`, so the box's own `TZ` cannot move
  anybody's guide.
* **A channel whose every row is undateable gets no bucket at all**, rather than an empty list.
  `{"a.tv": []}` would claim "this channel has a guide and it is empty", which is not what
  happened.
* **`_maybe_b64` decodes only when the result is believable.** `"News"` is valid base64 and
  decodes to bytes that are not text; a decoder that trusts the encoding turns a title into
  mojibake.
* **A truncated XMLTV document keeps what it parsed.** A panel that times out mid-write still
  returns 200, and discarding 9,000 good channels because the 9,001st is half-written is the
  wrong trade. `iterparse` + `elem.clear()` keeps memory bounded either way.
* **`now_next` returns `None` rather than `programmes[0]`.** A `get_short_epg` reply routinely
  begins in the past and can have a gap; a "now" plucked from whichever row happened to be
  first is the same class of lie as an always-green status LED.

`now`/`next`/`progress` are computed **on the server**, because the clock that matters is the
one the provider's timestamps are on. A visitor with a wrong system clock would otherwise see a
guide that is wrong in a way nothing on the page could explain.

`POST /epg` caps at **60 ids** and runs **6 at a time**; the page asks for the 30 rows it is
showing and no more. Each id is one request to somebody else's panel, so a "just fetch
everything" grid is a page hammering a third party. Measured against a real account: a grid of
24 named broadcasters answered **24/24 in 1,275 ms**, 23 of them with a programme on now. Of
10,072 live channels, **5,304 (52%) carry a `tvg_id`** — the rest genuinely have no guide, and
the page says so per row rather than drawing an empty box.

`backend/apps/streamer/test_epg.py` covers all of the above against a scripted panel: 34 tests,
no network.

---

## SSRF — `safefetch.validate_url`

One function, one docstring listing every rule, one hostile-input table in the tests.

1. `http` and `https` only, by allow-list, so `file:`, `gopher:`, `dict:`, `data:` and the rest
   need no individual rule.
2. The hostname is **resolved once**, and **every** address it returns must pass. A name with
   both a public and a private answer is refused outright rather than having the public one
   picked.
3. The **resolved address** is judged, never the hostname string: loopback, RFC1918 private,
   link-local (`169.254.0.0/16`, so cloud metadata), IPv6 unique-local, multicast, reserved,
   CGNAT and everything else not globally routable, with IPv4 addresses embedded in IPv6
   (`::ffff:`, 6to4, Teredo) unwrapped and judged on their own merits. This is why
   `http://2130706433/`, `http://0177.0.0.1/` and `http://127.1/` are all blocked and why no
   hostname denylist is needed or used.
4. Redirects are followed **by this module, capped at 6**, and each `Location` goes back
   through the same validator. Six rather than three because Xtream stream URLs chain —
   panel → balancer → region → edge, sometimes with a token handoff — and three was a guess
   that failed ordinary providers. Length is not the security property; every hop is
   re-validated, so the cap only exists to end a loop.

**DNS rebinding** is handled by there being only one lookup. `validate_url` resolves the name
and returns the approved address; `_PinnedHTTPConnection` connects to *that address* while
keeping the hostname for the `Host:` header and the TLS SNI, so certificate validation and
name-based virtual hosting still work and there is no second lookup for an attacker's second
answer to win. A test asserts the resolver is called **exactly once** for a successful fetch —
if a future change reintroduces a lookup at connect time, that count goes to 2 and the test
fails.

**The validator is not advisory.** No visitor-supplied URL is ever handed to a subprocess.
ffmpeg would resolve its own names and follow its own redirects in another process, which would
make this file decoration — so Python holds the upstream socket and ffmpeg reads `pipe:0` with
`-protocol_whitelist pipe,fd`. A test greps `_spawn` to keep it that way.

---

## Credentials

Never written to disk, never logged, never in a URL on any route here.

- The pipe architecture keeps them out of `argv`, so they are not visible in `ps` either.
- `XtreamCreds.__repr__` and `__str__` are overridden, so a traceback containing the object
  does not contain the password.
- Every credential-bearing pydantic field **has a default**. This is a leak fix, not laziness:
  a *missing required field* makes pydantic raise a `ValidationError` whose `input` is the whole
  request body, and FastAPI serialises that into the 422 response — so omitting `server` would
  have echoed the password back inside an error document. With defaults there is no validation
  path that can touch these values.
- Upstream exceptions are never re-raised with their message; `ssl` and `http.client` both quote
  URLs. Errors are rebuilt from a fixed string plus `scheme://host:port`.
- `Scrubber` carries the session's own literals, because an Xtream password sits in a *path
  segment* (`/live/<user>/<pass>/<id>.ts`) where a pattern-based redactor sees nothing. It is
  applied to ffmpeg's stderr. `Scrubber.from_url` derives those literals from the URL itself,
  which is what protects the **M3U path** — a visitor who pastes an Xtream-exported playlist
  sends `/tune` no username or password field at all, so a scrubber primed from the request
  body would be empty.
- **ffmpeg's stderr never reaches the client.** It is kept in `Session.transcoder_error`
  (internal, for logging) and `public()["error"]` carries only this package's own origin-only
  messages, or the fixed sentence *"the transcoder could not stream-copy this source"*. So the
  page cannot show ffmpeg's exact complaint — deliberately. Read it from the log instead.
- **`public()["vcodec"]` and `public()["acodec"]` are the two published fields derived from
  ffmpeg's output**, and they are safe for exactly one reason: they are not ffmpeg's text, they
  are tokens from allow-lists (`sessions.VIDEO_CODECS`, `sessions.AUDIO_CODECS`) that ffmpeg's
  text was matched against. Anything unrecognised — including a hostile stream whose metadata
  quotes a credential — becomes `""`. Tests feed the matchers a fabricated
  `Stream #0:0: Video: <sentinel password>` line and the audio equivalent, and assert the
  document stays clean.
- **An upstream error body is excerpted into the message**, which is the most dangerous string
  in the package: panels reflect the requested path back, credentials and all. It goes through
  `Scrubber.from_urls` over both the requested and the reached URL, which treats every path
  segment and query value as a secret. Over-scrubbing is the accepted cost — a message about a
  channel not being "live" may come back as not being "***" when the URL had a `/live/` segment.
- The test suite pushes a sentinel password through the real router and greps **log output, the
  response bodies, the exception text and the session document**.

---

## For the `api.py` / frontend owner — what changed under you

Nothing in the wiring contract moved: `router` and `status()` are unchanged, no new dependency,
no new deploy step. Two things are new in the payloads and one is a behaviour change.

1. **`Session.public()` gained `"vcodec"`** — a lowercase codec token (`"h264"`, `"hevc"`,
   `"mpeg2video"`, …) or `""` when it is not known yet or not recognised. The page **must check
   it even when `state == "live"`**. That is the whole point: an HEVC stream copies perfectly,
   the playlist is written, segments return 200, the session is genuinely live — and no browser
   decodes HEVC in MSE, so the visitor sees a black rectangle with every indicator green. The
   copy to write is roughly *"this stream is H.265/HEVC and your browser cannot decode it"*, and
   it is the honest thing to say rather than letting the player fail silently. `vcodec == ""` is
   not an error; it means the codec has not been read yet, so do not warn on it.

   **`"acodec"` is published too, and checking only `vcodec` is not enough.** It was withheld on
   the reasoning that an unused field is a field nobody is checking; a measured failure says that
   was wrong. One of the owner's channels reported `state: live`, `vcodec: h264`, 87 MB pulled
   from the provider over five minutes and every indicator on the box green, while the browser
   decoded **zero** frames — because MSE refuses the whole segment when it will not take the
   AUDIO track, and Chrome takes no AC-3. The picture stops for a soundtrack, and a page that can
   only see `vcodec` reports a perfectly healthy h264 stream over a black rectangle.

   **Ask the browser, do not consult a table.** The pages call
   `MediaSource.isTypeSupported()` against both `video/mp2t` (what this box serves) and fMP4
   (what hls.js remuxes to), and warn only when *neither* is accepted. Measured on Chrome 151:
   h264, aac, mp2 and mp3 accepted; hevc, mpeg2video, vc1, av1, vp9, ac3, eac3, dts and truehd
   refused. A hard-coded list would have been wrong about mp2 in the same week it was written.
2. **`public()["error"]` is now often the provider's own sentence**, not only our fixed one:
   `"http://host:80: upstream returned HTTP 403 - Subscription expired. Your account ran out on
   2026-01-01."` It is scrubbed, single-line and capped near 300 characters, but it is *third-
   party text* — render it as text, never as HTML. Expect `***` in the middle of some of them;
   that is the scrubber over-redacting a path segment on purpose.
3. **`POST /tune` can now block for up to 25 s** instead of 10 (measured; see the table above).
   Any client-side timeout on that call needs to be longer than 25 s, or it will abort requests
   that were about to succeed — the failure mode looks exactly like the bug this was fixing.

Nothing else in `public()` changed, and it still has no field that can hold a credential.

## Frontend — what the page must do (not built here; out of scope)

- **Include `hls.js`.** Safari plays `.m3u8` natively; Chrome and Firefox need MSE. This module
  cannot supply it and does not pretend to. Note the site's CSP/no-external-asset habit: it will
  need to be vendored locally, not pulled from a CDN.
- Resolve `session.playlist` (relative) against the streamer API base.
- Keep requesting segments — that is the session heartbeat. Stop, and the slot is reclaimed in
  `IDLE_TIMEOUT` seconds. Call `DELETE /session/{sid}` on unload to be polite.
- **With nothing loaded, show empty and offline.** No mock channel list, no sample EPG, no
  signal-strength meter. `/state` returns `channels_stored: 0` and means it.
- No `text-overflow: ellipsis` anywhere — channel names and group titles wrap. House rule.

---

## What is implemented

- M3U/EXTINF parser: attributes, `group-title`, `tvg-*`, `#EXTGRP`, CRLF, BOM, bare URLs,
  commas inside quoted attribute values, `MAX_CHANNELS` bound with an honest `truncated` flag —
  honest as far as the API, and for a while no further: the page read that flag nowhere, so a
  playlist over the cap silently lost its tail block under the words "Loaded from your
  playlist". A cap the visitor is not told about is not a cap, it is missing data. The page now
  names the limit.
- **Two byte ceilings, because a catalogue is not a playlist.** `safefetch.Policy.max_bytes` is
  24 MiB and was sized for an M3U file; `xtream.CATALOGUE_MAX_BYTES` is 64 MiB and applies to
  the Xtream catalogue fetches only, carried in with `dataclasses.replace` so the rest of the
  policy — `allow_private` above all — is untouched. They are separate because they measure
  different documents: measured against one real panel, live was 10,124 channels in 3.77 MB and
  series 7,883 shows in 6.43 MB, but movies were **31,888 titles in 27.57 MB**, since each film
  row carries `plot`, `cast`, `director` and `youtube_trailer` that this module discards. One
  ceiling for both meant Live TV and Series populated while Movies stayed empty. When a
  catalogue genuinely does exceed the ceiling, `XtreamTooLarge` makes the note say that *this
  box* declined it — "unavailable on this panel" blames the provider for our own limit.
- **live/vod/series classification that consults the group title.** The URL is authoritative
  when it says anything (`/live/`, `/movie/`, `/vod/`, `/series/`); the group title is consulted
  only as the fallback, in place of the old unconditional default of `live`. That default was
  the real "the Movies category is empty" bug on the plain-M3U path: a film at
  `http://host/12345.mp4` under `group-title="VOD | Movies"` has no `/movie/` segment anywhere,
  so every film arrived marked `live`. The cost, stated rather than hidden: a genuinely linear
  channel in a film-named group ("24/7 Movies") now counts as `vod`.
- Xtream Codes: authenticate, account info, live/VOD/series catalogues, stream URL construction.
- HLS output by stream copy, verified end to end: a real transport stream in, `live.m3u8` plus
  segments out, segments confirmed to decode as `h264`/`aac` with no re-encode.
- Upstream **direct** (continuous TS) and upstream **HLS** (master-variant selection, media
  playlist polling, `EXT-X-MEDIA-SEQUENCE` tracking), both verified end to end locally.
- Caps: concurrent sessions, idle timeout, hard lifetime, per-session byte cap, a reaper that
  runs whether or not the client disconnected politely, and a segment-name allow-list.
- **AES-128 HLS decryption.** `#EXT-X-KEY` is parsed in full — METHOD, URI, IV, KEYFORMAT —
  and attached to each segment it governs, so mid-playlist key rotation and a mid-playlist
  `METHOD=NONE` both work. Keys are fetched through `safefetch` (a key URI is a third-party URL
  like any other and is re-validated), resolved against the *playlist* URL, cached per URI, and
  required to be exactly 16 bytes. The IV comes from the `IV` attribute or, per RFC 8216 §5.2,
  from the segment's media sequence number. PKCS#7 unpadding is lenient, which is only safe
  because the first decrypted segment is checked for transport-stream sync: a wrong key does
  *not* fail on its own — CBC produces 16-byte blocks of noise and the unpadder cheerfully
  strips a random tail — so without that check a key mismatch would have been reported as
  "ffmpeg could not read the source". `cryptography` is imported lazily; if it ever goes
  missing, unencrypted streams still play and encrypted ones get the old honest refusal back.
- **Error-page detection.** A provider answering a dead channel with HTTP 200 and an HTML
  "stream offline" page is reported as *the provider's own words*, not as a transcoder failure.
  The sniff is markup-in-the-body (conclusive) OR a texty content type with no MPEG-TS sync
  pattern — deliberately not "the content type is texty", because misconfigured servers send
  real transport streams as `text/html` constantly and a header-only rule would break every one
  of those working streams.
- **Codec reporting.** `public()["vcodec"]` and `public()["acodec"]` name the codecs ffmpeg
  found. This exists for the nastiest failure here, the one where every indicator is green:
  `-c copy` succeeds, the playlist is written, segments are served with 200s, and the browser
  still shows a black rectangle. HEVC video is the obvious case. **AC-3 audio on H.264 video is
  the case that was missed for months**, because the video codec looked fine and the audio codec
  was not published — MSE refuses the whole segment over the soundtrack, so the picture dies
  too. There is nothing to fix in the pipeline; the only honest response is to say which codec
  arrived, both of them.
- 108 tests, offline, ~13 seconds (ffmpeg builds the media fixtures). Every fix above was
  verified by reverting it and confirming the guarding test fails.

## What is NOT implemented — the honest gap list

1. **No frontend.** No `site/streamer.html`, no player, no CSS. Out of scope by instruction, and
   the module is untested against a real browser.
2. **No EPG.** `xmltv.php` exists on Xtream panels and is not fetched. `tvg-id` is parsed and
   passed through so a future EPG can join on it, and that is all.
3. **Series episodes are not playable.** The catalogue lists a series with an **empty `url`**
   because `get_series_info` is not called; the UI must not show a play button for those. An
   episode URL was deliberately not guessed — that would produce a channel that looks playable
   and is not.
4. **SAMPLE-AES, DRM and unknown encryption methods are refused,** by name. Plain
   `METHOD=AES-128` **is** decrypted now (see below). The refusals are an allow-list on METHOD,
   not a denylist: `AES-256`, `SAMPLE-AES-CTR` and anything a panel invents are refused rather
   than fed to a CBC decryptor that would not fail, would produce noise, and would hand that
   noise to ffmpeg. SAMPLE-AES specifically encrypts only NAL unit payloads and leaves the
   container clear, so whole-segment CBC decryption destroys the parts that were never
   encrypted — silent corruption replacing an honest refusal. A `KEYFORMAT` other than
   `identity` is DRM (`urn:uuid:edef8ba9-…` is Widevine) wearing an AES-128 METHOD, and is
   refused too: the URI leads to a licence server, not to sixteen bytes.
5. **No reconnect or failover.** The reference's failover between two hardcoded sources went
   with the hardcoding; failing over to a source the visitor did not choose is not resilience.
   A dropped upstream ends the session and says so. A brief reconnect for live streams would be
   a reasonable addition and is not here.
6. **Progressive MP4 VOD over a pipe may fail.** An MP4 whose `moov` atom is at the end of the
   file is not demuxable from a non-seekable stdin. Live TS and HLS are unaffected. Untested
   against a real VOD source — I had no provider.
7. **Never tested against a real IPTV provider.** Every test and every smoke run used
   synthetic streams generated locally. The Xtream client is written to the protocol shapes in
   the JS reference and is **unverified against a live panel** — that is the single largest
   risk in this module, and the first thing to exercise once someone has credentials.
8. **`-c copy` only.** A source whose codecs cannot enter an MPEG-TS segment unchanged fails
   with ffmpeg's error rather than being re-encoded. Deliberate: the GPU is reserved for
   inference and re-encoding on the CPU would compete with serving the site.
9. **Bandwidth.** Session and byte caps bound it, but a public streamer is still a box fetching
   third-party video on request. Whether that is acceptable egress is a product decision nobody
   has made yet.
10. **Segments default to `/tmp`, which is usually tmpfs**, so they cost RAM. Bounded at
    roughly `hls_list_size × hls_time × bitrate × MAX_SESSIONS` — about 25 MB at 8 Mb/s with
    the defaults. Point `SYMONEURAL_STREAMER_DIR` at real disk if that trade is wrong.

## Open questions for the user

- **Legality and framing.** This box will proxy whatever stream a visitor points it at. The
  module takes no view; the page's copy should. Worth a decision before it is public.
- **Should the Streamer appear on the rack at all when it has no content of its own?** It reports
  `ready` when ffmpeg is present and no session is running, with a detail line saying plainly
  that no channels are stored here. The alternative reading — always `offline` until a visitor
  loads something — is defensible too, but the server genuinely cannot know what is in someone's
  `localStorage`, and a unit that is permanently `offline` while working is its own kind of
  dishonest indicator. Overrule me in `status()` if you disagree; it is six lines.

<!-- generated: do not edit below -->

## Operations — 14

|  | path | what it does |
|---|---|---|
| POST | `/api/streamer/epg` | Programme guide for one channel or a grid of them |
| POST | `/api/streamer/epg/xmltv` | The whole account's guide as XMLTV |
| POST | `/api/streamer/guide/catalogue` | Kinds, groups and group clusters for a channel list |
| POST | `/api/streamer/guide/filter` | Turn a question into a channel filter |
| GET | `/api/streamer/guide/state` | What Guide can do on this box right now |
| POST | `/api/streamer/playlist` | Parse an M3U playlist supplied by URL or pasted text |
| DELETE | `/api/streamer/session/{sid}` | Stop a tuning session |
| GET | `/api/streamer/session/{sid}` | State of one tuning session |
| POST | `/api/streamer/session/{sid}/stop` | Release a session on page unload |
| GET | `/api/streamer/state` | Streamer capacity and live sessions |
| GET | `/api/streamer/stream/{sid}/{name}` | HLS playlist and segments for a session |
| POST | `/api/streamer/tune` | Start a tuning session for one stream URL |
| POST | `/api/streamer/xtream/channels` | Fetch an Xtream Codes catalogue |
| POST | `/api/streamer/xtream/info` | Check an Xtream Codes account |

## Library — no routes, no side effects on import

| file |  |
|---|---|
| `epg.py` | Electronic programme guide for the Streamer. Two sources, one shape out. |
| `safefetch.py` | The one door out. Every outbound byte caused by a visitor-supplied URL goes through here. |
| `sessions.py` | Tuning sessions: one upstream stream, one ffmpeg, a bounded number of both. |
| `xtream.py` | Xtream Codes panel client. Protocol only -- no credential outlives the request. |

## Programs — runnable, or driven by a route

| file |  |
|---|---|
| `m3u.py` | Extended M3U parsing. Two dialects, deliberately kept apart. |

## Documents

- [`symoneural-streamer-scope.md`](docs/symoneural-streamer-scope.md)

<!-- end generated -->
