# `tests/component/runtime/` — what the runtime surface must do

Run: `python3 -m pytest tests/component/runtime -q`

| file |  |
|---|---|
| `test_rate_limits_are_real.py` | A published rate limit must be the enforced one. There were three answers before. |
| `test_runtime_boundary.py` | The runtime must not require /yocto. These tests fail if anything reintroduces it. |
| `test_runtime_names.py` | Every `runtime=` in the registry names something real, or is a declared logical label. |
| `test_runtimeconfig.py` | `runtimeconfig` decides what may change this process's environment. Test it like that. |
| `test_runtimes_registry.py` | `ops/RUNTIMES.tsv` must agree with the three things it points at, or it is a fourth copy. |
| `test_symoneuralenv.py` | Tests for the legacy env-var promotion. |

## Two things that bite here

These moved out of `backend/` on 2026-09-11. **`from . import X` has no package to be
relative to** — import the component by name: `from runtime import runtime`. And **`HERE`
and `ROOT` are the repository root**, not this directory; the root `conftest.py` puts
`backend/` on the path, in exactly one place.

## What a test here has to do

Exercise the surface, not the file. A test that reads source and asserts a string is a
grep with a test's authority — #94 archived on eighteen such checks over a surface that
was dead on arrival.

Prove the behaviour changed: break it on purpose, watch this fail, then fix it. A test
that passes before and after your change tested nothing.

See [`../README.md`](../README.md) for the convention and
[`../../../backend/runtime/README.md`](../../../backend/runtime/README.md) for what
`runtime` is.
