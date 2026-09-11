# Writing plugins

Everything here is mechanical. The argument for why the runtime is shaped this way is in
`docs/architecture.md`; the boundary question is in `docs/isolation.md`. This file is the part you
need open while writing one.

## The smallest complete plugin

```python
name = "bus"                      # what the fiber is labelled; defaults to __name__
schema = {"history": (int, 50)}   # {key: (type, default)}


def apply(ctx, config):
    bus = Bus(config["history"])
    ctx.provide("bus", bus)       # revoked on unload
```

Drop that in `plugins/`, then add three lines to a manifest:

```yaml
plugins:
  - id: bus
    use: apps.studio.plugins.exp.plugins.bus
    config: {history: 200}
```

`plugins/bus.py` is exactly this and nothing more; read it first.

## The four shapes

`registry.resolve()` accepts all four and reports which it found as `kind`:

| Shape | Looks like | Use it when |
|---|---|---|
| `module` | a module with a module-level `apply` | almost always — this is what `use:` points at |
| `function` | `def thing(ctx, config)` | tests, and plugins mounted from Python rather than YAML |
| `class` | `class Thing: def __init__(self, ctx, config)` | the plugin needs instance state |
| `object` | anything with a callable `.apply` | a configured factory or a closure holder |

Two details about classes, because they surprise people. The instance is **kept** for the fiber's
lifetime (`registry.py` holds it in an effect closure), so `self` is real state that exists while
mounted and is gone after unload — that is what a class plugin is *for*. And if the class defines
`stop()` or `dispose()`, it is registered as an effect and called on teardown; you do not need to
call `ctx.effect` yourself.

Metadata is read off the module first, then off the entry point, so for a module plugin
`inject`, `schema` and `name` are module globals sitting next to `apply`.

`apply` may be `async def`. `plugins/clock.py` is, because it starts a task.

## Declaring dependencies

```python
inject = ["bus"]                                          # both required
inject = {"required": ["bus"], "optional": ["memory"]}     # the dict form
inject = "bus"                                            # one dep, handled correctly
```

The third form is guarded on purpose: a string is iterable, so without the guard `inject = "llm"`
would declare three single-letter services and the fiber would sit in `PENDING` forever waiting
for `l`.

`ctx.bus` raises `ContextError` if `bus` is not declared. That is not security — the plugin is
ordinary Python and can `import` anything — it is because the declared graph is what the runtime
uses to decide **what to restart when a service changes**. An undeclared access that happens to
work is a plugin holding a stale object after someone else reloads.

An optional dependency is `None` when absent and does not hold the fiber in `PENDING`. Check it:

```python
inject = {"required": ["bus"], "optional": ["memory"]}

def apply(ctx, config):
    mem = ctx.memory                    # may be None
    if mem is not None:
        mem.write("started", {})
```

**A missing required dependency is not an error.** The fiber is `PENDING`, `error is None`, and
`missing` names what it is waiting for. It starts by itself the moment a provider appears, and
goes back to `PENDING` if that provider goes away. `plugins/recorder.py` is the worked example:
mount it without `bus` and watch it wait; mount `bus` and watch it start, with nothing polling.

## Config and `schema`

`schema = {"key": (type, default)}`. A one-element spec means required:

```python
schema = {
    "topic": (str, "tick"),   # optional, defaults to "tick"
    "keep": (int, 100),
    "path": (str,),           # required — no default
}
```

`registry.check_config` runs before your body does. It fills defaults, coerces the obvious YAML
typos (`"5"` → `5`), rejects unknown keys while naming what *is* accepted, and reports **every**
problem in one message so a three-field mistake takes one edit. Two behaviours worth knowing:
`interval: true` is rejected rather than read as `1` (`bool` is a subclass of `int`, and this is
the same trap the Studio registry has), and a plugin with no `schema` accepts anything.

Inside the body, `config[key]` is safe for every key in the schema — defaults are already filled.

## Making things reversible

Three registration calls, all returning a disposer, all recorded by the fiber in order and undone
in reverse:

```python
ctx.provide("clock", state)               # revoked; dependents unwind first
ctx.on("tick", handler)                   # unsubscribed
ctx.effect(lambda: task.cancel())         # arbitrary cleanup
```

Anything else your plugin does — a thread, a socket, a file, a subprocess, an entry in someone
else's registry — needs an `ctx.effect` that undoes it, or it leaks. That is the whole contract:
**if you cannot write the undo, do not write the do.**

Reverse order matters and is not a style choice. You provide a service, then subscribe a listener
that uses it; disposing forward would revoke the service while the listener could still fire. The
test suite measures this as `[3, 2, 1]` rather than trusting prose.

An async body should register the cancel *before* awaiting anything that can fail, so a body that
raises halfway still cleans up. It will be cleaned up either way — `Fiber._start` disposes what
was registered before the exception — but only what was registered.

## Providing versus consuming

`ctx.provide(name, value)` refuses a second live provider for the same name **in the same realm**,
with an error naming `isolate()` as the fix. If you want two of something, that is what realms
are for:

```yaml
- id: session-a
  isolate: [llm, memory]      # this group gets its own llm and memory
  plugins:
    - {id: a.llm, use: apps.studio.plugins.exp.plugins.echo_llm, config: {prefix: "a> "}}
```

Names not listed in `isolate` still resolve in the root realm, so `presets/sessions.yaml` forks
`llm` and `memory` per session while both sessions share one `bus`. `GET /api/exp/services` shows
two rows named `llm` with different keys, and the page shows them as two rows deliberately.

Providing a name that is already in the container, with a different object, bumps its `epoch`.
Every fiber that started against an older epoch is stale and restarts on the next `settle()`.
That is the reactive story in one sentence, and it is why reloading `bus` restarts `recorder`
without either plugin knowing about the other.

The bump is what a *live* provider does to its own name. A provider that unloads first revokes
the entry, and the fiber that mounts in its place provides a new service at `epoch` 1 -- the
dependents restart anyway, via `Fiber.missing` rather than `Fiber.stale`. So do not read `epoch`
as a count of how many objects a name has ever had; read it as a count of in-place swaps.

## Group entries

An entry with `plugins:` and no `use:` is a group. It mounts nothing itself; it shapes the context
its children get:

```yaml
- id: session-b
  isolate: [llm, memory]
  intercept:
    llm: {temperature: 0.0}
  plugins:
    - {id: b.llm, use: apps.studio.plugins.exp.plugins.echo_llm}
```

`intercept` supplies default keyword arguments to every call on that service for plugins under the
group. The children never see it and cannot remove it; the config lives on the group.

## Manifest fields, complete

| Key | Meaning |
|---|---|
| `id` | configuration identity. What the API mutates by. **Quote `off`, `on`, `yes`, `no`** — YAML 1.1 parses them as booleans |
| `use` | dotted module path, or `module:attribute` for a function or class |
| `config` | mapping, validated against `schema` before the body runs |
| `disabled` | `true` leaves the entry present and unmounted |
| `isolate` | list of service names to fork into a new realm (groups, usually) |
| `intercept` | `{service: {kwarg: value}}` defaults for descendants |
| `plugins` | children — makes this entry a group |

`Loader.apply` diffs by `id`, so re-applying an edited manifest restarts only what changed. That
is the behaviour to check first if you are evaluating whether this runtime does what it claims.

## When it does not work

Look at the state before anything else. A plugin that "does nothing" is almost always in one of
two states, and they mean opposite things:

* **`pending`** — a required dependency is not provided. `missing` on the fiber names it, and the
  page shows it. Mount the provider; nothing else is needed.
* **`failed`** — your body raised. The traceback is on the fiber and in
  `GET /api/exp/plugins`, not in the API's stderr, because the loader deliberately does not let
  one bad entry stop the other eleven.

`presets/failures.yaml` mounts both on purpose, plus `plugins/explode.py`, which fails four
different ways selected by config: a raising body, an undeclared `ctx.bus`, a config key its
schema rejects, and a raising cleanup. Mount that preset before you debug your own plugin, so you
know what each failure looks like on the page.

`GET /api/exp/events` is the trace: every mount, provide, revoke, unwind, reload and error in
order, with a sequence number. If the state table does not explain it, the trace does — that is
what it is for. Nothing in it is redacted, so do not trace a secret.

## Reload

`POST /api/exp/reload {"id": "recorder"}` re-imports the module, re-resolves the runner, and
restarts the fiber. Your instance state does **not** survive; a reload is a stop and a start. What
survives is what you wrote into a service somebody else owns. `plugins/recorder.py` demonstrates
both halves.

If the reloaded module fails to import, the entry keeps its error and stays addressable — which is
the point of entries being separate from fibers, since a broken entry needs fixing precisely when
it has no fiber.

## Two things you cannot do

You cannot be isolated from the process: your plugin runs with the API's privileges and can read
every service in every realm through `ctx.runtime`. `docs/isolation.md` says why in full, and why
that is not going to change in-process.

You cannot take the GPU without a lease and expect it to be fine. There is one card behind
`scripts/gpu-governor.sh`, and the runtime does not yet mediate it — a plugin that loads a model
resident is a plugin that locks out chat, image and train. `plugins/gpu.py` reads state and takes
nothing. Until leases are integrated, that is the only safe pattern for anything GPU-shaped.
