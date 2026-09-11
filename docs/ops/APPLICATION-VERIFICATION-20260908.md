# Application verification — 2026-09-08

Every declared surface, checked against what the box actually does. Measured with
`tools/probe_apps.py` at HEAD `cf3fa6b1`, 22 surfaces, 155 routes, 105 OpenAPI paths,
124 boundary probes, 44 latency samples. Suite at the same HEAD: **2333 passed, 0 failed**.

The vocabulary is the repo's own: **DEFINED** (named, no implementation claim) ·
**PRESENT** (code exists) · **WIRED** (connected into the running system) ·
**VERIFIED** (observed working this pass).

## Verdict

**19 of 22 surfaces are WIRED and answering.** Three are `offline` by configuration and say
so precisely. **Six declared-versus-enforced defects** stand, four of them in what the
documentation tells a visitor. Nothing found here is a crash or a broken route; every one is
a **claim that does not match the machine**, which is the failure class this project keeps
paying for.

## 1. The six defects

| # | Surface | Declared | Enforced |
|---|---|---|---|
| 1 | `coder` + `/local/*` | — | **9 routes documented nowhere.** The registry's totality test is scoped to `/api/*`, so they *escaped* it rather than failed it |
| 2 | `controlboard` | `GET /api/rack/power` returns 404 to conceal that the control exists | `/api/rack/power/{unit_id}` answers **422 and names its required field** before any gate is consulted. The gate holds; the module's own 404-rather-than-403 argument does not |
| 3 | platform-wide | `_require_local` refuses anything that crossed the proxy | checks 3 header names, **misses `Forwarded` (RFC 7239), `Via`, `X-Forwarded-Proto`** — all three served on all 6 probed `/local/*` routes. The peer check still holds; the secondary defence is incomplete |
| 4 | `chat`, `remix`, `image`, `ravencalc` | published per-surface rate limits — chat 120/min and 3,000/hour | **not enforced.** pid 1507 has **zero** `SYMONEURAL_RATE_*` vars, so `_rate_for` returns `(0, 0)` — no bucket at all. 150 consecutive `ravencalc` posts in 1.64 s produced **no 429** |
| 5 | `project` | *"public read, write on the same surface"* | all 3 parameterless GETs answer **401 `bad or missing X-Symoneural-Token`**. `appdocs.py` renders `/docs/project`, so that page is telling visitors a credentialled surface is open |
| 6 | `train` | rack reports **`ready`** | all 4 parameterless GETs answer **503**: *"SyMoNeuRaL Reinforce is off"*. Its sibling `studio` reports `offline` with a reason, so the rack **can** express this and does not here |

Items 4 and 5 are the ones with an audience. A published throughput figure nobody enforces
and a docs page calling a credentialled surface public are both read by people outside this
box.

## 2. Documentation that does not match the code

**Two surfaces name the wrong runtime**, and both were found by reading the registry against
the source rather than by anything failing:

| Surface | `appdocs.py` declares | Actually executes |
|---|---|---|
| `voice` | `symoneural-llm` | **`symoneural-listen`** — `voice/asr.py:64` builds that path, and its own docstring describes the whisper CPU build |
| `image`, `sigils` | `symoneural-image-engine` | **`symoneural-diffuse`** — `sigils/render.py:73`. `symoneural-image-engine` exists nowhere: no folder, no component-map row |

**Thirteen of 22 surfaces name a runtime with no component of that name.**
`symoneural-image-engine`, `symoneural-ravencalc`, `symoneural-project`,
`symoneural-studio`, `symoneural-live` have neither a directory nor a `COMPONENT-MAP.tsv`
row. Most are *logical* labels for in-process application modules, which is a defensible
thing to record — but the field is currently a mix of real runtime names and logical ones
with nothing distinguishing them, so `voice → symoneural-llm` reads exactly like
`live → symoneural-live` while one is wrong and the other is shorthand.

**Three real components are missing from `COMPONENT-MAP.tsv`:** `symoneural-listen` and
`symoneural-miner` are both **built and on disk** (verified: `SyMoNeuRaL Miner 1.2.4`), and
`symoneural-audit` is new this session. The map has 14 rows and includes `symoneural-llm-cli`
and `symoneural-buildv2`, so granularity is not the reason they are absent.

## 3. What is offline, and whether it says why

All five offline states name their own remedy, which is the right behaviour:

| Surface | Reason given |
|---|---|
| `miner`, `gpuminer` | disabled — `miner.env` not created from the example |
| `asicminer` | disabled — needs `SYMONEURAL_ASIC_ENABLED=1` (*"the literal string 1, not true"*) |
| `gateway` | not configured — needs enable, network and wallet settings |
| `studio` | ComfyUI not answering at `127.0.0.1:8188`; *"nothing starts it at boot"* |

**One rack disagreement:** `studio` is reported `offline` while **2 of its 6 serving routes
answer**. Partly-up reported as down is the safer direction, but it is still the rack
disagreeing with the routes.

**Two routes return 404 by design**, both documented at the line: `/api/live/now` (*"404 when
nothing is live, which is the normal state and not an error"*) and `/api/rack/power` (see
defect 2).

## 4. A defect this verification found in my own work

Nine Python files — including **`backend/api.py`, the live service** — and two shell scripts
still resolved engines through the old path, spelled as separate components:

```python
ROOT / "engines" / "symoneural-llm" / "build" / "bin" / "symoneural-llm"
```

The 2026-09-08 promotion sweep replaced the *string* `engines/symoneural-` and never saw
this form. Everything kept working, which is the problem: it worked through the five
compatibility symlinks in `engines/`, so those shims had quietly become **load-bearing**
instead of transitional. Deleting them would have broken chat, image, sigils, the miner
binary lookup, ASR and the reinforce rollout simultaneously.

Fixed and verified by moving `engines/` aside entirely: all four built binaries still
resolve, `api.py` still parses, 29 of 30 governor/probe/rack tests pass. The single failure
was the live rack disagreeing with disk — expected, since pid 1507 runs the pre-fix code in
memory. **The shims are now genuinely removable, once `symoneural-api` is restarted.**

## 5. What was NOT verified, stated plainly

- **No authenticated path was exercised.** `dispatchos` (15 routes, session cookie),
  `accounts` (8 routes) and `project`'s write side were probed unauthenticated only. Their
  auth *boundaries* were checked; their *behaviour behind* the boundary was not.
- **`train` and `studio` were not enabled** to test them. Enabling either takes the GPU and
  writes to the host, which is a mutation, not an audit.
- **`voice` end-to-end was not run** — no audio was submitted. The engine path is fixed and
  the binary is reachable; a real transcription was not performed this pass.
- **`guide`, `platform`, `controlboard` have no rack row**, so no rack state to compare.

## To act on

Ordered by who is affected first:

1. **`project`'s docs page says public and enforces 401** — a visitor reads that.
2. **Published rate limits are not enforced** — the figures are on the front page.
3. **`train` reports ready and answers 503** — the rack is the thing operators trust.
4. Complete `_require_local`'s header list with `Forwarded`, `Via`, `X-Forwarded-Proto`.
5. Bring the 9 `/local/*` routes into the registry, and widen its totality test past `/api/*`.
6. Fix `voice → symoneural-listen` and `image/sigils → symoneural-diffuse`; separate real
   runtime names from logical labels in the registry.
7. Add `symoneural-listen`, `symoneural-miner`, `symoneural-audit` to `COMPONENT-MAP.tsv`.
8. Restart `symoneural-api`, then delete the `engines/` and `bin/` shims.
