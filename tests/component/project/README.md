# `tests/component/project/` — what the project surface must do

Run: `python3 -m pytest tests/component/project -q`

| file |  |
|---|---|
| `test_project.py` | Tests for SyMoNeuRaL Project. System interpreter, stdlib unittest, no network, no GPU. |
| `test_projectstatus_checkpoint.py` | `ProjectStatus.md` claims a HEAD. Check that the claim is still true. |

## Two things that bite here

These moved out of `backend/` on 2026-09-11. **`from . import X` has no package to be
relative to** — import the component by name: `from project import project`. And **`HERE`
and `ROOT` are the repository root**, not this directory; the root `conftest.py` puts
`backend/` on the path, in exactly one place.

## What a test here has to do

Exercise the surface, not the file. A test that reads source and asserts a string is a
grep with a test's authority — #94 archived on eighteen such checks over a surface that
was dead on arrival.

Prove the behaviour changed: break it on purpose, watch this fail, then fix it. A test
that passes before and after your change tested nothing.

See [`../README.md`](../README.md) for the convention and
[`../../../backend/project/README.md`](../../../backend/project/README.md) for what
`project` is.
