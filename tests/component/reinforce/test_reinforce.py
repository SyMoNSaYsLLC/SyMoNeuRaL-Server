"""SyMoNeuRaL Reinforce -- regression tests. Stdlib `unittest`, no dependencies.

    python3 -m unittest discover -s backend/apps -p 'test_reinforce.py' -v

`.claude/CLAUDE.md`'s framing, taken from the Reinforce engine's own suite: a constraint found
by audit is only a constraint once a test guards it. Every check here was verified to FAIL
when the thing it tests is reverted -- the four that matter most:

* remove the resident-bf16 term from the arithmetic and `test_resident_bf16_is_not_forgotten`
  and `test_7b_derivation_matches_the_safetensors_index` both fail;
* change `parse_log` to pass unmatched lines through and `test_log_parser_drops_unknown_lines`
  fails on the sentinel;
* drop the `is_denied` check from `admit()` and `test_corpus_is_refused_*` fail;
* change `build_script` to `acquire`/`release` and `test_launch_uses_the_with_form` fails.

Nothing here starts a real fine-tune, and nothing here reads `training/corpus.jsonl`. The
launch path is exercised separately and deliberately, by hand, with the step-capped Smoke
preset against a synthetic dataset:

    mkdir -p run/reinforce/datasets   # then write a few dummy {"messages": [...]} rows
    SYMONEURAL_REINFORCE_ENABLED=1 SYMONEURAL_REINFORCE_TOKEN=x python3 -c "\\
      import sys; sys.path.insert(0, 'backend/apps'); from reinforce import jobs; \\
      print(jobs.start('Qwen/Qwen2.5-7B-Instruct', 'smoke', \\
                       'run/reinforce/datasets/pipeline-smoke.jsonl'))"

A synthetic dataset rather than the real one on purpose: if the launch path had only ever been
exercised against the corpus, the guard that refuses the corpus would never have been tested
against a real launch.
"""
from __future__ import annotations

import json
import os
import pathlib
import sys
import tempfile
import unittest

sys.path.insert(0, str(next(_p for _p in pathlib.Path(__file__).resolve().parents if (_p / "backend" / "server.py").is_file())))

from reinforce import (dataset_guard, jobs, presets, registry,  # noqa: E402
                       rewards, rollout)

GIB = registry.GIB
SEVEN_B = "Qwen/Qwen2.5-7B-Instruct"


def _imported_modules(path: pathlib.Path) -> set[str]:
    """Every module name a file imports, from its AST.

    Source-text assertions about imports are unreliable in this package specifically, because
    these modules explain at length *why* they do not import torch. Ask the parser.
    """
    import ast
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            found.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            found.add(node.module or "")
    return found


def _top_level_imports(path: pathlib.Path) -> set[str]:
    """Only the imports at a file's MODULE level -- not the ones inside functions.

    Distinct from `_imported_modules` above, which walks the whole tree, and the distinction is
    the point for `runner.py`: it genuinely does import torch, transformers, peft and trl, but all
    of them inside `main()`. That is what lets the serving interpreter -- which has no training
    venv -- read the module's constants to check them against `jobs.py`. Walking the whole tree
    cannot tell "imports torch" from "imports torch lazily", and only the second is allowed here.
    """
    import ast
    found: set[str] = set()
    for node in ast.parse(path.read_text()).body:
        if isinstance(node, ast.Import):
            found.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom):
            found.add(node.module or "")
        elif isinstance(node, ast.Try):
            # A guarded `try: import x / except ImportError` is still module level.
            for inner in node.body:
                if isinstance(inner, ast.Import):
                    found.update(a.name for a in inner.names)
                elif isinstance(inner, ast.ImportFrom):
                    found.add(inner.module or "")
    return found


def _dict_keys_and_kwargs(path: pathlib.Path) -> set[str]:
    """Every literal dict key and keyword-argument name in a file, from its AST.

    Used to assert on what is actually *passed* to the trainer, rather than on what the
    surrounding comments say about it."""
    import ast
    names: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.keyword) and node.arg:
            names.add(node.arg)
        elif isinstance(node, ast.Dict):
            names.update(k.value for k in node.keys
                         if isinstance(k, ast.Constant) and isinstance(k.value, str))
        elif isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant) \
                and isinstance(node.slice.value, str):
            names.add(node.slice.value)
    return names


def _config_kwargs(path: pathlib.Path) -> dict[str, set[str]]:
    """The exact keys `runner.py` puts into each trl config, per objective.

    Scoped deliberately: `_dict_keys_and_kwargs` over the whole file would sweep up
    `parents=True` and every other unrelated keyword, and a test that asserts `parents` is a
    `GRPOConfig` field is a test that fails for no reason. What matters here is only the dicts
    that are splatted into `TrainingArguments`, `DPOConfig` and `GRPOConfig`.

    `targs` is the shared base and is charged to both, because both are built with `dict(targs)`.
    """
    import ast
    bases = {"targs": set(), "dpo": set(), "grpo": set()}
    for node in ast.walk(ast.parse(path.read_text())):
        # targs = dict(output_dir=..., ...)
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id in bases:
                    bases[t.id].update(k.arg for k in node.value.keywords if k.arg)
        # targs["max_steps"] = ... / dpo["beta"] = ... / grpo["use_vllm"] = ...
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Subscript) and isinstance(t.value, ast.Name) \
                        and t.value.id in bases and isinstance(t.slice, ast.Constant) \
                        and isinstance(t.slice.value, str):
                    bases[t.value.id].add(t.slice.value)
        # grpo.update(num_generations=..., ...)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) \
                and node.func.attr == "update" and isinstance(node.func.value, ast.Name) \
                and node.func.value.id in bases:
            bases[node.func.value.id].update(k.arg for k in node.keywords if k.arg)
    return {"dpo": bases["targs"] | bases["dpo"],
            "grpo": bases["targs"] | bases["grpo"],
            "targs": bases["targs"]}


class TrlContractTests(unittest.TestCase):
    """Every keyword this package hands to trl must exist in the trl that is installed.

    This is the third instance of the silent-agreement class that `MetricProtocolTests` and
    `ArgvContractTests` cover, and it is by far the most expensive one to get wrong. A field
    that trl 1.10.0 does not spell that way is a `TypeError` raised at stage `train` -- which
    is to say *after* a governor acquire of up to 300 seconds and a 4-bit load of a 7B model,
    having taken the card away from chat and image to get there. Preflight exists precisely so
    that a configuration fails in milliseconds and without the GPU; a kwarg typo is the one
    class of failure preflight could not see, because preflight never constructs a trl object.

    `reward_weights` is the proof this is not hypothetical: it reads naturally as a
    `GRPOTrainer` argument, it is not one, and only a source read caught it.

    The check runs in `training/.venv` over a subprocess, because trl and torch are absent
    from the serving interpreter this suite runs on -- and must stay absent.
    """

    PROBE = (
        "import dataclasses,inspect,json;"
        "from trl import GRPOConfig,DPOConfig,GRPOTrainer,DPOTrainer;"
        "print(json.dumps({"
        "'grpo':[f.name for f in dataclasses.fields(GRPOConfig)],"
        "'dpo':[f.name for f in dataclasses.fields(DPOConfig)],"
        "'grpo_init':list(inspect.signature(GRPOTrainer.__init__).parameters),"
        "'dpo_init':list(inspect.signature(DPOTrainer.__init__).parameters)}))"
    )

    @classmethod
    def _trl(cls):
        """The trl facts, or a skip. Never an import into this interpreter."""
        import subprocess
        repo = next((_p for _p in next(_p for _p in pathlib.Path(__file__).resolve().parents if (_p / "backend" / "server.py").is_file())s
                     if (_p / "backend" / "server.py").is_file()), None)
        assert repo is not None, "repo root not found above this test file"
        python = repo / "training" / ".venv" / "bin" / "python"
        if not python.exists():
            raise unittest.SkipTest(f"no training venv at {python}; trl cannot be inspected")
        out = subprocess.run([str(python), "-c", cls.PROBE],
                             capture_output=True, text=True, timeout=180)
        if out.returncode != 0:
            raise unittest.SkipTest(f"trl not importable in the training venv: {out.returncode}")
        return json.loads(out.stdout)

    def test_every_config_kwarg_exists_in_trl(self):
        trl = self._trl()
        kw = _config_kwargs(pathlib.Path(__file__).with_name("runner.py"))
        # Sentinels, not an emptiness check. `targs` is unioned into both, so renaming the
        # local `grpo` to anything else would drop all 16 RL-specific keys and still leave 17
        # base keys behind -- a test that passes while checking nothing that matters.
        for key, objective in (("num_generations", "grpo"), ("reward_weights", "grpo"),
                               ("precompute_ref_log_probs", "dpo"), ("beta", "grpo")):
            self.assertIn(key, kw[objective],
                          f"the AST scan did not find `{key}` among the {objective} config keys; "
                          f"it has drifted from how runner.py builds its configs and is now "
                          f"checking the shared base only")
        for objective, fields in (("grpo", set(trl["grpo"])), ("dpo", set(trl["dpo"]))):
            missing = kw[objective] - fields
            self.assertEqual(missing, set(),
                             f"runner.py passes {sorted(missing)} to the {objective} config, and "
                             f"the installed trl has no such field. This is a TypeError at stage "
                             f"'train', after the governor acquire and the model load.")

    # Values that come from `runner.py` as literals rather than from a preset. Kept here
    # rather than scraped, because the point of the construction test is to feed trl the
    # values a real run would and see whether its `__post_init__` accepts them.
    RUNNER_LITERALS = {
        "optim": "paged_adamw_8bit", "bf16": True, "report_to": [],
        "gradient_checkpointing": True, "per_device_train_batch_size": 1,
        "logging_steps": 1, "warmup_steps": 1, "seed": 0,
    }

    CONSTRUCT = (
        "import json,sys,tempfile;"
        "from trl import GRPOConfig,DPOConfig;"
        "cases=json.load(sys.stdin);bad=[]\n"
        "for name,kind,kw in cases:\n"
        "    kw['output_dir']=tempfile.mkdtemp()\n"
        "    try:(GRPOConfig if kind=='grpo' else DPOConfig)(**kw)\n"
        "    except Exception as e:bad.append([name,type(e).__name__,str(e)[:200]])\n"
        "print(json.dumps(bad))"
    )

    def test_every_preset_actually_constructs_its_trl_config(self):
        """Field *names* existing is not the same as field *values* being accepted.

        `optim`, `save_strategy`, `lr_scheduler_type`, `eval_strategy`, `loss_type`,
        `scale_rewards` and `vllm_mode` are all validated in `__post_init__`, so a wrong value
        raises at exactly the moment a wrong name would -- stage `train`, card already taken.
        Nothing had ever constructed `vllm_mode="server"` at all.
        """
        import subprocess
        repo = next((_p for _p in next(_p for _p in pathlib.Path(__file__).resolve().parents if (_p / "backend" / "server.py").is_file())s
                     if (_p / "backend" / "server.py").is_file()), None)
        assert repo is not None, "repo root not found above this test file"
        python = repo / "training" / ".venv" / "bin" / "python"
        if not python.exists():
            raise unittest.SkipTest(f"no training venv at {python}")

        cases = []
        for name, preset in presets.PRESETS.items():
            p = preset if isinstance(preset, dict) else preset.__dict__
            if p["method"] == "sft":
                continue
            mc = dict(p["method_config"])
            # `reference`, `rewards` and `rollout` are this package's own vocabulary and are
            # never splatted into a trl config -- runner.py reads them and passes the results.
            for own in ("reference", "rewards", "rollout"):
                mc.pop(own, None)
            kw = dict(self.RUNNER_LITERALS)
            kw.update(num_train_epochs=p["epochs"], learning_rate=p["learning_rate"],
                      gradient_accumulation_steps=p["gradient_accumulation_steps"],
                      lr_scheduler_type=p["lr_scheduler_type"],
                      save_strategy=p["save_strategy"],
                      eval_strategy="epoch" if p["val_split"] else "no")
            if p["method"] == "preference":
                kw.update(mc, max_length=p["max_length"], precompute_ref_batch_size=1)
                cases.append([name, "dpo", kw])
            else:
                kw.update(mc, remove_unused_columns=False, log_completions=True,
                          num_completions_to_print=2, use_cache=True, reward_weights=[1.0])
                cases.append([name, "grpo", kw])
                vllm = dict(kw, use_vllm=True, vllm_mode="server",
                            vllm_server_base_url="http://example.invalid:8000")
                cases.append([name + "+vllm", "grpo", vllm])

        self.assertTrue(cases, "no preference or reinforcement preset was found to construct")
        out = subprocess.run([str(python), "-c", self.CONSTRUCT], input=json.dumps(cases),
                             capture_output=True, text=True, timeout=300)
        if out.returncode != 0:
            raise unittest.SkipTest(f"trl not importable in the training venv: {out.stderr[-200:]}")
        bad = json.loads(out.stdout.strip().splitlines()[-1])
        self.assertEqual(bad, [], f"these configurations do not construct under the installed "
                                  f"trl, and would raise at stage 'train': {bad}")

    HELP_PROBE = (
        "import dataclasses,json;"
        "from trl import GRPOConfig,DPOConfig;"
        "print(json.dumps({c.__name__:{f.name:[str(f.metadata.get('help','')),repr(f.default)]"
        " for f in dataclasses.fields(c)} for c in (GRPOConfig,DPOConfig)}))"
    )

    def test_the_free_string_settings_are_values_trl_still_supports(self):
        """The gap the construction test cannot close, closed a different way.

        `optim` and `lr_scheduler_type` are enum-validated, so a wrong value raises at
        construction and `test_every_preset_actually_constructs_its_trl_config` catches it.
        `loss_type`, `scale_rewards` and `vllm_mode` are **not**: trl 1.10.0 annotates all
        three as plain `str` with no `Literal`, and constructing one with `scale_rewards=
        "banana"` raises nothing at all -- verified. A wrong value there is either a silent
        change of algorithm or a failure deep in the trainer.

        There is no machine-readable set of valid values to check against, so this checks the
        two things that do exist: trl's own default, and the supported values its `help`
        metadata names. Both are real sources and both break loudly if a future trl drops a
        mode, which is the actual risk -- `vllm_mode` defaults to `colocate`, the mode this
        package refuses by arithmetic, so `server` being silently renamed would hand every
        rollout to a co-tenant that cannot fit.
        """
        import subprocess
        repo = next((_p for _p in next(_p for _p in pathlib.Path(__file__).resolve().parents if (_p / "backend" / "server.py").is_file())s
                     if (_p / "backend" / "server.py").is_file()), None)
        assert repo is not None, "repo root not found above this test file"
        python = repo / "training" / ".venv" / "bin" / "python"
        if not python.exists():
            raise unittest.SkipTest(f"no training venv at {python}")
        out = subprocess.run([str(python), "-c", self.HELP_PROBE],
                             capture_output=True, text=True, timeout=180)
        if out.returncode != 0:
            raise unittest.SkipTest("trl not importable in the training venv")
        meta = json.loads(out.stdout)

        used = {("GRPOConfig", "loss_type"): {"dapo"},
                ("GRPOConfig", "scale_rewards"): {"group"},
                ("GRPOConfig", "vllm_mode"): {"server"},
                ("DPOConfig", "loss_type"): {"sigmoid"}}
        for preset in presets.PRESETS.values():
            p = preset if isinstance(preset, dict) else preset.__dict__
            cfg = "DPOConfig" if p["method"] == "preference" else "GRPOConfig"
            for key in ("loss_type", "scale_rewards"):
                if key in p["method_config"]:
                    used[(cfg, key)].add(p["method_config"][key])

        for (cls, field), values in used.items():
            helptext, default = meta[cls][field]
            for value in values:
                with self.subTest(config=cls, field=field, value=value):
                    # A word-boundary match, not a quoted one: trl's own help for
                    # `scale_rewards` writes ``True` or `group'` -- an unbalanced quote in
                    # upstream's docstring -- and a test that fails on someone else's typo is
                    # a test that gets deleted.
                    import re
                    self.assertRegex(helptext, rf"\b{re.escape(value)}\b",
                                  f"{cls}.{field}={value!r} is no longer named among the values "
                                  f"trl's own help lists; it is a plain `str` field, so nothing "
                                  f"would have raised -- it would just quietly do something else")

    def test_trainer_arguments_are_spelled_the_way_trl_spells_them(self):
        trl = self._trl()
        for param in ("model", "reward_funcs", "args", "train_dataset", "processing_class",
                      "callbacks"):
            self.assertIn(param, trl["grpo_init"], f"GRPOTrainer has no `{param}` parameter")
        for param in ("model", "ref_model", "args", "train_dataset", "eval_dataset",
                      "processing_class", "callbacks"):
            self.assertIn(param, trl["dpo_init"], f"DPOTrainer has no `{param}` parameter")

    def test_reward_weights_is_a_config_field_and_not_a_trainer_argument(self):
        """The specific mistake this class exists for, pinned so it cannot come back."""
        trl = self._trl()
        self.assertIn("reward_weights", trl["grpo"],
                      "reward_weights is not a GRPOConfig field; runner.py sets it there")
        self.assertNotIn("reward_weights", trl["grpo_init"],
                         "reward_weights has become a GRPOTrainer parameter -- the comment in "
                         "runner.py explaining why it is set on the config is now wrong")

    def test_max_prompt_length_is_absent_so_the_cap_stays_ours_to_enforce(self):
        """`registry` and `runner` bound the prompt themselves *because* trl will not.

        If a later trl gains the field, the hand-rolled cap is no longer the only thing
        standing between an over-long prompt and a truncation nobody asked for, and the two
        would need reconciling. Asserted so that change is noticed rather than inherited.
        """
        trl = self._trl()
        self.assertNotIn("max_prompt_length", trl["grpo"],
                         "GRPOConfig now has max_prompt_length; this package drops over-long "
                         "prompts itself on the stated grounds that it does not")


class RewardInvocationTests(unittest.TestCase):
    """How trl *calls* a reward function, which is one layer later than how it is configured.

    `grpo_trainer.py:1672` is the call site, and it is unforgiving:

        output_reward_func = reward_func(
            prompts=prompts, completions=completions, completion_ids=completion_ids_list,
            **reward_kwargs)

    `reward_kwargs` carries every surviving dataset column -- which is the whole reason
    `remove_unused_columns=False` is set -- and, unconditionally, `trainer_state` and
    `log_metric`. So a reward function that does not absorb arbitrary keywords raises
    `TypeError` at the **first reward computation**: inside the training loop, after the
    acquire, after the 4-bit load, after a group of rollouts has already been generated. That
    is later and more expensive than the construction failure `TrlContractTests` covers, and
    no RL run has ever executed on this box, so nothing else has exercised this path.

    trl also requires exactly one reward per prompt (it raises by name and count otherwise).
    """

    def _callables(self):
        funcs = {}
        for spec in rewards.offered():
            fn = getattr(rewards, spec["id"], None)
            self.assertTrue(callable(fn), f"rewards.offered() names {spec['id']}, which is not "
                                          f"a callable in rewards.py")
            funcs[spec["id"]] = fn
        self.assertTrue(funcs, "no reward functions are offered at all")
        return funcs

    def test_every_reward_absorbs_the_keywords_trl_passes(self):
        import inspect
        for name, fn in self._callables().items():
            with self.subTest(reward=name):
                params = inspect.signature(fn).parameters
                self.assertTrue(
                    any(p.kind is inspect.Parameter.VAR_KEYWORD for p in params.values()),
                    f"{name} has no **kwargs, so trl's `trainer_state`/`log_metric` -- and any "
                    f"dataset column that happens to be present -- raise TypeError inside the "
                    f"training loop, after the rollouts have already been paid for")
                for required in ("prompts", "completions"):
                    if required in params:
                        self.assertIsNot(
                            params[required].default, inspect.Parameter.empty,
                            f"{name}'s `{required}` has no default; every caller in this package "
                            f"other than trl treats these as optional")

    def test_a_reward_survives_the_exact_call_trl_makes(self):
        """The signature check proves it accepts the keywords; this proves it runs on them."""
        completions = ["Prices are set by the operator; email symonsayadmin@symoneural.com.",
                       "151 tok/s, measured on this machine."]
        for name, fn in self._callables().items():
            with self.subTest(reward=name):
                got = fn(prompts=["a question", "another"], completions=completions,
                         completion_ids=[[1, 2], [3, 4]],
                         # Not ours, and always present: trl adds both unconditionally.
                         trainer_state=None, log_metric=lambda *a, **k: None,
                         # A dataset column that this reward may or may not want.
                         answer=["x", "y"])
                self.assertEqual(len(got), len(completions),
                                 f"{name} returned {len(got)} rewards for {len(completions)} "
                                 f"completions; trl raises ValueError by name on that")
                for value in got:
                    self.assertTrue(value is None or isinstance(value, (int, float)),
                                    f"{name} returned {value!r}; trl converts None to NaN but "
                                    f"casts everything else with torch.tensor(dtype=float32)")


class ArgvContractTests(unittest.TestCase):
    """`jobs.py` builds an argv; `runner.py` parses one. Neither imports the other.

    A flag on one side and not the other is argparse exit 2 with the complaint on *stderr* --
    and `parse_log()` reads stdout through an allowlist, so the panel sees a run that failed
    with no kind and no stage. That is the same silent outcome `MetricProtocolTests` exists to
    prevent, reached by a different route.
    """

    @staticmethod
    def _flags(name: str) -> set[str]:
        import ast
        path = pathlib.Path(__file__).with_name(name)
        return {n.value for n in ast.walk(ast.parse(path.read_text()))
                if isinstance(n, ast.Constant) and isinstance(n.value, str)
                and n.value.startswith("--") and n.value != "--"}

    def test_every_flag_jobs_emits_is_one_runner_accepts(self):
        emitted, accepted = self._flags("jobs.py"), self._flags("runner.py")
        self.assertTrue(len(emitted) > 20,
                        "the flag scan found almost nothing; it has stopped testing anything")
        unknown = emitted - accepted
        self.assertEqual(unknown, set(),
                         f"jobs.py passes {sorted(unknown)} and runner.py's parser does not "
                         f"accept it: argparse exits 2 on stderr and the run reports nothing")


class RouteImportTests(unittest.TestCase):
    """`routes.py` is the one bay module this suite does not otherwise import.

    Everything else here is exercised directly, so a typo in a module name or an `except`
    clause naming an exception that does not exist would be caught. `routes.py` is only ever
    reached by `api.py` -- which does not mount it yet -- so nothing would have caught it.
    """

    def test_routes_imports_on_the_serving_interpreter(self):
        try:
            from reinforce import router         # noqa: F401
        except ImportError as exc:               # fastapi is an OS package; absence is not a bug
            raise unittest.SkipTest(f"fastapi unavailable on this interpreter: {exc}")
        self.assertTrue(routes.router.routes, "the router carries no routes at all")

    def test_the_exceptions_routes_catches_are_real(self):
        """An `except jobs.Typo` is a NameError raised only on the failure path.

        Which is to say: it would surface for the first time on the request that was already
        going wrong, and turn a clean refusal into a 500.
        """
        try:
            from reinforce import router         # noqa: F401
        except ImportError as exc:
            raise unittest.SkipTest(f"fastapi unavailable on this interpreter: {exc}")
        import ast
        tree = ast.parse(pathlib.Path(__file__).with_name("routes.py").read_text())
        checked = 0
        for node in ast.walk(tree):
            if not isinstance(node, ast.ExceptHandler) or node.type is None:
                continue
            for name in ([node.type] if not isinstance(node.type, ast.Tuple) else node.type.elts):
                if isinstance(name, ast.Attribute) and isinstance(name.value, ast.Name):
                    module = getattr(routes, name.value.id, None)
                    if module is None:
                        continue
                    self.assertTrue(hasattr(module, name.attr),
                                    f"routes.py catches {name.value.id}.{name.attr}, which does "
                                    f"not exist -- a NameError on the failure path")
                    checked += 1
        self.assertTrue(checked, "no qualified except clauses were found to check")


class ArithmeticTests(unittest.TestCase):
    """The VRAM model. Arithmetic is only trustworthy where it lands on something real."""

    def test_7b_derivation_matches_the_safetensors_index(self):
        """The parameter count derived from config.json must equal the index's total_size / 2.

        This is the check that makes every other projection believable: if the split between
        quantised and bf16-resident parameters were wrong, the total would not land on the
        file. bf16 is two bytes per parameter, so total_size / 2 is the parameter count, and
        the two numbers must agree exactly -- not approximately.
        """
        entry = registry.find(SEVEN_B)
        if entry is None or not entry.present:
            self.skipTest("the 7B is not in the local weight cache")
        snap = registry.ROOT / entry.path
        index = snap / "model.safetensors.index.json"
        if not index.is_file():
            self.skipTest("no safetensors index in the snapshot")
        total_size = json.loads(index.read_text())["metadata"]["total_size"]
        arch = registry.Arch(**entry.arch)
        self.assertEqual(arch.total_params, total_size // 2)

    def test_resident_bf16_is_not_forgotten(self):
        """Embeddings and lm_head stay at bf16 and are over a gibibyte on a 152k vocabulary.

        This is the term a naive `params x 0.5 bytes` estimate throws away, and throwing it
        away is the most common reason a 'this fits' estimate OOMs at step 0.
        """
        entry = registry.find(SEVEN_B)
        if entry is None:
            self.skipTest("the 7B is not in the local weight cache")
        arch = registry.Arch(**entry.arch)
        self.assertGreater(arch.resident_bf16_params * 2, 2 * GIB)
        self.assertFalse(arch.tied_embeddings, "the 7B config states tie_word_embeddings false")

    def test_lora_params_match_the_adapter_on_disk(self):
        """r=16 over the seven modules must be the 40,370,176 the shipped adapter contains.

        Corroborated independently: `adapter_model.safetensors` is 161,533,192 bytes, which is
        40,370,176 fp32 parameters plus a 52 KB safetensors header. This asserts the shape of
        the adapter, never its contents -- the weights are output, and the corpus that produced
        them is never read by this suite.
        """
        entry = registry.find(SEVEN_B)
        if entry is None:
            self.skipTest("the 7B is not in the local weight cache")
        arch = registry.Arch(**entry.arch)
        self.assertEqual(arch.lora_params(16, presets.ALL_SEVEN), 40_370_176)
        # Attention-only is genuinely cheaper, not nominally so -- which is what makes Smoke's
        # q,v target list a real speed choice rather than a cosmetic one.
        self.assertLess(arch.lora_params(8, presets.ATTENTION_ONLY),
                        arch.lora_params(8, presets.ALL_SEVEN) // 4)

    def test_logits_dominate_the_activation_term(self):
        """On a 152k-vocabulary model the logit tensor is the largest activation.

        This is why `max_length` moves the projected peak more than layer count does, and it
        is the justification for Long-form being the preset nearest the ceiling. If this ever
        stops being true the presets' sequence-length reasoning needs revisiting.
        """
        entry = registry.find(SEVEN_B)
        if entry is None:
            self.skipTest("the 7B is not in the local weight cache")
        arch = registry.Arch(**entry.arch)
        acts = registry.activation_bytes(arch, seq_len=1024, batch=1, checkpointing=True)
        self.assertGreater(acts["logits"], acts["hidden_states"])
        self.assertGreater(acts["logits"], acts["recompute_peak"])
        self.assertEqual(acts["label"], "projected")

    def test_doubling_sequence_doubles_activations(self):
        entry = registry.find(SEVEN_B)
        if entry is None:
            self.skipTest("the 7B is not in the local weight cache")
        arch = registry.Arch(**entry.arch)
        a1 = registry.activation_bytes(arch, 1024, 1)["total"]
        a2 = registry.activation_bytes(arch, 2048, 1)["total"]
        self.assertAlmostEqual(a2 / a1, 2.0, places=6)


class VerdictTests(unittest.TestCase):
    """`headroom > 0` is the wrong test, and this is where that is enforced."""

    def _arch(self, model_id):
        entry = registry.find(model_id)
        if entry is None or entry.arch is None:
            self.skipTest(f"{model_id} not available on this box")
        return registry.Arch(**entry.arch)

    def test_7b_voice_fits_with_margin(self):
        arch = self._arch(SEVEN_B)
        p = presets.PRESETS["voice"]
        plan = registry.plan_fit(arch, rank=p.rank, target_modules=p.target_modules,
                                 seq_len=p.max_length, batch=1)
        self.assertEqual(plan["verdict"], "fits")
        self.assertEqual(plan["label"], "projected")
        self.assertEqual(plan["ladder"], [], "a fitting configuration offers no OOM ladder")

    def test_14b_is_refused_at_every_preset(self):
        """A 14B is NOT trainable on this card, at any preset. This reverses an earlier
        projection and the reversal is the point.

        The upgrade spec projected the 14B as "feasible at rank <=16, batch 1, sequence <=1024".
        That projection charged two bytes for each resident parameter. peft upcasts them to
        fp32, and the 14B has an untied lm_head, so its embeddings and output head alone are
        1.56B parameters -- 5.80 GiB rather than 2.90 GiB. The weights exceed the budget before
        a single activation exists. Measured on the 7B, applied to the 14B by arithmetic.
        """
        arch = self._arch("Qwen/Qwen2.5-14B-Instruct")
        for pid, p in presets.PRESETS.items():
            with self.subTest(preset=pid):
                plan = registry.plan_fit(arch, rank=p.rank, target_modules=p.target_modules,
                                         seq_len=p.max_length, batch=1)
                self.assertEqual(plan["verdict"], "refused")
                self.assertTrue(plan["ladder"])
                self.assertIn("smaller base model", plan["ladder"][-1])

    def test_a_refusal_shows_its_working(self):
        arch = self._arch("Qwen/Qwen2.5-14B-Instruct")
        p = presets.PRESETS["longform"]
        plan = registry.plan_fit(arch, rank=p.rank, target_modules=p.target_modules,
                                 seq_len=p.max_length, batch=1)
        self.assertEqual(plan["verdict"], "refused")
        self.assertFalse(plan["fits"])
        self.assertTrue(plan["ladder"], "a refusal must name a rung of the OOM ladder")
        self.assertIn("shorten max_length", plan["ladder"][0])
        # The sum has to come back with the refusal, or it is indistinguishable from a bug.
        self.assertEqual(len(plan["terms"]), 6)
        for term in plan["terms"].values():
            self.assertIn(term["label"], ("measured", "vendor", "projected"))
            self.assertTrue(term["basis"])

    def test_a_sub_gibibyte_margin_is_refused_not_called_a_fit(self):
        """`headroom > 0` is the wrong test, and this is the check that says so directly.

        The projection has unmodelled terms -- cuBLAS workspace growth, fragmentation, the
        dataloader, and an activation estimate that is arithmetic rather than a reading. Its own
        error bar is wider than a gibibyte; the one run that exists came in 7% over its content
        projection. So a configuration projected to fit by half a gibibyte is not a fit, it is a
        run whose OOM is inside the noise. Free VRAM is passed explicitly here to put the
        headroom in the band under test rather than relying on whatever this box has spare.
        """
        arch = self._arch(SEVEN_B)
        p = presets.PRESETS["voice"]
        base = registry.plan_fit(arch, rank=p.rank, target_modules=p.target_modules,
                                 seq_len=p.max_length, batch=1)
        peak = base["projected_peak_bytes"]
        for margin, expected in ((int(0.5 * GIB), "refused"),
                                 (int(1.5 * GIB), "tight"),
                                 (int(3.0 * GIB), "fits")):
            with self.subTest(margin_gib=margin / GIB):
                plan = registry.plan_fit(arch, rank=p.rank, target_modules=p.target_modules,
                                         seq_len=p.max_length, batch=1,
                                         free_bytes=peak + margin)
                self.assertEqual(plan["verdict"], expected)

    def test_resident_term_is_fp32_not_bf16(self):
        """The constant that cost 2.03 GiB. peft/utils/other.py:197-202 casts every
        non-quantised parameter to fp32 before training, so the resident term is 4 bytes per
        parameter and not 2. Reverting it makes the projection under-report a real run."""
        self.assertEqual(registry.RESIDENT_BYTES_PER_PARAM, 4)
        arch = self._arch(SEVEN_B)
        plan = registry.plan_fit(arch, rank=8, target_modules=presets.ATTENTION_ONLY,
                                 seq_len=512, batch=1)
        self.assertGreater(plan["terms"]["weights_resident_fp32"]["bytes"], 4 * GIB)
        self.assertIn("peft/utils/other.py", plan["terms"]["weights_resident_fp32"]["basis"])

    def test_the_projection_is_conservative_against_the_one_measurement(self):
        """The only run that exists reserved 9.46 GiB. The projected peak for that exact cell
        must sit ABOVE it -- under-projecting is what OOMs at step 0, and over-projecting only
        refuses a run that might have fit."""
        arch = self._arch(SEVEN_B)
        p = presets.PRESETS["smoke"]
        plan = registry.plan_fit(arch, rank=p.rank, target_modules=p.target_modules,
                                 seq_len=p.max_length, batch=1)
        self.assertGreater(plan["projected_peak_bytes"],
                           registry.ACCURACY["measured_reserved_bytes"])

    def test_accuracy_is_published_with_the_projection(self):
        """Publishing a projection without publishing how far off it was the one time it could
        be checked is the same class of dishonesty as an unlabelled figure."""
        arch = self._arch(SEVEN_B)
        plan = registry.plan_fit(arch, rank=16, target_modules=presets.ALL_SEVEN,
                                 seq_len=1024, batch=1)
        acc = plan["accuracy"]
        self.assertEqual(acc["label"], "measured")
        self.assertEqual(acc["runs_measured"], 1)
        self.assertIn("under", acc["content_term_error"])

    def test_budget_is_practical_not_nameplate(self):
        """Budgeting against 15.92 GiB is how a run OOMs at step 0."""
        self.assertLess(registry.PRACTICAL_BUDGET_BYTES, 15 * GIB)
        arch = self._arch(SEVEN_B)
        plan = registry.plan_fit(arch, rank=16, target_modules=presets.ALL_SEVEN,
                                 seq_len=1024, batch=1)
        self.assertEqual(plan["budget_label"], "projected")
        plan_measured = registry.plan_fit(arch, rank=16, target_modules=presets.ALL_SEVEN,
                                          seq_len=1024, batch=1, free_bytes=13 * GIB)
        self.assertEqual(plan_measured["budget_label"], "measured")


class RegistryTests(unittest.TestCase):
    """The model picker. Real files, real sizes, real quantisations."""

    def test_gguf_quantisation_is_read_from_the_file(self):
        """The quantisation label must come from the tensor table, not from the filename.

        A file named `...Q4_K_M.gguf` that was secretly Q8_0 would be caught by this, which is
        the difference between a measured figure and an assumed one.
        """
        ggufs = [e for e in registry.catalogue() if e.kind == "gguf" and e.present]
        if not ggufs:
            self.skipTest("no GGUF weights on this box")
        for e in ggufs:
            self.assertEqual(e.quant_label, "measured")
            self.assertTrue(e.quantisation)
            self.assertTrue(e.tensor_types, "the per-tensor histogram is the evidence")
            self.assertGreater(e.bytes_on_disk, 0)

    def test_gguf_is_offered_but_rejected_with_a_reason(self):
        for e in registry.catalogue():
            if e.kind == "gguf":
                self.assertFalse(e.trainable)
                self.assertIn("training format", e.reason)

    def test_tied_embeddings_detected_from_the_tensor_table(self):
        """The 0.5B is tied (no output.weight); the 14B is not. Worth ~0.9 GiB on the 14B."""
        small = registry.find("symon-1.0-draft-0.5b-q4_k_m")
        big = registry.find("symon-1.0-14b-q4_k_m")
        if not small or not big:
            self.skipTest("the 0.5B/14B GGUFs are not on this box")
        self.assertTrue(registry.Arch(**small.arch).tied_embeddings)
        self.assertFalse(registry.Arch(**big.arch).tied_embeddings)

    def test_hf_size_follows_symlinks(self):
        """The HF cache snapshots are symlinks into blobs/; reporting the link size would
        report ~60 bytes as the model size."""
        entry = registry.find(SEVEN_B)
        if entry is None or not entry.present:
            self.skipTest("the 7B is not in the local weight cache")
        self.assertGreater(entry.bytes_on_disk, 10 * GIB)

    def test_fetchable_rows_state_their_cost_and_are_not_trainable(self):
        for e in registry.catalogue():
            if not e.present and e.kind == "hf":
                self.assertFalse(e.trainable)
                self.assertGreater(e.fetch_bytes, 0)
                self.assertIn("not implemented", e.reason)

    def test_catalogue_never_touches_the_training_directory(self):
        """The picker enumerates weights. It must never enumerate the corpus."""
        for e in registry.catalogue():
            self.assertNotIn("corpus", e.path)
            self.assertFalse(e.path.startswith("training/"))

    def test_find_resolves_the_short_form(self):
        if registry.find(SEVEN_B) is None:
            self.skipTest("the 7B is not in the local weight cache")
        self.assertIsNotNone(registry.find("Qwen2.5-7B-Instruct"))
        self.assertIsNone(registry.find("no-such-model-anywhere"))


class PresetTests(unittest.TestCase):
    """The predetermined tuning methods, and the honesty rules they are held to."""

    def test_every_preset_has_a_rationale_for_its_choices(self):
        for pid, p in presets.PRESETS.items():
            with self.subTest(preset=pid):
                self.assertTrue(p.when, "a preset must say when it is the right one")
                self.assertTrue(p.rationale, "a value with no defensible source is not a preset")
                for key, why in p.rationale.items():
                    self.assertIn("provenance:", why,
                                  f"{pid}.{key} states no provenance")

    def test_alpha_is_twice_rank_everywhere(self):
        """Holding the ratio fixed is what makes rank the single knob it appears to be."""
        for pid, p in presets.PRESETS.items():
            with self.subTest(preset=pid):
                self.assertEqual(p.lora_alpha, p.rank * 2)

    def test_no_preset_claims_a_measured_quality_figure(self):
        """Nothing about training quality or throughput has been measured on this box.

        One adapter exists, from an unlogged run with no validation split. A preset carrying a
        'measured' quality claim would be the exact dishonesty CLAUDE.md names, so the only
        `measured` provenance permitted in this module is on `warmup`, where the measurement is
        a fact about the installed library rather than about training.
        """
        measured = [k for k, v in presets.SHARED.items() if v["provenance"] == "measured"]
        self.assertEqual(measured, ["warmup"])
        for p in presets.PRESETS.values():
            for why in p.rationale.values():
                self.assertNotIn("provenance: measured", why)

    def test_warmup_is_never_expressed_as_a_ratio(self):
        """`warmup_ratio` is absent from transformers 5.15.0 and trl 1.10.0 on this box; code
        copied from older guides raises TypeError here."""
        self.assertIn("never warmup_ratio", presets.SHARED["warmup"]["value"])
        # Read the AST, not the text. The comment on the line that sets `warmup_steps`
        # explains why `warmup_ratio` is not used, and a substring search would trip over its
        # own explanation -- which is how a source-text assertion quietly becomes untestable.
        keys = _dict_keys_and_kwargs(pathlib.Path(__file__).parent / "runner.py")
        self.assertIn("warmup_steps", keys)
        self.assertNotIn("warmup_ratio", keys)
        self.assertNotIn("group_by_length", keys, "also absent from transformers 5.15.0")

    def test_batch_is_one_and_checkpointing_is_on(self):
        """Both are forced by one 16 GiB card, and both are what the OOM ladder has already
        spent -- which is why `plan_fit`'s ladder never offers them as rungs."""
        self.assertEqual(presets.SHARED["per_device_train_batch_size"]["value"], 1)
        self.assertIs(presets.SHARED["gradient_checkpointing"]["value"], True)
        arch = registry.Arch(**registry.find(SEVEN_B).arch) if registry.find(SEVEN_B) else None
        if arch is None:
            self.skipTest("the 7B is not in the local weight cache")
        plan = registry.plan_fit(arch, rank=32, target_modules=presets.ALL_SEVEN,
                                 seq_len=8192, batch=1)
        self.assertEqual(plan["verdict"], "refused")
        joined = " ".join(plan["ladder"])
        self.assertNotIn("batch", joined.split("gradient")[0].replace("effective batch", ""))

    def test_every_likelihood_preset_holds_out_a_validation_split(self):
        """The repo manual: hold out 5-10% BEFORE looking at training loss. The shipped trainer
        does not, which is why no loss figure from it means anything.

        **Scoped to the methods that HAVE a held-out loss**, which is a real distinction and not
        a loosened assertion. Supervised and preference training both minimise a loss over text
        they were given, so a held-out split of that text measures generalisation. GRPO does not:
        its objective is a reward computed on completions the model draws as it goes, so there is
        no held-out loss to compute and holding back a tenth of the prompts would spend training
        signal to produce an eval the method does not define.

        The reinforcement presets are asserted to be exactly 0.0 rather than merely exempted, so
        a value drifting in there is still a failure.
        """
        for pid, p in presets.PRESETS.items():
            with self.subTest(preset=pid):
                if p.method == "reinforcement":
                    self.assertEqual(p.val_split, 0.0,
                                     "GRPO defines no held-out loss; a split here spends "
                                     "training signal on an eval that does not exist")
                    self.assertIn("val_split", p.rationale,
                                  "a preset departing from the manual's rule must say why")
                else:
                    self.assertGreaterEqual(p.val_split, 0.05)

    def test_smoke_is_capped_in_steps(self):
        """A capped step count is what makes a smoke test a smoke test rather than a short run."""
        self.assertGreater(presets.PRESETS["smoke"].max_steps, 0)
        self.assertEqual(presets.PRESETS["smoke"].target_modules, presets.ATTENTION_ONLY)

    def test_preference_and_reinforcement_are_built_not_deferred(self):
        """This assertion is the INVERSE of the one it replaces, and deliberately so.

        The old test asserted that preference tuning was named in `NOT_IN_V1` and therefore
        stated rather than built. That was correct when the only objection to it -- a reference
        model resident beside the policy -- was believed to cost a second copy of the weights. It
        does not: under peft the reference is this model with the adapter disabled. Both methods
        are now built, so the claim that they are absent must be gone from the code as well as
        from the docs, or `presets.NOT_IN_V1` becomes a stale state document contradicting the
        module that carries it.

        What is still absent is asserted to be absent for a stated reason.
        """
        self.assertNotIn("preference_tuning", presets.NOT_IN_V1,
                         "preference tuning is built; claiming otherwise is a stale claim")
        methods = {p.method for p in presets.PRESETS.values()}
        self.assertEqual(methods, {"sft", "preference", "reinforcement"})
        # Exactly one method is reinforcement learning in the ordinary sense, and DPO is not it.
        self.assertTrue(presets.METHODS["reinforcement"]["is_rl"])
        self.assertFalse(presets.METHODS["preference"]["is_rl"],
                         "DPO has no sampling loop and no reward function; calling it RL would "
                         "be an overstatement")
        self.assertFalse(presets.METHODS["sft"]["is_rl"])
        # And every remaining omission still carries its reason.
        for key in ("reward_model_training", "kto_and_online_dpo", "vllm_colocated_rollouts",
                    "llama_cpp_rollouts", "full_fine_tuning", "multi_gpu"):
            with self.subTest(omission=key):
                self.assertIn(key, presets.NOT_IN_V1)
                self.assertGreater(len(presets.NOT_IN_V1[key]), 80,
                                   "an omission without a reason is a shrug")

    def test_every_preset_declares_a_method_that_exists(self):
        """A preset naming a method that is not in `METHODS` would KeyError at `dataset_schema`,
        which is a property every caller touches -- including the rack unit."""
        for pid, p in presets.PRESETS.items():
            with self.subTest(preset=pid):
                self.assertIn(p.method, presets.METHODS)
                self.assertEqual(p.dataset_schema,
                                 presets.METHODS[p.method]["dataset_schema"])
                self.assertIn(p.dataset_schema, dataset_guard.SCHEMAS)

    def test_reinforcement_presets_name_reward_functions_that_exist(self):
        """GRPO cannot be constructed without a reward function, so a preset naming one that has
        been renamed or removed is a run that dies at `check_rewards` -- and would have taken the
        card to get there."""
        for pid, p in presets.PRESETS.items():
            if p.method != "reinforcement":
                continue
            with self.subTest(preset=pid):
                names = p.method_config.get("rewards", ())
                self.assertTrue(names, "a reinforcement preset with no reward function has "
                                       "nothing to optimise")
                for name in names:
                    self.assertIn(name, rewards.REWARDS)
                    # No preset may default to a reward that needs a dataset column, because a
                    # preset is chosen before a dataset is and it would refuse on most files.
                    self.assertFalse(rewards.REWARDS[name].requires,
                                     f"{name} needs a dataset column and cannot be a default")

    def test_generation_batch_is_divisible_by_num_generations(self):
        """trl requires the generation batch to divide evenly into groups, and violating it is a
        ValueError at construction -- after the governor has handed over the card.

        per-device batch is 1 on this card, so the generation batch is the accumulation count.
        """
        for pid, p in presets.PRESETS.items():
            if p.method != "reinforcement":
                continue
            with self.subTest(preset=pid):
                g = p.method_config["num_generations"]
                self.assertGreaterEqual(g, 2, "a group of one has no baseline to be relative to")
                self.assertEqual(p.gradient_accumulation_steps % g, 0,
                                 f"{pid}: generation batch {p.gradient_accumulation_steps} is not "
                                 f"divisible by num_generations {g}")

    def test_fit_table_costs_every_preset(self):
        if registry.find(SEVEN_B) is None:
            self.skipTest("the 7B is not in the local weight cache")
        rows = presets.fit_table(SEVEN_B)
        self.assertEqual(len(rows), len(presets.PRESETS))
        by_id = {r["preset"]: r["plan"] for r in rows}
        for row in rows:
            self.assertEqual(row["plan"]["label"], "projected")
            # Every preset must at least be offerable on the one model this box can train.
            self.assertNotEqual(row["plan"]["verdict"], "refused", row["preset"])
        # Long-form is the preset nearest the ceiling, and it is honest about being tight
        # rather than presenting a 1.1 GiB margin as comfort.
        self.assertEqual(by_id["longform"]["verdict"], "tight")
        self.assertEqual(by_id["voice"]["verdict"], "fits")
        self.assertLess(by_id["smoke"]["projected_peak_bytes"],
                        by_id["longform"]["projected_peak_bytes"])


class TradeSecretTests(unittest.TestCase):
    """The guard that matters most. `training/corpus.jsonl` is protected only by not being
    public, and this surface is the likeliest accident."""

    def test_corpus_is_refused_from_any_working_directory(self):
        """A guard whose answer depends on where the process was started is not a guard.

        This caught a live bug: `is_denied` resolved a relative path against the process's cwd
        while `admit()` resolved the same string against the repo root, so the refusal held
        from the repo root and failed from anywhere else. It now judges both interpretations.
        """
        import os as _os
        cwd = _os.getcwd()
        try:
            for where in (registry.ROOT, registry.ROOT / "backend", pathlib.Path("/tmp")):
                _os.chdir(where)
                with self.subTest(cwd=str(where)):
                    self.assertTrue(dataset_guard.is_denied(
                        pathlib.Path("training/corpus.jsonl")))
                    with self.assertRaises(dataset_guard.Refused) as ctx:
                        dataset_guard.admit("training/corpus.jsonl")
                    self.assertEqual(ctx.exception.code, "protected")
        finally:
            _os.chdir(cwd)

    def test_corpus_is_refused_by_every_spelling(self):
        corpus = registry.ROOT / "training" / "corpus.jsonl"
        spellings = [
            str(corpus),
            "training/corpus.jsonl",
            "./training/corpus.jsonl",
            "training/../training/corpus.jsonl",
            "training/adapter/../corpus.jsonl",
            str(registry.ROOT / "training" / "." / "corpus.jsonl"),
        ]
        for s in spellings:
            with self.subTest(spelling=s):
                self.assertTrue(dataset_guard.is_denied(pathlib.Path(s)))
                with self.assertRaises(dataset_guard.Refused) as ctx:
                    dataset_guard.admit(s)
                self.assertEqual(ctx.exception.code, "protected")

    def test_a_symlink_to_the_corpus_is_refused(self):
        corpus = registry.ROOT / "training" / "corpus.jsonl"
        if not corpus.is_file():
            self.skipTest("no corpus on this box")
        with tempfile.TemporaryDirectory() as td:
            link = pathlib.Path(td) / "innocent.jsonl"
            link.symlink_to(corpus)
            self.assertTrue(dataset_guard.is_denied(link))
            with self.assertRaises(dataset_guard.Refused) as ctx:
                dataset_guard.admit(str(link))
            self.assertEqual(ctx.exception.code, "protected")

    def test_build_dataset_and_the_adapter_tree_are_refused(self):
        self.assertTrue(dataset_guard.is_denied(registry.ROOT / "training" / "build_dataset.py"))
        self.assertTrue(dataset_guard.is_denied(
            registry.ROOT / "training" / "adapter" / "adapter_model.safetensors"))

    def test_the_refusal_message_describes_nothing(self):
        """The refusal is the feature. A helpful explanation of what is inside defeats it."""
        with self.assertRaises(dataset_guard.Refused) as ctx:
            dataset_guard.admit("training/corpus.jsonl")
        msg = ctx.exception.message.lower()
        for leak in ("persona", "refusal", "pricing", "example", "voice", "327"):
            self.assertNotIn(leak, msg)

    def test_deny_is_checked_before_existence(self):
        """Checking existence first would let a caller probe for the corpus by the difference
        between 'denied' and 'not found'."""
        with self.assertRaises(dataset_guard.Refused) as ctx:
            dataset_guard.admit("training/corpus.jsonl")
        self.assertEqual(ctx.exception.code, "protected")
        with self.assertRaises(dataset_guard.Refused) as ctx2:
            dataset_guard.admit("training/no-such-file-at-all.jsonl")
        self.assertEqual(ctx2.exception.code, "not_found")

    def test_runner_carries_its_own_copy_of_the_denylist(self):
        """The runner runs in a different interpreter under a different cwd. A guard that
        depends on an import path is a guard a refactor can lose, so it duplicates the list --
        and the two copies must agree."""
        source = (pathlib.Path(__file__).parent / "runner.py").read_text()
        self.assertIn('"corpus.jsonl"', source)
        self.assertIn('"build_dataset.py"', source)
        self.assertIn("ProtectedArtefact", source)

    def test_no_module_globs_the_training_directory(self):
        """A dataset picker that scans the sibling directory publishes the recipe. This asserts
        that no module in the serving path does, by reading the source."""
        here = pathlib.Path(__file__).parent
        for name in ("registry.py", "presets.py", "jobs.py", "routes.py", "dataset_guard.py"):
            src = (here / name).read_text()
            for forbidden in ('glob("training', "glob('training", '"training/*.jsonl"',
                              "iterdir()  # training"):
                self.assertNotIn(forbidden, src, f"{name} enumerates training/")

    def test_staging_directory_is_outside_the_published_webroot(self):
        """`deploy.sh` publishes `site/` wholesale. A dataset there would be public."""
        self.assertNotIn("site", dataset_guard.STAGE.parts)
        self.assertIn("run", dataset_guard.STAGE.parts)

    def test_malformed_rows_report_a_line_number_and_never_the_line(self):
        sentinel = "SYMONEURAL-SECRET-TRAINING-EXAMPLE"
        with tempfile.TemporaryDirectory() as td:
            p = pathlib.Path(td) / "bad.jsonl"
            p.write_text(
                json.dumps({"messages": [{"role": "user", "content": "hi"},
                                         {"role": "assistant", "content": "hello"}]}) + "\n"
                + '{"messages": "' + sentinel + '"}\n')
            with self.assertRaises(dataset_guard.Refused) as ctx:
                dataset_guard.admit(str(p))
            self.assertEqual(ctx.exception.code, "malformed")
            self.assertIn("line 2", ctx.exception.message)
            self.assertNotIn(sentinel, ctx.exception.message)

    def test_a_good_dataset_reports_shape_only(self):
        # Sentinels are long and distinctive on purpose. Two-character markers ("q0"/"a0")
        # collided with the random tempfile name in `path`, which to_dict() reports by
        # design -- measured at one failure per ~100 runs. `tempfile` draws 8 characters
        # from a 37-character alphabet, so over 400,000 trials "q0" appeared in 1 name in
        # 208 and "a0" in 1 in 192. A 1% flake in a project that anchors every claim to a
        # suite count at a SHA means a green reading could have been luck, so the fix is a
        # needle that cannot collide -- not a silenced assertion.
        USER = "SENTINEL-USER-CONTENT-DO-NOT-REPORT"
        ASSIST = "SENTINEL-ASSISTANT-CONTENT-DO-NOT-REPORT"
        with tempfile.TemporaryDirectory() as td:
            p = pathlib.Path(td) / "ok.jsonl"
            rows = [{"messages": [{"role": "user", "content": f"{USER}-{i}"},
                                  {"role": "assistant", "content": f"{ASSIST}-{i}"}]}
                    for i in range(5)]
            p.write_text("\n".join(json.dumps(r) for r in rows))
            info = dataset_guard.admit(str(p))
            self.assertEqual(info.rows, 5)
            d = info.to_dict()
            # `path` is a filesystem path and is reported deliberately. The guarantee under
            # test is that no ROW CONTENT is reported, so assert against everything else.
            self.assertEqual(d["path"], str(p))
            shape = json.dumps({k: v for k, v in d.items() if k != "path"})
            self.assertNotIn(USER, shape)
            self.assertNotIn(ASSIST, shape)

    def test_there_is_no_default_dataset(self):
        with self.assertRaises(dataset_guard.Refused) as ctx:
            dataset_guard.admit("")
        self.assertEqual(ctx.exception.code, "no_dataset")
        self.assertIn("does not fall back", ctx.exception.message)


class LogAllowlistTests(unittest.TestCase):
    """The other half of the trade-secret guard: a training process's stdout is not trusted."""

    def test_log_parser_drops_unknown_lines(self):
        """A traceback carrying a training example must not survive into an API response.

        This is an allowlist, not a denylist: the sentinel is dropped because the line does not
        match a known shape, not because anything recognised it as secret.
        """
        sentinel = "SYMONEURAL-SECRET-TRAINING-EXAMPLE"
        log = "\n".join([
            "Loading checkpoint shards: 100%|##########| 4/4",
            f'  File "train.py", line 9, in encode: row = {{"messages": "{sentinel}"}}',
            f"ValueError: could not tokenise {sentinel}",
            "REINFORCE event=step step=3 total_steps=8 loss=1.234 elapsed_s=12.5",
            f"REINFORCE event=step note={sentinel}",
        ])
        events = jobs.parse_log(log)
        self.assertEqual(len(events), 2)
        self.assertNotIn(sentinel, json.dumps(events))
        self.assertEqual(events[0]["step"], 3)
        self.assertEqual(events[0]["loss"], 1.234)
        # The last line is well-formed but carries a key outside the allowlist; the key is
        # dropped while the event survives.
        self.assertNotIn("note", events[1])

    def test_out_of_vocabulary_enum_values_are_dropped(self):
        self.assertEqual(jobs.parse_log("REINFORCE event=exfiltrate step=1"), [])
        self.assertEqual(jobs.parse_log("REINFORCE event=error kind=X stage=elsewhere"), [])
        ok = jobs.parse_log("REINFORCE event=error kind=OutOfMemoryError stage=train")
        self.assertEqual(ok[0]["kind"], "OutOfMemoryError")

    def test_overlong_and_spaced_values_are_dropped(self):
        self.assertEqual(jobs.parse_log("REINFORCE event=step kind=" + "x" * 65), [])
        self.assertEqual(jobs.parse_log('REINFORCE event=step kind=a b c'), [])
        self.assertEqual(jobs.parse_log("prefix REINFORCE event=step step=1"), [])

    def test_non_numeric_values_in_numeric_fields_are_rejected(self):
        self.assertEqual(jobs.parse_log("REINFORCE event=step step=NaNsy-text"), [])

    def test_runner_emit_and_parser_agree(self):
        """Both ends of the protocol are constrained, so they cannot drift silently."""
        src = (pathlib.Path(__file__).parent / "runner.py").read_text()
        self.assertIn('print("REINFORCE "', src)
        # The runner must not print an exception *message* anywhere on stdout.
        self.assertNotIn("print(exc", src)
        self.assertIn("traceback.print_exc(file=sys.stderr)", src)


class LaunchPathTests(unittest.TestCase):
    """The GPU rules, asserted on the command that would actually be run."""

    def test_launch_uses_the_with_form(self):
        script = jobs.build_script(["/x/python", "runner.py", "--preset", "smoke"],
                                   pathlib.Path("/tmp/j.exit"))
        self.assertIn("gpu-governor.sh with train --", script)

    def test_launch_never_calls_a_bare_release(self):
        """An unscoped release once destroyed a running fine-tune's lock from the API's
        shutdown hook. The release belongs to the governor's `with` form, and this package
        must not write one at all."""
        script = jobs.build_script(["/x/python"], pathlib.Path("/tmp/j.exit"))
        self.assertNotIn("release", script)
        self.assertNotIn("acquire", script)
        here = pathlib.Path(__file__).parent
        for name in ("jobs.py", "routes.py", "runner.py", "registry.py"):
            src = (here / name).read_text()
            for call in ("governor.sh release", "governor.sh acquire",
                         '"release"', "'release'", '"acquire"', "'acquire'"):
                self.assertNotIn(call, src, f"{name} talks to the governor directly")

    def test_dataset_paths_are_shell_quoted(self):
        script = jobs.build_script(["/x/python", "--dataset", "/tmp/a b; rm -rf /"],
                                   pathlib.Path("/tmp/j.exit"))
        self.assertNotIn("; rm -rf /'", script.replace("'/tmp/a b; rm -rf /'", ""))
        self.assertIn("'/tmp/a b; rm -rf /'", script)

    def test_exit_code_is_written_after_the_governor_returns(self):
        script = jobs.build_script(["/x/python"], pathlib.Path("/tmp/j.exit"))
        self.assertTrue(script.index("gpu-governor.sh") < script.index("printf"))
        self.assertIn("$?", script)

    def test_no_module_here_shadows_a_training_stack_package(self):
        """A sibling module named after a third-party package breaks the runner after acquire.

        This bit: `datasets.py` in this directory shadowed Hugging Face's `datasets` for the
        subprocess, because Python puts a script's own directory at sys.path[0]. The run failed
        at import -- 74 seconds after it had taken the GPU. Two fixes, and this asserts both:
        the module was renamed, and `runner.py` now removes its own directory from sys.path.
        """
        here = pathlib.Path(__file__).parent
        reserved = {"datasets", "torch", "transformers", "peft", "accelerate", "trl",
                    "bitsandbytes", "numpy", "tokenizers", "safetensors", "json", "os", "re"}
        for py in here.glob("*.py"):
            self.assertNotIn(py.stem, reserved,
                             f"{py.name} shadows a package the runner imports")
        self.assertIn("sys.path[:] = [p for p in sys.path", (here / "runner.py").read_text())

    def test_the_runner_is_invoked_with_the_training_interpreter(self):
        """The serving API runs on the system interpreter and has no torch. The training venv
        is cu128 because Blackwell sm_120 needs it."""
        self.assertEqual(jobs.TRAIN_PYTHON,
                         registry.ROOT / "training" / ".venv" / "bin" / "python")
        self.assertNotEqual(str(jobs.TRAIN_PYTHON), sys.executable)

    def test_serving_modules_import_no_training_stack(self):
        """Everything importable by api.py must be stdlib-only.

        Walks the AST rather than grepping the text: these modules discuss torch, transformers
        and peft at length in their docstrings, and a substring search would fail on its own
        documentation. The AST answers the question actually being asked -- what does this
        module import.
        """
        here = pathlib.Path(__file__).parent
        heavy = {"torch", "transformers", "peft", "numpy", "bitsandbytes", "trl", "datasets_hf",
                 "accelerate", "cupy", "cuda"}
        for name in ("registry.py", "presets.py", "dataset_guard.py", "jobs.py", "__init__.py"):
            for mod in _imported_modules(here / name):
                self.assertNotIn(mod.split(".")[0], heavy,
                                 f"{name} imports the training stack ({mod})")

    def test_routes_import_only_fastapi_and_pydantic(self):
        """Both are already OS packages on the system interpreter; the serving path has no
        virtualenv and nothing may be pip-installed into it."""
        mods = {m.split(".")[0] for m in
                _imported_modules(pathlib.Path(__file__).parent / "routes.py")}
        self.assertTrue(mods <= {"os", "hmac", "fastapi", "pydantic", "__future__", ""},
                        f"unexpected imports in routes.py: {mods}")


class RackUnitTests(unittest.TestCase):
    """`Unit.state` is a four-value Literal. An out-of-vocab string raises pydantic at
    /api/status and takes every other unit's rack row down with it."""

    VALID = {"ready", "busy", "queued", "offline"}

    def test_status_keys_match_the_unit_model(self):
        st = jobs.status()
        self.assertEqual(set(st), {"id", "label", "slot", "state", "bus", "href", "spec", "detail"})
        self.assertIn(st["state"], self.VALID)
        self.assertIn(st["bus"], {"gpu", "cpu", "asic", "net"})
        self.assertEqual(st["id"], "train")
        self.assertEqual(st["label"], "SyMoNeuRaL Reinforce")

    def test_status_is_offline_when_the_surface_is_off(self):
        old = dict(os.environ)
        try:
            os.environ.pop("SYMONEURAL_REINFORCE_ENABLED", None)
            self.assertEqual(jobs.status()["state"], "offline")
            self.assertIn("SYMONEURAL_REINFORCE_ENABLED", jobs.status()["detail"])
        finally:
            os.environ.clear()
            os.environ.update(old)

    def test_status_reports_a_real_model_count_when_enabled(self):
        old = dict(os.environ)
        try:
            os.environ["SYMONEURAL_REINFORCE_ENABLED"] = "1"
            os.environ["SYMONEURAL_REINFORCE_TOKEN"] = "test-token"
            st = jobs.status()
            self.assertIn(st["state"], self.VALID)
            if st["state"] == "ready":
                n = sum(1 for e in registry.catalogue() if e.trainable)
                self.assertIn(f"{n} base model(s) loadable", st["detail"])
                self.assertIn(f"{len(presets.PRESETS)} tuning presets", st["detail"])
        finally:
            os.environ.clear()
            os.environ.update(old)

    def test_no_decorative_indicator_when_there_is_no_run(self):
        snap = jobs.snapshot()
        if snap["state"] == "none":
            self.assertEqual(snap["detail"], "no run has been started from this surface")
            self.assertEqual(snap["events"], [])
            self.assertIsNone(snap["job"])

    def test_branding_carries_no_vendor_product_names(self):
        """The surface is SyMoNeuRaL Reinforce. Technique descriptions may say '4-bit low-rank
        adaptation', which describes the method without using anybody's product name."""
        st = jobs.status()
        blob = json.dumps(st).lower()
        for banned in ("qlora", "qwen", "mit ai training"):
            self.assertNotIn(banned, blob)
        self.assertIn("4-bit low-rank adaptation", st["spec"])

    def test_eta_is_labelled_projected(self):
        snap = jobs.snapshot()
        if snap.get("eta_s") is not None:
            self.assertEqual(snap["eta_label"], "projected")


class PreflightTests(unittest.TestCase):

    def test_unknown_preset_and_model_are_refused_by_name(self):
        r = jobs.preflight(SEVEN_B, "no-such-preset")
        self.assertFalse(r["ok"])
        self.assertEqual(r["reason"], "unknown_preset")
        r2 = jobs.preflight("no-such-model", "voice")
        self.assertFalse(r2["ok"])
        self.assertEqual(r2["reason"], "unknown_model")

    def test_a_gguf_is_refused_with_the_reason_not_a_shrug(self):
        gguf = next((e for e in registry.catalogue() if e.kind == "gguf"), None)
        if gguf is None:
            self.skipTest("no GGUF weights on this box")
        r = jobs.preflight(gguf.id, "voice")
        self.assertFalse(r["ok"])
        self.assertEqual(r["reason"], "model_not_trainable")
        self.assertIn("training format", r["message"])

    def test_preflight_refuses_the_corpus_as_a_dataset(self):
        """The protection, reached THROUGH preflight rather than by calling the guard.

        This one is contingent and the contingency is stated rather than left to fail
        confusingly. `preflight()` checks preset, then model, then dataset, so on a box with no
        `backend/models` this returns `unknown_model` and the assertion below reads
        `'unknown_model' != 'dataset_protected'` -- which looks like the corpus guard is broken
        and is not. That exact confusion cost another session time during the merge, in a temp
        worktree created by `git worktree add`, which does not get the symlink.

        The refusal is real either way: preflight returns before the dataset is opened on both
        paths, so the corpus is never read. And the guard itself does NOT depend on any of this
        -- `test_corpus_is_refused_from_any_working_directory`, `..._by_every_spelling` and
        `test_a_symlink_to_the_corpus_is_refused` call `dataset_guard.admit()` with no model
        involved, so the trade-secret invariant keeps its unconditional coverage on any box.
        What is tested here is only that preflight is wired to that guard.
        """
        _seven = registry.find(SEVEN_B)
        # The guard has to match this test's own reasoning above: preflight refuses on the
        # MODEL before it reaches the dataset, so the wiring is only testable when the 7B is
        # a usable training target. `is None` alone was too narrow -- once `fetchable()`
        # started offering the 7B as a row (present=False, trainable=False) the model check
        # began refusing with `model_not_trainable`, which is preflight working correctly and
        # is still not a state this test can exercise.
        if _seven is None or not _seven.trainable:
            self.skipTest(f"{SEVEN_B} is not a usable training target on this box -- "
                          "preflight refuses on the model before it reaches the dataset, so "
                          "this cannot test the wiring. The guard's own tests still run.")
        r = jobs.preflight(SEVEN_B, "smoke", "training/corpus.jsonl")
        self.assertFalse(r["ok"])
        self.assertEqual(r["reason"], "dataset_protected")


class MetricProtocolTests(unittest.TestCase):
    """The two ends of the log protocol must agree, key by key.

    This is the class the RL work most needed, because every failure it guards against is
    SILENT. `parse_log()` drops an unrecognised key and discards a whole line whose `stage` is
    unrecognised; neither raises, neither logs, and both produce a panel that looks healthy while
    reporting nothing. A reward curve that is blank because of a spelling mismatch is worse than
    an error, because an error would get fixed.
    """

    def _runner_source(self):
        return next(_p for _p in pathlib.Path(__file__).resolve().parents if (_p / "backend" / "server.py").is_file()) / "runner.py"

    def _runner_module(self):
        """Load `runner.py` without importing torch.

        `runner.py` imports torch, transformers and peft -- but all of them INSIDE `main()`, and
        that is exactly what makes this test possible: the module level is stdlib only, so it can
        be exec'd on the serving interpreter to read its constants. If somebody moves an import
        to the top of that file this test fails loudly, which is the correct outcome: the module
        level being importable without the training venv is a property worth keeping.
        """
        import importlib.util
        spec = importlib.util.spec_from_file_location("_runner_probe", self._runner_source())
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_every_metric_the_runner_emits_is_allowlisted(self):
        """A metric absent from `jobs._ALLOWED_KEYS` is dropped, giving a live RL run a blank
        curve. Asserted per key rather than as a set comparison, so the failure names the key."""
        runner = self._runner_module()
        for trl_name, emitted in runner._METRIC_KEYS.items():
            with self.subTest(metric=trl_name):
                self.assertIn(emitted, jobs._ALLOWED_KEYS,
                              f"runner emits {emitted!r} (from trl's {trl_name!r}) and the "
                              f"parser would silently drop it")
                self.assertIn(emitted, jobs._NUMERIC_KEYS,
                              f"{emitted!r} is a number and must be parsed as one")

    def test_no_emitted_metric_name_contains_a_slash(self):
        """trl logs `rewards/chosen`; `/` is outside the value character class, so an unmapped
        key would be dropped by `emit()`. The mapping is the runner's job and the narrow
        character class stays -- `/` is also how a filesystem path would arrive."""
        runner = self._runner_module()
        for trl_name, emitted in runner._METRIC_KEYS.items():
            with self.subTest(metric=trl_name):
                self.assertNotIn("/", emitted)
        # And at least one trl name genuinely has one, or this test is guarding nothing.
        self.assertTrue(any("/" in name for name in runner._METRIC_KEYS),
                        "no slashed trl metric is mapped, so this guard is vacuous")

    def test_runner_stages_and_parser_stages_agree(self):
        """The dangerous one. An unrecognised `stage` discards the ENTIRE line, including
        `event=error`, so a stage in one place and not the other turns a failure report into
        nothing at all."""
        runner = self._runner_module()
        self.assertEqual(set(runner.STAGES), jobs._ENUM_VALUES["stage"],
                         "runner.STAGES and jobs._ENUM_VALUES['stage'] have diverged; a run "
                         "failing in the missing stage would report no kind and no stage")

    def test_an_rl_metric_line_survives_the_parser(self):
        """End to end through the real parser, with the real key names."""
        line = ("REINFORCE event=step step=3 total_steps=6 reward=0.42 reward_std=0.11 "
                "kl=0.0031 completion_len=88 clip_ratio=0.02 entropy=1.4 vram_alloc=123 "
                "elapsed_s=12.5")
        events = jobs.parse_log(line)
        self.assertEqual(len(events), 1)
        got = events[0]
        for key, want in (("reward", 0.42), ("reward_std", 0.11), ("kl", 0.0031),
                          ("completion_len", 88), ("clip_ratio", 0.02), ("entropy", 1.4)):
            self.assertEqual(got[key], want, key)

    def test_a_dpo_metric_line_survives_the_parser(self):
        line = ("REINFORCE event=step step=1 total_steps=4 loss=0.69 reward_chosen=-1.2 "
                "reward_rejected=-1.9 reward_accuracy=0.75 reward_margin=0.7")
        got = jobs.parse_log(line)[0]
        self.assertEqual(got["reward_chosen"], -1.2)
        self.assertEqual(got["reward_accuracy"], 0.75)

    def test_an_error_in_a_new_stage_still_reports(self):
        """The failure this whole class exists for: an RL run dying in a stage the supervised
        path does not have must still report its kind and its stage."""
        for stage in ("check_rewards", "load_reference", "rollout"):
            with self.subTest(stage=stage):
                got = jobs.parse_log(f"REINFORCE event=error kind=ValueError stage={stage}")
                self.assertEqual(len(got), 1, f"the {stage} error line was discarded entirely")
                self.assertEqual(got[0]["stage"], stage)
                self.assertEqual(got[0]["kind"], "ValueError")

    def test_runner_module_level_is_stdlib_only(self):
        """Re-asserted for the RL path, and load-bearing for the three tests above: they read
        `runner.STAGES` and `runner._METRIC_KEYS` on the SERVING interpreter, which has no torch.

        `runner.py` does import torch, transformers, peft and trl -- inside `main()`. Move any one
        of them to the top and the protocol tests above stop being able to run at all, which is
        the failure this asserts against."""
        mods = _top_level_imports(self._runner_source())
        for banned in ("torch", "transformers", "peft", "trl", "datasets"):
            self.assertNotIn(banned, mods,
                             f"{banned} is imported at runner.py's module level; the protocol "
                             f"tests read that module without a training venv and would break")
        # It genuinely does import them, lazily. Asserted so this test cannot pass by the imports
        # having simply been deleted.
        self.assertTrue({"torch", "trl"} <= _imported_modules(self._runner_source()))


class RewardTests(unittest.TestCase):
    """The reward functions, and the contract that stops one of them dominating the sum."""

    def test_selfcheck_passes(self):
        """The same check the runner performs before the training loop starts."""
        self.assertEqual(rewards.selfcheck(), [])

    def test_every_function_stays_in_its_published_range(self):
        """The weighted sum has no normalisation step, so a function returning 5.0 where the
        table promises 1.0 silently dominates every other term and the run optimises that one
        function while the panel reports a healthy-looking total."""
        samples = ["", "no", "word " * 500, "It costs $200 per hour.",
                   "746 GB/s, measured on this card.",
                   "Pricing is not published; write to symonsayadmin@symoneural.com."]
        for name, fn in rewards.FUNCTIONS.items():
            spec = rewards.REWARDS[name]
            with self.subTest(reward=name):
                got = fn(completions=samples, prompts=["what does it cost?"] * len(samples),
                         answer=["746"] * len(samples))
                self.assertEqual(len(got), len(samples))
                for value in got:
                    self.assertIsInstance(value, float)
                    self.assertGreaterEqual(value, spec.lo)
                    self.assertLessEqual(value, spec.hi)

    def test_pricing_refusal_rewards_the_documented_behaviour(self):
        """`.claude/CLAUDE.md`: never invent pricing, direct it to the admin address. This is the
        one reward function whose correct answer is written down in the repo."""
        prompts = ["How much does a rack cost?"] * 3
        completions = [
            "It costs $200 per hour.",                                     # invented a figure
            "Pricing is not published here -- write to symonsayadmin@symoneural.com.",
            "The bus moved 746 GB/s.",                                     # ignored the question
        ]
        got = rewards.pricing_refusal(completions=completions, prompts=prompts)
        self.assertEqual(got[0], -1.0, "inventing a price must be punished, not merely unrewarded")
        self.assertEqual(got[1], 1.0)
        self.assertLess(got[2], 0.0)

    def test_pricing_refusal_is_neutral_when_the_prompt_is_not_about_price(self):
        """A model that earns points for mentioning the pricing contact in unrelated answers has
        learned the wrong rule."""
        got = rewards.pricing_refusal(
            completions=["Write to symonsayadmin@symoneural.com."],
            prompts=["What is the memory bandwidth?"])
        self.assertEqual(got, [0.0])

    def test_completions_may_arrive_as_conversations(self):
        """A conversational dataset yields message lists. A function that assumes strings would
        score `str(dict)` -- rewarding Python's repr -- while appearing to work."""
        convo = [[{"role": "assistant", "content": "Pricing is not published here."}]]
        plain = ["Pricing is not published here."]
        self.assertEqual(rewards.length_band(completions=convo),
                         rewards.length_band(completions=plain))

    def test_house_style_punishes_boilerplate_and_repetition(self):
        got = rewards.house_style(completions=[
            "As an AI language model, I cannot help with that.",
            "the same phrase again the same phrase again the same phrase again",
            "A clear, ordinary answer of reasonable length that says something specific.",
        ])
        self.assertLess(got[0], 0.0)
        self.assertLess(got[1], 0.0)
        self.assertEqual(got[2], 1.0)

    def test_resolve_refuses_a_reward_needing_an_absent_column(self):
        """`answer_match` needs an `answer` column. Refused by name rather than dropped: a run
        that quietly trained against fewer functions than were configured would report a reward
        curve meaning something other than what the panel says."""
        plan = rewards.resolve(["house_style", "answer_match"], available_fields=())
        self.assertEqual(plan["names"], ["house_style"])
        self.assertEqual(len(plan["refused"]), 1)
        self.assertEqual(plan["refused"][0]["id"], "answer_match")
        # With the column present it is admitted.
        plan2 = rewards.resolve(["house_style", "answer_match"], available_fields=("answer",))
        self.assertEqual(plan2["names"], ["house_style", "answer_match"])

    def test_resolve_refuses_an_unknown_name_rather_than_ignoring_it(self):
        with self.assertRaises(rewards.RewardError):
            rewards.resolve(["no_such_reward"])

    def test_resolve_refuses_an_empty_selection(self):
        """GRPO cannot run with nothing to optimise, and it must say so before the card is taken."""
        with self.assertRaises(rewards.RewardError):
            rewards.resolve([])

    def test_published_table_never_carries_the_patterns(self):
        """Publishing the exact pattern a policy is scored against publishes the loophole, and
        how a behaviour is detected is method rather than number."""
        for row in rewards.offered():
            with self.subTest(reward=row["id"]):
                self.assertFalse(row["patterns_published"])
                blob = json.dumps(row)
                for leak in ("re.compile", "\\\\b", "symonsayadmin@symoneural.com"):
                    self.assertNotIn(leak, blob, f"{row['id']} leaks its detection rule")

    def test_the_reward_hacking_risk_is_written_down(self):
        """`figure_labelling` can be earned by labelling everything 'measured', which is the exact
        dishonesty the rule exists to prevent. A reward function that can be gamed into the
        opposite of its intent must say so and must not be the heaviest term."""
        doc = rewards.__doc__ or ""
        self.assertIn("reward hacking", doc.lower())
        self.assertLess(rewards.REWARDS["figure_labelling"].weight,
                        rewards.REWARDS["pricing_refusal"].weight)


class DatasetSchemaTests(unittest.TestCase):
    """Three schemas, and the guard's refusals still content-free on every one of them."""

    def _write(self, rows):
        fh = tempfile.NamedTemporaryFile("w", suffix=".jsonl", delete=False, encoding="utf-8")
        for row in rows:
            fh.write(json.dumps(row) + "\n")
        fh.close()
        self.addCleanup(os.unlink, fh.name)
        return fh.name

    def test_preference_file_is_admitted_and_sniffed(self):
        path = self._write([{"prompt": "q", "chosen": "good", "rejected": "bad"}] * 3)
        self.assertEqual(dataset_guard.sniff(path), "preference")
        info = dataset_guard.admit(path, schema="preference")
        self.assertEqual(info.rows, 3)
        self.assertEqual(info.schema, "preference")

    def test_prompt_file_is_admitted_and_reports_its_answer_column(self):
        """The `answer` column is what unlocks `answer_match`, so its presence has to survive to
        the preflight -- as a column NAME, never a value."""
        path = self._write([{"prompt": "q", "answer": "42"}] * 2)
        info = dataset_guard.admit(path, schema="prompt")
        self.assertIn("answer", info.fields)
        self.assertNotIn("42", json.dumps(info.to_dict()))

    def test_a_chat_file_is_refused_against_the_preference_schema(self):
        """The mismatch that would otherwise be discovered inside a collator, twenty minutes in
        and holding the card."""
        path = self._write([{"messages": [{"role": "user", "content": "hi"},
                                          {"role": "assistant", "content": "hello"}]}])
        with self.assertRaises(dataset_guard.Refused) as caught:
            dataset_guard.admit(path, schema="preference")
        self.assertEqual(caught.exception.code, "no_valid_rows")

    def test_sniff_prefers_the_most_specific_schema(self):
        """A preference row also has a valid `prompt` field and would be mislabelled as the
        looser schema if the order were wrong."""
        path = self._write([{"prompt": "q", "chosen": "a", "rejected": "b"}])
        self.assertEqual(dataset_guard.sniff(path), "preference")

    def test_conversational_spellings_are_accepted(self):
        """trl takes both a plain string and a message list; refusing the conversational form
        would refuse what a chat model's own template produces."""
        path = self._write([{"prompt": [{"role": "user", "content": "q"}],
                            "chosen": [{"role": "assistant", "content": "a"}],
                            "rejected": [{"role": "assistant", "content": "b"}]}])
        self.assertEqual(dataset_guard.admit(path, schema="preference").rows, 1)

    def test_a_malformed_row_is_reported_by_number_never_by_content(self):
        secret = "SENSITIVE-CORPUS-STRING"
        path = self._write([{"prompt": "q", "chosen": "a", "rejected": "b"},
                            {"prompt": secret}])          # missing chosen/rejected
        with self.assertRaises(dataset_guard.Refused) as caught:
            dataset_guard.admit(path, schema="preference")
        self.assertNotIn(secret, caught.exception.message)
        self.assertIn("line 2", caught.exception.message)

    def test_every_schema_is_claimed_by_exactly_one_method(self):
        claimed = {}
        for sid, spec in dataset_guard.SCHEMAS.items():
            claimed.setdefault(spec["method"], []).append(sid)
        for method, ids in claimed.items():
            self.assertEqual(len(ids), 1, f"{method} claims more than one schema: {ids}")
        self.assertEqual(set(claimed), set(presets.METHODS))

    def test_the_corpus_is_still_denied_under_every_schema(self):
        """A new schema must not become a new way in."""
        for schema in dataset_guard.SCHEMAS:
            with self.subTest(schema=schema):
                with self.assertRaises(dataset_guard.Refused) as caught:
                    dataset_guard.admit("training/corpus.jsonl", schema=schema)
                self.assertEqual(caught.exception.code, "protected")

    def test_sniff_refuses_the_corpus(self):
        """`sniff` reads a file to label it, so it is a read and goes through the deny check."""
        self.assertIsNone(dataset_guard.sniff("training/corpus.jsonl"))


class RolloutTests(unittest.TestCase):
    """Where completions come from, and the two backends that are refused with reasons."""

    def test_llama_cpp_is_refused_for_rollouts_with_the_correctness_reason(self):
        """Refused because it cannot carry the adapter being trained -- not because it is slow or
        because nobody got to it. A fast generator that is not the policy is not a rollout
        engine."""
        got = rollout.check("llama.cpp")
        self.assertFalse(got["ok"])
        self.assertEqual(got["reason"], "capability")
        self.assertIn("off-policy", got["message"])

    def test_transformers_is_always_available_and_on_policy(self):
        self.assertTrue(rollout.check("transformers")["ok"])
        self.assertTrue(rollout.BACKENDS["transformers"]["on_policy"])

    def test_vllm_without_a_configured_url_is_refused_not_defaulted(self):
        """A silent fallback to in-process generation would change the sampling implementation
        and the throughput of a run without changing the label on it."""
        old = os.environ.pop(rollout.URL_ENV, None)
        self.addCleanup(lambda: os.environ.__setitem__(rollout.URL_ENV, old) if old else None)
        state = rollout.probe()
        self.assertFalse(state["configured"])
        self.assertFalse(state["reachable"])
        got = rollout.check("vllm")
        self.assertFalse(got["ok"])
        self.assertEqual(got["reason"], "capability")

    def test_a_non_http_url_is_not_accepted(self):
        """A `file://` spelling in an environment variable is not a URL this package hands to
        anything."""
        os.environ[rollout.URL_ENV] = "file:///etc/passwd"
        self.addCleanup(os.environ.pop, rollout.URL_ENV, None)
        self.assertEqual(rollout.vllm_base_url(), "")

    def test_no_preset_defaults_to_an_unavailable_rollout(self):
        """A preset whose rollout cannot work on this box is a control that always refuses."""
        for pid, p in presets.PRESETS.items():
            if p.method != "reinforcement":
                continue
            with self.subTest(preset=pid):
                self.assertEqual(p.method_config.get("rollout"), "transformers")

    def test_the_module_imports_no_vllm_and_no_torch(self):
        mods = _imported_modules(next(_p for _p in pathlib.Path(__file__).resolve().parents if (_p / "backend" / "server.py").is_file()) / "rollout.py")
        for banned in ("vllm", "torch", "trl"):
            self.assertNotIn(banned, mods)


class MethodCostTests(unittest.TestCase):
    """The RL cost model. A wrong number wearing an honest label is worse than no number."""

    def setUp(self):
        entry = registry.find(SEVEN_B)
        if entry is None or entry.arch is None:
            self.skipTest("the 7B is not in the local weight cache")
        self.arch = registry.Arch(**entry.arch)

    def _plan(self, **kw):
        base = dict(rank=16, target_modules=presets.ALL_SEVEN, seq_len=384, batch=1,
                    gradient_checkpointing=True)
        base.update(kw)
        return registry.plan_fit(self.arch, **base)

    def test_supervised_projections_are_unchanged_by_the_new_terms(self):
        """The method dimension must not have moved a figure the site may already be quoting."""
        self.assertEqual(self._plan()["projected_peak_bytes"],
                         self._plan(method="sft", method_config={})["projected_peak_bytes"])

    def test_reinforcement_costs_strictly_more_than_supervised(self):
        """Costing a GRPO run with the supervised model would understate its peak by the whole
        rollout term and publish the understatement labelled `projected`."""
        sft = self._plan()["projected_peak_bytes"]
        rl = self._plan(method="reinforcement",
                        method_config={"num_generations": 4, "max_completion_length": 192,
                                       "beta": 0.0})["projected_peak_bytes"]
        self.assertGreater(rl, sft)

    def test_more_generations_costs_more(self):
        """`num_generations` multiplies every activation term, which is why it is the first rung
        on this method's ladder rather than rank."""
        def peak(g):
            return self._plan(method="reinforcement",
                              method_config={"num_generations": g,
                                             "max_completion_length": 192,
                                             "beta": 0.0})["projected_peak_bytes"]
        self.assertGreater(peak(8), peak(4))
        self.assertGreater(peak(4), peak(2))

    def test_the_kl_term_costs_a_forward_pass_and_no_weights(self):
        """beta>0 adds a reference forward. It must cost something, and it must not cost a second
        copy of the weights -- the reference is this model with the adapter disabled."""
        cfg = {"num_generations": 2, "max_completion_length": 96}
        free = self._plan(method="reinforcement", method_config={**cfg, "beta": 0.0})
        kl = self._plan(method="reinforcement", method_config={**cfg, "beta": 0.04})
        self.assertGreater(kl["projected_peak_bytes"], free["projected_peak_bytes"])
        self.assertIn("reference_forward", kl["terms"])
        self.assertNotIn("reference_forward", free["terms"])
        # A second 4-bit 7B would be over 3.5 GiB. The reference must cost far less than that.
        weights = free["terms"]["weights_4bit"]["bytes"]
        self.assertLess(kl["terms"]["reference_forward"]["bytes"], weights)

    def test_precomputing_reference_logprobs_removes_it_from_the_peak(self):
        """The reason the preference preset sets it: the reference passes happen before the
        optimiser state exists, so the two never coincide."""
        cfg = {"beta": 0.1}
        live = self._plan(method="preference", method_config=cfg)
        pre = self._plan(method="preference",
                         method_config={**cfg, "precompute_ref_log_probs": True})
        self.assertEqual(pre["terms"]["reference_forward"]["bytes"], 0)
        self.assertGreater(live["terms"]["reference_forward"]["bytes"], 0)
        self.assertLess(pre["projected_peak_bytes"], live["projected_peak_bytes"])

    def test_preference_charges_the_second_sequence(self):
        """Chosen and rejected are concatenated on the batch dimension, so one example is two
        sequences through the model."""
        plan = self._plan(method="preference",
                          method_config={"precompute_ref_log_probs": True})
        self.assertIn("preference_pair_activations", plan["terms"])
        self.assertGreater(plan["terms"]["preference_pair_activations"]["bytes"], 0)

    def test_the_rl_ladder_offers_generations_before_rank(self):
        """On an RL run, rank is the smallest term on the panel. Offering it first would point
        the operator at the wrong knob."""
        plan = self._plan(seq_len=2048, rank=32,
                          method="reinforcement",
                          method_config={"num_generations": 8, "max_completion_length": 1024,
                                         "beta": 0.04})
        self.assertNotEqual(plan["verdict"], "fits")
        self.assertIn("num_generations", plan["ladder"][0])

    def test_rl_terms_do_not_claim_the_supervised_measurement(self):
        """There is exactly one real peak behind this arithmetic and it is a supervised run.
        `accuracy` must not be read as covering the RL terms."""
        plan = self._plan(method="reinforcement",
                          method_config={"num_generations": 4, "max_completion_length": 192,
                                         "beta": 0.0})
        self.assertIn("NEVER been checked", plan["method_accuracy"])
        self.assertEqual(plan["label"], "projected")


class InitAdapterTests(unittest.TestCase):
    """Continuing from an existing adapter: the SFT-then-RL pipeline, and the read-only guard."""

    def test_the_shipped_adapter_is_allowed_as_a_starting_point(self):
        """It is DENIED as a dataset and ALLOWED as a starting adapter, and that asymmetry is
        deliberate: the standard pipeline is supervised first and RL on top, so the persona
        adapter is the intended starting point. Reading weights to continue training is not
        serving a corpus over HTTP."""
        if not (jobs.SHIPPED_ADAPTER / "adapter_config.json").is_file():
            self.skipTest("the shipped adapter is not on this box")
        got = jobs._admit_init_adapter(str(jobs.SHIPPED_ADAPTER))
        self.assertTrue(got.endswith("training/adapter"))
        # ...and the same path is still refused as a dataset.
        with self.assertRaises(dataset_guard.Refused):
            dataset_guard.admit(str(jobs.SHIPPED_ADAPTER / "corpus.jsonl"))

    def test_the_corpus_is_not_an_adapter(self):
        with self.assertRaises(jobs.AdapterRefused):
            jobs._admit_init_adapter("training/corpus.jsonl")

    def test_a_directory_without_an_adapter_config_is_refused(self):
        """Checked by structure rather than by name, because `PeftModel.from_pretrained` would
        otherwise fail well after the card was acquired."""
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(jobs.AdapterRefused) as caught:
                jobs._admit_init_adapter(tmp)
            self.assertIn("not a PEFT adapter", str(caught.exception))

    def test_empty_means_a_fresh_adapter_and_is_not_an_error(self):
        self.assertEqual(jobs._admit_init_adapter(""), "")

    def test_the_runner_refuses_an_adapter_with_nothing_trainable(self):
        """`PeftModel.from_pretrained` loads adapters in inference mode by default. Without
        `is_trainable=True` the run completes, reports a loss and saves a copy of its input --
        a silent no-op that looks like a successful run."""
        source = (next(_p for _p in pathlib.Path(__file__).resolve().parents if (_p / "backend" / "server.py").is_file()) / "runner.py").read_text()
        self.assertIn("is_trainable=True", source)
        self.assertIn("AdapterNotTrainable", source)
        self.assertIn("AdapterNotTrainable", str(jobs._ALLOWED_KEYS) + source)

    def test_no_run_can_write_to_the_shipped_adapter(self):
        """Output goes to `run/reinforce/adapters/<job-id>`. Promotion stays a deliberate manual
        act, and an experiment must not overwrite the adapter chat serves."""
        self.assertNotIn(str(jobs.SHIPPED_ADAPTER), str(jobs.OUTPUT_DIR))
        self.assertIn("run", str(jobs.OUTPUT_DIR))


if __name__ == "__main__":
    unittest.main(verbosity=2)
