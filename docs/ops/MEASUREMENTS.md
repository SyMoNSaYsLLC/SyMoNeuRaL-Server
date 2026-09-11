# SyMoNeuRaL measurements — the suites, the ladder, the rules for numbers

Moved here verbatim from `.claude/CLAUDE.md` on 2026-08-22 (R-180, Phase 0.6b).
Same words, new home: the rules are project property, not agent configuration.

**This file is the one home for suite counts.** A number with no SHA cannot be checked,
only believed; a count carried forward and re-dated is the disease this ladder exists to
cure. `backend/apps/test_streamer_migration.py` parses THIS file for the commanded suite
paths, so every `tests/*.mjs` suite must be named here or that test goes red.

## Test in a real browser, not with curl

```bash
node tests/run_ui_verification.mjs   # required UI suites, one at a time; canonical record
node tests/applications_smoke.mjs    # self-contained fixture for the application workspaces
node tests/frontend.mjs             # every page, against a running API on :8800
node tests/streamer_failpaths.mjs   # streamer.html, self-contained -- starts its own fake provider
node tests/streamer_watch.mjs       # streamer-watch.html, ditto -- no account, no real stream
node tests/studio.mjs               # /studio -- needs the surface on, ComfyUI up, and the GPU
node tests/streamer_guide.mjs       # the guide grid on streamer.html -- own API, no GPU, no provider
node tests/project.mjs              # /project -- needs tests/project-harness.py, no GPU
node tests/live.mjs                 # /livestack/live -- needs tests/live-harness.py, no GPU, no OBS
node tests/responsive.mjs           # 24 pages x 8 viewports, against a running API on :8800
node tests/architecture.mjs         # the readability and ownership floors responsive.mjs cannot see
node tests/accessibility.mjs        # heading outlines and keyboard focus; writes SMOKE-ACCESSIBILITY.md
node tests/chat_smoke.mjs           # chat.html end to end -- TAKES THE GPU, run it alone
node tests/coders_smoke.mjs         # local scratch coder sessions + one real debate; provider accounts/GPU
python3 -m pytest backend -q          # one invocation, from the repo root, no flags to remember
```

**That python line replaced three, and the reason is worth keeping.** It used to be

```bash
cd backend && python3 -m pytest apps/ -q \
    --ignore=apps/studio/plugins/reinforce/tests --ignore=apps/remix/tests
cd backend/apps/remix && python3 -m pytest -q   # the 28 the line above has to exclude
```

Every part of that was a workaround an operator had to carry in their head, and each one
had already failed at least once:

- **the `cd backend`** was load-bearing and undocumented. `apps/**` imports its siblings as
  `apps.something`, which resolves only when `backend/` is on `sys.path`. Run from the repo
  root instead and `apps/controlboard`, `apps/dispatchos`, `apps/live` and
  `apps/streamer/guide` reported `ModuleNotFoundError: No module named 'apps'` as collection
  ERRORS while passing 169/169 with the path set. `backend/conftest.py` now puts `backend/`
  on `sys.path` — which is not a test-only convenience, it is what the service already does:
  `ExecStart=/usr/bin/python3 .../backend/server.py` makes `backend/` `sys.path[0]` at runtime.
- **the two `--ignore` flags** were an exclusion nobody could see from the failure. The
  reinforce path in the line above had gone stale — that suite moved to
  `apps/studio/plugins/reinforce/tests` — and the exclusion is now enforced by the suite
  itself, which `importorskip`s cupy so it skips cleanly instead of erroring.
- **the second invocation for `apps/remix`** existed because its tests import
  `symoneural_dj` directly. `apps/remix/conftest.py` puts that package's own directory on
  the path for both invocations, so remix is collected with everything else and needs no
  separate run.
- **`backend/vendor/`** is excluded by `collect_ignore_glob`, not by a flag. It holds the
  vendored Anthropic and OpenAI SDKs — 15,297 tracked files with their own suites, including
  `e2e-tests/` wanting network and provider credentials. Collecting them aborted the whole
  run at 48 errors before a first-party test executed. Point pytest at `backend/vendor/...`
  deliberately to run them; what is excluded is their appearance in *our* result.

`run_ui_verification.mjs` is the normal entry point for the four application-wide suites:
applications, responsive, frontend, then chat. It awaits each child before launching the
next, preserves complete logs under `run/ui-verification/`, forwards interrupts to the
active browser process group, and writes `docs/ops/SMOKE-APPLICATIONS.md`. The canonical
success marker appears only when all four exit zero; a partial or interrupted run cannot
manufacture it. Use `--dry-run` to inspect the order without an API or browser.

> **THIS DOCTRINE CANNOT BE EXECUTED ON THIS HOST AS IT STANDS, 2026-09-03.** Every suite above
> launches `channel: 'chrome'` — the system Google Chrome — and there is none:
> `/opt/google/chrome/chrome` is absent, no `google-chrome`/`chromium`/`chromium-browser` is on
> `PATH`, and `~/.cache/ms-playwright` holds no browser. `frontend.mjs` and
> `applications_smoke.mjs` were attempted read-only and both aborted with
> `browserType.launch: Chromium distribution 'chrome' is not found`. **Every UI, responsive,
> accessibility and browser-behaviour figure below therefore rests on August readings that
> cannot be re-measured here.**
>
> Playwright itself IS installed (`tests/node_modules/playwright` 1.56.1), and a headless
> Chromium exists at `/usr/lib/chromium/chromium-headless-shell`. **Neither suite was repointed
> at it, deliberately.** `tests/browser.mjs` says why in its own header: the suites use the
> browser real visitors use, which is what makes the readings mean anything. Substituting a
> different engine would keep the numbers flowing while quietly changing what they measure —
> a worse failure than an honest gap. The fix is to install Chrome and re-measure, not to
> re-point the harness.
>
> The suite named `applications` in the command list above is the file
> `tests/applications_smoke.mjs`.

**2203 pass, 0 fail and 56 skip at `4c36b77f`, measured 2026-09-03 in 293.9 s** from the
repo root with the single canonical command `python3 -m pytest backend -q`. Reproduced twice
on the same tree by an independent read-only session (293.65 s and 296.34 s), exit code read
directly as **0** rather than inferred from the summary line.

**`--collect-only` reads 2258, one LOWER than the 2259 outcomes the run accounts for, and that
gap is benign.** This file declares the collect-vs-run comparison the collection-abort tripwire,
so the difference is explained here rather than left for the next operator to read as an abort:
`apps/studio/plugins/reinforce/tests/conftest.py` calls `pytest.importorskip("cupy")` at module
level, which reports **one skip while contributing zero collected items**. That accounts for the
difference exactly. A collection abort produces no number at all, not a number short by one.

The jump from 1818 is mostly not new tests. `backend/conftest.py` (`71e78186`) put `backend/`
on `sys.path` and dropped `backend/vendor/` from collection; before it, four app modules --
`controlboard`, `dispatchos`, `live`, `streamer/guide` -- reported `ModuleNotFoundError: No
module named 'apps'` as collection ERRORS while passing 169/169 once the path was set, and the
vendored SDK suites aborted the whole run at 48 errors before a first-party test executed.

**1818 pass, 0 fail and 14 skip at `ca0571b7`, measured 2026-08-22 from `backend/` in
143.73 s, with `--collect-only` collecting 1832 in 1.24 s and `apps/remix` 28/28 in 0.44 s —
1846 across the two invocations, and 1818 + 14 = 1832 is the arithmetic that says nothing
aborted.** Unlike every recent rung this one carries no working-tree caveat: the run's
post-commit `git status` was untracked-only, so the tree measured IS `ca0571b7`.

This reading closes the no-SHA story below. `ce4fb27c` landed the ravencalc repair, so a
clean checkout collects again and the ladder's hole (`49185b8`..`48dcaaf`) is bounded, not
open-ended. The same commit range also caught the fold's stragglers the honest way: the
first 0.5 run went **3 fail at `242a688d`** — two `PageTests` because #81's `@@PAGECSS@@`
placeholder in `build_pages.SHELL` broke the generators that import that SHELL with their
own field dicts (a placeholder in a shared shell is a contract with every consumer; it is
an insertion in `page()` now), and one `RowCoverageTests` because `docs/SERVER-READY.md`
still carried a gateway row for a rack that no longer has one. Fixed at `ca0571b7`, the
commit this reading is true of.

Of the 60 over the working-tree 1758, thirteen are 2026-08-22's and attributable in full
per file: **+8** `apps/test_livestack_routes.py` (new at `1bccb765`, #81), **+3**
`apps/test_deploy_routes.py` and **+1** `apps/test_caddy_delegation.py` (across `1bccb765`
and `e71b51f7`), **+1** `apps/test_status_rack.py` (the FOLDED map, `c779e2cb`). The other
47 span the twelve commits `41e6a905`..`2d2af124` from the sessions between — Coder (#87),
the ravencalc show-your-work tests, the neglect measure — and are deliberately not
attributed per file here: a count moves when tests land, and whoever needs that span
attributed should diff `--collect-only` per file across it rather than believe a guess.

**1758 pass, 0 fail and 14 skip, measured 2026-08-21 from `backend/` in 139.31 s, with
`--collect-only` collecting 1772 in 1.24 s and `apps/remix` 28/28 in 0.43 s — and there is
deliberately no SHA on that sentence, because there is no commit it is true of.** It is a
reading of the **working tree** at `48dcaaf`, which is not the same thing as a reading of
`48dcaaf`, and the difference is the most useful thing in this section.

A clean worktree checked out at `48dcaaf` does not collect at all:

```
ERROR apps/ravencalc/test_ravencalc.py - NameError: name 'convert_xor' is not defined
!!!!!!!!!!!!!!!! Interrupted: 1 error during collection !!!!!!!!!!!!!!!!
```

Zero tests run — **no number at all**, wearing the costume of a broken suite, which is the
shape this file warns about twice already. Bisected in a detached worktree, `apps/ravencalc`
alone: **14 collected at `a944fae`**, then `1 error` at `49185b8`, `f63dd3e`, `95e02c5` and
`48dcaaf`. `49185b8` ("Facade sympy behind symbolic.py to close Task #74") routed
`ravencalc.py:47` at `symbolic.py` for `convert_xor` and `symbolic.py` does not re-export it,
so `_TRANSFORMS` at `ravencalc.py:89` blows up at import.

**What makes the tree green is two uncommitted files** — `backend/apps/ravencalc/ravencalc.py`
and `backend/apps/ravencalc/symbolic.py`, 5 insertions and 2 deletions, work in flight from
another session, which add the missing re-export. They are not mine and were deliberately kept
out of `48dcaaf` (explicit pathspecs on the commit). So the 1758 is a real measured reading
that **nobody can reproduce from git alone** until that repair lands, and stamping it with a
SHA would have been the carried-forward figure this file exists to prevent — arriving not by
somebody re-dating a number, but by the tree moving underneath one that was honestly taken.
Re-measure and re-stamp once ravencalc is committed.

The 22 over the reading below it are attributable in full, per file: **+13**
`apps/test_governor_evict.py`, landed whole at `95e02c5` with #100's R-172 half (the marker is
a hint, the process table is the fact), and **+9** `apps/test_chat_lease.py`, landed whole at
`48dcaaf` with #100's R-173 half. 1736 + 13 + 9 = 1758.

**Eight of those nine were red against `95e02c5` and that is the point of them**, not a
footnote: the ninth (`test_the_gate_still_decides_exactly_what_it_decided_before`) is green on
both trees on purpose, because it asserts the rack gate's verdict did *not* change when its
mounting did. And one of the eight was green on the broken tree when first written — it
asserted `"thinking.cancel()" in src`, and the handler has always cancelled that task on the
RavenCalc branch, so the loose form passed over the bug it was written to catch. A check that
can pass without the work being finished is worse than no check; it archives the task.
`backend/SMOKE-lease-503.md` has that and the four runs behind it.

**`@app.middleware("http")` is now barred in `api.py` and a test enforces it.** It is
`BaseHTTPMiddleware`, which runs the endpoint against a *substitute* receive channel, so
`http.disconnect` never arrives and `await request.is_disconnected()` never answers True —
which meant a visitor closing the tab mid-answer leaked the GPU lease until the process died,
with the next tenant waiting out `ACQUIRE_TIMEOUT_S = 300`. Measured, one handler, one
abandoned socket: bare app RELEASED, `+GZipMiddleware` RELEASED, `+BaseHTTPMiddleware`
**LEAKED with an empty event list** — neither the watchdog nor the generator's `finally` ran,
so there was nothing in any log to read — and `+` the gate rewritten as raw ASGI RELEASED.
Write middlewares as ASGI classes here.

**1736 pass, 0 fail and 14 skip at `594efac`, measured 2026-08-21 from `backend/` in
138.52 s, with `--collect-only` collecting 1750 in 1.37 s; the two `--ignore`s are not optional
and not a failure you introduced.** 1736 + 14 = 1750, which is the arithmetic that says nothing
aborted. `backend/apps/remix` is **28/28 in 0.42 s** on the same tree, so this tree carries
**1778 across the two invocations**.

**Run it from `backend/`, not from the repo root.** `python3 -m pytest backend/apps -q` with the
`--ignore`s rewritten to match looks equivalent and is not: rootdir moves, `apps` stops being
importable, and you get `Interrupted: 3 errors during collection` — no reading at all, wearing
the costume of a suite you just broke. That happened here on the run immediately before this
one. It is the same rootdir behaviour documented for `apps/remix` further down, and it bites
the whole suite, not just that corner.

The 14 over the reading below it are one file and are the whole delta: **+14**
`apps/test_governor_drain.py`, landed whole at `2dfd1af` with R-171's drain-floor fix.
1722 + 14 = 1736.

**#99 landed in this range as well and moved the count by nothing, and that is the most
instructive zero in this file.** Everything it added is a browser assertion in
`tests/studio.mjs` — five of them — and pytest never sees that file. The surface those five
gate went from **4% of the first viewport to 55%**, which is to say the most important test
written this week is invisible to the number at the top of this section. Do not read a flat
count as a quiet week.

The previous reading was **1722 pass, 0 fail and 14 skip at `4d0d812`**, measured 2026-08-21
from `backend/` in 123.84 s with `--collect-only` collecting 1736 in 1.31 s, and `apps/remix`
28/28 in 0.46 s.

The 54 over the reading below it are attributable in full and split two ways: **+52**
`apps/studio/test_cleanroom.py`, landed whole at `23f2f64` with #97's spec-mediated
reimplementation pipeline, and **+2** `apps/test_deploy_routes.py` (4 → 6 at `1e54a42`, the
exemption for `/livestack/live` and the assertion that should have caught its absence).
52 + 2 = 54, and 1668 + 54 = 1722. `apps/studio/test_studio.py` was also edited in this range —
a fifth group in `EXPECTED_TOOLS`, a fifth in `EXPECTED_GROUPS`, and `7 · 7 · 6 · 6` becoming
`7 · 7 · 6 · 6 · 2` — and moved the count by nothing, which is the usual case.

Three of the 52 are the ones worth knowing about, because they were written *after* the module
already passed everything else: `TheProvenanceBuiltByARealExtractionTests` exists because every
licence test called the helper functions directly, so `license_determined=bool(licence)`
returning a hardcoded `True` from the *builder* was invisible — one of seven deliberate breaks
stayed green. Tested branch is not shipped branch. See `backend/apps/studio/SMOKE-cleanroom.md`.

The previous reading was **1668 pass, 0 fail and 14 skip at `1224bf1`**, measured 2026-08-21
from `backend/` in 124.34 s with `--collect-only` collecting 1682 in 1.24 s, and `apps/remix`
28/28 in 0.43 s.

The 43 over the reading below that are one file, and the four files that added none of them are
the more useful half of the delta: **+43** `apps/live/tests/test_live.py`, landed whole with #96's `apps/live`. 1625 + 43 =
1668. `apps/test_status_rack.py`, `apps/test_roster.py`, `apps/test_enable_surfaces.py` and
`apps/test_studio_models.py` were all edited in this range — a fourteenth `EXPECTED` row, `13`
→ `14` on the router count, `20` → `21` rack slots, `LIVE` added to two literals and a method
renamed `..._known_seven` → `..._known_eight` — and they moved the count by **nothing**. Four
files changed, zero tests added, and the rack roster now describes a surface it did not know
existed. That is the whole argument for why a count is a weak signal on its own: every red test
that caught `apps/live` landing unbookkept was red while the total moved by nothing they did.

The previous reading was **1625 pass, 0 fail and 14 skip at `79d139b`**, measured 2026-08-21
from `backend/` in 122.50 s with `--collect-only` collecting 1639, and `apps/remix` 28/28 in
0.43 s.

The 13 over the reading below it are attributable in full, counted per file rather than
inferred from the total: **+5** `apps/studio/test_comfy_port.py` (4 → 9,
`TheEditorMountAndItsCookieAgreeTests` at `79d139b` — the editor's mount prefix and its
session-cookie path read off `api.py` and `gate.py` and compared, because a rename that moves
one and not the other breaks the framed editor with nothing in any log to read), **+3**
`apps/test_build_progress.py` (25 → 28, `AResolveIsEvidenceNotAVerdict` at `8c70d9b`), **+4**
`apps/test_desktop_client.py` (32 → 36 at `f1e8e51`), **+1** `apps/test_brand_boundary.py`
(12 → 13 at `e2da088`). 5 + 3 + 4 + 1 = 13. `apps/test_governor_paths.py` and
`apps/studio/test_studio.py` were both edited in this range and moved the count by nothing —
the first had its retired-path list and launcher names updated, the second had a URL literal
changed. That is the usual case and the reason a count is a weak signal on its own.

The previous reading was **1612 pass, 0 fail and 14 skip at `7079933`**, measured 2026-08-21
in 124.13 s with `--collect-only` collecting 1626, and `apps/remix` 28/28 in 0.42 s.

The 32 over the reading below it are one file: `apps/test_desktop_client.py`, landed whole by
`7079933` with #94's client. 1580 + 32 = 1612. Three of those 32 were written *after* the
client had already been declared finished by its checks, and are the more useful part of the
delta: `TheCapabilityGrantsExactlyWhatThePageUsesTests` exists because Tauri v2 gates its core
plugins, the client shipped with no `capabilities/` directory, and so chat rendered its turn
and then silently received nothing while every check on the task read green. See
`desktop-client/SMOKE.md`.

The reading before that was **1580 pass, 0 fail and 14 skip at `87c4042`**, measured
2026-08-21 in 122.01 s with `--collect-only` collecting 1594, and `apps/remix` 28/28 in 0.41 s.

The 16 over the reading below it are attributable in full, which is the second time running and
still not what to expect: 9 are `apps/test_api_reference.py`, new at `ad9b9fa`; 4 are
`apps/test_weight_names.py` going 10 → 14 at `f3ed5ab`; 3 are `apps/test_brand_boundary.py`
going 9 → 12 at `6542932`. 9 + 4 + 3 = 16. `5299200` is the fourth commit in that range to
touch a test file and it moved the count by nothing — it rewrote `WindowSmokeTests` to wait on
the shell instead of on a stopwatch, which is a fix to *what* 15 tests assert, not to how many
there are. That distinction is why a count is a weak signal on its own.

The reading before that was **1564 pass, 0 fail and 14 skip at `0d51b09`** in 127.85 s with
`--collect-only` collecting 1578; the 9 over the one below it were all
`apps/test_brand_boundary.py`, landed by that commit as #74 item 7.

The reading before that was **1555 pass, 0 fail and 14 skip at `2f97a3b`**, measured
2026-08-21 in 126.41 s with `--collect-only` collecting 1569.

The reading before it was **1526 pass, 0 fail, 14 skip at `c847b64`** in 126.78 s, and for once
the whole jump is accounted for rather than estimated: 21 are `apps/capture/test_capture.py`
(`1ec7cbe`), 4 are `apps/test_caddy_delegation.py` (`e5ca567`) and 4 are
`apps/test_deploy_routes.py` (`180cb60`) — 29 exactly, which is 1555 − 1526. That is unusual and
you should not expect it; the paragraphs below exist because most deltas span many commits and
cannot be attributed this way.

**The suite is green, and the three deliberate failures that stood here are gone for the right
reason.** This paragraph said for two days that `apps/test_rack_probes.py` fails three times
because `api.py` probes `contrib/llama.cpp` and `contrib/stable-diffusion.cpp`, which are not on
disk — Garrett having moved the engines to `references/`, and *"we cannot use code in
references its for reference only we must rebrand if we want to use it"*. That was true and it
is no longer: `d6b7838` forked both engines under our own names and repointed every consumer,
which is #74's work, so the probes now find what they look for and all five pass. **Nothing was
repointed at `references/` to make them green** — that was and remains barred. If those three go
red again, read them: red there means chat and image are offline, and it is the honest signal.

The published figure before this one was **1376 pass, 3 fail, 12 skip at `0c0f969`**. It is
left here rather than overwritten because the difference is instructive and not a mystery: of
the 149 between the two collections, three are the rack probes turning green, thirteen landed
with #73's four retired checks (`ComfyPortAgreementTests` 4, `PluginRowsMatchRosterTests` 4,
`RowCoverageTests` 5, plus 2 more skips for the live half of `test_server_ready.py`, which is
why the skip count moved 12 → 14), and the rest arrived across the commits between. As
everywhere else in this file: a count moves when tests land, not when a task closes.

**Note the `--ignore` paths changed at `0c0f969` and the old ones matched nothing.** They were
`apps/reinforce/tests` and `apps/remix/tests`; reinforce is now a studio plugin, so the first is
`apps/studio/plugins/reinforce/tests`. A stale `--ignore` is silent — pytest does not warn that
a path you excluded does not exist — so it stops excluding and you get a collection error
instead of a count. The ladder behind the figure, each read on the tree it names: **1085 at
`df1d862`**, **1093 at `e81ffa4`**, **1200 at `74dee33`**, **1229 at `d3a4040`**, **1391 at
`0c0f969`**, **1540 at `c847b64`**, **1569 at `2f97a3b`**, **1578 at `0d51b09`**, **1594 at
`87c4042`**, **1626 at `7079933`**, **1639 at `79d139b`**, **1682 at `1224bf1`**, **1736 at
`4d0d812`**, **1750 at `594efac`**, then a hole -- `49185b8` through `48dcaaf` collect **nothing** (no rung may be invented for them; `ce4fb27c` closed it by landing the ravencalc repair), then **1832 at `ca0571b7`** (2026-08-22). The pre-repair sentence stands: `49185b8` onward collects
**nothing**, so there is no rung for `f63dd3e`, `95e02c5` or `48dcaaf` and none may be
invented for them. Do not attribute a jump to one task from these numbers
alone: the 107 between `e81ffa4` and `74dee33` spans **25 commits** across most of two days'
work, while the 29 from `74dee33` to `d3a4040` is a single commit. A count moves when tests
land, not when a task closes. `df1d862` read 110.38 s then 111.55 s on that tree: two readings
of one tree, so treat the wall time as a range and the count as the reading. The count drifts
upward as apps land — it was 682, then 941, then 973, then 981, then 1084, then 1085 — so treat
the absolute number as a date-stamped reading, not a contract, and put a commit SHA beside it. A
published 1063 turned out never to have been true of the commit it sat beside: the tree it named
collects 1084, so the figure was carried forward from an earlier one. A number with no SHA
cannot be checked, only believed. `--collect-only` should report the same figure; that
comparison is what catches a collection abort, which is not a smaller number but no number at
all. Without them pytest stops at *collection* — `Interrupted: 2 errors`, zero tests run, which
reads exactly like you broke the suite.

`apps/studio/plugins/reinforce/tests` imports `cupy`, which is not installed on the **system**
interpreter and may not be, since that is the serving path (see *Python environments*). That one
is a genuine per-project suite with a genuine environment problem, and it stays excluded.

**`apps/remix/tests` is excluded for an entirely different reason, and the reason this file gave
until 2026-08-21 was wrong.** It said the suite imports `symon_capture` and that the module is
not installed. There is no such module anywhere on disk any more: `apps/remix/symoneural_dj/app.py:30`
imports `from apps.capture import CaptureStore`, which resolves perfectly well from `backend/`.
What actually breaks is **configuration, not environment**. `apps/remix/pyproject.toml:44` sets
`pythonpath = [".", "../.."]`, and pytest applies a `[tool.pytest.ini_options]` block only from
the directory it selects as **rootdir**. Run `pytest apps/` and rootdir is not `apps/remix`, so
that `pythonpath` is never added, `symoneural_dj` is unimportable, and you get one collection
error and zero tests. The `--ignore` is therefore still required for the `apps/` invocation — but
the suite is not dead, needs no venv, and runs on the system interpreter:

```bash
cd backend/apps/remix && python3 -m pytest -q     # 28 passed in 0.43 s
```

**28/28, measured 2026-08-21 at `0d51b09`.** Those 28 are not inside the 1578 and never have
been, so the tree really carries **1592 tests across two invocations**, not 1578 across one. Run
both before claiming the backend is green. The lesson generalises past this suite: an exclusion
outlives the reason it was added, and *"it needs its own environment"* is the most comfortable
reason to leave sitting there, because it reads as a policy decision rather than as a bug nobody
re-checked. Re-check the reason, not just the count.

The 162 between `d3a4040` and `0c0f969` is **not 162 new tests**, and reading it that way is
the mistake the paragraph above warns about. `d3a4040` was a healthy tree that genuinely
collected and ran 1229. What happened between the two is the 104-file restructure, and for
several commits in the middle the suite was **899 collected with 10 collection errors — zero
tests run**, which is neither 1229 nor 1391 but no reading at all. `0c0f969` repaired the
imports, and the 1391 is the same tests plus the ones that were never reachable from `apps/`
before the move. So the ladder has a hole in it, on purpose: there is no honest figure for the
trees in between, because a collection error is not a smaller number but no number.

**`frontend.mjs` was 49/49 at `d3a4040`, measured 2026-08-20 against
`http://127.0.0.1:8879`; it was 43/43 at `e81ffa4`, and the rack red that stood here is fixed.
It has NOT been re-read since `0c0f969` and that figure is deliberately in the past tense.**
`0c0f969` moved 104 files under `backend/apps`, and this suite asserts on what `/api/status`
renders, so its tree is not the tree the 49/49 was read on. Two of its assertions are also
known to be affected: the image assertion needs a working render engine, and chat and image are
offline (see the three red probes above). Re-run it and stamp the reading rather than believing
this one — that is the rule this file states everywhere else, and it applies to its own
figures first.
Always on a spare port, never the service — that is the only honest way to run it, see below.
The rack red, for the record: `#rack` on
`/livestack` overflowed its one-screen budget at 1855x745 — `scrollHeight` 599 against
`clientHeight` 584 — because `site/index.html` renders the rack client-side from `/api/status`
and the rack went from eleven units to thirteen when `studio` and `exp` landed (`e27b9c1`).
Nothing in any page source regressed. Two spacing rules closed it, both in the `html.ns` block
of `site/symoneural.css`: the rack note's measure (96ch → 160ch, three line boxes → two) and
the `.rk-fold` pill moved out of the heading's inline run onto the `.shead` row, which was a
whole line box on its own. No word, row or type token changed. **Measure slack with a cloned
`.unit`, not with `scrollHeight`** — it floors at `clientHeight`, so `584/584` says "fits" and
nothing about by how much, and three of the four in-gate viewports read `over=0` before the fix
as well. By that method fourteen units now fit everywhere and fifteen only at 1990x970; the
binding viewport is **1301x740**, not 1855x745, because its rows are 26.6px. `.claude/HANDOVER.md`
§0 has the full table, the retraction of the two-column option it used to recommend, and the one
lever deliberately left unspent. Do not close the next overflow by dropping a row or adding
`text-overflow` — both are barred above. The other two suites are green on the same tree:
`streamer_failpaths.mjs` **32/32** and `streamer_watch.mjs` **8/8**, **re-measured
2026-08-20 at `f6ed7d3` under the names above, which are the names that exist** — so unlike the
49/49 these two are not in the past tense and you can rely on them. They had also read
**32/32 and 8/8 at `e81ffa4`**, the same tree as the 43/43 above, which is what "same tree" has
to mean to be worth writing; that earlier pair was measured while the files were still called
`tuner_failpaths.mjs` and `tuner_watch.mjs`, and it keeps the SHA it was read on rather than
being re-dated to the rename (#73 item 2, Garrett *"i said tuner and guide needed to be merged
and migrated to streamer"*). Both readings are written out rather than one replacing the other
because a rename is exactly the change that can move a file without moving what it references —
so two identical readings, each stamped on the tree it was taken from, is the evidence that
nothing came loose. This paragraph named the old files for a while after they were gone, which
is worse than a stale count: a stale count can be checked, and `node tests/tuner_watch.mjs`
cannot run at all.

System Chrome via Playwright, nothing to download. The failpaths and watch suites need no API
and no provider account: each starts `tests/streamer_fake_provider.py` and stops it again, so the
whole invocation is the one line. **`frontend.mjs` needs an API**, and if you point it at the running
service you are testing what is *deployed*, not what you wrote — start your own on a spare port
and pass the base URL (`node tests/frontend.mjs http://127.0.0.1:8875`), or a red assertion will
send you hunting a bug you already fixed.

**`tests/studio.mjs` is the fourth suite and is deliberately not part of `frontend.mjs`.** That
one runs against any instance and asserts what every visitor sees; this one needs the Studio
surface switched on and it **takes the card for a real render**, so pointing it at the deployed
service would queue a job on the live GPU. Start the render UI and your own API, then run it:

```bash
bash scripts/symoneural-ui.sh start                       # loopback :8188, no lock held
cd backend && SYMONEURAL_STUDIO_ENABLED=1 SYMONEURAL_STUDIO_TOKEN=devtest \
    python3 -m uvicorn server:app --port 8876          # a spare port, not the service
SYMONEURAL_STUDIO_TOKEN=devtest node tests/studio.mjs http://127.0.0.1:8876
bash scripts/symoneural-ui.sh stop                        # /free, THEN SIGTERM -- see below
```

**21/21 passed, measured 2026-08-21 at `594efac`**, including a 1024x1024 FLUX-schnell render
decoding in the browser in 11.4 s (10.3 s server-side, lock released). It was **16/16** and had
been unread since `0c0f969`; five assertions landed with #99, and **two of the sixteen were red
on the first honest run of them, neither for a reason the page had caused**:

- **`26 tools` was stale.** `23f2f64` added `extract_spec` and `generate_native_code` (group
  `cleanroom`), updated `apps/studio/test_studio.py`'s `EXPECTED_TOOLS`, and never touched
  `tests/studio.mjs` — so this suite reported two failures for work that was correct. It is 28
  in both places now, and when you add a tool both move in the same commit.
- **`the render decoded in the browser` was racy**, which is worse than absent for that
  particular assertion. It waited on `waitForSelector('#st-shots img')`, which returns the
  moment `page.js` sets `src`, before a byte of the PNG has arrived; `naturalWidth` is 0 until
  it decodes, so a good render read `0x0`. Confirmed from the other end at the same moment:
  `curl` on `/api/studio/image?...` answered `200 image/png content-length: 996780`. It waits on
  `complete && naturalWidth > 0` now. The assertion exists because a render once succeeded
  server-side and still showed as a broken image to every visitor, so it has to go red for that
  and for nothing else.

**The lesson is the one #94 taught, arriving from the other side.** Every check on the Studio
task was green, this suite was 16/16, and the editor all of it was about had never been seen by
the person who asked for it: the frame was the fourth block down the page under
`height:min(78vh,760px)`, which at 1440x1000 put its top at y=962 — 38px of 1000 visible, 4%.
The suite now measures the frame's area inside the **first viewport**, not its height, because
`min(78vh,760px)` is 76% of a 1000px viewport and a height assertion would have passed
throughout. `backend/apps/studio/SMOKE-bench.md` has the three-viewport table and the deliberate
break.

The 16/16 that stood at `d3a4040`, `1537262` and `d20e09b` is kept in the ladder above rather
than overwritten: each was re-run rather than re-dated because `backend/server.py` had changed
underneath it, and studio.mjs runs against `api.py`. Its three `net::ERR_ABORTED` lines are
labelled optional and 404 upstream at :8188 as well; they are not proxy faults, and #99 checked
three more of the same class (`api/userdata?dir=workflows`, `?dir=subgraphs`,
`workflows%2F.index.json`) against :8188 directly and found the proxy faithful on every one.
`.claude/HANDOVER.md` has the reading and the VRAM curve.

**Run this suite and `frontend.mjs` one after the other, never at once.** Both take the card,
and `frontend.mjs`'s image assertion evicted ComfyUI out from under a studio render here — the
lease is released before the browser fetches the PNG, and evicting `comfy` stops the *process*
that serves it, so the render 503s as `comfyui_unreachable`. That reads as a studio bug and is
not one. `.claude/HANDOVER.md` §0a-quater has the governor log and the underlying defect, which
is real for a visitor too. The state document claimed for two days that this suite could not run
because ComfyUI "has no venv and no torch" — it has both (torch **2.13.0+cu130**, sm_120
verified by a real CUDA probe, 223 packages), and the suite had simply never been invoked.

**Stop the render UI with `scripts/symoneural-ui.sh stop`, never by killing the pid.** The script POSTs
`/free` and then waits on `gpu-governor.sh drain` — the process exiting is not the memory coming
back, and the next tenant OOMs at step 0. Measured here: a render peaks at **13,114 MiB of
16,303** and returns to 666 MiB in **4.1 s**, against the governor's 60 s timeout. That 666 MiB
is a live ComfyUI holding no weights, and it is the reason `DRAIN_FLOOR_MIB` is 1024 and not
lower: the floor has to sit above a correctly-freed engine's own idle context.

`symoneural-ui.sh` deliberately does **not** hold the lock for its process lifetime; the lease
is taken per render and released after the drain, which is the rule above applied.

**`tests/streamer_guide.mjs` is the fifth suite, and it was dead for a fortnight because
nothing in this file told anyone to run it.** It needs no GPU, no provider account and no
running service — it starts its own uvicorn carrying just the two streamer routers — so there is
no reason to skip it. **17/17 passed, measured 2026-08-20 at `7a5ced5`**, including that the
grid re-ticks to exactly the groups Guide returned, that *both* adult groups are found rather
than only the first, and that nothing overflows at 1440/1301/390px. Its failure mode is the one
worth knowing: it generates its own `app.py`, so a stale import there kills uvicorn before it
binds and Chrome reports `ERR_CONNECTION_REFUSED` twenty-four seconds later. That reads as an
infrastructure fault and is not one — it is this repo's own restructure, unpropagated. It had
been importing `from guide import routes` against a directory that is now
`backend/apps/streamer/guide/`, and mounting at `/api/guide` while the page fetches
`/api/streamer/guide/filter`. Two faults, the second hidden behind the first.

**`tests/project.mjs` is the sixth suite, it needs no GPU and no provider account, and it
was red for a fortnight for a reason that had nothing to do with the page it tests.** The
surface is off unless `SYMONEURAL_PROJECT_ENABLED` and `SYMONEURAL_PROJECT_TOKEN` are set, so
it brings its own harness with a throwaway store and a token that is deliberately not a secret:

```bash
python3 tests/project-harness.py &      # 127.0.0.1:8899, fresh temp store every start
node tests/project.mjs                  # or pass a base URL
kill %1
```

**16/16 passed, measured 2026-08-20 at `fdb21b0`.** It was **15/16** immediately before that,
and the red is the part worth reading, because it is the failure mode of every single-app
harness in this repo: `site/ui.js` fetches `/api/news/ticker` on **every** page load — the
ticker is shared page chrome, not a news-page feature — and the harness mounted only the
project router, so the browser logged a 404 and the *"no uncaught JavaScript errors"* assertion
went red for something this page does not own. `apps/news/routes.py` is explicit that the
endpoint is safe to expose in exactly that situation: it never triggers a fetch (the background
refresher owns the rate), it carries no token because everything it returns is already public,
and it answers 200 with an empty bar rather than 503 when the surface is off — and its stated
reason for that last one is *this same* red-line-in-the-console argument, aimed at a visitor
instead of a test. So the harness mounts it now, which reproduces the production shape rather
than papering over a gap. **If you write a harness, mount news in it.**

**`tests/live.mjs` is the seventh suite, it takes nothing — no GPU, no OBS, no provider
account, no token — and it had never been executed once before 2026-08-21.** Not "was red",
not "was skipped": `node` could not load it. Line 17 read
`import { dirname, fileURLToPath } from 'node:url'` and `node:url` exports neither name, so
the module failed to instantiate with a SyntaxError before a single assertion ran, and both
imported names were unused anywhere else in the file. It landed in `14814e9` beside the code
it was written to gate. A test file on disk satisfies `exists`, satisfies `grep`, and reads
to a human exactly like a suite — and says nothing at all about whether it has ever run.
That is #94's shape arriving from a new direction, and it is the reason this list exists and
the reason `apps/test_streamer_migration.py` fails when a `tests/*.mjs` file is not named
here.

```bash
python3 tests/live-harness.py &      # 127.0.0.1:8897, throwaway store, no OBS, no GPU
node tests/live.mjs                  # or pass a base URL
kill %1
```

**21/21 passed, measured 2026-08-21 at `a616168`.** The assertion it exists for is `video
decodes`: a `<video>` with an HLS URL behind it satisfies every DOM check anybody would think
to write while playing nothing, so the suite asserts `readyState >= 3`, that `videoWidth` and
`videoHeight` are the fixture's own `320x180`, and that `currentTime` advances — read
`readyState=4`, `320x180`, `4.67 -> 5.87`. Only real decoded video produces those three.
`tests/fixtures/live/` is six seconds of real MPEG-TS for the same reason: a hand-written
`.m3u8` pointing at empty files would go green.

**Start the harness immediately before the suite, and do not "fix" a timeout by widening
`hls.LIVE_WINDOW_S`.** `live-harness.py` builds its store at *import*, so the live session's
mtime is frozen at harness start; the window is 20 s, and after that `hls.scan()` correctly
reclassifies that session `abandoned`, `#lv-player` stays hidden and the run times out on its
third assertion. That is the classifier working. The harness carries a comment saying so, and
this is the second place it is written down because the misdiagnosis is so much cheaper than
the diagnosis: nothing in the console, no failed request, no HTTP >= 400 — the page simply
and correctly reports that nothing is being recorded.

It also asserts the trap that `site/streamer.html:1989` measured: Chrome returns the **truthy
string** `'maybe'` from `canPlayType('application/vnd.apple.mpegurl')` and then plays nothing,
so `if (canPlayType(...)) native;` takes a branch that cannot work. hls.js goes first
everywhere and native only where hls.js will not run, which is Safari. Asserting the
measurement means a future Chrome changing it is a red line here rather than folklore rotting
in two comments.

**The Studio agent loop does not stream tokens, so do not quote a first-token latency for
it.** `inference.Backend.chat` sends `"stream": False` and is the loop's only call site;
`Backend.stream()` is unexercised and says so. The loop's granularity is SSE *events*. Measured
2026-08-19 over six turns, warm: the `backend` probe frame lands in **0.015-0.022 s**, the first
frame carrying model output in **0.2 s warm / 1.06 s cold** (the cold penalty is `--no-warmup`
plus first processing of the 26 rendered tool specs), and a whole turn takes **0.53 s** with no
tool, **1.0-1.9 s** with one, **3.1 s** with three. Native tool calling works on this build --
no `notice` downgrade in any turn, and turn 6 returned three tools from one message.

**To measure it, warm the engine through the chat surface, never by spawning llama-server.**
`inference.py` probes and never spawns, because `api.py` owns that process inside
`gpu.hold("chat")` and a second spawner would race it for :8081 and the lease:
```bash
curl -sS -X POST http://127.0.0.1:8800/api/chat -H 'Content-Type: application/json' \
    -d '{"prompt":"ready","max_tokens":8}'   # ~7.1 s of that is spawn + weight load
ss -lntp | grep 8081                            # confirm it stayed resident; chat does not stop it
```
llama-server then holds **~8.1 GiB** and stays up, while `gpu-governor.sh` reads `lock free` --
**the agent loop takes no lease.** Only `api.py` can stop it (shutdown, or an image render at
`api.py:2052`), so expect to leave it resident; that is this box's warm state, not a leak.

These assert on what the DOM *shows*: units render from `/api/status`, the bus plate carries a
real reading, nothing overlaps at 390px, calc returns `x**3/3`, and a generated image actually
decodes. That last assertion exists because a render once succeeded server-side and still
showed as a broken image for every visitor — curl proved the endpoint answered, which was never
in doubt. Add an assertion here whenever you fix a frontend bug.

**Read computed styles rather than reasoning about the cascade.** Three separate bugs have now
come from generic class names colliding across components: `.bar` (collapsed the site header to
7px sitewide), `.live` (the nav badge styling the control board legend), and `#console .sub`
(a section rule outranking `.mod .sub`, rendering a footnote larger than the sentence above it).
Render the page and measure.


## `tests/responsive.mjs` — the layout suite, and the one check a clip cannot fake

```bash
node tests/responsive.mjs            # or pass a base URL; needs the API on :8800
```

**24 pages × 8 viewports = 192 combinations, 0 findings, measured 2026-08-26 at `9b3d1166`
on `127.0.0.1:8800`.** It was **78** when the suite was first run that morning — 47 overflow
and 31 unreachable — and `docs/ops/SMOKE-FRONTEND.md` is the record it writes, regenerated on
every run. Do not hand-edit that file; a hand-edited reading is worth nothing.

Widths 360, 390, 430, 768, 1024, 1440, 1920, plus 1440×700 for a short window.

**Why it does not simply check `scrollWidth`.** The defect it was written for was invisible to
one. At 360px the header's "Have one built" button laid out at left=336 inside a bar that set
`overflow-x:hidden` and clipped at 328: the document never scrolled sideways, so
`documentElement.scrollWidth` read exactly 360, `frontend.mjs` passed, and the button sat
outside the viewport on fourteen pages. So three things are measured instead — `scrollWidth`,
every visible element's right edge *including clipped ones*, and whether `elementFromPoint` at
a control's own centre returns that control. The third is the part a clip cannot fake.

**It distinguishes a scroll container from a clip, and the difference is the whole point.** An
element past the right edge inside an `overflow-x:auto` ancestor is reachable by dragging it and
is not reported; the same element inside an `overflow:hidden` ancestor is gone and is. Without
that distinction the suite reported `#reinforce .rf-scroll`'s seven tables, which work
correctly — and a check that calls working code broken stops being read.

`streamer-watch.html` and `share-dispatchos.html` are deliberately **not** in its page list:
the first is a bare player with no chrome by design (`build_pages.py:watch_page()` says so) and
the second is a credential-gated customer preview that must not carry site navigation. Both were
verified live and required on 2026-08-26 before being excluded — see
`docs/ops/AUDIT-FRONTEND-2026-08-26.md`.

## `tests/chat_smoke.mjs` — Chat exercised, not inspected

```bash
node tests/chat_smoke.mjs            # or pass a base URL; TAKES THE CARD
```

**46/46 passed, measured 2026-08-26 at `a5a30f1a`+working tree on `127.0.0.1:8800`**, at 1440×900
and 390×844. Read `5 tokens in 0.22s · 22.5 tok/s measured on the card` off the status line and
`SymonChat S1-7B` off the model indicator on both.

It exists because of #94, which `.claude/CLAUDE.md` records at length: eighteen green checks on a
chat surface that was dead on arrival, rendering one turn and then nothing with no error to read,
archived by the timer two minutes later. Existence assertions are what #94 had. This types into
the composer, presses Enter, waits for the 7B to stream back, and asserts the log grew and the
status line printed a measured rate — then opens a new conversation, reloads, and asserts the
history survived. Also covered: Shift+Enter makes a newline and the textarea grows with it
(28→52px desktop, 27→50px phone), the empty state clears on submit, and no page raised a
JavaScript error.

**Run it alone.** Like `studio.mjs` and `frontend.mjs` it takes the GPU, and the governor hands
the card to one surface at a time — a concurrent run evicts the other's model out from under it.
