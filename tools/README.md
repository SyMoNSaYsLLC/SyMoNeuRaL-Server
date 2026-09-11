# tools/ — generators, benchmarks and audits

**None of this runs in production.** Nothing under `backend/` imports anything here. These
build artefacts, measure the box, and check the tree against itself.

```
build/    generators. Read a record, write a rendering. Every one has --check.
bench/    measure the card and the models. Real runs, real numbers.
audit/    check the tree against itself. Report, never fix.
lib/      shared helpers, and the generators' own libraries
data/     storage and Drive tooling. Points at the OLD tree on purpose -- see below.
sh/       engine forks, upstream restore, cleanup pipelines
```

## The rule every generator follows

**Read a record, write a rendering. Never the other way round.**

```bash
python3 tools/build/build_ports.py      # ops/PORTS.tsv -> ops/registry/PORTS.md
python3 tools/build/build_ports.py      # AGAIN
git diff --exit-code                    # must be clean
```

**Run every generator twice and diff.** They re-read their own output, and one that does not
recognise something it emits accumulates it — one copy per run. That bug has happened three
times in this repository, and two runs with no diff is the check that catches it.

Each has `--check`, which fails rather than writes. That is what belongs in CI.

## bench/ — measuring, not guessing

```bash
python3 tools/bench/bench_maxfit.py   --model models/llm/<file>   # find the context ceiling
python3 tools/bench/bench_config.py   --model models/llm/<file>   # sweep the argv
python3 tools/bench/bench_models.py                               # compare models
python3 tools/bench/bench_scanrate.py                             # parameters per second
python3 tools/bench/qa_run.py                                     # does it still answer correctly
```

`bench_maxfit.py` finds the ceiling by **overshooting and backing off**, which is the owner's
correction to an earlier version that tried arbitrary values: raise `-c` until the allocation
fails, then step back to the largest that fits with headroom.

`bench_config.py` holds the model fixed and varies the argv; `bench_models.py` does the
opposite. They answer different questions and both are worth having.

**Fix the seed.** A token count that is not reproducible is not a measurement.

The `moe_*.py` tools capture and prune mixture-of-experts routing. The result is recorded and
negative — pruning produces broken models, and router healing does not fix it. See
`models/README.md` before spending time there.

## audit/ — report, never fix

`import_audit.py`, `route_audit.py`, `cross_root_audit.py`, `probe_apps.py`,
`probe_engines.py`, `serving_config_audit.py`, `prove_*.py`.

They print findings. An auditor that repaired what it found would destroy the evidence that
it was ever wrong, and the count it reports next run would mean nothing.

## data/ — points at /home/google/Symoneural on purpose

The storage-reorganisation tools hardcode the **old** tree, because that is what they operate
on. They are the record of a migration that is held, not a facility this server uses. Do not
"fix" those paths to point here.

## Root anchors

Every tool walks up for `backend/server.py`. On 2026-09-11 the tools moved from `tools/` into
these six directories and **63 parent-counting anchors broke at once**, silently, because the
wrong parent is usually a directory that exists. `tests/structure/test_path_fragility.py`
fails the build if one comes back.

## Adding a tool

Put it in the bucket that names what it does. Give a generator `--check`. Make it runnable
from anywhere. And before you write one that measures something, check whether a registry
already records it — a fifth answer to a question four records answer is a fifth thing that
can disagree.
