# CSS collision audit — `site/symoneural.css`, `site/rack-detail.css`, `site/swagger-dark.css`

Read-only audit run ahead of the chat-page and image-page restyles. Every claim marked
**MEASURED** was confirmed in Chrome via Playwright against the live server at
`http://127.0.0.1:8800/`, by enumerating `document.styleSheets` (proving both rules are live in the
*served* CSS, not just on disk) and then `deleteRule()`-ing the later rule **in the page only** to
get a genuine before/after. Nothing on disk was touched. Scratch scripts:
`specs/extract.py`, `specs/verify.mjs`, `specs/hover3.mjs`, `specs/rules_*.json`.

Files audited, and where they load:

| File | Loaded by | Order |
|---|---|---|
| `site/symoneural.css` | index, chat, image, ravencalc, remix, documentation, build, account | 1st |
| `site/rack-detail.css` | same 8 pages | 2nd (deliberate depth pass) |
| `site/swagger-dark.css` | `/docs` only | standalone |
| `site/training.html` | inline `<style>`, **does not load symoneural.css** | isolated |

`site/swagger-ui.css` is a 2-line stub. `chat.html` and `image.html` have **zero** inline
`<style>` blocks (MEASURED — `document.querySelectorAll('style').length === 0` on both), so the
restyles have exactly two cascade layers to reason about.

---

## 1. BUG — `.card` is defined twice, bare, and the second definition is eating the first

This is a live fourth instance of the `.bar` / `.live` / `#console .sub` bug class.

| Occurrence | File:line | Selector | Specificity |
|---|---|---|---|
| Grid card (documentation.html) | `site/symoneural.css:118` | `.card` | 0,1,0 |
| Grid card hover | `site/symoneural.css:122` | `.card:hover` | 0,2,0 |
| Receipts card (index.html) | `site/symoneural.css:955` | `.card` | 0,1,0 |
| Receipts card hover | `site/symoneural.css:962` | `.card:hover` | 0,2,0 |

Both `.card` rules are **bare and equal specificity**, so source order alone decides — and the
one written for the homepage receipts grid (L955, inside the `.cards` block, commented "a card
grid, not a link list") is winning on every `.card` in the site, including the 11 completely
unrelated `<div class="card">` on documentation.html (`img.ico` + `h3` + `p`). It should have been
scoped `.cards .card`.

Usage: `.card` × 11 on `documentation.html`, × 8 on `index.html`. Different markup, one skin.

**MEASURED** on `/documentation.html` at 1400px, `.grid.g2 > .card`, with rule index 332
(`.card`, the L955 one) deleted in-page:

| Property | With L955 (what ships today) | With L955 removed (what L118 intends) |
|---|---|---|
| `display` | `flex` | `block` |
| `flex-direction` | `column` | `row` |
| `padding` | `18px 17px 16px` | `22px` |
| `background-image` | `linear-gradient(rgb(28,34,30), rgb(22,26,24))` | `none` |
| `background-color` | `rgba(0,0,0,0)` | `rgb(22,26,24)` |
| `transition-property` | `border-color, transform, background` | `border-color` |

**MEASURED** hover on the same element (inline `style="border-color:…"` removed in-page so the
delta is visible):

| Property | Live | L955/L962 removed |
|---|---|---|
| `:hover` `border-top-color` | `rgba(46, 224, 138, 0.45)` (green) | `rgb(58, 69, 62)` (`#3a453e`) |
| `:hover` `transform` | `matrix(1,0,0,1,0,-2)` (lifts 2px) | `none` |

Severity: **high.** The *geometry* is coincidentally near-identical — measured height changed by
1px (400 → 401), because the reclaimed 4–5px of padding is absorbed by the `h3`/`p` margins inside
— which is why nobody has caught it. The *paint and behaviour* are not identical: the
documentation cards are inset 22px → 18px/17px/16px, filled with the homepage's gradient instead
of the flat `--panel` they were designed as, and they lift 2px and glow green on hover. They are
wearing the receipts skin. Any restyle that touches `.card` lands on top of this. Do not add a
`.card` variant; `symoneural.css:955–990` needs scoping to `.cards .card` (with its
`:hover`/`:focus-visible`/`b`/`s` children and `.ctag`/`.cdesc`) before `.card` is safe to reason
about at all.

Related, same block, same shape but currently harmless because the markup does not collide:
`.card:focus-visible` (L966), `.card b` (L971), `.card s` (L980), `.card:hover s` (L984),
`.card img.ico` (L123), `.card h3` (L124), `.card p` (L125), `.card code` (L127) — two components'
child rules sharing one parent class.

---

## 2. Deliberate second definitions — verified benign, listed so nobody panics

All confirmed to be intentional (each carries an explanatory comment), and each verified as either
adding a property or overriding one on purpose.

| Selector | Lines | Verdict |
|---|---|---|
| `.mod` | `symoneural.css:486`, `:1012` | L1012 adds `display:flex; flex-direction:column`. No property overlap. **MEASURED** `.mod` on index = `display:flex`. Note. |
| `.mod .sub` | `symoneural.css:525`, `:1017` | L1017 overrides `margin-top: 7px → auto` and restates `font-size:11.5px` (already inside the L525 `font:` shorthand — redundant but harmless). Deliberate: pushes the provenance line to the bottom of a stretched module. **MEASURED** `.mod .sub` = 11.5px, `.mod .plain` = 13px — the `#console .sub` inversion is fixed and holding. |
| `.console` | `symoneural.css:482`, `:1022` | L1022 adds `align-items:stretch`. Note. |
| `details.fold` | `symoneural.css:570`, `:680` | L680 `margin:0 0 8px` overrides L570 `margin-top:10px`. Deliberate (fold-stack density pass). Note. |
| `.mod::before` / `.mod::after` | `:492` then `:496` / `:497` | Shared-then-specific. Fine. |
| `th` | `:149` (`th,td`) then `:150` | Shared-then-specific. Fine. |
| `.led.on` / `.led.amber` / `.led.blue` | `rack-detail.css:119–121` then `:122` | Sets `--c`, then one shared rule consumes it. Fine. |

Every remaining duplicate in the file is a **responsive override inside `@media`** and is correct
by construction: `.g2/.g3/.g4`, `.mh`, `.rackrow`, `.cards`, `.eyebrow`, `.hero h1`, `.lede`,
`.actions`, `#rack`, `.foot nav`, `.pgwrap`, `.unit`, `.led.blink`, `.scan i`, `.chassis`,
`.chassis-id`, `.split-in`, `.hero.split h1`, `.masthead`, `.gart`, `.order`, `.cf-keys`,
`.cf-keys p`, `.cf-keys p:last-child`, `.sky`, `.sky-lines`, `.sky-art`, `.sky .q`, `html`.

The whole of `rack-detail.css` redefining `.rack .rail .unit .pwr .ubus .led .scan .chassis .bar
.mod .console .conhead` is the documented depth pass — loaded second on purpose, touches only
paint properties. Not a finding.

`swagger-dark.css`: every selector is under `.swagger-ui`, and it loads only on `/docs`. No risk.

---

## 3. Specificity traps — the `#console .sub` shape, currently unfired

`symoneural.css:719–744` is a `@media (min-width:900px)` density block written with **id
selectors**. Every rule in it is (1,0,1) and beats the component's own (0,1,0) rule silently, above
900px only. This is exactly the shape that produced the `#console .sub` bug. It is intentional
today, but any restyle that changes one of these components loses on desktop and works on mobile —
the hardest failure mode to notice.

**MEASURED** on `/` at 1400px (id rules active) vs 880px (base rules), same element:

| Selector | 1400px (id rule wins) | 880px (component rule) | Component rule it outranks |
|---|---|---|---|
| `#console .mod` (`:743`) | `padding: 10px 12px 9px` | `padding: 13px 14px 12px` | `.mod` `symoneural.css:486` |
| `#rack .unit` (`:735`) | `padding: 9px 15px`, `gap: 13px` | `padding: 13px 16px`, `gap: 16px` | `.unit` `:354` |
| `#console .console` (`:741`) | `gap: 8px`, 6 columns | `gap: 10px`, 4 columns | `.console` `:482` |
| `#console h2` (`:727`) | `font-size: 26px` | `font-size: 25.52px` | `section h2` `:108` |
| `#rack > .wrap > .sub` (`:729`) | `font-size: 15px` | `font-size: 16px` | `.sub` `:109` |

Also in this shape, lower risk: `#rack .units` (`:736`), `#rack .chassis` (`:737`),
`#console .conhead` (`:740`), `#rack .shead, #console .shead` (`:728`),
`#rack > .wrap > .tnote` (`:732`), `#rack` (`:102`, `:726`).

Confirmed **not** regressed (all three historic bugs still fixed, MEASURED on `/` at 1400px):

- `header .bar` = **66px** tall; `.gauge .bar` = **7px**. The `header .bar` scoping (`:44`) holds.
- `header .bar::after` content = **`none`**; `.gauge .bar::after` = **`""`**. The
  `rack-detail.css:163` exclusion keeps the silkscreen ticks off the nav.
- `.conhead .key.live` and `.conhead .key.meas` are **geometrically identical** (h 23px,
  `padding 5px 10px`, `border-radius 999px`) — `a.live` (`:309`) is no longer bleeding onto the
  legend.
- `.mod .sub` 11.5px < `.mod .plain` 13px — the size inversion is gone.
- **Zero** elements on `/` have `text-overflow: ellipsis`. The no-ellipsis rule holds.

One live cross-file bleed, harmless but real: `rack-detail.css:164` `.bar{position:relative}` is
**bare** and does apply to the site header — **MEASURED** `header .bar` (`<div class="wrap bar">`)
has `position: relative` on chat.html. It changes nothing today. Any future `.bar` gets it.

Dead-but-armed rule: `a.live` (`symoneural.css:309–316`) matches nothing on any page any more
(the nav badge is gone; `live` now appears only as `.conhead .key.live` on index.html and once
inside training.html's isolated stylesheet). It is a landmine for any future `<a class="live">`.

---

## 4. Dangerously generic names currently in use

Single common words a restyle would plausibly reach for. **Never redefine these bare.**

| Name | Where defined | Scope | Uses | Note |
|---|---|---|---|---|
| `.card` | `sym:118`, `sym:955` | **BARE ×2** | 19 (doc 11, index 8) | **Already collided — see §1** |
| `.bar` | `sym:44` (`header .bar`), `sym:459`, `rack-detail:164`, `:165` | mixed | 10 | Historic bug; header form is scoped, gauge form is bare |
| `.sub` | `sym:109` bare, `sym:525`/`1017` (`.mod .sub`), `sym:729` (`#rack/#console > .wrap > .sub`) | **BARE** | 34 | Historic bug; three definitions across two specificity tiers |
| `.live` | `sym:309` (`a.live`), `sym:560` (`.conhead .key.live`), `sym:993` (`.live-card`) | scoped | 2 | Historic bug; all three now scoped |
| `.panel` | `sym:249` | **BARE** | 4 (chat, image, ravencalc, remix) | Also the name of `--panel`/`--panel2` tokens. Occupied on both restyle pages. |
| `.grid` | `sym:112` | **BARE** | 5 | |
| `.tag` | `sym:499` (`.mod .tag`) | scoped to `.mod` | 19 (index) | A bare `.tag` would restyle every console module label |
| `.head` | `sym:212` (`.stage .head`) | scoped to `.stage` | 4 | Occupied on chat + image |
| `.body` | `sym:222` (`.stage .body`) | scoped to `.stage` | 4 | Occupied on chat + image |
| `.on` | `sym:172,219,772,1167`, `rack-detail:119` | compound only (`.tab.on`, `.led.on`, `.lightbox.on`, `s.on`) | 7 | **A bare `.on` would be the worst possible addition to this file** |
| `.warn` | `sym:139,462,540`, `rack-detail:173` | compound only | 1 + JS | `console.js:65` does `classList.toggle('warn', …)` |
| `.art` | `sym:1091` (`.sky .art`) | scoped to `.sky` | 19 (build) | Undefined bare — high-value name, deliberately namespaced |
| `.q` | `sym:1107` (`.sky .q`) | scoped to `.sky` | 4 (build) | |
| `.row` / `.rows` | `sym:607` (`.assist .rows`) | scoped to `.assist` | 1 | `.row` is **free** |
| `.key` | `sym:550` (`.conhead .key`) | scoped | 3 | |
| `.val`, `.plain`, `.meter`, `.sm` | `sym:518,1013,537,524` | scoped to `.mod` | 19 each | |
| `.who`, `.msg`, `.meta`, `.you`, `.bot` | `sym:227,233,235,231,232` | scoped to `.turn`/`.assist` | chat | Occupied on chat.html |
| `.cap` | `sym:278` (`.shot .cap`) | scoped to `.shot` | image | Occupied on image.html |
| `.slot`, `.txt` | `sym:421,425` | scoped to `.ustate` | index | |
| `.hi`, `.num` | `sym:138,153` | compound (`.metric.hi`, `td.num`) | 102 | |
| `.ico` | `sym:123` (`.card img.ico`) | scoped to `.card` | 5 | Inherits the §1 problem |

### Single-letter classes — the highest-risk names in the file

All currently scoped; every one is a loaded gun.

| Class | Definitions | Uses |
|---|---|---|
| `.a` | `pre.code .a` (`sym:181`), `.tracks .a` (`sym:302`) | documentation, remix |
| `.c` | `pre.code .c` (`sym:179`) | documentation ×15 |
| `.g` | `pre.code .g` (`sym:180`) | documentation ×8 |
| `.p` | `pre.code .p` (`sym:182`) | documentation ×13 |
| `.t` | `pre.code .t` (`sym:165`), `.tracks .t` (`sym:301`) | documentation, remix |
| `.k` | `td.k` (`sym:156`), `.readout .k` (`sym:287`), `.assist .k` (`sym:611`) | **63** |
| `.v` | `.readout .v` (`sym:288`), `.assist .v` (`sym:612`) | ravencalc |
| `.w` | `.tracks .w` (`sym:303`) | remix |
| `.r` | `.rail.r` (`sym:345`, `rack-detail:50`) | index |

`.k` and `.v` are already used on **two different components each**, and `.k` appears 63 times.
`chat.html:211` builds `<span class="k">` at runtime for the RavenCalc assist rows.

---

## 5. Reserved-name list

Every class name defined in `symoneural.css` + `rack-detail.css`. One per line, sorted, greppable.
Tags: `BARE` = matches any element carrying the class anywhere (highest collision risk);
`scoped:X` = only inside `X`; `compound:X` = only as `.X.name`.
**Do not define any of these bare in a restyle.**

```
.a                scoped: pre.code, .tracks
.absent           compound: .badge
.actions          BARE
.am               scoped: pre.code .t
.amber            compound: .led
.art              scoped: .sky
.assist           BARE
.bad              scoped: .assist, .readout
.badge            BARE
.bar              BARE  (+ header .bar, + rack-detail bare)   *** historic bug ***
.blink            compound: .led
.blue             compound: .led
.body             scoped: .stage
.bot              compound: .turn
.busy             scoped: .stage .head s
.c                scoped: pre.code
.callout          BARE
.cap              scoped: .shot
.card             BARE ×2                                     *** LIVE COLLISION ***
.cards            BARE
.caret            BARE
.cdesc            BARE
.cf-keys          BARE
.cf-rule          BARE
.chassis          BARE
.chassis-id       BARE
.code             compound: pre.code
.composer         BARE
.confoot          BARE
.conhead          BARE
.console          BARE ×2
.crt              compound: .console
.cspec            BARE
.cta              BARE  (+ .cta.ghost, button.cta)
.ctag             BARE
.ctl              BARE
.eyebrow          BARE
.fold             compound: details.fold
.foldbody         scoped: details.fold
.foot             BARE
.g                scoped: pre.code
.g2 .g3 .g4       BARE
.gart             BARE
.gauge            BARE
.ghost            compound: .cta
.gprov            BARE
.gq               BARE
.grid             BARE
.grow             scoped: .stage .head
.gwrap            BARE
.gzoom            BARE
.head             scoped: .stage
.hero             BARE  (+ .hero.split)
.hi               compound: .metric
.hint             BARE
.ico              scoped: .card (img.ico)
.k                scoped: td, .readout, .assist
.k-live .k-meas .k-proj   BARE
.key              scoped: .conhead
.layer            BARE
.lb-close .lb-fig .lb-meta .lb-prompt   BARE
.led              BARE
.lede             BARE
.leds             BARE
.lgrid            BARE
.lhead            BARE
.lightbox         BARE
.live             scoped: a.live, .conhead .key.live         *** historic bug ***
.live-card        BARE
.logo             BARE
.masthead         BARE
.meas             compound: .badge; scoped: .conhead .key
.meta             scoped: .turn
.meter            scoped: .mod
.metric           BARE
.mh .mh-body .mh-foot .mh-hero .mh-lede .mh-pitch   BARE
.mod              BARE ×2
.msg              scoped: .turn
.na               compound: .badge
.navlink          BARE
.neg              compound: .card
.num              compound: td
.ok               compound: .badge
.on               compound: .tab, .led, .lightbox, s (in .stage .head / pre.code .t)
.order            BARE
.p                scoped: pre.code
.panel            BARE
.pgwrap           BARE
.plain            scoped: .mod
.proj             scoped: .conhead .key
.pwr              BARE
.q                scoped: .sky
.r                compound: .rail
.rack             BARE
.rackrow          BARE
.rail             BARE
.readout          BARE
.rows             scoped: .assist
.scan             BARE
.scell            BARE
.seg              BARE
.shead            BARE
.shot             BARE
.shots            BARE
.sky .sky-art .sky-foot .sky-lede .sky-lines .sky-mid   BARE
.slot             scoped: .ustate
.sm               scoped: .mod .val
.sp               scoped: .conhead
.split            compound: .hero
.split-in         BARE
.split-side       BARE
.stack            BARE
.stage            BARE
.steps            BARE
.sub              BARE (+ .mod .sub, + #rack/#console > .wrap > .sub)   *** historic bug ***
.t                scoped: pre.code, .tracks
.tab              BARE  (+ .tab.on)
.tabpanel         BARE
.tabs             BARE
.tag              scoped: .mod
.tiny             scoped: .mh-hero, .split-side
.tnote            BARE
.tracks           BARE
.turn             BARE
.tw               BARE
.txt              scoped: .ustate
.ubus             BARE
.uname            BARE
.unit             BARE
.units            BARE
.ustate           BARE
.v                scoped: .readout, .assist
.val              scoped: .mod
.w                scoped: .tracks
.warn             compound: .metric, .bar, .mod .meter
.who              scoped: .turn, .assist
.wrap             BARE
.you              compound: .turn
```

Also reserved by `training.html`'s isolated inline stylesheet (safe today because that page does
**not** load `symoneural.css` — but do not promote any of these into the shared sheet without
checking): `.brand .chip .flag .hide .in .l2 .l3 .lib .navgrp .navinner .navtoggle .pass .shell
.sn-bar .strip .waive`, plus its own `.masthead .live .sp .sub .eyebrow .tw`.

**What is free:** the complement of this block plus the `training.html` block below. Anything not
listed in either is unclaimed. Single common words verified unused across all three stylesheets and
all nine pages, so safe to take (still better prefixed): `.row`, `.col`, `.pill`, `.chip` (taken
only inside training.html's isolated sheet), `.note`, `.stat`, `.bubble`, `.thread`, `.prompt`,
`.result`, `.frame`, `.tile`.

Element selectors are also global and unscoped in `symoneural.css`: `header, nav, section, footer,
table, caption, th, td, tbody tr, pre.code, details.fold, body, html, a, img, h1, h2, h3, button`.
A restyle that puts a `<table>` or a `<section>` on chat/image inherits all of them.

---

## 6. Runtime-only class names

Built by JS, invisible to a `grep 'class='` of the static HTML. All must be treated as taken.

| Class | Created at |
|---|---|
| `turn`, `you`, `bot` | `chat.html:152` — `className = 'turn ' + cls` |
| `msg`, `who`, `meta` | `chat.html:153`, `:227`; read back via `querySelector('.msg')` at `:165` |
| `caret` | `chat.html:169`, `:197` |
| `assist`, `rows`, `k`, `v` | `chat.html:204–213` |
| `shot`, `cap` | `image.html:169`, `:189`, `:199` |
| `tracks`, `t`, `a`, `w`, `hint` | `remix.html:157–171` |
| `k`, `v`, `bad` | `ravencalc.html:165–177` |
| `busy` / `on` | `chat:121`, `image:134`, `ravencalc:133`, `remix:123` — `className = busy ? 'busy' : 'on'` on the stage-head `<s>` |
| `warn` | `console.js:65` — `classList.toggle('warn', …)` |
| `on` | `ui.js:21,103,110,126` — tab + lightbox state |
| `lightbox`, `lb-fig`, `lb-prompt`, `lb-meta`, `lb-close` | `ui.js:68–84`, built entirely at runtime |
| `led`, `leds`, `pwr`, `scan`, `slot`, `txt`, `ubus`, `uname`, `unit`, `ustate` | `console.js` rack markup |

---

## 7. What the two restyles are walking into

**`chat.html` already occupies** (MEASURED from the rendered DOM):
`bar body bot callout composer cta ctl eyebrow foot grow head hero hint lede logo msg navlink panel
pgwrap stage turn who wrap` — plus runtime `assist rows k v caret meta you busy on`.

**`image.html` already occupies** (MEASURED):
`bar body callout cap composer cta ctl eyebrow foot grow head hero hint lede logo navlink panel
pgwrap seg shot shots stage wrap` — plus runtime `busy on`.

Recommendations for the restyles, in priority order:

1. **`.card` needs scoping to `.cards .card` before either restyle touches it**, otherwise a third
   `.card` definition arrives on top of an already-colliding two. Sequencing is the lander's call.
2. **Namespace both restyles** the way `.sky-*`, `.mh-*`, `.lb-*` and `.cf-*` already do — a short
   prefix per page (`.ch-*`, `.im-*`) is the only pattern in this file that has never produced a
   collision.
3. **If a shared component must be styled, scope it to its parent**, not to an id. `#console .sub`
   was correct-looking and wrong; `.mod .sub` is correct. Prefer `.stage .foo` over `#chat .foo`.
4. **Never introduce a bare rule for any name in §5.** The nine that are already taken or already
   burned and would be the worst additions: `.on`, `.wrap`, `.head`, `.body`, `.bar`, `.tag`,
   `.sub`, `.card`, `.live` — plus `.art` and `.q`, which are namespaced only by convention.
5. **After landing, verify by rendering.** Re-run `specs/verify.mjs` (it needs no repo write) or
   add the equivalent assertion to `tests/frontend.mjs`: read the computed style, do not reason
   about the cascade.

## Unverified

- Nothing in `swagger-dark.css` was rendered — `/docs` is served by the API, not the static path
  under test. Its `.swagger-ui` namespacing was confirmed by reading, not by measurement.
- `account.html` and `build.html` were not individually measured; their class usage was taken from
  static parsing only.
- `training.html` was not rendered. Its isolation from `symoneural.css` was confirmed by grepping
  its `<link>` tags, not by measurement.
