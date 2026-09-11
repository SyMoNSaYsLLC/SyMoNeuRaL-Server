# Online applications — test pass and audit, 2026-08-17

**Findings, not state.** `.claude/HANDOVER.md` is the one state document and `.claude/CLAUDE.md`
the one rulebook; read this as an argument to evaluate. One fix was made and is described in §4;
everything else here is a report, and several items are explicitly somebody else's file.

**Brief:** *"review all online applications, test them and upgrade them if possible. They seem to
be working but have slight bugs here and there."*

**Short answer: they are working.** 652 backend tests across eleven suites, 26 browser
assertions against the local origin and against production, and a crawl of every reference on
eighteen pages. One genuine defect was found on a public route, diagnosed to its root cause and
fixed with tests (§4). The rest of what looked wrong was either designed, already fixed on disk,
or a fault in my own probe — three of those, recorded in §6 because that is the more useful half.

**Eight other agents were writing this repo during this pass.** Per HANDOVER §0c, files another
agent holds are reported rather than edited. §5 is that list.

---

## 1. Method, so the numbers can be re-taken

| What | How |
|---|---|
| Backend suites | `python3 -m unittest discover -s backend/apps/<app> -p 'test_*.py'`, all eleven |
| Browser, local | `node tests/frontend.mjs` |
| Browser, production | `node tests/frontend.mjs https://symoneural.com` |
| Every route | probed each path in `/openapi.json`, reading the body and not only the status |
| Every reference | a crawler over eighteen pages, both origins, checking each `href`/`src` |

All timings and counts below are **measured on this box**, 2026-08-17 between 13:45 and 14:20.

**One fact that reframes "local versus production", and it is not in HANDOVER:** for anything
under `/api`, *there is only one process*. Caddy reverse-proxies `/api/*` to `127.0.0.1:8800`,
which is the same uvicorn the loopback tests hit — verified by comparing `/api/status` and
`/openapi.json` across both origins, and by the GPU panel reading the same VRAM from each. So the
four states an agent has to keep apart are really **working tree → running API process** for
backend behaviour and **`site/` → deployed webroot** for pages. An API change is invisible to both
origins until a restart; a page change is invisible to production only. Reasoning about
`/api/...` as "local versus live" is what produces the hour-long confusions §0c describes.

---

## 2. Result per surface

Twelve rack units, read from `/api/status`. "Online" below means the surface answers; whether it
has a page of its own is a separate column because those two have been conflated.

| Unit | State | Answers correctly | Note |
|---|---|---|---|
| `chat` | ready | yes | 12-unit rack, GPU panel live |
| `image` | ready | yes | a render decodes end to end in the browser suite |
| `remix` | ready | yes | client of the chat surface, not its own tenant |
| `ravencalc` | ready | **one defect, fixed — §4** | exact SymPy; `x**3/3` verified on the page |
| `train` | ready | yes | never evicted for a page view |
| `asicminer` | offline | by design | fail-closed: needs `SYMONEURAL_ASIC_ENABLED=1` **and** `SYMONEURAL_ASIC_TOKEN` |
| `gpuminer` | ready | yes | control gated: `401` without `SYMONEURAL_MINER_TOKEN`, correct |
| `tuner` | ready | yes | suite caught mid-edit by another agent — §3 |
| `coder` | offline | by design | deliberately has **no HTTP route** at all; see `api.py:1493` |
| `gateway` | offline | by design | needs network + contract configured |
| `guide` | ready | yes | **already in the live stack**; see below |
| `project` | offline | by design | needs `SYMONEURAL_PROJECT_ENABLED=1` and a token |

### The four `503`s are correct, and this is worth stating rather than assuming

Each one is fail-closed *and* actionable — it names the environment variables that would switch
it on and, in `project`'s case, the README to read first:

```
/api/gateway/state      503  "gateway surface is off — set SYMONEURAL_GATEWAY_ENABLED=1, SYMONEURAL_GATEWAY_NETWORK
                              and SYMONEURAL_GATEWAY_CONTRACT, then restart the service"
/api/project/state      503  {"ok":false,"code":"disabled","error":"surface disabled — set
                              SYMONEURAL_PROJECT_ENABLED=1 and SYMONEURAL_PROJECT_TOKEN, and read
                              backend/apps/project/README.md first"}
/api/accounts/me        503  "accounts are not switched on for this box"
/api/asicminer/firmware 503  "the miner surface is disabled on this installation"
```

`GET /api/accounts/status` answering **200** beside `/api/accounts/me` answering 503 looks
inconsistent and is right: `status` is the public "are accounts open here?" question, and it
answers honestly — `{"enabled":false, "note":"this box has not been given a session secret, so
accounts are closed"}`. A gate that cannot be interrogated without authenticating is a gate
nobody can debug.

### SyMoNeuRaL Guide is already in the live stack — nothing to add

Asked directly during this pass. Production `/api/status` returns it as unit 11 of 12:

```json
{"id":"guide","label":"SyMoNeuRaL Guide","slot":"1U","state":"ready","bus":"cpu",
 "href":"/tuner.html","spec":"question → channel filter · CPU",
 "detail":"CPU/stdlib matching — no weights of its own, never takes the GPU lock; the optional
           model pass borrows the chat surface"}
```

`grep Guide` against the deployed `/livestack` **returns nothing**, which is not a contradiction
and is the trap worth knowing: the rack is rendered client-side by `console.js` from
`/api/status`, so no unit label exists in the static HTML for any of the twelve. The browser suite
is the check that means anything here, and it reads `SyMoNeuRaL Guide=CPU` off the rendered bus
plate. Its `href` points at `/tuner.html` because Guide is the tuner's question-to-filter pass
rather than a surface with a page of its own.

Verified working rather than merely present:

```
POST /api/guide/filter  {"question":"live football tonight", channels:[ESPN HD, CNN, SKY SPORTS PL]}
  -> {"match":["football","tonight"], "kind":"live", "source":"fallback", "model_used":false,
      "why":"no model was available, so this matched your own words directly: football, tonight"}
```

Note `source` and `model_used`: the surface says outright when it fell back to plain word
matching instead of the model, which is the §2c-bis lesson (a feature whose happy path never runs
looks fine until someone measures it) encoded as a field. `POST /api/guide/catalogue` refuses with
*"send the channel list to filter; this box stores none"* — the no-storage claim enforced rather
than asserted.

---

## 3. Test results

### Backend — 652 tests, eleven suites

```
accounts     46 OK       asicminer    42 OK       coder        46 OK
cryptominer  72 OK       gateway      57 OK       guide        50 OK
licensing    21 OK       project     102 OK       reinforce    69 -- 1 failure
sigils       24 -- 1 failure           tuner      123 -- 1 failure, 1 error
```

Three reds, and **none of them is a new regression**:

1. **`reinforce`** — the documented `test_alpha_is_twice_rank_everywhere` failure (`48 != 64` for
   `preset='recall'`). HANDOVER §1 says explicitly: ask before choosing which side is wrong. Left
   alone. **A discovery artifact to discount:** `unittest discover` also imports `bench/`,
   `symoneural/` and `tests/` as packages, and those `import cupy`, which is not installed — so
   my run showed *six extra ImportErrors* that are an artifact of the invocation, not code
   faults. Run `test_reinforce.py` directly to see the real picture. Recorded because six
   fabricated errors landing in a report would read as six regressions to the agent who owns
   that file.
2. **`sigils`** — the documented despill boundary (`230 not less than 230`). HANDOVER says settle
   it by deciding what the correct despill output *is*, not by moving the threshold. Nobody held
   this file during the pass, and that is still not permission. Left alone.
3. **`tuner`** — 123 tests where HANDOVER records 121. Another agent was mid-build on the
   EPG work (`backend/apps/streamer/epg.py` did not exist when the running API started). This is a
   snapshot of somebody's work in progress, timestamped, **not a bug report**.

### Browser — the assertion that counts

```
local        26/26   13:55
production   25/26   13:58   -- before Garrett's 14:01 deploy
production   26/26   14:20   -- after it. The two origins now agree.
```

The single production failure, measured before the deploy, was the Live stack section
overflowing its panel:

```
livestack @1855x745   595 / 592     (3px over)
livestack @1301x740   619 / 587     (32px over)
```

against `587/587` and `589/589` locally at the same viewports. Same API process, so this was the
deployed stylesheet being older than `site/symoneural.css` — the pending-deploy state, not a code
defect. **The deploy confirmed the diagnosis**: re-running against production afterwards gives
26/26 with no change to any file. That is exactly why HANDOVER insists the two runs must agree —
the disagreement *was* the finding, and it named its own cause.

### Every reference on every page resolves — both origins

```
local        18 pages, 58 distinct references, 373 checks -- all resolve
production   18 pages, 58 distinct references, 373 checks -- all resolve   (after the 14:01 deploy)
```

This is HANDOVER §0c item 5 ("verify every link works") discharged. Identical reference counts
across the two origins is itself a useful signal — it means the cache-bust stamps agree, i.e.
the webroot and `site/` are in step.

### Seven pages are live and unreachable by clicking

The broken-link check passes on these *because* no reference to them exists to be broken, so it
needs saying separately:

```
/index.html  /image.html  /ravencalc.html  /remix.html  /miner.html  /gateway.html  /sigils.html
```

`/index.html` is deliberate and documented (HANDOVER §5 item 0b — `/` redirects to `/overview`
and the tabbed page survives as a build input). The other six are not documented as deliberate.
A concurrent session reported the same six independently and is adding image, ravencalc and remix
to the nav in `tools/build/build_pages.py`; miner, gateway and sigils belong to other active sessions.
**Not edited here** — three writers in one generator is the clobber CLAUDE.md warns about.

Related trap, confirmed by that session and consistent with everything measured here:
`/sigils.html` answers 200 but **`/sigils` 404s**, because Caddy serves `*.html` off disk with no
config while an extensionless top-level path only reaches FastAPI if `ops/Caddyfile` delegates it.
No page links to an undelegated extensionless path today — the crawl above would have caught it.

---

## 4. The one real defect, and the fix

**`POST /api/ravencalc` returned `500 Internal Server Error` on ordinary mathematics a visitor
can type.** Public, unauthenticated, and the only 5xx found anywhere in the pass.

```
{"expression":"factorial(99999)"}  -> 500   (12 ms -- it fails immediately, so not a slow path)
{"expression":"factorial(3000)"}   -> 500
{"expression":"2**200000"}         -> 500
```

Every *other* bad input was already handled well, which is what made this stand out rather than
look like a general absence of error handling:

```
"x**"                            -> 400  "cannot parse that expression"
""                               -> 422  "request document is not valid"
'__import__("os").system("id")'  -> 400  "expression contains characters this engine does not accept"
"1/0"                            -> 200  zoo          (correct: complex infinity)
```

### Root cause

Not sympy, and not the parser. **CPython 3.11+ refuses to convert an integer wider than 4,300
digits to a string** — `sys.get_int_max_str_digits()`, the CVE-2020-10735 mitigation, because the
conversion is quadratic. It is an *interpreter* limit, so it fires inside sympy's printer, which
is **after** the mathematics has already succeeded:

```
File "sympy/printing/str.py", line 679, in _print_Integer
    return str(expr.p)
ValueError: Exceeds the limit (4300 digits) for integer string conversion
```

`factorial(3000)` is 9,131 digits. The engine computed it exactly and correctly, then died on the
way out. `run_request`'s own docstring is the standard this breaks: *"Raises `RavenCalcError` for
anything a caller can fix … and lets nothing else out silently."*

### What was changed — `backend/apps/ravencalc/ravencalc.py` only

`api.py` already maps `RavenCalcError` to a 400, so the whole fix fits inside the engine and the
coordinate-first file was not touched.

- **`_rendered` refuses, and names both numbers.** All three renderings (`text`, `latex`, `tree`)
  go through the integer printer, so one guard covers them. The refusal says the answer is about
  9,131 digits *and* that this interpreter prints 4,300 — "too wide" alone gives a caller nothing
  to act on.
- **`_evaluate`'s note degrades instead of refusing.** `evaluate` at `x: 3000` with `digits: 20`
  returns a 20-digit Float that prints perfectly; only the exact pre-rounding form behind it is
  too wide. Refusing the whole request there would discard a good answer, so the note says what
  it could not show and how wide it was. A note reading `exact form before rounding:` followed by
  nothing would be the `text-overflow:ellipsis` bug wearing a different hat.
- **The width is estimated from `bit_length`, never measured.** This is the part worth keeping:
  the obvious exact count, `Decimal(n).adjusted() + 1`, **takes 11.8 s on 99999! measured on this
  box**, so counting the digits exactly in order to refuse would hand a visitor the denial of
  service the interpreter's limit exists to prevent. `bit_length` is O(1). It agreed exactly with
  the independent `Decimal` count (both 9,131), and can sit one digit either side near a power of
  ten — which is why every message says **"about"**. An engine whose argument is exactness does
  not quote an estimate as a measurement.
- **Raising the interpreter's limit was the other available fix and is deliberately not taken.**
  `sys.set_int_max_str_digits()` would make the 500 into a 200 and re-open the quadratic cost on
  an unauthenticated public route. A visitor can type `2**200000` as easily as `2+2`.
- **The guard is layered**, matching how `parse` is written: the estimate refuses before the
  printer is asked, and a narrow `except` catches an integer the estimate failed to find rather
  than letting a bare `ValueError` escape.

### Tests — a new file, because this app was the one with none

Every other surface in `backend/apps/` carries a `test_<app>.py`; `ravencalc` did not, which is
plausibly why this survived. `backend/apps/ravencalc/test_ravencalc.py`, **14 tests, all green**,
covering the defect, the note that must survive, and the refusals that were already right so the
new guard cannot loosen them.

**Verified non-vacuous.** With the fix stashed and the tests unchanged: **3 failures and 6
errors**. With it: 14/14. The suite asserts `RavenCalcError` *specifically* rather than
`ValueError`, because `RavenCalcError` subclasses `ValueError` — so `assertRaises(ValueError)`
would have passed before and after the fix and proved nothing. That is the vacuous-assertion trap
§3.0 records three times, met in a fourth costume.

---

## 5. Reported, not touched — other agents hold these files

| Finding | Whose |
|---|---|
| `reinforce` alpha/rank red test — needs Garrett's decision, not an edit | reinforce session |
| `tuner` suite red mid-EPG-build — a work-in-progress snapshot | tuner session |
| miner, gateway, sigils pages have no inbound links | those sessions |
| `sigils` despill boundary — settle the correct output first | unowned, still not licence to guess |

Nothing under `backend/server.py`, `ops/Caddyfile` or `scripts/deploy.sh` was edited: HANDOVER §0c
marks all three coordinate-first, and the ravencalc fix was deliberately shaped to stay out of
`api.py`.

**The generator chain was deliberately not run**, so no idempotency check was performed this pass.
`tools/build_*.py` rewrite files under `site/` and a typography/spacing session was editing that
directory throughout; two writers there lose one of the two edits silently. Whoever next has
`site/` to themselves should run the eleven-generator double-run diff from HANDOVER §6.

---

## 6. Three of my own probes failed on healthy input

HANDOVER §3.0d lists five verification steps that shouted while the system was correct, and notes
that the damage is cumulative — a check that cries wolf trains the reader to skip the block. Three
more, caught before they reached this report:

1. **`data-src="measured"` matched as `src="measured"`.** A regex of `(?:href|src)="([^"]+)"`
   matches the tail of any `data-src` attribute, so the crawler reported five broken links on the
   control board. Those are the provenance tags — `measured` / `vendor` / `projected`, the ones
   CLAUDE.md forbids folding away — and they are data attributes, not references. Fixed with a
   boundary: `(?:^|[\s"'])`.
2. **A `HEAD` probe reported `/docs`, `/livestack` and `/controlboard` as 404** while all three
   answer `GET` with 200. Measure the method a visitor actually uses.
3. **`/sigils.html` 404ing on production** was true when measured at 13:50 and false by 14:01,
   because Garrett deployed in between. Re-measured rather than reported.

The generalisation, which is the same one that file already draws: **a probe is a claim about the
system and needs its own evidence.** Both halves, every time — that it goes red on the real bug
*and* green on healthy input.

---

## 7. The tuner video failure — silent failure fixed, transcode still to build

Reported during this pass: *"you video isnt working"*, then *"ive noticed most the issues are with
the adult live tv"*.

**The tuner is another session's file, and the repair in it is theirs.** This audit did commit a
fix after announcing the exact lines; it collided with better work already in the main checkout
and was reverted, and both commits were later dropped in the rebase onto `aebd444`. See below —
the collision is recorded rather than tidied away, because what the audit got wrong is the useful
part. The transcode built in §7.5 is this branch's own work and sits on top of theirs.

What this section is, then: the measurement that located the failure, plus the NVENC numbers the
transcode work needs. The repair itself belongs to the tuner's own session, which has since
completed the Tuner+Guide merge as well (11 rack units, `tests/frontend.mjs` 28/28 against a
throwaway uvicorn with the change loaded).

### The pipeline is sound; the failure is channel-specific

A working channel, probed by fetching every segment the playlist advertises and running `ffprobe`
on one:

```
AMC (WEST)   6/6 segments served, ~1.1 MB each
             h264 High 1280x720  +  aac LC 48 kHz stereo      segment_s 2.002
```

A failing channel, from `/api/tuner/state` while it was live:

```
STARS EXCLUSIVE: LENA PAUL   state live · vcodec h264 · 87.0 MB in over 5 min · segments 6
                             segment_s 6.54          <- the one number that differs
browser:                     0 frames decoded, player at 0:00, and NO error banner
```

So data flows, the session is healthy, and the video codec is the one codec every browser plays.

### The prime suspect is audio, and it is unpublished

`sessions.py` parses `acodec` and its own comment says it is *"parsed but not published … three
lines cheaper to have ready than to add later"*. `public()` publishes `vcodec` only, and
`build_pages.py`'s `UNPLAYABLE` map is video-only — `{hevc, h265, av1, mpeg2video, vc1}`.

An AC-3 / E-AC-3 / MP2 / DTS soundtrack on an h264 stream reproduces every observable: server
indicators all green, `vcodec` reassuringly `h264`, hls.js unable to append the source buffer,
zero frames decoded, and **a page with nothing to warn about because it never sees the audio
codec**. That is this repo's recurring shape — a diagnosis that exists, is correct, and is
unreachable on the one axis that was left unpublished.

**Still not confirmed against a failing channel**, and the reason is worth recording: a session is
reaped 12 s after the tab goes idle and its temporary directory goes with it, so a probe arriving
later finds nothing. One `ffprobe` on a segment from a failing channel held open ~30 s settles it.

**Fixed — by the peer session that owns the tuner, not here.** `Session.public()` now publishes
`acodec`, under the same argument that makes `vcodec` safe: the value is a token matched against
`AUDIO_CODECS`, never ffmpeg's text, so a hostile stream cannot push arbitrary content or a
URL-embedded credential into the public document.

This audit independently reached the same diagnosis and committed the same fix, twenty minutes
later and worse, then reverted it. **Neither commit survives on this branch** — the pair cancelled
to zero content and would have conflicted twice against a `sessions.py` the owning session had
meanwhile rewritten, so both were dropped when this work was rebased onto `aebd444`. The reasoning
is preserved here, in prose, which is where it was always doing the work; a net-zero commit pair
carried in history to make a point is a worse record than a paragraph that explains it. It is
worth keeping because it is a case of the audit itself nearly shipping the thing the repo's
honesty rules exist to prevent:

- The peer's page **asks the browser** — `MediaSource.isTypeSupported()` against both `video/mp2t`
  and fMP4, since the box serves TS and hls.js remuxes. This audit's version hardcoded
  `UNPLAYABLE_AUDIO = {ac3, eac3, mp2, dts, truehd}`.
- **That table was already wrong about MP2.** Measured on Chrome 151: h264, aac, mp2 and mp3 are
  accepted; hevc, mpeg2video, vc1, av1, vp9, ac3, eac3, dts and truehd are refused. The static
  list would have told visitors that channels which play perfectly cannot play. A false warning on
  a working channel is a decorative status indicator by another route, and it teaches people to
  ignore the banner that is telling the truth.
- The peer found the **larger bug underneath**: `play()` tested
  `video.canPlayType('application/vnd.apple.mpegurl')` first, and Chrome returns the truthy string
  `'maybe'`, so every Chrome visitor took the native path and the whole hls.js block was dead code
  — no `liveSyncDurationCount: 1` (31 s to first frame instead of 2.5 s), no fatal-error handler,
  no level or throughput readings. The statistics panel reading *"the browser's own HLS"* with
  bitrate at `-` is what exposed it. A correct codec warning layered on a player silently running
  the wrong path would have been a fix that measured nothing.
- Also theirs: the codec panel is now sticky, because the fatal hls.js error an undecodable stream
  *causes* was overwriting *"This stream is H.265 / HEVC"* with *"Playback stopped — could not
  fetch the next part"* — replacing the cause with the symptom.

The honest status line: **the silent-failure mode is fixed** — a channel that cannot play now says
why. Whether the specific adult channels Garrett reported are the AC-3 case is what the next
failing session confirms for free, now that the field is published.

The generalisable lesson, which is the same one §6 of this document is about: **this audit's three
false findings and this reverted commit all came from reasoning about a system instead of
measuring it.** A hardcoded codec table is a claim about a browser, and the browser was available
to ask the whole time.

### GPU transcode — approved, and the hardware says it need not take the lock

Garrett was given the trade-off explicitly and chose full GPU transcode over audio-only-on-CPU.
Capability is **measured present**, with nothing to build:

```
encode   h264_nvenc  hevc_nvenc  av1_nvenc
decode   h264_cuvid  hevc_cuvid  mpeg2_cuvid  vc1_cuvid  vp9_cuvid
```

The decode list is the useful half — `hevc_cuvid`, `mpeg2_cuvid` and `vc1_cuvid` are precisely the
codecs the page's `UNPLAYABLE` map exists to apologise for.

**The architectural finding: NVENC and NVDEC are dedicated ASIC blocks, not CUDA compute.**
Measured while the `image` surface held the governor lock with the GPU at 67% compute
utilisation, `nvidia-smi` reported **encoder 0%, decoder 0%**. Those units are idle and
independent of what the governor arbitrates. A transcoding tuner therefore needs a **VRAM budget**
(a few hundred MB per 1080p stream), not exclusive possession of the card — so the "a stream holds
its lease for its whole lifetime" objection, which is real for the miner, probably does not apply
here. Taking the exclusive lock for a transcode would serialise video behind model inference for
no hardware reason, which is the opposite of why "the tuner never takes the lock" was right.

It does still falsify the page's *"Tuner does not use the GPU"*. The honest replacement is that it
uses the **video engine**, not the compute the models share — which is both true and a better
claim.

#### The throughput numbers — taken 14:41, card otherwise idle, under a governor lease

Everything below is **measured** on this box (RTX 5070 Ti, 16303 MiB), not projected. The earlier
revision of this section deferred these deliberately because the card was busy with another
session's image work and a contended measurement is a contaminated one. It was free at 14:40 —
14792 MiB free, encoder and decoder both at 0% — and the table below is from that run.

**How to tell a contaminated run, because one happened.** The VRAM column is a delta of
*whole-card* memory, not per-process, so another tenant allocating mid-run is billed to whichever
row is executing. Re-running this at 14:51 with ~8 GB already resident reported `all-CPU libx264
veryfast … VRAM +6576 MiB`, which is impossible — libx264 never touches the card. That row is the
canary: **if the pure-CPU case shows more than a few MiB, discard the entire run.** Holding a
governor lease does not prevent this, because a surface can be resident without holding the lock.
The clean run's pure-CPU rows read +8 MiB and +0 MiB, which is what a trustworthy run looks like.

**Engine separation, confirmed directly rather than inferred.** Sampled five times during a live
GPU transcode:

```
GPU compute  2%      encoder  50%      decoder  28-31%
```

The earlier finding stands and is now measured from the other direction: a transcode drives the
video engines hard while leaving compute essentially untouched. It does not contend with model
inference for anything except VRAM.

**Video transcode.** The synthetic source is `testsrc2` at 1080p25, which is high-entropy and
near-worst-case for rate control — read it as a **floor on throughput, not a prediction** for any
particular channel. The real source is six consecutive 2 s segments pulled from a live 720p
channel earlier the same day, concatenated: real broadcast bytes.

| Case | Source | Throughput | VRAM |
|---|---|---|---|
| `hevc_cuvid` → `h264_nvenc` | synthetic 1080p25 | **19.4× realtime** | +515 MiB |
| `hevc_cuvid` → `h264_nvenc`, audio copied | synthetic 1080p25 | 21.1× realtime | +515 MiB |
| all-CPU `libx264 veryfast` | synthetic 1080p25 | 11.5× realtime | +8 MiB |
| `h264_cuvid` → `h264_nvenc` | real 720p IPTV | **17.0× realtime** | +364 MiB |
| CPU decode → `h264_nvenc` | real 720p IPTV | 17.1× realtime | +290 MiB |
| all-CPU `libx264 veryfast` | real 720p IPTV | 13.4× realtime | +0 MiB |

Two things fall out. Hardware decode buys almost nothing at 720p — 17.0× against 17.1× is noise,
so the encoder is the bottleneck and `-hwaccel cuda` is not the load-bearing flag. And all-CPU
`libx264 veryfast` clears realtime by more than 10×, so the GPU is a **CPU-saving** choice here,
not an enabling one; the box could serve two transcodes on CPU alone if it had to.

**Concurrency.** The ceiling matters more than the single-stream figure:

```
2 concurrent HEVC->H.264   35.8x aggregate realtime   ~512 MiB each
4 concurrent HEVC->H.264   39.8x aggregate realtime   ~513 MiB each
```

NVENC saturates near **40× realtime aggregate**. `MAX_SESSIONS = 2` needs 2× and has 35.8× — about
18× headroom. Per-session VRAM is flat at ~515 MiB regardless of how many run, so the budget is
linear and the two-session ceiling costs about **1 GiB**.

#### This changes the design Garrett approved, and the change should be surfaced

Garrett chose "full GPU transcode" over "audio-only on CPU" when neither option had a number
attached. Now they do, and the audio-only repair turns out to cost **nothing measurable**:

```
-c:v copy -c:a aac    34.4x realtime (real 720p)    92x (synthetic)    +0 MiB VRAM, CPU only
```

If the dominant failure is AC-3 — which the evidence in this section supports — then the correct
repair is remuxing the soundtrack and copying the picture through untouched. No GPU, no governor
lease, no VRAM budget, and no need to weaken `_spawn`'s stream-copy guarantee for the majority of
channels. The honest design is two-tier:

| Failure | Repair | Cost |
|---|---|---|
| soundtrack undecodable, picture fine | `-c:v copy -c:a aac` | CPU, ~34× realtime, 0 MiB |
| picture undecodable (HEVC, MPEG-2, VC-1) | `hevc_cuvid` → `h264_nvenc` | ~19× realtime, ~515 MiB |

This is not a reversal of Garrett's decision — the GPU path is still built, and it is still the
right answer for the HEVC and MPEG-2 channels the `UNPLAYABLE` map exists for. It is a narrowing:
**reserve the GPU for the case that actually needs it**, because the common case does not.

**Not yet implemented.** One design constraint for whoever does it: codecs are only known *after*
ffmpeg starts and prints them, so `_spawn`'s unconditional `-c copy` cannot choose up front — the
repair needs detect-then-respawn. And `_spawn`'s comment currently promises *"it never quietly
re-encodes, because the GPU belongs to inference and the CPU has a site to serve"*. That comment
has to be rewritten with the measurements above as its justification, not quietly contradicted.

### yuki-iptv and VLC — references to read, not code to port

Asked for during this pass. Both were checked, because the answer changes the design:

| Reference | Licence | How it plays video |
|---|---|---|
| `references/IPTV/yuki-iptv/` | **GPLv3** (Astroncia / yuki-chan-nya) | **libmpv** — 186 mpv references in `yuki-copy.py` |
| `references/IPTV/vlc-master/` | **GPLv2** | already rejected, HANDOVER §2c-bis and `LICENSES.md` |

They play everything because they are **native players with a complete codec set** — mpv decodes
HEVC, AC-3, MPEG-2 without asking. A browser cannot copy that, so there is no code to port; and
porting it into `site/` would be the copyleft problem the VLC decision already turned down. What
transfers is the approach, and it is the same conclusion as the transcode work: stop assuming the
browser can decode the stream, detect what arrived, and convert the rest.

### One housekeeping leak

**165 empty `/tmp/tuner-run-*` directories.** Segment contents are cleaned when a session is
reaped; the directory itself is not. Harmless today, unbounded over time.

---

## 8. Reproducing this pass

```bash
# backend, the eleven packages. `-t .` is not optional -- without it, discover treats the app
# directory as top-level, every relative-import test module fails to load, and unittest reports
# one ERROR while all of that module's tests silently do not run. That is how the tuner read
# "126 tests, 1 error" here when the truth is 159 and green.
for a in accounts asicminer coder cryptominer gateway guide licensing project reinforce sigils tuner; do
  printf '%-14s ' "$a"
  python3 -m unittest discover -s backend/apps/$a -t . -p 'test_*.py' 2>&1 | tail -3 | tr '\n' ' '; echo
done

# RavenCalc takes the plain form, and must: it has no __init__.py because api.py:70 puts it on
# sys.path as a flat module. `-t .` fails on it with "Start directory is not importable".
python3 -m unittest discover -s backend/apps/ravencalc -p 'test_*.py'

# browser, both origins -- these must agree
node tests/frontend.mjs
node tests/frontend.mjs https://symoneural.com

# ...but from a git worktree that fails first with MODULE_NOT_FOUND on 'playwright'.
# frontend.mjs resolves it out of contrib/, which a worktree does not get a copy of, so
# symlink the real one in. contrib/ is gitignored, so this pollutes nothing.
ln -s /home/google/Symoneural/contrib contrib

# the transcode numbers in section 7. Takes a governor lease and releases it even on crash;
# runs in about two minutes. Re-take them on a card that is otherwise idle -- a contended
# measurement is a contaminated one, which is why they were not taken on the first attempt.
scripts/gpu-governor.sh with tuner -- tools/bench/bench_nvenc.sh
```

`bench_nvenc.sh` measures its real-source cases against `seg-*.ts` files sitting beside it, which
are live segments captured from a channel and are deliberately not committed. Without them it
reports the synthetic cases only and says so; §7's real-720p rows came from six consecutive
segments pulled off a working channel with `tools/audit/probe_tuner_stream.sh`.

The link/orphan crawler used here was a scratch probe and was not kept; it is ~60 lines of
`fetch` over the eighteen-page list, and §6 item 1 is the only subtlety in writing another.
Worth promoting into `tests/` if link rot becomes a recurring theme, in which case fold the
orphan check in with it — the broken-link pass is silent about orphans by construction.

---

## 9. State at close, and what only Garrett can do

Re-verified on 2026-08-17 after rebasing onto `aebd444`, with a **corrected harness** — see the
warning below, because the first sweep of this audit under-counted by 33 tests and invented a
failure that did not exist.

### Test sweep — 598 tests, 10 of 12 suites green

| Suite | Tests | Result |
|---|---|---|
| accounts | 46 | **OK** |
| asicminer | 42 | OK (3 skipped) |
| coder | 46 | **OK** |
| cryptominer | 72 | **OK** |
| gateway | 57 | **OK** |
| guide | 50 | **OK** |
| licensing | 21 | **OK** |
| project | 102 | **OK** |
| ravencalc | 14 | **OK** |
| tuner | **159** | **OK** |
| sigils | 24 | 1 error — another session's live work |
| reinforce | 69 | 1 failure, 6 loader stubs — both explained below |
| `node tests/frontend.mjs` — local `:8800` | 26 | **26/26** |
| `node tests/frontend.mjs https://symoneural.com` | 26 | **26/26** |

### The sweep command was wrong, and wrong in the direction that hides things

Every earlier sweep in this document ran `unittest discover -s backend/apps/<app>` with no `-t`.
That makes discover treat the app directory as the top-level package, so **any test module using a
relative import fails to load** — and unittest reports that as a single `ERROR` while every test
in that module silently does not run. The tuner is the case that matters: `test_epg.py` opens with
`from . import epg`, so the old command reported

```
tuner   Ran 126 tests   FAILED (errors=1)
```

when the truth, with `-t .`, is **`Ran 159 tests ... OK`**. A third of the suite was invisible and
the visible part looked broken. This is the more dangerous of the two failure modes: a red line
gets investigated, whereas 33 absent tests look exactly like a suite that is smaller than it is.

`ravencalc` needs the *opposite* treatment and is not an inconsistency to fix: it has no
`__init__.py` because `api.py:70` puts it on `sys.path` as a flat module, with the reason stated
there. `-t .` fails on it outright with *"Start directory is not importable"*. Eleven packages take
`-t .`; RavenCalc takes the plain form. §8 carries both.

**None of the failures is a regression from this audit**, and each was checked rather than
assumed:

- **tuner** — `test_the_wait_covers_a_realistically_paced_stream`, the stale
  `TUNE_WAIT_SECONDS < IDLE_TIMEOUT + 1` assertion described in §7. It went red *in this branch
  only*, because reverting the acodec commit reverted the fix for it along with everything else.

  **Resolved on `main`, and not by this branch.** This audit did briefly re-apply its own fix,
  reasoning that handing over a branch which merges red unless somebody else's *uncommitted*
  work lands first is not a real plan — an ordering constraint that exists only in a document is
  not a constraint. That reasoning was right, and the fix was still dropped in the rebase,
  because the owning session had already done it better. They did not delete the assertion; they
  replaced it with `test_the_wait_keeps_the_session_alive_while_it_waits`, which asserts the
  *mechanism* — that the wait loop touches the session repeatedly, so the reaper never sees it go
  quiet — and which found the root cause this audit missed: `979c3dc` raised the wait to 25 s and
  dropped the idle timeout 45 → 12 s in one change, so the assertion was false the day it was
  written. Asserting the mechanism beats asserting the arithmetic, and deleting beats neither.
- **sigils** — now one error, not two failures: the despill test went green on `main` while this
  branch was being rebased. What remains is
  `test_a_whole_sticker_end_to_end_without_a_gpu`, a `FileNotFoundError` on a
  `backend/output/sigil-raw-*.png` that was never written, followed by an `UnboundLocalError` on
  `doc` in the teardown path — the second masking the first. The sticker surface is under active
  development by another session. This branch contains no commit touching `backend/apps/sigils`.
- **reinforce** — the six errors are a discovery artifact, not tests: `unittest discover` imports
  `bench/`, `symoneural/` and `tests/`, which `import cupy`, which is not installed. The one real
  failure is `test_preflight_refuses_the_corpus_as_a_dataset`, and it is worth reading carefully
  because of what it looks like.

### The corpus guard is intact — the failing test says otherwise and is wrong

`test_preflight_refuses_the_corpus_as_a_dataset` asserts `reason == "dataset_protected"` and gets
`"unknown_model"`. That reads like the protection on `training/corpus.jsonl` — the artefact
`CLAUDE.md` says must never leave this box — has been removed. **It has not.** Verified directly
rather than reasoned about:

```
dataset_guard.admit('training/corpus.jsonl')     -> Refused(code='protected')
dataset_guard.admit('training/build_dataset.py') -> Refused(code='protected')
registry.catalogue()                             -> []      <- no weights on this box
```

`jobs.preflight()` checks the model at `jobs.py:390` and the dataset at `:428`. With no model
weights fetched, the model check short-circuits first and the dataset check is never reached — so
the test fails on an **environment** difference, not a missing guard. `jobs.start()` additionally
calls `dataset_guard.admit()` a second time at `:465` under the comment *"admitted again; the
guard is not optional"*, so there is no path that reads the corpus even if preflight were skipped
entirely. The test would be more honest asserting against the guard directly, or skipping when
`registry.catalogue()` is empty, the way the GGUF test above it already skips.

### What only Garrett can do

1. **Merge `tuner-transcode`.** Branch `worktree-online-apps-audit` is superseded: its eight
   commits were rebased onto `aebd444` as five, dropping the acodec commit, its revert and the
   stale-deadline fix for the reasons given above. What remains is the RavenCalc fix, the
   documentation, the NVENC measurements and `bench_nvenc.sh` — plus the two-tier transcode in
   §7.5, which is built on top of the tuner session's committed work rather than beside it.
2. **~~Commit the tuner session's work.~~ Done** — landed as `4b23f85` (guide grid,
   `site/tuner-watch.html`, the statistics panel, the Tuner+Guide rack merge) and `aebd444` (a
   review pass: the deadline test, watch-page `pageerror` coverage, a handoff slot-leak fix).
   This was the least durable valuable thing on the box and is now the base this branch builds on.
3. **`sudo systemctl restart symoneural-api`** *and* **`sudo scripts/deploy.sh --prune`.** Nothing
   below is live: the running `:8800` process predates all of today's tuner work and still reports
   12 rack units rather than the merged 11. Confirmed still broken live at 14:58:

   ```
   POST /api/ravencalc {"expression": "factorial(99999)"}
     127.0.0.1:8800      HTTP 500
     symoneural.com      HTTP 500
   ```

   With the branch's fix loaded the same request raises `RavenCalcError`, which the handler at
   `api.py:1900` turns into a **400 naming the reason** — *"the exact answer is too wide for this
   engine to print"* — while `factorial(20)` still returns its exact answer. The rack also still
   reports 12 units rather than the merged 11 for the same reason.

### The transcode — built, in `adec23d`

Designed and measured in §7, unblocked by `aebd444`, and now implemented in both tiers. A session
still starts with `-c copy` and most channels never leave that path; when the input dump names
codecs the browser has been measured unable to decode, ffmpeg is respawned once with the cheapest
repair — `-c:v copy -c:a aac` for a bad soundtrack, `h264_nvenc` (or `libx264`) for a bad picture.
`public()["repair"]` names what was re-encoded. `SYMONEURAL_TUNER_REPAIR=off` restores the previous
behaviour exactly. 17 new tests, 176 in the suite, green.

The allow-list polarity is the load-bearing decision: `PLAYABLE_VIDEO` / `PLAYABLE_AUDIO` list what
**does** play, so an unrecognised codec gets repaired rather than silently passed. A deny-list is
wrong in the direction that breaks working channels — which is exactly how `mp2` nearly shipped as
unplayable — and an allow-list is wrong only in the direction of a needless transcode.

Two bugs the tests found that reading the code did not:

- `ts_sync_offset` returns **-1** when it cannot lock, and the first draft sliced with it unguarded.
  `chunk[-1:]` discards all but the final byte — a repair that destroys the stream it repairs.
- The repair is decided by the stderr reader but applied by the pump thread, since only the pump may
  touch `proc.stdin`, so it lands on the **next write**. Given a 576 KB file, ffmpeg drains it all
  before it finishes announcing codecs and the plan is made with no writes left — measured, with
  `bytes_in` equal to the file size at that instant. Harmless in production, where a channel never
  stops mid-broadcast, but it means the fixture has to be a continuous feeder to be honest.

#### One decision that is Garrett's, not an agent's

**The video tier does not take a `gpu-governor.sh` lease**, and `CLAUDE.md` says everything touching
the GPU goes through the governor. This is a deliberate exception, argued from two measurements, and
it should either be ratified in `CLAUDE.md` or overruled — not left as an undocumented divergence:

- A tuner session lives as long as somebody watches, so a lease here would be held **for a process
  lifetime**, which is the one thing the governor's own rules forbid, and it would lock the CLI and
  every model out until the acquire timeout.
- NVENC does not contend for what the governor arbitrates: encoder 50% while compute read 2%, and
  encoder 0% while inference held compute at 67%.

What it does contend for is VRAM, so that is checked instead — below `VRAM_FLOOR_MIB` (1024 MiB by
default) free, the tuner takes the CPU path rather than the last of the card. Overruling this costs
the video tier, not the audio one: `SYMONEURAL_TUNER_REPAIR=cpu` keeps every channel playable at a
measured 13.4× realtime and never touches the GPU.

#### Not done: the page copy

`site/tuner-watch.html` still says the tuner does not use the GPU, and its codec warning does not
yet read `repair` — so a repaired channel will play while the page still explains that it cannot.
The backend publishes what the page needs; wiring it up is a `tools/build/build_pages.py` change, which
means it also needs `build_cachebust.py` after it, and it is the next piece of work rather than a
finished one.
