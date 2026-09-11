"""SyMoNeuRaL Live: what the disk says, what the bridge says, and where the two must not meet.

    cd backend && python3 -m pytest apps/live/tests -q

Collected by the documented `pytest apps/` invocation -- no venv, no GPU, no OBS, no network.
Everything here runs against temporary directories and hand-written playlists.

**What this suite deliberately cannot prove** is that the obs-websocket challenge/response is
right. `base64(sha256(base64(sha256(password + salt)) + challenge))` composed the wrong way
round yields a perfectly well-formed 44-character string, and no offline assertion can tell
that from a correct one -- a test written against a value this file computed would agree with
whatever the implementation does. `apps/live/verify_bridge.py` is that check, against the real
OBS, and its output is recorded in `SMOKE.md`. The assertions here on `_auth_response` are
change-detectors and are named as such.
"""
from __future__ import annotations

import ast
import inspect
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from live.lib import hls, obs
from live import live as routes

REPO = next(_p for _p in Path(__file__).resolve().parents if (_p / "backend" / "server.py").is_file())


def playlist(seconds: tuple[float, ...] = (2.0, 2.0), *, ended: bool) -> str:
    """A minimal but real HLS playlist, in the shape ffmpeg's hls muxer writes."""
    lines = ["#EXTM3U", "#EXT-X-VERSION:3", "#EXT-X-TARGETDURATION:2",
             "#EXT-X-MEDIA-SEQUENCE:0"]
    for i, s in enumerate(seconds):
        lines += [f"#EXTINF:{s:.6f},", f"stream{i}.ts"]
    if ended:
        lines.append("#EXT-X-ENDLIST")
    return "\n".join(lines) + "\n"


def write(dirpath: Path, stem: str, *, ended: bool, age_s: float = 0.0,
          seconds: tuple[float, ...] = (2.0, 2.0)) -> Path:
    p = dirpath / f"{stem}.m3u8"
    p.write_text(playlist(seconds, ended=ended))
    for i in range(len(seconds)):
        (dirpath / f"{stem}{i}.ts").write_bytes(b"\x47" * 188)
    if age_s:
        when = time.time() - age_s
        import os
        os.utime(p, (when, when))
    return p


# --------------------------------------------------------------------------------------
class TheEndlistIsWhatMakesItAVodTests(unittest.TestCase):
    """`#EXT-X-ENDLIST` is the muxer's trailer and the whole live/VOD distinction.

    One output serves both surfaces -- that is what makes "live on the site AND watchable
    after" a single recording rather than two. The line below is the entire mechanism, so it
    gets an assertion of its own rather than being implied by the state tests.
    """

    def test_a_playlist_with_the_trailer_reads_finished(self):
        with TemporaryDirectory() as td:
            d = Path(td)
            write(d, "done", ended=True)
            self.assertEqual([s.state for s in hls.scan(d)], ["finished"])

    def test_the_same_playlist_without_it_is_not_finished(self):
        with TemporaryDirectory() as td:
            d = Path(td)
            write(d, "running", ended=False)
            self.assertNotEqual(hls.scan(d)[0].state, "finished")

    def test_the_marker_is_the_one_this_module_looks_for(self):
        self.assertEqual(hls.ENDLIST, "#EXT-X-ENDLIST")
        self.assertIn(hls.ENDLIST, playlist(ended=True))
        self.assertNotIn(hls.ENDLIST, playlist(ended=False))


class ADeadObsMustNotLeaveTheLampOnTests(unittest.TestCase):
    """The reason there are three states and not two.

    A two-state rule -- trailer present means finished, absent means live -- lights LIVE
    permanently the first time OBS is killed, crashes, or the box loses power mid-recording,
    because the muxer never gets to write its trailer. This page's own rules bar a decorative
    indicator ("every LED and gauge on the site reflects a real reading"), so a stale playlist
    reads `abandoned`: watchable as a VOD, honestly labelled, and never reported as live.
    """

    def test_a_recently_written_playlist_with_no_trailer_is_live(self):
        with TemporaryDirectory() as td:
            d = Path(td)
            write(d, "now", ended=False, age_s=0)
            self.assertEqual(hls.scan(d)[0].state, "live")
            self.assertIsNotNone(hls.live_session(d))

    def test_a_stale_playlist_with_no_trailer_is_abandoned_not_live(self):
        with TemporaryDirectory() as td:
            d = Path(td)
            write(d, "crashed", ended=False, age_s=hls.LIVE_WINDOW_S + 30)
            (session,) = hls.scan(d)
            self.assertEqual(session.state, "abandoned")
            self.assertIsNone(hls.live_session(d))

    def test_an_abandoned_recording_is_still_offered_as_a_vod(self):
        """It is a real recording with a real duration and he asked to be able to watch it.

        Hiding it because a trailer is missing would silently discard his work; the honest
        version is to offer it with a `detail` line saying what happened.
        """
        with TemporaryDirectory() as td:
            d = Path(td)
            write(d, "crashed", ended=False, age_s=hls.LIVE_WINDOW_S + 30)
            (vod,) = hls.vods(d)
            self.assertEqual(vod.state, "abandoned")
            self.assertIn("EXT-X-ENDLIST", vod.detail)

    def test_nothing_here_rewrites_a_playlist_to_add_the_missing_trailer(self):
        with TemporaryDirectory() as td:
            d = Path(td)
            p = write(d, "crashed", ended=False, age_s=hls.LIVE_WINDOW_S + 30)
            before = p.read_text()
            hls.scan(d), hls.vods(d), hls.live_session(d), hls.usage(d)
            self.assertEqual(p.read_text(), before)


class TheDurationIsReadNotEstimatedTests(unittest.TestCase):
    def test_extinf_values_are_summed(self):
        with TemporaryDirectory() as td:
            d = Path(td)
            write(d, "x", ended=True, seconds=(2.0, 2.0, 0.5))
            self.assertAlmostEqual(hls.scan(d)[0].seconds, 4.5, places=3)

    def test_a_short_final_segment_is_not_rounded_up(self):
        """Segment count times target duration would say 6.0 here. A stopwatch would not."""
        with TemporaryDirectory() as td:
            d = Path(td)
            write(d, "x", ended=True, seconds=(2.0, 2.0, 0.5))
            self.assertNotAlmostEqual(hls.scan(d)[0].seconds, 6.0, places=3)


class AnUnservableNameIsReportedNotSkippedTests(unittest.TestCase):
    """#94's shape, headed off.

    OBS's default Filename Formatting is `%CCYY-%MM-%DD %hh-%mm-%ss`, which contains a space
    and cannot go in a URL. Skipping such a file would produce a recording that OBS is writing
    perfectly well and the site cannot see, with nothing in any log to read. It is listed with
    the reason instead, and `/api/live/state` carries it.
    """

    def test_the_obs_default_filename_is_the_case_this_catches(self):
        with TemporaryDirectory() as td:
            d = Path(td)
            write(d, "2026-08-21 10-30-00", ended=True)
            (s,) = hls.scan(d)
            self.assertFalse(s.servable)
            self.assertIn("space", s.detail)
            self.assertNotIn("playlist_url", s.as_dict())

    def test_the_recommended_filename_is_servable(self):
        with TemporaryDirectory() as td:
            d = Path(td)
            write(d, "2026-08-21_10-30-00", ended=True)
            (s,) = hls.scan(d)
            self.assertTrue(s.servable, s.detail)
            self.assertEqual(s.as_dict()["playlist_url"],
                             "/api/live/hls/2026-08-21_10-30-00.m3u8")

    def test_an_unservable_recording_is_never_offered_as_live_or_vod(self):
        with TemporaryDirectory() as td:
            d = Path(td)
            write(d, "2026-08-21 10-30-00", ended=False, age_s=0)
            self.assertIsNone(hls.live_session(d))
            self.assertEqual(hls.vods(d), [])


class NameToPathIsTheOnlyPlaceInputBecomesAPathTests(unittest.TestCase):
    def test_traversal_and_absolute_names_are_refused(self):
        with TemporaryDirectory() as td:
            d = Path(td)
            write(d, "ok", ended=True)
            for bad in ("../ok.m3u8", "..%2Fok.m3u8", "/etc/passwd", "ok.m3u8/../ok.m3u8",
                        ".hidden.m3u8", "ok .m3u8", "", "ok.m3u8 ", "a" * 200 + ".m3u8"):
                with self.subTest(bad=bad):
                    self.assertIsNone(hls.resolve(bad, d))

    def test_only_playlists_and_segments_resolve(self):
        with TemporaryDirectory() as td:
            d = Path(td)
            write(d, "ok", ended=True)
            (d / "notes.txt").write_text("x")
            (d / "symoneural-live.env").write_text("SYMONEURAL_OBS_PASSWORD=x")
            self.assertIsNotNone(hls.resolve("ok.m3u8", d))
            self.assertIsNotNone(hls.resolve("ok0.ts", d))
            self.assertIsNone(hls.resolve("notes.txt", d))
            self.assertIsNone(hls.resolve("symoneural-live.env", d))

    def test_a_symlink_out_of_the_directory_does_not_resolve(self):
        """A well-formed name is not the same as a file that belongs here."""
        with TemporaryDirectory() as td, TemporaryDirectory() as other:
            d, o = Path(td), Path(other)
            (o / "secret.m3u8").write_text("#EXTM3U\n")
            (d / "escape.m3u8").symlink_to(o / "secret.m3u8")
            self.assertIsNone(hls.resolve("escape.m3u8", d))


class SegmentsAreNotInTheWebrootTests(unittest.TestCase):
    """`site/` is staging; the web server serves `/var/www/symoneural`.

    A file written into `site/` 404s for every visitor until somebody deploys, and
    `scripts/deploy.sh` then copies it into the public webroot -- which is how nineteen
    unreferenced renders got published. Renders were moved to `backend/output/` for this
    reason; a stream is worse, because segments arrive every few seconds and the deploy race
    is permanent rather than occasional.
    """

    def test_the_output_directory_is_under_backend_output(self):
        self.assertEqual(hls.OUTPUT_DIR, REPO / "backend" / "output" / "live")

    def test_no_part_of_the_output_path_is_site(self):
        self.assertNotIn("site", hls.OUTPUT_DIR.parts)

    def test_the_module_says_where_it_writes(self):
        self.assertIn("output/live", inspect.getsource(hls))


class TheRecordOutputIsWhatTheSiteWatchesTests(unittest.TestCase):
    """The pairing that fails silently if it is wrong.

    The HLS this site serves comes out of OBS's **Recording** output -- the Stream output is
    his YouTube feed and taking it would stop him streaming to YouTube. The recording output
    fires `RecordStateChanged`. Bind to `StreamStateChanged` instead and the site reads
    offline while segments are being written to disk, with nothing wrong in any log to find:
    the same shape as the `/studio/comfy` cookie-path drift, where every piece worked and only
    the pairing did not.

    Asserted rather than remembered, because getting it right once is not it staying right.
    """

    def test_record_state_changed_drives_the_recording_flag(self):
        b = obs.Bridge(password="x")
        b._event("RecordStateChanged",
                 {"outputActive": True, "outputState": "OBS_WEBSOCKET_OUTPUT_STARTED"})
        self.assertIs(b.state()["recording"], True)
        self.assertEqual(b.state()["record_state"], "OBS_WEBSOCKET_OUTPUT_STARTED")

    def test_stream_state_changed_does_not_touch_the_recording_flag(self):
        b = obs.Bridge(password="x")
        b._event("StreamStateChanged",
                 {"outputActive": True, "outputState": "OBS_WEBSOCKET_OUTPUT_STARTED"})
        self.assertIsNone(b.state()["recording"])
        self.assertIs(b.state()["streaming"], True)

    def test_the_outputs_subscription_is_asked_for(self):
        """Neither event arrives at all without this bit, and the failure is silence."""
        self.assertTrue(obs.SUBSCRIPTIONS & obs.SUB_OUTPUTS)

    def test_the_module_names_the_record_event(self):
        self.assertIn("RecordStateChanged", inspect.getsource(obs))


class WhatIsLiveComesFromTheDiskNotFromObsTests(unittest.TestCase):
    """The bridge is telemetry; the disk is the truth.

    OBS reporting `recording: true` while no playlist is being written means it is recording
    somewhere else -- a real and likely misconfiguration, since the recording path is the one
    setting this whole feature depends on. The page must say what is actually watchable.
    """

    @staticmethod
    def _imports(module) -> set[str]:
        """Every module `module` imports, by top-level name, read from its AST.

        Read from the tree and not with `assertNotIn("import obs", src)`, which is what these
        two tests did until they were run for the first time. The substring version failed --
        correctly, by its own rule, and uselessly -- because `hls.py`'s docstring contains the
        words "obs-websocket" while explaining that it deliberately does not use one. A test
        that a module's prose may not name the thing it is avoiding is a test against writing
        the comment down, and the comment is the more valuable half.

        The AST cannot be fooled either way round: prose is invisible to it, and an import
        added inside a function -- which is exactly how `obs.py` imports `websockets` -- is
        still an `ast.Import` node and is still caught.
        """
        found: set[str] = set()
        for node in ast.walk(ast.parse(inspect.getsource(module))):
            if isinstance(node, ast.Import):
                found.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom):
                # `from . import obs` -- the module is the name, not node.module.
                if node.level and not node.module:
                    found.update(a.name.split(".")[0] for a in node.names)
                elif node.module:
                    found.add(node.module.split(".")[0])
        return found

    def test_hls_does_not_import_obs(self):
        """The import graph is the guarantee, not a comment.

        If `hls` ever imports `obs`, a wrong password or a stopped OBS can take the video off
        the site, and the failure will be discovered by a visitor rather than by this line.
        """
        self.assertNotIn("obs", self._imports(hls))

    def test_hls_opens_no_socket(self):
        """It reads a directory. Anything that could reach a network is a defect here."""
        for forbidden in ("websockets", "socket", "urllib", "http", "httpx", "requests",
                          "asyncio", "subprocess"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, self._imports(hls))

    def test_hls_holds_no_credential(self):
        """No identifier and no literal in the video path names a secret.

        Docstrings are excluded for the reason above -- `symoneural-live.env.example` and the
        password are discussed in the module's prose on purpose -- so this walks identifiers
        and non-docstring literals only.
        """
        tree = ast.parse(inspect.getsource(hls))
        # By identity, not by value. `ast.get_docstring` defaults to `clean=True` and runs the
        # text through `inspect.cleandoc`, so the string it returns is not the string in the
        # tree and a value comparison excludes nothing -- which is how this test first ran red
        # against the very docstring it meant to skip.
        docstrings = {id(n.body[0].value) for n in ast.walk(tree)
                      if isinstance(n, (ast.Module, ast.ClassDef, ast.FunctionDef,
                                        ast.AsyncFunctionDef))
                      and n.body and isinstance(n.body[0], ast.Expr)
                      and isinstance(n.body[0].value, ast.Constant)
                      and isinstance(n.body[0].value.value, str)}
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                self.assertNotIn("PASSWORD", node.id.upper())
            elif isinstance(node, ast.Attribute):
                self.assertNotIn("PASSWORD", node.attr.upper())
            elif isinstance(node, ast.Constant) and isinstance(node.value, str):
                if id(node) not in docstrings:
                    self.assertNotIn("PASSWORD", node.value.upper())


class TheBridgeReportsAbsenceRatherThanZeroTests(unittest.TestCase):
    """No decorative status indicators -- a project rule, applied to a gauge.

    A dropped-frame count of 0 before anything has ever connected is a number nobody measured.
    Every field starts as `None`, which the page renders as an em dash rather than a reading.
    """

    def test_nothing_reads_as_a_measurement_before_connecting(self):
        s = obs.Bridge(password="x").state()
        self.assertFalse(s["connected"])
        for field in ("recording", "streaming", "scene", "fps", "cpu_percent",
                      "render_skipped", "output_skipped"):
            with self.subTest(field=field):
                self.assertIsNone(s[field])

    def test_an_unconfigured_bridge_names_the_variable_to_set(self):
        import os
        old = os.environ.pop("SYMONEURAL_OBS_PASSWORD", None)
        try:
            ok, why = obs.configured()
            self.assertFalse(ok)
            self.assertIn("SYMONEURAL_OBS_PASSWORD", why)
        finally:
            if old is not None:
                os.environ["SYMONEURAL_OBS_PASSWORD"] = old

    def test_state_never_raises_and_returns_a_copy(self):
        b = obs.Bridge(password="x")
        first = b.state()
        first["connected"] = "tampered"
        self.assertIsNot(b.state()["connected"], "tampered")


class TheChallengeResponseIsAChangeDetectorTests(unittest.TestCase):
    """Named for what it is. See this module's docstring.

    These pin the shape and the sensitivity. They cannot pin correctness, because a value
    computed here by the same two rounds would agree with a wrong implementation just as
    happily as with a right one. `apps/live/verify_bridge.py` is the real check and runs
    against OBS itself; `SMOKE.md` records its output.
    """

    SALT = "82KLtNGXtLmxSFdVCFcTIbfDQhKQMtVh/HgYD0EAqfQ="
    CHALLENGE = "+IxH4CnCiqpX1rM9scsNynZzbOe4KhDeYcTNS3PDaeY="

    def test_it_is_base64_of_a_sha256_digest(self):
        import base64
        got = obs._auth_response("pw", self.SALT, self.CHALLENGE)
        self.assertEqual(len(got), 44)
        self.assertEqual(len(base64.b64decode(got)), 32)

    def test_it_is_deterministic(self):
        a = obs._auth_response("pw", self.SALT, self.CHALLENGE)
        b = obs._auth_response("pw", self.SALT, self.CHALLENGE)
        self.assertEqual(a, b)

    def test_every_input_changes_the_answer(self):
        base = obs._auth_response("pw", self.SALT, self.CHALLENGE)
        self.assertNotEqual(base, obs._auth_response("pw2", self.SALT, self.CHALLENGE))
        self.assertNotEqual(base, obs._auth_response("pw", self.CHALLENGE, self.CHALLENGE))
        self.assertNotEqual(base, obs._auth_response("pw", self.SALT, self.SALT))

    def test_the_salt_and_the_challenge_are_not_interchangeable(self):
        """The one composition error this can actually catch."""
        self.assertNotEqual(obs._auth_response("pw", self.SALT, self.CHALLENGE),
                            obs._auth_response("pw", self.CHALLENGE, self.SALT))


class TheSurfaceSwitchDefaultsOnTests(unittest.TestCase):
    """Deliberately unlike every other togglable app here, and the reason is written down.

    The others cost the GPU, an outbound fetcher or a miner when switched on. This one serves
    a directory that is empty until OBS is configured to write into it, so a default-off
    version has no safety to offer -- only a tab that is broken on arrival for a request he
    marked ASAP.
    """

    def _with(self, value):
        import os
        old = os.environ.get("SYMONEURAL_LIVE_ENABLED")
        if value is None:
            os.environ.pop("SYMONEURAL_LIVE_ENABLED", None)
        else:
            os.environ["SYMONEURAL_LIVE_ENABLED"] = value
        self.addCleanup(lambda: os.environ.__setitem__("SYMONEURAL_LIVE_ENABLED", old)
                        if old is not None
                        else os.environ.pop("SYMONEURAL_LIVE_ENABLED", None))

    def test_absent_means_on(self):
        self._with(None)
        self.assertTrue(routes.enabled())

    def test_zero_means_off(self):
        self._with("0")
        self.assertFalse(routes.enabled())

    def test_off_still_answers_200_with_words(self):
        """A 503 for a normal expected state puts a red line in every visitor's console and
        makes a real outage indistinguishable from "nothing is streaming right now" --
        `apps/news/routes.py` makes the same argument for the ticker."""
        self._with("0")
        got = routes.state()
        self.assertFalse(got["enabled"])
        self.assertIn("SYMONEURAL_LIVE_ENABLED", got["detail"])


class TheSceneNameIsWithheldByDefaultTests(unittest.TestCase):
    """The one field that describes his setup rather than his stream."""

    def test_state_does_not_publish_the_scene_unless_asked(self):
        import os
        os.environ.pop("SYMONEURAL_LIVE_PUBLIC_SCENE", None)
        import live
        live.bridge._s["scene"] = "Webcam + terminal"
        try:
            got = routes.state()
            self.assertIsNone(got["obs"]["scene"])
            self.assertTrue(got["obs"]["scene_withheld"])
        finally:
            live.bridge._s["scene"] = None

    def test_the_opt_in_publishes_it(self):
        import os
        os.environ["SYMONEURAL_LIVE_PUBLIC_SCENE"] = "1"
        import live
        live.bridge._s["scene"] = "Webcam + terminal"
        try:
            self.assertEqual(routes.state()["obs"]["scene"], "Webcam + terminal")
        finally:
            os.environ.pop("SYMONEURAL_LIVE_PUBLIC_SCENE", None)
            live.bridge._s["scene"] = None


class NothingHereDeletesARecordingTests(unittest.TestCase):
    """A render is a byproduct of a request and is pruned to sixty. A recording is the thing
    the user made, and he asked to be able to watch it afterwards."""

    def test_the_package_has_no_prune_or_unlink(self):
        for module in (hls, routes):
            src = inspect.getsource(module)
            for forbidden in ("unlink(", "rmtree", "os.remove", "def prune"):
                with self.subTest(module=module.__name__, forbidden=forbidden):
                    self.assertNotIn(forbidden, src)

    def test_usage_makes_the_cost_visible_instead(self):
        with TemporaryDirectory() as td:
            d = Path(td)
            write(d, "a", ended=True)
            write(d, "b", ended=True)
            got = hls.usage(d)
            self.assertEqual(got["sessions"], 2)
            self.assertGreater(got["bytes"], 0)


class TheDirectoryMayNotExistYetTests(unittest.TestCase):
    """The normal state of a fresh checkout, and not an error."""

    def test_scanning_a_missing_directory_is_empty_not_an_exception(self):
        missing = Path("/nonexistent-symoneural-live-dir")
        self.assertEqual(hls.scan(missing), [])
        self.assertIsNone(hls.live_session(missing))
        self.assertEqual(hls.vods(missing), [])
        self.assertEqual(hls.usage(missing)["sessions"], 0)


class TheTrackedEnvExampleCarriesNoValuesTests(unittest.TestCase):
    """`*.env.example` is the one env shape `archive-guard.sh` deliberately allows out."""

    EXAMPLE = REPO / "backend/live/symoneural-live.env.example"

    def test_the_password_line_is_empty(self):
        for line in self.EXAMPLE.read_text().splitlines():
            if line.startswith("SYMONEURAL_OBS_PASSWORD"):
                self.assertEqual(line.strip(), "SYMONEURAL_OBS_PASSWORD=")
                return
        self.fail("the example does not document SYMONEURAL_OBS_PASSWORD at all")

    def test_the_guard_knows_the_key_name(self):
        """The path list already refuses a real `.env`; this catches `live.env.old`."""
        guard = (REPO / "scripts/lib/archive-guard.sh").read_text()
        self.assertIn("SYMONEURAL_OBS_PASSWORD", guard)

    def test_the_real_env_file_is_not_tracked(self):
        import subprocess
        out = subprocess.run(["git", "ls-files", "backend/live/"], cwd=REPO,
                             capture_output=True, text=True).stdout
        self.assertNotIn("symoneural-live.env\n", out)


if __name__ == "__main__":
    unittest.main()
