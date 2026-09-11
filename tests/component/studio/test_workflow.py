"""The Studio workflow API: input swapping, event typing, and terminal status.

No engine is contacted. The wire frames here are the shapes `comfy.py` documents
out of the ComfyUI source, so a change in that mapping fails here.
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = next(p for p in Path(__file__).resolve().parents
            if (p / "backend" / "server.py").is_file())
sys.path.insert(0, str(ROOT / "backend"))

from studio.lib import workflow as wf  # noqa: E402

API_GRAPH = {
    "6": {"class_type": "CLIPTextEncode", "inputs": {"text": "a cat", "clip": ["4", 1]}},
    "10": {"class_type": "LoadImage", "inputs": {"image": "old.png"}},
    "9": {"class_type": "SaveImage", "inputs": {"images": ["8", 0]}},
}


class Fake:
    """Stands in for ComfyClient where only view_url is reached."""

    def view_url(self, filename, subfolder="", type_="output"):
        return f"http://127.0.0.1:8188/view?filename={filename}"


class SwappingInputs(unittest.TestCase):
    def setUp(self):
        self.wf = wf.Workflow(json.loads(json.dumps(API_GRAPH)))

    def test_set_input_replaces_the_value(self):
        self.wf.set_input("6", "text", "a dog")
        self.assertEqual(self.wf.get_input("6", "text"), "a dog")

    def test_set_input_chains(self):
        self.wf.set_input("6", "text", "x").set_input("10", "image", "new.png")
        self.assertEqual(self.wf.get_input("10", "image"), "new.png")

    def test_an_unknown_node_raises_and_names_what_exists(self):
        """Silently ignoring it would run the old prompt and look like success."""
        with self.assertRaises(KeyError) as caught:
            self.wf.set_input("999", "text", "x")
        self.assertIn("10", str(caught.exception))

    def test_an_unknown_field_raises_and_names_the_class(self):
        with self.assertRaises(KeyError) as caught:
            self.wf.set_input("6", "txt", "x")
        self.assertIn("CLIPTextEncode", str(caught.exception))

    def test_nodes_of_finds_by_class_not_by_number(self):
        self.assertEqual(self.wf.nodes_of("SaveImage"), ["9"])

    def test_a_canvas_save_is_refused_with_the_fix(self):
        """The canvas format will not queue; failing later inside the engine
        produces a message about a missing key and no way to act on it."""
        with self.assertRaises(ValueError) as caught:
            wf.Workflow({"nodes": [{"id": 1}], "links": []})
        self.assertIn("API Format", str(caught.exception))


class TypingTheEvents(unittest.TestCase):
    def setUp(self):
        self.client = Fake()

    def to(self, frame):
        return wf.to_event(frame, self.client)

    def test_progress_carries_a_fraction(self):
        e = self.to({"type": "progress", "data": {"value": 5, "max": 20, "node": "3"}})
        self.assertIsInstance(e, wf.Progress)
        self.assertAlmostEqual(e.fraction, 0.25)

    def test_a_zero_total_is_zero_not_a_crash(self):
        """A node that reports no total is common and is not an error."""
        e = self.to({"type": "progress", "data": {"value": 0, "max": 0}})
        self.assertEqual(e.fraction, 0.0)

    def test_a_preview_carries_the_bytes(self):
        e = self.to({"type": "preview", "data": {"image": b"PNG", "format": 1}})
        self.assertIsInstance(e, wf.Preview)
        self.assertEqual(e.image, b"PNG")

    def test_every_saved_file_gets_its_own_output_event(self):
        """Video and audio use the same record under other keys; missing them
        silently is how a caller saves half a result and thinks it saved all."""
        frame = {"type": "executed", "data": {"node": "9", "output": {
            "images": [{"filename": "a.png", "subfolder": "", "type": "output"},
                       {"filename": "b.png", "subfolder": "s", "type": "output"}],
            "gifs": [{"filename": "c.webp", "subfolder": "", "type": "output"}]}}}
        events = wf._executed_events(frame, self.client)
        self.assertEqual([e.filename for e in events], ["a.png", "b.png", "c.webp"])
        self.assertEqual({e.kind for e in events}, {"images", "gifs"})
        self.assertIn("a.png", events[0].url)

    def test_each_terminal_frame_maps_to_its_status(self):
        for kind, status in (("execution_start", "running"),
                             ("execution_success", "succeeded"),
                             ("execution_error", "failed"),
                             ("execution_interrupted", "interrupted"),
                             ("monitor_timeout", "failed"),
                             ("socket_closed", "failed")):
            e = self.to({"type": kind, "data": {}})
            self.assertIsInstance(e, wf.StatusChange, kind)
            self.assertEqual(e.status, status, kind)

    def test_a_failure_carries_the_engines_own_words(self):
        e = self.to({"type": "execution_error", "data": {
            "node_id": "8", "exception_message": "out of memory"}})
        self.assertIn("out of memory", e.detail)
        self.assertIn("8", e.detail)

    def test_queue_depth_noise_is_not_an_event(self):
        """Returning None means a caller matching on these classes never needs a
        default branch for frames it did not ask for."""
        self.assertIsNone(self.to({"type": "status", "data": {"exec_info": {}}}))

    def test_every_event_keeps_the_raw_frame(self):
        frame = {"type": "progress", "data": {"value": 1, "max": 2}}
        self.assertIs(self.to(frame).raw, frame)


class RefusedGraphs(unittest.TestCase):
    def test_the_refusal_names_the_node_and_the_message(self):
        detail = wf._queue_refusal({"ok": False, "node_errors": {
            "6": {"errors": [{"message": "required input is missing: clip"}]}}})
        self.assertIn("node 6", detail)
        self.assertIn("clip", detail)

    def test_a_refusal_with_no_node_errors_still_says_something(self):
        self.assertIn("refused", wf._queue_refusal({"ok": False}))


if __name__ == "__main__":
    unittest.main()
