# `tests/component/dispatchos/` — what the dispatchos surface must do

Run: `python3 -m pytest tests/component/dispatchos -q`

| file |  |
|---|---|
| `test_dispatchos.py` | DispatchOS: the lifecycle, the two tiers, the quote engine, and what SyMon AI refuses. |
| `test_dispatchos_security.py` | Security regression tests for the DispatchOS store and login boundary. |
| `test_route_authorization.py` | A-3 route authorization: the 15 classes, the four fail-closed conditions, T1-T22. |

## Two things that bite here

These moved out of `backend/` on 2026-09-11. **`from . import X` has no package to be
relative to** — import the component by name: `from dispatchos import dispatchos`. And **`HERE`
and `ROOT` are the repository root**, not this directory; the root `conftest.py` puts
`backend/` on the path, in exactly one place.

## What a test here has to do

Exercise the surface, not the file. A test that reads source and asserts a string is a
grep with a test's authority — #94 archived on eighteen such checks over a surface that
was dead on arrival.

Prove the behaviour changed: break it on purpose, watch this fail, then fix it. A test
that passes before and after your change tested nothing.

See [`../README.md`](../README.md) for the convention and
[`../../../backend/dispatchos/README.md`](../../../backend/dispatchos/README.md) for what
`dispatchos` is.
