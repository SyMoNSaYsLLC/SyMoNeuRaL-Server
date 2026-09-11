# tests/component/ — one directory per backend component

75 files, named for what they test. A directory here mirrors a directory in `backend/`.

```bash
python3 -m pytest tests/component/chat -q
python3 -m pytest tests/component -q
```

## Importing the component under test

The tests moved out of `backend/` on 2026-09-11. Two things changed and both bite:

- **`from . import X` has no package to be relative to.** Import the component by name:
  `from chat import chat`, `from voice.lib import asr`.
- **`HERE` and `ROOT` are the repository root**, not the test's directory. Several files
  carried `sys.path.insert(0, str(HERE.parent))`, which after the move pointed one level
  *above* the repository. They are gone: the root `conftest.py` puts `backend/` on the path,
  in exactly one place.

The router module is named for its component — `chat/chat.py`, not `chat/router.py` — so
`from X import routes` is stale wherever it survives.

## What a component test must do

Exercise the surface, not the file. A test that reads source and asserts a string is a
grep with a test's authority, and this repository has archived a task on eighteen such
checks over a surface that was dead on arrival.

Use `fastapi.testclient.TestClient` against the component's own router. If the behaviour
needs the GPU, it needs a smoke record in `ops/smoke/` instead — that file cannot be written
honestly without running the thing.
