"""The ComfyUI trigger tool -- the one the brief asks to be exposed through FastMCP.

> *"Expose a specific Python function via FastMCP that acts as a dedicated ComfyUI image
> generation trigger."*

That is `generate_image` below. It is an ordinary async Python function with type hints and a
docstring, which is the whole point: `registry.py` introspects it into a JSON Schema for the
LLM, and `mcp_server.py` hands the same function object to `@mcp.tool()`. Neither of those
files knows anything about ComfyUI.

## What one call actually does

    validate the graph          <- before the lock, so a typo never costs a queue wait
    acquire the GPU lease       <- scripts/gpu-governor.sh acquire comfy
      open the WebSocket        <- before queueing; see comfy.py on why the order matters
      POST /prompt              <- capture prompt_id
      watch to a terminal event <- collecting per-node progress
      GET /history/{prompt_id}  <- the outputs
    POST /free + drain + release  <- comfy.lease()'s finally, always

Every step reports what happened. A call that queued but timed out comes back with its
`prompt_id` and the events it did see, because "the job is still running and here is its id"
is a useful answer and "failed" is not.

## Where the images end up

ComfyUI writes into `ComfyUI/output/<subfolder>/`. Each returned image therefore carries
three ways to reach it, and they are for different consumers:

| Field | For | Note |
|---|---|---|
| `path` | the agent, and anything downstream on this box | absolute, existence-checked |
| `url` | nothing in a browser | port 8188, loopback-only, will not resolve for a visitor |
| `proxy_url` | the canvas | `/api/studio/image?...`, served by FastAPI, the only public one |

`url` is included anyway because when a render does not appear the first question is whether
ComfyUI itself will serve it, and that is the URL to try.
"""
from __future__ import annotations

import os
import secrets
import time
from typing import Any

from .. import comfy, graph as graphlib, workflows, workspace
from ..registry import tool

__all__ = ["generate_image", "run_workflow", "comfy_status", "list_comfy_nodes",
           "list_workflows", "execute"]

# ComfyUI's own default. `--output-directory` would move it, and `scripts/symoneural-ui.sh` does not
# pass that flag, so this is where files land on this box.
_OUTPUT_DIRNAME = "output"


def _disk_path(filename: str, subfolder: str = "", type_: str = "output") -> str | None:
    """Absolute path of a produced file, or None if it is not where we expect.

    Returning None rather than a guessed path matters: the agent may hand this to a downstream
    tool, and a path that does not exist produces a confusing failure two steps later instead
    of an honest "not found" here.
    """
    root = workspace.COMFYUI
    if root is None:
        return None
    base = {"output": _OUTPUT_DIRNAME, "input": "input", "temp": "temp"}.get(type_,
                                                                            _OUTPUT_DIRNAME)
    p = root / base / (subfolder or "") / filename
    return str(p) if p.is_file() else None


def _decorate(images: list[dict]) -> list[dict]:
    """Add the disk path and the FastAPI proxy URL to each output record."""
    out = []
    for im in images:
        rec = dict(im)
        rec["path"] = _disk_path(im.get("filename", ""), im.get("subfolder", ""),
                                 im.get("type", "output"))
        rec["proxy_url"] = ("/api/studio/image"
                            f"?filename={im.get('filename', '')}"
                            f"&subfolder={im.get('subfolder', '')}"
                            f"&type={im.get('type', 'output')}")
        out.append(rec)
    return out


async def execute(prompt_graph: dict, *, timeout_s: int = 900,
                  on_event: Any = None) -> dict:
    """Run one compiled graph end to end under the GPU lease. Shared by every tool here.

    Not registered as a tool itself -- `run_workflow` is the registered wrapper. `routes.py`
    calls this directly too, at `POST /api/studio/queue`, and **without** `on_event`: nothing in
    the repo passes one, so every caller today gets the summary and no live progress. The hook is
    the two lines under `client.watch` below and the frames go past it either way; a streaming
    `/queue` would use it. Until something does, treat the parameter as unexercised.
    """
    started = time.monotonic()
    client = comfy.ComfyClient()

    up = await client.alive()
    if not up.get("up"):
        return {"ok": False, "error": "comfyui_down", "url": client.url, "detail": (
            "ComfyUI is not answering. Start it with `scripts/symoneural-ui.sh start` (it runs "
            "under symoneural-ui/.venv on 127.0.0.1:8188). It is not a system service and is not "
            "expected to be up between jobs."), "probe": up}

    try:
        catalogue = await client.object_info()
    except Exception as e:                      # noqa: BLE001 -- any transport failure here
        catalogue = None                        # is a reason to validate structurally, not
        catalogue_error = f"{type(e).__name__}: {e}"   # to abandon the run
    else:
        catalogue_error = None

    check = graphlib.validate(prompt_graph, catalogue)
    if catalogue_error:
        check["catalogue_error"] = catalogue_error
    if not check["ok"]:
        # Deliberately before `lease()`. Taking a 15.9 GiB card away from chat to discover the
        # graph was never runnable is the exact waste the governor exists to avoid.
        return {"ok": False, "error": "invalid_graph", "validation": check}

    result: dict = {"ok": False, "prompt_id": None, "validation": check}

    async def _job() -> None:
        """The part that holds the card. Written as a nested function so that every early
        exit is a `return` out of *this*, not out of `execute` -- an early `return` inside
        the `async with lease(...)` block below would skip attaching the lease record, and
        the lease record is where "did the GPU actually come back" is reported."""
        async with client.socket() as ws:
            queued = await client.queue(prompt_graph)
            if not queued.get("ok"):
                result["error"] = "rejected_by_comfyui"
                # node_errors verbatim: it names the node id and the input, which is the
                # single most actionable thing available at this point.
                result["node_errors"] = queued.get("node_errors")
                result["detail"] = queued.get("error")
                result["http_status"] = queued.get("http_status")
                return

            prompt_id = queued.get("prompt_id")
            result["prompt_id"] = prompt_id
            result["queue_number"] = queued.get("number")

            progress: dict[str, dict] = {}
            cached: list[str] = []
            terminal: str | None = None
            error: dict | None = None

            async for ev in client.watch(ws, prompt_id, idle_timeout=timeout_s):
                if on_event is not None:
                    await on_event(ev)
                etype, data = ev.get("type"), (ev.get("data") or {})
                if etype == "progress":
                    node = str(data.get("node"))
                    progress[node] = {"value": data.get("value"), "max": data.get("max")}
                elif etype == "execution_cached":
                    cached = [str(n) for n in (data.get("nodes") or [])]
                elif etype == "execution_error":
                    error = data
                    terminal = etype
                elif etype in ("execution_success", "execution_interrupted",
                               "monitor_timeout"):
                    terminal = etype

            result["terminal"] = terminal
            result["cached_nodes"] = cached
            result["progress"] = progress

        if terminal == "monitor_timeout":
            result["error"] = "timed_out"
            result["detail"] = (f"no terminal event within {timeout_s}s. The job may still be "
                                f"running; check /history/{prompt_id} or the ComfyUI console.")
            return
        if error is not None:
            result["error"] = "execution_error"
            # ComfyUI's payload carries node_id, node_type, exception_message and a traceback.
            result["node_id"] = error.get("node_id")
            result["node_type"] = error.get("node_type")
            result["detail"] = error.get("exception_message")
            result["traceback"] = error.get("traceback")
            return

        try:
            result["images"] = _decorate(await client.outputs(prompt_id))
        except Exception as e:                  # noqa: BLE001
            result["images"] = []
            result["history_error"] = f"{type(e).__name__}: {e}"

        result["ok"] = terminal == "execution_success"
        if terminal == "execution_interrupted":
            result["error"] = "interrupted"

    async with comfy.lease("comfy") as record:
        await _job()

    # `record` is only fully populated once the lease's `finally` has run -- that is where
    # POST /free, the VRAM drain poll and the release happen -- so it is read after the block,
    # not inside it.
    result["lease"] = record
    result["elapsed_s"] = round(time.monotonic() - started, 1)
    if not record.get("released"):
        result["warning"] = ("the GPU lock may still be held: "
                             + str(record.get("release_error") or "release did not report ok"))
    return result


@tool("comfyui")
async def generate_image(prompt: str, negative: str = "", width: int = 1024,
                         height: int = 1024, steps: int = 4, seed: int | None = None,
                         guidance: float = 3.5, batch_size: int = 1,
                         workflow: str | None = None, timeout_s: int = 900) -> dict:
    """Render an image locally with ComfyUI and return where it was saved.

    Takes the GPU for the duration of the render and gives it back afterwards, so chat and
    training are blocked only while it runs, not while ComfyUI is up.

    Args:
        prompt: What to draw. FLUX responds to full descriptive sentences, not tag lists.
        negative: Ignored by the default FLUX-schnell workflow, which runs at cfg 1.0 and so
            has no unconditional branch to steer away from. Present because other workflows
            use it.
        width: Pixels. Use multiples of 16.
        height: Pixels. Use multiples of 16.
        steps: Sampling steps. The default workflow is a 4-step distilled model; more steps
            cost time and change almost nothing.
        seed: Reproducibility. Omit for a fresh random seed, which is reported in the result.
        guidance: FLUX's embedded guidance value. Around 3.5 is neutral; higher follows the
            prompt harder and looks more synthetic.
        batch_size: How many images in one run. Each one costs VRAM.
        workflow: Name of a stored workflow. Omit for the default. `list_workflows` has the
            names.
        timeout_s: Give up waiting after this many seconds. The job keeps running in ComfyUI.

    Returns:
        {ok, prompt_id, images: [{filename, path, proxy_url, url}], seed, lease, elapsed_s}
        or {ok: false, error, detail} naming what went wrong.
    """
    name = workflow or workflows.DEFAULT
    try:
        base = workflows.get(name)
    except KeyError as e:
        return {"ok": False, "error": "unknown_workflow", "detail": str(e),
                "available": workflows.names()}

    if seed is None:
        # 64-bit, matching ComfyUI's own seed range. `secrets` rather than `random` only
        # because it needs no seeding of its own to be different every call.
        seed = secrets.randbelow(2 ** 64)

    params = {
        workflows.PARAMETER_MAP["prompt"]: prompt,
        workflows.PARAMETER_MAP["negative"]: negative,
        workflows.PARAMETER_MAP["width"]: int(width),
        workflows.PARAMETER_MAP["height"]: int(height),
        workflows.PARAMETER_MAP["batch_size"]: int(batch_size),
        workflows.PARAMETER_MAP["steps"]: int(steps),
        workflows.PARAMETER_MAP["seed"]: int(seed),
        workflows.PARAMETER_MAP["guidance"]: float(guidance),
    }
    injected = graphlib.inject(base, params)

    out = await execute(injected["graph"], timeout_s=timeout_s)
    out["workflow"] = name
    out["seed"] = seed
    out["injected"] = injected["applied"]
    if injected["unapplied"]:
        # Only possible if a stored workflow's ids and PARAMETER_MAP have drifted apart. Say
        # so rather than silently rendering with the stored defaults, which would look like
        # the model ignoring the prompt.
        out["unapplied"] = injected["unapplied"]
    return out


@tool("comfyui")
async def run_workflow(canvas: dict, params: dict | None = None,
                       timeout_s: int = 900) -> dict:
    """Run a workflow built on the Studio canvas, optionally overriding node inputs.

    This is the path the canvas itself uses. The document is compiled to ComfyUI's prompt
    format, validated against the installed node set, then run under the same GPU lease as
    `generate_image`.

    Args:
        canvas: A canvas document: {"nodes": [{id, class_type, widgets}], "links": [...]}.
            A raw ComfyUI prompt graph ({"3": {"class_type", "inputs"}}) is also accepted.
        params: Node inputs to set before running, addressed "node_id.input_name", or
            "*.seed" to set every node that has that input.
        timeout_s: Give up waiting after this many seconds.

    Returns:
        The same shape as `generate_image`, without the seed and workflow fields.
    """
    if not isinstance(canvas, dict):
        return {"ok": False, "error": "bad_document",
                "detail": f"expected an object, got {type(canvas).__name__}"}

    # Both shapes are accepted because the agent will sometimes have a ComfyUI graph in hand
    # (from an example, or from its own earlier output) and requiring it to convert first
    # would be a tool call spent on bookkeeping.
    if "nodes" in canvas:
        try:
            prompt_graph = graphlib.to_prompt(canvas)
        except graphlib.GraphError as e:
            return {"ok": False, "error": "bad_document", "detail": str(e)}
    else:
        prompt_graph = canvas

    applied = []
    if params:
        injected = graphlib.inject(prompt_graph, params)
        prompt_graph, applied = injected["graph"], injected["applied"]

    out = await execute(prompt_graph, timeout_s=timeout_s)
    if applied:
        out["injected"] = applied
    return out


@tool("comfyui")
async def comfy_status() -> dict:
    """Whether ComfyUI is running, and what it reports about this machine.

    Returns:
        {up, url, system: {devices, vram_total, python_version, ...}} or {up: false, detail}.
    """
    client = comfy.ComfyClient()
    probe = await client.alive()
    probe["output_dir"] = str(workspace.COMFYUI / _OUTPUT_DIRNAME) if workspace.COMFYUI else None
    probe["workflows"] = workflows.names()
    if not probe.get("up"):
        probe["how_to_start"] = "scripts/symoneural-ui.sh start"
    return probe


@tool("comfyui")
async def list_comfy_nodes(search: str = "", limit: int = 40) -> dict:
    """List the node classes installed in this ComfyUI, with their inputs and outputs.

    Reads the live catalogue, so custom node packs such as ComfyUI-GGUF are included. Use it
    before building a graph rather than assuming a class exists.

    Args:
        search: Case-insensitive substring, matched against the class name, its display name
            and its category. Empty lists everything up to the limit.
        limit: Maximum classes to return.

    Returns:
        {count, total, nodes: [{class_type, display_name, category, required, optional,
        outputs, output_node}]}.
    """
    client = comfy.ComfyClient()
    try:
        catalogue = await client.object_info()
    except Exception as e:                      # noqa: BLE001
        return {"error": "comfyui_down", "detail": f"{type(e).__name__}: {e}",
                "how_to_start": "scripts/symoneural-ui.sh start"}

    needle = (search or "").lower()
    rows = []
    for cls, spec in sorted(catalogue.items()):
        if needle and needle not in " ".join(
                str(x).lower() for x in (cls, spec.get("display_name", ""),
                                         spec.get("category", ""))):
            continue
        inputs = spec.get("input") or {}
        rows.append({
            "class_type": cls,
            "display_name": spec.get("display_name"),
            "category": spec.get("category"),
            "required": list((inputs.get("required") or {}).keys()),
            "optional": list((inputs.get("optional") or {}).keys()),
            "outputs": list(spec.get("output") or []),
            "output_node": bool(spec.get("output_node")),
        })

    return {"count": len(rows[:limit]), "total": len(rows), "nodes": rows[:limit],
            "truncated": len(rows) > limit}


@tool("comfyui")
def list_workflows() -> dict:
    """The stored workflows `generate_image` can run, and what each one expects.

    Returns:
        {default, workflows: [{name, node_count, classes, parameters, weights, notes}]}.
    """
    return {"default": workflows.DEFAULT,
            "workflows": [workflows.describe(n) for n in workflows.names()],
            "output_dir": (str(workspace.COMFYUI / _OUTPUT_DIRNAME)
                           if workspace.COMFYUI else None)}


@tool("comfyui")
def read_image_file(path: str) -> dict:
    """Confirm a produced image exists on disk and report its size.

    The bytes are not returned -- an image in the LLM's context window is not useful to a
    text model and would blow the budget. This is for verifying a render landed before piping
    its path into another tool.

    Args:
        path: Absolute path, usually the `path` field from a `generate_image` result.

    Returns:
        {exists, path, bytes, modified} or {exists: false, path}.
    """
    if not os.path.isfile(path):
        return {"exists": False, "path": path}
    st = os.stat(path)
    return {"exists": True, "path": path, "bytes": st.st_size,
            "modified": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(st.st_mtime))}
