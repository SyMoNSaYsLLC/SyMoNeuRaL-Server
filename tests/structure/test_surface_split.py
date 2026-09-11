"""The surface split's invariants: one answerer, one port registry, and a rack that admits it.

Written 2026-09-10 with the RavenCalc pilot. Three properties, and the third is the one the
pilot exists to prove:

  1. A port appears in exactly one place — `ops/PORTS.tsv`. Nothing else may name one.
  2. Exactly one process can answer a surface's route. Never two, and never zero-by-accident.
  3. When the process that owns a rack row is gone, the rack says `unreachable` with a reason
     an operator can act on — not a stale `ready`, and not a blank.

`tools/lib/surface_pilot_proof.py` proves (3) end to end against real processes. These tests hold
the unit-level contracts so a change that breaks them fails here first, in a second rather
than in a nine-check integration run.
"""

from __future__ import annotations

import pathlib
import subprocess
import sys
import time
import unittest


def _repo_root() -> pathlib.Path:
    here = pathlib.Path(__file__).resolve()
    for cand in (here, *here.parents):
        if (cand / "backend" / "server.py").is_file():
            return cand
    raise AssertionError(f"repo root not found above {here}")


ROOT = _repo_root()
sys.path.insert(0, str(ROOT / "backend"))

from registry.lib import ports  # noqa: E402


class TheRegistryIsTheOnlyPlaceAPortLives(unittest.TestCase):
    def test_the_registry_parses_and_has_the_pilot(self):
        rows = ports.rows()
        self.assertTrue(rows, "ops/PORTS.tsv parsed to nothing")
        self.assertEqual(8811, ports.port_of("ravencalc"))
        self.assertEqual("http://127.0.0.1:8811", ports.base_url("ravencalc"))

    def test_a_surface_with_no_row_has_no_port_and_no_url(self):
        self.assertIsNone(ports.port_of("nosuchsurface"))
        self.assertIsNone(ports.base_url("nosuchsurface"))

    def test_a_wildcard_bind_still_gives_a_loopback_url(self):
        """`0.0.0.0` is where a service listens, not an address to dial."""
        self.assertTrue(ports.base_url("chat").startswith("http://127.0.0.1:"))

    def test_no_two_rows_claim_the_same_port(self):
        seen: dict[str, str] = {}
        for r in ports.rows():
            if r["PORT"] in seen:
                self.fail(f"port {r['PORT']} claimed by both {seen[r['PORT']]} and "
                          f"{r['SERVICE']}")
            seen[r["PORT"]] = r["SERVICE"]

    def test_every_delegated_row_has_a_port(self):
        """The invariant `apps.ports` enforces at read time, asserted over the real file."""
        for r in ports.rows():
            if r["DELEGATED"].lower() in ("yes", "true", "1"):
                self.assertNotEqual("-", r["PORT"],
                                    f"{r['SURFACE']} is delegated with no port")

    def test_a_short_row_is_an_error_not_padded(self):
        """A missing DELEGATED cell would read as falsy and silently un-delegate a surface."""
        import tempfile
        real = ports.REGISTRY
        try:
            with tempfile.NamedTemporaryFile("w", suffix=".tsv", delete=False) as fh:
                fh.write("\t".join(ports.FIELDS) + "\n")
                fh.write("svc\t9999\t127.0.0.1\n")          # three cells, seven expected
                bad = fh.name
            ports.REGISTRY = pathlib.Path(bad)
            ports.rows.cache_clear()
            with self.assertRaises(ports.RegistryError):
                ports.rows()
        finally:
            ports.REGISTRY = real
            ports.rows.cache_clear()

    def test_a_header_missing_a_column_is_an_error(self):
        import tempfile
        real = ports.REGISTRY
        try:
            with tempfile.NamedTemporaryFile("w", suffix=".tsv", delete=False) as fh:
                fh.write("SERVICE\tPORT\n svc\t1\n")
                bad = fh.name
            ports.REGISTRY = pathlib.Path(bad)
            ports.rows.cache_clear()
            with self.assertRaises(ports.RegistryError):
                ports.rows()
        finally:
            ports.REGISTRY = real
            ports.rows.cache_clear()

    def test_delegated_without_a_port_refuses_rather_than_answering_true(self):
        """The safety rule. Answering True here would drop the monolith's inline route while
        nothing else served it, and the surface would 404 as if it were a routing bug."""
        import os
        prev = os.environ.get(ports.DELEGATE_ENV)
        try:
            os.environ[ports.DELEGATE_ENV] = "remix"      # remix has no row
            with self.assertRaises(ports.RegistryError):
                ports.delegated("remix")
        finally:
            if prev is None:
                os.environ.pop(ports.DELEGATE_ENV, None)
            else:
                os.environ[ports.DELEGATE_ENV] = prev

    def test_the_generated_doc_is_current(self):
        r = subprocess.run([sys.executable, str(ROOT / "tools" / "build" / "build_ports.py"), "--check"],
                           capture_output=True, text=True, timeout=120)
        self.assertEqual(0, r.returncode,
                         f"ops/registry/PORTS.md is stale -- run tools/build/build_ports.py\n{r.stderr}")


class ExactlyOneProcessAnswers(unittest.TestCase):
    """The authority question, settled in code."""

    def test_the_monolith_registers_the_route_when_nothing_is_delegated(self):
        import server as api
        paths = [getattr(r, "path", None) for r in api.app.routes]
        if ports.delegated("ravencalc"):
            self.assertNotIn("/api/ravencalc", paths,
                             "ravencalc is delegated, so the monolith must NOT answer it")
        else:
            self.assertIn("/api/ravencalc", paths,
                          "ravencalc is not delegated, so the monolith MUST answer it")

    def test_the_surface_process_serves_the_same_route(self):
        from ravencalc.lib import service
        paths = [getattr(r, "path", None) for r in service.app.routes]
        self.assertIn("/api/ravencalc", paths)
        self.assertIn("/healthz", paths)

    def test_the_surface_enforces_the_same_published_cap(self):
        """Not a second policy. The whole reason the limiter moved into `apps.ratelimits`."""
        from runtime.lib import ratelimits
        from ravencalc.lib import service
        self.assertIs(service.ratelimits.BUDGETS, ratelimits.BUDGETS)
        self.assertEqual((240, 6000), ratelimits.BUDGETS["ravencalc"])


class TheRackAdmitsWhenASurfaceIsGone(unittest.TestCase):
    """Property (3), at unit level. `tools/lib/surface_pilot_proof.py` does it with real processes."""

    def setUp(self):
        import server as api
        self.api = api
        self.units = [
            api.Unit(id="ravencalc", label="SyMoNeuRaL RavenCalc", slot="1U", state="ready",
                     bus="cpu", href="/ravencalc.html", spec="s", detail="cpu only"),
            api.Unit(id="chat", label="Chat", slot="1U", state="ready", bus="gpu",
                     href="/chat.html", spec="s", detail="untouched"),
        ]
        self._saved = dict(api._delegated_rows)
        api._delegated_rows.clear()

    def tearDown(self):
        self.api._delegated_rows.clear()
        self.api._delegated_rows.update(self._saved)

    def _merge(self, delegate="ravencalc"):
        import os
        prev = os.environ.get(ports.DELEGATE_ENV)
        os.environ[ports.DELEGATE_ENV] = delegate
        try:
            return {u.id: u for u in self.api._merge_delegated(list(self.units))}
        finally:
            if prev is None:
                os.environ.pop(ports.DELEGATE_ENV, None)
            else:
                os.environ[ports.DELEGATE_ENV] = prev

    def test_a_fresh_poll_is_used(self):
        self.api._delegated_rows["ravencalc"] = (
            {"state": "ready", "detail": "from the surface"}, time.monotonic(), None)
        rows = self._merge()
        self.assertEqual("ready", rows["ravencalc"].state)
        self.assertEqual("from the surface", rows["ravencalc"].detail)

    def test_a_never_polled_surface_is_unreachable_not_ready(self):
        rows = self._merge()
        self.assertEqual("unreachable", rows["ravencalc"].state,
                         "an unpolled delegated surface must not inherit the in-process `ready`")

    def test_a_stale_poll_is_unreachable_even_though_the_row_says_ready(self):
        """The failure this rules out: a cache that keeps reporting a dead surface healthy."""
        self.api._delegated_rows["ravencalc"] = (
            {"state": "ready", "detail": "stale"},
            time.monotonic() - (self.api.DELEGATE_STALE_S + 5), "ConnectError")
        rows = self._merge()
        self.assertEqual("unreachable", rows["ravencalc"].state)

    def test_the_unreachable_detail_is_actionable(self):
        rows = self._merge()
        d = rows["ravencalc"].detail
        self.assertIn("8811", d, "the detail must name where it looked")
        self.assertIn("systemctl", d, "the detail must say what to do")
        self.assertGreater(len(d), 40, f"detail is too thin to act on: {d!r}")

    def test_other_rows_are_untouched(self):
        rows = self._merge()
        self.assertEqual("ready", rows["chat"].state)
        self.assertEqual("untouched", rows["chat"].detail)

    def test_nothing_delegated_means_nothing_changed(self):
        import os
        prev = os.environ.pop(ports.DELEGATE_ENV, None)
        try:
            out = self.api._merge_delegated(list(self.units))
            self.assertEqual([u.state for u in self.units], [u.state for u in out])
        finally:
            if prev is not None:
                os.environ[ports.DELEGATE_ENV] = prev

    def test_an_unreadable_registry_reports_in_process_state_rather_than_failing(self):
        """A malformed registry must not take the rack down."""
        real = ports.REGISTRY
        try:
            ports.REGISTRY = ROOT / "no-such-registry.tsv"
            ports.rows.cache_clear()
            out = self.api._merge_delegated(list(self.units))
            self.assertEqual(2, len(out))
            self.assertEqual("ready", out[0].state)
        finally:
            ports.REGISTRY = real
            ports.rows.cache_clear()

    def test_unreachable_is_a_valid_unit_state(self):
        """If the Literal did not accept it, `_merge_delegated` would raise inside the rack."""
        u = self.api.Unit(id="x", label="x", slot="1U", state="unreachable", bus="cpu",
                          href="/x", spec="s", detail="d")
        self.assertEqual("unreachable", u.state)


class TheRackPageDoesNotRenderADeadSurfaceAsPowered(unittest.TestCase):
    """`site/console.js` must never light a plate for a state it does not know.

    This is the display half of `unreachable`, and it was missed once. The API gained the
    fifth state and `leds()` still read `state === 'offline' ? dark : lit` -- an allow-list of
    ways to be OFF -- so a dead surface rendered with its POWER LED LIT in both `leds()` and
    `subs()`. An honest API behind a page that says "powered" is worse than the monolith,
    because the page is what a person looks at.

    Asserted by EXECUTING the function under node, not by grepping for a string. The first
    attempt at this fix failed silently because it was verified by reading rather than by
    running -- the fixture was copied from a `sed`-indented display and never matched the
    file, and the assertion error was misattributed to a different edit in the same script.
    """

    CONSOLE = ROOT / "site" / "console.js"

    @staticmethod
    def _node() -> str | None:
        import shutil
        return shutil.which("node")

    def test_powered_lights_only_known_live_states(self):
        node = self._node()
        if node is None:
            self.skipTest("node is not installed; this asserts JS behaviour by running it")
        src = self.CONSOLE.read_text()
        try:
            a = src.index("  var LIVE = {")
            b = src.index("function powered(state) { return !!LIVE[state]; }") + 49
        except ValueError:
            self.fail("site/console.js has no LIVE/powered() predicate -- the rack would fall "
                      "through to lit for any unrecognised state")
        harness = src[a:b] + """
const out = {};
for (const st of ['ready','busy','queued','offline','unreachable','some-future-state']) {
  out[st] = powered(st);
}
console.log(JSON.stringify(out));
"""
        r = subprocess.run([node, "-e", harness], capture_output=True, text=True, timeout=60)
        self.assertEqual(0, r.returncode, r.stderr[-400:])
        import json
        got = json.loads(r.stdout)
        self.assertTrue(got["ready"]);  self.assertTrue(got["busy"])
        self.assertTrue(got["queued"])
        self.assertFalse(got["offline"], "offline must not be powered")
        self.assertFalse(got["unreachable"],
                         "a surface whose process did not answer must not render as powered")
        self.assertFalse(got["some-future-state"],
                         "an UNKNOWN state must render dark -- lighting it is the bug class, "
                         "not just the `unreachable` instance")

    def test_both_renderers_use_the_predicate(self):
        """`leds()` was fixed once and `subs()` was not. Folded children are reached through
        their parent's process, so a dead process takes them with it."""
        src = self.CONSOLE.read_text()
        self.assertIn("powered(u.state)", src, "leds() must use the predicate")
        self.assertIn("powered(s.state)", src, "subs() must use it too -- the folded children")
        self.assertNotIn("s.state === 'offline' ? '' : ' on'", src,
                         "the old allow-list form is back in subs()")

    def test_the_state_vocabulary_covers_the_api(self):
        """WORDS is what the plate prints. A state the API can emit and WORDS lacks falls back
        to the raw id, which is honest but unstyled."""
        src = self.CONSOLE.read_text()
        for state in ("ready", "busy", "queued", "offline", "unreachable"):
            self.assertIn(f"{state}:", src, f"WORDS has no entry for {state}")


class TheUnitTemplate(unittest.TestCase):
    TEMPLATE = ROOT / "ops" / "symoneural-surface@.service"

    def test_it_exists_and_is_a_template(self):
        self.assertTrue(self.TEMPLATE.is_file())
        self.assertIn("%i", self.TEMPLATE.read_text())

    @staticmethod
    def _sections(text: str) -> dict[str, list[str]]:
        """Parse into sections by line, ignoring comments.

        A naive `text.split("[Service]")` split inside this template's own header comment --
        which says *"In [Unit], NOT [Service]"* -- and so tested the comment rather than the
        unit. Comments in a file about section placement will mention section names.
        """
        out: dict[str, list[str]] = {}
        current = None
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("#") or not stripped:
                continue
            if stripped.startswith("[") and stripped.endswith("]"):
                current = stripped
                out[current] = []
            elif current:
                out[current].append(stripped)
        return out

    def test_start_limits_are_in_unit_not_service(self):
        """The defect this repo already shipped once: systemd silently ignores StartLimit*
        under [Service] and reports the 10 s default."""
        sec = self._sections(self.TEMPLATE.read_text())
        self.assertIn("[Unit]", sec)
        self.assertIn("[Service]", sec)
        unit = "\n".join(sec["[Unit]"])
        service = "\n".join(sec["[Service]"])
        self.assertIn("StartLimitIntervalSec", unit, "crash-loop protection must be in [Unit]")
        self.assertIn("StartLimitBurst", unit)
        self.assertNotIn("StartLimitIntervalSec", service,
                         "systemd ignores StartLimit* under [Service] and says so")
        self.assertNotIn("StartLimitBurst", service)

    def test_it_names_no_port(self):
        """A port in the unit would be a second place a port lives."""
        for line in self.TEMPLATE.read_text().splitlines():
            if line.strip().startswith("#"):
                continue
            self.assertNotIn("--port 88", line,
                             f"the template hardcodes a port: {line.strip()!r}")

    def test_it_carries_the_placeholder_the_installer_substitutes(self):
        self.assertIn("@@ROOT@@", self.TEMPLATE.read_text())


if __name__ == "__main__":
    unittest.main()
