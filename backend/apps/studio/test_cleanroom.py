"""The spec-mediated reimplementation pipeline, and the honesty claims it makes.

No model is called anywhere below. The two tools each make exactly one `inference` call and
that call is the part with no interesting behaviour; everything that could be wrong about this
module is in the parts around it -- what reaches the second prompt, what the licence block
says, what gets refused, and whether the leak figure is a measurement or a decoration.

Every test here was written by breaking the thing it covers and watching it go red. The two
that matter most:

* `test_the_source_cannot_reach_the_second_prompt` passes a spec with the source text smuggled
  into an extra key. Change `_prompt_from_spec` to iterate `spec.items()` instead of
  `SPEC_FIELDS` -- which reads like a tidier implementation of the same thing -- and the source
  appears in the clean half's prompt and this fails.
* `test_a_copyleft_source_is_not_laundered_by_the_pipeline` is the one that has legal weight
  rather than technical weight, and it is asserted on the generated text a human will read.
"""
import dataclasses
import hashlib
import importlib.util
import pathlib
import re
import shutil
import tempfile
import unittest

from . import registry, workspace
from .tools_impl import cleanroom


class TheWireHasShapeTests(unittest.TestCase):
    """`FunctionalSpec` is the connection wire, so its schema is the feature.

    A `pydantic.BaseModel` here would have rendered as an untyped object: `registry._json_type`
    understands primitives, enums and **dataclasses**, and nothing else. So would a dataclass in
    a module carrying `from __future__ import annotations`, because `dataclasses.fields()[].type`
    is then the annotation's source text rather than the class. Both failures are silent -- the
    tool still works, the schema is just shapeless -- which is why they are asserted.
    """

    def test_the_spec_parameter_renders_as_a_typed_object(self):
        params = registry.TOOLS["generate_native_code"].parameters
        spec = params["properties"]["spec"]
        self.assertEqual("object", spec.get("type"))
        for field in cleanroom.SPEC_FIELDS:
            self.assertIn(field, spec["properties"], f"{field} missing from the wire schema")

    def test_the_list_fields_are_arrays_of_strings(self):
        spec = registry.TOOLS["generate_native_code"].parameters["properties"]["spec"]
        for field in ("inputs", "outputs", "logic_steps", "edge_cases"):
            self.assertEqual({"type": "array", "items": {"type": "string"}},
                             spec["properties"][field], field)

    def test_provenance_and_leakage_are_part_of_the_wire_not_beside_it(self):
        # A spec that has lost the licence of the thing it describes is not a smaller spec,
        # it is a wrong one -- so both travel inside the object, not as sibling keys the
        # second node would have to be wired separately to receive.
        spec = registry.TOOLS["generate_native_code"].parameters["properties"]["spec"]
        self.assertEqual("object", spec["properties"]["provenance"]["type"])
        self.assertEqual("object", spec["properties"]["leakage"]["type"])
        self.assertIn("license", spec["properties"]["provenance"]["properties"])
        self.assertIn("leaked", spec["properties"]["leakage"]["properties"])

    def test_the_dataclass_field_types_are_types_and_not_strings(self):
        """The condition itself, rather than a grep for the import that causes it.

        A first attempt at this asserted `"from __future__ import annotations" not in` the
        module source and failed on the module's own docstring, which explains the hazard by
        naming it. Grepping for the cause of a defect finds every mention of the cause; this
        checks the defect.
        """
        for field in dataclasses.fields(cleanroom.FunctionalSpec):
            self.assertNotIsInstance(
                field.type, str,
                f"{field.name} is annotated with a string, so registry._json_type cannot "
                f"render it and the wire schema silently loses its shape")
        self.assertIs(cleanroom.Provenance,
                      {f.name: f.type for f in
                       dataclasses.fields(cleanroom.FunctionalSpec)}["provenance"])

    def test_both_tools_are_registered_under_one_group(self):
        self.assertEqual("cleanroom", registry.TOOLS["extract_spec"].group)
        self.assertEqual("cleanroom", registry.TOOLS["generate_native_code"].group)


class LeakageIsMeasuredNotAssertedTests(unittest.TestCase):
    """The prompt says "do not output original variable names". Nothing enforces that.

    So the module returns a number instead of a claim. These tests are about the number being
    a real reading: that it finds a leak, that it reports zero honestly, and that the stoplist
    it applies is visible in a second count rather than hidden.
    """

    SOURCE = ("static int frobnicate_widget(struct widget_ctx *ctx, size_t nmemb) {\n"
              "  unsigned long checksum_accumulator = 0;\n"
              "  for (size_t i = 0; i < nmemb; i++) checksum_accumulator += ctx->data[i];\n"
              "  return checksum_accumulator & 0xff;\n"
              "}\n")

    def test_a_leaked_identifier_is_found_and_named(self):
        leak = cleanroom._leakage(self.SOURCE, "Calls frobnicate_widget over the input.")
        self.assertIn("frobnicate_widget", leak.leaked)
        self.assertEqual(1, leak.leaked_count)
        self.assertGreater(leak.ratio, 0.0)

    def test_a_description_in_roles_leaks_nothing(self):
        clean = ("Sums the bytes of a caller-supplied region and returns the low eight bits "
                 "of that total.")
        self.assertEqual([], cleanroom._leakage(self.SOURCE, clean).leaked)
        self.assertEqual(0.0, cleanroom._leakage(self.SOURCE, clean).ratio)

    def test_the_stoplist_is_reported_rather_than_applied_silently(self):
        # `data` is a source identifier AND a stoplist word, so it must not inflate `leaked`
        # and must still be visible in `leaked_raw_count`. One number with the judgement
        # hidden inside it would be the decoration this module exists to avoid.
        leak = cleanroom._leakage(self.SOURCE, "Reads the data in order.")
        self.assertEqual([], leak.leaked)
        self.assertGreater(leak.leaked_raw_count, 0)
        self.assertIn("stoplist", leak.method)

    def test_the_comparison_is_case_sensitive(self):
        # "Checksum accumulator" at the start of a sentence is English, not a leaked symbol.
        leak = cleanroom._leakage(self.SOURCE, "Checksum_accumulator is not this identifier.")
        self.assertNotIn("checksum_accumulator", leak.leaked)

    def test_the_denominator_is_never_zero(self):
        self.assertEqual(0.0, cleanroom._leakage("", "anything at all").ratio)


class TheCleanHalfHasNoChannelTests(unittest.TestCase):
    """The second turn must not be able to see the source, whatever it is handed.

    "It has never seen the original source code" is the claim the brief's prompt makes about
    this half. It is a claim about the prompt's *contents*, so it is checkable here, and the
    check is what makes it more than a sentence in a system message.
    """

    SMUGGLED = "static int frobnicate_widget(void) { return 0xdeadbeef; }"

    def spec(self):
        return {
            "module_name": "byte-sum accumulator",
            "purpose": "Sum a region and return the low byte.",
            "inputs": ["a caller-supplied region", "its element count"],
            "outputs": ["the low eight bits of the total"],
            "logic_steps": ["walk the region", "accumulate", "mask to eight bits"],
            "edge_cases": ["a zero-length region returns zero"],
            # Not a spec field. A caller could put anything here -- a hostile caller, or an
            # honest one round-tripping the whole tool result -- and it must not travel.
            "source_text": self.SMUGGLED,
            "provenance": {"source_path": "/tmp/dirty_library.c", "license": "MIT"},
        }

    def test_the_source_cannot_reach_the_second_prompt(self):
        prompt = cleanroom._prompt_from_spec(self.spec(), "Apple", "swift")
        self.assertNotIn("frobnicate_widget", prompt)
        self.assertNotIn("0xdeadbeef", prompt)
        self.assertNotIn(self.SMUGGLED, prompt)

    def test_the_provenance_path_does_not_travel_either(self):
        # The path alone would name the file, and often the project with it.
        prompt = cleanroom._prompt_from_spec(self.spec(), "linux", "python")
        self.assertNotIn("dirty_library", prompt)

    def test_the_six_declared_fields_do_travel(self):
        prompt = cleanroom._prompt_from_spec(self.spec(), "linux", "rust")
        self.assertIn("Sum a region and return the low byte.", prompt)
        self.assertIn("mask to eight bits", prompt)
        self.assertIn("a zero-length region returns zero", prompt)
        self.assertIn("rust", prompt)


class AttributionIsGeneratedNotOptionalTests(unittest.TestCase):
    """This repo treats a notice as a licence condition, not a courtesy.

    `built on Qwen2.5-7B-Instruct` is on the rack because Apache-2.0 requires it, and a CSS
    ellipsis rule that truncated it was removed for that reason. Dropping a licence on the way
    through a reimplementation pipeline is the same failure with better cover.
    """

    APACHE = {"identified_by": "oematch", "project": "curl", "recipe": "recipes-support/curl/curl_8.21.0.bb",
              "layer": "openembedded-core", "license": "curl", "sha256": "ab" * 32,
              "attribution_required": True, "copyleft": False}
    GPL = dict(APACHE, project="busybox", license="GPL-2.0-only", copyleft=True)

    def test_the_project_and_licence_are_named(self):
        block = cleanroom.attribution_block(self.APACHE, "c")
        self.assertIn("curl", block)
        self.assertIn("Derived from:", block)
        self.assertIn("recipes-support/curl/curl_8.21.0.bb", block)

    def test_a_copyleft_source_is_not_laundered_by_the_pipeline(self):
        block = cleanroom.attribution_block(self.GPL, "python")
        self.assertIn("copyleft", block.lower())
        self.assertIn("human decision", block)

    def test_the_block_says_plainly_that_this_is_not_a_clean_room(self):
        # The one sentence a reader of the generated file most needs, in the file itself
        # rather than in this repo's documentation.
        for prov in (self.APACHE, self.GPL, {}):
            self.assertIn("Not a clean-room reimplementation.",
                          cleanroom.attribution_block(prov, "python"))

    def test_an_unidentified_source_says_so_instead_of_leaving_blanks(self):
        block = cleanroom.attribution_block({"identified_by": "unavailable"}, "python")
        self.assertIn("unidentified", block)
        self.assertNotIn("Derived from:  ", block)

    def test_the_comment_syntax_matches_the_target_language(self):
        self.assertTrue(cleanroom.attribution_block(self.APACHE, "python").startswith("# "))
        self.assertTrue(cleanroom.attribution_block(self.APACHE, "swift").startswith("// "))
        self.assertTrue(cleanroom.attribution_block(self.APACHE, "lua").startswith("-- "))
        # An unknown language gets `//` rather than nothing, because a header that is not a
        # comment is a syntax error in the generated file and reads as a broken tool.
        self.assertTrue(cleanroom.attribution_block(self.APACHE, "brainfuck").startswith("// "))

    def test_an_unknown_licence_requires_attribution_and_warns_of_copyleft(self):
        """Both flags true, and the copyleft one is deliberate -- see `_license_flags`.

        This row asserted `assertFalse(copyleft)` until the first real run reported that
        CGMiner's GPL-3.0-or-later fan controller was not copyleft. Silence is the wrong
        default for the only warning this module owes anybody.
        """
        attribution, copyleft = cleanroom._license_flags("")
        self.assertTrue(attribution)
        self.assertTrue(copyleft)

    def test_copyleft_is_over_reported_rather_than_under_reported(self):
        for spdx in ("GPL-2.0-only WITH Classpath-exception-2.0", "AGPL-3.0-only",
                     "LGPL-2.1-or-later", "MPL-2.0"):
            self.assertTrue(cleanroom._license_flags(spdx)[1], spdx)
        for spdx in ("MIT", "Apache-2.0", "BSD-3-Clause", "Zlib"):
            self.assertFalse(cleanroom._license_flags(spdx)[1], spdx)


class TheThreeUnpublishedArtefactsAreNeverReadTests(unittest.TestCase):
    """`extract_spec` reads an arbitrary path and hands the bytes to a model.

    That is exactly the route by which the corpus stops being unpublished: an operator or an
    agent asks for a "spec" of `training/corpus.jsonl` and the answer -- the company voice and
    the refusal policy, restated -- comes back through an HTTP surface. Refused by path.
    """

    def test_the_corpus_and_its_method_are_refused(self):
        for rel in ("training/corpus.jsonl", "training/build_dataset.py",
                    "training/adapter/adapter_model.safetensors"):
            with self.subTest(rel=rel):
                self.assertIsNotNone(cleanroom._refuse(workspace.ROOT / rel),
                                     f"{rel} must never be read here")

    def test_an_ordinary_source_file_is_allowed(self):
        self.assertIsNone(cleanroom._refuse(workspace.ROOT / "backend" / "api.py"))
        # A file whose path merely starts with the same letters is not the corpus.
        self.assertIsNone(cleanroom._refuse(workspace.ROOT / "training" / "README.md"))

    def test_reading_one_raises_rather_than_returning_empty(self):
        target = workspace.ROOT / "training" / "corpus.jsonl"
        if not target.exists():
            self.skipTest("no corpus on this tree")
        with self.assertRaises(PermissionError):
            cleanroom._read(str(target), 1024)


class AModelsProseAroundItsJsonTests(unittest.TestCase):
    """Local models fence their JSON and preface it. That is ordinary, not a malfunction."""

    DOC = '{"module_name": "x", "purpose": "y"}'

    def test_a_fenced_object_is_found(self):
        self.assertEqual({"module_name": "x", "purpose": "y"},
                         cleanroom._json_object(f"Here you go:\n```json\n{self.DOC}\n```"))

    def test_a_brace_inside_a_string_does_not_end_the_object(self):
        got = cleanroom._json_object('prose {"purpose": "returns { or }", "module_name": "z"} tail')
        self.assertEqual("returns { or }", got["purpose"])

    def test_an_escaped_quote_inside_a_string_is_survived(self):
        got = cleanroom._json_object(r'{"purpose": "says \"hello\"", "module_name": "q"}')
        self.assertEqual('says "hello"', got["purpose"])

    def test_nesting_is_survived(self):
        got = cleanroom._json_object('{"a": {"b": {"c": 1}}, "module_name": "n"}')
        self.assertEqual(1, got["a"]["b"]["c"])

    def test_a_reply_with_no_object_raises_rather_than_returning_a_blank_spec(self):
        with self.assertRaises(ValueError):
            cleanroom._json_object("I cannot help with that.")

    def test_a_broken_first_object_does_not_hide_a_good_second_one(self):
        got = cleanroom._json_object('{not json at all} then {"module_name": "ok"}')
        self.assertEqual("ok", got["module_name"])


class TheEmptySpecIsRefusedTests(unittest.IsolatedAsyncioTestCase):
    """A spec with none of the six fields would produce code from nothing.

    The model would happily write *something*, and that something would arrive carrying an
    attribution header, which makes it look like the output of a pipeline that ran.

    `inference.pick` is stubbed to return nothing for the duration. Not for speed: without the
    stub a box with llama-server resident would take a real 600-second-timeout completion out
    of this test, and one with it stopped would not -- so the suite would pass or hang
    depending on what was running, which is the worst kind of flake.
    """

    def setUp(self):
        self._pick = cleanroom.inference.pick

        async def none():
            return None
        cleanroom.inference.pick = none

    def tearDown(self):
        cleanroom.inference.pick = self._pick

    async def test_a_spec_with_no_declared_fields_is_refused_before_the_model(self):
        got = await cleanroom.generate_native_code({"provenance": {}, "leakage": {}})
        self.assertFalse(got["ok"])
        self.assertEqual("empty_spec", got["error"])

    async def test_a_non_object_spec_is_refused_with_the_type_it_got(self):
        got = await cleanroom.generate_native_code("a string of prose")
        self.assertFalse(got["ok"])
        self.assertEqual("bad_spec", got["error"])
        self.assertIn("str", got["detail"])

    async def test_a_dataclass_spec_is_accepted_as_well_as_a_dict(self):
        # The registry hands a dict over HTTP and MCP; a caller inside the process may hold
        # the dataclass. Both are the wire.
        spec = cleanroom.FunctionalSpec(
            module_name="m", purpose="p", inputs=[], outputs=[], logic_steps=["s"],
            edge_cases=[],
            provenance=cleanroom.Provenance("", "", 0, "", "", "", "", "undetermined",
                                            False, True, True, "test"),
            leakage=cleanroom._leakage("", ""))
        got = await cleanroom.generate_native_code(spec)
        # It reached the backend lookup and stopped there, which is the proof it passed the
        # shape checks above rather than being refused by them.
        self.assertEqual("no_backend", got["error"])
        self.assertTrue(dataclasses.is_dataclass(spec))


class TheLicenceIsReadFromTheFileItselfTests(unittest.TestCase):
    """The defect the first real run found, turned into tests.

    `extract_spec` was asking oematch for the licence and nothing else. oematch fingerprints
    packages: handed one `.c` file it answers `unsupported artifact`, so on this tool's own
    input the licence was always empty and `_license_flags("")` returned `copyleft=False`.
    The smoke run read CGMiner's GPL-3.0-or-later fan controller and the module reported
    that the GNU General Public License was not copyleft. These rows are the reason the
    header scan is the primary signal and oematch the fallback.
    """

    GPL3 = ("/*\n * Copyright 2018 Duan Hao\n *\n * This program is free software; you can\n"
            " * redistribute it and/or modify it under the terms of the GNU General Public\n"
            " * License as published by the Free Software Foundation; either version 3 of the\n"
            " * License, or (at your option) any later version.\n */\nint main(void){return 0;}\n")

    def test_a_gpl_paragraph_with_no_spdx_tag_is_still_found(self):
        spdx, how = cleanroom._license_from_text(self.GPL3)
        self.assertEqual("GPL-3.0-or-later", spdx)
        self.assertEqual("file header (licence text)", how)
        self.assertEqual((True, True), cleanroom._license_flags(spdx))

    def test_only_the_or_later_wording_produces_or_later(self):
        strict = self.GPL3.replace(", or (at your option) any later version", " only")
        self.assertEqual("GPL-3.0-only", cleanroom._license_from_text(strict)[0])

    def test_an_spdx_tag_wins_over_the_prose_below_it(self):
        text = "/* SPDX-License-Identifier: MIT */\n" + self.GPL3
        spdx, how = cleanroom._license_from_text(text)
        self.assertEqual("MIT", spdx)
        self.assertEqual("file header (SPDX tag)", how)

    def test_the_lesser_licence_is_not_read_as_the_one_it_contains(self):
        """"GNU Lesser General Public License" contains "General Public License"."""
        lgpl = self.GPL3.replace("GNU General Public", "GNU Lesser General Public")
        self.assertTrue(cleanroom._license_from_text(lgpl)[0].startswith("LGPL-"))

    def test_a_permissive_header_is_not_flagged_copyleft(self):
        spdx, _ = cleanroom._license_from_text(
            "// Permission is hereby granted, free of charge, to any person obtaining\n")
        self.assertEqual("MIT", spdx)
        self.assertEqual((True, False), cleanroom._license_flags(spdx))

    def test_an_undetermined_licence_is_treated_as_copyleft_not_as_permissive(self):
        self.assertEqual(("", ""), cleanroom._license_from_text("int main(void){return 0;}"))
        self.assertEqual((True, True), cleanroom._license_flags(""))

    def test_a_licence_sentence_far_down_the_file_is_not_a_licence(self):
        """A --version banner is not a licence statement about the file printing it."""
        text = "int main(void){return 0;}\n" + ("/* filler */\n" * 900) + self.GPL3
        self.assertGreater(len(text), cleanroom._HEADER_BYTES)
        self.assertEqual(("", ""), cleanroom._license_from_text(text))

    def test_the_undetermined_case_gets_its_own_sentence_in_the_attribution(self):
        undetermined = {"sha256": "ab" * 32, "copyleft": True, "license_determined": False,
                        "attribution_required": True, "identified_by": "unavailable"}
        known = dict(undetermined, license_determined=True, license="GPL-3.0-or-later",
                     license_source="file header (licence text)")
        a = cleanroom.attribution_block(undetermined, "c")
        b = cleanroom.attribution_block(known, "c")
        self.assertIn("could not be determined", a)
        self.assertNotIn("The source licence is copyleft", a)
        self.assertIn("The source licence is copyleft", b)
        self.assertNotIn("could not be determined", b)
        # And the determined one names the licence and how it was read, because a header
        # saying "copyleft" without saying which licence cannot be checked by anybody.
        self.assertIn("GPL-3.0-or-later", b)
        self.assertIn("file header (licence text)", b)

    def test_the_two_new_fields_are_on_the_wire(self):
        names = {f.name for f in dataclasses.fields(cleanroom.Provenance)}
        self.assertIn("license_source", names)
        self.assertIn("license_determined", names)


class TheProvenanceBuiltByARealExtractionTests(unittest.IsolatedAsyncioTestCase):
    """`extract_spec`'s own provenance block, with the model stubbed and the file real.

    Every other licence row here calls `_license_from_text` or `_license_flags` directly, and
    that left the one line that wires them into the tool untested: hardcoding
    `license_determined=True` in the builder kept the whole suite green. A helper that is
    correct and a call site that ignores it is the shape that shipped #94's dead chat surface
    and this module's own socket literal, so it gets a row of its own.
    """

    REPLY = ('{"module_name": "m", "purpose": "p", "inputs": [], "outputs": [], '
             '"logic_steps": ["s"], "edge_cases": []}')

    def setUp(self):
        self._pick = cleanroom.inference.pick
        reply = self.REPLY

        class Stub:
            name = "stub"
            base = "http://127.0.0.1:0"

            async def chat(self, **kw):
                return {"choices": [{"message": {"content": reply}}],
                        "model": "stub-model"}

        async def pick():
            return Stub()
        cleanroom.inference.pick = pick
        self.dir = pathlib.Path(tempfile.mkdtemp())

    def tearDown(self):
        cleanroom.inference.pick = self._pick
        shutil.rmtree(self.dir, ignore_errors=True)

    async def _spec_for(self, text):
        f = self.dir / "sample.c"
        f.write_text(text)
        got = await cleanroom.extract_spec(str(f))
        self.assertTrue(got.get("ok"), got)
        return got["spec"]["provenance"]

    async def test_a_gpl_header_reaches_the_provenance_block(self):
        prov = await self._spec_for(
            "/* This program is free software; you can redistribute it and/or modify it\n"
            " * under the terms of the GNU General Public License as published by the\n"
            " * Free Software Foundation; either version 3 of the License, or (at your\n"
            " * option) any later version. */\nint main(void){return 0;}\n")
        self.assertEqual("GPL-3.0-or-later", prov["license"])
        self.assertEqual("file header (licence text)", prov["license_source"])
        self.assertTrue(prov["license_determined"])
        self.assertTrue(prov["copyleft"])

    async def test_a_file_with_no_licence_says_so_rather_than_claiming_one(self):
        prov = await self._spec_for("int main(void){return 0;}\n")
        self.assertEqual("", prov["license"])
        self.assertEqual("undetermined", prov["license_source"])
        self.assertFalse(prov["license_determined"])
        # And still warns, which is the whole argument of `_license_flags`.
        self.assertTrue(prov["copyleft"])
        self.assertTrue(prov["attribution_required"])

    async def test_the_sha256_and_byte_count_are_of_the_bytes_actually_read(self):
        text = "/* SPDX-License-Identifier: MIT */\nint main(void){return 0;}\n"
        prov = await self._spec_for(text)
        self.assertEqual("MIT", prov["license"])
        self.assertEqual(len(text), prov["bytes_read"])
        self.assertEqual(hashlib.sha256(text.encode()).hexdigest(), prov["sha256"])


class TheNodePackAgreesWithTheToolsTests(unittest.TestCase):
    """The ComfyUI pack is a separate file loaded by a separate interpreter.

    Nothing at runtime checks that its socket name matches the tools', or that the tool names
    it POSTs to exist -- a mismatch is a node that refuses every connection, or one that 404s
    when the graph is queued, and both read as "the editor is broken".
    """

    @classmethod
    def setUpClass(cls):
        path = (pathlib.Path(__file__).parent / "custom_nodes" / "symoneural_cleanroom"
                / "__init__.py")
        if not path.is_file():
            raise unittest.SkipTest("node pack not present")
        spec = importlib.util.spec_from_file_location("_symoneural_cleanroom_nodes", path)
        cls.pack = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.pack)

    def test_the_graph_has_exactly_one_terminus_and_it_pulls_the_code(self):
        """ComfyUI executes backwards from output nodes only.

        Queueing extract -> generate with nothing else ran *neither* node: `execution_success`
        with an empty output set, because no OUTPUT_NODE depended on them. A user reads that as
        a broken editor. So the report node is the pipeline's only terminus and it takes the
        generator's three strings as optional inputs, which is what pulls the generator into
        the execution set. Optional, so a spec-only graph is still valid.
        """
        outputs = {n for n, c in self.pack.NODE_CLASS_MAPPINGS.items()
                   if getattr(c, "OUTPUT_NODE", False)}
        self.assertEqual({"SymoneuralSpecReport"}, outputs)
        report = self.pack.SymoneuralSpecReport.INPUT_TYPES()
        self.assertEqual(["spec"], list(report["required"]))
        self.assertEqual({"code", "attribution", "residual_leakage"},
                         set(report.get("optional") or {}))
        # Those three are fed by the generator's three returns, in order, so the types have
        # to line up or the edge is refused at queue time.
        gen = self.pack.SymoneuralGenerateNativeCode
        self.assertEqual(("code", "attribution", "residual_leakage"), gen.RETURN_NAMES)
        self.assertEqual(("STRING", "STRING", "STRING"), gen.RETURN_TYPES)
        for name in ("code", "attribution", "residual_leakage"):
            self.assertEqual("STRING", report["optional"][name][0])

    def test_the_report_runs_with_the_optional_inputs_absent(self):
        got = self.pack.SymoneuralSpecReport().run({"module_name": "m", "leakage": {}})
        text = got["ui"]["text"][0]
        self.assertIn("barrier: none", text)
        self.assertNotIn("code:", text)

    def test_the_socket_name_is_the_tools_socket_name(self):
        # ComfyUI validates an edge by string equality of the two type names, so a drift here
        # is the wire silently refusing to connect.
        self.assertEqual(cleanroom.SOCKET, self.pack.SOCKET)

    def test_the_fallback_literal_agrees_too(self):
        """The branch this test run does NOT take is the branch ComfyUI takes.

        The pack imports `SOCKET` from the tools and falls back to a literal when the repo is
        not importable -- and under ComfyUI's own venv it is not importable, so the literal is
        the shipped value and the import is the tested one. Changing that literal to
        `FUNCTIONAL_SPECIFICATION` was tried here and the whole suite stayed green, including
        the assertion directly above, because this process imports the repo fine. The
        untested branch is the one that runs.

        So the literal is read out of the source rather than out of the module.
        """
        src = pathlib.Path(self.pack.__file__).read_text()
        found = re.findall(r'^\s*_SOCKET\s*=\s*"([^"]+)"', src, re.M)
        self.assertTrue(found, "no fallback _SOCKET literal in the node pack")
        for literal in found:
            self.assertEqual(cleanroom.SOCKET, literal,
                             "the fallback socket name is what ComfyUI actually uses, because "
                             "the repo is not importable from its venv")

    def test_the_spec_flows_out_of_one_node_and_into_the_other(self):
        producer = self.pack.SymoneuralExtractSpec
        consumer = self.pack.SymoneuralGenerateNativeCode
        self.assertEqual(cleanroom.SOCKET, producer.RETURN_TYPES[0])
        self.assertEqual((cleanroom.SOCKET,),
                         consumer.INPUT_TYPES()["required"]["spec"])

    def test_every_tool_the_pack_calls_is_registered(self):
        src = pathlib.Path(self.pack.__file__).read_text()
        for name in ("extract_spec", "generate_native_code"):
            self.assertIn(f'call_tool("{name}"', src)
            self.assertIsNotNone(registry.get(name), f"{name} is not a registered tool")


    def test_every_pack_under_custom_nodes_is_relinked_by_the_launcher(self):
        """The launcher named `symoneural_gguf` literally until this pack landed.

        A hardcoded name fails as "the node is not in the ComfyUI menu", with nothing in any
        log, which is #94's shape: the code is on disk, every path check passes, and the
        surface is dead. Asserted against the script rather than against a comment.
        """
        sh = (workspace.ROOT / "scripts" / "symoneural-ui.sh").read_text()
        self.assertIn("custom_nodes/*", sh,
                      "the launcher must loop over the directory, not name one pack")
        self.assertNotIn('custom_nodes/symoneural_gguf"', sh)


if __name__ == "__main__":
    unittest.main()
