"""The Python bridge and the shell that starts the server must agree on where ComfyUI is.

Two files hold this one address. `scripts/symoneural-ui.sh` *starts* ComfyUI on a host and port;
`apps/studio/comfy.py` *talks to it* on a host and port. Nothing makes them agree, and they
are edited by different kinds of change -- an ops tweak touches the shell, a bridge fix
touches the Python -- which is the same shape as the ExecStart path that took the public API
down for four hours: two plausible files, and the defect living only in the gap between them.

The failure mode if they drift is not a crash. `scripts/symoneural-ui.sh start` reports success and
writes a pidfile, the server really is up, and every Studio render then fails with
`comfyui_unreachable` against the port nothing is listening on. That reads as a Studio bug and
is not one.

## Why this is not `grep 8188 -- registry.py`

`PROJECT-TASKS.md` #73 carried `check: grep 8188 -- backend/studio/registry.py`, on the
reading that the port was "hard-coded somewhere other than the registry that is supposed to
own it". `registry.py` is not that registry: it is the agent **tool** registry -- signature
introspection and JSON Schema generation -- and it holds no addresses of any kind. Satisfying
that check would have meant writing a port constant into a file with no business holding one,
purely to turn a percentage green. The module that owns this address is `comfy.py`, which
already does it correctly: `base_url()` reads `SYMONEURAL_COMFY_URL`, then
`SYMONEURAL_COMFY_HOST`/`SYMONEURAL_COMFY_PORT`, then falls back to the constants below, and
`api.py:87` calls `symoneuralenv.promote()` so the legacy `SYM_COMFY_PORT` spelling the shell
still accepts arrives on the Python side under its new name.

So the honest invariant is not "the literal appears in file X". It is "the two defaults are
the same number, and both files read the same variable to override it" -- which is checkable
dry, on any machine, with no ComfyUI running and no GPU.

Read as text rather than imported on purpose. `comfy.py` imports `httpx` and `websockets` at
module scope, and this assertion has nothing to do with whether those are installed; a test
that can only run where the bridge's dependencies are present is a test that skips exactly
where an ops change is most likely to have been made.
"""
from __future__ import annotations

import pathlib
import re
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[2]
BRIDGE = ROOT / "backend" / "apps" / "studio" / "comfy.py"
LAUNCHER = ROOT / "scripts" / "symoneural-ui.sh"

# The variable both sides must read. `comfy.py` reads it directly; `symoneural-ui.sh` reads it first
# and only then falls back to the legacy `SYM_` spelling, which `symoneuralenv.promote()`
# rewrites for the Python side at startup.
PORT_ENV = "SYMONEURAL_COMFY_PORT"


def _bridge_defaults(text: str) -> tuple[str, str]:
    """(host, port) as the Python bridge falls back to them. Raises if either is gone."""
    host = re.search(r'^DEFAULT_HOST\s*=\s*"([^"]+)"', text, re.M)
    port = re.search(r"^DEFAULT_PORT\s*=\s*(\d+)", text, re.M)
    if host is None or port is None:
        raise AssertionError(
            f"{BRIDGE} no longer declares DEFAULT_HOST/DEFAULT_PORT at module scope; "
            "this comparison has stopped comparing anything and must be rewritten, not "
            "deleted")
    return host.group(1), port.group(1)


def _launcher_defaults(text: str) -> tuple[str, str]:
    """(host, port) as the shell starts the server. Raises if either is gone."""
    # PORT="${SYMONEURAL_COMFY_PORT:-${SYM_COMFY_PORT:-8188}}"  -- the last literal is the
    # default, whatever the fallback chain in front of it looks like.
    port = re.search(r'^PORT="\$\{.*?(\d+)\}*"\s*$', text, re.M)
    host = re.search(r'^HOST="?([\d.]+)"?\s*$', text, re.M)
    if host is None or port is None:
        raise AssertionError(
            f"{LAUNCHER} no longer sets HOST/PORT in the expected form; same warning as "
            "above -- rewrite this parse, do not drop the assertion")
    return host.group(1), port.group(1)


def _disagreement(bridge_text: str, launcher_text: str) -> str | None:
    """None if the two files address the same ComfyUI, else what differs."""
    b_host, b_port = _bridge_defaults(bridge_text)
    l_host, l_port = _launcher_defaults(launcher_text)
    if (b_host, b_port) != (l_host, l_port):
        return (f"comfy.py talks to {b_host}:{b_port} but symoneural-ui.sh starts the server on "
                f"{l_host}:{l_port}; every Studio render would fail with "
                "`comfyui_unreachable` while the launcher reported success")
    if PORT_ENV not in bridge_text:
        return f"comfy.py no longer reads {PORT_ENV}, so the launcher's override is ignored"
    if PORT_ENV not in launcher_text:
        return (f"symoneural-ui.sh no longer reads {PORT_ENV}, so setting it moves the bridge "
                "without moving the server")
    return None


class ComfyPortAgreementTests(unittest.TestCase):

    def test_the_comparison_catches_a_drifted_port(self):
        """Runs on the text, so it runs everywhere -- including where the files are correct.

        Without this the class is one assertion that passes today and would still pass if
        `_disagreement` were quietly rewritten to `return None`. A check that cannot fail is
        the thing #73's own notes have now retired twice.
        """
        bridge = f'DEFAULT_HOST = "127.0.0.1"\nDEFAULT_PORT = 8188\n{PORT_ENV}\n'
        drifted = f'PORT="${{{PORT_ENV}:-8199}}"\nHOST="127.0.0.1"\n'
        why = _disagreement(bridge, drifted)
        self.assertIsNotNone(why, "a drifted port was reported as agreeing")
        self.assertIn("8199", why)

        agreeing = f'PORT="${{{PORT_ENV}:-8188}}"\nHOST="127.0.0.1"\n'
        self.assertIsNone(_disagreement(bridge, agreeing))

    def test_the_comparison_catches_a_dropped_override(self):
        """Equal defaults are not enough: the override has to reach both sides."""
        bridge = 'DEFAULT_HOST = "127.0.0.1"\nDEFAULT_PORT = 8188\n'  # no PORT_ENV
        launcher = f'PORT="${{{PORT_ENV}:-8188}}"\nHOST="127.0.0.1"\n'
        why = _disagreement(bridge, launcher)
        self.assertIsNotNone(why, "a bridge that ignores the override was reported as fine")
        self.assertIn(PORT_ENV, why)

    def test_a_parse_that_stopped_parsing_is_an_error_not_a_pass(self):
        """The vacuity guard. If either file is restructured, this class must go red rather
        than silently comparing two things it no longer found."""
        with self.assertRaises(AssertionError):
            _bridge_defaults("nothing that looks like a constant\n")
        with self.assertRaises(AssertionError):
            _launcher_defaults("nothing that looks like an assignment\n")

    def test_the_bridge_and_the_launcher_agree_on_disk(self):
        why = _disagreement(BRIDGE.read_text(), LAUNCHER.read_text())
        self.assertIsNone(why, why)


# ---------------------------------------------------------------------------
# The second address pair in this surface, and the same failure shape.
#
# `api.py` MOUNTS the editor proxy at a URL prefix. `gate.py` scopes the editor's
# session cookie to a path. Nothing makes them agree, and they are edited by
# different kinds of change -- a rebrand touches the mount, a gate fix touches the
# cookie -- which is the gap this whole module exists to close.
#
# The failure mode if they drift is the worst kind: nothing errors. A cookie scoped
# to `/studio/comfy` is simply never sent to `/studio/editor`, because that is what
# `Path=` means and the browser is behaving correctly. The entry document loads (it
# carries the token in its own query string), the editor's own relative sub-resource
# requests then arrive with no header, no query string and no cookie, and every one
# of them 401s. The iframe renders a frame and then nothing -- which is #94's
# signature exactly, and `gate.py`'s own docstring records that this precise thing
# already happened once here: "seven aborted requests and a timeout waiting for the
# canvas".
#
# So this is read off both files rather than asserted as a literal. A hard-coded
# `assertEqual(COOKIE_PATH, "/studio/editor")` goes green the moment somebody edits
# the constant, which is the half of the rename that is easy to remember; the half
# that gets forgotten is the mount two thousand lines away in `api.py`.
API = ROOT / "backend" / "server.py"
GATE = ROOT / "backend" / "apps" / "studio" / "gate.py"

#: What the editor's URL prefix may not contain. This is task #74 item 2's standard --
#: the upstream name must not appear in a URL a visitor sees -- enforced here rather
#: than only in `apps/test_brand_boundary.py` because the mount is what makes the URL
#: real, and a page can be clean while the address bar is not.
FORBIDDEN_IN_PREFIX = re.compile(r"comfy", re.IGNORECASE)


def _mount_prefix(api_text: str) -> str:
    """The prefix `api.py` mounts `studio.ui_router` at. Raises if the mount is gone.

    Matched on `ui_router` specifically, not on any `include_router`: the same file
    mounts the agent router at `/api/studio`, and a pattern loose enough to catch
    either would happily compare the cookie path against the wrong one of the two.
    """
    m = re.search(r'include_router\(\s*studio\.ui_router\s*,\s*prefix\s*=\s*"([^"]*)"',
                  api_text)
    if m is None:
        raise AssertionError(
            f"{API} no longer mounts studio.ui_router with a literal prefix=; this "
            "comparison has stopped comparing anything and must be rewritten, not "
            "deleted")
    return m.group(1)


def _cookie_path(gate_text: str) -> str:
    """The path `gate.py` scopes the editor cookie to. Raises if the constant is gone."""
    m = re.search(r'^COOKIE_PATH\s*=\s*"([^"]*)"', gate_text, re.M)
    if m is None:
        raise AssertionError(
            f"{GATE} no longer declares COOKIE_PATH at module scope; this comparison "
            "has stopped comparing anything and must be rewritten, not deleted")
    return m.group(1)


def _prefix_disagreement(api_text: str, gate_text: str) -> str | None:
    """None if the mount and the cookie address the same place, else why not."""
    mount = _mount_prefix(api_text)
    cookie = _cookie_path(gate_text)
    if mount.rstrip("/") != cookie.rstrip("/"):
        return (f"api.py mounts the editor at {mount!r} but gate.py scopes its cookie to "
                f"{cookie!r}. The browser will not send that cookie to that mount, so the "
                "framed editor's own asset requests arrive unauthenticated and 401 -- the "
                "iframe will render and then stay empty, with nothing in any log to read.")
    return None


class TheEditorMountAndItsCookieAgreeTests(unittest.TestCase):
    def test_the_comparison_catches_a_half_finished_rename(self):
        """Rename the mount, forget the cookie: the exact way this drifts."""
        why = _prefix_disagreement(
            'app.include_router(studio.ui_router, prefix="/studio/editor")\n',
            'COOKIE_PATH = "/studio/comfy"\n')
        self.assertIsNotNone(why, "a half-finished rename was reported as agreeing")
        self.assertIn("/studio/comfy", why)

    def test_a_trailing_slash_is_not_a_disagreement(self):
        """`Path=/studio/editor` and `Path=/studio/editor/` scope the same subtree, and
        failing on that would be a false positive teaching people to ignore this test."""
        self.assertIsNone(_prefix_disagreement(
            'app.include_router(studio.ui_router, prefix="/studio/editor")\n',
            'COOKIE_PATH = "/studio/editor/"\n'))

    def test_a_parse_that_stopped_parsing_is_an_error_not_a_pass(self):
        with self.assertRaises(AssertionError):
            _mount_prefix("app.include_router(studio.router, prefix='/api/studio')\n")
        with self.assertRaises(AssertionError):
            _cookie_path("COOKIE_LEGACY = 'sym_studio'\n")

    def test_the_mount_and_the_cookie_agree_on_disk(self):
        why = _prefix_disagreement(API.read_text(), GATE.read_text())
        self.assertIsNone(why, why)

    def test_the_editor_url_does_not_carry_the_upstream_name(self):
        """#74 item 2. The engine was forked to `symoneural-ui`; the URL a visitor reads
        must move with it. This is the check `PROJECT-TASKS.md` declares as
        `ngrep /studio/comfy -- backend/server.py`, asserted here as well because a grep on
        one file cannot see that the cookie, the iframe `src` and the proxy all agree."""
        for label, value in (("api.py mount", _mount_prefix(API.read_text())),
                             ("gate.py cookie path", _cookie_path(GATE.read_text()))):
            self.assertNotRegex(
                value, FORBIDDEN_IN_PREFIX,
                f"{label} is {value!r}, which puts the upstream render UI's name in a URL "
                "a visitor sees. Rebranding the tree and leaving the address is the half "
                "of the rename nobody looks at.")


if __name__ == "__main__":
    # At the END of the file, with backend/ on the path: see the block at the foot of
    # apps/test_streamer_migration.py for what a misplaced one of these hides.
    import sys

    sys.path.insert(0, str(ROOT / "backend"))
    unittest.main()
