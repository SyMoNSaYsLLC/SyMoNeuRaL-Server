"""The Voice surface's HTTP contract.

    import voice
    app.include_router(voice.router, prefix="/api/voice", tags=["voice"])   # before static

    GET  /api/voice/state        what this box can actually do — no token
    POST /api/voice/transcribe   multipart audio -> the reading — token required
    POST /api/voice/speak        503 until something that speaks is installed

Speech to speech is `transcribe` -> **the existing `/api/chat`** -> `speak`. It is not a third
route and there is no audio-native model here: `SymonChat S1-7B` is text-only, so a spoken turn
is ASR -> the text model -> TTS and no page may imply otherwise.

**The one thing a voice path must not become.** `api.py`'s `Turn.role` is
`Literal["user", "assistant"]` on purpose -- it is what stops a client injecting a `system`
turn and overriding the trained persona and the pricing refusal, which live in
`training/corpus.jsonl` rather than in a prompt. This module never assembles a chat request and
never reaches the system prompt; the client composes the three calls. That is also what makes
the contract usable by something that is not this site (Garrett's iPhone app): multipart in,
JSON out, no cookie, no CSRF, no session, token in a header. If `curl` can compose it, an iOS
client can.

## Why `/state` carries no token and the other two do

`/state` returns presence and absence -- is the binary there, is a synthesiser there, what
model file -- and there is no key material in this package to leak. `transcribe` is CPU a
stranger can spend, on a box whose only contended resource is already rationed for the GPU
but not for the cores. `apps/gateway` is the precedent for the open read; `apps/asicminer` is
the precedent for the gate, and this uses its header name, `X-Symoneural-Token`.

## Why the two gated routes declare two header parameters

`X-Sym-Token` is the name that header had until the rename and is still accepted. Unlike the
other surfaces, which read a request object and can just try two keys, these are FastAPI
routes whose credential arrives as a declared parameter -- and `Header(alias=...)` binds
exactly one name. So each gated route takes both and passes `new or legacy` to `_require`,
which is also why both appear in the generated OpenAPI: they are both genuinely accepted, and
a schema that advertised only one would be describing a stricter server than this is.
"""
from __future__ import annotations

import re
import tempfile
from pathlib import Path

from fastapi import APIRouter, File, Header, HTTPException, UploadFile

from . import asr, tts

router = APIRouter()

# 64 KiB at a time. There is no byte cap on the upload (Garrett removed every size cap on the
# tuner and the wall clock was always the real bound), so the one thing that must not happen
# is holding the whole of a long recording in memory to find that out.
_CHUNK = 64 * 1024

_SUFFIX_OK = re.compile(r"^\.[A-Za-z0-9]{1,8}$")


def _off() -> HTTPException:
    """The 503 for a surface that is switched off, naming both variables.

    `SYMONEURAL_VOICE_ENABLED` must be the literal string `1`. `true`, `yes` and `on` all leave it
    off and say nothing -- the check is `== "1"`, not truthiness. That is the single most
    reported confusion about `SYMONEURAL_ASIC_ENABLED`, so it is spelled out here the first time.
    """
    return HTTPException(
        status_code=503,
        detail="voice surface is off — set SYMONEURAL_VOICE_ENABLED=1 (the literal string 1, not "
               "true) in ops/symoneural-api.service, then "
               "sudo systemctl daemon-reload && sudo systemctl restart symoneural-api",
    )


def _require(token: str | None) -> None:
    from . import enabled, token_ok
    if not enabled():
        raise _off()
    if not token_ok(token):
        # 401, not 403: the credential is missing or wrong, and there is no identity here to
        # be forbidden. No hint about the expected length or shape.
        # Names the new header only. A caller who sent the legacy one was accepted, so listing
        # both here would describe a rejection that did not happen for that reason.
        raise HTTPException(status_code=401, detail="X-Symoneural-Token missing or wrong")


def _safe_suffix(filename: str | None) -> str:
    """A suffix taken from the caller is a filename taken from the caller. ffmpeg sniffs the
    container anyway, so this exists only to be harmless -- alphanumerics, or nothing."""
    if not filename:
        return ".bin"
    suffix = Path(filename).suffix
    return suffix if _SUFFIX_OK.match(suffix) else ".bin"


@router.get("/state", summary="What this box can hear and whether it can speak")
def state() -> dict:
    from . import enabled, status
    if not enabled():
        raise _off()
    ready, why = asr.installed()
    return {
        "enabled": True,
        "asr": {
            "available": ready,
            "problem": why or None,
            "engine": "whisper.cpp, CPU build (GGML_CUDA=OFF)",
            "model": asr.MODEL.name if asr.MODEL.is_file() else None,
            "threads": asr.THREADS,
            "concurrency": asr.CONCURRENCY,
            "queued": asr.queue_depth(),
            "window_s": asr.WINDOW_S,
            # Measured on this machine at load average 6.5-7.5, so it is a ceiling. The
            # route reports its own `ms` per request; this is the published expectation and
            # it is labelled, per the honesty rules, rather than presented as a guarantee.
            "measured_ms_short_utterance": 650,
            "measured_note": "flat ~0.65 s for anything under 30 s — whisper encodes a padded "
                             "30 s window, so cost steps per window and never per second",
        },
        "tts": tts.state(),
        "gpu": "never — this surface takes no governor lease, like RavenCalc",
        "unit": status(),
    }


@router.post("/transcribe", summary="Speech to text, on the CPU, without queueing for the GPU")
async def transcribe(
    audio: UploadFile = File(..., description="Any container ffmpeg reads. WebM/Opus from a "
                                             "browser's MediaRecorder is the expected case."),
    x_symoneural_token: str | None = Header(default=None, alias="X-Symoneural-Token"),
    x_sym_token: str | None = Header(default=None, alias="X-Sym-Token",
                                     description="The name this header had until the rename. "
                                                 "Still accepted; prefer the one above."),
) -> dict:
    """The reading, including how long each stage took.

    Failure modes, all of which say what happened rather than returning an empty string:
    503 the engine is not installed, 400 the audio could not be decoded, 400 the engine read
    no audio from it (see `asr.py` -- `whisper-cli` exits 0 on that path, which is the trap
    this route exists to close).
    """
    _require(x_symoneural_token or x_sym_token)

    with tempfile.TemporaryDirectory(prefix="symvoice-") as tmp:
        work = Path(tmp)
        src = work / f"upload{_safe_suffix(audio.filename)}"
        with src.open("wb") as fh:
            while chunk := await audio.read(_CHUNK):
                fh.write(chunk)
        received = src.stat().st_size
        if received == 0:
            raise HTTPException(status_code=400, detail="that upload was empty")
        try:
            result = await asr.transcribe(src, work)
        except asr.AsrUnavailable as exc:
            raise HTTPException(status_code=503, detail=exc.message) from exc
        except asr.AsrError as exc:
            detail = exc.message + (f" — {exc.detail}" if exc.detail else "")
            raise HTTPException(status_code=400, detail=detail) from exc
        # Read inside the context: the scratch directory and everything in it is gone by the
        # time this function returns, so a stat() after the `with` block is always None.
        return {"bytes_in": received, **result}


@router.post("/speak", summary="Text to speech — not built; says so rather than faking it")
def speak(
    x_symoneural_token: str | None = Header(default=None, alias="X-Symoneural-Token"),
    x_sym_token: str | None = Header(default=None, alias="X-Sym-Token",
                                     description="The name this header had until the rename. "
                                                 "Still accepted; prefer the one above."),
) -> dict:
    """503, always, until an engine is installed and a synthesis path is written.

    The gate is checked first so this cannot be used to probe whether the surface exists, and
    the body names the command. See `tts.py` for why there is no placeholder wav here.
    """
    _require(x_symoneural_token or x_sym_token)
    half = tts.state()
    fix = half["install"] or "write the synthesis path in backend/voice/tts.py"
    raise HTTPException(status_code=503, detail=f"{half['problem']}. To close it: {fix}")
