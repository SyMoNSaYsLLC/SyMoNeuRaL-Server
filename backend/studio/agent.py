"""The cognitive loop: prompt, detect a tool call, execute it, feed the result back, synthesise.

## The loop

    user query
      -> system prompt (identity + the tool list, generated from registry.py)
      -> backend
      -> did it ask for a tool?
           yes -> execute the local Python function
                -> append the RAW result as a `tool` message
                -> back to the backend                      (up to SYMONEURAL_STUDIO_MAX_STEPS)
           no  -> that is the answer

"Raw" is meant literally. The tool's return value is JSON-serialised and handed back
unabridged rather than summarised, because a summary written by this module would be a second,
unreviewable model of what the tool meant. If a tool returns something large it is the tool's
job to truncate and to say that it truncated -- which is why every result shape in
`tools_impl/` carries its own truncation flags.

## Two ways a tool call arrives, because local models are inconsistent

1. **Native.** `choices[0].message.tool_calls`, the OpenAI shape. llama.cpp's server
   implements this for Qwen2.5's chat template and Ollama does for models whose template
   declares it.
2. **In the text.** A 7B model that has lost the thread will write the JSON into its reply as
   a fenced block, or bare. `_text_tool_calls` finds those.

Supporting only (1) means the loop silently stops working the moment a model or a build does
not do native calls, and the symptom -- the model narrating a tool call that never happens --
looks exactly like the model being stupid rather than like a parsing gap. Both paths are
normalised to the same internal shape before anything downstream sees them.

## What this does not do

There is no output filter, no refusal path and no prompt-injection guard, per the standing
instruction in `apps/voice/__init__.py`. `SYMONEURAL_STUDIO_MAX_STEPS` bounds the loop so a model
that gets stuck calling `list_dir` forever eventually stops and says what it found; that is a
termination condition, not a restriction on what may be called.
"""
from __future__ import annotations

import json
import os
import re
import time
from typing import Any, AsyncIterator

from . import inference, registry

__all__ = ["system_prompt", "run", "MAX_STEPS", "PERMISSION_MODES"]

MAX_STEPS = int(os.environ.get("SYMONEURAL_STUDIO_MAX_STEPS", "8"))

# The permission modes, spelled once. `routes.py` validates against this tuple and `run()`
# refuses anything outside it, so the two cannot disagree about what a valid mode is -- and
# the gate below tests `permissions in ("ask", "deny")`, which means any string this tuple
# does not contain would behave exactly like "allow". A permission system is not allowed to
# fail open on a typo, so an unknown mode has to be rejected rather than interpreted.
PERMISSION_MODES = ("allow", "deny", "ask")

IDENTITY = """\
You are SyMoNeuRaL Studio, the local orchestration agent for the SyMoNeuRaL stack.

You run entirely on this machine. There is no cloud model behind you, no telemetry, and no
external API. The person you are talking to is the operator of this box and has full rights
over it; you have been given real tools that read and write the host filesystem, run shell
commands, inspect and configure the applications in this stack, and drive image generation
through a local ComfyUI server.

How to work:

- Prefer a tool over a guess. You can read the actual file, run the actual command, and check
  the actual GPU state. Do that instead of describing what is probably there.
- Report what the tool returned, including failures. If a command exits non-zero, say so and
  quote the error. Never present an intention as a result.
- Chain tools when a task needs it. Look something up, then act on what you found.
- The GPU is a single card and one job holds it at a time. Image generation takes the lock,
  runs, and gives it back. Do not expect to run chat and image work simultaneously.
- Paths may be given relative to the project root; the tools resolve them.
- Numbers you report must come from a tool result. Do not invent measurements, timings, or
  file sizes.
"""

TOOL_PROTOCOL = """\
When you need a tool, emit a JSON object on its own, in a fenced block:

```json
{"tool": "<name>", "arguments": {"<arg>": <value>}}
```

Emit one call at a time and wait for its result before deciding the next step. When you have
enough information, answer in plain prose with no JSON block.
"""


def system_prompt(extra: str = "") -> str:
    """Identity plus a tool list generated from the registry.

    The list is rendered from `registry.tool_specs()` every time rather than being maintained
    by hand, so a tool added to `tools_impl/` is one the model knows about immediately and a
    tool removed cannot linger in the prompt as a promise the loop can no longer keep.
    """
    lines: list[str] = []
    by_group: dict[str, list[registry.Tool]] = {}
    for name in registry.names():
        t = registry.TOOLS[name]
        by_group.setdefault(t.group, []).append(t)

    for group in sorted(by_group):
        lines.append(f"\n## {group}")
        for t in by_group[group]:
            params = t.parameters.get("properties", {})
            required = set(t.parameters.get("required", []))
            sig = ", ".join(
                f"{p}: {_type_name(s)}" + ("" if p in required else " = optional")
                for p, s in params.items())
            mark = "  [writes to the host]" if t.dangerous else ""
            lines.append(f"- `{t.name}({sig})`{mark}\n      {t.description}")

    body = [IDENTITY, "\n# Tools available to you\n",
            f"{len(registry.TOOLS)} tools, generated from the running code:",
            "\n".join(lines), "\n", TOOL_PROTOCOL]
    if extra:
        body.append("\n# Context for this session\n" + extra)
    return "\n".join(body)


def _type_name(schema: dict) -> str:
    t = schema.get("type")
    if isinstance(t, list):
        return "|".join(x for x in t if x != "null") + "?"
    if t:
        return str(t)
    return "enum" if "enum" in schema else "any"


# ---- tool-call extraction --------------------------------------------------
_FENCED = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.S)


def _balanced_objects(text: str) -> list[str]:
    """Every top-level {...} in a string, by brace counting.

    A regex cannot do this correctly for nested objects, and tool arguments nest routinely
    (`{"tool": "queue_workflow", "arguments": {"graph": {...}}}`). String literals are tracked
    so a brace inside a prompt string does not throw the count off.
    """
    out: list[str] = []
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
            if depth:
                depth -= 1
                if depth == 0 and start >= 0:
                    out.append(text[start:i + 1])
    return out


def _text_tool_calls(text: str) -> list[dict]:
    """Tool calls a model wrote into its prose instead of into `tool_calls`.

    Accepts the documented `{"tool": ..., "arguments": ...}` and also the `{"name": ...,
    "parameters": ...}` variant, because Qwen and Llama templates each emit one of them and a
    loop that only understands the shape it asked for will silently drop half the calls it is
    given.
    """
    found: list[dict] = []
    seen: set[str] = set()
    candidates = _FENCED.findall(text) or _balanced_objects(text)
    for blob in candidates:
        try:
            doc = json.loads(blob)
        except ValueError:
            continue
        if not isinstance(doc, dict):
            continue
        name = doc.get("tool") or doc.get("name") or doc.get("function")
        if not isinstance(name, str) or name not in registry.TOOLS:
            continue
        args = doc.get("arguments")
        if args is None:
            args = doc.get("parameters") or doc.get("args") or {}
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except ValueError:
                args = {}
        if not isinstance(args, dict):
            args = {}
        key = name + json.dumps(args, sort_keys=True, default=str)
        if key in seen:
            continue
        seen.add(key)
        found.append({"name": name, "arguments": args})
    return found


def _native_tool_calls(message: dict) -> list[dict]:
    calls = message.get("tool_calls") or []
    out: list[dict] = []
    for c in calls:
        fn = (c or {}).get("function") or {}
        name = fn.get("name")
        if not name:
            continue
        args = fn.get("arguments")
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except ValueError:
                args = {}
        out.append({"name": name, "arguments": args if isinstance(args, dict) else {},
                    "id": c.get("id")})
    return out


def _strip_calls(text: str) -> str:
    """The prose with the tool-call JSON removed, so the UI can show reasoning without the
    machinery. Only fenced blocks are stripped -- cutting bare objects out of a reply would
    mangle a message that legitimately contains JSON."""
    return _FENCED.sub("", text or "").strip()


# ---- the loop --------------------------------------------------------------
async def run(query: str, history: list[dict] | None = None, *,
              max_steps: int | None = None, context: str = "",
              model: str | None = None,
              temperature: float = 0.6,
              permissions: str = "allow",
              allow: list[str] | None = None,
              resume: list[dict] | None = None) -> AsyncIterator[dict]:
    """Run one agent turn, yielding events as they happen.

    Events, all `{"event": ..., ...}`:

        backend   which engine answered, once, first
        thinking  prose the model produced on an intermediate step
        tool_call name + arguments, before execution
        tool_result the raw return value, after execution
        permission_required  a gated tool was chosen; the turn STOPS without running it
        answer    the final synthesis
        error     something failed; the turn is over
        done      step count and wall clock

    Yielding rather than returning is what lets the browser show a tool executing while it
    executes, instead of a spinner followed by a wall of text.

    `permissions` decides what happens when the model chooses a tool the registry marks
    `dangerous=True` -- `delete_path`, `env_set`, `run_command`, `write_file` -- and `allow`
    names individual tools exempted from it whatever the mode:

        "allow"  run it. The default, because it is what this endpoint did before the mode
                 existed and the /studio page has no way to answer a prompt. Changing the
                 default would have gated the browser surface silently, which is a different
                 decision that belongs to whoever makes it deliberately.
        "deny"   do not run it; hand the model a `not_permitted` result and keep going. This
                 is for a caller that cannot be asked -- a pipe, a cron job -- and it is the
                 honest shape for that case: the turn still completes and the model is told
                 what it was refused, instead of a client pretending to have asked somebody.
        "ask"    do not run it; yield `permission_required` and END THE TURN.

    Any other string is refused outright -- a `bad_permissions` error event and a turn that
    runs nothing, before a backend is even picked. That is not defensive noise: the gate is
    written as `permissions in ("ask", "deny")`, so an unrecognised mode would fall through
    it and behave exactly like "allow". `routes.py` already 400s a bad mode, which makes this
    the backstop for the next in-process caller rather than the check the HTTP surface relies
    on -- and a permission system may not fail open on a typo at either layer.

    "ask" ends the turn rather than waiting because this transport is one-directional: SSE
    cannot carry the answer back. The frame therefore carries everything the caller needs to
    resume -- the exact `arguments`, and `pending`, the messages already appended during this
    step. The caller runs the approved tool ITSELF via `POST /api/studio/tool/{name}` with the
    arguments it displayed, appends the result, and re-issues the turn with the longer history.

    That indirection is the point. The obvious design -- re-run the turn with the tool now
    allowed -- lets the model re-choose at temperature, so it can call `run_command` with
    different arguments than the ones a human read and approved, and every tool that ran
    before the gate runs a second time. A prompt that displays A and executes B is worse than
    no prompt at all.

    `resume` is the other half of that: messages appended AFTER the user query rather than
    before it, which is where the caller's approved tool call and its result belong. Sending
    them as `history` would put them ahead of the query and the model would read its own tool
    call as something that happened before it was asked, then find the question repeated at
    the end of the transcript. One list cannot do both jobs, so there are two.

    A resumed segment starts its step count at zero, because it is a new call. `steps` and
    `tools_used` on `done` are therefore per-segment, and a caller that wants the whole turn
    adds them up -- which is what the terminal client's status line does.
    """
    if permissions not in PERMISSION_MODES:
        yield {"event": "error", "code": "bad_permissions",
               "detail": "permissions must be one of: " + ", ".join(PERMISSION_MODES),
               "got": permissions}
        return

    started = time.monotonic()
    steps = max_steps if max_steps is not None else MAX_STEPS

    backend = await inference.pick()
    if backend is None:
        st = await inference.state()
        yield {"event": "error", "code": "no_backend",
               "detail": "no local inference backend is answering", "state": st}
        return
    yield {"event": "backend", "name": backend.name, "url": backend.base}

    messages: list[dict] = [{"role": "system", "content": system_prompt(context)}]
    messages += list(history or [])
    messages.append({"role": "user", "content": query})
    messages += list(resume or [])

    specs = registry.tool_specs()
    used = 0

    for step in range(steps):
        try:
            reply = await backend.chat(messages, tools=specs, model=model,
                                       temperature=temperature)
        except inference.InferenceError as e:
            # Native tool calling is the likeliest thing to 400 here. Retry once without the
            # tools array so the turn degrades to plain chat rather than dying -- and say so,
            # because a silent downgrade would look like the model ignoring its tools.
            yield {"event": "notice", "detail": f"retrying without native tools: {e}"}
            try:
                reply = await backend.chat(messages, tools=None, model=model,
                                           temperature=temperature)
            except inference.InferenceError as e2:
                yield {"event": "error", "code": "backend_error", "detail": str(e2)}
                return

        choice = (reply.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        text = message.get("content") or ""

        calls = _native_tool_calls(message) or _text_tool_calls(text)

        if not calls:
            yield {"event": "answer", "text": text, "step": step + 1}
            yield {"event": "done", "steps": step + 1, "tools_used": used,
                   "seconds": round(time.monotonic() - started, 2)}
            return

        prose = _strip_calls(text)
        if prose:
            yield {"event": "thinking", "text": prose, "step": step + 1}

        # Record the assistant turn before the results, so the transcript the model sees on
        # the next pass is in the order its template expects.
        messages.append({"role": "assistant",
                         "content": text or "",
                         **({"tool_calls": message["tool_calls"]}
                            if message.get("tool_calls") else {})})

        # Everything appended during this step, so that a gate can hand the caller exactly
        # what it must add to its own history before resuming. Slicing `messages` would work
        # today and would break the first time anything else appends; this is explicit.
        pending: list[dict] = [messages[-1]]
        exempt = set(allow or [])

        for call in calls:
            name, args = call["name"], call["arguments"]
            entry_tool = registry.get(name)
            gated = (entry_tool is not None and entry_tool.dangerous
                     and name not in exempt and permissions in ("ask", "deny"))

            if gated and permissions == "ask":
                # The turn ends here and NOTHING is run. Any tool call after this one in the
                # same message is dropped on purpose: the model chose them as a set, and
                # running the tail of a set whose head was never approved is a decision
                # nobody made. They come back when the caller resumes.
                yield {"event": "permission_required", "name": name, "arguments": args,
                       "call_id": call.get("id"), "step": step + 1, "pending": pending,
                       "reason": f"{name} is marked dangerous in the tool registry",
                       "dropped": [c["name"] for c in calls[calls.index(call) + 1:]]}
                yield {"event": "done", "steps": step + 1, "tools_used": used,
                       "awaiting_permission": True,
                       "seconds": round(time.monotonic() - started, 2)}
                return

            yield {"event": "tool_call", "name": name, "arguments": args, "step": step + 1,
                   **({"gated": True} if gated else {})}
            t0 = time.monotonic()
            try:
                if gated:                                  # permissions == "deny" by here
                    result = {"error": "not_permitted", "tool": name,
                              "detail": "the caller refused this tool without asking a "
                                        "human, because it has nobody to ask. Do not retry "
                                        "it; say what you would have needed it for."}
                else:
                    result = await registry.call(name, args)
            except TypeError as e:
                # Wrong arguments for a real tool. Recoverable: tell the model what it got
                # wrong and let it try again rather than ending the turn.
                result = {"error": "bad_arguments", "tool": name, "detail": str(e),
                          "schema": (registry.TOOLS[name].parameters
                                     if name in registry.TOOLS else None)}
            except Exception as e:
                result = {"error": "tool_raised", "tool": name,
                          "detail": f"{type(e).__name__}: {e}"}
            elapsed = round(time.monotonic() - t0, 3)
            # A refused tool is not a used tool. `tools_used` is read as "the card and the
            # filesystem were touched this many times", and counting a denial in it would
            # inflate exactly the figure somebody would check that against.
            if not gated:
                used += 1

            yield {"event": "tool_result", "name": name, "result": result,
                   "seconds": elapsed, "step": step + 1}

            payload = json.dumps(result, default=str)
            entry: dict[str, Any] = {"role": "tool", "name": name, "content": payload}
            if call.get("id"):
                entry["tool_call_id"] = call["id"]
            messages.append(entry)
            pending.append(entry)

    # Fell out of the loop with tools still being called. Ask once for a synthesis rather
    # than returning nothing, and label it -- an answer produced under a step cap is not the
    # same as one the model chose to give.
    try:
        final = await backend.chat(
            messages + [{"role": "user",
                         "content": "Step limit reached. Summarise what you found and what "
                                    "remains undone, using only tool results above."}],
            tools=None, model=model, temperature=temperature)
        text = ((final.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
    except inference.InferenceError as e:
        yield {"event": "error", "code": "backend_error", "detail": str(e)}
        return

    yield {"event": "answer", "text": text, "truncated": True, "step": steps}
    yield {"event": "done", "steps": steps, "tools_used": used, "hit_step_limit": True,
           "seconds": round(time.monotonic() - started, 2)}
