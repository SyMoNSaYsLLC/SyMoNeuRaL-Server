"""The inference adapter: one interface, two local backends, no cloud.

The brief said *"Configure the pipeline to use my local Ollama server via its HTTP API."*
**Ollama is not installed on this box.** There is no binary on `PATH` or in `/usr/local/bin`,
no `~/.ollama`, no systemd unit, and nothing listening on 11434. Installing it needs `sudo`,
which this agent does not have. Writing the pipeline against it anyway would have produced a
module that has never once run.

So this is written as an adapter with two backends rather than as an Ollama client:

| Backend | Where | Status on this box |
|---|---|---|
| `llamacpp` | `127.0.0.1:8081` | the stack's real chat engine (`api.py:151`) |
| `ollama` | `127.0.0.1:11434` | supported, not installed |

Both speak `POST /v1/chat/completions` with the OpenAI request shape, including the `tools`
array, so `agent.py` contains no per-backend branching at all -- picking a backend changes a
base URL and nothing else. If Ollama is installed later it is found automatically, and
`SYMONEURAL_STUDIO_LLM=ollama` pins it.

    curl -fsSL https://ollama.com/install.sh | sh
    ollama pull qwen2.5:7b-instruct

## Why this does not start llama-server itself

`backend/server.py` already owns that lifecycle: `start_llama()` spawns it *inside*
`gpu.hold("chat")` with a carefully measured argv (`-c 65536 -cb -np 2`, the LoRA adapter,
the draft model) and a module-level handle to the process. A second spawner here would race
that one for the same port and the same GPU lease, and the failure would be intermittent and
horrible to debug.

So this module **probes and uses**; it never spawns. When llama-server is down, `state()`
says so and names the fix rather than silently failing or, worse, quietly starting a second
copy with different parameters. The chat surface warms the engine; the Studio agent rides it.
That is the clean separation the deliverable asked for, and it is also the only safe one.
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, AsyncIterator

from ..lib import httpclient

__all__ = ["Backend", "backends", "pick", "state", "OLLAMA_URL", "LLAMACPP_URL"]

LLAMACPP_URL = os.environ.get("SYMONEURAL_LLAMACPP_URL", "http://127.0.0.1:8081")
OLLAMA_URL = os.environ.get("SYMONEURAL_OLLAMA_URL", "http://127.0.0.1:11434")


@dataclass(frozen=True)
class Backend:
    """One OpenAI-compatible endpoint. `name` is what the operator sets SYMONEURAL_STUDIO_LLM to."""
    name: str
    base: str
    model_hint: str

    @property
    def chat_url(self) -> str:
        return f"{self.base.rstrip('/')}/v1/chat/completions"

    async def up(self, timeout: float = 2.0) -> bool:
        """Is something answering. `/v1/models` is the one path both backends serve and
        neither of them makes expensive."""
        try:
            async with httpclient.AsyncClient(timeout=timeout) as c:
                r = await c.get(f"{self.base.rstrip('/')}/v1/models")
                return r.status_code < 500
        except httpclient.HTTPError:
            return False

    async def models(self, timeout: float = 5.0) -> list[str]:
        try:
            async with httpclient.AsyncClient(timeout=timeout) as c:
                r = await c.get(f"{self.base.rstrip('/')}/v1/models")
                r.raise_for_status()
                doc = r.json()
        except (httpclient.HTTPError, ValueError):
            return []
        return [m.get("id") for m in (doc.get("data") or []) if isinstance(m, dict)]

    async def chat(self, messages: list[dict], tools: list[dict] | None = None,
                   model: str | None = None, temperature: float = 0.6,
                   max_tokens: int = 2048, timeout: float = 600.0) -> dict:
        """One non-streaming completion. Returns the raw OpenAI-shaped response.

        `tools` is passed through when present. llama.cpp's server implements native tool
        calling for Qwen2.5's template, but coverage varies by model and build -- `agent.py`
        therefore also parses tool calls out of plain text, and does not assume this worked.
        """
        body: dict[str, Any] = {
            "model": model or self.model_hint,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"
        async with httpclient.AsyncClient(timeout=timeout) as c:
            r = await c.post(self.chat_url, json=body)
        if r.status_code != 200:
            # Surface the server's own error text. A 400 from llama.cpp about an unsupported
            # `tools` payload is the single most likely failure here and its message says so.
            raise InferenceError(f"{self.name} returned {r.status_code}: {r.text[:600]}")
        return r.json()

    async def stream(self, messages: list[dict], tools: list[dict] | None = None,
                     model: str | None = None, temperature: float = 0.6,
                     max_tokens: int = 2048,
                     timeout: float = 600.0) -> AsyncIterator[dict]:
        """Token-by-token deltas, as OpenAI-shaped chunk dicts. Nothing calls it.

        The agent loop uses `chat` only -- `agent.py:274`, `:282` and `:342` are the three call
        sites and all three are `backend.chat`. `/api/studio/agent` does stream, but it streams
        the loop's *events* (`agent.py:239`, "yielding events as they happen"): backend chosen,
        tool called, tool returned, done. That is a different granularity from tokens and it does
        not go through here.

        Kept because both backends support `stream: true` and the SSE surface it would feed
        already exists, so wiring a token channel is a change to `agent.py`, not a new module.
        Read it as tested-shaped but unexercised: no test drives it either, so treat the chunk
        parsing below as unproven rather than as a working path.
        """
        body: dict[str, Any] = {
            "model": model or self.model_hint,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
        }
        if tools:
            body["tools"] = tools
            body["tool_choice"] = "auto"
        async with httpclient.AsyncClient(timeout=timeout) as c:
            async with c.stream("POST", self.chat_url, json=body) as r:
                if r.status_code != 200:
                    detail = (await r.aread()).decode("utf-8", "replace")
                    raise InferenceError(f"{self.name} returned {r.status_code}: "
                                         f"{detail[:600]}")
                async for line in r.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    payload = line[5:].strip()
                    if payload == "[DONE]":
                        return
                    try:
                        yield json.loads(payload)
                    except ValueError:
                        continue


class InferenceError(RuntimeError):
    """The backend answered, and what it said was not a completion."""


LLAMACPP = Backend("llamacpp", LLAMACPP_URL, "SymonChat S1-7B")
OLLAMA = Backend("ollama", OLLAMA_URL, "qwen2.5:7b-instruct")


def backends() -> dict[str, Backend]:
    return {b.name: b for b in (LLAMACPP, OLLAMA)}


async def pick() -> Backend | None:
    """Choose a backend: the pinned one if `SYMONEURAL_STUDIO_LLM` names it, otherwise whichever is
    actually answering, llama.cpp first because it is this stack's own engine.

    Returns None when neither responds. That is a real state on this box -- llama-server is
    started on demand by the chat surface and is down most of the time -- and it is reported
    rather than papered over.
    """
    pinned = (os.environ.get("SYMONEURAL_STUDIO_LLM") or "").strip().lower()
    order = list(backends().values())
    if pinned in backends():
        chosen = backends()[pinned]
        # A pin is an instruction, not a preference: if the operator pinned Ollama, do not
        # silently answer from llama.cpp and let them believe Ollama is working.
        return chosen if await chosen.up() else None
    for b in order:
        if await b.up():
            return b
    return None


async def state() -> dict:
    """What `/api/studio/state` publishes about inference. Probes both, names the fix."""
    out: dict = {"pinned": os.environ.get("SYMONEURAL_STUDIO_LLM") or None, "backends": {}}
    active = None
    for name, b in backends().items():
        up = await b.up()
        row: dict = {"url": b.base, "up": up}
        if up:
            row["models"] = await b.models()
            if active is None:
                active = name
        elif name == "llamacpp":
            # Reads on the page, so it says what actually happens: this module never spawns
            # (see the header), and `agent.run` yields `no_backend` rather than starting one.
            row["detail"] = ("llama-server is started on demand by the chat surface, not by "
                             "this one: send a message to /api/chat to warm it. An agent turn "
                             "while it is down answers no_backend instead of starting it")
        elif name == "ollama":
            row["detail"] = ("not installed on this host. `curl -fsSL "
                             "https://ollama.com/install.sh | sh` then "
                             "`ollama pull qwen2.5:7b-instruct`")
        out["backends"][name] = row

    pinned = (os.environ.get("SYMONEURAL_STUDIO_LLM") or "").strip().lower()
    if pinned and pinned in out["backends"]:
        out["active"] = pinned if out["backends"][pinned]["up"] else None
        if out["active"] is None:
            out["detail"] = f"SYMONEURAL_STUDIO_LLM pins '{pinned}' and it is not answering"
    else:
        out["active"] = active
        if active is None:
            out["detail"] = "no local inference backend is answering"
    return out
