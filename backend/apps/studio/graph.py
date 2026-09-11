"""Canvas document -> ComfyUI prompt graph, and the validation that happens on the way.

## Who calls this, now that there is no hand-written canvas

The canvas this module was written for was deleted in favour of embedding ComfyUI's own editor
(`tools/build_studio.py` records why), and that editor speaks ComfyUI's format directly through
the proxy -- it never touches this file. What is left has three live callers, and no page among
them: `POST /api/studio/queue` converts a `canvas` field with `to_prompt`, `GET
/api/studio/workflow/{name}` returns `from_prompt` of a stored graph, and
`tools_impl/comfy_tool.execute` runs `validate` before it takes the GPU lock. `inject` is on
every render path. So the document format below is this API's, offered to a client that would
rather send nodes and links than ComfyUI's inputs-with-lists -- it is not what any shipped page
stores.

## The two formats

What a canvas document looks like (ours, and it may change; nothing in `site/` produces one):

    {"nodes": [{"id": "3", "class_type": "KSampler", "pos": {"x": 320, "y": 80},
                "widgets": {"seed": 0, "steps": 4, "cfg": 1.0}}],
     "links": [{"from_node": "1", "from_slot": 0, "to_node": "3", "to_input": "model"}]}

What ComfyUI's `POST /prompt` wants (theirs; read from
`ComfyUI/script_examples/websockets_api_example.py` and `ComfyUI/execution.py`):

    {"3": {"class_type": "KSampler",
           "inputs": {"seed": 0, "steps": 4, "model": ["1", 0], "positive": ["2", 0]}}}

The whole difference is that ComfyUI has no separate notion of a link: a connection *is* an
input whose value is the two-element list `[source_node_id, source_output_slot]`. Widget
values and wired inputs live in the same `inputs` dict and are told apart by type. That is why
this module exists rather than the frontend posting straight through -- a canvas that stored
links inline would be painful to edit, and a graph that stored them separately would be
rejected by the server.

## Validation

`validate()` checks against a live `GET /object_info`, so the rules come from the installed
node set -- including custom nodes such as `ComfyUI-GGUF`, whose loaders will not appear in
any hard-coded table. It reports every problem it finds rather than the first, because a user
who has wired six nodes wrong wants six messages, not six round trips.

It deliberately does **not** try to be a second copy of ComfyUI's own validator. ComfyUI
validates on `POST /prompt` and returns `node_errors` naming the node and input; that is
authoritative and it is surfaced verbatim. This pass exists to catch the cheap, common
mistakes before a job is queued and before the GPU lock is taken -- a missing required input,
a class that is not installed, a link to a node that does not exist, a cycle.
"""
from __future__ import annotations

import copy
from typing import Any

__all__ = ["to_prompt", "validate", "inject", "cycles", "GraphError"]


class GraphError(ValueError):
    """A canvas document that cannot be turned into a graph at all."""


def to_prompt(doc: dict) -> dict:
    """Compile a canvas document into a ComfyUI prompt graph.

    Node ids are stringified because ComfyUI keys its graph by string and a JSON round-trip
    through a browser will happily hand us integers. A link whose target input collides with a
    widget of the same name wins -- a wire is a stronger statement of intent than a leftover
    widget value, and this is the case that produces "expected MODEL, got INT" from the server
    when it is got wrong.
    """
    if not isinstance(doc, dict):
        raise GraphError(f"canvas document must be an object, got {type(doc).__name__}")
    nodes = doc.get("nodes")
    if not isinstance(nodes, list):
        raise GraphError("canvas document has no 'nodes' array")

    prompt: dict[str, dict] = {}
    for n in nodes:
        if not isinstance(n, dict):
            raise GraphError(f"node entry is not an object: {n!r}")
        nid = n.get("id")
        cls = n.get("class_type")
        if nid is None or not cls:
            raise GraphError(f"node missing id or class_type: {n!r}")
        widgets = n.get("widgets") or {}
        if not isinstance(widgets, dict):
            raise GraphError(f"node {nid} has non-object widgets")
        prompt[str(nid)] = {"class_type": str(cls), "inputs": dict(widgets)}

    for link in (doc.get("links") or []):
        if not isinstance(link, dict):
            raise GraphError(f"link entry is not an object: {link!r}")
        src, dst = str(link.get("from_node")), str(link.get("to_node"))
        name = link.get("to_input")
        if dst not in prompt:
            raise GraphError(f"link targets unknown node {dst!r}")
        if src not in prompt:
            raise GraphError(f"link comes from unknown node {src!r}")
        if not name:
            raise GraphError(f"link into node {dst} names no input")
        try:
            slot = int(link.get("from_slot", 0))
        except (TypeError, ValueError):
            raise GraphError(f"link from {src} has a non-integer slot "
                             f"{link.get('from_slot')!r}") from None
        prompt[dst]["inputs"][str(name)] = [src, slot]

    return prompt


def cycles(prompt: dict) -> list[list[str]]:
    """Every cycle in the graph. ComfyUI hangs or errors obscurely on one, and the canvas can
    produce one with a single mis-dropped wire, so it is worth naming precisely."""
    edges: dict[str, set[str]] = {nid: set() for nid in prompt}
    for nid, node in prompt.items():
        for value in (node.get("inputs") or {}).values():
            if isinstance(value, list) and len(value) == 2 and str(value[0]) in edges:
                edges[nid].add(str(value[0]))

    found: list[list[str]] = []
    WHITE, GREY, BLACK = 0, 1, 2
    colour = dict.fromkeys(edges, WHITE)

    def walk(node: str, path: list[str]) -> None:
        colour[node] = GREY
        path.append(node)
        for nxt in sorted(edges[node]):
            if colour[nxt] == GREY:
                found.append(path[path.index(nxt):] + [nxt])
            elif colour[nxt] == WHITE:
                walk(nxt, path)
        path.pop()
        colour[node] = BLACK

    for nid in sorted(edges):
        if colour[nid] == WHITE:
            walk(nid, [])
    return found


def _required_inputs(spec: dict) -> list[str]:
    """The required input names for one class, from its /object_info entry.

    ComfyUI's shape is `{"input": {"required": {name: [type, opts]}, "optional": {...}}}`.
    A missing `input` key means a node with no inputs, which is legitimate (primitives, some
    loaders), so it yields an empty list rather than an error.
    """
    return list(((spec.get("input") or {}).get("required") or {}).keys())


def validate(prompt: dict, object_info: dict | None) -> dict:
    """Check a compiled graph. Returns every problem found, not just the first.

    `object_info` may be None when ComfyUI is not running. In that case the structural checks
    -- dangling links, cycles, empty graph -- still run and the class-level checks are
    reported as skipped rather than silently passing. Claiming a graph is valid when the
    catalogue was never consulted would be the dishonest option.
    """
    problems: list[dict] = []

    if not prompt:
        problems.append({"level": "error", "code": "empty_graph",
                         "detail": "nothing to run: the canvas has no nodes"})

    for nid, node in sorted(prompt.items()):
        cls = node.get("class_type")
        inputs = node.get("inputs") or {}

        for name, value in inputs.items():
            if isinstance(value, list) and len(value) == 2:
                src = str(value[0])
                if src not in prompt:
                    problems.append({"level": "error", "code": "dangling_link", "node": nid,
                                     "input": name,
                                     "detail": f"input '{name}' is wired from node {src},"
                                               " which is not in the graph"})

        if object_info is None:
            continue
        spec = object_info.get(cls)
        if spec is None:
            problems.append({"level": "error", "code": "unknown_class", "node": nid,
                             "class_type": cls,
                             "detail": f"'{cls}' is not installed on this ComfyUI. If it "
                                       "comes from a custom node pack, that pack is missing."})
            continue
        for req in _required_inputs(spec):
            if req not in inputs:
                problems.append({"level": "error", "code": "missing_input", "node": nid,
                                 "class_type": cls, "input": req,
                                 "detail": f"{cls} requires input '{req}' and it is neither "
                                           "wired nor set"})

    for cyc in cycles(prompt):
        problems.append({"level": "error", "code": "cycle", "nodes": cyc,
                         "detail": "these nodes feed each other in a loop: "
                                   + " -> ".join(cyc)})

    if not any(p["level"] == "error" for p in problems) and object_info is not None:
        # A graph with no output node runs and saves nothing, which looks exactly like a
        # failure to the person who pressed the button. A warning, not an error: ComfyUI will
        # happily run it, and a preview-only graph is a legitimate thing to want.
        outputs = [nid for nid, n in prompt.items()
                   if (object_info.get(n.get("class_type")) or {}).get("output_node")]
        if not outputs:
            problems.append({"level": "warning", "code": "no_output_node",
                             "detail": "no output node (such as SaveImage), so this graph "
                                       "will run and produce no saved result"})

    return {"ok": not any(p["level"] == "error" for p in problems),
            "checked_against_catalogue": object_info is not None,
            "node_count": len(prompt),
            "problems": problems}


def inject(prompt: dict, params: dict) -> dict:
    """Programmatically set inputs on a compiled graph. Returns a new graph.

    This is the step the brief calls "inject any LLM-generated parameters": the canvas defines
    the shape of the pipeline, and the agent supplies the values. Two addressing forms, so
    the caller can be precise when it knows the graph and loose when it does not:

        {"6.text": "a raven over a foundry"}     one node's input, exact
        {"*.seed": 12345}                        every node that has a `seed` input

    An address naming a node that is not present, or an input that node does not have, is
    returned in `unapplied` rather than raising. The agent is the caller and a hard failure
    would end the turn over a typo it could have corrected; a wildcard that matches nothing is
    reported the same way.
    """
    out = copy.deepcopy(prompt)
    applied: list[dict] = []
    unapplied: list[dict] = []

    for address, value in (params or {}).items():
        if "." not in str(address):
            unapplied.append({"address": address, "reason": "expected 'node_id.input_name'"})
            continue
        nid, _, name = str(address).partition(".")
        targets = list(out) if nid == "*" else [nid]
        hit = False
        for t in targets:
            node = out.get(t)
            if node is None:
                continue
            inputs = node.setdefault("inputs", {})
            # A wildcard only ever *updates* inputs that already exist -- inventing `seed` on
            # a node that has none would produce a graph ComfyUI rejects.
            if nid == "*" and name not in inputs:
                continue
            inputs[name] = value
            applied.append({"node": t, "input": name, "value": value})
            hit = True
        if not hit:
            unapplied.append({"address": address,
                              "reason": ("no node has that input" if nid == "*"
                                         else f"node {nid} is not in this graph")})

    return {"graph": out, "applied": applied, "unapplied": unapplied}


def from_prompt(prompt: dict, columns: int = 4, spacing: tuple[int, int] = (320, 200)) -> dict:
    """The inverse of `to_prompt`: a ComfyUI graph back into a canvas document.

    Needed so an existing workflow JSON -- one of ComfyUI's own examples, or something the
    agent generated -- can be opened on the canvas and edited. Positions are not in the prompt
    format at all (ComfyUI's *API* format drops the UI layout), so nodes are laid out on a
    grid in dependency order. That is a fabricated layout and it is worth saying so: it will
    not match how the graph looked in ComfyUI's own editor, because that information is not
    in the file.
    """
    nodes: list[dict] = []
    links: list[dict] = []
    order = _topo(prompt)
    dx, dy = spacing

    for i, nid in enumerate(order):
        node = prompt[nid]
        widgets = {}
        for name, value in (node.get("inputs") or {}).items():
            if isinstance(value, list) and len(value) == 2 and str(value[0]) in prompt:
                links.append({"from_node": str(value[0]), "from_slot": int(value[1]),
                              "to_node": str(nid), "to_input": name})
            else:
                widgets[name] = value
        nodes.append({"id": str(nid), "class_type": node.get("class_type"),
                      "pos": {"x": (i % columns) * dx + 40, "y": (i // columns) * dy + 40},
                      "widgets": widgets})
    return {"nodes": nodes, "links": links, "layout": "generated"}


def _topo(prompt: dict) -> list[str]:
    """Dependency order, falling back to key order on a cycle so layout never raises."""
    seen: set[str] = set()
    order: list[str] = []

    def visit(nid: str, stack: frozenset[str]) -> None:
        if nid in seen or nid in stack:
            return
        node = prompt.get(nid) or {}
        for value in (node.get("inputs") or {}).values():
            if isinstance(value, list) and len(value) == 2 and str(value[0]) in prompt:
                visit(str(value[0]), stack | {nid})
        seen.add(nid)
        order.append(nid)

    for nid in prompt:
        visit(str(nid), frozenset())
    return order
