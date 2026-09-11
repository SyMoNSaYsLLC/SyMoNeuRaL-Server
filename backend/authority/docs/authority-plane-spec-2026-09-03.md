# Authority plane — closure spec, 2026-09-03

Status: **PLAN ONLY. Nothing in this document is implemented.**
Author role: AUDITOR, read-only. No source, service, or configuration was modified to produce it.
Deliverable exception: this file, under AGENTS.md §Roles ("create evidence only where the active
task explicitly permits a deliverable exception").

The chain this specifies:

```
TASK -> OWNER -> MUTATION LEASE -> RESOURCE SCOPE -> SPECIALIST
     -> PROVIDER -> CONTROLLED EXECUTOR -> RESULT -> DURABLE EVIDENCE
```

Every claim below cites the file and line it was read from on 2026-09-03. Where a line number is
given it was read at that revision; re-read before relying on it.

---

## 1. AUTHORITY-PLANE VERDICT

**The repository already contains a correct governed executor, and it has zero mutation callers.**

`backend/apps/coder/__init__.py` is a genuinely well-built controlled executor. It has workspace
containment (`_resolve`, line 365), an absolute-path segment denylist covering the trade-secret tree
(`DENY_SEGMENTS`, line 257), a journal that is written **before** the mutation and `fsync`ed so an
untraced edit cannot happen (`_journal`, line 421), backups including `.absent` markers so that
rollback can undo a *creation* (`_snapshot`, line 494), and an undoable `restore` that snapshots the
current state first (line 813). This is the shape the plan below needs.

It is mounted at `/local/coder/*` **read-only**. `backend/server.py:3885` states it in terms:

> `write_file`, `patch_file`, `delete_file`, `restore` and `run` are [not exposed]

A repo-wide grep for callers of those five functions returns their own test file and that comment.
**Nothing in this system mutates anything through the one component built to govern mutation.**

What does mutate the host is `backend/apps/studio`. Its own tool registry says, at
`backend/apps/studio/registry.py:212`:

> `dangerous` does not restrict anything -- nothing in this package refuses a call. It is a label.

and `backend/apps/studio/__init__.py:37`:

> no content filter, no path allow-list, no command blocklist -- `run_command` and `write_file`
> reach the whole host

That surface is mounted at `/api/studio` (`backend/server.py:3220`) and `ops/Caddyfile:50` proxies the
entire `/api/*` subtree to the public internet. `POST /api/studio/tool/run_command` is therefore a
publicly-routable path to arbitrary host command execution whose sole authority check is a shared
bearer token compared in constant time. The token is correct, the constant-time compare is correct,
and neither is an authority plane: a token identifies *nobody*, carries no task, no scope, and no
lease, and every holder of it is fully privileged.

So the verdict is not "authority is undesigned". It is narrower and more actionable:

1. **Authority is documented, not enforced.** AGENTS.md and GUARDRAILS.md specify task-gating, one
   mutation owner across the agent tree, non-inheriting children, and provider≠authority. Every one
   of those is prose that an agent is asked to honour. AGENTS.md concedes this itself: *"The planned
   Controlled Tool Executor must enforce the gate before actions reach the host; its design is not a
   claim that this enforcement system is already implemented."*
2. **The governed executor is bypassed, not missing.** The work is not "build an authority plane from
   nothing". It is: route the effectful paths that currently bypass `coder` through it, add the four
   identity fields its journal lacks, and put a lease in front.
3. **Permission mode is client-declared.** `bin/symoneural-cli:1072` sets `body["permissions"]` from
   its own `resolved_permissions()`, and the server defaults to `"allow"`. The caller declares its
   own authority. A client-supplied permission mode is not a permission system.
4. **Three of the four primitives already exist in this repo, proven, in other applications.** They
   do not need inventing — see §9.

**Severity ordering** for the mutation owner, highest first:

| # | Finding | Where |
|---|---|---|
| 1 | Public route to unrestricted host command execution, token-only | `POST /api/studio/tool/{name}` via `ops/Caddyfile:50` |
| 2 | Direct-tool route has no gate concept at all — not even the agent loop's `permission_required` | `studio/routes.py:393` |
| 3 | Server trusts a client-supplied `permissions` field, defaulting to `allow` | `studio/agent.py:266`, `symoneural-cli:1072` |
| 4 | Governed executor exists and is unreachable for mutation | `coder/__init__.py`, `api.py:3885` |
| 5 | Mutation evidence cannot be attributed to an actor, task, or lease | `coder/_journal`, line 421 |
| 6 | No mutual exclusion between two agents mutating the same tree | absent everywhere |

---

## 2. CURRENT VS REQUIRED MATRIX

Classification per the mission: `DOCUMENTATION_ONLY` (prose an agent is asked to honour),
`IN_MEMORY` (a live process object, lost on restart), `DURABLE` (survives restart),
`RUNTIME_ENFORCED` (a code path refuses when it is violated). `ABSENT` where no representation exists.

### task

| Representation | Location | Class |
|---|---|---|
| `◻ #NN — Title` block with `owner:` / `check:` / `note:` lines | `PROJECT-TASKS.md` | DOCUMENTATION_ONLY |
| `TASK: / ROLE: / MUTATION AUTHORITY:` preamble an agent types | `AGENTS.md` | DOCUMENTATION_ONLY |
| Percentage recomputed from declared checks | `tools/build/build_progress.py`, `tools/lib/archive_tasks.py` | DURABLE (measures *checks*, not authority) |
| A task id reaching any effectful code path | — | **ABSENT** |

**Required:** `TaskRecord` with a stable id that is presented on every mutating call and recorded in
evidence. Nothing today carries `#NN` past the Markdown file.

### owner

| Representation | Location | Class |
|---|---|---|
| `owner: coder \| garrett` text label | `PROJECT-TASKS.md` | DOCUMENTATION_ONLY |
| Rotation order "Codex → Claude → Codex" | `.claude/CLAUDE.md` | DOCUMENTATION_ONLY |
| "exactly one mutation owner across the complete task tree" | `AGENTS.md`, `GUARDRAILS.md` | DOCUMENTATION_ONLY |
| Peer IP recorded as `by` on a rack power change | `controlboard/__init__.py:299` → `run/` JSON, atomic tmp+rename | DURABLE |
| Shared bearer token (identifies no one) | `studio/gate.py`, `coder.token_ok` | RUNTIME_ENFORCED, but impersonal |

`controlboard` is the only surface in the repo that durably records *who* performed a mutation. It
records an **address**, not an actor — `_guard` returns the peer "for attribution"
(`controlboard/routes.py`). It is the right instinct with the wrong subject, and it is the closest
existing precedent to what §3 specifies.

### session

| Representation | Location | Class |
|---|---|---|
| `run/agent-<id>.json` transcript, client-held | `bin/symoneural-cli:577` `transcript_path` | DURABLE, never sent as identity |
| `Session` dataclass in a module-level dict | `coders/__init__.py:404`, `_remember`/`recent` | IN_MEMORY (lost on API restart) |
| `sessions` table keyed by token hash | `dispatchos/store.py:91` | DURABLE + RUNTIME_ENFORCED |
| A session id reaching `coder` or `studio` | — | **ABSENT** |

`dispatchos` already has the durable session model this plane needs. It was never applied to the
coder/studio control plane.

### role

| Representation | Location | Class |
|---|---|---|
| AUDITOR / OPERATOR / PLANNER / GOVERNOR / SME | `AGENTS.md` | DOCUMENTATION_ONLY |
| Route authorization classes, fail-closed | `dispatchos/authz.py` | RUNTIME_ENFORCED (that app only) |
| `owner: coder \| garrett` | `PROJECT-TASKS.md` | DOCUMENTATION_ONLY |

`dispatchos/authz.py` is the model to copy, including its stated precedence
(`authentication -> class -> entitlement|operator -> ownership`) and its fail-closed rule: *"An
authorization check that could not run has NOT passed."*

### provider

| Representation | Location | Class |
|---|---|---|
| `Provider` dataclass, `CLAUDE_BIN` / `CODEX_BIN` / symon | `coders/__init__.py:99` | IN_MEMORY |
| Per-provider argv flags carrying the read-only posture | `coders/__init__.py:240,279` | RUNTIME_ENFORCED by the provider binary |
| "Provider identity grants no project authority" | `AGENTS.md` | DOCUMENTATION_ONLY |

### lease

| Representation | Location | Class |
|---|---|---|
| GPU mutex: `mkdir` lock + `holder` file (`surface owner_pid`) | `scripts/gpu-governor.sh:43` | DURABLE + RUNTIME_ENFORCED |
| stale break via `kill -0` | `gpu-governor.sh:132` `break_if_stale` | RUNTIME_ENFORCED |
| release refused on claimant mismatch against a live holder | `gpu-governor.sh:350` | RUNTIME_ENFORCED |
| **A mutation lease of any kind** | — | **ABSENT** |

The GPU governor is a working lease state machine on this box with liveness, stale-break, and
conflict refusal already proven. §4 reuses its semantics rather than inventing new ones.

### resource

| Representation | Location | Class |
|---|---|---|
| `SYMONEURAL_CODER_WORKSPACE` — one workspace per **process** | `coder/__init__.py:124` | RUNTIME_ENFORCED, process-global |
| Absolute-segment denylist | `coder/__init__.py:257` | RUNTIME_ENFORCED |
| `studio/workspace.py` ROOT for fs tools | `studio/workspace.py` | RUNTIME_ENFORCED for `fs.*` only |
| `run_command` working directory | `studio/tools_impl/host.py:71` | **unbounded** |
| Per-request or per-lease scope | — | **ABSENT** |

`coder`'s workspace is a strong containment boundary and the wrong *granularity*: it is read from the
environment at call time and is global to the process, so it cannot express "this lease may write
`site/` while that lease writes `backend/apps/remix/`".

### mutation authority

| Representation | Location | Class |
|---|---|---|
| `enabled()` + `peer_ok()` + `token_ok()` | `coder/__init__.py:227` `authorize` | RUNTIME_ENFORCED, binary |
| `enabled()` + `token_ok()` + local bypass | `studio/gate.py` | RUNTIME_ENFORCED, binary |
| `dangerous=True` | `studio/registry.py:209` | DOCUMENTATION_ONLY — *explicitly non-restricting* |
| `permissions: allow\|ask\|deny` from the request body | `studio/agent.py:266` | IN_MEMORY, **client-declared** |
| `--dangerously-allow-all` / `auto` resolution | `symoneural-cli:957` | client-side only |

### parent / child

| Representation | Location | Class |
|---|---|---|
| "A child does not inherit mutation rights merely because its parent has them" | `AGENTS.md` | DOCUMENTATION_ONLY |
| Default child contract (`PROJECT/MUTATION/REPAIR AUTHORITY: NONE`) | `AGENTS.md` | DOCUMENTATION_ONLY |
| Provider sandbox flags on spawned children | `coders/__init__.py:240,279` | RUNTIME_ENFORCED by provider |
| A parent/child link in any record | — | **ABSENT** |

### read-only

| Representation | Location | Class |
|---|---|---|
| `claude --print --safe-mode --no-session-persistence --tools ""` | `coders/__init__.py:240` | RUNTIME_ENFORCED by the provider binary |
| `codex -a never exec --sandbox read-only --ephemeral` | `coders/__init__.py:279` | RUNTIME_ENFORCED by the provider binary |
| `/local/coder/*` mount exposing reads only | `api.py:3936-3980` | RUNTIME_ENFORCED |
| A `read_only` field on a session record | — | **ABSENT** |

`coders` is the best-behaved effectful surface in the repo: it spawns providers in a
`tempfile.TemporaryDirectory` scratch (`coders/__init__.py:542`) with sandbox flags and no tools. The
posture is nonetheless **argv, not scope** — see §7.

### evidence

| Representation | Location | Class |
|---|---|---|
| Journal record `{ts, action, path, workspace, pid}`, fsynced pre-mutation | `coder/_journal:421` | DURABLE, **unattributed** |
| Backups + `.absent` markers under `run/coder-backups/<ws-tag>/` | `coder/__init__.py:476` | DURABLE |
| Dated response + next-plan Markdown | `review/`, `ops/docs/` | DOCUMENTATION_ONLY |
| `{"at", "by"}` on a rack unit | `controlboard/__init__.py:299` | DURABLE |
| Evidence linked to task / actor / session / lease | — | **ABSENT** |

**The single cheapest real win in this whole plan:** `_journal()` already fsyncs a record before every
mutation. It is missing exactly four fields — `task_id`, `actor_id`, `session_id`, `lease_id`. That is
an addition to one function, not a redesign.

### Summary

| Required property | Today |
|---|---|
| Task identity reaches an effectful path | ABSENT |
| Owner identity reaches an effectful path | ABSENT (peer address only, one surface) |
| Mutation lease | ABSENT |
| Per-lease resource scope | ABSENT (process-global workspace only) |
| One mutation owner enforced | ABSENT (documented only) |
| Children cannot inherit write authority | ABSENT (documented only; provider flags coincidentally hold) |
| Provider cannot confer authority | ABSENT as a mechanism (documented only) |
| Effectful paths route through the controlled executor | ABSENT (executor has zero mutation callers) |
| Evidence links to task/session/lease | ABSENT |
| Survives API restart | N/A — nothing to survive |

---

## 3. MINIMAL DATA MODEL

One SQLite file, one host, no distributed system. Nine records. All ids are opaque strings; all
timestamps are `REAL` UTC epoch seconds, matching `dispatchos/store.py`.

Id conventions: `tsk_`, `act_`, `ses_`, `lse_`, `scp_`, `asg_`, `inv_`, `exe_`, `evd_` prefixes, then
16 hex characters from `secrets.token_hex(8)`. The prefix makes a mis-passed id fail loudly instead of
matching the wrong table.

### 3.1 TaskRecord

The runtime shadow of a `PROJECT-TASKS.md` entry. It does **not** replace that file —
`.claude/CLAUDE.md` forbids a second state document, and this is deliberately not one: it is a
reference to a task, holding no description, no checks, and no percentage.

| Field | Type | Notes |
|---|---|---|
| `task_id` | TEXT PK | `tsk_…` |
| `number` | INTEGER UNIQUE | the `#NN` in `PROJECT-TASKS.md`; the only linkage |
| `title` | TEXT | copied for legibility in evidence; never authoritative |
| `state` | TEXT | `open` / `closed`; mirrors archival, does not drive it |
| `authorized_by` | TEXT | `garrett`, always — the sole task authorizer |
| `created_at` / `closed_at` | REAL | |

Creation: an operator command (§11), never automatic. A task appearing in `PROJECT-TASKS.md` does
**not** create one; that would make the Markdown file grant authority, which `GUARDRAILS.md` forbids
("No task list or checkbox can by itself grant mutation authority").
Transitions: `open → closed`. No expiry.
Audit linkage: parent of every lease and every evidence record.

### 3.2 Actor

*Who* — independent of what software they run.

| Field | Type | Notes |
|---|---|---|
| `actor_id` | TEXT PK | `act_…` |
| `kind` | TEXT | `human` / `agent` |
| `label` | TEXT | `garrett`, `symon-coder`, `symon-sme` — an **identity**, never a provider name |
| `secret_hash` | TEXT | SHA-256 of the actor's credential; never the value (GUARDRAILS §Secrets) |
| `default_role` | TEXT | `auditor` / `operator` / `planner` |
| `created_at`, `disabled_at` | REAL | |

Creation: operator command. No self-registration — an unknown credential is a denial, never a new
actor.
Transitions: `active → disabled`. Disabling revokes every live session and lease.

### 3.3 Session

One authenticated run of one actor through one provider. This is the unit that presents credentials.

| Field | Type | Notes |
|---|---|---|
| `session_id` | TEXT PK | `ses_…` |
| `actor_id` | TEXT FK → Actor | |
| `task_id` | TEXT FK → TaskRecord | the authorized task; NULL is not permitted for effectful sessions |
| `role` | TEXT | `auditor` / `operator`; **never** wider than the actor's `default_role` |
| `read_only` | INTEGER | 0/1. A session with `read_only=1` can never hold a lease |
| `parent_session_id` | TEXT FK → Session, nullable | §6 |
| `provider` | TEXT | `claude` / `codex` / `symon` — recorded, never consulted for a decision |
| `token_hash` | TEXT | SHA-256 of the session bearer token |
| `pid` | INTEGER, nullable | the owning OS process, for liveness (§4) |
| `created_at`, `expires_at`, `revoked_at` | REAL | |

Creation: `POST /local/authority/session` presenting an actor credential and a `task_id`.
Expiry: `expires_at` — a hard ceiling, default 12h. An expired session authorizes nothing.
Transitions: `active → expired` (time) / `revoked` (explicit, or parent revoked, or actor disabled).

### 3.4 MutationLease

The exclusive right to mutate a scope. **This is the record the whole plane exists for.**

| Field | Type | Notes |
|---|---|---|
| `lease_id` | TEXT PK | `lse_…` |
| `session_id` | TEXT FK → Session | the holder |
| `task_id` | TEXT FK → TaskRecord | denormalised for query and evidence |
| `scope_id` | TEXT FK → ResourceScope | |
| `state` | TEXT | `active` / `released` / `expired` / `revoked` |
| `acquired_at` | REAL | |
| `renewed_at` | REAL | |
| `expires_at` | REAL | `renewed_at + ttl`; default ttl 900s |
| `owner_pid` | INTEGER | the process that will still be running while the lease is held |
| `owner_boot_id` | TEXT | contents of `/proc/sys/kernel/random/boot_id` at acquisition |
| `released_at`, `released_by`, `release_reason` | REAL/TEXT | `released` / `expired` / `revoked` / `stale-broken` |

**`state` is advisory for `active` rows and authoritative only for terminal ones.** The terminal
states — `released`, `revoked`, and an expiry already swept — cannot un-terminate, so a reader may
trust them. `active` may not be trusted on its own: it means "was active when last swept", and the
sweep is lazy by design (§4 EXPIRE). Every read path must therefore evaluate
`state = 'active' AND expires_at > now AND owner_alive()`, never `state = 'active'` alone. The column
exists so the audit trail records *how* a lease ended; it is a cache of a decision, not the decision.
A reader that trusts it directly is the fail-open bug this plane exists to prevent, and it would pass
every test in §12 that does not manipulate the clock.

`owner_boot_id` is not ceremony. `kill -0` on a recycled pid after a reboot reports *alive* for an
unrelated process, which would make a dead owner's lease look live forever. Comparing the boot id
first turns every pre-reboot lease into an unambiguous `OWNER_DEAD`. The GPU governor does not need
this because its lock directory does not survive a reboot; a SQLite row does.

**Confirmed available on this box, 2026-09-03:** `/proc/sys/kernel/random/boot_id` reads
`c6c8a595-…` (a UUID, regenerated each boot). It is the only mechanism in this plan with no in-repo
precedent, so it was checked rather than assumed. If it is ever unreadable, the fallback is `btime`
from `/proc/stat` (currently `1788451599`), which is the boot wall-clock in seconds — coarser, and
adequate, since the only question asked of it is "same boot or not". Read it once at process start
and cache it; it cannot change without the process dying.

Creation: `ACQUIRE` (§4). Expiry: `expires_at`. Transitions: §4.

### 3.5 ResourceScope

| Field | Type | Notes |
|---|---|---|
| `scope_id` | TEXT PK | `scp_…` |
| `kind` | TEXT | one of the eight in §5 |
| `selector` | TEXT | canonical, normalised — repo-relative POSIX path, unit name, device index |
| `recursive` | INTEGER | 0/1; meaningful for `directory` only |
| `created_at` | REAL | |

Scopes are **interned**: identical `(kind, selector, recursive)` reuses the row, so overlap can be
computed by joining on `scope_id` for the exact case and by the §5 predicate otherwise.

### 3.6 SpecialistAssignment

Binds a named specialist responsibility to a session, so a report can say which specialist produced
it. Names are PLANNED in `SyMoNSaysLLC.md`; this record does not invent any.

| Field | Type | Notes |
|---|---|---|
| `assignment_id` | TEXT PK | `asg_…` |
| `session_id` | TEXT FK | |
| `specialist` | TEXT | e.g. `authority-plane`, `frontend-audit` |
| `brief` | TEXT | the bounded objective |
| `read_only` | INTEGER | 0/1; may only ever be **narrower** than the session's |
| `created_at` | REAL | |

Assignment can restrict and never widen. A specialist assignment on a read-only session cannot make
it writable — the check is `session.read_only OR assignment.read_only`.

### 3.7 ProviderInvocation

One spawn of one provider binary. Records what ran; grants nothing.

| Field | Type | Notes |
|---|---|---|
| `invocation_id` | TEXT PK | `inv_…` |
| `session_id` | TEXT FK | |
| `provider` | TEXT | `claude` / `codex` / `symon` |
| `binary_path`, `binary_sha256` | TEXT | what actually ran |
| `argv_json` | TEXT | the exact argv, JSON array — never a shell string |
| `sandbox_profile` | TEXT | the §7 profile name the argv was **derived from** |
| `started_at`, `finished_at`, `exit_code` | REAL/INTEGER | |

`argv_json` and `sandbox_profile` together are the audit answer to "was this child really read-only?".
Storing both lets a test assert that the argv matches what the profile requires, which is the check
that stops an argv edit from silently creating a write path.

### 3.8 ExecutionResult

One governed mutation attempt. Written for refusals as well as successes — a refusal is the most
important thing this table holds.

| Field | Type | Notes |
|---|---|---|
| `execution_id` | TEXT PK | `exe_…` |
| `session_id`, `task_id`, `lease_id` | TEXT FK | `lease_id` NULL only for a *refused* attempt |
| `primitive` | TEXT | `write_file` / `patch_file` / `delete_file` / `restore` / `run` |
| `target` | TEXT | scope-relative path, or argv[0] for `run` |
| `outcome` | TEXT | `applied` / `refused` |
| `refusal_code` | TEXT | §4/§10 codes: `no_lease`, `wrong_owner`, `lease_expired`, `read_only_session`, `scope_violation`, `denied_path`, `surface_disabled` |
| `backup_version` | TEXT | the `coder` version id, so rollback is reachable from the record |
| `started_at`, `finished_at` | REAL | |

### 3.9 EvidenceRecord

The durable artifact pointer, so a claim can be traced to a file on disk.

| Field | Type | Notes |
|---|---|---|
| `evidence_id` | TEXT PK | `evd_…` |
| `task_id`, `session_id`, `lease_id`, `execution_id` | TEXT FK, nullable | |
| `kind` | TEXT | `journal` / `backup` / `report` / `smoke` / `test-run` |
| `path` | TEXT | repo- or state-dir-relative |
| `sha256` | TEXT | of the artifact at recording time |
| `created_at` | REAL | |

No expiry. Nothing in this plane deletes an evidence row: `GUARDRAILS.md` — "Do not erase failed
evidence".

### Audit linkage, end to end

```
TaskRecord ─┬─ Session ─┬─ SpecialistAssignment
            │           ├─ ProviderInvocation
            │           └─ MutationLease ── ResourceScope
            │                   │
            └───────────────────┴─ ExecutionResult ── EvidenceRecord
                                            └─ coder journal line + backup version
```

Every arrow is a foreign key with `PRAGMA foreign_keys=ON`, as `dispatchos/store.py:206` already does.

---

## 4. LEASE STATE MACHINE

Semantics are lifted from `scripts/gpu-governor.sh`, which is a working mutual-exclusion machine on
this box, and implemented over a SQLite row instead of a lock directory.

What is reused verbatim in behaviour:

- the holder records an **owner pid that will outlive the call** — the governor is explicit that
  recording `$$` is wrong because the script exits, and takes `SYMONEURAL_OWNER_PID` or `$PPID`
  instead (`gpu-governor.sh:313-319`). A lease records the agent process, not the request handler.
- **stale break by liveness**, `kill -0` (`break_if_stale`, line 132).
- **release refuses on claimant mismatch against a live holder** (line 350) — a lease is released by
  its owner or by an explicit operator revoke, never by whoever asked.

What is added: an `expires_at` ceiling (a live-but-wedged owner must not hold a scope forever), the
`owner_boot_id` reboot guard, and scope-overlap conflict rather than one global mutex.

### States

`active` → `released` | `expired` | `revoked`. Terminal states are final; a lease is never reanimated,
a new one is acquired.

### ACQUIRE

`acquire(session_id, scope, ttl) -> lease_id | conflict`

Refuse before anything else, in this order, each with a distinct code:

1. session unknown / expired / revoked → `no_session`
2. `session.read_only = 1` → `read_only_session`
3. `session.role != 'operator'` → `role_insufficient`
4. `session.task_id` is NULL or the task is `closed` → `no_task`
5. effective scope not within the session's authorized scope → `scope_escalation`

Then, in **one SQLite transaction with `BEGIN IMMEDIATE`**:

```
BEGIN IMMEDIATE;
  -- sweep first, inside the same transaction, so a stale row cannot win a race
  UPDATE leases SET state='expired', released_at=:now, release_reason='expired'
    WHERE state='active' AND expires_at < :now;
  -- OWNER_DEAD sweep, evaluated in Python over the candidate rows (see below)
  SELECT * FROM leases WHERE state='active';   -- candidates for overlap
  -- if any surviving active lease overlaps :scope  -> CONFLICT, rollback
  INSERT INTO leases (...) VALUES (...);
COMMIT;
```

`BEGIN IMMEDIATE` is the load-bearing detail: it takes the write lock at statement one, so two
concurrent acquires serialise rather than both reading "no conflict" and both inserting. A deferred
transaction would allow exactly the double-owner this plane exists to prevent.

Liveness (`OWNER_DEAD`) is evaluated in Python during the sweep, not in SQL: compare
`owner_boot_id` against the current boot id — mismatch is dead — then `os.kill(pid, 0)`, treating
`ProcessLookupError` as dead and `PermissionError` as **alive** (a pid owned by another uid exists).

Success writes the lease and an `ExecutionResult`-adjacent audit line. Conflict returns
`409` with the holder's `session_id`, `task_id`, scope selector, and `expires_at` — enough for a
human to decide, and no secret.

### RENEW

`renew(lease_id, session_id) -> expires_at | error`

- lease not `active` → `not_active`
- `lease.session_id != session_id` → `wrong_owner` (**refused, not obeyed** — governor line 350)
- otherwise `renewed_at = now`, `expires_at = now + ttl`.

Renewal never widens scope. A scope change is a release and a fresh acquire, so that the audit trail
shows two leases rather than one lease that quietly grew.

### RELEASE

`release(lease_id, session_id)`

- `wrong_owner` unless the caller is the holding session or an operator invoking the explicit revoke
  path.
- Idempotent on an already-terminal lease: returns the terminal state, not an error, so a crash-retry
  during cleanup is not itself a failure.
- Sets `state='released'`, `released_by=session_id`, `release_reason='released'`.

### EXPIRE

Time-driven, no daemon. Expiry is evaluated **lazily**, inside the `ACQUIRE` sweep and at the top of
every authority check. A background timer is deliberately avoided: a plane whose correctness depends
on a timer having run is a plane that fails open when the timer dies.

Consequence to state plainly: an expired lease may sit in the table as `active` until something looks
at it. That is safe because **every read path treats `expires_at < now` as expired** regardless of the
stored string. The column is a cache of the decision, never the decision.

### CONFLICT

Two sessions want overlapping scopes. The second is refused `409` with the holder's identity. There is
no queue and no wait: `GUARDRAILS.md` requires the agent to "record genuine blockers and continue
unaffected work", and a blocking wait inside an HTTP handler turns a policy refusal into a hang.

### STALE

`state='active'` and `expires_at < now` and the owner is still alive. The lease is expired normally;
the owner discovers it on its next call and receives `lease_expired`. It must re-acquire, and the
re-acquire may lose to someone else — which is correct, because an owner that stopped renewing for
longer than the ttl stopped holding the scope.

### OWNER_DEAD

`state='active'`, owner not alive by the boot-id + `kill -0` test. The lease is broken with
`release_reason='stale-broken'` and the break is written to the journal at `warning`, exactly as the
governor logs `stale "holder pid $pid is gone -- breaking the lock"`. A broken lease is never silently
reused: the row keeps its identity so the audit shows a lease that ended by death rather than release.

### RECOVERED

An owner returns after its lease was broken — it crashed, it was restarted, or it was `SIGSTOP`ped
past the ttl. Its next authority check finds no `active` lease for its id and returns
`lease_expired` / `wrong_owner`. **It must not auto-acquire.** Recovery is: re-acquire explicitly,
which may conflict, which is the honest answer.

### Required behaviour under each failure

| Event | Behaviour |
|---|---|
| **API restart** | Leases are rows in SQLite; they survive. On the first authority check after restart the sweep runs: rows whose owner pid is gone are `OWNER_DEAD`-broken, rows past ttl are expired, live owners keep their leases. **The API process is not the owner** — the owning pid is the agent/CLI process — so an API restart alone must not break a live lease. |
| **CLI crash** | Owner pid dies. Next sweep breaks the lease as `OWNER_DEAD`. |
| **provider crash** | The provider is a child of the session process and holds no lease (§7). Its death changes nothing in the plane; the `ProviderInvocation` row records the exit code. |
| **process death** | As CLI crash. |
| **manual recovery** | `symoneural-cli authority lease break <lease_id> --reason "..."` — operator-only, writes `release_reason='revoked'` and the reason. Never silent. |
| **stale lease** | See STALE. |
| **conflicting lease** | `409` with holder identity. No queue. |
| **non-overlapping scope** | Granted concurrently. This is the point of scope: two agents working `site/` and `backend/apps/remix/` are not in conflict and must not be serialised. |

---

## 5. RESOURCE SCOPE MODEL

### Kinds and selectors

| kind | selector, canonical form | example |
|---|---|---|
| `repository` | the repo root, literal `/` | `/` |
| `directory` | repo-relative POSIX dir, no trailing slash, no `.`/`..` | `backend/apps/remix` |
| `file` | repo-relative POSIX file path | `site/coder.html` |
| `service` | systemd unit name | `symoneural-api.service` |
| `runtime` | runtime id from the existing registry | `comfyui`, `llama-cpp` |
| `gpu` | device index, or `*` | `0` |
| `deployment` | environment id | `production`, `staging` |
| `sysconfig` | absolute path outside the repo, or a config domain | `/etc/symoneural/api.env` |
| `yocto` | layer or tree under `yocto/` | `yocto/meta-symoneural` |

`yocto` is deliberately its own kind rather than a `directory`: `GUARDRAILS.md` holds native platform
work behind separately named owner-authorized tasks, so a repository-wide lease must **not** silently
confer authority over the Yocto tree. Overlap for `yocto` is therefore asymmetric — see below.

Canonicalisation happens once, at scope creation: resolve, reject any path escaping the repo root
(reusing `coder._resolve`'s containment rule), strip trailing separators, reject `..`. A scope that
cannot be canonicalised is refused; an uncanonicalised selector must never reach the table, because
overlap would then be a string comparison between two spellings of the same directory.

### Overlap predicate

Two scopes A and B overlap iff:

1. **Different kinds never overlap**, with three explicit exceptions:
   - `repository` overlaps every `directory` and `file` — but **not** `yocto`, `sysconfig`,
     `service`, `runtime`, `gpu`, or `deployment`. A repo lease is a source-tree lease.
   - `directory` overlaps a `file` when the file is at or beneath the directory.
   - `directory` overlaps a `directory` when either is a prefix of the other on a path-segment
     boundary.
2. Same kind, same selector → overlap.
3. `service` / `runtime` / `gpu` / `deployment` / `sysconfig` overlap **only** on exact selector
   equality, except `gpu` where selector `*` overlaps every index.

Prefix matching is on **path segments**, never on string prefix. `backend/apps/coder` must not overlap
`backend/apps/coders`. This is the exact bug `coder/__init__.py:266` records having already shipped
once, where a segment-exact denylist entry let `training/adapter-qwen36` through while denying
`training/adapter`. Same failure mode, opposite direction; the plan must not re-introduce it.

### Conflict semantics

Two `active` leases may not hold overlapping scopes. Non-overlapping scopes are granted concurrently
and unconditionally — that is the feature, not a concession.

`repository` is not the default. A session requesting `repository` when the task's authorized paths
name three directories is a `scope_escalation` refusal, not a convenience.

---

## 6. PARENT / CHILD DELEGATION

A mutation owner may create read-only specialists. **Children never inherit write authority**, and
this must be structural rather than a default that could be overridden.

### The record

A child session carries `parent_session_id`, its own `session_id`, `role`, `read_only`, an authorized
scope no wider than the parent's, and its own `provider`. It holds **no** lease and cannot acquire one.

### The four runtime checks

1. **At creation** — `create_child_session()` sets `read_only = 1` unconditionally. There is no
   parameter to set it to 0. Making a writable child requires a *new* session created against the
   task with its own actor credential, which is a different act with a different audit trail.
2. **At acquire** — `ACQUIRE` refuses `read_only_session` before touching the lease table (§4 step 2).
3. **At execute** — the controlled executor refuses `read_only_session` independently, without
   consulting the lease table at all. Two independent refusals, so a bug in the lease sweep cannot
   produce a writable child.
4. **At scope** — a child's authorized scope is intersected with the parent's at creation, never
   unioned. `scope_of(child) ⊆ scope_of(parent)` is an invariant asserted at creation and re-asserted
   on every check.

### Lease relationship

The parent's lease is **not** shared with, delegated to, or borrowed by the child. If a child needs a
mutation performed it returns a proposal to its parent, and the parent executes under its own lease.
That is the same shape AGENTS.md already specifies for reports ("The parent reconciles findings and
applies the task-gate verdict") — this plan makes it the only mechanically possible shape.

### Cascade

Revoking or expiring a parent session revokes every descendant session in the same transaction
(recursive CTE over `parent_session_id`). A child outliving its parent is an orphan with credentials,
which is precisely the thing the one-owner rule forbids.

---

## 7. PROVIDER ≠ AUTHORITY

Symon, Claude, and Codex are **providers**: interchangeable engines that produce text and propose
tool calls. They are not authorization principals.

### The separation, structurally

`provider` appears on `Session` and `ProviderInvocation` as a **recorded** field. It appears in **no**
authorization predicate anywhere in the plane. The concrete rule for review, and the thing the test in
§12.9 asserts:

> `grep -n "provider" backend/apps/authority/authz.py backend/apps/authority/leases.py` returns
> only field assignments and audit writes — never a comparison, never a branch.

Changing `session.provider` from `claude` to `codex` and re-running any authority decision must
produce a byte-identical verdict. That is the whole property, and it is testable directly.

### Provider selection cannot grant permission

`POST /local/coders/ask` selects providers. That route must not be able to create a session, mint a
lease, or widen a scope. It runs providers **inside** the authority of the session that called it,
and if that session is read-only, so is everything it spawns.

### Sandbox profiles: derive the argv from the scope

This is the substantive fix, and it is aimed at a real weakness in the best-behaved code in the repo.
`coders/__init__.py:240,279` expresses the read-only posture as per-provider flag strings:

```
claude --print --output-format json --safe-mode --no-session-persistence --tools ""
codex  -a never exec --json --skip-git-repo-check --sandbox read-only --ephemeral -
```

Those are correct today. They are also *strings in a list*, chosen per provider, with nothing checking
that they still mean read-only. Editing one argv is enough to create a write path, and no record, test,
or reviewer would notice.

So: define a `SandboxProfile` — `read_only`, `scoped_write`, `unrestricted` — and make each provider
adapter a pure function `argv(profile, scope) -> list[str]` that **raises** when it cannot express the
profile. A provider that has no read-only mode is unavailable at that profile; it is not silently run
without one. The profile name and the resulting argv are both persisted on `ProviderInvocation`, and
§12.9's test asserts they agree. The posture then lives in the plane and the argv is derived from it,
which is the inverse of today.

---

## 8. CONTROLLED EXECUTOR

### The five primitives

`coder.write_file` (682), `patch_file` (719), `delete_file` (761), `restore` (813), `run` (914).

Today each takes `*, token, peer` and calls `_guard(token, peer)`. The change is to replace that pair
with one authority context and to refuse without it:

```python
@dataclasses.dataclass(frozen=True)
class Authority:
    session_id: str
    task_id: str
    lease_id: str
    actor_id: str
    scope_id: str
    workspace: pathlib.Path      # resolved from the SCOPE, not from the environment
```

Signature becomes `write_file(path, content, *, authority: Authority)`. **`authority` is
keyword-only and has no default**, so every existing caller fails at import/call time rather than
silently running unauthorized. A default of `None` checked at runtime would let a missed call site
reach production; a missing required argument cannot.

Each primitive then, in order, before any I/O:

1. `authz.verify(authority)` — session active, not read-only, role operator, task open, lease
   `active` and owned by that session and not past `expires_at` (re-evaluated, never trusted from the
   row), owner alive.
2. Resolve the target **against `authority.workspace`**, which comes from the leased scope. This is
   the change that makes containment per-lease instead of per-process: `workspace()` reading
   `SYMONEURAL_CODER_WORKSPACE` stays as the *outer* bound, and the scope narrows within it. The
   effective root is the intersection, so a scope can never widen what the environment permits.
3. Existing `_denied_reason` denylist — unchanged, and still evaluated on the absolute path.
4. `_journal(...)` with the four new fields — still before the mutation, still fsynced.
5. Write `ExecutionResult`.

A refusal at any step writes an `ExecutionResult` with `outcome='refused'` and the code, then returns
`{"ok": False, "error": ...}`. Refusals are evidence.

`run` needs one addition beyond the above: its argv is already checked against the denylist
(`_argv_touches_denied`, line 884), and it gains a scope check on the working directory plus
persistence of the full argv, so that a governed `run` is auditable to the same standard as a
governed write.

### Route classification

Every first-party effectful route, classified as required.

#### Studio

| Route | File | Classification |
|---|---|---|
| `POST /api/studio/tool/{name}` | `studio/routes.py:393` | **DISABLE** |
| `POST /api/studio/agent` | `studio/routes.py:485` | **ROUTE_THROUGH_CODER** |
| `POST /api/studio/queue` | `studio/routes.py:558` | **EXPLICIT EXCEPTION** |
| `POST /api/studio/interrupt` | `studio/routes.py:627` | **EXPLICIT EXCEPTION** |
| tools `write_file`, `delete_path` | `studio/tools_impl/fs.py:195,220` | **ROUTE_THROUGH_CODER** |
| tools `run_command`, `env_set` | `studio/tools_impl/host.py:70,160` | **ROUTE_THROUGH_CODER** |
| tools `list_dir`, `read_file`, `search`, `find_files`, `stack.*`, `env_get`, `*_status` | `fs.py`, `stack.py`, `host.py` | **READ_ONLY** — unchanged |

**`POST /api/studio/tool/{name}` is DISABLE, and it is the sharpest hole in the system.** It is worth
separating from `/agent` explicitly, because the agent loop at least *has* a gate concept —
`gated`, `permission_required`, and a deliberate refusal to run the tail of a tool-call set whose head
was not approved (`studio/agent.py:381-392`). The direct-tool route has none of that. Its only check
is `_guard(request)`, the token. It runs any registered tool, including `run_command`, with no model,
no gate, and no record. Its own docstring says *"No page calls it… These four are an operator surface,
reached with `curl` and a token."*

Since no page calls it, disabling costs nothing that a governed path does not replace. It is replaced
by `POST /local/authority/execute` (§10), which takes the same arguments plus a lease and is local-only.
Recommend `410 Gone` with the replacement named, not `404`: an operator who has this in a script needs
to be told where it went.

`/agent`: the loop keeps its structure, but the four dangerous tools dispatch into `coder` under the
session's `Authority`, and — critically — **the permission mode stops being client-supplied**. The
server derives it from the session: `read_only` or no lease → `deny`; operator with a live lease →
`allow` within scope. The request field is retained only as a **narrowing** hint: a caller may ask for
`ask`/`deny` when it would otherwise be allowed, and may never ask for `allow`. This is the direct
answer to §10's "no permissions auto shortcut may bypass runtime authority" — `auto` resolves on the
server, from the lease, and the client's resolution becomes advisory.

The `dangerous=True` flag stays and stops being a label: `registry.call` refuses a `dangerous` tool
that arrives without an `Authority`. `studio/registry.py:212`'s docstring must be rewritten in the
same commit — a comment that says the flag restricts nothing, sitting above a flag that now restricts
something, is the drift this repo's own rules are most alert to.

`/queue` and `/interrupt` are the **explicit exceptions**, and the reasons are specific rather than
convenience:

- `/queue` submits a **ComfyUI graph**, not a host mutation. Its effect is GPU work and files under
  the Comfy output directory. It is already governed by a different, working mechanism — the GPU lease
  cycle in `comfy.py` and `scripts/gpu-governor.sh`. Bringing it under the mutation plane would
  create *two* leases for one activity and a deadlock between them. It stays out, and the boundary is
  stated in code: `/queue` may not write outside the Comfy output tree.
- `/interrupt` cancels work already submitted. Requiring a mutation lease to *stop* something is
  backwards — it would make a wedged job unstoppable by anyone who could not acquire a lease. Cancel
  is authorized by session, not by lease.

#### Coders (plural)

| Route | Classification |
|---|---|
| `POST /local/coders/ask`, `/session/{sid}/debate` | **READ_ONLY** — with the §7 profile change |
| `POST /local/coders/session/{sid}/decide` | **READ_ONLY** — records an operator choice |
| `GET /providers`, `/session/{sid}`, `/sessions` | **READ_ONLY** |

These spawn providers read-only in a temp scratch dir and are already local-only via `_require_local`.
No bypass exists **today**; the change is to derive the sandbox argv from a profile (§7) so that none
can be introduced by editing a flag list. `/decide` records a decision and must be bound to a session
so the choice is attributable — currently it is anonymous.

> **Observed changing during this audit, 2026-09-03.** `coders/routes.py` gained a second gate while
> this document was being written: `_require_enabled`, applied as a router-level dependency so a route
> added later inherits it, checked **per request** rather than at mount time, answering `404` when the
> switch is off. That is a strict improvement and it does not change the classification above — it
> narrows the surface further. Two points it settles for this plan: per-request evaluation of a switch
> is the right pattern and §10's routes should follow it rather than reading the environment at import;
> and router-level dependencies are the correct place to put a gate that must not depend on the next
> author remembering. The mutation owner should re-read this file before executing §8, since it moved
> under the audit.

#### Coder (singular)

| Route | Classification |
|---|---|
| `GET /local/coder/{status,ls,file,history,journal}` | **READ_ONLY** — unchanged, correct today |

#### Controlboard / rack

| Route | Classification |
|---|---|
| `POST /api/rack/power/{unit_id}` | **EXPLICIT EXCEPTION**, narrowed |
| `GET /api/rack/power` | **READ_ONLY** |

Scope kind `service`. It is an exception because it is a bounded, allow-listed, reversible operator
switch: `TOGGLEABLE` is five ids (`controlboard/__init__.py:127`), the state is one JSON file written
atomically, and there is deliberately no bulk-off route. Requiring a mutation lease to flip a surface
offline during an incident would be a safety regression.

The narrowing: it currently records `by = peer address`. It must record `actor_id` and `session_id`
when a session token is presented, keeping the peer as a fallback. It is the only surface already
attributing mutations, and it is attributing them to an address.

#### Miners

| Route | Classification |
|---|---|
| `POST /api/gpuminer/control` | **EXPLICIT EXCEPTION** — scope kind `gpu` |
| `POST /api/asicminer/scan` | **READ_ONLY** — network discovery, mutates nothing here |
| `POST /api/asicminer/emulator` | **ROUTE_THROUGH_CODER** — scope kind `runtime` |

`gpuminer/control` starts a process that takes the GPU from every other surface. It is already
arbitrated by the GPU governor, which is the correct lease for that resource — the same argument as
`/queue`. It stays an exception **and** gains attribution, because "who started the miner" is exactly
the question an audit asks.

`asicminer/emulator` starts and stops a QEMU process. Nothing arbitrates it today. It is a runtime
mutation and belongs under a `runtime` lease.

#### Local intake

| Route | Classification |
|---|---|
| `POST /local/intake` | **EXPLICIT EXCEPTION** |
| `POST /local/tasknote` | **EXPLICIT EXCEPTION** |

These are Garrett's own two controls (Ready / Drop) and the append-only task comment box. They write
`INTAKE.md` and `PROJECT-TASKS.md`. They are excepted because **they are the human authorization
input to this plane**. Requiring a task-scoped mutation lease to authorize a task is circular: the
owner could not tick Ready without first holding a lease he could only get from a task he had not yet
authorized. They keep their existing peer check, which refuses proxy headers.

This exception must be written down as narrowly as it is meant: `/local/intake` and `/local/tasknote`
may write those two files and nothing else.

#### Every exception, restated

| Route | Why it is not routed through the executor |
|---|---|
| `/api/studio/queue` | GPU/graph work, already arbitrated by the GPU governor; a second lease would deadlock against the first |
| `/api/studio/interrupt` | Cancellation must not require an acquirable resource, or a wedged job becomes unstoppable |
| `/api/rack/power/{id}` | Five-id allow-list, atomic, reversible incident control; a lease requirement is a safety regression |
| `/api/gpuminer/control` | Same GPU-governor argument as `/queue` |
| `/local/intake`, `/local/tasknote` | The human authorization input; gating it on a lease is circular |

Everything not in that table is `READ_ONLY`, `ROUTE_THROUGH_CODER`, or `DISABLE`.

---

## 9. DURABLE PERSISTENCE

**One SQLite database in WAL mode at `run/authority.sqlite3`, mode 0600.**

Follow `backend/apps/dispatchos/store.py` exactly: `PRAGMA journal_mode=WAL` (line 76),
`PRAGMA foreign_keys=ON` (line 206), `CREATE TABLE IF NOT EXISTS` at `init_db()`, path overridable by
environment for tests. That module is already in this repo, already carries a security test
(`test_dispatchos_security.py`), and already solved the schema-migration trap it documents at line 210
(`CREATE TABLE IF NOT EXISTS` does not add a column to an existing table).

Why the alternatives lose, stated so the choice is reviewable:

- **The governor's `mkdir` mutex** (`gpu-governor.sh:43`) gives atomic acquisition, liveness, and
  stale-break, and it is proven here. It cannot answer "does this scope overlap any held scope" —
  it is one global lock — and it keeps no audit trail. Its *semantics* are reused (§4); its
  *mechanism* cannot express scope.
- **`capture/store.py`'s flock append** (line 112) gives a durable, concurrency-tested audit log, and
  its test suite proves records do not tear under 8 concurrent writers. It has no atomic
  compare-and-swap, so lease acquisition would be read-then-write with a race in the middle.
- **A JSON state file with tmp+rename**, as `controlboard` uses, is atomic per write but has no
  multi-row transaction, so the acquire sweep and the insert could not be one operation.
- **Anything networked** — Redis, Postgres — adds a daemon, a failure mode, and a second box's worth
  of operational surface to a one-host problem. The mission says not to introduce a distributed system
  unless genuinely necessary. It is not.

SQLite with `BEGIN IMMEDIATE` gives all four requirements in one file: atomic acquire, durable across
restart, queryable audit, and inspectable with `sqlite3 run/authority.sqlite3 'select …'` by a human
at a terminal.

Requirements check:

| Requirement | How |
|---|---|
| survive API restart | rows on disk; the API is not the lease owner (§4) |
| atomic enough for one host | `BEGIN IMMEDIATE` serialises writers; WAL keeps readers unblocked |
| auditable | five linked tables, every refusal recorded |
| recoverable | boot-id + `kill -0` sweep; explicit operator break with a reason |
| easy to inspect | `sqlite3` CLI; plus `symoneural-cli authority …` (§11) |
| supports expiry/conflict | `expires_at` re-evaluated on read; overlap predicate (§5) |
| links executions to evidence | `ExecutionResult.execution_id` ← `EvidenceRecord`, plus the journal line |

The `coder` journal at `run/coder.log` **stays**. It is not replaced by the database: it is
append-only, fsynced, written before the mutation, and readable when SQLite is not. The database is
the authority state; the journal is the tamper-evident mutation trail. Two records of different kinds,
not two state documents.

---

## 10. EXACT API CHANGES

### New: `backend/apps/authority/`

| File | Contents |
|---|---|
| `store.py` | schema, `init_db()`, `db_path()`, connection helper — modelled on `dispatchos/store.py` |
| `scope.py` | canonicalisation, `overlaps(a, b)`, `within(inner, outer)` |
| `leases.py` | `acquire` / `renew` / `release` / `revoke` / `sweep`, the §4 machine |
| `authz.py` | `verify(authority) -> None \| raises Denied`; the single decision point |
| `sessions.py` | actor auth, session create, `create_child_session`, cascade revoke |
| `routes.py` | the `/local/authority/*` router |
| `__init__.py` | re-exports; no FastAPI import at module top (the `studio/__init__.py` PEP 562 reason) |

### New routes — all under `/local`, all local-only

`/local/*` is not delegated by `ops/Caddyfile` (zero matchers), which `api.py:4033` already relies on
for `/local/coders/*`. Mounting the authority plane anywhere under `/api` would publish it.

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/local/authority/session` | authenticate an actor, open a session for a task |
| `POST` | `/local/authority/session/{sid}/child` | read-only child; `read_only` not a parameter |
| `DELETE` | `/local/authority/session/{sid}` | revoke, cascading to descendants |
| `POST` | `/local/authority/lease` | ACQUIRE |
| `POST` | `/local/authority/lease/{lid}/renew` | RENEW |
| `POST` | `/local/authority/lease/{lid}/release` | RELEASE |
| `POST` | `/local/authority/lease/{lid}/break` | operator break, reason required |
| `GET` | `/local/authority/leases` | held leases, holders, scopes, expiry |
| `POST` | `/local/authority/execute` | the governed mutation entry point — replaces `/api/studio/tool/{name}` |
| `GET` | `/local/authority/evidence?task_id=` | executions and evidence for a task |

Refusal codes, uniform across every route, `403` unless noted: `no_session`, `read_only_session`,
`role_insufficient`, `no_task`, `no_lease`, `wrong_owner`, `lease_expired`, `scope_escalation`,
`scope_violation`, `denied_path`, `surface_disabled`. `CONFLICT` is `409`.

### Changed: `backend/apps/coder/__init__.py`

1. Add the `Authority` dataclass.
2. `write_file`, `patch_file`, `delete_file`, `restore`, `run`: replace `*, token, peer` with
   `*, authority: Authority` — **required, keyword-only, no default**.
3. `_journal()`: add `task_id`, `actor_id`, `session_id`, `lease_id` to the record. Four fields on a
   function that already fsyncs before the mutation.
4. `_resolve()`: take the effective root as a parameter — `min(scope_root, workspace())` by
   containment — instead of always reading `workspace()`.
5. Read-side functions keep `token`/`peer`; the read mount does not change.

### Changed: `backend/apps/studio/`

1. `routes.py:393` `POST /tool/{name}` → `410 Gone`, naming `/local/authority/execute`.
2. `routes.py:485` `POST /agent`: resolve `permissions` **server-side** from the session and lease;
   accept the request field only as a narrowing hint.
3. `agent.py`: dangerous-tool dispatch calls `coder` under the session's `Authority`.
4. `registry.py`: `call()` refuses a `dangerous` tool with no `Authority`; rewrite the line-212
   docstring in the same commit.
5. `tools_impl/fs.py` `write_file`/`delete_path` and `tools_impl/host.py` `run_command`/`env_set`
   become thin adapters onto the `coder` primitives. They stop being independent implementations —
   which also removes the second `write_file` in the codebase.

### Changed: `backend/server.py`

1. Include the authority router at `/local/authority` with the same `_require_local` dependency
   `/local/coders` uses.
2. `authority.store.init_db()` at startup, beside the other lazy initialisers.
3. `/api/rack/power/{unit_id}` and `/api/gpuminer/control`: accept an optional session token and
   record `actor_id`/`session_id`, peer as fallback.
4. `/api/asicminer/emulator`: require a `runtime` lease.

---

## 11. EXACT CLI CHANGES

### `bin/symoneural-cli`

New `authority` subcommand group:

```
symoneural-cli authority login   --actor <label>            -> writes run/authority-session.json (0600)
symoneural-cli authority task    --number <NN>              -> binds the session to a task
symoneural-cli authority acquire --scope <kind>:<selector> [--ttl 900]
symoneural-cli authority renew | release
symoneural-cli authority status                             -> session, task, lease, scope, expiry
symoneural-cli authority leases                             -> every held lease on the box
symoneural-cli authority break   <lease_id> --reason "..."  -> operator only
```

`run/authority-session.json` holds `session_id`, `task_id`, `lease_id`, `actor_id`, `expires_at`, and
the session token, mode 0600. It is the client-side handle, deliberately shaped like the existing
`run/agent-<id>.json` transcript so there is one place a client keeps its state.

Changes to the existing agent path:

1. `api_open()` (line 511) sends `X-Symoneural-Session` and `X-Symoneural-Lease` alongside the
   existing token header, read from `run/authority-session.json`.
2. `resolved_permissions()` (line 957) keeps resolving `auto` from tty presence, and its result is
   now labelled a **request**, not a decision. The server decides. `--dangerously-allow-all` can no
   longer produce `allow` on its own; it can only decline to narrow. Its help text must say so.
3. `status_line()` (line 973) gains the lease and its remaining ttl. The existing rationale for
   showing the permission mode — *"A status line reading `auto` while the loop is denying is a lie
   shaped like a setting"* — applies with more force to a lease that expires in 40 seconds.
4. `cmd_tool()` (line 739) retargets from `/api/studio/tool/{name}` to
   `/local/authority/execute`, and refuses locally with a clear message when no lease is held —
   rather than sending a request that will be refused.
5. Renewal: `stream_turn()` renews the lease between steps of a long turn. A turn outliving its ttl
   because the model thought for 16 minutes must not lose the lease mid-edit.

### `bin/symoneural-code`

It is a flag translator with no engine, and it should stay that way. One change: before
`exec "$CLI" repl`, if `run/authority-session.json` is absent or expired, print the one-line hint
naming `symoneural-cli authority login`. It must **not** auto-acquire — a wrapper that silently
acquires a mutation lease because someone opened a prompt is exactly the "permissions auto shortcut"
the mission forbids.

`-p/--print` (one-shot, pipeable) stays read-only unless a lease is already held. A pipe is not a
session and there is nobody to ask.

---

## 12. EXACT TESTS

New file `backend/apps/test_authority_plane.py`, plus additions to `test_coder.py` and `test_studio.py`.
All fourteen from the mission, each with its assertion.

`.claude/CLAUDE.md`'s rule from #94 and #74 applies directly: `exists`/`grep` checks cannot prove
enforcement. Tests 12.7 and 12.12 in particular **must be real runs**; a file-presence check would go
green over a plane that refuses nothing.

| # | Test | Assertion |
|---|---|---|
| 1 | `test_owner_acquires_lease` | operator session + open task + scope → `active` lease; row present after reopening the connection |
| 2 | `test_second_conflicting_owner_denied` | session B acquires the same/overlapping scope → `409`, code `conflict`, body names holder's `session_id`; still exactly one `active` row |
| 3 | `test_non_overlapping_scope_allowed` | `site/` and `backend/apps/remix` concurrently → both `active`. Also asserts `backend/apps/coder` vs `backend/apps/coders` do **not** overlap (the segment-boundary rule, §5) |
| 4 | `test_wrong_owner_denied` | session B calls `renew`/`release`/`execute` with A's `lease_id` → `wrong_owner`; A's lease unchanged |
| 5 | `test_expired_lease_denied` | freeze clock past `expires_at`, then `execute` → `lease_expired`; **and the file on disk is unchanged** |
| 6 | `test_stale_recovery` | owner alive, ttl passed → lease expires; owner's next call gets `lease_expired`; owner re-acquires successfully; a *third* session could have won in between |
| 7 | `test_api_restart_persistence` | **real run.** Start uvicorn in a subprocess, acquire a lease from a separate owner process, SIGTERM and restart the API, query `/local/authority/leases` → the lease is still `active` and still owned. Then kill the owner process, sweep → `OWNER_DEAD`, `release_reason='stale-broken'` |
| 8 | `test_read_only_child_denied` | `create_child_session` on a lease-holding parent → `read_only=1`; child `acquire` → `read_only_session`; child `execute` → `read_only_session` **without consulting the lease table** (assert via a patched lease lookup that must not be called) |
| 9 | `test_provider_cannot_self_authorize` | (a) flip `session.provider` across `claude`/`codex`/`symon` and assert every `authz.verify` verdict is byte-identical; (b) assert `provider` appears in no comparison in `authz.py`/`leases.py`; (c) assert a `read_only` profile's persisted argv matches the profile's required flags for each provider adapter |
| 10 | `test_scope_escalation_denied` | session authorized for `site/` acquires `repository` → `scope_escalation`; acquires `site/../backend` → refused at canonicalisation; `yocto/…` under a `repository` lease → refused (§5 asymmetry) |
| 11 | `test_evidence_references_task_session_lease` | after a successful write, the `coder` journal's last line carries all four ids **and** an `ExecutionResult` row joins to task/session/lease; a *refused* attempt also writes a row, with `refusal_code` |
| 12 | `test_controlled_executor_refuses_missing_authority` | **real run.** `coder.write_file(path, content)` with no `authority` raises `TypeError` (required kwarg); with a fabricated `Authority` whose `lease_id` is unknown → refused and **the file is not created**. Assert on the filesystem, not the return value |
| 13 | `test_studio_bypass_path_refused` | `POST /api/studio/tool/run_command` → `410`; `POST /api/studio/agent` with `permissions:"allow"` from a read-only session → the dangerous tool does **not** execute (assert via a sentinel file that is never created); `registry.call` on a `dangerous` tool with no `Authority` → refused |
| 14 | `test_coders_bypass_path_refused` | `/local/coders/ask` from a read-only session → providers spawn with the `read_only` profile; a provider adapter asked for `scoped_write` when it cannot express it → raises rather than dropping the flag; every route refuses a non-loopback peer and refuses forged `x-forwarded-*` |

Two suite-level additions:

- `test_route_matrix_authority.py` — assert every effectful route carries one of the four
  classifications, so a new effectful route added without one **fails the suite**. This is what stops
  the plane decaying.

  **It must call `apps.route_matrix.collect(app)` and must not enumerate routes itself.** That module
  already walks `app.routes` — the same structure Starlette matches requests against — and it exists
  because a route list inferred from a UI label or a curl transcript produced a false "25 broken
  endpoints" report on 2026-08-26. Its own docstring states the rule: *"a route list must be READ FROM
  THE ROUTER, never inferred."* A second enumeration would be a second route matrix that can disagree
  with the first, which is the same failure `.claude/CLAUDE.md` forbids for state documents.

  The two classifications are **orthogonal and both are needed**: `route_matrix`'s existing axis is
  registration (`REGISTERED EXACTLY` / `NOT REGISTERED` / `WEBSOCKET`) — *does this path exist*. The
  new axis is authority (`ROUTE_THROUGH_CODER` / `READ_ONLY` / `DISABLE` / `EXPLICIT_EXCEPTION`) —
  *what may it do*. Add the second as a table in the new test file keyed by `(path, method)` from
  `collect()`, leaving `route_matrix.py` itself unchanged so the 2026-08-26 lesson keeps its own home.
- Extend `backend/apps/test_sabotage_matrix.py` with the §12.5/§12.12 negative cases, following the
  repo rule that a behaviour change must be provable by breaking it on purpose.

### Task checks for `PROJECT-TASKS.md`

Per `.claude/CLAUDE.md`, one check must be something only a real run turns green:

```
check: exists backend/apps/authority/store.py
check: exists backend/apps/test_authority_plane.py
check: ngrep "def call_tool" -- backend/apps/studio/routes.py
check: exists backend/apps/authority/SMOKE-authority.md
```

The SMOKE file is the run-proving check: it cannot be written honestly without starting the API,
acquiring a lease, restarting the API, observing the lease survive, killing the owner, and observing
the stale break. #94 archived itself on eighteen green checks over a dead surface; a stamped smoke
record is the cheap defence and this plan should not repeat that failure.

---

## 13. ORDERED IMPLEMENTATION PLAN FOR THE MUTATION OWNER

Each step is independently committable, leaves the tree working, and states its own proof. Steps 1–4
add capability without changing any existing behaviour; the first behaviour change is step 5.

| # | Step | Proof it worked |
|---|---|---|
| 1 | `authority/store.py` + `scope.py`. Schema, `init_db()`, canonicalisation, overlap predicate. No routes, nothing wired. | Unit tests 12.3 and 12.10's canonicalisation cases pass. `coder` vs `coders` non-overlap asserted. |
| 2 | `authority/sessions.py` + `leases.py`. The §4 machine over the schema, with `BEGIN IMMEDIATE`, the boot-id + `kill -0` sweep, and cascade revoke. Still no routes. | Tests 12.1, 12.2, 12.4, 12.5, 12.6, 12.8. |
| 3 | `authority/authz.py` — the single `verify()`. Fail-closed, following `dispatchos/authz.py`'s stated rule. | Test 12.9(a)(b): provider-invariance and no provider comparison. |
| 4 | `authority/routes.py` mounted at `/local/authority`, `init_db()` at startup. Read routes and lease routes only; **not** `/execute` yet. | Test 12.7 — the real-run restart test. This is the milestone: durable, restart-surviving leases with nothing yet depending on them. |
| 5 | `coder`: `Authority` dataclass, five primitives take it as a required kwarg, `_journal` gains four fields, `_resolve` takes an effective root. **First behaviour change.** Migrate `backend/apps/coder/test_coder.py` in the same commit — see below. | Tests 12.11, 12.12. Break it on purpose: remove the `verify()` call and watch 12.12 fail. |
| 6 | `POST /local/authority/execute` wired to the primitives. There is now a governed mutation path end to end. | A real write through `/execute` under a lease; the journal line carries four ids; the backup version restores it. |
| 7 | `symoneural-cli authority` subcommands, `run/authority-session.json`, headers on `api_open`. | `authority login → task → acquire → execute → release` by hand, recorded in the SMOKE file. |
| 8 | Studio: `/tool/{name}` → `410`; `registry.call` refuses `dangerous` without `Authority`; rewrite the `registry.py:212` docstring in the same commit. | Test 12.13, first two assertions. **This closes the publicly-routable hole and is the highest-value single commit in the plan.** |
| 9 | Studio `/agent`: server-derived permission mode; dangerous tools dispatch into `coder`; `fs.py`/`host.py` become adapters. | Test 12.13 in full. The second `write_file` implementation is gone. |
| 10 | `symoneural-cli` permission mode becomes a narrowing request; `status_line` shows the lease; `cmd_tool` retargets; mid-turn renewal. | Test 12.13 plus a long-turn renewal run. |
| 11 | Coders: `SandboxProfile`, provider adapters as `argv(profile, scope)` raising when inexpressible, `ProviderInvocation` persisted, `/decide` bound to a session. | Test 12.14, test 12.9(c). |
| 12 | Attribution on the exceptions: rack power and gpuminer record `actor_id`/`session_id`; asicminer emulator requires a `runtime` lease. | Rack toggle records an actor, not an address. |
| 13 | `test_route_matrix_authority.py` — every effectful route classified or the suite fails. Write `SMOKE-authority.md` from a real run. | Add an unclassified `POST` route and watch the suite go red. |

**Step 5 turns `test_coder.py` red, and that is the signal it worked.** That file is ~38 KB and is the
only existing caller of the five mutation primitives. Making `authority` a required keyword-only
argument breaks every mutation test in it at call time. Migrating those tests to construct an
`Authority` against a temp database belongs in the **same commit** as the signature change, because a
commit that changes a signature and leaves its tests passing untouched has not changed the signature.
Concretely: if `test_coder.py` is still green after step 5 without being edited, the required kwarg did
not land — check for a default value that crept in. The read-side tests (`list_dir`, `read_file`,
`history`, `journal_tail`) keep `token`/`peer` and must **not** be migrated; if they need editing, the
read mount was changed by mistake.

**Sequencing note.** Step 8 is the one with real urgency: it closes a publicly-routable path to
arbitrary host command execution. It is placed at 8 rather than 1 because `/execute` (step 6) must
exist before `/tool/{name}` is removed, or the operator surface disappears with no replacement. If the
owner wants the hole closed sooner, steps 1–8 can be compressed and 9–13 deferred; **step 8 must not
be reordered ahead of step 6.**

### Rollback

Steps 1–4 are additive: delete `backend/apps/authority/`, drop the router line, remove
`run/authority.sqlite3`. Step 5 onward changes existing signatures — rollback is `git revert` of the
focused commit. Every step is one commit with its reason in the message, per `.claude/CLAUDE.md`.

### Commit acceptance — an unmet requirement to report

AGENTS.md and GUARDRAILS.md require that a commit changing verified state updates `ProjectStatus.md`,
and a commit changing architecture, component relationships, or providers updates `SyMoNSaysLLC.md`,
**in that focused commit**.

This plan changes both: it introduces a new component (`backend/apps/authority`), changes the
relationship between Studio, Coder, and the CLI, and changes how providers are invoked. Steps 5, 8, 9
and 11 each require a `SyMoNSaysLLC.md` update in their own commit, and steps 4, 6 and 8 change
verified state and require `ProjectStatus.md`.

**This document does not make those updates.** The author of this plan holds no mutation authority and
those files are outside its scope. Per AGENTS.md — "If required documentation is outside scope, report
the unmet acceptance requirement to Garrett before committing" — this is that report: **the mutation
owner executing this plan must make those updates within each focused commit.**

---

## Appendix — files read

Governance: `AGENTS.md`, `GUARDRAILS.md`, `CLAUDE.md`, `.claude/CLAUDE.md`, `PROJECT-TASKS.md`.

Runtime: `backend/server.py`, `backend/apps/coder/__init__.py`, `backend/apps/coders/__init__.py`,
`backend/apps/coders/routes.py`, `backend/apps/studio/__init__.py`, `studio/gate.py`,
`studio/registry.py`, `studio/agent.py`, `studio/routes.py`, `studio/workspace.py`,
`studio/tools_impl/fs.py`, `studio/tools_impl/host.py`, `backend/apps/controlboard/__init__.py`,
`controlboard/routes.py`, `backend/apps/dispatchos/store.py`, `dispatchos/authz.py`,
`backend/apps/capture/store.py`, `bin/symoneural-code`, `bin/symoneural-cli`,
`scripts/gpu-governor.sh`, `ops/Caddyfile`.

Nothing was modified. No service was started, stopped, or restarted. No provider was invoked.
