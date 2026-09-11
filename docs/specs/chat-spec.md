# chat.html restyle — implementation brief

**Goal:** the llama.cpp web UI *layout* (slim left icon rail, centred empty state, one large
rounded composer) rendered in the SyMoNeuRaL palette and component vocabulary.

**Scope of the change:** `tools/build_pages.py` → `CHAT_BODY` (and two named lines in `CHAT_JS`),
plus one appended block in `site/symoneural.css`. **`SHELL` is not touched** — it is shared by
`image.html`, `ravencalc.html`, `remix.html` and `miner.html`, and every one of them would
inherit the change.

> **Before you start — this spec was written against a moving tree.** Concurrent agents were
> editing `tools/build_pages.py`, `site/chat.html`, `site/console.js`, `backend/api.py` and
> `tests/frontend.mjs` while it was being written. Two consequences, both verified at the time
> of writing:
> - Every `build_pages.py` line number cited below is **still correct**: the concurrent change
>   is a pure insertion at line 561+ (a new `MINER_BODY` / miner page) and everything this spec
>   touches lives above line 290. Re-check with the greps given rather than trusting the numbers.
> - `SHELL` is now shared by **five** pages, not four (`site/miner.html` is new). That
>   strengthens the core rule here: **do not touch `SHELL`, `.pgwrap`, `.stage`, `.panel` or
>   `.composer`.** Rebase and re-run the greps in §4 before you write anything.

Screenshots backing the numbers below are beside this file:
`ref-1600.png`, `ref-1100.png`, `ref-390.png` (reference), `now-1600.png`, `now-390.png` (today).
Geometry was read out of `getComputedStyle` + `getBoundingClientRect` in Chrome, not eyeballed;
the raw dump is `../measure.txt`.

---

## 1. The reference, measured

Served from `contrib/llama.cpp/tools/ui/dist` on :8877, Chrome, `colorScheme: dark`.

### 1600 × 1200

| Thing | Measurement |
|---|---|
| Rail `<aside>` | 48 × 1182 at x=8, y=8 — `border-radius:16px`, `margin:8px`, transparent bg |
| Horizontal cost of rail | **56px** (content column `.flex-1` starts at x=56) |
| Rail item (button) | 36 × 36, `border-radius:9999px`, transparent until hover |
| Rail item pitch | **40px** (buttons at y=60, 100, 140, 180 → 36px + 4px gap) |
| Rail icon | 16 × 16 (`h-4 w-4`), stroke icons |
| Logo button | 36 × 36 at y=16; 8px gap, then the nav group starts at y=60 |
| Content column | **max-width 768px** (`max-w-3xl`), `margin-inline:auto`; page padding 16px |
| Empty-state `h1` | 30px / 600 / lh 36px, `margin-bottom:8px`, centred |
| Empty-state `p` | 18px / 400 / lh 28px, muted colour, centred |
| Greeting block → composer | 32px |
| Composer outer | 768 × **118**, `border-radius:24px`, bg `muted/75`, border `1px rgba(255,255,255,.06)` |
| Composer inner padding | `12px 0` vertical; textarea row `padding:0 20px 6px` |
| Textarea | 726 × 48 (`min-h-12`), 16px / lh 24px, transparent, `border:0`, `resize:none` |
| Action row | full width × **32px**, `padding:0 12px`, `gap:12px` |
| "+" button | 32 × 32 circle, bg `rgba(255,255,255,.15)`, icon 16px |
| Model chip | 26 × 22, `border-radius:6px`, 12px text, **`max-width:512px`** |
| Send button | 32 × 32 circle, bg `oklch(.922 0 0)` (near-white), 16px dark arrow |

### 1100 × 1200
Identical. The rail stays 56px; the content column stays pinned at 768px and simply gains
gutters. **There is no intermediate breakpoint** — one desktop layout, one mobile layout.

### 390 × 844 (below `md`, 768px)
| Thing | Measurement |
|---|---|
| Rail | becomes a **fixed full-width overlay sheet** — `w-[calc(100dvw-1rem)]`, `border-radius:24px`, holds a conversation list |
| Content | `padding-top:48px` (clears the fixed logo button), `padding-bottom:192px` (clears the fixed composer) |
| Composer | 374 wide, `border-radius:32px` (`rounded-4xl`), action row grows to **36px** |
| Empty-state `h1` | drops 30px → **24px**; sub 18px → 16px |

### The spacing rhythm, distilled
Everything is on a **4px grid**: 4 (rail gap) · 8 (rail margin, heading→sub) · 12 (composer
pad-y, action gap) · 16 (page pad) · 20 (textarea pad-x) · 32 (greeting→composer). Radii come in
two sizes only: **9999px** for every circular control, **24px** for the composer.

---

## 2. Take / reject

### Take
1. **The 56px icon-only rail.** It is the layout cue the user asked for and it earns its keep
   here: it becomes a *surface switcher* (Chat / Image / RavenCalc / Remix / API), which is the
   rack's own vocabulary applied to a page you are already standing on.
2. **The 768px centred column.** Today the chat stage is a 1fr column in `.pgwrap` next to a
   300px `.panel` — see `now-1600.png`: at 1600px the transcript is ~740px wide but the page is
   *also* only 340px tall, so most of the screen is empty. A fixed 768px measure fixes the line
   length and lets the composer be big.
3. **One large rounded composer**, textarea over a control row, send as a circle on the right.
4. **The centred empty state**: short heading + one muted sentence, vertically centred in the
   transcript box, replaced by the transcript as soon as a turn exists.
5. **The 4px spacing grid and the two-radius rule.** Both already match our system
   (`.mod` = 10px, `.card` = 14px, `.cta` = 999px).
6. **Single desktop breakpoint.** Our stylesheet already has too many; do not add a third.

### Reject
1. **Every truncation in it.** The reference puts `line-clamp-1` on its banner title and
   `max-width:512px` on the model chip. That chip is exactly where
   `SymonChat S1-7B · built on Qwen2.5-7B-Instruct` would sit, and clipping it breaks an
   Apache-2.0 attribution condition. Our model line is a full-width caption that **wraps**
   (`overflow-wrap:anywhere`, no `white-space:nowrap`, no `text-overflow`). Non-negotiable —
   see `.claude/CLAUDE.md` and the comment at `site/symoneural.css:396`.
2. **The "+" attachment button.** `backend/api.py` exposes `/api/chat`, `/api/image`,
   `/api/gen/{name}`, `/api/ravencalc`, `/api/remix`, `/api/status`, `/api/ws` — there is no
   upload endpoint. A button that cannot do anything is a decorative control.
3. **The search icon and the conversation list.** Verified: no persistence endpoint exists and
   `/api/chat` takes a single `prompt`, not a message array. There is nothing to list or search.
4. **The mobile overlay drawer.** It needs open/close JS and a scrim. Our rail is six links; on
   a phone it becomes a horizontal strip. No new JS.
5. **The near-white send button** (`oklch(.922 0 0)`). Use `var(--accent)` on `var(--accent-ink)` —
   the same pair `.cta` already uses.
6. **Destructive red.** Errors on this site are `var(--amber)`; `CHAT_JS` already sets
   `msg.style.color = 'var(--amber)'` on failure.
7. **Full-bleed app shell** (rail flush to the viewport edge). That requires editing `SHELL`,
   which would restyle three other pages, and it would drop the site header — the only way off
   this page. See **§6 Q1**.

---

## 3. Markup skeleton

Replaces `CHAT_BODY` in `tools/build_pages.py` (~line 143). **Every existing `id` is preserved
byte-for-byte**, so `CHAT_JS` keeps working; only classes and nesting change.

```html
<div class="cu">                                   <!-- namespace root; ALL new CSS is scoped to this -->

  <!-- NOT a <nav>. See §4: `nav a:not(.cta){display:none}` at symoneural.css:77 would delete
       every rail link at <=780px, and `nav{margin-left:auto;gap:24px}` at line 55 would shift
       it. role="navigation" gives the same semantics with none of the element selectors. -->
  <div class="cu-rail" role="navigation" aria-label="Live surfaces">
    <!-- Real destinations, all already in the rack on the home page.
         aria-current marks this page; there is no "active" invention.
         aria-label on the <a>, not just title=: alt="" leaves the link with no
         accessible name at all. -->
    <a class="cu-railbtn" href="/" aria-label="Live stack" title="Live stack">
      <img src="/mark-32.png" alt="" width="22" height="22"></a>
    <a class="cu-railbtn" href="/chat.html" aria-current="page" aria-label="Chat" title="Chat">
      <img src="/chat-64.png" alt="" width="22" height="22"></a>
    <a class="cu-railbtn" href="/image.html" aria-label="Image" title="Image">
      <img src="/image-64.png" alt="" width="22" height="22"></a>
    <a class="cu-railbtn" href="/ravencalc.html" aria-label="RavenCalc" title="RavenCalc">
      <img src="/calc-64.png" alt="" width="22" height="22"></a>
    <a class="cu-railbtn" href="/remix.html" aria-label="Remix" title="Remix">
      <img src="/dj-64.png" alt="" width="22" height="22"></a>
    <a class="cu-railbtn" href="/docs" aria-label="API" title="API">
      <img src="/terminal-64.png" alt="" width="22" height="22"></a>
  </div>

  <div class="cu-col">                              <!-- the 768px measure -->

    <!-- The request-state strip. KEEP #chead, the <s> and .grow: status() in SHELL's inline
         script does $('s', el) and $('.grow', el) and both lookups are null-safe, so dropping
         either kills the busy indicator with no error. The dot reflects a real request, which
         is what makes it allowed. -->
    <div class="cu-head" id="chead"><s></s>SyMoNeuRaL Chat<span class="grow">idle</span></div>

    <!-- #log keeps its id and its overflow so log.scrollTop = log.scrollHeight still works.
         The empty state lives INSIDE #log and is hidden by :has() the moment JS appends the
         first .turn -- no JS change, and it degrades to "always visible" on a browser without
         :has(), which is a greeting, not a broken page. -->
    <div class="cu-log" id="log">
      <div class="cu-empty">
        <h2>Ask the box something.</h2>
        <p>Ask me about this machine, what we build, or local AI engineering generally. I run
           on the RTX 5070 Ti described on the home page &mdash; nothing you type here leaves
           the box.</p>
      </div>
    </div>

    <form class="cu-box" id="form">                 <!-- was class="composer" -->
      <textarea class="cu-field" id="prompt" rows="1" maxlength="1200"
                placeholder="Why is decode memory-bandwidth bound?"></textarea>
      <div class="cu-tools">
        <span class="cu-model">SymonChat S1-7B &middot; Q4_K_M &middot; built on
              Qwen2.5-7B-Instruct</span>
        <button class="cu-send" id="send" type="submit" aria-label="Send">
          <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4"
               stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">
            <path d="M12 19V5"/><path d="M5 12l7-7 7 7"/></svg>
        </button>
      </div>
    </form>

    <!-- Parameters: folded, not deleted. details.fold is an existing component
         (symoneural.css:570). Every id and both hint paragraphs survive verbatim. -->
    <details class="fold cu-params">
      <summary>Parameters <span>temperature &middot; max tokens</span></summary>
      <div class="foldbody">
        <div class="ctl">
          <label for="temp">Temperature <b id="tempv">0.7</b></label>
          <input type="range" id="temp" min="0" max="1.5" step="0.05" value="0.7">
        </div>
        <div class="ctl">
          <label for="toks">Max tokens <b id="toksv">320</b></label>
          <input type="range" id="toks" min="16" max="512" step="16" value="320">
        </div>
        <p class="hint">Low temperature keeps it factual; high makes it wander. Both are
           clamped server-side &mdash; the sliders describe the range, they do not define it.</p>
        <p class="hint" id="stat">&nbsp;</p>
      </div>
    </details>

  </div>
</div>
```

**Existing classes reused unchanged, read-only:** `.turn`, `.turn.you`, `.turn.bot`, `.who`,
`.msg`, `.meta`, `.caret`, `.assist` (+ `.rows` `.k` `.v` `.bad`) — all created by `CHAT_JS` at
runtime; `details.fold`, `.foldbody`, `.ctl`, `.hint`, `.grow`.

**Deliberately NOT reused:** `.pgwrap`, `.stage`, `.stage .head`, `.stage .body`, `.panel`,
`.composer`. All six are shared verbatim with `image.html`, `ravencalc.html`, `remix.html` (and now `miner.html`);
restyling any of them restyles three other live pages.

---

## 4. CSS namespace check

Every proposed name is prefixed `cu-` (**c**hat **u**I). The greps, run against both stylesheets
the page links (`symoneural.css` *and* `rack-detail.css`, which chat.html loads at line 9) plus
every file in `site/` and the generator:

```
$ grep -rn "\.cu\b\|\.cu-" site/symoneural.css site/rack-detail.css site/swagger-dark.css
  (no matches — namespace free)

$ grep -rn 'class="[^"]*cu-' site/ tools/build_pages.py
  (no matches)

$ for n in cu-shell cu-rail cu-railbtn cu-main cu-col cu-empty cu-log \
           cu-box cu-field cu-tools cu-send cu-model cu-head cu-params; do
    grep -rn -- "$n" site/symoneural.css site/rack-detail.css site/*.html \
                     site/console.js site/ui.js tools/build_pages.py | wc -l
  done
  0 0 0 0 0 0 0 0 0 0 0 0 0 0
```

| Proposed | Collision? | Note |
|---|---|---|
| `.cu` | none | scope root — **prefix every rule with it** |
| `.cu-rail` | none | **`.rail` is taken** — `symoneural.css:339` *and* `rack-detail.css` define it as the rack's 26px absolute strip. Using the bare name would be production bug #4 after `.bar`, `.live`, `#console .sub` |
| `.cu-railbtn` | none | |
| `.cu-col` | none | |
| `.cu-head` | none | **`.head` is taken** (`.stage .head`, shared by 3 pages) |
| `.cu-log` | none | |
| `.cu-empty` | none | |
| `.cu-box` | none | **`.composer` is taken**, shared by 3 pages |
| `.cu-field` | none | |
| `.cu-tools` | none | |
| `.cu-send` | none | |
| `.cu-model` | none | |
| `.cu-params` | none | modifier on the existing `details.fold` |

New ids: none. Existing ids kept: `#chead #log #form #prompt #send #temp #tempv #toks #toksv #stat`.

### The second half of the check: bare *element* selectors

A class grep cannot catch a global rule written against a tag name. Sweep every element the
skeleton introduces:

```
$ grep -nE '^\s*(nav|form|textarea|button|h2|h3|p|img|s|a|details|summary)[ ,{:]' \
        site/symoneural.css site/rack-detail.css

  symoneural.css:22   a{color:inherit}
  symoneural.css:23   img{max-width:100%; display:block}
  symoneural.css:55   nav{margin-left:auto; display:flex; align-items:center; gap:24px}
  symoneural.css:56   nav a{color:var(--dim); text-decoration:none; font-size:14.5px}
  symoneural.css:57   nav a:hover{color:var(--fg)}
  symoneural.css:58   a:focus-visible{outline:2px solid var(--accent); …}
```

Plus, one line further on:

```
  symoneural.css:77   @media (max-width:780px){ nav a:not(.cta){display:none} }
```

🔴 **This is why the rail must not be a `<nav>`.** Every `.cu-railbtn` is an `<a>` with no `cta`
class, so inside a `<nav>` all six would be `display:none` at ≤780px — an empty 56px column
between 760 and 780px, and an empty strip below 760px. `role="navigation"` on a `<div>` gives
the same semantics and matches none of these selectors. `a{color:inherit}`, `img{display:block}`
and `a:focus-visible` are all benign or wanted.

**`<s>` is `<strike>`.** It defaults to `text-decoration:line-through`, which is why every
existing dot rule in this stylesheet (`.stage .head s`, `a.live s`, `.mod .tag s`, `pre.code .t s`)
carries `text-decoration:none`. The new dot rules must too — written out in full below, not
"reuse the `.stage .head` ones": `status()` sets `dot.className = 'on'` or `'busy'`, so an
implementer who writes only `.cu-head s` gets a dot that never changes colour, and nothing errors.

**Where the CSS goes:** appended to `site/symoneural.css` in one `/* ==== chat surface ==== */`
block. `SHELL` has no per-page stylesheet hook and adding one would change all four pages;
`rack-detail.css` is the rack's enhancement layer and this is not the rack.

**Sanity rule for the implementer:** `grep -c "^\.cu" site/symoneural.css` must equal the number
of rules you added, and **no rule in the new block may start with anything but `.cu`**. Read the
computed styles back with a browser afterwards (`.claude/CLAUDE.md`: render and measure, do not
reason about the cascade).

### The numbers, ours

```
.cu            display:grid; grid-template-columns:57px minmax(0,1fr); margin-top:30px
.cu-rail       width:56px; border-right:1px solid var(--line); padding:6px 0;
               display:flex; flex-direction:column; align-items:center; gap:6px
.cu-railbtn    40x40; border-radius:10px; display:grid; place-items:center
               img 22x22; opacity:.55
.cu-railbtn:hover                 background:var(--panel2); opacity:1
.cu-railbtn[aria-current=page]    background:rgba(46,224,138,.11); opacity:1;
                                  box-shadow:inset 0 0 0 1px rgba(46,224,138,.3)
.cu-railbtn:focus-visible         outline:2px solid var(--accent); outline-offset:2px
                                  (rail pitch 46px = 40 + 6, vs the reference's 40 = 36 + 4)

.cu-col        max-width:768px; margin-inline:auto; padding:0 24px; min-width:0

.cu-head       display:flex; align-items:center; gap:10px;
               font:650 11px/1 ui-sans-serif,system-ui,sans-serif; letter-spacing:.13em;
               text-transform:uppercase; color:var(--faint);
               padding:0 0 10px; border-bottom:1px solid var(--line)
.cu-head .grow display:block; margin-left:auto; letter-spacing:.06em;
               text-transform:none; font-weight:500
/* All three rules are required. status() writes dot.className = 'on' | 'busy', so the
   base rule alone gives a dot that never changes colour and never errors.
   text-decoration:none is not optional -- <s> is <strike>. */
.cu-head s     width:8px; height:8px; border-radius:50%; background:var(--line);
               text-decoration:none; display:block; flex:none
.cu-head s.on    background:var(--accent)
.cu-head s.busy  background:var(--amber); animation:pulse 1.1s ease-in-out infinite

.cu-log        min-height:340px; max-height:min(58vh,560px); overflow-y:auto;
               padding:20px 2px 0
.cu-log:has(.turn) .cu-empty      display:none
.cu-empty      min-height:300px; display:grid; align-content:center; text-align:center
.cu-empty h2   font-size:clamp(24px,2.6vw,31px); font-weight:660; letter-spacing:-.016em;
               margin:0 0 8px            (mirrors the reference's 30px/600, in our scale)
.cu-empty p    color:var(--dim); font-size:16.5px; line-height:1.6;
               max-width:52ch; margin:0 auto
.cu .turn.you .msg   background:var(--panel2); border-radius:14px; padding:11px 15px;
                     max-width:82%; margin-left:auto; color:var(--fg)

.cu-box        margin-top:26px; background:var(--panel2);
               border:1px solid var(--line); border-radius:22px;
               padding:14px 0 10px; display:block
.cu-box:focus-within    border-color:var(--accent)
.cu-field      width:100%; min-height:48px; max-height:200px; resize:none;
               background:none; border:0; outline:none; color:var(--fg);
               padding:0 20px; font:15.5px/1.55 ui-sans-serif,system-ui,sans-serif
.cu-tools      display:flex; align-items:center; gap:14px;
               padding:8px 12px 0 20px; min-height:40px
.cu-model      flex:1; min-width:0; color:var(--faint);
               font:11.5px/1.45 ui-monospace,Menlo,Consolas,monospace;
               overflow-wrap:anywhere        /* NO nowrap, NO ellipsis -- licence condition */
.cu-send       flex:none; width:36px; height:36px; border-radius:50%; border:0;
               background:var(--accent); color:var(--accent-ink); cursor:pointer;
               display:grid; place-items:center
.cu-send svg   width:16px; height:16px
.cu-send[disabled]      opacity:.45; cursor:not-allowed
      /* required: the button loses class="cta", so button.cta[disabled] (line 273)
         no longer applies and send.disabled would have no visible effect */
.cu-send:focus-visible  outline:2px solid var(--accent); outline-offset:3px

.cu-params     margin-top:18px
```

Composer height check: 14 + 48 + 8 + 40 + 10 = **120px** (reference: 118).

### One breakpoint

```
@media (max-width:760px){
  .cu        grid-template-columns:minmax(0,1fr)
  .cu-rail   width:auto; flex-direction:row; overflow-x:auto; gap:6px;
             border-right:0; border-bottom:1px solid var(--line); padding:6px 2px
  .cu-railbtn  width:36px; height:36px
  .cu-col    padding:0
  .cu-box    border-radius:26px            /* reference goes 24 -> 32 at the same point */
  .cu-tools  min-height:44px; flex-wrap:wrap    /* the model line wraps above the button
                                                   rather than squeezing it */
  .cu-empty h2  font-size:24px
}
```
Measured budget at 390px: `.wrap` gives 334px of content; the rail row is 6 × 36 + 5 × 6 = **246px**,
so it fits without scrolling. No `overflow:hidden` anywhere in the new block.

---

## 5. Behaviour: what maps, what breaks

`site/console.js` and `site/ui.js` are **both inert on this page today** and stay inert:
the last line of `console.js` gates on `if (el('units') || el('m-vram')) connect();` — grep for
that condition rather than a line number, it is drifting (it was line 259, it is 266 as of the
concurrent ASIC-surface change) — and `ui.js` returns early with no
`.tab[role=tab]` and no `a.art, a.gart`. **There is no WebSocket on chat.html today.** Do not
describe the redesign as "keeping" one.

The live behaviour is entirely `CHAT_JS` plus the `status()`/`api()` helpers inlined by `SHELL`.

All line numbers below are **`tools/build_pages.py`** (the file you are editing), not `site/chat.html`.

| Binding | `build_pages.py` | Survives? |
|---|---|---|
| `$('#log')` + `log.scrollTop = log.scrollHeight` | 180, 198, 241, 284 | ✅ id kept; `.cu-log` keeps `overflow-y:auto`, so it is still the scroll container |
| `$('#form')`, `form.requestSubmit()` | 180, 190 | ✅ still a `<form id="form">` |
| `$('#prompt')` | 180 | ✅ |
| `$('#send')`, `send.disabled = …` | 180, 207, 283 | ⚠️ **needs `.cu-send[disabled]` CSS** (above) — the `cta` class is gone, so `button.cta[disabled]` (symoneural.css:273) stops applying and `disabled` becomes invisible |
| `$('#chead')` → `status(head, …)` | 181, 213, 283 | ⚠️ **`<s>` and `.grow` must stay inside `#chead`** — `status()` (SHELL, line 112) uses `$('s', el)` / `$('.grow', el)`, both null-safe, so losing either kills the busy indicator with no error |
| `$('#temp')`, `$('#toks')` | 220–221 | ⚠️ read to build the request body. Inside a **closed** `<details>` they are still in the DOM and `.value` reads fine — but assert it in the browser test |
| `$('#tempv')`, `$('#toksv')` | 182–183 | ✅ |
| `$('#stat')` | 274 | 🔴 **the trap.** This write is *inside the try*, on `ev.done`. Delete `#stat` and it throws `TypeError`, control lands in `catch` (278), which does `msg.innerHTML=''; msg.append(err.message)` and paints it amber — **a successful generation renders as an error, with the completed answer erased.** `#stat` must exist, even folded |
| `turn()` → `.turn/.who/.msg` | 193–200 | ✅ classes still defined globally; `.cu` only adds the user bubble |
| `.caret` streaming span | 212, 240 | ✅ |
| `.assist` box, `bot.parentNode.insertBefore` | 247, 265 | ✅ parent is `#log`, unchanged |
| `.meta` tok/s line | 269–273 | ✅ |
| SSE `data:` reader | 229–241 | ✅ untouched by markup |

### Two required one-line edits in `CHAT_JS`

1. **`build_pages.py:187`** — `Math.min(150, promptEl.scrollHeight)` must become
   `Math.min(200, …)` to match `.cu-field{max-height:200px}`. Left at 150 the box stops growing
   50px early and the CSS max never engages; the two numbers must agree or the textarea scrolls
   when it looks like it should still be growing.
2. **`build_pages.py:206`** — `promptEl.style.height = 'auto'` after submit. Harmless (CSS
   `min-height:48px` floors it) but confirm in the browser: the inline height only wins over the
   CSS `min-height` when it is larger, which is the behaviour we want.

### The greeting turn moves

Today `#log` ships one pre-rendered `<div class="turn bot">`. It becomes `.cu-empty` instead.
The copy is carried over **verbatim** — nothing is trimmed. If `:has()` is unavailable the
greeting simply stays above the first answer, which is the current behaviour.

### Optional: a live status readout in the rail foot

Wanted, but it is a real decision, not a freebie. `.claude/CLAUDE.md` forbids indicators that do
not reflect a reading, so this is all-or-nothing:

- **Do it:** add `<span id="m-holder">`, `<span id="m-queue">`, `<span id="con-link">` to a
  `.cu-railfoot`, **and** widen the gate on the last line of `console.js` to
  `if (el('units') || el('m-vram') || el('con-link')) connect();`. `txt()` fills all three for
  free and `offline()` degrades them correctly. Cost: a WebSocket (plus 4s polling fallback) on
  every chat page view, against a single contended GPU.
  **Do not** add `id="m-vrambar"` without its inner `<i>` — `meter()` does
  `n.firstElementChild.style.width` and throws on an empty node.
- **Don't do it:** ship no rail indicator. `#chead` already carries an honest request-state dot.

**Default recommendation: don't, in this change.** Ship the layout first; wire the socket as a
separate commit with its own frontend assertion.

### Tests

`tests/frontend.mjs` currently asserts nothing about `chat.html` (`grep -n 'chat.html\|#prompt\|#log'`
→ no hits). Add, per the house rule that every frontend fix earns an assertion:
1. `.cu-empty` is visible on load and its `<h2>` has non-zero height.
2. Typing into `#prompt` and submitting hides `.cu-empty` (i.e. `.turn` exists) — no live GPU
   needed; a `route.fulfill()` stub of `/api/chat` is enough.
3. `getComputedStyle($('.cu-model')).textOverflow !== 'ellipsis'` **and** its full text still
   contains `Qwen2.5-7B-Instruct` at 390px — the licence guard, as a test.
4. Nothing overlaps at 390px (the existing helper).
5. `#stat` exists in the DOM.
6. **At 390px, all six `.cu-railbtn` have non-zero height.** This is the regression guard for
   the `nav a:not(.cta){display:none}` trap in §4 — the failure is invisible on desktop and
   total on a phone, which is exactly the shape of the three bugs the house rule was written for.
7. After a `status(head,'generating',true)` call, `#chead s` has class `busy` and a computed
   `background-color` that is not the idle `var(--line)` — guards the three-rule dot.

### Generator hygiene

`build_pages.py` writes each page with a single `write_text` of a fully substituted `SHELL` —
there are no BEGIN/END markers and no in-place editing, so the "run every generator twice and
diff" rule is satisfied by construction. Run it twice anyway and diff, then check
`git diff --stat` touches only `site/chat.html` (and `site/symoneural.css` for the appended block).

---

## 6. Open questions — not guessed

1. **Full-bleed or inside `.wrap`?** This spec keeps the chat surface inside `SHELL`'s
   `section > .wrap` (max 1120px), so the rail sits at x≈240 on a 1600px screen rather than
   flush left. The reference is flush left. Going flush needs a new `@@FRAME@@` placeholder in
   `SHELL` — a shared-template change affecting three other pages. **Confirm with the user
   before doing it.**
2. **Does the hero stay?** `SHELL` hardcodes the "Talk to the box." hero above `@@BODY@@` (~230px)
   and the 16 GB callout below it. Both are kept here, so no copy is lost — but the hero heading
   and the empty-state heading now sit ~400px apart and both greet you. Author's call: either
   accept the repetition or change the empty-state heading. I have proposed
   "Ask the box something." as a placeholder; **the wording is not mine to decide.**
3. **Seed prompts in the empty state?** Natural for this layout (three `.cu-seed` buttons that
   fill `#prompt`), but it needs ~6 new lines in `CHAT_JS` and three pieces of copy. Not specced.
4. **Rail icon set.** I chose Home / Chat / Image / RavenCalc / Remix / API from the existing
   PNGs. Should `/documentation.html` or `/build.html` be in there too, and does an icon rail of
   raster PNGs at 22px look right next to the reference's 16px stroke icons? Worth one look at a
   rendered page before committing.
   **Heads-up:** a concurrent change is adding an **ASIC** surface (`backend/apps/asicminer/`,
   plus a `BUSES` table in `console.js`). If it lands with its own page, the rail gains a
   seventh item — 7 × 46 = 322px tall on desktop, still fine, and 7 × 36 + 6 × 6 = 288px on a
   390px phone, still fits. Re-check the count before you hardcode the list.
5. **Model attribution string.** I hardcoded `SymonChat S1-7B · Q4_K_M · built on
   Qwen2.5-7B-Instruct`, mirroring `backend/api.py:1122`. But `api.py` swaps `· Q4_K_M` for
   `+ persona adapter` when `training/adapter/symoneural-lora.gguf` exists, and the page would
   then be stale. Options: (a) accept the static string, (b) have `build_pages.py` read the same
   condition at build time, (c) fill it from `/api/status` at runtime. **(b) is cheapest and
   honest; confirm.**
6. **`max-height:min(58vh,560px)` on the transcript.** Chosen so the composer is always on
   screen without a `100dvh` app shell fighting the sticky header. If the user wants the
   composer pinned to the viewport bottom like the reference, that is question 1 again.
