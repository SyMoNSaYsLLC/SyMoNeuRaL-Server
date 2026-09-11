"""Studio tests. Standard library and `unittest` only -- no network, no GPU, no fixtures.

**Why the import list matters more than usual here.** `apps/studio/plugins/reinforce/tests` and
`apps/remix/tests` are excluded from the suite by `--ignore` because they import `cupy` and
`symon_capture`, which are not installed on the system interpreter and never may be: it is the
serving path. A test file that needs a third dependency would make this a third `--ignore`, and
`.claude/CLAUDE.md` says to say so loudly rather than let "941 collected" quietly become
"collected 12". So this file imports nothing that is not already in the serving path. `httpx`
and `fastapi` are, so importing the package is fine; `pytest` is only the runner.

What is asserted here is what cannot be checked by looking at the page:

* the registry produces schemas an OpenAI-shaped `tools` array will accept
* the workspace resolves to a real checkout (this one is a regression test -- see below)
* the stock FLUX graph is internally consistent and carries schnell's parameters
* `graph.inject` addresses land where `workflows.PARAMETER_MAP` says they do
* the generated page kept the id its whole stylesheet hangs off

Nothing here starts ComfyUI, takes the GPU lock or calls an LLM. Those paths are exercised by
running the surface, and their results are in `README.md` with the numbers that came back.

Two tests do spawn a real `/bin/sh` -- `RunCommandTests`, which is about a timeout killing a
process group and cannot be faked into telling the truth about that. They cost about 2 s of the
file's runtime and clean up after themselves; the timeout test
(`test_a_backgrounded_child_does_not_outlive_the_timeout`) is the one that asserts the cleanup
with `pgrep`.
"""
from __future__ import annotations

import asyncio
import io
import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile
import time
import tokenize
import unittest
import unittest.mock
from unittest import mock

from . import gate, routes
from .lib import comfy
from .lib import graph
from .lib import registry
from .apps import workflows
from .lib import workspace
from . import tools_impl  # noqa: F401  -- imported for its @tool registrations

ROOT = next(_p for _p in pathlib.Path(__file__).resolve().parents if (_p / "backend" / "server.py").is_file())
APP = next(_p for _p in pathlib.Path(__file__).resolve().parents if (_p / "backend" / "server.py").is_file())


class RegistryTests(unittest.TestCase):
    def test_every_tool_has_a_description_the_model_can_use(self):
        for name in registry.names():
            description, _ = registry.schema_for(registry.get(name).fn)
            with self.subTest(tool=name):
                self.assertTrue(description.strip(),
                                f"{name} has no docstring summary; the system prompt renders "
                                f"this list, so an empty one reaches the model verbatim")

    def test_specs_are_shaped_like_an_openai_tools_array(self):
        for spec in registry.tool_specs():
            with self.subTest(tool=spec.get("function", {}).get("name")):
                self.assertEqual(spec["type"], "function")
                fn = spec["function"]
                self.assertRegex(fn["name"], r"^[A-Za-z0-9_-]{1,64}$")
                params = fn["parameters"]
                self.assertEqual(params["type"], "object")
                self.assertIsInstance(params["properties"], dict)
                self.assertIsInstance(params["required"], list)
                # Every required name must be a real property. A required entry with no
                # property is the one schema error that makes llama.cpp's grammar compiler
                # reject the whole tools array, taking every other tool down with it.
                for req in params["required"]:
                    self.assertIn(req, params["properties"])

    #: Every tool the agent is offered, listed under the module that defines it. Written out
    #: instead of derived: deriving it from the registry would assert only that the registry
    #: equals itself, and the bug this guards is a module dropped from `tools_impl/__init__.py`,
    #: which leaves a registry that is smaller and perfectly self-consistent.
    EXPECTED_TOOLS = {
        "cleanroom": {"extract_spec", "generate_native_code"},
        "comfy_tool": {"comfy_status", "generate_image", "list_comfy_nodes", "list_workflows",
                       "read_image_file", "run_workflow"},
        "fs": {"delete_path", "find_files", "list_dir", "read_file", "search", "workspace_root",
               "write_file"},
        "host": {"disk_usage", "env_get", "env_set", "gpu_status", "python_packages",
                 "run_command", "service_status"},
        "stack": {"app_status", "list_apps", "list_generators", "list_models", "list_routes",
                  "read_app_config"},
    }

    def test_the_whole_tool_inventory_is_registered(self):
        """The assertion `tools_impl/__init__.py` names.

        `@tool` registers at import time, so a module left out of that file's import list
        contributes nothing and raises nothing: the agent just gets a shorter tool list and the
        system prompt renders it without complaint. Comparing per defining module rather than
        only the total is what makes the failure say *which* import went missing.
        """
        actual: dict[str, set[str]] = {}
        for name in registry.names():
            module = registry.get(name).fn.__module__.rsplit(".", 1)[-1]
            actual.setdefault(module, set()).add(name)
        self.assertEqual(actual, self.EXPECTED_TOOLS)
        self.assertEqual(len(registry.names()),
                         sum(len(v) for v in self.EXPECTED_TOOLS.values()))

    #: The group table in `README.md`, transcribed row for row. `EXPECTED_TOOLS` above is keyed
    #: by *defining module* and this is keyed by *group*; they are not the same question, and
    #: `fs.py` -> `workspace` is where the two names diverge. Written out for the same reason:
    #: derived from the registry it would assert that the registry equals itself, and the thing
    #: being guarded is a static table in a document.
    EXPECTED_GROUPS = {
        "cleanroom": {"extract_spec", "generate_native_code"},
        "workspace": {"workspace_root", "list_dir", "read_file", "write_file", "delete_path",
                      "search", "find_files"},
        "host": {"run_command", "env_get", "env_set", "service_status", "gpu_status",
                 "disk_usage", "python_packages"},
        "stack": {"list_apps", "app_status", "read_app_config", "list_routes", "list_models",
                  "list_generators"},
        "comfyui": {"generate_image", "run_workflow", "list_workflows", "list_comfy_nodes",
                    "comfy_status", "read_image_file"},
    }

    def test_the_group_each_tool_reports_is_the_one_the_readme_documents(self):
        """`README.md` tabulates the tools by group and the page prints the same field, so a
        group typo shows up in two places and used to be asserted in neither.

        This test was named for the whole table and checked three things out of it:
        `read_image_file`, the set of group names, and the six under `stack`. The other
        nineteen rows were unguarded, so a tool moving between `workspace`, `host` and
        `comfyui` left the README wrong and every test green. It now compares the entire
        mapping against `EXPECTED_GROUPS`, which is that table transcribed.

        `read_image_file` is still the row worth naming: it lives in `comfy_tool.py` and is
        registered `comfyui`, not `workspace`, which is what the README claimed for two weeks
        because the tool reads a file off disk.
        """
        groups: dict[str, set[str]] = {}
        for name in registry.names():
            groups.setdefault(registry.get(name).group, set()).add(name)
        # Without this the four-group diff is 811 characters and unittest replaces it with
        # "Diff is 811 characters long", so the failure says a group changed and not which tool
        # moved -- which is the only thing anyone reading it needs.
        self.maxDiff = None
        self.assertEqual(groups, self.EXPECTED_GROUPS)
        # The README states these numbers in prose under the table ("7 · 7 · 6 · 6 · 2"), which
        # is a second place they can go stale, so assert the shape the sentence claims and not
        # only the membership above.
        self.assertEqual({g: len(n) for g, n in sorted(groups.items())},
                         {"cleanroom": 2, "comfyui": 6, "host": 7, "stack": 6, "workspace": 7})

    def test_names_are_unique(self):
        names = registry.names()
        self.assertEqual(len(names), len(set(names)))

    def test_the_dangerous_ones_are_labelled_as_such(self):
        """Not a guard -- a label. No filtering is implemented as of 2026-08-20 (R-98, held),
        so `run_command` and `write_file` run unrestricted. But the UI prints which tools
        write, and that flag has to come from the registry rather than a list in the page that
        drifts. This asserts the label, and stays true either way."""
        for name in ("run_command", "write_file", "delete_path", "env_set"):
            self.assertTrue(registry.get(name).dangerous, f"{name} is not flagged as writing")
        for name in ("list_dir", "read_file", "gpu_status"):
            self.assertFalse(registry.get(name).dangerous, f"{name} is flagged as writing")


class ArgumentCheckTests(unittest.TestCase):
    """`registry.check` and `registry._coerce`.

    These restrict nothing -- no tool refuses a call anywhere in this package. They exist
    because the caller is a 7B model, and the alternative to a checked argument list is a
    `TypeError` raised inside the tool, which arrives as a traceback and ends the turn.
    """

    def test_an_invented_parameter_is_reported_with_the_real_ones(self):
        out = registry.check("list_dir", {"path": "scripts", "recursive": True})
        self.assertEqual(out["error"], "bad_arguments")
        self.assertEqual(out["unknown"], ["recursive"])
        self.assertIn("path", out["accepts"])

    def test_a_missing_required_parameter_is_named(self):
        out = registry.check("generate_image", {})
        self.assertEqual(out["error"], "bad_arguments")
        self.assertIn("prompt", out["missing"])

    def test_a_correct_call_returns_none(self):
        self.assertIsNone(registry.check("list_dir", {"path": "scripts"}))

    def test_a_bool_is_not_an_integer_even_though_python_says_it_is(self):
        """`isinstance(True, int)` is True. A model answering `"steps": true` would sail
        through the obvious check and render one step."""
        out = registry.check("generate_image", {"prompt": "x", "steps": True})
        self.assertEqual(out["error"], "bad_argument_types")
        self.assertEqual(out["parameters"][0]["parameter"], "steps")

    def test_a_numeric_string_is_accepted_and_then_coerced(self):
        """Local models emit `"steps": "4"` regularly -- a text-completion artefact, not a
        misunderstanding, and one they will repeat next turn. Rewriting it is cheaper than a
        round trip that teaches nothing."""
        self.assertIsNone(registry.check("generate_image", {"prompt": "x", "steps": "4"}))
        out = registry._coerce(registry.get("generate_image"), {"steps": "4", "width": "768"})
        self.assertEqual(out, {"steps": 4, "width": 768})

    def test_a_value_that_does_not_convert_is_left_alone(self):
        out = registry._coerce(registry.get("generate_image"), {"prompt": "a raven"})
        self.assertEqual(out, {"prompt": "a raven"})

    def test_an_unknown_tool_lists_the_real_ones(self):
        out = registry.check("read_teh_file", {})
        self.assertEqual(out["error"], "unknown_tool")
        self.assertIn("read_file", out["available"])


class WorkspaceTests(unittest.TestCase):
    def test_root_returns_the_checkout(self):
        """Regression. `root()` raised when discovery failed but had no `return` on success,
        so it handed back `None` and every filesystem tool resolved against it -- which
        surfaced as `/api/studio/state` reporting `"root": "None"` rather than as an
        exception. A function whose failure path is written and whose success path is not is
        exactly the shape that reads as correct."""
        r = workspace.root()
        self.assertIsInstance(r, pathlib.Path)
        self.assertTrue((r / "backend" / "server.py").is_file())
        self.assertTrue((r / "scripts" / "gpu-governor.sh").is_file())

    def test_relative_paths_resolve_against_the_root_not_the_cwd(self):
        self.assertEqual(workspace.resolve("backend/server.py"), workspace.root() / "backend/server.py")

    def test_absolute_paths_are_left_alone(self):
        self.assertEqual(workspace.resolve("/etc/hostname"), pathlib.Path("/etc/hostname"))


class GateTests(unittest.TestCase):



    def test_a_header_beats_a_query_parameter(self):
        got = gate.present_token({gate.HEADER: "from-header"}, {"token": "from-query"})
        self.assertEqual(got, "from-header")

    def test_bearer_and_query_are_both_accepted(self):
        """`<img src>` and `new WebSocket()` cannot set a header. Removing the query form
        would not make the surface safer, it would make images and live progress impossible."""
        self.assertEqual(gate.present_token({"authorization": "Bearer tok"}, {}), "tok")
        self.assertEqual(gate.present_token({}, {"token": "tok"}), "tok")
        self.assertIsNone(gate.present_token({}, {}))


class StudioLocalBypassTests(unittest.TestCase):
    """#88's chosen resolution, and the invariant it must never break.

    The complaint #88 records is real -- Studio answered 503 unless a secret was exported, so
    Garrett could not open his own surface. The naive fix was rejected because `ops/Caddyfile`
    delegates `/studio` AND `/studio/*`, and `/studio/editor/*` proxies ComfyUI's own editor
    over seven methods plus a WebSocket, so dropping the token would have published a ComfyUI
    admin surface (`docs/ops/SECURITY-AUDIT.md` BLOCKER-1).

    So the bypass drops **token friction on the local path only**, and the thing these tests
    exist to pin is the sentence it must never violate:

        it bypasses the SECRET, never the SWITCH.

    `local_bypass()` is not a master allow switch. If a future change makes it one,
    `test_disabled_studio_refuses_even_with_the_bypass_flag` is the test that fails.
    """

    KEYS = (gate.ENV_ENABLED, gate.ENV_LOCAL_BYPASS)

    def setUp(self):
        import os
        self._keep = {k: os.environ.get(k) for k in self.KEYS}

    def tearDown(self):
        import os
        for k, v in self._keep.items():
            os.environ.pop(k, None)
            if v is not None:
                os.environ[k] = v

    def _env(self, **kw):
        """Set exactly the three variables under test; absent means unset, not empty."""
        import os
        # `token=` is still accepted as a keyword and deliberately ignored: NO API KEYS,
        # 2026-09-11. Callers below pass it, and silently dropping it here is one edit
        # instead of thirty.
        for key, val in ((gate.ENV_ENABLED, kw.get("enabled")),
                         (gate.ENV_LOCAL_BYPASS, kw.get("bypass"))):
            os.environ.pop(key, None)
            if val is not None:
                os.environ[key] = val

    # -- the invariant -------------------------------------------------------------------

    def test_disabled_studio_refuses_even_with_the_bypass_flag(self):
        """The one that must never go green by accident.

        Both spellings of off: the variable absent, and the variable explicitly "0". A bypass
        that let either through would be a master allow switch, which is exactly what the
        chosen #88 path is not.
        """
        for enabled_v in (None, "0", "true", "yes", "TRUE"):
            with self.subTest(enabled=enabled_v):
                self._env(enabled=enabled_v, bypass="1")
                self.assertFalse(gate.local_bypass("127.0.0.1", {}))


    # -- the bypass itself ---------------------------------------------------------------

    def test_enabled_plus_bypass_plus_loopback_succeeds_without_a_token(self):
        self._env(enabled="1", bypass="1")           # deliberately no token at all
        for peer in gate.LOCAL_PEERS:
            with self.subTest(peer=peer):
                self.assertTrue(gate.local_bypass(peer, {}))

    def test_a_remote_peer_is_refused_even_with_the_bypass_on(self):
        self._env(enabled="1", bypass="1")
        for peer in ("203.0.113.9", "10.0.0.4", "192.168.1.20", "::ffff:127.0.0.1", "", None):
            with self.subTest(peer=peer):
                self.assertFalse(gate.local_bypass(peer, {}))

    def test_a_loopback_peer_carrying_proxy_headers_is_refused(self):
        """The case the peer check alone waves through.

        Caddy sets these on everything it proxies, so their presence means the request crossed
        the reverse proxy even though the socket says loopback -- which is what a future
        `handle /studio*` change would produce. Both spellings, because a plain dict is
        case-sensitive where Starlette's `Headers` is not.
        """
        self._env(enabled="1", bypass="1")
        for name in gate.PROXY_HEADERS:
            for spelling in (name, name.title()):
                with self.subTest(header=spelling):
                    self.assertFalse(gate.local_bypass("127.0.0.1", {spelling: "1.2.3.4"}))

    def test_without_the_flag_there_is_no_bypass(self):
        """Default OFF. Absent is not empty and not "0" -- all three are no."""
        for bypass_v in (None, "", "0", "true", "yes", "TRUE", "on"):
            with self.subTest(bypass=bypass_v):
                self._env(enabled="1", token="s3cret", bypass=bypass_v)
                self.assertFalse(gate.local_bypass("127.0.0.1", {}))


    def test_a_valid_token_still_works_while_the_bypass_is_on(self):
        """The bypass is additive. A remote caller with the right token is still let in by the
        normal path, so switching it on cannot lock anybody out."""
        self._env(enabled="1", token="s3cret", bypass="1")
        self.assertFalse(gate.local_bypass("203.0.113.9", {}))   # bypass says no
        self.assertTrue(gate.enabled())                          # and the token path says yes
        self.assertTrue(gate.token_ok("s3cret"))

    # -- the helper it is built on -------------------------------------------------------

    def test_local_request_is_two_conditions_and_needs_both(self):
        self.assertTrue(gate.local_request("127.0.0.1", {}))
        self.assertFalse(gate.local_request("127.0.0.1", {"x-forwarded-for": "1.2.3.4"}))
        self.assertFalse(gate.local_request("8.8.8.8", {}))
        self.assertFalse(gate.local_request("8.8.8.8", {"x-forwarded-for": "1.2.3.4"}))

    def test_the_bypass_is_spelled_for_studio_alone(self):
        """No other surface's gate is reachable through this flag, and no token was collapsed.

        The eight surfaces behind their own `_ENABLED`/`_TOKEN` pairs stay separate -- #88's
        note records that the risk type differs per surface, so one flag must not answer for
        all of them.
        """
        self.assertEqual(gate.ENV_LOCAL_BYPASS, "SYMONEURAL_STUDIO_LOCAL_BYPASS")
        self.assertIn("STUDIO", gate.ENV_LOCAL_BYPASS)
        self.assertEqual(gate.ENV_ENABLED, "SYMONEURAL_STUDIO_ENABLED")  # not removed


class WorkflowTests(unittest.TestCase):
    def test_schnell_parameters_are_schnells_and_not_stable_diffusions(self):
        g = workflows.get()
        ks = g["8"]["inputs"]
        # cfg 1.0 and 4 steps are the design point of a guidance-distilled model, not a
        # shortcut. Raising cfg does not sharpen the image, it destroys it -- which looks
        # exactly like a broken checkpoint and has cost hours elsewhere.
        self.assertEqual(ks["cfg"], 1.0)
        self.assertEqual(ks["steps"], 4)
        self.assertEqual(g["7"]["class_type"], "EmptySD3LatentImage",
                         "FLUX's latent space is 16-channel; EmptyLatentImage emits 4 and "
                         "KSampler fails on the shape mismatch")
        self.assertEqual(g["5"]["class_type"], "FluxGuidance")

    def test_every_link_points_at_a_node_that_exists(self):
        g = workflows.get()
        for nid, node in g.items():
            for name, value in node["inputs"].items():
                if isinstance(value, list) and len(value) == 2 and isinstance(value[1], int):
                    with self.subTest(node=nid, input=name):
                        self.assertIn(value[0], g)

    def test_there_is_exactly_one_output_node(self):
        g = workflows.get()
        saves = [n for n in g.values() if n["class_type"] == "SaveImage"]
        self.assertEqual(len(saves), 1)

    def test_get_hands_back_a_copy(self):
        """The library dicts are module level. A caller that injected into the original would
        silently change every later generation on the box."""
        a = workflows.get()
        a["8"]["inputs"]["steps"] = 999
        self.assertEqual(workflows.get()["8"]["inputs"]["steps"], 4)

    def test_every_parameter_map_address_lands_on_a_real_input(self):
        g = workflows.get()
        for friendly, address in workflows.PARAMETER_MAP.items():
            nid, _, field = address.partition(".")
            with self.subTest(parameter=friendly):
                self.assertIn(nid, g)
                self.assertIn(field, g[nid]["inputs"])


class InjectTests(unittest.TestCase):
    def test_an_exact_address_sets_one_input(self):
        out = graph.inject(workflows.get(), {"4.text": "a raven over a foundry"})
        self.assertEqual(out["graph"]["4"]["inputs"]["text"], "a raven over a foundry")
        self.assertEqual(out["unapplied"], [])

    def test_a_wildcard_only_updates_inputs_that_already_exist(self):
        out = graph.inject(workflows.get(), {"*.seed": 12345})
        self.assertEqual(out["graph"]["8"]["inputs"]["seed"], 12345)
        self.assertNotIn("seed", out["graph"]["4"]["inputs"])

    def test_a_bad_address_is_reported_not_raised(self):
        """The agent is the caller. A hard failure would end its turn over a typo it could
        have corrected from the response."""
        out = graph.inject(workflows.get(), {"99.text": "x", "nonsense": 1})
        self.assertEqual(len(out["unapplied"]), 2)
        self.assertEqual(out["applied"], [])

    def test_injection_does_not_touch_the_input_graph(self):
        g = workflows.get()
        graph.inject(g, {"4.text": "changed"})
        self.assertEqual(g["4"]["inputs"]["text"], "a photograph")


class QueueParameterTests(unittest.TestCase):
    """`routes._addresses`, the friendly-name -> `node.input` translation.

    These exist because `tests/studio.mjs` caught a bug that every unit test here missed:
    `POST /api/studio/queue` handed `{"width": 1024}` straight to `graph.inject`, which
    addresses `"7.width"`, so nothing was applied -- and then passed inject's *report* dict on
    as though it were the graph, producing a 500. A render with no parameters worked
    perfectly, which is exactly why it survived. The browser check submitted the page's own
    form, which always sends parameters.
    """

    def test_friendly_names_become_addresses(self):
        from . import router
        out = routes._addresses({"prompt": "a raven", "width": 768, "steps": 4})
        self.assertEqual(out, {"4.text": "a raven", "7.width": 768, "8.steps": 4})

    def test_an_explicit_address_is_passed_through(self):
        from . import router
        self.assertEqual(routes._addresses({"7.width": 512}), {"7.width": 512})

    def test_an_unknown_name_survives_to_be_reported(self):
        """Dropping it here would lose the only chance to tell the caller it was ignored;
        `graph.inject` puts it in `unapplied` with a reason, and `queue` returns that."""
        from . import router
        self.assertEqual(routes._addresses({"nonsense": 1}), {"nonsense": 1})

    def test_the_translated_addresses_all_land_on_the_stock_graph(self):
        from . import router
        params = {name: 0 for name in workflows.PARAMETER_MAP}
        out = graph.inject(workflows.get(), routes._addresses(params))
        self.assertEqual(out["unapplied"], [])


class EditorCookieTests(unittest.TestCase):
    """The proxied editor's session cookie.

    Also from `tests/studio.mjs`: the iframe's entry URL carries `?token=`, but the assets it
    then loads are relative URLs the browser fetches by itself, with no header and no query
    string. Seven of them 401'd and the canvas never appeared.
    """


    def test_a_header_still_wins_over_a_cookie(self):
        self.assertEqual(
            gate.present_token({gate.HEADER: "from-header"}, {}, {gate.COOKIE: "from-cookie"}),
            "from-header")

    def test_no_cookie_is_not_an_error(self):
        self.assertIsNone(gate.present_token({}, {}, None))

    def test_the_cookie_is_scoped_to_the_editor_only(self):
        """If this path ever widened to `/`, the operator token would be attached to every
        request to the public site, including pages served to anyone."""
        self.assertEqual(gate.COOKIE_PATH, "/studio/editor")


class PageTests(unittest.TestCase):
    """The fragment and the generated page. `tools/build/build_studio.py` asserts these too, at
    build time; these run in CI-shaped invocations where nobody ran the generator."""

    def setUp(self):
        self.fragment = (APP / "page.html").read_text()

    def test_the_markers_the_generator_looks_for_are_present(self):
        self.assertTrue(self.fragment.strip().startswith("<!-- BEGIN STUDIO -->"))
        self.assertTrue(self.fragment.strip().endswith("<!-- END STUDIO -->"))

    def test_no_ellipsis_rule_survives_in_the_stylesheet(self):
        """Comment-stripped, because the fragment opens with a comment in capitals promising
        there is none -- and a substring search cannot tell a rule from a promise not to write
        one. That distinction has produced a red check on healthy input before."""
        css = re.sub(r"/\*.*?\*/", "", self.fragment, flags=re.S)
        css = re.sub(r"<!--.*?-->", "", css, flags=re.S)
        self.assertNotIn("text-overflow", css)

    def test_every_selector_is_namespaced(self):
        """Three separate bugs on this site came from generic class names colliding across
        components: `.bar`, `.live` and `#console .sub`. Every rule here hangs off `#studio`."""
        style = re.search(r"<style>(.*?)</style>", self.fragment, re.S)
        self.assertIsNotNone(style)
        body = re.sub(r"/\*.*?\*/", "", style.group(1), flags=re.S)
        for block in body.split("}"):
            selector = block.split("{")[0].strip()
            if not selector or selector.startswith("@"):
                continue
            for part in selector.split(","):
                part = part.strip()
                if not part:
                    continue
                with self.subTest(selector=part):
                    self.assertTrue(part.startswith("#studio"),
                                    f"{part!r} is not namespaced to #studio")

    def test_neither_protected_artefact_is_named(self):
        for artefact in ("corpus.jsonl", "build_dataset"):
            self.assertNotIn(artefact, self.fragment)
            self.assertNotIn(artefact, (APP / "page.js").read_text())

    def _regenerate(self, tmp: pathlib.Path) -> tuple[str, str]:
        """Run `tools/build/build_studio.py` with its output directory pointed at `tmp`.

        The generator's transform lives inside `main()`, which writes. Rather than reimplement
        it here -- a copy of a transform asserts nothing about the transform -- `SITE` is
        redirected and the real `main()` runs, so this compares against the code that actually
        builds the page.
        """
        sys.path.insert(0, str(ROOT / "tools"))
        try:
            import build_studio
        except ImportError as exc:                # pragma: no cover -- tools/ is in the repo
            self.skipTest(f"tools/build/build_studio.py is not importable: {exc}")
        finally:
            sys.path.pop(0)
        with mock.patch.object(build_studio, "SITE", tmp), \
                mock.patch("builtins.print", lambda *a, **k: None):
            build_studio.main()
        return (tmp / "studio.html").read_text(), (tmp / "studio.js").read_text()

    def test_the_built_page_is_this_generators_output_with_stamps_added(self):
        """`site/studio.html` must be this generator's output plus cache-bust stamps.

        The generator emits plain `href="/symoneural.css"`; `tools/build/build_cachebust.py` rewrites
        those to `?v=<hash>` so a week-old cached stylesheet can never be served against new
        markup. Any *other* difference means `site/` was hand-edited or built from a different
        fragment, and a page whose stamps have been stripped -- the state a bare generator run
        leaves behind, which `.claude/CLAUDE.md` records happening to seven pages at once --
        fails here with the stamp count it is missing rather than shipping.
        """
        built = ROOT / "site" / "studio.html"
        if not built.is_file():
            self.skipTest("site/studio.html not generated in this checkout")
        shipped = built.read_text()
        with tempfile.TemporaryDirectory() as td:
            html, js = self._regenerate(pathlib.Path(td))
        stamps = re.findall(r"\?v=[0-9a-f]+", shipped)
        self.assertEqual(re.sub(r"\?v=[0-9a-f]+", "", shipped), html,
                         "site/studio.html is not build_studio.py's output; regenerate it")
        self.assertTrue(stamps,
                        "site/studio.html carries no ?v= stamps -- a generator was run without "
                        "`python3 tools/build/build_cachebust.py` afterwards, so its CSS and JS are "
                        "cacheable for a week with no way to invalidate them")
        shipped_js = ROOT / "site" / "studio.js"
        self.assertEqual(shipped_js.read_text(), js,
                         "site/studio.js is not a copy of the app's page.js")

    def test_the_built_page_kept_the_id_its_stylesheet_hangs_off(self):
        built = ROOT / "site" / "studio.html"
        if not built.is_file():
            self.skipTest("site/studio.html not generated in this checkout")
        html = built.read_text()
        self.assertIn('id="studio"', html)
        self.assertNotIn('class="wrap">\n      <div class="wrap"', html)
        self.assertNotIn("@@", html)


if __name__ == "__main__":
    unittest.main()


# ---------------------------------------------------------------------------
# Regression tests for the correctness items in the 2026-08-19 closeout review.
# Each one fails if its fix is reverted; that was checked by reverting them.
# ---------------------------------------------------------------------------
def _code_only(source: str) -> str:
    """`source` with comments and string literals removed, as one space-joined token stream."""
    kept = []
    for token in tokenize.generate_tokens(io.StringIO(source).readline):
        if token.type in (tokenize.COMMENT, tokenize.STRING):
            continue
        kept.append(token.string)
    return " ".join(kept)


class _FakeBrowserSocket:
    """Records what a relay sent, in order, keeping text and binary distinguishable."""

    def __init__(self) -> None:
        self.frames: list = []

    async def send_json(self, payload) -> None:
        # Through `json.dumps`, deliberately: the bug being guarded here is a payload that a
        # real socket would refuse, and a fake that merely stores the dict would not see it.
        self.frames.append(("json", json.loads(json.dumps(payload))))

    async def send_bytes(self, blob) -> None:
        self.frames.append(("bytes", bytes(blob)))


class _FakeComfySocket:
    """Enough of a websockets connection for `ComfyClient.watch`: `recv`, and then silence."""

    def __init__(self, frames) -> None:
        self.frames = list(frames)

    async def recv(self):
        if self.frames:
            return self.frames.pop(0)
        await asyncio.sleep(3600)       # `watch`'s idle timeout ends the iteration


class JobTrackingTests(unittest.TestCase):
    def test_the_release_task_is_referenced_while_it_runs(self):
        async def go():
            started = asyncio.Event()
            release = asyncio.Event()

            async def body():
                started.set()
                await release.wait()

            task = routes._track_job(body(), "p-1")
            await started.wait()
            # Nothing else holds this task. Unreferenced, it can be collected mid-await, and
            # this task is the only caller of `_KEEPER.leave()` -- losing one holds the governor
            # lock for the life of the process.
            self.assertIn(task, routes._JOBS)
            release.set()
            await task
            self.assertNotIn(task, routes._JOBS, "the set leaks finished tasks")
        asyncio.run(go())

    def test_a_tracking_task_that_raises_is_reported_on_state(self):
        async def go():
            async def body():
                raise RuntimeError("history poll died")

            keeper = routes._LeaseKeeper()
            with mock.patch.object(routes, "_KEEPER", keeper):
                task = routes._track_job(body(), "p-2")
                with self.assertRaises(RuntimeError):
                    await task
                await asyncio.sleep(0)
            reported = keeper.snapshot(full=True)["last_job_error"]
            self.assertIsNotNone(reported, "nobody awaits this task, so /state is the only "
                                           "place its failure can appear")
            self.assertEqual(reported["prompt_id"], "p-2")
            self.assertIn("history poll died", reported["error"])
        asyncio.run(go())

    def test_a_tokenless_reader_gets_the_fact_of_the_failure_and_not_its_text(self):
        """`/state` says it discloses presence/absence. An exception string is not that.

        A `/history` poll dies with whatever the failure carries -- a filesystem path, an
        upstream URL, a slice of a response body. The page needs to know a job failed and when,
        which is presence and a timestamp; the sentence is for whoever holds the token.
        """
        async def go():
            async def body():
                raise RuntimeError("/home/google/Symoneural/run/secret-path.json is missing")

            keeper = routes._LeaseKeeper()
            with mock.patch.object(routes, "_KEEPER", keeper):
                task = routes._track_job(body(), "p-3")
                with self.assertRaises(RuntimeError):
                    await task
                await asyncio.sleep(0)
            public = keeper.snapshot(full=False)["last_job_error"]
            self.assertEqual(public, {"present": True, "at": keeper._job_error["at"]})
            self.assertNotIn("error", public)
            self.assertNotIn("secret-path", repr(public))
            # And the token holder still gets the whole thing, or this is a fix that removed the
            # only place the failure was readable.
            self.assertIn("secret-path", keeper.snapshot(full=True)["last_job_error"]["error"])
        asyncio.run(go())

    def test_a_clean_keeper_reports_no_job_error_either_way(self):
        keeper = routes._LeaseKeeper()
        self.assertIsNone(keeper.snapshot(full=False)["last_job_error"])
        self.assertIsNone(keeper.snapshot(full=True)["last_job_error"])


class RunCommandTests(unittest.TestCase):
    """These test run_command's MECHANICS -- timeout kill, output capture -- not its
    authorisation. Since the authority plane landed, the tool refuses without a bound task,
    so each test holds a `service` grant for its duration. Without this they fail with
    NoTask, which is the gate working correctly rather than a regression in the behaviour
    they were written to pin. `AuthorityRefusesUngrantedCallers` below covers the other half.
    """

    def setUp(self):
        import os, tempfile
        import authority
        self.enterContext(unittest.mock.patch.dict(
            os.environ, {"SYMONEURAL_AUTHORITY_DIR": tempfile.mkdtemp()}))
        self.enterContext(authority.acting_as(authority.Task(
            task_id="t-run-command-mechanics", owner="test",
            mutation_authority=("service",))))

    def test_a_backgrounded_child_does_not_outlive_the_timeout(self):
        from .tools_impl import host

        marker = "sleep 4747"
        started = time.time()
        result = host.run_command(f"nohup {marker} > /dev/null 2>&1 & echo queued; sleep 20",
                                 timeout=2)
        elapsed = time.time() - started
        # The defect: `subprocess.run`'s timeout kills `/bin/sh` and then calls `communicate()`
        # again with no timeout, so the inherited stdout pipe held this call open forever. Sync
        # tools dispatch through `anyio.to_thread.run_sync`, so enough of these stall the whole
        # serving API.
        self.assertEqual(result.get("error"), "timeout")
        self.assertEqual(result.get("killed"), "process_group")
        self.assertLess(elapsed, 15, f"the call did not return promptly ({elapsed:.1f}s)")
        self.assertIn("queued", result.get("stdout", ""))
        survivors = subprocess.run(["pgrep", "-f", marker], capture_output=True, text=True)
        self.assertEqual(survivors.stdout.strip(), "", "the process group outlived the kill")

    def test_output_and_exit_code_still_come_back(self):
        from .tools_impl import host

        result = host.run_command("echo out; echo err 1>&2; exit 7")
        self.assertEqual(result["exit_code"], 7)
        self.assertEqual(result["stdout"].strip(), "out")
        self.assertEqual(result["stderr"].strip(), "err")


class ReadFileTests(unittest.TestCase):
    def test_max_bytes_bounds_the_read_and_not_just_the_return_value(self):
        from .tools_impl import fs

        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as fh:
            fh.write(b"text at the front so the NUL check does not call this binary\n" * 32)
            fh.truncate(1 << 30)                 # a sparse gibibyte; costs no disk
            path = fh.name
        try:
            # `read_bytes()[:max_bytes]` pulled the whole file in first, which is an OOM on any
            # of the multi-GB `.gguf` files under `backend/models/`. If the implementation goes
            # back to it, this patch turns that into a failure instead of a slow pass.
            with mock.patch.object(pathlib.Path, "read_bytes",
                                   side_effect=AssertionError("read the whole file")):
                result = fs.read_file(path, max_bytes=64)
            self.assertEqual(result["bytes_returned"], 64)
            self.assertTrue(result["truncated"])
            self.assertEqual(len(result["text"]), 64)
        finally:
            os.unlink(path)

    def test_a_file_shorter_than_the_limit_is_not_reported_as_truncated(self):
        from .tools_impl import fs

        result = fs.read_file(str(APP / "test_studio.py"))
        self.assertFalse(result["truncated"])
        self.assertEqual(result["bytes"], result["bytes_returned"])


#: A string this repo does not contain, assembled so that it is not a literal in this file --
#: see `SearchBoundTests.test_no_matches_is_a_result_and_not_an_error` for why that matters.
_NEEDLE = "zzz-no-such-" + "string-in-this-tree-" + "zzz"


class SearchBoundTests(unittest.TestCase):
    """`search` and `find_files` bound the *work*, which is the claim their docstrings make.

    Written the same way as `ReadFileTests` above and for the same reason: the failure being
    guarded is a revert to `subprocess.run(capture_output=True)`, which passes every assertion
    about the returned list while running grep over the whole tree first. So the check is not
    "did five results come back" -- it is "was `subprocess.run` never reached". Patching it to
    raise turns the slow-but-correct implementation into a red test instead of a quiet one.

    The wall-clock evidence these were written against, taken 2026-08-19 on this box:
    `search("def", "/", max_results=5)` returns in **0.05 s**, where a plain
    `grep -rnI def backend/` runs 2.41 s and produces 342,656 lines -- all of which the previous
    implementation materialised in the serving process before slicing to five.
    """

    def test_search_never_runs_grep_to_completion(self):
        from .tools_impl import fs

        with mock.patch.object(fs.subprocess, "run",
                               side_effect=AssertionError("ran the search to completion")):
            result = fs.search("def", str(APP), max_results=5)
        self.assertEqual(result["count"], 5)
        self.assertEqual(len(result["matches"]), 5)
        self.assertTrue(result["truncated"])

    def test_find_files_never_runs_find_to_completion(self):
        from .tools_impl import fs

        with mock.patch.object(fs.subprocess, "run",
                               side_effect=AssertionError("ran the walk to completion")):
            result = fs.find_files("*.py", str(APP), max_results=2)
        self.assertEqual(result["count"], 2)
        self.assertTrue(result["truncated"])

    def test_find_files_count_agrees_with_the_list_it_reports(self):
        from .tools_impl import fs

        # This is a behaviour change, deliberately locked in. `count` used to be the total
        # matched while `files` was the truncated slice, so a caller reading `count` and then
        # `len(files)` got two different numbers from one reply and neither was labelled.
        result = fs.find_files("*.py", str(APP), max_results=2)
        self.assertEqual(result["count"], len(result["files"]))

    def test_no_matches_is_a_result_and_not_an_error(self):
        from .tools_impl import fs

        # grep exits 1 when it matches nothing. The implementation never consults the exit
        # code, and this is the case that would surface it as `search_failed` if it started to.
        #
        # The needle is assembled at runtime rather than written as one literal, because the
        # first draft of this test searched the directory this file lives in for a string that
        # this file therefore contained, and got two hits. A literal here is a test that fails
        # the moment it is written down.
        result = fs.search(_NEEDLE, str(APP))
        self.assertNotIn("error", result)
        self.assertEqual(result["count"], 0)
        self.assertFalse(result["truncated"])
        self.assertNotIn("timed_out_after_s", result)

    def test_the_deadline_is_reported_separately_from_truncation(self):
        from .tools_impl import fs

        # A pattern that matches nothing over a tree too big to finish: the count bound can
        # never trip, so only the timer can end this. `timed_out_after_s` is what distinguishes
        # "there is more" from "we stopped looking before we knew", and an empty result with no
        # such key would be a claim that the tree really contains no matches.
        with mock.patch.object(fs, "SEARCH_TIMEOUT_S", 1):
            started = time.monotonic()
            result = fs.search(_NEEDLE, "/", max_results=5)
            elapsed = time.monotonic() - started
        self.assertEqual(result["timed_out_after_s"], 1)
        self.assertFalse(result["truncated"])
        self.assertLess(elapsed, 10, f"the deadline did not fire promptly ({elapsed:.1f}s)")


class EventRelayTests(unittest.TestCase):
    def test_a_preview_goes_out_as_a_json_header_then_a_binary_frame(self):
        async def go():
            ws = _FakeBrowserSocket()
            event = {"type": "preview", "data": {"prompt_id": "p", "bytes": 3,
                                                "format": "image/jpeg"},
                     "binary": b"\xff\xd8\xff"}
            await routes._relay_event(ws, event)
            self.assertEqual([kind for kind, _ in ws.frames], ["json", "bytes"])
            header = ws.frames[0][1]
            self.assertNotIn("binary", header, "bytes in a JSON frame is the original crash")
            self.assertEqual(header["data"]["format"], "image/jpeg")
            self.assertEqual(ws.frames[1][1], b"\xff\xd8\xff")
        asyncio.run(go())

    def test_an_ordinary_event_is_one_frame(self):
        async def go():
            ws = _FakeBrowserSocket()
            await routes._relay_event(ws, {"type": "progress",
                                           "data": {"value": 2, "max": 4, "node": "3"}})
            self.assertEqual([kind for kind, _ in ws.frames], ["json"])
        asyncio.run(go())

    def test_watch_names_the_preview_format_instead_of_dropping_the_header(self):
        async def go():
            # Two big-endian uint32s -- event type 1, format 2 (PNG) -- then the image.
            frame = (1).to_bytes(4, "big") + (2).to_bytes(4, "big") + b"\x89PNG"
            client = comfy.ComfyClient(client_id="test")
            events = []
            async for event in client.watch(_FakeComfySocket([frame]), idle_timeout=0.05):
                events.append(event)
            self.assertEqual(events[0]["type"], "preview")
            self.assertEqual(events[0]["data"]["format"], "image/png")
            self.assertEqual(events[0]["data"]["bytes"], 4)
            self.assertEqual(events[0]["binary"], b"\x89PNG")
            self.assertEqual(events[-1]["type"], "monitor_timeout")
        asyncio.run(go())


class MissingWorkspaceTests(unittest.TestCase):
    """The tokenless status surfaces must report absence, not raise it."""

    def test_nothing_that_reports_status_calls_the_raising_accessor(self):
        # Read from disk rather than imported: `mcp_server` exits at import time when `fastmcp`
        # is absent, which it is on the system interpreter and must stay -- see this file's
        # header. `inspect.getsource` on an unimportable module is not available to us.
        #
        # Comments and strings are stripped first. All three files *discuss* `workspace.root()`
        # in the comment explaining why they no longer call it, and a substring search cannot
        # tell a call from a note about one -- the same rule-versus-promise problem
        # `build_studio.without_comments` exists for. The assertion message stays short on
        # purpose: printing the diff means printing three whole modules.
        for name in ("routes.py", "mcp_server.py", "__init__.py"):
            with self.subTest(module=name):
                code = _code_only((APP / name).read_text())
                # `workspace.root()` raises `RuntimeError` when discovery found nothing. Every
                # caller here is a status path, and `api.py:build_status()` calls `status()`
                # inline -- so one unlocatable checkout 500'd the whole dashboard.
                if re.search(r"workspace\s*\.\s*root\s*\(", code):
                    self.fail(f"{name} calls workspace.root(), which raises; a status path "
                              f"must read workspace.ROOT and report None")

    def test_the_rack_row_reports_a_missing_checkout_instead_of_raising(self):
        import sys

        # This module's own package object, not `apps.studio`: pytest imports the
        # test file as `symoneuralstudio.test_studio`, so the two are different module objects
        # with different `workspace` attributes and the patch below would miss.
        pkg = sys.modules[__package__]

        with mock.patch.dict(os.environ, {"SYMONEURAL_STUDIO_ENABLED": "1",
                                          "SYMONEURAL_STUDIO_TOKEN": "t"}), \
             mock.patch.object(workspace, "ROOT", None):
            row = pkg.status()
        self.assertEqual(row["state"], "offline")   # a Unit.state literal, checked in api.py
        self.assertIn("SYMONEURAL_STUDIO_ROOT", row["detail"])

    def test_describe_reports_a_null_root_rather_than_raising(self):
        with mock.patch.object(workspace, "ROOT", None):
            described = workspace.describe()
        self.assertIsNone(described["root"])
        # `page.js` renders `ws.root || 'not found'` with a `set SYMONEURAL_STUDIO_ROOT` hint. That
        # branch was dead code while `/state` 500'd instead of reaching it.
        self.assertEqual(described["override_env"], "SYMONEURAL_STUDIO_ROOT")


class AuthorityRefusesUngrantedCallers(unittest.TestCase):
    """The other half of RunCommandTests: with no task bound, the shell refuses.

    Studio admits a caller with `enabled() + token_ok()`; that is admission, not authority.
    This is the assertion that the 28 tools behind that gate do not come with the right to
    change the host.
    """

    def test_run_command_refuses_without_a_task(self):
        import os, tempfile
        import authority
        from .tools_impl import host
        with unittest.mock.patch.dict(os.environ,
                                      {"SYMONEURAL_AUTHORITY_DIR": tempfile.mkdtemp()}):
            with self.assertRaises(authority.NoTask):
                host.run_command("echo this must not run")
