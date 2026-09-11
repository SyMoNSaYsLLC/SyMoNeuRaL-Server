#!/usr/bin/env python3
"""Tests for SyMoNeuRaL Coder. System interpreter, stdlib only, no network, no GPU.

    python3 backend/apps/coder/test_coder.py

Every test here exists because of a specific way this surface could hand somebody the box
or the corpus. The guards are the product -- a workspace agent whose containment check can
be walked past with `../` is arbitrary code execution on the machine that serves
symoneural.com, and one whose denylist runs on the input string instead of the resolved
path hands over `training/corpus.jsonl` to anyone who can make a symlink.

Two things this file is careful about:

* It never touches the real `run/`. That directory holds `gpu.lock.d`, the GPU mutex, and a
  test that wrote into it could destroy a lock while a surface held the card. Every test
  points `SYMONEURAL_CODER_STATE_DIR` at a temp directory.
* It never touches the real workspace. `SYMONEURAL_CODER_WORKSPACE` is a temp tree built per test.
"""
from __future__ import annotations

import json
import os
import pathlib
import shutil
import sys
import tempfile
import unittest

from apps import coder  # noqa: E402

TOKEN = "test-token-not-a-real-secret"
LOCAL = "127.0.0.1"


def _restore_env(name: str, value: str | None) -> None:
    if value is None:
        os.environ.pop(name, None)
    else:
        os.environ[name] = value


class Base(unittest.TestCase):
    """A temp workspace, a temp state dir, the surface switched on, and a mutation grant.

    The grant is new as of 2026-09-04. These classes test coder's MECHANICS -- path
    containment, rollback, journalling, denylists -- and since `_mutate` became an authority
    chokepoint every one of them refuses without a bound task. Without the grant twenty of
    them fail with "mutation authority: ... requires a task record", which is the gate
    working rather than a regression in the behaviour they pin.

    `AuthorityGate` at the bottom of this file covers the other half: the same admitted
    caller, with no grant, refused.

    Both scopes are granted because the classes below span both -- file tools take
    `workspace`, `run()` takes `service`. `AuthorityGate` proves one does not imply the other.
    """

    ENABLED = True
    GRANT = ("workspace", "service")

    def setUp(self):
        from apps import authority
        self._authdir = tempfile.mkdtemp(prefix="symcoder-auth-")
        os.environ["SYMONEURAL_AUTHORITY_DIR"] = self._authdir
        self._acting = authority.acting_as(authority.Task(
            task_id="t-coder-mechanics", owner="test", provider="test",
            mutation_authority=self.GRANT))
        self._acting.__enter__()
        self.addCleanup(self._acting.__exit__, None, None, None)
        self._setup_env()

    def _setup_env(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="symcoder-test-"))
        self.ws = self.tmp / "ws"
        self.state = self.tmp / "state"
        self.outside = self.tmp / "outside"
        for d in (self.ws, self.state, self.outside):
            d.mkdir(parents=True)
        (self.outside / "secret.txt").write_text("MUST NOT BE READABLE\n")

        self._saved = {k: os.environ.get(k) for k in (
            "SYMONEURAL_CODER_ENABLED", "SYMONEURAL_CODER_TOKEN", "SYMONEURAL_CODER_ALLOW_REMOTE",
            "SYMONEURAL_CODER_WORKSPACE", "SYMONEURAL_CODER_STATE_DIR")}
        os.environ["SYMONEURAL_CODER_WORKSPACE"] = str(self.ws)
        os.environ["SYMONEURAL_CODER_STATE_DIR"] = str(self.state)
        os.environ.pop("SYMONEURAL_CODER_ALLOW_REMOTE", None)
        if self.ENABLED:
            os.environ["SYMONEURAL_CODER_ENABLED"] = "1"
            os.environ["SYMONEURAL_CODER_TOKEN"] = TOKEN
        else:
            os.environ.pop("SYMONEURAL_CODER_ENABLED", None)
            os.environ.pop("SYMONEURAL_CODER_TOKEN", None)

    def tearDown(self):
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        shutil.rmtree(self.tmp, ignore_errors=True)

    # every call carries credentials; there is no unauthenticated entry point
    def auth(self):
        return {"token": TOKEN, "peer": LOCAL}

    def journal(self) -> list[dict]:
        jp = self.state / "coder.log"
        if not jp.is_file():
            return []
        return [json.loads(l) for l in jp.read_text().splitlines() if l.strip()]


# ------------------------------------------------------------------ 1. path containment


class TestPathContainment(Base):

    def test_traversal_is_rejected(self):
        """`../` out of the workspace, at every depth, for read and for write."""
        (self.ws / "sub").mkdir()
        for bad in ("../outside/secret.txt",
                    "sub/../../outside/secret.txt",
                    "./../../outside/secret.txt",
                    "sub/../sub/../../outside/secret.txt",
                    ".."):
            r = coder.read_file(bad, **self.auth())
            self.assertFalse(r["ok"], f"read {bad!r} was ALLOWED")
            self.assertIn("escapes the workspace", r["error"])
            w = coder.write_file(bad, "x", **self.auth())
            self.assertFalse(w["ok"], f"write {bad!r} was ALLOWED")
        self.assertEqual((self.outside / "secret.txt").read_text(),
                         "MUST NOT BE READABLE\n")

    def test_absolute_path_outside_the_root_is_rejected(self):
        r = coder.read_file(str(self.outside / "secret.txt"), **self.auth())
        self.assertFalse(r["ok"])
        self.assertIn("escapes", r["error"])
        r = coder.read_file("/etc/passwd", **self.auth())
        self.assertFalse(r["ok"])

    def test_absolute_path_inside_the_root_is_allowed(self):
        """The rule is containment, not "must be relative"."""
        (self.ws / "ok.txt").write_text("hello\n")
        r = coder.read_file(str(self.ws / "ok.txt"), **self.auth())
        self.assertTrue(r["ok"], r.get("error"))
        self.assertEqual(r["text"], "hello\n")

    def test_symlink_escape_is_rejected(self):
        """The classic bypass: the string is inside the root, the target is not.

        Resolving only the string would allow every one of these.
        """
        (self.ws / "link.txt").symlink_to(self.outside / "secret.txt")
        (self.ws / "linkdir").symlink_to(self.outside)
        (self.ws / "etc").symlink_to("/etc")

        for bad in ("link.txt", "linkdir/secret.txt", "etc/passwd"):
            r = coder.read_file(bad, **self.auth())
            self.assertFalse(r["ok"], f"read through symlink {bad!r} was ALLOWED")
            self.assertIn("escapes", r["error"])

        w = coder.write_file("link.txt", "overwritten", **self.auth())
        self.assertFalse(w["ok"], "write THROUGH an escaping symlink was ALLOWED")
        self.assertEqual((self.outside / "secret.txt").read_text(),
                         "MUST NOT BE READABLE\n")

    def test_symlink_to_a_denied_path_inside_the_root_is_rejected(self):
        """The denylist runs after resolve(), so an innocent name cannot launder a secret.

        This is the "publish the manual" failure `.claude/CLAUDE.md` exists to prevent: an
        agent asked for documentation follows a link called `notes.txt` and hands over the
        corpus. A string-level denylist would allow it.
        """
        (self.ws / "training").mkdir()
        (self.ws / "training" / "corpus.jsonl").write_text('{"secret":"the recipe"}\n')
        (self.ws / "notes.txt").symlink_to(self.ws / "training" / "corpus.jsonl")

        r = coder.read_file("notes.txt", **self.auth())
        self.assertFalse(r["ok"], "the corpus was readable through a symlink")
        self.assertIn("denied", r["error"])

        w = coder.write_file("notes.txt", "clobbered", **self.auth())
        self.assertFalse(w["ok"])
        self.assertEqual((self.ws / "training" / "corpus.jsonl").read_text(),
                         '{"secret":"the recipe"}\n')

    def test_symlink_loops_and_junk_input_are_refused_not_crashed(self):
        (self.ws / "loop").symlink_to(self.ws / "loop")
        for bad in ("loop", "", "   ", "a\x00b"):
            r = coder.read_file(bad, **self.auth())
            self.assertFalse(r["ok"])
            self.assertIsInstance(r["error"], str)
        r = coder.read_file(None, **self.auth())          # type: ignore[arg-type]
        self.assertFalse(r["ok"])


# ------------------------------------------------------------------ 2. the denylist


class TestDenylist(Base):
    """Trade secret, the GPU mutex, keys, and this module's own audit trail."""

    # (relative path, what it is)
    CASES = [
        ("training/corpus.jsonl", "the 327-example corpus — trade secret"),
        ("training/build_dataset.py", "the method that produces it — trade secret"),
        ("training/adapter/adapter_model.safetensors", "adapter weights"),
        ("training/adapter/README.md", "anything inside training/adapter/"),
        ("run/gpu.lock.d/owner", "the GPU mutex"),
        (".git/config", "git remotes and credential helpers"),
        ("run/coder.log", "this module's own journal"),
        ("run/coder-backups/x", "the rollback store"),
        ("secrets/contract-signing.key", "*.key"),
        ("deep/nested/tls.key", "*.key anywhere"),
        (".env", "environment secrets"),
        (".env.production", ".env.*"),
    ]

    def test_denied_paths_are_not_readable(self):
        for rel, why in self.CASES:
            p = self.ws / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("SENSITIVE\n")
            r = coder.read_file(rel, **self.auth())
            self.assertFalse(r["ok"], f"READ ALLOWED for {rel} ({why})")
            self.assertIn("denied" if "denied" in r["error"] else "pattern", r["error"])

    def test_denied_paths_are_not_writable(self):
        for rel, why in self.CASES:
            p = self.ws / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("SENSITIVE\n")
            w = coder.write_file(rel, "clobbered", **self.auth())
            self.assertFalse(w["ok"], f"WRITE ALLOWED for {rel} ({why})")
            self.assertEqual(p.read_text(), "SENSITIVE\n", f"{rel} was modified")

    def test_denied_paths_cannot_be_deleted_or_patched_or_restored(self):
        p = self.ws / "training" / "corpus.jsonl"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("SENSITIVE\n")
        for call in (
            lambda: coder.delete_file("training/corpus.jsonl", **self.auth()),
            lambda: coder.patch_file("training/corpus.jsonl", "SENSITIVE", "x", **self.auth()),
            lambda: coder.restore("training/corpus.jsonl", "20260817T120000000000", **self.auth()),
            lambda: coder.history("training/corpus.jsonl", **self.auth()),
            lambda: coder.diff("training/corpus.jsonl", "x", **self.auth()),
        ):
            r = call()
            self.assertFalse(r["ok"])
        self.assertEqual(p.read_text(), "SENSITIVE\n")

    def test_a_neighbour_of_a_denied_path_is_still_allowed(self):
        """The denylist must not be so broad it eats ordinary work.

        `training/train_lora.py` is publishable source; `docs/symoneural-manual.md` is the
        manual and CLAUDE.md says explicitly that it IS publishable.
        """
        for rel in ("training/train_lora.py", "docs/symoneural-manual.md",
                    "training/adapters.md", "site/index.html", "keyboard.py"):
            p = self.ws / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("fine\n")
            r = coder.read_file(rel, **self.auth())
            self.assertTrue(r["ok"], f"{rel} was denied and should not be: {r.get('error')}")

    def test_a_second_adapter_directory_is_denied_like_the_first(self):
        """The 2026-08-21 leak, pinned by the shape that caused it rather than by one name.

        `DENY_SEGMENTS` matched path segments with `==`, so `training/adapter` was denied and
        `training/adapter-qwen36` -- a real 200 MB LoRA sitting beside it in this repo -- was
        served. Measured through the live `/local/coder/file` mount before the fix:
        `adapter_config.json` (the rank, the alpha, the target modules) and `README.md` both
        came back 200 with their contents.

        The weights blob itself was refused at the same moment, which is the part that makes
        this worth a test rather than a one-line fix: it was refused for being over
        MAX_READ_BYTES and not being UTF-8. Neither of those is a secrecy rule. A smaller
        adapter would have been handed over whole, and the surface would have looked exactly
        as correct as it did that morning."""
        for rel in ("training/adapter-qwen36/adapter_config.json",
                    "training/adapter-qwen36/README.md",
                    "training/adapter/adapter_model.safetensors"):
            p = self.ws / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("secret\n")
            r = coder.read_file(rel, **self.auth())
            self.assertFalse(r["ok"], f"{rel} was served and is ours")

    def test_public_model_weights_are_not_denied(self):
        """The other half, and the reason the weight rule is scoped to `training/`.

        This was written first as `*.safetensors`/`*.gguf` in DENY_NAME_GLOBS, matched
        anywhere -- which reports every off-the-shelf model under `backend/models/` as
        refused. `.claude/CLAUDE.md` says the stack is "off-the-shelf and permissively
        licensed, so nothing here is protected by a licence", so that is a false statement
        about a licence, rendered on a page whose whole argument is that its readings are
        real. A denylist that cries wolf gets read as noise, and then the entries that matter
        get read as noise too."""
        for rel in ("backend/models/qwen2.5-7b-instruct-q4_k_m.gguf",
                    "backend/models/flux/flux1-schnell.safetensors",
                    "models/whatever.gguf"):
            p = self.ws / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text("public weights\n")
            r = coder.read_file(rel, **self.auth())
            self.assertTrue(r["ok"], f"{rel} was denied: {r.get('error')}")

    def test_our_weights_are_denied_wherever_they_sit_under_training(self):
        """A checkpoint written mid-run is the same asset as the finished adapter.

        `training/runs/<id>/` is where `train_lora.py` puts them, and nothing in
        `DENY_SEGMENTS` names that directory. The weight rule tests the path parts rather
        than a fixed run of segments for exactly this case."""
        rel = "training/runs/20260818-1/checkpoint-200/adapter_model.safetensors"
        p = self.ws / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("ours\n")
        self.assertFalse(coder.read_file(rel, **self.auth())["ok"])

    def test_list_dir_flags_denied_entries_rather_than_hiding_them(self):
        """Silent omission is the decorative-dishonesty shape this repo argues against."""
        (self.ws / "training").mkdir()
        (self.ws / "training" / "corpus.jsonl").write_text("x\n")
        (self.ws / "training" / "train_lora.py").write_text("x\n")
        (self.ws / "esc").symlink_to(self.outside)

        r = coder.list_dir("training", **self.auth())
        self.assertTrue(r["ok"], r.get("error"))
        by = {e["name"]: e for e in r["entries"]}
        self.assertIn("corpus.jsonl", by, "the denied entry was silently omitted")
        self.assertTrue(by["corpus.jsonl"]["denied"])
        self.assertFalse(by["train_lora.py"]["denied"])

        top = {e["name"]: e for e in coder.list_dir(".", **self.auth())["entries"]}
        self.assertTrue(top["esc"]["denied"], "an escaping symlink was listed as usable")

    def test_the_entry_cap_stops_the_walk_rather_than_trimming_afterwards(self):
        """The cap must bind DURING the walk, not after it.

        The default workspace is the repo root, and `rglob("*")` there descends into
        backend/models/ (40 GB), external/ (8.5 GB), contrib/ and three venvs. Draining
        the generator into `sorted()` and then trimming to the cap returns the same answer
        and does all the work first, which is the "guard that protects nothing" shape.

        So this asserts on how far the walk got, not just on the length of the result --
        a test that only checked `len(entries) == cap` passes against the broken version.
        """
        consumed = []

        def counting_walk(full, recursive):
            for i in range(5_000):
                consumed.append(i)
                yield full / f"f{i:05d}.txt"

        real_walk, real_cap = coder._walk, coder.MAX_LIST_ENTRIES
        coder._walk, coder.MAX_LIST_ENTRIES = counting_walk, 5
        try:
            r = coder.list_dir(".", recursive=True, **self.auth())
        finally:
            coder._walk, coder.MAX_LIST_ENTRIES = real_walk, real_cap

        self.assertTrue(r["ok"], r.get("error"))
        self.assertEqual(len(r["entries"]), 5)
        self.assertTrue(r["truncated"])
        self.assertLessEqual(len(consumed), 6,
                             f"the walk consumed {len(consumed)} entries for a cap of 5 — "
                             "the generator was drained before the cap was checked")


# ------------------------------------------------------------------ 3. command execution


class TestRun(Base):

    def test_a_timeout_actually_kills_the_command(self):
        r = coder.run([sys.executable, "-c", "import time; time.sleep(30)"],
                      timeout=1.0, **self.auth())
        self.assertFalse(r["ok"])
        self.assertTrue(r["timed_out"])
        self.assertIn("timed out", r["error"])

    def test_a_timeout_reaps_grandchildren_too(self):
        """A child that spawns a child must not keep the pipe open past the timeout.

        Signalling only the direct pid leaves the grandchild holding stdout and the reap
        hangs; the process group is why `start_new_session=True` is there.
        """
        script = ("import subprocess,sys,time;"
                  "subprocess.Popen([sys.executable,'-c','import time;time.sleep(30)']);"
                  "time.sleep(30)")
        r = coder.run([sys.executable, "-c", script], timeout=1.0, **self.auth())
        self.assertTrue(r["timed_out"])

    def test_shell_metacharacters_are_not_interpreted(self):
        """argv is data. If any of this reached a shell the assertions below break."""
        payload = "a; touch pwned.txt && b > out.txt | c $(whoami) `id` *"
        r = coder.run(["echo", payload], **self.auth())
        self.assertTrue(r["ok"], r.get("error"))
        self.assertEqual(r["exit"], 0)
        self.assertEqual(r["stdout"], payload + "\n")
        for artefact in ("pwned.txt", "out.txt"):
            self.assertFalse((self.ws / artefact).exists(),
                             f"{artefact} was created — the string reached a shell")
        self.assertNotIn(os.environ.get("USER", "\x00nope"), r["stdout"])

    def test_a_command_line_string_is_refused(self):
        r = coder.run("echo hi > /tmp/x", **self.auth())          # type: ignore[arg-type]
        self.assertFalse(r["ok"])
        self.assertIn("never invokes a shell", r["error"])

    def test_output_is_captured_and_the_exit_code_is_reported(self):
        r = coder.run([sys.executable, "-c",
                       "import sys; print('out'); print('err', file=sys.stderr); sys.exit(3)"],
                      **self.auth())
        self.assertEqual(r["exit"], 3)
        self.assertEqual(r["stdout"], "out\n")
        self.assertEqual(r["stderr"], "err\n")

    def test_cwd_is_pinned_to_the_workspace_and_cannot_be_moved_out(self):
        r = coder.run([sys.executable, "-c", "import os; print(os.getcwd())"], **self.auth())
        self.assertEqual(r["stdout"].strip(), str(self.ws.resolve()))
        r = coder.run(["echo", "x"], cwd="../outside", **self.auth())
        self.assertFalse(r["ok"])
        self.assertIn("cwd", r["error"])

    def test_the_token_is_scrubbed_from_the_child_environment(self):
        r = coder.run([sys.executable, "-c",
                       "import os; print(os.environ.get('SYMONEURAL_CODER_TOKEN','ABSENT'))"],
                      **self.auth())
        self.assertEqual(r["stdout"].strip(), "ABSENT")

    def test_both_env_prefixes_are_scrubbed_and_nothing_else_is(self):
        """Both env spellings are scrubbed, and nothing else is.

        `_scrubbed_env` matches by prefix, which is what makes a wrong prefix silent:
        `"SYMONEURAL_STUDIO_TOKEN".startswith("SYM_")` is False, so a check written for one
        spelling stops removing anything the moment the box uses the other -- no exception,
        no log line. The legacy `SYM_` spelling is not history: `symoneuralenv.promote()`
        migrates an old env file by copying each name onto its new spelling and leaving the
        old one in place (children inherit this environment and some still read it), so a
        live process can hold both at once and both have to go.

        The surviving half is not padding. A scrubber that emptied the environment wholesale
        would satisfy every absence assertion here for entirely the wrong reason, so two
        names carrying the prefix but neither TOKEN, SECRET nor KEY are asserted to remain.
        """
        gone = {
            "SYMONEURAL_STUDIO_TOKEN": "new-spelling-token",
            "SYMONEURAL_SESSION_SECRET": "new-spelling-secret",
            "SYMONEURAL_NGC_API_KEY": "new-spelling-key",
            "SYM_ASIC_TOKEN": "legacy-spelling-token",
        }
        kept = {
            "SYMONEURAL_NEWS_ENABLED": "1",
            "SYM_GATEWAY_NETWORK": "testnet",
        }
        for k, v in {**gone, **kept}.items():
            # Restore rather than pop: two of these names can legitimately be set in the
            # shell that runs the suite, and popping them would leave later tests running
            # in an environment this one edited.
            self.addCleanup(_restore_env, k, os.environ.get(k))
            os.environ[k] = v
        names = list(gone) + list(kept)
        r = coder.run([sys.executable, "-c",
                       "import json, os, sys; "
                       "print(json.dumps({k: os.environ.get(k) for k in sys.argv[1:]}))",
                       *names], **self.auth())
        self.assertEqual(r["exit"], 0, r)
        seen = json.loads(r["stdout"])
        for k in gone:
            self.assertIsNone(seen[k], f"{k} reached the child environment")
        for k, v in kept.items():
            self.assertEqual(seen[k], v, f"{k} was scrubbed and carries no secret")

    def test_an_argument_naming_a_denied_path_is_refused(self):
        """A speed bump, and it is documented as one -- but it catches the honest mistake."""
        p = self.ws / "training" / "corpus.jsonl"
        p.parent.mkdir(parents=True)
        p.write_text("SENSITIVE\n")
        for argv in (["cat", "training/corpus.jsonl"],
                     ["cat", str(p)],
                     ["cp", "training/corpus.jsonl", "site/corpus.jsonl"]):
            r = coder.run(argv, **self.auth())
            self.assertFalse(r["ok"], f"{argv} was ALLOWED")
            self.assertIn("denied", r["error"])

    def test_an_argument_that_symlinks_to_a_denied_path_is_refused(self):
        """The argv scan resolves, so it agrees with read_file about what a path means.

        Still a speed bump -- a glob or a here-doc walks past it -- but two guards that
        disagree about the same path is how one of them becomes the one an agent reaches
        for by accident.
        """
        (self.ws / "training").mkdir()
        (self.ws / "training" / "corpus.jsonl").write_text("SENSITIVE\n")
        (self.ws / "notes.txt").symlink_to(self.ws / "training" / "corpus.jsonl")
        r = coder.run(["cat", "notes.txt"], **self.auth())
        self.assertFalse(r["ok"], "the corpus was readable via a symlinked argv")
        self.assertIn("denied", r["error"])

    def test_a_missing_binary_is_an_error_not_an_exception(self):
        r = coder.run(["definitely-not-a-real-binary-xyzzy"], **self.auth())
        self.assertFalse(r["ok"])
        self.assertIn("no such command", r["error"])


# ------------------------------------------------------------------ 4. write and rollback


class TestWriteAndRollback(Base):

    def test_write_then_restore_returns_the_original_bytes(self):
        original = "line one\nline two\nunicode: ✓ é\n"
        p = self.ws / "app.py"
        p.write_text(original)

        w = coder.write_file("app.py", "TOTALLY DIFFERENT\n", **self.auth())
        self.assertTrue(w["ok"], w.get("error"))
        self.assertEqual(p.read_text(), "TOTALLY DIFFERENT\n")

        h = coder.history("app.py", **self.auth())
        self.assertTrue(h["ok"])
        self.assertEqual(len(h["versions"]), 1)
        v = h["versions"][0]["version"]
        self.assertFalse(h["versions"][0]["absent"])

        r = coder.restore("app.py", v, **self.auth())
        self.assertTrue(r["ok"], r.get("error"))
        self.assertEqual(p.read_bytes(), original.encode(),
                         "restore did not return the original bytes")

    def test_a_restore_is_itself_undoable(self):
        p = self.ws / "a.txt"
        p.write_text("v1\n")
        coder.write_file("a.txt", "v2\n", **self.auth())
        v1 = coder.history("a.txt", **self.auth())["versions"][0]["version"]
        r = coder.restore("a.txt", v1, **self.auth())
        self.assertEqual(p.read_text(), "v1\n")
        # rolling back the wrong file must not destroy what you were trying to keep
        back = coder.restore("a.txt", r["undo_version"], **self.auth())
        self.assertTrue(back["ok"], back.get("error"))
        self.assertEqual(p.read_text(), "v2\n")

    def test_creating_a_file_is_undoable_too(self):
        """Rollback that cannot undo a creation is not rollback."""
        w = coder.write_file("new.txt", "created by the agent\n", **self.auth())
        self.assertTrue(w["ok"], w.get("error"))
        self.assertTrue(w["created"])
        h = coder.history("new.txt", **self.auth())["versions"]
        self.assertTrue(h[0]["absent"])
        r = coder.restore("new.txt", h[0]["version"], **self.auth())
        self.assertTrue(r["ok"], r.get("error"))
        self.assertFalse((self.ws / "new.txt").exists())

    def test_delete_is_backed_up_and_restorable(self):
        (self.ws / "gone.txt").write_text("important\n")
        d = coder.delete_file("gone.txt", **self.auth())
        self.assertTrue(d["ok"], d.get("error"))
        self.assertFalse((self.ws / "gone.txt").exists())
        r = coder.restore("gone.txt", d["version"], **self.auth())
        self.assertTrue(r["ok"], r.get("error"))
        self.assertEqual((self.ws / "gone.txt").read_text(), "important\n")

    def test_restore_refuses_a_version_that_is_not_a_version(self):
        """`version` is caller-supplied and becomes a filesystem path.

        This is HANDOVER §3.3 again -- the render endpoint matches the name against the
        exact shape the generator emits. So does this.
        """
        (self.ws / "a.txt").write_text("x\n")
        coder.write_file("a.txt", "y\n", **self.auth())
        for bad in ("../../../../etc/passwd",
                    "../../coder.log",
                    "20260817T120000000000/../../../etc/passwd",
                    "*", "", "latest", None, 12345,
                    "20260817T12000000000"):        # one digit short
            r = coder.restore("a.txt", bad, **self.auth())   # type: ignore[arg-type]
            self.assertFalse(r["ok"], f"restore version {bad!r} was ALLOWED")
            self.assertEqual(r["error"], "no such version")
        self.assertEqual((self.ws / "a.txt").read_text(), "y\n")

    def test_restore_cannot_be_pointed_at_another_file_s_backup(self):
        """The case the containment re-check alone does NOT catch.

        Verified by mutation: delete VERSION_RE from `_backup_file` and every other case in
        the test above still passes, because they resolve outside the backups root and get
        caught there. This one resolves *inside* it -- `a.txt./../sub/b.txt.<v>.bak` is a
        real file under `coder-backups/` -- so the shape check is the only thing standing
        between a restore and one file's history being written into another file. Without
        it, `version` is a read primitive over the whole backup store.
        """
        (self.ws / "sub").mkdir()
        (self.ws / "a.txt").write_text("A ORIGINAL\n")
        (self.ws / "sub" / "b.txt").write_text("B CONTENT\n")
        coder.write_file("a.txt", "A NEW\n", **self.auth())
        coder.write_file("sub/b.txt", "B NEW\n", **self.auth())
        vb = coder.history("sub/b.txt", **self.auth())["versions"][0]["version"]

        r = coder.restore("a.txt", f"/../sub/b.txt.{vb}", **self.auth())
        self.assertFalse(r["ok"], "restore read another file's backup")
        self.assertEqual(r["error"], "no such version")
        self.assertEqual((self.ws / "a.txt").read_text(), "A NEW\n")
        self.assertNotIn("B CONTENT", (self.ws / "a.txt").read_text())

    def test_two_workspaces_do_not_share_a_history(self):
        """Same filename, different tree -- restore must not cross them."""
        (self.ws / "same.txt").write_text("workspace one\n")
        coder.write_file("same.txt", "edited one\n", **self.auth())
        v1 = coder.history("same.txt", **self.auth())["versions"][0]["version"]

        ws2 = self.tmp / "ws2"
        ws2.mkdir()
        (ws2 / "same.txt").write_text("workspace two\n")
        os.environ["SYMONEURAL_CODER_WORKSPACE"] = str(ws2)
        coder.write_file("same.txt", "edited two\n", **self.auth())
        h2 = coder.history("same.txt", **self.auth())["versions"]
        self.assertEqual(len(h2), 1, "the second workspace inherited the first's history")
        self.assertNotIn(v1, [x["version"] for x in h2])
        coder.restore("same.txt", h2[0]["version"], **self.auth())
        self.assertEqual((ws2 / "same.txt").read_text(), "workspace two\n")
        self.assertEqual((self.ws / "same.txt").read_text(), "edited one\n")

    def test_patch_requires_the_match_to_be_unique(self):
        (self.ws / "c.txt").write_text("a\nb\na\n")
        r = coder.patch_file("c.txt", "a\n", "z\n", **self.auth())
        self.assertFalse(r["ok"])
        self.assertIn("occurs 2 times", r["error"])
        self.assertEqual((self.ws / "c.txt").read_text(), "a\nb\na\n")
        r = coder.patch_file("c.txt", "b\n", "z\n", **self.auth())
        self.assertTrue(r["ok"], r.get("error"))
        self.assertEqual((self.ws / "c.txt").read_text(), "a\nz\na\n")

    def test_diff_writes_nothing(self):
        (self.ws / "d.txt").write_text("one\n")
        r = coder.diff("d.txt", "two\n", **self.auth())
        self.assertTrue(r["ok"], r.get("error"))
        self.assertIn("-one", r["diff"])
        self.assertIn("+two", r["diff"])
        self.assertEqual((self.ws / "d.txt").read_text(), "one\n")
        self.assertEqual(self.journal(), [], "a read-only preview was journalled as a change")


# ------------------------------------------------------------------ 5. the journal


class TestJournal(Base):

    def test_every_mutating_action_is_journalled_with_a_timestamp_and_a_path(self):
        (self.ws / "j.txt").write_text("x\n")
        coder.write_file("j.txt", "y\n", **self.auth())
        coder.patch_file("j.txt", "y", "z", **self.auth())
        coder.run(["echo", "hi"], **self.auth())
        v = coder.history("j.txt", **self.auth())["versions"][0]["version"]
        coder.restore("j.txt", v, **self.auth())
        coder.delete_file("j.txt", **self.auth())

        recs = self.journal()
        actions = [r["action"] for r in recs]
        # `patch` is recorded in its own right as well as the `write` it delegates to, so
        # the log says how the change arrived and not merely that bytes changed.
        for want in ("write", "patch", "run", "restore", "delete"):
            self.assertIn(want, actions, f"{want} was not journalled")
        for r in recs:
            self.assertTrue(r["ts"].startswith("20"), r)
            self.assertIn("path", r)
        self.assertTrue((self.state / "coder.log").is_file())

    def test_a_read_is_not_journalled(self):
        (self.ws / "r.txt").write_text("x\n")
        coder.read_file("r.txt", **self.auth())
        coder.list_dir(".", **self.auth())
        self.assertEqual(self.journal(), [])

    def test_a_write_that_cannot_be_journalled_does_not_happen(self):
        """HANDOVER §5 item 1 in miniature: the failure path must deny, not proceed."""
        (self.ws / "k.txt").write_text("original\n")
        os.environ["SYMONEURAL_CODER_STATE_DIR"] = "/proc/cannot-create-this/state"
        r = coder.write_file("k.txt", "should not land\n", **self.auth())
        self.assertFalse(r["ok"], "an unjournalled write was ALLOWED")
        self.assertEqual((self.ws / "k.txt").read_text(), "original\n")

    def test_nothing_is_created_under_the_state_dir_at_import_time(self):
        """api.py imports this module while the surface is disabled. It must be inert."""
        self.assertFalse((self.state / "coder.log").exists())
        self.assertFalse((self.state / "coder-backups").exists())
        coder.status(**self.auth())
        coder.read_file("nope.txt", **self.auth())
        self.assertEqual(list(self.state.iterdir()), [])


# ------------------------------------------------------------------ 6. the gates


class TestDisabled(Base):
    """SYMONEURAL_CODER_ENABLED unset. Every entry point must refuse."""

    ENABLED = False

    def test_the_module_refuses_everything_when_the_switch_is_unset(self):
        (self.ws / "x.txt").write_text("untouched\n")
        calls = {
            "status": lambda: coder.status(**self.auth()),
            "list_dir": lambda: coder.list_dir(".", **self.auth()),
            "read_file": lambda: coder.read_file("x.txt", **self.auth()),
            "diff": lambda: coder.diff("x.txt", "y", **self.auth()),
            "write_file": lambda: coder.write_file("x.txt", "clobbered", **self.auth()),
            "patch_file": lambda: coder.patch_file("x.txt", "untouched", "z", **self.auth()),
            "delete_file": lambda: coder.delete_file("x.txt", **self.auth()),
            "history": lambda: coder.history("x.txt", **self.auth()),
            "restore": lambda: coder.restore("x.txt", "20260817T120000000000", **self.auth()),
            "run": lambda: coder.run(["echo", "hi"], **self.auth()),
            "journal_tail": lambda: coder.journal_tail(10, **self.auth()),
        }
        for name, call in calls.items():
            r = call()
            self.assertFalse(r["ok"], f"{name}() worked with the surface DISABLED")
            self.assertIn("disabled", r["error"], f"{name}(): {r['error']}")
        self.assertEqual((self.ws / "x.txt").read_text(), "untouched\n")
        self.assertEqual(self.journal(), [])
        self.assertEqual(coder.unit_state()[0], "offline")

    def test_a_token_alone_is_not_enough(self):
        os.environ["SYMONEURAL_CODER_TOKEN"] = TOKEN        # but not SYMONEURAL_CODER_ENABLED
        self.assertFalse(coder.enabled())
        self.assertFalse(coder.read_file("x.txt", **self.auth())["ok"])



class TestGates(Base):


    def test_a_non_loopback_peer_is_refused_even_with_the_right_token(self):
        """The second, independent gate. A leaked token alone must not reach the box."""
        (self.ws / "x.txt").write_text("untouched\n")
        for peer in ("203.0.113.9", "10.0.0.5", "192.168.1.20", "2606:4700::1",
                     "0.0.0.0", "::"):
            r = coder.write_file("x.txt", "clobbered", token=TOKEN, peer=peer)
            self.assertFalse(r["ok"], f"peer {peer} was ACCEPTED without ALLOW_REMOTE")
            self.assertIn("loopback", r["error"])
        self.assertEqual((self.ws / "x.txt").read_text(), "untouched\n")

    def test_an_absent_or_unparseable_peer_is_refused(self):
        """A check that cannot be performed is a refusal, never a pass."""
        for peer in (None, "", "   ", "unknown", "localhost", "example.com",
                     "127.0.0.1, 203.0.113.9"):
            ok, why = coder.authorize(TOKEN, peer)
            self.assertFalse(ok, f"peer {peer!r} was ACCEPTED")
        # and still refused when remote is allowed -- there is nothing to attribute to
        os.environ["SYMONEURAL_CODER_ALLOW_REMOTE"] = "1"
        for peer in (None, "", "unknown", "localhost"):
            ok, _ = coder.authorize(TOKEN, peer)
            self.assertFalse(ok, f"peer {peer!r} was ACCEPTED with ALLOW_REMOTE")

    def test_loopback_in_its_several_spellings_is_accepted(self):
        for peer in ("127.0.0.1", "127.0.0.53", "::1", "[::1]",
                     "::ffff:127.0.0.1", "[::ffff:127.0.0.1]"):
            ok, why = coder.authorize(TOKEN, peer)
            self.assertTrue(ok, f"loopback peer {peer} was refused: {why}")


    def test_allow_remote_must_be_exactly_1(self):
        for v in ("0", "true", "yes", "", "TRUE", "1 "):
            os.environ["SYMONEURAL_CODER_ALLOW_REMOTE"] = v
            self.assertFalse(coder.allow_remote(), f"{v!r} enabled remote access")


# ------------------------------------------------------------------ 7. the GPU

class TestNoGpu(Base):
    """This module is orchestration and file I/O. It must never take the card."""

    def test_the_module_never_mentions_the_governor_or_a_model(self):
        src = pathlib.Path(coder.__file__).read_text()
        code = "\n".join(l for l in src.splitlines() if not l.strip().startswith("#"))
        for forbidden in ("gpu-governor", "gpu_governor", "llama-server", "nvidia-smi",
                          "torch", "cuda"):
            self.assertNotIn(forbidden, code.lower().replace("gpu.lock.d", ""),
                             f"{forbidden} appears in the coder module")
        self.assertIsNone(coder.status(**self.auth())["model"])

    def test_the_gpu_lock_directory_is_denied(self):
        lock = self.ws / "run" / "gpu.lock.d"
        lock.mkdir(parents=True)
        (lock / "owner").write_text("chat\n")
        self.assertFalse(coder.read_file("run/gpu.lock.d/owner", **self.auth())["ok"])
        self.assertFalse(coder.delete_file("run/gpu.lock.d/owner", **self.auth())["ok"])
        self.assertTrue((lock / "owner").is_file(), "the GPU mutex was disturbed")


if __name__ == "__main__":
    unittest.main(verbosity=2)


class AuthorityGate(Base):
    """The half `Base`'s grant no longer exercises: an admitted caller with no authority.

    `token_ok` + `peer_ok` decide whether a CALLER may reach this surface. The authority
    plane decides whether THIS TASK may change the workspace right now. Until 2026-09-04 the
    coder surface only asked the first question, so a valid token was a standing licence to
    write, delete, restore and exec.
    """

    #: No grant at all. Everything else about the fixture is a fully admitted caller.
    GRANT = ()

    def _kw(self):
        return dict(token=TOKEN, peer="127.0.0.1")

    def test_write_is_refused_and_nothing_is_written(self):
        target = self.ws / "new.txt"
        r = coder.write_file("new.txt", "x", **self._kw())
        self.assertFalse(r["ok"])
        self.assertIn("mutation authority", r["error"])
        self.assertFalse(target.exists(), "the file was written despite the refusal")

    def test_run_is_refused_at_service_scope(self):
        r = coder.run(["echo", "hi"], **self._kw())
        self.assertFalse(r["ok"])
        self.assertIn("mutation authority", r["error"])
        self.assertIn("service", r["error"])

    def test_delete_and_patch_are_refused_without_changing_the_file(self):
        """Seeded under a grant so the refusal is about authority and not about the file
        being absent -- the first version of this check passed for the wrong reason."""
        from apps import authority
        seeded = authority.Task(task_id="t-seed", owner="test",
                                mutation_authority=("workspace",))
        with authority.acting_as(seeded):
            coder.write_file("seed.txt", "original", **self._kw())
        target = self.ws / "seed.txt"
        before = target.read_text()

        r = coder.patch_file("seed.txt", "original", "changed", **self._kw())
        self.assertFalse(r["ok"]); self.assertIn("mutation authority", r["error"])
        r = coder.delete_file("seed.txt", **self._kw())
        self.assertFalse(r["ok"]); self.assertIn("mutation authority", r["error"])

        self.assertTrue(target.exists(), "the file was deleted despite the refusal")
        self.assertEqual(target.read_text(), before, "the file changed despite the refusal")

    def test_read_only_operations_still_work_without_any_grant(self):
        """Read-only paths deliberately need no lease. Requiring one would make `status` and
        `list_dir` unusable for the page that renders them, and gain nothing: they change
        nothing to serialise against."""
        for label, r in (("status", coder.status(**self._kw())),
                         ("list_dir", coder.list_dir(".", **self._kw())),
                         ("diff", coder.diff("nothing.txt", "x", **self._kw()))):
            with self.subTest(op=label):
                self.assertNotIn("mutation authority", str(r.get("error", "")))

    def test_a_workspace_grant_does_not_reach_the_executor(self):
        """The lateral move the scope split exists to stop: `run()` execs a binary that can
        touch anything the API user can, far outside the workspace the file tools confine."""
        from apps import authority
        ws_only = authority.Task(task_id="t-ws", owner="test",
                                 mutation_authority=("workspace",))
        with authority.acting_as(ws_only):
            self.assertTrue(coder.write_file("ok.txt", "x", **self._kw())["ok"])
            r = coder.run(["echo", "hi"], **self._kw())
            self.assertFalse(r["ok"], "a workspace grant reached the executor")
            self.assertIn("service", r["error"])

    def test_an_authority_refusal_is_not_reported_as_a_backup_failure(self):
        """Two different problems with two different fixes. 'journal/backup failed' sent the
        reader to check disk space for what was a missing grant."""
        r = coder.write_file("x.txt", "x", **self._kw())
        self.assertNotIn("journal/backup failed", r["error"])
