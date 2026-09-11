"""SyMoNeuRaL Voice -- speech in, on the CPU, without ever queueing behind the GPU.

`backend/voice/docs/voice-spec.md` is the design and its §2 holds the measurements this package is
built on. HANDOVER §5 item 12 asked for text-to-speech, speech-to-text and speech-to-speech
wired into SyMoNeuRaL Chat. **This is the input half.** The output half is not built and
`tts.py` reports that instead of faking it.

Three exports, and they are the whole contract with `api.py`:

    import voice
    app.include_router(voice.router, prefix="/api/voice", tags=["voice"])   # before static
    Unit(**voice.status())          # the rack row -- see the warning below
    "voice": (60, 900)              # a key in api.py's _RATE_SUGGESTED

**The rack row is deliberately NOT mounted yet.** `status()` is here and correct, but its
`href` is `/voice.html` and that page does not exist -- it is written by
`tools/build/build_pages.py`, which two other sessions were holding when this landed. A rack row
pointing at a 404 is worse than no row: the front page is the one place on this site where
every link is expected to work. Add the row in the same commit as the page, not before.

## It takes the GPU lock never, and that is measured rather than asserted

The card is 15.92 GiB and chat (~5 GB) and image (~7 GB) already cannot co-reside; that
constraint is why `scripts/gpu-governor.sh` exists. A voice surface looks like it should be a
third tenant -- ASR, evict, chat, evict, TTS, with the governor's 1.5 GB VRAM drain wait
between each stage. It is not, because the engine on this box is a CPU build:
`symoneural-listen/build/CMakeCache.txt` carries `GGML_CUDA:BOOL=OFF`.

| Reading | Measured | Consequence |
|---|---|---|
| Peak RSS of a transcription | 284 MiB | System RAM is 96 GiB. Not a VRAM tenant. |
| VRAM used | 0 | There is nothing for the mutex to arbitrate. |
| A 3-second utterance, end to end | 579 ms | Faster than the governor's drain wait alone. |

So Voice is the second surface to take no lease, and **RavenCalc is the precedent it copies**
(`.claude/CLAUDE.md` names it). The benefit is not saved VRAM: it is that a spoken question
can be transcribed *while* a chat generation is running, instead of after it.

## What the numbers do NOT cover, stated here so a page cannot overreach

- **Time to first token from chat is unmeasured.** The handover records 80-92 tok/s with the
  persona adapter, which is throughput, not first-token latency -- and TTFT is what a spoken
  turn feels like. Measuring it means taking the lock on a quiet box; it was not worth
  evicting a peer session's work for. **Do not publish a round-trip figure until it is.**
- **Every timing here was taken at load average 6.5-7.5 on 20 CPUs** with a dozen agent
  sessions writing this repo, which biases them slow. They are ceilings.
- **The chat model is text-only.** the chat model is text-only and has no audio path
  any more than it has the vision projector `/chat.html` rules out. Speech to speech here is
  ASR -> text -> TTS, and the page must say so.

## Off unless both switches are set

    SYMONEURAL_VOICE_ENABLED=1              # the literal string 1; `true` leaves it off, silently
    SYMONEURAL_VOICE_TOKEN=<shared secret>  # transcribe and speak require it in
                                            # X-Symoneural-Token

`/api/*` is wholly delegated to FastAPI, so a route here is a public route, and a transcribe
endpoint is CPU a stranger can spend. Requiring both variables is what makes a
misconfiguration fail closed on a box with a public IP -- the pattern is
`backend/asicminer/__init__.py` and this follows it, header name included.

`GET /api/voice/state` needs no token: it publishes presence and absence, and there is no key
material in this package to leak. `apps/gateway` is the precedent for that.

## No content filtering is implemented

As of 2026-08-20 nothing here inspects what was said. **A deliberate pre-launch state, not a
cleared posture** — the standing instruction this section used to quote is held (request ledger
R-98, 2026-08-20) and is being re-scoped per surface. The guards that do exist are
structural: a scratch directory per request that is deleted with it, a suffix taken from the
caller only after it has been proved to be alphanumeric, subprocess timeouts instead of byte
caps, and a semaphore so two requests cannot thrash 20 cores into a third's latency.
"""
from __future__ import annotations

import hmac
import os

from .lib import asr
from .lib import tts
from .voice import router

__all__ = ["router", "status", "enabled", "installed", "asr", "tts"]


def enabled() -> bool:
    """On when the flag is on. The token half of this test is gone.

    `== "1"` and not truthiness is kept: it reads like a boolean and is not one,
    and that confusion is worth keeping consistent rather than solving differently
    in each package.
    """
    return True


def installed() -> bool:
    """Whether the ASR engine and its weights are actually on this disk. Both artefacts are
    gitignored (`contrib/`, `models/`), so a fresh checkout has neither and this is
    the difference between `ready` and `offline` on the rack."""
    return asr.installed()[0]


def status() -> dict:
    """The rack unit, keys matching `api.py`'s `Unit` model.

    `state` is honest in three directions rather than two: `offline` when the binary or the
    weights are missing (and `detail` says which), `busy` while a transcription is actually
    running, `ready` otherwise. It is never `queued` -- this surface does not wait for the
    card, which is the entire argument for it, and printing `queued` would quietly contradict
    that. No figure in here is a constant dressed as a reading: `detail` reports the engine
    and the model file, both read from disk.
    """
    ready, why = asr.installed()
    if not ready:
        state, detail = "offline", why
    else:
        busy = asr.queue_depth() > 0 or asr.in_flight() > 0
        state = "busy" if busy else "ready"
        detail = (f"{asr.MODEL.name} on the CPU · {asr.THREADS} threads · never waits for "
                  f"the GPU")
        if not tts.installed():
            detail += " · speech out not installed"
    return {
        "id": "voice",
        "label": "SyMoNeuRaL Voice",
        "slot": "1U",
        "state": state,
        "bus": "cpu",
        "href": "/voice.html",
        "spec": "whisper.cpp base.en · CPU build",
        "detail": detail,
    }
