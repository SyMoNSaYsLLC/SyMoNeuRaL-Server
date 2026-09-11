# makemeone — scaffold one of anything this tree has a shape for

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
