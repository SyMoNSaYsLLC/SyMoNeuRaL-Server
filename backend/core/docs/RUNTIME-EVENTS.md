# Runtime events — what we took from a log that was better than ours

The owner pointed at the ChatGPT desktop app's startup log and asked how to get our runtimes
to work like that. Five properties were worth copying. All five are now in
`backend/core/events.py`, and applying them found **three real startup defects** in a
service that imported cleanly.

## What ours said, and what it could not answer

```
2026-09-11 14:29:27 INFO  starting chat surface
2026-09-11 14:29:35 INFO  chat surface up
```

Both true. Neither answers: how long, with what argv, whether the adapter applied, from what
previous state — and when it does not come up, which of six reasons. Four hundred lines of
prose that `grep` can search and nothing can parse.

## The five properties

### 1 · `key=value` on every event, with a stable name

```
runtime_status runtime=symoneural-llm status=ready pid=73205 ms=8210 port=8081
```

`runtime_status` survives a rewording; "chat surface up" is a sentence somebody will edit.
Fields are **sorted**, so two occurrences of the same event diff cleanly — an event whose
field order follows kwargs order cannot be compared between runs.

### 2 · Phases are timed, and emitted together

```
startup_complete ms=1 phases=1 routes=127 slowest="dispatchos store" slowest_ms=0 tasks=4
  durations="dispatchos store=0"
```

One line, not fifteen. A reader comparing two starts wants the phase map side by side;
fifteen scattered lines means subtracting timestamps by hand. `slowest` is called out because
that is the only field anybody acts on.

### 3 · A state change names `previous`, `next` and `cause`

```
state_changed subject=gpu.lease previous=free next=held cause="chat acquired" holder=chat
```

The reference log does this for every transition and it is the property ours lacked most:
"chat surface up" says neither what it was before nor what moved it, and both matter when it
flaps.

### 4 · A runtime reports status with a reason when it is not ready

```
runtime_status runtime=asicminer status=absent reason="no rigs configured" rigs=0
```

`status=failed` with no reason is the entry that costs an afternoon. The engine spawn now
distinguishes three failures that used to be one line:

```
status=failed reason="exited rc=1 before answering"        ms=340    a bad argv or missing file
status=failed reason="no answer on /health within 120 s"   ms=120000 a hang
status=ready  ms=8210                                                warm page cache
status=ready  ms=41000                                               cold read of 11 GB
```

The **duration is the diagnostic**, and the old log printed the same sentence for all four.

### 5 · A skip is an event

```
skipped what="persona adapter" reason="adapter arch differs from chat arch"
        adapter=symoneural-lora.gguf adapter_arch=qwen2 chat_arch=qwen3moe
```

The reference log emits `bundled_plugin_install_skipped_current`,
`..._skipped_missing`, `..._skipped_user_managed` — three different reasons for not doing
something, each named. Silence and "did not need to" read identically, and this repository
has already shipped a deploy that published nothing while printing `deployed`.

## What applying it found

None of these could be seen by importing the module. `import server` builds the app and
counts 160 routes; it does **not** run the lifespan. All three were found by starting the
service and watching it stop.

| defect | effect |
|---|---|
| `guide_ask_model` never passed to `configure()` | **startup failed**, every time |
| `_llama_lock` lived in `server.py`, read off `ctx` | started fine, **shutdown failed** |
| `_llama` never declared at module scope | `NameError` on shutdown if the engine never started |

All three are the same mistake: a plain function and a lock routed through the context bag,
which exists to break an import cycle and buys nothing for something with no cycle to break.
Both now live beside what they guard.

## Using it

```python
from core import events

events.emit("engine_spawned", runtime="symoneural-llm", pid=73205, ctx=33792)
events.runtime_status("symoneural-diffuse", "failed", reason="cudaMalloc: 11.8 GiB of 15.9")
events.state("gpu.lease", "held", "free", cause="drain complete", floor_mib=1024)
events.skipped("speculative decoding", "draft arch differs", draft_arch="qwen2")

with events.phase("routers mounted"):
    ...
events.startup_complete(routes=len(app.routes))
```

Two rules:

- **Never interpolate a value into the message.** `emit("x", path=p)`, not
  `log.info("x %s", p)` — the whole point is that a field can be extracted.
- **Never emit a secret.** Fields are identities, counts, durations and states. Not prompts,
  not transcripts, and nothing from `run/config/api.env`.

## Reading it

`run/events.log` is a single shape — `HH:MM:SS.mmm event key=value ...` — so it parses
without a regex that has to tolerate prose.

```bash
grep '^.* runtime_status ' run/events.log | grep -v status=ready     # what is not up
grep startup_complete run/events.log | tail -5                       # the last five starts
awk '/status=failed/ {print}' run/events.log                         # with reasons attached
```

## What we did not copy

The reference log carries a 40 KB runtime-install manifest inline on one line — every
platform, digest, size and CDN URL, on every start. That belongs in a file, and ours is
`ops/manifests/`. Logging a manifest on every boot makes the log unreadable and the manifest
unversioned.

It also logs at a volume that suits a desktop app phoning home. This box serves one operator;
per-request routing lines would bury the six lines that matter.
