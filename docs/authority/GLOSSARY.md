# The house vocabulary

**This encodes words already in use. It does not invent any.** Every term below was already
load-bearing in the code, the registries or the tests; what was missing was one place that says
so. Before this file, the vocabulary was consistent in practice and defined nowhere — which made
it invisible to anyone arriving, and a synonym costs nothing to write and reopens a confusion
that was already paid for.

Written 2026-09-10. **It is a rule, not a reference** — `PROJECT-AUTHORITY.md` indexes it for
that reason.

---

## Use these words

| use | not | why the synonym hurts |
|---|---|---|
| **surface** | endpoint group, service, app | a surface is a unit the governor can name and evict; "service" collides with systemd units, which are a different thing |
| **runtime** | binary, engine, backend | a runtime is an artefact that **executes** and has a row in `ops/RUNTIMES.tsv`. "Backend" is a directory here |
| **application** | app | an application is a rack row with a page. `backend/apps/` is a directory and shares no meaning with it |
| **lease** / **holder** | lock, mutex, semaphore | the lease is a `mkdir` directory that outlives the shell that took it. "Mutex" implies in-process; this one is cross-process and that distinction is the whole design |
| **evict** / **drain** / **drain floor** | kill, cleanup, wait | eviction stops a tenant; **drain waits for the driver to return the memory**, and they are separate steps with separate failures. Collapsing them is how a lock is returned before the CUDA context is gone |
| **rack row** | status entry, health item | the `/api/status` contract |
| **registry** | config file, manifest | a **manifest** is a *restore* artefact (`restore/manifests/`). A registry is a hand-maintained record with readers and an agreement test |
| **delegated** | split out, moved, extracted | `DELEGATED` is a column in `ops/PORTS.tsv` with a defined meaning, and `ports.delegated()` refuses to report a surface delegated without a port |
| **FIRST_PARTY** / **SYMONEURAL_VERSION_OF** / **DEPENDENCY** | ours, forked, third-party | the `IMPLEMENTATION_CLASS` values in `FIRST-PARTY-CLOSURE.tsv`. They carry authorship consequences the loose words do not |
| **DEFINED / PRESENT / WIRED / VERIFIED** | done, working, in progress | four measurable levels. "Done" is not one of them |

## Two distinctions that get blurred, and both have cost money

### `sigils` is the application. `sigil` is the governor surface name.

They genuinely differ and **one is not a typo for the other**. `ops/RUNTIMES.tsv` carries the
diffusion runtime twice because it serves `image` **and** `sigil` under two governor surfaces
with two eviction arms — `test_runtimes_registry.py:63` says so in its own failure message, and
one row would hide `sigil`.

Folding them moves the surface to the governor's `*)` arm. Before 2026-09-10 that arm killed
both engines; it now refuses. `SurfaceIsARealRackUnit` in `test_runtimes_registry.py` pins the
spelling against `appdocs.APPLICATIONS`, proven red against exactly this mistake.

### `symoneural-ui` is the runtime. `studio` is the application.

`appdocs.py:204` gives `studio` `runtime="symoneural-studio"` — and **`symoneural-studio` is in
no `RUNTIME` column in `ops/RUNTIMES.tsv` and names no artefact on disk.** It is a product
label. Three other values (`symoneural-live`, `symoneural-project`, `symoneural-platform`) have
the same problem.

That is what the `product` / `runtimes` column split in `RUNTIME-PROPOSAL.md` step 2 exists to
fix. **Until it lands, say which namespace you mean every time**, because both use
`symoneural-*` names and nothing in the text tells a reader which question is being answered.

## When there is no house word

**Say so plainly rather than reaching for a generic one.** A missing word is a finding, the same
as a missing record — and it is usually pointing at a thing the system does not yet name because
it does not yet model it.

Two that are missing today, recorded here rather than papered over:

- **No word for a continuous-hold tenant.** The lease arbitrates *burst* surfaces that acquire,
  work and release. A miner never finishes, and the vocabulary has no term for that — which is
  why it reads as an ordinary surface right up until it blocks every visitor for 300 s.
- **No word for "the set of files that are ours."** Four records answer it from different angles
  (`git ls-files`, `FIRST-PARTY-CLOSURE.tsv`, `SOURCE-CLOSURE.tsv`, the disposition scan) and
  none is named as *the* answer, which is how a fifth ad-hoc walk gets written.

## The rule this file exists to serve

**Before measuring something, check whether a registry already records it.**

A measurement written fresh is a new answer that can disagree with the recorded one, and this
repository's idiom is *one record, several readers, a test asserting they agree*. The cost is
not hypothetical: an ad-hoc `pathlib.glob` for "which files are ours" walked a gitignored
`.venv` and reported **355 retry loops in a surface whose tracked source is four files** —
a number `git ls-files` could not have produced. `conftest.py` already carries
`collect_ignore_glob = ["vendor/*"]` because someone hit that and encoded the answer where it
would be reused.
