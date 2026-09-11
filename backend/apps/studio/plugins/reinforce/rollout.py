"""SyMoNeuRaL Reinforce -- where a reinforcement run's completions come from.

The reinforcement method has to **generate before it can learn**: sample `num_generations`
completions for a prompt, score them, take the gradient. Nothing else in this package generates
anything, so this is the one genuinely new piece of machinery the RL path needs, and *what does
the sampling* is most of its performance story.

Three backends were considered. The answers differ, and two of them are refusals with reasons
rather than work not yet done.

## `transformers` -- the default, and the only one that works on this box today

The model being trained generates its own completions in-process, with the adapter live. That
makes it **on-policy by construction**, which is not a detail: a policy-gradient step is only
valid for the policy that drew the samples. It is also the slow option -- one sequence at a time
through a training-shaped forward pass, no continuous batching, no paged attention.

Slow and correct is the right default here. `use_cache=True` is set for this method precisely so
the sampling phase is not quadratic in the prefix.

## vLLM -- supported as an external server, refused as a co-tenant

Two modes exist in trl and they are very different propositions on one card:

* **colocate** -- vLLM runs inside this process and shares the GPU. **Refused, by arithmetic.**
  It needs a second full copy of the weights plus a pre-allocated KV block pool sized by
  `vllm_gpu_memory_utilization`, and the training process alone already projects near 12 GiB of
  a ~14.2 GiB practical budget. There is no value of that fraction which leaves both alive.
* **server** -- vLLM runs somewhere else and is called over HTTP. **Supported**, because this is
  genuinely how RL at scale is done: a rollout fleet generating while the trainer takes steps.
  It needs a machine that is not this one.

So the vLLM path here is configuration plus a reachability probe, and **never a silent
fallback**. If a preset asks for vLLM and the endpoint does not answer, preflight refuses and
says which URL it tried. Quietly generating in-process instead would change the sampling
implementation, the throughput and the numerical details of the run without changing the label
on it -- and the operator would draw conclusions about a run that did not happen.

vLLM is **not installed on this box**, and that is stated rather than hidden: nothing here
imports it, and the probe is plain `urllib` against an HTTP endpoint, so this module keeps
working on the serving interpreter with no torch and no vLLM anywhere near it.

## llama.cpp -- deliberately not a rollout backend

This is the one that looks like it should work, because `llama-server` is already built here,
already serving chat, and already fast. It is refused on **correctness**, not effort:

1. **It cannot carry the adapter being trained.** `llama-server` holds a Q4_K_M GGUF of the
   *base* model. The adapter under training exists as fp32 PEFT tensors in another process and
   changes every optimiser step. llama.cpp can load a GGUF LoRA, but converting and hot-reloading
   one per step is not a thing that happens, so every completion would come from a *different
   model* than the one taking the gradient -- off-policy from step 1, and silently.
2. **The logprobs would be the wrong model's.** GRPO's importance-sampling correction needs the
   sampling policy's log-probabilities. llama.cpp can return logprobs; they would belong to the
   Q4 base. Feeding those in as though they were the policy's is not an approximation, it is a
   different algorithm with no name.
3. **It cannot co-reside anyway.** `train` holds the governor lock and is never evicted, and
   4.36 GiB of GGUF beside a ~12 GiB training process does not fit on a 15.92 GiB card.

**What llama.cpp does contribute is real and unchanged**: it *serves* a GGUF LoRA. That is the
other end of this pipeline -- the promotion step -- and it is why the trainer's PEFT output has
to be converted before the chat surface can run it. `routes.py` documents why that conversion
stays a deliberate manual act.

The general shape of the argument is worth keeping: a fast generator that is not the policy is
not a rollout engine. It is a different model's opinion.
"""
from __future__ import annotations

import os
import urllib.error
import urllib.request

from .registry import ROOT

# Our LLM engine. Detected only so this module can state, accurately, that it exists and is
# still not used for rollouts. Nothing here executes it.
LLM_ENGINE = ROOT / "symoneural-llm" / "build" / "bin" / "symoneural-llm"

BACKENDS = {
    "transformers": {
        "id": "transformers",
        "label": "transformers (in-process)",
        "on_policy": True,
        "available": True,
        "why": ("the model being trained generates its own completions with the adapter live, so "
                "the samples belong to the policy taking the gradient. On-policy by "
                "construction, and slow -- no continuous batching and no paged attention"),
        "cost": "no extra weights and no second process; the sampling happens inside the run",
    },
    "vllm": {
        "id": "vllm",
        "label": "vLLM (server mode, external host)",
        "on_policy": False,
        "available": False,          # resolved at runtime by `probe()`
        "why": ("how reinforcement learning is done at scale: a rollout server generates while "
                "the trainer steps. Server mode only -- colocate is refused by arithmetic, "
                "because vLLM wants a second copy of the weights plus a pre-allocated KV pool "
                "and the training process already projects near 12 GiB of a 14.2 GiB budget"),
        "cost": ("a machine that is not this one. vLLM is not installed here and nothing in this "
                 "package imports it; the probe is plain HTTP"),
    },
    "llama.cpp": {
        "id": "llama.cpp",
        "label": "llama.cpp (refused for rollouts)",
        "on_policy": False,
        "available": False,
        "why": ("REFUSED, on correctness rather than effort. llama-server holds a Q4_K_M GGUF of "
                "the BASE model and cannot carry the adapter being trained, so its completions "
                "and their logprobs would belong to a different model than the one taking the "
                "gradient -- off-policy from step 1, and silently. It also cannot co-reside: "
                "`train` holds the governor lock and never yields"),
        "cost": ("not offered at any price. llama.cpp's real job here is the other end of the "
                 "pipeline -- it SERVES a GGUF LoRA, which is what makes an adapter promotable"),
    },
}

# Where an external rollout server is configured. An environment variable rather than a request
# field: an operator-supplied URL arriving in a POST body is a request that makes this process
# open a socket to an address of the caller's choosing, which is the shape of a server-side
# request forgery. The box's owner sets this, or there is no vLLM rollout.
URL_ENV = "SYMONEURAL_REINFORCE_VLLM_URL"

_TIMEOUT_S = 2.0


def vllm_base_url() -> str:
    """The configured external rollout endpoint, or empty.

    Only `http://` and `https://` are accepted. A `file://` or `unix://` spelling in an
    environment variable is not a URL this package will hand to anything.
    """
    url = (os.environ.get(URL_ENV) or "").strip().rstrip("/")
    if not url.startswith(("http://", "https://")):
        return ""
    return url


def probe(url: str = "") -> dict:
    """Is the configured rollout server answering? A real reading, or an honest failure.

    Called from preflight, so a run that asks for vLLM either has a reachable endpoint or is
    refused before the card is taken. The alternative -- discovering it at step 0, after a
    governor acquire that can block for up to 300 seconds while another surface's weights drain
    -- is the failure mode this whole preflight exists to prevent.

    Never raises. A probe that throws would take out the `/presets` read that calls it.
    """
    url = url or vllm_base_url()
    if not url:
        return {"configured": False, "reachable": False, "url": None,
                "detail": (f"no external rollout server configured. Set {URL_ENV} to the base "
                           f"URL of a vLLM server on another machine. vLLM is not installed on "
                           f"this box and colocate mode does not fit beside a 4-bit 7B here."),
                "label": "measured"}
    # `trl vllm-serve` exposes /health/; a stock vLLM OpenAI server exposes /health. Both are
    # tried, and the first to answer wins.
    for path in ("/health/", "/health"):
        try:
            req = urllib.request.Request(url + path, method="GET")
            with urllib.request.urlopen(req, timeout=_TIMEOUT_S) as resp:
                if 200 <= resp.status < 300:
                    return {"configured": True, "reachable": True, "url": url,
                            "detail": f"answered {resp.status} at {path}", "label": "measured"}
        except (urllib.error.URLError, OSError, ValueError):
            continue
    return {"configured": True, "reachable": False, "url": url,
            "detail": ("configured but not answering. A reinforcement run set to the vLLM "
                       "rollout is refused rather than quietly generating in-process -- a "
                       "silent fallback would change the sampling implementation without "
                       "changing the label on the run."),
            "label": "measured"}


def describe() -> dict:
    """The published backend table, with vLLM's availability resolved by a real probe."""
    state = probe()
    rows = []
    for spec in BACKENDS.values():
        row = dict(spec)
        if row["id"] == "vllm":
            row["available"] = bool(state["reachable"])
            row["detail"] = state["detail"]
        rows.append(row)
    return {
        "backends": rows,
        "default": "transformers",
        "vllm": state,
        "llm_engine_present": LLM_ENGINE.is_file(),
        "llm_engine_note": ("present on this box and still not used for rollouts -- it serves "
                              "a GGUF of the base model and cannot carry the adapter being "
                              "trained. A fast generator that is not the policy is not a rollout "
                              "engine, it is a different model's opinion."),
        "note": ("only the reinforcement method generates anything. The supervised and preference "
                 "methods train on text they were given and have no rollout at all."),
    }


def check(backend: str) -> dict:
    """Can a run use this backend right now? `{ok, reason, message}`.

    `reason="capability"` is the same vocabulary `preflight` uses for a configuration this box
    cannot run, and it surfaces as 501 rather than 500 for the same reason: "cannot here" is not
    "broken".
    """
    if backend not in BACKENDS:
        return {"ok": False, "reason": "unknown_rollout",
                "message": f"No such rollout backend. Available: {', '.join(BACKENDS)}."}
    if backend == "transformers":
        return {"ok": True, "reason": "", "message": ""}
    if backend == "llama.cpp":
        return {"ok": False, "reason": "capability", "message": BACKENDS["llama.cpp"]["why"]}
    state = probe()
    if not state["reachable"]:
        return {"ok": False, "reason": "capability",
                "message": (f"the vLLM rollout backend is not usable: {state['detail']} "
                            f"This run is refused rather than silently generating in-process.")}
    return {"ok": True, "reason": "", "message": "", "url": state["url"]}


__all__ = ["BACKENDS", "URL_ENV", "vllm_base_url", "probe", "describe", "check", "LLM_ENGINE"]
