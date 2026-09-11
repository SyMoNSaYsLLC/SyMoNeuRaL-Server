# Frontend audit — the site as an application, 2026-08-26

**This is a dated audit, not a state document.** State lives in `.claude/HANDOVER.md`; rules
live in `.claude/CLAUDE.md`. Everything below was measured on this date against the working
tree at `01dc6205` and the live local API on `127.0.0.1:8800`. Nothing here is carried
forward from an earlier reading, and every number states how it was taken.

Written to answer the UI/UX brief Garrett gave on 2026-08-26: *"Transform SyMoNeuRaL from
pages that feel like individually designed website/marketing surfaces into a cohesive,
responsive application interface"* — llama.cpp-like ergonomics, SyMoNeuRaL identity.

---

## 0. Two premises in the brief that this repo does not match

Stated once, here, so they do not have to be re-argued later.

**(a) There is no frontend `.mjs` layer.** The brief's §8 and §15 ask for an audit and
refactor of "every frontend .mjs module". No `.mjs` file is served to a browser. The 13
`.mjs` files in this repo are:

| file | what it actually is |
|---|---|
| `tests/frontend.mjs`, `browser.mjs`, `account.mjs`, `live.mjs`, `project.mjs`, `studio.mjs`, `stickers.mjs`, `code_cli.mjs`, `streamer_guide.mjs`, `streamer_watch.mjs`, `streamer_failpaths.mjs` | Playwright **verification** suites, run under Node |
| `ops/gateway/build.mjs`, `ops/gateway/test_contracts.mjs` | gateway build + contract tests |
| `backend/apps/studio/plugins/reinforce/test_page.mjs` | a plugin page test |

The browser-side code is **classic `<script>` tags** — `site/*.js` plus large inline blobs.
So §8 is mapped onto that layer, and §15 is read as *"the `.mjs` suites stay green"*, which
is the only `.mjs` stake in this work.

**(b) Neither screenshot in the brief was attached to the conversation.** The repo does
contain `mob-composer.png` (2026-08-17); it is a phone screenshot of the **Image** page
composer, not the header overflow §6 describes. The header defect was therefore located by
measurement rather than from the picture — see §5 below, where it is reproduced with exact
geometry. The llama.cpp reference is likewise taken from §3's written description.

---

## 1. Application / page / route inventory

26 HTML surfaces. `backend/server.py:3802` mounts `StaticFiles(directory=site/, html=True)` at
`/`, with clean-URL routes declared *before* the mount. `ops/Caddyfile` has no rewrites.

| # | Page | Clean route | Function | Loads |
|---|---|---|---|---|
| 1 | `index.html` | `/index.html` | dashboard (4 tabs) | console.js, ui.js, 3.2KB inline |
| 2 | `overview.html` | `/overview`, `/` → redirect | informational | console.js, ui.js |
| 3 | `livestack.html` | `/livestack` | dashboard / rack | console.js, ui.js |
| 4 | `controlboard.html` | `/controlboard` | diagnostics | console.js, ui.js |
| 5 | `receipts.html` | `/receipts` | informational | console.js, ui.js |
| 6 | `chat.html` | — | **workspace** (conversation) | console.js, ui.js, visualizer.js, 10.5KB inline |
| 7 | `image.html` | — | **workspace** (generate + gallery) | console.js, ui.js, image.js, image.css |
| 8 | `ravencalc.html` | — | **workspace** (calculator) | console.js, ui.js, 7.2KB inline |
| 9 | `remix.html` | — | **workspace** (playlist) | console.js, ui.js, 3.1KB inline |
| 10 | `miner.html` | — | **operator / diagnostics** | console.js, ui.js, 17.5KB inline |
| 11 | `gateway.html` | — | **workspace / status** | console.js, ui.js, 2.9KB inline |
| 12 | `streamer.html` | — | **workspace** (IPTV) | console.js, ui.js, hls.js, **91.5KB inline** |
| 13 | `streamer-watch.html` | — | media player (no chrome) | hls.js, 49.2KB inline |
| 14 | `studio.html` | `/studio` | **workspace** (graph) | console.js, ui.js, studio.js |
| 15 | `exp.html` | `/exp` | **workspace** (experiments) | console.js, ui.js, exp.js |
| 16 | `project.html` | — | **workspace** (project) | console.js, ui.js, 17.8KB inline |
| 17 | `reinforce.html` | — | **workspace** (training) | console.js, ui.js, reinforce.js |
| 18 | `sigils.html` | — | **workspace** (sigils) | console.js, ui.js, 18.1KB inline |
| 19 | `coder.html` | `/livestack/coder` | **workspace** (code) | ui.js, coder.js, coder.css |
| 20 | `live.html` | `/livestack/live` | media workspace | console.js, ui.js, hls.js, live.js, live.css |
| 21 | `account.html` | — | configuration / forms | ui.js, 6.3KB inline |
| 22 | `credits.html` | — | informational | console.js, ui.js |
| 23 | `documentation.html` | — | informational (long doc) | console.js, ui.js |
| 24 | `build.html` | — | marketing | ui.js |
| 25 | `training.html` | — | informational (430KB manual) | **no stylesheet, no ui.js** |
| 26 | `share-dispatchos.html` | — | protected preview | 2KB inline |

**14 of the 26 are application workspaces.** Every one of them currently ships the marketing
shell described in §3.

---

## 2. Frontend file mapping — and the constraint that governs every edit

**The HTML is generated. Editing `site/*.html` loses the work on the next generator run.**

| Page(s) | Owner | Edit here |
|---|---|---|
| chat, image, ravencalc, remix, miner, gateway, streamer, streamer-watch | `tools/build/build_pages.py` (5,974 lines) | generator |
| overview, livestack, controlboard, receipts | `tools/build/build_split.py` (subtraction from `index.html`) | `index.html`, then re-run |
| exp (+ `exp.js`) | `tools/build/build_exp.py` | generator |
| project | `tools/build/build_project.py` | generator |
| reinforce (+ `reinforce.js`) | `tools/build/build_reinforce.py` | generator |
| sigils | `tools/build/build_sigils.py` | generator |
| studio (+ `studio.js`) | `tools/build/build_studio.py` | generator |
| training | `tools/build/build_training.py` | generator |
| build | `tools/build/build_sky.py` | generator |
| `index.html` | hand-maintained, **patched between BEGIN/END markers** by `build_masthead.py`, `build_rack.py`, `build_console.py`, `build_tabs.py` | `site/index.html` outside markers, else the generator |
| `documentation.html` | hand-maintained, patched by `build_cost.py`, `build_stack.py` | as above |
| account, coder, credits, live, share-dispatchos | **hand-written in `site/`** | `site/` directly |

Sequence, fixed by `.claude/CLAUDE.md`: generators → `build_cachebust.py` **last** (a rebuild
strips the stamps) → run each generator **twice and diff** (they re-read their own output;
that bug has landed three times in this repo).

CSS: `symoneural.css` (3,253 lines, shared) + `rack-detail.css`, `coder.css`, `image.css`,
`live.css`. `training.html` links **none of them**.

---

## 3. UI architecture findings

### F1 — Every generated application page is wrapped in a marketing shell

`tools/build/build_pages.py:33` `SHELL` hardcodes, above the workspace and identically for all
eight pages it writes:

```html
<div class="hero" style="padding:56px 0 26px">
  <h1 style="font-size:clamp(28px,3.6vw,40px);max-width:24ch">@@HEADING@@</h1>
  <p class="lede" style="font-size:16.5px">@@LEDE@@</p>
```

56px of padding, a 40px display headline and a 16.5px lede stand between the viewport top
and the first control on Chat, Image, RavenCalc, Remix, Miner, Gateway and Streamer. This is
§11's "giant hero headings inside operational applications", and it is one template.

### F2 — The test-bench callout is baked into the shell, below every workspace

`SHELL` also hardcodes the `<div class="callout">` — *"This is a 16 GB consumer card, and it
is a test bench"*, two paragraphs — **after `@@BODY@@` on every page**. On Chat that is
exactly §4's complaint: explanatory hardware material sitting underneath the composer,
inside the active workspace. It is useful and must be relocated, not deleted.

### F3 — Inline one-off styles defeat the token system

`SHELL` alone carries `style="padding:56px 0 26px"`, `style="font-size:clamp(28px,3.6vw,40px)"`,
`style="font-size:16.5px"`, `style="font-size:14.5px"`, `style="margin-top:34px"`,
`style="border-top:0;padding-top:0"`. The `--t4: 14.5px` token comment in `symoneural.css`
records that the scale was *bent to fit an inline style in seventeen files* rather than the
markup being fixed — a token chosen by the thing it was meant to govern.

### F4 — The token set covers colour and type only

`:root` in `symoneural.css` defines `--bg --panel --panel2 --line --fg --dim --faint
--accent --accent-ink --amber --max` and a strictly-enforced seven-step type scale
`--t1…--t7`. §7 additionally requires, and there is **no token for**: spacing scale, border
radius, control heights, sidebar dimensions, transitions, focus states, elevation.

### F5 — 18 distinct breakpoints, no system

Measured by parsing `symoneural.css`: `520, 560, 620, 760, 780, 820, 860, 900, 1040, 1280,
1300, 1360, 1601, 1700, 2000` px plus height-coupled compounds
(`min-width:1301px and max-height:899px`, `min-width:1700px and min-height:900px`, …).
Neighbouring components change layout at 860 and 900 for no shared reason.

### F6 — Chat already has the llama.cpp-shaped shell; it is page-local

`chat.html` carries a `cu-*` structure — `.cu-rail` (New chat, history list, footer note),
`.cu-main`, `.cu-empty`, `.cu-log`, `.cu-composer` with attach + model indicator + send.
**Most of brief §3 is already built.** It lives in one page's CSS block and one generator
constant. The work is to *promote* it into the shell, not to author a parallel one.

Its own comment records that the rail was built to dodge a sitewide rule rather than fix it:

> A `<div role=navigation>`, NOT a `<nav>`: the sitewide rule `nav a:not(.cta){display:none}`
> hides nav links below 820px, which would delete every link in here on a phone.

That rule is the direct cause of F7.

---

## 4. Frontend (JS) architecture findings

### F7 — A 1,368-byte helper block is inlined verbatim into 13 pages

`SHELL` ends with an inline `<script>` defining `$`, `status()`, the Enter-to-send binding
and `api()`. Byte-identical on chat, exp, gateway, image, miner, project, ravencalc,
reinforce, remix, sigils, streamer, studio. It declares `const $` **at global scope on every
page**, is re-parsed per navigation and can never be cached. This is the single clearest
"shared behaviour implemented per page" in the codebase, and the fix is one file.

### F8 — Behaviour counts across the 34 browser-side modules

Scanned mechanically over `site/*.js` plus every inline block over 200 bytes:

| implementations | behaviour |
|---:|---|
| 31 | status / error message presentation |
| 28 | `fetch()` — with at least four different error conventions |
| 15 | Enter-to-send |
| 13 | `innerHTML =` writes |
| 9 | `localStorage` |
| 9 | `setInterval` polling |
| 5 | `X-Sym…` credential header, hand-assembled |
| 4 | `/api/status` consumers |
| 3 | streaming response readers (`getReader()`) |
| 3 | textarea autogrow (`scrollHeight`) |
| 2 | file upload |
| 2 | model/runtime selector |
| **1** | **`AbortController` — and it is inside vendored `hls.js`** |

The last row answers a §3 question directly: **Chat has no cancel/abort.** Once a generation
starts it cannot be stopped from the UI. That is a gap to close, not a regression to avoid.

### F9 — Inline blobs are the real duplication problem

`streamer.html` carries **90KB of inline JavaScript**; sigils 16.7KB, project 16.4KB, miner
16.2KB, chat 9.1KB, `streamer-watch.html` 49.2KB. None of it is cacheable, none of it is
lintable, and `#81` already established the migration pattern — `build_pages.py:52` records
that Image was split into static html + js + css first, *"a pattern proven on one page is
worth more than nine half-migrations."*

---

## 5. Responsive findings — measured, not inferred

Probe: Chrome via Playwright, every page at 360/390/430/768/1024/1440/1920, recording
`documentElement.scrollWidth` and every visible element whose right edge exceeds the
viewport. **46 of 168 page×width combinations overflow.**

### F10 — The mobile header defect (§6), reproduced exactly

At a 360px viewport on `chat.html`:

```
header .wrap.bar     l=  32  r= 328  w= 296   overflow-x: HIDDEN
.logo                l=  60  r= 168  w= 108
.llc                 l= 182  r= 322  w= 140   display: block
nav                  l= 336  r= 405  w=  70
nav a.cta            l= 336  r= 405  w=  70   ← entirely outside the 328px clip edge
```

Four separate defects compound here:

1. **`.llc` — "a SymonSays LLC company", 140px — is `display:block` below 820px and
   `display:none` at 820px and above.** The responsive logic is inverted: the descriptor is
   hidden on desktop, where there is room, and shown on a phone, where there is not.
2. **`nav a:not(.cta){display:none}` below 820px leaves the CTA as the only nav item**, so
   "Have one built" is pushed out by the logo + descriptor. No other navigation is reachable
   at all on a phone — no Account, no Documentation, no Live stack.
3. **`.wrap.bar` sets `overflow-x:hidden`.** That is why `scrollWidth` reads 360 and no
   scrollbar appears: the button is not off-screen-and-scrollable, it is *clipped away*.
   This is precisely the "hide the problem with arbitrary clipping" §6 forbids, and it is
   why the defect survived 49 green frontend assertions.
4. Geometry is **identical at 360, 390 and 430** (`r=405` in all three). Nothing is
   shrinking; the bar is laid out at min-content and cut off.

Affected: 14 pages at 360px and 390px.

### F11 — No table on this site responds

`credits`, `documentation`, `exp`, `reinforce` put bare `<table>` elements in the flow with
no `overflow-x:auto` wrapper. `documentation.html` is **1,072px wide at a 1,024px viewport**
— it overflows on a laptop, not just a phone.

### F12 — `training.html` overflows at every width tested, including 1920

`<code>` blocks reach 6,248px. The page links no stylesheet and loads no `ui.js`: it is a
430KB standalone document outside the design system entirely.

---

## 6. Proposed shared shell and component structure

```
site/symoneural.css
  ├─ tokens        colour, type (existing) + spacing, radius, control heights,
  │                sidebar/content widths, transitions, focus ring, elevation   [F4]
  ├─ breakpoints   3 named steps, replacing 18 ad-hoc ones                      [F5]
  ├─ app shell     .app / .app-nav / .app-main / .app-bar / .app-drawer
  └─ components    buttons, inputs, cards, badges, tables, empty/loading/error

tools/build/build_pages.py
  ├─ SHELL         marketing shell — build.html, credits, overview, receipts
  └─ APP_SHELL     new: compact bar, no hero, no baked-in callout, 100dvh    [F1,F2]
```

Application pages inherit `APP_SHELL`; informational pages keep `SHELL`. The `cu-*` chat
structure is promoted to the shell's workspace primitives rather than duplicated [F6].

## 7. Proposed shared JS structure

Explicit modules, no monolith:

| file | owns | replaces |
|---|---|---|
| `site/app.js` | `$`, `api()`, error convention, Enter-to-send, textarea autogrow | the 13 inlined copies [F7] |
| `site/shell.js` | drawer/sidebar toggle, nav state, responsive shell | nothing today — new |
| existing `console.js`, `ui.js` | GPU readings; news bar, lightbox, tabs, maintenance banner | retained unchanged |

Inline blobs migrate to page files **one page at a time**, Image's proven pattern [F9].

## 8. Files to modify

1. `site/symoneural.css` — tokens, breakpoints, shell, components, header fix
2. `tools/build/build_pages.py` — `APP_SHELL`, hero removal, callout relocation, script tags
3. `site/app.js`, `site/shell.js` — new
4. `site/index.html`, `documentation.html`, `account.html`, `coder.html`, `credits.html`,
   `live.html` — hand-maintained pages, header markup
5. `tools/build_{exp,project,reinforce,sigils,studio,training,sky,split}.py` — shell adoption
6. `tests/responsive.mjs` — new, the check below
7. `tools/build/build_cachebust.py` — run last

## 9. The check that makes this task honest

`.claude/CLAUDE.md` records that #94 and #74 both archived themselves green while broken,
because `exists`/`grep` checks ask what is written on disk and cannot ask whether the thing
works — and that a `note:` saying so is ignored, since `archive_tasks.py` reads checks.

This redesign is exactly that failure mode. So the task's binding check is a **real run**:
`tests/responsive.mjs` loads every shell-bearing page at eight viewport sizes and asserts no horizontal
overflow, no clipped control, reachable navigation and an in-viewport composer. Its result
is stamped into `ops/docs/SMOKE-FRONTEND.md`, which cannot be written honestly without running it.

---

# Part 2 — what was implemented, and what it measures

Written after the work, same day. Task **#109**, commits `7f09c3b2`..`ddcc1563`.
**Nothing here was deployed** — `sudo scripts/deploy.sh --prune` is Garrett's to run and an
agent cannot. Every reading below is local, against `127.0.0.1:8800`.

## 10. Implementation

| # | Change | Files |
|---|---|---|
| 1 | `.bar` collision removed: the rack gauge is `.meterbar` | `symoneural.css`, `rack-detail.css`, `build_rack.py` |
| 2 | Tokens: spacing, radius, control heights, shell geometry, elevation, transitions, focus | `symoneural.css` `:root` |
| 3 | `.llc` un-inverted — hidden until 901px | `symoneural.css` |
| 4 | Mobile navigation drawer, built from the existing `<nav>` | `site/shell.js` (new), `symoneural.css` |
| 5 | Three overlapping header rules collapsed to one at 900px | `symoneural.css` |
| 6 | 13 inlined helper copies → one cached file | `site/app.js` (new), `build_pages.py` |
| 7 | Tables scroll in their own box | `symoneural.css` |
| 8 | Streamer guide pill stops covering its page's controls | `build_pages.py` |
| 9 | Application shell: no hero, callout relocated | `build_pages.py` `appify()`, `symoneural.css` |
| 10 | Five importing generators opt in | `build_{exp,project,reinforce,sigils,studio}.py` |
| 11 | `shell.js` wired into the hand-maintained pages | `index/documentation/account/coder/credits/live/build.html` |
| 12 | Two new suites + one rewritten assertion | `tests/responsive.mjs`, `tests/chat_smoke.mjs`, `tests/frontend.mjs` |

## 11. Responsive verification

`node tests/responsive.mjs` — 24 pages × 8 viewports × news-bar off/on.

| run | combinations | findings |
|---|---|---|
| baseline, `011aa4b1` | 192 | **78** (47 overflow, 31 unreachable) |
| after header work | 192 | 54 |
| after tables + drawer at 900px | 192 | 1 |
| after the streamer pill | 192 | **0** |
| news bar enabled (the hole) | 384 | 368 → 11 → **0** |
| after the application shell | 384 | **0** |

Header, measured on `/chat.html`:

| | before | after |
|---|---|---|
| destinations reachable at 390px | **0 of 7** | **7 of 7** |
| `a.cta` box at 360/390/430px | `336..405` — outside all three | inside |
| `.wrap.bar` overflow | `hidden` (clipping the button away) | none |
| toggle | did not exist | 44×44, inside the bar |

Page chrome above the first control, 1440×900: chat and image **298 → 169px**; sigils 298 →
238; studio 316 → 263; exp 341 → 286; project 290 → 263; reinforce 290 → 240.

**The mutation test.** The scroll-to-centre refinement could have blunted the suite, so it was
broken on purpose: removing the streamer pill fix and rebuilding turns it red at 360, 390 and
430 (`.sn-x` covered by `div#tnfg` even when scrolled to centre). Fix restored, green restored.

## 12. Functional smoke tests

`node tests/chat_smoke.mjs` — **46/46**, at 1440×900 and 390×844. Typed into the composer,
pressed Enter, and the 7B streamed back: `5 tokens in 0.22s · 22.5 tok/s measured on the card`,
model indicator `SymonChat S1-7B`. Shift+Enter newline with the textarea growing 28→52px
(desktop) and 27→50px (phone); empty state clears on submit; conversation enters history; new
chat clears the log and keeps history; history survives a refresh; no page errors.

Drawer, `/chat.html` at 390px: closed → 0 links reachable; opened → 7; focus moves to the first
link; Escape closes; widening to 1440px while open closes it and restores the horizontal nav
**with no reload**; no page errors.

`node tests/frontend.mjs` — **66/66**. Three assertions went red first and were right to: they
pinned the six-link nav laid out inside the bar at 781/800/860px. Rewritten to press the toggle
and assert reachability, toggle size and wordmark width instead of deleting the check.

Backend page guards: **227 passed** (`studio`, `exp`, `credential_header`, `desktop_client`,
`maintenance_banner`, `streamer_migration`). Generator chain including `build_cachebust`:
**run twice, byte-identical**. `build_intake.py` and `build_progress.py`: twice, no diff.
`apps/test_build_progress.py` 28 passed.

## 13. Browser-module verification

There is no `.mjs` frontend layer (§0a). What ships is `site/*.js` plus inline blocks:

| module | responsibility | pages | disposition | reason |
|---|---|---|---|---|
| `app.js` | `$`, `api()`, `status()`, Enter-to-send | 13 | **new — extracted** | was inlined byte-identically 13×; loaded **without `defer`** because each page's own inline script runs at parse time and would find `$` undefined |
| `shell.js` | narrow-viewport navigation | all with a header | **new** | reads the existing `<nav>`, so no page can be missed and there is no markup to drift |
| `ui.js` | doc tabs, lightbox, news bar, maintenance banner | 25 | retained, unchanged | four unrelated concerns in one file; a fifth IIFE would repeat the cost its own comments record |
| `console.js` | GPU readings over WebSocket | 20 | retained, unchanged | not touched by the redesign |
| `image/live/studio/exp/coder/reinforce/visualizer.js` | per-surface logic | 1 each | retained, unchanged | own their workspaces |
| `hls.js` | vendored player | 3 | retained | vendor |
| inline blobs (6 pages) | per-page logic | 1 each | **deferred → `AUDIT.md` Q14** | `build_pages.py:52`: *"a pattern proven on one page is worth more than nine half-migrations"* |

No duplicate event registrations (`shell.js` guards on `nav.dataset.shellBound`), no console
errors across 384 page loads, no stale selectors — the `cu-*` structure Chat's JS depends on was
not touched, verified element by element in `chat_smoke.mjs`.

## 14. Surfaces proven live before exclusion

Asked for explicitly. Neither is obsolete; **neither was removed**, and both stay outside the
application shell for stated reasons.

**`streamer-watch.html` — live and required.** Linked from `site/streamer.html:512` (the
playback handoff); routed — `api.py:3791` maps `/tuner-watch.html` → it, and `ops/Caddyfile:258`
references it; three suites cover it (`tests/streamer_watch.mjs`, `tests/frontend.mjs`,
`backend/apps/test_streamer_migration.py`); named in `backend/streamer/docs/symoneural-streamer-scope.md`.
Its generator states the design intent: *"Not routed through `page()`: this surface has no
header, no footer and no prose measure, because the picture is the page."* Chrome-less **by
design** — retained, unchanged.

**`share-dispatchos.html` — live and required.** An active credentialed customer preview behind
`basicauth` for four named accounts (`ops/Caddyfile:332`), with a documented install-order
safety property in `ops/ops/backend/authority/docs/share-previews/README.md`. Decisively,
`backend/apps/test_maintenance_banner.py:139-144` asserts the file **exists** ("the customer
preview page has gone missing") **and that it must not load `ui.js`**. Adding site navigation
would put the internal surface list in front of a customer and break that test — retained,
deliberately outside the shell.

**`training.html` — intentional, outside the shell.** A 430KB converted manual with its own
inline `<style>`, no shared stylesheet and no `ui.js`. Treated as a document, per instruction.

## 15. Remaining defects and deferred work

| item | status |
|---|---|
| `miner.html` 333px / `gateway.html` 311px app head | **open** — their own six-line ledes, not the template. Copy, and #80 owns neighbouring strings, so not rewritten here |
| Chat cannot cancel a generation | **`AUDIT.md` Q13** — one `AbortController` on the whole site and it is inside vendored `hls.js`. Functional change; reported, not built |
| Inline JS blobs on six pages | **`AUDIT.md` Q14** — scope and order need authorizing |
| 18 breakpoints reduced, not eliminated | partial — three named steps are defined and new rules use them; existing component rules were not rewritten, which would be churn without a measured defect |

**Correction, 2026-08-26:** the exploratory Training finding was invalidated before the
responsive suite was written. Its wide code blocks live inside named horizontal scroll
containers and the page itself does not overflow. `training.html` is one of the 24 pages in
the recorded 384-combination run and passes. Carrying the exploratory result into this final
table was an error; it is removed rather than softened.

**Pre-existing, proven so rather than assumed** — the same tests run in worktrees at
`01dc6205`, before any of this work:

- 16 backend failures (`roster`, `status_rack`, `studio_models`, `desktop_shell`,
  `enable_surfaces`, `control_plane_matrix`, `chat_model_identity`, `rack_probes`,
  `gateway_unit`) fail **identically** there. Three more in the working tree come from the
  uncommitted #108 runtime cutover.
- `tools/audit/check_links.py` — 3 broken (`/livestack/live`, `/studio`): routes, not files.
- `apps/test_brand_boundary.py` — 3 errors, `ModuleNotFoundError: No module named 'steps'`
  from `apps/ravencalc/ravencalc.py:45`.

None of these were touched by #109 and none are claimed as fixed.

---

# Part 3 — reopened completion pass

Task #109 was reopened after its declared checks reached 100% before the brief did. The
responsive result was real, but it measured layout and shell reachability rather than every
functional requirement.

## 16. Scope and provenance corrections

- The inventory names **14 application workspaces**. The first implementation converted 12;
  the two hand-maintained exceptions were `coder.html` and `live.html`. Both now use
  `.apphead apphead-after`, retain their instrument-first order, load `shell.js`, and no
  longer carry the marketing `.hero` chrome.
- `site/ui.js` and `ops/docs/MAINTENANCE-SURFACES.md` entered commits `9b3d1166` and
  `9eadca7d` from the pre-existing runtime-cutover working tree. They are mutually consistent
  and their maintenance-surface test passes, but they are not UI-redesign work. This record
  corrects attribution without rewriting or discarding their content.
- `streamer-watch.html` and `share-dispatchos.html` remain outside the 24-page shell matrix for
  their documented no-chrome and credential-gated boundaries. They require their own
  functional verification; exclusion from the shell matrix is not a verified verdict.

## 17. Completion boundary

Responsive rendering is not functional smoke. Task #109 remains open until the sequential UI
verification runner records every required browser suite as passing in
`ops/docs/SMOKE-APPLICATIONS.md`. A generated record containing a failure cannot satisfy the
task check, and no source-file edit can manufacture the required success line.

The runner is `node tests/run_ui_verification.mjs [baseURL]`. Its canonical order is
`applications_smoke.mjs`, `responsive.mjs`, `frontend.mjs`, then `chat_smoke.mjs`; the two
GPU-using suites are therefore never concurrent. Each child gets a complete log under
`run/ui-verification/`. `--dry-run` shows the exact commands without launching a browser,
and an interrupt is forwarded to the active process group so Chrome is not orphaned.
