# tests/misc/ — genuinely cross-cutting

Seven files that belong to no single component. **If something lands here twice it wants a
home**, and this directory is where that is noticed rather than where it is hidden.

```
test_sabotage_matrix.py        break a thing on purpose, confirm the right test goes red
test_bootcamp_referee.py       the training-bay referee
test_bootcamp_scout.py         the scout
test_bench_llm.py              the benchmark harness itself
test_serving_config_audit.py   what the running service was configured with
test_references_boundary.py    references stay inspiration, never a source
test_loop_not_blocked.py       nothing blocks the event loop
```

## `test_sabotage_matrix.py` is the one to know

It implements the standing rule: **a test that passes before and after your change tested
nothing.** It breaks a thing deliberately and asserts a specific test goes red. Reach for it
when you are unsure a check discriminates — which is most of the time, since a check that
can pass without the work being finished is worse than no check at all.

Note it has a side effect worth knowing about, recorded in its own docstring: running it
rewrites files in a temp tree, and an earlier version did so in the real one.
