# SyMoNeuRaL Live Stack — the observable rack, and why every chip must be a reading

**Scope captured 2026-08-22.** Docs and scope only. **No implementation, no folder migration,
no rack-assembly rewrite, no deploy.**

## What it is, and what it is not

> **Live Stack is the observable system/rack surface.** It shows the current rack units and
> reads real status.

It is **not** a marketing grid · a decorative dashboard · a duplicate source of truth · a
stale hand-maintained inventory.

**Live Stack is not the same thing as SyMoNeuRaL Live.** Live is one unit *on* the rack — the
live/media/OBS/HLS surface. Live Stack is the rack. Two different objects that share five
letters, and conflating them is how a fold loses a surface.

## 1. Identity lives in one file, and state in another

The split already exists on disk and it is the reason this surface does not drift:

| Concern | Source |
|---|---|
| **identity** — what the row is, where it points | `backend/apps/ROSTER.md` (+ `roster.py`) |
| **state** — is it ready, offline, queued | `/api/status`, which *measures* it |

`ROSTER.md:15` states it directly: *"This file carries identity only."* **A row's LED is never
written down.** That is the structural guarantee against a decorative dashboard, and it must
survive any migration.

## 2. The thirteen units, measured from `ROSTER.md`

| id | label | slot | bus | href |
|---|---|---|---|---|
| `chat` | SyMoNeuRaL Chat | 1U | gpu | `/chat.html` |
| `image` | SyMoNeuRaL Image | 2U | gpu | `/image.html` |
| `remix` | SyMoNeuRaL Remix | 1U | gpu | `/remix.html` |
| `ravencalc` | SyMoNeuRaL RavenCalc | 1U | **cpu** | `/ravencalc.html` |
| `miner` | SyMoNeuRaL Miner | 6U | gpu | `/miner.html` |
| `streamer` | SyMoNeuRaL Streamer | 1U | net | `/streamer.html` |
| `coder` | SyMoNeuRaL Coder | 1U | cpu | `/livestack/coder` — §5 is fixed |
| `project` | SyMoNeuRaL Project | 1U | cpu | `/project.html` |
| `sigils` | SyMoNeuRaL Sigils | 1U | gpu | `/sigils.html` |
| `studio` | SyMoNeuRaL Studio | 1U | gpu | `/studio` |
| `live` | SyMoNeuRaL Live | 1U | net | `/livestack/live` |
| `dispatchos` | SyMoNeuRaL DispatchOS | 1U | cpu | `/demo/dispatchos` |

**Twelve rows, eighteen rack units, as of 2026-08-29.** Two changes landed together and they
are unrelated. `train` and `exp` left the table because they were folded under `studio` (§4);
`dispatchos` joined it because it had been a row `build_status()` actually built since #95
while **every** description of the rack — this file, `ROSTER.md`, `EXPECTED` and the hand-typed
count in `api.py` — omitted it. Six tests were red on that omission. Recorded here because
omission is the harder drift to see: a missing row reads as a shorter list, not as a mistake.

Plus `miner`'s three subunits: `gpuminer` (gpu), `asicminer` (asic), `gateway` (net).

**Reinforce and Exp are no longer rows; their ids are unchanged.** Both are `sub` entries on
the `studio` row since 2026-08-29 — see §4. `/reinforce.html` and `/exp` both still answer and
neither redirects.

**Note the `id` for Reinforce is `train`, not `reinforce`.** The label was renamed and the id
was not. Any migration that "tidies" the id breaks `/api/status` consumers and
`apps/test_status_rack.py`; any doc that writes `reinforce` as the id is wrong.

## 3. The two `bus` cells that look like mistakes and are not

`ROSTER.md` calls these out under *"things that column will mislead you about if you read it too
fast"*, and both must survive a migration with their reasoning attached:

**`live` is `net`, not `gpu`** — even though OBS encodes with NVENC and a stream genuinely does
use the card. It uses it **outside `scripts/gpu-governor.sh`**, which cannot see the session,
cannot evict it, and does not count it against its drain floor. Writing `gpu` would enter the
row in the rack's *who holds the card* readout and **advertise management that does not exist.**
What the row actually spends is upstream bandwidth, and `apps/live/README.md` records the GPU
cost as **unmeasured**, which it is.

**`streamer` is `net` here and `cpu` in the module** — `apps/streamer.status()` returns
`bus="cpu"` and `api.py` overrides it at the call site. `net` is the truth about the row: an
IPTV surface is bound by the network, not by this box's cores. **The override is the
disagreement, not a bug**, and `test_roster.py` knows about it by name rather than skipping the
row.

This is the pattern to preserve generally: **a disagreement between two sources is named and
tested, never averaged away.**

## 4. Folds — folded is not deleted

| Fold | State |
|---|---|
| **Gateway → under Miner** | done 2026-08-22. `/gateway.html` still answers and still owns the surface; the fold kept the **id `gateway`** on the `SubUnit` rather than renaming it. `apps/test_status_rack.py::FOLDED` asserts **both** halves: not a row, and not deleted either |
| **Tuner + Guide → under Streamer** | one product name, guide routes nested under `/api/streamer/guide/*` |
| **Exp → Studio family** | **done 2026-08-29.** `SubUnit(id="exp")` on the `studio` row. `/exp` still answers and still owns the surface; the fold kept the id so `site/exp.html` keeps finding its own reading in `/api/status` |
| **Reinforce → Studio family** | **done 2026-08-29.** `SubUnit(id="train")` on the `studio` row. `/reinforce.html` still answers; the id `train` is unchanged, which is what `site/reinforce.html`, the governor's holder name and `apps/controlboard`'s exclusion list all depend on. `apps/test_status_rack.py::FOLDED` now asserts both halves for both, as it does for `gateway` |
| **Project → Chat cowork** | target; the current row may remain during transition. Open task **#83** |
| **Coder** | stays its own privileged developer surface — not folded |

**`backend/apps/gateway/` did not move and must not be read as having moved.** `ROSTER.md`
states the reason in a sentence worth keeping: *"thirteen modules of TRON settlement inside a
mining package would be a rename dressed as an architecture."* **Folding a rack row is a display
decision. Moving a package is a migration.**

Rules that follow: a folded surface stays **accounted for**; the page must not print *"not
present"* for one; the rack count is **tested**; the generated fallback must match the roster;
frontend smoke must assert **no duplicate page/bus rows**; and status detail must carry the
important folded behaviour rather than dropping it.

## 5. The defect this audit found — FIXED 2026-08-29

**`coder`'s href was `/documentation.html`.** The Coder rack row — a privileged browser
terminal — pointed at the documentation page.

Per `symoneural-coder-project-cli-scope.md` §4 the real surface is `/livestack/coder` (with
`/live-stack/coder` as compatibility only), and the underlying app is 2,748 lines with a
stamped smoke record. So this was a **wrong href on a working surface**, not a missing surface.

**It is fixed.** `build_status()` had in fact already been corrected; what had not been was
`ROSTER.md`, which is the identity AUTHORITY, and this file, which is the spec — so
`test_roster.py::test_every_field_matches_the_module_that_publishes_the_row` was red and the
generated pre-JS fallback in `site/index.html` still shipped the wrong link to anyone without
JavaScript. Both are corrected and the roster reconciliation is green.

The lesson is the one this document keeps arriving at from new directions: **the code being
right is not the same as the surface being right.** A row's href reaches a visitor through
`/api/status` for a JavaScript client and through the generated fallback for everyone else,
and only one of those two paths had the fix.

## 6. `toggle` — a cross-check, not the source

The authority is `TOGGLEABLE` in `apps/controlboard/__init__.py`, which carries the reasoning
for every exclusion: `train` because interrupting a fine-tune mid-epoch is destructive; `miner`
because one row spans a GPU half and an ASIC half; `coder`/`gateway`/`project` because they are
already config-gated and an operator override would be a second source of truth for the same
LED; and `live` because **the override could not do what the button would promise** — OBS keeps
writing segments whatever the rack says, so the row would read *taken offline by operator* while
a stream stayed genuinely watchable.

`test_roster.py` asserts the column and the tuple agree. **Two hand-maintained copies plus a
test that they match is the point** — deriving one from the other would delete the check.

## 7. The rules

- **No decorative LEDs. No fake READY. No stale OFFLINE after work finishes.**
- Every `READY` / `OFFLINE` / `QUEUED` chip is backed by a probe or a test.
- **No duplicated top-level products pointing at the same page or bus.** This has happened: the
  rack once showed one page twice because Tuner and Guide both used `/tuner.html`.
- **No missing folded surfaces.**
- Top-level ids match the current product architecture — and `train` is the id, per §2.
- **Current rack reality and target architecture are stated separately.** A row that exists
  today is reported as existing today even when the target folds it.

## 8. What this document is now allowed to describe

The 2026-08-22 scope was docs-only and this section listed what it could not touch: no rack
assembly change in `api.py`, no `ROSTER.md` identity change, no href fix, no deploy.

**Handshake 6.0 authorised all four, and they are done.** What did NOT change, and is still
not this document's to change: no folder migration (`backend/apps/gateway/` and
`backend/apps/studio/plugins/` are where they were — folding a rack row is a display decision,
moving a package is a migration), no runtime built, selected or reconfigured, no Control Board
or rackpower move, no raw ComfyUI exposure, and no change to what `/api/status` MEASURES —
only to how the rack is composed from it.

Related: `backend/controlboard/docs/symoneural-control-board.md` (the operator half),
`backend/docs/docs/symoneural-api-surface.md` (where status comes from),
`backend/apps/ROSTER.md` (identity, and the authority),
`backend/apps/appdocs.py` (per-application documentation ownership, and the partition that
makes a scoped page unable to show another application's routes).
