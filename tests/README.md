# tests/

```bash
python3 -m pytest tests -q                              # everything. ~4 minutes
python3 -m pytest tests/component/chat -q               # one component
python3 -m pytest tests/structure -q                    # the rules about the tree
python3 -m pytest tests -q --continue-on-collection-errors   # do not stop at the first broken import
python3 -m pytest tests -q -x --ff                      # stop at the first failure, failures first
python3 -m pytest tests -q -k "governor or lease"       # by name
```

`--continue-on-collection-errors` matters right now: a module that will not import stops the
whole run without it, and there are still some.

## The state, measured — not asserted

**Read this before trusting a green run on one directory.** Measured 2026-09-11 at
`026f289`, on the command above:

```
840 failed, 1207 passed, 43 skipped, 77 errors in 240s
```

| bucket | files | result |
|---|---|---|
| `component/` | 75 | the bulk of both the passes and the failures |
| `structure/` | 12 | 48 failed, 49 passed, 4 skipped, 1 error |
| `ops/` | 15 | 111 failed, 145 passed, 9 skipped |
| `site/` | 9 | 47 failed, 19 passed, 3 errors |
| `clients/` | 4 | 128 failed, 3 passed, 4 skipped, 38 errors |
| `models/` | 2 | 21 passed, 8 failed, 1 skipped |
| `misc/` | 7 | 27 passed, 11 failed, 2 errors |

**The suite is not green and has not been since the restructure.** Saying so here is the
point: a README that described the intent while the run was red would be the thing this
repository warns about most.

## Why it is red, in order of how many

The failures are **overwhelmingly tests describing the tree as it was**, not defects in the
code. Four classes, and each is mechanically fixable:

1. **Moved paths.** `site/` became `frontend/site/{pages,css,js,assets}`, `backend/apps/`
   was flattened into per-component directories, `ops/symoneural-*.service` moved into
   `ops/units/`, and every tool moved one level deeper. 185 references already repointed;
   about 20 `FileNotFoundError`s remain.
2. **Symbols that moved.** `server._delegated_rows`, `server.record_engine` — the module a
   test reaches into is not the module that holds the thing any more.
3. **A contract deliberately removed.** Tests asserting `OPERATOR_HEADER`,
   `_operator_token`, `present_token` and `token_ok` still exist are testing a gate that was
   removed on purpose and will not come back. These need deleting, not fixing — but
   deliberately, one at a time, because `test_no_tokens.py` is the replacement and it must
   keep its teeth.
4. **Relative imports.** The tests left `backend/` on 2026-09-11, so `from . import X` has
   no package to be relative to.

## What each bucket is about

```
component/   one directory per backend component. Mirrors backend/.
structure/   rules about the tree: no tokens, no fragile paths, no vendored SDKs
ops/         scripts, units, deploys, generators, model staging. Runs the real thing
site/        the pages, the CSS, the API reference
models/      weight names, provenance, the fetch script's promote-after-verify order
clients/     the CLI and the desktop client
misc/        genuinely cross-cutting. If something lands here twice it wants a home
```

## The one arrangement everything depends on

`conftest.py` at the **repository root** puts `backend/` on `sys.path`. That is not a test
convenience — the service runs as `python3 backend/server.py`, and Python puts a script's own
directory at `sys.path[0]`, so `from hardware.lib import gpu` means what it says only under
that arrangement. There is exactly one place that knows it.

Two consequences after the tests moved out of `backend/`:

- **`from . import X` has no package.** Import the component by name: `from chat import chat`.
- **`HERE` and `ROOT` are the repository root**, not the test's directory. Several files
  carried `sys.path.insert(0, str(HERE.parent))`, which pointed one level *above* the
  repository.

## What a test here has to do

**Prove the behaviour changed.** Break it on purpose, watch the test fail, then fix it. A
test that passes before and after your change tested nothing.

**`exists`, `grep` and `ngrep` cannot ask whether a thing works.** They ask what is written
on disk. #94 shipped a desktop client whose eighteen declared checks were all green and whose
chat surface was dead on arrival — a missing capability meant the page was never permitted to
hear the stream it had asked for, so it rendered one turn and then nothing, with no error to
read. The task archived itself two minutes later.

If the deliverable runs, one check must be something only a real run can turn green. A
stamped record in `ops/smoke/` is the cheap one: that file cannot be written honestly without
running the thing.

Three of today's defects prove the same point from the other side — `guide_ask_model`,
`_llama_lock` and `_llama` were all invisible to `import server`, which builds the app,
counts 160 routes, and **runs no lifespan at all**. They were found by starting the service.

## `structure/` is the tree's own conscience

Each exists after a specific failure:

| test | what it cost |
|---|---|
| `test_no_tokens.py` | passed for days while walking `backend/apps/`, a directory that had stopped existing, over a tree where five surfaces still refused callers |
| `test_path_fragility.py` | its first version opened with `parents[2]`, the exact construct it counts, and caught its own author |
| `test_readmes_are_tracked.py` | three READMEs were on disk and not in git, swallowed by an ignore rule a directory above |
| `test_repository_map.py` | the root README reached 32 rows against 26 directories, six of which had none |

**A guard must be able to fail.** Before trusting a green one, check it looked at something:
`test_no_tokens.py` now asserts its walk found source files before believing an empty result.
A guard that exempts itself is the first step to a guard that exempts everything.

## When a whole file errors on collection

That is an import, not a failure — a module moved, a name was renamed, a path points at
something gone. **Fix the import; never skip the file.** A skipped file is a suite reporting
green over code nobody ran.
