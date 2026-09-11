# `tests/component/hardware/` — what the hardware surface must do

Run: `python3 -m pytest tests/component/hardware -q`

| file |  |
|---|---|
| `test_drain_fails_closed.py` | If the Python side cannot run, the governor must NOT report a drained card. |
| `test_governor_drain.py` | What `gpu-governor.sh drain` measures, exercised by running the real script. |
| `test_governor_evict.py` | What `gpu-governor.sh evict` and `status` say about a surface that is not running. |
| `test_governor_paths.py` | Every path `scripts/gpu-governor.sh` names must exist, and its kills must name our engines. |
| `test_governor_same_surface.py` | Acquiring the surface that is already resident must still evict, when a NEW engine is coming. |
| `test_gpu_driver_health.py` | `/api/status` must not claim GPU health it does not have. |
| `test_probes.py` | The two probe tools read their targets out of things that move. This pins that. |

## Two things that bite here

These moved out of `backend/` on 2026-09-11. **`from . import X` has no package to be
relative to** — import the component by name: `from hardware import hardware`. And **`HERE`
and `ROOT` are the repository root**, not this directory; the root `conftest.py` puts
`backend/` on the path, in exactly one place.

## What a test here has to do

Exercise the surface, not the file. A test that reads source and asserts a string is a
grep with a test's authority — #94 archived on eighteen such checks over a surface that
was dead on arrival.

Prove the behaviour changed: break it on purpose, watch this fail, then fix it. A test
that passes before and after your change tested nothing.

See [`../README.md`](../README.md) for the convention and
[`../../../backend/hardware/README.md`](../../../backend/hardware/README.md) for what
`hardware` is.
