# tests/ops/ — scripts, units, deploys and generators

15 files. These run real scripts against temporary trees, so they are slower than the
component tests and they catch a different class of fault: the kind that only appears when
something is *executed* rather than imported.

```
test_model_staging.py       the staging script's refusals, and the model inventory
test_build_progress.py      the generators are idempotent -- run twice, no diff
test_restore_manifests.py   every manifest regenerates to itself
test_service_control.py     the units start, stop and report
test_server_ready.py        SERVER-READY.md covers every row the roster declares
test_caddy_delegation.py    Caddy sends /api to the gateway and nothing else
test_deploy_routes.py       what deploy.sh publishes, and what it refuses to
test_enable_surfaces.py     a surface turns on exactly as PORTS.tsv says
test_governor_*.py          drain, evict, same-surface, paths -- the lease protocol
test_preflight.py           the preflight refuses what it should
test_archive_guard.py       a task cannot archive on checks that cannot discriminate
test_build_deb.py  test_export_snapshot.py  test_modelops.py
```

## Why the generator tests matter most

Every generator in this repository re-reads its own output. One that does not recognise
something it emits **accumulates it, one copy per run** — and that bug has happened three
separate times here. `test_build_progress.py` runs each generator twice and diffs, which is
the only check that catches it.

## A test here should run the real thing

Against a temp tree, with a fixture that sets up `backend/server.py` as the marker — the
scripts walk up for it. A test that asserts on a script's source rather than its behaviour
cannot tell a working script from a renamed one.
