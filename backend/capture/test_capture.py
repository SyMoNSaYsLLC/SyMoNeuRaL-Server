"""`apps.capture` -- the shared distill store every surface banks training turns into.

This package had no tests at all. That is worse here than the line count suggests, because
`capture()` is called from inside a `try/except` that is *designed* to swallow: the store's
own docstring says banking a training pair "must never change the result of the job the user
actually asked for", and `symoneural_dj.pipeline` duly logs and carries on. So a broken store
does not fail anything a person is watching. It quietly stops accumulating the material, and
the first symptom is an empty directory noticed weeks later.

The store also makes four claims that are only claims until something checks them, and each
one is the kind that fails silently:

  * **Concurrent appends do not tear.** `store.py` credits `flock` for this. `ConcurrencyTests`
    asserts the outcome and is explicit that it does NOT prove the lock is doing the work --
    see its docstring, and the measurement recorded beside the lock in `store.py`.
  * **0700 on the tree, 0600 on the files.** These are prompts and model output tied to an
    account id. A mode regression is invisible until it matters, and then it is a disclosure.
  * **`read()` salvages.** One bad line must not cost the other several thousand.
  * **`_safe_app` refuses a path.** Its own comment names the trap: callers pass literals
    today, "which is exactly the condition under which a traversal check looks unnecessary
    and gets left out. The next caller passes a surface name that came from a request."

Stdlib only, deliberately -- see the package docstring. The serving path is the system
interpreter and nothing may be pip-installed there, so a test needing a wheel would be a test
that cannot run where the code runs. `unittest` and `multiprocessing` are enough.
"""
from __future__ import annotations

import json
import multiprocessing
import os
import pathlib
import stat
import sys
import tempfile
import unittest
from datetime import datetime, timezone

import capture  # noqa: E402
from capture import CaptureError, CaptureStore  # noqa: E402

MESSAGES = [{"role": "user", "content": "two hours of drum and bass"},
            {"role": "assistant", "content": "here you go"}]


def _hammer(root: str, app: str, worker: int, n: int) -> None:
    """One process, `n` appends. Module level so it survives spawn as well as fork."""
    store = CaptureStore(root)
    for i in range(n):
        store.capture(app, MESSAGES, verdict={"worker": worker, "i": i})


class StoreLayoutTests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.tmp.name) / "distill"
        self.addCleanup(self.tmp.cleanup)

    def test_constructing_a_store_creates_nothing(self):
        """Documented and deliberate: a surface that merely *might* capture should not leave
        an empty directory tree behind on a box where the feature is never used."""
        CaptureStore(self.root)
        self.assertFalse(self.root.exists())

    def test_a_record_round_trips(self):
        store = CaptureStore(self.root)
        rec_id = store.capture("dj", MESSAGES, verdict={"added": 27}, meta={"job_id": "j1"})

        records = list(store.read("dj"))
        self.assertEqual(len(records), 1)
        rec = records[0]
        self.assertEqual(rec["id"], rec_id)
        self.assertEqual(rec["app"], "dj")
        self.assertEqual(rec["messages"], MESSAGES)
        self.assertEqual(rec["verdict"], {"added": 27})
        self.assertEqual(rec["meta"], {"job_id": "j1"})
        self.assertIsInstance(rec["ts"], float)

    def test_the_path_is_root_app_utcday(self):
        store = CaptureStore(self.root)
        store.capture("dj", MESSAGES)
        day = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        self.assertTrue((self.root / "dj" / f"{day}.jsonl").is_file())
        self.assertEqual(store.path_for("dj"), self.root / "dj" / f"{day}.jsonl")
        self.assertEqual(store.path_for("dj", "2026-01-02"),
                         self.root / "dj" / "2026-01-02.jsonl")

    def test_the_day_is_utc_and_not_local(self):
        """`_utc_day` uses `datetime.now(timezone.utc)`. On this box (EDT, UTC-4) a capture
        taken late in the evening belongs to *tomorrow's* file, and a store that quietly used
        local time would split a day's records across two files for four hours out of every
        twenty-four -- readable, but silently wrong for anything counting per day."""
        self.assertEqual(capture.store._utc_day(),
                         datetime.now(timezone.utc).strftime("%Y-%m-%d"))

    def test_appends_accumulate_rather_than_overwrite(self):
        store = CaptureStore(self.root)
        ids = [store.capture("dj", MESSAGES, verdict=i) for i in range(5)]
        self.assertEqual([r["id"] for r in store.read("dj")], ids)
        self.assertEqual(store.count("dj"), 5)

    def test_each_app_gets_its_own_file(self):
        store = CaptureStore(self.root)
        store.capture("dj", MESSAGES)
        store.capture("remix", MESSAGES)
        store.capture("remix", MESSAGES)
        self.assertEqual(store.count("dj"), 1)
        self.assertEqual(store.count("remix"), 2)

    def test_meta_defaults_to_an_empty_dict_not_null(self):
        """A reader doing `rec["meta"].get(...)` must not have to test for None first."""
        store = CaptureStore(self.root)
        store.capture("dj", MESSAGES)
        rec = next(iter(store.read("dj")))
        self.assertEqual(rec["meta"], {})
        self.assertIsNone(rec["verdict"])

    def test_no_provenance_field_is_written(self):
        """`provenance.py` was deleted 2026-08-11 and the package docstring states why:
        recording an unverified provenance string is worse than recording none, because it
        reads as a checked claim. Pinned so it is not helpfully added back."""
        store = CaptureStore(self.root)
        store.capture("dj", MESSAGES)
        rec = next(iter(store.read("dj")))
        self.assertEqual(set(rec), {"id", "ts", "app", "messages", "verdict", "meta"})


class PermissionTests(unittest.TestCase):
    """0700 on the tree and 0600 on the files. Captured turns are prompts and model output
    tied to an account id; the package docstring says they "are not world-readable by
    accident", and this is what stops that sentence being decoration."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.tmp.name) / "distill"
        self.addCleanup(self.tmp.cleanup)

    def test_the_app_directory_is_0700(self):
        store = CaptureStore(self.root)
        store.capture("dj", MESSAGES)
        mode = stat.S_IMODE((self.root / "dj").stat().st_mode)
        self.assertEqual(mode, 0o700, f"app dir is {mode:o}, not 0700")

    def test_the_jsonl_file_is_0600(self):
        store = CaptureStore(self.root)
        store.capture("dj", MESSAGES)
        mode = stat.S_IMODE(store.path_for("dj").stat().st_mode)
        self.assertEqual(mode, 0o600, f"capture file is {mode:o}, not 0600")

    def test_a_permissive_umask_does_not_widen_them(self):
        """The modes must come from the code, not from the caller's environment. A service
        started under `umask 000` is the case that matters, and it is not hypothetical --
        systemd units set their own umask."""
        old = os.umask(0)
        self.addCleanup(os.umask, old)
        store = CaptureStore(self.root)
        store.capture("dj", MESSAGES)
        self.assertEqual(stat.S_IMODE((self.root / "dj").stat().st_mode), 0o700)
        self.assertEqual(stat.S_IMODE(store.path_for("dj").stat().st_mode), 0o600)


class AppNameTests(unittest.TestCase):
    """`app` becomes a directory name under the store root, so it may not contain a path."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.tmp.name) / "distill"
        self.addCleanup(self.tmp.cleanup)

    def test_a_traversal_is_refused(self):
        store = CaptureStore(self.root)
        for bad in ("..", ".", "", "   ", "../etc", "a/b", "a\\b", "/abs", ".hidden"):
            with self.subTest(app=bad):
                with self.assertRaises(CaptureError):
                    store.capture(bad, MESSAGES)

    def test_a_refused_name_writes_nothing_anywhere(self):
        """The check must happen before any mkdir. Refusing the write but creating the
        directory on the way would still put an attacker-named path on disk."""
        store = CaptureStore(self.root)
        with self.assertRaises(CaptureError):
            store.capture("../escaped", MESSAGES)
        self.assertFalse(self.root.exists())
        self.assertFalse((self.root.parent / "escaped").exists())

    def test_reading_and_path_for_refuse_the_same_names(self):
        """`path_for` is public and `read` goes through it, so the guard has to hold on the
        read side too -- otherwise the traversal just moves to the other verb."""
        store = CaptureStore(self.root)
        with self.assertRaises(CaptureError):
            store.path_for("../etc")
        with self.assertRaises(CaptureError):
            list(store.read("../etc"))

    def test_surrounding_whitespace_is_stripped(self):
        store = CaptureStore(self.root)
        store.capture("  dj  ", MESSAGES)
        self.assertTrue((self.root / "dj").is_dir())


class FailureTests(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.tmp.name) / "distill"
        self.addCleanup(self.tmp.cleanup)

    def test_capture_error_is_a_plain_runtime_error(self):
        """Documented contract: callers are expected to swallow it, which is why it is not
        something a caller must special-case. `symoneural_dj.pipeline` catches and logs."""
        self.assertTrue(issubclass(CaptureError, RuntimeError))

    def test_an_unserialisable_payload_raises_rather_than_writing_junk(self):
        store = CaptureStore(self.root)
        with self.assertRaises(CaptureError):
            store.capture("dj", [{"role": "user", "content": object()}])

    def test_a_failed_serialisation_leaves_the_file_intact(self):
        """The record is serialised BEFORE the file is opened, so a bad payload must not cost
        the good records already banked -- nor leave a half-written line that would take the
        next one down with it."""
        store = CaptureStore(self.root)
        good = store.capture("dj", MESSAGES)
        with self.assertRaises(CaptureError):
            store.capture("dj", [{"bad": {1, 2, 3}}])
        self.assertEqual([r["id"] for r in store.read("dj")], [good])

    def test_reading_an_app_that_has_never_captured_yields_nothing(self):
        store = CaptureStore(self.root)
        self.assertEqual(list(store.read("dj")), [])
        self.assertEqual(store.count("dj"), 0)

    def test_a_bad_line_is_skipped_and_the_rest_survive(self):
        """Deliberate: this store is append-only and a reader's job is to salvage what is
        there. A disk that filled mid-write must not make several thousand records
        unreadable."""
        store = CaptureStore(self.root)
        first = store.capture("dj", MESSAGES)
        path = store.path_for("dj")
        with path.open("a", encoding="utf-8") as fh:
            fh.write('{"truncated": \n')
            fh.write("\n")
            fh.write("not json at all\n")
        last = store.capture("dj", MESSAGES)

        self.assertEqual([r["id"] for r in store.read("dj")], [first, last])
        self.assertEqual(store.count("dj"), 2)


class ConcurrencyTests(unittest.TestCase):
    """Concurrent appends produce N intact records. An OUTCOME test, and read the second half.

    `symoneural_dj` backgrounds every playlist as its own task, so two jobs finishing together
    write at the same moment. This asserts what has to be true of the file afterwards: the
    right number of lines, every one parseable, no duplicate ids, nothing missing.

    Real processes, not threads: `flock` is held per open file description, so a threaded
    version would exercise the GIL and say nothing about cross-process behaviour.

    **WHAT THIS TEST DOES NOT DO, stated plainly because the class name invites the mistake:
    it does not guard the lock.** Measured here 2026-08-20: comment out both `fcntl.flock`
    calls in `store.py` and this still passes. That is not a weak test that needs more
    workers -- 8 concurrent processes appending 20 records each were run at 100 B, 100 KB and
    **4 MB** per record with the lock removed, and all three produced 160 intact, parseable
    lines. Linux holds the inode lock for the duration of a buffered write to a regular file,
    so `O_APPEND` plus a single `write()` is already atomic against other writers on ext4 at
    any size. There is no payload that makes this fail on this box.

    So the lock stays and is not being called dead code -- see the note in `store.py`, which
    records the same measurement and the reason it is still correct. What changed is this
    docstring: a test named for the lock, passing without the lock, would be read by the next
    person as proof the lock works. `.claude/CLAUDE.md`: *"a check that can pass without the
    work being finished is worse than no check."*
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.tmp.name) / "distill"
        self.addCleanup(self.tmp.cleanup)

    def test_concurrent_appends_do_not_tear_lines(self):
        workers, per_worker = 8, 40
        ctx = multiprocessing.get_context("fork")
        procs = [ctx.Process(target=_hammer, args=(str(self.root), "dj", w, per_worker))
                 for w in range(workers)]
        for p in procs:
            p.start()
        for p in procs:
            p.join(timeout=120)

        self.assertEqual([p.exitcode for p in procs], [0] * workers,
                         "a worker did not exit cleanly")

        raw = CaptureStore(self.root).path_for("dj").read_text(encoding="utf-8")
        lines = raw.splitlines()
        self.assertEqual(len(lines), workers * per_worker,
                         "line count is wrong -- writes were lost or interleaved")

        # Parsed directly rather than through read(), which SKIPS anything unparseable --
        # exactly the damage this test exists to detect. Using it here would score green on
        # a shredded file.
        for i, line in enumerate(lines):
            with self.subTest(line=i):
                json.loads(line)

        self.assertTrue(raw.endswith("\n"), "final line has no terminator")

        records = [json.loads(l) for l in lines]
        self.assertEqual(len({r["id"] for r in records}), workers * per_worker,
                         "duplicate ids -- a record was written twice")
        self.assertEqual(
            sorted((r["verdict"]["worker"], r["verdict"]["i"]) for r in records),
            sorted((w, i) for w in range(workers) for i in range(per_worker)),
            "some worker's records are missing or duplicated")


if __name__ == "__main__":
    unittest.main()
