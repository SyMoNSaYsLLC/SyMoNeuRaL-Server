# `tests/component/gateway/` — what the gateway surface must do

Run: `python3 -m pytest tests/component/gateway -q`

| file |  |
|---|---|
| `test_gateway.py` | Tests for the Gateway. Stdlib `unittest`, and they run with the network unplugged. |
| `test_gateway_unit.py` | The gateway unit's ExecStart has to name the crate that is actually on disk. |
| `test_settlement.py` | Tests for on-chain settlement. Run: cd backend && python3 -m pytest apps/gateway -q |

## Two things that bite here

These moved out of `backend/` on 2026-09-11. **`from . import X` has no package to be
relative to** — import the component by name: `from gateway import gateway`. And **`HERE`
and `ROOT` are the repository root**, not this directory; the root `conftest.py` puts
`backend/` on the path, in exactly one place.

## What a test here has to do

Exercise the surface, not the file. A test that reads source and asserts a string is a
grep with a test's authority — #94 archived on eighteen such checks over a surface that
was dead on arrival.

Prove the behaviour changed: break it on purpose, watch this fail, then fix it. A test
that passes before and after your change tested nothing.

See [`../README.md`](../README.md) for the convention and
[`../../../backend/gateway/README.md`](../../../backend/gateway/README.md) for what
`gateway` is.
