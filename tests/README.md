# tests/ — by what they are about

```
component/   one directory per backend component. 75 files.
structure/   rules about the tree: no tokens, no fragile paths, no vendored SDKs. 11
ops/         scripts, units, deploys, generators, model staging. 15
site/        the pages, the CSS, the API reference, the smoke runners. 9
models/      weight names, provenance, the fetch script's promote-after-verify. 2
clients/     the CLI and the desktop client. 4
misc/        genuinely cross-cutting; if something lands here twice it wants a home. 7
```

## Running them

```bash
python3 -m pytest tests -q                       # everything
python3 -m pytest tests/component/chat -q        # one component
python3 -m pytest tests/structure -q             # the rules about the tree
```

`conftest.py` at the **repository root** puts `backend/` on `sys.path`, reproducing the one
arrangement under which `from hardware.lib import gpu` means what it says — the service runs
as `python3 backend/server.py`, and Python puts a script's directory at `sys.path[0]`. There
is exactly one place that knows this.

The tests left `backend/` on 2026-09-11. A `from . import X` in here has no package to be
relative to, and `HERE`/`ROOT` in a test file is the **repository** root, not the test's
directory — several `sys.path.insert(str(HERE.parent))` lines were pointing one level above
the repository after that move.

## What a test here has to do

**Prove the behaviour changed.** Break it on purpose, watch the test fail, then fix it. A
test that passes before and after your change tested nothing, and this repository has
archived a task on eighteen checks that were all green over a surface that was dead on
arrival.

`exists`, `grep` and `ngrep` ask what is written on disk. **None of them can ask whether the
thing works.** If the deliverable runs, one check must be something only a real run can turn
green — a stamped smoke record in `ops/smoke/` is the cheap one, because that file cannot be
written honestly without running the thing.

## structure/ is the tree's own conscience

These are the ones to read first, because each exists after a specific failure:

| test | the rule, and what broke |
|---|---|
| `test_no_tokens.py` | no inbound gate anywhere. It passed for days while walking `backend/apps/`, a directory that had stopped existing — the baseline now asserts the walk found files before believing an empty result |
| `test_path_fragility.py` | no parent-counting root anchors. Its first version opened with the exact construct it was written to count, and the ratchet caught its own author |
| `test_one_route_to_each_module.py` | every route reachable, each module mounted once |
| `test_credential_header.py` | no credential header is ever sent by our own client |
| `test_no_external_source_dependency.py` | nothing imports out of the tree |
| `test_repository_map.py` | the README describes every folder that exists |

A guard that exempts itself is the first step to a guard that exempts everything.

## When a whole file errors on collection

That is an import, not a failure — a module moved, a name was renamed, or a path points at
something gone. Fix the import; do not skip the file. A skipped file is a suite that reports
green over code nobody ran.
