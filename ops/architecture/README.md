# ops/architecture/ — the maps, as TSV

Machine-readable because several consumers read them and none should re-derive them.

```
COMPONENT-MAP.tsv     every component: what it is, its state, where it lives
SERVICE-MAP.tsv       every service: what runs it, what it listens on
APPLICATION-MAP.tsv   every application: its rack row, its page, its runtime
ARTIFACT-MAP.tsv      every artefact: what produced it, what consumes it
SOURCE-CHAIN-MAP.tsv  artefact back to the source it was built from
ALIASES.tsv           the same thing under its several names
```

## The vocabulary these encode

Each word was chosen after a specific confusion, and a synonym reopens it:

- **surface** — an `/api/...` unit. Not "endpoint group", not "service"
- **runtime** — an artefact that executes. Not "binary", not "engine", not "backend"
- **application** — a rack row with a page. Not "app"
- **lease** / **holder** — not "lock", "mutex" or "semaphore"
- **evict** / **drain** / **drain floor** — not "kill", "cleanup" or "wait"
- **delegated** — a `PORTS.tsv` column with a defined meaning, not "split out"
- **DEFINED / PRESENT / WIRED / VERIFIED** — the maturity levels. Not "done" or "working"

Two splits that get blurred and matter: **`sigils` is the rack unit, `sigil` is the governor
surface name** — folding them moves the surface to the wrong eviction arm, and a test pins
it. **`symoneural-ui` is the runtime, `studio` is the application.**

`ALIASES.tsv` exists because the same thing has several names and a reader needs to know
they are the same thing. Where a house word does not exist, say so plainly — a missing word
is a finding, like a missing record.
