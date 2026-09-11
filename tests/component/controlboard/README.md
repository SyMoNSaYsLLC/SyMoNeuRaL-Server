# `tests/component/controlboard/` — what the controlboard surface must do

Run: `python3 -m pytest tests/component/controlboard -q`

| file |  |
|---|---|
| `test_control_models.py` | control/models/ -- the operator model-control surface. |
| `test_control_plane_matrix.py` | The Control Plane Matrix, held to its own claims. |
| `test_rack_probes.py` | The rack's readiness probes, held to the disk they claim to describe. |
| `test_rackpower.py` | Tests for the per-unit power switch. |

## Two things that bite here

These moved out of `backend/` on 2026-09-11. **`from . import X` has no package to be
relative to** — import the component by name: `from controlboard import controlboard`. And **`HERE`
and `ROOT` are the repository root**, not this directory; the root `conftest.py` puts
`backend/` on the path, in exactly one place.

## What a test here has to do

Exercise the surface, not the file. A test that reads source and asserts a string is a
grep with a test's authority — #94 archived on eighteen such checks over a surface that
was dead on arrival.

Prove the behaviour changed: break it on purpose, watch this fail, then fix it. A test
that passes before and after your change tested nothing.

See [`../README.md`](../README.md) for the convention and
[`../../../backend/controlboard/README.md`](../../../backend/controlboard/README.md) for what
`controlboard` is.
