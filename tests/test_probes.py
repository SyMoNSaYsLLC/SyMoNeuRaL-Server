"""The two probe tools read their targets out of things that move. This pins that.

`tools/probe_apps.py` and `tools/probe_engines.py` are sweeps, and a sweep has one
characteristic way of failing: it silently stops covering something. A new
application mounted without a registry entry, a new engine directory, a `DOORS`
entry naming a route that was renamed, an expectation branch that no longer matches
any app -- none of those make a sweep fail. They make it pass over less, and report
a clean result for a smaller set than the reader believes was checked. Which is the
same failure as a figure carried forward and re-dated: the number looks fine and no
longer describes what it claims to.

So these tests assert COVERAGE and the hand-maintained exception lists, not the
findings. Findings are measurements and belong in `review/`; what belongs here is
that the next application, engine or renamed route cannot slip past unnoticed.

The named exception lists are the fragile part, because each entry is a judgement
somebody made after reading code, and an entry that stops matching a real route
quietly stops excusing anything -- or worse, keeps excusing a route that has since
changed meaning. Every entry is checked against the live router.

No GPU, no engine, no network beyond importing the app object.
"""
import importlib.util
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load(name: str):
    """Import a tool from `tools/`, which is not a package.

    The `sys.modules` registration is required, not tidiness: `probe_apps` defines a
    `@dataclasses.dataclass`, and `dataclasses` resolves the decorated class's
    module through `sys.modules[cls.__module__]` to look for `KW_ONLY`. A module
    executed without being registered there has that lookup return None, and the
    decorator raises `AttributeError: 'NoneType' object has no attribute '__dict__'`
    before any test runs.
    """
    spec = importlib.util.spec_from_file_location(name, ROOT / "tools" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


probe_apps = _load("probe_apps")
probe_engines = _load("probe_engines")


class SweepCoversEveryApplication(unittest.TestCase):
    """A new application must not be able to appear un-swept."""

    @classmethod
    def setUpClass(cls):
        from registry import appdocs
        cls.appdocs = appdocs
        cls.table = probe_apps.route_table()
        cls.paths = {r.path for r in cls.table}

    def test_every_declared_application_gets_an_expectation(self):
        # `expectation()` is a chain of branches over the registry's own `auth`
        # string. A new application whose auth wording matches none of them would
        # fall through to "public" and be waved past the boundary probe, which is
        # the one outcome that must not happen silently.
        from registry import appdocs
        part = probe_apps.partition(self.table)
        for app in appdocs.APPLICATIONS:
            for route in part["owned"][app.id]:
                exp, why = probe_apps.expectation(app, route)
                self.assertIn(exp, probe_apps.EXPECTATIONS,
                              f"{app.id} {route.path} got expectation {exp!r}")
                self.assertTrue(why, f"{app.id} {route.path} has no stated reason")

    def test_a_protected_surface_is_never_classified_public(self):
        # The specific silent failure: an auth string reworded so that neither
        # "loopback" nor "session cookie" nor "operator" appears in it, leaving a
        # credential-bearing surface probed as though nothing guards it.
        from registry import appdocs
        part = probe_apps.partition(self.table)
        for app in appdocs.APPLICATIONS:
            if app.auth.lower().startswith("public"):
                continue
            for route in part["owned"][app.id]:
                exp, _ = probe_apps.expectation(app, route)
                self.assertNotEqual(
                    "public", exp,
                    f"{app.id} declares auth {app.auth[:40]!r} but {route.path} "
                    f"was classified public")

    def test_the_partition_is_split_by_subtree_not_lumped(self):
        part = probe_apps.partition(self.table)
        split = probe_apps.unowned_by_subtree(part["unowned"])
        self.assertEqual({"api", "local"}, set(split))
        for row in split["api"]:
            self.assertIn("/api/", row)
        for row in split["local"]:
            self.assertIn("/local/", row)


class NamedExceptionsStillMatchRealRoutes(unittest.TestCase):
    """Each hand-written exception is a judgement about a route that must still exist."""

    @classmethod
    def setUpClass(cls):
        cls.table = probe_apps.route_table()
        cls.paths = {r.path for r in cls.table}

    def test_every_door_is_a_registered_route(self):
        stale = sorted(p for p in probe_apps.DOORS if p not in self.paths)
        self.assertEqual([], stale,
                         f"DOORS names {stale}, which the router does not have. A "
                         f"door that no longer exists excuses nothing and hides that "
                         f"its replacement is being probed as protected")

    def test_every_deliberate_404_is_a_registered_route(self):
        stale = sorted(p for p in probe_apps.DELIBERATE_404 if p not in self.paths)
        self.assertEqual([], stale,
                         f"DELIBERATE_404 names {stale}, which the router does not "
                         f"have; the exemption would go on excusing a path nobody "
                         f"serves")

    def test_every_deliberate_404_carries_its_evidence(self):
        for path, why in probe_apps.DELIBERATE_404.items():
            self.assertIn(".py:", why,
                          f"{path} is excused without a file:line to check it against")

    def test_the_spoof_set_covers_the_headers_the_guard_checks(self):
        # If `_require_local`'s list ever grows a name this set does not send, the
        # sweep would stop testing the header it just started checking -- and would
        # report a clean pass for having asked a narrower question.
        src = (ROOT / "backend" / "server.py").read_text()
        # Read the CONSTANT, not the function body. This regexed a literal tuple inline in
        # `_require_local`, and broke the moment the list was lifted out to
        # `api._PROXY_HEADERS` -- reporting "no longer a literal tuple" rather than anything
        # about coverage. A guard that inspects source shape breaks when the shape improves;
        # importing the value cannot.
        import server as api
        checked = {h.lower() for h in api._PROXY_HEADERS}
        self.assertTrue(checked, "api._PROXY_HEADERS is empty, so nothing is checked")
        sent = {k.lower() for h in probe_apps.SPOOF_HEADERS for k in h}
        self.assertTrue(checked <= sent,
                        f"_require_local checks {sorted(checked - sent)} which the "
                        f"probe never sends")


class MethodsComeFromTheRouter(unittest.TestCase):
    """The 2026-08-26 lesson, as a test: never guess a verb."""

    @classmethod
    def setUpClass(cls):
        cls.table = probe_apps.route_table()

    def test_a_prefix_with_no_route_of_its_own_has_no_verb(self):
        # `/api/sigils` is a mount prefix. An earlier revision posted to it, got
        # 405, and recorded a working surface as broken.
        self.assertIsNone(probe_apps.method_for(self.table, "/api/sigils"))

    def test_the_compute_and_gpu_targets_all_have_a_real_verb(self):
        for path in list(probe_apps.COMPUTE) + list(probe_apps.GPU_LAST):
            self.assertIsNotNone(
                probe_apps.method_for(self.table, path),
                f"{path} is a probe target with no verb on the router")

    def test_path_parameters_are_filled_with_something_that_cannot_name_a_record(self):
        filled = probe_apps.concrete("/api/dispatchos/bookings/{bid}/advance")
        self.assertNotIn("{", filled)
        self.assertIn("probe-nonexistent", filled)


class EngineAuditCoversEveryEngine(unittest.TestCase):

    def test_every_engine_directory_is_declared(self):
        # The silent failure for this tool: a sixth engine appears under engines/
        # and the audit reports "5 of 5 built" without ever looking at it.
        # A DERIVED engine, not merely a directory whose name starts with symoneural-.
        # After 2026-09-08 the repo root also holds symoneural-api/, symoneural-code/,
        # symoneural-audit/ and symoneural-adaptive-fabric/, which are first-party source
        # and not engines at all -- a name prefix cannot tell them apart. What can is
        # THIRD_PARTY_NOTICES.md: fork_engines.sh writes one into every tree it derives
        # from an upstream, and nothing writes one into code we authored.
        on_disk = {p.name for p in ROOT.iterdir()
                   if p.is_dir() and p.name.startswith("symoneural-")
                   and (p / "THIRD_PARTY_NOTICES.md").is_file()}
        declared = {e["id"] for e in probe_engines.ENGINES}
        self.assertEqual(set(), on_disk - declared,
                         f"a derived engine tree {sorted(on_disk - declared)} exists which "
                         f"probe_engines.ENGINES does not declare")
        self.assertEqual(set(), declared - on_disk,
                         f"ENGINES declares {sorted(declared - on_disk)} with no "
                         f"directory")

    def test_an_engine_with_no_binary_states_why(self):
        for e in probe_engines.ENGINES:
            if e["binary"] is None:
                self.assertTrue(e.get("note"),
                                f"{e['id']} is declared unbuilt with no reason given")

    def test_only_identity_surfaces_are_authorship_tier(self):
        for where in ("version", "server_header", "model_owner"):
            self.assertEqual("authorship", probe_engines.tier_of(where))
        for where in ("help", "flag_description", "url"):
            self.assertEqual("reference", probe_engines.tier_of(where))

    def test_a_project_name_is_not_shadowed_by_the_vocabulary_list(self):
        # `ggml-org` contains `ggml`, and `ggml` is deliberately vocabulary rather
        # than a project name. The scan runs the two lists separately for exactly
        # this reason: were `ggml` allowed to absorb the hit, an announced
        # `github.com/ggml-org` URL would be filed as harmless library vocabulary.
        line = "see https://github.com/ggml-org/llama.cpp/pull/13194"
        projects = probe_engines.scan(line, probe_engines.PROJECT_NAMES)
        self.assertIn("ggml-org", projects)
        self.assertIn("llama.cpp", projects)

    def test_the_serving_exclusions_are_named_and_reasoned(self):
        # Each excluded field is a decision not to relitigate; the docstring must
        # carry the reasoning, because an unexplained exclusion is indistinguishable
        # from a blind spot.
        self.assertIn("chat_template", probe_engines.SERVING_SCAN_EXCLUDE)
        doc = probe_engines.__doc__ or ""
        src = (ROOT / "tools" / "probe_engines.py").read_text()
        self.assertIn("api.py:2823", src,
                      "the chat_template exclusion no longer cites the file:line "
                      "that argues for it")
        self.assertTrue(doc.strip())


if __name__ == "__main__":
    unittest.main()
