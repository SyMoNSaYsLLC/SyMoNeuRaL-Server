"""Speech to text: ffmpeg to 16 kHz mono, then `symoneural-listen`, then two failure checks.

Everything in here is CPU work and none of it touches `scripts/gpu-governor.sh`. That is not
a preference, it is what the build on this box is:
`symoneural-listen/build/CMakeCache.txt` carries `GGML_CUDA:BOOL=OFF`, set by
`tools/sh/fork_engines.sh listen` and argued there. The evidence path named here until
2026-09-04 was under `contrib/`, which no longer exists -- a claim whose source cannot be
opened is the thing this file's own §2.2 warning is about.
Measured with `base.en` at `-t 8`: peak RSS **284 MiB**, **0**
VRAM, and a 3-second utterance end to end in **579 ms**. See `backend/voice/docs/voice-spec.md` §2 for
the table those came out of, and read §2.2 before putting any latency figure on a page.

## The two traps, both of which return a working-looking empty answer

**`whisper-cli` exits 0 on a file it could not read.** Verified again while writing this:
handed an Opus file it prints `read_audio_data: failed to read audio data` on stderr, writes
nothing to stdout, and exits **0**. A route that checks `returncode` therefore reports success
with an empty transcript and the visitor's question vanishes with no error anywhere.

**The usage banner claims ogg support this build does not have.** `--help` prints
`supported audio formats: flac, mp3, ogg, wav`; the decoder is miniaudio, which has no Opus
path. Chrome's `MediaRecorder` produces WebM/Opus, so the browser's native format is exactly
the one that silently fails. Measured: wav, mp3 and flac transcribe; ogg and webm yield 0
bytes and exit 0. `ffmpeg -ar 16000 -ac 1` costs 66-72 ms, so the transcode is unconditional.

## Empty stdout is a failure, and that is safe to assert because silence is not empty

The obvious worry about "empty output means the file was unreadable" is that a silent
recording would be misreported as a decode failure. It would not: measured on three seconds
of `anullsrc`, `whisper-cli` prints ` you` -- it invents a word rather than returning nothing.
So empty stdout is unambiguous evidence the audio never reached the model.

The flip side is a real artefact and callers have to know about it: **this model emits a word
on silence.** No filter is applied to it here (house rule; and a filter would also throw away
a legitimate one-word answer). What is published instead is a measurement: `peak`, the largest
sample amplitude in the decoded audio, 0.0 to 1.0. A caller that wants to distinguish "nobody
spoke" from "the model heard something" has a real reading to do it with rather than a guess.
"""
from __future__ import annotations

import asyncio
import math
import os
import time
import shutil
import wave
import weakref
from array import array
from pathlib import Path

# Nothing here hardcodes its own location: the root is derived from this file, the way
# `backend/server.py` derives it from `__file__` and the scripts derive it from `$0`. That
# calculation has been wrong four times in this repo, so it is asserted below.
ROOT = next(_p for _p in Path(__file__).resolve().parents if (_p / "backend" / "server.py").is_file())
assert (ROOT / "backend" / "server.py").is_file(), f"repo root not found at {ROOT}"

# Our engine, under our name, built by `tools/sh/fork_engines.sh listen`. The default used to
# name a third-party binary under `contrib/`, which was two problems in one line: `/contrib`
# is gitignored, so the capability vanished with nothing in `git log` to say it had, and the
# path is one `backend/test_references_boundary.py` bans outright -- it escaped that
# test only because the segments are separate string literals, so the banned spelling never
# appears as text. Neither of those was a decision anyone made.
WHISPER_CLI = Path(os.environ.get("SYMONEURAL_WHISPER_CLI")
                   or ROOT / "symoneural-listen" / "build" / "bin"
                   / "symoneural-listen")
MODEL = Path(os.environ.get("SYMONEURAL_WHISPER_MODEL")
             or ROOT / "models" / "whisper" / "symoneural-listen-base-en.bin")

# Whisper pads its input to a fixed window and encodes the window, not the speech. This is
# the number behind the flat 353-414 ms `encode` column for every clip from 3 s to 22 s, and
# behind its doubling at 33 s. It is a property of the model, not a tunable.
WINDOW_S = 30.0

# 8 threads measured ~1.5x faster than 4 on the same clip (0.60 s vs 0.89 s) on 20 CPUs.
THREADS = max(1, int(os.environ.get("SYMONEURAL_VOICE_THREADS") or 8))

# Two concurrent transcriptions are 16 of 20 threads. A third makes all three slower than
# serving them in turn would have been, and also slows the chat generation the visitor is
# waiting on. A 0.6 s job that waits 0.6 s is still a good answer, so queue instead.
CONCURRENCY = max(1, int(os.environ.get("SYMONEURAL_VOICE_CONCURRENCY") or 2))

# There is no byte cap on the upload, deliberately: Garrett removed every size cap on the
# tuner and the wall clock was always the bound doing the real work. A 30-minute recording
# is a legitimate request that takes a while; a hang is not, and this is what catches it.
TIMEOUT_S = float(os.environ.get("SYMONEURAL_VOICE_TIMEOUT_S") or 300)

TRANSCODE_TIMEOUT_S = float(os.environ.get("SYMONEURAL_VOICE_TRANSCODE_TIMEOUT_S") or 120)


class AsrError(RuntimeError):
    """Something about this request could not be done. Carries what the tool said.

    `detail` is the tail of the tool's stderr. It is surfaced to the caller on purpose: this
    repo's own history is a list of features that looked fine because the failure path was
    silent, and "failed to read audio data" is the difference between debugging a route and
    debugging a microphone.
    """

    def __init__(self, message: str, *, detail: str = "") -> None:
        super().__init__(message)
        self.message = message
        self.detail = detail


class AsrUnavailable(AsrError):
    """The engine is not installed on this box. A 503, not a 400 -- the caller did nothing
    wrong. Kept a distinct class so a route cannot blame the visitor for a missing binary."""


def ffmpeg_path() -> str | None:
    return shutil.which(os.environ.get("SYMONEURAL_FFMPEG") or "ffmpeg")


def installed() -> tuple[bool, str]:
    """(ready, why not). Every clause names the exact missing path, because both artefacts
    are gitignored (`contrib/` and `models/`) and a fresh checkout has neither."""
    if not WHISPER_CLI.is_file():
        return False, f"whisper-cli missing at {WHISPER_CLI}"
    if not os.access(WHISPER_CLI, os.X_OK):
        return False, f"whisper-cli is not executable at {WHISPER_CLI}"
    if not MODEL.is_file():
        return False, f"whisper weights missing at {MODEL}"
    if ffmpeg_path() is None:
        return False, "ffmpeg not on PATH -- browser audio is Opus and must be transcoded"
    return True, ""


# One semaphore per event loop. `asyncio.Semaphore` binds to the loop that first waits on it
# and raises if a second loop touches it, so a module-level singleton works in the service
# (one loop, forever) and breaks the moment a test calls `asyncio.run` twice. Weak keys so a
# finished loop's entry goes away with it.
_sems: weakref.WeakKeyDictionary = weakref.WeakKeyDictionary()


def _sem() -> asyncio.Semaphore:
    loop = asyncio.get_running_loop()
    sem = _sems.get(loop)
    if sem is None:
        sem = _sems[loop] = asyncio.Semaphore(CONCURRENCY)
    return sem


_in_flight = 0


def in_flight() -> int:
    """How many transcriptions are running right now. The rack row reads this to say `busy`,
    and it is a real count rather than a guess at whether the surface is doing something."""
    return _in_flight


def queue_depth() -> int:
    """How many callers are waiting for a slot right now, or 0 outside a loop. A real
    reading, for a surface that is allowed to publish one."""
    try:
        sem = _sems.get(asyncio.get_running_loop())
    except RuntimeError:
        return 0
    if sem is None:
        return 0
    waiters = getattr(sem, "_waiters", None)
    return len(waiters) if waiters else 0


async def _run(argv: list[str], timeout: float) -> tuple[int, bytes, bytes]:
    proc = await asyncio.create_subprocess_exec(
        *argv, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise AsrError(f"{Path(argv[0]).name} did not finish within {timeout:g}s")
    return proc.returncode, out, err


def _tail(raw: bytes, limit: int = 400) -> str:
    text = raw.decode("utf-8", "replace").strip()
    return text[-limit:]


async def transcode(src: Path, dst: Path) -> int:
    """Anything the browser can record -> 16 kHz mono PCM. Returns milliseconds spent.

    Unconditional, including for a file that is already a 16 kHz mono wav. Trusting a
    filename or a content-type here is how the Opus trap gets back in: `MediaRecorder` can
    be handed `audio/wav` as a MIME type and still produce a container this build cannot
    read, and 70 ms is not worth a branch that can be wrong.
    """
    ff = ffmpeg_path()
    if ff is None:
        raise AsrUnavailable("ffmpeg not on PATH -- browser audio must be transcoded")
    started = time.monotonic()
    # `-nostdin` because a subprocess inheriting the service's stdin can consume it.
    rc, _out, err = await _run(
        [ff, "-nostdin", "-v", "error", "-y", "-i", str(src),
         "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", str(dst)],
        TRANSCODE_TIMEOUT_S)
    if rc != 0 or not dst.is_file() or dst.stat().st_size == 0:
        # Unlike whisper-cli, ffmpeg does exit non-zero on input it cannot parse -- measured
        # 183 on 2 KB of /dev/urandom in a .webm. So this arm is a real signal.
        raise AsrError("that audio could not be decoded", detail=_tail(err))
    return int((time.monotonic() - started) * 1000)


def probe_wav(path: Path) -> tuple[float, float]:
    """(seconds, peak amplitude 0.0-1.0) read from the decoded file itself.

    Read with the `wave` module rather than by asking ffprobe: it is one open instead of a
    third process, and the file is ours -- we just wrote it as 16-bit mono PCM.
    """
    with wave.open(str(path), "rb") as w:
        frames, rate, width = w.getnframes(), w.getframerate(), w.getsampwidth()
        if rate <= 0:
            raise AsrError("decoded audio reports a zero sample rate")
        seconds = frames / rate
        if width != 2 or frames == 0:
            # We asked for pcm_s16le; anything else means the transcode did not do what it
            # was told, and a peak computed off the wrong width would be nonsense.
            return seconds, 0.0
        samples = array("h")
        samples.frombytes(w.readframes(frames))
    peak = max((abs(s) for s in samples), default=0) / 32768.0
    return seconds, round(peak, 5)


def windows_for(seconds: float) -> int:
    """How many 30-second encodes this costs. The honest unit of progress for this engine --
    count these, never seconds, because cost is flat inside a window and steps between."""
    return max(1, math.ceil(seconds / WINDOW_S))


async def transcribe(src: Path, work: Path) -> dict:
    """`src` (any container ffmpeg reads) -> the reading. `work` is a caller-owned scratch
    directory; nothing here writes outside it, and nothing here deletes it."""
    ready, why = installed()
    if not ready:
        raise AsrUnavailable(why)

    wav = work / "in16k.wav"
    transcode_ms = await transcode(src, wav)
    seconds, peak = probe_wav(wav)

    global _in_flight
    started = time.monotonic()
    async with _sem():
        waited_ms = int((time.monotonic() - started) * 1000)
        asr_started = time.monotonic()
        _in_flight += 1
        try:
            # `-nt` is no timestamps: stdout becomes the transcript and nothing else, so there
            # is no format to parse and none to break. Every banner goes to stderr.
            rc, out, err = await _run(
                [str(WHISPER_CLI), "-m", str(MODEL), "-t", str(THREADS), "-nt", "-f", str(wav)],
                TIMEOUT_S)
        finally:
            # In a `finally` because a timeout raises out of `_run`, and a counter that only
            # decrements on the happy path leaves the rack row stuck on `busy` forever.
            _in_flight -= 1
        asr_ms = int((time.monotonic() - asr_started) * 1000)

    text = out.decode("utf-8", "replace").strip()
    if rc != 0:
        raise AsrError("transcription failed", detail=_tail(err))
    if not text:
        # THE TRAP. rc is 0 here. See this module's docstring: silence produces a word, so
        # nothing at all means the audio never reached the model.
        raise AsrError("the engine read no audio from that file", detail=_tail(err))

    return {
        "text": text,
        "audio_s": round(seconds, 3),
        "peak": peak,
        "windows": windows_for(seconds),
        "transcode_ms": transcode_ms,
        "asr_ms": asr_ms,
        "queued_ms": waited_ms,
        "ms": transcode_ms + waited_ms + asr_ms,
        "threads": THREADS,
        "model": MODEL.name,
        "engine": "whisper.cpp, CPU build (GGML_CUDA=OFF) — never takes the GPU lock",
    }
