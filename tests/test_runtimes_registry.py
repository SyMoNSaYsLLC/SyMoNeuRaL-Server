"""`ops/RUNTIMES.tsv` must agree with the three things it points at, or it is a fourth copy.

The runtime map existed in four places before 2026-09-10 -- the argv builders in `api.py`,
the `case` arms in `scripts/gpu-governor.sh`, `restore/manifests/BUILD-RECIPES.tsv`, and
`ops/PORTS.tsv` -- and nothing asserted they agreed. Writing a fifth document that merely
*restates* them would make the disagreement more likely, not less. So every cell in the new
registry that names something in one of those files is checked against it here.

Three of these tests are worth reading before changing anything:

* `test_every_lease_is_known_to_the_governor` turns the two-process lease proof's first
  finding into an assertion. `drain()` with no pattern reads EVERY compute context against
  `DRAIN_FLOOR_MIB=1024`, so a leaseholding surface the governor does not recognise falls to
  the `*)` default and its first acquire behind a resident tenant is refused -- correctly,
  and it presents as a lock bug. That was written up as "a checklist item for surfaces three
  onward, and it is not in any document yet."

* `test_call_site_patterns_resolve_to_exactly_one_line` is the check a `grep`-shaped test
  cannot make. A fragment that matches two lines still "passes" an `in` check while having
  stopped identifying a call site.

* `test_nothing_here_carries_a_measurement` guards the design rule. Sizes and build dates
  belong in the generated Markdown where they are dated; in a hand-maintained TSV they are
  the carried-forward figure this repository has published before.
"""

from __future__ import annotations

import pathlib
import re
import sys
import unittest


def _repo_root() -> pathlib.Path:
    here = pathlib.Path(__file__).resolve()
    for cand in (here, *here.parents):
        if (cand / "backend" / "server.py").is_file():
            return cand
    raise AssertionError(f"repo root not found above {here}: no backend/server.py marker")


ROOT = _repo_root()
sys.path.insert(0, str(ROOT / "backend"))

from registry.lib import ports, runtimes  # noqa: E402

GOVERNOR = ROOT / "scripts" / "gpu-governor.sh"


class RegistryShape(unittest.TestCase):
    def test_it_parses_and_is_not_empty(self):
        rows = runtimes.rows()
        self.assertGreaterEqual(len(rows), 10,
                                "the registry lost rows; every first-party runtime has one")

    def test_the_key_is_runtime_plus_surface_and_is_unique(self):
        """Not RUNTIME alone: symoneural-diffuse legitimately has two rows."""
        keys = [(r["RUNTIME"], r["SURFACE"]) for r in runtimes.rows()]
        dupes = {k for k in keys if keys.count(k) > 1}
        self.assertEqual(set(), dupes, f"duplicate (RUNTIME, SURFACE) keys: {dupes}")
        self.assertEqual(2, len(runtimes.for_runtime("symoneural-diffuse")),
                         "the diffuse engine serves image AND sigil under two governor "
                         "surfaces with two eviction arms; one row would hide sigil")

    def test_enumerated_columns_only_take_known_values(self):
        kinds = {"engine-cuda", "engine-cpu", "service-go", "service-rust", "service-python",
                 "interpreter", "cli", "not-a-runtime"}
        invocations = {"long-lived-child", "per-request-subprocess", "systemd-unit",
                       "hand-started", "detached-job", "never"}
        states = {"running", "present", "proposed", "disabled", "absent"}
        for r in runtimes.rows():
            who = f"{r['RUNTIME']}/{r['SURFACE']}"
            self.assertIn(r["KIND"], kinds, who)
            self.assertIn(r["INVOCATION"], invocations, who)
            self.assertIn(r["STATE"], states, who)


class AgreesWithThePortRegistry(unittest.TestCase):
    """One-directional, on purpose.

    RUNTIMES -> PORTS only. `sshd`, `xrdp` and the second and third `symoneural-web` ports
    are in PORTS.tsv and have no runtime row, so a bidirectional assertion would be red on
    arrival for reasons that are not defects.
    """

    def test_every_port_matches_the_port_registry_on_port_and_surface(self):
        by_port: dict[int, list[dict[str, str]]] = {}
        for p in ports.rows():
            by_port.setdefault(int(p["PORT"]), []).append(p)
        for r in runtimes.rows():
            if r["PORT"] == "-":
                continue
            with self.subTest(runtime=r["RUNTIME"]):
                port = int(r["PORT"])
                self.assertIn(port, by_port,
                              f"{r['RUNTIME']} claims port {port}, which ops/PORTS.tsv does "
                              f"not record. One of the two registries is wrong.")
                surfaces = {p["SURFACE"] for p in by_port[port]}
                self.assertIn(r["SURFACE"], surfaces,
                              f"{r['RUNTIME']} says port {port} serves surface "
                              f"{r['SURFACE']!r}; ops/PORTS.tsv says {surfaces}")

    def test_a_delegated_surface_has_a_runtime_that_can_answer_it(self):
        """The split's own safety rule, from the other side.

        `ports.delegated()` refuses to report a surface delegated without a port. This is
        the complementary check: a delegated surface with no runtime row is a surface the
        monolith has stopped answering and nothing has been recorded as picking up.
        """
        for surface in ports.delegated_surfaces():
            with self.subTest(surface=surface):
                self.assertTrue(runtimes.for_surface(surface),
                                f"surface {surface!r} is DELEGATED in ops/PORTS.tsv but no "
                                f"row in ops/RUNTIMES.tsv says what process answers it")


class SurfaceIsARealRackUnit(unittest.TestCase):
    """`SURFACE` is the `/api/status` unit id, and it is a different namespace from `LEASE`.

    This test exists because the first version of the registry got it wrong twice. It wrote
    `sigil` for two rows -- which is the *governor* surface name -- where the rack unit is
    `sigils`, plural. `apps/ports.py` uses the unit id in the same column, so a `sigil` row
    would have made `runtimes.for_surface("sigils")` return nothing for the id every other
    consumer uses, and the delegation check below would have gone on passing because nothing
    is delegated yet. A vacuous guard beside a wrong value is the worst of both.

    Checked against `appdocs.APPLICATIONS`, the static declaration the rack is built from,
    rather than a live `/api/status` call -- a test that needs the API running is a test that
    gets skipped. `gpuminer` and `train` are legitimate ids: both are `kind="child"`, and they
    do not appear in a flat reading of `/api/status` when their parent has no live sub-units.
    Checking against the live endpoint is exactly how they would have been "corrected" to
    something wrong.
    """

    def test_every_surface_is_an_id_appdocs_declares(self):
        from registry.lib import appdocs
        ids = {a.id for a in appdocs.APPLICATIONS}
        self.assertIn("sigils", ids, "reading appdocs failed; this check would be vacuous")
        self.assertNotIn("sigil", ids, "if `sigil` ever becomes a real unit id, the "
                                       "distinction this test guards has gone away")
        for r in runtimes.rows():
            if r["SURFACE"] == "-":
                continue
            with self.subTest(runtime=r["RUNTIME"], surface=r["SURFACE"]):
                self.assertIn(r["SURFACE"], ids,
                              f"{r['RUNTIME']} claims SURFACE {r['SURFACE']!r}, which is not "
                              f"an /api/status unit id. Governor surface names go in LEASE.")

    def test_the_two_namespaces_are_allowed_to_differ_and_one_does(self):
        """Not a typo to be tidied away: `sigils` the unit, `sigil` the governor surface."""
        row = runtimes.get("symoneural-diffuse", "sigils")
        self.assertIsNotNone(row, "the sigils row is gone or renamed")
        self.assertEqual("sigil", row["LEASE"],
                         "the governor arm is `sigil` singular; changing this to match the "
                         "unit id would silently move the surface to the `*)` default arm")

    def test_appdocs_runtime_labels_are_not_asserted_against_this_registry(self):
        """Recording why the obvious stronger check would be wrong.

        `appdocs` also carries a `runtime` per unit, and asserting it equals this registry's
        RUNTIME looks like the better test. It is not: `appdocs.runtime` is a PRODUCT label --
        `studio` and `train` both say `symoneural-studio`, which is not an artefact on disk --
        while this registry names the thing that is actually executed (`symoneural-ui`'s
        `main.py`, `training/.venv/bin/python`). Two different questions. This test pins the
        difference so nobody "fixes" one to match the other.
        """
        from registry.lib import appdocs
        by_id = {a.id: a.runtime for a in appdocs.APPLICATIONS}
        self.assertEqual("symoneural-studio", by_id["train"])
        self.assertEqual("training", runtimes.get("training", "train")["RUNTIME"])


class AgreesWithTheBuildAuthority(unittest.TestCase):
    def test_every_build_recipe_names_an_existing_component(self):
        known = runtimes.build_recipe_ids()
        self.assertIn("symoneural-llm", known,
                      "BUILD-RECIPES.tsv parsed to something without the llm engine in it; "
                      "this check would then be vacuously green")
        for r in runtimes.rows():
            if r["BUILD_RECIPE"] == "-":
                continue
            with self.subTest(runtime=r["RUNTIME"]):
                self.assertIn(r["BUILD_RECIPE"], known,
                              f"{r['RUNTIME']} points at BUILD_RECIPE "
                              f"{r['BUILD_RECIPE']!r}, which has no row in "
                              f"restore/manifests/BUILD-RECIPES.tsv")

    def test_the_registry_carries_no_build_command_of_its_own(self):
        """Naming a recipe is the point; copying it would recreate the second copy."""
        text = runtimes.REGISTRY.read_text()
        body = "\n".join(ln for ln in text.splitlines() if not ln.lstrip().startswith("#"))
        for smell in ("cargo build", "go build", "cmake ", "fork_engines.sh"):
            self.assertNotIn(smell, body,
                             f"{smell!r} appears in RUNTIMES.tsv. The build authority is "
                             "restore/manifests/BUILD-RECIPES.tsv; this file names a "
                             "COMPONENT_ID and stops.")


class CallSitesAreReal(unittest.TestCase):
    def test_call_site_patterns_resolve_to_exactly_one_line(self):
        for r in runtimes.rows():
            with self.subTest(runtime=r["RUNTIME"], surface=r["SURFACE"]):
                path, line = runtimes.resolve_site(r["CALL_SITE"], "CALL_SITE")
                self.assertTrue(path.is_file())
                self.assertGreater(line, 0)

    def test_lease_sites_resolve_too(self):
        for r in runtimes.rows():
            if r["LEASE_SITE"] == "-":
                continue
            with self.subTest(runtime=r["RUNTIME"], surface=r["SURFACE"]):
                runtimes.resolve_site(r["LEASE_SITE"], "LEASE_SITE")

    def test_an_ambiguous_pattern_is_an_error_not_a_pass(self):
        """The property a bare `in` check cannot have."""
        with self.assertRaises(runtimes.RegistryError) as cm:
            runtimes.resolve_site("backend/runtimes.py::import", "CALL_SITE")
        self.assertIn("matches", str(cm.exception))

    def test_a_vanished_call_site_is_an_error(self):
        with self.assertRaises(runtimes.RegistryError):
            runtimes.resolve_site("backend/server.py::this fragment is not in that file",
                                  "CALL_SITE")

    def test_nothing_invoked_says_so_rather_than_leaving_a_blank(self):
        """A runtime nothing calls is a finding. It must not be silently absent."""
        for r in runtimes.rows():
            if r["INVOCATION"] == "never":
                with self.subTest(runtime=r["RUNTIME"]):
                    self.assertNotEqual("-", r["NOTE"].strip(),
                                        "a runtime nothing invokes must carry a NOTE saying "
                                        "what it is instead")


class ArtefactsAndModels(unittest.TestCase):
    def test_a_row_that_is_not_absent_names_an_artefact_on_disk(self):
        for r in runtimes.rows():
            if r["STATE"] == "absent" or r["ARTEFACT"] == "-":
                continue
            with self.subTest(runtime=r["RUNTIME"], surface=r["SURFACE"]):
                p = ROOT / r["ARTEFACT"]
                self.assertTrue(p.exists(),
                                f"{r['RUNTIME']} is STATE={r['STATE']} but {r['ARTEFACT']} "
                                f"is not on disk. Either it went, or the state is stale.")

    def test_the_two_gpu_engines_name_the_weights_they_were_measured_with(self):
        """Captured live from /proc on 2026-09-10 while each engine was actually running."""
        chat = runtimes.models("symoneural-llm", "chat")
        self.assertEqual(3, len(chat), "chat is model + draft model + LoRA adapter")
        self.assertTrue(any("draft" in p.name for p in chat))
        self.assertTrue(any(p.suffix == ".gguf" and "lora" in p.name.lower() for p in chat))
        image = runtimes.models("symoneural-diffuse", "image")
        self.assertEqual(4, len(image), "flux is unet + vae + clip_l + t5xxl")
        self.assertEqual(image, runtimes.models("symoneural-diffuse", "sigils"),
                         "both surfaces run the same binary on the same weights; if these "
                         "ever diverge the rack is describing two different things")


class LeaseAgreesWithTheGovernor(unittest.TestCase):
    """The rule the lease proof found and no document carried.

    Broken on purpose to check it can fail: deleting the `comfy)` arm from `evict()` reddens
    `test_every_lease_is_known_to_the_governor`, and deleting `image|sigil)` from
    `surface_pattern()` reddens `test_every_lease_can_be_probed_for_liveness`.
    """

    @classmethod
    def setUpClass(cls):
        cls.code = GOVERNOR.read_text()
        cls.evict = cls._block(cls.code, "evict")
        cls.pattern = cls._block(cls.code, "surface_pattern")
        cls.live = cls._block(cls.code, "surface_live")

    @staticmethod
    def _block(code: str, fn: str) -> str:
        m = re.search(rf"^{re.escape(fn)}\(\) \{{\n(.*?)^\}}", code, re.S | re.M)
        assert m, f"{fn}() not found in gpu-governor.sh -- this test is reading the wrong file"
        return m.group(1)

    @staticmethod
    def _arms(block: str) -> set[str]:
        """Every surface name in a shell `case` block, `a|b)` expanded."""
        out: set[str] = set()
        for m in re.finditer(r"^\s{4,}([a-z|*]+)\)", block, re.M):
            out.update(m.group(1).split("|"))
        return out

    def test_the_governor_still_has_the_three_blocks(self):
        """If this fails the parsing above is wrong and every check below is vacuous."""
        self.assertIn("chat", self._arms(self.pattern))
        self.assertIn("*", self._arms(self.evict))
        self.assertIn('surface" = "miner"', self.live)

    def test_every_lease_can_be_probed_for_liveness(self):
        """Probeable by ONE of two routes, and the second one is not a workaround.

        The first draft of this test asserted every lease name appears in
        `surface_pattern()`, and it went red on `miner` -- which looked like a defect, since
        `evict()` does have a `miner)` arm and an arm the probe never reaches would never
        fire. It is not a defect: `surface_live()` special-cases `miner` ahead of the
        pattern lookup and checks the recorded process GROUP instead, because a miner is a
        detached job under `gpu-governor.sh with miner` rather than a process whose command
        line contains a known path. Asserting the mechanism rather than one implementation
        of it is the difference between this test and the wrong version of it.
        """
        known = self._arms(self.pattern)
        for runtime, surface, lease in runtimes.leaseholders():
            with self.subTest(runtime=runtime, surface=surface):
                self.assertTrue(
                    lease in known or f'"{lease}"' in self.live,
                    f"{runtime}/{surface} acquires as {lease!r}, which the governor cannot "
                    f"probe: it is neither an arm of surface_pattern() nor a special case "
                    f"in surface_live(). It falls to `*)`, so the governor reads the wrong "
                    f"processes and reports a live tenant as stale.")

    def test_every_lease_is_known_to_the_governor(self):
        arms = self._arms(self.evict)
        for runtime, surface, lease in runtimes.leaseholders():
            with self.subTest(runtime=runtime, surface=surface):
                if lease == "train":
                    # `train` is answered BEFORE the case and is never evicted to serve a
                    # page view. The refusal is its arm, and it is deliberate.
                    self.assertIn('[ "$prev" = "train" ]', self.evict,
                                  "the train refusal is gone; a fine-tune can now be "
                                  "evicted by a page view")
                    continue
                self.assertIn(lease, arms,
                              f"{runtime}/{surface} acquires the card as {lease!r} but "
                              f"evict() has no arm for it. It falls to `*)`, which gets a "
                              f"patternless drain() reading every compute context against "
                              f"DRAIN_FLOOR_MIB -- so its first acquire behind a resident "
                              f"tenant is refused, and it will look like a lock bug.")

    def test_a_row_with_no_lease_is_not_quietly_a_leaseholder(self):
        """The CPU and no-lease rows are design decisions; each must say so."""
        for r in runtimes.rows():
            if r["LEASE"] != "-":
                continue
            with self.subTest(runtime=r["RUNTIME"], surface=r["SURFACE"]):
                self.assertEqual("-", r["LEASE_SITE"],
                                 "LEASE is '-' but LEASE_SITE names one")


class NoMeasurementsInAHandMaintainedFile(unittest.TestCase):
    def test_nothing_here_carries_a_measurement(self):
        """Sizes and dates go stale silently. They live in the generated doc, dated."""
        body = [ln for ln in runtimes.REGISTRY.read_text().splitlines()
                if ln.strip() and not ln.lstrip().startswith("#")]
        for ln in body:
            with self.subTest(row=ln.split("\t")[0]):
                self.assertIsNone(
                    re.search(r"\b\d{4}-\d{2}-\d{2} \d{2}:\d{2}", ln),
                    "a build timestamp in RUNTIMES.tsv. tools/build_runtimes.py measures "
                    "those fresh into docs/ops/RUNTIMES.md, where they are dated.")
                self.assertIsNone(
                    re.search(r"\b\d{7,}\s*bytes\b", ln),
                    "a byte count in RUNTIMES.tsv; same reason as the timestamp")

    def test_no_line_numbers_are_pinned(self):
        for r in runtimes.rows():
            for field in ("CALL_SITE", "LEASE_SITE"):
                with self.subTest(runtime=r["RUNTIME"], field=field):
                    head = r[field].split(runtimes.SITE_SEP)[0]
                    self.assertIsNone(
                        re.search(r"\.(py|sh|service):\d+$", head),
                        f"{field} pins a line number. api.py is 235 KB; any edit above it "
                        "reddens this, and the fix would be re-stamping the number.")


if __name__ == "__main__":
    unittest.main()
