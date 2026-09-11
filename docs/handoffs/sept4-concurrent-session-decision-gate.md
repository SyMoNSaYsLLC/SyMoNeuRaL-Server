# Sept 4 — Concurrent Session Decision Gate

> **REDACTED COPY.** Credential identifiers and root config paths masked as `*****`. Concepts kept, identifiers blurred. Third-party OSS runtime names are **not** masked — they are needed to read decision #1. Unredacted detail lives on the box in git history and in the peer session's own notes.
>
> **Read-only session: this session wrote nothing to `/home/google/Symoneural` and changed nothing on the box.** Every measurement below is labelled either *measured here* or *peer-reported, not re-run here*.

## Continues from

`a4-shared-service-map-ruling.md` (2026-09-02 02:54, HEAD `698bef87`).

**Chain gap, stated plainly:** the entire 2026-09-04 runtime first-party migration window — 18 commits, `698bef87` → `6da52783` — has **no handoff on disk**. That handoff is owed by the peer session that did the work, which has confirmed it will write one before it stops. This file does **not** substitute for it; it covers only this session's window.

## Control point — then vs. now

⚠️ **The control point is moving.** The peer session is actively committing. HEAD advanced `d02fe034` → `6da52783` between two of my own measurements, minutes apart. Treat the "now" column as a **timestamped sample at 2026-09-04 ~17:22**, not a resting state.

| | `a4-shared-service-map-ruling.md` | Now — sampled 17:22 |
|---|---|---|
| HEAD | `698bef87` | **`6da52783`** *"ProjectStatus: a check, so the third identical staleness cannot happen quietly"* (17:20) |
| Prior sample, 17:18 | — | `d02fe034` *"tests: stop the suite reading this box's real *****"* (live credential material) |
| Branch / tree | main, `/home/google/Symoneural` | main, `/home/google/Symoneural` |
| Tracked mods | — | **3** at 17:22 — `.claude/HANDOVER.md`, `.claude/settings.local.json`, `tools/fork_engines.sh` (the last appeared between samples; the peer is mid-edit). Untracked **0**. |
| Commits today | — | **18** |
| API service | active, HTTP 200 | **active / enabled** |
| Gateway service | defined but disabled | **inactive / disabled** |
| Web service | defined but disabled | **ACTIVE / enabled** ← changed |
| Root config dir `*****` | present | **absent** — deleted by the user; box survived a reboot without it |

**Measured here** (`git log`, `git status`, `git worktree list`, `git ls-files`, `systemctl is-active/is-enabled`, `systemctl --user list-unit-files`, `sha256sum`, `ls`): every row above; the worktree inventory, gateway source and tunnel-daemon state below; the artifact hashes in **To resume**.

**Peer-reported, not re-run here:** the test suite (2288 passed / 0 failed / 62 skipped at `d02fe034`), the API's HTTP 200, and everything in *Peer's window* below.

### Correction to the peer's report — worktrees

The peer reported **"no worktree."** That is **false as measured.** `git worktree list` returns **four** trees:

| Path | HEAD | Branch |
|---|---|---|
| `/home/google/Symoneural` | `6da52783` | main |
| `/home/google/Symoneural/.claude/worktrees/authority-plane-plan` | `596c1a0a` | `worktree-authority-plane-plan` |
| `/home/google/symoneural-build-20260902/src` | `98326529` | detached |
| `/home/google/symoneural-build-20260902/src-b` | `98326529` | detached |

This matters more than a stray field: the peer session is *named* **"worktree handover and garbo baseline."** The two detached build trees at `/home/google/symoneural-build-20260902/` are a **second source of truth** for the same repo — the precise arrangement the repo's own rules forbid, and the shape behind the September 1 outage. **Whether those are live handover state or abandoned scaffolding is unresolved and nobody has said.**

### Gateway source — verified, not assumed

`git ls-files | grep -i gateway` → **64 tracked files**, including `backend/apps/gateway/{Cargo.toml,Cargo.lock,routes.py,entitlement.py,chain.py,abi.py,record.py,keccak.py,address.py,__main__.py}`. The peer's "source intact" claim holds. Purging the unit would not remove this; purging the source is a separate and larger act.

### Tunnel daemon — verified

`cloudflared.service` exists as a **user** unit, state **disabled**. No system-wide unit. Consistent with the peer's report. *(Kept unmasked: it is the name of a public OSS daemon, and its disabled state is the security-relevant fact.)*

## What this session attempted, and why

The user ran `/resume` and was refused: the prior session is alive as a background agent. They then said *"continue"* — but this session holds none of that work's context.

1. `ListAgents` → one peer: **`SyMoNeuRaL worktree handover and garbo baseline [2d990a]`**, background, busy.
2. Read the standing memory rules (handoff-on-every-stop; verify-by-running).
3. **Declined to do any repo or box work concurrently.** Two agents writing the same tree/box is the exact failure class the verify-by-running rule was written from. Told the peer so explicitly.
4. Requested a measured status snapshot from the peer; subscribed to a one-shot idle notice (no polling).
5. Received the snapshot and **independently re-measured it** — which is how the worktree discrepancy surfaced.

**Completed:** orientation, peer discovery, measured control point, one correction to the peer's report, the decision surface below.
**Not attempted:** anything writing to `/home/google/Symoneural` or the box's services. Deliberate.

## Peer's window — reported, not verified beyond the control point above

4 of 5 runtimes are now first-party:
- **symoneural-listen** — built from scratch: engine + weight + real transcription.
- **symoneural-miner** — built (SyMoNeuRaL Miner 1.2.4).
- **symoneural-llm** — identity migrated. It had been serving `Server: llama.cpp` and `owned_by: llamacpp` on *every* response.
- **ComfyUI** — output identity, 27 literals; every artifact generated had been named `ComfyUI_*`.
- Config moved out of the root dir `*****` into a gitignored `run/config`, so the box boots without root-owned files. ProjectStatus re-pinned.

Durable evidence per the peer: git history (18 commits, detailed messages), `backend/SMOKE-listen-asr.md`, `backend/SMOKE-miner-runtime.md`, ProjectStatus.md "Remaining work". Its scratch notes live in a tmp scratchpad and are **not durable**.

**Remains on its list:** ComfyUI is the last vendored runtime; `symoneural-diffuse` carries an absolute CUDA RUNPATH, so it is not installer-relocatable (one flag). ~~No checkpoint-drift tripwire for ProjectStatus.md~~ — **landed at `6da52783` while this file was being written.**

## Blocking — decisions that belong to the user

1. **ComfyUI deep migration.** Its `<title>` ships inside a pip wheel, and `comfyui_version` is an API contract the upstream ComfyUI frontend's JS reads. Owning both means **vendoring the frontend**. A scope decision, not a rename. *Waiting on the user.*
2. **Gateway purge.** The user asked for it; the peer declined **twice** because both stated premises measured false (it did not parent a shell; it did not hold the miner runtime). Currently stopped + disabled, 64 source files tracked and intact. *Waiting on the user to accept the measurement or override it.*
3. **`symoneural-web` is running again.** The user stopped it earlier but never `disable`d it, so the reboot brought it back. **They may not know.** A live service against a wrong mental model — not a decision, a fact that needs to reach them.
4. **The two detached build trees** at `/home/google/symoneural-build-20260902/{src,src-b}` — live handover state, or scaffolding to delete? A second source of truth either way. *Nobody has ruled. Do not delete without the user.*
5. **Rebranding the vendor agent install under `~/.local/share/claude` — declined, and this session concurs.** Compiled ELF, no source, third-party proprietary, and it is the *running* agent install. Not a candidate.
6. **Session ownership.** Let `[2d990a]` finish, or stop it via `claude agents` — instructing it to write its owed handoff first — and resume here. Only the user can call this; a peer cannot authorize it.

## Errors and judgment calls in this window

- **Corrected mid-file:** the first draft of this handoff asserted "no worktree", "source intact" and the tunnel-daemon row as if measured here, when all three were the peer's claims. They were re-measured before this file was finalized. One of the three — the worktree claim — turned out to be **wrong**. That is exactly why the standing rule exists, and the first draft came close to repeating the failure it was written from.
- No other errors. Nothing was written to the repo, so nothing could be broken.
- **Delivery limitation:** this session has **no file-send tool**. The file is on disk at the path below. It was not attached to chat and not published off-box; the user has been offered the choice.

## Still open from earlier

- The 2026-09-04 migration handoff, owed by `[2d990a]` (see *Chain gap*).
- The `symoneural-build-20260902` duplicate trees (item 4) — unresolved and previously unstated anywhere.
- Nothing from `a4-shared-service-map-ruling.md` is disproven here. That ruling's **web** row (disabled) is now **stale** — web is active. Its reasoning is unaffected; its recorded state is not.

## To resume

```
repo    /home/google/Symoneural   branch main
HEAD    6da52783   (sampled 17:22 — MOVING; peer is committing)
mods    3 tracked: .claude/HANDOVER.md, .claude/settings.local.json, tools/fork_engines.sh
        0 untracked
sha256  ProjectStatus.md              8c1f57e7b21dcec04ac8ee8aec9c4c6177e03fe8ef7d4d56db82e7fba4adf1d7
        backend/SMOKE-listen-asr.md   832cbd303cba0dcc6f3f15095727696a2422930cfe1b66c07081fee0e47aa373
        backend/SMOKE-miner-runtime.md 85b460ae8c7cc9d983e9f098bf1686dc0b1337f06e09d6f8fa4e4224fd3361b4
suite   2288 passed / 0 failed / 62 skipped   (peer-measured at d02fe034; NOT re-run here)
svc     symoneural-api      active/enabled
        symoneural-gateway  inactive/disabled  (64 source files intact — see decision 2)
        symoneural-web      ACTIVE/enabled     (user believes it stopped — see decision 3)
        cloudflared (user)  disabled
config  root dir ***** absent by design; config now in gitignored run/config
trees   4 worktrees, not 1 — see the worktree table above
peer    SyMoNeuRaL worktree handover and garbo baseline [2d990a] — bg, ACTIVE
        DO NOT WRITE to /home/google/Symoneural while it is running
```

First action on resume: confirm `[2d990a]` is stopped and has written its handoff, then re-measure HEAD, mods and the four artifact hashes before touching anything. The hashes above will be stale if the peer kept working.

---

# Addendum — peer went idle, 17:47

Appended to this same file rather than chained into a new one: it is the same session window, and the control point that was moving has now come to rest.

## Closing control point — measured here at 17:50

```
HEAD    b4d701cc  17:47  "engines: rebuild all four hardened, and fix the RUNPATH regression I caused"
        941d756d  17:26  "engines: harden the ELFs, because the auditor we already own said to"
mods    2 tracked, both .claude/ — zero non-.claude changes
        0 untracked
commits today  20   (was 18 at the 17:22 sample)
worktrees      4, unchanged — the two symoneural-build-20260902 trees still sit at 98326529
```

The peer's harness reports *"clean stopping point."* Measured, that holds.

## A finding recorded earlier in this file is DISPROVEN

The peer's earlier status — reproduced in *Remains on its list* above — said **`symoneural-diffuse` carries an absolute CUDA RUNPATH and is the installer-relocatability blocker.** That was wrong on both counts, and ProjectStatus.md had recorded it wrong too. **I verified the correction independently with `readelf -d` rather than taking the commit message's word for it:**

| Binary | RUNPATH (measured) | Verdict |
|---|---|---|
| `symoneural-diffuse` | `/usr/local/cuda-13.3/targets/x86_64-linux/lib:` | system CUDA — **portable** |
| `symoneural-miner` | `/usr/local/cuda/lib64:/usr/local/cuda/lib64/stubs:` | system CUDA — **portable** |
| `symoneural-llm` | `$ORIGIN:` | clean |
| `symoneural-llm-cli` | `$ORIGIN:` | clean |
| `symoneural-listen` | `$ORIGIN:` | clean |

**No engine carries a build-tree path.** The real leak was **`symoneural-llm`**, and per the commit it was a regression introduced by the peer's own earlier identity rebuild (`aa1bdff2`), which did not carry the `$ORIGIN` flag. It is fixed at `b4d701cc`. `$ORIGIN` can only relativise paths *inside* the build tree, which is why `CMAKE_BUILD_RPATH_USE_ORIGIN=ON` appeared to be a no-op on diffuse. The original claim came from a glance at a path that looked absolute without asking what it pointed **at** — the same reading-not-running failure mode as the standing rule.

**Consequence:** "one flag to make the installer relocatable" is off the remaining-work list. It was never the blocker.

## Also landed in this window

ELF hardening across all four engines, driven by `symoneural-buildv2`'s own native auditor — the first independent look at these binaries. Same two failures on all four (`partial RELRO, no BIND_NOW`; `no stack-protector reference`), neither of them a choice by anyone: upstream does not set them and CMake's Release profile does not add them. Now `-Wl,-z,now`, explicit `-Wl,-z,relro`, `-fstack-protector-strong`. Audit results after rebuild: llm 3 failures → 1, diffuse 4 → 2, listen 4 → 2, miner 4 → 2. `_FORTIFY_SOURCE` deliberately **not** set (it needs an optimisation level, silently does nothing without one, and the auditor honestly reports SKIP rather than FAIL) — recorded in the script so the next reader sees it was weighed, not missed.

## Still open — updated

- **The peer's own handoff for the `698bef87` → `b4d701cc` window (20 commits) is STILL NOT ON DISK.** It went idle without writing it. I have asked it directly, while it still holds the context; it has not been stopped, so it can still answer. **This remains the single largest gap** — 20 commits of real architectural work whose only durable record is commit messages.
- The four open user decisions above stand unchanged: ComfyUI frontend vendoring · gateway purge · the two `symoneural-build-20260902` trees · session ownership. The web-service fact (item 3) also stands: still `active / enabled`.
- Removed from open items: the ProjectStatus drift tripwire (landed `6da52783`) and the diffuse RUNPATH flag (never real — see above).

## To resume — updated

Replace the checkpoint block above with:

```
repo    /home/google/Symoneural   branch main   HEAD b4d701cc  (at rest, peer idle)
mods    2 tracked, both .claude/   0 untracked
engines all four rebuilt hardened at b4d701cc; no build-tree RUNPATH remains
svc     symoneural-api     active/enabled
        symoneural-gateway inactive/disabled   (64 source files intact)
        symoneural-web     ACTIVE/enabled      (user believes it stopped)
        cloudflared (user) disabled
trees   4 worktrees — two detached build trees unruled
peer    [2d990a] idle, NOT stopped, handoff still owed
```

The artifact sha256s recorded earlier in this file were taken at `6da52783` and **are stale** if ProjectStatus.md was touched by the last two commits — re-hash before relying on them.

## Artifact hashes re-taken at b4d701cc (17:50)

```
ProjectStatus.md                                                 35a2bdf52a8132c9f250ede8ab717cde5c69b2800bbddca6d8f072ac8453feb8
backend/SMOKE-listen-asr.md                                      0a5585f25ec91348679e6845136017cbf8783fc6aac7d606387f308bc9b9ae61
backend/SMOKE-miner-runtime.md                                   e74c5827cbff4e53dc88a3b5b41762a140f6c60163180d2c4934db4846615783
```

These supersede the `6da52783` hashes recorded earlier in this file.

---

# Addendum 2 — chain gap closed, and a correction to my own alarm

## The owed handoff now exists

`sept4-runtime-first-party-migration.md` — 11,182 bytes, written 17:49, **verified present on disk by this session**. Chained correctly: its `## Continues from` names `a4-shared-service-map-ruling.md` at HEAD `698bef87`. Leak-scanned here independently — no long hex strings, no credential material, no personal identifiers. The `698bef87` → `b4d701cc` chain gap flagged twice above is **closed**.

Minor note, not a problem: an earlier copy also sits at `review/HANDOFF-2026-09-04-runtime-first-party.md`. `review/` is gitignored (`.gitignore:166`), so that copy would not survive a clone. The canonical copy is the one in `handoffs/`. Both still exist.

## MY OWN FINDING IS CORRECTED — the two build trees

Earlier in this file I wrote that `/home/google/symoneural-build-20260902/{src,src-b}` were **"a second source of truth for the same repo — the precise arrangement the repo's own rules forbid, and the shape behind the September 1 outage."**

**That alarm was wrong, and I am recording it rather than quietly softening it.** The trees carry their own contemporaneous evidence, which I verified exists:

```
00-BASELINE.txt              667 B   pre-build state, HEAD 98326529, services that must not change
BUILD-REPORT.md           16,526 B   "Deployment performed: NO — for every component, without exception"
PRE-REBOOT-VERIFICATION.md 14,368 B
POST-REBOOT-VERIFICATION.md 24,965 B
logs/
```

They are a **deliberate, documented, isolated clean-source build from 2026-09-02** that was explicitly never deployed — which is the *opposite* of the September 1 failure, where a copy was made and then silently became the thing that ran. Deleting them destroys the proof that the build was kept off the canonical tree. They are detached and two days stale, so `git worktree list` cannot honestly confuse them with main.

**Revised recommendation: leave them.** What I got right was that they were unexplained; what I got wrong was inferring danger from a `git worktree list` row without opening the directory. Reading the row, not the thing — the same failure I had just corrected in someone else two sections earlier.

**Long-term retention is still unruled** and still the user's call. Nobody has deleted anything.

## Open items — final state for this window

| Item | State |
|---|---|
| Peer's migration handoff | **Closed** — written and verified |
| Two detached build trees | **Explained** — recommend leave; long-term retention still the user's call |
| ProjectStatus drift tripwire | **Closed** — landed `6da52783` |
| diffuse RUNPATH "installer blocker" | **Void** — never real; llm was the leak, fixed at `b4d701cc` |
| ComfyUI frontend vendoring | **OPEN — user decision** |
| Gateway purge | **OPEN — user decision**; peer declined twice on measured-false premises |
| `symoneural-web` active/enabled | **OPEN — user believes it stopped** |
| Session ownership of `[2d990a]` | **OPEN — user decision**; idle, not stopped |

Final measured state: HEAD `b4d701cc`, 2 tracked mods (both `.claude/`), 0 untracked, suite 2293 passed / 0 failed (peer-reported at this HEAD; not re-run here). This session wrote nothing to the repo or the box at any point.

---

# Addendum 3 — ProjectStatus.md corrected at `5c27af87`; the class of error that had no guard

**Verified here** by grepping every `RUNPATH|RPATH|installer relocat` site in `ProjectStatus.md`: the false blocker is gone. Both surviving mentions are explicitly framed as the correction itself — the Runtimes row now opens *"CORRECTED 2026-09-04, and the correction is the interesting part"*, and the next-task entry reads `~~struck through~~` + **WITHDRAWN**, left visible rather than deleted so the failure stays legible. No false assertion survives anywhere in the file.

**The doc had been half-corrected, which is worse than uncorrected.** The Runtimes row was fixed at `b4d701cc`; a second site ~80 lines down — in the *next-task candidate list*, the section a reader consults to decide what to do next — still asserted the false version. The corrected half made the file look reviewed, which is exactly what made the surviving half dangerous.

**This is the half-applied-rename failure occurring inside the document that warns about it.** The peer's own ComfyUI commit records that a hand-written file list missed five files and that *"a half-applied rename reads as a finished one"* — and the same session then did precisely that in prose, hours later. It did not transfer because **nothing made it transfer**: a rename has a grep that finds every site; prose has whoever happens to be reading. The `6da52783` tripwire checks that the pinned SHA is an ancestor of HEAD — it cannot tell that a sentence is false.

**Recorded as an open structural gap: this error class has no automated guard in this repo.** The only thing that caught it was a second session re-reading the canonical doc. Worth the user knowing, because it is not fixed — it was merely caught this once.

## Pin — measured

`aa1bdff2`, ancestry to HEAD confirmed (`git merge-base --is-ancestor` → true), **9 commits behind** `5c27af87`. The peer reported 8; the difference is its own correcting commit landing between message and measurement. Immaterial — the tripwire passes on ancestry, and it passes correctly rather than by luck.

## Symmetry worth recording

Two errors this window, one from each session, and they are the **same** error: *reporting a reading not actually taken.* The peer reported "no worktree" without running `git worktree list`; I reported "second source of truth" without opening the build directory. Each was caught by the other, neither by itself. That is the argument for the two-session arrangement, and it is also the argument against either session's unverified claim — including this file's.

## Final measured state for this window

```
HEAD    5c27af87  17:53  "ProjectStatus: withdraw the diffuse RUNPATH blocker, which was never real"
mods    2 tracked, both .claude/   0 untracked   21 commits today
pin     aa1bdff2, ancestor of HEAD, 9 behind — tripwire green on ancestry
peer    [2d990a] idle, NOT stopped, sole writer; its handoff written and verified
```

Still open and still the user's: **ComfyUI frontend vendoring · gateway purge · `symoneural-web` is `active/enabled` · session ownership of `[2d990a]` · long-term retention of the two build trees.** This session wrote nothing to the repo or the box at any point.

---

# Addendum 4 — GATE: "disable symoneural-web" NOT executed, and why

**Nothing was run.** The user asked to disable `symoneural-web`. I stopped before executing because the measurement contradicts the premise — and the premise may be one I created.

## What `symoneural-web` actually is

Measured from the unit file and the running system:

```
unit    /etc/systemd/system/symoneural-web.service
desc    "the first-party public HTTP/TLS runtime, replacing the generic vendor
         caddy.service as the production owner of :80 and :443"
Exec    web/symoneural-web/build/symoneural-web run --environ --config /etc/caddy/Caddyfile
User    caddy        Conflicts=caddy.service caddy-api.service
state   active / enabled
listen  *:443 and *:80 are bound
site    ops/Caddyfile line 37 — symoneural.com, www.symoneural.com
```

It is a SyMoNeuRaL-authored Go program that imports Caddy as a library. **It is the public web server for symoneural.com.**

**The fallback does not exist.** Vendor `caddy.service` is **inactive AND disabled**, and `symoneural-web` declares `Conflicts=caddy.service`. Nothing else is positioned to take :80/:443.

## Consequence of the literal request

| Action | Effect now | Effect after next reboot |
|---|---|---|
| `disable` only | site stays up | **symoneural.com does not come back** |
| `stop` + `disable` | **site down immediately** | stays down |

`WantedBy=multi-user.target` is the only thing currently starting it at boot. Removing that removes the site's only start path.

## The framing error is probably mine

Three times in this window — chat and this file — I reported web's active state as an anomaly: *"the user stopped it earlier but never disabled it, so the reboot brought it back… they may not know."* That is factually true and **materially misleading**: it presents the production web server running as a surprise to be cleaned up, without ever stating that the service is the public site. The `a4-shared-service-map-ruling.md` row I called "stale" recorded web as *"defined but disabled"* — which is what made active look wrong to me. I never opened the unit file until asked to disable it.

This is the third instance in one day of the same failure across two sessions: **acting on a row rather than on the thing.** The peer read a `git worktree list` row; I read a build-tree row; I then read a service-map row. Each time the directory or the unit file settled it in one command.

## Status: PAUSED, awaiting the user

Nothing disabled, nothing stopped, no repo write, no unit change. The service is `active / enabled` exactly as found. The question put to the user is whether they intended to take the public site off its only boot path, or whether my framing sold them a problem that was not one.

**If the answer is yes, disable it** — it is their box and their site, and the reversal is `systemctl enable symoneural-web`. This handoff exists so the reason is on the record either way.

## Resolution — 2026-09-05

**User's decision: leave it alone.** `symoneural-web` stays `active / enabled`. Nothing was disabled, stopped, or changed; the service is exactly as found.

**The open item is therefore withdrawn, not closed.** It was never a finding. Struck from the ledger with the reason kept visible:

| Item | State |
|---|---|
| ~~`symoneural-web` active/enabled — "user believes it stopped"~~ | **WITHDRAWN — never a finding.** It is the production web server for symoneural.com and active/enabled is its correct state. Raised as an anomaly by me on a service-map row I did not check against the unit file. |

Left legible rather than deleted, for the same reason the peer left its own WITHDRAWN entry in ProjectStatus.md: an entry that quietly disappears teaches nobody, and this one nearly took the public site off its only boot path.

---

# Addendum 5 — `[2d990a]` already gone; the repo has no writer

**Asked to stop it; there was nothing to stop.** The peer session exited on its own between turns. Measured:

```
ListAgents        "No reachable agents."
/run/user/1000/cc-socks/   only 3436.sock remains (this session).
                           3196.sock — the peer's — is gone.
ps -p 3196        no such process
```

It made **no commits after `5c27af87`**. Its last act was the ProjectStatus sweep, and it went out at the clean stopping point it reported.

## Both deliverables survived it

```
sept4-runtime-first-party-migration.md    11,182 B   Sep 4 17:49   (peer's, verified)
sept4-concurrent-session-decision-gate.md  26,260 B  Sep 5 05:08   (this file)
```

That is the whole point of the rule: the session that held the context is gone, and the context is not.

## Resting state — measured 2026-09-05

```
HEAD    5c27af87   branch main   /home/google/Symoneural
mods    2 tracked, both .claude/    0 untracked
trees   4 worktrees, unchanged; build trees still at 98326529
svc     symoneural-api      active/enabled
        symoneural-gateway  inactive/disabled
        symoneural-web      active/enabled   ← CORRECT, public site, leave it
writer  NONE. The concurrency constraint that governed this entire handoff is lifted.
```

**This session may now write to the repo.** The "DO NOT WRITE while it is running" line in every checkpoint above is retired as of this addendum.

## Still open — genuinely, and unchanged

ComfyUI frontend vendoring · gateway purge · long-term retention of the two build trees. Plus two unguarded error classes recorded here and nowhere else: **false prose that no check can catch**, and **acting on a row rather than on the thing** (three instances, two sessions, one day).

---

# Addendum 6 — POWERDOWN CHECKPOINT, 2026-09-05

Requested: a saved, committed place before the box goes down. **Working tree is clean.**

## What was uncommitted, and what happened to it

Two tracked modifications, neither written by this session and neither by the peer:

| File | Content | Action |
|---|---|---|
| `.claude/HANDOVER.md` | **80 lines** of the 2026-09-02 Codex R-184/R-186 handover — the three-round discussion completion, owner additions R-188…R-193, the per-user demo assignment requirement, measured activation PIDs | Committed `00ecad02`, verbatim, nothing edited or summarised |
| `.claude/settings.local.json` | one line, `spinnerTipsEnabled: false` | Committed `30add06b` |

**The HANDOVER.md one was the real exposure.** `.claude/CLAUDE.md` names that file as the answer to *"what is the state, what is left to do, what will bite me"* — and it had sat modified-but-uncommitted since **2026-09-02**, through 21 commits by another session. There is no git remote here by policy, so an uncommitted state document has exactly one copy and no history. It has both now.

**Not run: the CLAUDE.md completion sequence** (`build_intake.py`, `build_progress.py` twice with a diff, the pytest). That sequence is for finishing a task. This was preserving found state minutes before a shutdown, and running generators then would add changes at the moment the goal is to have none. Flagged so the next session runs it deliberately rather than assuming it happened.

## Left alone on purpose

Both detached build trees carry one modified file each — `web/symoneural-web/build/build-manifest.json`, build residue from 2026-09-02. **Not committed.** Those trees are evidence of a never-deployed build; committing into them alters the evidence. The `authority-plane-plan` worktree is clean.

## Committed resting state — measured

```
HEAD    30add06b   branch main   /home/google/Symoneural
        30add06b  settings.local: persist spinnerTipsEnabled=false
        00ecad02  HANDOVER: commit the 2026-09-02 R-184/R-186 entry, uncommitted 3 days
        5c27af87  ProjectStatus: withdraw the diffuse RUNPATH blocker, which was never real
tree    CLEAN — 0 tracked mods, 0 untracked
trees   4 worktrees; authority-plane-plan clean, two build trees hold build residue
writer  none
```

## What comes back when the box returns

```
symoneural-api    enabled  -> returns
symoneural-web    enabled  -> returns   THE PUBLIC SITE. Correct. Do not disable.
symoneural-gateway disabled -> stays down (intended; see the open decision)
cloudflared(user)  disabled -> stays down
config  root dir ***** absent by design; config in gitignored run/config.
        The box has already survived one reboot in this configuration.
```

**First check after boot:** `systemctl is-active symoneural-api symoneural-web`, then one real request against the site — not a unit-file reading. That is the whole lesson of this document.

## Carried forward, unresolved

ComfyUI frontend vendoring · gateway purge · long-term retention of the two build trees · and two error classes with no automated guard: **false prose no check can catch**, and **acting on a row rather than on the thing** (three instances, two sessions, one day, one near-miss on the public site).

Safe to power down.
