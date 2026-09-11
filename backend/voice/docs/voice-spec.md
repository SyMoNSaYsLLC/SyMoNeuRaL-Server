# SyMoNeuRaL Voice — design brief, with the input half measured

**HANDOVER §5 item 12.** Text-to-speech, speech-to-text and speech-to-speech, wired into
SyMoNeuRaL Chat. Asked for by Garrett 2026-08-17, alongside item 13 (Stickers).

**Status: proposed. Nothing is built.** There is no `backend/apps/voice/`, no route, no page
and no rack unit. This file is the spec the handover asks for before code, and it exists
because the central question — *does a voice surface have to queue behind the GPU?* — is now
answered by measurement rather than by argument. **It does not.**

> **Written against a moving tree, 2026-08-17 ~15:25.** Thirteen agent sessions were writing
> this repo while this was measured. `backend/server.py` (2,167 lines), `tools/build/build_pages.py`,
> `site/tuner.html`, `site/tuner-watch.html` and `site/project.html` were all in flight, so
> **every `file:line` below must be re-grepped before it is trusted.** Nothing outside
> `backend/authority/docs/` was touched to produce this. The load average during every measurement was
> **6.5–7.5 on 20 CPUs**, which biases every timing *slow* — these are ceilings, not best
> cases, and a quiet box will beat them.

---

## 0. The groundwork already on disk was not built by this spec's author

Somebody prepared the ASR half at ~14:03 today and their session is no longer in
`ListAgents`. Recorded so the next reader does not mistake it for their own or for mine:

| Artefact | When | Note |
|---|---|---|
| `contrib/whisper.cpp` @ `1fe009c` | 14:03 | cloned **and built** — `build/bin/whisper-cli`, `whisper-server`, `whisper-bench` all present. Gitignored (`.gitignore:41`). |
| `models/whisper/symoneural-listen-base-en.bin` | 14:04 | 141 MB, the real `base.en` weights. Gitignored (`.gitignore:2`). |
| `models/licenses/whisper.cpp.LICENSE.txt` | 14:46 | MIT, "Copyright (c) 2023-2026 The ggml authors". |
| `models/licenses/openai-whisper.LICENSE.txt` | 14:46 | the model's own licence. |

**The single most important byte in all of it:** `contrib/whisper.cpp/build/CMakeCache.txt`
carries `GGML_CUDA:BOOL=OFF`. The ASR engine that exists on this box is a **CPU** build.

---

## 1. The design question the handover poses, and its answer

§5 item 12 asks whether Voice is *(a)* CPU inference at both ends, taking the GPU lock never,
or *(b)* a third governor surface with an ASR → *evict* → chat → *evict* → TTS round trip and
the governor's 1.5 GB VRAM drain wait between each stage.

**It is (a), and the branch that made (b) plausible is already closed.** Measured on this
machine, `base.en`, 8 threads:

| Reading | Measured | Consequence |
|---|---|---|
| Peak RSS of a transcription | **284 MiB** | System RAM is 96 GiB. This is not a VRAM tenant and never contends with chat's ~5 GB or image's ~7 GB. |
| VRAM used | **0** | `GGML_CUDA=OFF`. There is nothing for `gpu-governor.sh` to arbitrate. |
| A 3-second utterance, end to end | **579 ms** | Faster than the governor's *drain wait alone* would be. |

So Voice takes the lock **never**, for the same reason RavenCalc does not: it is CPU work, and
that is precisely what lets it overlap a chat generation instead of queueing behind it.
`.claude/CLAUDE.md` names RavenCalc as the precedent; this is the second surface to use it, and
the reasoning is identical.

**Do not implement option (b).** It was the honest alternative when nobody had numbers. The
numbers exist now and they retire it.

## 2. What was measured

Reproduce any of it:

```bash
W=contrib/whisper.cpp/build/bin/whisper-cli
M=models/whisper/symoneural-listen-base-en.bin
$W -m $M -t 8 -nt -f contrib/whisper.cpp/samples/jfk.wav
```

### 2.1 Latency, by utterance length — **measured**

Clips cut from `contrib/whisper.cpp/samples/jfk.wav` (11 s) with ffmpeg; the 22 s and 33 s
cases are that sample repeated. `-t 8`, wall clock is `date +%s.%N` around the process, the
rest is `whisper-cli`'s own `whisper_print_timings`.

| Audio | Wall | model load | encode | decode | batched | whisper's own total |
|---|---|---|---|---|---|---|
| 3 s | **0.608 s** | 77 ms | 397 ms | 5.4 ms | 57 ms | 579 ms |
| 6 s | **0.617 s** | 73 ms | 353 ms | 4.5 ms | 104 ms | 590 ms |
| 11 s | **0.790 s** | 71 ms | 414 ms | 5.1 ms | 198 ms | 764 ms |
| 22 s | **1.015 s** | 71 ms | 381 ms | 10.7 ms | 398 ms | 984 ms |
| 33 s | **1.808 s** | 73 ms | 841 ms | 24.3 ms | 644 ms | 1,775 ms |

### 2.2 The 30-second window is the shape of the whole route — **measured**

Read the `encode` column: it is **flat at 353–414 ms from 3 s through 22 s, and then doubles
to 841 ms at 33 s.** Whisper pads its input to a fixed 30-second window and encodes the window,
not the speech. Three things follow, and they are API design rather than trivia:

- **An utterance under 30 s costs a flat ~0.6 s.** A 3-second "what's the VRAM at?" is not
  meaningfully cheaper than a 20-second question.
- **Cost steps at every 30 s boundary**, so the route should chunk on that boundary and a
  progress indicator should count windows, not seconds.
- **The page must never promise per-second scaling.** "About half a second for anything you
  can say in one breath" is both true and measured; "1/9th of realtime" is a number that stops
  being true the moment somebody talks for 31 seconds.

### 2.3 Threads — **measured**

Same 3 s clip: `-t 4` → 0.890/0.946/0.890 s. `-t 8` → 0.607/0.601/0.591 s. Eight threads is
~1.5× four and there are 20 CPUs, so 8 is the right default for a serving route with room for
two concurrent requests. See §4.4 — this number is a concurrency decision, not a tuning knob.

### 2.4 Browser audio must be transcoded, and that is not optional — **measured**

`MediaRecorder` in Chrome produces **WebM/Opus**. What this build actually reads:

| Handed to `whisper-cli` | Exit code | Transcript |
|---|---|---|
| `.wav` (16 kHz mono) | 0 | 47 bytes — correct |
| `.mp3` | 0 | 47 bytes — correct |
| `.flac` | 0 | 47 bytes — correct |
| `.ogg` (Opus) | **0** | **0 bytes** |
| `.webm` (Opus) | **0** | **0 bytes** |

`ffmpeg -i in.webm -ar 16000 -ac 1 out.wav` costs **66–72 ms** over five runs. That is the
whole fix and it belongs in the route unconditionally.

### 2.5 TWO TRAPS, both of which produce a working-looking empty answer

**`whisper-cli` exits 0 on a file it could not read.** Re-checked after the table above was
first written, because the run that produced it read `$?` through a `tr`/`sed` pipeline and so
was reporting `sed`'s status rather than whisper's: invoked directly, with no pipeline, all five
formats — including both that transcribe nothing — exit **0**. The claim stands as written.
stderr says
`read_audio_data: failed to read audio data` / `error: failed to read audio file`, and the exit
code is still **0**. A route that shells out and checks `returncode` sees success and returns an
empty transcript. The visitor hears their question vanish. **Check for empty stdout and treat
it as failure**, and surface what stderr said rather than an empty string — this repo's own
history is a list of features that looked fine because the failure path was silent.

**The usage banner lies about ogg for this build.** `whisper-cli --help` prints
`supported audio formats: flac, mp3, ogg, wav`, and ogg/Opus does not work — the decoder is
miniaudio, which has no Opus path (`read_audio_data: trying to decode with miniaudio`, then
failure). An implementer who trusts the banner will send Opus straight through, get exit 0 and
an empty string, and go looking for the bug in the microphone. It is not in the microphone.

### 2.6 Residency buys 75 ms, and costs a process to supervise — **measured**

`whisper-server` is built and available, so keeping the model resident is a real option. Model
load is **71–77 ms** across all five runs above. That is what residency buys.

**Recommendation: shell out to `whisper-cli` per request.** 75 ms does not justify a second
long-lived process with its own port, its own supervision, its own resident marker in `run/`
and its own failure mode when it dies while FastAPI is up. Revisit only if a measurement shows
the load is not amortised — and if it is ever revisited, note that the 141 MB file will be in
the page cache after the first call, which is part of why 75 ms is as low as it is.

## 3. What is NOT measured, and why

**The TTS half.** Nothing that speaks is installed on this box: no `piper`, no `espeak-ng`, no
`espeak`, no `festival`, no `flite`, and the system interpreter has no `onnxruntime`,
`torchaudio` or `soundfile`. `arecord` is present; nothing else is.

**Piper was deliberately not installed.** It needs its own venv (`.claude/CLAUDE.md`: the
serving path is the system interpreter and must not be `pip install`ed into; anything that
conflicts gets an isolated venv), and downloading a package plus a voice model is a change to
the machine that belongs to Garrett rather than to an agent working an unattended queue. It is
one word away. The command that closes the gap:

```bash
# The venv goes beside the package, where backend/apps/asicminer/.venv already lives. An
# earlier revision of this line said `voice/.venv` at the repo root; that would have been a
# second convention for the same thing. backend/apps/voice/tts.py holds the corrected path.
cd backend/apps/voice && python3 -m venv .venv && .venv/bin/pip install piper-tts
# then, and this is the measurement that matters:
#   time .venv/bin/piper -m <voice>.onnx -f out.wav <<< "a one-sentence answer"
# report: wall clock, peak RSS, and audio seconds produced per second of compute.
```

Two things to settle at the same time, both cheap if done then and expensive if done later:

- **The voice model's licence** must go in `models/licenses/` like every other weight
  on this box. Piper's voices are not uniformly licensed — check the specific voice, do not
  assume it inherits Piper's own terms.
- **`onnxruntime` is already in play here.** `models/licenses/onnxruntime.LICENSE.txt`
  and `rembg`/`u2net` were recorded at 14:46 for the Stickers work (item 13). Coordinate rather
  than adding a second copy of the same dependency under a different owner.

**Chat's time-to-first-token.** The handover records **80–92 tok/s measured** with the persona
adapter, which is throughput, not first-token latency — and TTFT is what a spoken turn feels
like. It was not measured here because measuring it means taking the GPU lock while a dozen
peer sessions are live, and this spec is not worth evicting somebody's work for. Measure it
with the governor, on a quiet box, before any latency figure goes on a page.

## 4. The design that follows from the numbers

### 4.1 Two new routes, and the existing chat route untouched

```
POST /api/voice/transcribe    multipart audio -> {"text": "...", "windows": N, "ms": N}
POST /api/voice/speak         {"text": "..."}  -> audio/wav
```

Speech-to-speech is `transcribe` → **the existing `/api/chat`** → `speak`. It is not a third
route and it is not an audio-native model. `backend/server.py:1769` already streams SSE and
already accepts a `history` array; a voice turn is a client-side composition of three calls,
which is also what makes it usable by something that is not this site (see §4.5).

**The one thing a voice path must not become.** `Turn.role` is
`Literal["user", "assistant"]` (`backend/server.py:246`, used at `:259`) *on purpose* — it is what
stops a client injecting a `system` turn and overriding the trained persona and the pricing
refusal. That refusal is trained into `training/corpus.jsonl`, not prompted. Any voice route
that assembles a chat request must go through the same model, with the same `Literal`, and must
not grow a parameter that reaches the system prompt.

### 4.2 The rack unit is `bus="cpu"`

Like RavenCalc (`backend/server.py:1477`). The honest `spec` line is something close to
*"whisper.cpp base.en on the CPU — never waits for the GPU"*, and the honest `state` is `ready`
only while the binary and the weights are both present; absent either, it is `offline` and says
which is missing. No decorative indicator: if the surface reports a latency, it must be one it
measured on the last request, not a constant from this file.

### 4.3 The gate, because a transcribe endpoint is CPU a stranger can spend

`/api/*` is wholly delegated to FastAPI, so a route is a public route. Follow the pattern that
already exists in this repo (`backend/apps/asicminer/__init__.py`): `SYMONEURAL_VOICE_ENABLED=1` **and**
`SYMONEURAL_VOICE_TOKEN`, both required, `hmac.compare_digest`, 503 with a body naming both variables
when off. Fails closed on a public box.

Add a `voice` entry to `_RATE_SUGGESTED` (`backend/server.py:169`) and use
`throttled_for("voice")` (`:504`). The comment above that table is worth re-reading first: on
one GPU a rate limit never bought throughput because the queue rations the card. **Voice is the
first surface where that reasoning does not apply** — it is CPU work with no queue in front of
it, so the bucket is the only backstop there is. A suggested starting pair, by the same logic
the existing rows use: `"voice": (60, 900)` — ~0.6 s of CPU each, an order of magnitude cheaper
than image, an order dearer than RavenCalc.

**Read the two halves of that as two separate jobs, or you will ship an unmetered endpoint.**
The comment says of `_RATE_SUGGESTED` that "nothing reads it", and that is true of the *numbers*
but not of the *keys*: `LIMITS = {name: _rate_for(name) for name in _RATE_SUGGESTED}` (`:189`)
iterates them, so a surface absent from the table never has its environment variable read and
can never be metered at all — that is why the row is required. What the row does not do is set a
budget. `_rate_for` returns `(0, 0)` when `SYMONEURAL_RATE_VOICE` is unset, the `_limiters`
comprehension at `:477` drops any pair that is not `> 0` on both, and `check_rate` treats a
missing limiter as **unmetered** (deliberately — the comment there explains that building a
zero-capacity bucket instead would deny every request forever). So the pair above is
documentation of an intended budget; the operative change is `SYMONEURAL_RATE_VOICE=60/900` in
`ops/units/symoneural-api.service`, and that needs a service restart, which is Garrett's to run.
Adding the row and stopping there gives you a route that throttles nothing and reports no error.

### 4.4 Concurrency: a blocking subprocess on an async loop, and 8 threads twice over

`whisper-cli` is a blocking subprocess and uvicorn is single-threaded per worker, so it must go
through `asyncio.to_thread` — the same shape RavenCalc already uses at `backend/server.py:1795`.

And it needs a small semaphore. At `-t 8`, two concurrent transcriptions are 16 threads of 20,
and a third makes every one of them slower than serving them in turn would have been. **Cap
concurrency at 2 and queue the rest**; a 0.6 s job that waits 0.6 s is still a good answer, and
a box that thrashes its cores also slows down the chat generation the visitor is waiting on.

### 4.5 The iPhone app is a constraint on the API, not a later concern

The handover is explicit that items 12 and 13 are for an app Garrett intends to build against
this server. So: multipart in, JSON or `audio/wav` out, no cookie, no CSRF, no session-shaped
assumption, and the token in a header. If the three calls above are composable by `curl` they
are composable by an iOS client, and that is the test to hold them to.

## 5. The honesty rules this surface will be tempted to break

- **The chat model is text-only.** `Qwen2.5-7B-Instruct` has no audio path any more than it has
  the vision projector §2f rules out. Speech-to-speech here is ASR → text → TTS, and the page
  must say so. Anything implying the model *hears* is a claim about hardware we do not have.
- **The latency is the product.** §5 item 12 says it and the numbers agree: the input half of a
  spoken turn is **~0.65 s measured** (70 ms transcode + 579 ms ASR) and never touches the GPU.
  What remains unknown is TTFT and TTS. Publish the parts that are measured, label the rest
  `projected`, and do not publish a round-trip figure until the whole round trip has been timed.
- **A microphone level meter must read the microphone.** The one place this surface will want a
  decorative animation is a waveform while recording; the Web Audio API gives a real level, so
  there is no excuse for a fake one.
- **Every figure on the page carries `measured` / `vendor` / `projected`**, and the numbers in
  §2 here are measured *under contention* — re-measure on a quiet box before any of them is
  printed for a visitor.

## 6. Where the numbers came from

Everything in §2 is reproducible from the two commands in §2 and §2.4 on this machine, with
`base.en`, `-t 8`, on an i9-10900KF (10 cores / 20 threads), load average 6.5–7.5 throughout.
The clips were cut with ffmpeg 7.1.5; the 22 s and 33 s files are `jfk.wav` concatenated twice
and three times with Python's `wave` module. No GPU lock was taken and no model was evicted to
produce any of it.
