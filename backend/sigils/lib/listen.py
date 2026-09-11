"""Speech to a subject line. The audio half of SyMoNeuRaL Stickers.

**This never touches the GPU, and that is the design rather than an implementation
detail.** One card, 15.92 GiB, one tenant at a time. If the transcription were a CUDA
tenant, a spoken sticker would be: take the lock, transcribe, release, wait for the
governor's 1.5 GiB drain floor, take the lock again, render -- and the drain wait alone is
bounded at 60 s. Kept on the CPU it can run *while another surface holds the card*, so the
only GPU wait a spoken sticker pays is the one a typed sticker already pays.

That is RavenCalc's argument, not a new one. RavenCalc deliberately never takes the lock,
which is what lets it answer while the card is loading, and HANDOVER 5 item 12 names it as
the precedent for exactly this work.

## What this is, stated honestly, because the page must not overclaim

`whisper.cpp` transcribes; the transcript is then used as the sticker's subject and goes
down the *same* text path a typed subject goes down. **There is no audio-native model
here.** Nothing listens to a voice and draws; speech becomes text, and text becomes a
picture. The page says so, and this docstring exists so that a later change does not
quietly start implying otherwise.

## The failure this guards, which a naive version ships

Whisper does not return "nothing" for silence -- it returns a marker like `[BLANK_AUDIO]`,
and on near-silence it will sometimes confabulate a short pleasantry ("Thank you.").
Passing either straight through gives a visitor a confident sticker of the words
`[BLANK_AUDIO]`, which looks like a bug in the renderer and is really a missing check
here. `subject_from` is that check.
"""
from __future__ import annotations

import asyncio
import os
import pathlib
import re
import shutil
import tempfile
import time

ROOT = next(_p for _p in pathlib.Path(__file__).resolve().parents if (_p / "backend" / "server.py").is_file())
assert (ROOT / "scripts" / "gpu-governor.sh").is_file(), (
    f"{ROOT / 'scripts' / 'gpu-governor.sh'} is not a file. Either that script is "
    f"missing, or ROOT is wrong (computed {ROOT}). Same wording as api.py:58 and the "
    "same reason: commissioning moved the script aside and the old message blamed the "
    "root, which was the one thing that was correct."
)

#: Built by `tools/sh/fork_engines.sh listen`, CPU-only on purpose. See the module docstring.
#: The CPU-only choice is unchanged and is argued in `scripts/fetch-whisper.sh`; what changed
#: is the home. This named a third-party binary under `contrib/`, which is gitignored -- so
#: the engine could disappear without a trace, and did. `voice/asr.py` is the other call site
#: and moved in the same commit; those two were the only ones.
WHISPER = ROOT / "symoneural-listen" / "build" / "bin" / "symoneural-listen"
MODELS = ROOT / "backend" / "models" / "whisper"
#: `base.en` is the default the fetch script pulls. English-only, 142 MB, and enough for
#: an utterance that is a handful of words describing a sticker. A larger model is a
#: straight swap -- the file name is the only thing that changes.
DEFAULT_MODEL = "symoneural-listen-base-en.bin"

#: Decoded audio is capped by *duration*, not only by bytes, and both caps are structural:
#: a sticker subject is a few words, and a surface that will transcribe an hour of audio on
#: request has handed one caller the CPU for minutes. The trim is done by ffmpeg, so a long
#: upload is truncated rather than refused -- the first 30 s of someone describing a sticker
#: is the part that describes the sticker.
MAX_AUDIO_BYTES = 25 * 1024 * 1024
MAX_SECONDS = 30
#: A wedged decoder must not hold a worker forever. Generous against the 2.2 s measured for
#: an 11 s clip, because a cold page cache and a contended CPU are both real.
FFMPEG_TIMEOUT_S = 120
WHISPER_TIMEOUT_S = 300

#: Whisper's own markers for "there was no speech here", plus the short confabulations it
#: produces on near-silence. Matched case-insensitively against the whole transcript, so a
#: sticker whose subject genuinely contains one of these words is unaffected.
_NOT_SPEECH = re.compile(
    r"^(\[[^\]]*\]|\([^)]*\)|thank you\.?|thanks\.?|you\.?|bye\.?|\.|)$", re.I)
#: Whisper brackets non-speech events inline: "[MUSIC] a raven [BLANK_AUDIO]". Those are
#: annotations about the recording, never part of what was asked for.
_EVENT = re.compile(r"\[[^\]]*\]|\([^)]*\)")


def model_path(name: str = DEFAULT_MODEL) -> pathlib.Path:
    return MODELS / name


def installed(name: str = DEFAULT_MODEL) -> bool:
    """The binary and the weights genuinely on disk -- not this module importing.

    `shutil.which("ffmpeg")` is part of it because the decode step is not optional: an
    iPhone sends `.m4a`/`.caf` and a browser sends WebM/Opus, and whisper.cpp reads
    neither. Reporting this surface as available without ffmpeg would be reporting a
    capability the box does not have.
    """
    return (WHISPER.is_file() and model_path(name).is_file()
            and shutil.which("ffmpeg") is not None)


class Unheard(RuntimeError):
    """The audio decoded, but there was no speech in it."""


class Undecodable(RuntimeError):
    """ffmpeg could not read the upload at all."""


async def _spawn(argv: list[str], timeout: float) -> tuple[int, bytes, bytes]:
    proc = await asyncio.create_subprocess_exec(
        *argv, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except (asyncio.TimeoutError, asyncio.CancelledError):
        proc.kill()
        await proc.wait()
        raise
    return proc.returncode or 0, out or b"", err or b""


async def to_wav(blob: bytes, dest: pathlib.Path) -> float:
    """Decode anything ffmpeg reads into 16 kHz mono 16-bit PCM. Returns seconds taken.

    16 kHz mono s16 is not a preference -- it is what whisper.cpp's frontend consumes, and
    handing it anything else means it either refuses the file or resamples it itself.

    The blob is written to a file rather than piped: `.m4a` and `.mov` keep their index at
    the end of the container, so a demuxer reading a non-seekable pipe fails on exactly the
    formats an iPhone produces. That failure is intermittent-looking and format-specific,
    which is the worst kind to debug from a bug report.
    """
    started = time.monotonic()
    with tempfile.NamedTemporaryFile(suffix=".upload", delete=False) as raw:
        raw.write(blob)
        src = pathlib.Path(raw.name)
    try:
        rc, _out, err = await _spawn([
            "ffmpeg", "-hide_banner", "-nostdin", "-loglevel", "error",
            "-i", str(src),
            "-vn",                       # a video attachment is not speech
            "-t", str(MAX_SECONDS),
            "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le",
            "-f", "wav", "-y", str(dest),
        ], FFMPEG_TIMEOUT_S)
    finally:
        src.unlink(missing_ok=True)
    if rc != 0 or not dest.is_file() or dest.stat().st_size < 1024:
        raise Undecodable(err.decode("utf-8", "replace").strip()[-300:]
                          or "ffmpeg could not read that audio")
    return time.monotonic() - started


def subject_from(transcript: str) -> str:
    """The transcript, reduced to something that can be a sticker subject.

    Raises `Unheard` rather than returning an empty string: the caller must distinguish
    "silence" from "a subject that happens to be short", and returning `""` for the first
    invites a render of nothing.
    """
    text = _EVENT.sub(" ", transcript)
    text = re.sub(r"\s+", " ", text).strip()
    if _NOT_SPEECH.match(text):
        raise Unheard("no speech in that recording")
    # Whisper punctuates a sentence; a sticker subject is a noun phrase. The trailing stop
    # is dropped because it reaches the prompt otherwise, and a full stop in a diffusion
    # prompt is a token spent on nothing.
    text = text.rstrip(" .!?,")
    if len(text) < 2:
        raise Unheard("no speech in that recording")
    return text


async def transcribe(blob: bytes, model: str = DEFAULT_MODEL,
                     threads: int | None = None) -> dict:
    """Audio bytes in, a sticker subject out, with both timings measured separately.

    `decode_seconds` and `transcribe_seconds` are kept apart for the same reason the render
    path keeps `queued_seconds` apart from `render_seconds`: they are different work on
    different tools, and their sum reported as one number would be a measurement that means
    something other than what it says.
    """
    if len(blob) > MAX_AUDIO_BYTES:
        raise Undecodable(f"that recording is larger than the {MAX_AUDIO_BYTES // (1 << 20)} MB cap")
    if not installed(model):
        raise Undecodable("speech-to-text is not installed on this box")
    with tempfile.TemporaryDirectory() as tmp:
        wav = pathlib.Path(tmp) / "in.wav"
        decode_s = await to_wav(blob, wav)
        # 16-bit mono at 16 kHz: two bytes a frame, and a 44-byte canonical header.
        audio_s = round(max(0, wav.stat().st_size - 44) / (16000 * 2), 2)
        started = time.monotonic()
        rc, out, err = await _spawn([
            str(WHISPER),
            "-m", str(model_path(model)),
            "-f", str(wav),
            "-nt",                                    # no timestamps; we want the words
            "-t", str(threads or min(8, os.cpu_count() or 4)),
        ], WHISPER_TIMEOUT_S)
        transcribe_s = time.monotonic() - started
    if rc != 0:
        raise Undecodable(err.decode("utf-8", "replace").strip()[-300:]
                          or "the transcriber failed")
    transcript = out.decode("utf-8", "replace").strip()
    return {
        "subject": subject_from(transcript),
        "transcript": transcript,
        "audio_seconds": audio_s,
        "decode_seconds": round(decode_s, 3),
        "transcribe_seconds": round(transcribe_s, 3),
        "model": model,
        # Named so a client cannot mistake this for an audio-native model. It is ASR, and
        # the picture is drawn from the words.
        "path": "speech -> text -> the same render a typed subject gets",
    }


def state() -> dict:
    """What this half can do, as a reading rather than a claim."""
    return {
        "installed": installed(),
        "model": DEFAULT_MODEL if model_path().is_file() else None,
        "engine": "whisper.cpp, CPU only -- never takes the GPU lock",
        "max_seconds": MAX_SECONDS,
        "max_bytes": MAX_AUDIO_BYTES,
        "ffmpeg": shutil.which("ffmpeg") is not None,
    }
