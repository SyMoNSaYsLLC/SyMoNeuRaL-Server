# Restyling `site/image.html` — implementation brief

Scope: the image surface. Implemented by editing `tools/build_pages.py` (`IMAGE_BODY`,
`IMAGE_JS`, `SHELL`), `site/symoneural.css`, and `site/ui.js`. No new files, no new
generator.

**Blast radius, up front.** `SHELL` and `page()` are shared, so the hero and callout changes
regenerate **chat.html, image.html, ravencalc.html and remix.html**. Expect four changed
files in the diff. That is intended — one shell is why they cannot drift.

All measurements below were taken in system Chrome against the live local site at
`127.0.0.1:8800`, reading computed styles and bounding boxes. No GPU work was done; the
"three results" states were simulated by injecting DOM nodes, not by generating.

---

## 1. Diagnosis

### The four that answer "the text is all jacked up"

**D1 — the result caption is one 12px blob carrying three unrelated things.**

`tools/build_pages.py:377-381` concatenates the prompt, a newline, and the whole provenance
chain into a single text node and leans on `white-space:pre-line`:

```js
cap.textContent = `${prompt}\n${r.size}×${r.size} · ${r.steps} steps · ` +
                  `seed ${r.seed} · ${r.seconds}s on the card · ${r.model}`;
cap.style.whiteSpace = 'pre-line';
```

styled by `site/symoneural.css:278-279`:

```css
.shot .cap{padding:11px 14px; font-size:12px; color:var(--faint); line-height:1.6;
  font-variant-numeric:tabular-nums; border-top:1px solid var(--line)}
```

Measured at 1280px with three results: the tile is 222px wide, the image 222×222, and the
caption **138px tall — seven lines of 12px `--faint`**, taller than half the image it
describes. The visitor's prompt and the model attribution (`FLUX.1-schnell q4_k`, an
Apache-2.0 condition) are typographically identical and run together. Nothing on the page
distinguishes what was asked from what the machine did.

The site already solves this exact problem on the front page — `symoneural.css:882-891`,
`.gprov` (mono, provenance) and `.gq` (serif quote, the prompt) as two separate lines. The
image page is the only place a render appears without that split.

**D2 — `.shot`/`.cap` is press-ganged into being an empty state.**

`tools/build_pages.py:296-300`:

```html
<div class="shot" style="grid-column:1/-1;border-style:dashed">
  <div class="cap" style="border-top:0;text-align:center;padding:40px 20px">
```

Four inline overrides to make a 12px caption component behave as a panel. The result: the
page's single most important sentence — the instruction telling a first-time visitor what to
do — is rendered 698px wide at 12px in `--faint` (`#77837b` on `#0e100f`, 4.8:1; it clears AA,
but it is the weakest treatment on the page applied to the highest-priority content).

**D3 — the status line has `line-height:1` and wraps.**

`symoneural.css:215` and `:221`:

```css
.stage .head{... font:650 11px/1 ui-sans-serif,system-ui,sans-serif; letter-spacing:.13em;
  text-transform:uppercase; color:var(--faint)}
.stage .head .grow{margin-left:auto; letter-spacing:.06em; text-transform:none; font-weight:500}
```

`.grow` inherits `11px/1`. The busy string set at `build_pages.py:354` is 59 characters:
`loading the image model — chat is being evicted to make room`. Measured at 390px it wraps to
**3 lines, 33px tall, at 11px line-height — zero leading, lines touching**, and the head grows
36px → 58px. `.stage .head` has no `flex-wrap`, so a three-line status is jammed onto one flex
row beside the title. This is the literal "jacked up text" on a phone.

**D4 — the measures are 92ch and 140ch.**

- `.hero .lede`: `image.html:40` carries inline `font-size:16.5px`; `symoneural.css:723`
  (inside `@media (min-width:900px)`) sets `.lede{margin-top:15px; font-size:16px;
  line-height:1.55; max-width:92ch}`. Inline wins on size, the media rule wins on measure.
  Measured: **868px wide at 16.5px ≈ 100+ characters per line.**
  (Note: that rule is bare `.lede` and reaches seven pages — `account`, `build`,
  `documentation` and the four surfaces. Do **not** change it globally; opt out, see §3.)
- `.callout p` (`symoneural.css:191`) has **no `max-width` at all**. Measured **1016px at
  14.5px ≈ 140 characters per line** — the longest text block on the page. Every sibling body
  class caps its measure (`.lede` 66ch:96, `.sub` 72ch:109, `.tnote` 80ch:157); this one
  doesn't. `.callout` is also used 4× in `documentation.html`, so this fix **must be scoped**
  to the surface shell.

### Secondary — layout and interaction defects behind the same complaint

**D5 — the box you type into sinks below the fold.** `.stage` is a column flexbox with
`min-height:340px`, and `.stage .body{overflow-y:auto; flex:1; min-height:0}`
(`symoneural.css:208-222`) — but nothing caps the stage height, so `overflow-y` never engages
and the body grows without bound. Measured with three results: composer at **y=760** (below
the fold on a 900px viewport) and **y=1712 at 390px**. The control is two screens below where
the visitor is looking.

**D6 — the prompt field is a one-line `<input type=text maxlength=1200>`**
(`build_pages.py:305-306`). You can see roughly 60 of 1,200 permitted characters. The chat
page next door already has an auto-growing textarea (`build_pages.py:185-191`).

**D7 — `.hint` buries the argument.** `symoneural.css:270` sets 12px/`--faint`. The paragraph
explaining *why* guidance is pinned to 1.0 — the page's actual engineering content — is
smaller and fainter than everything around it, and `#stat` (the last-render readout) shares
the class and ships an `&nbsp;` placeholder (`build_pages.py:333`).

**D8 — dead measurement.** `const t0 = performance.now();` (`build_pages.py:365`) is assigned
and never read. The one honest live number the page could show while you wait is computed and
thrown away.

**D9 — the render cannot be opened.** A 768×768 file is shown at 222px with no link. Every
front-page render links to its PNG and gets the lightbox (`ui.js:59-127`,
`symoneural.css:1162-1192`). The page's strongest proof is its least inspectable image.
`ImageResult` also returns `bytes` (`api.py:1470`), which the page discards.

**D10 — inline styles fighting the cascade** at `image.html:35,39,40,44` (emitted from
`build_pages.py:59-68`) — the mechanism by which the measure got out of the stylesheet's
control in the first place.

---

## 2. What to take from `references/stable-diffusion-webui-master/`, and what not to

### Take

1. **The toprow: prompt and Generate above the gallery.** `modules/ui_toprow.py:52-60`,
   `style.css:303-310`. This is the direct fix for D5 and the single highest-value idea in the
   reference. We take the *position*, not their markup.
2. **A multi-line prompt.** `ui_toprow.py:83` — `lines=3`. Fixes D6. **Use our chat page's
   auto-grow + Enter-to-submit / Shift+Enter-for-newline handler (`build_pages.py:185-191`),
   not SD's Ctrl+Enter.** "Like the rest of the site" is the instruction.
3. **Generation info as a structured block, not a sentence.** `ui_common.py:20-27,219`,
   `style.css:405`. Combined with their performance strip — `call_queue.py:129` emits
   `Time taken: <span class='measurement'>3.4 sec</span>`, and `style.css:272-300` renders the
   label dim and bolds only the *measurement*. That is precisely our house rule about labelling
   figures, arrived at independently. Fixes D1.
4. **Seed reuse and randomise as first-class controls.** `modules/ui.py:71-72` (`♻️`/`🎲️`).
   Cheap, and it is what makes "seed" mean anything to a visitor. **Words, not emoji** — there
   are no emoji anywhere on this site.
5. **An elapsed-time readout while you wait.** `javascript/progressbar.js:36-45`
   (`formatTime`). Fixes D8. See the labelling rule in §3.
6. **Click the render to see it full size.** `javascript/imageviewer.js`. We already have
   `.lightbox`; reuse it rather than build a second one. Fixes D9. **But see the trap in §4.**

### Reject

1. **Negative prompt** (`ui_toprow.py:86-87`). `api.py:1442` runs `--cfg-scale 1.0`. At
   guidance 1.0 a negative prompt has no effect whatsoever. Shipping a control that does
   nothing is the decorative-status-LED rule applied to a form field.
2. **Sampler / CFG / hires-fix / refiner accordions.** We pin sampler to `euler` and guidance
   to 1.0 server-side, and the page's own `.hint` explains why. Exposing the knobs would
   contradict the copy sitting next to them.
3. **The determinate progress bar and live latent preview** (`style.css:560-610`,
   `progressbar.js`). `POST /api/image` is one request with no progress channel. A bar that
   animates on a guess is a fake instrument on the page least entitled to one. Take the
   elapsed counter, which is a real reading; reject the percentage.
4. **Batch count / batch size.** One 16 GB card, one tenant, a throttled public surface
   (`throttled_for("image")`). Offering batch=8 is offering a queue we deliberately do not have.
5. **Gradio's chrome**: light-grey blocks, `0.85em #444` performance text
   (`style.css:272-275`), and `!important` (`style.css:320`). Wrong palette, and our stylesheet
   contains no `!important` anywhere — do not introduce one.
6. **The tabbed top nav** (txt2img / img2img / extras / PNG Info) and
   `#txt2img_gallery{min-height:768px}` (`style.css:314-318`). We have one endpoint; tabs to
   nothing are decoration, and reserving a fixed 768px hole is the empty-box problem.

---

## 3. Proposed structure

### 3a. Shell change (`build_pages.py`, `SHELL`) — affects all four surface pages

Replace the three inline styles on the hero with one class. This is the change that lets the
measure be controlled from the stylesheet at all.

```html
<div class="hero pghero">                          <!-- was style="padding:56px 0 26px" -->
  <div class="wrap">
    <p class="eyebrow"><img src="@@ICON@@" alt="" width="20" height="20">@@EYEBROW@@</p>
    <h1>@@HEADING@@</h1>                           <!-- was inline clamp + max-width:24ch -->
    <p class="lede">@@LEDE@@</p>                   <!-- was inline font-size:16.5px -->
  </div>
</div>
```

The `<img>` inside `.eyebrow` keeps its inline `vertical-align` for now — out of scope, and
moving it changes four pages' icon alignment for no benefit.

### 3b. Page body (`build_pages.py`, `IMAGE_BODY`)

The one structural move: **`.composer` goes above `.body`, inside `.stage`.** It keeps its
existing `border-top` (which now separates it from the head instead of from nothing), needs no
new wrapper, and puts the prompt exactly where SD's toprow is.

```html
<div class="pgwrap">
  <div class="stage">

    <!-- unchanged component; head now wraps instead of crushing (see 3d) -->
    <div class="head" id="ihead"><s></s>SyMoNeuRaL Image
      <span class="grow">idle</span></div>

    <!-- MOVED: was after .body. Reuses .composer verbatim; textarea replaces input. -->
    <form class="composer" id="form">
      <textarea id="prompt" rows="2" maxlength="1200"
        placeholder="a raven perched on a server rack, volumetric light, cinematic"></textarea>
      <button class="cta" id="send" type="submit">Generate</button>
    </form>

    <div class="body">
      <div class="shots" id="shots">

        <!-- empty state: a real panel, not a caption with four inline overrides -->
        <p class="ig-empty">
          Describe something and press Generate. FLUX.1-schnell, four steps, rendered on the
          card in this machine.
        </p>

      </div>
    </div>
  </div>

  <aside class="panel">
    <h3>Parameters</h3>

    <div class="ctl">
      <label for="steps">Steps <b id="stepsv">4</b></label>
      <input type="range" id="steps" min="4" max="8" step="1" value="4">
    </div>

    <div class="ctl">
      <label>Size</label>
      <div class="seg" id="size">
        <button type="button" data-v="512">512</button>
        <button type="button" data-v="768" aria-pressed="true">768</button>
      </div>
    </div>

    <div class="ctl">
      <label for="seed">Seed <b id="seedlock">random</b></label>
      <input type="number" id="seed" min="0" max="2147483647"
             placeholder="leave blank for random">
      <!-- reference idea 4, in our own segmented control -->
      <div class="seg" id="seedmode">
        <button type="button" data-seed="random" aria-pressed="true">Randomise</button>
        <button type="button" data-seed="reuse" disabled>Reuse last</button>
      </div>
    </div>

    <p class="hint">schnell is a distilled model: four steps is what it was trained for, and
      guidance is pinned to 1.0 because raising it degrades this model rather than sharpening
      it. More steps costs time without buying much.</p>
    <p class="hint" id="stat">&nbsp;</p>
  </aside>
</div>
```

### 3c. A result tile (built in `IMAGE_JS`)

Three lines in descending order of who needs them — the same discipline as `.mod`
(`symoneural.css:1002-1019`: `.val` / `.plain` / `.sub`).

*While rendering:*

```html
<div class="shot">
  <div class="ig-frame">rendering<span class="ig-elapsed">0.0s</span></div>
  <p class="ig-q">a raven perched on a server rack…</p>
</div>
```

*When done:*

```html
<div class="shot">
  <!-- data-lightbox is the hook ui.js matches on (see §3f); href is the real PNG, so the
       click still works with JS off. data-strip is deliberately ABSENT — see §3f. -->
  <a class="ig-frame" data-lightbox href="/api/gen/gen-…png"
     data-prompt="a raven perched on a server rack…" data-secs="12.9">
    <img src="/api/gen/gen-…png" alt="a raven perched on a server rack…" loading="lazy">
  </a>
  <p class="ig-q">a raven perched on a server rack…</p>
  <p class="ig-prov">768×768 · 4 steps · seed 1873220145 ·
     <b>12.9 s on the card</b> · FLUX.1-schnell q4_k · 812 KB</p>
</div>
```

*On failure:*

```html
<div class="shot">
  <p class="ig-err"><b>Render failed</b>That prompt is outside what this public surface
    will render.</p>
</div>
```

Order is deliberate and diverges from the front page (`.gwrap` → `.gprov` → `.gq`): there the
image is the argument and the quote is the flourish, so provenance comes first. Here the
visitor wrote the prompt, so it is the **label**, and the provenance is the **receipt** — and a
receipt goes last. `.ig-prov` bolds only the measurement, per `call_queue.py:129`.

### 3d. CSS

New rules, all of them either namespaced or compound selectors over existing names.

```css
/* ---- surface-page hero: the measure, back under the stylesheet's control ---- */
.pghero{padding:56px 0 26px}
.pghero h1{font-size:clamp(28px,3.6vw,40px); max-width:24ch}
/* 0,0,2,0 beats the bare `.lede` at line 723 regardless of source order. That rule stays
   as it is: it also reaches account, build and documentation, which are not in scope. */
.pghero .lede{font-size:16.5px; max-width:66ch}
/* .callout has no max-width and runs to ~140ch. Scoped to the surface shell by the
   sibling combinator, because documentation.html uses .callout four times and is not
   in scope. If SHELL is ever reordered, replace this with a modifier class. */
.pghero + section .callout p{max-width:78ch}

/* ---- the status strip stops crushing itself (D3) ---- */
.stage .head{flex-wrap:wrap; row-gap:5px}
.stage .head .grow{line-height:1.45}      /* was 1, inherited from `font:650 11px/1` */

/* ---- composer is no longer last in the stage (D5) ---- */
.stage .composer:not(:last-child){border-bottom:1px solid var(--line)}
/* chat/calc/remix keep the composer last, so :not(:last-child) leaves them untouched */

/* ---- second control in a .ctl, and a disabled segment ---- */
.ctl input + .seg{margin-top:9px}
.seg button[disabled]{opacity:.45; cursor:not-allowed}

/* ---- results ---- */
/* 210px gave 222px tiles for a 768px render — a 3.5x downscale. */
.shots{grid-template-columns:repeat(auto-fill,minmax(280px,1fr))}
/* the newest render, large; the history as thumbnails. Guarded so it cannot span a
   grid that only has one column. */
@media (min-width:700px){ .shots > .shot:first-child{grid-column:span 2} }

.shot{padding-bottom:2px}                  /* .ig-q / .ig-prov sit inside the border */
.ig-frame{
  display:grid; place-items:center; aspect-ratio:1/1; background:var(--panel2);
  color:var(--faint); font:13px/1.5 ui-sans-serif,system-ui,sans-serif;
  text-decoration:none; cursor:zoom-in;
}
.ig-frame img{width:100%; height:100%; object-fit:cover; display:block}
a.ig-frame:focus-visible{outline:2px solid var(--accent); outline-offset:-2px}
.ig-elapsed{
  display:block; margin-top:6px; color:var(--dim);
  font:600 15px/1 ui-monospace,Menlo,Consolas,monospace; font-variant-numeric:tabular-nums;
}
/* the prompt: what was asked. Serif and one shade up, matching .gq on the front page. */
.ig-q{
  margin:0; padding:12px 14px 0; color:#a3b8ab;
  font:400 14.5px/1.45 ui-serif,Georgia,"Times New Roman",serif; letter-spacing:-.01em;
  overflow-wrap:anywhere;              /* no ellipsis, ever — it wraps */
}
/* the receipt: mono, dimmer, smaller, and only the measurement is lit */
.ig-prov{
  margin:0; padding:9px 14px 12px; color:var(--faint);
  font:11.5px/1.5 ui-monospace,"SF Mono",Menlo,Consolas,monospace;
  font-variant-numeric:tabular-nums; overflow-wrap:anywhere;
}
.ig-prov b{color:var(--accent); font-weight:600}
/* the empty state: a panel, at body size, in a colour you can read */
.ig-empty{
  grid-column:1/-1; margin:0; padding:38px 26px; text-align:center;
  border:1px dashed var(--line); border-radius:12px; background:var(--bg);
  color:var(--dim); font-size:14.5px; line-height:1.62; max-width:56ch;
  margin-inline:auto;
}
.ig-err{
  margin:0; padding:16px 16px 18px; color:var(--dim); font-size:13.5px; line-height:1.55;
  overflow-wrap:anywhere;
}
.ig-err b{display:block; margin-bottom:5px; color:var(--amber); font-weight:650;
  font-size:11px; letter-spacing:.13em; text-transform:uppercase}

/* ---- .hint carries the page's actual argument; stop hiding it (D7) ---- */
.hint{font-size:13px; color:var(--dim); line-height:1.6}
```

`.shot .cap` (`symoneural.css:278-279`) becomes dead — `class="cap"` is used nowhere but
`image.html` (verified). **Delete it in the same commit**; leaving a dead rule named `.cap` in
a stylesheet with this collision history is how the next one starts.

### 3e. JS (`IMAGE_JS`)

- Prompt: copy the auto-grow + Enter/Shift+Enter handler from `CHAT_JS`
  (`build_pages.py:185-191`) verbatim.
- **Use `t0`.** Start a 100ms interval on submit, write `((performance.now()-t0)/1000).toFixed(1)+'s'`
  into `.ig-elapsed`, clear it in `finally`.
- **Label the two numbers so they cannot be read as contradicting each other.** They will
  differ: `api.py:1424` states `seconds` is the render alone, excluding the GPU lock wait and
  the chat eviction, so the stopwatch always reads higher. Therefore:
  - `.ig-elapsed` is prefixed **`waiting + rendering`** (it starts while the page is queued).
  - `.ig-prov` says **`12.9 s on the card`** — the server's measured render time.
  - Add one sentence to the `.hint` block: *"The counter runs from the moment you press
    Generate, so it includes the wait for the card; the seconds under the render are the
    render alone, measured server-side."* Two unlabelled numbers that disagree is worse than
    one number.
- `Reuse last`: stores `r.seed` from the previous response, writes it into `#seed`, flips
  `#seedlock` to `locked`, and enables itself only once a render has succeeded.
- Include `r.bytes` in `.ig-prov` as `${Math.round(r.bytes/1024)} KB` — it is a measured fact
  already on the wire and thrown away today. (Drop it if it reads as clutter; see §5.)

### 3f. `site/ui.js` — two changes, both required

`ui.js:61` builds a static NodeList at load and bails early:

```js
var links = [].slice.call(document.querySelectorAll('a.art, a.gart'));
if (!links.length) return;
```

On image.html there are zero such links at load, so it returns immediately and no result would
ever open. **Replace the static list + per-link listeners (`ui.js:117-124`) with one delegated
listener on `document`**, and drop the early return. Match on
`e.target.closest('a.art, a.gart, a[data-lightbox]')` — the two existing classes keep the
front page and `/build.html` working, and `data-lightbox` is what new markup uses.
`.art` was considered as the hook for the new tiles and rejected: it is currently only ever
matched as `.sky .art` (`symoneural.css:1091-1146`), so a bare `.art` rule added later would
silently reach this page — the `.bar` / `.live` / `#console .sub` failure mode exactly. An
attribute hook cannot be styled by accident.

**And the trap — this half is not optional.** `ui.js:96-103` hardcodes

> "The strip along the bottom is printed into the file, not added by this page."

That is **false for API renders**. The watermark strip is drawn by `tools/build_gallery.py`
(`ImageDraw`, lines 115-126) for the front-page art only; `api.py`'s sd-cli invocation writes
no strip. Reusing the lightbox unchanged would print a false provenance claim on the one page
whose entire job is honest provenance.

**Required:** gate the sentence behind `data-strip` — `ui.js` emits it only when the clicked
link carries that attribute, and image.html's result links never carry it. With a bare
`data-secs` it prints only the seconds claim. Ship this in the same commit as the delegation
fix; the false sentence must not survive the change.

**Optional, separately:** add `data-strip` to the `.gart`/`.art` links emitted by
`build_gallery.py` / `build_sky.py`, so the front-page lightbox keeps the sentence it has
today. Without it the front page simply loses one true sentence — no false claim either way,
which is why this half can wait.

---

## 4. CSS namespace check

Every new name, grepped against `site/symoneural.css`, `site/rack-detail.css`,
`site/swagger-dark.css`, all `site/*.js` and all `site/*.html`.

| Proposed name | Selector hits in any CSS | `class="…"` hits in any HTML/JS | Verdict |
|---|---|---|---|
| `.pghero` | 0 | 0 | free — sits in the existing `pg` namespace (`.pgwrap`) |
| `.ig-frame` | 0 | 0 | free |
| `.ig-q` | 0 | 0 | free |
| `.ig-prov` | 0 | 0 | free |
| `.ig-empty` | 0 | 0 | free |
| `.ig-err` | 0 | 0 | free |
| `.ig-elapsed` | 0 | 0 | free |

`grep -rn 'ig-' site/*.html` returns 3 hits, all substrings inside `id=` slugs in
`training.html` (`…-big-one`, `…-big-models`). No `class` attribute anywhere uses an `ig-`
prefix, and `grep -nE '\.ig-' site/*.css` is empty. The `ig-` prefix is unclaimed.

**Names deliberately reused rather than reinvented:** `.stage`, `.head`, `.grow`, `.body`,
`.composer`, `.cta`, `.panel`, `.ctl`, `.seg`, `.hint`, `.shots`, `.shot`, `.callout`,
`.pgwrap` and `.badge`.

**No class is used as the lightbox hook.** `.art` was the obvious candidate and is rejected in
§3f — the tiles carry the attribute `data-lightbox` instead, which cannot be styled by a
later rule the way `.bar`, `.live` and `#console .sub` each were.

**Things not touched, and why:** the bare `.lede` rule at `symoneural.css:723` (reaches
`account`, `build`, `documentation`); `.callout p` globally (`documentation.html` uses
`.callout` 4×); `.shot img`'s `object-fit:cover` (both offered sizes are square, so it never
crops).

**No `text-overflow:ellipsis` is introduced anywhere.** `.ig-q`, `.ig-prov` and `.ig-err` all
set `overflow-wrap:anywhere` and wrap. The model attribution moves out of the tail of a 12px
faint run into its own line, which strengthens rather than weakens the Apache-2.0 condition.

---

## 5. Open questions — decide before implementing, do not guess

1. **`.hint` at 13px/`--dim` changes four pages** (`class="hint"` appears only on chat, image,
   ravencalc, remix — verified). I think that is right and consistent. Confirm before shipping,
   since three of those pages were not complained about.
2. **File size in `.ig-prov`.** `r.bytes` is measured and free, but "812 KB" may be noise a
   visitor does not want. Ship it or cut it — I have no evidence either way.
3. **The 512 option.** The page offers 512 and 768 but makes no claim about what 512 buys you.
   If there is a measured 512-vs-768 render time on this card it belongs in the `.hint`; if
   there is not, say nothing — do not estimate it.
4. **Newest-render-spans-2-columns** (`.shots > .shot:first-child`) is an opinion, not a fix.
   Drop it if it reads as lopsided with exactly two results.
5. **`data-strip` on the front-page renders** (the optional half of §3f). Adding it to
   `build_gallery.py` / `build_sky.py` output preserves a true sentence in the front-page
   lightbox; skipping it loses that sentence and nothing else. The blocking half — gating the
   sentence so image.html never prints it — is specified in §3f and is not optional.

---

## 6. Order of work, and verification

1. Edit `tools/build_pages.py` (`SHELL`, `IMAGE_BODY`, `IMAGE_JS`), `site/symoneural.css`,
   `site/ui.js`.
2. `python3 tools/build_pages.py` — **then `python3 tools/build_cachebust.py`**, which stamps
   `?v=<hash>` onto the changed `symoneural.css` and `ui.js`. `build_pages.py` emits bare
   paths; without the second step a warm browser gets new markup against a week-old
   stylesheet, which is the exact failure that generator was written for. Run both **twice and
   `diff`** — the idempotence rule.
3. `node tests/frontend.mjs`. **This must be the implementer's first verification step, and I
   could not run it: the image assertions generate a real render on the GPU.** Two things to
   watch: `tests/frontend.mjs:230` selects `input[type=text], textarea` and takes the **first
   in DOM order** — swapping the prompt to a `<textarea>` is fine, but the header must not gain
   a text input before it, or the test fills the wrong box; and the composer moving above
   `.body` does not change any selector the test uses.
4. Add an assertion for the bug that was fixed, per the working agreements: at 390px, assert
   `.stage .head` height stays under ~62px with the busy status set, and that `.ig-prov` and
   `.ig-q` are two separate non-empty elements with different computed `font-family`.
5. Read computed styles at 390 / 900 / 1280 rather than reasoning about the cascade —
   `.pghero .lede`, `.pghero + section .callout p`, `.stage .head .grow`, `.ig-q`, `.ig-prov`,
   and that `.ig-empty` stays centred (`max-width` + `margin-inline:auto` on a
   `grid-column:1/-1` item does centre, but measure it rather than trust that).
6. `sudo ./scripts/deploy.sh` — read its output, do not trust its exit code
   (`missing=1` is set in a subshell).
