# Miner preemption — the yield protocol

**Status: specified, NOT implemented. Do not implement it without reading §7.**
Written 2026-08-17. Cited by `.claude/HANDOVER.md` §5 item 8,
`backend/apps/cryptominer/README.md` and `backend/apps/cryptominer/__init__.py` — all three
referred to this file before it existed, which is the same defect as `asicminer.probe()` citing
a README that had not been written. The citations are now true; the feature is still
deliberately absent, and §7 is why.

---

## 1. The problem, stated exactly

One RTX 5070 Ti, one tenant, arbitrated by a `mkdir` lock at `run/gpu.lock.d`. Every GPU
surface holds the lock for **a job** — a chat completion, an image render, a fine-tune step
loop. The GPU miner is the one exception: it holds the lock for **its whole process
lifetime**, because that is what mining is.

`scripts/gpu-governor.sh` has an eviction arm for exactly this surface, and it is correct:

```bash
miner)
  python3 -c '... import cryptominer; cryptominer.stop()' \
    >/dev/null 2>&1 || pkill -g "$(cat "$RUN/miner.pid" ...)" ...
  ;;
```

**It is also unreachable while the miner is running,** and the reason is the order of
operations in `cmd_acquire` (`gpu-governor.sh:122`):

```bash
until mkdir "$LOCKDIR" 2>/dev/null; do      # 1. spin until the lock is FREE
  break_if_stale && continue
  ...timeout...
done
prev="$(cat "$RUN/resident" ...)"           # 2. only now read who was resident
if [ -n "$prev" ] && [ "$prev" != "$surface" ]; then
  if ! evict "$prev"; then ... fi           # 3. and only now evict them
fi
```

Eviction happens **after** the arriving surface owns the lock. A live miner owns the lock, so
step 1 never completes and step 3 never runs. The `miner)` arm therefore only ever fires in
the *other* case: the miner is recorded in `run/resident` but is no longer holding the lock —
it crashed, or exited, and left a stale residency marker. That is a real case and the arm
handles it. It is not preemption.

**Measured, on this box:** `gpu-governor.sh acquire chat 10` against a live miner logs

```
'chat' TIMED OUT after 10s behind 'miner'
```

with the timeout deliberately cut to ten seconds to show the behaviour rather than wait out
the real `ACQUIRE_TIMEOUT_S=300`. In production that is a visitor watching a chat request hang
for five minutes and then fail.

The governor's own comment on the `miner)` arm says the intent plainly — *"the exact opposite
of 'train': a miner yields to everything, because no hashrate is worth making a visitor
wait"*. **The intent is right and the mechanism does not exist.** This file specifies the
missing half.

## 2. What must remain true afterwards

These are the invariants the current design already holds. A yield protocol that breaks any
of them is worse than no yield protocol, because each one exists because of an incident.

1. **`train` is never evicted, and is never yieldable.** `evict()` refuses when
   `train_lora.py` is running and says so. Yieldability must be an **allow-list** (`miner`
   today), never a deny-list, so a new surface is non-yieldable until somebody decides
   otherwise.
2. **Nothing kills a tenant to take the card.** Killing returns the lock before the CUDA
   context has torn down, and the next tenant OOMs at step 0. That is what `drain()` and its
   `DRAIN_FLOOR_MIB` floor exist for. A yield ends with the holder **exiting on its own**
   and the drain wait doing its job unchanged.
3. **A release names its surface.** `cmd_release` refuses a mismatched claimant against a live
   holder, because an unscoped release once destroyed a running fine-tune's lock from the
   API's shutdown hook. The yield path must not introduce a second way to remove a lock
   directory somebody else owns.
4. **One place stops the miner.** `cryptominer.stop()` signals the process **group**, because
   the miner runs under `gpu-governor.sh with miner --` and signalling the recorded pid alone
   orphans the actual miner while looking like a clean stop. Any yield implementation calls
   that function; it does not grow its own kill.
5. **Honest states.** A miner that is alive but does not hold the lock is `queued`, not
   `busy`. A hashrate is never displayed without the binary having reported it. Yielding must
   be visible as what it is, not as a stall.

## 3. The protocol

A file-based request, matching the existing lock's idiom (no daemon, no socket, no new
dependency; readable with `cat` when something goes wrong at 2 a.m.).

### 3.1 Requester side — inside the `until mkdir` spin

```
YIELDABLE="miner"                      # allow-list, one entry today
YIELD_REQ="$RUN/gpu.yield"             # "<requester> <deadline-unix>"
YIELD_GRACE_S=20                       # how long a holder gets to leave
```

On entering `cmd_acquire`, and only while the spin is failing:

1. Read the current holder with the existing `held_surface()`.
2. If that surface is in `YIELDABLE` **and** the requester is not itself that surface **and**
   no live request is outstanding, write `"$surface $(( $(date +%s) + YIELD_GRACE_S ))"` to
   `$YIELD_REQ` and log `yield "'$surface' asked '$held' for the card"`.
3. Keep spinning exactly as now. **The requester never signals the holder and never removes
   the lock directory.** Its only new power is to leave a note.
4. On acquiring, or on timing out, remove `$YIELD_REQ` — and only if it is still the request
   this process wrote. Two requesters must not delete each other's notes.
5. If the grace deadline passes with the lock still held, log
   `yield "'$held' did not yield within ${YIELD_GRACE_S}s"` and carry on spinning to the
   normal timeout. An unhonoured yield degrades to today's behaviour, which is the whole
   safety argument for this shape.

### 3.2 Holder side — a watcher in `with`, for yieldable surfaces only

`gpu-governor.sh with miner -- <cmd>` gains, **only when the surface is in `YIELDABLE`**, a
background watcher that polls once a second:

1. Read `$YIELD_REQ`. Ignore it unless it parses as `<name> <integer>` **and** the deadline is
   in the future. A stale or garbage request must never stop a miner — otherwise one leftover
   file makes the surface unstartable, and the operator sees a miner that dies seconds after
   every start with nothing in its own log to explain it.
2. Log `yield "'miner' releasing for '<requester>'"`.
3. Call `cryptominer.stop()` — the same entry point as the evict arm (invariant 4). That
   signals the process group; the tenant exits; `with`'s existing trap releases the lock,
   naming its own surface (invariant 3).
4. Exit the watcher. It must not outlive the tenant, and `with` must reap it on the normal
   path too, or every finished mining run leaves a stray watcher polling for a file forever.

Then the requester's `until mkdir` succeeds on its next poll, `run/resident` still reads
`miner`, and the **existing** `miner)` evict arm runs against an already-stopped miner —
`stop()` returns `{"ok": true, "stopped": null, "note": "was not running"}`, which is why that
arm is safe to reach twice. `drain()` then waits for VRAM as it does today. **No change to the
eviction or drain logic at all**, which is the point of putting the mechanism in the spin loop
rather than in `evict()`.

### 3.3 What the surfaces show while it happens

- The rack unit goes `busy` → (miner stopping) → `ready`, and the arriving surface goes
  `queued` → `busy`. No new `Unit.state` literal is needed; `queued` already means "alive,
  waiting for the card".
- `cryptominer.status()` gains one field, `yielded_to` (string or null), read from the request
  file, so `/api/gpuminer/status` and `/miner.html` can say **"stopped to give the card to
  chat"** rather than leaving an operator to conclude the miner crashed. A miner that
  disappears without explanation is indistinguishable from a bug, and the page's whole job is
  to be the place where that is not true.
- The miner does **not** restart itself afterwards. Auto-restart plus auto-yield is a loop
  that hashes in the gaps between page views and takes the card back the moment a visitor
  leaves; that is a scheduler, it is a much larger decision than this file, and it is
  explicitly out of scope. Restart stays an operator action.

## 4. Rejected alternative: pause the miner instead of stopping it

kawpowminer exposes a monitoring/control interface — verified on the binary in use,
`kawpowminer 1.2.4+commit.8bd0d598.dirty -H api`, which documents `--api-bind`, `--api-port`
and `--api-password`. So "ask the miner to pause over its own API" looks like the gentler
design.

**It does not work here, and the reason is VRAM rather than politeness.** A paused miner is
still a resident process with its DAG allocated — measured during run 3 on 2026-08-17,
`nvidia-smi --query-compute-apps` reported the kawpowminer process holding **1808 MiB** while
hashing. The governor's `drain()` waits for CUDA-context usage to fall below **1024 MiB** before
handing the card over, precisely so the next tenant does not allocate on top of a
half-released context. A paused miner never gets under that floor, so either the arriving
surface waits forever or somebody lowers the floor — and the floor is what stops the
OOM-at-step-0 failure.

Whether kawpowminer's API even offers a pause verb was **not** verified, and it does not
matter: the memory arithmetic rejects the approach before the API surface is relevant.

## 5. Tests that must exist first

All CPU-only, no GPU, nothing mined — the same standard as `cryptominer`'s existing 72.

1. **A yieldable tenant releases.** `with fake-yieldable -- sleep 300` (with `fake-yieldable`
   temporarily in `YIELDABLE`), write a live request, assert the lock directory is gone inside
   the grace window and the tenant's process group is dead.
2. **A stale request is ignored.** Deadline in the past → the tenant keeps running. This is
   the footgun; test it before shipping, not after.
3. **Garbage is ignored.** Empty file, one field, non-numeric deadline, 1 MB of noise.
4. **`train` is never yielded.** A request naming `train` as the holder leaves it alone, and
   `evict train` still refuses while `train_lora.py` runs.
5. **A requester only deletes its own note.** Two requesters, one acquires; the other's note
   survives its neighbour's cleanup.
6. **No watcher survives its tenant.** After a normal run, `pgrep` finds no watcher.
7. **The unhonoured path degrades to today.** A yieldable holder that ignores the request must
   produce exactly the current outcome — `TIMED OUT after Ns behind 'miner'` — and not a
   broken lock.
8. **A yield is visible.** `status()["yielded_to"]` names the requester, and `unit_state()`
   does not invent a fifth state literal.

Measured before/after, and both numbers belong in `HANDOVER.md`: today
`acquire chat 10` behind a live miner times out; afterwards it should succeed in roughly
(grace + drain) seconds. **Quote the measurement, not the design intent.**

## 6. What this does not solve

- **Fairness.** Nothing stops an arriving surface, a yield, and an operator restart from
  thrashing the card. There is no scheduler here and this does not add one.
- **Partial work.** A stopped mining run loses nothing (a benchmark's numbers are in its log;
  a pool run loses at most the current share attempt), which is exactly why the miner is the
  right — and only — first yieldable tenant. Do not generalise this to a surface whose work
  cannot be thrown away.
- **The ASIC surface.** `asicminer` never takes the GPU lock. None of this touches it.

## 7. Why it is not implemented, and what would change that

It changes the hot path of **the only arbitrator of the only contended resource in this
system**. Every surface on the box — chat, image, remix, reinforce, the CLI, the test suite —
goes through `cmd_acquire`. A bug in that spin loop is not a mining bug; it is every surface
at once, and the failure modes are the expensive ones: a lock that is never released, a lock
released out from under a live tenant, or a fine-tune losing hours because something new
learned to ask for the card.

Against that: the miner already has a working manual answer. It never auto-starts, it is
started deliberately from `/miner.html` or the CLI, and it is stopped the same way — a **Stop**
button whose route was verified end to end on 2026-08-17 (`POST /api/gpuminer/control`
returned 200 with a real pid, and after it the card measurably came back: no `kawpowminer`
process, 876 MiB / 19.4 W, and the `image` tenant that had been queued behind it took the
lock). The gap between "an operator stops it" and "it yields by itself" is small while this
box is one machine with one operator.

**Implement it when either of these becomes true:**

- The miner is expected to run **unattended** — a real pool, left hashing between visits. Then
  "an operator stops it" stops being an answer, because the operator is asleep and a visitor is
  on the site. That is the trigger, and it is a business decision, not an engineering one.
- The box gains a second GPU. Then eviction and residency stop being one-lock questions and
  `cmd_acquire` has to be reworked anyway; do this in that change rather than before it.

Until one of those, the honest position is the current one: the miner takes the card only when
someone tells it to, the page says so in plain words before the button is pressed, and the rack
never claims otherwise.
