# Architecture: what was taken from Cordis, what was left, and where the plateau is

This package exists because of a design Garrett sent on 2026-08-18 — a Cordis-like plugin
runtime — and because of the verdict this repository already wrote about it in
`ops/registry/integration-sources.md` (the repo-level `docs/`, not this one). That verdict said no. This
document explains what changed, what was actually ported, what was deliberately left on the
table, and — the part `__init__.py` promises — where the plateau is.

## First, the contradiction, said out loud

The repo-level verdict's closing line reads: *"Deliberately not taken: TypeScript, `pnpm`,
`ts-node`, vm2, WASI, Landlock, seccomp, the fiber lifecycle, session forks, reactive reload, the
YAML preset loader, the capability gatekeeper, and the three-sprint plan."*

Four items on that list are in this package: the fiber lifecycle (`fiber.py`), session forks
(`isolate()` and `presets/sessions.yaml`), reactive reload (`Runtime.settle()` and service
epochs), and the YAML preset loader (`loader.py`). Pretending otherwise would make both documents
useless, so here is the actual distinction, which is not a hedge:

**The verdict was about the serving path.** It was answering "should the Studio's tool registry
be replaced by a TypeScript Cordis runtime with `pnpm` and `ts-node` in front of it?" The answer
to that is still no, and every reason still holds: a second serving runtime, a second dependency
tree, a second place a route can be defined, and a build step in front of a repository whose
whole discipline is generator → `site/*.html` → `build_cachebust.py`.

**This is not that.** `symoneuralexp` is one app package in `backend/apps/`, stdlib-only under
`routes.py`, off unless two environment variables are set, mounting nothing at all if
`SYMONEURAL_EXP_PRESET=""`. It does not replace `registry.TOOLS`, it does not touch `api.py`'s
`include_router` calls, and no request to any other surface reaches it. It is a workbench for the
layer, built where a workbench belongs, and the thing it lets you do is the thing the verdict
could not do: **look at the mechanism running and decide from evidence rather than from a
blueprint.** The verdict was written from reading a design document. This package can be mounted,
broken on purpose (`plugins/explode.py`), and watched.

And the two items the verdict *endorsed* are the two load-bearing pieces here, which is the real
continuity between the documents:

1. *"Validate tool arguments against the generated schema before dispatch"* → `registry.check_config`,
   which coerces and rejects against `schema = {"key": (type, default)}` before a plugin body ever
   runs, so a bad manifest value is a message rather than a `TypeError` in a traceback.
2. *"An append-only session trace"* → `trace.py`, whose own docstring calls itself the second of
   the two, with the ring in memory that the page reads and the optional JSONL in `run/`.

Everything the verdict declined *for reasons that were about correctness rather than scope* is
still declined. There is no vm2, no WASI, no Landlock, no seccomp, no capability gatekeeper, and
no sandbox of any kind. `docs/isolation.md` is a whole document about why, and it declines them
with measurements from this box rather than by citation.

## What was ported

Ported, in the sense of "the idea was read and then rewritten in Python against this repository's
constraints". Nothing is vendored; there is no npm anywhere near it; the runtime modules import
only the standard library, and PyYAML only when a manifest is actually a YAML file.

| Idea | Where it lives | What it became |
|---|---|---|
| `Context` as the whole extension surface | `context.py` | a plugin is `(ctx, config)`; every registration returns a disposer |
| Spatiotemporal composability | `Context.isolate` / `Fiber._unwind` | realms for space, reverse teardown for time |
| Declared dependencies | `plugin.inject` → `Runner.required/optional` | `ctx.llm` raises unless declared, because the graph is what drives reload |
| Fibers with a lifecycle | `fiber.py` | six states, one of which — `PENDING` — is not an error |
| Reactive reload | `Runtime.settle()` + `Service.epoch` | no polling; a bumped epoch makes dependents stale and they restart |
| A manifest loader with presets | `loader.py` | YAML → `Entry` tree → reconcile; `dev`, `sessions`, `failures` |
| Schema validation | `registry.check_config` | coerce, default, reject, before the body runs |
| An append-only trace | `trace.py` | memory ring + optional JSONL, nothing redacted |

Four design decisions inside that port are worth stating because they are where this
implementation is *not* a translation:

**`PENDING` is a first-class state, not a failure.** A plugin that injects `llm` before anything
provides `llm` sits in `PENDING` with `error is None` and `missing == ["llm"]`, and starts by
itself the moment a provider appears. That is what makes hot-plug work in both directions and it
is the single most useful thing to see on the page, because "nothing happened" and "waiting for a
dependency you never mounted" look identical from outside and are completely different problems.

**A failed body leaves nothing half-mounted.** `Fiber._start` disposes the effects the body did
manage to register before it raised, keeps the exception on the fiber, writes it to the trace,
and does *not* propagate it into the loader — because the loader is usually working through a
twelve-entry manifest and one bad entry must not stop the other eleven. `presets/failures.yaml`
mounts exactly this on purpose.

**Reverse teardown is not stylistic.** Registration order is dependency order: a plugin provides
a service and then subscribes a listener that uses it. Disposing forward would revoke the service
while the listener could still fire. It is the same argument `contextlib.ExitStack` makes, and
`test_exp.py` measures it as `ORDER == [3, 2, 1]` rather than asserting it in prose.

**Settling is bounded.** `Runtime.MAX_PASSES = 32`, and exceeding it raises with a message that
names the likely cause — two fibers whose provide/inject relationship oscillates. A reactive
system without a bound is a reactive system that hangs the API, and the bound is the difference
between a diagnosable manifest and a wedged process.

## What was left

* **A second runtime.** No TypeScript, no `pnpm`, no `ts-node`, no build step. The reason is
  `.claude/CLAUDE.md`'s first rule: exactly one of each thing.
* **Any sandbox.** See `docs/isolation.md`. Briefly: in-process isolation of Python from Python is
  not achievable, the tools for out-of-process isolation are on this box and measured, and the
  seam where they would attach is `Runner.call` — but building it would mean proxying every
  service in the container, which is a different runtime, and it pays for itself only when a
  plugin arrives that was not written in this repository. None has.
* **A capability gatekeeper.** `POST /call` has no method allow-list. That is Garrett's standing
  instruction applied rather than half-applied.
* **State migration on reload.** `reload()` re-imports the module and rebinds the runner; it does
  not attempt to carry a plugin's internal state across. The verdict's warning about hot-reload
  was specifically that "every plugin must declare how to snapshot and restore state", and the
  answer here is to not pretend: a reload is a stop and a start, `plugins/recorder.py` shows what
  survives (what you wrote to a service someone else owns) and what does not (what you kept on
  `self`).
* **Distributed anything.** One process, one card, one operator.

## The one architectural shape worth knowing

    Loader ── reads YAML ──▶ Entry tree (groups, ids, config, enabled)
      │
      └─ per entry ──▶ registry.resolve(plugin) ──▶ Runner (call, required, optional, schema)
                           │
                           └─▶ Context.plugin(...) ──▶ Fiber ──▶ effects [disposer, disposer, …]
                                     │                             ▲
                                     └── provide() bumps epoch ─────┘ reverse on unmount

`Runner.call` is the only thing in the package that touches the plugin object. `Fiber` is the only
thing that holds a disposer. `Runtime.settle()` is the only thing that decides a fiber should
start or stop. Three chokepoints, deliberately, because each one is where a future change attaches:
out-of-process plugins at `Runner.call`, resource leases at `Fiber`, and scheduling at `settle`.

## Where the plateau is

Here is the argument in full, because `__init__.py` promises it and because it is the reason this
package exists rather than a nicer version of the tool registry.

**The claim.** The next round of capability on this stack is not blocked on the model. It is
blocked on the fact that the process cannot be changed while it runs. Every interesting feature
above this layer is easy once mounting is reversible and a rewrite of the process every time it is
not — and "a rewrite of the process" is a cost high enough that the features simply do not get
built. That ceiling is the plateau, and it sits below the model, not above it.

**Where exactly.** At the line between *"the model can do this"* and *"the process can be changed
while it runs"*. Take three features nobody in this repository would call speculative:

* *An agent that gains a tool at runtime.* The model can already call a tool it is told about;
  `registry.tool_specs()` renders the list into the system prompt live. What it cannot do is
  acquire one, because `tools_impl/` is populated at import and the only mount operation this
  stack has is `systemctl restart symoneural-api`.
* *A session that forks its own model without disturbing the process-wide one.* Nothing about
  this is hard for the model. It is hard because a service in this stack is a module-level
  object, so "this session's `llm`" and "the `llm`" are the same name bound in the same
  namespace. That is precisely what `isolate()` is; `presets/sessions.yaml` is fourteen lines.
* *A UI that reloads its own plugin while a render is in flight.* The blocker is that a reload
  today drops everything the old code registered, including the in-flight thing, because nothing
  recorded what it registered.

None of those three needs a smarter model. All three need an entry to be the unit of change
instead of a process.

**Why the restart is not an adequate answer, on this box specifically.** The repo-level verdict
made the strongest available counter-argument — `Restart=always` under systemd brings this API
back in about two seconds — and it is right about availability and wrong about experimentation.
Two seconds of downtime is cheap. What is not cheap is what the restart *takes with it*: every
in-flight lease, the governor's view of who holds the card, a loaded model's warm VRAM, and the
state of whatever was mid-render. And the escape hatch that makes restarts tolerable everywhere
else — run a second process — is unavailable here, because there is one RTX 5070 Ti with 15.92 GiB
behind `scripts/gpu-governor.sh` and the rule is *hold the lock for a job, never for a process
lifetime*. You cannot spin up a second copy of the thing you are experimenting on. On a box with
four cards this plateau would be an inconvenience; with one card it is a wall, and it is a
physical fact about the hardware rather than a matter of architectural taste.

**The mechanism, stated as a general rule.** *The cost of an experiment is bounded below by the
cost of undoing it.* If undo is "restart the API and lose every lease", experiments are expensive,
so few get tried, so the layer above stops moving — and it stops moving in a way that looks like
a capability limit from the outside. That is what a plateau is: not an absence of ideas, and not
an absence of model quality, but a substrate where the ideas cost too much to test. Reversibility
is the cheap-undo primitive, which is why `provide`/`on`/`effect` all return disposers and why
teardown runs in reverse — and why the thing this package makes visible on `/exp` is not a
throughput number but a state table and a trace.

**What this package actually moves.** The unit of change becomes an `Entry`. Mount, unmount,
reload, patch config, enable, disable — each is one request, each is undone by the disposers the
fiber kept, and each is recorded. Nothing in the process restarts. That is the entire claim, and
it is small on purpose: the interesting work is the layer above, and this is the layer under it.

**What it does not move, so the argument stays honest.** A plugin can still take the process down
— `os._exit`, or a segfault in a native extension, and then there is no fiber state to look at
because there is no process. GPU leases are not integrated: a mounted plugin cannot yet hold the
card for a job, which is the next thing that actually needs building and is why `Fiber` was named
as the attachment point above. Reload does not migrate state. Settling is bounded at 32 passes,
so a pathological manifest raises rather than converges. And none of it is isolation.

**Where the plateau moves to, once this exists.** Two places, both nameable. First, resource
scheduling: with mounting solved, the binding constraint on this box goes back to being 15.92 GiB
and one mutex, and the next layer is a lease-aware scheduler that lets a fiber acquire the card
for the duration of a job. Second, provenance: once plugins can arrive at runtime, the question
"who wrote this code" stops being answerable by "everything here was written here", and that is
the day `docs/isolation.md`'s mechanism 1 stops being a design sketch and becomes work. Both are
better problems than the one above, which is the only claim a layer like this can honestly make.

Further reading: `docs/writing-plugins.md` for the shapes and the mechanics, `docs/isolation.md`
for the boundary question, and `presets/failures.yaml` for the failure modes mounted rather than
described.
