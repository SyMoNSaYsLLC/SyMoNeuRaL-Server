"""NO API KEYS. This file is the rule, and it is the only place the rule is written as code.

Owner decision, 2026-09-11, stated four times without hedging:

    "i dont need any fucking api keys"
    "this is my goddamn server and its not on the web MAKE IT TALK"
    "no tokens thats not how my server is gong to work everything is straught post get fetch"
    "no api keys period"                       ... and then: "i will never reverse the decision"

Twenty tests asserting the *old* contract were deleted rather than quarantined, because the
last sentence removes the only reason to keep them. Deleting them leaves a hole: the tree then
has no opinion about tokens at all, and nothing stops the next surface from growing a gate.
**This file is that opinion.**

## Why it scans instead of listing

The obvious shape is a list of the modules that had gates. That shape is what caused the bug
this file was written after: the first removal pass worked from a hand-made list of five
modules, and the tree actually had **nine** `token_ok` functions plus two more gates that do
not use that name. `project.lib.store.token_ok` was still refusing every caller while
`apps/project/routes.py::_deny` above it had been opened -- a half-removed gate, which is
worse than either end state because the surface's behaviour then depends on which door you
came in by.

So this walks `backend/` and asks every module it finds. A tenth gate added next month is
caught on the run after it is written, without anybody remembering to extend a list.

## What each check discriminates, and why none of them is vacuous

Every assertion here was proven able to fail before this file was committed, by restoring the
`hmac.compare_digest` body into one gate and watching the specific test go red. A check that
cannot fail is the failure mode this repository names explicitly, and three of the four below
would have been vacuous if written the obvious way:

* `test_every_token_ok_accepts_everything` would pass on a gated tree **if the environment
  happened to carry the right token**, so it presents deliberately wrong values -- including
  `None`, the empty string, and a non-ASCII character that used to be a 500 rather than a 401.
* `test_no_module_reads_a_token_from_the_environment` is the structural half. Behaviour alone
  cannot distinguish "no gate" from "a gate whose secret is unset and which therefore fails
  open", and those are different trees. This one reads the AST.
* `test_no_refusal_message_tells_the_owner_to_set_a_token` catches the thing that is not a
  gate but wastes a morning: a 503 whose detail names an environment variable that no longer
  does anything. The owner follows the instruction, the surface stays off, and the message was
  the bug.
* `test_the_config_file_carries_no_token` reads `run/config/api.env` **without printing it**,
  which is a standing rule. It asserts on key names only and never on a value.

## The one exemption, and why it is not a hole

`DJ_TOKEN` / `DJ_TOKEN_PATH` in `apps/remix/symoneural_dj/config.py` are **Spotify OAuth
credentials**: a secret this box presents to somebody else's service, not a gate this box puts
in front of the owner. The decision was about the second kind. Removing the first kind would
not simplify anything, it would just break the integration. The allowlist below is explicit so
that the distinction is a decision on the record rather than a regex that happened not to
match.
"""
from __future__ import annotations

import ast
import os
import pathlib
import re
import unittest

ENV_NAME = re.compile(r"[A-Z][A-Z0-9_]*")

# Anchored on the REPO, not on this file's parent. These tests moved from backend/ to
# tests/ on 2026-09-11, and a `parent`-relative anchor silently pointed at the wrong tree --
# the scan then found no gates and the suite went green over an unexamined codebase.
REPO = next(_p for _p in pathlib.Path(__file__).resolve().parents if (_p / "backend" / "server.py").is_file())
BACKEND = REPO / "backend"
# backend/ was flattened into per-component directories on 2026-09-11. This pointed
# at the vanished path and walked an empty tree, so every check below passed over nothing
# while cryptominer and asicminer were still refusing callers. Walk backend/ itself.

# Credentials that are NOT gates, each with the reason it is not one. A gate is something a
# caller presents to this box to be let in; the decision was about those. Everything here is a
# different kind of secret, and removing it would break a thing rather than simplify it.
THIRD_PARTY_SECRETS = {
    # Spotify OAuth. A secret this box presents TO somebody else's service. Not a gate.
    "DJ_TOKEN",
    "DJ_TOKEN_PATH",
    # The key the server signs its OWN session cookies with -- `apps/accounts`. Nobody types
    # it and no caller presents it; it is what makes a cookie unforgeable. Deleting it does
    # not open the door, it makes every session forgeable by anyone who can write a cookie,
    # which is the opposite of what "no api keys" asked for. Its own docstring already
    # refuses a generated or hardcoded fallback, for reasons worth reading.
    "SYMONEURAL_SESSION_SECRET",
    # Third-party service credentials this box presents TO other services. Same category as
    # DJ_TOKEN: removing them breaks an integration rather than removing a gate.
    "SPOTIFY_CLIENT_SECRET",
    "GOOGLE_CLIENT_SECRET",
    "VLLM_API_KEY",
    "ANTHROPIC_API_KEY",
    "BING_SEARCH_API_KEY",
    "SERPAPI_API_KEY",
    "GOOGLE_CSE_API_KEY",
}

# Generators that assert a live token was NOT baked into a published page. These are leak
# guards pointing the opposite way from a gate, and they are inert when no token is set.
LEAK_GUARDS = {REPO / "tools" / "build" / "build_studio.py", REPO / "tools" / "build" / "build_exp.py"}


#: Vendored trees living INSIDE apps/. `apps/sigils/.venv` is a gitignored virtualenv whose
#: site-packages carry tqdm's TQDM_DISCORD_TOKEN and rembg's WITHOUTBG_API_KEY -- third-party
#: code, third-party credentials, and not this repository's to police. Excluding them is the
#: same correction HOUSE-LANGUAGE made once already: the glob was the bug, not the symptom.
VENDORED = (".venv/", "site-packages/", "node_modules/", "/vendor/")


def _source_files() -> list[pathlib.Path]:
    """Every non-test, non-vendored Python file under `backend/`. Walked, not listed."""
    return [p for p in sorted(BACKEND.rglob("*.py"))
            if "test" not in p.name and not any(v in p.as_posix() for v in VENDORED)]


def _modules_defining(func: str) -> list[tuple[str, pathlib.Path]]:
    """(importable name, path) for every module with a module-level `func` definition."""
    out = []
    for p in _source_files():
        try:
            tree = ast.parse(p.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:                     # vendored or generated; not ours to police
            continue
        if any(isinstance(n, ast.FunctionDef) and n.name == func for n in tree.body):
            rel = p.relative_to(BACKEND).with_suffix("")
            name = str(rel).replace(os.sep, ".").removesuffix(".__init__")
            out.append((name, p))
    return out


class TokenOkAcceptsEverything(unittest.TestCase):
    """Behavioural half: every gate says yes, to every input, including the hostile ones."""

    # Deliberately wrong values. A tree with a real gate configured could pass a test that
    # presented the RIGHT token, which is how this check would have been vacuous.
    PRESENTED = (
        None,                       # no header at all -- the plain-fetch case the owner named
        "",                         # header present and empty
        "wrong",                    # an ordinary wrong guess
        "—",                        # non-ASCII: this was once a 500 out of compare_digest
        "\ud800",                   # an unpaired surrogate: .encode() raises on this
        "x" * 8192,                 # longer than any real token
    )

    def test_no_gate_function_survives_anywhere(self):
        """The gates are gone, not opened. `token_ok` and `present_token` define nothing.

        The earlier version of this asserted the opposite -- at least nine gates must exist,
        so the two behavioural checks below had something to check. That was right while the
        gates were being opened one at a time; it is wrong now that they are removed, and it
        went red for the right reason on 2026-09-11 when the last one went.

        Kept non-vacuous by the walk assertion: if `_source_files()` ever returns nothing --
        which is exactly what happened when `backend/` was flattened and this file kept
        pointing at it -- an empty gate list is not evidence of anything.
        """
        self.assertGreater(len(_source_files()), 100,
                           "the walk found almost no source files; it is broken, and an "
                           "empty result below would mean nothing")
        self.assertEqual(_modules_defining("token_ok"), [],
                         "a token gate is back. The decision was stated five times and "
                         "ends with 'i will never reverse the decision'")
        self.assertEqual(_modules_defining("present_token"), [],
                         "something is still reading a token off a request")

    def test_every_token_ok_accepts_everything(self):
        import importlib
        refused = []
        for name, path in _modules_defining("token_ok"):
            mod = importlib.import_module(name)
            for value in self.PRESENTED:
                try:
                    ok = mod.token_ok(value)
                except Exception as exc:                        # a raise is also a refusal
                    refused.append(f"{name}.token_ok({value!r}) raised {type(exc).__name__}")
                    continue
                if ok is not True:
                    refused.append(f"{name}.token_ok({value!r}) -> {ok!r}")
        self.assertEqual([], refused,
                         "these gates still refuse a caller; there are no API keys on this box")


class NoTokenIsReadFromTheEnvironment(unittest.TestCase):
    """Structural half. Behaviour cannot tell "no gate" from "a gate that is unconfigured"."""

    def test_no_module_reads_a_token_from_the_environment(self):
        offenders = []
        for p in _source_files():
            try:
                tree = ast.parse(p.read_text(encoding="utf-8", errors="replace"))
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
                    continue
                v = node.value
                # A BARE IDENTIFIER only. Matching any string that merely *ends* with
                # "_TOKEN" catches the prose too -- a 503 detail reading "...set
                # SYMONEURAL_ACCOUNTS_ENABLED=1 and SYMONEURAL_SESSION_SECRET" is a sentence,
                # not a lookup, and eighteen of them drowned the two real findings on the
                # first run of this test. Refusal prose has its own check below.
                if not ENV_NAME.fullmatch(v):
                    continue
                if not (v.endswith("_TOKEN") or v.endswith("_SECRET") or v.endswith("_API_KEY")):
                    continue
                if v in THIRD_PARTY_SECRETS:
                    continue
                offenders.append(f"{p.relative_to(REPO)}:{node.lineno}  {v}")
        self.assertEqual([], offenders,
                         "a credential name survives in live code. If it is a third-party "
                         "secret this box presents to someone else, add it to "
                         "THIRD_PARTY_SECRETS with the reason; otherwise remove the gate.")

    def test_the_env_var_indirection_is_gone_too(self):
        """`ENV_TOKEN = "SYMONEURAL_EXP_TOKEN"` then `environ.get(ENV_TOKEN)` reads as clean.

        The check above sees the string constant wherever it is assigned, so this asserts the
        thing that check relies on: no module-level name is bound to a credential spelling.
        """
        offenders = []
        for p in _source_files():
            try:
                tree = ast.parse(p.read_text(encoding="utf-8", errors="replace"))
            except SyntaxError:
                continue
            for node in tree.body:
                if not isinstance(node, ast.Assign):
                    continue
                for t in node.targets:
                    if isinstance(t, ast.Name) and t.id in ("ENV_TOKEN", "TOKEN_ENV", "HEADER_TOKEN"):
                        offenders.append(f"{p.relative_to(REPO)}:{node.lineno}  {t.id}")
        self.assertEqual([], offenders, "a token indirection survives")


class RefusalMessagesDoNotAskForAToken(unittest.TestCase):
    """The non-gate that still costs a morning: a 503 naming a variable that does nothing."""

    def test_no_refusal_message_tells_the_owner_to_set_a_token(self):
        offenders = []
        for p in _source_files():
            for i, line in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
                low = line.lower()
                if "token" not in low:
                    continue
                if ("set sym" in low or "and sym" in low) and "_token" in low:
                    offenders.append(f"{p.relative_to(REPO)}:{i}  {line.strip()[:90]}")
        self.assertEqual([], offenders,
                         "a message still instructs the owner to set a token variable that no "
                         "longer has any effect")


class TheConfigFileCarriesNoToken(unittest.TestCase):
    """Reads `run/config/api.env` and asserts on KEY NAMES ONLY. Never prints a value."""

    ENV = REPO / "run" / "config" / "api.env"

    def test_the_config_file_carries_no_token(self):
        if not self.ENV.exists():                       # a clean box has not written it yet
            self.skipTest(f"{self.ENV} is absent")
        keys = []
        for raw in self.ENV.read_text(encoding="utf-8", errors="replace").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            keys.append(line.split("=", 1)[0].strip().removeprefix("export ").strip())
        bad = [k for k in keys
               if (k.endswith("_TOKEN") or k.endswith("_API_KEY"))
               and k not in THIRD_PARTY_SECRETS]
        # The assertion message carries key NAMES, which are not secret. A value never
        # reaches an assertion, a print, or a traceback in this file.
        self.assertEqual([], bad, "token keys survive in the API config")

    def test_the_config_file_is_still_mode_600(self):
        """Unrelated to tokens and deliberately kept here: this file is edited by hand during
        exactly this kind of sweep, and a chmod lost in a rewrite is silent."""
        if not self.ENV.exists():
            self.skipTest(f"{self.ENV} is absent")
        self.assertEqual(0o600, self.ENV.stat().st_mode & 0o777,
                         "run/config/api.env must stay owner-read-write only")


if __name__ == "__main__":
    unittest.main()
