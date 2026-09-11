"""Tool registry and JSON Schema introspection, on the standard library alone.

`FastMCP` is the framework the brief named and `mcp_server.py` is where it lives -- but it
is not installed and, per `.claude/CLAUDE.md`, must never be installed into the system
interpreter, which is the serving path. So this package keeps the tool *implementations* and
their *schemas* dependency-free, and FastMCP wraps the very same functions from its own venv.

The consequence is worth stating plainly, because it is the whole reason for the split:

    api.py  ->  registry.py  ->  tools_impl/*     always works, stdlib + httpx
    MCP client ->  mcp_server.py  ->  tools_impl/*     works when .venv is built

Both routes execute *the same function objects*. There is no second copy of a tool to drift,
and `mcp_server.py` contains no tool logic at all -- it iterates this registry and calls
`mcp.tool()` on what it finds. A tool added to `tools_impl/` appears on both surfaces without
being mentioned in either place.

## Where the schema comes from

`inspect.signature` for the parameter names, order and defaults; `typing.get_type_hints` for
the annotations (resolved, so `from __future__ import annotations` does not leave us holding
strings); the docstring for the descriptions. Nothing is hand-written, which is what the
brief asked for -- "write the Python functions so that FastMCP can introspect them" -- and
what keeps the prompt the LLM sees honest: the tool list it is given is generated from the
code that will actually run.

Docstrings are Google-style. The summary line becomes the tool description and an `Args:`
block becomes the per-property descriptions:

    def read_file(path: str, max_bytes: int = 200_000) -> dict:
        '''Read a UTF-8 text file.

        Args:
            path: Absolute, or relative to the project root.
            max_bytes: Truncate beyond this. The result says whether it truncated.
        '''

A parameter with no `Args:` entry still gets a schema entry -- it just has no description.
That is a documentation gap, not an error, and failing the whole registry over it would mean
one sloppy docstring took every tool offline.
"""
from __future__ import annotations

import dataclasses
import enum
import inspect
import re
import typing

__all__ = ["tool", "TOOLS", "Tool", "tool_specs", "get", "names", "call", "check",
           "schema_for"]

# ---- type mapping ----------------------------------------------------------
# Deliberately small. An unmapped annotation becomes an untyped property rather than raising:
# JSON Schema's "no `type` key" means "any", which is a truthful description of a parameter
# whose type we could not express, and a great deal better than refusing to expose the tool.
_PRIMITIVES: dict[object, str] = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
    type(None): "null",
}


def _unwrap_optional(ann: object) -> tuple[object, bool]:
    """`X | None` -> (X, True). Handles both `typing.Optional[X]` and PEP 604 unions."""
    origin = typing.get_origin(ann)
    if origin is typing.Union or origin is getattr(__import__("types"), "UnionType", None):
        args = [a for a in typing.get_args(ann) if a is not type(None)]
        if len(args) == 1:
            return args[0], True
        # A genuine multi-member union. JSON Schema can express it, but the LLM-facing
        # value of doing so is low and the failure modes are subtle, so it degrades to
        # "any" with the nullability preserved.
        return object, True
    return ann, False


def _json_type(ann: object) -> dict:
    """One annotation -> one JSON Schema fragment."""
    ann, nullable = _unwrap_optional(ann)

    if ann in _PRIMITIVES:
        node: dict = {"type": _PRIMITIVES[ann]}
    elif isinstance(ann, type) and issubclass(ann, enum.Enum):
        # An Enum is the one case where we can hand the model an exact vocabulary, which
        # measurably beats describing the options in prose.
        node = {"enum": [m.value for m in ann]}
    elif isinstance(ann, type) and dataclasses.is_dataclass(ann):
        node = {"type": "object", "properties": {
            f.name: _json_type(f.type) for f in dataclasses.fields(ann)}}
    else:
        origin = typing.get_origin(ann)
        args = typing.get_args(ann)
        if origin in (list, set, frozenset, tuple):
            node = {"type": "array"}
            if args and args[0] is not Ellipsis:
                node["items"] = _json_type(args[0])
        elif origin is dict:
            node = {"type": "object"}
            if len(args) == 2:
                node["additionalProperties"] = _json_type(args[1])
        elif ann is typing.Any or ann is object or ann is inspect.Parameter.empty:
            node = {}
        else:
            node = {}

    if nullable and "type" in node:
        node["type"] = [node["type"], "null"]
    return node


# ---- docstring parsing -----------------------------------------------------
_ARGS_HEADER = re.compile(r"^\s*(Args|Arguments|Parameters)\s*:\s*$", re.M)
_ARG_LINE = re.compile(r"^\s{2,}(\*{0,2}\w+)\s*(?:\([^)]*\))?\s*:\s*(.+)$")
_SECTION = re.compile(r"^\s*(Returns|Raises|Yields|Example|Examples|Note|Notes)\s*:\s*$", re.M)


def _split_doc(doc: str | None) -> tuple[str, dict[str, str]]:
    """(summary, {param: description}). Continuation lines are folded into the previous
    parameter so a wrapped description does not silently lose its tail."""
    if not doc:
        return "", {}
    text = inspect.cleandoc(doc)
    m = _ARGS_HEADER.search(text)
    if not m:
        return text.split("\n\n")[0].strip(), {}

    summary = text[: m.start()].split("\n\n")[0].strip()
    body = text[m.end():]
    end = _SECTION.search(body)
    if end:
        body = body[: end.start()]

    params: dict[str, str] = {}
    last: str | None = None
    for line in body.splitlines():
        if not line.strip():
            continue
        hit = _ARG_LINE.match(line)
        if hit:
            last = hit.group(1).lstrip("*")
            params[last] = hit.group(2).strip()
        elif last:
            params[last] += " " + line.strip()
    return summary, params


# ---- the registry ----------------------------------------------------------
@dataclasses.dataclass(frozen=True)
class Tool:
    name: str
    group: str
    fn: typing.Callable
    description: str
    parameters: dict
    dangerous: bool

    def spec(self) -> dict:
        """OpenAI / Ollama `tools` array entry. llama.cpp's server accepts the same shape,
        which is why the two inference backends need no per-backend tool formatting."""
        return {"type": "function", "function": {
            "name": self.name,
            "description": self.description,
            "parameters": self.parameters,
        }}


TOOLS: dict[str, Tool] = {}


def schema_for(fn: typing.Callable) -> tuple[str, dict]:
    """(description, JSON Schema object) for one callable. Exported because `test_studio.py`
    asserts against it directly.

    `mcp_server.py` does not call it. FastMCP derives its own schema from the wrapped function's
    signature (`functools.wraps` there is what makes that work), so the only thing of this
    function's that reaches an MCP client is the description -- `tool()` below calls it at
    registration time and stores the summary on the `Tool`."""
    try:
        hints = typing.get_type_hints(fn)
    except Exception:
        # A forward reference we cannot resolve should cost that tool its *types*, not its
        # existence. The parameter names and defaults still come through below.
        hints = {}
    summary, docs = _split_doc(fn.__doc__)

    props: dict[str, dict] = {}
    required: list[str] = []
    for name, param in inspect.signature(fn).parameters.items():
        if name in ("self", "cls") or param.kind in (
                inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
            continue
        node = _json_type(hints.get(name, param.annotation))
        if name in docs:
            node["description"] = docs[name]
        if param.default is not inspect.Parameter.empty:
            # `default` is advisory in JSON Schema but several local models do read it, and
            # it stops the model inventing a value for something that already has a sane one.
            node["default"] = param.default
        else:
            required.append(name)
        props[name] = node

    return summary, {"type": "object", "properties": props, "required": required}


def tool(group: str = "misc", *, name: str | None = None, dangerous: bool = False):
    """Register a function as an agent-callable tool.

    `dangerous` does not restrict anything -- nothing in this package refuses a call. It is
    a label, surfaced in the UI and in the system prompt, so the operator can see at a glance
    which tools write to the host. No filtering is implemented here as of 2026-08-20 (a
    deliberate pre-launch state, not a cleared posture -- request ledger R-98, held); the
    switch that controls this surface is the token gate in `__init__.py`.
    """
    def deco(fn: typing.Callable) -> typing.Callable:
        summary, params = schema_for(fn)
        key = name or fn.__name__
        if key in TOOLS:
            raise ValueError(f"duplicate tool name {key!r}: "
                             f"{TOOLS[key].fn.__module__} already registered it")
        TOOLS[key] = Tool(name=key, group=group, fn=fn, description=summary,
                          parameters=params, dangerous=dangerous)
        return fn
    return deco


def names() -> list[str]:
    return sorted(TOOLS)


def get(name: str) -> Tool | None:
    return TOOLS.get(name)


def tool_specs() -> list[dict]:
    """The whole registry in OpenAI `tools` form -- what gets injected into the prompt."""
    return [TOOLS[n].spec() for n in names()]


def check(name: str, arguments: dict) -> dict | None:
    """Validate arguments against the generated schema. `None` means they are fine.

    This is not a safeguard and does not restrict what any tool may do -- it restricts nothing
    at all. It exists because the caller is a 7B model and the alternative to a checked
    argument list is a `TypeError` raised inside the tool, which arrives as a traceback and
    ends the turn. A structured refusal naming the parameter arrives as a `tool` message the
    model can read and correct on the next step, which is the difference between a wasted turn
    and a corrected one.

    Three things are checked, and deliberately only three:

    * a required parameter is missing -- the model omitted it;
    * an argument was passed that the function does not accept -- the model invented it,
      usually by carrying a parameter name over from a different tool;
    * a value is of a type the function cannot use, where the schema says a primitive.

    Types are checked loosely on purpose. `1` for a `number` is fine, and a string that parses
    as an integer is *not* rewritten here -- `_coerce` below does that, because rejecting
    `steps="4"` for being a string would be pedantry rather than help.
    """
    entry = TOOLS.get(name)
    if entry is None:
        return {"error": "unknown_tool", "tool": name, "available": names()}
    props = entry.parameters.get("properties", {})
    required = entry.parameters.get("required", [])

    missing = [k for k in required if k not in arguments]
    unknown = [k for k in arguments if k not in props]
    if missing or unknown:
        return {"error": "bad_arguments", "tool": name,
                "missing": missing, "unknown": unknown,
                "accepts": sorted(props),
                "detail": (f"{name} takes {sorted(props)}"
                           + (f"; required: {required}" if required else "")),
                "hint": "call it again with these corrected"}

    wrong = []
    for key, value in arguments.items():
        want = props[key].get("type")
        if want is None or value is None:
            continue
        if want == "boolean" and not isinstance(value, bool):
            wrong.append({"parameter": key, "expected": want, "got": type(value).__name__})
        elif want == "integer":
            # `bool` is a subclass of `int`, so `isinstance(True, int)` is True and a model
            # that answered `"steps": true` would sail through an obvious check and render
            # one step. Excluded explicitly.
            numeric = isinstance(value, int) and not isinstance(value, bool)
            digits = isinstance(value, str) and value.strip().lstrip("-").isdigit()
            if not (numeric or digits):
                wrong.append({"parameter": key, "expected": want, "got": type(value).__name__})
        elif want == "number" and not isinstance(value, (int, float)):
            try:
                float(value)
            except (TypeError, ValueError):
                wrong.append({"parameter": key, "expected": want, "got": type(value).__name__})
        elif want == "string" and not isinstance(value, str):
            wrong.append({"parameter": key, "expected": want, "got": type(value).__name__})
    if wrong:
        return {"error": "bad_argument_types", "tool": name, "parameters": wrong,
                "hint": "call it again with these corrected"}
    return None


def _coerce(entry: Tool, arguments: dict) -> dict:
    """Numbers arriving as strings, made numbers.

    Local models emit `"steps": "4"` regularly -- it is a text-completion artefact, not a
    misunderstanding, and the model will make the same one again next turn. Rewriting it here
    is cheaper than a round trip that teaches it nothing. Anything that does not convert is
    left exactly as it came, because `check()` has already passed it and guessing further
    would be the kind of silent repair that hides a real bug.
    """
    props = entry.parameters.get("properties", {})
    out = dict(arguments)
    for key, value in out.items():
        want = props.get(key, {}).get("type")
        if not isinstance(value, str):
            continue
        try:
            if want == "integer":
                out[key] = int(value.strip())
            elif want == "number":
                out[key] = float(value.strip())
            elif want == "boolean":
                out[key] = value.strip().lower() in ("true", "1", "yes", "on")
        except ValueError:
            pass
    return out


async def call(name: str, arguments: dict) -> object:
    """Execute a registered tool, awaiting it if it is a coroutine function.

    Unknown names and bad argument lists return a structured error rather than raising,
    because the caller is an LLM that hallucinated and the useful response is to tell it so in
    a message it can recover from -- a traceback would end the turn. See `check()`.
    """
    entry = TOOLS.get(name)
    if entry is None:
        return {"error": "unknown_tool", "tool": name, "available": names()}
    problem = check(name, arguments)
    if problem is not None:
        return problem
    arguments = _coerce(entry, arguments)
    if inspect.iscoroutinefunction(entry.fn):
        return await entry.fn(**arguments)
    import anyio
    return await anyio.to_thread.run_sync(lambda: entry.fn(**arguments))
