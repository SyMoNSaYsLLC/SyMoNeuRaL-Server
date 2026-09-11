"""Drive one render, and give the card straight back.

The engine, the weights and the flags are **the image surface's**. This is not a second
image pipeline and must never become one: a second set of weights resident on a 15.92 GiB
card is the exact failure the GPU governor exists to prevent. What is different about a
sigil is the prompt suffix, the canvas and everything that happens *after* the card is
released.

`backend/api.py` cannot be imported from here -- it is the application, this is one of its
plug-ins, and importing upward would make the plug-in a dependency of its own host. So the
flags are copied, with their reasons, from **`backend/api.py:1736-1747`**. If that argv
changes, this one has to change with it; the provenance line is there so the next person
knows there are two copies rather than discovering it.

**How the lock is taken, and why not the way the rules recommend.** `.claude/CLAUDE.md`
prefers `gpu-governor.sh with <surface> -- <cmd>`, because that form releases from a trap
and so gives the card back even on a crash. **That form cannot run this engine, and the
reason is measured rather than theoretical.** Tested here on 2026-08-17 with `run/resident`
set to `image`:

    gpu-governor.sh with sigil -- /bin/sleep 2                    ->  rc 0
    gpu-governor.sh with sigil -- /bin/sleep 2 <path>/symoneural-diffuse      ->  rc 143, SIGTERM

`cmd_acquire` evicts the previous resident before handing over, and `evict()`'s `image)` arm
is `pkill -f 'bin/symoneural-diffuse'`. `pkill -f` matches the **whole command line**, and the wrapper's own
command line contains the engine path -- so the `with` form asks the governor to kill the
process that is running the governor. Sixteen consecutive renders died there, and the
failure is silent unless the exit status is read, because the eviction logs a success.

So the lock is taken the way `backend/api.py` already takes it, for a neighbouring reason
(that file cannot use `with` either -- wrapping a command that already holds the lock
self-deadlocks, and it only surfaced 120 s later as a job timeout):

* `acquire sigil`, then the engine, then `release sigil` from a `finally`, so an exception,
  a timeout and a cancellation all still give the card back;
* the release **names its surface**. A bare `release` once destroyed a running fine-tune's
  lock from a shutdown hook, and the governor refuses a mismatched claim -- but only when it
  is given a name to check. There is no bare release anywhere in this package;
* `SYMONEURAL_OWNER_PID` records *this* process, so if it dies while holding the card the
  next acquirer's staleness check breaks the lock instead of waiting out the full timeout;
* the hold covers **the job, not the process**. The engine is not resident between jobs, so
  the lock spans the render and nothing else. The matte, the encode and the write all happen
  after this returns, which is what stops a CPU post-process from keeping the next tenant
  off the card.

One thing to fix in the same commit that first writes `sigil` into `run/resident`: the
governor's `evict()` has a `case` per surface, and an unregistered name falls to `*)`, which
pkills `bin/symoneural-llm|bin/symoneural-diffuse` -- stopping a sigil render, and taking chat with it as
collateral. The arm to add, beside `image)`:

    sigil) pkill -f 'bin/symoneural-diffuse' 2>/dev/null || true ;;

Registering a surface name without its `case` is the same split contract as the generators'
BEGIN/END markers: two files have to change together or the mechanism silently half-works.
"""
from __future__ import annotations

import asyncio
import os
import pathlib
import subprocess
import time

# backend/apps/sigils/render.py -> backend/apps/sigils -> backend/apps -> backend -> root.
# This calculation has been wrong four times in this repo and it fails silently, because
# the wrong parent usually exists. Assert on something that only the real root has.
ROOT = pathlib.Path(__file__).resolve().parents[3]
assert (ROOT / "scripts" / "gpu-governor.sh").is_file(), (
    f"{ROOT / 'scripts' / 'gpu-governor.sh'} is not a file. Either that script is "
    f"missing, or ROOT is wrong (computed {ROOT}). Same wording as api.py:58 and the "
    "same reason: commissioning moved the script aside and the old message blamed the "
    "root, which was the one thing that was correct."
)

GOVERNOR = ROOT / "scripts" / "gpu-governor.sh"
#: Our diffusion engine, built by `tools/fork_engines.sh`. It was pointed into
#: `external/` -- a tree this project may not build or link -- which is what took
#: the sigil surface offline with every weight file present.
DIFFUSE_ENGINE = ROOT / "symoneural-diffuse" / "build" / "bin" / "symoneural-diffuse"
MODELS = ROOT / "backend" / "models" / "image"
#: Renders are API output. They go to backend/output/ and come back as /api/gen/<name>;
#: they never go to site/, which is the staging webroot the web server does not serve.
RENDERS = ROOT / "backend" / "output"

#: The governor surface name. Its own, not `image`: the log line, the queue accounting and
#: the rack's "who holds the card" display all key off this string, and folding it into
#: `image` would make the surface invisible in exactly the readout the site is built to be
#: honest about.
SURFACE = "sigil"

WEIGHTS = {
    "unet": MODELS / "symoneural-image-unet-q4_k.gguf",
    "vae": MODELS / "symoneural-image-vae.safetensors",
    "clip": MODELS / "symoneural-image-clip.safetensors",
    "t5": MODELS / "symoneural-image-t5-q8_0.gguf",
}

#: The product name for the engine. The site uses SyMoNeuRaL product names; the upstream
#: model identity is a licence matter recorded in LICENSES.md, not page copy.
MODEL_NAME = "SymonImage F1 q4_k"

#: Appended to the subject the caller asks for. This is the constraint that makes the whole
#: surface work, and it is not a hidden edit: "no background" alone produces nothing useful
#: because a diffusion model has no concept of absence -- it renders *something*. Naming a
#: flat field colour is what gives the key something to find. "no shadow" earns its place
#: too: a contact shadow keys out as a grey smear still attached to the subject.
#:
#: The page shows this text. A surface that rewrites your prompt and does not say so is
#: lying by omission, and this site's argument is that it does not do that.
SUFFIX = ("sticker illustration, single subject, centred, thick clean outline, "
          "flat vector shading, no scene, no shadow, no text, "
          "isolated on a solid flat {key} #{hex} background, no gradient")

KEY_HEX = {"magenta": "FF00FF", "green": "00FF00"}

#: The suffix for img2img, and it deliberately does **not** name a field colour.
#:
#: Measured on this box 2026-08-17, 768x768, seeds fixed, two photographic uploads, at
#: 4/8/12 steps and strengths 0.55-0.60: the engine never painted the requested magenta
#: field. The border came back grey every time (measured: 38,38,38 / 55,58,59 / 64,71,76 /
#: 67,71,71 / 151,154,149) because at the strengths where the upload still influences the
#: result, the upload's own background wins. Asking for a colour that never arrives would
#: put a promise in the prompt that the page then has to explain away, so the field clause
#: is dropped and the matte measures whatever background actually came out.
#:
#: "plain flat background" stays, because a plainer background keys better and that much the
#: engine does respond to.
REDRAW_SUFFIX = ("sticker illustration, single subject, centred, thick clean outline, "
                 "flat vector shading, no scene, no shadow, no text, "
                 "plain flat background, no gradient")


def compose(subject: str, key_name: str) -> str:
    """The prompt actually sent to the engine, exactly as the page displays it."""
    return f"{subject.strip()}, {SUFFIX.format(key=key_name, hex=KEY_HEX[key_name])}"


def compose_redraw(subject: str) -> str:
    """The img2img prompt. `subject` may be empty -- the upload is then the only subject."""
    subject = subject.strip()
    return f"{subject}, {REDRAW_SUFFIX}" if subject else REDRAW_SUFFIX


def weights_present() -> bool:
    return DIFFUSE_ENGINE.is_file() and all(p.is_file() for p in WEIGHTS.values())


def output_name(stamp_ms: int, seed: int) -> str:
    """The delivered filename, in `/api/gen/{name}`'s exact shape.

    That route matches `gen-\\d{13}-\\d{1,10}\\.png` against an attacker-controlled path
    segment, which is the right way to handle a string that lands in a filesystem path and
    must stay. It also means a sticker with a `sigil-` prefix would 404 on every single
    request. Two resolutions are acceptable and this is the cheaper one: emit the shape the
    route already serves, and change nothing in the surface that owns it. Picking a new
    prefix *silently* is the one option that is not acceptable.
    """
    return f"gen-{stamp_ms}-{seed}.png"


def raw_name(stamp_ms: int, seed: int) -> str:
    """The intermediate render: the subject still sitting on its field colour.

    Named deliberately outside `/api/gen`'s regex so it cannot be fetched even by guessing,
    and outside the `gen-*` glob the gallery prune walks so it never costs a real render its
    place in the retention window. It is unlinked as soon as the matte has read it.
    """
    return f"sigil-raw-{stamp_ms}-{seed}.png"


def build_argv(prompt: str, out: pathlib.Path, seed: int, steps: int, size: int,
               init: pathlib.Path | None = None,
               strength: float | None = None) -> list[str]:
    """The engine command line. Copied from `backend/api.py:1736-1747`, with its reasons.

    `--cfg-scale 1.0` and `--sampling-method euler` are what this distilled model wants;
    four steps is what it is distilled for. `--backend te=cpu` moves the text encoder to
    system RAM -- it runs once per prompt, so the PCIe cost is paid once rather than per
    step -- and `--vae-tiling` decodes in tiles. Without those two a 768x768 render dies in
    VAE decode: it wants a 3.7 GB compute buffer, and with the text encoder also resident
    there is nothing left.

    `init` and `strength` turn this into img2img for the image surface. Two measured facts
    about that pair, both surprising enough to be worth carrying here:

    * The engine quantises to `int(steps * strength)` denoise steps, so at four steps
      strengths 0.55 and 0.70 are the *same render* (both round to two) and 0.85 and 0.95
      are the same as each other. Verified by sha256 on the outputs.
    * At 0.85 the init image stops contributing at all: two entirely different uploads
      produced byte-identical PNGs. `upload.MAX_STRENGTH` caps below that, and the cap
      exists to stop the surface claiming to use a picture it is ignoring.
    """
    argv = [str(DIFFUSE_ENGINE),
            "--diffusion-model", str(WEIGHTS["unet"]), "--vae", str(WEIGHTS["vae"]),
            "--clip_l", str(WEIGHTS["clip"]), "--t5xxl", str(WEIGHTS["t5"]),
            "-p", prompt, "--cfg-scale", "1.0", "--sampling-method", "euler",
            "--steps", str(steps), "-W", str(size), "-H", str(size),
            "--seed", str(seed), "-o", str(out),
            "--backend", "te=cpu", "--vae-tiling", "--diffusion-fa"]
    if init is not None:
        argv += ["-i", str(init)]
        if strength is not None:
            argv += ["--strength", str(strength)]
    return argv


#: How long a render may wait for the card before giving up, mirroring the governor's own
#: ACQUIRE_TIMEOUT_S. A visitor waiting behind a fine-tune is told so; they are not left on
#: a spinner that explains nothing.
ACQUIRE_TIMEOUT_S = 300
#: How long the engine itself may run before it is killed. A wedged render must not hold
#: the card for the rest of the day. This is a structural cap on the machine, not a limit
#: on what may be asked for.
RENDER_TIMEOUT_S = 900


def acquire_argv(timeout: int = ACQUIRE_TIMEOUT_S) -> list[str]:
    return [str(GOVERNOR), "acquire", SURFACE, str(timeout)]


def release_argv() -> list[str]:
    """Always named. `release` on its own is the call that destroyed a fine-tune's lock."""
    return [str(GOVERNOR), "release", SURFACE]


class Busy(RuntimeError):
    """The card could not be had inside the acquire timeout."""


def _record_engine(pid: int) -> None:
    """Name the spawned process to the governor, so eviction signals it by identity.

    This file's own header records sixteen consecutive renders killed by
    `pkill -f`, which matched the governor wrapper's command line as readily as the engine's.
    A recorded pid cannot do that. Demonstrated again 2026-09-10: `pgrep -af` on the same
    engine patterns matched an interactive shell that merely mentioned them.

    No pgid is offered -- `_spawn` does not pass `start_new_session=True`, so this child
    shares the API's process group and signalling that group would signal the API. The
    governor re-checks and would refuse it anyway; not sending it says so at the source.

    Best-effort: losing this costs the identity path, not the render.
    """
    try:
        subprocess.run([str(GOVERNOR), "engine", str(pid)],
                       capture_output=True, timeout=10, check=False)
    except Exception:  # noqa: BLE001 -- never fail a render over a bookkeeping call
        pass


async def _spawn(argv: list[str], timeout: float, env: dict | None = None
                 ) -> tuple[int, bytes]:
    proc = await asyncio.create_subprocess_exec(
        *argv, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.PIPE,
        env=env)
    _record_engine(proc.pid)
    try:
        _out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except (asyncio.TimeoutError, asyncio.CancelledError):
        proc.kill()
        await proc.wait()
        raise
    return proc.returncode or 0, err or b""


async def run(argv: list[str], timeout: float = RENDER_TIMEOUT_S,
              acquire_timeout: int = ACQUIRE_TIMEOUT_S) -> tuple[int, bytes, float, float]:
    """Take the card, run one render, give the card back.

    Returns `(returncode, stderr, wait_seconds, render_seconds)`. The two times are kept
    apart deliberately: waiting behind another tenant is a queue figure and has nothing to
    do with how fast this box renders, and reporting their sum as a render time would be a
    measured number that means something other than what it says.

    Raises `Busy` if the acquire times out. The release is in a `finally`, so the card comes
    back on a failed render, a timeout, and a cancelled request alike.
    """
    waited = time.monotonic()
    env = {**os.environ, "SYMONEURAL_OWNER_PID": str(os.getpid())}
    rc, err = await _spawn(acquire_argv(acquire_timeout), acquire_timeout + 15, env)
    wait_s = time.monotonic() - waited
    if rc != 0:
        raise Busy(err.decode("utf-8", "replace").strip()[-300:] or "the GPU is busy")
    started = time.monotonic()
    try:
        try:
            rc, err = await _spawn(argv, timeout)
        except asyncio.TimeoutError:
            return 124, b"the render exceeded its time budget", wait_s, time.monotonic() - started
    finally:
        # Named, and unconditional. The card is not left held because the engine failed.
        await _spawn(release_argv(), 120)
    return rc, err, wait_s, time.monotonic() - started
