"""Exp tests. Standard library and `unittest` only -- no network, no GPU, no fixtures.

**Why the import list matters more than usual here.** `apps/studio/plugins/reinforce/tests` and
`apps/remix/tests` are excluded from the suite by `--ignore` because they import `cupy` and
`symon_capture`, which are not installed on the system interpreter and never may be: it is the
serving path. A test file that needs a third dependency would make this a third `--ignore`, and
`.claude/CLAUDE.md` says to say so loudly rather than let a collected count quietly become
"collected 12". So this file imports nothing that is not already in the serving path: `unittest`,
`asyncio`, `re`, `pathlib`, this package, and `yaml` only indirectly, through the loader, which
imports it lazily and which `backend/server.py` already imports on every boot.

`routes` -- and therefore FastAPI -- is imported by `_routes()` inside the tests that read it,
never at module scope. `__init__.py` goes to the trouble of making `router` a PEP-562 lazy
attribute so a box without FastAPI fails at the API's import line instead of aborting collection
here; a `from . import router` at the top of this file would quietly undo that.

`asyncio.run` per test rather than a plugin: the runtime is async, and a fresh event loop per
test is also a fresh `Loader`, which is what keeps these tests from leaking mounted state into
each other. Nothing here touches the process-wide loader that `__init__.runtime()` hands the
API -- mounting into that would mount into the live process.

What is asserted here is what cannot be checked by looking at the page or by reading the code:

* **temporal composability** -- effects are undone in reverse registration order, measured by
  recording the order rather than by trusting `reversed()` in the source
* **spatial composability** -- two isolated groups providing one name produce two services with
  different values, and neither is the other's
* **hot-plug in both directions** -- a fiber with a missing dependency is PENDING and not
  FAILED, becomes ACTIVE when the dependency arrives, and goes back to PENDING when it leaves
* **the read/write line** -- every POST handler in `routes.py` calls `_guard`, and no GET handler
  does. This one is source inspection on purpose: it is a claim about a set of functions, and
  the way it breaks is somebody adding a thirteenth route
* **`config` never leaks** -- `Entry.snapshot(with_config=False)` has no `config` key at all
* **the page's ids exist** -- every `getElementById` in `page.js` matches an `id=` in
  `page.html`, because a typo there renders nothing and raises nothing
* **the docs the source promises exist** -- four modules cite files under `docs/`; a citation to
  a file that is not there is a lie in shipped prose

Nothing here starts the API, takes the GPU lock or calls an LLM.
"""
from __future__ import annotations

import asyncio
import contextlib
import inspect
import pathlib
import re
import shutil
import sys
import tempfile
import types
import unittest
from unittest import mock

from . import fiber as fibermod
from . import cli, gate, loader as loadermod
from . import registry
from .context import Context, ContextError, Runtime
from .plugins import CATALOGUE

APP = next(_p for _p in pathlib.Path(__file__).resolve().parents if (_p / "backend" / "server.py").is_file())

#: The repository root, WALKED for by its marker rather than counted to. `APP.parents[2]`
#: was the root while this package sat at `backend/symoneuralexp`; moving it to
#: `backend/studio/plugins/exp` made the same expression resolve to `backend/apps`,
#: which exists -- so the docs assertions below started reporting that repo-level docs were
#: missing, three directories from the cause. Counting levels breaks silently every time
#: this tree is reorganised; a walk does not.
ROOT = next(_p for _p in APP.parents if (_p / "backend" / "server.py").is_file())

#: This module's own import name, used to build `module:attribute` refs for the plugins defined
#: below. `__name__` and not the literal `studio.plugins.exp.test_exp`: pytest imports this file
#: as `symoneuralexp.test_exp` (it inserts `apps/` on the path), so a hard-coded ref makes
#: `importlib` load a *second copy* of this module, and the plugins then append to a different
#: `ORDER` list than the one the assertion reads. That failure looks like "teardown did not run".
HERE = __name__


def _routes():
    """`routes` imported inside the tests that need it, never at module scope.

    `__init__.py` exposes `router` through a PEP-562 `__getattr__` so that a box without FastAPI
    fails at the API's own import line instead of aborting pytest *collection* for this whole
    file. A module-scope `from . import router` here would import FastAPI at collection time and
    defeat exactly that -- the laziness would still be in the source and would no longer be worth
    anything. FastAPI is in the serving path on this box, so the skip below is the unusual case
    and not the expected one.
    """
    try:
        from . import router
    except ImportError as exc:                # pragma: no cover -- fastapi is a serving-path dep
        raise unittest.SkipTest(f"fastapi is not importable: {exc}") from exc
    return routes

#: Teardown order, appended to by `three_effects` below. Reset by the test that reads it.
ORDER: list[int] = []


# ---------------------------------------------------------------------------
# plugins defined here, used by the lifecycle tests through `module:attribute` refs
# ---------------------------------------------------------------------------
def provider(ctx, config):
    """Provides `probe`, carrying whatever value it was configured with."""
    ctx.provide("probe", {"value": config.get("value", 1)})


provider.schema = {"value": (int, 1)}


def consumer(ctx, config):
    """Declares `probe` and republishes what it saw, so the test can prove which one it got."""
    ctx.provide("saw", ctx.probe["value"])


consumer.inject = ["probe"]


def three_effects(ctx, config):
    """Registers three cleanups. Their order on the way out is the whole point."""
    for n in (1, 2, 3):
        ctx.effect(lambda n=n: ORDER.append(n))


def wants_a_float(ctx, config):
    """Schema-checked. Mounted with a string, it fails validation -- and the message it fails
    with is what the closeout review found publishing config values to an open endpoint."""


wants_a_float.schema = {"interval": (float, 1.0)}


#: Appended to by `disposes_itself_twice`. Reset by the test that reads it.
DISPOSED: list[int] = []


def disposes_itself_twice(ctx, config):
    """Registers one cleanup and calls its disposer twice, which is what a plugin that tidies up
    early and then gets torn down amounts to."""
    undo = ctx.effect(lambda: DISPOSED.append(1))
    undo()
    undo()


def mounts_a_child_then_raises(ctx, config):
    """A parent that mounts a child and then fails. The child must not survive it."""
    ctx.plugin(provider, {"value": 99}, name="orphan-child")
    raise RuntimeError("parent failed after mounting a child")


class _AlwaysChanges:
    """A stand-in fiber whose reconcile never settles.

    `Runtime.settle` only ever calls `_reconcile()` on the things in `runtime.fibers` and stops
    when a whole pass reports no change, so this is the smallest thing that reaches MAX_PASSES.
    Building a genuinely oscillating pair of real plugins would test the plugins; this tests the
    backstop, which is the part that has to hold whatever the plugins do.
    """

    def __init__(self) -> None:
        self.id = "always-changes"
        self.passes = 0

    async def _reconcile(self) -> bool:
        self.passes += 1
        return True


class Stateful:
    """The class form: the instance is kept alive by the fiber, so `self` is plugin state."""

    def __init__(self, ctx, config):
        self.calls = 0
        ctx.provide("counter", self)

    def bump(self):
        self.calls += 1
        return self.calls


def run(coro):
    return asyncio.run(coro)


async def fresh(manifest):
    """A `Loader` of its own, with `manifest` applied. Never the process-wide one."""
    loader = loadermod.Loader(Runtime())
    await loader.apply(manifest, label="test")
    return loader


#: Filled by `llm_consumer` below. The kwargs it *received*, which is the only place an
#: `intercept` default is observable: the caller never passes it and the provider cannot tell it
#: from an explicit argument.
CALLS: list[dict] = []


def llm_service(ctx, config):
    """Provides `llm`. Its one method reports what it was called with, nothing more."""

    class Echo:
        def complete(self, prompt, **kwargs):
            return {"prompt": prompt, "kwargs": dict(kwargs)}

    ctx.provide("llm", Echo())


def llm_consumer(ctx, config):
    CALLS.append(ctx.llm.complete("hello"))


llm_consumer.inject = ["llm"]


def state_of(loader, entry_id):
    return loader.find(entry_id).snapshot(with_config=False)["state"]


#: The one plugin shape that has no file behind it. `registry.resolve` accepts it -- an object
#: with `.apply(ctx, config)` -- and it is assembled here at import time rather than defined as
#: a class, so it carries no `__module__` at all: `hasattr(NAMESPACE_PLUGIN, "__module__")` is
#: False on 3.13.5, not None. `ReloadTests` is about what `Loader.reload` may claim about it.
NAMESPACE_PLUGIN = types.SimpleNamespace(apply=lambda ctx, config: None)

#: What a probe module writes on every execution, so "was it re-executed" is a count on disk
#: rather than a belief. Set by `probe_module` for the duration of one test.
PROBE_SOURCE = """import pathlib

with pathlib.Path({counter!r}).open("a") as fh:
    fh.write("exec\\n")


def apply(ctx, config):
    return None


class Plug:
    def apply(self, ctx, config):
        return None


PLUGIN = Plug()
"""


@contextlib.contextmanager
def probe_module():
    """An importable-by-name module on `sys.path` that records each execution of its body.

    Not a path `use:`, deliberately. `_from_path` calls `exec_module` every time it is asked, so
    a path-loaded plugin is re-executed by `resolve_ref` whether or not anything reloaded it,
    and it cannot discriminate the case these tests are about. A module with a real name on
    `sys.path` goes through the finders, which is the ordinary case in every preset.

    Yields `(name, execs)` where `execs()` is the count so far.
    """
    with tempfile.TemporaryDirectory() as tmp:
        root = pathlib.Path(tmp)
        counter = root / "execs.log"
        counter.write_text("")
        name = "expprobe_reload"
        (root / f"{name}.py").write_text(PROBE_SOURCE.format(counter=str(counter)))
        sys.path.insert(0, str(root))
        try:
            yield name, lambda: counter.read_text().count("exec")
        finally:
            sys.path.remove(str(root))
            sys.modules.pop(name, None)


@contextlib.contextmanager
def watch_reloads(loader):
    """Collect the `reason` of every `hmr/reload` emitted while the block runs, oldest first.

    Subscribed straight into `runtime.listeners` rather than through `Context.on`, which
    registers its own unsubscribe as an effect and therefore wants a fiber to hang it on.
    `hmr/reload` is a runtime event delivered to listeners and is *not* written to the trace
    ring -- `Runtime.emit` records only `listener/error` -- so a listener is the only place the
    reason is observable at all.

    Two reasons arrive per reload: the loader's, and then `"requested"` from `Fiber.restart`
    underneath it. The loader's is the one under test and it is first.
    """
    seen: list[str] = []
    entry = (-1, lambda fiber, reason=None: seen.append(reason))
    loader.runtime.listeners.setdefault("hmr/reload", []).append(entry)
    try:
        yield seen
    finally:
        bucket = loader.runtime.listeners.get("hmr/reload") or []
        if entry in bucket:
            bucket.remove(entry)


# ---------------------------------------------------------------------------
class RegistryTests(unittest.TestCase):
    def test_all_four_plugin_shapes_resolve(self):
        import types

        def as_function(ctx, config):
            pass

        class AsClass:
            def __init__(self, ctx, config):
                pass

        as_object = types.SimpleNamespace(apply=lambda ctx, config: None)
        as_module = types.ModuleType("fake_plugin_module")
        as_module.apply = lambda ctx, config: None

        for target, expected in ((as_function, "function"), (AsClass, "class"),
                                 (as_object, "object"), (as_module, "module")):
            with self.subTest(kind=expected):
                self.assertEqual(registry.resolve(target).kind, expected)

    def test_something_that_is_not_a_plugin_says_what_a_plugin_is(self):
        with self.assertRaises(ContextError) as caught:
            registry.resolve(42)
        message = str(caught.exception)
        # The error is the documentation for anyone who gets it, so it has to name all four
        # accepted shapes rather than say "expected a plugin".
        for form in ("function", "class", "apply", "module"):
            self.assertIn(form, message)

    def test_a_string_inject_is_one_dependency_and_not_eight_letters(self):
        def one(ctx, config):
            pass

        one.inject = "llm"
        self.assertEqual(registry.resolve(one).required, ("llm",))

    def test_every_catalogue_plugin_describes_without_being_mounted(self):
        for short in CATALOGUE:
            with self.subTest(plugin=short):
                described = registry.describe(
                    loadermod.resolve_ref(f"studio.plugins.exp.plugins.{short}"))
                self.assertIn(described["kind"],
                              ("function", "class", "object", "module"))
                self.assertTrue(described["doc"],
                                f"{short} has no docstring; the catalogue table on the page "
                                f"renders this field verbatim, so an empty one ships")
                for key, spec in described["schema"].items():
                    self.assertIn("type", spec, f"{short}.{key} has no declared type")


    def test_a_yaml_true_is_refused_by_every_field_that_is_not_a_bool(self):
        """`check_config`'s fast path rejects `bool` for an `int` field and its comment says the
        principle. The principle did not hold for the other two.

        `bool` subclasses `int`, so `isinstance(True, int)` is True and the fast path catches
        it. But `isinstance(True, float)` and `isinstance(True, str)` are both False, so a bool
        written against a float or a str field skipped that branch entirely and landed in
        `_coerce`, whose tests are `isinstance(value, (int, str))` for float and
        `isinstance(value, (int, float))` for str -- and a bool passes both. `interval: true`
        therefore became `1.0` on a float field and `"True"` on a str one, silently, which is
        exactly the repair the `int` branch exists to refuse.

        The string coercions are the point of `_coerce` and must keep working, so they are
        asserted in the same test: killing the bool leak by dropping `int` from the float test
        would take `"1.5"` with it.
        """
        class Runner:
            label = "probe"
            schema = {"flag": (bool, False), "n": (int, 0), "x": (float, 0.0), "s": (str, "")}

        for key, want in (("n", "int"), ("x", "float"), ("s", "str")):
            with self.subTest(field=key):
                with self.assertRaises(ContextError) as caught:
                    registry.check_config(Runner(), {key: True})
                self.assertIn(f"{key!r} wants {want}, got bool", str(caught.exception))

        # A bool for a bool field is not the trap and must still pass, as must the quoted forms
        # `_coerce` exists for. Without this half the guard could be `return _NO` unconditionally
        # and the test above would still be green.
        self.assertEqual(registry.check_config(Runner(), {"flag": True})["flag"], True)
        for given, expect in (({"flag": "true"}, ("flag", True)),
                              ({"flag": "FALSE"}, ("flag", False)),
                              ({"n": "5"}, ("n", 5)),
                              ({"x": "1.5"}, ("x", 1.5)),
                              ({"s": 7}, ("s", "7"))):
            with self.subTest(given=given):
                key, value = expect
                self.assertEqual(registry.check_config(Runner(), dict(given))[key], value)


class PresetTests(unittest.TestCase):
    def test_every_preset_parses_and_names_are_what_the_files_are_called(self):
        names = loadermod.presets()
        self.assertIn("dev", names)
        for name in names:
            with self.subTest(preset=name):
                entries = loadermod.load_manifest(loadermod.preset_path(name))
                self.assertTrue(entries, f"{name}.yaml parsed to nothing")

    def test_dev_resolves_every_ref_it_names(self):
        # `dev` is the preset that mounts into the live API process on first request, so a
        # `use:` in it that does not resolve is a 500 on `/api/exp/state` for a visitor.
        for raw in loadermod.load_manifest(loadermod.preset_path("dev")):
            for entry in loadermod.Entry(raw).walk():
                if entry.use:
                    with self.subTest(use=entry.use):
                        loadermod.resolve_ref(entry.use)

    def test_dev_leaves_the_only_perpetual_worker_disabled(self):
        # `clock` is the one entry that runs forever once mounted, and `dev` mounts into the
        # live API process. Enabled by default it would tick in production for anyone who loaded
        # the page. Regression test for a default, not a style preference.
        clock = [loadermod.Entry(raw) for raw in
                 loadermod.load_manifest(loadermod.preset_path("dev"))]
        by_id = {e.id: e for e in clock}
        self.assertIn("clock", by_id)
        self.assertTrue(by_id["clock"].disabled)

    def test_switching_presets_leaves_the_shared_bus_alone(self):
        """The claim on the page's Mount button and in `routes.py::mount_preset`.

        The reading that discriminates is the **service object**, not the fiber id. A changed
        config keeps the fiber id too -- `_patch_fiber` calls `Fiber.restart`, which unwinds and
        re-mounts the same handle -- so an assertion on the id alone would pass while `Bus` was
        rebuilt underneath it and every subscriber was dropped. `dev` and `failures` give `bus`
        the same config on purpose, so the entry is left running: same fiber, same instance.
        """
        async def go():
            loader = loadermod.Loader(Runtime())
            await loader.apply(loadermod.preset_path("dev"), label="dev")
            before = loader.find("bus").fiber
            instance = loader.runtime.services[":bus"].value
            self.assertIsNotNone(before)
            await loader.apply(loadermod.preset_path("failures"), label="failures")
            self.assertIs(loader.find("bus").fiber, before)
            self.assertIs(loader.runtime.services[":bus"].value, instance,
                          "switching presets rebuilt `bus`: the two manifests now disagree about "
                          "its config, so the page's 'a diff, not a rebuild' claim is false and "
                          "every subscriber was dropped on the way")
            self.assertEqual(state_of(loader, "bus"), fibermod.ACTIVE)
            # And the rest of the graph really did change, or the assertion above is vacuous.
            self.assertIn("no-such-module", [e.id for e in loader.all_entries()])
        run(go())

    def test_failures_lands_exactly_as_its_header_says(self):
        """That header is a table of measured states. If the preset changes, it goes stale."""
        async def go():
            loader = await fresh(loadermod.preset_path("failures"))
            got = {e.id: e.snapshot(with_config=False)["state"] for e in loader.all_entries()}
            self.assertEqual(got, {"bus": fibermod.ACTIVE,
                                   "no-such-module": fibermod.FAILED,
                                   "bad-config": fibermod.FAILED,
                                   "raises": fibermod.FAILED,
                                   "undeclared": fibermod.FAILED,
                                   "waiting-room": "group",
                                   "waiting": fibermod.PENDING,
                                   "off": "disabled"})
        run(go())

    def test_the_yaml_boolean_trap_is_still_defused(self):
        # YAML 1.1 reads the bare word `off` as False. `failures.yaml` quotes it, so the id
        # survives as a string and the entry is addressable by the word its author typed.
        ids = [loadermod.Entry(raw).id for raw in
               loadermod.load_manifest(loadermod.preset_path("failures"))]
        self.assertIn("off", ids)

    def test_an_unquoted_boolean_id_raises_instead_of_becoming_the_word_False(self):
        """This assertion used to read `== "False"`, which is what the code did.

        Naming an entry "False" is not a rescue: `POST /remove {"id": "off"}` cannot find it,
        `{"id": "False"}` is not a spelling anyone would guess, and the manifest and the running
        graph disagree with no error anywhere. The message has to reach the person editing the
        YAML, so it raises and quotes the fix.
        """
        for given, quoted in ((False, 'id: "off"'), (True, 'id: "on"')):
            with self.subTest(given=given):
                with self.assertRaises(ContextError) as caught:
                    loadermod.Entry({"id": given, "use": "x.y"})
                self.assertIn(quoted, str(caught.exception))
        # A string that merely looks like one is untouched -- the trap is the YAML parser, not
        # the word.
        self.assertEqual(loadermod.Entry({"id": "off", "use": "x.y"}).id, "off")


class LifecycleTests(unittest.TestCase):
    def test_a_provided_service_reaches_the_plugin_that_declared_it(self):
        async def go():
            loader = await fresh({"plugins": [
                {"id": "p", "use": f"{HERE}:provider", "config": {"value": 7}},
                {"id": "c", "use": f"{HERE}:consumer"},
            ]})
            self.assertEqual(state_of(loader, "c"), fibermod.ACTIVE)
            self.assertEqual(loader.root.get("saw"), 7)
        run(go())

    def test_effects_are_undone_in_reverse_registration_order(self):
        async def go():
            ORDER.clear()
            loader = await fresh({"plugins": [{"id": "e", "use": f"{HERE}:three_effects"}]})
            self.assertEqual(ORDER, [], "effects ran on the way in, not on the way out")
            await loader.remove("e")
            # Reverse order is not decoration. An effect registered second may depend on what
            # the first one set up, and undoing forwards tears the ground out from under it.
            self.assertEqual(ORDER, [3, 2, 1])
        run(go())

    def test_a_missing_dependency_is_pending_and_not_failed(self):
        async def go():
            loader = await fresh({"plugins": [{"id": "c", "use": f"{HERE}:consumer"}]})
            snap = loader.find("c").snapshot(with_config=False)
            self.assertEqual(snap["state"], fibermod.PENDING)
            self.assertIsNone(snap["error"], "waiting is not an error and must not read as one")
            fiber = [f for f in loader.runtime.fibers if f.id == snap["fiber"]][0]
            self.assertEqual(fiber.snapshot()["missing"], ["probe"])
        run(go())

    def test_hot_plug_runs_in_both_directions(self):
        async def go():
            loader = await fresh({"plugins": [{"id": "c", "use": f"{HERE}:consumer"}]})
            self.assertEqual(state_of(loader, "c"), fibermod.PENDING)

            await loader.add({"id": "p", "use": f"{HERE}:provider", "config": {"value": 3}})
            self.assertEqual(state_of(loader, "c"), fibermod.ACTIVE)
            self.assertEqual(loader.root.get("saw"), 3)

            # And back. Removing the provider must not fail the consumer -- it waited before the
            # service existed and it waits again now, which is the same state for the same
            # reason.
            await loader.remove("p")
            self.assertEqual(state_of(loader, "c"), fibermod.PENDING)
            self.assertIsNone(loader.root.get("saw"))
        run(go())

    def test_two_isolated_groups_provide_one_name_twice(self):
        async def go():
            loader = await fresh({"plugins": [
                {"id": "a", "isolate": ["probe"], "plugins": [
                    {"id": "a-p", "use": f"{HERE}:provider", "config": {"value": 10}}]},
                {"id": "b", "isolate": ["probe"], "plugins": [
                    {"id": "b-p", "use": f"{HERE}:provider", "config": {"value": 20}}]},
            ]})
            probes = [s for s in loader.runtime.services.values() if s.name == "probe"]
            self.assertEqual(len(probes), 2, "the two realms collapsed into one service")
            self.assertNotEqual(probes[0].key, probes[1].key)
            self.assertEqual(sorted(p.value["value"] for p in probes), [10, 20])
            # The point of isolation is that neither realm is the shared container. A root
            # reader sees no `probe` at all.
            self.assertIsNone(loader.root.get("probe"))
        run(go())

    def test_two_plugins_providing_one_name_in_one_realm_is_an_error_that_says_isolate(self):
        async def go():
            loader = await fresh({"plugins": [
                {"id": "p1", "use": f"{HERE}:provider"},
                {"id": "p2", "use": f"{HERE}:provider"},
            ]})
            second = loader.find("p2").snapshot(with_config=False)
            self.assertEqual(second["state"], fibermod.FAILED)
            self.assertIn("isolate", second["error"])
        run(go())

    def test_a_class_plugin_keeps_its_state_while_it_is_mounted(self):
        async def go():
            loader = await fresh({"plugins": [{"id": "s", "use": f"{HERE}:Stateful"}]})
            counter = loader.root.get("counter")
            self.assertEqual([counter.bump(), counter.bump()], [1, 2])
            # ...and loses it on the way out, which is the half that makes it a plugin rather
            # than a global.
            await loader.remove("s")
            self.assertIsNone(loader.root.get("counter"))
        run(go())

    def test_the_deliberately_broken_preset_produces_every_failure_it_documents(self):
        async def go():
            loader = await fresh(loadermod.preset_path("failures"))
            states = {e["id"]: e["state"]
                      for e in (x.snapshot(with_config=False) for x in loader.all_entries())}
            self.assertIn(fibermod.FAILED, states.values(),
                          f"nothing failed in failures.yaml: {states}")
            self.assertIn(fibermod.PENDING, states.values(),
                          f"nothing is waiting in failures.yaml: {states}")
            # Every failure is reported with a message. A FAILED fiber with `error: null` would
            # be the one state this runtime must never produce, because it is indistinguishable
            # from a bug in the runtime itself.
            for entry in loader.all_entries():
                snap = entry.snapshot(with_config=False)
                if snap["state"] == fibermod.FAILED:
                    self.assertTrue(snap["error"], f"{snap['id']} failed silently")
        run(go())

    def test_settling_converges_on_an_ordinary_manifest(self):
        async def go():
            loader = await fresh({"plugins": [
                {"id": "p", "use": f"{HERE}:provider"},
                {"id": "c", "use": f"{HERE}:consumer"},
            ]})
            # Converged means both ACTIVE *and* nothing recorded as unsettled. A bound on
            # `len(trace.tail(500))` would hold for every trace this runtime can produce and so
            # would assert nothing; `runtime/unsettled` is the row that appears only when
            # `settle` gave up, which is the thing being denied here.
            self.assertEqual([state_of(loader, "p"), state_of(loader, "c")],
                             [fibermod.ACTIVE, fibermod.ACTIVE])
            self.assertIsNone(loader.runtime.settle_error)
            self.assertEqual([e for e in loader.runtime.trace.tail(500)
                              if e["event"] == "runtime/unsettled"], [])
        run(go())

    def test_an_oscillating_graph_is_reported_and_not_only_raised(self):
        """`registry.mount` launches `settle()` as a task, so a raise on that path reaches
        nobody. The failure has to be on the runtime and in the trace as well."""
        async def go():
            runtime = Runtime()
            stuck = _AlwaysChanges()
            runtime.fibers.append(stuck)
            with self.assertRaises(ContextError):
                await runtime.settle()
            self.assertEqual(stuck.passes, Runtime.MAX_PASSES)
            self.assertIsNotNone(runtime.settle_error)
            self.assertIn("did not settle", runtime.settle_error)
            events = [e for e in runtime.trace.tail(50) if e["event"] == "runtime/unsettled"]
            self.assertEqual(len(events), 1, "the give-up is not in the trace")
        run(go())

    def test_the_settle_failure_travels_in_the_state_payload(self):
        async def go():
            loader = await fresh({"plugins": [{"id": "p", "use": f"{HERE}:provider"}]})
            self.assertIn("settle_error", loader.state(),
                          "the page cannot show a wedged runtime it is never told about")
            self.assertIsNone(loader.state()["settle_error"])
        run(go())


class ReloadTests(unittest.TestCase):
    """`Loader.reload` may only report a reload it performed.

    This path had no test at all until B14. The defect it hides is quiet by construction: a
    plugin with no module to re-execute took the same 200, the same `error: null` and the same
    `hmr/reload reason="module-reloaded"` as a plugin whose file had just been read off disk.
    The fiber did restart in both cases, so the page animated and nothing looked wrong -- which
    is why an editor could sit there re-saving a file and watching a reload that never happened.
    """

    def test_reload_of_an_assembled_object_reports_that_nothing_was_reimported(self):
        async def go():
            loader = await fresh({"plugins": [{"id": "ns", "use": f"{__name__}:NAMESPACE_PLUGIN"}]})
            self.assertEqual(state_of(loader, "ns"), fibermod.ACTIVE)
            with watch_reloads(loader) as seen:
                entry = await loader.reload("ns")
            # The fiber really did restart -- that half was never broken and is not being
            # removed. What is new is that the entry now says what did not happen.
            self.assertEqual(state_of(loader, "ns"), fibermod.ACTIVE)
            self.assertIsNotNone(entry.error, "a reload that re-imported nothing reported clean")
            self.assertIn("nothing was re-imported", entry.error)
            self.assertIn("sys.modules", entry.error)
            self.assertEqual(seen[0], "rebound-only")
            self.assertNotIn("module-reloaded", seen)
        run(go())

    def test_reload_of_a_module_plugin_re_executes_the_file_and_reports_clean(self):
        async def go():
            with probe_module() as (name, execs):
                loader = await fresh({"plugins": [{"id": "p", "use": name}]})
                self.assertEqual(execs(), 1, "mounting did not import the module once")
                with watch_reloads(loader) as seen:
                    entry = await loader.reload("p")
                self.assertEqual(execs(), 2, "reload did not re-execute the module body")
                self.assertIsNone(entry.error)
                self.assertEqual(seen[0], "module-reloaded")
                self.assertEqual(state_of(loader, "p"), fibermod.ACTIVE)
        run(go())

    def test_reload_of_a_class_instance_plugin_re_executes_its_file_too(self):
        """The shape a `__module__`-only guard would have broken.

        An instance has no `__name__` and is neither a class nor a routine, so a guard written
        around those predicates returns None for it and turns this working reload into the
        no-op the test above now detects. `__module__` inherited from the type names the file
        the class was defined in, which is the file the editor just changed, so it is the right
        answer and the body of `_module_of` is left alone.
        """
        async def go():
            with probe_module() as (name, execs):
                loader = await fresh({"plugins": [{"id": "p", "use": f"{name}:PLUGIN"}]})
                target = loader.find("p").fiber.runner.target
                self.assertFalse(inspect.isclass(target) or inspect.isroutine(target))
                self.assertEqual(execs(), 1)
                with watch_reloads(loader) as seen:
                    entry = await loader.reload("p")
                self.assertEqual(execs(), 2, "an instance plugin no longer reloads its file")
                self.assertIsNone(entry.error)
                self.assertEqual(seen[0], "module-reloaded")
        run(go())

    def test_a_path_use_is_not_reported_as_unreloadable(self):
        """`_from_path` execs on every resolve, so a path plugin is always running new code.

        It reaches `resolve_ref` by a route that re-reads the file regardless of what
        `_module_of` answered, so the skip message would be false about it even when the module
        lookup comes back empty. That is why the flag is `module is None and not from_disk`.
        """
        async def go():
            loader = await fresh({"plugins": [{"id": "clock", "use": "plugins/clock.py"}]})
            with watch_reloads(loader) as seen:
                entry = await loader.reload("clock")
            self.assertIsNone(entry.error)
            self.assertEqual(seen[0], "module-reloaded")
        run(go())


class DisposedFiberTests(unittest.TestCase):
    """A disposed fiber is not restartable, and neither `restart` nor `/reload` may pretend.

    `dispose` takes the fiber out of `runtime.fibers`, so `settle` never looks at it again. Every
    assertion here failed before B16: `restart` returned the same disposed object having done
    nothing, with `reloads` one higher, and `Loader.reload` handed that straight back as a 200.
    """

    def test_restart_on_a_disposed_fiber_raises_instead_of_doing_nothing(self):
        async def go():
            loader = await fresh({"plugins": [{"id": "p", "use": f"{__name__}:NAMESPACE_PLUGIN"}]})
            fiber = loader.find("p").fiber
            await fiber.dispose()
            before = fiber.reloads
            with self.assertRaises(ContextError) as caught:
                await fiber.restart()
            self.assertIn("disposed", str(caught.exception))
            self.assertIn("Mount the entry again", str(caught.exception))
            # The counter is the tell: a no-op that increments `reloads` puts a number on the
            # page for work that never happened.
            self.assertEqual(fiber.reloads, before)
        run(go())

    def test_reload_of_a_disposed_entry_mounts_a_new_fiber(self):
        async def go():
            loader = await fresh({"plugins": [{"id": "p", "use": f"{__name__}:NAMESPACE_PLUGIN"}]})
            entry = loader.find("p")
            dead = entry.fiber
            await dead.dispose()
            self.assertEqual(dead.state, fibermod.DISPOSED)
            reloaded = await loader.reload("p")
            self.assertIsNot(reloaded.fiber, dead, "reload handed back the disposed fiber")
            self.assertEqual(state_of(loader, "p"), fibermod.ACTIVE)
            self.assertNotIn(dead, loader.runtime.fibers)
        run(go())

    def test_patch_of_a_disposed_entry_mounts_a_new_fiber_with_the_new_config(self):
        async def go():
            loader = await fresh({"plugins": [{"id": "p", "use": f"{__name__}:NAMESPACE_PLUGIN"}]})
            dead = loader.find("p").fiber
            await dead.dispose()
            entry = await loader.patch("p", {"depth": 3})
            self.assertIsNot(entry.fiber, dead)
            self.assertEqual(entry.config, {"depth": 3})
            self.assertEqual(state_of(loader, "p"), fibermod.ACTIVE)
        run(go())


class GpuPluginTests(unittest.TestCase):
    """`plugins/gpu.py` promises `available: False` where it cannot read. It used to raise.

    Every shape below is a real `nvidia-smi` output, and three of the four raised out of `vram()`
    before B17 -- `ValueError` twice and `IndexError` once -- straight through `ctx.call` and out
    of `POST /call` as a 500 on a method whose entire contract is to report what it has. The
    fourth did not raise, which is worse: a two-card box was reported as a one-card box.

    This machine has one RTX 5070 Ti, so the multi-card and unreadable-field paths cannot be
    exercised by the hardware and are stubbed. The single-card path is *also* asserted against
    the real card in `test_the_live_card_answers_in_the_documented_shape`.
    """

    @staticmethod
    def _vram(stdout):
        from .plugins import gpu
        completed = types.SimpleNamespace(stdout=stdout, returncode=0)
        with mock.patch.object(gpu.shutil, "which", return_value="/usr/bin/nvidia-smi"), \
                mock.patch.object(gpu.subprocess, "run", return_value=completed):
            return gpu.GPU(3.0).vram()

    def test_every_card_is_reported_and_not_just_the_first(self):
        got = self._vram("0, 1024, 16384, NVIDIA GeForce RTX 5070 Ti\n"
                         "1, 2048, 16384, NVIDIA GeForce RTX 5070 Ti\n")
        self.assertEqual(got["count"], 2)
        self.assertEqual([c["index"] for c in got["gpus"]], [0, 1])
        self.assertEqual([c["used_mib"] for c in got["gpus"]], [1024, 2048])

    def test_a_field_nvidia_smi_could_not_read_is_None_and_not_a_zero(self):
        got = self._vram("0, [N/A], [N/A], NVIDIA GeForce RTX 5070 Ti\n")
        self.assertTrue(got["available"])
        card = got["gpus"][0]
        self.assertIsNone(card["used_mib"])
        self.assertIsNone(card["total_mib"])
        # A zero here would draw a full bar for a card whose usage is unknown, which is the
        # decorative reading CLAUDE.md forbids.
        self.assertNotEqual(card["used_mib"], 0)

    def test_a_comma_in_the_product_name_survives(self):
        # "Tesla V100-SXM2, 16GB" is a real product string. An unbounded split made it an
        # unpacking error; the split is bounded at three commas so the name keeps its own.
        got = self._vram("0, 1024, 16384, Tesla V100-SXM2, 16GB\n")
        self.assertEqual(got["gpus"][0]["model"], "Tesla V100-SXM2, 16GB")

    def test_empty_output_is_unavailable_with_a_reason_and_not_an_IndexError(self):
        got = self._vram("\n")
        self.assertFalse(got["available"])
        self.assertIn("nothing parseable", got["reason"])

    @unittest.skipUnless(shutil.which("nvidia-smi"), "no nvidia-smi on this host")
    def test_the_live_card_answers_in_the_documented_shape(self):
        from .plugins import gpu
        got = gpu.GPU(5.0).vram()
        self.assertTrue(got["available"], got)
        self.assertEqual(got["source"], "measured")
        self.assertEqual(got["count"], len(got["gpus"]))
        for card in got["gpus"]:
            self.assertEqual(set(card), {"index", "used_mib", "total_mib", "model"})
            self.assertIsInstance(card["model"], str)


class InterceptTests(unittest.TestCase):
    """`intercept` -- what a group declares, and what the call underneath it receives.

    The first three tests use local fixtures because they need to vary the manifest. The last
    one mounts `presets/sessions.yaml` itself, because that file's header publishes two specific
    numbers and something has to hold it to them: it once declared an `intercept` with no
    consumer under it at all, which made the whole demonstration unobservable while reading as
    if it worked. `plugins/asker.py` is that consumer.

    Both directions are asserted throughout, because a proxy that merged nothing would pass
    every "the default arrived" assertion on its own and fail no test.
    """

    def setUp(self):
        CALLS.clear()

    def _manifest(self, group: dict) -> dict:
        entry = {"id": "session", "isolate": ["llm"], "plugins": [
            {"id": "session.llm", "use": f"{HERE}:llm_service"},
            {"id": "session.consumer", "use": f"{HERE}:llm_consumer"},
        ]}
        entry.update(group)
        return {"plugins": [entry]}

    def test_a_group_default_reaches_a_call_the_plugin_wrote_itself(self):
        async def go():
            loader = await fresh(self._manifest({"intercept": {"llm": {"temperature": 0.0}}}))
            self.assertEqual(state_of(loader, "session.consumer"), fibermod.ACTIVE)
            self.assertEqual(len(CALLS), 1)
            self.assertEqual(CALLS[0]["kwargs"], {"temperature": 0.0},
                             "the group's `intercept` default did not reach the call")
            self.assertEqual(CALLS[0]["prompt"], "hello")
        run(go())

    def test_without_the_declaration_the_same_call_carries_nothing(self):
        async def go():
            loader = await fresh(self._manifest({}))
            self.assertEqual(state_of(loader, "session.consumer"), fibermod.ACTIVE)
            self.assertEqual(CALLS[0]["kwargs"], {},
                             "a kwarg arrived that no caller and no manifest asked for")
        run(go())

    def test_an_explicit_argument_beats_the_group_default(self):
        """A default the caller cannot see must still be a default and not an override."""
        async def go():
            loader = await fresh(self._manifest({"intercept": {"llm": {"temperature": 0.0}}}))
            ctx = loader.find("session.consumer").fiber.ctx
            self.assertEqual(ctx.llm.complete("x", temperature=0.7)["kwargs"],
                             {"temperature": 0.7})
        run(go())

    def test_the_sessions_preset_shows_both_sides_of_one_declaration(self):
        """The shipped preset, not a fixture: 0.7 on one side and 0.0 on the other.

        `presets/sessions.yaml` and `plugins/asker.py` both name this test, and both publish
        those two figures. Reading them means holding the two `Asker` objects -- `Loader.state`
        serialises service *keys* and never service contents -- so this is the only place the
        claim can be checked, which is why the preset's header points here rather than at a
        command to run.

        The two entries are identical apart from which group they sit in. If the reading ever
        comes back the same on both sides, `intercept` stopped reaching the consumer.
        """
        async def go():
            loader = await fresh(loadermod.preset_path("sessions"))
            askers = {s.key: s.value for s in loader.runtime.services.values()
                      if s.name == "asker"}
            self.assertEqual(len(askers), 2, sorted(askers))
            by_realm = {key.split(".", 1)[0]: value for key, value in askers.items()}
            self.assertEqual(sorted(by_realm), ["session-a", "session-b"], sorted(askers))
            for realm, expected in (("session-a", 0.7), ("session-b", 0.0)):
                answer = by_realm[realm].answers[0]
                self.assertEqual(answer["temperature"], expected,
                                 f"{realm} asked at {answer['temperature']}, not {expected}")
            # Same prompt, same plugin, same config -- and two different calls landed. The
            # prefixes come from the two `echo_llm` entries and prove the fork happened too:
            # one shared service would have answered both with one prefix.
            self.assertEqual(by_realm["session-a"].answers[0]["text"], "a> olleh")
            self.assertEqual(by_realm["session-b"].answers[0]["text"], "b> olleh")
        run(go())


class ServiceEpochTests(unittest.TestCase):
    """What `Service.epoch` counts, and what it does not.

    `context.py` says the number is a count of in-place swaps rather than of every object a name
    has ever had, and `page.html` and `docs/writing-plugins.md` now say the same. Both halves are
    asserted, because a reader who checks only the first would take the bump for a lifetime
    counter and read a reloaded service's `epoch=1` as a bug.
    """

    def _manifest(self, value: int) -> dict:
        return {"plugins": [
            {"id": "p", "use": f"{HERE}:provider", "config": {"value": value}},
            {"id": "c", "use": f"{HERE}:consumer"},
        ]}

    def test_a_live_provider_re_providing_bumps_the_epoch_and_restarts_dependents(self):
        async def go():
            loader = await fresh(self._manifest(1))
            services = loader.runtime.services
            self.assertEqual(services[":probe"].epoch, 1, "a first provide is epoch 1, not 0")
            self.assertEqual(services[":saw"].value, 1)
            loader.find("p").fiber.ctx.provide("probe", {"value": 7})
            self.assertEqual(services[":probe"].epoch, 2, "an in-place swap did not bump")
            await loader.runtime.settle()
            self.assertEqual(services[":saw"].value, 7,
                             "the consumer did not restart against the new object")
            self.assertEqual(loader.find("c").fiber.epochs, {"probe": 2})
        run(go())

    def test_re_providing_the_same_object_does_not_bump(self):
        async def go():
            loader = await fresh(self._manifest(1))
            service = loader.runtime.services[":probe"]
            loader.find("p").fiber.ctx.provide("probe", service.value)
            self.assertEqual(service.epoch, 1,
                             "the same object provided twice is not a new version")
        run(go())

    def test_a_reload_replaces_the_service_and_the_epoch_starts_over(self):
        """The case the docstrings had wrong: a changed config unwinds the provider, so `revoke`
        deletes the entry and the replacement is a fresh `Service` at 1 -- the dependent still
        re-resolves, by way of `missing()` rather than `stale()`."""
        async def go():
            loader = await fresh(self._manifest(1))
            services = loader.runtime.services
            before = services[":probe"]
            await loader.apply(self._manifest(2), label="test")
            after = services[":probe"]
            self.assertIsNot(after, before, "the reload kept the old service entry")
            self.assertEqual(after.epoch, 1, "a post-revoke provide is a new name, not a swap")
            self.assertEqual(services[":saw"].value, 2,
                             "the consumer kept the value from before the reload")
        run(go())


class TraceTests(unittest.TestCase):
    """The two promises in `trace.py`'s own docstrings."""

    def test_a_cursor_read_returns_the_oldest_unseen_events_and_not_the_newest(self):
        """`since` is the page's cursor. Handing back the *newest* `limit` events silently
        discards the middle of a reload, because the page then advances its cursor past
        everything it was not given."""
        from .trace import Trace
        trace = Trace()
        for i in range(10):
            trace.add("row", i=i)
        got = trace.since(0, limit=4)
        self.assertEqual([e["seq"] for e in got], [1, 2, 3, 4])
        # And the next poll, from the cursor the page would now hold, continues where it stopped.
        nxt = trace.since(got[-1]["seq"], limit=4)
        self.assertEqual([e["seq"] for e in nxt], [5, 6, 7, 8])

    def test_a_payload_json_cannot_encode_is_a_dropped_write_and_not_a_raise(self):
        """`add` says it never raises. `default=str` covers an unknown *type*; a reference cycle
        raises `ValueError` and a non-string mapping key raises `TypeError`, both from inside
        `json.dumps` and both after the ring already holds the record."""
        import tempfile
        from .trace import Trace
        cycle: dict = {}
        cycle["self"] = cycle
        with tempfile.TemporaryDirectory() as tmp:
            path = pathlib.Path(tmp) / "trace.jsonl"
            trace = Trace(path=path)
            trace.add("fine", n=1)
            trace.add("cyclic", payload=cycle)
            trace.add("bad-key", payload={(1, 2): "tuple key"})
            self.assertEqual(trace.dropped_writes, 2)
            self.assertEqual([e["event"] for e in trace.tail(10)],
                             ["fine", "cyclic", "bad-key"])
            self.assertEqual(len(path.read_text(encoding="utf-8").strip().splitlines()), 1)


class PrivacyTests(unittest.TestCase):
    def test_a_snapshot_without_config_has_no_config_key_at_all(self):
        entry = loadermod.Entry({"id": "x", "use": "y.z", "config": {"token": "s3cret"}})
        snap = entry.snapshot(with_config=False)
        self.assertNotIn("config", snap)
        # Not `config: {}` and not `config: "***"`. An empty dict reads as "this plugin has no
        # config", which is a different and false statement.
        self.assertNotIn("s3cret", repr(snap))
        self.assertEqual(entry.snapshot(with_config=True)["config"], {"token": "s3cret"})


class _CountingLoader:
    """Stands in for the process-wide loader so `boot()` can be tested without mounting into it.

    `apply` awaits before recording, which is the whole point: the bug this guards was two
    concurrent first requests both passing the pre-await check.
    """

    def __init__(self) -> None:
        self.applies: list = []
        self.source = None

    async def apply(self, manifest, label=None):
        await asyncio.sleep(0)
        self.applies.append(label)
        self.source = str(manifest)


class RegressionTests(unittest.TestCase):
    """One test per correctness item in the 2026-08-19 closeout review's section 1.

    Named for what each one measures rather than for the item number, because the numbers are in
    a document that is not in this directory and the behaviour is.
    """

    def test_a_rejected_config_value_is_not_in_the_error_the_trace_or_the_state(self):
        secret = "sk-live-NOTAREALKEY"

        async def go():
            loader = await fresh({"plugins": [
                {"id": "leaky", "use": f"{HERE}:wants_a_float", "config": {"interval": secret}},
            ]})
            entry = loader.find("leaky")
            snap = entry.snapshot(with_config=False)
            self.assertEqual(snap["state"], "failed")
            # From the snapshot, not `entry.error`: the config check runs in `registry.mount`, so
            # the message is on the fiber and reaches the page through `snapshot`.
            err = snap["error"] or ""
            # The key and both type names are what an operator needs; the value is what the
            # closeout found being published. `GET /api/exp/events` is an open read.
            self.assertIn("'interval'", err)
            self.assertIn("float", err)
            self.assertIn("str", err)
            self.assertNotIn(secret, err)
            self.assertNotIn(secret, repr(loader.runtime.trace.tail(200)))
            self.assertNotIn(secret, repr(loader.state()))
            # And still present where it was deliberately kept: the entry's own config, which
            # only the token-gated read returns.
            self.assertEqual(entry.snapshot(with_config=True)["config"]["interval"], secret)
        run(go())

    def test_a_parent_that_raises_does_not_leave_its_children_mounted(self):
        async def go():
            loader = await fresh({"plugins": [
                {"id": "parent", "use": f"{HERE}:mounts_a_child_then_raises"},
            ]})
            self.assertEqual(state_of(loader, "parent"), "failed")
            # The child provided `probe`. If the failure path skipped children, the service
            # outlives the plugin that owns it and the next consumer injects a dead object.
            self.assertEqual([s.key for s in loader.runtime.services.values()], [])
            self.assertEqual([f.id for f in loader.runtime.fibers if f.state == fibermod.ACTIVE],
                             [])
        run(go())

    def test_an_unimportable_use_fails_one_entry_and_not_the_manifest(self):
        async def go():
            loader = await fresh({"plugins": [
                {"id": "bad", "use": "no_such_module_anywhere:apply"},
                {"id": "good", "use": f"{HERE}:provider"},
            ]})
            self.assertEqual(state_of(loader, "bad"), "failed")
            self.assertEqual(state_of(loader, "good"), fibermod.ACTIVE)
            # The module name is the only useful part of this failure, so it has to survive
            # into the message the page shows.
            self.assertIn("no_such_module_anywhere",
                          loader.find("bad").snapshot(with_config=False)["error"] or "")
        run(go())

    def test_two_concurrent_boots_apply_the_preset_once(self):
        import sys

        pkg = sys.modules[__package__]
        stub = _CountingLoader()
        saved = (pkg._LOADER, pkg._BOOTED, pkg._BOOT_LOCK)
        pkg._LOADER, pkg._BOOTED, pkg._BOOT_LOCK = stub, False, None
        try:
            async def go():
                await asyncio.gather(pkg.boot(), pkg.boot(), pkg.boot())
            run(go())
            self.assertEqual(len(stub.applies), 1, f"applied {len(stub.applies)} times")
        finally:
            pkg._LOADER, pkg._BOOTED, pkg._BOOT_LOCK = saved

    def test_an_explicit_preset_applies_even_when_boot_already_ran(self):
        import sys

        pkg = sys.modules[__package__]
        stub = _CountingLoader()
        saved = (pkg._LOADER, pkg._BOOTED, pkg._BOOT_LOCK)
        pkg._LOADER, pkg._BOOTED, pkg._BOOT_LOCK = stub, True, None
        try:
            run(pkg.boot("sessions"))
            self.assertEqual(stub.applies, ["sessions"])
        finally:
            pkg._LOADER, pkg._BOOTED, pkg._BOOT_LOCK = saved

    def test_calling_a_disposer_twice_runs_the_cleanup_once(self):
        async def go():
            DISPOSED.clear()
            loader = await fresh({"plugins": [
                {"id": "d", "use": f"{HERE}:disposes_itself_twice"},
            ]})
            self.assertEqual(state_of(loader, "d"), fibermod.ACTIVE)
            self.assertEqual(DISPOSED, [1], "the second call ran the cleanup again")
            # And the fiber does not run it a third time on the way out, because calling it
            # early removed it from the effect list.
            await loader.dispose()
            self.assertEqual(DISPOSED, [1], "teardown re-ran an already-run cleanup")
        run(go())

    def test_a_settle_task_is_held_until_it_finishes_and_its_failure_is_recorded(self):
        async def go():
            runtime = Runtime()
            ctx = Context(runtime)

            async def explodes():
                raise RuntimeError("boom")

            runtime.settle = explodes
            before = set(registry._SETTLES)
            ctx.plugin(provider, {})
            launched = set(registry._SETTLES) - before
            # Nothing else holds this task. Without the set, it is collectable mid-await and the
            # fiber stays PENDING with nothing scheduled to start it.
            self.assertEqual(len(launched), 1, "the settle task is not referenced anywhere")
            for _ in range(4):
                await asyncio.sleep(0)
            self.assertEqual(set(registry._SETTLES) & launched, set(), "the set leaks tasks")
            # The task has no caller, so the only place its exception can surface is here.
            self.assertEqual(runtime.settle_error, "RuntimeError: boom")
            self.assertTrue([e for e in runtime.trace.tail(20)
                             if e["event"] == "runtime/settle-error"])
        run(go())

    def test_the_rack_row_counts_services_inside_isolated_realms(self):
        """Two panels on one page must not disagree about one reading.

        `status()` counts `Loader.state()["services"]`, and that list has to be the runtime's --
        `root.services()` sees the root realm only, so with one isolated `memory` mounted the rack
        row said "0 services" while the Services table right below it listed the row. The count
        the row prints and the rows `/api/exp/services` returns come from the same place now, and
        this asserts both together rather than the count alone.
        """
        import sys

        pkg = sys.modules[__package__]

        async def go():
            loader = await fresh({"plugins": [
                {"id": "session", "isolate": ["memory"], "plugins": [
                    {"id": "session.memory", "use": "studio.plugins.exp.plugins.memory"},
                ]},
            ]})
            keys = loader.state()["services"]
            self.assertEqual(len(keys), 1, f"the isolated service is invisible: {keys}")
            self.assertTrue(keys[0].endswith(":memory"), keys)
            self.assertNotEqual(keys[0], ":memory", "it was not isolated at all")
            saved = pkg._LOADER
            pkg._LOADER = loader
            try:
                detail = pkg.status()["detail"]
            finally:
                pkg._LOADER = saved
            self.assertIn("1 services", detail,
                          f"the rack row disagrees with /api/exp/services: {detail}")
        run(go())



class _FakeRequest:
    """Enough of a Starlette `Request` for `_guard`: two mappings, no ASGI scope.

    `_guard` reads `request.headers` and `request.query_params` and nothing else. Building a real
    `Request` would mean building a scope, and the test would then be asserting Starlette works.
    """

    def __init__(self, headers=None, query=None) -> None:
        self.headers = dict(headers or {})
        self.query_params = dict(query or {})


class RouteTests(unittest.TestCase):
    """The read/write line, asserted against the source of the handlers."""

    def setUp(self):
        self.routes = _routes()

    def _handlers(self, method):
        routes = self.routes
        found = {}
        for name, fn in vars(routes).items():
            if not callable(fn) or not hasattr(fn, "__module__"):
                continue
            if getattr(fn, "__module__", None) != routes.__name__:
                continue
            try:
                src = inspect.getsource(fn)
            except (OSError, TypeError):                      # pragma: no cover
                continue
            if f"@router.{method}(" in src:
                found[name] = src
        return found

    def test_every_write_route_is_guarded(self):
        posts = self._handlers("post")
        self.assertGreaterEqual(len(posts), 8, f"routes went missing: {sorted(posts)}")
        for name, src in posts.items():
            with self.subTest(route=name):
                self.assertIn("_guard(request)", src,
                              f"{name} mutates the runtime without checking the token")

    def test_no_read_route_is_guarded(self):
        gets = self._handlers("get")
        self.assertGreaterEqual(len(gets), 5, f"routes went missing: {sorted(gets)}")
        for name, src in gets.items():
            with self.subTest(route=name):
                self.assertNotIn("_guard(request)", src,
                                 f"{name} became token-gated; reads are open by design and a "
                                 f"plugin table nobody can see is a plugin table nobody looks "
                                 f"at. If this changed on purpose, change routes.py's docstring "
                                 f"in the same commit.")

    def test_off_and_refused_are_different_statuses(self):
        src = inspect.getsource(self.routes._guard)
        self.assertIn("503", src)
        self.assertIn("401", src)
        # The 503 has to name the switch, because "not enabled" without it is a dead end.
        # `_guard` interpolates the *constant*, so the literal "SYMONEURAL_EXP_ENABLED" never
        # appears in its source -- assert the interpolation is there, and pin the value
        # separately, or this passes while the message says `{ENV_ENABLED}` to the operator.
        #
        # There used to be a second pair of assertions here for ENV_TOKEN. NO API KEYS,
        # 2026-09-11: the constant is gone, so a message naming it would be a message telling
        # the operator to set something nothing reads. The 401 branch is still asserted to
        # exist in the source above, because `token_ok` is kept as the one place a gate would
        # go back -- it simply cannot fire today.
        self.assertIn("{ENV_ENABLED}", src)
        self.assertEqual(gate.ENV_ENABLED, "SYMONEURAL_EXP_ENABLED")



class GateTests(unittest.TestCase):


    def test_the_token_is_read_from_header_bearer_and_query(self):
        self.assertEqual(gate.present_token({gate.HEADER: "a"}, {}), "a")
        self.assertEqual(gate.present_token({"authorization": "Bearer b"}, {}), "b")
        self.assertEqual(gate.present_token({}, {"token": "c"}), "c")
        # No cookie form. The studio has one only because its proxied iframe cannot send a
        # header; nothing here is proxied, so a cookie would be a CSRF surface bought for
        # nothing. Checked against the code with the docstring cut off, because the docstring
        # says the word "cookie" four times explaining why there is no cookie -- the same
        # rule-versus-promise problem `build_exp.without_comments` exists for.
        src = inspect.getsource(gate.present_token)
        code = src.split('"""')[2] if src.count('"""') >= 2 else src
        self.assertNotIn("cookie", code.lower())


class PageTests(unittest.TestCase):
    def setUp(self):
        self.html = (APP / "page.html").read_text()
        self.js = (APP / "page.js").read_text()

    def test_the_fragment_keeps_the_contract_the_generator_asserts(self):
        import sys

        sys.path.insert(0, str(APP.parents[2] / "tools"))
        try:
            import build_exp
        finally:
            sys.path.pop(0)
        stripped = self.html.strip()
        self.assertTrue(stripped.startswith(build_exp.BEGIN))
        self.assertTrue(stripped.endswith(build_exp.END))
        self.assertIn(build_exp.OUTER_OPEN, stripped)
        self.assertIn(build_exp.SCRIPT_TAG, stripped)

    def test_the_built_page_is_the_generators_output_with_stamps_added(self):
        """`site/exp.html` must be `tools/build/build_exp.py`'s output plus cache-bust stamps.

        The generator emits plain `href="/symoneural.css"`; `tools/build/build_cachebust.py` rewrites
        those to `?v=<hash>`. So a bare generator run leaves the page destamped and the diff reads
        as a harmless refresh -- `.claude/CLAUDE.md` records that happening to seven pages at
        once. `SITE` is redirected and the real `main()` runs rather than the transform being
        copied here, because a copy of a transform asserts nothing about the transform.
        """
        import sys
        import tempfile
        from unittest import mock

        root = ROOT
        built = root / "site" / "exp.html"
        if not built.is_file():
            self.skipTest("site/exp.html not generated in this checkout")
        sys.path.insert(0, str(root / "tools"))
        try:
            import build_exp
        finally:
            sys.path.pop(0)
        shipped = built.read_text()
        with tempfile.TemporaryDirectory() as td:
            tmp = pathlib.Path(td)
            with mock.patch.object(build_exp, "SITE", tmp), \
                    mock.patch("builtins.print", lambda *a, **k: None):
                build_exp.main()
            generated = (tmp / "exp.html").read_text()
            generated_js = (tmp / "exp.js").read_text()
        self.assertEqual(re.sub(r"\?v=[0-9a-f]+", "", shipped), generated,
                         "site/exp.html is not build_exp.py's output; regenerate it")
        self.assertTrue(re.findall(r"\?v=[0-9a-f]+", shipped),
                        "site/exp.html carries no ?v= stamps -- a generator ran without "
                        "`python3 tools/build/build_cachebust.py` after it, so its CSS and JS are "
                        "cacheable for a week with no way to invalidate them")
        self.assertEqual((root / "site" / "exp.js").read_text(), generated_js,
                         "site/exp.js is not a copy of this app's page.js")

    def test_the_page_names_no_legacy_env_var_to_the_operator(self):
        """The four strings an operator actually types, pinned as literals.

        These are the *display* names -- what the panel tells you to set on the API process --
        and they are the one part of the rename that no symbolic assertion can reach.
        `GateTests` above pins `gate.ENV_ENABLED` through the constant, which is
        the right way to write that test and is exactly why it cannot notice this: the panel
        does not read the constants, it hard-codes the words. All four sat at the legacy
        spelling through a 1225-test run, telling every operator to set a variable nothing
        reads any more.

        `SYM_EXP_` is checked as a whole-file absence rather than paired against the new
        spelling, because a single reverted line is the realistic regression and pairing
        cannot see it -- three correct occurrences elsewhere in the file satisfy a pairing
        rule. `SYM_EXP_` is not a substring of `SYMONEURAL_EXP_`, so this is unambiguous.
        `apps/test_credential_header.py::TheEnvNameTripwire` is the repo-wide net; this is the
        per-occurrence one, and the byte-copy assertion above carries it to `site/exp.js`.
        """
        self.assertNotIn("SYM_EXP_", self.js,
                         "page.js names a legacy SYM_EXP_* variable to the operator")
        for want in ("SYMONEURAL_EXP_ENABLED=1", "SYMONEURAL_EXP_TOKEN"):
            self.assertIn(want, self.js)

    def test_every_id_the_script_reaches_for_exists_in_the_markup(self):
        ids = set(re.findall(r'id="([^"]+)"', self.html))
        wanted = set(re.findall(r"\$\('([^']+)'\)", self.js))
        wanted |= set(re.findall(r"getElementById\('([^']+)'\)", self.js))
        # Ids the script creates itself rather than finds.
        created = set(re.findall(r"\.id = '([^']+)'", self.js))
        missing = sorted(wanted - ids - created)
        self.assertEqual(missing, [], f"page.js reaches for ids that are not in page.html: "
                                      f"{missing}. getElementById returns null silently, so "
                                      f"this renders nothing and raises nothing.")

    def test_the_stylesheet_is_namespaced(self):
        # Every rule inside the fragment's <style> must start `#exp`. Four bugs on this site
        # came from generic class names colliding across components.
        style = self.html.split("<style>", 1)[1].split("</style>", 1)[0]
        style = re.sub(r"/\*.*?\*/", "", style, flags=re.S)
        for block in style.split("}"):
            selector = block.split("{", 1)[0].strip()
            if not selector or selector.startswith("@"):
                continue
            for one in selector.split(","):
                one = one.strip()
                if one:
                    with self.subTest(selector=one):
                        self.assertTrue(one.startswith("#exp"), f"{one!r} is not namespaced")

    def test_the_token_dies_with_the_tab(self):
        # Comments stripped first. `page.js` opens with a paragraph explaining why it uses
        # sessionStorage and not localStorage, and a substring search cannot tell a call from a
        # sentence about not making one -- the same reason the generator has
        # `without_comments`.
        code = re.sub(r"/\*.*?\*/", "", self.js, flags=re.S)
        code = re.sub(r"(?m)//.*$", "", code)
        self.assertIn("sessionStorage", code)
        self.assertNotIn("localStorage", code)

    def test_there_is_no_ellipsis_rule(self):
        rules = re.sub(r"/\*.*?\*/", "", self.html, flags=re.S)
        rules = re.sub(r"<!--.*?-->", "", rules, flags=re.S)
        self.assertNotIn("text-overflow", rules)


class CliTests(unittest.TestCase):
    """The CLI is the standing proof that the runtime imports nothing outside the standard
    library: it goes nowhere near `routes.py`, so if FastAPI is missing it still works. These
    tests call `main()` in-process rather than spawning `python3 -m`, because a subprocess test
    would pass on a box where `apps` happens to be importable and fail on the one where it is
    not, for reasons that have nothing to do with this package."""

    def _run(self, argv):
        import contextlib
        import io

        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = cli.main(argv)
        return code, out.getvalue(), err.getvalue()

    def test_the_dev_preset_mounts_and_prints_a_table(self):
        code, out, _ = self._run(["--preset", "dev"])
        self.assertEqual(code, 0)
        for expected in ("bus", "memory", "recorder", "active", "disabled"):
            self.assertIn(expected, out)

    def test_json_is_the_same_structure_the_api_returns(self):
        import json

        code, out, _ = self._run(["--json"])
        self.assertEqual(code, 0)
        payload = json.loads(out)
        # The keys `routes.state` adds on top are the gate's; the rest comes from
        # `Loader.state()` and both callers must keep seeing the same shape.
        for key in ("source", "presets", "entries", "fibers", "services", "states", "seq"):
            self.assertIn(key, payload)
        self.assertNotIn("config", payload["entries"][0],
                         "the CLI leaked config without --config")

    def test_config_is_opt_in_here_too(self):
        import json

        code, out, _ = self._run(["--json", "--config"])
        self.assertEqual(code, 0)
        self.assertIn("config", json.loads(out)["entries"][0])

    def test_isolated_sessions_produce_two_services_of_one_name(self):
        code, out, _ = self._run(["--preset", "sessions"])
        self.assertEqual(code, 0)
        # Three, not two: `isolate: [llm, memory, asker]`. `asker` is in that list because
        # without it both sessions provide one root-realm `asker` and the second entry fails to
        # mount -- see the preset's header.
        self.assertEqual(out.count("realm=session-a"), 3, out)
        self.assertEqual(out.count("realm=session-b"), 3, out)
        self.assertNotIn("failed", out)

    def test_failures_exit_zero_unless_strict(self):
        ok, out, _ = self._run(["failures"])
        self.assertEqual(ok, 0)
        strict, _, _ = self._run(["failures", "--strict"])
        self.assertEqual(strict, 1)
        # Entry ids, not fiber ids: `no-such-module` fails while resolving and never gets a
        # fiber, so counting fibers reports three where the table shows four.
        self.assertIn("4 failed:", out)
        self.assertIn("no-such-module", out)

    def test_a_missing_manifest_is_its_own_exit_code_and_lists_the_presets(self):
        code, _, err = self._run(["no-such-manifest"])
        self.assertEqual(code, 2)
        for name in loadermod.presets():
            self.assertIn(name, err)

    def test_the_flag_form_is_not_overwritten_by_the_positional_default(self):
        """argparse applies a `nargs="?"` positional's default *after* the optionals, so sharing
        one `dest` between `--preset` and the positional silently mounts `dev` instead."""
        code, out, _ = self._run(["--preset", "sessions"])
        self.assertEqual(code, 0)
        self.assertIn("source: sessions", out)


class DocsTests(unittest.TestCase):
    def test_every_doc_the_source_cites_exists(self):
        cited = set()
        for path in sorted(APP.glob("*.py")):
            for ref in re.findall(r"docs/([a-z0-9-]+\.md)", path.read_text()):
                cited.add(ref)
        self.assertTrue(cited, "no docs are cited any more; this test has stopped testing")
        # Two `docs/` directories are in play: this package's, and the repository's at
        # `Symoneural/docs/`. `trace.py` cites `docs/integration-sources.md`, which is the
        # repo-level one -- it is the file that records the verdict this package argues with --
        # so a citation resolves if it exists in either place.
        repo_docs = ROOT / "docs"
        for ref in sorted(cited):
            with self.subTest(doc=ref):
                self.assertTrue((APP / "docs" / ref).is_file() or (repo_docs / ref).is_file(),
                                f"the source promises docs/{ref} and it is in neither "
                                f"{APP / 'docs'} nor {repo_docs}")

    def test_the_docs_the_docs_cite_exist_too(self):
        """Cross-references between the three docs and the README. A dead link in shipped prose
        is the same defect whether the citation is in a docstring or in Markdown."""
        docs = APP / "docs"
        repo_docs = ROOT / "docs"
        for path in sorted(list(docs.glob("*.md")) + [APP / "README.md"]):
            for ref in re.findall(r"docs/([a-z0-9-]+\.md)", path.read_text()):
                with self.subTest(source=path.name, doc=ref):
                    self.assertTrue((docs / ref).is_file() or (repo_docs / ref).is_file(),
                                    f"{path.name} cites docs/{ref}, which is not there")

    def test_the_plateau_argument_is_actually_in_the_architecture_doc(self):
        """`__init__.py` promises that `docs/architecture.md` "closes with the plateau argument
        in full". A promise in a package docstring is a claim about a file, so check the file."""
        text = (APP / "docs" / "architecture.md").read_text()
        self.assertIn("plateau", text.lower())
        heading = [line for line in text.splitlines() if line.startswith("## ")][-1]
        self.assertIn("plateau", heading.lower(),
                      "the plateau argument is no longer the closing section")

    def test_isolation_doc_still_says_isolate_is_not_a_security_boundary(self):
        """The one document that must not drift: it exists to say this is not containment.

        Asserting on a phrase the file does not contain would make this test the very thing the
        closeout review was written about, so it checks two sentences that are actually in it and
        prints only the missing phrase rather than the whole document.

        Whitespace is collapsed before matching. The second phrase used to be written with the
        newline the file happens to wrap on -- `"there is no\nin-process isolation here"` -- so
        the test was asserting on the width of a paragraph, and re-wrapping a sentence that had
        not changed its meaning would have failed it.
        """
        text = " ".join((APP / "docs" / "isolation.md").read_text().lower().split())
        for phrase in ("it is not a **security** boundary",
                       "there is no in-process isolation here"):
            with self.subTest(phrase=phrase):
                self.assertTrue(phrase in text, f"isolation.md no longer says {phrase!r}")


if __name__ == "__main__":                                    # pragma: no cover
    unittest.main()
