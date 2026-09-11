"""Paths, limits and tunables. Values, not runtime objects.

These were module-level constants in server.py. Components import them directly:
they are literals and paths, fixed at import, so routing them through core.context
would be indirection for nothing -- and reading ctx at import time is exactly what
breaks, because a default argument evaluates when the module loads.
"""
from __future__ import annotations
import json
import logging
import os
import pathlib
import re
import time
from fastapi import (Depends, FastAPI, HTTPException, Request, Response, WebSocket,
                     WebSocketDisconnect, status as http)
from runtime.lib.ratelimits import BUDGETS as _BUDGETS  # noqa: E402


# The two GPU engines, and they are ours. They pointed into `external/` until 2026-08-20,
# which broke two standing rules at once -- nothing under `external/` is imported, built or
# linked, and nothing here ships under a third-party name -- and it took chat and image
# offline the moment that tree moved. `tools/sh/fork_engines.sh` builds both from our own tree
# and renames every shipped artefact; the constants below carry our names because a constant
# spelling a third-party product is the same leak as a filename doing it.
#
# Provenance is checkable, and `grep` is not how you check it: a name matches whether or not
# an engine is on disk. `readelf -d` on either binary shows a RUNPATH inside `engines/`, and
# each reports the *SyMoNeuRaL* commit it was built from -- the fork excludes `.git/`, so
# CMake walks up and reads this repo's HEAD. That is kept deliberately.
#: Both engine paths accept an environment override, added 2026-08-26 for the runtime cutover.
#:
#: The default is the historical `build/bin` location, so an unset variable changes nothing --
#: that is deliberate: a cutover mechanism whose OFF state differs from today's behaviour is
#: a second thing to debug when the cutover goes wrong.
#:
#: The override exists because a rebuilt engine is a whole RUNTIME DIRECTORY, not one file.
#: `readelf -d` shows RUNPATH `$ORIGIN` on the staged set, so the executable resolves its
#: eight SyMoNeuRaL shared objects from whatever directory it is launched out of. Copying
#: only the executable over the old one would leave it loading the OLD libraries beside it
#: and reporting a new hash while running old code -- which would pass a checksum test and
#: fail as a runtime.
#:
#: Rollback is therefore `unset SYMONEURAL_LLM_ENGINE` (or remove the line from
#: /etc/symoneural/api.env) and restart; the previous engine directory is untouched.
def _engine_path(env_var: str, default: pathlib.Path) -> pathlib.Path:
    raw = os.environ.get(env_var, "").strip()
    if not raw:
        return default
    p = pathlib.Path(raw)
    # A non-existent override is a misconfiguration that must be loud at import, not a
    # surface that silently reports `offline` for a reason nobody can find.
    if not p.is_file():
        # `logging.getLogger(...)` inline rather than the module-level `log`: this function is
        # CALLED at import time, ~130 lines before `log` is assigned, so referencing it here
        # would raise NameError and take the whole API down -- and only on the misconfigured
        # path, which is the one nobody exercises before shipping.
        logging.getLogger("symoneural.api").error(
            "%s points at %s which is not a file; falling back to %s", env_var, p, default)
        return default
    return p


HERE = next(p for p in pathlib.Path(__file__).resolve().parents if (p / "server.py").is_file())
ROOT = HERE.parent
RUN = ROOT / "run"
RUN.mkdir(exist_ok=True)   # ROOT/run, not HERE/run: gpu-governor.sh takes its mkdir lock
                           # there. Two lock dirs = two engines = 12 GB onto a 16 GB card.
GOVERNOR = ROOT / "scripts" / "gpu-governor.sh"
assert GOVERNOR.is_file(), (
    f"{GOVERNOR} is not a file: either the script is missing, or ROOT is wrong "
    f"(computed {ROOT} from {HERE}). On a complete checkout the first is likelier.")
LLM_ENGINE = _engine_path(
    "SYMONEURAL_LLM_ENGINE",
    ROOT / "symoneural-llm" / "build" / "bin" / "symoneural-llm")
DIFFUSE_ENGINE = _engine_path(
    "SYMONEURAL_DIFFUSE_ENGINE",
    ROOT / "symoneural-diffuse" / "build" / "bin" / "symoneural-diffuse")
MODELS = ROOT / "models"   # real weight files, not symlinks -- see models/README.md
SITE = ROOT / "site"          # the website: static files Caddy serves and deploy.sh publishes
RENDERS = HERE / "output"
CHAT_MODEL = MODELS / "llm" / "symon-1.0-30b-a3b-q2_k_l.gguf"
CHAT_ADAPTER = ROOT / "training" / "adapter" / "symoneural-lora.gguf"
CHAT_MODEL_LABEL = "SymonChat S1-30B-A3B"
CHAT_CTX_TOTAL = 33792
DRAFT_MODEL = MODELS / "llm" / "symon-1.0-draft-0.5b-q4_k_m.gguf"
SPEC_DRAFT_MAX = 2
FLUX = {
    "unet": MODELS / "image" / "symoneural-image-unet-q4_k.gguf",
    "vae": MODELS / "image" / "symoneural-image-vae.safetensors",
    "clip": MODELS / "image" / "symoneural-image-clip.safetensors",
    "t5": MODELS / "image" / "symoneural-image-t5-q8_0.gguf",
}
PORT = int(os.getenv("SYMONEURAL_PORT", "8800"))
LLAMA_PORT = 8081
MAX_PROMPT_CHARS = 100_000
QUEUE_DEPTH = 24
JOB_TIMEOUT_S = 1800
_RATE_SUGGESTED = {
    "ravencalc": (240, 6000),   # CPU only, never queues, ~0.1 s
    "chat":  (120, 2000),       # ~1-3 s of GPU, and the queue is the real backstop
    "remix": (40,  600),        # a longer generation
    "image": (20,  300),        # ~9 s of exclusive GPU each
    # Stickers. Same engine and the same exclusive GPU as image, so the same budget --
    # the name is listed here for a reason that is not cosmetic: LIMITS is built by
    # iterating this dict, and `check_rate` returns True for any surface it does not
    # find. A name absent from here is not "unlimited by choice", it is *unmeterable*,
    # and SYMONEURAL_RATE_SIGIL would be read by nothing. This surface is the one aimed at a
    # phone app, so leaving it unmeterable was the wrong default to inherit.
    "sigil": (20,  300),
    # Voice is the first surface where the comment above does NOT apply. It is CPU work with
    # no GPU queue in front of it, so nothing else rations it and the bucket is the only
    # backstop there is. ~0.65 s of CPU each: an order cheaper than image, an order dearer
    # than RavenCalc. The key must exist even while unset -- throttled_for() reads LIMITS on
    # its deny path, and LIMITS is built from this dict.
    "voice": (60,  900),
    # `/api/studio/models`. No GPU, no CPU to speak of -- one `read_text` and a validation
    # pass -- so this bucket is not protecting the card, and today it is unset like every
    # other one here. It is listed for the reason spelled out under "sigil": a surface absent
    # from this dict is not unlimited by choice, it is *unmeterable*, and SYMONEURAL_RATE_STUDIO
    # would be read by nothing. This is a public, unauthenticated list that a client polls,
    # which is exactly the shape where the operator may later want a ceiling, so the knob
    # exists ahead of the need. Same numbers as voice: cheap, but not free.
    "studio": (60,  900),
    # The plugin runtime's reads (`/api/exp/state`, `/plugins`, `/events`). Listed for the
    # reason spelled out under "sigil" and repeated under "studio": absent from this dict is
    # not unlimited-by-choice, it is unmeterable, and SYMONEURAL_RATE_EXP would be read by nothing.
    # The page polls `/events` with a cursor while it is open, so the ceiling has to sit above
    # a poll loop rather than below it -- the same shape as voice, and the same numbers.
    "exp": (60,  900),
}
def _rate_for(surface: str) -> tuple[int, int]:
    """Read a surface's budget from the environment. Unset means no limit."""
    raw = os.getenv(f"SYMONEURAL_RATE_{surface.upper()}", "").strip()
    if raw:
        try:
            per_min, per_hour = (int(x) for x in raw.split("/", 1))
            return per_min, per_hour
        except ValueError:
            log.warning("ignoring malformed SYMONEURAL_RATE_%s=%r, want N/N",
                        surface.upper(), raw)
    # Fall back to the published budget rather than to no limit. This returned (0, 0),
    # which check_rate reads as "allow", so every figure on /docs was decorative: 150
    # ravencalc posts in 1.64 s drew no 429 on 2026-09-08. A published ceiling that is not
    # applied is worse than no ceiling, because a reader plans against it.
    return _BUDGETS.get(surface, (0, 0))

LIMITS = {name: _rate_for(name) for name in _RATE_SUGGESTED}
ACQUIRE_TIMEOUT_S = 300
DISCONNECT_POLL_S = 0.25
_MINOR = re.compile(r"\b(child|children|kid|kids|toddler|infant|baby|babies|minor|minors|"
                    r"underage|preteen|pre-teen|teen|teens|teenage|teenager|schoolgirl|"
                    r"schoolboy|loli|lolita|shota|"
                    # Ages ONE TO SEVENTEEN only. `\d` matched a single digit, so "12 year
                    # old" walked straight through -- caught by tests/deny_regex.py, which
                    # is the entire reason that file exists. `\d{1,2}` would have been the
                    # obvious fix and is wrong in the other direction: it refuses "a 25
                    # year old woman, nude", which is exactly the legitimate adult prompt
                    # this gate must not touch. Enumerating 1-17 refuses neither.
                    r"(?:1[0-7]|[1-9]|one|two|three|four|five|six|seven|eight|nine|ten|"
                    r"eleven|twelve|thirteen|fourteen|fifteen|sixteen|seventeen)[\s-]*"
                    r"years?[\s-]*old)\b", re.I)
_SEXUAL = re.compile(r"\b(nude|nudity|naked|topless|undress\w*|nsfw|porn\w*|erotic\w*|"
                     r"sexual\w*|sexy|sex|xxx|hentai|fellatio|genital\w*|penis|vagina|"
                     r"pussy|breasts?|boobs?|nipples?|buttocks|masturbat\w*|orgasm\w*|"
                     r"intercourse|fucking|blowjob|cum|lewd|explicit\s+sex\w*)\b", re.I)
GALLERY_KEEP = 60
SYSTEM_PROMPT = (
    "You are SyMoNeuRaL, the admin representative and resident expert for SyMoNeuRaL, a "
    "SymonSays LLC company that builds custom local AI infrastructure. You run locally on "
    "the machine you are describing. Be concise, concrete and never oversell. "
    "Measured facts about this machine, which you may cite: NVIDIA RTX 5070 Ti, Blackwell "
    "sm_120, 70 SMs x 128 = 8,960 CUDA cores, 15.92 GiB VRAM (15,858 MB), 256-bit bus at "
    "14,001 MHz, 896.1 GB/s theoretical DRAM bandwidth, ~752 GB/s measured (~84% of peak), "
    "48 MB L2, PCIe Gen 3 x8 host cap (the GPU supports Gen 5) giving ~6.94 GB/s H2D and "
    "~7.20 GB/s D2H pinned. Decode is memory-bandwidth bound: every token reads the full "
    "weight set once, so tokens/second is roughly bandwidth divided by weight bytes. "
    "Never invent a number you were not given, and never quote a price -- direct pricing "
    "questions to symonsayadmin@symoneural.com."
)
_OPERATION_WORDS = [
    (re.compile(r"\b(integrat\w*|antideriv\w*)\b", re.I), "integrate"),
    (re.compile(r"\b(differentiat\w*|derivat\w*|d/d[a-z])\b", re.I), "differentiate"),
    (re.compile(r"\blimit\b", re.I), "limit"),
    (re.compile(r"\b(solve|roots?\s+of|solutions?\s+(?:to|of))\b", re.I), "solve"),
    (re.compile(r"\b(simplif\w*|reduce)\b", re.I), "simplify"),
    (re.compile(r"\b(expand|series|taylor)\b", re.I), "series"),
    (re.compile(r"\b(evaluat\w*|compute|calculate|what\s+is)\b", re.I), "evaluate"),
]
_EXPR_CANDIDATE = re.compile(r"[0-9A-Za-z_+\-*/^().,\s]{3,120}")
_HAS_MATH = re.compile(r"[+\-*/^]|\b[a-z]+\s*\(")
_VARIABLE = re.compile(r"\b(?:with respect to|wrt|in terms of|for)\s+([a-zA-Z])\b", re.I)
DOCS_HEADER = """
<header>
  <div class="wrap bar">
    <a class="logo" href="/">
      <img src="/mark-64.png" srcset="/mark-32.png 1x, /mark-64.png 2x" alt="SyMoNeuRaL"
           width="30" height="30">
      <b>SyMoNeu<i>RaL</i></b>
    </a>
    <nav>
      <a class="live" href="/chat.html"><s></s>Talk to the box</a>
      <a class="live" href="/image.html"><s></s>Make it draw</a>
      <a href="/ravencalc.html">RavenCalc</a>
      <a href="/#rack">Stack</a>
      <a class="cta ghost" href="/openapi.json">openapi.json</a>
    </nav>
  </div>
</header>
<div class="wrap" style="padding-top:26px">
  <p class="eyebrow"><img src="/terminal-64.png" alt="" width="20" height="20"
     style="display:inline-block;vertical-align:-4px;margin-right:8px">API Reference</p>
  <h1 style="margin:0;font-size:clamp(26px,3.4vw,38px);letter-spacing:-.022em;font-weight:680">
    SyMoNeuRaL API</h1>

  <div class="console" style="margin-top:20px">
    <div class="mod" data-src="live"><div class="tag"><s></s>VRAM free</div>
      <div class="val" id="m-vram">&mdash;</div><div class="sub">of 15.92 GiB</div>
      <div class="meter" id="m-vrambar"><i style="width:0%"></i></div></div>
    <div class="mod" data-src="live"><div class="tag"><s></s>Power draw</div>
      <div class="val" id="m-pwr">&mdash;</div><div class="sub">300 W limit</div>
      <div class="meter" id="m-pwrbar"><i style="width:0%"></i></div></div>
    <div class="mod" data-src="live"><div class="tag"><s></s>Resident</div>
      <div class="val sm" id="m-holder">idle</div><div class="sub">one surface at a time</div></div>
    <div class="mod" data-src="live"><div class="tag"><s></s>Queue</div>
      <div class="val" id="m-queue">0</div><div class="sub">jobs waiting</div></div>
    <div class="mod" data-src="measured"><div class="tag"><s></s>Rate limit</div>
      @@RATE@@</div>
    <div class="mod" data-src="measured"><div class="tag"><s></s>Prompt cap</div>
      <div class="val">@@CAP@@</div><div class="sub">chars &middot; refused, not truncated</div></div>
  </div>

  <div class="callout" style="margin-top:22px">
    <h3>Prefer the socket to the poller</h3>
    <p>
      <code style="color:var(--dim)">GET /api/ws</code> upgrades to a WebSocket and then stays
      quiet until the machine actually changes &mdash; one handshake, one baseline snapshot,
      then patches of a few dozen bytes. Polling <code style="color:var(--dim)">/api/status</code>
      works too and supports <code style="color:var(--dim)">If-None-Match</code>, so an
      unchanged rack costs a bare <code style="color:var(--dim)">304</code> with no body.
    </p>
    <p>
      <strong>Frames.</strong> Server sends <code style="color:var(--dim)">welcome</code> &rarr;
      <code style="color:var(--dim)">rack</code> (full) &rarr;
      <code style="color:var(--dim)">patch</code> (deltas, units addressed by id) and
      <code style="color:var(--dim)">bus</code> (an agent announcing what it did).
      Client may send <code style="color:var(--dim)">ping</code>,
      <code style="color:var(--dim)">rack</code>,
      <code style="color:var(--dim)">chat</code>, <code style="color:var(--dim)">ravencalc</code>,
      <code style="color:var(--dim)">remix</code> &mdash; rate limited exactly like the REST
      routes, because holding a socket open is not a way around the caps.
    </p>
  </div>
</div>
"""
API_REFERENCE_STYLE = """<style>
/* The scoped-application index at the top of this page. `ar-` prefixed like everything
   else here, for the reason the block comment above gives at length. */
.ar-index{margin:0 0 34px;padding:0 0 30px;border-bottom:1px solid var(--sfline)}
.ar-index h2{margin:0 0 10px;font-size:clamp(20px,2.4vw,27px);letter-spacing:-.015em;
  font-weight:665}
.ar-runtimes{display:grid;gap:14px;margin-top:20px;
  grid-template-columns:repeat(auto-fit,minmax(260px,1fr))}
.ar-rt{background:var(--sf3);border:1px solid var(--sfline);border-radius:var(--r-panel);
  padding:16px 18px}
.ar-rt h3{margin:0;font:600 var(--t6)/1.4 ui-monospace,"SF Mono",Menlo,Consolas,monospace;
  letter-spacing:.05em;color:var(--accent)}
.ar-rt>p{margin:5px 0 12px;color:var(--faint);font-size:var(--t6);line-height:1.5}
.ar-apps{display:flex;flex-direction:column;gap:9px}
.ar-applink{display:block;text-decoration:none;color:var(--fg);font-size:var(--t5);
  min-height:32px;display:flex;align-items:center}
.ar-applink:hover b{color:var(--accent)}
.ar-applink b{font-weight:620;letter-spacing:-.003em}
.ar-appkids{display:flex;flex-wrap:wrap;gap:7px;margin:5px 0 3px 13px;
  padding-left:11px;border-left:1px solid var(--sfline)}
.ar-appkid{display:inline-flex;align-items:center;min-height:30px;padding:3px 10px;
  border:1px solid var(--sfline);border-radius:var(--r-pill);text-decoration:none;
  color:var(--dim);font-size:var(--t6)}
.ar-appkid:hover{color:var(--accent);border-color:var(--accent)}

.ar-wrap{max-width:1080px;margin:0 auto;padding:0 22px 80px}
.ar-note{color:var(--dim);margin:18px 0 26px;max-width:78ch;line-height:1.55}
.ar-group{margin:34px 0 0}
.ar-group>h2{font-size:15px;letter-spacing:.04em;text-transform:uppercase;color:var(--dim);
  font-weight:640;margin:0 0 10px;padding-bottom:8px;border-bottom:1px solid var(--line)}
.ar-op{border:1px solid var(--line);border-radius:9px;margin:9px 0;background:var(--panel)}
.ar-op>summary{cursor:pointer;padding:11px 14px;display:flex;gap:11px;align-items:baseline;
  flex-wrap:wrap;list-style:none}
.ar-op>summary::-webkit-details-marker{display:none}
.ar-op>summary:hover{background:rgba(255,255,255,.028)}
.ar-verb{font:600 11px/1.5 ui-monospace,SFMono-Regular,Menlo,monospace;letter-spacing:.07em;
  padding:3px 8px;border-radius:5px;border:1px solid var(--line);flex:none}
.ar-get{color:#7fd1b9;border-color:#2f5f52}
.ar-post{color:#8fb8f0;border-color:#33507d}
.ar-put,.ar-patch{color:#e0c07a;border-color:#6b5a2e}
.ar-delete{color:#e59a9a;border-color:#7a3f3f}
.ar-ws{color:#c9a2e8;border-color:#5d3f74}
.ar-path{font:500 13.5px/1.6 ui-monospace,SFMono-Regular,Menlo,monospace;
  word-break:break-word;overflow-wrap:anywhere}
.ar-sum{color:var(--dim);font-size:13.5px;line-height:1.6;flex:1 1 220px;min-width:0}
.ar-body{padding:4px 14px 16px;border-top:1px solid var(--line)}
.ar-body p{line-height:1.6;max-width:80ch}
.ar-body h3{font-size:12px;letter-spacing:.05em;text-transform:uppercase;color:var(--dim);
  margin:18px 0 7px;font-weight:640}
.ar-tbl{width:100%;border-collapse:collapse;font-size:13.5px;display:block;overflow-x:auto}
.ar-tbl th,.ar-tbl td{text-align:left;padding:6px 12px 6px 0;vertical-align:top;
  border-bottom:1px solid var(--line);line-height:1.55}
.ar-tbl th{color:var(--dim);font-weight:600;font-size:11.5px;letter-spacing:.04em;
  text-transform:uppercase;white-space:nowrap}
.ar-mono{font-family:ui-monospace,SFMono-Regular,Menlo,monospace;overflow-wrap:anywhere}
.ar-req{color:#e59a9a;font-size:11px;letter-spacing:.04em}
.ar-pre{background:var(--sunk,rgba(0,0,0,.28));border:1px solid var(--line);border-radius:7px;
  padding:11px 13px;overflow-x:auto;font:400 12.5px/1.65 ui-monospace,SFMono-Regular,Menlo,
  monospace;white-space:pre;margin:0}
.ar-fold{margin:9px 0 0}
.ar-fold>summary{cursor:pointer;color:var(--dim);font-size:12.5px;padding:4px 0}
.ar-count{color:var(--dim);font-size:12px;font-variant-numeric:tabular-nums}
.ar-fail{border:1px solid #7a3f3f;border-radius:9px;padding:14px 16px;color:#e59a9a;
  line-height:1.6}
@media (max-width:560px){.ar-op>summary{gap:8px}.ar-sum{flex-basis:100%}}
</style>
"""
API_REFERENCE_SCRIPT = """
<script>
(function () {
  var esc = function (s) {
    return String(s == null ? "" : s).replace(/[&<>"]/g, function (c) {
      return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c];
    });
  };

  // $ref resolution, depth-capped. A schema may legitimately reference itself -- a tree
  // node with children of its own type is the ordinary case -- so an uncapped walk hangs
  // the tab rather than failing visibly. Six levels renders every schema this API has.
  function resolve(node, doc, depth) {
    if (!node || typeof node !== "object" || depth > 6) return node;
    if (node.$ref) {
      var parts = String(node.$ref).replace(/^#\\//, "").split("/");
      var at = doc;
      for (var i = 0; i < parts.length; i++) {
        at = at && at[parts[i]];
      }
      return at ? resolve(at, doc, depth + 1) : { type: "object" };
    }
    return node;
  }

  function typeOf(schema, doc, depth) {
    var s = resolve(schema, doc, depth || 0);
    if (!s) return "any";
    if (s.anyOf || s.oneOf) {
      return (s.anyOf || s.oneOf).map(function (m) {
        return typeOf(m, doc, (depth || 0) + 1);
      }).join(" | ");
    }
    if (s.enum) return s.enum.map(function (v) { return JSON.stringify(v); }).join(" | ");
    if (s.type === "array") return typeOf(s.items, doc, (depth || 0) + 1) + "[]";
    if (s.type) return s.format ? s.type + " (" + s.format + ")" : s.type;
    if (s.properties) return "object";
    return "any";
  }

  // Fields are listed in full, never sampled. A reference that shows "the first few"
  // properties is the same failure as a truncated attribution: the reader cannot tell
  // whether what they need is missing or absent.
  function fieldTable(schema, doc) {
    var s = resolve(schema, doc, 0);
    if (!s || !s.properties) return "";
    var required = s.required || [];
    var rows = Object.keys(s.properties).map(function (name) {
      var p = resolve(s.properties[name], doc, 0) || {};
      var need = required.indexOf(name) >= 0
        ? '<span class="ar-req">required</span>' : "";
      var extra = [];
      if (p.minimum !== undefined) extra.push("min " + p.minimum);
      if (p.maximum !== undefined) extra.push("max " + p.maximum);
      if (p.maxLength !== undefined) extra.push("max length " + p.maxLength);
      if (p.default !== undefined) extra.push("default " + JSON.stringify(p.default));
      return "<tr><td class=\\"ar-mono\\">" + esc(name) + "</td>"
        + '<td class="ar-mono">' + esc(typeOf(s.properties[name], doc, 0)) + "</td>"
        + "<td>" + need + "</td>"
        + "<td>" + esc(p.description || "")
        + (extra.length ? " <span class=\\"ar-count\\">" + esc(extra.join(" \\u00b7 "))
            + "</span>" : "")
        + "</td></tr>";
    });
    if (!rows.length) return "";
    return '<table class="ar-tbl"><thead><tr><th>Field</th><th>Type</th><th></th>'
      + "<th>Notes</th></tr></thead><tbody>" + rows.join("") + "</tbody></table>";
  }

  function paramTable(params, doc) {
    if (!params || !params.length) return "";
    var rows = params.map(function (p) {
      return "<tr><td class=\\"ar-mono\\">" + esc(p.name) + "</td>"
        + "<td>" + esc(p.in) + "</td>"
        + '<td class="ar-mono">' + esc(typeOf(p.schema, doc, 0)) + "</td>"
        + "<td>" + (p.required ? '<span class="ar-req">required</span>' : "") + "</td>"
        + "<td>" + esc(p.description || "") + "</td></tr>";
    });
    return "<h3>Parameters</h3>"
      + '<table class="ar-tbl"><thead><tr><th>Name</th><th>In</th><th>Type</th><th></th>'
      + "<th>Notes</th></tr></thead><tbody>" + rows.join("") + "</tbody></table>";
  }

  function schemaOf(content, doc) {
    if (!content) return null;
    var key = Object.keys(content)[0];
    return key ? content[key].schema : null;
  }

  function render(doc) {
    var root = document.getElementById("ar-root");
    var groups = {}, order = [], total = 0;

    Object.keys(doc.paths || {}).sort().forEach(function (path) {
      var item = doc.paths[path];
      Object.keys(item).forEach(function (verb) {
        if (["get", "post", "put", "patch", "delete", "head", "options"]
            .indexOf(verb) < 0) return;
        var op = item[verb];
        var tag = (op.tags && op.tags[0]) || path.split("/")[2] || "root";
        if (!groups[tag]) { groups[tag] = []; order.push(tag); }
        groups[tag].push({ path: path, verb: verb, op: op });
        total++;
      });
    });

    if (!total) {
      root.innerHTML = '<div class="ar-fail">The schema loaded but declares no '
        + "operations. That is a fault in the API, not in this page.</div>";
      return;
    }

    var html = ['<p class="ar-count">' + total + " operations across "
      + order.length + ' groups, read from <span class="ar-mono">/openapi.json</span> '
      + "at " + esc(new Date().toLocaleTimeString()) + ".</p>"];

    order.sort().forEach(function (tag) {
      html.push('<section class="ar-group"><h2>' + esc(tag) + "</h2>");
      groups[tag].forEach(function (entry) {
        var op = entry.op, doc_ = doc;
        var body = [];
        if (op.description) {
          body.push("<p>" + esc(op.description) + "</p>");
        }
        body.push(paramTable(op.parameters, doc_));

        var reqSchema = schemaOf(op.requestBody && op.requestBody.content, doc_);
        if (reqSchema) {
          var t = fieldTable(reqSchema, doc_);
          body.push("<h3>Request body</h3>" + (t ||
            '<p class="ar-count">Free-form; see the schema below.</p>'));
          body.push('<details class="ar-fold"><summary>Raw request schema</summary>'
            + '<pre class="ar-pre">'
            + esc(JSON.stringify(resolve(reqSchema, doc_, 0), null, 2))
            + "</pre></details>");
        }

        var responses = op.responses || {};
        var codes = Object.keys(responses).sort();
        if (codes.length) {
          body.push("<h3>Responses</h3>");
          body.push('<table class="ar-tbl"><thead><tr><th>Code</th><th>Meaning</th>'
            + "</tr></thead><tbody>"
            + codes.map(function (code) {
                return "<tr><td class=\\"ar-mono\\">" + esc(code) + "</td><td>"
                  + esc((responses[code] || {}).description || "") + "</td></tr>";
              }).join("")
            + "</tbody></table>");
          codes.forEach(function (code) {
            var rs = schemaOf((responses[code] || {}).content, doc_);
            if (!rs) return;
            body.push('<details class="ar-fold"><summary>Response schema for '
              + esc(code) + "</summary>"
              + (fieldTable(rs, doc_) || "")
              + '<pre class="ar-pre">'
              + esc(JSON.stringify(resolve(rs, doc_, 0), null, 2))
              + "</pre></details>");
          });
        }

        html.push('<details class="ar-op"><summary>'
          + '<span class="ar-verb ar-' + entry.verb + '">'
          + esc(entry.verb.toUpperCase()) + "</span>"
          + '<span class="ar-path">' + esc(entry.path) + "</span>"
          + '<span class="ar-sum">' + esc(op.summary || "") + "</span>"
          + '</summary><div class="ar-body">' + body.join("") + "</div></details>");
      });
      html.push("</section>");
    });

    root.innerHTML = html.join("");
  }

  fetch("/openapi.json", { headers: { accept: "application/json" } })
    .then(function (r) {
      if (!r.ok) throw new Error("/openapi.json answered " + r.status);
      return r.json();
    })
    .then(render)
    .catch(function (err) {
      // Says what actually failed. A reference page that renders an empty list on a fetch
      // error reads as "this API has no endpoints", which is a worse lie than an error.
      document.getElementById("ar-root").innerHTML =
        '<div class="ar-fail">Could not read <span class="ar-mono">/openapi.json</span>: '
        + esc(err && err.message ? err.message : err)
        + ". The reference is generated from the running service, so this means the "
        + "service is not answering -- not that the reference is missing.</div>";
    });
})();
</script>
"""
DELEGATE_POLL_S = 2.0
DELEGATE_STALE_S = 6.0
OPERATOR_HEADER = "X-Symoneural-Token"
OPERATOR_HEADER_LEGACY = "X-Sym-Token"
STUDIO_REGISTRY_FILE = RUN / "registry.json"
SECTION_PAGES = {
    "overview": "overview.html",
    "livestack": "livestack.html",
    "controlboard": "controlboard.html",
    "receipts": "receipts.html",
}
LIVESTACK_PAGES = {
    "image": "image.html",
}
LOCAL_ONLY = ("127.0.0.1", "::1", "localhost")
_PROXY_HEADERS = (
    "forwarded",                # RFC 7239
    "x-forwarded-for",
    "x-forwarded-host",
    "x-forwarded-proto",        # Caddy sets this on everything it proxies
    "x-forwarded-port",
    "x-real-ip",
    "via",                      # RFC 9110; any conforming proxy appends it
)
_RETIRED_PAGES = {"/tuner.html": "/streamer.html",
                  "/tuner-watch.html": "/streamer-watch.html"}
