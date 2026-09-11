# `tests/component/exp/` — what the exp surface must do

Run: `python3 -m pytest tests/component/exp -q`

| file |  |
|---|---|
| `test_exp.py` | Exp tests. Standard library and `unittest` only -- no network, no GPU, no fixtures. |

## Two things that bite here

These moved out of `backend/` on 2026-09-11. **`from . import X` has no package to be
relative to** — import the component by name: `from exp import exp`. And **`HERE`
and `ROOT` are the repository root**, not this directory; the root `conftest.py` puts
`backend/` on the path, in exactly one place.

## What a test here has to do

Exercise the surface, not the file. A test that reads source and asserts a string is a
grep with a test's authority — #94 archived on eighteen such checks over a surface that
was dead on arrival.

Prove the behaviour changed: break it on purpose, watch this fail, then fix it. A test
that passes before and after your change tested nothing.

See [`../README.md`](../README.md) for the convention and
[`../../../backend/exp/README.md`](../../../backend/exp/README.md) for what
`exp` is.
