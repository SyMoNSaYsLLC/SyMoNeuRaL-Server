# `tests/component/remix/` — what the remix surface must do

Run: `python3 -m pytest tests/component/remix -q`

| file |  |
|---|---|
| `conftest.py` | Make `symoneural_dj` importable however pytest was invoked. |
| `conftest_tests.py` | Shared fixtures. House convention (from symon_llm): CPU-only, no network, |
| `test_connectors.py` | The DJ is not a Spotify client, and these are the tests that keep it that way. |
| `test_matching.py` | Fuzzy artist accept/reject — the gate between symon's suggestions and |
| `test_routes.py` | Routes and the auth middleware, through fastapi's in-process TestClient |

## Two things that bite here

These moved out of `backend/` on 2026-09-11. **`from . import X` has no package to be
relative to** — import the component by name: `from remix import remix`. And **`HERE`
and `ROOT` are the repository root**, not this directory; the root `conftest.py` puts
`backend/` on the path, in exactly one place.

## What a test here has to do

Exercise the surface, not the file. A test that reads source and asserts a string is a
grep with a test's authority — #94 archived on eighteen such checks over a surface that
was dead on arrival.

Prove the behaviour changed: break it on purpose, watch this fail, then fix it. A test
that passes before and after your change tested nothing.

See [`../README.md`](../README.md) for the convention and
[`../../../backend/remix/README.md`](../../../backend/remix/README.md) for what
`remix` is.
