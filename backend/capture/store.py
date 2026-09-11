"""The append-only JSONL capture store.

One file per app per UTC day. Appends are serialised with `flock`, because the
callers are concurrent: `symoneural_dj` backgrounds every playlist as its own task
and two jobs finishing together would otherwise interleave inside one line.

A note on why the lock is here. A torn line is not a corrupt record, it is a corrupt
FILE: every reader of a JSONL store parses line by line, so one interleaved write costs
the two records that collided and every tool that later chokes on them.

This paragraph used to say the lock "is not optional" and that O_APPEND alone leaves a
write that only "usually" lands whole. **Measured 2026-08-20, and that overstated it on
this box.** With both `flock` calls removed, 8 concurrent processes appending 20 records
each produced 160 intact, parseable lines at 100 B, at 100 KB and at 4 MB per record.
Linux holds the inode lock across a buffered write to a regular file, so `O_APPEND` plus
a single `write()` is already atomic against other writers on ext4, at any size.

The lock stays, and the honest reason is portability rather than ext4: that guarantee is
the kernel's implementation, not POSIX, and it is specifically **not** true over NFS,
where `O_APPEND` is emulated client-side and concurrent appends genuinely do interleave.
`root` is a caller-supplied path -- `settings.capture_dir` -- so nothing here gets to
assume the filesystem underneath it. The lock is cheap and the failure it prevents is
silent.

What this means for testing: `test_capture.py`'s `ConcurrencyTests` asserts the outcome
and CANNOT fail when the lock is removed on this box. Its docstring says so rather than
letting its name imply a guard it does not provide. Do not "fix" that test by adding
workers; the measurement above is why it would not help.
"""
from __future__ import annotations

import fcntl
import json
import os
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator, Mapping, Sequence


class CaptureError(RuntimeError):
    """A capture could not be written. Callers are expected to swallow this.

    `symoneural_dj.pipeline` wraps its capture call in try/except and logs, which is
    the correct shape and the reason this is a plain RuntimeError subclass rather
    than anything a caller must special-case: banking a training pair must never
    change the result of the job the user actually asked for.
    """


def _utc_day() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


class CaptureStore:
    """Appends captured turns under `root`, one JSONL file per app per UTC day.

        store = CaptureStore(Path("~/distill").expanduser())
        rec_id = store.capture("dj", messages, verdict={...}, meta={...})

    `root` is created on first write, not in the constructor: constructing a store is
    something an app does at import/startup time, and a surface that merely *might*
    capture should not leave an empty directory tree behind on a box where the
    feature is never used.
    """

    def __init__(self, root: str | os.PathLike) -> None:
        self.root = Path(root)

    # -- writing ---------------------------------------------------------------------

    def capture(
        self,
        app: str,
        messages: Sequence[Mapping[str, Any]],
        verdict: Any = None,
        meta: Mapping[str, Any] | None = None,
    ) -> str:
        """Append one record and return its id.

        `app` names the surface ("dj"). `messages` is an OpenAI-shaped chat turn list.
        `verdict` is how well the turn actually went -- for a playlist, how many of the
        suggested tracks resolved -- and is what makes the store filterable later
        rather than merely large. `meta` is caller context (job id, user).

        Positional order matches the existing call site in `symoneural_dj.pipeline`,
        which passes verdict and meta positionally.
        """
        app_name = self._safe_app(app)
        record = {
            "id": uuid.uuid4().hex,
            "ts": time.time(),
            "app": app_name,
            "messages": list(messages),
            "verdict": verdict,
            "meta": dict(meta or {}),
        }
        try:
            line = json.dumps(record, ensure_ascii=False)
        except (TypeError, ValueError) as exc:
            raise CaptureError(f"capture payload is not JSON-serialisable: {exc}") from exc

        path = self.path_for(app_name)
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            # 0700 on the tree, 0600 on the files: these are user prompts and model
            # output tied to an account id, not public artefacts.
            os.chmod(path.parent, 0o700)
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
            try:
                fcntl.flock(fd, fcntl.LOCK_EX)
                os.write(fd, (line + "\n").encode("utf-8"))
            finally:
                fcntl.flock(fd, fcntl.LOCK_UN)
                os.close(fd)
        except OSError as exc:
            raise CaptureError(f"could not append to {path}: {exc}") from exc
        return record["id"]

    # -- reading ---------------------------------------------------------------------

    def path_for(self, app: str, day: str | None = None) -> Path:
        return self.root / self._safe_app(app) / f"{day or _utc_day()}.jsonl"

    def read(self, app: str, day: str | None = None) -> Iterator[dict]:
        """Yield the records for one app-day, skipping any line that will not parse.

        Skipping rather than raising is deliberate: this store is append-only and a
        reader's job is to salvage what is there. A single bad line -- a disk that
        filled mid-write, a record from a future schema -- must not make the other
        several thousand unreadable.
        """
        path = self.path_for(app, day)
        if not path.exists():
            return
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except ValueError:
                    continue

    def count(self, app: str, day: str | None = None) -> int:
        return sum(1 for _ in self.read(app, day))

    # -- internals -------------------------------------------------------------------

    @staticmethod
    def _safe_app(app: str) -> str:
        """`app` becomes a directory name, so it may not contain a path.

        Callers pass literals today ("dj"), which is exactly the condition under which
        a traversal check looks unnecessary and gets left out. The next caller passes a
        surface name that came from a request.
        """
        name = str(app).strip()
        if not name or name in (".", "..") or "/" in name or "\\" in name or name.startswith("."):
            raise CaptureError(f"invalid app name for a capture directory: {app!r}")
        return name
