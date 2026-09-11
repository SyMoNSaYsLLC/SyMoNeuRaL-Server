"""The Studio workflow API: load a graph, swap its inputs, run it, watch it work.

This is the ergonomic surface over `comfy.py`. That module speaks the wire
protocol -- HTTP queueing, the WebSocket frame types, the GPU lease -- and every
claim in it was read out of the ComfyUI source rather than documentation. This
one is the part a caller touches::

    studio = Studio()
    wf = studio.workflow("workflow_api.json")
    wf.set_input("10", "image", await studio.upload("input_photo.png"))
    wf.set_input("6", "text", "a high-tech cityscape, cinematic lighting")

    async for event in studio.run(wf):
        match event:
            case Progress() as p:      print(f"{p.fraction:.0%} {p.message}")
            case Preview() as pv:      canvas.show(pv.image)
            case OutputReady() as o:   o.save(f"partial/{o.filename}")
            case StatusChange(status="succeeded"): break

    outputs = await studio.outputs(wf)

Why this and not `comfy-sdk`
----------------------------
`comfy-sdk` on PyPI (0.2.0) offers roughly this shape and would have saved the
file. It is not used, for one reason that is not about taste: **it declares no
licence.** Neither does `comfy-api-proxy` (0.1.6). Unlicensed is not permissive
-- it is all rights reserved by default, and a dependency nobody is allowed to
redistribute is exactly the kind of thing `LICENSES.md` exists to keep out of a
product. ComfyUI itself is GPL-3.0 and is spoken to over a socket, which is an
arm's-length boundary; pulling an unlicensed client *into* this process would
not be.

The transport was already written and already measured, so what was actually
missing was this: typed events instead of `{"type": …, "data": …}` dictionaries,
and `set_input` instead of reaching into the graph dict by hand.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, AsyncIterator

from . import comfy


# --------------------------------------------------------------------------
# Events. One class per thing that can happen, so a caller can `match` on them
# instead of comparing strings and guessing at the payload's shape.
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Event:
    """Base class. `raw` is the untouched frame, so nothing is ever lost here."""

    raw: dict = field(repr=False)


@dataclass(frozen=True)
class Progress(Event):
    """A step finished. ComfyUI reports value/max per node, not per job."""

    value: int = 0
    maximum: int = 0
    node: str | None = None

    @property
    def fraction(self) -> float:
        """0.0-1.0. Zero when max is zero rather than a ZeroDivisionError: a node
        that reports no total is common and is not an error."""
        return (self.value / self.maximum) if self.maximum else 0.0

    @property
    def message(self) -> str:
        return f"node {self.node}" if self.node else "working"


@dataclass(frozen=True)
class Preview(Event):
    """A latent preview: the partial render, mid-job."""

    image: bytes = b""
    image_format: int = 0

    def save(self, path: str | Path) -> Path:
        """Write the preview bytes. No decode: this stays dependency-free, and a
        caller that wants a PIL image already has Pillow."""
        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(self.image)
        return out


@dataclass(frozen=True)
class OutputReady(Event):
    """A node produced a saved file. Carries the URL that fetches it."""

    node: str = ""
    filename: str = ""
    subfolder: str = ""
    kind: str = "images"
    url: str = ""


@dataclass(frozen=True)
class StatusChange(Event):
    """The job moved: queued -> running -> succeeded | failed | interrupted.

    `status` is one of those five words and nothing else, so a `match` on it is
    exhaustive. `detail` carries the server's own words when it failed.
    """

    status: str = "queued"
    detail: str = ""


# ComfyUI frame type -> the status this service reports. Anything not named here
# is not a status change; it is progress, a preview, or an output.
_STATUS = {
    "execution_start": "running",
    "execution_success": "succeeded",
    "execution_error": "failed",
    "execution_interrupted": "interrupted",
    "monitor_timeout": "failed",
    "socket_closed": "failed",
}


def to_event(frame: dict, client: comfy.ComfyClient) -> Event | None:
    """One wire frame -> one typed event, or None for frames with no meaning here.

    Returning None rather than a catch-all event is deliberate: a caller matching
    on these classes should never have to write a default branch for `status`
    queue-depth noise it did not ask for.
    """
    kind = frame.get("type", "")
    data = frame.get("data") or {}

    if kind == "progress":
        return Progress(raw=frame, value=int(data.get("value", 0)),
                        maximum=int(data.get("max", 0)), node=data.get("node"))

    if kind == "preview":
        return Preview(raw=frame, image=data.get("image", b""),
                       image_format=int(data.get("format", 0)))

    if kind == "executed":
        # One frame can carry several saved files; the caller wants one event per
        # file, so the first is returned here and the rest by `_executed_events`.
        events = _executed_events(frame, client)
        return events[0] if events else None

    if kind in _STATUS:
        return StatusChange(raw=frame, status=_STATUS[kind],
                            detail=_failure_detail(kind, data))

    return None


def _failure_detail(kind: str, data: dict) -> str:
    if kind == "execution_error":
        node = data.get("node_id") or data.get("node")
        return f"node {node}: {data.get('exception_message') or 'execution error'}"
    if kind == "monitor_timeout":
        return f"no event for {data.get('after_s')} s"
    if kind == "socket_closed":
        return f"socket closed ({data.get('code')}) {data.get('reason', '')}".strip()
    return ""


def _executed_events(frame: dict, client: comfy.ComfyClient) -> list[OutputReady]:
    """Every saved file in one `executed` frame, as one event each.

    Anything shaped like a saved file is collected, not just `images`: video and
    audio use the same `{filename, subfolder, type}` record under other keys, and
    a caller saving outputs must not silently miss them.
    """
    data = frame.get("data") or {}
    node = str(data.get("node") or data.get("display_node") or "")
    found = []
    for kind, items in (data.get("output") or {}).items():
        if not isinstance(items, list):
            continue
        for item in items:
            if not isinstance(item, dict) or "filename" not in item:
                continue
            found.append(OutputReady(
                raw=frame, node=node, kind=kind,
                filename=item.get("filename", ""),
                subfolder=item.get("subfolder", ""),
                url=client.view_url(item.get("filename", ""),
                                    item.get("subfolder", ""),
                                    item.get("type", "output"))))
    return found


# --------------------------------------------------------------------------
# The workflow itself
# --------------------------------------------------------------------------

class Workflow:
    """An API-format graph, with its inputs addressable by node id and field.

    API format, not the canvas save format: `{"<node id>": {"class_type", "inputs"}}`.
    A canvas export has a `nodes` array instead and will not queue, so it is
    refused at load with the fix named rather than failing later inside the
    server with a message about a missing key.
    """

    def __init__(self, graph: dict, source: Path | None = None) -> None:
        self.graph = graph
        self.source = source
        self.prompt_id: str | None = None
        _refuse_canvas_format(graph, source)

    @classmethod
    def from_file(cls, path: str | Path) -> Workflow:
        p = Path(path)
        return cls(json.loads(p.read_text()), source=p)

    def set_input(self, node_id: str, name: str, value: Any) -> Workflow:
        """Point one node input at a new value. Returns self, so calls chain.

        A node id or field that does not exist raises. The alternative is a run
        that quietly uses the old prompt and produces a plausible wrong image,
        which is the worst outcome available here.
        """
        node = self.graph.get(str(node_id))
        if node is None:
            raise KeyError(f"no node {node_id!r} in "
                           f"{self.source or 'this graph'}; have "
                           f"{', '.join(sorted(self.graph)[:12])}")
        inputs = node.setdefault("inputs", {})
        if name not in inputs:
            raise KeyError(f"node {node_id} ({node.get('class_type', '?')}) has no "
                           f"input {name!r}; have {', '.join(sorted(inputs))}")
        inputs[name] = value
        return self

    def get_input(self, node_id: str, name: str) -> Any:
        return self.graph[str(node_id)]["inputs"][name]

    def nodes_of(self, class_type: str) -> list[str]:
        """Node ids of one class, so a caller can find "the CLIPTextEncode" without
        hardcoding a number that changes whenever the graph is re-saved."""
        return [nid for nid, n in self.graph.items()
                if isinstance(n, dict) and n.get("class_type") == class_type]


def _refuse_canvas_format(graph: dict, source: Path | None) -> None:
    if "nodes" in graph and not any(
            isinstance(v, dict) and "class_type" in v for v in graph.values()):
        raise ValueError(
            f"{source or 'this graph'} is a canvas save, not API format. "
            "In ComfyUI: enable Settings -> Dev mode, then "
            "'Save (API Format)'. The canvas format will not queue.")


# --------------------------------------------------------------------------
# The client
# --------------------------------------------------------------------------

class Studio:
    """Run workflows against the local engine, under the GPU lease.

    The lease is not optional and is not the caller's job to remember. Studio
    shares one card with chat, image, sigils and training, and a run that queued
    without holding the lease is how two surfaces end up allocating the same VRAM
    at once. `run()` takes it for the length of the job and gives it back.
    """

    def __init__(self, url: str | None = None) -> None:
        self.client = comfy.ComfyClient(url)

    @property
    def url(self) -> str:
        return self.client.url

    async def alive(self) -> dict:
        """Is the engine answering. Never raises; absence is a reading, not a fault."""
        return await self.client.alive()

    def workflow(self, path: str | Path) -> Workflow:
        return Workflow.from_file(path)

    async def run(self, wf: Workflow, *, lease: bool = True,
                  idle_timeout: float = 900) -> AsyncIterator[Event]:
        """Queue `wf` and yield typed events until it ends.

        The socket is opened *before* queueing. ComfyUI routes frames to the
        client id that queued the prompt, and a job that finishes between the
        POST and the connect would otherwise be watched in silence forever --
        the reason `comfy.py` says so in its module docstring.

        The final event is always a StatusChange with a terminal status, even
        when the socket dies: a caller looping until terminal must terminate.
        """
        if lease:
            async with comfy.lease("studio"):
                async for event in self._run(wf, idle_timeout):
                    yield event
            return
        async for event in self._run(wf, idle_timeout):
            yield event

    async def _run(self, wf: Workflow, idle_timeout: float) -> AsyncIterator[Event]:
        async for ws in self.client.socket():
            reply = await self.client.queue(wf.graph)
            if not reply.get("ok"):
                # A refused graph names the node and input that is wrong. That is
                # the single most useful thing to hand back, so it is carried
                # verbatim into the failure rather than summarised away.
                yield StatusChange(raw=reply, status="failed",
                                   detail=_queue_refusal(reply))
                return

            wf.prompt_id = reply.get("prompt_id")
            yield StatusChange(raw=reply, status="queued")

            terminal = False
            async for frame in self.client.watch(ws, wf.prompt_id,
                                                 idle_timeout=idle_timeout):
                # `executed` carries several files; every one gets its own event.
                if frame.get("type") == "executed":
                    for event in _executed_events(frame, self.client):
                        yield event
                    continue
                event = to_event(frame, self.client)
                if event is None:
                    continue
                if isinstance(event, StatusChange) and event.status != "running":
                    terminal = True
                yield event
            if not terminal:
                # The watcher returned without a terminal frame. Say so, rather
                # than letting a caller's `until terminal` loop hang on nothing.
                yield StatusChange(raw={}, status="failed",
                                   detail="the event stream ended with no result")
            return

    async def outputs(self, wf: Workflow) -> list[dict]:
        """Every file the run produced, from history. Empty before a run."""
        if wf.prompt_id is None:
            return []
        return await self.client.outputs(wf.prompt_id)

    async def interrupt(self) -> bool:
        return await self.client.interrupt()

    async def free(self) -> bool:
        """Give the card back: unload models and free VRAM. The lease does this
        on release, so this is for a caller holding the engine open deliberately."""
        return await self.client.free()


def _queue_refusal(reply: dict) -> str:
    """The server's own words for why a graph will not run."""
    errors = reply.get("node_errors") or {}
    if errors:
        parts = []
        for node_id, err in errors.items():
            detail = err.get("errors") if isinstance(err, dict) else None
            first = (detail or [{}])[0] if isinstance(detail, list) else {}
            parts.append(f"node {node_id}: {first.get('message') or err}")
        return "; ".join(parts)
    return str(reply.get("error") or "the engine refused the graph")
