# `tests/component/chat/` — what the chat surface must do

Run: `python3 -m pytest tests/component/chat -q`

| file |  |
|---|---|
| `test_chat_lease.py` | The GPU lease comes back when the visitor closes the tab -- and the gate that broke it. |
| `test_chat_model_identity.py` | The chat surface must not claim a persona adapter it is not running. |

## Two things that bite here

These moved out of `backend/` on 2026-09-11. **`from . import X` has no package to be
relative to** — import the component by name: `from chat import chat`. And **`HERE`
and `ROOT` are the repository root**, not this directory; the root `conftest.py` puts
`backend/` on the path, in exactly one place.

## What a test here has to do

Exercise the surface, not the file. A test that reads source and asserts a string is a
grep with a test's authority — #94 archived on eighteen such checks over a surface that
was dead on arrival.

Prove the behaviour changed: break it on purpose, watch this fail, then fix it. A test
that passes before and after your change tested nothing.

See [`../README.md`](../README.md) for the convention and
[`../../../backend/chat/README.md`](../../../backend/chat/README.md) for what
`chat` is.
