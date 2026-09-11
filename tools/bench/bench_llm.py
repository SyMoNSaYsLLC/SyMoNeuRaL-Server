#!/usr/bin/env python3
"""Measure the chat surface's throughput and its real context ceiling.

Two questions, and neither is answerable by reading a file:

  * **tok/s.** `site/index.html` and `site/controlboard.html` publish `151 tok/s`
    labelled *measured*, and `.claude/HANDOVER.md` carries 100.6 and 129.6 from two
    different sessions. Those three numbers cannot all describe the same workload,
    and two of them were taken on counting prompts -- `1,2,3,4,5,6,7,8,9,10` is the
    single most draftable string a speculative decoder will ever see, so it reads
    high and is true of nothing anyone types. This tool measures several distinct
    regimes and refuses to collapse them into one figure.

  * **Context size.** There are five candidate answers on this box:
    the GGUF's own `*.context_length`, the engine's `-c 65536` total, the
    `-c / -np` per-slot share, `MAX_PROMPT_CHARS`, and `ChatRequest.max_tokens`.
    Only one of them is the ceiling a conversation actually hits. The per-slot
    value is read off the **running server** (`GET /props`), never off the argv
    comment in `api.py`, which is dated 2026-08-17 and is a claim about a config
    rather than a reading of one. Then it is *probed*: a prompt deliberately past
    the ceiling must be refused or truncated, and the response says which.

Timings come from the engine's own `timings` block (`predicted_per_second`), not
from wall-clock division. Wall-clock over HTTP folds in queueing, the governor
lease and SSE framing; the site's own `tok_per_s` field is computed that way, so
this tool records the API's figure too and reports the gap between them rather
than pretending either one is "the" number.

WHAT THIS DOES NOT MUTATE: nothing. It drives `POST /api/chat` on the running
service, which spawns the engine on demand through `start_llama()`, then reads
the resident engine on 127.0.0.1:8081. It never spawns an engine of its own --
`LLAMA_PORT` is fixed at 8081 in `api.py` and `llama_up()` only probes `/health`,
so a bench instance on that port would silently become what the production chat
surface proxies to, carrying this tool's argv instead of production's.

    python3 tools/bench/bench_llm.py                     # full run, writes JSON + Markdown
    python3 tools/bench/bench_llm.py --quick             # decode regimes only
    python3 tools/bench/bench_llm.py --no-sha            # skip the 4.7 GB model digest
"""

from __future__ import annotations

import argparse
import json
import hashlib
import os
import re
import shutil
import struct
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = next(_p for _p in Path(__file__).resolve().parents if (_p / "backend" / "server.py").is_file())
API = os.environ.get("SYMONEURAL_API", "http://127.0.0.1:8800")
ENGINE = os.environ.get("SYMONEURAL_LLAMACPP_URL", "http://127.0.0.1:8081")

#: Filler for context-fill probes. Deliberately ordinary English: a repeated single
#: token would compress into a run the drafter predicts perfectly, which is the very
#: bias this tool exists to avoid. The measured prompt length is read back from
#: `timings.prompt_n` rather than assumed from the character count.
FILLER = ("The card holds the weights and the cache in the same memory, so every "
          "token generated must read the whole of both. ")


# --------------------------------------------------------------------------- transport

def _post(url: str, body: dict, timeout: float = 600.0) -> dict:
    raw = json.dumps(body).encode()
    req = urllib.request.Request(
        url, data=raw, headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def _get(url: str, timeout: float = 30.0) -> dict:
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def engine_up() -> bool:
    try:
        with urllib.request.urlopen(f"{ENGINE}/health", timeout=3) as r:
            return r.status == 200
    except Exception:
        return False


# --------------------------------------------------------------------------- identity

def head_sha() -> str:
    out = subprocess.run(["git", "-C", str(ROOT), "rev-parse", "HEAD"],
                         capture_output=True, text=True)
    dirty = subprocess.run(["git", "-C", str(ROOT), "status", "--porcelain"],
                           capture_output=True, text=True).stdout.strip()
    sha = out.stdout.strip() or "unknown"
    return sha + (" (tree dirty)" if dirty else "")


def sha256(path: Path, chunk: int = 1 << 22) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while block := f.read(chunk):
            h.update(block)
    return h.hexdigest()


def engine_argv() -> dict:
    """The argv of the engine child, read from the process table.

    Transcribing `api.py:1303-1337` instead would miss the two conditional blocks
    that decide what is actually in the throughput path: the draft model (`-md`,
    speculative decoding) and the persona adapter (`--lora`). Both are appended at
    runtime by `start_llama()`, and both change the number this tool reports.
    """
    out = subprocess.run(
        ["pgrep", "-af", "symoneural-llm"], capture_output=True, text=True).stdout
    binary = str(ROOT / "symoneural-llm" / "build" / "bin" / "symoneural-llm")
    for line in out.splitlines():
        pid, _, args = line.partition(" ")
        # `pgrep -af` matches on the whole command line, so this tool's own shell
        # wrapper -- which mentions the engine by name in a curl URL -- comes back
        # too. Match the argv's first word against the binary instead of the pattern.
        if not args.split()[:1] == [binary]:
            continue
        argv = subprocess.run(["ps", "-o", "args=", "-p", pid],
                              capture_output=True, text=True).stdout.strip()
        return {"pid": int(pid), "argv": argv,
                "draft_model": "-md" in argv.split(),
                "lora": "--lora" in argv.split(),
                "ctx_total_argv": _flag(argv, "-c"),
                "slots_argv": _flag(argv, "-np")}
    return {"pid": None, "argv": None}


def _flag(argv: str, flag: str) -> str | None:
    parts = argv.split()
    return parts[parts.index(flag) + 1] if flag in parts[:-1] else None


def serving_features() -> dict:
    """Which optional serving features are ACTIVE, asked of the running engine.

    The argv is what was requested; this is what happened. The two came apart on
    this box: `api.py:1333-1335` passes `-md`, `-ngld 99` and `--spec-draft-n-max 2`,
    yet both slots report `speculative: false`. In this engine's own source
    `common/common.h:370` defaults `speculative.types` to `{ NONE }`, and only
    `--spec-type` (`common/arg.cpp:4154`) selects a method -- `--spec-draft-model`
    (`-md`, line 4146) does nothing but record a path. So the draft model is named,
    is not loaded, and is not drafting.

    `/lora-adapters` is the same kind of question for the persona adapter, and there
    the answer is the other way round: `default_generation_settings.params.lora` is
    `[]`, which looks like "no adapter" and is not -- that field is the per-request
    scale override list. The loaded set is on its own endpoint.
    """
    out: dict = {}
    try:
        slots = _get(f"{ENGINE}/slots")
        out["slots"] = [{"id": s.get("id"), "n_ctx": s.get("n_ctx"),
                         "speculative": s.get("speculative")} for s in slots]
        out["speculative_active"] = any(s.get("speculative") for s in slots)
    except Exception as exc:
        out["slots_error"] = str(exc)
    try:
        out["lora_adapters"] = _get(f"{ENGINE}/lora-adapters")
        out["adapter_active"] = bool(out["lora_adapters"])
    except Exception as exc:
        out["lora_error"] = str(exc)
    return out


def gpu_state() -> dict:
    exe = shutil.which("nvidia-smi")
    if not exe:
        return {}
    q = ("name,memory.total,memory.used,clocks.current.sm,"
         "clocks.current.memory,power.draw,temperature.gpu")
    out = subprocess.run([exe, f"--query-gpu={q}", "--format=csv,noheader"],
                         capture_output=True, text=True).stdout.strip()
    keys = ["name", "vram_total", "vram_used", "sm_clock", "mem_clock", "power", "temp"]
    return dict(zip(keys, [v.strip() for v in out.split(",")])) if out else {}


# --------------------------------------------------------------------------- GGUF

_GGUF_STR = 8
_GGUF_ARRAY = 9
#: struct formats by GGUF metadata value type id, from the GGUF spec's enum order.
_GGUF_SCALARS = {0: "<B", 1: "<b", 2: "<H", 3: "<h", 4: "<I", 5: "<i",
                 6: "<f", 7: "<?", 10: "<Q", 11: "<q", 12: "<d"}


def gguf_metadata(path: Path, want: tuple[str, ...]) -> dict:
    """Read named metadata keys out of a GGUF header.

    Parsed rather than grepped: `strings | grep context_length` finds the key name
    and cannot tell you its value, and the value is the whole point. Arrays are
    skipped by length -- the tokenizer's 150k-entry vocabulary is in this header and
    reading it to find a scalar three keys later would be absurd.
    """
    found: dict[str, object] = {}
    with path.open("rb") as f:
        magic, version, _n_tensors, n_kv = struct.unpack("<4sIQQ", f.read(24))
        if magic != b"GGUF":
            raise ValueError(f"{path} is not a GGUF file (magic {magic!r})")
        found["_gguf_version"] = version
        for _ in range(n_kv):
            klen, = struct.unpack("<Q", f.read(8))
            key = f.read(klen).decode("utf-8", "replace")
            vtype, = struct.unpack("<I", f.read(4))
            value = _gguf_value(f, vtype)
            if key in want or any(key.endswith(w) for w in want):
                found[key] = value
    return found


def _gguf_value(f, vtype: int):
    if vtype in _GGUF_SCALARS:
        fmt = _GGUF_SCALARS[vtype]
        return struct.unpack(fmt, f.read(struct.calcsize(fmt)))[0]
    if vtype == _GGUF_STR:
        n, = struct.unpack("<Q", f.read(8))
        return f.read(n).decode("utf-8", "replace")
    if vtype == _GGUF_ARRAY:
        etype, count = struct.unpack("<IQ", f.read(12))
        if etype == _GGUF_STR:
            for _ in range(count):
                n, = struct.unpack("<Q", f.read(8))
                f.seek(n, os.SEEK_CUR)
        elif etype == _GGUF_ARRAY:
            raise ValueError("nested GGUF arrays are not supported")
        else:
            f.seek(struct.calcsize(_GGUF_SCALARS[etype]) * count, os.SEEK_CUR)
        return f"<array of {count}>"
    raise ValueError(f"unknown GGUF value type {vtype}")


# --------------------------------------------------------------------------- limits

def api_declared_limits() -> dict:
    """The caps the API itself imposes, read out of its own source.

    These are the ceilings a visitor hits *before* the engine's, and they are
    expressed in different units -- one in characters, one in tokens, one in turns --
    which is exactly why "the context size" has no single answer here.
    """
    src = (ROOT / "backend" / "server.py").read_text()
    def one(pat: str) -> str | None:
        # MULTILINE, because the two module-level constants below are anchored with
        # `^` to avoid matching the same names inside the docstrings and comments
        # that discuss them -- and this file discusses them at length.
        m = re.search(pat, src, re.M | re.S)
        return m.group(1) if m else None
    return {
        "MAX_PROMPT_CHARS": one(r"^MAX_PROMPT_CHARS\s*=\s*([\d_]+)"),
        "max_tokens_ceiling": one(r"max_tokens:\s*int\s*=\s*Field\(\d+,\s*ge=\d+,\s*le=(\d+)"),
        "history_turn_cap": one(r"history:.*?max_length=(\d+)"),
        "chat_model_label": one(r'^CHAT_MODEL_LABEL\s*=\s*"([^"]+)"'),
    }


# --------------------------------------------------------------------------- regimes

#: `ignore_eos` fixes the work per sample so repeats are comparable: without it a
#: model that stops at 40 tokens and one that runs to 256 are averaged together and
#: the short sample's cold first token dominates its own rate.
DECODE_N = 256

#: The three regimes describe what is being ASKED, not what the answer will be. An
#: earlier revision of this table said counting "reproduces the historical 129.6" and
#: that code "drafts better than prose"; the run measured 114.9, 115.6 and 116.3 and
#: falsified both. A rationale that predicts its own result is how a bench stops being
#: able to surprise you -- the conclusion belongs in the report, downstream of numbers.
REGIMES = [
    {"key": "counting",
     "why": "the most predictable output a drafter will ever see; the workload the "
            "129.6 and 100.6 tok/s figures in the handover were taken on",
     "prompt": "Count from 1 to 400. Output only the numbers, comma separated."},
    {"key": "prose",
     "why": "ordinary English at the production temperature",
     "prompt": "Explain, in several paragraphs, why generating one token on a consumer "
               "GPU is limited by memory bandwidth rather than by arithmetic."},
    {"key": "code",
     "why": "structured output: repetitive syntax, but real branching",
     "prompt": "Write a Python function that streams a file in fixed-size chunks and "
               "returns its SHA-256, with a docstring and error handling."},
]


def completion(prompt: str, n_predict: int, *, temperature: float, seed: int,
               ignore_eos: bool, cache_prompt: bool = False) -> dict:
    """Raw `/completion`: the prompt goes to the model verbatim, no chat template.

    Right for the context-fill curve, where the whole point is a prompt of a known
    token length and a template would add an unaccounted preamble. WRONG for the
    workload regimes -- see `chat_completion`.
    """
    return _post(f"{ENGINE}/completion", {
        "prompt": prompt, "n_predict": n_predict, "temperature": temperature,
        "seed": seed, "ignore_eos": ignore_eos, "cache_prompt": cache_prompt,
        "timings_per_token": True, "stream": False})


def chat_completion(prompt: str, n_predict: int, *, temperature: float, seed: int) -> dict:
    """The templated path, which is the one production uses.

    This distinction is not pedantry, it changes the measurement. Sent to raw
    `/completion`, "Count from 1 to 400" is a text continuation, and the model
    answered it with *"Use `sleep` to pause for 1 second after every 50th number.
    Write a Python script that..."* -- prose, not digits. The regime meant to be
    maximally repetitive was measuring nothing of the kind. Through the chat
    template the same prompt returns `1,2,3,4,...`, which is the workload the
    historical figures were taken on. `chat_deltas` in `api.py:1369` posts here.
    """
    return _post(f"{ENGINE}/v1/chat/completions", {
        "model": "symoneural", "messages": [{"role": "user", "content": prompt}],
        "max_tokens": n_predict, "temperature": temperature, "seed": seed,
        # A llama.cpp extension the OpenAI-compatible handler forwards. Without it
        # a regime that stops at 40 tokens and one that runs to 256 are averaged
        # together, and the short sample's fixed per-request cost dominates its own
        # rate -- the 8-token warmup on this box reported 27.2 tok/s for that reason.
        "ignore_eos": True, "timings_per_token": True, "stream": False})


def decode_runs(regime: dict, repeats: int, temperature: float) -> dict:
    samples = []
    for i in range(repeats):
        r = chat_completion(regime["prompt"], DECODE_N,
                            temperature=temperature, seed=1000 + i)
        t = r.get("timings", {})
        samples.append({
            "predicted_n": t.get("predicted_n"),
            "predicted_ms": _r(t.get("predicted_ms")),
            "decode_tok_s": _r(t.get("predicted_per_second")),
            "prompt_n": t.get("prompt_n"),
            "prefill_tok_s": _r(t.get("prompt_per_second")),
            # Present only on builds that report speculative-decode counters. Absent
            # is recorded as absent; a missing field is not a zero acceptance rate.
            "draft_n": t.get("draft_n"), "draft_accepted": t.get("draft_n_accepted"),
        })
    rates = [s["decode_tok_s"] for s in samples if s["decode_tok_s"]]
    return {**{k: regime[k] for k in ("key", "why")},
            "samples": samples, **_stats(rates)}


def _stats(rates: list[float]) -> dict:
    if not rates:
        return {"mean": None, "min": None, "max": None, "spread_pct": None}
    mean = sum(rates) / len(rates)
    return {"mean": round(mean, 2), "min": round(min(rates), 2),
            "max": round(max(rates), 2),
            "spread_pct": round(100 * (max(rates) - min(rates)) / mean, 1)}


def fill_curve(fills: list[int], temperature: float) -> list[dict]:
    """Decode rate as the context fills -- the measurement that ties the two metrics
    together. Every generated token attends over the whole cache, so tok/s at 31K of
    context is the number a long conversation actually gets, and a single figure
    quoted from an empty context is the best case rather than the typical one.
    """
    rows: list[dict] = []
    # Calibrated, not assumed. A flat 4 chars/token guess undershot this filler by
    # 16%, so the probe aimed at 36,864 tokens landed at 31,616 -- UNDER the 32,768
    # ceiling it was built to breach, and reported a comfortable pass as though the
    # ceiling had been tested. The ratio is re-derived from every readback.
    chars_per_token = 4.0
    for target in fills:
        prompt = ("Hello." if not target
                  else FILLER * max(1, round(target * chars_per_token / len(FILLER))))
        try:
            r = completion(prompt + "\n\nSummarise the passage above.", 128,
                           temperature=temperature, seed=7, ignore_eos=True)
        except urllib.error.HTTPError as exc:
            rows.append({"target_prompt_tokens": target, "refused": True,
                         "http": exc.code, "chars_sent": len(prompt),
                         "body": exc.read().decode("utf-8", "replace")[:400]})
            continue
        t = r.get("timings", {})
        measured = t.get("prompt_n")
        if measured and target:
            chars_per_token = len(prompt) / measured
        rows.append({"target_prompt_tokens": target,
                     "measured_prompt_tokens": measured,
                     "truncated": r.get("truncated"),
                     "prefill_tok_s": _r(t.get("prompt_per_second")),
                     "decode_tok_s": _r(t.get("predicted_per_second")),
                     "predicted_n": t.get("predicted_n")})
    return rows


def _r(v, places: int = 2):
    """Round for the report. `predicted_per_second` arrives as a float64 with
    fifteen significant digits, none of which past the second survive a rerun --
    the measured spread across identical samples is 0.5-3%."""
    return round(v, places) if isinstance(v, (int, float)) else v


def api_reported_rate(repeats: int) -> dict:
    """What the *site* shows. `site/chat.html:321` renders the API's `tok_per_s`,
    and `api.py:2868` computes it as tokens over wall-clock across the SSE stream.
    Recorded separately so the two can be compared instead of conflated.
    """
    samples = []
    for i in range(repeats):
        body = json.dumps({"prompt": REGIMES[1]["prompt"], "max_tokens": DECODE_N,
                           "temperature": 0.7}).encode()
        req = urllib.request.Request(f"{API}/api/chat", data=body,
                                     headers={"Content-Type": "application/json"})
        started = time.monotonic()
        with urllib.request.urlopen(req, timeout=600) as r:
            done, first = None, None
            for raw in r:
                line = raw.decode("utf-8", "replace").strip()
                if not line.startswith("data:"):
                    continue
                payload = json.loads(line[5:])
                if first is None and "delta" in payload:
                    first = time.monotonic() - started
                if payload.get("done"):
                    done = payload
        samples.append({**(done or {}), "ttft_s": round(first, 3) if first else None,
                        "wall_s": round(time.monotonic() - started, 3)})
    rates = [s["tok_per_s"] for s in samples if s.get("tok_per_s")]
    return {"samples": samples, **_stats(rates)}


# --------------------------------------------------------------------------- report

def markdown(d: dict) -> str:
    L = [f"# LLM throughput and context ceiling — measured {d['measured_at']}", "",
         f"Commit: `{d['head']}`  ", f"Engine PID: `{d['engine']['pid']}`  ",
         f"GPU: {d['gpu'].get('name')} — {d['gpu'].get('vram_used')} of "
         f"{d['gpu'].get('vram_total')} in use at capture  ",
         f"Cold start (weight load, `--no-warmup` is in the argv): "
         + (f"**{d['cold_start_s']} s**, paid by the first request"
            if d.get("cold_start_s")
            else "not measured this run — the engine was already resident"), ""]

    L += ["## Context size — five numbers, one ceiling", "",
          "| What | Value | Where it comes from |", "|---|---|---|"]
    ctx = d["context"]
    for row in ctx["table"]:
        L.append(f"| {row[0]} | **{row[1]}** | {row[2]} |")
    L += ["", f"**The operative ceiling for one conversation is "
              f"{ctx['operative_per_slot']:,} tokens** — prompt, replayed transcript "
              f"and reply combined, because they share the slot.", ""]
    if ctx.get("probe"):
        L += ["Probed rather than asserted:", ""]
        for p in ctx["probe"]:
            L.append(f"- {p}")
        L.append("")

    L += ["## Decode throughput by workload", "",
          f"Engine `timings.predicted_per_second`, {d['repeats']} samples per regime, "
          f"`n_predict={DECODE_N}` with `ignore_eos` so every sample does identical "
          f"work. Temperature {d['temperature']} (the production default).", "",
          "| Regime | tok/s mean | min | max | spread | Why this regime |",
          "|---|---|---|---|---|---|"]
    for r in d["decode"]:
        L.append(f"| `{r['key']}` | **{r['mean']}** | {r['min']} | {r['max']} | "
                 f"{r['spread_pct']}% | {r['why']} |")
    L.append("")

    if d.get("api_rate"):
        a, engine_prose = d["api_rate"], d["decode"][1]["mean"]
        gap = ((engine_prose - a["mean"]) / engine_prose * 100
               if a["mean"] and engine_prose else None)
        ttfts = [s["ttft_s"] for s in a["samples"] if s.get("ttft_s")]
        L += ["## What the site reports, for comparison", "",
              f"`POST /api/chat` returns `tok_per_s` computed as tokens over "
              f"wall-clock (`api.py:2868`), which is what `site/chat.html` renders: "
              f"**{a['mean']} tok/s** over {len(a['samples'])} prose replies, against "
              f"the engine's **{engine_prose} tok/s** for the same workload — a gap of "
              + (f"{gap:.1f}%" if gap is not None else "?") + ". "
              # Stated as a measurement rather than explained away: the gap is the
              # governor lease, SSE framing and HTTP, and it is not constant. It
              # measured 12% on one run of this tool and under 1% on the next, which
              # is why the wall-clock figure is recorded beside the engine's instead
              # of being treated as the same number.
              "That gap is queueing, SSE framing and HTTP rather than the card, and "
              "it is not stable between runs — which is the reason to record both "
              "figures rather than to publish either one alone.", ""]
        if ttfts:
            L += [f"Time to first token, end to end: "
                  f"{min(ttfts):.2f}–{max(ttfts):.2f} s on a warm engine.", ""]

    if d.get("fill"):
        L += ["## Decode rate as context fills", "",
              "Every new token attends over the entire cache, so this is the curve a "
              "long conversation rides down.", "",
              "| Target prompt | Measured prompt | Prefill tok/s | Decode tok/s |",
              "|---|---|---|---|"]
        for r in d["fill"]:
            if r.get("refused"):
                L.append(f"| {r['target_prompt_tokens']} | — | refused "
                         f"HTTP {r['http']} | — |")
            else:
                L.append(f"| {r['target_prompt_tokens']} | "
                         f"{r['measured_prompt_tokens']} | "
                         f"{r['prefill_tok_s']} | **{r['decode_tok_s']}** |")
        L.append("")

    f = d.get("features", {})
    if f:
        L += ["## Requested vs active serving features", "",
              "| Feature | Requested in argv | Active in the engine |", "|---|---|---|",
              f"| Speculative decoding (draft model) | "
              f"{'yes — `-md`, `-ngld 99`, `--spec-draft-n-max 2`' if d['engine'].get('draft_model') else 'no'} "
              f"| **{'yes' if f.get('speculative_active') else 'NO'}** |",
              f"| Persona adapter | "
              f"{'yes — `--lora`' if d['engine'].get('lora') else 'no'} "
              f"| **{'yes' if f.get('adapter_active') else 'NO'}** |", ""]
        if d["engine"].get("draft_model") and not f.get("speculative_active"):
            L += ["**Speculative decoding is requested and is not running.** Both slots "
                  "report `speculative: false`, and the two workloads that should differ "
                  "most under drafting instead measure the same rate — which is the "
                  "signature of a drafter that is not there. In this engine's own source "
                  "`common/common.h:370` defaults `speculative.types` to `{ NONE }` and "
                  "only `--spec-type` (`common/arg.cpp:4154`) selects a method; "
                  "`--spec-draft-model` / `-md` (line 4146) records a path and nothing "
                  "else. The 0.5 GB draft GGUF is named in the argv, is not loaded, and "
                  "is not drafting.", ""]

    L += ["## Engine argv actually in the path", "", "```",
          (d["engine"].get("argv") or "engine not running at capture"), "```", "",
          f"Draft model (speculative decoding): "
          f"**{'yes' if d['engine'].get('draft_model') else 'no'}**. "
          f"Persona adapter (`--lora`): "
          f"**{'yes' if d['engine'].get('lora') else 'no'}**.", "",
          "## Weights", "",
          "| File | Bytes | SHA-256 |", "|---|---|---|"]
    for m in d["models"]:
        L.append(f"| `{m['name']}` | {m['bytes']:,} | `{m.get('sha256') or 'not computed'}` |")
    L.append("")
    return "\n".join(L)


# --------------------------------------------------------------------------- main

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--temperature", type=float, default=0.7,
                    help="production default; greedy would flatter the drafter")
    ap.add_argument("--quick", action="store_true",
                    help="decode regimes only: no fill curve, no API comparison")
    ap.add_argument("--no-sha", action="store_true", help="skip model digests")
    ap.add_argument("--out", default=None, help="write JSON + .md beside this stem")
    args = ap.parse_args()

    d: dict = {"measured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
               "head": head_sha(), "repeats": args.repeats,
               "temperature": args.temperature, "api": API, "engine_url": ENGINE}

    # Bring the engine up the way production does, and pay the cold load out loud.
    # `--no-warmup` is in the argv, so the first request after a cold start includes
    # the weight load; averaging that into a throughput figure is how a bench lies.
    cold = None
    if not engine_up():
        print("engine down -- warming through POST /api/chat (cold weight load)",
              file=sys.stderr)
        t0 = time.monotonic()
        try:
            urllib.request.urlopen(urllib.request.Request(
                f"{API}/api/chat",
                data=json.dumps({"prompt": "Say READY.", "max_tokens": 8}).encode(),
                headers={"Content-Type": "application/json"}), timeout=600).read()
        except Exception as exc:
            print(f"warmup failed: {exc}", file=sys.stderr)
            return 2
        cold = round(time.monotonic() - t0, 1)
    d["cold_start_s"] = cold
    if not engine_up():
        print("engine still not answering on 8081", file=sys.stderr)
        return 2

    d["gpu"] = gpu_state()
    d["engine"] = engine_argv()
    d["features"] = serving_features()
    props = _get(f"{ENGINE}/props")
    gen = props.get("default_generation_settings", {})
    served_slot = gen.get("n_ctx") or props.get("n_ctx")
    d["props"] = {"n_ctx_slot_served": served_slot,
                  "total_slots": props.get("total_slots"),
                  "model_path": props.get("model_path") or gen.get("model"),
                  "build": props.get("build_info")}

    chat_model = ROOT / "backend" / "models" / "llm" / "symon-1.0-7b-q4_k_m.gguf"
    draft_model = ROOT / "backend" / "models" / "llm" / "symon-1.0-draft-0.5b-q4_k_m.gguf"
    d["models"] = []
    for p in (chat_model, draft_model):
        if not p.exists():
            continue
        row = {"name": p.name, "bytes": p.stat().st_size}
        if not args.no_sha:
            row["sha256"] = sha256(p)
        d["models"].append(row)

    meta = gguf_metadata(chat_model, ("context_length", "general.architecture",
                                      "general.name", "block_count",
                                      "embedding_length", "general.file_type",
                                      "rope.freq_base"))
    d["gguf"] = {k: v for k, v in meta.items()}
    trained = next((v for k, v in meta.items() if k.endswith("context_length")), None)
    limits = api_declared_limits()
    d["api_limits"] = limits

    total_argv = d["engine"].get("ctx_total_argv")
    slots_argv = d["engine"].get("slots_argv")
    d["context"] = {
        "operative_per_slot": served_slot,
        "table": [
            ["Trained context (GGUF metadata)", f"{trained:,}" if trained else "?",
             f"`{chat_model.name}` header, parsed"],
            ["Engine total context (`-c`)",
             f"{int(total_argv):,}" if total_argv else "?",
             "argv of the running engine child"],
            ["Concurrent slots (`-np`)", slots_argv or "?",
             "argv of the running engine child"],
            ["**Per-slot context, as served**",
             f"{served_slot:,}" if served_slot else "?",
             "`GET /props` on the running engine"],
            ["API prompt cap (characters, not tokens)",
             f"{int(limits['MAX_PROMPT_CHARS'].replace('_', '')):,}"
             if limits.get("MAX_PROMPT_CHARS") else "?", "`api.py` MAX_PROMPT_CHARS"],
            ["API reply cap (`max_tokens` ceiling)",
             f"{int(limits['max_tokens_ceiling']):,}"
             if limits.get("max_tokens_ceiling") else "?", "`ChatRequest.max_tokens`"],
            ["API history cap (turns)", limits.get("history_turn_cap") or "?",
             "`ChatRequest.history`"],
        ]}

    print("measuring decode regimes...", file=sys.stderr)
    d["decode"] = [decode_runs(r, args.repeats, args.temperature) for r in REGIMES]

    if not args.quick:
        print("measuring the context-fill curve...", file=sys.stderr)
        slot = served_slot or 32768
        # The last entry is over the per-slot ceiling on purpose, and it is in the
        # SAME call as the rest so it inherits the calibrated chars-per-token: the
        # ceiling is only proven by a request that actually reaches it, and a probe
        # that quietly lands short reports a pass it never earned. Overshot by a
        # quarter rather than a hair, so calibration error cannot swallow it.
        fills = [0, 4096, 16384, int(slot * 0.95), int(slot * 1.25)]
        d["fill"] = fill_curve(fills, args.temperature)
        probe = []
        for r in d["fill"]:
            if r.get("refused"):
                probe.append(f"A prompt aimed at {r['target_prompt_tokens']:,} tokens "
                             f"was **refused** with HTTP {r['http']}: "
                             f"`{r['body'][:160]}`")
            elif r.get("truncated"):
                probe.append(f"A prompt aimed at {r['target_prompt_tokens']:,} tokens "
                             f"was **truncated** to "
                             f"{r['measured_prompt_tokens']:,} evaluated.")
            elif (r.get("measured_prompt_tokens") or 0) > slot:
                probe.append(f"A {r['measured_prompt_tokens']:,}-token prompt was "
                             f"served **without** truncation or refusal, which puts "
                             f"the real ceiling above the {slot:,} `/props` reports.")
        d["context"]["probe"] = probe or [
            f"No probe reached past {slot:,} tokens, so the ceiling is reported from "
            f"`/props` rather than demonstrated."]

        print("measuring what the API reports...", file=sys.stderr)
        d["api_rate"] = api_reported_rate(max(2, args.repeats - 1))

    d["gpu_after"] = gpu_state()
    d["engine_after"] = {"pid": engine_argv().get("pid")}

    stem = Path(args.out) if args.out else (
        ROOT / "review" / f"MEASURED-{datetime.now(timezone.utc):%Y-%m-%d}-llm-throughput-context")
    stem.parent.mkdir(parents=True, exist_ok=True)
    stem.with_suffix(".json").write_text(json.dumps(d, indent=2) + "\n")
    stem.with_suffix(".md").write_text(markdown(d))
    print(f"wrote {stem.with_suffix('.json')}\nwrote {stem.with_suffix('.md')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
