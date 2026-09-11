"""Drag-and-drop nodes for the spec-mediated reimplementation pipeline.

## Why this is a ComfyUI pack and not a canvas of our own

`graph.py` records that Studio's hand-written canvas was deleted in favour of embedding
ComfyUI's own editor. So the drag-and-drop surface in SyMoNeuRaL Studio *is* the ComfyUI
editor, reached through the framed `/studio/editor/` mount, and a node pack is the only way to
put a new box in it. `custom_nodes/symoneural_gguf` is the precedent and this follows its
shape, including being relinked by `scripts/symoneural-ui.sh` on every start because the
ComfyUI clone is gitignored in full.

## The connection wire

ComfyUI validates an edge by **string equality of the two socket type names**. So the literal
`"FUNCTIONAL_SPEC"` is not documentation, it is the constraint: it is what makes the spec
output of the first node droppable into the second node's spec input, and what makes a plain
`STRING` refuse to go there. That literal is imported from `tools_impl/cleanroom.py` when the
package is reachable, so the node pack and the tool cannot drift to two different spellings --
and there is a fallback constant for the case where it is not, because the pack runs inside
ComfyUI's venv and must not die on an import.

## Why the nodes call HTTP instead of importing the tool

The tool functions live in the API process, on the **system** interpreter, and ComfyUI runs in
its own venv with its own torch. Importing `studio.tools_impl.cleanroom` from here would
mean either a `sys.path` graft into a foreign interpreter or a second copy of the logic, and
the second copy is the one that rots. `POST /api/studio/tool/{name}` already exists as an
operator surface -- "run one tool directly, bypassing the model" -- so these nodes are a fourth
client of the same code that the agent loop, the MCP server and `curl` all reach. `urllib` from
the stdlib, so the pack adds nothing to ComfyUI's dependency set.

The consequence to know: **the API must be up and Studio switched on** for these nodes to do
anything. There is no third condition -- the token requirement that used to stand here was
removed on 2026-09-11 (NO API KEYS, owner decision). Both remaining failures raise with the
reason on the node rather than returning an empty string, because a node that outputs "" on a
refusal produces a graph that looks like it ran.

## No GPU lease is taken here

The tools ride `inference.pick()`, which probes llama-server and never spawns it -- `api.py`
owns that process inside `gpu.hold("chat")`. So a spec node in a graph beside a render node
does not deadlock; it contends, and waits for the card like any other tenant.
"""
import json
import os
import urllib.error
import urllib.request

try:  # inside ComfyUI's venv the repo may not be importable; that is not a fatal condition
    from studio.tools_impl.cleanroom import SOCKET as _SOCKET
except Exception:  # pragma: no cover - exercised only under ComfyUI
    _SOCKET = "FUNCTIONAL_SPEC"

SOCKET = _SOCKET

DEFAULT_BASE = "http://127.0.0.1:8800"

LANGUAGES = ["python", "swift", "rust", "c", "cpp", "go", "java", "kotlin",
             "javascript", "typescript", "lua", "sh"]
PLATFORMS = ["linux", "Apple", "Windows", "Android", "FreeBSD", "embedded"]


def _base() -> str:
    return (os.environ.get("SYMONEURAL_API_BASE") or DEFAULT_BASE).rstrip("/")


def call_tool(name: str, arguments: dict, timeout: float = 900.0) -> dict:
    """One tool call over the operator route. Raises with the reason; never returns a blank.

    Timeout is generous on purpose: the first call after a cold start waits on llama-server
    loading weights, which is seconds not milliseconds, and a node that gave up at 30 s would
    look like a broken pipeline every morning.
    """
    # NO API KEYS, owner decision 2026-09-11. This node used to refuse to run unless
    # SYMONEURAL_STUDIO_TOKEN was exported into ComfyUI's environment -- which meant the node
    # failed for a reason that had nothing to do with the tool call. `/api/studio/tool` takes
    # no token now, so this is a plain POST with a plain Content-Type and nothing else.
    req = urllib.request.Request(
        f"{_base()}/api/studio/tool/{name}",
        data=json.dumps(arguments).encode(),
        headers={"Content-Type": "application/json"},
        method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = json.loads(r.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:600]
        raise RuntimeError(f"{_base()} answered {exc.code} for {name}: {detail}") from None
    except urllib.error.URLError as exc:
        raise RuntimeError(
            f"no API at {_base()} ({exc.reason}). These nodes drive the running "
            f"SyMoNeuRaL API; start it before queueing the graph.") from None
    if not body.get("ok"):
        raise RuntimeError(f"{name} failed: {json.dumps(body)[:600]}")
    result = body.get("result") or {}
    if isinstance(result, dict) and result.get("ok") is False:
        raise RuntimeError(f"{name}: {result.get('error')} -- {result.get('detail', '')}")
    return result


def _leak_report(leak: dict) -> str:
    """The figure, in words, for the canvas.

    Written as a sentence rather than a badge because this repo has a rule against decorative
    indicators: a green light saying "clean" would be the one dishonest pixel in the graph,
    and what is actually known is a count and the method that produced it.
    """
    n = leak.get("leaked_count", 0)
    if n == 0:
        return ("no source identifier appeared in the spec on this run "
                f"({leak.get('source_identifiers', 0)} distinct identifiers in the source, "
                f"{leak.get('leaked_raw_count', 0)} before the stoplist)")
    return (f"{n} source identifier(s) appeared in the spec: "
            f"{', '.join(leak.get('leaked') or [])} -- the no-identifiers instruction did not "
            f"hold. Ratio {leak.get('ratio')} of {leak.get('source_identifiers', 0)}.")


class SymoneuralExtractSpec:
    """Read a source file, emit a behavioural spec on the FUNCTIONAL_SPEC socket."""

    RETURN_TYPES = (SOCKET, "STRING", "STRING")
    RETURN_NAMES = ("spec", "leakage", "provenance")
    FUNCTION = "run"
    CATEGORY = "symoneural/cleanroom"
    DESCRIPTION = ("Describes what a source file does. One model reads the source and writes "
                   "this description, so there is no clean-room barrier -- the `leakage` "
                   "output is the measurement of how much of the original came through.")

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "source_path": ("STRING", {"default": "", "multiline": False,
                                       "tooltip": "file to read; relative to the repo root"}),
            "max_bytes": ("INT", {"default": 60000, "min": 1024, "max": 400000, "step": 1024}),
            "temperature": ("FLOAT", {"default": 0.2, "min": 0.0, "max": 2.0, "step": 0.05}),
        }}

    def run(self, source_path, max_bytes, temperature):
        res = call_tool("extract_spec", {"source_path": source_path,
                                         "max_bytes": int(max_bytes),
                                         "temperature": float(temperature)})
        spec = res.get("spec") or {}
        prov = spec.get("provenance") or {}
        # Project and licence are identified by different means and are reported separately:
        # oematch names the project and cannot read a single file, the file header names the
        # licence and knows nothing about the project.
        who = (f"project: {prov.get('project') or 'unidentified'} "
               f"(via {prov.get('identified_by', 'unavailable')}) | "
               f"licence: {prov.get('license') or 'undetermined'} "
               f"(via {prov.get('license_source') or 'nothing'})")
        if prov.get("copyleft") and not prov.get("license_determined", True):
            who += " -- licence undetermined, treated as copyleft until established"
        elif prov.get("copyleft"):
            who += " -- copyleft; a spec does not clear that obligation"
        return (spec, _leak_report(spec.get("leakage") or {}), who)


class SymoneuralGenerateNativeCode:
    """Write fresh code from a FUNCTIONAL_SPEC, without reading any source."""

    RETURN_TYPES = ("STRING", "STRING", "STRING")
    RETURN_NAMES = ("code", "attribution", "residual_leakage")
    FUNCTION = "run"
    CATEGORY = "symoneural/cleanroom"
    DESCRIPTION = ("Implements the spec in a target language. Only the six specification "
                   "fields are sent; the attribution header is generated from the spec's "
                   "provenance and is prepended to the code rather than offered as an option.")

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {
            "spec": (SOCKET,),
            "target_os": (PLATFORMS, {"default": "linux"}),
            "target_lang": (LANGUAGES, {"default": "python"}),
            "temperature": ("FLOAT", {"default": 0.3, "min": 0.0, "max": 2.0, "step": 0.05}),
        }}

    def run(self, spec, target_os, target_lang, temperature):
        res = call_tool("generate_native_code", {"spec": spec, "target_os": target_os,
                                                 "target_lang": target_lang,
                                                 "temperature": float(temperature)})
        rl = res.get("residual_leakage") or {}
        survived = rl.get("survived_into_code") or []
        note = (f"{len(survived)} spec-leaked identifier(s) survived into the code: "
                f"{', '.join(survived)}" if survived else
                "no identifier carried in the spec survived into the code")
        return (res.get("code") or "", res.get("attribution") or "",
                f"{note} (lower bound: {rl.get('bound', '')})")


class SymoneuralSpecReport:
    """Terminal node: put the spec, its leakage figure and the generated code on screen.

    An OUTPUT_NODE exists here because otherwise the honest number is a string on a wire that
    nobody has to look at. This makes reading it the default.

    It takes the code and attribution as **optional** inputs, and that is what makes the
    pipeline runnable rather than a convenience. ComfyUI executes backwards from output nodes
    only: `SymoneuralGenerateNativeCode` returns plain strings and is not an output node, so a
    graph of extract -> generate and nothing else has no output to pull on and ComfyUI runs
    *neither* node -- Queue returns immediately and the canvas looks broken with nothing to
    read. Found by queueing exactly that graph. Wiring the code back into this node gives the
    whole chain one terminus, and leaving the inputs optional keeps the spec-only graph valid.
    """

    RETURN_TYPES = ()
    FUNCTION = "run"
    OUTPUT_NODE = True
    CATEGORY = "symoneural/cleanroom"

    @classmethod
    def INPUT_TYPES(cls):
        return {"required": {"spec": (SOCKET,)},
                "optional": {"code": ("STRING", {"forceInput": True}),
                             "attribution": ("STRING", {"forceInput": True}),
                             "residual_leakage": ("STRING", {"forceInput": True})}}

    def run(self, spec, code=None, attribution=None, residual_leakage=None):
        spec = spec or {}
        prov = spec.get("provenance") or {}
        lines = [
            f"module: {spec.get('module_name', '?')}",
            f"purpose: {spec.get('purpose', '')}",
            f"steps: {len(spec.get('logic_steps') or [])}, "
            f"edge cases: {len(spec.get('edge_cases') or [])}",
            f"source: {prov.get('project') or 'unidentified'} "
            f"[{prov.get('license') or 'licence unknown'}] "
            f"sha256 {(prov.get('sha256') or '')[:12]}",
            f"leakage: {_leak_report(spec.get('leakage') or {})}",
            "barrier: none -- one model read the source and wrote this spec.",
        ]
        if residual_leakage:
            lines.append(f"residual: {residual_leakage}")
        if attribution:
            lines.append("attribution header:\n" + attribution)
        if code:
            lines.append(f"code: {len(code.splitlines())} lines generated")
        return {"ui": {"text": ["\n".join(lines)]}}


NODE_CLASS_MAPPINGS = {
    "SymoneuralExtractSpec": SymoneuralExtractSpec,
    "SymoneuralGenerateNativeCode": SymoneuralGenerateNativeCode,
    "SymoneuralSpecReport": SymoneuralSpecReport,
}

NODE_DISPLAY_NAME_MAPPINGS = {
    "SymoneuralExtractSpec": "Extract Functional Spec (reads source)",
    "SymoneuralGenerateNativeCode": "Generate Native Code (spec only)",
    "SymoneuralSpecReport": "Spec + Leakage Report",
}

__all__ = ["NODE_CLASS_MAPPINGS", "NODE_DISPLAY_NAME_MAPPINGS", "SOCKET", "call_tool"]
