# SyMoNeuRaL Coder

A sandboxed workspace agent: list and read files, write and patch them, run commands. It is
the backend half of the site-development agent Garrett raised in `.claude/HANDOVER.md` §2g
item 2.

**It is local-only and off by default, and that is not a configuration preference — it is
the design.** Read the next section before you switch it on or wire it to anything.

---

## 1. Why the security shape decides everything else

Garrett's words, recorded in HANDOVER §2g:

> *"i want to be able to somehow integrate site development agent but we have to be careful
> to only give me that maybe by the seat — only thing with seat is i use xrdp also for
> this."*

And the conclusion already reached there:

> **An agent that can develop the site is arbitrary code execution on the box that serves
> the public internet.** It must never be reachable from a visitor-facing route, and
> "behind a password" is not sufficient on its own for that capability.

His xrdp habit is the *safest* answer rather than a complication. An agent running inside
his desktop session is local-only: no public route, no token to leak, no rate limit to get
wrong. This module is built for that shape first. Everything below — the gates, the
denylist, the journal — is defence in depth *behind* that, not a substitute for it.

Per-seat licensing is a separate question and should not be conflated with this one.
`backend/apps/licensing/` gates **use**; the gates here gate **reach**.

### Fail closed, because the repo has the counter-example in it

`.claude/HANDOVER.md` §5 item 1: the SyMoN_ML auth daemon calls
`_check_local_sandbox_state()` as a fallback and that function is `return True`
unconditionally, so **blocking `api.trongrid.io` grants the licence** — `iptables -j DROP`
defeats the entire moat. Nothing in this module has that shape. There is no fallback that
returns permission, no default more permissive than the explicit answer, and no exception
handler that swallows a failure into an allow. A check that cannot be performed **denies**.

There is a test for it: `test_the_module_refuses_everything_when_the_switch_is_unset` walks
all eleven public entry points with the switch off and asserts every one refuses and that
the file on disk is untouched.

---

## 2. The three gates

```bash
SYMONEURAL_CODER_ENABLED=1                 # the surface exists at all
SYMONEURAL_CODER_TOKEN=<shared secret>     # every call presents it; constant-time compared
SYMONEURAL_CODER_ALLOW_REMOTE=1            # ONLY THEN may a non-loopback peer call
```

The first two mirror `backend/apps/asicminer/__init__.py` exactly — the pattern this repo
already uses for a route that must not be world-callable. The third is additional and
specific to this surface.

They are **independent**. A correct token from `203.0.113.9` is refused. A loopback peer
with no token is refused. Both must pass, plus the master switch, and one misconfiguration
is therefore not enough to open the box.

Optional:

```bash
SYMONEURAL_CODER_WORKSPACE=/home/google/Symoneural/site   # default: the repo root
SYMONEURAL_CODER_STATE_DIR=/home/google/Symoneural/run    # default: <repo>/run
```

**Narrowing the workspace is the strongest single thing you can do here.** Pointing it at
`site/` produces an agent that can edit the site and cannot see `training/` at all. That is
structurally better than relying on the denylist, because it removes the path rather than
refusing it.

---

## 3. Wiring it up — and the one thing that would undo all of it

**The recommended answer is not to add a route.** Import the module from a process running
in Garrett's desktop session and call it directly. There is then no listener, no token in a
web process's environment, and nothing for Caddy to proxy.

If a route is added anyway, this is the shape, and the comment on `peer` is the important
line in this file:

```python
import coder                      # backend/apps is already on sys.path in api.py

def _coder_gate(request: Request) -> None:
    # request.client.host is the real socket peer. DO NOT use api.py's client_key():
    # it reads X-Forwarded-For first, which is correct for rate limiting and CATASTROPHIC
    # here -- Caddy sits in front, so that header is written by the caller, and a remote
    # attacker would simply assert 127.0.0.1 and walk through the loopback gate.
    peer = request.client.host if request.client else None
    # The new header name only, with no legacy fallback. Every other surface reads
    # `X-Sym-Token` as well, because each has a browser sender that may be cached; a
    # route that does not exist yet has no sender to be behind, so a fallback here would
    # be a deprecation with nothing deprecated.
    ok, why = coder.authorize(request.headers.get("X-Symoneural-Token"), peer)
    if not ok:
        raise HTTPException(503 if not coder.enabled() else 401, why)
```

Three further facts that decide whether that is safe:

1. **`/api/*` is already delegated to FastAPI by `ops/Caddyfile`** (HANDOVER §3.0c lists the
   delegated paths). So a route at `/api/coder/...` is **publicly reachable the moment it
   exists** — the loopback gate would be the only thing between the internet and this
   module. That is exactly the situation §2g says to avoid.
2. A route mounted after the `StaticFiles` mount at `/` is unreachable; declare it before.
3. If you want a listener at all, the honest shape is a **separate uvicorn bound to
   `127.0.0.1`** that is not behind Caddy, rather than a path on the public API.

`unit_state()` is provided in the five-line `asicminer` shape if the surface is ever put on
the rack. Its honest default is `offline`, and it reports `no GPU lease` because that is
true.

---

## 4. The API

Every function is keyword-gated on `token` and `peer` — there is no unauthenticated entry
point, and a caller who forgets gets a `TypeError` rather than an open door. Nothing raises;
every call returns a dict with `ok`, and on refusal an `error` string. That is the contract
`asicminer` uses, for the same reason: a surface that throws takes its caller down with it.

| Call | What it does |
|---|---|
| `status()` | workspace, state dir, the active denylist |
| `list_dir(path, recursive=False)` | one directory; denied entries are **listed and flagged**, not hidden |
| `read_file(path, max_bytes=2_000_000)` | UTF-8 text, or an error saying it is binary |
| `diff(path, content)` | unified diff of a proposed write. Writes nothing, journals nothing |
| `write_file(path, content)` | whole-file replace, previous state saved first |
| `patch_file(path, find, replace, count=1)` | exact-string replace; refuses unless it matches exactly `count` times |
| `delete_file(path)` | backed up first, so it is undoable |
| `history(path)` | every saved version, oldest first |
| `restore(path, version)` | roll back; the restore is itself undoable via `undo_version` |
| `run(argv, cwd=".", timeout=120)` | argv list, never a shell |
| `journal_tail(n)` | the last n journal records |
| `unit_state()` | `(state, detail)` for the rack. Ungated — it reveals nothing |

---

## 5. The guards, and what each one is actually worth

### Path containment

Every path is joined onto the workspace (unless already absolute), `resolve()`d — **which
follows symlinks** — and then required to land inside the resolved workspace root. Traversal,
absolute paths outside the root, and symlinks whose *target* escapes are all refused.

Resolving the string with `os.path.normpath` instead is the classic bypass, and it is not
what this does. Verified by mutation: swapping `resolve()` for `normpath()` turns
`test_symlink_escape_is_rejected` red.

Same lesson as `/api/gen/<name>` in HANDOVER §3.3 — the name is attacker-controlled and hits
the filesystem, so it is matched against the exact shape expected rather than trusted.

### The denylist, applied to the RESOLVED path

```
training/corpus.jsonl        trade secret — the 327-example corpus
training/build_dataset.py    trade secret — the method that produces it
training/adapter/            adapter weights
run/gpu.lock.d               the GPU mutex
.git/config                  remotes and any credential helper
run/coder.log                this module's own journal          (see §8, owner's call)
run/coder-backups/           the rollback store                 (see §8, owner's call)
*.key  .env  .env.*          keys and environment secrets
```

`.claude/CLAUDE.md` is explicit that the first three must never be copied into `site/`,
served from an endpoint, or quoted into a page or a commit message — and that **an agent
asked to "publish the manual" could reasonably mistake the corpus for documentation**. That
is precisely the failure this list exists to prevent. `frontend/site/docs/symoneural-manual.md` is the
manual and is publishable; the corpus is not. The line that resolves it against the site's
transparency argument is CLAUDE.md's own: **publish the numbers, keep the methods.**

**The check runs after `resolve()`, on the absolute path's segments.** Two consequences, both
tested:

- A symlink named `notes.txt` pointing at `training/corpus.jsonl` is refused, because it
  resolves to a denied path. A string-level denylist would hand the corpus over.
- Matching absolute segments rather than workspace-relative ones means that if the workspace
  is ever narrowed to `training/`, the adapter is still denied — its relative path is
  `adapter/x`, which a relative match would miss.

Denied entries appear in `list_dir` with `denied: true` and a reason rather than being
silently omitted. Silent omission is the decorative-dishonesty shape this repo argues
against everywhere else: the operator should see that the file exists and is refused.

### `run()` is arbitrary code execution, and the denylist cannot constrain it

**Say this plainly rather than let someone discover it.** `run(["cat",
"training/corpus.jsonl"])` walks straight past every path guard, because the guard protects
`read_file`, not the kernel. There is an argv scan that refuses arguments naming a denied
path, and it catches exactly that call — but a glob, a here-doc, a Python one-liner or
`tar -c training/` walks past it.

The scan `resolve()`s its arguments, so `cat notes.txt` where `notes.txt` is a symlink to
the corpus *is* refused — the scan and `read_file` agree about what a path means, and two
guards that disagree is how one of them becomes the one an agent reaches for by accident.
That does not change what it is.

So, stated as a negative result, which is what this repo does with negative results:

> **The denylist protects against the agent's own mistakes, not against a hostile caller.
> The loopback gate plus the token is the only real boundary.**

That is the whole reason local-first matters, and it is why the recommendation in §3 is not
to expose a route at all. If the caller is hostile, you have already lost — not because of
anything in this module, but because "run a command on the server" is the feature.

What `run()` does guarantee:

- **No shell, ever.** argv list only; a command-line *string* is refused with an error
  saying so. `shell=True` would make every string this agent assembles subject to `;`, `|`,
  `$( )` and `>`. Verified by mutation: switching to `shell=True` turns seven tests red,
  including the one asserting a payload of shell metacharacters comes back as literal
  stdout with no files created.
- **cwd pinned inside the workspace.** A `cwd` outside it is refused.
- **A timeout that actually kills.** The process starts in its own session, so the timeout
  signals the whole group — SIGTERM, a grace period, then SIGKILL. Killing only the direct
  child leaves grandchildren holding the pipe and the reap hangs; there is a test that
  spawns a grandchild specifically to prove it.
- **stdout and stderr captured** and returned with the exit code.
- **A scrubbed environment.** `SYMONEURAL_*` **and** `SYMONEURAL_*` variables containing `TOKEN`,
  `SECRET` or `KEY` are removed from the child, so a command cannot read this surface's own
  token out of its environment and print it back over the wire. Both prefixes are listed
  because the check is a prefix match rather than a list of names, so it would go quietly
  dead against a box whose variables had been renamed — see `_SECRET_PREFIXES` in
  `__init__.py` and the test that pins both spellings.

---

## 6. Rollback and the journal

**Before any write, delete or restore, the previous state is saved** under
`<state>/coder-backups/<workspace-digest>/<path>/<name>.<version>.bak`, and the mutation is
journalled to `<state>/coder.log` as one JSON line carrying a timestamp, the action, the
path, the version and the pid.

Both of those happen **before** the change, not after. `_mutate()` snapshots, then journals,
then lets the caller write — and if either step fails, the mutation does not happen.
"Every mutating action must be journalled" means an unjournalled edit is not allowed to
occur; there is a test that makes the state dir unwritable and asserts the file on disk is
unchanged.

Three details worth knowing:

- **Creating a file is undoable too.** A write to a path that did not exist records an
  `.absent` marker, and restoring that version removes the file. Rollback that cannot undo a
  creation is not rollback.
- **A restore is itself undoable.** It snapshots the current state first and returns
  `undo_version`, so rolling back the wrong file does not destroy what you were trying to
  keep.
- **`version` is validated against the exact shape emitted** (`\d{8}T\d{12}`) and the
  assembled backup path is re-checked against the backups root. Both checks are load-bearing
  and neither is redundant: verified by mutation, removing the shape check lets
  `restore("a.txt", "/../sub/b.txt.<v>")` resolve to a real file *inside* the backups root
  and write another file's saved content into `a.txt`. The containment check does not catch
  that one. There is a test named for it.
- **Two workspaces never share a history.** The backup path is keyed by a digest of the
  workspace, so a temp-workspace `foo.py` and the repo's `foo.py` cannot cross.
- **A patch is journalled twice, on purpose.** `patch_file` writes its own `patch` record
  before delegating to `write_file`, which adds a `write`. The patch record is the intent
  (what was matched, how many times); the write record carries the backup version rollback
  needs. One record alone would lose one of the two.

`run/` is runtime state, not logs (`.claude/CLAUDE.md`) — it holds `gpu.lock.d`, the GPU
mutex. This module writes two things beside the lock and never touches it, creates nothing
under `run/` at import time, and denies `run/gpu.lock.d` outright. `run/` is gitignored, so
neither the journal nor the backups are ever committed.

---

## 7. No model, and the arithmetic for why

**This module runs no model and takes no GPU lease.** It is orchestration and file I/O. A
test reads the module's own source and asserts it never names the governor, `llama-server`,
`nvidia-smi`, torch or CUDA.

If a code model is ever wired in, it goes through `scripts/gpu-governor.sh` as **its own
surface**, and here is the cost, labelled as `.claude/CLAUDE.md` requires:

| Figure | Value | Label |
|---|---|---|
| RTX 5070 Ti usable VRAM | 15.92 GiB | **measured** on this machine |
| Idle occupancy | ~946 MiB | **measured** |
| Chat (Qwen2.5-7B-Instruct Q4_K_M, adapter loaded) | ~5 GB resident | **measured** |
| Image (FLUX.1-schnell q4_k) | ~7 GB resident | **measured** |
| A QLoRA fine-tune | ~12 GB | **measured** |
| A 7B code model at Q4_K_M | ~5 GB, same class as chat | **projected** |
| A 32B code model at Q4_K_M | ~19 GB | **projected** |

The arithmetic, all of it projected because no code model has been run here:

- Chat and image already **cannot co-reside** — that is the measured finding the governor
  exists to serialise. A code model is a **third tenant** on a one-tenant card, so it makes
  a constraint that already binds strictly worse, not better.
- A 32B coder exceeds the card outright at ~19 GB projected against 15.92 GiB. It is not a
  scheduling problem; it does not fit.
- A 7B coder at ~5 GB projected would fit *alone*, and would therefore mean
  **evict chat → load coder → evict coder → reload chat** for a session that interleaves
  asking and editing, with the governor's 1.5 GB VRAM-drain wait between every tenant swap.
  Measure that round trip before promising anyone an interactive coding agent. This is the
  same reasoning HANDOVER §5 item 12 applies to SyMoNeuRaL Voice.
- The genuinely cheap answer is the one this module already implements: **the agent's
  reasoning does not have to live on this box.** File I/O and command execution are the
  parts that must be local; a model that decides what to edit need not be, and costs zero
  VRAM if it is not.

(The repo quotes weights in GB against a card specified in GiB — 15.92 GiB ≈ 17.1 GB. The
conclusion does not turn on the conversion, and the figures are left in the units they were
measured in rather than silently restated.)

---

## 8. Tests

```bash
python3 backend/apps/coder/test_coder.py       # 46 tests, ~2s
```

System interpreter, stdlib only, no network, no GPU, and **it never writes into the real
`run/`** — every test points `SYMONEURAL_CODER_STATE_DIR` and `SYMONEURAL_CODER_WORKSPACE` at temp
directories, because a test that wrote into `run/` could destroy the GPU lock while a
surface held the card.

HANDOVER §3.0d is blunt that a verification step which passes on a healthy system proves
less than people think, so **every guard here was checked by reintroducing the bug it
prevents** and confirming the suite goes red:

| Bug reintroduced | Result |
|---|---|
| denylist matched on the input string instead of the resolved path | 1 failure — the corpus became readable through a symlink |
| `os.path.normpath()` instead of `Path.resolve()` | 2 failures |
| `subprocess` with `shell=True` | 7 failures |
| `restore()` stops validating the version shape | 1 failure — another file's backup could be restored into this one |
| journal written after the write instead of before | 1 failure |
| `authorize()` returns `True` unconditionally (the SyMoN_ML shape) | 5 failures |
| `list_dir` drains the walker into `sorted()` before checking the cap | 1 failure |
| the argv scan uses `normpath()` instead of `resolve()` | 1 failure |

That fourth row is the one worth remembering: the test written for it *first* was vacuous —
it passed with the check deleted, because the traversal payloads it used resolved outside the
backups root and were caught by a different guard. It was replaced with a payload that
resolves *inside* the backups root, which only the shape check refuses.

The sixth row is the same lesson in a different place. `list_dir`'s entry cap was originally
checked inside `for child in sorted(walker)`, which drains the entire generator before the
loop body runs even once — on the default workspace, the repo root, that means `rglob("*")`
descending through `models/` (40 GB), `references/` (8.5 GB), `contrib/` and three
venvs before the limit is consulted. It returned the right answer and did all the work
first, which is exactly the §3.0d shape: a guard that reads as if it protects something and
does not. The cap now binds during the walk, and the test asserts **how far the walk got**
rather than only the length of the result — because a test that checked only the length
passes against the broken version.

---

## 9. Decisions for the owner

1. **Route or no route.** The recommendation is **no route** — drive the module from a
   process in the xrdp desktop session. If you want one, note that `ops/Caddyfile` already
   delegates `/api/*` to FastAPI, so an `/api/coder/...` path is publicly reachable the
   moment it exists and the loopback gate becomes the only barrier. A separate uvicorn bound
   to `127.0.0.1` is the safer shape.
2. **The default workspace is the repo root.** Narrowing it to `site/` gives an agent that
   can do the site-development job and cannot see `training/` at all. Recommended, but it is
   your call — it also stops the agent editing `backend/`, `tools/` and the generators.
3. **`run/coder.log` and `run/coder-backups/` were added to the denylist and were not in the
   brief.** Reasoning: an agent that can rewrite the journal it is audited by, or delete the
   backups it is rolled back from, has neither an audit trail nor an undo. Say if you would
   rather it could clean up after itself.
4. **Nothing prunes the backups.** Every write keeps a full copy forever under `run/`, which
   is gitignored but not unbounded. A retention policy (age or count) is a small addition and
   has deliberately not been guessed at.
5. **`run()` has no binary allowlist.** Refusing everything except a named set (`git`,
   `python3`, `node`, the generators) would harden it considerably, at the cost of the agent
   being unable to do things you have not predicted. Worth deciding once you know what you
   actually run through it.
6. **No model is wired in, by design** (§7). If you want one, the cheap answer is a model
   that is not resident on this card at all.

<!-- generated: do not edit below -->

## Operations

None. This component is a library for others, or is driven from the desktop session rather than over HTTP.

## Documents

- [`code-client-spec.md`](docs/code-client-spec.md)
- [`coder-spec.md`](docs/coder-spec.md)
- [`symoneural-coder-project-cli-scope.md`](docs/symoneural-coder-project-cli-scope.md)

<!-- end generated -->
