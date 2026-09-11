# tools/ — generators, benchmarks and audits

**None of this runs in production.** Nothing under `backend/` imports anything here. These
build artefacts, measure the box, and check the tree against itself.

```
makemeone.mjs  scaffold one of anything this tree has a shape for
build/    generators. Read a record, write a rendering. Every one has --check.
bench/    measure the card and the models. Real runs, real numbers.
audit/    check the tree against itself. Report, never fix.
lib/      shared helpers, and the generators' own libraries
data/     storage and Drive tooling. Points at the OLD tree on purpose -- see below.
sh/       engine forks, upstream restore, cleanup pipelines
```

## makemeone

```bash
node tools/makemeone.mjs --list
node tools/makemeone.mjs component ravenstore          # backend surface, 7 files
node tools/makemeone.mjs surface   ravenstore          # frontend application, 6 files
node tools/makemeone.mjs page      live-stack          # static site page
node tools/makemeone.mjs script    drain-cache         # shell script with the lib preamble
node tools/makemeone.mjs component ravenstore --dry-run
```

## Why a generator and not a wiki page

Every convention here was paid for:

- a component is `<name>/<name>.py`, **not** `router.py` — thirty files called router.py tell
  you nothing in a file manager
- its subdirectories are always `models/ lib/ apps/ docs/` — asymmetry is what made the old
  tree unreadable
- a script sources `lib/repo.sh` — sixteen of them resolved the repository eight different
  ways and all but one counted parents
- `prefix` and `tags` live on the `APIRouter`, not at the mount — so `/docs` groups a surface
  by reading the router rather than by `server.py` remembering to say so

None of that survives being remembered. A generator is how a convention outlives the person
who learned it the hard way.

## It refuses rather than overwrites

Every target is checked **before** anything is written, and one existing file aborts the whole
run. A scaffolder that half-writes over a real component is worse than no scaffolder.

## Names are checked per kind

A component becomes a **Python package**, so no hyphen — `import gpu-governor` is a syntax
error. A script and a page become **filenames**, and this tree spells those with hyphens:
`gpu-governor.sh`, `check-stale-pyc.py`. One rule for both would either break imports or force
scripts into a spelling nothing else here uses.

## What it writes for a component

```
backend/<name>/__init__.py            exports the router and nothing else
backend/<name>/<name>.py             the routes, with prefix and tags on the router
backend/<name>/models/__init__.py    request and response models, every field bounded
backend/<name>/lib/__init__.py       no routes, no side effects on import
backend/<name>/apps/__init__.py      runnable programs
backend/<name>/docs/
tests/component/<name>/test_<name>.py
```

Then it prints the five things it cannot do for you — mount it, give it a rate budget,
regenerate the READMEs, run its test, and **write the prose half of its README**. The
generated half is a reading of the tree and the schema; the reason a component exists is not.

## The bug this caught on its first real run

The component template had `dependencies=[throttled_for("<name>")]`. `throttled_for` returns
the dependency *function*; FastAPI needs `Depends(throttled_for(...))`. Every scaffolded
component would have failed to mount with `'function' object has no attribute 'dependency'`.

Found by generating one, running its test, and importing it — not by reading the template.
That is the same lesson as the three startup defects: a thing that imports is not a thing
that works.

---

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

## One thing to check before trusting this directory

`.gitignore` carried a bare `build/` for the life of this tree. Unanchored, that matches
**any** directory named build at any depth — and it silently swallowed `tools/build/`, all
32 generators. `build_progress.py`, `build_ports.py`, `build_pages.py` and
`build_component_readmes.py` were untracked, so a clone got none of the things that write
this repository's records.

It was found by checking a README somebody reported missing. The README was there; the whole
directory was ignored. Nothing reports that — `git status` is clean, `ls` shows the files,
and only `git check-ignore -v <path>` says why.

```bash
git status --ignored --short | grep '^!!'    # what is excluded, and is that deliberate
```

Run that after any `.gitignore` edit. An ignore rule is the one kind of mistake that makes
work disappear while every other signal says it is fine.
