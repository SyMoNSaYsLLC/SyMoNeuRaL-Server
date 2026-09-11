# SMOKE — `gpu-governor.sh` evict/status read the process table

Task #100, R-172. Written from runs, not from reading the diff. Every block below is
pasted output.

**Tree:** `f63dd3e` + the working change to `scripts/gpu-governor.sh`.
**Measured:** 2026-08-21 on this box. One RTX 5070 Ti, 16303 MiB.

---

## The defect, reproduced against the shipped file

`a944fae` inferred "did I stop something?" from the stop command's exit code. Two arms
shell out to a helper script and both helpers succeed whether or not anything was running:

- `bin/symoneural-cli:346` — `cmd_stop_chat` ends `return 0`, no branch reports otherwise.
- `scripts/symoneural-ui.sh:95-120` — the not-running path pkills, unlinks, exits 0.

Run in a throwaway root with `run/resident` stamped to a surface that is **not running** and
both helpers stubbed as `exit 0` — an accurate model of the two real ones, not a
convenience. `git show a944fae:scripts/gpu-governor.sh`, same skeleton, same stubs:

```
--- evict 'chat' over a dead marker (a944fae) ---
2026-08-21 18:24:53  evict    stopping 'chat' to make room -- the weight sets do not co-fit
--- evict 'comfy' over a dead marker (a944fae) ---
2026-08-21 18:24:53  evict    stopping 'comfy' to make room -- the weight sets do not co-fit
--- evict 'image' over a dead marker (a944fae) ---
2026-08-21 18:24:53  evict    'image' recorded but no run is active -- treating as stale
=== status over a dead marker (a944fae) ===
resident surface   comfy
```

Three lines, three findings. `chat` and `comfy` claim an eviction that freed nothing.
`image` is correct, because its stop action is a bare `pkill` whose exit code means
something — so the commit fixed the half that was already honest and missed **`comfy`, the
surface R-172 was written about**. And `status` prints the marker with nothing beside it.

## The same skeleton, after

```
--- evict 'chat' over a dead marker (FIXED) ---
2026-08-21 18:24:46  evict    'chat' recorded but no run is active -- treating as stale
2026-08-21 18:24:46  acquire  'sigil' holds the card -- 16303 MiB free, waited 0s
--- evict 'comfy' over a dead marker (FIXED) ---
2026-08-21 18:24:46  evict    'comfy' recorded but no run is active -- treating as stale
2026-08-21 18:24:46  acquire  'sigil' holds the card -- 16303 MiB free, waited 0s
--- evict 'image' over a dead marker (FIXED) ---
2026-08-21 18:24:46  evict    'image' recorded but no run is active -- treating as stale
2026-08-21 18:24:46  acquire  'sigil' holds the card -- 16303 MiB free, waited 0s
--- evict 'miner' over a dead marker (FIXED) ---
2026-08-21 18:24:46  evict    'miner' recorded but no run is active -- treating as stale
2026-08-21 18:24:46  acquire  'sigil' holds the card -- 16303 MiB free, waited 0s
=== status over a dead marker (FIXED) ===
resident surface   comfy (not running -- stale marker)
```

## The live half, on the real card

The negative case can be run in a skeleton; the positive case cannot be faked into one
without killing whatever is genuinely resident, so it is read off this box instead. ComfyUI
was up throughout — `pgrep -af 'engines/symoneural-ui/main.py'` → pid 14202 — and
`run/resident` said `comfy`:

```
$ bash scripts/gpu-governor.sh status
resident surface   comfy (running)
lock               free
vram used          469 MiB  (whole card, desktop included)
```

Same marker, same file, opposite reading from the one above. That is the whole change: the
marker is a hint and the process table is the fact, which is what R-172 asked for in those
words.

## The miner arm

`a944fae` collapsed the quoted `$ROOT` interpolation at line 204, so the arm raised
`SyntaxError: unterminated triple-quoted string literal` on every invocation and always
fell through to its pgid `pkill`. Nothing went red anywhere, because `bash -n` cannot see
inside a `python3 -c` string, `run/miner.pid` does not exist, and `pgrep -g -1` matches
nothing. Executed for real after the fix:

```
$ python3 -c 'import sys; sys.path.insert(0, "'"$PWD"'/backend/apps"); import cryptominer; cryptominer.stop()'
exit=0
```

`apps/test_governor_evict.py::TheMinerArmIsValidPythonTests` compiles that string out of
the shipped file, because that is the only check that can see it.

## Why the probe patterns are anchored at `$ROOT` and the `pkill` patterns are not

They ask different questions. `pkill` aims at a process we have already decided to stop,
where a tail match is the forgiving end. The probe answers *is **our** surface resident*,
and a bare `engines/symoneural-ui/main.py` answers yes to any other checkout on the box.

Anchoring can only produce a false **negative** — conclude nothing is running when
something is — and that lands on `drain`, which reads the card itself and refuses the
handoff. A false positive has no backstop: it logs a successful eviction and hands over
memory that is still held. Verified the anchored form is what is actually in the table:

```
14202 /home/google/Symoneural/engines/symoneural-ui/.venv/bin/python \
      /home/google/Symoneural/engines/symoneural-ui/main.py --listen 127.0.0.1 --port 8188
```

`api.py:1151` and `:2397` both spawn by absolute path (`LLM_ENGINE`, `DIFFUSE_ENGINE` are
`ROOT`-relative `Path`s), so the same holds for chat and image.

## Suites

Red first, on the tree that shipped the bug, then green:

```
$ cd backend && python3 -m pytest apps/test_governor_evict.py -q     # at a944fae
5 failed, 8 passed in 0.23s
    TheLogFollowsTheProcessTableTests::test_chat_over_a_dead_marker_reports_stale
    TheLogFollowsTheProcessTableTests::test_comfy_over_a_dead_marker_reports_stale
    TheMinerArmIsValidPythonTests::test_the_broken_literal_is_gone
    TheMinerArmIsValidPythonTests::test_the_miner_arm_compiles
    StatusReadsTheProcessTableTests::test_a_dead_marker_is_reported_as_not_running

$ cd backend && python3 -m pytest apps/test_governor_evict.py \
      apps/test_governor_drain.py apps/test_governor_paths.py -q
31 passed in 10.57s
```

The five that were red are the five findings. `image`, `miner` and the `*` fallback were
green before and after, which is the part that makes the red meaningful: the suite
distinguishes the arms that were broken from the arms that were not.

## What this does not cover

`train` keeps its own liveness check and its refusal, unchanged and untouched by the
refactor — it is answered before the probe and is never evicted to serve a page view.

The positive path for `chat` and `image` is not exercised by any automated test, because
doing it honestly means killing a real engine. It is covered by the `comfy (running)`
reading above, which goes through the same `surface_live` for the same reason.
