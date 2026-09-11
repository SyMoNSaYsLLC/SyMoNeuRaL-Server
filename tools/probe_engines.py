#!/usr/bin/env python3
"""Audit every runtime engine: artefact identity, announced identity, real work.

Five engines live in their own top-level directories -- `symoneural-llm/`,
`symoneural-diffuse/`, `symoneural-listen/`, `symoneural-miner/`, `symoneural-ui/`
-- promoted out of `engines/` on 2026-09-08. `ProjectStatus.md` records that three are
first-party and one is not, and — this is the gap this tool exists to close —
that `symoneural-diffuse` has *"artefacts; identity not audited"*. Identity was
audited once, by hand, on one engine: `aa1bdff2` found the language server
announcing `Server: llama.cpp` on every HTTP response and `owned_by: llamacpp` in
`/v1/models`, and fixed both. Nothing has asked the same question of the others.

So this asks it of all of them, and it asks it in the three places an answer can
live:

  * **Artefact identity** — path, byte size, SHA-256, and what `--version` says.
    A rebuilt engine that lost its version string is a different artefact than the
    one a report was written about.
  * **Announced identity** — what a user or a client is TOLD. `--version` output,
    `--help` text, and for a serving engine the HTTP `Server` header and the model
    ownership fields. This is where `aa1bdff2`'s defect lived and it is the half
    that matters: an internal symbol nobody reads is not a claim, and a help page
    that names somebody else's project is.
  * **Real work** — a measurement, not a smoke test. Transcription speed as a
    realtime factor for the ASR engine; render wall-clock for diffusion; and for
    the language engine, a pointer to `tools/bench_llm.py`, which measures it
    properly rather than badly a second time.

## Project names versus library vocabulary

The scan separates two things that a naive grep for "ggml" would merge, and the
distinction decides whether a hit is a finding:

  **project identity** — `llama.cpp`, `whisper.cpp`, `stable-diffusion.cpp`,
  `ComfyUI`, a `github.com/<upstream>` URL, an upstream author's name. Announced to
  a user, these say the product is somebody else's. That is the `aa1bdff2` defect.

  **library and format vocabulary** — `ggml`, `gguf`, `ggml_conv2d_direct`. These
  are the names of a tensor library's API and of an on-disk format, and they turn
  up in flag descriptions because the flag really does control
  `ggml_conv2d_direct`. Renaming a function in a help string would make the help
  wrong. Reported separately, and not as findings.

`backend/models/PROVENANCE.json` is the sanctioned place upstream attribution
lives, and none of this argues for erasing it — `test_weight_names.py` already
enforces that every house name records where it came from. The question here is
narrower: what does the engine SAY IT IS when something asks.

    python3 tools/probe_engines.py                 # full audit
    python3 tools/probe_engines.py --no-work        # identity only, no measurement
    python3 tools/probe_engines.py --no-sha         # skip artefact digests
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
API = "http://127.0.0.1:8800"

#: Fields excluded from the serving-surface scan, each because the codebase has
#: already decided the question and decided it in writing.
#:
#: `chat_template` carries the GGUF's own Qwen fallback -- *"You are Qwen, created
#: by Alibaba Cloud"* -- and `api.py:2823-2834` argues the position at length: it
#: *"is truthful upstream provenance for the weights and it stays in the file; what
#: must never happen is the PRODUCT presenting it to a user as its own identity"*,
#: which is enforced one layer up by always sending a system prompt. An earlier
#: revision of this tool reported that string as an identity finding. It is not a
#: finding, it is a decision, and a prober that relitigates settled decisions
#: teaches its reader to skim the findings list.
SERVING_SCAN_EXCLUDE = ("chat_template", "chat_template_caps", "media_marker")

#: Names that assert whose product this is. Where one of these turns up decides
#: nothing on its own -- `tier_of()` decides, from WHERE it turned up.
PROJECT_NAMES = (
    "llama.cpp", "whisper.cpp", "stable-diffusion.cpp", "ComfyUI", "comfyanonymous",
    "ggerganov", "ggml-org", "leejet", "Alibaba Cloud", "black-forest-labs",
    "github.com/ggml", "github.com/leejet", "github.com/comfy",
)

#: Names that are a library API or an on-disk format rather than a claim of
#: authorship. Counted and shown, never reported as a finding. `ggml_conv2d_direct`
#: is the function a flag controls; renaming it in the help text would make the help
#: text wrong, which is a worse outcome than naming a dependency.
VOCABULARY = ("ggml", "gguf", "GGUF", "cuBLAS", "cuDNN")

#: Where a name was found decides what it means, and collapsing these three into
#: one verdict is what made the first run of this tool wrong twice.
#:
#:   `authorship`  the banner, the `--version` line, the HTTP `Server` header, a
#:                 model-ownership field. A third-party name HERE says the product
#:                 is somebody else's. This is the `aa1bdff2` class and the only
#:                 tier reported as a finding.
#:   `reference`   a third-party name inside a flag description, a URL, or an
#:                 interop mode value. `--rng ... cpu(comfyui)` names the project
#:                 whose RNG behaviour that mode reproduces; it is an interop label,
#:                 not a claim of authorship, and renaming it would make the flag
#:                 lie about what it does. Listed for a human to judge, because the
#:                 line between "names a dependency" and "calls itself by their
#:                 name" is a reading and not a regex -- `--completion-bash: print
#:                 source-able bash completion script for llama.cpp` sits right on
#:                 it, since the script is for THIS program.
#:   `embedded`    symbols and strings inside the artefact. Not user-visible, and
#:                 never a finding.
TIERS = ("authorship", "reference", "embedded")


def tier_of(where: str) -> str:
    return "authorship" if where in ("version", "server_header", "model_owner") \
        else "reference"

ENGINES = (
    {"id": "symoneural-llm", "binary": "symoneural-llm",
     "role": "language model serving on the RTX 5070 Ti",
     "version_flag": "--version", "help_flag": "--help",
     "serving": "http://127.0.0.1:8081"},
    {"id": "symoneural-diffuse", "binary": "symoneural-diffuse",
     "role": "diffusion image generation on the RTX 5070 Ti",
     "version_flag": "--version", "help_flag": "--help", "serving": None},
    {"id": "symoneural-listen", "binary": "symoneural-listen",
     "role": "speech recognition, CPU only",
     "version_flag": None, "help_flag": "--help", "serving": None},
    # `bindir` because this one does not build into build/bin: the vendored
    # kawpowminer CMake project puts its executable in build/kawpowminer/. The
    # spec used to say `binary: None` with a note asserting "no built binary
    # under build/bin", which was written on 2026-09-07 -- three days after
    # f5f0a7e4 built it -- and was true of the path, not of the engine. A probe
    # that reports a built engine as missing is worse than no probe.
    {"id": "symoneural-miner", "binary": "symoneural-miner",
     "bindir": "kawpowminer",
     "role": "mining control: GPU, ASIC and settlement", "serving": None,
     "version_flag": "--version", "help_flag": "--help"},
    {"id": "symoneural-ui", "binary": None,
     "role": "graph and workflow editor", "serving": None,
     "note": "vendored ComfyUI, and the one runtime ProjectStatus.md already "
             "records as NOT first-party. Its identity is not a finding here "
             "because it is a known, recorded position rather than a discovery."},
)


# --------------------------------------------------------------------------- helpers

def sha256(path: Path, chunk: int = 1 << 22) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while block := f.read(chunk):
            h.update(block)
    return h.hexdigest()


def run(argv: list[str], timeout: int = 30) -> str:
    """Combined stdout and stderr: engines put their banner on either."""
    try:
        p = subprocess.run(argv, capture_output=True, text=True, timeout=timeout)
        return (p.stdout or "") + (p.stderr or "")
    except subprocess.TimeoutExpired:
        return "<timed out>"
    except Exception as exc:
        return f"<{type(exc).__name__}: {exc}>"


def scan(text: str, needles: tuple[str, ...]) -> dict:
    """Which needles appear, and one example line for each.

    A line rather than an offset: the finding has to be readable by whoever fixes
    it, and "the help text says this" is actionable in a way that "byte 41,882" is
    not.
    """
    hits: dict[str, str] = {}
    for line in text.splitlines():
        for n in needles:
            if n.lower() in line.lower() and n not in hits:
                hits[n] = line.strip()[:160]
    return hits


def binary_strings(path: Path, limit: int = 220_000_000) -> str:
    """Printable runs out of the artefact, for the embedded-name count.

    Read here rather than shelled out to `strings`, so the tool has no dependency
    on binutils being installed and cannot be silently defeated by its absence.
    Embedded names are reported as a COUNT and are explicitly not findings: a
    symbol in a `.so` is not something the product says to anybody.
    """
    raw = path.read_bytes()[:limit]
    return "\n".join(m.group().decode("ascii", "replace")
                     for m in re.finditer(rb"[\x20-\x7e]{6,}", raw))


def gpu_used_mib() -> int | None:
    exe = shutil.which("nvidia-smi")
    if not exe:
        return None
    out = run([exe, "--query-gpu=memory.used", "--format=csv,noheader,nounits"])
    try:
        return int(out.strip().splitlines()[0])
    except Exception:
        return None


# --------------------------------------------------------------------------- per engine

def audit_identity(spec: dict, do_sha: bool) -> dict:
    out: dict = {"id": spec["id"], "role": spec["role"]}
    if spec["binary"] is None:
        out["built"] = False
        out["note"] = spec.get("note", "")
        return out

    path = ROOT / spec["id"] / "build" / spec.get("bindir", "bin") / spec["binary"]
    out["built"] = path.is_file()
    if not out["built"]:
        out["note"] = f"declared binary absent at {path.relative_to(ROOT)}"
        return out
    out["path"] = str(path.relative_to(ROOT))
    out["bytes"] = path.stat().st_size
    if do_sha:
        out["sha256"] = sha256(path)

    # Scanned SEPARATELY by where it came from, because that is what sets the tier.
    if spec.get("version_flag"):
        out["version"] = run([str(path), spec["version_flag"]]).strip()[:300]
        out["authorship_hits"] = scan(out["version"], PROJECT_NAMES)
    else:
        out["version"] = None
        out["authorship_hits"] = {}
        # Not a defect, but worth saying: an engine that will not state its own
        # version cannot be pinned to a build in any report written about it, and
        # the other two here do state one.
        out["no_version_flag"] = True

    help_text = run([str(path), spec["help_flag"]]) if spec.get("help_flag") else ""
    out["help_first_line"] = next(
        (l for l in help_text.splitlines() if l.strip()), "")[:200]
    out["reference_hits"] = {k: v for k, v in scan(help_text, PROJECT_NAMES).items()
                             if k not in out["authorship_hits"]}
    out["announced_vocabulary"] = sorted(
        scan((out["version"] or "") + help_text, VOCABULARY))

    if spec.get("serving"):
        out["serving"] = probe_serving(spec["serving"])

    embedded = binary_strings(path)
    out["embedded_project_names"] = {
        n: len(re.findall(re.escape(n), embedded, re.I)) for n in PROJECT_NAMES
        if re.search(re.escape(n), embedded, re.I)}
    return out


def probe_serving(base: str) -> dict:
    """What a CLIENT is told by the running server: the `aa1bdff2` surface."""
    out: dict = {"base": base}
    try:
        req = urllib.request.Request(base + "/health")
        with urllib.request.urlopen(req, timeout=5) as r:
            out["up"] = r.status == 200
            out["server_header"] = r.headers.get("Server")
    except Exception as exc:
        return {"base": base, "up": False, "error": f"{type(exc).__name__}"}
    for endpoint in ("/v1/models", "/props"):
        try:
            with urllib.request.urlopen(base + endpoint, timeout=10) as r:
                body = json.loads(r.read().decode("utf-8", "replace"))
            if endpoint == "/props":
                out["build_info"] = body.get("build_info")
            # Drop the excluded fields BEFORE scanning. The GGUF's own chat template
            # is upstream provenance the codebase deliberately keeps; see
            # SERVING_SCAN_EXCLUDE.
            pruned = {k: v for k, v in body.items()
                      if k not in SERVING_SCAN_EXCLUDE}
            out[endpoint] = scan(json.dumps(pruned, indent=1), PROJECT_NAMES)
            out[endpoint + ":excluded"] = [k for k in body
                                           if k in SERVING_SCAN_EXCLUDE]
        except Exception as exc:
            out[endpoint] = {"error": type(exc).__name__}
    return out


# --------------------------------------------------------------------------- real work

def measure_listen(repeats: int) -> dict:
    """Transcription speed as a realtime factor, on the sample shipped beside it.

    A realtime factor rather than seconds, because seconds are meaningless without
    the clip length: `xRT = audio_seconds / wall_seconds`, so 10x means ten seconds
    of speech transcribed per second of compute. CPU-only, so this measurement does
    not contend with anything on the card and does not need the governor.
    """
    binary = ROOT / "symoneural-listen" / "build" / "bin" / "symoneural-listen"
    weight = ROOT / "backend" / "models" / "whisper" / "symoneural-listen-base-en.bin"
    sample = ROOT / "symoneural-listen" / "samples" / "jfk.wav"
    if not all(p.exists() for p in (binary, weight, sample)):
        return {"skipped": "binary, weight or sample absent",
                "missing": [str(p.relative_to(ROOT)) for p in (binary, weight, sample)
                            if not p.exists()]}
    audio_s = wav_seconds(sample)
    runs = []
    for _ in range(repeats):
        started = time.monotonic()
        out = run([str(binary), "-m", str(weight), "-f", str(sample), "-nt"], timeout=300)
        wall = time.monotonic() - started
        runs.append({"wall_s": round(wall, 2),
                     "xrt": round(audio_s / wall, 2) if wall and audio_s else None,
                     "produced_text": bool(re.search(r"[A-Za-z]{4,}", out))})
    xrts = [r["xrt"] for r in runs if r["xrt"]]
    return {"audio_seconds": round(audio_s, 2) if audio_s else None,
            "sample": str(sample.relative_to(ROOT)),
            "weight": str(weight.relative_to(ROOT)),
            "runs": runs,
            "xrt_median": round(sorted(xrts)[len(xrts) // 2], 2) if xrts else None,
            "note": "first run includes the weight load; `runs` is listed in order "
                    "so that cost is visible rather than averaged away"}


def wav_seconds(path: Path) -> float | None:
    """Clip length from the RIFF header, so the xRT has a real numerator."""
    try:
        import wave
        with wave.open(str(path)) as w:
            return w.getnframes() / float(w.getframerate())
    except Exception:
        return None


def measure_diffuse() -> dict:
    """Render wall-clock, THROUGH THE API rather than by invoking the engine.

    Deliberate, and the reason is arithmetic: the language model is resident at
    ~8.5 GB and diffusion wants ~7 GB of a 16.3 GB card, so a direct invocation
    while chat is loaded does not fit. `POST /api/image` calls `stop_llama()` first
    (`api.py:2916`) and takes the governor lease, which is the mechanism that makes
    the two surfaces coexist at all. Bypassing it to measure it would measure an
    allocator failure.

    So this is the engine's time inside the platform's sequencing, and it is
    labelled as such rather than presented as a bare engine number.
    """
    before = gpu_used_mib()
    body = json.dumps({"prompt": "a grey cube on a white background",
                       "steps": 1, "size": 256}).encode()
    req = urllib.request.Request(API + "/api/image", data=body,
                                 headers={"Content-Type": "application/json"})
    started = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=900) as r:
            payload = json.loads(r.read())
        wall = time.monotonic() - started
        return {"via": "POST /api/image (governor-mediated)",
                "status": 200, "wall_s": round(wall, 2),
                "reported_seconds": payload.get("seconds"),
                "steps": 1, "size": 256,
                "vram_before_mib": before, "vram_after_mib": gpu_used_mib(),
                "note": "one step at 256 px: the question is what a render costs to "
                        "start and finish, not image quality"}
    except Exception as exc:
        return {"via": "POST /api/image", "error": f"{type(exc).__name__}: {exc}"[:200],
                "wall_s": round(time.monotonic() - started, 2)}


# --------------------------------------------------------------------------- report

def markdown(d: dict) -> str:
    L = [f"# Engine audit — measured {d['measured_at']}", "",
         f"Commit: `{d['head']}`  ",
         f"{sum(1 for e in d['engines'] if e.get('built'))} of "
         f"{len(d['engines'])} declared engines are built.", "",
         "## Findings", ""]
    if d["findings"]:
        for f in d["findings"]:
            L.append(f"- **{f}**")
    else:
        L.append("No announced-identity or artefact finding survived this audit.")
    L += ["", "## Artefacts", "",
          "| Engine | Built | Bytes | `--version` |", "|---|---|---|---|"]
    for e in d["engines"]:
        if not e.get("built"):
            L.append(f"| `{e['id']}` | no | — | — |")
            continue
        L.append(f"| `{e['id']}` | yes | {e['bytes']:,} | "
                 f"{(e.get('version') or '—').splitlines()[0][:70]} |")
    L.append("")

    L += ["## Announced identity", "",
          "What each engine TELLS a user or a client. This is the surface "
          "`aa1bdff2` fixed on the language server — `Server: llama.cpp` on every "
          "response and `owned_by: llamacpp` in `/v1/models` — and the question had "
          "not been put to the others.", ""]
    for e in d["engines"]:
        if not e.get("built"):
            L += [f"### `{e['id']}` — not built", "",
                  e.get("note", "") or "No binary to interrogate.", ""]
            continue
        L += [f"### `{e['id']}`", ""]
        s = e.get("serving")
        if s:
            L += [f"- Serving on `{s['base']}`: "
                  + (f"`Server: {s.get('server_header')}`" if s.get("up")
                     else f"not up ({s.get('error', '')})")]
            if s.get("build_info"):
                L.append(f"- `build_info`: `{s['build_info']}`")
            for ep in ("/v1/models", "/props"):
                hits = s.get(ep)
                if hits is None:
                    continue
                if "error" in hits:
                    L.append(f"- `{ep}`: not read ({hits['error']})")
                elif hits:
                    L.append(f"- `{ep}` names: " + ", ".join(f"`{k}`" for k in hits))
                else:
                    L.append(f"- `{ep}`: no third-party project name")
                ex = s.get(ep + ":excluded")
                if ex:
                    L.append(f"  - excluded from that scan by decision: "
                             + ", ".join(f"`{k}`" for k in ex)
                             + " — the GGUF's own chat template carries upstream "
                               "provenance `api.py:2823-2834` argues for keeping, "
                               "and enforces one layer up")
        auth = e.get("authorship_hits") or {}
        if auth:
            L += ["", "  **Authorship claims** — a third-party name where the engine "
                  "states what it is:", ""]
            for n, line in auth.items():
                L.append(f"  - **`{n}`** — `{line}`")
        elif e.get("version"):
            L.append("- `--version` names no third-party project.")
        if e.get("no_version_flag"):
            L.append("- **No `--version` flag.** Not a defect, but this engine cannot "
                     "state its own build, so no report can pin which one it "
                     "measured. The other two built engines can.")
        ref = e.get("reference_hits") or {}
        if ref:
            L += ["", "  References in flag descriptions — a human call, not a "
                  "finding:", ""]
            for n, line in ref.items():
                L.append(f"  - `{n}` — `{line}`")
        vocab = e.get("announced_vocabulary") or []
        if vocab:
            L.append(f"- Library/format vocabulary, not a finding: "
                     + ", ".join(f"`{v}`" for v in vocab))
        emb = e.get("embedded_project_names") or {}
        if emb:
            L.append(f"- Embedded in the artefact (symbols and strings, not "
                     f"user-visible, not findings): "
                     + ", ".join(f"`{k}`×{v}" for k, v in sorted(emb.items())))
        L.append("")

    if d.get("references"):
        L += ["## Third-party names in flag descriptions — for a human to judge", "",
              "Not findings. Each of these names an upstream project inside a flag's "
              "description, a URL, or an interop mode value, which is a different "
              "thing from claiming to be that project — `--rng ... cpu(comfyui)` "
              "names the RNG behaviour that mode reproduces, and renaming it would "
              "make the flag lie about what it does. One line below is genuinely "
              "borderline and is left to a reader rather than decided by a regex: a "
              "bash-completion script *for this program* that calls the program "
              "`llama.cpp` is closer to an authorship claim than to a citation.", "",
              "| Engine | Name | Line |", "|---|---|---|"]
        for r in d["references"]:
            L.append(f"| `{r['engine']}` | `{r['name']}` | `{r['line'][:110]}` |")
        L.append("")

    if d.get("work"):
        L += ["## Real work", ""]
        w = d["work"]
        if w.get("listen"):
            l = w["listen"]
            if l.get("skipped"):
                L += [f"**`symoneural-listen`** — not measured: {l['skipped']} "
                      f"({', '.join(l.get('missing', []))})", ""]
            else:
                L += [f"**`symoneural-listen`** — `{l['sample']}`, "
                      f"{l['audio_seconds']} s of audio, CPU only.", "",
                      f"Median **{l['xrt_median']}× realtime** — that many seconds of "
                      f"speech transcribed per second of compute.", "",
                      "| Run | Wall | xRT | Produced text |", "|---|---|---|---|"]
                for i, r in enumerate(l["runs"], 1):
                    L.append(f"| {i} | {r['wall_s']} s | **{r['xrt']}×** | "
                             f"{'yes' if r['produced_text'] else 'NO'} |")
                L += ["", l["note"], ""]
        if w.get("diffuse"):
            f = w["diffuse"]
            if f.get("error"):
                L += [f"**`symoneural-diffuse`** — render failed: `{f['error']}` "
                      f"after {f['wall_s']} s", ""]
            else:
                L += [f"**`symoneural-diffuse`** — one step at 256 px via "
                      f"`{f['via']}`: **{f['wall_s']} s** wall, "
                      f"{f.get('reported_seconds')} s reported by the surface. "
                      f"VRAM {f.get('vram_before_mib')} → "
                      f"{f.get('vram_after_mib')} MiB.", "", f["note"], ""]
        L += ["**`symoneural-llm`** — measured properly in "
              "`MEASURED-2026-09-07-llm-throughput-context.md` (≈116 tok/s decode, "
              "32,768-token per-slot context) and not re-measured worse here.", ""]
    return "\n".join(L)


# --------------------------------------------------------------------------- main

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--no-sha", action="store_true")
    ap.add_argument("--no-work", action="store_true",
                    help="identity only: no transcription, no render")
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    d: dict = {"measured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
               "head": subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"],
                                      capture_output=True, text=True).stdout.strip(),
               "findings": []}

    print("auditing engine identity...", file=sys.stderr)
    d["engines"] = [audit_identity(spec, not args.no_sha) for spec in ENGINES]

    d["references"] = []
    for e in d["engines"]:
        # FINDINGS: authorship tier only -- the banner, the version line, an HTTP
        # identity field. That is where `aa1bdff2`'s defect lived.
        for name, line in (e.get("authorship_hits") or {}).items():
            d["findings"].append(
                f"`{e['id']}` names `{name}` in its own `--version` output: "
                f"`{line}`. That is an authorship claim, the same class as the "
                f"`Server: llama.cpp` and `owned_by: llamacpp` defect `aa1bdff2` "
                f"fixed on the HTTP surface")
        s = e.get("serving") or {}
        if s.get("server_header") and any(
                n.lower() in s["server_header"].lower() for n in PROJECT_NAMES):
            d["findings"].append(
                f"`{e['id']}` serves `Server: {s['server_header']}` — a third-party "
                f"name in the HTTP identity header")
        for ep in ("/v1/models", "/props"):
            hits = s.get(ep) or {}
            if hits and "error" not in hits:
                d["findings"].append(
                    f"`{e['id']}` serving surface `{ep}` returns third-party project "
                    f"name(s) " + ", ".join(f"`{n}`" for n in hits)
                    + " outside the fields the codebase deliberately keeps")
        # REFERENCES: recorded for a human to judge, deliberately not findings.
        for name, line in (e.get("reference_hits") or {}).items():
            d["references"].append({"engine": e["id"], "name": name, "line": line})
        if e.get("built") is False and not e.get("note"):
            d["findings"].append(f"`{e['id']}` declares a binary that is not present")

    if not args.no_work:
        print("measuring real work (ASR on CPU, then a render)...", file=sys.stderr)
        d["work"] = {"listen": measure_listen(args.repeats), "diffuse": measure_diffuse()}
        l = d["work"]["listen"]
        if not l.get("skipped") and not all(r["produced_text"] for r in l["runs"]):
            d["findings"].append(
                "`symoneural-listen` ran without producing transcribed text on at "
                "least one run — a timing that measures a failure is worse than no "
                "timing, so the text check is part of the measurement")
        if d["work"]["diffuse"].get("error"):
            d["findings"].append(
                f"`symoneural-diffuse` did not complete a one-step 256 px render: "
                f"{d['work']['diffuse']['error']}")

    stem = Path(args.out) if args.out else (
        ROOT / "review" / f"MEASURED-{datetime.now(timezone.utc):%Y-%m-%d}-engine-audit")
    stem.parent.mkdir(parents=True, exist_ok=True)
    stem.with_suffix(".json").write_text(json.dumps(d, indent=2, default=str) + "\n")
    stem.with_suffix(".md").write_text(markdown(d))
    print(f"wrote {stem.with_suffix('.json')}\nwrote {stem.with_suffix('.md')}")
    print(f"{len(d['findings'])} findings", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
