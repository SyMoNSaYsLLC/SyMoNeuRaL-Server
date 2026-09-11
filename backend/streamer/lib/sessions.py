"""Tuning sessions: one upstream stream, one ffmpeg, a bounded number of both.

## What this fixes in `external/IPTV/IPTV/iptv_gateway_server.py`

That file is the right idea and three things in it cannot ship on a public box.

**1. The source was hardcoded.** `PRIMARY_SOURCE` and `BACKUP_SOURCE` were constants at the top
of the file. Here the source arrives per request and belongs to the visitor. Its "self-healing
failover" between the two constants is gone with them: failing over to a source the visitor did
not choose is not resilience, it is playing them something else. A session that loses its
upstream reports that it lost its upstream.

**2. It emitted raw MPEG-TS via `-c copy` to `pipe:1`, which a browser cannot play.** No
`<video>` element in any browser decodes an MPEG-TS elementary stream; the reference's endpoint
works in VLC and shows a broken player on a web page. **We emit HLS** -- `-f hls`, an `.m3u8`
plus rolling `.ts` segments -- and the choice over fragmented MP4 was made on three grounds:

  - **`-c copy` survives more sources.** IPTV upstreams are H.264 or HEVC with AAC, AC-3 or
    MP2 audio, and MPEG-TS segments carry all of those unchanged. Several of them cannot go
    into MP4 without re-encoding, and re-encoding on a box whose GPU is reserved for inference
    is not acceptable -- it would either take the card the rack promised to chat and image, or
    burn the CPU. Stream copy is the requirement; TS segments are what keeps it possible.
  - **The player is decoupled from the transcoder.** A single progressive fMP4 response ties
    one ffmpeg to one TCP connection, so a page reload, a seek or a flaky connection restarts
    the upstream pull. With HLS the segments are on disk and a reload is just more GETs.
  - **Disk is bounded by the muxer itself.** `hls_flags delete_segments` with a short
    `hls_list_size` keeps a rolling window and deletes behind it, so a session cannot fill the
    disk however long it runs.

  The cost is honest and belongs in the wiring notes: Safari plays `.m3u8` natively, and Chrome
  and Firefox need `hls.js` (MSE). That is a frontend dependency this module cannot satisfy for
  the page and does not pretend to.

**3. One unbounded ffmpeg per client was a trivial denial of service.** The reference spawns a
process per request, forever, with no cap and no timeout: a few dozen GETs and the box is gone.
Here there is a hard concurrent-session cap, an idle timeout keyed on the player actually
asking for segments, a hard maximum lifetime, and a reaper that runs whether or not the client
was polite enough to disconnect.

## Telling "the channel is dead" apart from "the streamer is broken"

The owner's diagnosis, and the reason for three of the behaviours below: *"if it's not active
you will come to a page from the server saying it's down, not just a blank screen."* A provider
page means the channel is off. A blank screen means we are. Everything that used to produce a
blank screen with a healthy-looking session is now named:

* an HTML page arriving where a stream was expected is reported as **the provider's words**
  rather than as "the transcoder could not stream-copy this source", which describes our
  transcoder and tells the visitor nothing (`looks_like_error_page`);
* **AES-128** HLS is decrypted rather than refused, while SAMPLE-AES and DRM stay refused *by
  name* -- decrypting those as if they were AES-128 would produce corruption instead of an
  error, which is worse than the refusal it replaced;
* **HEVC** is the one failure where every indicator is honest and the screen is still black.
  Nothing here can fix it, so `Session.vcodec` reports it and the page can say why.

## Why Python holds the socket and ffmpeg only sees a pipe

`safefetch` validates a URL and pins the address. Handing that URL to ffmpeg would throw all of
it away -- ffmpeg resolves its own names, follows its own redirects, in another process. So
**the upstream URL never reaches the subprocess**: a pump thread opens the connection through
`safefetch`, and ffmpeg reads `pipe:0` with `-protocol_whitelist pipe,fd` so it could not open
a URL if one arrived. The same arrangement keeps the visitor's credentials out of `argv`.
"""
from __future__ import annotations

import logging
import os
import re
import secrets
import shutil
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from ..lib import safefetch
from ..apps.m3u import HlsKey, HlsPlaylist, HlsSegment, parse_hls
from .safefetch import BlockedURL, FetchError, Policy, Scrubber

log = logging.getLogger("symoneural.streamer")

__all__ = ["Session", "SessionManager", "MANAGER", "StreamerBusy", "StreamerError",
           "PLAYLIST_NAME", "SEGMENT_RE", "VIDEO_CODECS", "ts_sync_offset"]


def _env_int(name: str, default: int, lo: int, hi: int) -> int:
    try:
        return max(lo, min(hi, int(os.environ[name])))
    except (KeyError, ValueError):
        return default


#: Concurrent ffmpeg processes. Two, because this is one box that is also serving a 7B model and
#: an image pipeline, and because the honest ceiling is low rather than because the number is
#: tidy. Raise it with `SYMONEURAL_STREAMER_MAX_SESSIONS` if the box ever grows.
MAX_SESSIONS = _env_int("SYMONEURAL_STREAMER_MAX_SESSIONS", 2, 1, 8)
#: No segment or playlist request for this long and the session is dead, whatever the client
#: thinks. This is the cap that survives a browser tab being closed without a goodbye.
#:
#: **12 s, not 45.** With `MAX_SESSIONS = 2` against an account whose own `max_connections` is
#: also 2, a slot held by a visitor who has already walked away is the whole capacity of the
#: surface. 45 s plus a 5 s reaper tick meant a closed tab kept a channel unavailable for the
#: best part of a minute, which reads as "the streamer is broken", not "the streamer is busy". The
#: page heartbeats every 5 s and every segment fetch also counts, so 12 s tolerates two missed
#: beats before it gives up on a client. The real fix is the client saying goodbye -- see
#: `POST /session/{sid}/stop` -- and this is what covers the cases where it cannot: a crash, a
#: killed browser, a lost network.
IDLE_TIMEOUT = _env_int("SYMONEURAL_STREAMER_IDLE_TIMEOUT", 12, 5, 600)
#: Nothing streams forever on a shared demo box, however attentive the client is.
MAX_LIFETIME = _env_int("SYMONEURAL_STREAMER_MAX_LIFETIME", 1800, 60, 21600)
#: A pump that has read this much has had its turn. Bounds egress independently of time.
MAX_SESSION_BYTES = _env_int("SYMONEURAL_STREAMER_MAX_BYTES", 4096, 64, 65536) * 1024 * 1024
#: Rolling window: 6 segments x ~2 s. Per session that is ~12 s of video on disk; at a heavy
#: 8 Mb/s that is about 12 MB, and the cap above bounds the total.
HLS_SEGMENT_SECONDS = 2
HLS_WINDOW = 6

PLAYLIST_NAME = "live.m3u8"
#: Anything served out of a session directory must match this. The directory holds only files
#: ffmpeg created with names we chose, so an allow-list of that exact shape is achievable, and
#: it means no request path is ever joined to a directory without first being proved to be a
#: plain filename.
SEGMENT_RE = re.compile(r"^s[0-9]{1,6}\.(ts|m4s)$")

FFMPEG = shutil.which("ffmpeg")

#: One HLS segment is buffered whole when it has to be decrypted -- CBC cannot be streamed into
#: ffmpeg block by block and still be unpadded correctly at the end. A 2 s segment at 8 Mb/s is
#: about 2 MB; 32 MB is room for a long segment at an absurd bitrate and a firm refusal for
#: anything that is not a segment at all.
MAX_SEGMENT_BYTES = 32 * 1024 * 1024


# ---------------------------------------------------------------- sniffing what arrived

def ts_sync_offset(data: bytes, packets: int = 3) -> int:
    """Offset of the first MPEG-TS packet in `data`, or -1 if there is no transport stream here.

    Not "does 0x47 appear": 0x47 is the letter `G`, so a check that loose calls every English
    web page a transport stream. A TS is a lockstep sequence of 188-byte packets each beginning
    with the sync byte, so the real test is that 0x47 recurs at exactly 188-byte spacing. Three
    packets is the conventional lock and is enough that a false positive needs a 377-byte
    coincidence.
    """
    span = 188 * (packets - 1)
    limit = min(188, len(data) - span)
    for off in range(max(0, limit)):
        if all(data[off + 188 * i] == 0x47 for i in range(packets)):
            return off
    return -1


_MARKUP_LEADS = (b"<!doctype", b"<html", b"<head", b"<body", b"<?xml", b"<!--", b"<h1", b"<div")
#: Content types a provider's error page arrives as. `application/json` is here because some
#: panels answer `{"error":"maximum connections reached"}` with a 200 and no other clue.
_TEXTY_TYPES = ("application/json", "application/xhtml+xml", "application/xml")


def looks_like_error_page(ctype: str, head: bytes) -> bool:
    """True when what arrived is a document about the stream rather than the stream.

    The whole defect this exists for: a provider answers a dead or over-subscribed channel with
    HTTP **200** and an HTML "stream offline" page. The old sniff only asked "is this HLS or
    does it start with 0x47", and anything else went to ffmpeg -- which spent ten seconds
    failing to demux a web page and reported "the transcoder could not stream-copy this source".
    That sentence describes our transcoder. The visitor needed to be told their channel is off.

    The test is deliberately **not** "the content type is texty". A very common misconfiguration
    is nginx serving real MPEG-TS as `text/html`, and a rule that trusted the header alone would
    turn every one of those working streams into a failure -- the exact inverse of the point.
    So: markup in the body is conclusive on its own, and a texty content type only counts when
    the body also fails to look like a transport stream.
    """
    lead = head.lstrip(b"\xef\xbb\xbf \r\n\t")[:64].lower()
    if lead.startswith(_MARKUP_LEADS):
        return True
    if head[4:8] in (b"ftyp", b"styp", b"moof", b"moov", b"sidx"):
        # An ISO-BMFF box header: a fragmented-MP4 HLS segment. It has no 0x47 sync pattern, so
        # a mislabelled one would otherwise be judged an error page on the strength of its
        # content type alone -- the same false positive the rule below exists to avoid.
        return False
    texty = ctype.startswith("text/") or ctype in _TEXTY_TYPES
    return bool(texty) and ts_sync_offset(head) < 0


# ---------------------------------------------------------------- codec reporting
#
# The HEVC failure is the nastiest one in this module because every indicator is green. ffmpeg
# stream-copies H.265 into TS segments happily, the playlist is written, the session says
# `live`, segments are served with 200s -- and no browser on earth decodes HEVC in MSE, so the
# visitor gets a black rectangle. There is nothing to fix in the pipeline; the only honest
# response is to say which codec arrived and let the page tell the visitor why it is blank.

#: What may be reported. ffmpeg's stderr is written by a program we do not control and can quote
#: its input, so the codec is not extracted as "whatever token followed `Video:`" -- it is
#: matched against this list and anything else is reported as nothing at all. That is what makes
#: a new field on `public()` unable to carry a credential.
VIDEO_CODECS = frozenset({
    "h264", "hevc", "mpeg2video", "mpeg4", "mpeg1video", "av1", "vp8", "vp9", "vc1", "wmv3",
    "h263", "mjpeg", "theora", "dirac", "msmpeg4v3", "prores", "dvvideo", "rawvideo", "flv1",
})
#: `[level]` markers come from `-loglevel level+info`; see `_spawn`. They can follow a component
#: tag (`[out#0/null @ 0x55…] [error] …`), so this is searched for, not anchored.
_LEVEL_RE = re.compile(r"\[(fatal|error|panic|warning|info|verbose|debug|trace)\]")
_VIDEO_RE = re.compile(r"Stream #\d+:\d+.*?:\s*Video:\s*([A-Za-z0-9_]+)")
#: The end of ffmpeg's input inventory. Searched, not anchored: `-loglevel level+info` prefixes
#: every line with `[info]`.
#:
#: A repair cannot be decided from the FIRST codec line, and the reason is a bug this avoided
#: rather than one it fixed. ffmpeg prints one `Stream #0:N` line per stream, so an HEVC/AC-3
#: channel announces its picture before its soundtrack. Deciding on the video line alone yields
#: "re-encode the picture, copy the audio" -- and since a session is only ever repaired once, the
#: AC-3 would then survive into the repaired stream and the channel would still be silent, or
#: black, with the streamer reporting that it had fixed it. Both codecs are known by the time this
#: marker appears, so the decision waits for it.
_DUMP_DONE_RE = re.compile(r"Stream mapping:|Output #\d")


def match_video_codec(line: str) -> str:
    """The video codec named in one ffmpeg log line, or "" -- allow-list only.

    Pure and separately testable on purpose: the security property here is that a fabricated
    stderr line cannot put arbitrary text into `Session.public()`, and that property is only
    checkable if the matcher can be handed a hostile line directly.
    """
    m = _VIDEO_RE.search(line or "")
    if not m:
        return ""
    token = m.group(1).lower()
    return token if token in VIDEO_CODECS else ""


#: Same rules as `VIDEO_CODECS`, for the audio side, and published by `public()` -- see the note
#: there. AC-3 and E-AC-3 are not merely the "video plays, no sound" complaint: an MSE build that
#: refuses the audio codec appends nothing at all, so the picture stops too, and the reading that
#: separates that from a broken streamer is this one.
AUDIO_CODECS = frozenset({
    "aac", "ac3", "eac3", "mp2", "mp3", "opus", "vorbis", "flac", "pcm_s16le", "dts", "truehd",
})
_AUDIO_RE = re.compile(r"Stream #\d+:\d+.*?:\s*Audio:\s*([A-Za-z0-9_]+)")


def _match_audio_codec(line: str) -> str:
    m = _AUDIO_RE.search(line or "")
    if not m:
        return ""
    token = m.group(1).lower()
    return token if token in AUDIO_CODECS else ""


# ---------------------------------------------------------------- codec repair
#
# Making a channel the browser cannot decode play, instead of only explaining why it does not.
#
# WHAT PLAYS IS AN ALLOW-LIST, AND THE POLARITY IS THE POINT. The obvious shape is a deny-list
# of known-bad codecs, and it was tried: a deny-list containing `mp2` shipped briefly on another
# branch and was reverted, because Chrome decodes mp2 perfectly and the list would have re-encoded
# -- and warned about -- channels that work. A deny-list is wrong in the direction that breaks
# working channels and silently passes codecs nobody thought of; an allow-list is wrong only in
# the direction of an unnecessary transcode, which costs CPU and nothing else.
#
# Both sets are MEASURED, not reasoned about, via `MediaSource.isTypeSupported()` on the Chrome in
# this repo's test path (Chrome 151) against `video/mp2t` and fMP4 -- the box serves TS and hls.js
# remuxes, so both containers have to be asked. Accepted: h264, aac, mp2, mp3. Refused: hevc,
# mpeg2video, vc1, av1, vp9, ac3, eac3, dts, truehd.
#
# THIS COMMENT USED TO CLAIM A GUARD THAT DOES NOT EXIST. It said `tests/tuner_codecs.mjs`
# re-asks the browser and fails if these two sets have drifted, "so this cannot rot into a
# claim". There is no such file and there never was -- the suites in `tests/` are
# streamer_failpaths, streamer_watch, streamer_guide and streamer_fake_provider. So the
# claim rotted in precisely the way it promised it could not, and the sets below are a
# 2026-08-19 reading of Chrome 151 that nothing re-measures. Treat them as dated, not
# enforced, until that suite is actually written.
PLAYABLE_VIDEO = frozenset({"h264"})
#: mp2 and mp3 are HERE, in the playable set, and that is the whole lesson of the reverted commit.
PLAYABLE_AUDIO = frozenset({"aac", "mp2", "mp3"})

#: `auto` repairs what needs repairing, preferring the video engine and falling back to CPU.
#: `cpu` never touches the GPU. `off` restores the old behaviour exactly -- stream copy or fail --
#: and exists because a new re-encode path in the middle of a working streamer deserves a kill switch
#: that does not require an edit to turn.
REPAIR_MODE = (os.environ.get("SYMONEURAL_STREAMER_REPAIR") or "auto").strip().lower()

#: A repaired stream needs about 515 MiB of VRAM (measured, flat across 1-4 concurrent streams).
#: Below this much free, the video engine is declined and CPU takes it: `libx264 veryfast` was
#: measured at 13.4x realtime on real 720p, so the fallback is comfortable rather than a
#: degradation, and stealing the last of the card from a model that is mid-answer is not.
VRAM_FLOOR_MIB = _env_int("SYMONEURAL_STREAMER_VRAM_FLOOR", 1024, 0, 16000)


@dataclass(frozen=True)
class RepairPlan:
    """How to make one session's codecs playable. `None` anywhere means "no repair needed"."""
    vargs: tuple[str, ...]
    aargs: tuple[str, ...]
    #: Short, fixed, published. Built from this module's own vocabulary, never from ffmpeg's text.
    reason: str
    uses_gpu: bool


def plan_repair(vcodec: str, acodec: str, nvenc: bool = False) -> RepairPlan | None:
    """The cheapest repair that makes `vcodec`/`acodec` playable, or None if they already are.

    Pure and separately testable, like `match_video_codec`, and for a similar reason: the
    interesting property is *which* streams get re-encoded, and that is only checkable if the
    decision can be asked directly instead of inferred from a running ffmpeg.

    An empty codec means "not detected yet" and never triggers a repair -- guessing from absence
    would re-encode every stream whose input dump had not arrived.
    """
    v_bad = bool(vcodec) and vcodec not in PLAYABLE_VIDEO
    a_bad = bool(acodec) and acodec not in PLAYABLE_AUDIO
    if not v_bad and not a_bad:
        return None
    # Audio is always re-encoded to AAC when it is the problem; there is no hardware path for it
    # and none is wanted -- measured at 34.4x realtime on real 720p for +0 MiB of VRAM.
    aargs = ("-c:a", "aac", "-b:a", "128k") if a_bad else ("-c:a", "copy")
    if not v_bad:
        # THE COMMON CASE, and the reason this is two tiers rather than one. The picture is
        # already h264; copying it through untouched costs nothing and keeps the stream-copy
        # guarantee for every frame the visitor actually sees.
        return RepairPlan(("-c:v", "copy"), aargs,
                          f"soundtrack re-encoded from {acodec} to aac", False)
    if nvenc:
        # No `-hwaccel cuda` and no `*_cuvid`: hardware decode measured 17.0x against 17.1x for
        # software decode at 720p, which is noise. The encoder is the bottleneck, so the flag
        # that buys nothing is left out rather than carried for looking thorough -- and software
        # decode accepts every codec on the input side, including the ones with no cuvid decoder.
        vargs = ("-c:v", "h264_nvenc", "-preset", "p4", "-b:v", "6M")
        gpu = True
    else:
        vargs = ("-c:v", "libx264", "-preset", "veryfast", "-b:v", "6M")
        gpu = False
    reason = f"picture re-encoded from {vcodec} to h264"
    if a_bad:
        reason += f", soundtrack from {acodec} to aac"
    return RepairPlan(vargs, aargs, reason, gpu)


_NVENC: bool | None = None


def _nvenc_available() -> bool:
    """Whether this ffmpeg has `h264_nvenc`. Asked once, lazily, and never at import.

    Not at import because this module is imported by the API at startup and a subprocess there is
    latency on every boot for a fact that is only needed the first time a channel needs repairing.
    """
    global _NVENC
    if _NVENC is None:
        if not FFMPEG:
            _NVENC = False
        else:
            try:
                out = subprocess.run([FFMPEG, "-hide_banner", "-encoders"],
                                     capture_output=True, timeout=10).stdout
                _NVENC = b"h264_nvenc" in out
            except Exception:
                _NVENC = False
    return _NVENC


def _vram_free_mib() -> int | None:
    """Free VRAM, or None if that cannot be determined -- which is not the same as zero.

    None means "no card, or nvidia-smi did not answer", and the caller treats it as "do not use
    the GPU" rather than "the GPU is empty".
    """
    smi = shutil.which("nvidia-smi")
    if not smi:
        return None
    try:
        out = subprocess.run([smi, "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
                             capture_output=True, timeout=5, text=True).stdout
        return int(out.strip().splitlines()[0].strip())
    except Exception:
        return None


def _may_use_video_engine() -> bool:
    """Whether the video engine is available *and* affordable right now.

    **This deliberately does not take a `gpu-governor.sh` lease, and that is a considered
    exception to "everything touching the GPU goes through the governor" rather than an
    oversight.** Two measurements decide it. First, NVENC and NVDEC are dedicated ASIC blocks:
    sampled while the `image` surface held the lock with compute at 67%, the encoder and decoder
    both read 0%, and sampled during a transcode, compute read 2% while the encoder read 50%.
    A transcode does not contend for what the governor arbitrates. Second, and this is the part
    that makes a lease actively harmful, a streamer session lives for as long as somebody watches --
    so a lease here would be held for a process lifetime, which is the one thing the governor's
    own rules forbid, and it would lock the CLI and every model out until the acquire timeout.

    What a transcode does contend for is VRAM, so that is what is checked, and the streamer yields
    rather than competing: below `VRAM_FLOOR_MIB` free it takes the CPU path.
    """
    if REPAIR_MODE == "cpu" or not _nvenc_available():
        return False
    free = _vram_free_mib()
    return free is not None and free >= VRAM_FLOOR_MIB


# ---------------------------------------------------------------- AES-128 HLS
#
# Encrypted HLS used to be refused outright, and the refusal was honest but it was also wrong
# about the facts: `cryptography` is present on this box as a Debian package, AES-128-CBC
# segment decryption is thirty lines, and a large share of ordinary IPTV -- not DRM, just a
# panel using the standard `#EXT-X-KEY:METHOD=AES-128` -- was being turned away by it. What is
# genuinely out of reach is SAMPLE-AES and anything with a KEYFORMAT, and those are still
# refused by name (see `SessionManager._reject_unsupported_encryption`).
#
# Imported lazily and tolerantly: if the package ever goes missing this module must still
# import and every unencrypted stream must still play. An encrypted one then gets the old
# honest refusal back, rather than an ImportError at request time.

def _aes_cbc_decrypt(key: bytes, iv: bytes, data: bytes) -> bytes:
    try:
        from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    except Exception:                                     # pragma: no cover - packaging
        raise StreamerError("this stream is AES-128 encrypted and the AES library is not "
                         "installed on this machine") from None
    dec = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
    return dec.update(data) + dec.finalize()


def _strip_pkcs7(plain: bytes) -> bytes:
    """Remove PKCS#7 padding if it is there, and leave the data alone if it is not.

    Lenient on purpose. The padding is only meaningful on the final block of a *complete*
    segment, and a live segment that was truncated in transit has no valid padding -- refusing
    it would drop a segment ffmpeg could otherwise have used most of. This is safe here only
    because the caller separately proves the decrypted bytes are a transport stream; on its own,
    lenient unpadding of a wrong-key decryption strips a random number of random bytes and
    reports success.
    """
    if not plain:
        return plain
    pad = plain[-1]
    if 1 <= pad <= 16 and len(plain) >= pad and plain[-pad:] == bytes([pad]) * pad:
        return plain[:-pad]
    return plain


def _decrypt_segment(blob: bytes, key: bytes, iv: bytes) -> bytes:
    if len(blob) % 16:
        # Not a judgement call: AES-CBC ciphertext is a whole number of blocks. A segment that
        # is not says the transfer was truncated or the segment was never encrypted.
        raise StreamerError("an encrypted HLS segment was not a whole number of AES blocks")
    return _strip_pkcs7(_aes_cbc_decrypt(key, iv, blob))


def _segment_iv(seg: HlsSegment) -> bytes:
    """The initialisation vector for one segment.

    RFC 8216 §5.2: if `#EXT-X-KEY` carries an `IV` attribute, use it; otherwise the media
    sequence number of the segment, as a 128-bit big-endian integer. Getting the fallback wrong
    is invisible -- it decrypts to noise exactly like a wrong key would.
    """
    raw = (seg.key.iv or "").strip().strip('"')
    if not raw:
        return seg.sequence.to_bytes(16, "big")
    if raw[:2].lower() == "0x":
        raw = raw[2:]
    try:
        iv = bytes.fromhex(raw)
    except ValueError:
        raise StreamerError("the HLS key IV is not hexadecimal") from None
    if len(iv) != 16:
        raise StreamerError(f"the HLS key IV is {len(iv)} bytes; AES-128-CBC needs 16")
    return iv


_TOKEN_OK = re.compile(r"[^A-Za-z0-9 ._:+/-]")


def _safe_token(text: str) -> str:
    """A third-party token made safe to put in a message shown to a visitor.

    METHOD and KEYFORMAT come out of a playlist written by somebody else. They are named in
    refusals because "encrypted with SAMPLE-AES" is a far more useful sentence than
    "encrypted", but they are not passed through as text.
    """
    return _TOKEN_OK.sub("", (text or ""))[:40] or "(unnamed)"


class StreamerError(Exception):
    """A session could not start or has failed. Messages are scrubbed before they get here."""


class StreamerBusy(StreamerError):
    """Every slot is taken. Distinct from StreamerError so the router can answer 503, not 400."""


@dataclass
class Session:
    id: str
    label: str                       # channel name, shown to the visitor. Never a URL.
    dir: Path
    created: float
    scrub: Scrubber
    policy: Policy
    url: str = ""                    # upstream. In memory only, never logged, never returned.
    proc: subprocess.Popen | None = None
    thread: threading.Thread | None = None
    stop: threading.Event = field(default_factory=threading.Event)
    last_seen: float = 0.0
    state: str = "starting"          # starting | live | ended | failed
    #: Our own failure text, and only ours. Every string assigned here comes from this package's
    #: own exception classes, whose messages are built from a fixed string plus `scheme://host:
    #: port` -- never from a path, never from an upstream library's message.
    error: str | None = None
    #: ffmpeg's stderr. **Internal.** Never returned to a client and never logged unscrubbed.
    #: Kept apart from `error` because it is the one string in this object whose contents are
    #: written by a program we do not control, and `public()` must have no such field: an M3U
    #: from an Xtream panel has the password in a *path segment*, and a session started from a
    #: pasted playlist has no credentials registered with its scrubber to catch it.
    transcoder_error: str | None = None
    bytes_in: int = 0
    mode: str = "direct"             # direct | hls  -- what the upstream turned out to be
    #: The video codec ffmpeg found on the input, or "". **Only ever a token from
    #: `VIDEO_CODECS`** -- see `match_video_codec`. That constraint is what lets it be published
    #: at all: it comes out of ffmpeg's stderr, which is the one string in this object written
    #: by a program we do not control, and an allow-listed token cannot be a credential.
    vcodec: str = ""
    #: The audio codec, same rules. Not currently published; see `public()`.
    acodec: str = ""
    #: What was re-encoded to make this playable, or "" for the stream-copy path most channels
    #: take. Published. Safe for the same reason `vcodec` is: it is built by `plan_repair` out of
    #: this module's own vocabulary plus an allow-listed codec token, never from ffmpeg's text.
    repair: str = ""
    #: The plan the stderr reader decided on and the pump thread has yet to apply. Handing it
    #: between threads as data is deliberate: only the pump thread ever touches `proc.stdin`, so
    #: only the pump thread swaps the process, and the reader never has to synchronise with it.
    pending_repair: RepairPlan | None = None
    #: One repair per session, ever. Without this a source whose codecs are re-announced mid-stream
    #: -- which happens on an ad insert -- would respawn ffmpeg on every announcement.
    repaired: bool = False

    def public(self) -> dict:
        """What a visitor may see. Deliberately has no field that could hold a credential.

        `error` is either one of our own origin-only messages or a fixed sentence. It is never
        ffmpeg's stderr and never an upstream library's exception text.

        `vcodec` and `acodec` are the two fields here whose values originate in ffmpeg's output,
        and they are safe for exactly one reason: they are not ffmpeg's text, they are tokens
        from `VIDEO_CODECS` / `AUDIO_CODECS` that ffmpeg's text was matched against. Anything
        unrecognised becomes "".

        The reason `vcodec` is published at all: a session can be `live`, with a playlist, with
        segments being served, and still show the visitor a black rectangle, because the stream
        is HEVC and no browser decodes HEVC in MSE. **A client must read `vcodec` even when
        `state == "live"`.** It is the only signal that separates "working" from "working, and
        unwatchable here".
        """
        error = self.error
        if error is None and self.state == "failed":
            error = "the transcoder could not stream-copy this source"
        return {
            "id": self.id,
            "label": self.label,
            "state": self.state,
            "error": error,
            "mode": self.mode,
            "vcodec": self.vcodec,
            # `acodec` IS published now, and the docstring above no longer says otherwise.
            #
            # It was parsed and withheld on the grounds that an unused field is a field nobody
            # is checking. That was the wrong call and a measured failure says so: a channel
            # reported `state: live`, `vcodec: h264`, 87 MB pulled from the provider over five
            # minutes and every indicator on the box green, while the browser decoded ZERO
            # frames and the page had nothing to say. An MSE build that will not take AC-3 --
            # `MediaSource.isTypeSupported('video/mp2t; codecs="avc1.42E01E,ac-3"')` is false
            # on the Chrome in this repo's test path -- fails to append the buffer, and a page
            # that can only see `vcodec` reports a perfectly healthy h264 stream over a black
            # rectangle. The audio codec was the missing half of that diagnosis.
            #
            # Same safety property as `vcodec`, for the same reason: this is not ffmpeg's text,
            # it is a token from `AUDIO_CODECS` that ffmpeg's text was matched against, and
            # anything unrecognised becomes "". A fabricated stderr line cannot get through it.
            "acodec": self.acodec,
            # What had to be re-encoded, or "" for the stream-copy path. Published because
            # `vcodec: hevc` on a picture that is now playing would otherwise read as a
            # contradiction: the field names what ffmpeg found on the INPUT, and after a repair
            # that is no longer what the browser is being handed. A client that shows a codec
            # warning must suppress it when this is non-empty, or it will apologise for a stream
            # that works -- which is the same false-warning failure the reverted acodec commit
            # would have shipped, arriving from the opposite direction.
            "repair": self.repair,
            "playlist": f"stream/{self.id}/{PLAYLIST_NAME}",
            "age_s": round(time.monotonic() - self.created, 1),
            "bytes_in": self.bytes_in,
            "idle_timeout_s": IDLE_TIMEOUT,
            "max_lifetime_s": MAX_LIFETIME,
            # How many segments the playlist actually lists, and how long each one runs.
            #
            # Published because `state == "live"` is not sufficient for a client that has to
            # decide when to start playing. A playlist file exists before it names a segment, so
            # a client handing it to a player at first sight gets a manifest with nothing in it.
            # And `segment_s` is the number nobody expects: `-hls_time 2` asks for 2 s segments,
            # but `-c copy` can only cut on a keyframe, so a source with a 10 s GOP yields 10 s
            # segments. A player that waits for three of those waits half a minute. It cannot
            # make that trade sensibly without being told the real duration.
            "segments": self.segment_count,
            "segment_s": self.segment_seconds,
        }

    @property
    def segment_count(self) -> int:
        """Segments named by the playlist -- not files on disk.

        The distinction matters: `hls_flags temp_file` means a segment exists as `.tmp` before it
        is renamed, and `delete_segments` removes it from disk while the playlist may still be
        being rewritten. The playlist is what a player reads, so the playlist is what is counted.
        """
        try:
            return sum(1 for ln in (self.dir / PLAYLIST_NAME).read_text().splitlines()
                       if ln.strip().endswith(".ts"))
        except OSError:
            return 0

    @property
    def segment_seconds(self) -> float:
        """Duration of the last segment the playlist names, from its own `#EXTINF`. 0 if none.

        Read rather than assumed. `HLS_SEGMENT_SECONDS` is what ffmpeg was asked for and is not
        what a stream-copied long-GOP source produces.
        """
        try:
            lines = (self.dir / PLAYLIST_NAME).read_text().splitlines()
        except OSError:
            return 0.0
        for ln in reversed(lines):
            if ln.startswith("#EXTINF:"):
                try:
                    return round(float(ln.split(":", 1)[1].split(",")[0]), 3)
                except (ValueError, IndexError):
                    return 0.0
        return 0.0

    @property
    def ready(self) -> bool:
        """True once ffmpeg has actually written a playlist -- the only honest readiness test.

        Not "the process started": ffmpeg exits nonzero several seconds later on a source it
        cannot copy, and reporting `live` in that window would be a status light that reflects
        nothing.
        """
        return (self.dir / PLAYLIST_NAME).is_file()


class SessionManager:
    def __init__(self, root: Path | None = None):
        self._root = Path(root) if root else None
        self._sessions: dict[str, Session] = {}
        # Reentrant: `start` reads the `root` property (which takes the lock to create the
        # directory lazily) from inside its own locked section. With a plain Lock that is a
        # deadlock on the first session, and only on the first session -- the worst kind.
        self._lock = threading.RLock()
        self._reaper: threading.Thread | None = None

    @property
    def root(self) -> Path:
        """Where segments live. Created on first session, never at import.

        Not `run/` -- that directory's contract is locks and pidfiles, and something clearing
        it while a surface holds the card is already a documented hazard here. Not
        `backend/output/` either, which is the render namespace served by `/api/gen/<name>`:
        HLS segments are not renders and this module has no business writing into a namespace
        somebody else owns. A private temporary directory, removed session by session.

        On most systems `/tmp` is tmpfs, so segments cost RAM rather than disk. That is bounded
        deliberately: `hls_list_size` x `hls_time` per session, times `MAX_SESSIONS`. Point
        `SYMONEURAL_STREAMER_DIR` at real disk if that trade is wrong for the box.
        """
        if self._root is None:
            with self._lock:
                if self._root is None:
                    self._root = Path(os.environ.get("SYMONEURAL_STREAMER_DIR")
                                      or tempfile.mkdtemp(prefix="symoneural-streamer-"))
        self._root.mkdir(parents=True, exist_ok=True)
        return self._root

    # ------------------------------------------------------------------ lifecycle

    def start(self, url: str, label: str, policy: Policy | None = None,
              scrub: Scrubber | None = None) -> Session:
        """Validate the source, take a slot, spawn ffmpeg, start pumping.

        The URL is validated *before* a slot is taken, so a hostile URL cannot occupy capacity
        while it fails.
        """
        if not FFMPEG:
            raise StreamerError("ffmpeg is not installed on this machine")
        policy = policy or Policy()
        # Whatever the caller registered, plus everything the URL itself hides. The caller
        # only has credentials to register on the Xtream path; a pasted M3U carries them in
        # the URL and tells us nothing.
        scrub = Scrubber.from_url(url, *(scrub._secrets if scrub else ()))
        # Fail fast and loudly on the SSRF check, before any resource is committed.
        try:
            safefetch.validate_url(url, policy)
        except BlockedURL as exc:
            raise StreamerError(scrub(str(exc))) from None

        self.reap()
        with self._lock:
            if len(self._sessions) >= MAX_SESSIONS:
                raise StreamerBusy(
                    f"all {MAX_SESSIONS} streamer slots are in use; try again shortly")
            sid = secrets.token_urlsafe(12)
            sdir = self.root / sid
            sdir.mkdir(parents=True, exist_ok=False)
            now = time.monotonic()
            s = Session(id=sid, label=label or "(unnamed)", dir=sdir, created=now,
                        scrub=scrub, policy=policy, url=url, last_seen=now)
            self._sessions[sid] = s

        try:
            s.proc = self._spawn(s)
        except Exception as exc:
            self._drop(sid)
            raise StreamerError(f"could not start the transcoder: {type(exc).__name__}") from None

        s.thread = threading.Thread(target=self._pump, args=(s,),
                                    name=f"streamer-pump-{sid}", daemon=True)
        s.thread.start()
        self._ensure_reaper()
        # The label is safe (it came from a playlist display name, not a URL) but it is visitor
        # data, so it is scrubbed and truncated before it is allowed into a log line.
        log.info("streamer: session %s started (%s)", sid, safefetch.redact(s.label)[:60])
        return s

    def _spawn(self, s: Session, plan: RepairPlan | None = None) -> subprocess.Popen:
        """Start ffmpeg for `s`. With no plan this is stream copy, which is what most channels get.

        `plan` is set only on the respawn described in `_apply_repair`, and it is the only thing
        that makes this process re-encode anything.
        """
        cmd = [
            FFMPEG, "-hide_banner", "-nostdin",
            # `level+info`, not `error`. `info` is what prints the input dump -- the
            # `Stream #0:0: Video: hevc` line that is the only way to find out that a stream
            # copying perfectly is one no browser can decode. `level+` prefixes every line with
            # its severity in brackets, which is what keeps `transcoder_error` meaning "the last
            # error" rather than "the last line ffmpeg printed"; without it, raising the
            # verbosity would have buried every real failure under progress output.
            "-loglevel", "level+info",
            # Input-side protocol allow-list. Binds to the input that follows, and means a
            # malformed or hostile stream cannot talk ffmpeg into opening a file or a URL.
            # There is no `file` and no `http` here on purpose.
            "-protocol_whitelist", "pipe,fd",
            "-fflags", "+genpts+discardcorrupt",
            "-analyzeduration", "5M", "-probesize", "5M",
            "-i", "pipe:0",
            # Stream copy FIRST, always, for every session -- and re-encoding only as a named,
            # published second attempt. This comment used to end "it never quietly re-encodes,
            # because the GPU belongs to inference and the CPU has a site to serve", and both
            # halves of that reason were measured and turned out to be wrong in a way worth
            # recording rather than deleting:
            #
            #   * the GPU does NOT belong to inference in the part that matters here. NVENC is a
            #     dedicated ASIC: during a transcode the encoder read 50% while CUDA compute read
            #     2%, and while inference held the card at 67% compute the encoder read 0%. The
            #     two do not contend, except for VRAM -- see `_may_use_video_engine`.
            #   * the CPU can serve the site and transcode. `libx264 veryfast` measured 13.4x
            #     realtime on a real 720p channel, so one stream costs well under a tenth of a
            #     core-hour per hour watched.
            #
            # What survives from the old promise is the word "quietly", and it is now the actual
            # guarantee: a re-encode is never silent. It happens only when the browser has been
            # measured unable to decode the source (`plan_repair`, an allow-list), it is announced
            # in `public()["repair"]`, and stream copy is still what every playable channel gets.
            *(plan.vargs + plan.aargs if plan else ("-c", "copy")),
            "-f", "hls",
            "-hls_time", str(HLS_SEGMENT_SECONDS),
            "-hls_list_size", str(HLS_WINDOW),
            # delete_segments is the disk bound; omit_endlist keeps the player at the live edge;
            # independent_segments lets a player start on any segment; temp_file stops a player
            # fetching a segment ffmpeg is still writing.
            "-hls_flags", "delete_segments+omit_endlist+independent_segments+temp_file",
            "-hls_allow_cache", "0",
            "-hls_segment_type", "mpegts",
            "-hls_segment_filename", str(s.dir / "s%05d.ts"),
            str(s.dir / PLAYLIST_NAME),
        ]
        # No URL and no credential appears anywhere in this argv -- see the module docstring.
        # stderr is a pipe rather than DEVNULL so a failure can be explained, and is drained by
        # a thread that scrubs every line before it is stored.
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                                stderr=subprocess.PIPE, start_new_session=True)
        threading.Thread(target=self._drain_stderr, args=(s, proc), daemon=True,
                         name=f"streamer-err-{s.id}").start()
        return proc

    def _drain_stderr(self, s: Session, proc: subprocess.Popen) -> None:
        """Read ffmpeg's stderr for two things: the codecs, and the last real error.

        ffmpeg quotes its input in some messages. Our input is `pipe:0`, so there should be no
        URL in there at all -- this runs the scrubber anyway, because "should be" is not a
        security control.

        Two separate extractions, and they are kept separate on purpose:

        * the **codec** is matched against `VIDEO_CODECS` and never taken as text, so a stream
          whose metadata is hostile cannot write into a published field;
        * `transcoder_error` keeps only lines marked `[error]`, `[fatal]` or `[panic]`. At
          `-loglevel error` every line was an error, so "last line" and "last error" were the
          same string. They no longer are, and a field that quietly became "frame= 40 fps=..."
          would have made every failure unexplainable.
        """
        try:
            for raw in iter(proc.stderr.readline, b""):
                text = raw.decode("utf-8", "replace").strip()
                if not text:
                    continue
                # Codec first: the input dump is `[info]`, so it must be read before the
                # severity filter throws info lines away.
                vcodec = match_video_codec(text)
                if vcodec and not s.vcodec:
                    s.vcodec = vcodec
                acodec = _match_audio_codec(text)
                if acodec and not s.acodec:
                    s.acodec = acodec
                # The input inventory is complete: decide whether this stream needs repairing.
                # Only a decision is made here -- the pump thread performs the swap, because it
                # owns `proc.stdin` and nothing else may write to it. `proc is s.proc` keeps the
                # drain thread of an already-replaced process from planning a second repair.
                if (REPAIR_MODE != "off" and not s.repaired and s.pending_repair is None
                        and proc is s.proc and _DUMP_DONE_RE.search(text)):
                    # `_may_use_video_engine` shells out to nvidia-smi, so it is only asked when
                    # the picture is the problem. The common repair is audio-only and must not pay
                    # for a GPU query it will not use.
                    v_bad = bool(s.vcodec) and s.vcodec not in PLAYABLE_VIDEO
                    s.pending_repair = plan_repair(
                        s.vcodec, s.acodec, _may_use_video_engine() if v_bad else False)
                m = _LEVEL_RE.search(text)
                if m and m.group(1) not in ("error", "fatal", "panic"):
                    continue
                line = s.scrub(_LEVEL_RE.sub("", text).strip())
                if line:
                    s.transcoder_error = line[:200]
        except Exception:
            pass
        finally:
            try:
                proc.stderr.close()
            except Exception:
                pass

    # ------------------------------------------------------------------ the pump

    def _pump(self, s: Session) -> None:
        """Read the upstream through the pinned client, write it into ffmpeg's stdin."""
        try:
            self._pump_inner(s)
            if s.state != "failed":
                s.state = "ended"
        except BlockedURL as exc:
            s.state, s.error = "failed", s.scrub(str(exc))
        except FetchError as exc:
            s.state, s.error = "failed", s.scrub(str(exc))
        except StreamerError as exc:
            s.state, s.error = "failed", s.scrub(str(exc))
        except BrokenPipeError:
            # ffmpeg went away. Its stderr says why and stays internal; the client gets a
            # sentence we wrote.
            s.state = "failed"
            s.error = "the transcoder exited before the stream ended"
        except Exception as exc:
            # Never surface the message: an arbitrary exception from a network stack can quote
            # the URL, and the URL is the credential.
            s.state, s.error = "failed", f"upstream error ({type(exc).__name__})"
        finally:
            try:
                if s.proc and s.proc.stdin:
                    s.proc.stdin.close()
            except Exception:
                pass

    def _account(self, s: Session, n: int) -> None:
        """Charge `n` bytes of ingress to the session and enforce the cap.

        Separate from `_write` because on the encrypted path bytes are *read* long before they
        are written: a segment is buffered whole, decrypted, then written. Charging on write
        there would let an unbounded amount of ciphertext through before the cap noticed.
        """
        s.bytes_in += n
        if s.bytes_in > MAX_SESSION_BYTES:
            raise StreamerError("session reached its data cap")

    def _apply_repair(self, s: Session) -> bool:
        """Swap ffmpeg for one that re-encodes. Called on the pump thread only. True if it swapped.

        Restarting the transcoder mid-stream sounds worse than it is, because of *which* streams
        get here: a session is only ever repaired when the browser has been measured unable to
        decode its codecs, so there is no working playback to interrupt. Whatever segments the
        copy attempt produced are unplayable by construction, which is why they are deleted rather
        than left for the playlist to reference.

        MPEG-TS is what makes this possible at all. It is a self-synchronising container -- the PAT
        and PMT recur every few hundred milliseconds -- so a fresh ffmpeg handed the middle of a
        transport stream finds its bearings without ever seeing the beginning. `ts_sync_offset`
        aligns the first write to a packet boundary to save it the work.
        """
        plan = s.pending_repair
        s.pending_repair = None
        if plan is None or s.repaired:
            return False
        old = s.proc
        # Close stdin first: ffmpeg then sees EOF and exits on its own, and a terminate that
        # arrives while it is mid-write to a segment is what leaves a half-written `.tmp` behind.
        try:
            if old and old.stdin:
                old.stdin.close()
        except Exception:
            pass
        if old:
            try:
                old.wait(timeout=2)
            except Exception:
                try:
                    old.kill()
                except Exception:
                    pass
        # Everything the copy attempt wrote refers to codecs the browser cannot decode. Removing
        # the playlist too means `ready` goes back to False, so a client polling `/tune` waits for
        # the repaired stream instead of being handed the broken one.
        try:
            for stale in list(s.dir.glob("s*.ts")) + list(s.dir.glob("s*.ts.tmp")):
                stale.unlink(missing_ok=True)
            (s.dir / PLAYLIST_NAME).unlink(missing_ok=True)
        except Exception:
            pass
        # A copy-path error ("could not stream copy this source") describes a process that no
        # longer exists. Keeping it would attach a stale explanation to a session that now works.
        s.transcoder_error = None
        s.repaired = True
        s.proc = self._spawn(s, plan)
        s.repair = plan.reason
        s.state = "starting"
        threading.Thread(target=self._drain_stderr, args=(s, s.proc), daemon=True,
                         name=f"streamer-err-{s.id}-repair").start()
        # The label is visitor data and is scrubbed; the reason is this module's own vocabulary.
        log.info("streamer: session %s repairing -- %s (%s)", s.id, plan.reason,
                 "video engine" if plan.uses_gpu else "cpu")
        return True

    def _write(self, s: Session, chunk: bytes) -> None:
        """Write upstream bytes straight through. Read and written are the same bytes here."""
        if s.pending_repair is not None and self._apply_repair(s):
            # The new ffmpeg is joining a transport stream in progress. Hand it a packet boundary.
            #
            # `> 0` and not `>= 0`, and above all not a bare slice: `ts_sync_offset` returns **-1**
            # when it cannot lock onto three consecutive packets, and `chunk[-1:]` would throw the
            # whole chunk away except its final byte -- a repair that destroyed the stream it was
            # repairing. -1 here means "too short to lock, or not a transport stream at all", and
            # in both cases the honest move is to pass the bytes through untouched and let ffmpeg,
            # which re-syncs for a living, decide what they are.
            off = ts_sync_offset(chunk)
            if off > 0:
                chunk = chunk[off:]
        s.proc.stdin.write(chunk)
        self._account(s, len(chunk))

    def _feed(self, s: Session, chunk: bytes) -> None:
        """Write bytes that were already charged as ingress (a decrypted segment)."""
        # No `ts_sync_offset` here: on the HLS path a chunk is a whole segment, which already
        # begins on a packet boundary.
        if s.pending_repair is not None:
            self._apply_repair(s)
        s.proc.stdin.write(chunk)

    @staticmethod
    def _read_a_little(resp) -> bytes:
        """A bit more of a response body, for an error excerpt. Never raises, never blocks long.

        `read1`, not `read`: `read(n)` waits for n bytes or EOF, so a provider dribbling its
        error page would hold this thread indefinitely. One underlying read is plenty for a
        sentence.
        """
        try:
            return resp.read1(safefetch.ERROR_BODY_BYTES)
        except Exception:
            return b""

    def _pump_inner(self, s: Session) -> None:
        resp, conn, target = safefetch.open_stream(s.url, s.policy)
        try:
            ctype = (resp.getheader("Content-Type") or "").split(";")[0].strip().lower()
            head = resp.read(4096)
            # An IPTV "stream URL" is about as likely to be an HLS playlist as a continuous
            # transport stream, and the extension lies often enough to be useless. Sniff:
            # MPEG-TS begins with the 0x47 sync byte, an HLS playlist begins with #EXTM3U.
            looks_hls = head.lstrip(b"\xef\xbb\xbf \r\n\t").upper().startswith(b"#EXTM3U") or \
                ctype in ("application/vnd.apple.mpegurl", "application/x-mpegurl",
                          "audio/mpegurl", "audio/x-mpegurl")
            if looks_hls:
                body = head + resp.read(s.policy.max_bytes)
                conn.close()
                s.mode = "hls"
                return self._pump_hls(s, target, body)

            # Not a playlist. Before assuming it is video, check whether the provider answered
            # with a page *about* the stream -- "channel offline", "maximum connections
            # reached", "subscription expired" -- which arrives with HTTP 200 more often than
            # with an error status. Feeding that to ffmpeg produces a ten-second wait and a
            # message about our transcoder, which is the wrong bug reported to the wrong person.
            if looks_like_error_page(ctype, head):
                said = safefetch.text_excerpt(head + self._read_a_little(resp), s.scrub)
                raise StreamerError(
                    f"the provider answered with a page, not a stream: {said}" if said
                    else "the provider answered with a web page, not a stream")

            s.mode = "direct"
            s.state = "live"
            self._write(s, head)
            while not s.stop.is_set():
                chunk = resp.read(65536)
                if not chunk:
                    return          # upstream EOF. No failover -- see the module docstring.
                self._write(s, chunk)
        finally:
            try:
                conn.close()
            except Exception:
                pass

    def _pump_hls(self, s: Session, target: safefetch.Target, body: bytes) -> None:
        """Follow an upstream HLS playlist, concatenating its segments into ffmpeg's stdin.

        Every playlist URL, every segment URL **and every AES key URI** goes back through
        `safefetch`, so the SSRF rules are re-applied to each one. A playlist is a list of URLs
        supplied by a third party and is exactly as untrusted as the URL the visitor typed.
        """
        pl = parse_hls(body.decode("utf-8", "replace"))
        if pl.is_master:
            # Prefer the highest bitrate that is not absurd for a shared box; if every variant
            # is above the ceiling take the smallest, rather than refusing to play anything.
            ceiling = 8_000_000
            under = [v for v in pl.variants if 0 < v.bandwidth <= ceiling]
            pick = (max(under, key=lambda v: v.bandwidth) if under
                    else min(pl.variants, key=lambda v: v.bandwidth or 1 << 62))
            body, ct, target = safefetch.fetch(target.join(pick.uri), s.policy)
            # The same check the direct path makes, for the same reason: a provider answering a
            # dead variant with an HTML page at 200 would otherwise surface as the far weaker
            # "upstream playlist contained no segments", which describes our parser rather than
            # their outage.
            if looks_like_error_page(ct, body[:4096]):
                said = safefetch.text_excerpt(body[:safefetch.ERROR_BODY_BYTES], s.scrub)
                raise StreamerError(
                    f"the provider answered with a page, not a playlist: {said}" if said
                    else "the provider answered with a web page, not a playlist")
            pl = parse_hls(body.decode("utf-8", "replace"))
        if not pl.segments:
            raise StreamerError("upstream playlist contained no segments")
        # Refuse unsupported encryption **before** committing to playback, not on reaching the
        # first segment we cannot handle -- a session that plays for two seconds and then dies
        # is harder to diagnose than one that never starts and says why.
        self._reject_unsupported_encryption(pl)
        keys: dict[str, bytes] = {}      # key URI -> the 16 bytes at the other end of it
        #: Key URIs whose output has been confirmed to be a transport stream. Per *key*, not
        #: once per session: HLS rotates keys mid-stream -- which is why `HlsKey` hangs off the
        #: segment -- so a single flag would check the first key and wave the second one
        #: through, and a wrong second key is exactly the silent corruption the check exists
        #: to prevent.
        checked: set[str] = set()

        # The absolute URL of the media playlist, kept as a string. Segment URIs and every
        # refresh resolve against *this*, not against whatever the last redirect left in
        # `target` -- refreshing a playlist by re-joining an empty reference is the kind of
        # thing that works until a provider serves the playlist from a redirect.
        playlist_url = target.join("")

        # Where to start reading. A live playlist should start near its live edge -- handing
        # ffmpeg the whole window only starts playback further behind. A playlist carrying
        # #EXT-X-ENDLIST is not live, it is a complete recording, and starting at its "live
        # edge" would silently skip everything but the last few seconds. That distinction cost
        # a smoke-test run to find: a 12 s VOD playlist played 4 s of itself.
        if pl.ended:
            next_seq = pl.segments[0].sequence
        else:
            next_seq = max(pl.segments[0].sequence, pl.segments[-1].sequence - 2)
        s.state = "live"
        deadline = time.monotonic() + MAX_LIFETIME

        while not s.stop.is_set() and time.monotonic() < deadline:
            for seg in [g for g in pl.segments if g.sequence >= next_seq]:
                if s.stop.is_set():
                    return
                # The key first, before a byte of the segment is fetched: a key server that is
                # down, or a key that is not 16 bytes, should fail before the bandwidth is
                # spent, and the failure should name the key rather than the segment.
                key = (self._segment_key(s, playlist_url, seg.key, keys)
                       if seg.key.encrypted else None)
                # Re-validated per segment: a playlist is a list of URLs written by a third
                # party and is exactly as untrusted as the one the visitor typed.
                resp, conn, _t = safefetch.open_stream(
                    safefetch.validate_url(playlist_url, s.policy).join(seg.uri), s.policy)
                try:
                    seg_ctype = (resp.getheader("Content-Type") or "").split(";")[0] \
                        .strip().lower()
                    first = resp.read(4096)
                    # A segment can be an error page too. A provider whose channel died between
                    # writing the playlist and serving the segment answers 200 with HTML, and
                    # that used to go straight into ffmpeg.
                    if looks_like_error_page(seg_ctype, first):
                        said = safefetch.text_excerpt(
                            first + self._read_a_little(resp), s.scrub)
                        raise StreamerError(
                            f"the provider answered a segment with a page: {said}" if said
                            else "the provider answered a segment with a web page")
                    if key is None:
                        self._write(s, first)
                        while True:
                            chunk = resp.read(65536)
                            if not chunk:
                                break
                            self._write(s, chunk)
                    else:
                        blob = bytearray()
                        self._account(s, len(first))
                        blob += first
                        while True:
                            chunk = resp.read(65536)
                            if not chunk:
                                break
                            # Charged on read: on this path the bytes are buffered before they
                            # are written, so charging on write would not bound ingress.
                            self._account(s, len(chunk))
                            blob += chunk
                            if len(blob) > MAX_SEGMENT_BYTES:
                                raise StreamerError("an HLS segment was implausibly large")
                        plain = _decrypt_segment(bytes(blob), key, _segment_iv(seg))
                        if seg.key.uri not in checked:
                            # A wrong key does not fail -- AES-CBC turns it into 16-byte blocks
                            # of noise, PKCS7 unpadding cheerfully strips a random tail, and
                            # ffmpeg receives garbage and reports that *it* could not read the
                            # source. Check the first segment of each key, so a key mismatch is
                            # reported as a key mismatch.
                            if ts_sync_offset(plain[:4096]) < 0:
                                raise StreamerError(
                                    "the segment did not decrypt to a transport stream; the "
                                    "HLS key does not fit this stream")
                            checked.add(seg.key.uri)
                        self._feed(s, plain)
                finally:
                    conn.close()
                next_seq = seg.sequence + 1
            if pl.ended:
                return
            # A live playlist gains a segment every target duration; polling faster than half
            # of that is load on someone else's server for no new data.
            if s.stop.wait(max(1.0, pl.target_duration / 2)):
                return
            body, _ct, _t = safefetch.fetch(playlist_url, s.policy)
            pl = parse_hls(body.decode("utf-8", "replace"))
            # Re-checked on every refresh, not only at the start: HLS rotates keys, and a
            # playlist that begins in the clear or in AES-128 can introduce SAMPLE-AES or a
            # KEYFORMAT halfway through. Checking once would leave that case decrypting
            # something it must not.
            self._reject_unsupported_encryption(pl)

    # ------------------------------------------------------------------ HLS encryption

    def _reject_unsupported_encryption(self, pl: HlsPlaylist) -> None:
        """Refuse, with the reason, anything we must not attempt to decrypt.

        This is an **allow-list on METHOD**, and that shape is the point. The obvious spelling
        -- "refuse SAMPLE-AES, decrypt everything else" -- routes `AES-256`, `SAMPLE-AES-CTR`
        and whatever a panel invents next into a CBC decryptor that will not fail, will produce
        noise, and will hand that noise to ffmpeg. Silent corruption replacing an honest refusal
        is a worse outcome than the refusal, and it is much harder to diagnose.

        The two cases worth naming:

        * **SAMPLE-AES** encrypts only the *payload* of certain NAL units and leaves the
          container in the clear. Decrypting the whole segment as one CBC stream destroys the
          parts that were never encrypted. It would look like it worked.
        * **KEYFORMAT other than `identity`** is DRM -- `urn:uuid:edef8ba9-...` is Widevine,
          `com.apple.streamingkeydelivery` is FairPlay -- and the METHOD still reads `AES-128`.
          The URI leads to a licence server, not to sixteen bytes of key.
        """
        for key in pl.keys:
            fmt = (key.keyformat or "identity").strip('"')
            if fmt.lower() != "identity":
                raise StreamerError(
                    "this stream is DRM-protected (" + _safe_token(fmt) + "); the streamer "
                    "decrypts plain AES-128 HLS only and will not pretend otherwise")
            if key.method != "AES-128":
                raise StreamerError(
                    f"this stream is encrypted with {_safe_token(key.method)}, which the streamer "
                    f"does not implement; it decrypts AES-128 only, because decrypting the "
                    f"others as if they were AES-128 produces corruption rather than an error")
            if not key.uri:
                raise StreamerError("this stream is AES-128 encrypted but names no key URI")

    def _segment_key(self, s: Session, playlist_url: str, key: HlsKey,
                     cache: dict[str, bytes]) -> bytes:
        """The 16 key bytes for one segment, fetched once per URI and then cached.

        The key URI is a URL supplied by a third party in a playlist and goes through
        `safefetch` like everything else -- a key URI pointing at `http://127.0.0.1:8800/` is
        the same SSRF as a segment URI pointing there. It is resolved against the *playlist*
        URL, not against whatever the last segment's redirects left behind.
        """
        if key.uri in cache:
            return cache[key.uri]
        key_url = safefetch.validate_url(playlist_url, s.policy).join(key.uri)
        body, _ct, _t = safefetch.fetch(key_url, s.policy)
        if len(body) != 16:
            raise StreamerError(f"the HLS key is {len(body)} bytes; AES-128 needs exactly 16")
        cache[key.uri] = body
        return body

    # ------------------------------------------------------------------ reaping

    def touch(self, sid: str) -> Session | None:
        s = self._sessions.get(sid)
        if s:
            s.last_seen = time.monotonic()
        return s

    def get(self, sid: str) -> Session | None:
        return self._sessions.get(sid)

    def list(self) -> list[Session]:
        return list(self._sessions.values())

    def stop_session(self, sid: str) -> bool:
        if sid not in self._sessions:
            return False
        self._drop(sid)
        return True

    def _drop(self, sid: str) -> None:
        with self._lock:
            s = self._sessions.pop(sid, None)
        if not s:
            return
        s.stop.set()
        proc = s.proc
        if proc and proc.poll() is None:
            try:
                proc.terminate()
                proc.wait(timeout=3)
            except Exception:
                try:
                    proc.kill()
                    # Reap it. Without this wait the child stays a zombie until the next
                    # garbage collection of the Popen object -- which on a long-lived API
                    # process is "eventually", and eventually is how a process table fills.
                    proc.wait(timeout=3)
                except Exception:
                    pass
        try:
            if proc and proc.stdin:
                proc.stdin.close()
        except Exception:
            pass
        shutil.rmtree(s.dir, ignore_errors=True)
        log.info("streamer: session %s reaped (%s, %.1f MB in)",
                 sid, s.state, s.bytes_in / 1048576)

    def reap(self) -> int:
        """Close sessions that are idle, expired, or whose transcoder has exited.

        Idleness is measured from the last *player* request, not from the last upstream byte:
        a source can keep sending long after the visitor closed the tab, and it is the tab
        closing that should free the slot.
        """
        now = time.monotonic()
        doomed = []
        for sid, s in list(self._sessions.items()):
            if now - s.last_seen > IDLE_TIMEOUT:
                doomed.append(sid)
            elif now - s.created > MAX_LIFETIME:
                doomed.append(sid)
            elif s.proc is not None and s.proc.poll() is not None:
                doomed.append(sid)
            elif s.state in ("ended", "failed") and now - s.created > 10:
                doomed.append(sid)
        for sid in doomed:
            self._drop(sid)
        return len(doomed)

    def _ensure_reaper(self) -> None:
        """Start the reaper on first use.

        Lazily, and never at import: the wiring engineer imports this module at module scope in
        `api.py`, and importing something should not spawn a background thread in a process that
        may never tune a channel.
        """
        if self._reaper and self._reaper.is_alive():
            return
        with self._lock:
            if self._reaper and self._reaper.is_alive():
                return
            self._reaper = threading.Thread(target=self._reap_loop, name="streamer-reaper",
                                            daemon=True)
            self._reaper.start()

    def _reap_loop(self) -> None:
        # 2 s, not 5. The tick is added to `IDLE_TIMEOUT` in the worst case, and on a
        # two-slot surface that latency is the difference between "busy" and "broken".
        # The loop costs a dict scan; there is nothing to save by sleeping longer.
        while True:
            time.sleep(2)
            try:
                if not self._sessions:
                    return          # nothing to watch; `_ensure_reaper` restarts us on demand
                self.reap()
            except Exception:       # pragma: no cover - a reaper that dies leaks processes
                log.exception("streamer: reaper iteration failed")

    def shutdown(self) -> None:
        for sid in list(self._sessions):
            self._drop(sid)


#: The process-wide manager. One per API process; sessions are in-memory, so a restart ends
#: every session, which is correct -- the segments went with the temporary directory.
MANAGER = SessionManager()
