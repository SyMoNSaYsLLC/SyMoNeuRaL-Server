#!/usr/bin/env python3
"""Invoke each runtime directly and check a known property of its output.

    python3 tools/runtime_probe.py                 # every probe
    python3 tools/runtime_probe.py --only llm      # one, by name
    python3 tools/runtime_probe.py --list

`tools/smoke.py` exercises **surfaces**. A surface passing tells you the chain worked; it
does not tell you which link is healthy, and it cannot test a runtime nothing routes to.
This runs the binaries.

## The three rules that make this different from `smoke.py`

**1. Production's environment, not this shell's.** `ops/RUNTIMES.tsv` and
`docs/ops/RUNTIMES.md` record the measurement that forces this: an interactive shell here
exports `LD_LIBRARY_PATH=/usr/local/cuda/lib64`, the systemd units export **none**, and
`LD_LIBRARY_PATH` outranks `DT_RUNPATH` in the loader's search order. So
`symoneural-diffuse` links CUDA **13.3** under systemd and **13.4** in a terminal. A probe
run from this shell would test a build production does not use. Every engine probe therefore
runs in `ENV_PROD` (`LD_LIBRARY_PATH` unset), and the CUDA engines run in `ENV_SHELL` as
well so the pair can be compared.

**2. Determinism is established within one environment before it is compared across two.**
A differing output hash between 13.3 and 13.4 means nothing if the same seed does not
reproduce byte-for-byte in one environment first. So each engine's probe runs twice in
`ENV_PROD` and only then once in `ENV_SHELL`. "Identical across both" is as much a result as
a divergence.

**3. `acquire`/`release`, never `gpu-governor.sh with`.** The `with` form's eviction arm is
`pkill -f 'bin/symoneural-llm'`, and `pkill -f` matches the whole command line -- so it
matches `bin/symoneural-llm-cli`, and it matches any argv that merely *contains* the engine
path, including the governor's own. `backend/sigils/render.py:16-27` records sixteen
consecutive renders dying at rc 143 to exactly that. This takes the lock, runs, and releases
from a `finally`.

## Skips are loud

A runtime that cannot be exercised here gets a row saying so and why. It is never dropped
from the list and never quietly passed: an unmeasured runtime is not a working one. Where
exercising a runtime would evict something production is serving, the probe **skips rather
than evicts** -- `run/resident` and the card are read before every acquire and recorded with
the result, because a mid-run eviction is a measurement condition rather than a fault.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import pathlib
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
from registry.lib import runtimes  # noqa: E402

GOVERNOR = ROOT / "scripts" / "gpu-governor.sh"

#: What systemd hands a unit: no LD_LIBRARY_PATH at all. Measured from /proc/<api pid>/environ.
ENV_PROD = "systemd (LD_LIBRARY_PATH unset)"
#: What an interactive shell on this box exports.
ENV_SHELL = "shell (LD_LIBRARY_PATH=/usr/local/cuda/lib64)"
SHELL_LD_PATH = "/usr/local/cuda/lib64"

#: Fixed everywhere a probe needs one, so a later run can be diffed against this one.
SEED = 42
IMAGE_SEED = 7

#: The governor surface these probes acquire under. Deliberately NOT one of the real surface
#: names: claiming to be `chat` would put a test process in the rack's "who holds the card"
#: readout. The consequence is recorded rather than worked around -- `probe` is unknown to
#: `surface_pattern()` and `evict()`, so it falls to the `*)` default and gets a patternless
#: `drain()`. On a card with a resident tenant that acquire is REFUSED, by design; the probe
#: reports the refusal and skips instead of evicting production.
PROBE_SURFACE = "probe"

#: A transient test port for the llm server probe. Deliberately not in ops/PORTS.tsv: that
#: registry is for ports something LISTENS on, and this binds for under a minute inside one
#: probe. Production's engine port is 8081 and is not touched.
LLM_PROBE_PORT = 8082


def env_for(which: str) -> dict[str, str]:
    e = {k: v for k, v in os.environ.items() if k != "LD_LIBRARY_PATH"}
    if which == ENV_SHELL:
        e["LD_LIBRARY_PATH"] = SHELL_LD_PATH
    return e


def run(argv: list[str], env: str = ENV_PROD, timeout: float = 120,
        cwd: pathlib.Path | None = None) -> tuple[int, str, str, float]:
    t0 = time.monotonic()
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout,
                           env=env_for(env), cwd=str(cwd or ROOT))
    except subprocess.TimeoutExpired:
        return 124, "", f"timed out after {timeout}s", time.monotonic() - t0
    except OSError as exc:
        return 127, "", f"{exc.__class__.__name__}: {exc}", time.monotonic() - t0
    return p.returncode, p.stdout, p.stderr, time.monotonic() - t0


# ---------------------------------------------------------------------------- card + lease

def card() -> dict[str, int]:
    rc, out, _, _ = run(["nvidia-smi", "--query-gpu=memory.used,memory.free",
                         "--format=csv,noheader,nounits"], timeout=30)
    if rc != 0:
        return {}
    used, free = (int(x) for x in out.strip().splitlines()[0].split(", "))
    return {"used_mib": used, "free_mib": free}


def resident() -> str:
    p = ROOT / "run" / "resident"
    return p.read_text().strip() if p.is_file() else "(none)"


class LeaseRefused(RuntimeError):
    """The governor would not hand over the card. Not a fault -- see the module docstring."""


class lease:
    """`acquire` on enter, `release` from a `finally`. Never the `with` subcommand.

    `SYMONEURAL_OWNER_PID` is this process, because the standalone `acquire` form exits
    immediately and would otherwise record a pid that is already dead -- which makes
    staleness detection break a live lock on its first poll.
    """

    def __init__(self, timeout: int = 20):
        self.timeout = timeout
        self.before: dict = {}

    def __enter__(self):
        self.before = {"card": card(), "resident": resident()}
        env = os.environ.copy()
        env["SYMONEURAL_OWNER_PID"] = str(os.getpid())
        p = subprocess.run([str(GOVERNOR), "acquire", PROBE_SURFACE, str(self.timeout)],
                           capture_output=True, text=True, timeout=self.timeout + 120, env=env)
        if p.returncode != 0:
            raise LeaseRefused(
                f"acquire rc={p.returncode} after ~{self.timeout}s. Card was "
                f"{self.before['card']}, run/resident={self.before['resident']!r}. "
                f"governor said: {p.stderr.strip().splitlines()[-1] if p.stderr.strip() else '(nothing)'}")
        return self

    def __exit__(self, *exc):
        subprocess.run([str(GOVERNOR), "release", PROBE_SURFACE],
                       capture_output=True, text=True, timeout=120)
        clear_probe_resident()
        return False


def clear_probe_resident() -> bool:
    """Remove `run/resident` if and only if it still names this probe. Returns whether it did.

    `cmd_acquire` writes `run/resident` and `cmd_release` leaves it -- correctly, since the
    weights usually ARE still resident and the next tenant needs to know whom to evict. But
    these probes unload everything before releasing, so leaving `probe` there hands the next
    real acquire a resident surface that does not exist AND is unknown to the governor.
    `surface_live("probe")` then falls to the `*)` pattern, `symoneural-llm/|symoneural-diffuse/`,
    and the outcomes are both wrong: either it matches nothing and logs a stale eviction, or it
    matches a genuinely live production engine and pkills BOTH engines to evict a surface that
    was never there.

    That is not the same as a normal `image` -> `chat` transition, where both names are
    registered and `surface_live` can give a real answer about a real tenant. This is the §1
    registry rule biting the tool that wrote it: an unregistered leaseholder gets the default
    arm, so it must not leave itself recorded.

    The `== PROBE_SURFACE` guard is the race: if a real surface acquired between the release
    and this call, the file names THEM, and removing it would be worse than leaving ours.
    """
    p = ROOT / "run" / "resident"
    try:
        if p.is_file() and p.read_text().strip() == PROBE_SURFACE:
            p.unlink()
            return True
    except OSError:
        pass
    return False


# ---------------------------------------------------------------------------- result record

PASS, FAIL, SKIP = "PASS", "FAIL", "SKIP"
RESULTS: list[dict] = []


def record(runtime: str, probe: str, status: str, why: str, **evidence) -> dict:
    r = {"runtime": runtime, "probe": probe, "status": status, "why": why,
         "evidence": evidence}
    RESULTS.append(r)
    mark = {PASS: "[PASS]", FAIL: "[FAIL]", SKIP: "[SKIP]"}[status]
    print(f"{mark} {runtime}/{probe}: {why}")
    for k, v in evidence.items():
        s = str(v)
        print(f"       {k} = {s if len(s) < 200 else s[:197] + '...'}")
    return r


# ---------------------------------------------------------------------------------- helpers

def png_info(path: pathlib.Path) -> dict:
    """Width, height and whether it is genuinely a PNG -- from the bytes, not the extension.

    §2 asks for the dimensions and validity rather than "bytes came back", because a
    zero-byte file and a JPEG both "came back".
    """
    b = path.read_bytes()
    if not b.startswith(b"\x89PNG\r\n\x1a\n"):
        return {"valid_png": False, "reason": f"bad signature: {b[:8]!r}", "bytes": len(b)}
    if b[12:16] != b"IHDR":
        return {"valid_png": False, "reason": "no IHDR where one must be", "bytes": len(b)}
    w, h = struct.unpack(">II", b[16:24])
    # The trailer proves the file is complete rather than a truncated write.
    return {"valid_png": True, "width": w, "height": h, "bytes": len(b),
            "ends_with_IEND": b.rstrip().endswith(b"IEND\xaeB`\x82"),
            "sha256": hashlib.sha256(b).hexdigest()}


def http(method: str, url: str, body: dict | None = None, timeout: float = 300) -> tuple[int, str]:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json"} if data else {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", "replace")
    except Exception as e:  # noqa: BLE001 -- a connection refused is a result, not a crash
        return 0, f"{e.__class__.__name__}: {e}"


# ------------------------------------------------------------------------------- the probes

def probe_llm_cli() -> None:
    """Fixed prompt, fixed seed, greedy. The check that 13.3 -> 13.4 did not move the numbers.

    **This is `symoneural-llm-cli`, not the binary production runs** -- production runs the
    `symoneural-llm` *server*, a different entry point over the same 23 libraries. The server
    is probed separately below; this one is here because a CLI with `--seed` and `--temp 0`
    is the cleanest determinism check available.

    The model is `symon-1.0-draft-0.5b-q4_k_m.gguf`, 0.4 GB, chosen for the reason the lease
    proof chose it: it fits in the headroom beside a resident engine, so this probe does not
    require an empty card and is therefore a test somebody will run twice.
    """
    cli = ROOT / "symoneural-llm" / "build" / "bin" / "symoneural-llm-cli"
    model = ROOT / "backend" / "models" / "llm" / "symon-1.0-draft-0.5b-q4_k_m.gguf"
    if not cli.is_file() or not model.is_file():
        record("symoneural-llm", "cli-fixed-seed", SKIP,
               "binary or draft model absent", cli=cli.is_file(), model=model.is_file())
        return

    prompt = "The capital of France is"
    argv = [str(cli), "-m", str(model), "-p", prompt, "-n", "16", "-s", str(SEED),
            "--temp", "0", "-ngl", "99", "--no-warmup", "-no-cnv", "-st"]

    def once(which: str) -> dict | None:
        rc, out, err, secs = run(argv, env=which, timeout=300)
        if rc != 0:
            return {"rc": rc, "err": err.strip()[-400:], "secs": round(secs, 2)}
        # The CLI echoes the prompt and then prints a PERFORMANCE FOOTER --
        # `[ Prompt: 877.2 t/s | Generation: 246.4 t/s ]` -- whose numbers differ on every
        # run by construction. The first version of this probe hashed the whole tail and
        # reported "SAME SEED PRODUCED DIFFERENT TEXT" when the words were character-for-
        # character identical and only the timings moved. That is the same false negative the
        # ravencalc probe hit on its `seconds` field, and it is the failure mode worth naming:
        # a determinism check that includes a timing can only ever fail.
        text = out
        idx = text.find(prompt)
        completion = text[idx + len(prompt):] if idx >= 0 else text
        completion = re.split(r"\n\s*\[\s*Prompt:", completion)[0]
        completion = completion.replace("Exiting...", "").strip()
        return {"rc": 0, "completion": completion, "secs": round(secs, 2),
                "sha256": hashlib.sha256(completion.encode()).hexdigest()[:16]}

    try:
        with lease():
            a = once(ENV_PROD)
            b = once(ENV_PROD)
            c = once(ENV_SHELL)
    except LeaseRefused as exc:
        record("symoneural-llm", "cli-fixed-seed", SKIP,
               "the governor refused the card -- NOT evicting production to run a probe",
               governor=str(exc))
        return

    if any(x is None or x.get("rc") != 0 for x in (a, b, c)):
        record("symoneural-llm", "cli-fixed-seed", FAIL,
               "the engine did not complete", prod_1=a, prod_2=b, shell=c)
        return

    same_env = a["completion"] == b["completion"]
    cross_env = a["completion"] == c["completion"]
    status = PASS if (same_env and a["completion"]) else FAIL
    record("symoneural-llm", "cli-fixed-seed", status,
           ("deterministic within production's environment, and identical across 13.4/13.4"
            if same_env and cross_env else
            "SAME SEED PRODUCED DIFFERENT TEXT -- see the two completions" if not same_env
            else "reproducible in one environment but the two environments disagree"),
           prompt=prompt, seed=SEED,
           completion=a["completion"],
           deterministic_same_env=same_env, identical_across_envs=cross_env,
           prod_run_1_sha=a["sha256"], prod_run_2_sha=b["sha256"], shell_run_sha=c["sha256"],
           seconds=[a["secs"], b["secs"], c["secs"]])


def probe_llm_server() -> None:
    """The binary production actually runs, on a transient port, with a seeded completion.

    `probe_llm_cli` tests a different entry point. This one starts `symoneural-llm` -- the
    same executable `backend/server.py` spawns -- and asks it for a completion with a fixed
    seed, so the report cannot read as "the production engine is deterministic" on the
    strength of a CLI run.
    """
    exe = ROOT / "symoneural-llm" / "build" / "bin" / "symoneural-llm"
    model = ROOT / "backend" / "models" / "llm" / "symon-1.0-draft-0.5b-q4_k_m.gguf"
    if not exe.is_file() or not model.is_file():
        record("symoneural-llm", "server-fixed-seed", SKIP, "binary or draft model absent")
        return

    def once(which: str) -> dict:
        argv = [str(exe), "-m", str(model), "-ngl", "99", "--host", "127.0.0.1",
                "--port", str(LLM_PROBE_PORT), "-c", "2048", "--no-warmup"]
        proc = subprocess.Popen(argv, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                env=env_for(which), cwd=str(ROOT))
        try:
            base = f"http://127.0.0.1:{LLM_PROBE_PORT}"
            for _ in range(120):
                if http("GET", base + "/health", timeout=2)[0] == 200:
                    break
                time.sleep(0.5)
            else:
                return {"up": False}
            code, body = http("POST", base + "/completion",
                              {"prompt": "The capital of France is", "n_predict": 16,
                               "seed": SEED, "temperature": 0.0}, timeout=120)
            if code != 200:
                return {"up": True, "http": code, "body": body[:300]}
            content = json.loads(body).get("content", "")
            return {"up": True, "http": 200, "content": content,
                    "sha256": hashlib.sha256(content.encode()).hexdigest()[:16]}
        finally:
            proc.terminate()
            try:
                proc.wait(timeout=30)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=30)

    try:
        with lease():
            a = once(ENV_PROD)
            b = once(ENV_PROD)
    except LeaseRefused as exc:
        record("symoneural-llm", "server-fixed-seed", SKIP,
               "the governor refused the card -- NOT evicting production to run a probe",
               governor=str(exc))
        return

    if not (a.get("http") == 200 and b.get("http") == 200):
        record("symoneural-llm", "server-fixed-seed", FAIL,
               "the production engine did not answer /completion", run_1=a, run_2=b)
        return
    same = a["content"] == b["content"]
    record("symoneural-llm", "server-fixed-seed", PASS if same and a["content"] else FAIL,
           "the production entry point answers and repeats itself on a fixed seed" if same
           else "the production entry point gave two different answers to one seed",
           port=LLM_PROBE_PORT, seed=SEED, content=a["content"],
           deterministic=same, run_1_sha=a["sha256"], run_2_sha=b["sha256"])


def probe_diffuse() -> None:
    """Fixed seed, twice in production's environment and once in the shell's.

    This is the probe amendment B exists for: this binary's RUNPATH pins CUDA 13.3 and the
    shell's `LD_LIBRARY_PATH` overrides it to 13.4, so the two runs genuinely execute against
    different CUDA runtimes. Asserting a valid PNG of the right dimensions rather than "bytes
    came back" is §2's own requirement; the sha256 is what makes the cross-environment
    comparison mean anything.
    """
    exe = ROOT / "symoneural-diffuse" / "build" / "bin" / "symoneural-diffuse"
    w = {"unet": "symoneural-image-unet-q4_k.gguf", "vae": "symoneural-image-vae.safetensors",
         "clip": "symoneural-image-clip.safetensors", "t5": "symoneural-image-t5-q8_0.gguf"}
    mdir = ROOT / "backend" / "models" / "image"
    missing = [k for k, v in w.items() if not (mdir / v).is_file()]
    if not exe.is_file() or missing:
        record("symoneural-diffuse", "fixed-seed-png", SKIP,
               f"binary or weights absent (missing: {missing})")
        return

    tmp = pathlib.Path(tempfile.mkdtemp(prefix="probe-diffuse-"))

    def once(which: str, tag: str) -> dict:
        out = tmp / f"{tag}.png"
        argv = [str(exe), "--diffusion-model", str(mdir / w["unet"]),
                "--vae", str(mdir / w["vae"]), "--clip_l", str(mdir / w["clip"]),
                "--t5xxl", str(mdir / w["t5"]),
                "-p", "a single grey cube on white", "--cfg-scale", "1.0",
                "--sampling-method", "euler", "--steps", "4", "-W", "256", "-H", "256",
                "--seed", str(IMAGE_SEED), "-o", str(out),
                "--backend", "te=cpu", "--vae-tiling", "--diffusion-fa"]
        rc, _o, err, secs = run(argv, env=which, timeout=600)
        if rc != 0 or not out.is_file():
            return {"rc": rc, "err": err.strip()[-400:], "secs": round(secs, 2)}
        return {"rc": 0, "secs": round(secs, 2), **png_info(out)}

    try:
        with lease():
            a = once(ENV_PROD, "prod1")
            b = once(ENV_PROD, "prod2")
            c = once(ENV_SHELL, "shell")
    except LeaseRefused as exc:
        record("symoneural-diffuse", "fixed-seed-png", SKIP,
               "the governor refused the card -- NOT evicting production to run a probe",
               governor=str(exc))
        return
    finally:
        shutil.rmtree(tmp, ignore_errors=True)

    ok = all(x.get("valid_png") and x.get("width") == 256 and x.get("height") == 256
             and x.get("ends_with_IEND") for x in (a, b, c))
    same_env = a.get("sha256") == b.get("sha256")
    cross_env = a.get("sha256") == c.get("sha256")
    if not ok:
        record("symoneural-diffuse", "fixed-seed-png", FAIL,
               "at least one render is not a complete 256x256 PNG",
               prod_1=a, prod_2=b, shell=c)
        return
    # "Identical across CUDA" is only a result if the two runs GENUINELY linked different
    # CUDA. Without this the claim is vacuous: both runs could have resolved the same tree
    # and the probe would still print "identical". Resolve the loader's actual answer in each
    # environment and put it in the record, so the reader can see the inputs differed.
    def cudart(which: str) -> str | None:
        _rc, o, _e, _s = run(["ldd", str(exe)], env=which, timeout=60)
        m = re.search(r"libcudart\.so\.\d+ => (\S+)", o)
        return m.group(1) if m else None

    linked = {"prod": cudart(ENV_PROD), "shell": cudart(ENV_SHELL)}
    if linked["prod"] == linked["shell"]:
        record("symoneural-diffuse", "fixed-seed-png", FAIL,
               "the two environments resolved the SAME libcudart, so the cross-CUDA "
               "comparison would have been vacuous", linked=linked)
        return

    record("symoneural-diffuse", "fixed-seed-png", PASS if same_env else FAIL,
           ("byte-identical on a fixed seed in production's environment, and "
            + ("the 13.4 shell run matches it too" if cross_env else
               "THE 13.4 SHELL RUN DIFFERS -- the CUDA minor changes the output bytes"))
           if same_env else "the same seed gave two different images in one environment",
           seed=IMAGE_SEED, size="256x256", steps=4,
           libcudart_prod=linked["prod"], libcudart_shell=linked["shell"],
           the_two_runs_linked_different_cuda=True,
           deterministic_same_env=same_env, identical_across_cuda=cross_env,
           prod_run_1_sha=a.get("sha256"), prod_run_2_sha=b.get("sha256"),
           shell_run_sha=c.get("sha256"),
           seconds=[a["secs"], b["secs"], c["secs"]],
           bytes_=[a["bytes"], b["bytes"], c["bytes"]])


def probe_listen_binary() -> None:
    """`SMOKE-listen-asr.md`'s own invocation, and its own expected sentence.

    The smoke names `engines/symoneural-listen/samples/jfk.wav`, a path from the retired
    layout; the file is at `symoneural-listen/samples/jfk.wav` now. Run in both environments
    as a CONTROL: this engine links no CUDA, so the two must agree, and if they ever do not
    the cross-environment comparisons elsewhere in this file are measuring something other
    than CUDA.
    """
    exe = ROOT / "symoneural-listen" / "build" / "bin" / "symoneural-listen"
    model = ROOT / "backend" / "models" / "whisper" / "symoneural-listen-base-en.bin"
    wav = ROOT / "symoneural-listen" / "samples" / "jfk.wav"
    if not all(p.is_file() for p in (exe, model, wav)):
        record("symoneural-listen", "jfk-wav", SKIP, "binary, weight or sample absent",
               binary=exe.is_file(), model=model.is_file(), sample=wav.is_file())
        return

    expected = ("and so my fellow americans ask not what your country can do for you "
                "ask what you can do for your country")

    def once(which: str) -> dict:
        rc, out, err, secs = run([str(exe), "-m", str(model), "-f", str(wav),
                                  "-t", "8", "-nt"], env=which, timeout=300)
        return {"rc": rc, "text": out.strip(), "secs": round(secs, 2),
                "err": err.strip()[-200:] if rc != 0 else ""}

    a = once(ENV_PROD)
    b = once(ENV_SHELL)

    def norm(s: str) -> str:
        return re.sub(r"[^a-z ]", "", s.lower()).strip()

    heard = norm(a["text"])
    correct = heard == expected
    record("symoneural-listen", "jfk-wav", PASS if correct else FAIL,
           "transcribed the sample correctly, word for word"
           if correct else "the transcript is not the sentence SMOKE-listen-asr.md recorded",
           audio_seconds=11.0, threads=8,
           transcript=a["text"],
           matches_smoke_record=correct,
           envs_agree=norm(a["text"]) == norm(b["text"]),
           seconds_prod=a["secs"], seconds_shell=b["secs"],
           realtime_factor=round(11.0 / a["secs"], 1) if a["secs"] else None)


def probe_listen_route() -> None:
    """The half that matters more: the live, unauthenticated route a visitor can reach.

    `/api/sigils/*` is included with `dependencies=[Depends(throttled_for("sigil"))]`
    (`api.py:3439`) and no token. This posts the same known WAV and checks the surface heard
    it, then states the throughput arithmetic amendment A asked for as measured numbers
    rather than as an assertion.
    """
    wav = ROOT / "symoneural-listen" / "samples" / "jfk.wav"
    if not wav.is_file():
        record("symoneural-listen", "live-route", SKIP, "sample absent")
        return
    code, body = http("GET", "http://127.0.0.1:8800/api/sigils/state", timeout=30)
    if code != 200:
        record("symoneural-listen", "live-route", SKIP,
               f"the API is not answering /api/sigils/state (HTTP {code})")
        return
    if not json.loads(body).get("inputs", {}).get("audio"):
        record("symoneural-listen", "live-route", SKIP,
               "the surface reports audio is not installed")
        return

    payload = {"audio_base64": base64.b64encode(wav.read_bytes()).decode(),
               "key": "green", "size": 512, "steps": 4, "seed": IMAGE_SEED}
    t0 = time.monotonic()
    code, body = http("POST", "http://127.0.0.1:8800/api/sigils/from-audio", payload,
                      timeout=600)
    secs = time.monotonic() - t0
    if code != 200:
        record("symoneural-listen", "live-route", FAIL,
               f"POST /api/sigils/from-audio returned {code}", body=body[:400],
               seconds=round(secs, 1))
        return
    doc = json.loads(body)
    heard = str(doc.get("heard") or doc.get("subject") or doc.get("prompt") or "")
    record("symoneural-listen", "live-route", PASS if "country" in heard.lower() else FAIL,
           "the live unauthenticated route transcribed and rendered"
           if "country" in heard.lower() else "the route answered but did not hear the words",
           http=code, seconds=round(secs, 1), heard=heard,
           response_keys=sorted(doc.keys()))


def probe_listen_cost() -> None:
    """Measured CPU cost per second of audio, and what the `sigil` bucket admits against it.

    Amendment A: *measure, do not assert*. This times the engine on the known 11.00 s sample
    and reports the ratio; the extrapolation to `MAX_AUDIO_BYTES` is stated with its
    assumption visible, because 25 MB of WAV and 25 MB of opus are very different amounts of
    audio and only one of them is arithmetic anybody can check.
    """
    exe = ROOT / "symoneural-listen" / "build" / "bin" / "symoneural-listen"
    model = ROOT / "backend" / "models" / "whisper" / "symoneural-listen-base-en.bin"
    wav = ROOT / "symoneural-listen" / "samples" / "jfk.wav"
    if not all(p.is_file() for p in (exe, model, wav)):
        record("symoneural-listen", "cost-vs-bucket", SKIP, "binary, weight or sample absent")
        return
    t0 = time.process_time()
    rc, _o, _e, wall = run([str(exe), "-m", str(model), "-f", str(wav), "-t", "8", "-nt"],
                           timeout=300)
    _ = time.process_time() - t0  # our own CPU, not the child's; the child's is below
    if rc != 0:
        record("symoneural-listen", "cost-vs-bucket", FAIL, "the engine failed", rc=rc)
        return

    audio_s = 11.0
    # 16 kHz mono 16-bit: two bytes a frame, plus a 44-byte canonical header. This is the
    # decoded form whisper consumes, which is what the cap has to be reasoned about in.
    wav_bytes_per_audio_s = 16000 * 2
    cap_bytes = 25 * 1024 * 1024
    max_audio_s_if_wav = cap_bytes / wav_bytes_per_audio_s
    engine_s_per_audio_s = wall / audio_s
    worst_engine_s = max_audio_s_if_wav * engine_s_per_audio_s
    per_min, per_hr = 20, 300

    record("symoneural-listen", "cost-vs-bucket", PASS,
           "measured; the arithmetic below is a reading plus one stated assumption",
           measured_wall_s_for_11s_audio=round(wall, 2),
           engine_seconds_per_audio_second=round(engine_s_per_audio_s, 3),
           threads_per_request=8,
           MAX_AUDIO_BYTES=cap_bytes,
           assumption="the upload is already 16 kHz mono 16-bit WAV, the LEAST audio 25 MB "
                      "can carry; a compressed container at the same cap carries far more",
           max_audio_seconds_at_cap_if_wav=round(max_audio_s_if_wav, 1),
           engine_seconds_for_one_max_request=round(worst_engine_s, 1),
           WHISPER_TIMEOUT_S=300,
           bucket_sigil=f"{per_min}/min, {per_hr}/hr, unauthenticated",
           serialised="NO -- listen.transcribe() is awaited BEFORE `async with _JOB` in "
                      "routes.py, and listen._spawn() has no semaphore",
           # Wall-seconds understate it: each request asks for 8 threads. Core-seconds is
           # the quantity the box actually has a fixed supply of, so that is the comparison.
           threads=8, cores_on_this_box=(os.cpu_count() or 0),
           core_seconds_demanded_per_minute=round(per_min * min(worst_engine_s, 300) * 8, 1),
           core_seconds_available_per_minute=(os.cpu_count() or 0) * 60,
           oversubscription=round(
               (per_min * min(worst_engine_s, 300) * 8) / max(1, (os.cpu_count() or 1) * 60), 1))


def probe_miner() -> None:
    """`-M <block>`: kawpow's own bounded hashing benchmark. No pool, no wallet, no shares.

    This is the only way to exercise the miner without connecting it to a pool, which would
    be mining rather than testing. It builds the DAG and hashes, so it is a real CUDA
    workload and takes the lease.
    """
    exe = ROOT / "symoneural-miner" / "build" / "kawpowminer" / "symoneural-miner"
    if not exe.is_file():
        record("symoneural-miner", "benchmark", SKIP, "binary absent", path=str(exe))
        return
    # `-M` is a CONTINUOUS mining test: it builds the DAG and then hashes until stopped. The
    # first version of this probe waited for it to exit and recorded rc=124 "timed out",
    # which said nothing about the miner and everything about the probe. Sample its output
    # for a bounded window, then stop it -- the reading is the hashrate, not the exit code.
    window_s = 90
    try:
        with lease(timeout=20):
            t0 = time.monotonic()
            proc = subprocess.Popen([str(exe), "-U", "-M", "22000"],
                                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                    text=True, env=env_for(ENV_PROD), cwd=str(ROOT),
                                    start_new_session=True)
            lines: list[str] = []
            try:
                while time.monotonic() - t0 < window_s:
                    line = proc.stdout.readline() if proc.stdout else ""
                    if not line:
                        if proc.poll() is not None:
                            break
                        continue
                    lines.append(line)
                    # Stop as soon as there is a real reading; no point hashing for 90 s.
                    if re.search(r"[\d.]+\s*[KMG]h/s", line) and len(lines) > 4:
                        break
            finally:
                proc.terminate()
                try:
                    proc.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=30)
            rc, secs = proc.returncode, time.monotonic() - t0
            blob = "".join(lines)
    except LeaseRefused as exc:
        record("symoneural-miner", "benchmark", SKIP,
               "the governor refused the card -- NOT evicting production to run a probe",
               governor=str(exc))
        return
    # kawpowminer colourises its status line and prints `52.81 Mh`, not `52.81 Mh/s`. The
    # first pattern here wanted `Mh/s` against raw ANSI-laden output and found nothing while
    # the miner was hashing at 52.8 MH/s in front of it -- a FAIL that was entirely the
    # probe's. Strip the escapes, then match the unit as the miner actually writes it.
    plain = re.sub(r"\x1b\[[0-9;]*m", "", blob)
    hashes = re.findall(r"([\d.]+)\s*([KMG])h\b", plain)
    device = re.search(r"\bcu(\d+)\b", plain)
    got_rate = bool(hashes) and any(float(v) > 0 for v, _ in hashes)
    record("symoneural-miner", "benchmark", PASS if got_rate else FAIL,
           "the miner initialised CUDA, built the DAG and reported a hashrate"
           if got_rate else "no hashrate in the output -- see the tail",
           note="`-M` runs until stopped; this samples it and terminates. rc is the signal it "
                "was stopped with, NOT a verdict -- the hashrate is the verdict.",
           rc=rc, seconds=round(secs, 1),
           hashrates=[f"{v} {u}H/s" for v, u in hashes[:4]],
           cuda_device=f"cu{device.group(1)}" if device else None,
           block=22000,
           tail=plain.strip()[-500:] if not got_rate else plain.strip()[-160:])


def probe_training_interpreter() -> None:
    """Does the training venv's cu128 torch actually reach this card?

    A real fine-tune is hours and is not a runtime test. This is the property that makes the
    training bay possible at all: a separate interpreter whose torch was built for Blackwell
    `sm_120`, doing one real device allocation and one real kernel. It takes the lease
    because it puts weights, however small, on the card.
    """
    py = ROOT / "training" / ".venv" / "bin" / "python"
    if not py.is_file():
        record("training", "torch-sm120", SKIP, "the training interpreter is absent",
               path=str(py))
        return
    # The kernel is checked against the SAME computation on the CPU, not merely run. "torch
    # imported and did not raise" is the fake-green here: a matmul that returns garbage
    # returns it without an exception.
    src = (
        "import json, torch\n"
        "d = {'torch': torch.__version__, 'cuda_built': torch.version.cuda,\n"
        "     'available': torch.cuda.is_available()}\n"
        "if d['available']:\n"
        "    d['device'] = torch.cuda.get_device_name(0)\n"
        "    d['capability'] = '.'.join(map(str, torch.cuda.get_device_capability(0)))\n"
        "    a = torch.arange(1024., dtype=torch.float64).reshape(32, 32)\n"
        "    cpu = float((a @ a).diagonal().sum().item())\n"
        "    gpu = float((a.cuda() @ a.cuda()).diagonal().sum().item())\n"
        "    d['cpu_trace'], d['gpu_trace'] = cpu, gpu\n"
        "    d['kernel_agrees_with_cpu'] = cpu == gpu\n"
        "print(json.dumps(d))\n")
    try:
        with lease(timeout=20):
            rc, out, err, secs = run([str(py), "-c", src], timeout=300)
    except LeaseRefused as exc:
        record("training", "torch-sm120", SKIP,
               "the governor refused the card -- NOT evicting production to run a probe",
               governor=str(exc))
        return
    if rc != 0:
        record("training", "torch-sm120", FAIL, "the training interpreter raised",
               rc=rc, err=err.strip()[-500:])
        return
    d = json.loads(out.strip().splitlines()[-1])
    # sm_120 is what Blackwell reports and what the cu128 wheel exists for. Checking the
    # capability rather than just `is_available()` is the difference between "torch imported"
    # and "torch can use THIS card".
    ok = (d.get("available") and d.get("capability", "").startswith("12")
          and d.get("kernel_agrees_with_cpu"))
    record("training", "torch-sm120", PASS if ok else FAIL,
           "the training venv's torch reaches this card and runs a kernel on it"
           if ok else "torch is present but did not reach the card at sm_12x",
           seconds=round(secs, 1), **d)


def probe_gateway() -> None:
    """The Rust binary the unit runs, exercised through its own forwarding path."""
    exe = ROOT / "backend" / "apps" / "gateway" / "target" / "release" / "symoneural-gateway"
    if not exe.is_file():
        record("symoneural-gateway", "forwarding", SKIP, "binary absent")
        return
    code, body = http("GET", "http://127.0.0.1:8000/api/status", timeout=30)
    direct, dbody = http("GET", "http://127.0.0.1:8800/api/status", timeout=30)
    same = code == direct == 200 and json.loads(body).get("schema") == json.loads(dbody).get("schema")
    record("symoneural-gateway", "forwarding", PASS if same else FAIL,
           "forwards /api/* to the monolith and the two answers agree"
           if same else "the gateway did not forward equivalently",
           gateway_http=code, direct_http=direct,
           note="the running unit, not a fresh invocation: starting a second gateway would "
                "collide on 8000")


def probe_web() -> None:
    """Go binary: its own stamped identity, plus the port it is actually serving."""
    exe = ROOT / "web" / "symoneural-web" / "build" / "symoneural-web"
    if not exe.is_file():
        record("symoneural-web", "version-and-serve", SKIP, "binary absent")
        return
    rc, out, err, _ = run([str(exe), "--version"], timeout=60)
    ver = (out + err).strip()
    code, _ = http("GET", "http://127.0.0.1:2019/config/", timeout=30)
    stamped = "git commit" in ver and "unknown" not in ver.split("git commit")[-1][:60]
    record("symoneural-web", "version-and-serve", PASS if rc == 0 and code == 200 else FAIL,
           "reports a stamped build and its admin API is live"
           if rc == 0 and code == 200 else "did not report a version or is not serving",
           version=ver.splitlines()[0] if ver else None,
           build_stamped_not_unknown=stamped,
           admin_api_http=code,
           note="the running unit answers 2019; this does not restart it")


def probe_ravencalc() -> None:
    """Start the split surface's own uvicorn on its registered port, ask it, stop it."""
    svc = ROOT / "backend" / "apps" / "ravencalc" / "service.py"
    if not svc.is_file():
        record("symoneural-ravencalc", "own-uvicorn", SKIP, "service absent")
        return
    from registry.lib import ports
    port = ports.port_of("ravencalc")
    if port is None:
        record("symoneural-ravencalc", "own-uvicorn", SKIP, "no port in ops/PORTS.tsv")
        return
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "ravencalc.service:app",
         "--host", "127.0.0.1", "--port", str(port), "--log-level", "warning"],
        cwd=str(ROOT / "backend"), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        env=env_for(ENV_PROD))
    try:
        base = f"http://127.0.0.1:{port}"
        for _ in range(60):
            if http("GET", base + "/healthz", timeout=2)[0] == 200:
                break
            time.sleep(0.5)
        else:
            record("symoneural-ravencalc", "own-uvicorn", FAIL,
                   f"never bound {port} within 30s")
            return
        # RavenCalc is the symbolic maths surface -- sympy, no GPU, no lease. An earlier
        # version of this probe posted a mining-calculator body on the strength of the name
        # and got a 422 from both; the two 422s were byte-identical, which was parity
        # evidence for the wrong reason. Read the schema, then ask a real question.
        # `operation` is a Literal enum: factor is NOT one of its members. Asking for it
        # is how the two 422s above happened.
        ask = {"expression": "x**2 + 2*x + 1", "operation": "differentiate",
               "variable": "x"}
        code, body = http("POST", base + "/api/ravencalc", ask, timeout=30)
        mono, mbody = http("POST", "http://127.0.0.1:8800/api/ravencalc", ask, timeout=30)
        # `seconds` is a timing, and the two processes will never agree on it -- 0.0176 vs
        # 0.0011 on the run that first caught this, because the split process was cold. A
        # strict byte comparison therefore fails on a surface whose CONTRACT is identical,
        # which is a false negative on the one property the split has to preserve. Compare
        # the contract, and name the field being excluded rather than hiding the exclusion.
        def contract(s: str) -> dict:
            d = json.loads(s)
            d.pop("seconds", None)
            return d

        same_contract = code == mono == 200 and contract(body) == contract(mbody)
        record("symoneural-ravencalc", "own-uvicorn", PASS if same_contract else FAIL,
               "its own process answers, and every field except the timing is identical to "
               "the monolith's inline route"
               if same_contract else "the split process and the monolith disagree",
               port=port, split_http=code, monolith_http=mono,
               identical_excluding=["seconds"],
               byte_identical=body == mbody,
               differing_fields=sorted(k for k in set(contract(body)) | set(contract(mbody))
                                       if contract(body).get(k) != contract(mbody).get(k)),
               result=json.loads(body).get("result", {}).get("text"),
               split_seconds=json.loads(body).get("seconds"),
               monolith_seconds=json.loads(mbody).get("seconds"))
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=20)
        except subprocess.TimeoutExpired:
            proc.kill()


def probe_clis() -> None:
    """The three interpreted runtimes, and the one that is part of the governor."""
    for name, argv, want in (
            ("symoneural-cli", [str(ROOT / "symoneural-code" / "bin" / "symoneural-cli"),
                                "--help"], "usage"),
            ("symoneural-code", [str(ROOT / "symoneural-code" / "bin" / "symoneural-code"),
                                 "--help"], "usage"),
            ("symoneural-audit", [str(ROOT / "symoneural-audit" / "bin" / "symoneural-audit"),
                                  "--help"], "usage")):
        exe = pathlib.Path(argv[0])
        if not exe.is_file():
            record(name, "invoke", SKIP, "absent", path=argv[0])
            continue
        rc, out, err, secs = run(argv, timeout=60)
        blob = (out + err).lower()
        record(name, "invoke", PASS if rc in (0, 1, 2) and want in blob else FAIL,
               "runs and describes itself" if want in blob else "did not run",
               rc=rc, seconds=round(secs, 2), first_line=(out + err).strip().splitlines()[0]
               if (out + err).strip() else None)


def probe_miner_core() -> None:
    """Its own smoke, which is the only executable it has. `--no-write`, loopback, no mining."""
    exe = ROOT / "symoneural-miner-core" / "bin" / "symoneural-miner-smoke"
    if not exe.is_file():
        record("symoneural-miner-core", "own-smoke", SKIP, "absent")
        return
    rc, out, err, secs = run([sys.executable, str(exe), "--no-write"], timeout=300)
    blob = out + err
    record("symoneural-miner-core", "own-smoke", PASS if rc == 0 else FAIL,
           "its pipeline smoke passes -- which is the pipeline, NOT the algorithm: "
           "docs/ALGORITHM-GAP.md states what is missing"
           if rc == 0 else "the smoke failed",
           rc=rc, seconds=round(secs, 1), tail=blob.strip()[-300:])


def probe_comfyui() -> None:
    """Declared and skipped, with the reason, rather than left out.

    Starting ComfyUI is a deliberate operator act: `scripts/symoneural-ui.sh` exists for it,
    nothing starts it at boot, and it is 8.1 GB of untracked tree that has not been started
    in this session. It also takes the `comfy` lease and holds it for as long as it is up.
    §2 says to skip loudly rather than quietly pass; this is that.
    """
    sh = ROOT / "scripts" / "symoneural-ui.sh"
    main = ROOT / "symoneural-ui" / "main.py"
    code, _ = http("GET", "http://127.0.0.1:8188/system_stats", timeout=5)
    record("symoneural-ui", "comfyui", SKIP,
           "NOT STARTED. Starting it is a deliberate operator act, not a probe: it is "
           "hand-started by design, holds the `comfy` lease for its whole uptime, and "
           "nothing routes to it today. The launcher and the entry point are both present "
           "and the tree is intact -- what is untested is whether it comes up.",
           launcher_present=sh.is_file(), entrypoint_present=main.is_file(),
           currently_listening_on_8188=(code == 200),
           how_to_test_it="scripts/symoneural-ui.sh start && curl -fsS "
                          "http://127.0.0.1:8188/system_stats && scripts/symoneural-ui.sh stop")


PROBES = {
    "llm-cli": probe_llm_cli,
    "llm-server": probe_llm_server,
    "diffuse": probe_diffuse,
    "listen-binary": probe_listen_binary,
    "listen-route": probe_listen_route,
    "listen-cost": probe_listen_cost,
    "miner": probe_miner,
    "training": probe_training_interpreter,
    "gateway": probe_gateway,
    "web": probe_web,
    "ravencalc": probe_ravencalc,
    "clis": probe_clis,
    "miner-core": probe_miner_core,
    "comfyui": probe_comfyui,
}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--only", action="append", choices=sorted(PROBES), default=None)
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--json", type=pathlib.Path, default=None)
    ap.add_argument("--cleanup", action="store_true",
                    help="clear a leftover run/resident naming this probe, and exit")
    a = ap.parse_args()
    if a.list:
        for k in sorted(PROBES):
            print(k)
        return 0
    if a.cleanup:
        print("cleared run/resident" if clear_probe_resident()
              else f"run/resident is {resident()!r} -- not ours, left alone")
        return 0

    print(f"card at start : {card()}")
    print(f"run/resident  : {resident()!r}")
    print(f"lock          : {'held' if (ROOT / 'run' / 'gpu.lock.d').exists() else 'free'}")
    print(f"registry      : {len(runtimes.rows())} rows in ops/RUNTIMES.tsv")
    print()

    for name in (a.only or list(PROBES)):
        PROBES[name]()
        print()

    # Belt and braces: every lease clears this on exit, but a probe killed mid-run would
    # not have, and the next real acquire is the one that pays for it.
    if clear_probe_resident():
        print("cleared a leftover run/resident naming this probe")
    print(f"card at end   : {card()}")
    print(f"run/resident  : {resident()!r}")
    p = sum(1 for r in RESULTS if r["status"] == PASS)
    f = sum(1 for r in RESULTS if r["status"] == FAIL)
    s = sum(1 for r in RESULTS if r["status"] == SKIP)
    print(f"\n{p} passed, {f} failed, {s} skipped")
    if s:
        print("skips, each with its reason:")
        for r in RESULTS:
            if r["status"] == SKIP:
                print(f"  {r['runtime']}/{r['probe']}: {r['why']}")
    if a.json:
        a.json.write_text(json.dumps(RESULTS, indent=2, default=str))
        print(f"\nwrote {a.json}")
    return 1 if f else 0


if __name__ == "__main__":
    raise SystemExit(main())
