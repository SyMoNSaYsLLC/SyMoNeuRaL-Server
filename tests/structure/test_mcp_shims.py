"""The MCP shims repair a measured upstream defect; these pin what they promise.

They run against the shim itself with a fake server, not against GitHub, so they
need no credential and no network.
"""

from __future__ import annotations

import json
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents
            if (p / "backend" / "server.py").is_file())
SHIM = ROOT / "tools" / "mcp" / "fill_result_type.py"
LAUNCHER = ROOT / "bin" / "symoneural-github-mcp"


def run_shim(frames: list[dict]) -> list[dict]:
    """Feed `frames` through the shim from a fake server, return what a client sees."""
    emit = "; ".join(f"print(json.dumps({f!r}), flush=True)" for f in frames)
    fake = f"import json, sys; {emit}; sys.stdin.read()"
    out = subprocess.run(
        [sys.executable, str(SHIM), "--", sys.executable, "-c", fake],
        input=b"", capture_output=True, timeout=30).stdout
    return [json.loads(l) for l in out.splitlines() if l.strip().startswith(b"{")]


class TheShimRepairsTheDefect(unittest.TestCase):
    def test_a_result_with_no_result_type_gets_complete(self):
        """The exact defect: github-mcp-server 1.6.0 sends tools/list without it."""
        seen, = run_shim([{"jsonrpc": "2.0", "id": 2, "result": {"tools": []}}])
        self.assertEqual(seen["result"]["resultType"], "complete")

    def test_the_payload_is_otherwise_untouched(self):
        tools = [{"name": "get_me"}, {"name": "list_commits"}]
        seen, = run_shim([{"jsonrpc": "2.0", "id": 2, "result": {"tools": tools}}])
        self.assertEqual(seen["result"]["tools"], tools)
        self.assertEqual(seen["id"], 2)

    def test_an_existing_result_type_is_left_alone(self):
        """This is what lets the shim stay in place after upstream is fixed."""
        seen, = run_shim([{"jsonrpc": "2.0", "id": 2,
                           "result": {"tools": [], "resultType": "input_required"}}])
        self.assertEqual(seen["result"]["resultType"], "input_required")

    def test_an_error_frame_is_not_given_a_result_type(self):
        """Errors carry `error`, not `result`; inventing one would mask a failure."""
        frame = {"jsonrpc": "2.0", "id": 2,
                 "error": {"code": -32601, "message": "no such method"}}
        seen, = run_shim([frame])
        self.assertEqual(seen, frame)

    def test_every_frame_arrives(self):
        """A shim must never be the reason a message goes missing."""
        sent = [{"jsonrpc": "2.0", "id": i, "result": {"n": i}} for i in range(25)]
        self.assertEqual([f["id"] for f in run_shim(sent)], list(range(25)))


class TheLauncherUsesIt(unittest.TestCase):
    def test_the_launcher_runs_the_server_behind_the_shim(self):
        """Removing the shim from the exec line drops all 26 tools. Measured."""
        self.assertIn("fill_result_type.py", LAUNCHER.read_text())

    def test_no_credential_is_written_into_the_launcher(self):
        """The token comes from the gh keyring at launch, never from a file."""
        text = LAUNCHER.read_text()
        for literal in ("ghp_", "gho_", "github_pat_"):
            self.assertNotIn(literal, text)
        self.assertIn("gh auth token", text)

    def test_it_is_read_only_until_the_owner_says_otherwise(self):
        self.assertIn("--read-only", LAUNCHER.read_text())


if __name__ == "__main__":
    unittest.main()
