# SyMoNeuRaL Control Board — the operator surface, and the gate that makes a button true

**Scope captured 2026-08-22.** Docs and scope only. **No implementation, no move of Live Stack /
Control Board / rackpower, no `api.py` rack-assembly rewrite, no deploy.**

## What it is

> **Control Board is the operator control surface for the rack.** It shows the rack and its
> controls, and the controls are real.

Related to Live Stack, not identical to it: **Live Stack reads, Control Board acts.**
`backend/live/docs/symoneural-live-stack.md` owns the read side.

## 1. The one requirement, and it is already met

> *"If a unit is powered off through the control board, HTTP work for that surface must be
> refused."* — and *"a UI button must not lie about actual backend behaviour."*

**This is implemented.** `RackPowerGate` in `backend/server.py:1415` is **raw ASGI middleware, on
purpose** (`:49` says so), installed at `:1486`. Per request it resolves
`rackpower.unit_for_path(...)` and, if `rackpower.is_disabled(unit_id)`, refuses the work
(`:1471-1472`). The module is `apps.controlboard`, imported under the name `rackpower` at `:158`.

Two design details worth keeping:

- **It is middleware, not a per-route check.** `:1427` records why: a surface added later
  *"inherits the switch by adding one line to `rackpower.ROUTES` rather than by"* remembering to
  guard each new endpoint. A gate you can forget to apply is not a gate.
- **`rackpower.apply` gets the last word on unit state, and only ever in one place** (`:1948`,
  `:1955`). So the LED and the refusal come from the same authority — the button cannot read
  *off* while the endpoint still serves, which is precisely the failure the requirement names.

There is also a frame-level equivalent for WebSocket work: `rackpower.unit_for_frame(kind)` at
`:2294`, so a socket message for a powered-off unit is caught the same way an HTTP request is.

**So Control Board's controls already change backend behaviour.** The requirement is recorded
here as *satisfied and to be preserved*, not as work to queue.

## 2. `rackpower` is not Miner

**`rackpower` is the per-unit power switch for the whole rack.** It is not a mining concept and
**must not be folded into Miner.** The name sits next to a mining surface in a rack UI and that
is the only relationship.

Gateway *was* folded under Miner as a display decision (`ROSTER.md`, and
`symoneural-live-stack.md` §4) — that is not a precedent for folding rackpower, because Gateway
is one surface and rackpower is the mechanism that switches all of them.

## 3. Which units are toggleable, and why the exclusions are not gaps

The authority is `TOGGLEABLE` in `apps/controlboard/__init__.py`, and every exclusion carries
its reason:

| Excluded | Reason |
|---|---|
| `train` | interrupting a fine-tune mid-epoch is destructive |
| `miner` | one row spans a GPU half and an ASIC half |
| `coder`, `gateway`, `project` | already config-gated; an operator override would be a **second source of truth for the same LED** |
| `live` | **the override could not do what the button promises** — OBS keeps writing segments whatever the rack says, so the row would read *taken offline by operator* while a stream stayed genuinely watchable |

`live` is the important one: a control that cannot deliver what it appears to deliver is worse
than no control, because it converts an honest surface into a lying one. **The exclusion is the
feature.**

`ROSTER.md`'s `toggle` column is a **cross-check**, not the source, and `test_roster.py` asserts
the column and the tuple agree. Two hand-maintained copies plus a test that they match is
deliberate — deriving one from the other would delete the check.

## 4. Where it lives today, and where it is going

**Today:**

| Piece | Location |
|---|---|
| rack assembly | **inline in `backend/server.py`** (`:1955` onward) |
| the switch | `backend/apps/controlboard/` |
| the gate | `RackPowerGate`, `backend/server.py:1415-1486` |
| the page | generated into `site/index.html` by `tools/build/build_console.py` |
| the live view | browser script over WebSocket |

**Direction:** rackpower + Live Stack + Control Board eventually belong under
`backend/apps/controls`.

**Not now.** And the reason is specific rather than general caution: **the rack assembly is
inline in `api.py`, and the rack tripwire tests would have to move in the same change.**
`apps/test_status_rack.py` asserts the row count and `FOLDED` asserts gateway is neither a row
nor deleted; `test_roster.py` asserts the roster and `TOGGLEABLE` agree. Moving the assembly
without moving those in the same commit leaves the tripwires pointing at nothing while still
passing — the worst of both states. **This is a larger move than a folder rename**, and it is
not authorized.

## 5. Generator rules — for whenever the page is touched

- **`tools/build/build_console.py` must be idempotent.** Run it **twice and diff**. This repo has had
  the accumulate bug — a generator that re-reads its own output and does not recognise something
  it emits will duplicate it, one copy per run — **three times**.
- **`build_cachebust.py` runs last.** Learned again in this session: `build_pages.py` alone
  *strips* the `?v=` asset hashes from all 25 pages, which surfaced as eight changed files that
  had nothing to do with the change being made. Generated pages must not ship unstamped.
- **Route and deploy tests must know any new top-level path**, and `ops/Caddyfile` must delegate
  it explicitly. **Localhost success does not prove deployed-webroot success** — open task **#86**
  exists because a page can ship to `site/` and never reach the webroot with nothing going red.

## 6. Control rules

- Control Board **must not bypass route or gate checks** — it is a client of the same API.
- **No public destructive controls without auth and gates.** `/api/*` is delegated wholesale to
  the public internet by `ops/Caddyfile`; write endpoints live behind `/local/*` with a
  peer-address check that also refuses proxy headers.
- A control that cannot deliver its promise is **excluded, not shipped** (§3, `live`).

## 7. Not authorized

No move of rackpower / Live Stack / Control Board to `backend/apps/controls` · no `api.py`
rack-assembly rewrite · no tripwire relocation · no new public control route · no generator run
committed without the twice-and-diff check · no folder migration · no deploy.
