"""Every path `scripts/gpu-governor.sh` names must exist, and its kills must name our engines.

Two defects motivated this file, both found on 2026-08-20 and both of the same shape: a
command whose primary silently could not run, masked by a `||` fallback that could.

    chat)  "$HERE/symoneural" _stop-chat ... || pkill -f 'llama-server'
    comfy) "$HERE/comfyui.sh" stop        ... || pkill -f 'ComfyUI/main.py'

`HERE` is the repo root, so those were `<root>/symoneural` and `<root>/comfyui.sh`. Neither
has ever existed -- the CLI is `bin/symoneural-cli` and the launcher, since 2026-08-21, is
`scripts/symoneural-ui.sh` --
so **every** chat eviction and **every** ComfyUI eviction took the fallback. For comfy that
fallback is the ungraceful kill its own arm spends a paragraph arguing against: the process
exits before the driver returns the memory and the next tenant OOMs at step 0.

Nothing caught it because a `||` chain cannot fail. This does, by reading the script and
checking the filesystem rather than trusting either.
"""
from __future__ import annotations

import pathlib
import re
import unittest

ROOT = next(_p for _p in pathlib.Path(__file__).resolve().parents if (_p / "backend" / "server.py").is_file())
GOVERNOR = ROOT / "scripts" / "gpu-governor.sh"
SOURCE = GOVERNOR.read_text()

#: `"$HERE/<path>"` and `"$ROOT/<path>"` as invoked commands. Comment lines are stripped
#: before this is applied: the header comment on `HERE` quotes the two old broken spellings
#: verbatim so the next reader knows what went wrong, and matching those would make this
#: file fail on its own documentation. (It did, first run.)
INVOKED = re.compile(r'"\$(?:HERE|ROOT)/([A-Za-z0-9._/-]+)"')

#: The script with comments removed, which is what any check on *behaviour* must read.
CODE = "\n".join(l for l in SOURCE.splitlines() if not l.lstrip().startswith("#"))

#: What the engines are actually called. `bin/` anchors these to the binary rather than to a
#: log file or a python process that merely mentions the name.
LLM = "bin/symoneural-llm"
DIFFUSE = "bin/symoneural-diffuse"

#: Names this project may not kill by, because it neither builds nor ships them. Renaming an
#: engine without moving its pkill leaves the kill switch pointing at nothing.
RETIRED = ("llama-server", "sd-cli", "llama.cpp", "stable-diffusion.cpp",
           "ComfyUI/main.py")
#: `ComfyUI/main.py` joined that list on 2026-08-21. The render UI is now
#: `symoneural-ui`, produced by `tools/sh/fork_render_ui.sh` from the vendored tree, and
#: the directory that pattern named is not on disk under any spelling -- so the `comfy)`
#: fallback would have matched nothing while reporting success, which is this file's subject.


class EveryInvokedPathExists(unittest.TestCase):
    def test_the_governor_only_invokes_paths_that_are_on_disk(self):
        """A `||` fallback makes a missing primary invisible. Check the disk instead."""
        found = INVOKED.findall(CODE)
        self.assertGreaterEqual(len(found), 2,
                                "the $HERE/$ROOT invocations vanished -- if they moved, move "
                                "this check with them rather than letting it pass vacuously")
        for rel in found:
            with self.subTest(path=rel):
                self.assertTrue((ROOT / rel).exists(),
                                f"gpu-governor.sh invokes $HERE/{rel}, which is not on disk. "
                                "Its `||` fallback will run instead and nothing will say so.")

    def test_the_two_graceful_stops_are_still_the_ones_we_expect(self):
        """Named explicitly: these two are the arms whose fallback is *worse* than the
        primary, so losing either to a silent path break is a real regression and not a
        cosmetic one."""
        for rel in ("bin/symoneural-cli", "scripts/symoneural-ui.sh"):
            with self.subTest(path=rel):
                self.assertIn(f'"$HERE/{rel}"', CODE,
                              f"the governor no longer invokes {rel}; the graceful stop it "
                              "guards has been lost or renamed")


class EvictionKillsNameOurEngines(unittest.TestCase):
    def test_no_eviction_arm_kills_by_a_retired_upstream_name(self):
        """`tools/sh/fork_engines.sh` builds both engines under our names. A pkill left on an
        upstream name matches no running process, so the governor logs a successful
        eviction while the tenant keeps the card -- the failure the `miner)` arm records."""
        kills = [l for l in CODE.splitlines() if "pkill" in l]
        self.assertTrue(kills, "no pkill lines found -- this file is reading the wrong script")
        for line in kills:
            for retired in RETIRED:
                with self.subTest(line=line.strip()[:60], retired=retired):
                    self.assertNotIn(retired, line,
                                     f"an eviction still kills by {retired!r}, which this "
                                     "project does not build")

    def test_the_default_arm_refuses_instead_of_killing_both_engines(self):
        """The `*)` arm must REFUSE. It used to kill both engines, and that was the bug.

        This test previously asserted the opposite -- that the default arm reached both
        `symoneural-llm` and `symoneural-diffuse` -- on the reasoning that an unnamed tenant
        must still be evictable. The reasoning was sound and the conclusion was wrong, and
        it took `surface_pattern()` to show why: an unknown surface's liveness probe is
        *itself* the two engines, because `surface_pattern`'s own `*)` returns
        `symoneural-llm/|symoneural-diffuse/`. So a typo in a surface name reads as live
        whenever chat OR image is running, and the old default arm then killed both of them
        -- stopping two working surfaces to make room for a name that does not exist.

        The card being held by something this script cannot name is a condition for a
        person. Failing closed loses an eviction; failing open loses two live surfaces.
        """
        default = [l for l in CODE.splitlines() if l.lstrip().startswith("*)")]
        arm = [l for l in default if "REFUSING" in l]
        self.assertTrue(arm, "the default eviction arm no longer refuses -- if it kills "
                             "again, a mistyped surface name takes chat and image with it")
        for line in default:
            self.assertNotIn("pkill", line,
                             "the default eviction arm kills by pattern again")

    def test_eviction_prefers_the_recorded_pid_over_any_pattern(self):
        """Building the identity path and then still running the pattern one proves nothing.

        The guard is structural: `evict` must consult `engine_is` BEFORE it reaches the
        `case` of pattern arms, and the pattern branch must announce itself as a fallback.
        """
        body = CODE.split("\nevict() {", 1)[1].split("\n}\n", 1)[0]
        self.assertIn("engine_is", body,
                      "evict() does not consult the recorded engine at all")
        self.assertLess(body.index("engine_is"), body.index("case "),
                        "evict() reaches the pattern arms before checking for a recorded "
                        "pid -- the identity path would never be taken")
        self.assertIn("FALLBACK", body,
                      "the pattern path no longer says it is a fallback, so a silent "
                      "regression to pattern killing would not show up in the log")

    def test_only_real_engine_spawns_record_an_engine_pid(self):
        """`api.run()` is a GENERAL subprocess helper and must not record every child.

        Shipped as a regression on 2026-09-10 and caught on the live box within the hour:
        `record_engine` was called unconditionally inside `run()`, which also runs
        `gpu-governor.sh acquire` and `release`. A chat request therefore left `run/engine`
        naming the governor's own acquire shell -- a process that had already exited --
        while the actual engine ran on under a different pid, holding 8.3 GB.

        Eviction would then find a dead pid, log "already exited -- nothing to signal",
        clear the record, and never stop the engine. That is WORSE than the pattern kill it
        replaced: it fails silently and the log looks correct.

        Measured at the time: `run/engine` read `chat 58079 58079` while `nvidia-smi`
        showed the engine at pid 58041, pgid 54797 -- the API's own group.
        """
        import ast
        api = (ROOT / "backend" / "server.py").read_text()
        tree = ast.parse(api)

        run_fn = next((n for n in ast.walk(tree)
                       if isinstance(n, ast.AsyncFunctionDef) and n.name == "run"), None)
        self.assertIsNotNone(run_fn, "api.run() is gone -- this guard needs rewriting")

        gate = {a.arg for a in run_fn.args.args} | {a.arg for a in run_fn.args.kwonlyargs}
        self.assertIn("is_engine", gate,
                      "api.run() no longer takes is_engine, so it either records every "
                      "child again or the opt-in was renamed without updating this guard")

        calls = [n for n in ast.walk(run_fn)
                 if isinstance(n, ast.Call) and getattr(n.func, "id", None) == "record_engine"]
        self.assertTrue(calls, "run() never records an engine at all -- the identity path "
                               "is dead for the diffusion engine")
        for c in calls:
            parent_ifs = [n for n in ast.walk(run_fn)
                          if isinstance(n, ast.If) and any(c is x for x in ast.walk(n))]
            self.assertTrue(parent_ifs,
                            "record_engine() is called unconditionally inside run() -- "
                            "every governor acquire would overwrite the engine record")

    def test_a_pgid_is_never_recorded_for_a_process_that_does_not_lead_its_group(self):
        """`kill -TERM -<pgid>` against a group we merely belong to signals symoneural-api.

        Two of the three spawn sites do not pass `start_new_session=True`, so their child's
        process group is the API's own. Recording that pgid would arm a group kill aimed at
        ourselves -- strictly worse than the pattern kill being replaced.
        """
        body = CODE.split("\ncmd_engine() {", 1)[1].split("\n}\n", 1)[0]
        self.assertIn('"$pgid" != "$pid"', body,
                      "cmd_engine does not verify that the pid leads the recorded group")
        self.assertIn("not a group leader", body,
                      "cmd_engine drops an unverified pgid without saying so")


class TheGovernorTracksTheManifestedEngine(unittest.TestCase):
    """The manifest is authoritative for the engine's location; the governor holds a literal.

    `scripts/gpu-governor.sh` deliberately does not read `ops/manifests/llm-engine.json` at
    runtime -- it runs from `ExecStartPre` on the path that hands the card over, and a failed
    read would produce an empty pattern, which `pgrep -f` matches against every process on the
    box. The governor would then log a successful eviction of a tenant that still holds the
    memory, which is worse than the staleness it would be guarding against.

    So the literal is checked HERE instead. Moving the engine now fails a test rather than
    quietly breaking eviction, and there is still exactly one authored source for where the
    engine lives.
    """

    def manifest(self):
        import json
        return json.loads((ROOT / "ops" / "manifests" / "llm-engine.json").read_text())

    def test_the_chat_probe_pattern_still_covers_the_manifested_engine(self):
        """`surface_pattern chat` is what decides whether chat is resident. If it stops being
        a prefix of the manifested engine path, the probe answers "nothing is running" about a
        process that is -- and `evict` logs a stale-marker message and hands the card over."""
        rel = self.manifest()["relative_path"]
        m = re.search(r'chat\)\s+echo "\$ROOT/([^"]+)"', CODE)
        self.assertIsNotNone(m, "the chat arm of surface_pattern is gone or has been reshaped; "
                                "move this check with it rather than letting it pass vacuously")
        pattern = m.group(1)
        self.assertTrue(
            rel.startswith(pattern.rstrip("/") + "/") or rel == pattern.rstrip("/"),
            f"gpu-governor.sh probes for {pattern!r} but ops/manifests/llm-engine.json says "
            f"the engine is at {rel!r}. The probe would not find a running engine.")

    def test_the_chat_and_default_kills_name_the_manifested_binary(self):
        """The pkill patterns are unanchored by design (see the governor's own comment), so
        what is checked is that the tail they match is the manifested binary's, not that the
        whole path agrees."""
        server = self.manifest()["server"]["relative_path"]
        tail = "/".join(pathlib.PurePosixPath(server).parts[-2:])   # bin/symoneural-llm
        kills = [l for l in CODE.splitlines() if "pkill" in l and "symoneural-llm" in l]
        self.assertTrue(kills, "no eviction arm kills the inference engine any more")
        for line in kills:
            with self.subTest(line=line.strip()[:60]):
                self.assertIn(tail, line,
                              f"an eviction kills by a pattern that does not name {tail!r}, "
                              "which is what ops/manifests/llm-engine.json records")

    def test_the_governor_introduces_no_second_identity_source(self):
        """A hash pasted in here would be a second thing to go stale, and the manifest would
        stop being the single source of truth the moment it disagreed. `gateway-build.json`
        spent three days disagreeing with reality precisely because nothing read it."""
        self.assertNotRegex(CODE, r"\b[0-9a-f]{64}\b",
                            "gpu-governor.sh contains what looks like a sha256; artifact "
                            "identity belongs in ops/manifests/, read via artifact.sh")
        # Anchored on `$ROOT/` so this counts DIRECTORY spellings, which is what a second
        # identity source would look like. It must not also match the `bin/symoneural-llm`
        # pkill patterns -- those are the binary tail, and the test above already checks
        # them against the manifest. The anchor used to be `engines/`; the 2026-09-08
        # promotion of the runtimes to the repo root moved it, and a blanket path rewrite
        # briefly dropped the anchor altogether, which made this assertion count two
        # unrelated things and fail. A rename that edits an assertion changes what is
        # being checked, which is worse than breaking a path.
        engine_paths = set(re.findall(r"\$ROOT/symoneural-llm[A-Za-z0-9._/-]*", CODE))
        self.assertLessEqual(len(engine_paths), 1,
                             f"the governor names the LLM engine by {len(engine_paths)} "
                             f"different paths: {sorted(engine_paths)}. One is the pattern; "
                             "any more is a second identity source.")


if __name__ == "__main__":
    unittest.main()
