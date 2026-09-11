"""status()'s ComfyUI arm: the Studio row may not read `ready` unless the bench answers.

Audit item 27, decided by Garrett 2026-08-20 (option 2 — fix the claim): nothing starts
ComfyUI at boot, so the row's green used to outlive the bench it advertises. The case that
forced the decision was live that morning: :8188 had nothing listening and the deployed rack
still reported `studio: ready · 26 tools`. `status()` now makes one TCP connect to wherever
`comfy.base_url()` points, and `ready` is earned per call.

The two probe tests are a mutation pair, not redundancy: dead port → offline proves the probe
can take the green away, live listener → ready proves the reading recovers and therefore
derives from the connect and not from anything cached or softer. `SYMONEURAL_COMFY_URL` is the
sanctioned override read on every `base_url()` call, so pointing it at a port this test owns
is the same mechanism an operator would use, not sandbox surgery.

No ComfyUI, no GPU, no lock: the "listener" is a bare socket, which is exactly the floor the
probe claims to measure (the proxy still 503s a broken server per request; the LED only
promises something is there).
"""
from __future__ import annotations

import os
import socket
import unittest

from apps.studio import status

ENV_KEYS = ("SYMONEURAL_STUDIO_ENABLED", "SYMONEURAL_STUDIO_TOKEN", "SYMONEURAL_COMFY_URL")


class GreenMustBeEarned(unittest.TestCase):

    def setUp(self):
        self._saved = {k: os.environ.get(k) for k in ENV_KEYS}
        os.environ["SYMONEURAL_STUDIO_ENABLED"] = "1"
        os.environ["SYMONEURAL_STUDIO_TOKEN"] = "t" * 32

    def tearDown(self):
        for k, v in self._saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v

    def test_row_is_offline_when_nothing_listens_where_comfy_points(self):
        """The 2026-08-20 live case, reproduced: switches on, stack found, bench dead."""
        probe = socket.socket()
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
        probe.close()  # bound then closed: guaranteed refused, never a hung 0.25 s wait
        os.environ["SYMONEURAL_COMFY_URL"] = f"http://127.0.0.1:{port}"
        row = status()
        self.assertEqual(row["state"], "offline",
                         "the row reads green with nothing listening at the bench -- "
                         "the exact lie audit item 27 closed")
        self.assertIn("ComfyUI is not answering", row["detail"])
        self.assertIn(f"127.0.0.1:{port}", row["detail"],
                      "the detail must name the address it probed, not a generic sentence")

    def test_row_is_ready_again_the_moment_something_answers(self):
        with socket.socket() as srv:
            srv.bind(("127.0.0.1", 0))
            srv.listen(1)
            os.environ["SYMONEURAL_COMFY_URL"] = f"http://127.0.0.1:{srv.getsockname()[1]}"
            row = status()
        self.assertEqual(row["state"], "ready",
                         "a live listener did not restore ready -- the state no longer "
                         "derives from the probe")
        self.assertIn("tools", row["detail"])

    def test_switch_arm_is_unchanged_by_the_probe(self):
        """Switches off stays the first word: no probe fires, the detail still names them."""
        os.environ.pop("SYMONEURAL_STUDIO_ENABLED", None)
        os.environ.pop("SYMONEURAL_STUDIO_TOKEN", None)
        row = status()
        self.assertEqual(row["state"], "offline")
        self.assertIn("SYMONEURAL_STUDIO_ENABLED", row["detail"])


if __name__ == "__main__":
    unittest.main()
