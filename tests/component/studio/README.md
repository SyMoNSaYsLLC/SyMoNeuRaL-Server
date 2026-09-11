# `tests/component/studio/` — what the studio surface must do

Run: `python3 -m pytest tests/component/studio -q`

| file |  |
|---|---|
| `test_agent.py` | `agent.run()` -- the loop that decides whether a dangerous tool executes. |
| `test_cleanroom.py` | The spec-mediated reimplementation pipeline, and the honesty claims it makes. |
| `test_comfy_port.py` | The Python bridge and the shell that starts the server must agree on where ComfyUI is. |
| `test_plugin_contract.py` | The plugin contract in `apps/studio/plugins/__init__.py`, asserted against the disk. |
| `test_reinforce_registry_provenance.py` | The Reinforce catalogue must connect a house name to its upstream, and must not be silent |
| `test_status_probe.py` | status()'s ComfyUI arm: the Studio row may not read `ready` unless the bench answers. |
| `test_studio.py` | Studio tests. Standard library and `unittest` only -- no network, no GPU, no fixtures. |
| `test_studio_models.py` | `GET /api/studio/models` -- the route, its validator, and the file behind it. |

## Two things that bite here

These moved out of `backend/` on 2026-09-11. **`from . import X` has no package to be
relative to** — import the component by name: `from studio import studio`. And **`HERE`
and `ROOT` are the repository root**, not this directory; the root `conftest.py` puts
`backend/` on the path, in exactly one place.

## What a test here has to do

Exercise the surface, not the file. A test that reads source and asserts a string is a
grep with a test's authority — #94 archived on eighteen such checks over a surface that
was dead on arrival.

Prove the behaviour changed: break it on purpose, watch this fail, then fix it. A test
that passes before and after your change tested nothing.

See [`../README.md`](../README.md) for the convention and
[`../../../backend/studio/README.md`](../../../backend/studio/README.md) for what
`studio` is.
