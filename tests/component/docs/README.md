# `tests/component/docs/` — what the docs surface must do

Run: `python3 -m pytest tests/component/docs -q`

| file |  |
|---|---|
| `test_application_docs.py` | Per-application documentation: ownership is a partition, and leakage is impossible. |
| `test_application_shell.py` | Structural guards for the shared browser-application shell. |
| `test_manual_slices.py` | The playbook slices must stay derivable from the manual. |

## Two things that bite here

These moved out of `backend/` on 2026-09-11. **`from . import X` has no package to be
relative to** — import the component by name: `from docs import docs`. And **`HERE`
and `ROOT` are the repository root**, not this directory; the root `conftest.py` puts
`backend/` on the path, in exactly one place.

## What a test here has to do

Exercise the surface, not the file. A test that reads source and asserts a string is a
grep with a test's authority — #94 archived on eighteen such checks over a surface that
was dead on arrival.

Prove the behaviour changed: break it on purpose, watch this fail, then fix it. A test
that passes before and after your change tested nothing.

See [`../README.md`](../README.md) for the convention and
[`../../../backend/docs/README.md`](../../../backend/docs/README.md) for what
`docs` is.
