"""SyMon AI for DispatchOS -- the managed assistant layer, and what it refuses to do.

Task #106. Garrett: *"make sure to integrate my AI models into his application"*.

The customer preview sets the positioning and it is worth keeping honest, because it is a
claim a customer has read:

    "SyMon AI is not a generic chatbot pasted onto a website. For DispatchOS, it is
    positioned as a managed SyMoNeuRaL assistant tied to the transportation workflow:
    bookings, quote logic, dispatch steps, reminders, and review requests."

So this module does exactly one thing: it takes the operator's *own* live booking state,
puts it in front of the local model as context, and asks a question about it. That is the
whole difference between "a managed assistant" and "a chat window" -- the assistant is
looking at the jobs on the board.

## IT NEVER STARTS THE MODEL, and this is the load-bearing rule

`guide_ask_model` in `backend/server.py` is the template and its docstring states the reason:

    "It never starts the model. If chat is not already resident this raises, and Guide
    falls back to its local pass and says so. Starting a 7B to answer [a small question]
    would evict whatever holds the card -- possibly an image render somebody is waiting
    on."

The card is 15.92 GiB and the chat and image weight sets do not both fit, so a lock hands
the GPU to one surface at a time. A booking page that evicted a running render to answer a
rider would be the wrong trade, and on presentation day it would be the wrong trade in
front of a customer. `ask()` therefore raises `ModelUnusable` when the model is not already
resident, and every caller degrades to a deterministic local answer that says out loud that
the model was not consulted.

## Error hygiene: the underlying message never reaches the surface

Also copied from `guide_ask_model`, which deliberately re-raises with only an exception
class name because the real message "can quote a socket path or an internal address". This
surface faces a paying customer rather than a visitor, so that matters more here, not less.

## The injection seam

`backend/server.py` calls `set_ask_model(fn)` at import time with a `str -> str` callable, the
same shape `apps/streamer/guide` and `apps/project` already use. This package never imports
the API, never opens a socket and never touches `scripts/gpu-governor.sh`. That is what
makes it testable without a GPU: the test injects a stub.
"""
from __future__ import annotations

import logging
from typing import Callable

log = logging.getLogger("symoneural.dispatchos.ai")

#: The `str -> str` callable into the chat surface, injected by backend/server.py. None means
#: nobody wired it up, which is a different failure from "the model is not resident" and is
#: reported differently.
_ASK: Callable[[str], str] | None = None


class ModelUnusable(Exception):
    """The local model could not answer. Never carries an internal message."""


def set_ask_model(fn: Callable[[str], str] | None) -> None:
    global _ASK
    _ASK = fn


def available() -> bool:
    return _ASK is not None


#: Kept deliberately small. The context is a summary of the board, not a dump of the
#: database: a prompt that grows with the number of bookings is one that silently starts
#: costing seconds and then failing, and it would put every rider's contact details into
#: the model's context to answer a question about one job.
MAX_JOBS_IN_CONTEXT = 12


def board_context(bookings: list[dict], counts: dict[str, int]) -> str:
    """Summarise the board for the model. Contact details are NOT included.

    A rider's phone number cannot help answer an operational question, and putting it in a
    prompt is how it ends up in a log. Names are included because "who is the airport run
    for" is a real dispatch question; contact fields are not.
    """
    lines = [
        "You are SyMon AI, the assistant inside DispatchOS, a transport dispatch system.",
        "Answer only from the job board below. If the board does not contain the answer, "
        "say so plainly rather than guessing.",
        "",
        "Board totals: " + ", ".join(f"{k}={v}" for k, v in counts.items() if v),
        "",
    ]
    for b in bookings[:MAX_JOBS_IN_CONTEXT]:
        q = b.get("quote") or {}
        lines.append(
            f"- {b.get('ref')} [{b.get('state')}] {b.get('pickup','?')} -> "
            f"{b.get('dropoff','?')} | when: {b.get('when_text') or 'unspecified'} | "
            f"pax {b.get('passengers')} bags {b.get('luggage')} | "
            f"rider: {b.get('rider') or 'unnamed'} | "
            f"quote: {q.get('display', '——')}")
    if len(bookings) > MAX_JOBS_IN_CONTEXT:
        lines.append(f"({len(bookings) - MAX_JOBS_IN_CONTEXT} further jobs not listed)")
    return "\n".join(lines)


def ask(question: str, bookings: list[dict], counts: dict[str, int]) -> dict:
    """Ask SyMon AI about the board.

    Returns `{"answer": str, "model": True}` on a real answer. Raises `ModelUnusable` if the
    model is not wired up or not already resident -- the caller is expected to catch it and
    degrade, not to retry.
    """
    question = (question or "").strip()
    if not question:
        raise ModelUnusable("no question was asked")
    if len(question) > 600:
        # A bound the UI also enforces. Stated here because the UI is not the limit.
        question = question[:600]
    if _ASK is None:
        raise ModelUnusable("the assistant is not connected on this box")

    prompt = (board_context(bookings, counts)
              + "\n\nOperator question: " + question
              + "\n\nAnswer in at most three sentences.")
    try:
        out = _ASK(prompt)
    except Exception as exc:                       # noqa: BLE001
        # Only the class name. The real message can name a socket path or an internal
        # address, and this answer is rendered on a customer-facing page.
        log.info("dispatchos ai unavailable: %s", type(exc).__name__)
        raise ModelUnusable(f"the assistant is not available right now "
                            f"({type(exc).__name__})") from None
    answer = (out or "").strip()
    if not answer:
        raise ModelUnusable("the assistant returned nothing")
    return {"answer": answer, "model": True}


def local_answer(question: str, bookings: list[dict], counts: dict[str, int]) -> dict:
    """The deterministic fallback, and it says it is one.

    This is not a pretend model. It answers the two questions the board can answer by
    counting, and otherwise says it cannot -- which is the honest behaviour when the card is
    busy. `model: False` is carried all the way to the UI so the page can label it, because
    an answer that looks like the assistant but was not is the decorative-indicator failure
    this project already has a rule about.
    """
    q = (question or "").lower()
    if any(w in q for w in ("how many", "count", "total")):
        live = ", ".join(f"{v} {k}" for k, v in counts.items() if v) or "no jobs yet"
        return {"answer": f"On the board right now: {live}.", "model": False}
    nxt = [b for b in bookings if b.get("state") in ("confirmed", "dispatched")]
    if nxt and any(w in q for w in ("next", "now", "current", "today", "who")):
        b = nxt[0]
        return {"answer": (f"The live job is {b['ref']}: {b.get('pickup')} to "
                           f"{b.get('dropoff')}, {b.get('when_text') or 'time unspecified'}."),
                "model": False}
    return {"answer": ("The assistant is not available right now, so this answer was "
                       "produced without it. The board is shown in full above."),
            "model": False}
