"""Spec-mediated reimplementation: read a source file, write down what it *does*, then have
a second turn write fresh code from that description alone.

## What this is not

The brief called the two halves a "Dirty Room" and a "Clean Room", and that is worth being
precise about, because a clean-room reimplementation is a legal representation and this is
not one. A clean room means two teams who cannot talk to each other: one reads the original
and writes a specification, the other has provably never seen it and implements from the
specification only, and the barrier is *institutional* -- signed, logged, auditable.

Here, one model in one process reads the source and writes the replacement. Both halves run
through `inference.pick()`, on the same weights, in the same box. There is no barrier. The
line "do NOT output any original variable names" is an instruction to a 7B model with nothing
verifying it, and a model that ignores it produces output indistinguishable from one that
obeyed -- which is the whole problem.

So this module does not assert the barrier held. It **measures** how much of the original
came through, and returns the number in the result:

    leakage.leaked        identifiers present in BOTH the source and the spec
    leakage.leaked_raw    the same count before the stoplist below is applied
    leakage.ratio         leaked / distinct source identifiers

A non-zero `leaked` is the direct evidence that the instruction did not hold. Nothing here
refuses on that basis -- refusing would be this module deciding a legal question -- but the
figure travels with the spec, so a human deciding whether to ship the output is deciding
with the reading in front of them rather than with a label.

The same applies to the licence. `oematch` already knows what the source is and under what
terms, so provenance is carried forward as a fact: project, recipe, layer, licence, and
whether the licence carries a notice-retention obligation. This repo already treats
attribution as a licence condition rather than a courtesy -- `built on Qwen2.5-7B-Instruct`
is on the site because Apache-2.0 requires it, and an ellipsis rule that truncated it was
removed for that reason. Silently dropping a licence on the way through a reimplementation
pipeline is the same failure with better cover, so the attribution block is generated from
the provenance and `generate_native_code` puts it at the top of what it returns.

**A copyleft source is not laundered by passing through here, and this module says so rather
than implying otherwise.** `provenance.copyleft` is reported and `attribution_required` stays
true; whether a GPL-derived rewrite can be shipped under other terms is a legal decision and
belongs to the five things `owner: garrett` is reserved for.

## Why it does not use litellm, and why the model name in the result is not the one asked for

The brief's script called `litellm.acompletion` against `ollama/SyMoNeuRaL32b`. Neither is
available and neither can be made available here:

* **Ollama is not installed on this box.** No binary on `PATH`, no `~/.ollama`, nothing
  listening on 11434 -- `inference.py` says so at length. The real engine is llama-server on
  127.0.0.1:8081, serving a 7B, and `inference.Backend` is the adapter for both.
* **litellm cannot be installed into the interpreter that serves this.** The serving path is
  the *system* interpreter deliberately (fastapi, uvicorn, pydantic and sympy are OS
  packages), and `pip install` into it is blocked by the repo's own deny rules.

So both turns go through `inference.pick()`, and the result reports `backend`, `base` and the
`model` string the engine itself returned -- not the name that was requested. A pipeline that
prints back the model you asked for while a different one answered is the kind of figure this
project has a rule against.

## Two turns, no GPU lease

Neither tool takes a governor lease. llama-server's lifecycle belongs to `api.py`, inside
`gpu.hold("chat")`; a tool acquiring a lease would be the second-spawner race `inference.py`
exists to avoid, and it would lock out the CLI for the duration. RavenCalc's "deliberately
never takes the lock" is the same rule. The consequence is real and is not engineered around:
a graph that mixes one of these nodes with a render node will contend during the render, and
the spec call will wait on the card like anything else.

## No `from __future__ import annotations` in this module, on purpose

`registry._json_type` renders a dataclass by walking `dataclasses.fields(ann)` and reading
`f.type`. With the future import in effect that attribute is the annotation's *source text* --
the string `"Provenance"` -- which matches nothing in `_PRIMITIVES`, is not a class, and falls
through to the untyped branch. The wire would still work and the schema handed to the model
and to every MCP client would quietly lose its shape. `FunctionalSpec` is the connection
wire, so its shape is the point.
"""
import dataclasses
import hashlib
import json
import os
import pathlib
import re
import shutil
import subprocess

from ..lib import inference
from ..lib import workspace
from ..lib.registry import tool

# ---------------------------------------------------------------------------
# the wire
# ---------------------------------------------------------------------------


@dataclasses.dataclass
class Provenance:
    """What the source was, and what its licence obliges. Never inferred from the filename."""
    source_path: str
    sha256: str
    bytes_read: int
    project: str
    recipe: str
    layer: str
    license: str
    license_source: str
    license_determined: bool
    attribution_required: bool
    copyleft: bool
    identified_by: str


@dataclasses.dataclass
class Leakage:
    """How much of the original survived into the description of it.

    `leaked_raw` is before the stoplist, `leaked` after. Both are reported because the
    stoplist is a judgement -- it holds `data`, `value` and `name`, so a variable genuinely
    called `data` is invisible in `leaked` and counted in `leaked_raw`. Two numbers with the
    method named beats one number with the method hidden.
    """
    source_identifiers: int
    leaked: list[str]
    leaked_count: int
    leaked_raw_count: int
    ratio: float
    method: str


@dataclasses.dataclass
class FunctionalSpec:
    """The connection wire: everything the second turn is allowed to see.

    The first six fields are the brief's. `provenance` and `leakage` were added because a
    spec that has lost the licence of the thing it describes is not a smaller spec, it is a
    wrong one -- and because the leak figure is only useful if it travels with the artefact
    it is a figure about.
    """
    module_name: str
    purpose: str
    inputs: list[str]
    outputs: list[str]
    logic_steps: list[str]
    edge_cases: list[str]
    provenance: Provenance
    leakage: Leakage


SPEC_FIELDS = ("module_name", "purpose", "inputs", "outputs", "logic_steps", "edge_cases")

# The ComfyUI socket type. A ComfyUI edge is legal when the two type strings are equal, so
# this literal IS the connection constraint -- it is what stops a STRING output being dropped
# into the clean-room node's spec input. Shared from here so the node pack and the tools
# cannot drift to two different spellings.
SOCKET = "FUNCTIONAL_SPEC"

# ---------------------------------------------------------------------------
# measurement
# ---------------------------------------------------------------------------

_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]{2,}")

# Language furniture and ordinary English, so `ratio` is about the source's own vocabulary
# rather than about how many times the word `return` appears in both files. Listed rather
# than computed because a reader has to be able to audit what was excluded.
_STOPLIST = frozenset("""
int char void long short float double unsigned signed const static extern struct union enum
typedef sizeof return while for if else switch case break continue goto default inline
register volatile restrict NULL true false bool size_t ssize_t uint8_t uint16_t uint32_t
uint64_t int8_t int16_t int32_t int64_t include define ifndef endif ifdef pragma printf
fprintf sprintf snprintf malloc calloc realloc free memcpy memmove memset strlen strcpy
strncpy strcmp stdout stderr stdin errno assert
def class self import from None True False and not in is with as try except raise yield
lambda global nonlocal del pass elif finally async await print str dict set tuple bytes
object super property staticmethod classmethod
the that this these those when where which what who whom whose then than there here
data value values name names file files path paths type types kind list items item index
count length size len result results input inputs output outputs error errors buffer
number numbers string strings function functions module modules code source target
first second next last new old get set add all any one two each other same such
""".split())


def _identifiers(text: str) -> set[str]:
    return set(_IDENT_RE.findall(text))


def _leakage(source: str, spec_text: str) -> Leakage:
    """Identifiers present in both, whole-word and case-sensitive.

    Case-sensitive on purpose: `buffer` the variable and `Buffer` the English word at the
    start of a sentence are different claims, and folding case would report the second as a
    leak of the first. A model that leaks an identifier leaks it verbatim -- that is what
    makes it a leak -- so the strict comparison is also the accurate one.
    """
    src = _identifiers(source)
    spec_ids = _identifiers(spec_text)
    raw = src & spec_ids
    kept = sorted(raw - _STOPLIST)
    denom = len(src - _STOPLIST) or 1
    return Leakage(
        source_identifiers=len(src - _STOPLIST),
        leaked=kept,
        leaked_count=len(kept),
        leaked_raw_count=len(raw),
        ratio=round(len(kept) / denom, 4),
        method=("whole-word case-sensitive identifier intersection, "
                f"{len(_STOPLIST)}-word stoplist applied to `leaked` and not to `leaked_raw`"),
    )


# ---------------------------------------------------------------------------
# provenance
# ---------------------------------------------------------------------------

# Notice-retention: every one of these obliges the licence text or a copyright notice to be
# carried. Reproduced from the licence identifiers oematch reports, which are SPDX.
_NOTICE = ("MIT", "BSD", "Apache", "ISC", "Zlib", "libpng", "PSF", "Python", "BSL",
           "Unicode", "OpenSSL", "curl", "X11", "MPL", "CDDL", "EPL", "GPL", "LGPL", "AGPL")
_COPYLEFT = ("GPL", "LGPL", "AGPL", "MPL", "EPL", "CDDL", "OSL", "EUPL", "CeCILL")


def _license_flags(spdx: str) -> tuple[bool, bool]:
    """(attribution_required, copyleft) from an SPDX-ish expression.

    Substring matching, and it over-reports rather than under-reports: `GPL-2.0-only WITH
    Classpath-exception-2.0` is flagged copyleft, and deciding what the exception does to
    that is not a decision a substring match gets to make.

    **An undetermined licence is reported as copyleft**, and that is the whole point of this
    function rather than an oddity of it. The first real run of this module read a
    GPL-3.0-or-later file, got `unsupported artifact` out of oematch -- which fingerprints
    packages, not single files -- and reported `copyleft: false` about the GNU General Public
    License. A false negative here is silence exactly where the module owes a warning, so
    "nothing identified" now produces the warning and says the licence was not determined.
    An MIT file mislabelled copyleft costs a human thirty seconds; a GPL file mislabelled
    permissive costs a licence breach.
    """
    if not spdx or spdx.strip() in ("-", "unknown", "CLOSED"):
        return True, True
    return (any(k.lower() in spdx.lower() for k in _NOTICE) or True,
            any(k.lower() in spdx.lower() for k in _COPYLEFT))


# An SPDX tag is authoritative and is checked first. The prose patterns below are the
# fallback for the majority of files that predate the convention -- CGMiner's fan controller
# carries eight lines of GPL paragraph and no tag at all. Ordered longest-claim-first so
# "Lesser General Public License" is not read as the GPL it contains as a substring.
_SPDX_TAG_RE = re.compile(r"SPDX-License-Identifier:\s*([^\s*/#;]+(?:\s+(?:OR|AND|WITH)\s+[^\s*/#;]+)*)")

_LICENCE_PHRASES = (
    ("GNU Affero General Public License", "AGPL-3.0"),
    ("GNU Lesser General Public License", "LGPL-2.1"),
    ("GNU Library General Public License", "LGPL-2.0"),
    ("GNU General Public License", "GPL-2.0"),
    ("Mozilla Public License", "MPL-2.0"),
    ("Eclipse Public License", "EPL-2.0"),
    ("Common Development and Distribution License", "CDDL-1.0"),
    ("Apache License", "Apache-2.0"),
    ("MIT License", "MIT"),
    ("Redistribution and use in source and binary forms", "BSD-3-Clause"),
    ("Permission is hereby granted, free of charge", "MIT"),
    ("Permission to use, copy, modify, and/or distribute this software", "ISC"),
    ("Boost Software License", "BSL-1.0"),
    ("zlib License", "Zlib"),
)

_HEADER_BYTES = 6000


def _license_from_text(text: str) -> tuple[str, str]:
    """(spdx, how) read out of the file's own header. ("", "") when it says nothing.

    This is the primary signal for a single source file and oematch is the secondary one,
    which is the opposite of how this module was first written. oematch fingerprints a
    `.deb`, a tarball, a wheel, an ELF or a directory; handed one `.c` file it answers
    `unsupported artifact`, so on the input this tool actually takes it could never
    contribute a licence at all. The licence, meanwhile, is usually sitting in the first
    twenty lines in plain English.

    Only the header is scanned. A licence phrase appearing 4000 lines into a source file is
    far more likely to be a string constant, a comment about somebody else's code, or the
    text of a `--version` banner than it is a statement about this file.
    """
    head = text[:_HEADER_BYTES]
    tag = _SPDX_TAG_RE.search(head)
    if tag:
        return tag.group(1).strip(), "file header (SPDX tag)"
    # Flatten the comment furniture before matching. A GPL header wraps at 80 columns and
    # the seam falls wherever it falls: `GNU General Public\n * License` is one of the
    # commonest wraps there is, and a plain substring search over the raw text misses it and
    # reports the file as unlicensed. Strip the leading `*`/`//`/`#`/`;` of each line, then
    # collapse every whitespace run to one space, so the paragraph is one line to match on.
    head = re.sub(r"(?m)^[\s]*(?:/\*+|\*+/|\*|//+|#+|;+|--)[ \t]?", " ", head)
    head = re.sub(r"\s+", " ", head)
    for phrase, spdx in _LICENCE_PHRASES:
        if phrase.lower() in head.lower():
            # "either version 3 ... or (at your option) any later version" is the GPL's own
            # wording for -or-later, and the version number is in the sentence beside it.
            if spdx.startswith(("GPL", "LGPL", "AGPL")):
                base = spdx.split("-")[0]
                ver = re.search(r"version\s+([123](?:\.\d+)?)", head, re.I)
                num = (ver.group(1) if ver else spdx.split("-")[1])
                later = "or-later" if "any later version" in head.lower() else "only"
                return f"{base}-{num}.0-{later}" if "." not in num else f"{base}-{num}-{later}", \
                       "file header (licence text)"
            return spdx, "file header (licence text)"
    return "", ""


def _oematch(path: pathlib.Path) -> dict:
    """Ask `oematch` what this file is. Absent tool and absent corpus are both fine.

    Called as a subprocess rather than imported: oematch is a separately packaged Debian
    tool whose `pyproject.toml` declares `dependencies = []`, and importing it here would
    make Studio's GPU stack a soft dependency of a stdlib-only package in the direction
    nobody wants. If it is not installed the result says so -- `identified_by: "unavailable"`
    -- and never invents a project name, because a fabricated licence is worse than no
    licence.
    """
    exe = shutil.which("oematch")
    if not exe:
        return {"identified_by": "unavailable", "detail": "oematch is not on PATH"}
    try:
        out = subprocess.run([exe, "match", "--json", "--top", "1", str(path)],
                             capture_output=True, text=True, timeout=120)
    except (OSError, subprocess.SubprocessError) as exc:
        return {"identified_by": "unavailable", "detail": f"{type(exc).__name__}: {exc}"}
    if out.returncode != 0:
        return {"identified_by": "unavailable",
                "detail": (out.stderr or "").strip()[:400] or f"exit {out.returncode}"}
    try:
        doc = json.loads(out.stdout)
    except ValueError:
        return {"identified_by": "unavailable", "detail": "oematch did not return JSON"}
    rows = doc.get("matches") or []
    if not rows:
        return {"identified_by": "oematch", "detail": "no recipe matched this file"}
    top = rows[0]
    return {
        "identified_by": "oematch",
        "project": top.get("pn") or "",
        "recipe": top.get("recipe") or "",
        "layer": top.get("layer") or "",
        "license": top.get("recipe_license") or "",
        "score": top.get("score"),
        "evidence": top.get("evidence") or [],
    }


# ---------------------------------------------------------------------------
# reading the source
# ---------------------------------------------------------------------------

# Never read, whatever the argument says. These three are the company's only trade secrets
# and are protected by not being public; a tool that reads an arbitrary path, hands the bytes
# to a model and returns the answer through an HTTP surface is precisely the route by which
# they stop being unpublished. `training/adapter/` is weights and would be unreadable as text
# anyway, which is not a reason to leave it off the list.
_FORBIDDEN = ("training/corpus.jsonl", "training/build_dataset.py", "training/adapter")


def _refuse(path: pathlib.Path) -> str | None:
    try:
        rel = path.resolve().relative_to(workspace.ROOT.resolve()).as_posix()
    except (ValueError, OSError):
        return None
    for bad in _FORBIDDEN:
        if rel == bad or rel.startswith(bad + "/"):
            return rel
    return None


def _read(path_s: str, max_bytes: int) -> tuple[pathlib.Path, str, str]:
    path = pathlib.Path(path_s).expanduser()
    if not path.is_absolute() and workspace.ROOT:
        path = workspace.ROOT / path
    if not path.is_file():
        raise FileNotFoundError(f"no such file: {path}")
    bad = _refuse(path)
    if bad:
        raise PermissionError(
            f"{bad} is one of this repo's three unpublished artefacts and is never read here")
    raw = path.read_bytes()[: max(1024, max_bytes)]
    return path, raw.decode("utf-8", "replace"), hashlib.sha256(path.read_bytes()).hexdigest()


def _json_object(text: str) -> dict:
    """The first JSON object in a model's answer.

    Local models fence their JSON, prefix it with "Here is the specification:", or emit it
    after a paragraph of reasoning, and all three are ordinary rather than a malfunction. A
    brace-counting scan is what survives them; `json.loads` on the whole reply does not.
    """
    depth = 0
    start = -1
    in_str = False
    esc = False
    for i, ch in enumerate(text):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0 and start >= 0:
                try:
                    return json.loads(text[start:i + 1])
                except ValueError:
                    start, depth = -1, 0
    raise ValueError("no JSON object in the model's reply")


def _as_list(v) -> list[str]:
    if v is None:
        return []
    if isinstance(v, str):
        return [v] if v.strip() else []
    if isinstance(v, dict):
        return [f"{k}: {x}" for k, x in v.items()]
    return [x if isinstance(x, str) else json.dumps(x) for x in v]


# ---------------------------------------------------------------------------
# turn one -- read the source, describe the behaviour
# ---------------------------------------------------------------------------

ANALYST_SYSTEM = """You are a software behaviour analyst. You are given the text of a source
file. Describe WHAT IT DOES, at the level of observable behaviour, and nothing about how it is
written.

Answer with a single JSON object and no other text, with exactly these keys:
  module_name   a short neutral name for the behaviour, NOT the original file or symbol name
  purpose       one or two sentences on what a caller gets from this
  inputs        array of strings: what comes in, described by role and type
  outputs       array of strings: what goes out, described by role and type
  logic_steps   array of strings: the behaviour in order, as steps a reader could follow
  edge_cases    array of strings: boundary conditions, failures and limits

Do not reproduce original identifiers, function names, variable names, string literals,
macro names, comments or code syntax. Describe roles, not names: "the caller-supplied
destination buffer", not "dst". If a step can only be stated by naming an original
identifier, restate the step."""


@tool("cleanroom")
async def extract_spec(source_path: str, max_bytes: int = 60000,
                       temperature: float = 0.2) -> dict:
    """Read a source file and return a behavioural specification of it, plus a measurement of
    how much of the original leaked into that specification.

    The spec is the wire: `generate_native_code` takes it and never sees the file. Provenance
    (project, recipe, licence) comes from `oematch` when it is installed and is carried in the
    spec rather than alongside it.

    source_path: file to read; relative paths resolve against the repo root.
    max_bytes: cap on how much of the file is sent to the model.
    temperature: sampling temperature for the description turn.
    """
    try:
        path, source, sha = _read(source_path, int(max_bytes))
    except (FileNotFoundError, PermissionError, OSError) as exc:
        return {"ok": False, "error": type(exc).__name__, "detail": str(exc)}

    be = await inference.pick()
    if be is None:
        return {"ok": False, "error": "no_backend",
                "detail": "no OpenAI-compatible engine answered; see /api/studio/state"}

    resp = await be.chat(
        messages=[{"role": "system", "content": ANALYST_SYSTEM},
                  {"role": "user", "content": f"Source file text follows.\n\n{source}"}],
        temperature=float(temperature), max_tokens=2048)
    try:
        content = resp["choices"][0]["message"]["content"] or ""
    except (KeyError, IndexError, TypeError):
        return {"ok": False, "error": "bad_response", "detail": json.dumps(resp)[:600]}
    try:
        doc = _json_object(content)
    except ValueError as exc:
        return {"ok": False, "error": "unparsed_spec", "detail": str(exc),
                "reply": content[:1200]}

    ident = _oematch(path)
    # The file's own header first, oematch second. oematch answers `unsupported artifact`
    # for a single source file, so on this tool's actual input it contributes a project name
    # (when the path is a directory) and, in the single-file case, nothing whatsoever.
    licence, how = _license_from_text(source)
    if not licence and ident.get("license"):
        licence, how = ident["license"], "oematch recipe LICENSE"
    attribution_required, copyleft = _license_flags(licence)
    prov = Provenance(
        source_path=str(path), sha256=sha, bytes_read=len(source),
        project=ident.get("project", ""), recipe=ident.get("recipe", ""),
        layer=ident.get("layer", ""), license=licence,
        license_source=how or "undetermined", license_determined=bool(licence),
        attribution_required=attribution_required, copyleft=copyleft,
        identified_by=ident.get("identified_by", "unavailable"))

    fields = {k: (doc.get(k) or "") if k in ("module_name", "purpose") else _as_list(doc.get(k))
              for k in SPEC_FIELDS}
    # Measured against the spec's own words only -- not against the provenance block, whose
    # `recipe` path legitimately carries the project name and would otherwise be counted as
    # the model leaking it.
    leak = _leakage(source, json.dumps(fields))
    spec = FunctionalSpec(provenance=prov, leakage=leak, **fields)

    return {
        "ok": True,
        "spec": dataclasses.asdict(spec),
        "backend": be.name, "base": be.base, "model": resp.get("model") or be.model_hint,
        "leakage_note": ("non-zero `leaked` is evidence the no-identifiers instruction did not "
                         "hold; nothing here refuses on that basis"
                         if leak.leaked_count else
                         "no source identifier appeared in the spec on this run"),
        "barrier": ("none -- one model, one process, read the source and wrote this. "
                    "This is a measured reimplementation, not a clean-room one."),
    }


# ---------------------------------------------------------------------------
# turn two -- write fresh code from the specification alone
# ---------------------------------------------------------------------------

ENGINEER_SYSTEM = """You are a software engineer implementing a component from a written
specification. You have not seen any prior implementation of it and none is available to you.

Write idiomatic, native {lang} for {os}. Follow the specification's behaviour exactly,
including its edge cases. Use naming and structure natural to {lang}; do not attempt to
mirror any other implementation's layout. Output the code only -- no commentary, no fences."""


def _prompt_from_spec(spec: dict, target_os: str, target_lang: str) -> str:
    """The user turn, assembled field by field from `SPEC_FIELDS` and nothing else.

    Written as an explicit whitelist so there is no channel: source text cannot reach this
    prompt even if a caller stuffs it into an extra key of the spec dict, because a key not
    named in `SPEC_FIELDS` is never read. `test_cleanroom.py` asserts that by passing a spec
    with the source smuggled into it.
    """
    lines = [f"Target platform: {target_os}", f"Target language: {target_lang}", ""]
    for key in SPEC_FIELDS:
        v = spec.get(key)
        if not v:
            continue
        label = key.replace("_", " ").upper()
        if isinstance(v, str):
            lines.append(f"{label}: {v}")
        else:
            lines.append(f"{label}:")
            lines += [f"  - {x}" for x in _as_list(v)]
        lines.append("")
    return "\n".join(lines).strip()


_COMMENT = {"python": "#", "sh": "#", "bash": "#", "ruby": "#", "perl": "#", "yaml": "#",
            "lua": "--", "sql": "--", "haskell": "--"}


def attribution_block(prov: dict, target_lang: str) -> str:
    """A comment header naming what this was derived from. Generated, never optional.

    A pipeline that turns somebody's Apache-2.0 code into a description and then into fresh
    code has not stopped being derived from it, and this repo already treats a notice as a
    licence condition rather than a courtesy. So the block is produced whenever provenance
    identified anything at all, and it says plainly when identification failed instead of
    emitting a confident-looking header with blanks in it.
    """
    c = _COMMENT.get((target_lang or "").strip().lower(), "//")
    rows = []
    if prov.get("identified_by") == "oematch" and prov.get("project"):
        rows.append(f"Derived from: {prov['project']} ({prov.get('license') or 'licence unknown'})")
        if prov.get("recipe"):
            rows.append(f"OpenEmbedded recipe: {prov['recipe']} in {prov.get('layer') or '?'}")
    else:
        rows.append("Derived from: an unidentified source file "
                    f"({prov.get('identified_by', 'unavailable')})")
    if prov.get("license"):
        rows.append(f"Source licence: {prov['license']} "
                    f"(read from {prov.get('license_source') or 'an unnamed source'})")
    if prov.get("sha256"):
        rows.append(f"Source sha256: {prov['sha256']}")
    rows.append("Written from a behavioural specification, by a model that also read the "
                "source. Not a clean-room reimplementation.")
    if prov.get("copyleft") and not prov.get("license_determined", True):
        # The undetermined case gets its own sentence rather than borrowing the copyleft one.
        # "The source licence is copyleft" would be a claim about a licence nothing read.
        rows.append("The source licence could not be determined -- no SPDX tag, no licence "
                    "header, and oematch identified nothing -- so it is treated as copyleft "
                    "here. Establish the licence before shipping this.")
    elif prov.get("copyleft"):
        rows.append("The source licence is copyleft. Passing through a specification does "
                    "not clear that obligation; this needs a human decision.")
    elif prov.get("attribution_required"):
        rows.append("The source licence requires its notice to be retained. Keep this header.")
    return "\n".join(f"{c} {r}" for r in rows)


@tool("cleanroom")
async def generate_native_code(spec: FunctionalSpec, target_os: str = "linux",
                               target_lang: str = "python",
                               temperature: float = 0.3) -> dict:
    """Write fresh code from a behavioural specification, without reading any source.

    Takes the object `extract_spec` returned. Only the six specification fields reach the
    model; `provenance` is used to build the attribution header and `leakage` is reported
    forward so the figure is not lost between the two halves.

    spec: the FunctionalSpec object from `extract_spec` (its `spec` key).
    target_os: platform the code is for, e.g. linux, Apple, Windows.
    target_lang: language to write, e.g. python, swift, rust, c.
    """
    if dataclasses.is_dataclass(spec) and not isinstance(spec, type):
        spec = dataclasses.asdict(spec)
    if not isinstance(spec, dict):
        return {"ok": False, "error": "bad_spec", "detail": f"expected an object, got {type(spec).__name__}"}
    if not any(spec.get(k) for k in SPEC_FIELDS):
        return {"ok": False, "error": "empty_spec",
                "detail": f"a spec needs at least one of {list(SPEC_FIELDS)}",
                "got": sorted(spec)}

    prov = spec.get("provenance") or {}
    prompt = _prompt_from_spec(spec, target_os, target_lang)

    be = await inference.pick()
    if be is None:
        return {"ok": False, "error": "no_backend",
                "detail": "no OpenAI-compatible engine answered; see /api/studio/state"}
    resp = await be.chat(
        messages=[{"role": "system",
                   "content": ENGINEER_SYSTEM.format(lang=target_lang, os=target_os)},
                  {"role": "user", "content": prompt}],
        temperature=float(temperature), max_tokens=3072)
    try:
        code = (resp["choices"][0]["message"]["content"] or "").strip()
    except (KeyError, IndexError, TypeError):
        return {"ok": False, "error": "bad_response", "detail": json.dumps(resp)[:600]}
    code = re.sub(r"^```[A-Za-z0-9+#-]*\n|\n```$", "", code).strip()

    header = attribution_block(prov, target_lang)
    # How far the leak travelled. The spec's own leaked identifiers are the only ones this
    # side can know about -- the source is not here, by design -- so this is a lower bound on
    # residual leakage and is labelled as one rather than as a total.
    upstream_leaks = list((spec.get("leakage") or {}).get("leaked") or [])
    survived = sorted(w for w in upstream_leaks if re.search(rf"\b{re.escape(w)}\b", code))

    return {
        "ok": True,
        "code": f"{header}\n\n{code}" if header else code,
        "attribution": header,
        "target_os": target_os, "target_lang": target_lang,
        "backend": be.name, "base": be.base, "model": resp.get("model") or be.model_hint,
        "residual_leakage": {
            "carried_in_spec": upstream_leaks,
            "survived_into_code": survived,
            "survived_count": len(survived),
            "bound": "lower -- the source is not available to this half, so only identifiers "
                     "already visible in the spec can be counted",
        },
        "provenance": prov,
    }
