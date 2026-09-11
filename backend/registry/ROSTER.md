# The rack roster

The rack has **twelve rows**, and this file is where they are written down. It exists
because the roster was living in four places that could disagree — `backend/apps/` on disk,
the hand-written `Unit(...)` rows in `api.py:build_status()`, `apps/controlboard`'s
`TOGGLEABLE`, and `apps/test_status_rack.py`'s hand-typed `EXPECTED` — and three lists that
disagree is the three-state-documents failure with a different filename.

This file does **not** replace those. It is the fourth copy made deliberate: read by
`tools/build_rack.py` so the pre-JS fallback stops carrying rows by hand, and reconciled
against `api.py` and the directory by `apps/test_roster.py`. The other copies stay
independent on purpose — a tripwire wired to the thing it is watching is not a tripwire.

Live state is **not** here and must never be. Every reading a visitor sees comes from
`/api/status`, which measures it. This file carries identity only: what the row is, where it
points, how much rack it occupies.

## The rows

Read in the order `build_status()` emits them, which is the order the rack renders.

| id | label | slot | bus | href | implementation | toggle |
|---|---|---|---|---|---|---|
| chat | SyMoNeuRaL Chat | 1U | gpu | /chat.html | backend/server.py | yes |
| image | SyMoNeuRaL Image | 2U | gpu | /image.html | backend/server.py | yes |
| remix | SyMoNeuRaL Remix | 1U | gpu | /remix.html | backend/apps/remix | yes |
| ravencalc | SyMoNeuRaL RavenCalc | 1U | cpu | /ravencalc.html | backend/apps/ravencalc | yes |
| miner | SyMoNeuRaL Miner | 6U | gpu | /miner.html | backend/apps/cryptominer | no |
| streamer | SyMoNeuRaL Streamer | 1U | net | /streamer.html | backend/apps/streamer | no |
| coder | SyMoNeuRaL Coder | 1U | cpu | /livestack/coder | backend/apps/coder | no |
| project | SyMoNeuRaL Project | 1U | cpu | /project.html | backend/apps/project | no |
| sigils | SyMoNeuRaL Sigils | 1U | gpu | /sigils.html | backend/apps/sigils | yes |
| studio | SyMoNeuRaL Studio | 1U | gpu | /studio | backend/apps/studio | no |
| live | SyMoNeuRaL Live | 1U | net | /livestack/live | backend/apps/live | no |
| dispatchos | SyMoNeuRaL DispatchOS | 1U | cpu | /demo/dispatchos | backend/apps/dispatchos | no |

Twelve rows, eighteen rack units. The slot figures are what the one-screen budget is
spent on; `.claude/HANDOVER.md` §0 has the viewport table and says fourteen rows fit
everywhere -- so the folds below have **given slots back** rather than spending them, and the
next rows to land have that slack and no more. Measure with a cloned `.unit`, never with
`scrollHeight`.

**`dispatchos` was a row that was never written here, and that is the more instructive half
of this file's history.** `build_status()` has been building it since #95; `ROSTER.md`, the
`EXPECTED` list in `apps/test_status_rack.py`, the hand-typed count in the comment above it
and `docs/specs/symoneural-live-stack.md` all went on describing a rack without it. Six tests
were red on that disagreement on 2026-08-29. This is exactly the failure the file's own
opening paragraph names -- a roster living in several places that can disagree -- arriving
from the direction nobody guarded: not a row invented in one copy, but a row omitted from
every copy except the code. The tripwire worked. It just had to be run.

**`train` and `exp` are not rows any more.** Folded into `studio` as its two `sub` entries on
2026-08-29. Reinforce and Exp are Studio plugins in the implementation -- `/api/train/*` is
served by `apps.studio.plugins.reinforce.routes` and `/api/exp/*` by
`apps.studio.plugins.exp.routes`, both mounted from inside the Studio package -- and a
top-level row for each presented two plugins of one application as independent runtimes
sitting beside their own parent. `docs/specs/symoneural-live-stack.md` §4 carried both as
*"target architecture; may stay separately addressable during transition"*. They stayed
separately addressable: `/reinforce.html` and `/exp` both still answer, neither redirects,
and the `SubUnit` ids are unchanged at `train` and `exp` so `site/reinforce.html`,
`site/exp.html`, the governor's holder name and `apps/controlboard`'s exclusion list all
still find what they look for. What changed is the rack's claim about what they are.

**`gateway` is not a row any more.** Folded into `miner` as a third `sub` on 2026-08-22 --
Garrett: *"gateway is a miner app so it can merge into miner"*, *"gatway should be a sub app
of miner"*. It was a 1U tile whose LED had never been anything but grey, because there is no
contract, no wallet and no key material, and it was spending a rack slot to say so.

`backend/apps/gateway/` did **not** move and must not be read as having moved: thirteen
modules of TRON settlement inside a mining package would be a rename dressed as an
architecture. `/gateway.html` still answers, still owns the surface, and still renders its
state out of `/api/status` -- which is why the fold kept the id `gateway` on the `SubUnit`
rather than renaming it. `apps/test_status_rack.py::FOLDED` asserts both halves: not a row,
and not deleted either.

### Things that column will mislead you about if you read it too fast

**`bus` for `live` is `net` and this is the least obvious cell in the table.** OBS encodes
with NVENC, so a stream genuinely does use the card -- but it uses it *outside*
`scripts/gpu-governor.sh`, which cannot see the session, cannot evict it and does not count
it against its drain floor. `gpu` here would enter this row in the rack's "who holds the
card" readout and advertise management that does not exist. What the row actually spends is
upstream bandwidth. `apps/live/routes.py::status()` and `apps/live/README.md`'s NVENC section
carry the same reasoning, and the README records the GPU cost as **unmeasured**, which it is.

**`bus` for `streamer` is `net` here and `cpu` in the module.** `apps/streamer.status()`
returns `bus="cpu"` and `api.py` overrides it at the call site with
`Unit(**{**streamer.status(), "bus": "net"})`. `net` is the truth about the row — an IPTV
surface is bound by the network, not by this box's cores — so `net` is what is written down.
The override is the disagreement, not a bug, and `test_roster.py` knows about it by name
rather than skipping the row.

**`implementation` is where the code is, not a package name.** Four rows are served straight
out of `backend/server.py` and have no directory under `backend/apps/` at all: `chat`, `image`
and `train` are the GPU tenants the API owns directly, and `miner` is one row over two
directories (see below). Two more have a directory that is deliberately **not** a Python
package: `ravencalc/` holds a bare `ravencalc.py` that `api.py` reaches by inserting the
directory on `sys.path`, and `remix/` is a whole sub-project with its own `pyproject.toml`
and its own test suite. Neither has an `__init__.py`, and a roster built by looking for
`__init__.py` files silently drops both — which is exactly how this file came to be needed.

**`toggle` is a cross-check, not the source.** The authority is `TOGGLEABLE` in
`apps/controlboard/__init__.py`, which carries the reasoning for every exclusion:
`train` because interrupting a fine-tune mid-epoch is destructive, `miner` because one row
spans a GPU half and an ASIC half, coder/gateway/project because they are already
config-gated and an operator override would be a second source of truth for the same LED, and
`live` because the override could not do what the button would promise -- OBS keeps writing
segments whatever this rack says, so the row would read `taken offline by operator` while a
stream stayed genuinely watchable.
`test_roster.py` asserts the column and the tuple agree. Two hand-maintained copies and a
test that they match is the point; deriving one from the other would delete the check.

## What is under `backend/apps/` and is deliberately not a rack row

A directory here is not a claim to a row on the front page. These are not omissions:

- **`voice`** — `status()` is written and correct, but its `href` is `/voice.html` and that
  page does not exist, so the row would be a dead link on the front page. `api.py` says so
  at its `include_router` call. It gets a row when the page lands.
- **`cryptominer`** and **`asicminer`** — the two halves of the single `miner` row. The row
  reports one state derived from both, and the detail line always names both in the same
  order, so a reading from one can never be mistaken for a reading from the other.
- **`gateway`** — the third piece of that same row since 2026-08-22, carried as a `SubUnit`
  with its own `net` bus (see the fold note above the table). The thirteen TRON settlement
  modules stay in this directory and `/gateway.html` still reads their state off
  `/api/status`; what it no longer has is a rack row of its own.
- **`discovery`**, **`reinforce`** and **`exp`** (under `studio/plugins/`) — Studio
  plugins. None of them is a row: `reinforce` and `exp` became `sub` entries on the `studio`
  row on 2026-08-29 (see the fold note above the table) and `discovery` has never had a
  surface. `exp` was the only plugin with a row of its own and the sentence that stood here
  said so; that is the sentence the fold retired.
- **`authority`** — the mutation-authority plane, and the only entry here that is not a
  surface. It has no route, no page and no user: it is the thing every host effect on this box
  is gated by. `apps/coder`, `apps/coders` and `apps/studio` can all change this machine, and
  each used to decide for itself whether a caller was allowed to. Studio in particular admits a
  caller once with `enabled() + token_ok()`, and behind that gate a request holds 28 tools
  including a shell and an environment mutator — admission, not authority.

  Two properties carry the design. **Provider identity does not grant mutation authority**: the
  provider is who is speaking, the grant lives on the task record, and one is never derived from
  the other. And **the default is refusal** — the task travels in a ContextVar defaulting to
  None, so a surface that has not been converted to establish a task cannot mutate anything.
  Converting a surface is what turns it back on.

  The lease is a `mkdir` lock with `kill -0` staleness, both taken from
  `scripts/gpu-governor.sh` for its reason: the hold must outlive the shell that took it,
  because the API acquires in one request handler and releases in another. State lives in
  `run/authority/`, the pre-mutation journal is fsynced before the effect, and a stale holder is
  reconciled loudly rather than inherited quietly.

- **`coders`** — the multi-coder session surface (R-184): one prompt, every selected coder
  answers, each answer shown attributed. It is an **operator** surface, not a rack
  application: it holds no weights, takes no GPU lease of its own (Symon's answer goes
  through `/api/chat`, which takes the lease the governor already accounts for), and serves
  no public page. Its routes are `/local/coders/*` and its page is `/coders`, both refused
  off-box by `_require_local` — because an adapter here spawns provider CLIs under the
  operator's own logged-in sessions, and `ops/Caddyfile` delegates the whole `/api/*`
  subtree to the public internet. A rack row would advertise on a public page a surface
  that deliberately answers 404 to every public caller.

  **Off by default**, 2026-09-03: `SYMONEURAL_CODERS_ENABLED=1`, checked per request, and
  `sudo ./scripts/enable-surfaces.sh coders` is the supported way to set it. It takes no
  token, and the difference from singular `coder` is a decision rather than an oversight --
  `coder` can be opened to the network by `SYMONEURAL_CODER_ALLOW_REMOTE`, so loopback is not
  its boundary and a shared secret has to be; this surface has no such escape hatch and must
  never grow one. Provider children get an **allow-listed** environment (`child_env`), not
  `os.environ`, so no `SYM_*` or `SYMONEURAL_*` secret reaches a third-party CLI. Sessions,
  operator decisions and debate rounds are journalled to `run/coders.log` (0600, append +
  fsync, no prompt or answer text -- `prompt_sha256` pins which prompt a row refers to).

- **`accounts`**, **`capture`**, **`controlboard`**, **`licensing`**, **`news`** —
  infrastructure behind the surfaces, not surfaces. `controlboard` *drives* the rack's
  operator overrides; a row for it would be the rack reporting on itself. `news` renders the
  site's ticker, which is a site surface rather than a rack unit — that is why it moved out
  of `apps/symoneuralnews` and why it has no row.

## Adding a row

1. Add the `Unit(...)` to `build_status()` in `backend/server.py`, or the `status()` to the
   module, and make sure the page in `href` exists first. A row pointing at a 404 is worse
   than no row.
2. Add the line here, in emit order.
3. Type the new id into `EXPECTED` in `apps/test_status_rack.py` **and** the new count into
   the comment above it. That is the tripwire, and typing the number is the point of it.
4. Run `python3 tools/build_rack.py` twice, diff, then `python3 tools/build_cachebust.py`.
5. Check the one-screen budget: `.claude/HANDOVER.md` §0. Measure with a cloned `.unit`,
   never with `scrollHeight` — it floors at `clientHeight`, so it says "fits" and nothing
   about by how much.
