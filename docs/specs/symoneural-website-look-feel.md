# SyMoNeuRaL Website — look, feel, and the layout rules that are not decoration

**Scope captured 2026-08-22.** Docs and scope only. **No page implementation, no folder
migration, no deploy.**

## What it is

> **The website is the public product surface.** Not just generated docs, and not just the rack.

Public identity and branding · application discovery · overview · the Live Stack / rack surface ·
control and readout surfaces where appropriate · app pages · docs and API access where
appropriate · demos and result gallery **where implemented** · signup, accounts, credits and
pricing **only where current policy supports it** · cloud/local hardware options **only where
current docs support it**.

The classification is `docs/ops/BOX-REALITY-AUDIT.md` §10.1: **AUDIT, upgrade needed.** Not a
doubt that it serves — it serves. Garrett's judgement that the public surface needs a major
upgrade, not scoped and not started.

## 1. Look and feel

Dark technical product surface. **Embedded, instrument style.**

**The instrument comes first.** The app tool is at the top; explanation goes below it or into
`<details>`. **No documentation dump above the actual instrument.** This is the standing rule
behind two open tasks — **#84** (RavenCalc: *"so that the top of the calculator is at the top of
the page"*) and **#85** (the miner page, *"embedded like symoneural ravencalc"*) — and it
generalises to every app page.

**No decorative status LEDs.** Every chip is a reading. `symoneural-live-stack.md` §7 is the
full rule and it applies wherever a status appears, not only on the rack.

## 2. The layout rule that has teeth: no data is dropped

**Layout changes must not delete content.** This is stated as a rule because it is the one that
gets violated by accident, in the name of tidying:

- **Fold long content into `<details>`.** Do not trim it.
- **Merge duplicate copy** rather than deleting one of the copies.
- **Do not remove load-bearing claims.** #84 names its own examples: the CPU-never-queues fact
  and the not-a-language-model claim *"are both load-bearing arguments about what this surface
  is, so they move and merge."*
- **No `text-overflow` that drops data** — #84: *"that rule has no exceptions here."*

**A layout task is not a licence to edit meaning.** #84 makes the distinction explicitly: it is
*"not a trim"*, and it refuses to do the SymPy rebrand sitting on the same page because *"that is
its own task, and re-typing the word here is the edit that would hide it."*

## 3. Honesty rules for anything numeric or commercial

- **No stale marketing claims.** This session's worked example: the miner page said *"SyMoNeuRaL
  Miner runs KawPow"* and quoted 52.3–53.2 MH/s while the engine path did not exist in the tree
  (`symoneural-miner-scope.md` §2).
- **No invented pricing, capacity, throughput or revenue.** The API's own description already
  frames the box correctly — one GPU, chat and image weights do not both fit in 15.92 GiB — and
  **this is demonstration hardware, not production capacity.**
- **Every numeric figure is labelled `measured` / `vendor` / `projected`.** The pattern already
  exists in `plugins/reinforce/registry.py`: *scan-never-hardcode, derive-never-look-up, every
  figure labelled.*
- **A measured figure with a date and no reproducibility note reads as current capability.**
  That was the whole miner defect. Provenance means saying what produced it and whether the tree
  can produce it again.
- **Pricing questions route to the existing channel** (`symonsayadmin@symoneural.com`) rather
  than inventing an answer on a page.

## 4. Navigation and route rules

- **No duplicate pages under old product names.** The rack once showed one page twice because
  Tuner and Guide both pointed at `/tuner.html`.
- **Retired pages redirect only where bookmark compatibility matters** — not as a permanent
  parallel surface.
- **`/livestack/*` is the current published spelling.** `/live-stack/*` may remain as
  compatibility **only** where tests or docs require it, and the **published link must use the
  unhyphenated form**. One live defect: the `coder` rack row's href is `/documentation.html`
  (`symoneural-live-stack.md` §5).
- **Do not keep old API aliases forever** without explicit authorization — e.g. no permanent
  `/api/tuner/*` alias once Streamer owns the surface.
- **`ops/Caddyfile` must delegate any new top-level path explicitly.** It handles `/api/*` and
  delegates that subtree wholesale; a new top-level path is not covered by inheritance.

## 5. Build rules

Learned the hard way, in this order:

1. **Regenerate generated pages from source.** They are build products; editing `site/*.html` by
   hand puts the change one regeneration away from deletion.
2. **`build_cachebust.py` runs last.** `build_pages.py` alone **strips** the `?v=` asset hashes
   from all 25 pages. In this session that surfaced as eight changed files that had nothing to do
   with the change being made; running the pair left exactly one page changed. **Generated assets
   must not ship unstamped.**
3. **Run any generator twice and diff.** The accumulate bug — a generator that re-reads its own
   output and does not recognise something it emits duplicates it, one copy per run — **has
   happened three times in this repo.**
4. **Split HTML/CSS/JS where the current page pattern requires it.**
5. **The deploy script compares staged and live route expectations.**

**Localhost success does not prove deployed-webroot success.** Open task **#86** exists for
exactly this: *"a page can ship to `site/` and never reach the webroot, and nothing goes red."*
**A website upgrade built on top of a publish path that can silently not-publish is built on
sand**, which is why `BOX-REALITY-AUDIT.md` §10.1 records #86 as a prerequisite rather than a
parallel concern.

**No stale webroot after a rename.** The Tuner → Streamer fold produced precisely that: 
`/streamer.html` missing or stale on the public origin while `/tuner.html` still answered — so
**do not diagnose a surface as absent merely because the public webroot is stale.**

## 6. Product-name rules

App pages must match **current** product names. Two live cases:

- **SyMoNeuRaL DJ → SyMoNeuRaL Remix.** Visible product copy may be corrected to Remix under an
  authorized page/spec cleanup; **internal env and module names stay** until the scoped naming
  task. The drift is recorded as `AUDIT.md` **Q12** and is not a task until Garrett scopes it.
- **Tuner is retired as a top-level product name**, folded under Streamer. Users must not land on
  retired Tuner branding.

## 7. Not authorized

No page implementation · no layout change (that is #84, #85, and their own tasks) · no href fix ·
no redirect added · no `ops/Caddyfile` edit · no rename of any module, token or route · no folder
migration · **no deploy.**

Related: `symoneural-live-stack.md` · `symoneural-api-surface.md` ·
`symoneural-application-lab.md` §3.1 · `docs/ops/BOX-REALITY-AUDIT.md` §10.1.
