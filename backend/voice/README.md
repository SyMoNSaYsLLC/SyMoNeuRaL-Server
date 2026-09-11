# SyMoNeuRaL Voice — what works today, and the two things that are owed

**Built 2026-08-17.** The design is `backend/voice/docs/voice-spec.md`; HANDOVER §5 item 12 is the ask.
This is the **input half**. Speech out is not built and `tts.py` says so rather than faking it.

## Works, mounted, and testable right now

```
GET  /api/voice/state        presence and absence — no token
POST /api/voice/transcribe   multipart `audio` -> the reading — X-Symoneural-Token
POST /api/voice/speak        503 naming the missing engine — X-Symoneural-Token
```

Mounted in `backend/server.py` (`include_router(voice.router, prefix="/api/voice")`). Off unless
**both** `SYMONEURAL_VOICE_ENABLED=1` (the literal string `1`) and `SYMONEURAL_VOICE_TOKEN` are set.

```bash
cd backend && python3 apps/voice/test_voice.py        # 31 tests
curl -sS -H "X-Symoneural-Token: $SYMONEURAL_VOICE_TOKEN" -F audio=@clip.webm \
     http://127.0.0.1:8800/api/voice/transcribe
```

Measured end to end through the route on this box: an 11-second WebM/Opus clip → **847 ms**
(67 ms transcode, 780 ms ASR), correct transcript, **0 VRAM**, no governor lease taken.

## The two owed pieces, and who they belong to

1. **`site/voice.html` and the rack row.** `status()` is written and correct, but its `href` is
   `/voice.html` and that page does not exist — the page is written by `tools/build/build_pages.py`,
   which other sessions were holding. **No `voice` `Unit` was added to `api.py` for exactly
   this reason:** a rack row pointing at a 404 is worse than no row. Add both in one commit.
2. **Speech out.** Nothing that speaks is installed and Piper needs its own venv, which is
   Garrett's call, not an agent's. `tts.py`'s docstring carries the command and the two things
   to settle alongside it (the voice model's licence, and `onnxruntime` already being in play
   for the Stickers work).

Neither is a design question. Both are one decision or one file away.

## What will bite the next reader

- **`whisper-cli` exits 0 on a file it could not read**, and the browser's own recording format
  (WebM/Opus) is one of those files — this build's decoder is miniaudio, which has no Opus
  path, while `--help` claims ogg support. A route trusting `returncode` returns an empty
  transcript as success. `asr.transcribe` treats empty stdout as failure, and that is safe
  because **silence is not empty**: measured on three seconds of `anullsrc`, the model prints
  ` you`. It invents a word rather than returning nothing.
- **So the model hallucinates on silence, and no filter is applied to it here** (house rule).
  What is published instead is `peak`, the largest sample amplitude 0.0–1.0, read from the
  decoded audio. Silence measures `0.0` and speech measures `0.79`, so a caller can tell
  "nobody spoke" from "the model heard something" with a real reading rather than a guess.
- **`ffmpeg -ar 16000 -ac 1` is unconditional**, including on a file that claims to be a wav.
  It costs 66–72 ms and a content-type is a claim, not a fact.
- **Cost is flat inside a 30-second window and steps between windows** — `encode` measured flat
  at 353–414 ms from 3 s to 22 s, then doubling at 33 s. Whisper encodes a padded window, not
  the speech. Publish "about half a second for anything you can say in one breath"; never
  promise per-second scaling, and count windows rather than seconds in any progress indicator.
- **Both artefacts this needs are gitignored** (`contrib/whisper.cpp`, `models/whisper`)
  so a fresh checkout has neither. `EngineTests` **skips** as a unit there rather than failing.
- **The semaphore is per event loop**, held in a `WeakKeyDictionary`. A module-level singleton
  works in the service (one loop, for ever) and raises the moment a suite calls `asyncio.run`
  twice; there is a test asserting the two loops get different objects.

## What is NOT measured, and must not be published as if it were

- **Chat's time to first token.** The handover records 80–92 tok/s, which is throughput, not
  TTFT — and TTFT is what a spoken turn feels like. Measuring it means taking the GPU lock on
  a quiet box; the fleet was live. **No round-trip figure may go on a page until it is.**
- **Anything about speech out.** There is no engine to time.
- Every timing here was taken at load average 6.5–7.5 on 20 CPUs with a dozen sessions writing
  this repo. They are **ceilings**; a quiet box beats them.
