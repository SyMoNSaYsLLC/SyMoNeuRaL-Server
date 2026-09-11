"""Structural guards for the shared browser-application shell.

The browser suites prove geometry and behaviour.  These small guards answer a
different question before Chrome ever starts: did every operational workspace
actually opt into the application shell, or did a hand-maintained page escape
the generator path again?
"""

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"

WORKSPACES = (
    "chat.html",
    "image.html",
    "ravencalc.html",
    "remix.html",
    "miner.html",
    "gateway.html",
    "streamer.html",
    "studio.html",
    "exp.html",
    "project.html",
    "reinforce.html",
    "sigils.html",
    "coder.html",
    "live.html",
)


def _page(name: str) -> str:
    return (SITE / name).read_text(encoding="utf-8")


class ApplicationShellTests(unittest.TestCase):
    def test_all_fourteen_workspaces_use_application_chrome(self) -> None:
        missing = [name for name in WORKSPACES if 'class="apphead' not in _page(name)]
        self.assertEqual(
            missing,
            [],
            f"workspaces still wearing page-local/marketing chrome: {missing}",
        )

    def test_no_workspace_keeps_the_marketing_hero(self) -> None:
        escaped = [name for name in WORKSPACES if '<div class="hero"' in _page(name)]
        self.assertEqual(
            escaped,
            [],
            f"operational workspaces still contain marketing heroes: {escaped}",
        )

    def test_all_fourteen_workspaces_load_the_shared_shell_behaviour(self) -> None:
        missing = [name for name in WORKSPACES if '/shell.js?' not in _page(name)]
        self.assertEqual(missing, [], f"workspaces missing shell.js: {missing}")

    def test_coder_and_live_keep_the_instrument_before_explanatory_copy(self) -> None:
        coder = _page("coder.html")
        live = _page("live.html")
        self.assertLess(coder.index('id="cd-head"'), coder.index('class="apphead'))
        self.assertLess(live.index('id="lv-player"'), live.index('class="apphead'))
