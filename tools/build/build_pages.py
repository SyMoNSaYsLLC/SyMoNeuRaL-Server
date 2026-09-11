#!/usr/bin/env python3
"""Generate the surface pages into site/.

Four pages that differ only in their middle. Generating them from one shell means the
header, banner, nav and footer cannot drift apart, which is the failure mode when five
static pages are maintained by hand and someone edits four of them.

The pages are plain HTML with a little inline JS and no build step, no framework and no
external request -- everything a visitor loads comes off this box.
"""
from __future__ import annotations

import pathlib
import re
import sys

# The generators live in tools/, so the repo root is one level up. This exact
# calculation has been wrong twice in this repo's history -- once when demo/ was
# flattened and once here -- and it fails *silently*, because the wrong parent is
# usually a directory that exists. Assert rather than trust it.
ROOT = next(_p for _p in pathlib.Path(__file__).resolve().parents if (_p / "backend" / "server.py").is_file())
assert (ROOT / "backend" / "server.py").is_file(), f"repo root not found at {ROOT}"
SITE = ROOT / "frontend" / "site"

# The authored page-family map. Imported rather than restated: see tools/lib/page_families.py for
# why the families live in one file instead of in every generator, the markup and the tests.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import page_families  # noqa: E402

NAV = """    <nav>
      <a class="navlink" href="/livestack">Live stack</a>
      <a class="navlink" href="/documentation.html">Documentation</a>
      <a class="navlink" href="/training.html">Manuals</a>
      <a class="navlink" href="/docs">API</a>
      <a class="navlink" href="/account.html">Account</a>
      <a class="navlink" href="mailto:symonsayadmin@symoneural.com">Contact</a>
      <a class="cta" href="/build.html">Have one built</a>
    </nav>"""

SHELL = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>@@TITLE@@</title>
<meta name="description" content="@@DESC@@">
<link rel="stylesheet" href="/symoneural.css">
<link rel="stylesheet" href="/rack-detail.css">
<link rel="icon" href="/favicon-32.png" sizes="32x32" type="image/png">
<link rel="icon" href="/favicon-16.png" sizes="16x16" type="image/png">
<link rel="apple-touch-icon" href="/apple-touch-icon.png">
<meta name="theme-color" content="#0e100f">
</head>
<body>

<header>
  <div class="wrap bar">
    <a class="logo" href="/">
      <img src="/mark-64.png" srcset="/mark-32.png 1x, /mark-64.png 2x" alt="SyMoNeuRaL" width="30" height="30">
      <b>SyMoNeu<i>RaL</i></b>
    </a>
    <!-- Outside the `.logo` anchor on purpose: it is a statement of who owns the company, not
         a second thing to click, and inside the link it would join the accessible name. -->
    <span class="llc">a <b>SymonSays LLC</b> company</span>
@@NAV@@
  </div>
</header>

<div class="hero" style="padding:56px 0 26px">
  <div class="wrap">
    <p class="eyebrow"><img src="@@ICON@@" alt="" width="20" height="20"
       style="display:inline-block;vertical-align:-4px;margin-right:8px">@@EYEBROW@@</p>
    <h1 style="font-size:clamp(28px,3.6vw,40px);max-width:24ch">@@HEADING@@</h1>
    <p class="lede" style="font-size:16.5px">@@LEDE@@</p>
  </div>
</div>

<section style="border-top:0;padding-top:0">
  <div class="wrap">
@@BODY@@

    <div class="callout" style="margin-top:34px">
      <!-- h2, not h3. `appify` relocates this block out of the page body and into a
           top-level <details class="appinfo"> below the footer, where it is a section
           of the page in its own right and has no h2 parent to sit under. As an h3 it
           was the entire outline defect on /project.html, whose only other visible
           heading is the page h1. -->
      <h2>This is a 16 GB consumer card, and it is a test bench</h2>
      <p>
        Chat and image never run at the same time here. A lock hands the GPU to exactly one
        surface and the other waits, because both weight sets do not fit in 15.92&nbsp;GiB at
        once &mdash; and when they swap, we wait for the driver to actually hand the memory
        back before the next one starts. If you are queued behind someone, that is not a bug;
        it is one card doing one thing at a time.
      </p>
      <p>
        <strong>RavenCalc is the exception</strong> &mdash; it is symbolic algebra on the CPU, so it never
        touches the GPU and never queues. Everything here is a demonstration of the stack on
        the smallest machine we would ever ship, not a statement of capacity. A server we spec
        for you would not be sharing one GPU with itself.
      </p>
    </div>
  </div>
</section>

<footer>
  <div class="wrap foot">
    <a class="logo" href="/" style="text-decoration:none;display:flex;align-items:center;gap:10px">
      <img src="/mark-32.png" alt="" width="22" height="22">
      <b style="font-size:14.5px;color:var(--fg)">SyMoNeu<i style="font-style:normal;color:var(--accent)">RaL</i></b>
    </a>
    <span>&copy; SymonSays LLC &middot; <a href="mailto:symonsayadmin@symoneural.com"
      style="color:var(--dim);text-decoration:none">symonsayadmin@symoneural.com</a></span>
    <nav>
      <a href="/">Home</a>
      <a href="/training.html">Training</a>
      <a href="/documentation.html#hardware">Hardware</a>
      <a href="/documentation.html#inference">Inference</a>
      <a href="/credits.html">Credits</a>
    </nav>
  </div>
</footer>

<script src="/app.js"></script>
<script src="/console.js" defer></script>
<script src="/ui.js" defer></script>
<script src="/shell.js" defer></script>
<script src="/fit.js" defer></script>
@@SCRIPT@@
</body>
</html>
"""


# ------------------------------------------------------------- the application shell
# Every page `page()` writes is wrapped in SHELL, and SHELL is a MARKETING page: a 56px-padded
# hero with a 40px display headline above the content, and the "16 GB consumer card / test
# bench" callout below it. That is right for build.html and credits.html and wrong for the
# fourteen surfaces that are workspaces -- on chat.html it puts two paragraphs of hardware
# prose underneath the composer, inside the thing somebody is trying to use.
#
# This is a POST-PROCESS ON THE RENDERED HTML, deliberately, and not a new `@@...@@` in SHELL.
# `page()` already carries the note explaining why, from the day `@@PAGECSS@@` was tried:
# build_exp, build_project, build_reinforce, build_sigils and build_studio all import this
# SHELL and substitute their own field dicts, which know nothing of a new placeholder, and
# their own `assert "@@" not in html_out` guards went red on correct pages. A placeholder in a
# shared shell is a contract with every consumer. A function they can call is a contract with
# whoever calls it, so those five opt in by calling this rather than by being broken by it.
#
# WHAT IT DOES NOT DO: it does not touch a single word of copy. The heading and lede strings
# are moved and resized, never rewritten. Task #80 owns two of them -- `Make it draw
# something.` and `talk to the box` -- and carries `ngrep` checks against both this file and
# frontend/site/pages/image.html, which go green when the string is ABSENT. Rewriting a heading here would
# hand #80 two free percentage points for work nobody did.

_HERO = re.compile(
    r'<div class="hero" style="padding:56px 0 26px">\s*'
    r'<div class="wrap">\s*(.*?)\s*</div>\s*</div>', re.S)
_CALLOUT = re.compile(r'\n\s*<div class="callout" style="margin-top:34px">.*?</div>\n', re.S)


def appify(html: str) -> str:
    """Turn a marketing page into an application page. Same words, different furniture.

    Two structural edits, each asserted so a change to SHELL fails loudly here instead of
    silently emitting a page that still has the hero on it.
    """
    hero = _HERO.search(html)
    assert hero, "SHELL's hero block moved; the application shell cannot find it"
    # The eyebrow, heading and lede survive verbatim -- `.apphead` simply sizes and spaces
    # them as page furniture instead of as a landing page, and the lede is capped at a
    # reading measure rather than running the width of a 1920px workspace.
    html = html.replace(hero.group(0),
                        '<div class="apphead">\n  <div class="wrap">\n    '
                        + hero.group(1) + '\n  </div>\n</div>')

    callout = _CALLOUT.search(html)
    assert callout, "SHELL's test-bench callout moved; it would be left inside the workspace"
    body = callout.group(0).strip()
    html = html.replace(callout.group(0), "\n")
    # RELOCATED, NOT DELETED. It is a true and useful statement about this machine -- one card,
    # one surface at a time, and RavenCalc the exception -- and the honesty rules in
    # ENGINEERING.md are the reason it exists at all. It now sits below the footer as a
    # closed disclosure, so it is one click from every workspace instead of two paragraphs
    # inside one.
    panel = ('<details class="appinfo">\n'
             '  <summary>System information &mdash; one card, one surface at a time</summary>\n'
             '  <div class="wrap">\n    ' + body + '\n  </div>\n</details>\n')
    assert "</footer>" in html, "the footer moved; the system-information panel has no anchor"
    return html.replace("</footer>", "</footer>\n\n" + panel, 1)


_HEADING = re.compile(r"<(h[1-6])(\b[^>]*)>(.*?)</\1>", re.S | re.I)


def _outline(html: str, filename: str) -> str:
    """Renumber content headings so the document outline has no level jump.

    Measured across the 23 shell pages: ten started their content at `h3` directly under the
    page `h1`, so the outline read 1 -> 3 with nothing at level 2. The headings themselves are
    correct and correctly placed; only their LEVEL is wrong, which is why this renumbers rather
    than adds, removes or hides anything. No heading text is touched, none is invented, and
    none is deleted -- the brief rules all three out and they would each be a way of making the
    check pass without making the page better.

    Two passes, because the ten pages fail for two different reasons.

    **Pass A -- depth.** A page whose shallowest content heading is `h3` has simply been
    written one level too deep; every heading shifts up by the same amount, so relative
    nesting is preserved exactly. `studio` goes 3,3,4,4,...,3 -> 2,2,3,3,...,2 and keeps its
    shape.

    **Pass B -- order.** A page can have genuine `h2` sections AND panel labels marked `h3`
    that appear before the first of them, which is `sigils`: `Field colour` and `Parameters`
    are workbench controls at the top level of the page, sitting above four real `h2`
    sections. Pass A cannot see this because the shallowest level is already 2. So any
    heading deeper than `h2` that appears before the first `h2` is promoted to `h2` -- it has
    no parent to be nested under, which is the definition of the defect.

    `h1` is never touched: `landmark` and the generators guarantee exactly one, and it is the
    page title.
    """
    heads = list(_HEADING.finditer(html))
    content = [m for m in heads if m.group(1).lower() != "h1"]
    if not content:
        return html

    levels = {int(m.group(1)[1]) for m in content}
    shift = max(0, min(levels) - 2)

    seen_h2 = False
    out, last = [], 0
    for m in content:
        lvl = int(m.group(1)[1]) - shift          # pass A
        if lvl > 2 and not seen_h2:               # pass B
            lvl = 2
        if lvl == 2:
            seen_h2 = True
        lvl = max(2, min(6, lvl))
        tag = f"h{lvl}"
        out.append(html[last:m.start()])
        out.append(f"<{tag}{m.group(2)}>{m.group(3)}</{tag}>")
        last = m.end()
    out.append(html[last:])
    return "".join(out)


def landmark(html: str, filename: str) -> str:
    """Give a rendered page its `<main>` landmark and its static `data-family`.

    A SECOND POST-PROCESS BESIDE `appify()`, and for exactly the reason `appify()`'s own
    comment gives at length: build_exp, build_project, build_reinforce, build_sigils and
    build_studio import `SHELL` and substitute their own field dicts, which know nothing of a
    new `@@...@@`, and their `assert "@@" not in html_out` guards go red on correct pages. A
    placeholder in a shared shell is a contract with every consumer; a function they call is a
    contract with whoever calls it. So those five opt in by calling this, exactly as they opt
    in to `appify()`.

    ## `<main>`

    Measured across all 23 shell pages: **zero** carried a `<main>` element. The shared shell
    supplies no landmark, so every page needed one, not the single page an earlier count
    reported. `frontend/site/pages/training.html` already had one and is the precedent for the shape.

    The wrapper opens after `</header>` and closes before `<footer>`, which is the same
    boundary on every page this shell produces. Verified safe before writing: `site/*.css`
    contains no `body > ...` child selector, no `header + ...` or `... + footer` sibling rule,
    and no JavaScript walks `document.body.children`. The `section + section` rules at
    symoneural.css:913 and :919 operate BETWEEN sections, and sections stay siblings of one
    another inside the wrapper, so those keep matching.

    ## `data-family`

    Emitted into `<html>` so the width a workspace gets does not wait for JavaScript. Before
    this, 14 pages rendered 224px narrower with scripting off -- 1120px instead of 1344px at
    a 1440px viewport. The value comes from `page_families.FAMILIES`; a page with no family
    keeps the prose width and gets no attribute at all.
    """
    fam = page_families.attribute(filename)
    if fam:
        assert '<html lang="en">' in html, (
            f"{filename}: the opening <html> tag moved; data-family has nowhere to go")
        html = html.replace('<html lang="en">', f'<html lang="en"{fam}>', 1)

    assert "</header>" in html and "<footer>" in html, (
        f"{filename}: the header/footer boundary moved; <main> has nothing to wrap")
    assert "<main" not in html, f"{filename}: already has a <main>; refusing to add a second"
    html = html.replace("</header>", "</header>\n\n<main>", 1)
    html = html.replace("<footer>", "</main>\n\n<footer>", 1)
    # The third semantic repair, done here so the five generators that already opt into this
    # function get it without a further call site. See `_outline` for what it renumbers.
    return _outline(html, filename)


# ---------------------------------------------------------------- the GPU panel
# Reuses `frontend/site/js/console.js` outright rather than adding a second data path. That file
# connects when it finds `#units` OR `#m-vram` on the page (console.js:266) and then writes
# m-vram / m-pwr / m-temp / m-holder / m-queue / con-link. So carrying those ids is the whole
# integration: same WebSocket, same readings, same fallback to polling. Its txt()/meter()
# helpers no-op on ids that are absent, so the ids the rack uses and this does not are safe.
#
# Every number here is read from nvidia-smi through /api/status. `holder` is which surface
# owns the card right now, which is the one that explains a wait -- if it names something
# other than this page, you are queued behind it, and that is why the button is slow.
def gpu_panel(uses_gpu: bool, surface: str, why: str = "") -> str:
    # `why` overrides the sentence under the panel. It exists for the miner, which is the
    # one surface here that does NOT hold the card for the length of a prompt: it holds it
    # for its whole process lifetime, so the default wording ("while a prompt runs") would
    # understate what starting it does to every other surface. Every other page passes
    # nothing and gets the sentence it always got.
    if why:
        pass
    elif uses_gpu:
        why = (f"While a prompt runs, <b>{surface}</b> holds the card and every other GPU "
               "surface waits. If <i>holding</i> names something else, you are queued behind "
               "it &mdash; that is the honest reason a request is slow.")
    else:
        why = (f"<b>{surface} does not use the GPU.</b> This is the card the rest of the "
               "stack shares, shown here so you can see what it is doing; nothing on this "
               "page waits for it.")
    return f'''<div class="gpu-panel">
          <p class="gpu-head"><s></s>RTX 5070 Ti<span class="gpu-link" id="con-link">socket: connecting</span></p>
          <div class="gpu-row">
            <label>VRAM free <b id="m-vram">&mdash;</b></label>
            <div class="gbar" id="m-vrambar"><i style="width:0%"></i></div>
          </div>
          <div class="gpu-row">
            <label>Power <b id="m-pwr">&mdash;</b></label>
            <div class="gbar" id="m-pwrbar"><i style="width:0%"></i></div>
          </div>
          <dl class="gpu-facts">
            <dt>Temperature</dt><dd id="m-temp">&mdash;</dd>
            <dt>Holding</dt><dd id="m-holder">&mdash;</dd>
            <dt>Queued</dt><dd id="m-queue">&mdash;</dd>
          </dl>
          <!-- The whole stack, not just the holder. console.js already renders the rack
               into #units, so carrying that id here shows every surface and which one is
               actually busy -- "something else is running" answered by looking, rather
               than inferred from one field. Styled compact for a sidebar. -->
          <div class="units gpu-stack" id="units"></div>
          <p class="gpu-why">{why}</p>
        </div>
        '''


def page(name: str, gpu: bool | None = None, surface: str = "", why: str = "",
         css: str = "", js: str = "", app: bool = False, **kw) -> None:
    """Render one surface page.

    `gpu` places the live GPU panel at the top of the page's aside -- beside the prompt,
    which is where it answers the question it exists for ("why is this slow"). Pass False
    for a surface that does not use the card: the panel still appears, because the card is
    shared and its state is worth seeing, but it says plainly that this page does not wait
    for it. Omit entirely for a page with no prompt.

    `css` and `js` are the page's OWN stylesheet and behaviour. They are written out as
    `site/<stem>.css` and `site/<stem>.js` and referenced from the shell, rather than
    inlined into the markup -- #81: *"the image html should be static with [js] and css"*,
    scoped by him one minute later to *"apply this to all applications."*

    Three things about that split are load-bearing and none of them is style:

      * **The files are WRITTEN BY THIS GENERATOR, beside the markup they belong to.**
        `frontend/site/pages/image.html` is generated. A hand-edited `frontend/site/js/image.js` sitting next to a
        generated page is a second source of truth for one surface, and the next
        `python3 tools/build/build_pages.py` would revert half of it and leave the other half --
        which is the drift `.claude/CLAUDE.md` bans second state documents to prevent.
      * **`defer`, and the shared helpers above stay inline.** `$`, `status()` and `api()`
        are declared in the shell's own inline block, which runs at parse time; a deferred
        external script runs after the document is parsed, so it sees all three. That
        ordering is the same one `console.js` and `ui.js` have always relied on. An
        external file that ran BEFORE them would find `$` undefined and fail on its first
        line, silently, with a rendered page.
      * **`tools/build/build_cachebust.py` has to run afterwards.** It stamps `?v=<hash>` onto
        these references the same way it stamps `/symoneural.css`. The CALC_BODY comment
        below argues for inline CSS on the grounds that *"an inline block cannot be served
        stale against new markup"* -- true, and the stamper is the other answer to it. What
        is NOT an answer is an unstamped external file, which is exactly the week-old-CSS
        failure that comment is about. Regenerate, stamp, then read `git status`.
    """
    if gpu is not None:
        body = kw.get("body", "")
        i = body.find("<aside")
        if i >= 0:
            j = body.find(">", i)
            kw["body"] = (body[:j + 1] + "\n        "
                          + gpu_panel(gpu, surface or name, why) + body[j + 1:])
    stem = name[:-len(".html")] if name.endswith(".html") else name

    # The page's own stylesheet link is INSERTED after the shared sheets rather than living
    # as a SHELL placeholder. It was `@@PAGECSS@@` in the shell for one day, and the 0.5
    # re-measure caught why that cannot work: `tools/build/build_exp.py` and Studio's builder
    # import this SHELL and substitute their own field dicts, which know nothing of a new
    # placeholder -- their own `assert "@@" not in html_out` vacuity guards went red on
    # correct pages. A placeholder in a shared shell is a contract with every consumer;
    # an insertion here is a contract with nobody.
    if css:
        (SITE / f"{stem}.css").write_text(css)
        print(f"  {stem}.css")
    if js:
        (SITE / f"{stem}.js").write_text(js)
        kw["script"] = f'<script src="/{stem}.js" defer></script>'
        print(f"  {stem}.js")

    html = SHELL.replace("@@NAV@@", NAV)
    for key, value in kw.items():
        html = html.replace(f"@@{key.upper()}@@", value)
    if css:
        shared = '<link rel="stylesheet" href="/rack-detail.css">'
        assert shared in html, "the shared stylesheet line moved; the css insertion is lost"
        html = html.replace(
            shared, f'{shared}\n<link rel="stylesheet" href="/{stem}.css">', 1)
    if app:
        html = appify(html)
    # Unconditional, unlike `appify`: a landmark and a family are not application furniture.
    # `landmark` decides from `page_families` whether this page gets a `data-family` at all,
    # so a prose page passes through with only the <main> wrapper added.
    html = landmark(html, name)
    (SITE / name).write_text(html)
    print(f"  {name}")


# ---------------------------------------------------------------- chat
CHAT_BODY = """    <div class="cu">

      <!-- Left rail. A <div role=navigation>, NOT a <nav>: the sitewide rule
           `nav a:not(.cta){display:none}` hides nav links below 820px, which would delete
           every link in here on a phone. -->
      <div class="cu-rail" id="cu-rail" role="navigation" aria-label="Conversations">
        <div class="cu-railtop">
          <button type="button" class="cu-new" id="cu-new">+ New chat</button>
          <button type="button" class="cu-collapse" id="cu-collapse"
                  aria-label="Hide conversations">&#8942;</button>
        </div>
        <p class="cu-railhead">Conversations</p>
        <ul class="cu-hist" id="cu-hist"></ul>
        <p class="cu-railfoot">Kept in this browser only.<br>Nothing is stored on the box.</p>
      </div>

      <div class="cu-main">
        <!-- Empty state: centred, and it goes away once there is a transcript. -->
        <div class="cu-empty" id="cu-empty">
          <h2 class="cu-greet">Ask SyMon.</h2>
          <p class="cu-sub">A 7B at Q4 on the RTX 5070 Ti in this room. Nothing you type
            leaves the machine.</p>
        </div>

        <div class="cu-log" id="log"></div>

        <form class="cu-composer" id="form">
          <textarea id="prompt" rows="1" maxlength="100000"
                    placeholder="How can I help?"></textarea>
          <div class="cu-tools">
            <label class="cu-attach" title="Attach a text file">
              <input type="file" id="cu-file" accept=".txt,.md,.csv,.json,.log,.py,.js,.html,.css,.yaml,.yml,.toml,.ini,.sh">
              <span>&#43;</span>
            </label>
            <span class="cu-file-name" id="cu-filename"></span>
            <span class="cu-spacer"></span>
            <span class="cu-model" id="cu-model">&nbsp;</span>
            <button class="cu-send" id="send" type="submit" aria-label="Send">&#8593;</button>
          </div>
        </form>
        <p class="cu-hint" id="stat">&nbsp;</p>
      </div>
    </div>
"""


# The visualizer is loaded only on this page, not from SHELL, because it is the only surface
# with a token stream to visualise -- on image.html or ravencalc.html it would have nothing
# honest to show and would be pure decoration.
#
# `defer` so it never blocks the chat script below, and the chat script never checks whether
# it loaded: frontend/site/js/visualizer.js installs a no-op `window.SymonVisualizer` before it does
# anything that can fail, so every call below is safe on a machine with no WebGL.
CHAT_JS = """<script src="/visualizer.js" defer></script>
<script>
(function () {
  'use strict';
  var log = document.getElementById('log'), form = document.getElementById('form');
  var box = document.getElementById('prompt'), send = document.getElementById('send');
  var empty = document.getElementById('cu-empty'), stat = document.getElementById('stat');
  var histEl = document.getElementById('cu-hist'), fileEl = document.getElementById('cu-file');
  var fileName = document.getElementById('cu-filename');
  var K = 'symoneural.chat.v1';
  var chats = [], cur = null, attached = null, busy = false;

  // ---------------------------------------------------------------- storage
  // Conversations live in THIS BROWSER and nowhere else. There is no history endpoint and
  // no conversation id on the server, which is not a gap -- it is the same promise the rest
  // of the site makes about your data. The transcript is replayed to /api/chat on each turn
  // so the model can follow along, and the server keeps none of it.
  function load() {
    try { chats = JSON.parse(localStorage.getItem(K) || '[]'); }
    catch (e) { chats = []; }
    if (!Array.isArray(chats)) chats = [];
  }
  function save() {
    try { localStorage.setItem(K, JSON.stringify(chats.slice(0, 50))); }
    catch (e) { /* private mode, or full -- the chat still works, it just will not persist */ }
  }
  function title(t) { return (t || 'New chat').replace(/\\s+/g, ' ').trim().slice(0, 42); }

  function renderHist() {
    histEl.innerHTML = '';
    chats.forEach(function (c, i) {
      var li = document.createElement('li');
      var b = document.createElement('button');
      b.type = 'button';
      b.className = 'cu-histbtn' + (cur === i ? ' on' : '');
      b.textContent = c.title;
      b.addEventListener('click', function () { open(i); });
      var d = document.createElement('button');
      d.type = 'button'; d.className = 'cu-del'; d.textContent = '×';
      d.setAttribute('aria-label', 'Delete this conversation');
      d.addEventListener('click', function (e) {
        e.stopPropagation();
        chats.splice(i, 1);
        if (cur === i) { cur = null; log.innerHTML = ''; empty.hidden = false; }
        else if (cur !== null && cur > i) cur--;
        save(); renderHist();
      });
      li.appendChild(b); li.appendChild(d); histEl.appendChild(li);
    });
    if (!chats.length) {
      var p = document.createElement('li');
      p.className = 'cu-histnone'; p.textContent = 'No conversations yet.';
      histEl.appendChild(p);
    }
  }

  function open(i) {
    cur = i; log.innerHTML = '';
    chats[i].turns.forEach(function (t) { paint(t.role, t.content); });
    empty.hidden = chats[i].turns.length > 0;
    renderHist();
    log.scrollTop = log.scrollHeight;
  }

  document.getElementById('cu-new').addEventListener('click', function () {
    cur = null; log.innerHTML = ''; empty.hidden = false; box.value = ''; clearFile();
    renderHist(); box.focus();
  });
  document.getElementById('cu-collapse').addEventListener('click', function () {
    document.getElementById('cu-rail').classList.toggle('shut');
  });

  // ---------------------------------------------------------------- transcript
  function paint(role, text) {
    var wrap = document.createElement('div');
    wrap.className = 'cu-turn ' + (role === 'user' ? 'you' : 'bot');
    var who = document.createElement('div');
    who.className = 'cu-who';
    who.textContent = role === 'user' ? 'You' : 'SyMoNeuRaL';
    var msg = document.createElement('div');
    msg.className = 'cu-msg';
    msg.textContent = text;
    wrap.appendChild(who); wrap.appendChild(msg);
    log.appendChild(wrap);
    return msg;
  }

  // ---------------------------------------------------------------- attachments
  // TEXT ONLY, and the accept list says so. The chat model is Qwen2.5-7B-Instruct with no
  // vision projector -- it cannot see an image, so an image picker here would be a control
  // that can never work. The file is read in the browser and its text is prepended to the
  // prompt; it is never uploaded, because there is no upload endpoint and none is needed.
  fileEl.addEventListener('change', function () {
    var f = fileEl.files && fileEl.files[0];
    if (!f) return clearFile();
    if (f.size > 200000) {
      fileName.textContent = f.name + ' is too large (200 KB max)';
      fileEl.value = ''; attached = null; return;
    }
    var r = new FileReader();
    r.onload = function () {
      attached = {name: f.name, text: String(r.result).slice(0, 24000)};
      fileName.textContent = f.name + '  ×';
    };
    r.readAsText(f);
  });
  fileName.addEventListener('click', clearFile);
  function clearFile() { attached = null; fileEl.value = ''; fileName.textContent = ''; }

  // ---------------------------------------------------------------- send
  box.addEventListener('input', function () {
    box.style.height = 'auto';
    box.style.height = Math.min(260, box.scrollHeight) + 'px';
  });
  box.addEventListener('keydown', function (e) {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); form.requestSubmit(); }
  });

  form.addEventListener('submit', function (e) {
    e.preventDefault();
    if (busy) return;
    var q = box.value.trim();
    if (!q) return;
    var sent = q;
    if (attached) sent = 'File: ' + attached.name + '\\n\\n' + attached.text + '\\n\\n' + q;

    if (cur === null) {
      chats.unshift({title: title(q), turns: []});
      cur = 0;
    }
    empty.hidden = true;
    paint('user', attached ? (attached.name + '  —  ' + q) : q);
    chats[cur].turns.push({role: 'user', content: sent});
    box.value = ''; box.style.height = 'auto'; clearFile();
    log.scrollTop = log.scrollHeight;

    var out = paint('assistant', '');
    busy = true; send.disabled = true; stat.textContent = 'thinking…';

    // Everything before this turn, replayed. The cap matches the server's, so a long chat
    // is trimmed here rather than refused there.
    var prior = chats[cur].turns.slice(0, -1).slice(-1000);

    fetch('/api/chat', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({prompt: sent, history: prior,
                            temperature: 0.7, max_tokens: 4096})
    }).then(function (r) {
      if (!r.ok) return r.json().catch(function () { return {}; }).then(function (j) {
        throw new Error(j.detail || j.error || ('HTTP ' + r.status));
      });
      var reader = r.body.getReader(), dec = new TextDecoder(), buf = '', text = '';
      return (function pump() {
        return reader.read().then(function (res) {
          if (res.done) return text;
          buf += dec.decode(res.value, {stream: true});
          var parts = buf.split('\\n\\n'); buf = parts.pop();
          parts.forEach(function (block) {
            block.split('\\n').forEach(function (line) {
              if (line.indexOf('data:') !== 0) return;
              var j; try { j = JSON.parse(line.slice(5)); } catch (e) { return; }
              if (j.delta) {
                text += j.delta; out.textContent = text; log.scrollTop = log.scrollHeight;
                // One token landed, right now. `tick` rather than a guessed velocity: the
                // rate is not measured until the server sends `done`, and inventing a
                // number here to make the picture livelier is exactly the dishonest pixel
                // the visualizer's header comment refuses.
                window.SymonVisualizer.tick();
              }
              if (j.done) {
                // Measured, not claimed -- the server times the card and sends the rate.
                stat.textContent = j.tokens + ' tokens in ' + j.seconds + 's  ·  '
                                 + j.tok_per_s + ' tok/s measured on the card'
                                 + (j.adapter ? '  ·  persona adapter loaded' : '');
                // Generation is over, so the emitter stops. The particles already in flight
                // finish their arcs and expire; nothing new is produced, because nothing new
                // is being computed.
                window.SymonVisualizer.setVelocity(0);
              }
              if (j.error) throw new Error(j.error);
            });
          });
          return pump();
        });
      })();
    }).then(function (text) {
      chats[cur].turns.push({role: 'assistant', content: text});
      if (chats[cur].turns.length === 2) chats[cur].title = title(q);
      save(); renderHist();
    }).catch(function (err) {
      out.textContent = String(err.message || err);
      out.parentElement.classList.add('failed');
      stat.textContent = '';
    }).then(function () {
      busy = false; send.disabled = false; box.focus();
      // The one place that runs on every exit path. A stream that fails mid-answer never
      // sends `done`, so without this the emitter would keep running after an error and the
      // page would be showing activity that had stopped -- the failure mode this whole file
      // is written to avoid.
      window.SymonVisualizer.setVelocity(0);
    });
  });

  load(); renderHist();
})();
</script>"""



# ---------------------------------------------------------------- image
IMAGE_BODY = """    <div class="pgwrap">
      <div class="stage">
        <div class="head" id="ihead"><s></s>SyMoNeuRaL Image
          <span class="grow">idle</span></div>
        <div class="body">
          <div class="shots" id="shots">
            <div class="shot im-empty">
              <div class="cap im-empty-cap">
                Describe something and press Generate. FLUX.1-schnell, four steps, rendered on
                the card in this machine.
              </div>
            </div>
          </div>
        </div>
        <form class="composer" id="form">
          <textarea id="prompt" rows="3" maxlength="100000"
                    placeholder="a raven perched on a server rack, volumetric light, cinematic"></textarea>
          <button class="cta" id="send" type="submit">Generate</button>
        </form>
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
          <input type="number" id="seed" min="0" max="2147483647" placeholder="leave blank for random">
        </div>
        <p class="hint">
          schnell is a distilled model: four steps is what it was trained for, and guidance is
          pinned to 1.0 because raising it degrades this model rather than sharpening it. More
          steps costs time without buying much.
        </p>
        <p class="hint" id="stat">&nbsp;</p>
      </aside>
    </div>"""

# ---------------------------------------------------------------- image: css
#
# EVERY class here is prefixed `im-` and every rule is a class, never an element or a
# generic name. `.bar`, `.live`, `.card` and `#console .sub` have each been defined a
# second time in this codebase and each time the second definition silently ate the first.
# The CALC_BODY comment below states the same rule for the keypad; it applies with more
# force here, because this file is a separate stylesheet and a collision would be even
# further from the markup that suffers it.
#
# These rules were `style="..."` attributes until #81 -- four of them in the markup and,
# worse, three built by string concatenation inside the render handler. There is no
# `text-overflow` rule here and none may be added: `.claude/CLAUDE.md` bars ellipsis
# outright, and a truncated caption would be hiding the seed, the step count and the
# wall-clock, which are the only reason the caption exists.
IMAGE_CSS = """/* SyMoNeuRaL Image -- the page's own rules. Generated by tools/build/build_pages.py.
   Do not hand-edit: the next generator run overwrites this file. */

/* The dashed "nothing rendered yet" tile, spanning the whole shot grid. */
.im-empty { grid-column: 1 / -1; border-style: dashed; }
.im-empty-cap { border-top: 0; text-align: center; padding: 40px 20px; }

/* The square placeholder that stands in while the card is working. Its aspect-ratio is
   what stops the grid reflowing when the real image replaces it. */
.im-pending {
  aspect-ratio: 1 / 1;
  display: grid;
  place-items: center;
  background: var(--panel2);
  color: var(--faint);
  font-size: 13px;
}

/* pre-line, because the caption is deliberately two lines: the prompt as typed, then the
   measurements. Collapsing them would run the prompt into the seed. */
.im-cap { white-space: pre-line; }
.im-error { color: var(--amber); }
"""

# ---------------------------------------------------------------- image: js
#
# No <script> wrapper: `page(js=...)` writes this to frontend/site/js/image.js and the shell references
# it with `defer`. See page()'s docstring for why deferred is correct here and why the
# shared `$`/`status`/`api` helpers stay inline in the shell.
IMAGE_JS = """// SyMoNeuRaL Image -- the page's own behaviour. Generated by tools/build/build_pages.py.
// Do not hand-edit: the next generator run overwrites this file.
//
// Deferred, so the document is parsed before this runs and every element queried below
// exists. `$`, `status()` and `api()` come from the shell's inline block, which runs at
// parse time and therefore earlier than this file -- see tools/build/build_pages.py.
const form = $('#form'), send = $('#send'), shots = $('#shots'), head = $('#ihead');
let size = 768, first = true;
$('#steps').addEventListener('input', e => $('#stepsv').textContent = e.target.value);
$('#seed').addEventListener('input', e =>
  $('#seedlock').textContent = e.target.value === '' ? 'random' : 'locked');
$('#size').addEventListener('click', e => {
  const b = e.target.closest('button'); if (!b) return;
  size = parseInt(b.dataset.v, 10);
  [...e.currentTarget.children].forEach(x => x.setAttribute('aria-pressed', x === b));
});

form.addEventListener('submit', async e => {
  e.preventDefault();
  const prompt = $('#prompt').value.trim();
  if (!prompt) return;
  send.disabled = true;
  status(head, 'loading the image model \\u2014 chat is being evicted to make room', true);

  const card = document.createElement('div');
  card.className = 'shot';
  card.innerHTML = '<div class="im-pending">rendering\\u2026</div>' +
                   '<div class="cap"></div>';
  $('.cap', card).textContent = prompt;
  if (first) { shots.innerHTML = ''; first = false; }
  shots.prepend(card);

  const t0 = performance.now();
  try {
    const seedRaw = $('#seed').value;
    const r = await api('/api/image', {
      prompt, size,
      steps: parseInt($('#steps').value, 10),
      ...(seedRaw === '' ? {} : {seed: parseInt(seedRaw, 10)})
    });
    card.innerHTML = '';
    const img = document.createElement('img');
    img.src = r.url; img.alt = prompt; img.loading = 'lazy';
    const cap = document.createElement('div');
    cap.className = 'cap im-cap';
    // The wall-clock is the point. It is what this card actually took, round trip included.
    cap.textContent = `${prompt}\\n${r.size}\\u00d7${r.size} \\u00b7 ${r.steps} steps \\u00b7 ` +
                      `seed ${r.seed} \\u00b7 ${r.seconds}s on the card \\u00b7 ${r.model}`;
    card.append(img, cap);
    $('#stat').textContent = `last render: ${r.seconds}s`;
  } catch (err) {
    card.innerHTML = '';
    const cap = document.createElement('div');
    cap.className = 'cap im-error';
    cap.textContent = err.message;
    card.append(cap);
  } finally {
    send.disabled = false; status(head, 'idle', false);
  }
});
"""

# ---------------------------------------------------------------- calc
#
# The keypad's CSS is inline, in the page, on purpose. `frontend/site/css/symoneural.css` is not written
# by this generator, so shipping these rules with the markup keeps the two halves in one
# file and one commit -- and an inline block cannot be served stale against new markup,
# which is the failure `tools/build/build_cachebust.py` exists to prevent.
#
# EVERY class below is prefixed `rc-` and EVERY rule is scoped under `.rc-calc`. `.bar`,
# `.live`, `.card` and `#console .sub` have each been defined a second time in this
# codebase and each time the second definition silently ate the first -- five instances of
# one bug class. Do not add a generic name here.
CALC_BODY = """    <style>
    /* ---- RavenCalc keypad. All names rc-, all rules scoped under .rc-calc. ---- */
    .rc-calc .rc-strip{
      display:flex; flex-wrap:wrap; align-items:center; gap:7px;
      padding:12px 16px; border-top:1px solid var(--line); background:var(--panel2);
    }
    .rc-calc .rc-lab{
      font:650 var(--t7)/1.5 ui-sans-serif,system-ui,sans-serif; letter-spacing:.13em;
      text-transform:uppercase; color:var(--faint); margin-right:4px;
    }
    .rc-calc .rc-op{
      background:var(--bg); color:var(--dim); border:1px solid var(--line);
      border-radius:8px; padding:7px 11px; cursor:pointer;
      font:600 11.9px/1.3 ui-sans-serif,system-ui,sans-serif;
    }
    .rc-calc .rc-op:hover{color:var(--fg); border-color:var(--faint)}
    .rc-calc .rc-op[aria-pressed=true]{
      background:var(--accent); color:var(--accent-ink); border-color:transparent;
    }
    .rc-calc .rc-op:focus-visible,
    .rc-calc .rc-key:focus-visible{outline:2px solid var(--accent); outline-offset:2px}

    .rc-calc .rc-pad{
      padding:12px 16px 14px; border-top:1px solid var(--line); background:var(--panel2);
    }
    .rc-calc .rc-group{margin-top:11px}
    .rc-calc .rc-group:first-child{margin-top:0}
    .rc-calc .rc-glab{
      margin:0 0 6px; font:650 var(--t7)/1.5 ui-sans-serif,system-ui,sans-serif;
      letter-spacing:.13em; text-transform:uppercase; color:var(--faint);
    }
    /* minmax(0,1fr), never a fixed width: a fixed key width is how a six-column pad runs
       past the right edge of a 390px viewport. Long labels wrap and the row grows. */
    .rc-calc .rc-keys{display:grid; grid-template-columns:repeat(6,minmax(0,1fr)); gap:6px}
    .rc-calc .rc-key{
      background:var(--bg); color:var(--fg); border:1px solid var(--line);
      border-radius:8px; padding:9px 3px; cursor:pointer; min-height:36px;
      font:600 11.9px/1.25 ui-monospace,Menlo,Consolas,monospace;
      overflow-wrap:anywhere;
    }
    .rc-calc .rc-key:hover{border-color:var(--accent)}
    .rc-calc .rc-key:active{background:var(--panel)}
    .rc-calc .rc-fn{color:var(--dim)}
    .rc-calc .rc-var{color:var(--accent)}
    .rc-calc .rc-act{color:var(--amber)}
    /* `del` and `AC` are both words on purpose: the U+232B backspace glyph rendered as an
       unreadable smudge at this size in the monospace stack, measured on this machine. */

    .rc-calc .rc-line{margin-bottom:5px}
    .rc-calc .rc-line:last-child{margin-bottom:0}
    /* The answer is the readout. Nothing here truncates -- it wraps, per the repo rule. */
    .rc-calc .rc-ans{
      font-size:19px; line-height:1.45; color:var(--accent); overflow-wrap:anywhere;
    }
    @media (max-width:560px){
      .rc-calc .rc-keys{gap:5px}
      .rc-calc .rc-key{font-size:11px; padding:9px 2px}
      .rc-calc .rc-ans{font-size:17px}
    }
    </style>
    <div class="pgwrap rc-calc">
      <div class="stage">
        <div class="head" id="rhead"><s class="on"></s>SyMoNeuRaL RavenCalc
          <span class="grow">cpu &middot; never queues</span></div>
        <div class="body">
          <div class="readout" id="out" style="color:var(--faint)">
            Exact symbolic mathematics. Not a language model guessing at algebra &mdash; an exact symbolic engine
            computing it, and checking its own answer where checking is cheap.
          </div>
        </div>

        <!-- The operation is a row of real buttons rather than a <select>: it is the single
             most important choice on the page and a collapsed menu hides six of the seven
             answers. `#op` is a hidden input and is the ONE source of truth -- the buttons
             write it and read their pressed state back from it, so the field that is posted
             and the button that looks chosen cannot disagree. -->
        <div class="rc-strip" role="group" aria-label="Operation">
          <span class="rc-lab">Operation</span>
          <input type="hidden" id="op" value="integrate">
          <button type="button" class="rc-op" data-op="differentiate" aria-pressed="false">differentiate</button>
          <button type="button" class="rc-op" data-op="integrate" aria-pressed="true">integrate</button>
          <button type="button" class="rc-op" data-op="limit" aria-pressed="false">limit</button>
          <button type="button" class="rc-op" data-op="series" aria-pressed="false">series</button>
          <button type="button" class="rc-op" data-op="solve" aria-pressed="false">solve</button>
          <button type="button" class="rc-op" data-op="simplify" aria-pressed="false">simplify</button>
          <button type="button" class="rc-op" data-op="evaluate" aria-pressed="false">evaluate</button>
        </div>

        <form class="composer" id="form">
          <textarea id="expr" rows="3" maxlength="100000" placeholder="x**2*sin(x)"></textarea>
          <button class="cta" id="send" type="submit">Compute</button>
        </form>

        <!-- The keypad sits OUTSIDE #form deliberately. A <button> inside a form with no
             type is a submit button, and the shared Enter handler calls requestSubmit(),
             which activates the form's default submit button -- so a key in here without
             type="button" would make Enter type a digit instead of computing. They all
             carry type="button" as well; both halves, because either alone is one edit
             away from being wrong.
             Every label is the engine name that is actually inserted. `title` carries the
             human meaning; the button does not lie about what it types. -->
        <div class="rc-pad" id="rcpad">
          <div class="rc-group">
            <p class="rc-glab">Functions</p>
            <div class="rc-keys">
              <button type="button" class="rc-key rc-fn" data-fn="sin">sin</button>
              <button type="button" class="rc-key rc-fn" data-fn="cos">cos</button>
              <button type="button" class="rc-key rc-fn" data-fn="tan">tan</button>
              <button type="button" class="rc-key rc-fn" data-fn="asin" title="inverse sine">asin</button>
              <button type="button" class="rc-key rc-fn" data-fn="acos" title="inverse cosine">acos</button>
              <button type="button" class="rc-key rc-fn" data-fn="atan" title="inverse tangent">atan</button>
              <button type="button" class="rc-key rc-fn" data-fn="sinh" title="hyperbolic sine">sinh</button>
              <button type="button" class="rc-key rc-fn" data-fn="cosh" title="hyperbolic cosine">cosh</button>
              <button type="button" class="rc-key rc-fn" data-fn="tanh" title="hyperbolic tangent">tanh</button>
              <button type="button" class="rc-key rc-fn" data-fn="log" title="natural logarithm (log and ln are the same function here)">log</button>
              <button type="button" class="rc-key rc-fn" data-fn="ln" title="natural logarithm">ln</button>
              <button type="button" class="rc-key rc-fn" data-fn="exp" title="e raised to the power">exp</button>
              <button type="button" class="rc-key rc-fn" data-fn="sqrt" title="square root">sqrt</button>
              <button type="button" class="rc-key rc-fn" data-fn="Abs" title="absolute value &mdash; capital A, this is the engine's name for it">Abs</button>
              <button type="button" class="rc-key rc-fn" data-fn="factorial" title="factorial, n!">factorial</button>
              <button type="button" class="rc-key rc-fn" data-ins="pi" title="pi, exactly &mdash; not 3.14159">pi</button>
              <button type="button" class="rc-key rc-fn" data-ins="E" title="Euler's number e, exactly">E</button>
              <button type="button" class="rc-key rc-fn" data-ins="oo" title="infinity &mdash; two lowercase letter o">oo</button>
            </div>
          </div>
          <div class="rc-group">
            <p class="rc-glab">Numbers, operators, variables</p>
            <div class="rc-keys">
              <button type="button" class="rc-key" data-ins="7">7</button>
              <button type="button" class="rc-key" data-ins="8">8</button>
              <button type="button" class="rc-key" data-ins="9">9</button>
              <button type="button" class="rc-key" data-ins="(" aria-label="Open bracket">(</button>
              <button type="button" class="rc-key" data-ins=")" aria-label="Close bracket">)</button>
              <button type="button" class="rc-key rc-act rc-back" data-act="back" aria-label="Backspace" title="Backspace &mdash; deletes at the caret">del</button>
              <button type="button" class="rc-key" data-ins="4">4</button>
              <button type="button" class="rc-key" data-ins="5">5</button>
              <button type="button" class="rc-key" data-ins="6">6</button>
              <button type="button" class="rc-key" data-ins="+" aria-label="Plus">+</button>
              <button type="button" class="rc-key" data-ins="-" aria-label="Minus">-</button>
              <button type="button" class="rc-key rc-act" data-act="clear" aria-label="Clear the expression" title="Clear the expression">AC</button>
              <button type="button" class="rc-key" data-ins="1">1</button>
              <button type="button" class="rc-key" data-ins="2">2</button>
              <button type="button" class="rc-key" data-ins="3">3</button>
              <button type="button" class="rc-key" data-ins="*" aria-label="Multiply">*</button>
              <button type="button" class="rc-key" data-ins="/" aria-label="Divide">/</button>
              <button type="button" class="rc-key" data-ins="," aria-label="Comma">,</button>
              <button type="button" class="rc-key" data-ins="0">0</button>
              <button type="button" class="rc-key" data-ins="." aria-label="Decimal point">.</button>
              <button type="button" class="rc-key" data-ins="**" aria-label="Power, two asterisks" title="power &mdash; x**2 is x squared">**</button>
              <button type="button" class="rc-key rc-var" data-ins="x">x</button>
              <button type="button" class="rc-key rc-var" data-ins="y">y</button>
              <button type="button" class="rc-key rc-var" data-ins="z">z</button>
            </div>
          </div>
        </div>
      </div>

      <aside class="panel">
        <h3>Applied to</h3>
        <div class="ctl">
          <label for="var">Variable</label>
          <input type="text" id="var" value="x" maxlength="16">
        </div>
        <div class="ctl" id="ptwrap" hidden>
          <label for="pt">Point</label>
          <input type="text" id="pt" value="0" maxlength="32">
        </div>
        <p class="hint">
          The keys type the engine&#39;s own notation, which is the language it actually reads:
          <code>**</code> for a power, <code>sqrt(x)</code>, <code>Abs(x)</code>,
          <code>pi</code> and <code>E</code> as exact constants, <code>oo</code> for
          infinity. You can type it yourself as well &mdash; the box is a plain text field.
        </p>
        <p class="hint">
          Symbolic in, symbolic out &mdash; you get an exact answer rather than a float that
          already lost the argument. An antiderivative is differentiated back and simplified
          against zero before you see it, and if that check cannot confirm the result it says
          so rather than rounding up to &ldquo;verified&rdquo;.
        </p>
      </aside>
    </div>"""

# NOTE ON ESCAPES, which have killed a page in production once already: this is a NORMAL
# triple-quoted string, not a raw one. A `\n` written here becomes a REAL newline inside the
# emitted JavaScript, and inside a JS string literal that is an unterminated string that
# kills the whole page's script -- silently, because markup, CSS and endpoint assertions all
# still pass. Write `\\n`. There are none below; keep it that way.
CALC_JS = """<script>
(function () {
  'use strict';
  var form = document.getElementById('form');
  var out = document.getElementById('out');
  var expr = document.getElementById('expr');
  var opField = document.getElementById('op');
  var ptwrap = document.getElementById('ptwrap');
  var head = document.getElementById('rhead');
  var send = document.getElementById('send');
  var pad = document.getElementById('rcpad');
  var ops = Array.prototype.slice.call(document.querySelectorAll('.rc-op'));

  // ---- the operation ------------------------------------------------------
  // `point` reaches the engine for BOTH limit and series -- ravencalc.py parses it and
  // passes it to the engine's series expansion as the expansion point, even though CalcRequest documents
  // the field as limit-only. Offered for both, hidden for the five that ignore it.
  function setOp(name) {
    opField.value = name;
    ops.forEach(function (b) {
      b.setAttribute('aria-pressed', b.getAttribute('data-op') === name ? 'true' : 'false');
    });
    ptwrap.hidden = !(name === 'limit' || name === 'series');
  }
  ops.forEach(function (b) {
    b.addEventListener('click', function () { setOp(b.getAttribute('data-op')); });
  });
  setOp(opField.value);

  // ---- the keypad ---------------------------------------------------------
  // Everything is written at the caret, not appended: a calculator that can only add to the
  // end of the line is not one you can correct a mistake in.
  function place(a, b) { expr.focus(); expr.setSelectionRange(a, b); }

  function insert(text) {
    var s = expr.selectionStart, e = expr.selectionEnd, v = expr.value;
    expr.value = v.slice(0, s) + text + v.slice(e);
    place(s + text.length, s + text.length);
  }

  // A function key wraps the selection if there is one -- select `x+1`, press sin, and you
  // get sin(x+1) rather than losing what you had. With no selection the caret lands between
  // the brackets, which is where you are about to type.
  function wrap(name) {
    var s = expr.selectionStart, e = expr.selectionEnd, v = expr.value;
    var inner = v.slice(s, e);
    expr.value = v.slice(0, s) + name + '(' + inner + ')' + v.slice(e);
    var caret = s + name.length + 1 + inner.length;
    place(caret, caret);
  }

  function backspace() {
    var s = expr.selectionStart, e = expr.selectionEnd, v = expr.value;
    if (s !== e) { expr.value = v.slice(0, s) + v.slice(e); place(s, s); return; }
    if (s === 0) return;
    expr.value = v.slice(0, s - 1) + v.slice(s);
    place(s - 1, s - 1);
  }

  // Pressing a button moves focus off the textarea and the browser forgets the selection,
  // so every key would type at position 0. Cancelling mousedown keeps the caret where the
  // user put it.
  pad.addEventListener('mousedown', function (ev) {
    if (ev.target.closest('.rc-key')) ev.preventDefault();
  });
  pad.addEventListener('click', function (ev) {
    var key = ev.target.closest('.rc-key');
    if (!key) return;
    var act = key.getAttribute('data-act');
    if (act === 'clear') { expr.value = ''; place(0, 0); }
    else if (act === 'back') backspace();
    else if (key.getAttribute('data-fn')) wrap(key.getAttribute('data-fn'));
    else insert(key.getAttribute('data-ins') || '');
  });

  // ---- compute ------------------------------------------------------------
  function esc(s) {
    var d = document.createElement('div');
    d.textContent = s == null ? '' : String(s);
    return d.innerHTML;
  }

  form.addEventListener('submit', function (ev) {
    ev.preventDefault();
    var expression = expr.value.trim();
    if (!expression) return;
    var operation = opField.value;
    out.style.color = 'var(--fg)';
    out.textContent = 'computing\\u2026';
    send.disabled = true;
    status(head, 'computing\\u2026', true);

    var payload = {expression: expression, operation: operation,
                   variable: document.getElementById('var').value.trim()};
    if (operation === 'limit' || operation === 'series') {
      payload.point = document.getElementById('pt').value.trim();
    }

    api('/api/ravencalc', payload).then(function (r) {
      var c = r.check || {};
      var verdict = c.performed
        ? (c.passed === true ? '<span class="v">verified</span>'
           : c.passed === false ? '<span class="bad">CHECK FAILED</span>'
           : '<span class="bad">unconfirmed</span>')
        : '<span class="k">not checked</span>';
      // `in` is what the engine PARSED, which is not always what you typed -- the engine
      // evaluates as it parses, so integrate(x**2, x) is already x**3/3 by the time the
      // operation runs. Printing it is how you can see that, rather than being surprised
      // by the answer. It is not decoration and it is asserted on by the test suite.
      out.innerHTML =
        '<div class="rc-line"><span class="k" title="the expression as the engine parsed it">in</span> ' +
          esc(r.input.text) + '</div>' +
        '<div class="rc-line"><span class="k">out</span> <span class="rc-ans">' +
          esc(r.result.text) + '</span></div>' +
        '<div class="rc-line"><span class="k">chk</span> ' + verdict +
          (c.how ? ' <span class="k">&mdash; ' + esc(c.how) + '</span>' : '') + '</div>' +
        (r.note ? '<div class="rc-line"><span class="k">note</span> <span class="k">' +
          esc(r.note) + '</span></div>' : '') +
        '<div class="rc-line"><span class="k">eng</span> <span class="k">' + esc(r.engine) +
          ' \\u00b7 ' + r.seconds + 's \\u00b7 ' + (r.exact ? 'exact' : 'symbolic') +
          '</span></div>';
    }).catch(function (err) {
      out.innerHTML = '<span class="bad">' + esc(err.message) + '</span>';
    }).then(function () {
      send.disabled = false;
      status(head, 'cpu \\u00b7 never queues', false);
    });
  });
}());
</script>"""

# ---------------------------------------------------------------- remix
REMIX_BODY = """    <div class="pgwrap">
      <div class="stage">
        <div class="head" id="mhead"><s></s>SyMoNeuRaL Remix
          <span class="grow">idle</span></div>
        <div class="body">
          <div id="out" style="color:var(--faint);font-size:14.5px;line-height:1.66">
            Describe a mood, a night, a drive, a room. You get an ordered set rather than a pile
            of songs &mdash; sequenced so it actually flows.
          </div>
        </div>
        <form class="composer" id="form">
          <textarea id="brief" rows="3" maxlength="100000"
                    placeholder="late-night drive through a rainy city, building slowly"></textarea>
          <button class="cta" id="send" type="submit">Build it</button>
        </form>
      </div>

      <aside class="panel">
        <h3>Parameters</h3>
        <div class="ctl">
          <label for="count">Tracks <b id="countv">12</b></label>
          <input type="range" id="count" min="5" max="20" step="1" value="12">
        </div>
        <p class="hint">
          Remix is a client of the chat surface rather than its own model &mdash; the same 7B
          that answers questions writes the sequence, which is what &ldquo;one server
          underneath&rdquo; means in practice. So it queues behind chat, and behind image.
        </p>
        <p class="hint">
          <strong style="color:var(--dim)">Generation only, here.</strong> Resolving these
          against Spotify and writing the playlist to an account needs OAuth, and that half
          runs on the box behind admin auth &mdash; not from a public page.
        </p>
      </aside>
    </div>"""

REMIX_JS = """<script>
const form = $('#form'), out = $('#out'), send = $('#send'), head = $('#mhead');
$('#count').addEventListener('input', e => $('#countv').textContent = e.target.value);

form.addEventListener('submit', async e => {
  e.preventDefault();
  const prompt = $('#brief').value.trim();
  if (!prompt) return;
  send.disabled = true;
  out.style.color = 'var(--faint)';
  out.textContent = 'sequencing\\u2026';
  status(head, 'generating', true);
  try {
    const r = await api('/api/remix', {prompt, count: parseInt($('#count').value, 10)});
    if (!r.tracks || !r.tracks.length) {
      out.innerHTML = '<span style="color:var(--amber)">The model did not return a clean list. ' +
                      'Try phrasing the brief differently.</span>';
    } else {
      const ul = document.createElement('ul');
      ul.className = 'tracks';
      for (const t of r.tracks) {
        const li = document.createElement('li');
        const d = document.createElement('div');
        d.innerHTML = '<span class="t"></span> <span class="a"></span><span class="w"></span>';
        d.querySelector('.t').textContent = t.title || '';
        d.querySelector('.a').textContent = t.artist ? '\\u2014 ' + t.artist : '';
        d.querySelector('.w').textContent = t.why || '';
        li.append(d); ul.append(li);
      }
      out.innerHTML = '';
      out.style.color = 'var(--fg)';
      out.append(ul);
      const m = document.createElement('p');
      m.className = 'hint';
      m.textContent = `${r.tracks.length} tracks \\u00b7 ${r.seconds}s on the card \\u00b7 ${r.note}`;
      out.append(m);
    }
  } catch (err) {
    out.innerHTML = '<span style="color:var(--amber)">' + err.message + '</span>';
  } finally {
    send.disabled = false; status(head, 'idle', false);
  }
});
</script>"""


# ---------------------------------------------------------------- miner (ASIC)
# Deliberately has no controls on it. The rig actions -- reboot, pool change, power mode --
# are operator functions behind a token, and putting the buttons on a public page and then
# refusing the click is worse than not drawing them: it advertises an attack surface and
# teaches visitors that the site's controls are ornamental. This page reports, and says
# plainly what it would report if hardware were attached.
MINER_BODY = """    <div class="pgwrap">
      <!-- TWO units answer on this page and they are different hardware: `gpuminer` is the
           RTX 5070 Ti in this box, `asicminer` is a panel for rigs on the operator's
           network. They share no code, no token and no route prefix, so they get one card
           each rather than one merged "miner" that would have to lie about one of them.
           `.mg-col` exists because .pgwrap is a two-column grid -- a second .stage as a
           direct child would land in the aside column. -->
      <div class="mg-col">

      <div class="stage" id="mg-stage">
        <div class="head" id="mghead"><s id="mgdot"></s>SyMoNeuRaL Miner &mdash; GPU, Ravencoin
          <span class="grow" id="mgstate">reading&hellip;</span></div>
        <div class="body" id="mgbody">
          <p class="mg-lede">The <b>intended</b> KawPow path for the RTX 5070 Ti described on
            the home page, through the same GPU governor every other surface queues on. It is
            <b>offline unless configured</b>: <code>SYMONEURAL_MINING_ENABLED=1</code>,
            <code>SYMONEURAL_MINER_CMD</code> and <code>SYMONEURAL_MINER_TOKEN</code> all have
            to be set, and the engine work is <b>incomplete</b> &mdash; there is no
            <code>symoneural-miner</code> in this tree and the build script that produced the
            binary behind the benchmark is not tracked here. So this half reports <i>offline /
            engine missing</i> rather than a hashrate. When a miner <i>is</i> running, every
            figure below is read from it or from <code>nvidia-smi</code>; when it is not, there
            is no figure, and the row says so rather than showing a last-known value.</p>

          <!-- Public rows first. Both come from GET /api/status, which every visitor can
               read, and both are produced by cryptominer.unit_state() -- so this card and
               the rack on the home page cannot disagree about what the miner is doing. -->
          <dl class="mg-facts">
            <dt>Rack unit</dt><dd id="mg-unit">&mdash;</dd>
            <dt>Reading</dt><dd id="mg-detail">reading <code>/api/status</code>&hellip;</dd>
          </dl>

          <!-- The numeric feed is behind the operator token and stays there: it describes
               the machine's own configuration, which is the operator's business and not a
               visitor's. Until a token is presented these rows say what is missing rather
               than showing a plausible number. -->
          <p class="mg-telhead">Operator telemetry</p>
          <dl class="mg-facts mg-tel">
            <dt>Hashrate</dt><dd id="mg-hr">token required</dd>
            <dt>Submitting to a pool</dt><dd id="mg-pool">token required</dd>
            <dt>Holds the card</dt><dd id="mg-lock">token required</dd>
            <dt>Running for</dt><dd id="mg-up">token required</dd>
          </dl>

          <p class="mg-warn"><b>Starting this takes the card from everything else.</b> The
            miner holds the GPU lock for its whole process lifetime, not for a job, and it
            is not preemptible: an arriving chat or image request spins in the governor&rsquo;s
            acquire loop for up to its 300&nbsp;s timeout and then gives up. <b>Measured</b>
            on this box, with the timeout cut to ten seconds to show it rather than wait it
            out: <code>gpu-governor.sh acquire chat 10</code> against a live miner logs
            <code>'chat' TIMED OUT after 10s behind 'miner'</code>. That is why nothing here
            starts by itself, and why it should be stopped deliberately rather than left
            holding the card on a box that also serves chat and image.</p>

          <form class="mg-ops" id="mg-ops" autocomplete="off">
            <label for="mg-token">Operator token</label>
            <input type="password" id="mg-token" name="mg-token"
                   placeholder="SYMONEURAL_MINER_TOKEN" autocomplete="off" spellcheck="false">
            <button type="button" class="mg-btn" id="mg-start">Start mining</button>
            <button type="button" class="mg-btn" id="mg-stop">Stop</button>
            <button type="button" class="mg-btn ghost" id="mg-read">Read telemetry</button>
          </form>
          <p class="mn-note" id="mgnote"></p>
        </div>
      </div>

      <div class="stage" id="mn-stage">
        <div class="head" id="mnhead"><s></s>SyMoNeuRaL ASIC &mdash; stack controller
          <span class="grow" id="mnstate">reading&hellip;</span></div>
        <div class="body" id="mnbody">

          <ol class="mn-steps" id="mn-steps">
            <li class="on" data-step="1"><b>1</b> Source</li>
            <li data-step="2"><b>2</b> Vendor</li>
            <li data-step="3"><b>3</b> Model</li>
          </ol>

          <section class="mn-pane on" id="mn-p1">
            <p class="mn-q">Where should the controller look for rigs?</p>
            <div class="mn-choices">
              <button type="button" class="mn-choice" data-src="scan">
                <b>IP scanner</b>
                <span>Sweep a private range for anything answering on the miner API port,
                  then identify it. Real hardware only.</span>
              </button>
              <button type="button" class="mn-choice" data-src="emu">
                <b>Emulator</b>
                <span>Boot real vendor firmware under QEMU and drive that instead. For
                  working on the flash path without risking a rig.</span>
              </button>
            </div>
          </section>

          <section class="mn-pane" id="mn-p2">
            <p class="mn-q">Which vendor?</p>
            <div class="mn-choices">
              <button type="button" class="mn-choice" data-vendor="antminer">
                <b>Antminer</b><span>Bitmain &middot; Xilinx Zynq control board</span>
              </button>
              <button type="button" class="mn-choice" data-vendor="microbt">
                <b>MicroBT</b><span>Whatsminer</span>
              </button>
            </div>
            <button type="button" class="mn-back" data-to="1">&larr; back</button>
          </section>

          <section class="mn-pane" id="mn-p3">
            <p class="mn-q">Which model?</p>
            <div class="mn-models" id="mn-models"></div>
            <p class="mn-legend">
              <i class="mn-dot ok"></i> boots, verified
              <i class="mn-dot part"></i> firmware present, does not boot yet
              <i class="mn-dot no"></i> no firmware on this machine
            </p>
            <button type="button" class="mn-back" data-to="2">&larr; back</button>
          </section>

          <p class="mn-note" id="mnnote"></p>

          <!-- These two were callouts in the aside. They are folds here for two reasons:
               the aside ran a full screen longer than this column, which is the "we went a
               little too small, fill the window" complaint in its other form; and an
               explanation of what the emulator cannot do belongs beside the button that
               starts it rather than in a sidebar. Folded, not trimmed -- the text is
               unchanged and in the DOM either way. `details.fold` is the existing styled
               component from build_console.py, reused rather than reinvented. -->
          <details class="fold">
            <summary>What the emulator is and is not<span>QEMU, no hashboards</span></summary>
            <div class="foldbody">
              <p>QEMU runs the control board&rsquo;s ARM cores. It does <b>not</b> emulate the
                FPGA fabric or the links to the hashboards &mdash; those are the part that is
                not there. So the firmware&rsquo;s web UI and its upgrade path run, and
                <b>bmminer does not</b>: with the miner&rsquo;s own init the firmware finds no
                hashboards and reboot-loops, which is correct behaviour and useless as a
                target.</p>
              <p>It is a good way to work on <b>flashing</b> without risking a rig. It is
                <b>not</b> a substitute for hardware when testing telemetry.</p>
            </div>
          </details>
          <details class="fold">
            <summary>Why models are greyed out<span>read off this disk</span></summary>
            <div class="foldbody">
              <p>A model is listed as available only if its firmware is actually on this
                machine and has been booted. Nothing is listed on the strength of the
                hardware existing &mdash; the same rule the rack follows.</p>
            </div>
          </details>
        </div>
      </div>

      </div>

      <aside class="side">
        <div class="callout">
          <h3>A benchmark from August, not current telemetry</h3>
          <p><b>52.3 &ndash; 53.2 MH/s</b> on KawPow &mdash; <b>measured</b> on this machine
            across four runs, RTX 5070 Ti at a 300&nbsp;W limit, driver 610.57.04,
            <code>kawpowminer 1.2.4</code>, <b>2026-08-17</b>. The miner&rsquo;s own summary for
            the longest run reads <code>Max 53.209880 Mh Mean 53.026032 Mh</code>. A short run
            reads lower because its mean includes spin-up, not because the card slowed down.
            The spread across runs is quoted rather than the best figure and <b>no cause has
            been established for it</b>.</p>
          <p><b>This tree cannot reproduce it.</b> The figures came from somebody
            else&rsquo;s binary, and the script that built it &mdash;
            <code>contrib/build-kawpowminer.sh</code> &mdash; <b>is not tracked in this
            repository</b>, so a clone has no path from source to a running miner. Read the
            numbers as <b>provenance</b>: evidence of what this card did once, on a dated run,
            with a named binary. They are not a claim about what the surface does now, and
            nothing on this page reports them as live telemetry.</p>
          <p>All four were <b>benchmarks against no pool</b>. A miner with nowhere to submit
            a share earns nothing whatever its hashrate says, so the surface reports
            hashrate and income as two separate claims &mdash; and publishes no income
            figure at all, because that depends on network difficulty, pool fees and the RVN
            price, none of which this box measures. Pricing questions go to
            <a href="mailto:symonsayadmin@symoneural.com">symonsayadmin@symoneural.com</a>.</p>
        </div>
        <div class="callout">
          <h3>One miner, two kinds of hardware</h3>
          <p>The rack lists <b>one</b> SyMoNeuRaL Miner. Under it are two halves that fail
            independently, so this page gives each its own card and its own status chip
            rather than averaging them into a single light.</p>
          <p><b>GPU &middot; Ravencoin</b> is the card in this box &mdash; the intended
            KawPow path for the RTX 5070 Ti, and the only half of this surface that has ever
            hashed, on the dated 2026-08-17 benchmark above. It is also the only half that
            takes the GPU, which is why the merged row reports <i>busy</i> whenever it is
            running: that is a fact every other surface on this machine feels. The engine work
            is <b>incomplete</b>, so it is <i>offline</i> here rather than hashing.</p>
          <p><b>ASIC &middot; Antminer + MicroBT</b> reads rigs on your own network, and
            carries a firmware emulator and a network scanner &mdash; the two parts that do
            real work with <i>no rig attached</i>. It reports offline here because none is
            attached and the surface is switched off, and that is the reading rather than a
            placeholder.</p>
          <p>They keep separate tokens and separate routes. They were two rack rows until
            2026-08-17 &mdash; <i>SyMoNeuRaL Miner</i>, offline with no rig attached, beside
            <i>SyMoNeuRaL Miner GPU</i>, which was the one actually hashing. The plain
            product name was on the dead row and the working one wore a qualifier, so the
            pair read as a single half-broken surface.</p>
        </div>
        <div class="callout">
          <h3>What the switches actually switch</h3>
          <p><code>SYMONEURAL_ASIC_ENABLED</code> does not enable a rig and does not enable mining.
            It enables <b>these operator controls on this server</b> &mdash; scan, firmware
            listing, emulator &mdash; and with <code>SYMONEURAL_ASIC_TOKEN</code> unset they stay
            off, so a misconfigured box serves nothing here rather than serving an
            unauthenticated scanner. The scanner also refuses any range that is not private,
            so it cannot be aimed at the internet from this host.</p>
          <p><b>You do not need either variable to run the QEMU emulator.</b>
            <code>SYMONEURAL_ASIC_ENABLED=1</code> and <code>SYMONEURAL_ASIC_TOKEN</code> gate the HTTP API
            only; <code>scripts/qemu-antminer.sh</code> runs without them. Setting them will
            not make an emulator report a hashrate either, because QEMU emulates the Zynq CPU
            and <b>not</b> the hashboards &mdash; so nothing answers on port 4028, and that is
            the emulator working correctly rather than a misconfiguration. The value is
            compared as the literal string <code>1</code>: <code>true</code>, <code>yes</code>
            and <code>on</code> all leave the surface off.</p>
          <p>The GPU miner above has its own pair, <code>SYMONEURAL_MINING_ENABLED</code> and
            <code>SYMONEURAL_MINER_TOKEN</code>, and the two tokens must not be the same string:
            this one authorises reading rigs, that one authorises taking the card away from
            every other surface.</p>
        </div>
      </aside>
    </div>
"""


MINER_JS = """<script>
(function () {
  'use strict';
  var state = {src: null, vendor: null, pkg: null, packages: null};
  var note = document.getElementById('mnnote');
  var stEl = document.getElementById('mnstate');

  // The operator token. sessionStorage, not localStorage: this authorises scanning and
  // starting processes, so it should not outlive the tab. It is never sent anywhere but
  // this origin's own /api/asicminer routes.
  function token() {
    var t = sessionStorage.getItem('sym.asic.token');
    if (!t) {
      t = window.prompt('Operator token (SYMONEURAL_ASIC_TOKEN)');
      if (t) sessionStorage.setItem('sym.asic.token', t);
    }
    return t || '';
  }
  function api(path, body) {
    return fetch(path, {
      method: body ? 'POST' : 'GET',
      headers: {'Content-Type': 'application/json', 'X-Symoneural-Token': token(),
                /* And the name it replaced. site/ and the API deploy separately, so this
                   file can be newer than the server reading it; the server reads both too,
                   for the reverse. Remove once the deployed API reads the new name. */
                'X-Sym-Token': token()},
      body: body ? JSON.stringify(body) : undefined
    }).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (j) {
        if (r.status === 401) sessionStorage.removeItem('sym.asic.token');
        return {ok: r.ok, status: r.status, j: j};
      });
    });
  }
  function say(t) { note.textContent = t; }
  function fail(res, what) {
    say(what + ' failed (' + res.status + '): '
        + (res.j.detail || res.j.error || 'no reason given'));
  }

  function show(n) {
    for (var i = 1; i <= 3; i++) {
      var pane = document.getElementById('mn-p' + i);
      if (pane) pane.classList.toggle('on', i === n);
    }
    document.querySelectorAll('.mn-steps li').forEach(function (li) {
      li.classList.toggle('on', Number(li.dataset.step) <= n);
    });
  }

  document.querySelectorAll('[data-src]').forEach(function (b) {
    b.addEventListener('click', function () {
      state.src = b.dataset.src;
      if (state.src === 'scan') { runScan(); return; }
      say(''); show(2);
    });
  });

  function runScan() {
    var cidr = window.prompt('Private range to sweep', '192.168.1.0/24');
    if (!cidr) return;
    say('scanning ' + cidr + ' …');
    api('/api/asicminer/scan', {cidr: cidr}).then(function (res) {
      if (!res.ok) return fail(res, 'scan');
      var d = res.j;
      if (d.error) { say('scan refused: ' + d.error); return; }
      var found = (d.rigs || []).filter(function (r) { return r.identified; });
      say('swept ' + d.swept + ' addresses, ' + d.responded + ' answered on port '
          + d.port + ', ' + found.length + ' identified'
          + (found.length ? ': ' + found.map(function (r) {
               return r.host + ' ' + (r.vendor || '?') + ' ' + (r.model || ''); }).join(', ')
             : '. Nothing on this network is a rig.'));
    });
  }

  document.querySelectorAll('[data-vendor]').forEach(function (b) {
    b.addEventListener('click', function () {
      state.vendor = b.dataset.vendor;
      loadPackages();
      show(3);
    });
  });
  document.querySelectorAll('.mn-back').forEach(function (b) {
    b.addEventListener('click', function () { show(Number(b.dataset.to)); });
  });

  // The model list is READ OFF DISK, not hardcoded. A list written into this page goes
  // stale the moment firmware is added or removed, and would claim images that are not
  // there -- the same failure as a status light that is not wired to anything.
  function loadPackages() {
    var host = document.getElementById('mn-models');
    host.textContent = 'reading firmware on this machine…';
    api('/api/asicminer/firmware').then(function (res) {
      if (!res.ok) { host.textContent = ''; return fail(res, 'firmware listing'); }
      state.packages = res.j.packages || [];
      renderModels();
    });
  }

  function renderModels() {
    var host = document.getElementById('mn-models');
    var list = (state.packages || []).filter(function (p) {
      return p.vendor === state.vendor;
    });
    host.innerHTML = '';
    if (!list.length) {
      host.textContent = 'No ' + state.vendor + ' firmware is present on this machine.';
      return;
    }
    list.forEach(function (m) {
      var bootable = (m.kind === 'browser');
      var el = document.createElement('button');
      el.type = 'button';
      el.className = 'mn-model ' + (bootable ? 'ok' : 'part');
      var d = document.createElement('i'); d.className = 'mn-dot ' + (bootable ? 'ok' : 'part');
      var b = document.createElement('b'); b.textContent = m.name;
      var sp = document.createElement('span');
      sp.textContent = (m.bytes / 1048576).toFixed(1) + ' MB · '
        + (bootable ? 'browser-upgrade package — bootable'
                    : 'SD recovery package — not bootable this way');
      el.appendChild(d); el.appendChild(b); el.appendChild(sp);
      el.addEventListener('click', function () {
        state.pkg = m;
        host.querySelectorAll('.mn-model').forEach(function (x) { x.classList.remove('sel'); });
        el.classList.add('sel');
        if (!bootable) { say(m.name + ' is an SD recovery package; the emulator takes a '
                             + 'browser-upgrade .tar.gz.'); return; }
        startEmulator(m);
      });
      host.appendChild(el);
    });
  }

  function startEmulator(m) {
    say('starting ' + m.name + ' …');
    api('/api/asicminer/emulator', {action: 'start', package: m.id}).then(function (res) {
      if (!res.ok) return fail(res, 'emulator');
      if (!res.j.ok) { say('emulator: ' + res.j.error); return; }
      say('booted ' + res.j.package + ' (pid ' + res.j.pid + '). ' + res.j.note
          + '  Guest web UI: ' + res.j.web);
      refreshEmu();
    });
  }

  function refreshEmu() {
    api('/api/asicminer/emulator', {action: 'status'}).then(function (res) {
      if (res.ok && res.j.running) {
        stEl.textContent = 'emulating ' + (res.j.package || '');
      }
    });
  }

  fetch('/api/status', {headers: {'Accept': 'application/json'}})
    .then(function (r) { return r.ok ? r.json() : null; })
    .then(function (s) {
      // The ASIC half is a sub-unit of the merged `miner` row, so look in both places --
      // top level first, because the site goes live before the API restarts and until then
      // this id is still a rack unit of its own. Same helper shape as the GPU card below;
      // deliberately duplicated rather than shared, because these two IIFEs share no state
      // and one of them holds a token that must never reach the other's routes.
      var us = (s && s.units) || [], u = null, i, j, sub;
      for (i = 0; i < us.length && !u; i++) { if (us[i].id === 'asicminer') u = us[i]; }
      for (i = 0; i < us.length && !u; i++) {
        sub = us[i].sub || [];
        for (j = 0; j < sub.length && !u; j++) { if (sub[j].id === 'asicminer') u = sub[j]; }
      }
      // `offline` rather than a fifth state literal like "not present": the four states are
      // what every other surface reports, and a word only this card uses reads as a broken
      // probe.
      stEl.textContent = u ? u.state : 'offline';
      if (u && u.state === 'offline') say(u.detail);
      if (!u) say('this server did not report an ASIC unit at all — the surface is built '
                + 'but not registered, which is a server-side fault rather than a missing rig');
    })
    .catch(function () { stEl.textContent = 'unreachable'; });
})();

// ---------------------------------------------------------------- Miner GPU (Ravencoin)
// A SEPARATE surface from the ASIC panel above: its own token, its own route prefix, its
// own rack unit. Deliberately a second IIFE sharing nothing with the first -- one `token()`
// serving both would send the ASIC token to a route that takes the GPU away from chat.
(function () {
  'use strict';
  var $ = function (id) { return document.getElementById(id); };
  var stEl = $('mgstate'), dot = $('mgdot'), note = $('mgnote'), tokEl = $('mg-token');
  var startB = $('mg-start'), stopB = $('mg-stop'), readB = $('mg-read');
  if (!stEl) return;
  var TK = 'sym.miner.token';        // NOT sym.asic.token. See the comment above.
  var armed = 0;                     // start is two-step; see arm() below.

  try { if (sessionStorage.getItem(TK)) tokEl.value = sessionStorage.getItem(TK); }
  catch (e) { /* private mode: the field still works, it just will not persist */ }

  function token() { return (tokEl.value || '').trim(); }
  function say(t) { note.textContent = t; }

  function api(path, body) {
    return fetch(path, {
      method: body ? 'POST' : 'GET',
      headers: {'Content-Type': 'application/json', 'X-Symoneural-Token': token(),
                /* And the name it replaced. site/ and the API deploy separately, so this
                   file can be newer than the server reading it; the server reads both too,
                   for the reverse. Remove once the deployed API reads the new name. */
                'X-Sym-Token': token()},
      body: body ? JSON.stringify(body) : undefined
    }).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (j) {
        if (r.status === 401) { try { sessionStorage.removeItem(TK); } catch (e) {} }
        return {ok: r.ok, status: r.status, j: j};
      });
    });
  }

  // The two mining halves are ONE rack row with a `sub` array under it, so a lookup by id
  // has to try both places. Top level FIRST and on purpose: the static site deploys before
  // the API restarts, so for a while the browser will be talking to an API that still
  // publishes `gpuminer` as its own unit. Both shapes read correctly, and neither invents
  // a state when the id is genuinely absent.
  function unitById(s, id) {
    var us = (s && s.units) || [], i, j, sub;
    for (i = 0; i < us.length; i++) { if (us[i].id === id) return us[i]; }
    for (i = 0; i < us.length; i++) {
      sub = us[i].sub || [];
      for (j = 0; j < sub.length; j++) { if (sub[j].id === id) return sub[j]; }
    }
    return null;
  }

  // The public half. GET /api/status needs no token and carries the same (state, detail)
  // pair the rack renders, so this card and the home page read from one source.
  function paint(s) {
    var u = unitById(s, 'gpuminer');
    if (!u) { stEl.textContent = 'not present'; return; }
    stEl.textContent = u.state;
    // A sub-unit carries no slot of its own -- the slot belongs to the merged row.
    $('mg-unit').textContent = u.id + ' \\u2014 ' + u.state + (u.slot ? ' \\u00b7 ' + u.slot : '');
    $('mg-detail').textContent = u.detail || '';
    // Not decorative: green only when the surface is actually usable, amber while it holds
    // or waits for the card, grey when it is offline. Straight off unit_state().
    dot.className = (u.state === 'busy' || u.state === 'queued') ? 'busy'
                  : (u.state === 'ready' ? 'on' : '');
  }

  // console.js already holds a websocket to /api/ws and falls back to polling, and it stops
  // both while the tab is hidden -- on purpose, because this hits a real GPU on somebody's
  // desk. So this card listens to what that file already received instead of opening a
  // second poller that would quietly break that promise.
  document.addEventListener('sym:status', function (e) { paint(e.detail); });

  // One bootstrap read, so the card is populated before the socket's first frame arrives --
  // and so it still fills in if console.js is not on the page at all.
  function poll() {
    fetch('/api/status', {headers: {'Accept': 'application/json'}})
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(paint)
      .catch(function () { stEl.textContent = 'unreachable'; });
  }

  function human(s) {
    if (s === null || s === undefined) return null;
    if (s < 60) return s + 's';
    if (s < 3600) return Math.floor(s / 60) + 'm ' + (s % 60) + 's';
    return Math.floor(s / 3600) + 'h ' + Math.floor((s % 3600) / 60) + 'm';
  }

  // The gated half. Values only -- never the miner command and never the pool URL, which
  // carries the operator's wallet address. `pool` is reported as a yes/no, not a string.
  function paintTelemetry(d) {
    var hr = d.hashrate_mh_s;
    $('mg-hr').textContent = (hr === null || hr === undefined)
      ? (d.running ? 'running, nothing reported yet' : 'not running \\u2014 no reading')
      : hr + ' MH/s \\u00b7 measured, ' + (d.hashrate_source || 'reported by the miner')
        + (d.hashrate_age_s !== null && d.hashrate_age_s !== undefined
           ? ' (' + d.hashrate_age_s + 's ago)' : '');
    $('mg-pool').textContent = d.benchmark
      ? 'no \\u2014 benchmark configuration, so it measures the card and earns nothing'
      : (d.pool ? 'yes \\u2014 a pool is configured' : 'unknown');
    $('mg-lock').textContent = d.holds_gpu_lock ? 'yes \\u2014 other GPU surfaces are queued'
      : ('no' + (d.lock_holder ? ' \\u2014 held by \\u2018' + d.lock_holder + '\\u2019' : ''));
    $('mg-up').textContent = d.running ? (human(d.uptime_s) || 'just started')
                                       : 'not running';
  }

  function read(quiet) {
    if (!token()) { if (!quiet) say('An operator token is required to read telemetry or '
                                    + 'to start and stop the miner.'); return; }
    api('/api/gpuminer/status').then(function (res) {
      if (!res.ok) {
        if (!quiet) say('telemetry refused (' + res.status + '): '
                        + (res.j.detail || 'no reason given'));
        return;
      }
      try { sessionStorage.setItem(TK, token()); } catch (e) {}
      paintTelemetry(res.j);
      poll();
    });
  }

  // Start is two clicks, and the second one is labelled with what it does. An inline
  // re-label rather than window.confirm(): a modal dialog blocks every subsequent event in
  // the page until it is dismissed, which breaks automation and keyboard users both.
  function arm() {
    armed = Date.now();
    startB.textContent = 'Confirm \\u2014 take the card';
    startB.classList.add('warn');
    say('Starting the miner will hold the RTX 5070 Ti until it is stopped, and chat, image '
        + 'and remix will fail while it does. Click again to confirm.');
    window.setTimeout(function () {
      if (!armed) return;
      armed = 0;
      startB.textContent = 'Start mining';
      startB.classList.remove('warn');
    }, 8000);
  }

  startB.addEventListener('click', function () {
    if (!token()) { say('An operator token is required to start the miner.'); return; }
    if (!armed) { arm(); return; }
    armed = 0;
    startB.textContent = 'Start mining';
    startB.classList.remove('warn');
    say('starting the miner \\u2026');
    api('/api/gpuminer/control', {action: 'start'}).then(function (res) {
      if (!res.ok) { say('start refused (' + res.status + '): '
                         + (res.j.detail || 'no reason given')); return; }
      if (!res.j.ok) { say('the miner did not start: ' + (res.j.error || 'no reason given'));
                       poll(); return; }
      try { sessionStorage.setItem(TK, token()); } catch (e) {}
      say('started, pid ' + res.j.pid + ' \\u2014 ' + res.j.note);
      read(true);
    });
  });

  stopB.addEventListener('click', function () {
    if (!token()) { say('An operator token is required to stop the miner.'); return; }
    say('stopping \\u2026');
    api('/api/gpuminer/control', {action: 'stop'}).then(function (res) {
      if (!res.ok) { say('stop refused (' + res.status + '): '
                         + (res.j.detail || 'no reason given')); return; }
      say(res.j.stopped ? ('stopped pid ' + res.j.stopped + '; the governor releases the '
                           + 'card as the process group exits')
                        : ('nothing to stop \\u2014 ' + (res.j.note || 'it was not running')));
      read(true);
    });
  });

  readB.addEventListener('click', function () { read(false); });

  poll();
  read(true);                        // silent: no token is the normal case for a visitor
})();
</script>"""


# ---------------------------------------------------------------- gateway (TRON)
# No fee figures anywhere on this page, and that is not an oversight. Prices are quoted,
# not published, and a licensing surface is the worst possible place to break that rule.
GATEWAY_BODY = """    <div class="pgwrap">
      <div class="stage">
        <div class="head" id="gwhead"><s></s>SyMoNeuRaL Gateway
          <span class="grow" id="gwstate">reading&hellip;</span></div>
        <div class="body" id="gwbody">
          <p class="gw-note" id="gwdetail">Reading the surface state from
            <code>/api/status</code>&hellip;</p>
          <h3>How a licence would clear</h3>
          <ol class="gw-steps">
            <li><b>Contract (on-chain).</b> A licensing contract on the TRON Virtual
              Machine, denominated in USDT (TRC-20) rather than a native token.</li>
            <li><b>Daemon (off-chain).</b> Runs on the operator&rsquo;s own machine. It
              hashes the build logs into a reviewable tree and <b>pauses for a human to
              approve the configuration</b> before anything is broadcast. No blind script
              touches a rig.</li>
            <li><b>Energy.</b> TRON meters execution as Bandwidth and Energy rather than a
              gas auction. Renting Energy moves the execution cost off the end user.</li>
            <li><b>Settlement.</b> The daemon broadcasts the validation state and the
              payment. Once DPoS confirms it, the settlement is read back off the chain and
              checked field by field &mdash; payer, token, amount, workspace &mdash; and a
              short-lived entitlement is issued for the workspace it covers.</li>
          </ol>
          <p class="gw-note">One thing this is not: <b>a copy-protection scheme.</b> A
            blockchain is public, so a key published to it is published to everyone, and any
            arrangement that actually withholds one puts a server we run in the loop &mdash;
            which makes that server the authority and the chain a payment rail. So we call it
            a payment rail. Settlement is final, auditable and needs no card processor; that
            is the whole of the claim, and it is worth having. The encryption at rest is
            real and is not load-bearing against a determined licensee.</p>
        </div>
      </div>

      <aside class="side">
        <div class="callout">
          <h3>Every figure here is someone else&rsquo;s</h3>
          <p><b>~3 second confirmation</b> and <b>27 Super Representatives</b> are
            <b>vendor</b> figures &mdash; published parameters of the TRON network, not
            timings taken on this machine. Block times are a target, not a guarantee.</p>
          <p>&ldquo;Effectively zero fee&rdquo; is <b>projected</b>. Energy rental does not
            make execution free; it moves the cost from the end user to whoever rents the
            Energy. Calling that zero would describe an accounting choice as a physical
            property.</p>
          <p><b>What is measured here comes from the chain reader</b> &mdash; head block,
            whether a contract exists at the configured address, and how long the node took
            to answer. It runs off the request path and its age is printed with it, because
            &ldquo;real, and 40 seconds old&rdquo; is a different claim from &ldquo;real
            right now&rdquo;. When the surface is switched off there is no reading to show,
            and the status line says that rather than showing a stale one.</p>
        </div>
        <div class="callout">
          <h3>Pricing</h3>
          <p>Licence fees are quoted, not published &mdash; the same answer this site gives
            for hardware, and for the same reason. Ask
            <a href="mailto:symonsayadmin@symoneural.com">symonsayadmin@symoneural.com</a>.</p>
        </div>
        <div class="callout">
          <h3>What is, and is not, on this box</h3>
          <p>There is <b>no wallet, no private key and no signing code</b> in the process
            serving this page. Reading a public chain needs none of them: the calls this box
            makes are unauthenticated, and it cannot build, sign or broadcast a transaction
            &mdash; its own test suite asserts that.</p>
          <p>The licensing logic is split along the same line. <b>Checking</b> a licence needs
            only public information, so it runs here: reading the settlement off the chain,
            confirming the payer, the token, the amount and the workspace all match, and
            verifying an entitlement against a public key. <b>Issuing</b> one needs a private
            key, so it does not run here and cannot. A break-in on this box could read
            licences and could not mint one.</p>
          <p>Signing lives on the operator&rsquo;s own machine. Whether a contract is deployed,
            and what is at that address, is <b>not claimed on this page</b> &mdash; it is read
            from the chain and reported in the status line above, so this page cannot come to
            disagree with the machine.</p>
        </div>
      </aside>
    </div>
"""

GATEWAY_JS = """<script>
(function () {
  'use strict';
  var st = document.getElementById('gwstate'), d = document.getElementById('gwdetail');
  fetch('/api/status', {headers: {'Accept': 'application/json'}})
    .then(function (r) { return r.ok ? r.json() : null; })
    .then(function (s) {
      // Searched in `sub` as well as in `units`, and the order matters less than the fact
      // that BOTH are searched. Gateway was a top-level rack unit until 2026-08-22, when it
      // was folded into the Miner row as a third `sub` -- *"gateway is a miner app so it
      // can merge into miner"*. A lookup that reads only `units` would have gone on working
      // in every test that stubs the payload and reported 'not present' to every real
      // visitor, which is the failure this page exists to not have: it renders the API's
      // own words about a licensing surface, so being wrong here is worse than being blank.
      var rows = (s && s.units) || [];
      var all = rows.concat.apply(rows, rows.map(function (x) { return x.sub || []; }));
      var u = all.filter(function (x) { return x.id === 'gateway'; })[0];
      if (!u) { st.textContent = 'not present'; d.textContent =
        'The gateway surface is not present in this API build.'; return; }
      st.textContent = u.state;
      d.textContent = u.detail;   // the API's own words, not a rewrite of them
    })
    .catch(function () { st.textContent = 'unreachable';
      d.textContent = 'Could not reach /api/status.'; });
})();
</script>"""


# ---------------------------------------------------------------- streamer (IPTV)
# The credentials never reach this box. They live in the visitor's localStorage and are
# sent per request; the backend registers them for the life of a stream session and scrubs
# them from every error path. Nothing is written to disk and nothing is logged.
#
# The browsing UI's CSS is emitted here rather than added to frontend/site/css/symoneural.css on
# purpose: the markup and the rules that lay it out are written in the same place and
# ship in the same commit, so they cannot drift apart. Every class is `tn-` prefixed AND
# scoped to `#tnbody`, because generic class names have collided across components five
# times in this stylesheet already (`.bar`, `.live`, `.card`, `#console .sub`, `.gart`).
STREAMER_BODY = """    <style>
    /* ---- Streamer browsing, 2026-08-17 -------------------------------------------
       Six top-level categories, a full-width subcategory grid, and a filter that
       answers locally before the model is asked. All selectors are scoped to
       #tnbody. Grepped against frontend/site/css/symoneural.css and frontend/site/css/rack-detail.css first:
       every class name below has zero prior definitions.

       There is no `text-overflow:ellipsis` anywhere in this block and there must
       never be one. A truncated group name is often the only thing distinguishing
       two identically named channels, so clipping it is data loss. Long names wrap. */

    /* ---- why a stream did not play -------------------------------------------
       The blank screen this replaces was a real defect, not a missing nicety.
       POST /tune answers 200 with state:"starting" when ffmpeg has not written a
       playlist within its deadline, and the page used to hand that not-yet-existent
       manifest straight to hls.js -- which failed its manifest load and left a black
       <video> with a line of library jargon underneath. The visitor could not tell
       "the provider says this channel is off air" from "our streamer is broken", and
       those need completely different responses.

       So: the server is asked why, and its sentence is what gets shown. The hls.js
       detail is kept too, folded, because it is the thing an engineer needs and
       dropping it would be data loss. No ellipsis here either -- a provider's
       message is often long and is exactly the part you must be able to read. */
    #tnbody .tn-fail{
      margin:10px 0 0; padding:13px 15px; border-radius:12px;
      border:1px solid rgba(255,171,61,.42); background:rgba(255,171,61,.07);
    }
    #tnbody .tn-fail h4{
      margin:0 0 5px; font:650 13.5px/1.35 inherit; color:var(--warn,#ffab3d);
    }
    #tnbody .tn-fail p{margin:0; font:14px/1.5 inherit; color:var(--fg); overflow-wrap:anywhere}
    #tnbody .tn-fail .tn-said{
      display:block; margin-top:7px; padding-left:11px;
      border-left:2px solid rgba(255,171,61,.42);
      color:var(--dim); font-style:italic; overflow-wrap:anywhere;
    }
    #tnbody .tn-fail details{margin-top:9px}
    #tnbody .tn-fail summary{cursor:pointer; color:var(--dim); font-size:12.6px}
    #tnbody .tn-fail code{
      display:block; margin-top:6px; font-size:12.4px; color:var(--dim);
      white-space:pre-wrap; overflow-wrap:anywhere;
    }

    /* ---- the floating guide prompt ------------------------------------------
       Fixed, bottom-right, above the fold on every viewport. `position:fixed` puts
       it outside the page flow deliberately: the alternative -- docking it to the
       grid -- means it scrolls away exactly when you are looking at the grid,
       which is the moment it exists for.

       Widths are clamped rather than fixed so the panel never causes a horizontal
       scrollbar at 390px, which is the constraining viewport for this page. No
       ellipsis anywhere: the `why` line is Guide's account of what it did to your
       question, and a truncated account is worse than none. */
    #tnbody .tn-fg{position:fixed; right:18px; bottom:18px; z-index:70;
      display:flex; flex-direction:column; align-items:flex-end; gap:9px;
      max-width:min(380px, calc(100vw - 36px));}
    #tnbody .tn-fgpill{
      display:inline-flex; align-items:center; gap:9px; cursor:pointer;
      padding:10px 17px; border-radius:999px; border:1px solid rgba(46,224,138,.42);
      background:var(--panel); color:var(--fg); font:650 12.9px/1 inherit;
      box-shadow:0 6px 22px rgba(0,0,0,.42);
    }
    #tnbody .tn-fgpill:hover{border-color:var(--accent)}
    #tnbody .tn-fgmark{
      display:inline-flex; align-items:center; justify-content:center;
      width:20px; height:20px; border-radius:50%; background:var(--accent);
      color:#07130d; font:800 11.5px/1 inherit;
    }
    #tnbody .tn-fgbody{
      width:min(380px, calc(100vw - 36px)); box-sizing:border-box;
      border:1px solid var(--line); border-radius:15px; background:var(--panel);
      padding:15px 16px; box-shadow:0 12px 40px rgba(0,0,0,.5);
    }
    #tnbody .tn-fghead{display:flex; align-items:center; gap:10px; margin-bottom:7px}
    #tnbody .tn-fghead b{font-size:13.6px}
    #tnbody .tn-fgx{
      margin-left:auto; background:none; border:0; color:var(--dim); cursor:pointer;
      font-size:18px; line-height:1; padding:0 2px;
    }
    #tnbody .tn-fgx:hover{color:var(--fg)}
    #tnbody .tn-fgctx{margin:0 0 9px; color:var(--dim); font-size:12.2px; line-height:1.5}

    /* The couple of questions. A <details> rather than a wizard: the panel has to stay
       inside one 390px screen, and somebody who already knows what to type should not have
       to walk past a form to reach the box they type it in. */
    #tnbody .tn-fgask{margin:0 0 10px; padding:9px 11px; border:1px solid var(--line);
      border-radius:11px; background:var(--panel2, #121513)}
    #tnbody .tn-fgask summary{cursor:pointer; color:var(--fg); font:600 12.5px/1.45 inherit}
    #tnbody .tn-fgask summary:hover{color:var(--accent)}
    #tnbody .tn-fgnote{margin:8px 0 0; color:var(--dim); font-size:11.9px; line-height:1.5}
    #tnbody .tn-fgnote code{font-size:11.4px; color:var(--fg)}
    #tnbody .tn-fglab{margin:11px 0 6px; color:var(--fg); font:600 12.2px/1.4 inherit}
    #tnbody .tn-fgfield{display:block; margin-top:9px; color:var(--fg);
      font:600 12.2px/1.4 inherit}
    #tnbody .tn-fgfield input{
      display:block; width:100%; box-sizing:border-box; margin-top:6px; padding:8px 10px;
      border-radius:9px; border:1px solid var(--line); background:var(--panel);
      color:var(--fg); font:13.2px/1.4 inherit;
    }
    #tnbody .tn-fgfield input:focus{outline:2px solid var(--accent); outline-offset:1px}
    #tnbody .tn-fgchips{display:flex; flex-wrap:wrap; gap:6px}
    #tnbody .tn-fgchip{
      display:inline-flex; align-items:center; gap:6px; cursor:pointer;
      padding:6px 11px; border:1px solid var(--line); border-radius:999px;
      color:var(--dim); font:600 12px/1 inherit;
    }
    #tnbody .tn-fgchip input{margin:0}
    #tnbody .tn-fgchip.on{border-color:var(--accent); color:var(--fg)}
    #tnbody .tn-fg textarea{
      width:100%; box-sizing:border-box; resize:vertical; padding:9px 11px;
      border-radius:9px; border:1px solid var(--line); background:var(--panel2, #121513);
      color:var(--fg); font:13.4px/1.45 inherit;
    }
    #tnbody .tn-fg textarea:focus{outline:2px solid var(--accent); outline-offset:1px}
    #tnbody .tn-fgrow{display:flex; flex-wrap:wrap; align-items:center; gap:10px; margin-top:10px}
    #tnbody .tn-fggo{
      background:var(--accent); color:#07130d; border:0; border-radius:999px;
      padding:8px 16px; font:650 12.6px/1 inherit; cursor:pointer;
    }
    #tnbody .tn-fggo:disabled{opacity:.5; cursor:default}
    #tnbody .tn-fgalt{
      background:none; border:1px solid var(--line); color:var(--dim);
      border-radius:999px; padding:8px 15px; font:600 12.4px/1 inherit; cursor:pointer;
    }
    #tnbody .tn-fgalt:hover{color:var(--fg)}
    #tnbody .tn-fgmodel{display:inline-flex; align-items:center; gap:6px;
      color:var(--dim); font-size:12.2px; cursor:pointer}
    #tnbody .tn-fgwhy{
      margin:11px 0 0; padding:9px 11px; border-radius:9px;
      border:1px solid var(--line); background:var(--panel2, #121513);
      color:var(--dim); font-size:12.3px; line-height:1.55; overflow-wrap:anywhere;
    }
    #tnbody .tn-fgsaved{margin:9px 0 0; color:var(--accent); font-size:12.2px}
    @media (max-width:520px){
      #tnbody .tn-fg{right:12px; bottom:12px; left:12px; max-width:none; align-items:stretch}
      #tnbody .tn-fgbody{width:auto}
      /* ...but NOT the collapsed pill. Stretching the container is right for the panel --
         it wants every pixel at this width -- and wrong for the pill, which needs its own
         label and nothing more. Measured at 390px it came out 366px wide, a bar across the
         whole bottom of the screen at z-index:70, and `elementFromPoint` at the centre of
         the two view tabs (#tnvguide, #tnvlist, x=49..169) returned the pill: a click aimed
         at either one hit the guide instead. `align-self` overrides the container's
         `align-items` for this one child, so the pill shrinks back to ~110px at the right
         and the tabs beside it are clickable again. */
      #tnbody .tn-fgpill{align-self:flex-end}
      /* Shrinking the pill is not enough on its own: the CONTAINER still spans left:12px to
         right:12px and is `position:fixed` at z-index:70, so it went on swallowing clicks
         across the whole width in the space beside the pill, where there is nothing to see
         at all. A transparent box that eats input is worse than a visible one, because
         nothing on screen explains why the tab underneath stopped responding. The container
         stops being a click target; its two real children take it back. */
      #tnbody .tn-fg{pointer-events:none}
      #tnbody .tn-fgpill, #tnbody .tn-fgbody{pointer-events:auto}
    }

    #tnbody .tn-cats{display:flex; flex-wrap:wrap; gap:8px; margin:2px 0 10px}
    #tnbody .tn-cat{
      display:inline-flex; align-items:center; gap:8px; cursor:pointer;
      padding:9px 15px; border:1px solid var(--line); border-radius:999px;
      background:var(--panel2); color:var(--dim); font:600 12.9px/1 inherit;
      transition:color .14s ease, border-color .14s ease, background .14s ease;
    }
    #tnbody .tn-cat:hover:not(:disabled){color:var(--fg)}
    #tnbody .tn-cat.on{color:var(--accent); border-color:rgba(46,224,138,.45); background:var(--panel)}
    #tnbody .tn-cat:disabled{opacity:.42; cursor:default}
    #tnbody .tn-cat:focus-visible{outline:2px solid var(--accent); outline-offset:2px}
    #tnbody .tn-cat i{
      font-style:normal; color:var(--faint);
      font:var(--t7)/1 ui-monospace,Menlo,Consolas,monospace;
    }
    #tnbody .tn-cat.on i{color:var(--accent)}
    /* The sentence under the chips carries the honesty: what the current category is
       actually sorted or selected by. It wraps -- it is an explanation, and a clipped
       explanation explains nothing. */
    #tnbody .tn-catwhy{
      margin:0 0 4px; color:var(--faint);
      font:11.5px/1.62 ui-monospace,Menlo,Consolas,monospace; overflow-wrap:break-word;
    }
    #tnbody .tn-catwhy:empty{display:none}

    /* ---- the subcategory grid: "literally take entire screen" -------------------
       Garrett asked for as many groups visible at once as possible. It sits inside
       .stage .body rather than as a third child of .pgwrap, because .pgwrap is
       `1fr 320px` from a stylesheet this generator does not own -- a third child
       would land in row 2 and gain nothing. The 1fr column is ~1400px at 1990px
       viewport, which auto-fill turns into 5-6 columns of real checkboxes. */
    #tnbody .tn-gpanel{
      margin:14px 0 0; border:1px solid var(--line); border-radius:12px;
      background:var(--panel2); overflow:hidden;
    }
    #tnbody .tn-gpanel[hidden]{display:none}
    #tnbody .tn-ghead{
      display:flex; flex-wrap:wrap; align-items:center; gap:8px;
      padding:10px 12px; border-bottom:1px solid var(--line);
    }
    #tnbody .tn-gtitle{
      display:inline-flex; align-items:center; gap:8px; cursor:pointer;
      background:none; border:0; padding:0; color:var(--fg);
      font:650 11px/1 ui-sans-serif,system-ui,sans-serif; letter-spacing:.13em;
      text-transform:uppercase;
    }
    #tnbody .tn-gtitle:hover{color:var(--accent)}
    #tnbody .tn-gtitle u{
      text-decoration:none; display:inline-block; width:12px; color:var(--faint);
      font:11px/1 ui-monospace,Menlo,Consolas,monospace;
    }
    #tnbody .tn-gn{
      color:var(--faint); letter-spacing:0; text-transform:none;
      font:11px/1.5 ui-monospace,Menlo,Consolas,monospace; overflow-wrap:break-word;
    }
    #tnbody .tn-gsearch{
      flex:1 1 200px; min-width:0; margin-left:auto; padding:7px 11px;
      background:var(--bg); color:var(--fg); border:1px solid var(--line);
      border-radius:8px; font:11.9px/1.4 inherit;
    }
    #tnbody .tn-gsearch:focus{outline:none; border-color:rgba(46,224,138,.5)}
    #tnbody .tn-gbtn{
      flex:0 0 auto; padding:7px 12px; cursor:pointer; border-radius:8px;
      border:1px solid var(--line); background:var(--panel); color:var(--dim);
      font:600 11.4px/1 inherit;
    }
    #tnbody .tn-gbtn:hover{color:var(--accent); border-color:rgba(46,224,138,.45)}
    #tnbody .tn-gbtn:focus-visible{outline:2px solid var(--accent); outline-offset:2px}
    /* Measured, not guessed: at a 1990px viewport the grid box is 1330px wide, and a
       200px track gives six columns. With a 60vh scroll box that is ~120 groups on
       screen at once, which is what "the most possible to see at one time" asked for.
       Wider tracks looked calmer and showed 80. */
    #tnbody .tn-gwrap{padding:9px 12px 12px; max-height:min(60vh,620px); overflow-y:auto}
    #tnbody .tn-gwrap[hidden]{display:none}
    #tnbody .tn-ggrid{
      display:grid; grid-template-columns:repeat(auto-fill,minmax(200px,1fr));
      gap:1px 16px; align-items:start;
    }
    #tnbody .tn-gcell{
      display:flex; align-items:flex-start; gap:8px; padding:3px 5px;
      border-radius:6px; cursor:pointer; color:var(--dim); font:11.9px/1.4 inherit;
    }
    #tnbody .tn-gcell:hover{background:var(--panel); color:var(--fg)}
    #tnbody .tn-gcell[hidden]{display:none}
    #tnbody .tn-gcell input{
      flex:0 0 auto; width:13px; height:13px; margin:2px 0 0; accent-color:var(--accent);
      cursor:pointer;
    }
    #tnbody .tn-gname{overflow-wrap:anywhere}
    #tnbody .tn-gcnt{
      margin-left:auto; padding-left:9px; flex:0 0 auto; color:var(--faint);
      font:var(--t7)/1.6 ui-monospace,Menlo,Consolas,monospace;
    }
    #tnbody .tn-gempty{
      margin:8px 3px 2px; color:var(--faint);
      font:11.5px/1.6 ui-monospace,Menlo,Consolas,monospace;
    }
    #tnbody .tn-gempty:empty{display:none}

    /* ---- the filter row and its state readout ---------------------------------
       The pill is a real state machine, not decoration: it says `not needed` when
       the local pass answered on its own, `thinking` only while a request is in
       flight, and `unavailable` when the model could not be reached -- which is
       the case the previous version could hit silently. */
    #tnbody .tn-model{
      display:inline-flex; align-items:center; gap:8px; margin:11px 10px 0 0;
      padding:6px 11px; border:1px solid var(--line); border-radius:999px;
      background:var(--panel2); color:var(--faint);
      font:11px/1 ui-monospace,Menlo,Consolas,monospace;
    }
    #tnbody .tn-model s{
      width:7px; height:7px; border-radius:50%; background:var(--line);
      text-decoration:none; display:block; flex:0 0 auto;
    }
    #tnbody .tn-model.tn-think s{background:var(--amber); animation:pulse 1.1s ease-in-out infinite}
    #tnbody .tn-model.tn-done s{background:var(--accent)}
    #tnbody .tn-model.tn-warn s{background:var(--amber)}

    /* ---- results ---------------------------------------------------------------
       At full width the channel list is a multi-column grid: it is a long list of
       short rows, so the room turns vertical scrolling into readable columns
       instead of longer lines. */
    #tnbody .tn-list{max-height:min(68vh,640px)}
    @media (min-width:1301px){
      #tnbody .tn-list{
        display:grid; grid-template-columns:repeat(auto-fill,minmax(330px,1fr));
        gap:0 24px; align-content:start;
      }
    }
    /* The base rule is `justify-content:space-between`, which with a star added as the
       first child parked it at the far left of a 440px column with a hole beside it.
       Measured in the render, not reasoned about: the star belongs against the name and
       the group is what gets pushed to the right edge. */
    /* `[hidden]` has to win over the `display:grid` above it. The UA rule for `hidden` is
       weaker than any author `display`, so without this the guide view would render with the
       full channel list still laid out underneath it. */
    #tnbody .tn-list[hidden]{display:none}
    #tnbody .tn-list li{gap:9px; align-items:center; justify-content:flex-start}
    #tnbody .tn-list b{margin-right:auto}
    #tnbody .tn-fav{
      flex:0 0 auto; cursor:pointer; background:none; border:0; padding:1px 3px;
      border-radius:6px; color:var(--faint); font:13.5px/1 inherit;
    }
    #tnbody .tn-fav:hover{color:var(--accent)}
    #tnbody .tn-fav.on{color:var(--accent)}
    #tnbody .tn-fav:focus-visible{outline:2px solid var(--accent); outline-offset:1px}
    #tnbody .tn-evi{
      flex:0 1 auto; text-align:right; color:var(--faint);
      font:11px/1.5 ui-monospace,Menlo,Consolas,monospace; overflow-wrap:anywhere;
    }
    #tnbody .tn-empty{
      margin:18px 0 0; padding:16px 18px; border:1px dashed var(--line);
      border-radius:11px; color:var(--dim); font-size:12.3px; line-height:1.65;
      overflow-wrap:break-word;
    }
    #tnbody .tn-empty[hidden]{display:none}
    #tnbody .tn-showmore{
      display:block; width:100%; margin:12px 0 0; padding:9px 12px; cursor:pointer;
      border:1px solid var(--line); border-radius:9px; background:var(--panel2);
      color:var(--dim); font:600 11.9px/1 inherit;
    }
    #tnbody .tn-showmore:hover{color:var(--accent); border-color:rgba(46,224,138,.45)}
    #tnbody .tn-showmore[hidden]{display:none}

    /* ---- the guide, 2026-08-17 -------------------------------------------------
       A real grid: time across, channels down, what is on in the cell. It replaces
       nothing -- the list is still there behind a toggle, because a list is the
       right shape for 31,888 films and a grid is the right shape for live TV.

       Every cell is drawn from `POST /api/streamer/epg`, which is the provider's own
       `get_short_epg`. A channel the provider publishes no guide for says so in
       words; there is no placeholder programme and no "No Information" filler,
       because a made-up cell in a grid is indistinguishable from a real one.

       The row is a positioned strip rather than a CSS grid of half-hour columns:
       programmes do not respect half hours (a 42-minute Walking Dead measured off
       a real panel), so column snapping would draw every one of them in the wrong
       place. Left and width are percentages of the visible window. */
    #tnbody .tn-guide{margin-top:14px}
    #tnbody .tn-guide[hidden]{display:none}
    #tnbody .tn-vtabs{display:flex; gap:7px; align-items:center; margin:12px 0 0; flex-wrap:wrap}
    #tnbody .tn-vtab{
      cursor:pointer; padding:6px 13px; border-radius:999px; border:1px solid var(--line);
      background:var(--panel2); color:var(--dim); font:650 11.9px/1 inherit;
    }
    #tnbody .tn-vtab.on{
      border-color:rgba(46,224,138,.5); color:var(--accent); background:rgba(46,224,138,.1);
    }
    #tnbody .tn-vmeta{color:var(--faint); font-size:11.4px; margin-left:auto}
    #tnbody .tn-ghead3{
      display:flex; gap:8px; align-items:center; flex-wrap:wrap; margin:0 0 9px;
    }
    #tnbody .tn-gwhen{color:var(--fg); font:650 12.4px/1.4 inherit}
    #tnbody .tn-gnav{
      cursor:pointer; padding:5px 11px; border-radius:8px; border:1px solid var(--line);
      background:var(--panel2); color:var(--dim); font:600 11.6px/1 inherit;
    }
    #tnbody .tn-gnav:hover{color:var(--accent); border-color:rgba(46,224,138,.45)}
    /* The row under the status line that offers full-width playback. `[hidden]` is honoured
       explicitly because the rule beside it sets `display`, and an author `display` on a
       class beats the UA stylesheet's `[hidden]{display:none}` -- which is how a hidden
       front-page section shipped occupying 425px of a 1440px window on this site. */
    #tnbody .tn-prow{display:flex; gap:10px; align-items:center; flex-wrap:wrap; margin:9px 0 0}
    #tnbody .tn-prow[hidden]{display:none}
    #tnbody .tn-watchwhy{font:500 11.4px/1.45 inherit; color:var(--faint)}
    #tnbody .tn-gscroll{
      position:relative; overflow:auto; max-height:min(60vh,560px);
      border:1px solid var(--line); border-radius:12px; background:var(--panel);
    }
    #tnbody .tn-gruler{
      position:sticky; top:0; z-index:3; display:flex; background:var(--panel2);
      border-bottom:1px solid var(--line);
    }
    #tnbody .tn-gcorner{
      flex:0 0 186px; padding:7px 10px; color:var(--faint); font:650 var(--t7)/1.3 inherit;
      letter-spacing:.11em; text-transform:uppercase; border-right:1px solid var(--line);
      position:sticky; left:0; background:var(--panel2); z-index:4;
    }
    #tnbody .tn-gticks{position:relative; flex:1 1 auto; min-width:520px; height:30px}
    #tnbody .tn-gtick{
      position:absolute; top:0; bottom:0; padding-left:6px; color:var(--faint);
      font:600 var(--t7)/30px inherit; border-left:1px solid var(--line); white-space:nowrap;
    }
    #tnbody .tn-grow{display:flex; border-bottom:1px solid var(--line-soft,rgba(255,255,255,.06))}
    #tnbody .tn-grow:last-child{border-bottom:0}
    #tnbody .tn-gchan{
      flex:0 0 186px; padding:8px 10px; border-right:1px solid var(--line);
      position:sticky; left:0; background:var(--panel); z-index:2; cursor:pointer;
      display:flex; flex-direction:column; gap:3px; text-align:left; color:var(--fg);
      font:600 11.9px/1.35 inherit; overflow-wrap:break-word;
    }
    #tnbody .tn-gchan:hover{background:var(--panel2)}
    #tnbody .tn-gchan em{font-style:normal; color:var(--faint); font-size:var(--t7); font-weight:500}
    #tnbody .tn-gstrip{position:relative; flex:1 1 auto; min-width:520px; min-height:46px}
    #tnbody .tn-gprog{
      position:absolute; top:4px; bottom:4px; overflow:hidden; cursor:pointer;
      border:1px solid var(--line); border-radius:8px; background:var(--panel2);
      padding:5px 8px; text-align:left; color:var(--dim); font:600 11.4px/1.3 inherit;
    }
    #tnbody .tn-gprog:hover{border-color:rgba(46,224,138,.5); color:var(--fg)}
    #tnbody .tn-gprog.on{
      border-color:rgba(46,224,138,.55); background:rgba(46,224,138,.12); color:var(--fg);
    }
    #tnbody .tn-gprog u{
      display:block; text-decoration:none; color:var(--faint); font-size:var(--t7); font-weight:500;
    }
    #tnbody .tn-gnone{
      position:absolute; inset:4px 6px; display:flex; align-items:center;
      color:var(--faint); font:500 11.1px/1.4 inherit;
    }
    #tnbody .tn-gline{
      position:absolute; top:0; bottom:0; width:2px; background:var(--accent);
      opacity:.75; pointer-events:none; z-index:1;
    }
    #tnbody .tn-gnote{margin:9px 0 0; color:var(--faint); font-size:11.5px; line-height:1.6}

    /* ---- what the player is actually doing ------------------------------------
       Every figure in here is read from hls.js or from the session document; there
       is not one number on this panel that the page made up. `-` means the player
       has not reported it yet, which is a reading too. */
    #tnbody .tn-stats{margin:10px 0 0; font-size:11.9px}
    #tnbody .tn-stats > summary{cursor:pointer; color:var(--dim); font-weight:600}
    #tnbody .tn-stats > summary:hover{color:var(--accent)}
    #tnbody .tn-sgrid{
      display:grid; grid-template-columns:repeat(auto-fit,minmax(168px,1fr)); gap:8px;
      margin:10px 0 0;
    }
    #tnbody .tn-scell{
      border:1px solid var(--line); border-radius:9px; background:var(--panel2);
      padding:8px 10px;
    }
    #tnbody .tn-scell b{
      display:block; color:var(--faint); font:650 var(--t7)/1.3 inherit;
      letter-spacing:.11em; text-transform:uppercase;
    }
    #tnbody .tn-scell span{
      display:block; margin-top:4px; color:var(--fg); font:600 12.6px/1.35 inherit;
      font-variant-numeric:tabular-nums; overflow-wrap:break-word;
    }
    #tnbody .tn-srow{display:flex; gap:9px; align-items:center; flex-wrap:wrap; margin:10px 0 0}
    #tnbody .tn-srow label{color:var(--faint); font-size:11.2px}
    #tnbody .tn-srow select{
      background:var(--panel2); color:var(--fg); border:1px solid var(--line);
      border-radius:8px; padding:5px 9px; font:600 11.4px/1 inherit;
    }
    </style>

    <div class="pgwrap">
      <div class="stage">
        <div class="head" id="tnhead"><s></s>SyMoNeuRaL Streamer
          <span class="grow" id="tnstate">idle</span></div>
        <div class="body" id="tnbody">

          <form class="tn-load" id="tnform">
            <div class="tn-tabs">
              <button type="button" class="tn-tab on" data-mode="m3u">M3U playlist</button>
              <button type="button" class="tn-tab" data-mode="xtream">Xtream Codes</button>
            </div>
            <div class="tn-fields" id="tn-m3u">
              <label for="tn-url">Playlist URL</label>
              <input id="tn-url" type="url" placeholder="https://example.com/playlist.m3u"
                     autocomplete="off" spellcheck="false">
            </div>
            <div class="tn-fields" id="tn-xtream" hidden>
              <label for="tn-host">Server</label>
              <input id="tn-host" type="url" placeholder="http://example.com:8080"
                     autocomplete="off" spellcheck="false">
              <label for="tn-user">Username</label>
              <input id="tn-user" type="text" autocomplete="off" spellcheck="false">
              <label for="tn-pass">Password</label>
              <input id="tn-pass" type="password" autocomplete="off">
            </div>
            <button class="cta" id="tn-go" type="submit">Load channels</button>
          </form>

          <!-- player: hidden until something is tuned, because an empty <video> with
               controls is a piece of furniture that does nothing.
               #tnvideo is load-bearing beyond playback: symoneural.css widens this page
               to 1800px through `body:has(#tnvideo) .wrap`. Rename it and the page
               silently reverts to the 1120px prose measure. -->
          <div class="tn-player" id="tnplayer" hidden>
            <video id="tnvideo" controls playsinline></video>
            <p class="tn-now" id="tnnow"></p>

            <!-- Full-width playback on its own page, /streamer-watch.html. The handoff is a
                 localStorage entry plus a navigation and NOTHING is put in the URL: a stream
                 URL carries the visitor's own provider credentials and uvicorn logs a request
                 line. It carries the live session id too, so the other page rejoins this
                 stream instead of closing it and asking the provider again. -->
            <div class="tn-prow" id="tnprow" hidden>
              <button type="button" class="tn-gnav" id="tnwatch">Watch full width, with the
                guide over the picture &rarr;</button>
              <span class="tn-watchwhy" id="tnwatchwhy"></span>
            </div>
            <div class="tn-fail" id="tnfail" hidden>
              <h4 id="tnfailh"></h4>
              <p id="tnfailp"></p>
              <details id="tnfaild" hidden>
                <summary>Technical detail</summary>
                <code id="tnfailc"></code>
              </details>
            </div>

            <!-- Options, settings and statistics. Every figure is a reading taken from
                 hls.js or from the session document this box publishes -- resolution and
                 bitrate from the chosen level, buffer from the video element's own
                 buffered ranges, dropped frames from getVideoPlaybackQuality(), throughput
                 from hls.js's bandwidth estimate. Nothing on this panel is computed from a
                 guess, and a figure the player has not reported yet reads as `-`. -->
            <details class="tn-stats" id="tnstats" hidden>
              <summary>Playback options, settings and statistics</summary>
              <div class="tn-sgrid">
                <div class="tn-scell"><b>Resolution</b><span id="ps-res">-</span></div>
                <div class="tn-scell"><b>Level bitrate</b><span id="ps-rate">-</span></div>
                <div class="tn-scell"><b>Measured throughput</b><span id="ps-tp">-</span></div>
                <div class="tn-scell"><b>Buffer ahead</b><span id="ps-buf">-</span></div>
                <div class="tn-scell"><b>Dropped frames</b><span id="ps-drop">-</span></div>
                <div class="tn-scell"><b>Frames decoded</b><span id="ps-dec">-</span></div>
                <div class="tn-scell"><b>Segment length</b><span id="ps-seg">-</span></div>
                <div class="tn-scell"><b>Segments held</b><span id="ps-segn">-</span></div>
                <div class="tn-scell"><b>From the provider</b><span id="ps-in">-</span></div>
                <div class="tn-scell"><b>Path</b><span id="ps-mode">-</span></div>
                <div class="tn-scell"><b>Session age</b><span id="ps-age">-</span></div>
                <div class="tn-scell"><b>Player</b><span id="ps-eng">-</span></div>
              </div>
              <div class="tn-srow">
                <label for="ps-level">Quality</label>
                <select id="ps-level"><option value="-1">auto</option></select>
                <label for="ps-audio">Audio</label>
                <select id="ps-audio"><option value="-1">as sent</option></select>
                <button type="button" class="tn-gnav" id="ps-pip">Picture in picture</button>
                <button type="button" class="tn-gnav" id="ps-full">Full screen</button>
              </div>
              <p class="tn-gnote" id="ps-why"></p>
            </details>
          </div>

          <p class="tn-note" id="tnnote">Your playlist is yours. It is held in this
            browser&rsquo;s localStorage, sent per request, and never stored on this
            machine. <b>Favourites are the same</b> &mdash; they are a list in this
            browser and are never sent anywhere.</p>

          <!-- browse: six categories, then a subcategory grid, then the filter -->
          <div class="tn-browse" id="tnbrowse" hidden>
            <div class="tn-cats" id="tncats" role="group" aria-label="Categories"></div>
            <p class="tn-catwhy" id="tncatwhy"></p>

            <div class="tn-ask">
              <input id="tnask" type="text" autocomplete="off"
                     placeholder="Ask for what you want &mdash; &ldquo;90s action movies&rdquo;, &ldquo;motorsport&rdquo;">
              <button type="button" class="tn-askgo" id="tnaskgo">Filter</button>
              <button type="button" class="tn-askclear" id="tnaskclear" hidden>clear</button>
            </div>
            <p class="tn-model" id="tnmodel"><s></s><span id="tnmodeltxt">model: idle</span></p>
            <p class="tn-askwhy" id="tnaskwhy"></p>

            <div class="tn-gpanel" id="tngpanel" hidden>
              <div class="tn-ghead">
                <button type="button" class="tn-gtitle" id="tngtoggle"
                        aria-expanded="true" aria-controls="tngwrap"><u>&minus;</u>Subcategories</button>
                <span class="tn-gn" id="tngcount"></span>
                <input id="tngsearch" class="tn-gsearch" type="search" autocomplete="off"
                       placeholder="find a subcategory">
                <button type="button" class="tn-gbtn" id="tngall">Select all</button>
                <button type="button" class="tn-gbtn" id="tngnone">None</button>
                <button type="button" class="tn-gbtn" id="tnginv">Invert</button>
              </div>
              <div class="tn-gwrap" id="tngwrap">
                <div class="tn-ggrid" id="tngrid" role="group" aria-label="Subcategories"></div>
                <p class="tn-gempty" id="tngempty"></p>
              </div>
            </div>
          </div>

          <p class="tn-empty" id="tnempty" hidden></p>

          <!-- Guide or list. Both views read the same filtered set, so a subcategory
               tick or a Guide-AI filter narrows them together; only the shape changes. -->
          <div class="tn-vtabs" id="tnviews" hidden>
            <button type="button" class="tn-vtab" id="tnvguide" aria-pressed="false">Guide</button>
            <button type="button" class="tn-vtab on" id="tnvlist" aria-pressed="true">List</button>
            <span class="tn-vmeta" id="tnvmeta"></span>
          </div>

          <div class="tn-guide" id="tnguide" hidden>
            <div class="tn-ghead3">
              <button type="button" class="tn-gnav" id="tngback">&#8592; 90 min</button>
              <button type="button" class="tn-gnav" id="tngnow">now</button>
              <button type="button" class="tn-gnav" id="tngfwd">90 min &#8594;</button>
              <span class="tn-gwhen" id="tngwhen"></span>
              <button type="button" class="tn-gnav" id="tngpage">next 30 channels</button>
            </div>
            <div class="tn-gscroll" id="tngscroll">
              <div class="tn-gruler">
                <div class="tn-gcorner">Channel</div>
                <div class="tn-gticks" id="tngticks"></div>
              </div>
              <div id="tngrows"></div>
            </div>
            <p class="tn-gnote" id="tngnote"></p>
          </div>

          <ul class="tn-list" id="tnlist"></ul>
          <button type="button" class="tn-showmore" id="tnmore" hidden></button>

          <!-- The floating guide prompt. It follows you down the page because setting up a
               guide means looking at the subcategory grid and talking about it at the same
               time, and a prompt that scrolls away turns that into two operations.

               It is not a chat window. It sends ONE question plus the subcategories you
               have ticked to SyMoNeuRaL Guide, and what comes back re-ticks the grid --
               so the outcome of the conversation is the guide itself, not a transcript
               about it. Collapsed by default: an open panel over the player would be the
               thing everyone hates about floating widgets. -->
          <div class="tn-fg" id="tnfg" hidden>
            <button type="button" class="tn-fgpill" id="tnfgpill" aria-expanded="false"
                    aria-controls="tnfgbody">
              <span class="tn-fgmark" aria-hidden="true">G</span>
              <span id="tnfgcount">Guide</span>
            </button>
            <div class="tn-fgbody" id="tnfgbody" hidden>
              <div class="tn-fghead">
                <b>Set up your guide</b>
                <button type="button" class="tn-fgx" id="tnfgx" aria-label="Close">&times;</button>
              </div>
              <p class="tn-fgctx" id="tnfgctx"></p>
              <!-- The couple of questions, and the reason they are QUESTIONS. "smart based
                   off location" cannot honestly become an IP lookup here: there is none in
                   the serving path, and adding one so a guide could open pre-filled would
                   be the first thing on this site that reads the visitor instead of asking
                   them. So it asks -- in one field -- and every answer lands in the prompt
                   box below, visible and editable, before anything is sent anywhere. -->
              <details class="tn-fgask" id="tnfgask">
                <summary>Answer a couple of questions instead</summary>
                <p class="tn-fgnote">Your answers write the prompt below, which you can read
                  and edit before asking. They stay in this browser.</p>
                <label class="tn-fgfield" for="tnfgloc">Where are you watching from?
                  <input type="text" id="tnfgloc" autocomplete="off"
                         placeholder="UK &mdash; or US East, or Germany">
                </label>
                <p class="tn-fgnote"><b>Nothing is looked up.</b> This box does not geolocate
                  you. Whatever you type is matched against your provider&rsquo;s own group
                  titles, so their spelling is the one that wins &mdash; &ldquo;UK&rdquo;
                  finds <code>UK| SPORTS</code>. If it matches nothing, Guide sets it aside
                  and says so rather than handing you an empty guide.</p>
                <p class="tn-fglab">What do you actually watch?</p>
                <div class="tn-fgchips" id="tnfgkeep"></div>
                <p class="tn-fglab">Anything you never want to see?</p>
                <div class="tn-fgchips" id="tnfgdrop"></div>
                <div class="tn-fgrow">
                  <button type="button" class="tn-fggo" id="tnfgwrite">Write the prompt and ask</button>
                  <button type="button" class="tn-fgalt" id="tnfgforget">Forget my answers</button>
                </div>
              </details>
              <textarea id="tnfgq" rows="2" placeholder="What should your guide keep? &ldquo;UK sports and films, no shopping&rdquo;"></textarea>
              <div class="tn-fgrow">
                <button type="button" class="tn-fggo" id="tnfggo">Ask SyMon</button>
                <label class="tn-fgmodel"><input type="checkbox" id="tnfgmodel"> use the model too</label>
              </div>
              <p class="tn-fgwhy" id="tnfgwhy" hidden></p>
              <div class="tn-fgrow" id="tnfgapplyrow" hidden>
                <button type="button" class="tn-fggo" id="tnfgapply">Re-tick the grid</button>
                <button type="button" class="tn-fgalt" id="tnfgsave">Save as my guide</button>
              </div>
              <p class="tn-fgsaved" id="tnfgsaved" hidden></p>
            </div>
          </div>
        </div>
      </div>

      <aside class="side">
        <div class="callout">
          <h2>Where your credentials go</h2>
          <p><b>Nowhere.</b> They stay in this browser&rsquo;s localStorage and travel with
            each request. The server holds them only for the life of a stream and keeps them
            out of process arguments and error text. Nothing is written to disk.</p>
          <p><b>Favourites too.</b> The star beside a channel writes to this browser and
            nothing else. There is no account here and no list of what you watch on this
            box.</p>
        </div>
        <div class="callout">
          <h2>Why there is no &ldquo;Trending&rdquo;</h2>
          <p>A playlist is a list of names and URLs. It carries <b>no view counts, no
            ratings and no trend feed</b>, so a tab called Trending would be a number this
            machine cannot read &mdash; the same dishonest pixel as a status light that is
            green because green looks better.</p>
          <p><b>Most carried</b> is what the data does support: it counts how many of your
            provider&rsquo;s own groups carry the same title, and how many listings of it
            exist &mdash; a channel duplicated across Sports, Premium and 4K is genuinely
            more prominent in that lineup. Ties fall back to the order the provider wrote
            the playlist in. Every row prints the counts it was ranked by, so you can check
            it.</p>
        </div>
        <div class="callout">
          <h2>How the stream is handled</h2>
          <p>ffmpeg copies the stream rather than re-encoding it, so it costs muxing and
            network rather than compute &mdash; this surface never queues behind the GPU. The
            upstream socket is opened in Python against a pinned, validated address and the
            bytes are piped in; <b>ffmpeg is never handed a URL</b>, so it cannot make its own
            DNS lookup or follow its own redirect.</p>
          <p>Playback is <b>hls.js</b> (Apache-2.0, vendored at <code>/hls.js</code>), because
            Chrome and Firefox will not play an <code>.m3u8</code> natively.</p>
        </div>
        <div class="callout">
          <h2>What the model actually does here</h2>
          <p><b>Your filter runs before the model does.</b> Matching your words against the
            list already in this browser is pure JavaScript over an array &mdash; it is done
            in single-digit milliseconds and the page prints the measurement. Results appear
            first; the card is only asked afterwards, and only when the local pass came back
            thin or left one of your words unmatched.</p>
          <p>When it is asked, it reads <b>your question</b>, not your playlist. The prompt
            comes back as one line of keywords, which widen the match already on screen.
            Feeding thousands of channel names through a 7B would be slow, would hold the GPU
            lock while it ran, and would be worse at it than a substring match. The pill above
            the results says which of those happened: <i>not needed</i>, <i>answered</i>,
            <i>added nothing</i>, or <i>unavailable</i>.</p>
        </div>
        <div class="callout">
          <h2>Known gaps, stated rather than hidden</h2>
          <p>The vendored hls.js is the <b>light</b> build: no subtitle or alternate-audio
            rendering. The Xtream client has <b>never been tested against a live panel</b>
            beyond channel listing. Series episodes list without URLs rather than with guessed
            ones, and AES-encrypted HLS is refused rather than decrypted.</p>
        </div>
      </aside>
    </div>
"""


# NOTE FOR ANYONE EDITING THE JS BELOW -- this has shipped broken twice.
# STREAMER_JS is a NORMAL triple-quoted string, not a raw one. A `\n` written here becomes a
# REAL newline in the emitted JavaScript; inside a string literal that leaves it
# unterminated and kills the entire page's script, and the browser suite passed 22/22
# while the page was dead. The same applies to every other backslash escape: `\b`, `\s`,
# `\d`, `\.` in a regex literal are all silently rewritten by Python.
# WRITE `\\n`, `\\b`, `\\s`, `\\.` -- always double. Verify by extracting the emitted
# <script> bodies and running `node --check` on each one; grep alone cannot catch it.
STREAMER_JS = """<script src="/hls.js"></script>
<script>
(function () {
  'use strict';

  // ---- Carry the visitor's own data across the rename. ----------------------------
  // These keys were `symoneural.streamer*` until the Streamer and the Guide were merged into
  // the Streamer. The whole promise of this surface is that the playlist, the favourites
  // and the credentials live in THIS browser and are never stored on the box -- which
  // means there is nowhere to restore them from. Renaming the namespace without carrying
  // the data would silently empty everything the visitor typed, and look like data loss
  // because it would be.
  //
  // Prefix-generic on purpose: a seventh key added later is carried without anyone
  // remembering to add it here. Idempotent on purpose: it never overwrites a value that
  // already exists under the new name, so a second visit cannot roll a visitor back to
  // what they had before the rename.
  try {
    var _OLD = 'symoneural.tuner', _NEW = 'symoneural.streamer';   // NOTE: _OLD is the RETIRED prefix and must stay spelled that way
    for (var _i = localStorage.length - 1; _i >= 0; _i--) {
      var _k = localStorage.key(_i);
      if (!_k || (_k !== _OLD && _k.indexOf(_OLD + '.') !== 0)) continue;
      var _nk = _NEW + _k.slice(_OLD.length);
      if (localStorage.getItem(_nk) === null) localStorage.setItem(_nk, localStorage.getItem(_k));
      localStorage.removeItem(_k);
    }
  } catch (_e) { /* private mode, or storage full: the page still works without history */ }
  var K = 'symoneural.streamer';
  // Favourites are the visitor's, and they stay here. They are never posted to this box:
  // the whole promise of this surface is that the playlist and the credentials live in the
  // browser, and a list of what someone likes to watch is exactly the same kind of fact.
  var FK = 'symoneural.streamer.favourites';

  var form = document.getElementById('tnform'), list = document.getElementById('tnlist');
  var note = document.getElementById('tnnote'), st = document.getElementById('tnstate');
  var browse = document.getElementById('tnbrowse'), catsEl = document.getElementById('tncats');
  var catWhy = document.getElementById('tncatwhy'), askWhy = document.getElementById('tnaskwhy');
  var gpanel = document.getElementById('tngpanel'), grid = document.getElementById('tngrid');
  var gwrap = document.getElementById('tngwrap'), gcount = document.getElementById('tngcount');
  var gsearch = document.getElementById('tngsearch'), gempty = document.getElementById('tngempty');
  var emptyEl = document.getElementById('tnempty'), moreBtn = document.getElementById('tnmore');
  var modelPill = document.getElementById('tnmodel'), modelTxt = document.getElementById('tnmodeltxt');
  var player = document.getElementById('tnplayer'), video = document.getElementById('tnvideo');
  var nowEl = document.getElementById('tnnow');

  var mode = 'm3u', all = [], hay = [], view = [], hls = null;
  // Which player got the stream, recorded when the choice is made rather than inferred from
  // `hls` being non-null -- see the same variable on streamer-watch.html for the measurement.
  // Inferring it means the panel starts claiming "the browser's own HLS" the moment the
  // instance is destroyed, which is exactly when somebody is reading the panel to find out
  // why the picture stopped.
  var engine = '';
  var cat = 'live', favs = {}, sel = {}, groupRows = [], filterState = null;
  var carried = [], carriedBy = {}, carriedMaxG = 0, carriedMaxN = 0;
  var PAGE = 300, shown = PAGE;

  // ---- the six top-level categories.
  // `live` / `vod` / `series` are the BACKEND'S vocabulary and are not negotiable:
  // m3u.py::_classify() emits `vod` for a film and never `movie`, xtream.py's spec table
  // is keyed on `vod`, and routes.py:142 filters the requested kinds to exactly those
  // three and falls back to ("live",) for anything else. Sending `movie` did not merely
  // mislabel something once -- the movie catalogue was never requested from the panel at
  // all. `fav`, `carried` and `filtered` are browser-side views and never leave this file.
  var CATS = [
    {id: 'fav',      label: 'Favorites'},
    {id: 'carried',  label: 'Most carried'},
    {id: 'filtered', label: 'Filtered'},
    {id: 'vod',      label: 'Movies'},
    {id: 'live',     label: 'Live TV'},
    {id: 'series',   label: 'TV Series'}
  ];

  document.querySelectorAll('.tn-tab').forEach(function (b) {
    b.addEventListener('click', function () {
      mode = b.dataset.mode;
      document.querySelectorAll('.tn-tab').forEach(function (x) {
        x.classList.toggle('on', x === b); });
      document.getElementById('tn-m3u').hidden = mode !== 'm3u';
      document.getElementById('tn-xtream').hidden = mode !== 'xtream';
    });
  });

  try {
    var saved = JSON.parse(localStorage.getItem(K) || 'null');
    if (saved) {
      mode = saved.mode || 'm3u';
      document.querySelector('.tn-tab[data-mode="' + mode + '"]').click();
      ['url', 'host', 'user', 'pass'].forEach(function (f) {
        if (saved[f]) document.getElementById('tn-' + f).value = saved[f]; });
    }
  } catch (e) { /* corrupt entry -- start clean */ }

  try {
    var fv = JSON.parse(localStorage.getItem(FK) || '[]');
    if (fv && fv.length) fv.forEach(function (k) { favs[k] = 1; });
  } catch (e2) { /* corrupt entry -- start with no favourites */ }

  function creds() {
    if (mode === 'm3u') return {mode: 'm3u', url: document.getElementById('tn-url').value.trim()};
    return {mode: 'xtream', host: document.getElementById('tn-host').value.trim(),
            user: document.getElementById('tn-user').value,
            pass: document.getElementById('tn-pass').value};
  }

  form.addEventListener('submit', function (e) {
    e.preventDefault();
    var c = creds();
    try { localStorage.setItem(K, JSON.stringify(c)); } catch (e2) { /* private mode */ }
    st.textContent = 'loading'; list.innerHTML = ''; browse.hidden = true;
    emptyEl.hidden = true; moreBtn.hidden = true;
    note.textContent = 'Fetching\\u2026';
    var url  = c.mode === 'm3u' ? '/api/streamer/playlist' : '/api/streamer/xtream/channels';
    var body = c.mode === 'm3u' ? {url: c.url}
             : {server: c.host, username: c.user, password: c.pass,
                kinds: ['live', 'vod', 'series']};
    fetch(url, {method: 'POST', headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(body)})
      .then(function (r) { return r.json().then(function (j) { return {ok: r.ok, j: j}; }); })
      .then(function (res) {
        if (!res.ok) throw new Error(res.j.error || res.j.detail || 'load failed');
        all = res.j.channels || [];
        st.textContent = all.length ? all.length + ' channels' : 'empty';
        // `truncated` is the M3U parser saying it stopped early. It was returned by the API
        // and read by nothing here, so a playlist over the cap lost its tail block -- usually
        // Movies, which is the biggest and last in most provider files -- and the page said
        // "Loaded" as if it had it all. A silent cap is data loss with a friendly face.
        var notes = (res.j.notes || []).slice();
        if (res.j.truncated) {
          notes.push('Only the first ' + res.j.limit + ' entries of this playlist were read. '
                   + 'Anything after that in the file is missing, which can be a whole '
                   + 'category -- Movies is usually last.');
        }
        var src = c.mode === 'm3u' ? 'playlist' : 'panel';
        note.textContent = (all.length
            ? 'Loaded from your ' + src + '. Nothing was stored here.'
            : 'That ' + src + ' answered but contained no channels.')
            + (notes.length ? '  ' + notes.join('  ') : '');
        indexAll();
        filterState = null; askWhy.textContent = '';
        document.getElementById('tnaskclear').hidden = true;
        setModel('', 'model: idle');
        if (all.length) { browse.hidden = false; pick(firstCat()); }
      })
      .catch(function (err) { st.textContent = 'failed'; note.textContent = String(err.message || err); });
  });

  // ---- indexing -------------------------------------------------------------------
  function kindOf(c) {
    var k = (c && c.kind ? String(c.kind) : 'live').toLowerCase();
    if (k === 'vod' || k === 'movie' || k === 'movies') return 'vod';
    if (k === 'series' || k === 'show' || k === 'shows') return 'series';
    return 'live';
  }
  function groupOf(c) { return (c && c.group) ? String(c.group) : '(no group)'; }
  // Which groups does one row belong to? For every category but Most carried that is the
  // one group the channel is listed under. A Most carried row is a TITLE, and its whole
  // claim is that several groups carry it -- so it belongs to all of them. Ticking by the
  // representative's group alone would let a row saying "3 groups" vanish when one of the
  // other two is unticked, which is the panel and the evidence line contradicting each
  // other in the one view built to be auditable.
  function groupsOfRow(i) {
    if (cat === 'carried') {
      var e = carriedBy[i];
      if (e && e.ng) return Object.keys(e.groups);
    }
    return [groupOf(all[i])];
  }
  // A favourite is identified by what a visitor can see -- kind, group and name. The URL
  // is deliberately not part of the key: providers rotate stream URLs, and a favourite
  // that evaporates on a URL change would look like a bug in the star.
  function favKey(c) { return kindOf(c) + '\\u0001' + groupOf(c) + '\\u0001' + (c.name || ''); }
  function isFav(c) { return favs[favKey(c)] === 1; }

  // Quality markers, stripped so that "Sky Sports HD" and "Sky Sports FHD" count as two
  // listings of one title rather than two unrelated channels. Country and language
  // prefixes are deliberately NOT stripped: "UK: Sky One" and "US: Sky One" are different
  // channels, and merging them would inflate the carriage count -- which is the one
  // number this view is ranked by, so inflating it would make the ranking a lie.
  // Deliberately narrow. Earlier drafts also stripped bare `1080`/`720` and the words
  // `raw`, `vip`, `alt`, `multi` -- which merges "Cinema 1080" into "Cinema" and
  // "Sky Sports Raw" into "Sky Sports". Merging two different channels INFLATES the
  // carriage count, and that count is the one number this view stakes its honesty on.
  // When in doubt, do not merge: an under-merged title is ranked slightly low, an
  // over-merged one is a number that is simply wrong.
  var QUALITY = /\\b(sd|hd|fhd|uhd|qhd|4k|8k|hevc|h265|h264|1080p|720p|480p|540p)\\b/g;
  function titleKey(name) {
    return String(name || '').toLowerCase()
      .replace(/[\\[\\(\\{][^\\]\\)\\}]*[\\]\\)\\}]/g, ' ')
      .replace(QUALITY, ' ')
      .replace(/[^a-z0-9]+/g, ' ')
      .trim();
  }

  function indexAll() {
    hay = all.map(function (c) {
      return ((c.name || '') + ' ' + (c.group || '')).toLowerCase();
    });
    buildCarried();
  }

  // ---- "Most carried" -------------------------------------------------------------
  // THIS TAB IS NOT "TRENDING", AND THAT IS THE POINT.
  //
  // A playlist carries no view counts, no ratings and no trend feed. Nothing in this
  // browser or on that box knows what anyone is watching. A tab labelled "Trending"
  // populated from a shuffle, or from any proxy dressed up as popularity, would be the
  // decorative indicator this site's whole argument forbids -- and a tooltip cannot
  // un-say a label, which is why the honest signal got the NAME and not a footnote.
  //
  // What the playlist really does contain, and what this ranks by:
  //   1. how many of the provider's own groups carry the same title -- a channel that
  //      appears in Sports, Premium and 4K is genuinely more prominent in that lineup;
  //   2. how many listings of the same title exist once quality markers are stripped;
  //   3. playlist position, as the tie-break -- a provider orders its own lineup
  //      deliberately, and position 1 is a decision somebody made.
  // Every row prints the counts it was ranked by, so the ranking is auditable rather
  // than asserted. And when the playlist has no such structure at all, the panel says
  // so instead of showing an arbitrary order that looks like a ranking.
  function buildCarried() {
    var by = {}, order = [];
    all.forEach(function (c, i) {
      var key = titleKey(c.name);
      if (!key) return;
      var e = by[key];
      if (!e) { e = by[key] = {idx: i, groups: {}, ng: 0, n: 0}; order.push(e); }
      e.n += 1;
      var g = c.group ? String(c.group) : '';
      if (g && e.groups[g] !== 1) { e.groups[g] = 1; e.ng += 1; }
      if (!all[e.idx].url && c.url) e.idx = i;
    });
    order.sort(function (a, b) { return (b.ng - a.ng) || (b.n - a.n) || (a.idx - b.idx); });
    carried = order;
    carriedBy = {}; carriedMaxG = 0; carriedMaxN = 0;
    order.forEach(function (e) {
      carriedBy[e.idx] = e;
      if (e.ng > carriedMaxG) carriedMaxG = e.ng;
      if (e.n > carriedMaxN) carriedMaxN = e.n;
    });
  }

  // Indexed, not searched. A linear scan per rendered row was 300 x every title on the
  // playlist, which is real time spent on a page whose selling point is that it is instant.
  function carriedEvidence(i) { return carriedBy[i] || null; }

  // ---- categories -----------------------------------------------------------------
  function kindCount(k) {
    var n = 0;
    for (var i = 0; i < all.length; i++) if (kindOf(all[i]) === k) n++;
    return n;
  }
  function favCount() {
    var n = 0;
    for (var i = 0; i < all.length; i++) if (isFav(all[i])) n++;
    return n;
  }

  function poolFor(id) {
    var out = [], i;
    if (id === 'fav') {
      for (i = 0; i < all.length; i++) if (isFav(all[i])) out.push(i);
      return out;
    }
    if (id === 'carried') {
      for (i = 0; i < carried.length; i++) out.push(carried[i].idx);
      return out;
    }
    if (id === 'filtered') return filterState ? filterState.idx.slice() : [];
    for (i = 0; i < all.length; i++) if (kindOf(all[i]) === id) out.push(i);
    return out;
  }

  function catCount(id) {
    if (id === 'fav') return favCount();
    if (id === 'carried') return carried.length;
    if (id === 'filtered') return filterState ? filterState.idx.length : 0;
    return kindCount(id);
  }

  function firstCat() {
    if (favCount()) return 'fav';
    var order = ['live', 'vod', 'series'];
    for (var i = 0; i < order.length; i++) if (kindCount(order[i])) return order[i];
    return 'carried';
  }

  function renderCats() {
    catsEl.innerHTML = '';
    CATS.forEach(function (c) {
      var n = catCount(c.id);
      var b = document.createElement('button');
      b.type = 'button';
      b.className = 'tn-cat' + (cat === c.id ? ' on' : '');
      b.setAttribute('aria-pressed', cat === c.id ? 'true' : 'false');
      // Filtered is dead until a filter has actually produced something. An enabled tab
      // that opens an empty panel is a promise the page has not kept yet.
      if (c.id === 'filtered' && !filterState) { b.disabled = true; b.title = 'run a filter first'; }
      var lab = document.createElement('b'); lab.textContent = c.label;
      var num = document.createElement('i');
      num.textContent = (c.id === 'filtered' && !filterState) ? '\\u2014' : String(n);
      b.appendChild(lab); b.appendChild(num);
      b.addEventListener('click', function () { if (!b.disabled) pick(c.id); });
      catsEl.appendChild(b);
    });
  }

  function catExplain() {
    if (cat === 'carried') {
      if (carriedMaxG > 1) {
        return 'Ranked by how many of this playlist\\u2019s own groups carry the same '
             + 'title, then by how many listings exist, then by playlist position. '
             + 'Quality markers (HD, FHD, 4K\\u2026) are stripped before counting. '
             + 'This is carriage in your provider\\u2019s lineup \\u2014 not popularity: '
             + 'this box has no view counts and does not pretend to.';
      }
      if (carriedMaxN > 1) {
        return 'No title in this playlist appears in more than one group, so there is no '
             + 'carriage to rank by. This is ranked by how many listings of the same '
             + 'title exist (quality variants), then by playlist position. Still a real '
             + 'count from your file \\u2014 not popularity.';
      }
      return 'Nothing to rank: every title in this playlist appears exactly once, in one '
           + 'group. This is the provider\\u2019s own playlist order, unchanged. No '
           + 'popularity data exists here and none has been invented.';
    }
    if (cat === 'fav') {
      return 'Your picks, kept in this browser only. Nothing about them is sent to this '
           + 'box.';
    }
    if (cat === 'filtered' && filterState) {
      return 'Produced by: ' + filterState.query + '  \\u2014  ' + filterState.why;
    }
    if (cat === 'vod') return 'Everything the playlist classifies as a film (the backend calls this kind `vod`).';
    if (cat === 'series') return 'Everything the playlist classifies as a series.';
    if (cat === 'live') return 'Everything the playlist classifies as a live channel.';
    return '';
  }

  function pick(id) {
    cat = id;
    shown = PAGE;
    renderCats();
    catWhy.textContent = catExplain();
    rebuildGroups();
    render();
  }

  // ---- the subcategory grid --------------------------------------------------------
  // Every group in the current category, all of them, with counts. No slice() cap: a cap
  // here is data loss, and the ask was explicitly for "the most possible to see at one
  // time". Real <input type="checkbox"> inside a <label> so the whole row is a hit target
  // and a keyboard reaches it. Every playlist-derived string is set with textContent --
  // group names arrive from a third party and carry quotes, ampersands and non-ASCII.
  function rebuildGroups() {
    var pool = poolFor(cat), counts = {}, names = [];
    pool.forEach(function (i) {
      groupsOfRow(i).forEach(function (g) {
        if (counts[g] === undefined) { counts[g] = 0; names.push(g); }
        counts[g] += 1;
      });
    });
    names.sort(function (a, b) { return (counts[b] - counts[a]) || a.localeCompare(b); });
    groupRows = names.map(function (g) { return {name: g, n: counts[g]}; });
    // Ticks reset with the category, because the groups themselves are different: the
    // groups under Movies are not the groups under Live TV. Everything ticked is the
    // only starting point where "None" and "All" both mean something unambiguous.
    sel = {};
    names.forEach(function (g) { sel[g] = 1; });

    grid.innerHTML = '';
    groupRows.forEach(function (row, n) {
      var lab = document.createElement('label');
      lab.className = 'tn-gcell';
      lab.htmlFor = 'tn-g-' + n;
      var box = document.createElement('input');
      box.type = 'checkbox'; box.id = 'tn-g-' + n; box.checked = true;
      box.addEventListener('change', function () {
        if (box.checked) sel[row.name] = 1; else delete sel[row.name];
        shown = PAGE; updateGroupCount(); render();
      });
      var nm = document.createElement('span');
      nm.className = 'tn-gname'; nm.textContent = row.name;
      var ct = document.createElement('span');
      ct.className = 'tn-gcnt'; ct.textContent = String(row.n);
      lab.appendChild(box); lab.appendChild(nm); lab.appendChild(ct);
      grid.appendChild(lab);
    });
    gpanel.hidden = groupRows.length < 2;
    gsearch.value = '';
    gempty.textContent = '';
    applyGroupSearch();
    updateGroupCount();
  }

  function cells() { return grid.querySelectorAll('.tn-gcell'); }

  function updateGroupCount() {
    // The floating prompt states how many subcategories it will read. That number has to
    // move with the ticks or the panel is describing a selection that no longer exists.
    // Guard on the element, not on the function: `fgSync` is a hoisted declaration and
    // is callable before the `var fg = document.getElementById(...)` line has run, so a
    // typeof check would pass and then dereference undefined.
    if (fg) fgSync();
    var on = 0;
    groupRows.forEach(function (r) { if (sel[r.name] === 1) on += 1; });
    // Under Most carried the number beside a group is how many RANKED TITLES it carries,
    // not how many listings -- because a row there is a title. Say which, rather than
    // leaving two different meanings behind the same bare number.
    gcount.textContent = on + ' of ' + groupRows.length + ' ticked'
      + (cat === 'carried' ? '  \\u00b7  counts are ranked titles each group carries' : '')
      + (gsearch.value.trim() ? '  \\u00b7  Select all / None / Invert act on what the search shows' : '');
  }

  function applyGroupSearch() {
    var q = gsearch.value.trim().toLowerCase(), visible = 0;
    var nodes = cells();
    for (var n = 0; n < nodes.length; n++) {
      var hit = !q || groupRows[n].name.toLowerCase().indexOf(q) >= 0;
      nodes[n].hidden = !hit;
      if (hit) visible += 1;
    }
    gempty.textContent = (q && !visible)
      ? 'No subcategory here matches \\u201c' + gsearch.value.trim() + '\\u201d.' : '';
  }

  function bulk(fn) {
    var nodes = cells();
    for (var n = 0; n < nodes.length; n++) {
      if (nodes[n].hidden) continue;              // acts on what the search shows
      var box = nodes[n].querySelector('input');
      box.checked = fn(box.checked);
      if (box.checked) sel[groupRows[n].name] = 1; else delete sel[groupRows[n].name];
    }
    shown = PAGE; updateGroupCount(); render();
  }

  // ---- the floating guide prompt ----------------------------------------------------
  //
  // One question plus the subcategories you have ticked go to SyMoNeuRaL Guide, and the
  // answer re-ticks the grid. That is the whole design: the outcome of asking is the
  // guide itself rather than a paragraph about it.
  //
  // The grid is the context on purpose. Guide is good at "sports" and hopeless at "the
  // ones I picked" -- it never sees your screen. Sending the ticked set with the question
  // is what lets "drop the shopping channels from these" mean something.
  var fg = document.getElementById('tnfg'), fgPill = document.getElementById('tnfgpill');
  var fgBody = document.getElementById('tnfgbody'), fgCount = document.getElementById('tnfgcount');
  var fgCtx = document.getElementById('tnfgctx'), fgQ = document.getElementById('tnfgq');
  var fgGo = document.getElementById('tnfggo'), fgWhy = document.getElementById('tnfgwhy');
  var fgApplyRow = document.getElementById('tnfgapplyrow'), fgApply = document.getElementById('tnfgapply');
  var fgSave = document.getElementById('tnfgsave'), fgSaved = document.getElementById('tnfgsaved');
  var fgModel = document.getElementById('tnfgmodel');
  var fgLast = null;                       // the last answer, or null
  var GK = 'symoneural.streamer.guide';

  function fgTicked() {
    var out = [];
    groupRows.forEach(function (r) { if (sel[r.name] === 1) out.push(r.name); });
    return out;
  }

  // Only the channels the grid is currently showing. Sending the whole playlist would
  // make "these" mean "everything", which is the one thing the ticks are there to stop.
  function fgChannels() {
    var on = {}, out = [];
    fgTicked().forEach(function (g) { on[g] = 1; });
    poolFor(cat).forEach(function (i) {
      var hit = false;
      groupsOfRow(i).forEach(function (g) { if (on[g] === 1) hit = true; });
      if (!hit) return;
      var c = all[i];
      out.push({name: c.name || '', group: groupOf(c), kind: kindOf(c), url: c.url || ''});
    });
    return out;
  }

  function fgSync() {
    if (!all.length) { fg.hidden = true; return; }
    fg.hidden = false;
    var n = fgTicked().length;
    fgCount.textContent = 'Guide \u00b7 ' + n + ' ticked';
    fgCtx.textContent = 'It will read the ' + n + ' subcategor'
      + (n === 1 ? 'y' : 'ies') + ' you have ticked under ' + catLabel(cat)
      + ' \u2014 ' + fgChannels().length + ' channels \u2014 and nothing else. '
      + 'Your playlist is not sent anywhere but this box.';
  }

  function catLabel(id) {
    for (var i = 0; i < CATS.length; i++) if (CATS[i].id === id) return CATS[i].label;
    return id;
  }

  function fgOpen(open) {
    fgBody.hidden = !open;
    fgPill.setAttribute('aria-expanded', open ? 'true' : 'false');
    if (open) { fgSync(); fgQ.focus(); }
  }
  fgPill.addEventListener('click', function () { fgOpen(fgBody.hidden); });
  document.getElementById('tnfgx').addEventListener('click', function () { fgOpen(false); });

  // Named rather than inline because the questionnaire below fills the prompt box and then
  // asks the same way the button does -- two paths into one request, not two requests.
  function fgAsk() {
    var q = fgQ.value.trim();
    if (!q) { fgQ.focus(); return; }
    var chans = fgChannels();
    if (!chans.length) {
      fgWhy.hidden = false;
      fgWhy.textContent = 'Nothing is ticked, so there is nothing to narrow. Tick some '
        + 'subcategories first \u2014 or use Select all and let the box cut it down.';
      return;
    }
    fgGo.disabled = true;
    fgWhy.hidden = false;
    fgWhy.textContent = 'asking\u2026';
    fgApplyRow.hidden = true; fgSaved.hidden = true;
    fetch('/api/streamer/guide/filter', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({question: q, channels: chans,
                            use_model: fgModel.checked, apply: true})
    }).then(function (r) {
      return r.json().then(function (j) { return {ok: r.ok, j: j}; });
    }).then(function (res) {
      fgGo.disabled = false;
      if (!res.ok) {
        fgWhy.textContent = (res.j && res.j.detail) ? String(res.j.detail)
                                                    : 'the box could not answer that';
        return;
      }
      fgLast = res.j;
      var n = res.j.count || 0;
      // Guide's own account of what it did, verbatim. It already names its provenance
      // -- local pass or model, and anything it set aside -- and paraphrasing it here
      // would be this page asserting something the box did not say.
      fgWhy.textContent = n + (n === 1 ? ' channel' : ' channels') + '. ' + (res.j.why || '');
      fgApplyRow.hidden = !(res.j.groups && res.j.groups.length);
    }).catch(function () {
      fgGo.disabled = false;
      fgWhy.textContent = 'could not reach the box';
    });
  }
  fgGo.addEventListener('click', fgAsk);

  fgApply.addEventListener('click', function () {
    if (!fgLast || !fgLast.groups) return;
    var keep = {};
    fgLast.groups.forEach(function (g) { keep[g] = 1; });
    var nodes = cells(), on = 0;
    for (var n = 0; n < nodes.length; n++) {
      var box = nodes[n].querySelector('input');
      var name = groupRows[n].name;
      box.checked = keep[name] === 1;
      if (box.checked) { sel[name] = 1; on += 1; } else { delete sel[name]; }
    }
    shown = PAGE; updateGroupCount(); render();
    fgSaved.hidden = false;
    fgSaved.textContent = on + ' subcategor' + (on === 1 ? 'y is' : 'ies are')
      + ' now ticked. Nothing was removed from your playlist \u2014 untick and they come back.';
  });

  fgSave.addEventListener('click', function () {
    var payload = {cat: cat, groups: fgTicked()};
    try {
      localStorage.setItem(GK, JSON.stringify(payload));
      fgSaved.hidden = false;
      fgSaved.textContent = 'Saved in this browser. It is never sent anywhere, exactly '
        + 'like your favourites.';
    } catch (e) {
      fgSaved.hidden = false;
      fgSaved.textContent = 'This browser refused to store it (private mode). The ticks '
        + 'still apply for this session.';
    }
  });

  // ---- the couple of questions -------------------------------------------------------
  //
  // Garrett: "I really wanted to integrate the symoneural guide AI so it would be smart
  // based off location and ask a couple questions". It asks. Location here is a question
  // and never a lookup -- see the comment on the markup for why that is deliberate rather
  // than lazy -- and the answers compose one sentence that lands in the prompt box, where
  // the visitor can see exactly what is about to be sent and change it.
  //
  // The words are kept as the visitor's own. `guide/__init__.py` matches them against the
  // playlist's group vocabulary and bridges the ones it knows ("films" -> the MOVIES
  // groups), so rewording them here would be this page guessing on the module's behalf and
  // getting the credit or the blame for it.
  var QK = 'symoneural.streamer.guideq';
  var FG_KEEP = ['sports', 'films', 'news', 'kids', 'documentaries', 'music', 'entertainment'];
  var FG_DROP = ['shopping', 'religion', 'adult', 'radio'];
  var fgAskEl = document.getElementById('tnfgask'), fgLoc = document.getElementById('tnfgloc');
  var fgKeepEl = document.getElementById('tnfgkeep'), fgDropEl = document.getElementById('tnfgdrop');
  var qKeep = {}, qDrop = {};

  function fgChips(host, words, state) {
    host.textContent = '';
    words.forEach(function (w) {
      var lab = document.createElement('label');
      var box = document.createElement('input');
      box.type = 'checkbox';
      box.checked = state[w] === 1;
      lab.className = 'tn-fgchip' + (box.checked ? ' on' : '');
      box.addEventListener('change', function () {
        if (box.checked) { state[w] = 1; } else { delete state[w]; }
        lab.className = 'tn-fgchip' + (box.checked ? ' on' : '');
        fgSaveAnswers();
      });
      lab.appendChild(box);
      lab.appendChild(document.createTextNode(w));
      host.appendChild(lab);
    });
  }

  function fgSaveAnswers() {
    try {
      localStorage.setItem(QK, JSON.stringify({loc: fgLoc.value.trim(),
                                               keep: Object.keys(qKeep),
                                               drop: Object.keys(qDrop)}));
    } catch (e) { /* private mode: the answers still hold for this session */ }
  }

  function fgLoadAnswers() {
    var saved = null;
    try { saved = JSON.parse(localStorage.getItem(QK) || 'null'); } catch (e) { saved = null; }
    if (saved) {
      fgLoc.value = saved.loc || '';
      (saved.keep || []).forEach(function (w) { qKeep[w] = 1; });
      (saved.drop || []).forEach(function (w) { qDrop[w] = 1; });
    }
    fgChips(fgKeepEl, FG_KEEP, qKeep);
    fgChips(fgDropEl, FG_DROP, qDrop);
    // Open on a first visit, folded once there are answers to come back to. The questions
    // are the point on the visit where you have no idea what to type; on the next visit
    // you do, and a form in the way would be the thing being complained about.
    fgAskEl.open = !saved;
  }

  // One sentence, in the shape the module reads best: the positive clause first, then the
  // exclusions after "not" -- a word `_NEGATORS` splits on, so "not shopping" narrows the
  // negative clause instead of leaking backwards over the whole question.
  function fgList(a) {
    if (a.length < 2) return a.join('');
    return a.slice(0, -1).join(', ') + ' and ' + a[a.length - 1];
  }

  function fgCompose() {
    var keep = FG_KEEP.filter(function (w) { return qKeep[w] === 1; });
    var drop = FG_DROP.filter(function (w) { return qDrop[w] === 1; });
    var loc = fgLoc.value.trim();
    var s = keep.length ? (loc ? loc + ' ' : '') + fgList(keep) : loc;
    if (drop.length) s += (s ? ', ' : '') + 'not ' + fgList(drop);
    return s;
  }

  document.getElementById('tnfgwrite').addEventListener('click', function () {
    var s = fgCompose();
    if (!s) {
      fgWhy.hidden = false;
      fgWhy.textContent = 'Answer at least one of them \\u2014 a location on its own is '
        + 'enough, and so is a single category. With none of them answered there is no '
        + 'question to ask.';
      return;
    }
    fgSaveAnswers();
    fgQ.value = s;                      // visible and editable BEFORE the request goes out
    fgAsk();
  });

  document.getElementById('tnfgforget').addEventListener('click', function () {
    qKeep = {}; qDrop = {};
    fgLoc.value = '';
    try { localStorage.removeItem(QK); } catch (e) { /* nothing was stored to remove */ }
    fgChips(fgKeepEl, FG_KEEP, qKeep);
    fgChips(fgDropEl, FG_DROP, qDrop);
    fgSaved.hidden = false;
    fgSaved.textContent = 'Answers cleared from this browser. Nothing left this browser in '
      + 'the first place \\u2014 they only ever wrote the prompt.';
  });

  fgLoc.addEventListener('change', fgSaveAnswers);
  fgLoadAnswers();

  gsearch.addEventListener('input', function () { applyGroupSearch(); updateGroupCount(); });
  document.getElementById('tngall').addEventListener('click', function () { bulk(function () { return true; }); });
  document.getElementById('tngnone').addEventListener('click', function () { bulk(function () { return false; }); });
  document.getElementById('tnginv').addEventListener('click', function () { bulk(function (v) { return !v; }); });
  document.getElementById('tngtoggle').addEventListener('click', function () {
    var open = gwrap.hidden;
    gwrap.hidden = !open;
    this.setAttribute('aria-expanded', open ? 'true' : 'false');
    this.querySelector('u').textContent = open ? '\\u2212' : '+';
  });

  // ---- results ---------------------------------------------------------------------
  function render() {
    var pool = poolFor(cat);
    view = pool.filter(function (i) {
      var gs = groupsOfRow(i);
      for (var n = 0; n < gs.length; n++) if (sel[gs[n]] === 1) return true;
      return false;
    });
    renderList();
    renderEmpty();
  }

  function renderEmpty() {
    var msg = '';
    if (view.length) { emptyEl.hidden = true; return; }
    if (cat === 'fav' && !favCount()) {
      // A visitor with favourites from a DIFFERENT playlist has not got "none" -- they
      // have got none *here*, and telling them otherwise reads as data loss.
      msg = Object.keys(favs).length
        ? 'You have ' + Object.keys(favs).length + ' favourite(s) saved in this browser, '
          + 'but none of them are in the playlist currently loaded. They are still there '
          + 'for the playlist they came from.'
        : 'No favourites yet. Tap the star beside any channel and it is kept here, in '
          + 'this browser, for next time. Nothing about it is sent to this machine.';
    } else if (cat === 'filtered' && !filterState) {
      msg = 'Nothing has been filtered yet. Ask for something above and the result lands '
          + 'here.';
    } else if (groupRows.length && !Object.keys(sel).length) {
      msg = 'Nothing is ticked in the subcategory list, so there is nothing to show. '
          + '\\u201cSelect all\\u201d puts it back.';
    } else if (!poolFor(cat).length) {
      msg = 'This playlist has nothing in this category. That is the reading, not a '
          + 'placeholder.';
    } else {
      msg = 'Nothing here matches the ticked subcategories.';
    }
    emptyEl.textContent = msg;
    emptyEl.hidden = false;
  }

  function renderList() {
    list.innerHTML = '';
    var upto = Math.min(shown, view.length);
    for (var n = 0; n < upto; n++) list.appendChild(row(view[n]));
    if (view.length > upto) {
      moreBtn.hidden = false;
      moreBtn.textContent = 'showing ' + upto + ' of ' + view.length + ' \\u2014 show '
        + Math.min(PAGE, view.length - upto) + ' more';
    } else {
      moreBtn.hidden = true;
    }
  }

  moreBtn.addEventListener('click', function () { shown += PAGE; renderList(); });

  function row(i) {
    var c = all[i];
    var li = document.createElement('li');

    var star = document.createElement('button');
    star.type = 'button';
    star.className = 'tn-fav' + (isFav(c) ? ' on' : '');
    star.textContent = isFav(c) ? '\\u2605' : '\\u2606';
    star.title = isFav(c) ? 'remove from favourites' : 'keep in favourites (this browser only)';
    star.setAttribute('aria-label', star.title);
    star.setAttribute('aria-pressed', isFav(c) ? 'true' : 'false');
    star.addEventListener('click', function (e) {
      e.stopPropagation();
      toggleFav(c);
      if (cat === 'fav') { shown = PAGE; render(); }
      else {
        star.className = 'tn-fav' + (isFav(c) ? ' on' : '');
        star.textContent = isFav(c) ? '\\u2605' : '\\u2606';
        star.setAttribute('aria-pressed', isFav(c) ? 'true' : 'false');
      }
      renderCats();
    });
    li.appendChild(star);

    var b = document.createElement('b'); b.textContent = c.name || '(unnamed)';
    li.appendChild(b);

    if (cat === 'carried') {
      var e = carriedEvidence(i);
      var ev = document.createElement('span');
      ev.className = 'tn-evi';
      ev.textContent = e
        ? (e.ng + (e.ng === 1 ? ' group' : ' groups') + ' \\u00b7 '
           + e.n + (e.n === 1 ? ' listing' : ' listings'))
        : (c.group || '');
      li.appendChild(ev);
    } else {
      var sp = document.createElement('span'); sp.textContent = c.group || '';
      li.appendChild(sp);
    }

    if (c.url) {
      li.className = 'playable';
      li.addEventListener('click', function () { tune(c); });
    } else {
      var no = document.createElement('em'); no.textContent = 'no stream url';
      li.appendChild(no);
    }
    return li;
  }

  function toggleFav(c) {
    var k = favKey(c);
    if (favs[k] === 1) delete favs[k]; else favs[k] = 1;
    try { localStorage.setItem(FK, JSON.stringify(Object.keys(favs))); }
    catch (e) { /* private mode -- the star still works for this session */ }
  }

  // ---- playback --------------------------------------------------------------------
  //
  // A stream that does not play must SAY why. The rule of thumb the owner uses to
  // triage his own provider is exactly right and is what this code is built around:
  // a page from the provider saying the channel is down means the channel is down;
  // a blank screen means the streamer is broken. A player that renders both as a black
  // rectangle destroys the only diagnostic signal there is.
  //
  // Two mechanisms produced that blank screen and both are handled here.
  //
  //   1. POST /tune answers **200** with state:"starting" and a `note` when ffmpeg has
  //      not written a playlist inside its deadline. `res.ok` is true, so the old code
  //      handed a manifest that did not exist yet to hls.js. We now wait on the session
  //      instead of guessing, and report whichever way it resolves.
  //   2. A fatal hls.js error was written into the status line as library jargon
  //      ("networkError / manifestLoadError") and nothing ever asked the server why.
  //      The server is the only party that knows -- it is the one that talked to the
  //      provider -- so a fatal error now goes and asks it.
  var failEl = document.getElementById('tnfail'), failH = document.getElementById('tnfailh'),
      failP = document.getElementById('tnfailp'), failD = document.getElementById('tnfaild'),
      failC = document.getElementById('tnfailc');
  var sid = null, waitT = null, watchT = null, hiddenT = null;

  // ---- give the slot back ----------------------------------------------------------
  // A slot held by somebody who has already left is, on a two-slot box, the entire streamer.
  // Silence used to be the only signal a departing visitor gave, and silence takes the
  // server IDLE_TIMEOUT plus a reaper tick to read. So say goodbye out loud.
  //
  // `sendBeacon` and not `fetch`: a request started in an unload handler is cancelled when
  // the document goes away, and beacons are explicitly exempt from that. It only does POST,
  // which is why the server has a POST route beside the DELETE one.
  function release(id) {
    if (!id) return;
    var u = '/api/streamer/session/' + encodeURIComponent(id) + '/stop';
    if (navigator.sendBeacon) { navigator.sendBeacon(u, ''); return; }
    // No beacon (older Safari): keepalive is the documented fallback and survives unload.
    try { fetch(u, {method: 'POST', keepalive: true}); } catch (e) {}
  }

  // Set for exactly one navigation: the handoff to /streamer-watch.html. The slot is deliberately
  // NOT released then, because that page ADOPTS the running session -- which is what makes the
  // handoff instant rather than a fresh upstream connect and several seconds of black screen.
  // The exposure is bounded and collecting it is the reaper's ordinary job: if that page never
  // loads, nothing polls the session and it is taken back within IDLE_TIMEOUT.
  var handingOff = false;

  function letGo() {
    if (handingOff) return;
    var id = sid; sid = null;
    stopTimers();
    if (hls) { try { hls.destroy(); } catch (e) {} hls = null; }
    release(id);
  }

  // Both events, because neither alone is reliable: `pagehide` misses a tab discarded by the
  // OS, and iOS Safari fires only `visibilitychange` on app switch. The server treats a
  // repeated release as success, so firing twice costs nothing.
  window.addEventListener('pagehide', letGo);
  window.addEventListener('beforeunload', letGo);

  // A hidden tab is not a viewer. Browsers throttle background timers to about one tick a
  // minute, which is slow enough that the heartbeat alone kept a slot alive indefinitely for
  // a tab nobody was looking at. Give it a grace period, then hand the slot back; the visitor
  // gets a plain sentence saying why, not a silently dead player.
  var HIDDEN_GRACE_MS = 20000;
  document.addEventListener('visibilitychange', function () {
    if (document.hidden) {
      if (!sid || hiddenT) return;
      hiddenT = setTimeout(function () {
        hiddenT = null;
        if (!sid || !document.hidden) return;
        var name = nowEl.textContent.split('  \\u00b7  ')[0];
        letGo();
        video.pause();
        nowEl.textContent = name + '  \\u00b7  released';
        showFail('The stream was closed while this tab was in the background.',
                 'This box has a small number of streamer slots and holding one for a tab '
                 + 'nobody is watching makes the streamer unavailable to everyone, '
                 + 'including you in another window. Press the channel again to reopen '
                 + 'it \\u2014 nothing has failed.', null, null);
      }, HIDDEN_GRACE_MS);
    } else if (hiddenT) {
      clearTimeout(hiddenT); hiddenT = null;
    }
  });

  // How long to wait for first video. The server's own /tune deadline is 10s and a
  // cold upstream plus a probe genuinely takes longer than that, so giving up at 10
  // would report a failure the box had not actually reached.
  var FIRST_VIDEO_MS = 45000;

  function clearFail() {
    failEl.hidden = true; failD.hidden = true; failSticky = false;
    failH.textContent = ''; failP.textContent = ''; failC.textContent = '';
  }

  // THE CODEC DIAGNOSIS OUTRANKS WHAT FOLLOWS IT, and this is not cosmetic ordering.
  //
  // A stream the browser cannot decode produces a fatal hls.js error a moment after the codec
  // panel is written -- MSE refuses the buffer, that is the whole mechanism -- and the error
  // handler then overwrote "This stream is H.265 / HEVC" with "Playback stopped. The player
  // could not fetch the next part of the stream." Which is the same black rectangle with the
  // cause replaced by a symptom, and it is exactly the failure this panel exists to prevent.
  //
  // It surfaced the moment the hls.js path started running on Chrome at all (see `play`); the
  // native path never raised the error, so the bug was there the whole time and unreachable.
  // The suite caught it: `an undecodable codec is named outright` went red on "Playback
  // stopped.".
  //
  // `sticky` is cleared by clearFail(), i.e. by the next tune, so it cannot outlive its stream.
  var failSticky = false;

  // `said` is the provider's or the server's own sentence and is quoted as such, kept
  // apart from our explanation so the visitor can see which words are whose.
  function showFail(head, mine, said, tech, sticky) {
    if (failSticky && !sticky) return;
    failSticky = !!sticky;
    failH.textContent = head;
    failP.textContent = mine || '';
    if (said) {
      var q = document.createElement('span');
      q.className = 'tn-said';
      q.textContent = said;
      failP.appendChild(q);
    }
    if (tech) { failC.textContent = tech; failD.hidden = false; }
    failEl.hidden = false;
    player.hidden = false;
  }

  function stopTimers() {
    if (waitT) { clearInterval(waitT); waitT = null; }
    if (watchT) { clearInterval(watchT); watchT = null; }
  }

  function session() {
    if (!sid) return Promise.resolve(null);
    return fetch('/api/streamer/session/' + encodeURIComponent(sid))
      .then(function (r) { return r.ok ? r.json() : null; })
      .catch(function () { return null; });
  }

  // ---- codecs a browser cannot decode ------------------------------------------------
  //
  // `-c copy` succeeds, every light on the box is green, and the visitor gets a black
  // rectangle. This is unfindable unless the page says the word out loud.
  //
  // IT IS NOT ONLY THE VIDEO CODEC, and that was a real hole. Measured on one of the owner's
  // own channels: `state: live`, `vcodec: h264`, 87 MB pulled from the provider across five
  // minutes, session healthy -- and the browser decoded ZERO frames, because MSE refuses the
  // whole segment when it cannot take the AUDIO track. The picture stops for a soundtrack.
  // `sessions.py` had parsed `acodec` all along and deliberately not published it; it does now.
  //
  // And the answer is ASKED OF THIS BROWSER rather than looked up in a table of what browsers
  // are believed to do. Measured here on Chrome 151, in MPEG-TS, which is what the box serves:
  // h264, aac, mp2 and mp3 accepted; hevc, mpeg2video, vc1, av1, vp9, ac3, eac3, dts and
  // truehd all refused. A table would have been wrong about mp2 in the same week it was
  // written -- it is fine, and it was on the suspect list.
  var VMIME = {h264: 'avc1.42E01E', hevc: 'hvc1.1.6.L93.B0', h265: 'hvc1.1.6.L93.B0',
               av1: 'av01.0.04M.08', vp9: 'vp09.00.10.08', vp8: 'vp8',
               mpeg2video: 'mp4v.61', vc1: 'vc-1', mpeg4: 'mp4v.20.9'};
  var AMIME = {aac: 'mp4a.40.2', ac3: 'ac-3', eac3: 'ec-3', mp2: 'mp4a.6B', mp3: 'mp4a.69',
               opus: 'opus', flac: 'flac', dts: 'dtsc', truehd: 'mlpa', vorbis: 'vorbis'};
  var CODEC_NAMES = {hevc: 'H.265 / HEVC', h265: 'H.265 / HEVC', av1: 'AV1', vp9: 'VP9',
                     vp8: 'VP8', mpeg2video: 'MPEG-2', vc1: 'VC-1', mpeg4: 'MPEG-4 Part 2',
                     ac3: 'Dolby Digital (AC-3)', eac3: 'Dolby Digital Plus (E-AC-3)',
                     dts: 'DTS', truehd: 'Dolby TrueHD', opus: 'Opus', flac: 'FLAC',
                     vorbis: 'Vorbis'};

  // Both containers are asked about and a codec either one will take is NOT warned about: the
  // box serves MPEG-TS and hls.js remuxes to fMP4, so refusing on the strength of one of them
  // would put a scary sentence over a stream that plays. A false alarm here is the expensive
  // mistake -- it teaches the visitor to ignore the panel.
  function decodable(token, isVideo) {
    var m = (isVideo ? VMIME : AMIME)[token];
    if (!m) return true;
    if (!window.MediaSource || !window.MediaSource.isTypeSupported) return true;
    return window.MediaSource.isTypeSupported('video/mp2t; codecs="' + m + '"')
        || window.MediaSource.isTypeSupported((isVideo ? 'video/mp4' : 'audio/mp4')
                                              + '; codecs="' + m + '"');
  }

  // One place for the sentence, because it was two and they had already drifted -- one named the
  // codec in its technical line and the other did not.
  function codecFail(j, warn) {
    showFail('This stream is ' + warn + '.',
             'The box is receiving it and copying it through without re-encoding, so nothing '
             + 'here has failed \\u2014 but this browser cannot decode ' + warn + '. When it is '
             + 'the sound it will not take, it refuses the whole stream rather than just the '
             + 'audio, so the picture stays black either way. Play it in VLC, or pick another '
             + 'quality from your provider.',
             null,
             'reported by the transcoder \\u2014 video: ' + (j.vcodec || 'not reported')
             + ', audio: ' + (j.acodec || 'not reported'),
             true);
  }

  //: The name of the codec this browser will not take, video first, or '' if it will take both.
  function codecWarning(j) {
    var v = j && j.vcodec ? String(j.vcodec).toLowerCase() : '';
    if (v && !decodable(v, true)) return CODEC_NAMES[v] || v;
    var a = j && j.acodec ? String(j.acodec).toLowerCase() : '';
    if (a && !decodable(a, false)) return (CODEC_NAMES[a] || a) + ' audio';
    return '';
  }

  function tune(c) {
    stopTimers(); clearFail();
    if (hls) { hls.destroy(); hls = null; }
    // Only reset a source that exists. Calling load() on a <video> with no src makes
    // Chrome raise NotSupportedError, which is an uncaught error on the page for a
    // situation where nothing has gone wrong at all.
    if (video.getAttribute('src')) { video.removeAttribute('src'); video.load(); }
    // Hand the outgoing session back in the same request that asks for the next one. Changing
    // channel used to abandon it: the id was dropped here and the session lived on until the
    // idle reaper noticed, so on a two-slot box the third channel clicked was refused with a
    // message blaming the provider.
    var leaving = sid;
    sid = null;
    nowEl.textContent = 'opening ' + (c.name || '') + '\\u2026';
    player.hidden = false;
    var creds_ = creds();
    fetch('/api/streamer/tune', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({url: c.url, label: c.name || '', release: leaving || '',
                            username: creds_.user || '', password: creds_.pass || ''})
    }).then(function (r) {
        return r.json().then(function (j) { return {ok: r.ok, status: r.status, j: j}; });
      })
      .then(function (res) {
        var j = res.j || {};
        if (!res.ok) {
          var why = j.detail || j.error || 'no reason given';
          // 503 with the word "slots" is this box, not the provider. Saying "your provider
          // refused it" for our own capacity limit is the reason a full streamer reads as a
          // blocked channel -- and it is the page telling the visitor something untrue.
          if (res.status === 503 && /slot/i.test(String(why))) {
            nowEl.textContent = (c.name || '') + '  \\u00b7  no free streamer slot';
            showFail('Every streamer slot on this box is in use.',
                     'This is a limit here, not your provider and nothing to do with '
                     + 'this channel. A slot frees the moment another stream is closed, '
                     + 'and an abandoned one is collected within seconds. Try again.',
                     why, null);
            return;
          }
          nowEl.textContent = (c.name || '') + '  \\u00b7  did not open';
          showFail('This channel did not open.',
                   'The box asked your provider for it and was refused. That is a '
                   + 'reading from the provider, not a limit here \\u2014 nothing on '
                   + 'this machine filters what you may watch.',
                   why, null);
          return;
        }
        sid = j.id || null;
        var warn = codecWarning(j);
        // `live` plus at least one segment actually named by the playlist. The playlist file
        // exists before it lists anything, so `state === 'live'` alone can hand hls.js an
        // empty manifest; it then sits silent on a black rectangle while the page claims to
        // be playing. `segments` is published for exactly this decision.
        if (j.state === 'live' && !j.note && (j.segments || 0) > 0) {
          nowEl.textContent = (c.name || '') + '  \\u00b7  live';
          if (warn) codecFail(j, warn);
          play('/api/streamer/' + j.playlist, c, j);
          return;
        }
        // Still starting. Wait on the session rather than handing hls.js a manifest
        // that does not exist yet -- that is mechanism (1) above.
        waitFor(c, j);
      })
      .catch(function (e) {
        nowEl.textContent = (c.name || '') + '  \\u00b7  could not reach the box';
        showFail('The streamer could not be reached.',
                 'The request to this machine failed before your provider was ever '
                 + 'contacted, so this says nothing about the channel.',
                 null, String(e && e.message ? e.message : e));
      });
  }

  function waitFor(c, first) {
    var t0 = Date.now();
    nowEl.textContent = (c.name || '') + '  \\u00b7  opening\\u2026';
    waitT = setInterval(function () {
      var waited = Date.now() - t0;
      session().then(function (j) {
        if (!waitT) return;
        if (!j) {
          stopTimers();
          nowEl.textContent = (c.name || '') + '  \\u00b7  ended';
          showFail('The session ended before any video arrived.',
                   'The box opened a slot for this channel and the slot closed again '
                   + 'without producing a picture.', null, null);
          return;
        }
        if (j.state === 'failed') {
          stopTimers();
          nowEl.textContent = (c.name || '') + '  \\u00b7  failed';
          showFail('This channel did not start.',
                   'This is what the box got back when it tried. Nothing here blocks '
                   + 'or filters streams.',
                   j.error || 'no reason given', null);
          return;
        }
        if (j.state === 'live' && (j.segments || 0) > 0) {
          stopTimers();
          nowEl.textContent = (c.name || '') + '  \\u00b7  live';
          var warn = codecWarning(j);
          if (warn) codecFail(j, warn);
          play('/api/streamer/' + j.playlist, c, j);
          return;
        }
        if (waited > FIRST_VIDEO_MS) {
          stopTimers();
          nowEl.textContent = (c.name || '') + '  \\u00b7  no video';
          showFail('No video arrived within ' + Math.round(FIRST_VIDEO_MS / 1000) + ' seconds.',
                   'The upstream connection opened but never produced anything the '
                   + 'transcoder could copy. That usually means the provider is '
                   + 'answering with something other than a stream.',
                   j.error || null,
                   'session state: ' + j.state + ' \\u00b7 bytes read from upstream: '
                   + (j.bytes_in || 0));
          return;
        }
        nowEl.textContent = (c.name || '') + '  \\u00b7  opening\\u2026 ('
          + Math.round(waited / 1000) + 's)';
      });
    }, 700);
  }

  // A rejected play() is not a fault worth throwing: autoplay policy and an
  // undecodable codec both reject here, and both are already explained on the page.
  function safePlay() {
    var pr = video.play();
    if (pr && pr.catch) pr.catch(function () {});
  }

  function play(src, c, j) {
    if (hls) { hls.destroy(); hls = null; }
    // hls.js FIRST, and the browser's own HLS only where hls.js will not run. This order is the
    // reverse of what shipped, and the reversal is a bug fix, not a preference.
    //
    // MEASURED on the Chrome this repo tests with: `canPlayType('application/vnd.apple.mpegurl')`
    // returns **'maybe'** -- a truthy string. So `if (canPlayType(...))` took the native branch
    // on every Chrome visit, and everything below it was dead code in the browser almost every
    // visitor uses: the `liveSyncDurationCount: 1` change that took first video from 31 s to
    // 2.5 s, the fatal-error handler that goes and asks the box why a stream stopped, the level
    // and throughput readings on the statistics panel, and the quality selector. The panel read
    // "the browser's own HLS" with bitrate and throughput at `-`, which is what gave it away.
    //
    // Safari is the case the fallback exists for: it has no MSE-based path and does play HLS
    // natively, and there `Hls.isSupported()` is false, so it falls through correctly.
    if (window.Hls && window.Hls.isSupported()) {
      hlsPlay(src, c, j);
      return;
    }
    if (video.canPlayType('application/vnd.apple.mpegurl')) {
      engine = 'the browser\\u2019s own HLS';
      video.src = src; safePlay(); watch(c); return;
    }
    showFail('This browser cannot play HLS.',
             'hls.js is vendored at /hls.js and either did not load or is not supported '
             + 'here, and this browser has no HLS support of its own. The stream itself '
             + 'is fine.', null, null);
  }

  function hlsPlay(src, c, j) {
    // THE THING THAT MADE IT SLOW, and it was never the box.
    //
    // ffmpeg is asked for 2-second segments, but it stream-copies -- so it can only cut on a
    // keyframe, and a provider stream with a 10-second GOP yields 10-second segments however
    // small `-hls_time` is. Measured on a real channel: `#EXT-X-TARGETDURATION:10`,
    // `#EXTINF:10.427`. hls.js then defaults to `liveSyncDurationCount: 3`, i.e. it starts
    // three segments behind the live edge, so it waited for THIRTY-ONE SECONDS of video before
    // showing a frame, on a stream whose first segment was ready in 2.25s.
    //
    // Starting one segment back is the whole fix. The cost is honest and it is the reason 3 is
    // the library default: one segment of buffer absorbs less network jitter, so a bad
    // connection can stall where it would previously have coasted. That trade is right here --
    // the alternative is half a minute of black screen on every channel change, and the
    // segments are 10s each, so even one of them is a deep buffer in absolute terms.
    //
    // `segment_s` comes from the session's own `#EXTINF`, so the buffer targets below are
    // derived from what this stream actually produces rather than from what we asked for.
    var segS = (j && j.segment_s) || 2;
    engine = 'hls.js ' + (window.Hls.version || '');
    hls = new window.Hls({
      lowLatencyMode: false,          // LL-HLS needs partial segments; ffmpeg is not making any
      liveSyncDurationCount: 1,       // was the default 3 -- this is the 31s -> 2.5s change
      liveMaxLatencyDurationCount: 6,
      maxBufferLength: Math.max(10, Math.ceil(segS * 2)),
      startFragPrefetch: true,        // fetch the first fragment while the manifest is parsing
      manifestLoadingTimeOut: 20000,  // a cold provider is slow to answer, not broken
      manifestLoadingMaxRetry: 4,
      manifestLoadingRetryDelay: 250,
      levelLoadingRetryDelay: 250,
      fragLoadingRetryDelay: 250,
      backBufferLength: 30            // a live stream does not need a rewind buffer in RAM
    });
    hls.loadSource(src); hls.attachMedia(video);
    hls.on(window.Hls.Events.MANIFEST_PARSED, function () { safePlay(); watch(c); });
    hls.on(window.Hls.Events.ERROR, function (_e, d) {
      if (!d || !d.fatal) return;
      // The player only knows that a request failed. The server knows what the
      // provider actually said, so ask it before writing anything down.
      var tech = 'hls.js: ' + d.type + ' / ' + d.details
               + (d.response && d.response.code ? ' (HTTP ' + d.response.code + ')' : '');
      session().then(function (j) {
        stopTimers();
        var name = (c && c.name) || '';
        nowEl.textContent = name + '  \\u00b7  stopped';
        if (j && j.error) {
          showFail('Playback stopped.',
                   'The box was still connected to your provider when this happened, '
                   + 'and this is what it reported.', j.error, tech);
        } else {
          showFail('Playback stopped.',
                   'The player could not fetch the next part of the stream and the '
                   + 'box reported no upstream error, so the fault is between this '
                   + 'browser and this machine rather than at your provider.',
                   null, tech);
        }
      });
    });
  }

  // A stream can die halfway through, and the honest report for that is the provider's
  // reason -- not a picture that silently stops. Cheap: one GET every five seconds,
  // which doubles as the session heartbeat the reaper keys on.
  function watch(c) {
    if (watchT) clearInterval(watchT);
    watchT = setInterval(function () {
      session().then(function (j) {
        if (!watchT) return;
        if (!j) { stopTimers(); return; }
        if (j.state === 'failed' || j.state === 'ended') {
          stopTimers();
          var name = (c && c.name) || '';
          nowEl.textContent = name + '  \\u00b7  ' + j.state;
          showFail(j.state === 'ended' ? 'The stream ended.' : 'The stream stopped.',
                   j.state === 'ended'
                     ? 'Your provider closed the connection. For a live channel that '
                       + 'usually means the channel went off air.'
                     : 'The box lost the upstream while playing.',
                   j.error || null, null);
        }
      });
    }, 5000);
  }

  // ---- filtering: LOCAL FIRST, then the model only if the local pass was thin --------
  // The perceived speed is the product. Matching the visitor's words against an array
  // already in this browser costs single-digit milliseconds; a round trip to a 7B costs
  // hundreds at best and queues behind whatever else holds the card. So the local pass
  // runs, renders and prints its own measured duration BEFORE any request is made, and
  // the model is asked only when that pass came back thin or left a word unmatched.
  var askBox = document.getElementById('tnask');
  document.getElementById('tnaskgo').addEventListener('click', ask);
  askBox.addEventListener('keydown', function (e) { if (e.key === 'Enter') ask(); });
  document.getElementById('tnaskclear').addEventListener('click', function () {
    filterState = null; askBox.value = ''; askWhy.textContent = '';
    this.hidden = true;
    setModel('', 'model: idle');
    pick(firstCat());
  });

  function setModel(cls, text) {
    modelPill.className = 'tn-model' + (cls ? ' ' + cls : '');
    modelTxt.textContent = text;
  }

  // Words that carry no signal in a channel name. Dropping them is what stops "show me
  // some football" from matching every channel with "me" in it.
  var STOP = {the: 1, and: 1, for: 1, with: 1, show: 1, some: 1, something: 1, any: 1,
              all: 1, please: 1, channel: 1, channels: 1, want: 1, watch: 1, give: 1,
              list: 1, find: 1, that: 1, this: 1, from: 1, you: 1, can: 1, get: 1,
              are: 1, have: 1, anything: 1, everything: 1};

  function tokenise(q) {
    var seen = {}, out = [];
    q.toLowerCase().split(/[^a-z0-9]+/).forEach(function (t) {
      if (t.length < 3 || STOP[t] === 1 || seen[t] === 1) return;
      seen[t] = 1; out.push(t);
    });
    return out;
  }

  // One-character-deletion variants: honest typo tolerance ("motorsprt" -> "motorsport")
  // without the false positives a subsequence match produces, since a subsequence of
  // three letters matches almost any long string.
  function variants(t) {
    var out = [t];
    if (t.length > 4 && t.charAt(t.length - 1) === 's') out.push(t.slice(0, -1));
    if (t.length >= 5) {
      for (var n = 0; n < t.length; n++) out.push(t.slice(0, n) + t.slice(n + 1));
    }
    return out;
  }

  function hits(terms, needAll, fuzzy) {
    var out = [];
    var pats = terms.map(function (t) { return fuzzy ? variants(t) : [t]; });
    for (var i = 0; i < hay.length; i++) {
      var h = hay[i], got = 0;
      for (var k = 0; k < pats.length; k++) {
        var any = false;
        for (var v = 0; v < pats[k].length; v++) {
          if (h.indexOf(pats[k][v]) >= 0) { any = true; break; }
        }
        if (any) { got += 1; if (!needAll) break; }
        else if (needAll) break;
      }
      if (needAll ? got === pats.length : got > 0) out.push(i);
    }
    return out;
  }

  function localPass(q) {
    var t0 = (window.performance && performance.now) ? performance.now() : Date.now();
    var terms = tokenise(q);
    var idx = [], how = 'and';
    if (!terms.length) { idx = []; how = 'none'; }
    else {
      idx = hits(terms, true, false);
      if (!idx.length && terms.length > 1) { idx = hits(terms, false, false); how = 'or'; }
      if (!idx.length) { idx = hits(terms, false, true); how = 'fuzzy'; }
    }
    var unmatched = terms.filter(function (t) { return !hits([t], true, false).length; });
    var t1 = (window.performance && performance.now) ? performance.now() : Date.now();
    return {idx: idx, terms: terms, unmatched: unmatched, how: how,
            ms: Math.round((t1 - t0) * 10) / 10};
  }

  function ask() {
    var q = askBox.value.trim();
    if (!q) return;
    var local = localPass(q);
    if (!local.terms.length) {
      askWhy.textContent = 'Nothing in that to search for \\u2014 try a name, a sport or a genre.';
      return;
    }

    var how = local.how === 'and' ? 'all of your words'
            : local.how === 'or' ? 'any of your words'
            : 'your words with one-character typo tolerance';
    filterState = {idx: local.idx, query: q,
                   why: 'matched ' + how + ' here in this browser, in ' + local.ms + ' ms'};
    document.getElementById('tnaskclear').hidden = false;
    pick('filtered');
    askWhy.textContent = local.idx.length + ' of ' + all.length + ' channels, matched '
      + how + ' \\u2014 measured at ' + local.ms + ' ms in this browser.';

    // The gate is match QUALITY, not question length. A wordy question that already
    // matched well does not need the card; a two-word question that matched nothing does.
    var thin = local.idx.length < 6 || local.unmatched.length > 0;
    if (!thin) {
      setModel('tn-done', 'model: not needed \\u2014 the local pass answered');
      return;
    }
    setModel('tn-think', 'model: thinking\\u2026');
    askModel(q, local);
  }

  function askModel(q, local) {
    // A FLAT KEYWORD LIST, not JSON. Asking this 7B for a JSON object at temperature 0.2
    // makes it loop -- measured: it emitted {"match":["premier league","nfl","nba","mlb",
    // "f1","nfl","nba",... until it hit the token cap, so the object never closed and
    // nothing parsed. One line of comma-separated words it completes cleanly every time.
    // Small models are far better at a flat list than at nested structure; picking the
    // format the model can actually finish is the difference between this working and the
    // fallback firing on every request. If you need a second field, send a SECOND
    // one-line prompt -- do not go back to structured output.
    var prompt = 'List the words to search for in a TV channel list to find: ' + q
      + '\\n\\nRules: reply with ONE line, at most 8 lowercase keywords, comma separated. '
      + 'No sentences, no repeats, no explanation.\\n\\nKeywords:';
    fetch('/api/chat', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({prompt: prompt, temperature: 0.1, max_tokens: 64})
    }).then(function (r) {
      if (!r.ok) throw new Error('chat ' + r.status);
      return r.text();
    }).then(function (txt) {
      var out = '';
      txt.split('\\n').forEach(function (line) {
        if (line.indexOf('data:') !== 0) return;
        try { var j = JSON.parse(line.slice(5)); if (j.delta) out += j.delta; } catch (e) {}
      });
      var first = out.trim().split('\\n').filter(function (l) { return l.trim(); })[0] || '';
      var terms = first.split(',').map(function (t) {
        return t.trim().toLowerCase().replace(/^[^a-z0-9]+|[^a-z0-9 ]+$/g, '');
      }).filter(function (t) { return t.length > 1 && t.length < 24; }).slice(0, 12);
      if (!terms.length) throw new Error('no usable keywords');
      applyModel(q, local, terms);
    }).catch(function (e) {
      // The fallback is SAID OUT LOUD. A silent fallback is how the JSON version looked
      // like it worked for weeks while never once using the model.
      setModel('tn-warn', 'model: unavailable (' + (e.message || e) + ')');
      askWhy.textContent = local.idx.length + ' of ' + all.length + ' channels. The model '
        + 'could not be used, so this is your own words matched directly \\u2014 the '
        + 'result above came from this browser, not the card.';
    });
  }

  function applyModel(q, local, terms) {
    var added = terms.filter(function (t) { return local.terms.indexOf(t) < 0; });
    var union = local.terms.concat(added);
    var wide = hits(union, false, false);
    if (wide.length > local.idx.length) {
      filterState = {idx: wide, query: q,
                     why: 'your words, widened by the model with: ' + added.join(', ')};
      setModel('tn-done', 'model: answered \\u2014 ' + terms.join(', '));
      pick('filtered');
      askWhy.textContent = wide.length + ' of ' + all.length + ' channels. The local pass '
        + 'found ' + local.idx.length + ' in ' + local.ms + ' ms and the model widened it '
        + 'with: ' + added.join(', ') + '.';
    } else {
      setModel('tn-done', 'model: answered \\u2014 added nothing');
      askWhy.textContent = local.idx.length + ' of ' + all.length + ' channels, matched in '
        + local.ms + ' ms in this browser. The model suggested ' + terms.join(', ')
        + ', which found nothing your own words had not \\u2014 so this is the local result.';
    }
  }

  // =====================================================================================
  // THE GUIDE. Time across, channels down, what is on in the cell.
  // =====================================================================================
  //
  // Garrett, on the thing this replaces: "update the damn tuner guide with epg and not that
  // terrible tiny select and deselect shit". The tick grid is still there -- it is how you
  // choose what the guide covers, and 10,072 channels need choosing from -- but it is no
  // longer the only way to look at live TV.
  //
  // The data is the provider's own `get_short_epg`, via `POST /api/streamer/epg`, which returns
  // epoch seconds. The window is 3 hours wide and starts on a half hour so the ruler lands on
  // round numbers.
  //
  // WHAT THIS DOES NOT DO, deliberately:
  //   * it does not invent a cell. A channel the provider publishes nothing for says
  //     "no guide published" in the strip, once, and stays empty. A grid full of
  //     "No Information" boxes is the decorative-indicator rule broken forty times a screen.
  //   * it does not ask for the guide for 10,072 channels. It asks for the rows on screen,
  //     30 at a time -- the route caps at 60 and each row is one request to somebody else's
  //     panel. `next 30 channels` is what pages it.
  //   * it does not fetch for VOD or Series. A film has no schedule; the honest answer is the
  //     list, which the toggle keeps one click away.
  var guideEl = document.getElementById('tnguide');
  var viewsEl = document.getElementById('tnviews'), vMeta = document.getElementById('tnvmeta');
  var vGuide = document.getElementById('tnvguide'), vList = document.getElementById('tnvlist');
  var ticksEl = document.getElementById('tngticks'), rowsEl = document.getElementById('tngrows');
  var whenEl = document.getElementById('tngwhen'), gNote = document.getElementById('tngnote');
  var WINDOW_S = 10800, STEP_S = 5400, GROWS = 30;
  var viewMode = 'list', gLeft = 0, gPage = 0, gCache = {}, gBusy = false, gTick = null;

  function snapHalfHour(t) { return Math.floor(t / 1800) * 1800; }

  function hhmm(epoch) {
    var d = new Date(epoch * 1000);
    var h = d.getHours(), m = d.getMinutes();
    return (h < 10 ? '0' : '') + h + ':' + (m < 10 ? '0' : '') + m;
  }

  function setView(m) {
    viewMode = m;
    vGuide.className = 'tn-vtab' + (m === 'guide' ? ' on' : '');
    vList.className = 'tn-vtab' + (m === 'list' ? ' on' : '');
    vGuide.setAttribute('aria-pressed', m === 'guide' ? 'true' : 'false');
    vList.setAttribute('aria-pressed', m === 'list' ? 'true' : 'false');
    guideEl.hidden = m !== 'guide';
    list.hidden = m === 'guide';
    if (m === 'guide') {
      moreBtn.hidden = true;
      if (!gLeft) gLeft = snapHalfHour(Date.now() / 1000);
      gDraw();
      gLoad();
      if (!gTick) gTick = setInterval(gNowLine, 30000);
    } else {
      renderList();
      if (gTick) { clearInterval(gTick); gTick = null; }
    }
  }
  vGuide.addEventListener('click', function () { setView('guide'); });
  vList.addEventListener('click', function () { setView('list'); });

  document.getElementById('tngback').addEventListener('click', function () {
    gLeft -= STEP_S; gDraw(); gLoad();
  });
  document.getElementById('tngfwd').addEventListener('click', function () {
    gLeft += STEP_S; gDraw(); gLoad();
  });
  document.getElementById('tngnow').addEventListener('click', function () {
    gLeft = snapHalfHour(Date.now() / 1000); gDraw(); gLoad();
  });
  document.getElementById('tngpage').addEventListener('click', function () {
    gPage += 1;
    if (gPage * GROWS >= view.length) gPage = 0;
    gDraw(); gLoad();
  });

  //: The channels this page of the guide is showing: the current filtered view, sliced.
  function gRows() {
    return view.slice(gPage * GROWS, gPage * GROWS + GROWS);
  }

  function gDraw() {
    var rows = gRows();
    var right = gLeft + WINDOW_S;
    whenEl.textContent = hhmm(gLeft) + '\\u2013' + hhmm(right) + '  \\u00b7  rows '
      + (rows.length ? gPage * GROWS + 1 : 0) + '\\u2013' + (gPage * GROWS + rows.length)
      + ' of ' + view.length;

    ticksEl.innerHTML = '';
    for (var t = gLeft; t < right; t += 1800) {
      var tick = document.createElement('div');
      tick.className = 'tn-gtick';
      tick.style.left = ((t - gLeft) / WINDOW_S * 100) + '%';
      tick.style.width = (1800 / WINDOW_S * 100) + '%';
      tick.textContent = hhmm(t);
      ticksEl.appendChild(tick);
    }

    rowsEl.innerHTML = '';
    rows.forEach(function (idx) {
      var c = all[idx];
      var row = document.createElement('div');
      row.className = 'tn-grow';

      var chan = document.createElement('button');
      chan.type = 'button';
      chan.className = 'tn-gchan';
      chan.appendChild(document.createTextNode(c.name || '(unnamed)'));
      var sub = document.createElement('em');
      sub.textContent = groupOf(c);
      chan.appendChild(sub);
      chan.addEventListener('click', function () { tune(c); });
      row.appendChild(chan);

      var strip = document.createElement('div');
      strip.className = 'tn-gstrip';
      gStrip(strip, c);
      row.appendChild(strip);
      rowsEl.appendChild(row);
    });
    gNowLine();
  }

  // One row's worth of programmes, clipped to the window. A programme that starts before the
  // left edge is drawn from the edge, which is how a grid shows something already running --
  // dropping it would leave the row looking empty during a three-hour film.
  function gStrip(strip, c) {
    var sid = String(c.stream_id || '');
    var progs = sid ? gCache[sid] : null;
    var right = gLeft + WINDOW_S;
    strip.innerHTML = '';
    if (!sid) {
      var m = document.createElement('div');
      m.className = 'tn-gnone';
      m.textContent = 'no guide for a pasted playlist \\u2014 an Xtream panel login is what '
        + 'carries one';
      strip.appendChild(m);
      return;
    }
    if (progs === undefined) {
      var l = document.createElement('div');
      l.className = 'tn-gnone';
      l.textContent = 'asking your provider\\u2026';
      strip.appendChild(l);
      return;
    }
    var shownAny = false;
    var now = Date.now() / 1000;
    (progs || []).forEach(function (p) {
      if (p.stop <= gLeft || p.start >= right) return;
      var a = Math.max(p.start, gLeft), b = Math.min(p.stop, right);
      var el = document.createElement('button');
      el.type = 'button';
      el.className = 'tn-gprog' + (p.start <= now && now < p.stop ? ' on' : '');
      el.style.left = ((a - gLeft) / WINDOW_S * 100) + '%';
      el.style.width = (Math.max(60, b - a) / WINDOW_S * 100) + '%';
      el.appendChild(document.createTextNode(p.title || '(untitled)'));
      var u = document.createElement('u');
      u.textContent = hhmm(p.start) + '\\u2013' + hhmm(p.stop);
      el.appendChild(u);
      el.title = (p.title || '') + '  ' + hhmm(p.start) + '\\u2013' + hhmm(p.stop)
               + (p.desc ? '\\n\\n' + p.desc : '');
      el.addEventListener('click', function () { tune(c); });
      strip.appendChild(el);
      shownAny = true;
    });
    if (!shownAny) {
      var n = document.createElement('div');
      n.className = 'tn-gnone';
      n.textContent = (progs && progs.length)
        ? 'nothing published for this part of the day'
        : 'no guide published for this channel';
      strip.appendChild(n);
    }
  }

  // The "now" marker is a reading, so it is only drawn when now is actually inside the
  // window being displayed. Pinning it to the edge while you page forward would be a
  // decoration that always agrees with itself.
  function gNowLine() {
    var old = rowsEl.querySelectorAll('.tn-gline');
    for (var i = 0; i < old.length; i++) old[i].remove();
    var now = Date.now() / 1000;
    if (now < gLeft || now > gLeft + WINDOW_S) return;
    var pct = (now - gLeft) / WINDOW_S * 100;
    var strips = rowsEl.querySelectorAll('.tn-gstrip');
    for (var n = 0; n < strips.length; n++) {
      var line = document.createElement('div');
      line.className = 'tn-gline';
      line.style.left = pct + '%';
      strips[n].appendChild(line);
    }
  }

  // Ask for the rows on screen that we have not already got, and nothing else.
  function gLoad() {
    var c = creds();
    if (c.mode !== 'xtream') {
      gNote.textContent = 'A pasted M3U carries no guide endpoint, so there is nothing to '
        + 'ask for. Log in with an Xtream panel and the guide fills in from your '
        + 'provider\\u2019s own schedule.';
      return;
    }
    var want = [];
    gRows().forEach(function (idx) {
      var sid = String(all[idx].stream_id || '');
      if (sid && gCache[sid] === undefined) want.push(sid);
    });
    if (!want.length || gBusy) { if (!want.length) gDraw(); return; }
    gBusy = true;
    gNote.textContent = 'asking your provider for ' + want.length + ' channel'
      + (want.length === 1 ? '' : 's') + ' of guide\\u2026';
    fetch('/api/streamer/epg', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({server: c.host, username: c.user, password: c.pass,
                            stream_ids: want, limit: 8})
    }).then(function (r) {
      return r.json().then(function (j) { return {ok: r.ok, j: j}; });
    }).then(function (res) {
      gBusy = false;
      if (!res.ok) {
        gNote.textContent = 'The guide request failed: '
          + ((res.j && res.j.detail) ? String(res.j.detail) : 'no reason given')
          + '  Nothing on this box filters a guide; this is what came back.';
        return;
      }
      // A channel that answered with an empty list is CACHED as empty, not left unknown --
      // otherwise every redraw asks the panel again for a channel that has no guide, which
      // is how a page ends up hammering somebody else's server.
      want.forEach(function (sid) {
        gCache[sid] = (res.j.channels && res.j.channels[sid]) || [];
      });
      var withData = 0;
      want.forEach(function (sid) { if (gCache[sid].length) withData += 1; });
      var failed = Object.keys(res.j.failed || {}).length;
      gNote.textContent = withData + ' of ' + want.length + ' channels published a guide'
        + (failed ? ', ' + failed + ' request' + (failed === 1 ? '' : 's') + ' failed' : '')
        + '  \\u00b7  ' + (res.j.elapsed_ms || 0) + ' ms, straight from your provider'
        + '  \\u00b7  nothing about it is stored on this box.'
        + (withData < want.length
            ? '  A channel with no guide is one your provider publishes no schedule for; '
              + 'it is not hidden and it still plays.'
            : '');
      // Failures are cached as empty too, but the note above has already said how many
      // failed -- so the row reads "no guide published" while the count says why.
      gDraw();
    }).catch(function (e) {
      gBusy = false;
      gNote.textContent = 'Could not reach this box for the guide (' + String(e && e.message)
        + '). Your provider was never contacted.';
    });
  }

  // The guide only makes sense for live TV, and `render()` is what knows the category
  // changed. Wrapping it here rather than editing it keeps one definition of "the view
  // has changed" instead of two that can drift.
  var renderInner = render;
  render = function () {
    renderInner();
    viewsEl.hidden = !all.length;
    // `renderInner` decides the pager from the list's own paging state, so in guide view it
    // has to be put back -- the list it pages is hidden.
    if (viewMode === 'guide') { moreBtn.hidden = true; list.hidden = true; }
    var live = (cat === 'live' || cat === 'fav' || cat === 'filtered');
    vGuide.disabled = !live;
    vMeta.textContent = live ? '' : 'The guide is for live TV. ' + catLabel(cat)
      + ' has no schedule to draw, so this stays a list.';
    if (!live && viewMode === 'guide') { setView('list'); return; }
    if (viewMode === 'guide') { gPage = 0; gDraw(); gLoad(); }
  };

  // =====================================================================================
  // PLAYBACK OPTIONS, SETTINGS AND STATISTICS
  // =====================================================================================
  //
  // Garrett asked for this directly. Every number is read from the player or from the
  // session document; `-` means it has not been reported yet, which is itself a reading.
  // There is no synthetic "health" score and no bar that moves on a timer.
  var statsEl = document.getElementById('tnstats');
  var psLevel = document.getElementById('ps-level'), psAudio = document.getElementById('ps-audio');
  var psWhy = document.getElementById('ps-why');
  var statsT = null, lastSession = null;

  function put(id, text) { document.getElementById(id).textContent = text; }

  function fmtRate(bps) {
    if (!bps || bps < 1) return '-';
    if (bps >= 1e6) return (bps / 1e6).toFixed(2) + ' Mb/s';
    return Math.round(bps / 1e3) + ' kb/s';
  }

  function fmtBytes(n) {
    if (!n) return '-';
    if (n >= 1e9) return (n / 1e9).toFixed(2) + ' GB';
    if (n >= 1e6) return (n / 1e6).toFixed(1) + ' MB';
    return Math.round(n / 1e3) + ' kB';
  }

  function bufferAhead() {
    try {
      for (var i = 0; i < video.buffered.length; i++) {
        if (video.buffered.start(i) <= video.currentTime
            && video.currentTime <= video.buffered.end(i)) {
          return video.buffered.end(i) - video.currentTime;
        }
      }
    } catch (e) { /* buffered throws on a detached element */ }
    return null;
  }

  function statsTick() {
    var q = null;
    if (video.getVideoPlaybackQuality) { q = video.getVideoPlaybackQuality(); }
    var w = video.videoWidth, h = video.videoHeight;
    put('ps-res', (w && h) ? w + ' \\u00d7 ' + h : '-');
    var buf = bufferAhead();
    put('ps-buf', buf === null ? '-' : buf.toFixed(1) + ' s');
    put('ps-drop', q ? String(q.droppedVideoFrames) : '-');
    put('ps-dec', q ? String(q.totalVideoFrames) : '-');
    put('ps-eng', engine || '-');

    if (hls) {
      // `currentLevel` is **-1 while the level is being chosen automatically**, which is the
      // default and therefore the normal case -- so reading it alone printed `-` for the level
      // bitrate on a stream that was plainly playing at a known bitrate. `loadLevel` is the
      // index actually being fetched, and it resolves the auto choice. Measured: 286 Mb/s of
      // throughput and 2 levels beside a bitrate of `-`, which is what gave it away.
      var li = hls.currentLevel;
      if (li < 0 && typeof hls.loadLevel === 'number') li = hls.loadLevel;
      var lv = (li >= 0 && hls.levels) ? hls.levels[li] : null;
      put('ps-rate', lv ? fmtRate(lv.bitrate)
                          + (hls.currentLevel < 0 ? ' (auto)' : '') : '-');
      put('ps-tp', fmtRate(hls.bandwidthEstimate));
    } else {
      put('ps-rate', '-');
      put('ps-tp', '-');
    }
    var j = lastSession;
    put('ps-seg', j && j.segment_s ? Number(j.segment_s).toFixed(2) + ' s' : '-');
    put('ps-segn', j && j.segments !== undefined ? String(j.segments) : '-');
    put('ps-in', j ? fmtBytes(j.bytes_in) : '-');
    put('ps-mode', j && j.mode ? (j.mode === 'direct' ? 'stream copy, no GPU' : String(j.mode))
                              : '-');
    put('ps-age', j && j.age_s !== undefined ? Math.round(j.age_s) + ' s' : '-');
  }

  function statsStart(c, j) {
    lastSession = j || null;
    statsEl.hidden = false;
    if (statsT) clearInterval(statsT);
    statsT = setInterval(function () {
      statsTick();
      // The session half of the panel comes from the same poll the watchdog already runs,
      // one level up; this only refreshes the numbers it left behind.
      session().then(function (s) { if (s) { lastSession = s; } });
    }, 1000);
    statsTick();
    fillLevels();
    psWhy.textContent = 'Quality is your provider\\u2019s -- this box stream-copies and does '
      + 'not re-encode, so there is one level unless they publish more. Everything above is '
      + 'measured by the player in this browser or read from the session on the box.';
  }

  function fillLevels() {
    while (psLevel.options.length > 1) psLevel.remove(1);
    while (psAudio.options.length > 1) psAudio.remove(1);
    if (!hls) return;
    (hls.levels || []).forEach(function (lv, i) {
      var o = document.createElement('option');
      o.value = String(i);
      o.textContent = (lv.height ? lv.height + 'p' : 'level ' + (i + 1))
        + (lv.bitrate ? ' \\u00b7 ' + fmtRate(lv.bitrate) : '');
      psLevel.appendChild(o);
    });
    (hls.audioTracks || []).forEach(function (tr, i) {
      var o = document.createElement('option');
      o.value = String(i);
      o.textContent = tr.name || tr.lang || ('track ' + (i + 1));
      psAudio.appendChild(o);
    });
  }

  psLevel.addEventListener('change', function () {
    if (hls) hls.currentLevel = parseInt(psLevel.value, 10);
  });
  psAudio.addEventListener('change', function () {
    var v = parseInt(psAudio.value, 10);
    if (hls && v >= 0) hls.audioTrack = v;
  });
  document.getElementById('ps-pip').addEventListener('click', function () {
    if (!video.requestPictureInPicture) {
      psWhy.textContent = 'This browser does not offer picture-in-picture.';
      return;
    }
    video.requestPictureInPicture().catch(function (e) {
      psWhy.textContent = 'Picture-in-picture was refused: ' + String(e && e.message);
    });
  });
  document.getElementById('ps-full').addEventListener('click', function () {
    var el = document.getElementById('tnplayer');
    if (el.requestFullscreen) { el.requestFullscreen().catch(function () {}); }
  });

  // =====================================================================================
  // HANDING THE STREAM TO /streamer-watch.html
  // =====================================================================================
  //
  // Garrett: "You can make the stream move to its own symoneural.com/tuner/watch or something
  // so we can almost like full screen for improved guide pip settings etc etc."
  //
  // The offer only appears once a channel is actually playing. A button that says "watch full
  // width" beside a stream that never opened is an invitation to a black rectangle on a second
  // page, and the whole design of this surface is that it says what is true.
  //
  // NOTHING GOES IN THE URL. The stream URL carries the visitor's provider credentials and
  // uvicorn logs a request line, so the channel travels in localStorage -- the same place the
  // credentials already live, and never off this browser.
  var prow = document.getElementById('tnprow'), watchBtn = document.getElementById('tnwatch');
  var watchWhy = document.getElementById('tnwatchwhy');
  var WK = 'symoneural.streamer.watch';
  var watchable = null;

  function offerWatch(c) {
    watchable = c || null;
    prow.hidden = !watchable;
    watchWhy.textContent = '';
  }

  watchBtn.addEventListener('click', function () {
    if (!watchable) return;
    try {
      localStorage.setItem(WK, JSON.stringify({
        name: watchable.name || '', url: watchable.url || '',
        stream_id: watchable.stream_id || '', group: groupOf(watchable), sid: sid || ''}));
    } catch (e) {
      // Private mode, or a full quota. Say so and stay here rather than navigating to a page
      // that would have nothing to open and no way to explain why.
      watchWhy.textContent = 'This browser refused to store the handoff ('
        + String(e && e.message ? e.message : e) + '), so the other page would open empty. '
        + 'Playback here is unaffected.';
      return;
    }
    // The session is handed over alive, not released: the watch page adopts it. See `letGo`.
    handingOff = true;
    location.href = '/streamer-watch.html';
  });

  // `play()` is where a stream actually becomes a picture, so that is where the panel
  // starts reading -- and where the handoff becomes truthful. Wrapped rather than edited,
  // same reason as `render()` above.
  var playInner = play;
  play = function (src, c, j) {
    playInner(src, c, j);
    statsStart(c, j);
    offerWatch(c);
  };

  // Withdraw the offer the moment a different channel is asked for: until that one is playing
  // there is nothing to hand over, and the id in the old offer is about to be released.
  var tuneInner = tune;
  tune = function (c) {
    offerWatch(null);
    tuneInner(c);
  };

  var stopInner = stopTimers;
  stopTimers = function () {
    stopInner();
    if (statsT) { clearInterval(statsT); statsT = null; }
  };
})();
</script>"""


# ======================================================================================
# THE WATCH PAGE  --  frontend/site/pages/streamer-watch.html
# ======================================================================================
#
# Garrett: "You can make the stream move to its own symoneural.com/tuner/watch or something
# so we can almost like full screen for improved guide pip settings etc etc."
#
# This is a SEPARATE, SELF-CONTAINED page. It does not share code with STREAMER_JS, and three
# blocks below are duplicated from it deliberately -- the hls.js configuration, the
# `state === 'live' && segments > 0` gate, and the release beacon. Each says so where it
# sits, and names STREAMER_JS as the original, so a change to one is findable from the other.
#
# The alternative was to split STREAMER_JS into chunks both pages concatenate. The "interface"
# that would create is mutable closure state (`all`, `view`, `cat`) plus reassigned function
# bindings (`render = function ...`), which has no enforcement point and no failure signal:
# the failure mode is a dead script on a page that still looks right. This repo has already
# shipped exactly that once -- a suite passed 22/22 while streamer.html's script was dead.
#
# WHY THE FILE IS `streamer-watch.html` AND NOT `/streamer/watch`, which is what was asked for:
#   * scripts/deploy.sh publishes `find "$SRC" -maxdepth 1 -type f`, so a
#     site/streamer/watch/index.html form is never copied into the webroot at all.
#   * ops/Caddyfile delegates an explicit list of top-level paths to FastAPI. A new one
#     404s until `sudo ./scripts/install-caddy.sh` runs, and that needs a password.
# The flat file is the form that deploys today. .claude/HANDOVER.md records the two edits
# that give the pretty path later; this page needs no change when they happen.
#
# THE HANDOFF. streamer.html writes {name, url, stream_id, group, release} into localStorage
# under `symoneural.streamer.watch` and navigates here. Nothing goes in the URL: the stream URL
# carries the visitor's own provider credentials and uvicorn logs a request line. `release`
# is the outgoing session id and is passed straight through as /tune's `release` field, so
# the box frees that slot inside the same request that allocates the new one -- a handoff
# cannot momentarily hold both streamers of a two-slot box, which would refuse itself with 503.
#
# This is a RAW Python string, unlike STREAMER_JS. That removes the escaping trap that killed
# streamer.html's script once: `\n` and `·` written here reach the JavaScript unchanged.
WATCH_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>SyMoNeuRaL Streamer — watch</title>
<meta name="description" content="Near-fullscreen playback for the SyMoNeuRaL streamer: the guide, the readings and picture-in-picture over the picture itself.">
<link rel="stylesheet" href="/symoneural.css">
<link rel="icon" href="/favicon-32.png" sizes="32x32" type="image/png">
<link rel="icon" href="/favicon-16.png" sizes="16x16" type="image/png">
<link rel="apple-touch-icon" href="/apple-touch-icon.png">
<meta name="theme-color" content="#0e100f">
<style>
/* ---- the watch surface, 2026-08-17 -----------------------------------------------
   Every selector is `w`-prefixed or an id, and every one was grepped against
   frontend/site/css/symoneural.css, frontend/site/css/rack-detail.css and the streamer page's own `tn-` block
   before being written: no name here has a prior definition anywhere.

   There is no text-overflow:ellipsis in this file and there must never be one. The
   channel name and the programme title are the two things a viewer is reading.

   The stylesheet above is linked for its tokens and its font stack. This block comes
   after it so the four rules that fight it -- html/body height, margin, overflow and
   background -- win on document order at equal specificity, and `body.wpage` is used
   for the rest so nothing depends on that. */
html, body.wpage{height:100%; margin:0; overflow:hidden; background:#000}

#wstage{position:fixed; inset:0; background:#000}
#tnvideo{position:absolute; inset:0; width:100%; height:100%; background:#000}

/* The bar dims itself out of the way, and comes back on any pointer or key. It is never
   `hidden`: a control the viewer cannot find is worse than one they can see through. */
#wbar{
  position:absolute; left:0; right:0; top:0; z-index:4; display:flex; gap:16px;
  align-items:flex-start; padding:13px 18px 34px; color:#e9efe9;
  font:500 13px/1.45 ui-sans-serif,-apple-system,"Segoe UI",Roboto,Inter,sans-serif;
  background:linear-gradient(180deg,rgba(5,7,6,.94) 0%,rgba(5,7,6,.72) 55%,rgba(5,7,6,0) 100%);
  transition:opacity .28s ease;
}
#wbar.wdim{opacity:0; pointer-events:none}
#wtitle{flex:1 1 auto; min-width:0}
#wname{display:block; font-size:16.5px; font-weight:700; color:#fff}
#wgroup{font-size:11.5px; font-weight:500; color:#93a597; letter-spacing:.04em}
#tnnow{margin:3px 0 0; font-size:12.5px; color:#9fb0a4}
#wnn{margin:5px 0 0; font-size:12.8px; color:#d6e5da; max-width:78ch}
#wnn i{font-style:normal; color:#8fa295; font-weight:600; margin-right:5px}
#wnn s{text-decoration:none; color:#93a597}
#wbtns{flex:0 0 auto; display:flex; flex-wrap:wrap; gap:8px; justify-content:flex-end}

.wb{
  appearance:none; -webkit-appearance:none; background:rgba(20,25,22,.86); color:#e9efe9;
  border:1px solid rgba(126,146,133,.5); border-radius:9px; padding:7px 12px;
  font:600 12.4px/1.2 inherit; cursor:pointer;
}
.wb:hover:not(:disabled){border-color:rgba(46,224,138,.75); color:#fff}
.wb.won{border-color:rgba(46,224,138,.85); color:#5ee9a4}
.wb:disabled{opacity:.42; cursor:default}
a.wb{text-decoration:none; display:inline-block}

/* Panels. `[hidden]` is a UA rule and loses to any author `display:` on a class, which is
   how two components on this site have shipped visible while reporting hidden. So the
   attribute is honoured explicitly, right here, next to the rule that would beat it.

   `top` is the measured height of the bar, published as --wbarh by the script on load and on
   resize. A panel at top:0 covered the bar completely, and the bar is where Statistics, PiP
   and full screen live -- so with the guide open those four controls could not be clicked at
   all. Playwright caught it: "<button id=wgnow> from <aside id=wguide> subtree intercepts
   pointer events". The fallback in the var() is a sane first paint, not a layout assumption:
   the real number is set before the first panel can be opened. */
.wpanel{
  position:absolute; top:var(--wbarh,104px); right:0; bottom:0; z-index:6; width:min(880px,96vw);
  display:flex; flex-direction:column; color:#e9efe9;
  background:rgba(7,10,8,.975); border-left:1px solid rgba(126,146,133,.36);
  border-top:1px solid rgba(126,146,133,.36); border-top-left-radius:12px;
  font:500 13px/1.45 ui-sans-serif,-apple-system,"Segoe UI",Roboto,Inter,sans-serif;
}
.wpanel[hidden]{display:none}
.whead{
  display:flex; align-items:center; gap:10px; padding:12px 14px;
  border-bottom:1px solid rgba(126,146,133,.24);
}
.whead h2{
  margin:0; flex:1 1 auto; font:700 11.5px/1.2 inherit; letter-spacing:.12em;
  text-transform:uppercase; color:#93a597;
}
.wbody{flex:1 1 auto; min-height:0; overflow-y:auto; padding:12px 14px}
.wnote{margin:10px 0 0; font:500 11.6px/1.5 inherit; color:#93a597}
.wnote b{color:#c3d3c8}

/* guide */
.wgtools{display:flex; flex-wrap:wrap; gap:8px; align-items:center; margin:0 0 10px}
#wq{
  flex:1 1 220px; min-width:0; background:rgba(16,20,18,.9); color:#e9efe9;
  border:1px solid rgba(126,146,133,.45); border-radius:9px; padding:8px 11px;
  font:500 13px/1.3 inherit;
}
#wq:focus{outline:none; border-color:rgba(46,224,138,.7)}
#wgwhen{font:600 12px/1.2 inherit; color:#c3d3c8}
#wgscroll{overflow-x:auto}
#wgticks{position:relative; height:28px; min-width:560px; margin-left:170px}
.wgtick{
  position:absolute; top:0; bottom:0; padding-left:6px; border-left:1px solid rgba(126,146,133,.28);
  font:600 var(--t7)/28px inherit; color:#8fa295; white-space:nowrap;
}
.wgrow{display:flex; border-bottom:1px solid rgba(126,146,133,.14)}
.wgrow:last-child{border-bottom:0}
.wgchan{
  flex:0 0 170px; display:flex; flex-direction:column; gap:2px; padding:8px 10px;
  border:0; border-right:1px solid rgba(126,146,133,.24); background:transparent;
  text-align:left; color:#e9efe9; font:600 12.2px/1.3 inherit; cursor:pointer;
}
.wgchan:hover{color:#5ee9a4}
.wgchan.wcur{color:#5ee9a4}
.wgchan em{font-style:normal; font-size:var(--t7); font-weight:500; color:#8fa295}
.wgstrip{position:relative; flex:1 1 auto; min-width:560px; min-height:46px}
.wgprog{
  position:absolute; top:4px; bottom:4px; overflow:hidden; padding:5px 8px; cursor:pointer;
  border:1px solid rgba(126,146,133,.3); border-radius:8px; background:rgba(18,23,20,.92);
  text-align:left; color:#c3d3c8; font:600 11.4px/1.3 inherit;
}
.wgprog:hover{border-color:rgba(46,224,138,.55); color:#fff}
.wgprog.wgon{border-color:rgba(46,224,138,.6); background:rgba(24,48,35,.92); color:#eaffef}
.wgprog u{display:block; text-decoration:none; font:500 var(--t7)/1.3 inherit; color:#8fa295}
.wgnone{
  position:absolute; inset:4px 6px; display:flex; align-items:center;
  font:500 11.1px/1.4 inherit; color:#8fa295;
}
.wgline{position:absolute; top:0; bottom:0; width:2px; background:rgba(46,224,138,.75)}

/* statistics */
.wsgrid{display:grid; grid-template-columns:repeat(auto-fit,minmax(170px,1fr)); gap:8px}
.wscell{
  border:1px solid rgba(126,146,133,.24); border-radius:9px; padding:8px 10px;
  background:rgba(14,18,16,.85);
}
.wscell b{display:block; font:600 var(--t7)/1.3 inherit; letter-spacing:.06em;
          text-transform:uppercase; color:#8fa295}
.wscell span{display:block; margin-top:3px; font:600 14px/1.3 inherit; color:#e9efe9}
.wsrow{display:flex; flex-wrap:wrap; gap:10px; align-items:center; margin-top:12px}
.wsrow label{font:600 11.4px/1.2 inherit; color:#93a597}
.wsrow select{
  background:rgba(16,20,18,.9); color:#e9efe9; border:1px solid rgba(126,146,133,.45);
  border-radius:8px; padding:6px 9px; font:500 12.4px/1.2 inherit;
}

/* why a stream did not play. Same job, same words, as the panel on streamer.html. */
#tnfail{
  position:absolute; z-index:5; left:50%; top:50%; transform:translate(-50%,-50%);
  width:min(620px,90vw); padding:18px 20px; border-radius:14px;
  background:rgba(8,11,9,.965); border:1px solid rgba(214,140,90,.55); color:#e9efe9;
  font:500 13px/1.5 ui-sans-serif,-apple-system,"Segoe UI",Roboto,Inter,sans-serif;
}
#tnfail[hidden]{display:none}
#tnfail h4{margin:0 0 8px; font:700 15px/1.3 inherit; color:#ffd7a8}
#tnfail p{margin:0; color:#d6e5da}
#tnfail .wsaid{
  display:block; margin-top:9px; padding:8px 10px; border-radius:8px;
  background:rgba(20,25,22,.9); border:1px solid rgba(126,146,133,.3);
  font:500 12.2px/1.45 ui-monospace,SFMono-Regular,Menlo,monospace; color:#c3d3c8;
}
#tnfail details{margin-top:10px}
#tnfail summary{cursor:pointer; font:600 11.6px/1.3 inherit; color:#93a597}
#tnfail code{
  display:block; margin-top:6px; font:500 11.6px/1.5 ui-monospace,SFMono-Regular,Menlo,monospace;
  color:#8fa295; word-break:break-word;
}

/* playback blocked by the browser, not by anything here */
#wplay{
  position:absolute; z-index:5; left:50%; top:50%; transform:translate(-50%,-50%);
  display:flex; align-items:center; gap:14px; cursor:pointer;
  padding:16px 22px; border-radius:14px; color:#eaffef;
  background:rgba(10,26,17,.94); border:1px solid rgba(46,224,138,.6);
  font:600 14px/1.45 ui-sans-serif,-apple-system,"Segoe UI",Roboto,Inter,sans-serif;
  max-width:min(520px,90vw); text-align:left;
}
#wplay[hidden]{display:none}
#wplay b{font-size:26px; line-height:1; color:#5ee9a4}
#wplay:hover{border-color:rgba(46,224,138,.95)}

/* nothing handed over */
#wcold{
  position:absolute; z-index:3; left:50%; top:50%; transform:translate(-50%,-50%);
  width:min(560px,90vw); text-align:center; color:#e9efe9;
  font:500 14px/1.6 ui-sans-serif,-apple-system,"Segoe UI",Roboto,Inter,sans-serif;
}
#wcold[hidden]{display:none}
#wcold h1{margin:0 0 10px; font:700 22px/1.25 inherit}
#wcold p{margin:0 0 16px; color:#a9b9ad}
</style>
</head>
<body class="wpage">

<div id="wstage">
  <!-- Native controls, deliberately. Scrub, volume, captions and the browser's own
       full-screen button are all keyboard-reachable and already understood; the bar above
       adds only what the browser has no opinion about. -->
  <video id="tnvideo" controls playsinline></video>

  <div id="wbar">
    <div id="wtitle">
      <b id="wname">&nbsp;</b>
      <span id="wgroup"></span>
      <p id="tnnow"></p>
      <p id="wnn"></p>
    </div>
    <div id="wbtns">
      <a class="wb" href="/streamer.html" id="wback">&larr; Streamer</a>
      <button type="button" class="wb" id="wgbtn">Guide</button>
      <button type="button" class="wb" id="wsbtn">Statistics</button>
      <button type="button" class="wb" id="wpip">Picture in picture</button>
      <button type="button" class="wb" id="wfull">Full screen</button>
    </div>
  </div>

  <div id="tnfail" hidden>
    <h4 id="tnfailh"></h4>
    <p id="tnfailp"></p>
    <details id="tnfaild" hidden>
      <summary>Technical detail</summary>
      <code id="tnfailc"></code>
    </details>
  </div>

  <!-- Shown only when the browser has declined to start playback by itself. It is not a
       decoration and it is not always there: it appears because a reading said the element is
       paused. Pressing it is the user gesture the autoplay policy always accepts. -->
  <button type="button" id="wplay" hidden>
    <b>&#9658;</b>
    <span>This browser blocked playback from starting on its own. Press to play.</span>
  </button>

  <div id="wcold" hidden>
    <h1>Nothing to watch yet.</h1>
    <p id="wcoldp">This page plays one channel at a time, full width. Pick one on the streamer
      and it will open here.</p>
    <p><a class="wb" href="/streamer.html">Open the streamer</a></p>
  </div>

  <!-- The guide. Time across, channels down, and clicking a cell changes channel without
       leaving the picture. The channel list is fetched the first time this panel opens and
       not before: somebody who came here to watch full screen should not pay for a
       catalogue request they never asked for. -->
  <aside class="wpanel" id="wguide" hidden aria-label="Guide">
    <div class="whead">
      <h2>Guide</h2>
      <button type="button" class="wb" id="wgback">&minus;90 min</button>
      <button type="button" class="wb" id="wgnow">now</button>
      <button type="button" class="wb" id="wgfwd">90 min &rarr;</button>
      <button type="button" class="wb" id="wgpage">next 30</button>
      <button type="button" class="wb" id="wgclose">Close</button>
    </div>
    <div class="wbody">
      <div class="wgtools">
        <input id="wq" type="text" autocomplete="off"
               placeholder="Find a channel — name or group">
        <span id="wgwhen"></span>
      </div>
      <div id="wgscroll">
        <div id="wgticks"></div>
        <div id="wgrows"></div>
      </div>
      <p class="wnote" id="wgnote"></p>
    </div>
  </aside>

  <!-- Options, settings and statistics. Every figure is a reading: resolution and bitrate
       from the level actually playing, buffer from the video element's own buffered ranges,
       dropped frames from getVideoPlaybackQuality(), throughput from hls.js's estimate, and
       the rest from the session document this box publishes. A figure the player has not
       reported yet reads `-`, which is itself the reading. -->
  <aside class="wpanel" id="wstats" hidden aria-label="Playback statistics">
    <div class="whead">
      <h2>Playback options, settings and statistics</h2>
      <button type="button" class="wb" id="wsclose">Close</button>
    </div>
    <div class="wbody">
      <div class="wsgrid">
        <div class="wscell"><b>Resolution</b><span id="ps-res">-</span></div>
        <div class="wscell"><b>Level bitrate</b><span id="ps-rate">-</span></div>
        <div class="wscell"><b>Measured throughput</b><span id="ps-tp">-</span></div>
        <div class="wscell"><b>Buffer ahead</b><span id="ps-buf">-</span></div>
        <div class="wscell"><b>Dropped frames</b><span id="ps-drop">-</span></div>
        <div class="wscell"><b>Frames decoded</b><span id="ps-dec">-</span></div>
        <div class="wscell"><b>Segment length</b><span id="ps-seg">-</span></div>
        <div class="wscell"><b>Segments held</b><span id="ps-segn">-</span></div>
        <div class="wscell"><b>From the provider</b><span id="ps-in">-</span></div>
        <div class="wscell"><b>Path</b><span id="ps-mode">-</span></div>
        <div class="wscell"><b>Session age</b><span id="ps-age">-</span></div>
        <div class="wscell"><b>Player</b><span id="ps-eng">-</span></div>
      </div>
      <div class="wsrow">
        <label for="ps-level">Quality</label>
        <select id="ps-level"><option value="-1">auto</option></select>
        <label for="ps-audio">Audio</label>
        <select id="ps-audio"><option value="-1">as sent</option></select>
      </div>
      <p class="wnote" id="ps-why"></p>
      <p class="wnote">Keys: <b>g</b> guide, <b>s</b> statistics, <b>f</b> full screen,
        <b>p</b> picture in picture, <b>Esc</b> closes a panel.</p>
    </div>
  </aside>
</div>

<noscript>
  <p style="color:#e9efe9;font:500 15px/1.6 sans-serif;padding:24px">
    This page is a video player and needs JavaScript. The rest of the site does not.
  </p>
</noscript>

<script src="/hls.js"></script>
<script>
(function () {
  'use strict';
  // The visitor's credentials, written by streamer.html and read here. Same key, same browser,
  // same promise: they are never posted anywhere but into the body of a request to this box,
  // which registers them for the life of a stream and scrubs them from every error path.

  // ---- Carry the visitor's own data across the rename. ----------------------------
  // These keys were `symoneural.streamer*` until the Streamer and the Guide were merged into
  // the Streamer. The whole promise of this surface is that the playlist, the favourites
  // and the credentials live in THIS browser and are never stored on the box -- which
  // means there is nowhere to restore them from. Renaming the namespace without carrying
  // the data would silently empty everything the visitor typed, and look like data loss
  // because it would be.
  //
  // Prefix-generic on purpose: a seventh key added later is carried without anyone
  // remembering to add it here. Idempotent on purpose: it never overwrites a value that
  // already exists under the new name, so a second visit cannot roll a visitor back to
  // what they had before the rename.
  try {
    var _OLD = 'symoneural.tuner', _NEW = 'symoneural.streamer';   // NOTE: _OLD is the RETIRED prefix and must stay spelled that way
    for (var _i = localStorage.length - 1; _i >= 0; _i--) {
      var _k = localStorage.key(_i);
      if (!_k || (_k !== _OLD && _k.indexOf(_OLD + '.') !== 0)) continue;
      var _nk = _NEW + _k.slice(_OLD.length);
      if (localStorage.getItem(_nk) === null) localStorage.setItem(_nk, localStorage.getItem(_k));
      localStorage.removeItem(_k);
    }
  } catch (_e) { /* private mode, or storage full: the page still works without history */ }
  var K = 'symoneural.streamer';
  // The handoff: which channel this page was opened on. Rewritten on every channel change so
  // a reload resumes what was playing rather than dropping back to a black screen.
  var WK = 'symoneural.streamer.watch';

  var video = document.getElementById('tnvideo');
  var bar = document.getElementById('wbar');
  var nameEl = document.getElementById('wname'), groupEl = document.getElementById('wgroup');
  var nowEl = document.getElementById('tnnow'), nnEl = document.getElementById('wnn');
  var coldEl = document.getElementById('wcold'), coldP = document.getElementById('wcoldp');
  var failEl = document.getElementById('tnfail'), failH = document.getElementById('tnfailh'),
      failP = document.getElementById('tnfailp'), failD = document.getElementById('tnfaild'),
      failC = document.getElementById('tnfailc');
  var gPanel = document.getElementById('wguide'), sPanel = document.getElementById('wstats');
  var ticksEl = document.getElementById('wgticks'), rowsEl = document.getElementById('wgrows');
  var whenEl = document.getElementById('wgwhen'), gNote = document.getElementById('wgnote');
  var qBox = document.getElementById('wq');
  var psLevel = document.getElementById('ps-level'), psAudio = document.getElementById('ps-audio');
  var psWhy = document.getElementById('ps-why');

  var cfg = null, chan = null, hls = null, sid = null;
  // Which player the stream was actually handed to, recorded at the moment of the choice
  // rather than inferred from `hls` being non-null. Inferring it was wrong in a way that
  // mattered: `statsStart()` runs at the top of `play()`, BEFORE the engine is picked, and its
  // first tick is synchronous -- so on a channel that dies inside a second (a dead channel,
  // which is common) `stopTimers()` cleared the interval before any later tick, and the panel
  // sat there reporting "the browser's own HLS" for a stream hls.js had in fact been given.
  // That is the same misdirection as the original bug: the one readout that says which player
  // is running has to be right when the picture is black, because that is when it gets read.
  var engine = '';
  var waitT = null, watchT = null, hiddenT = null, statsT = null, lastSession = null;

  try { cfg = JSON.parse(localStorage.getItem(K) || 'null'); } catch (e) { cfg = null; }

  function creds() {
    if (!cfg) return {mode: 'none'};
    if (cfg.mode === 'xtream') {
      return {mode: 'xtream', host: cfg.host || '', user: cfg.user || '', pass: cfg.pass || ''};
    }
    return {mode: 'm3u', url: cfg.url || ''};
  }

  // ---- the bar gets out of the way -------------------------------------------------
  // Three seconds of no input and it fades. It never fades while a panel is open, while a
  // failure is on screen, or while nothing is playing -- in each of those cases the thing
  // the viewer needs next is in the bar.
  var dimT = null;
  function pinned() {
    return !gPanel.hidden || !sPanel.hidden || !failEl.hidden || !coldEl.hidden
        || !document.getElementById('wplay').hidden;
  }
  function wake() {
    bar.classList.remove('wdim');
    if (dimT) clearTimeout(dimT);
    dimT = setTimeout(function () {
      if (!pinned()) bar.classList.add('wdim');
    }, 3000);
  }
  ['pointermove', 'pointerdown', 'keydown', 'touchstart', 'wheel'].forEach(function (ev) {
    document.addEventListener(ev, wake, {passive: true});
  });
  wake();

  // How far down the panels start, so they cannot cover the bar's own controls. Measured from
  // the bar's CONTENT rather than its box: the box carries 34px of bottom padding that exists
  // only to let the gradient fade out, and a panel pushed down by it would leave a stripe of
  // video between the two. Re-measured on resize because the button cluster wraps.
  function barHeight() {
    var t = document.getElementById('wtitle').getBoundingClientRect().bottom;
    var b = document.getElementById('wbtns').getBoundingClientRect().bottom;
    document.documentElement.style.setProperty('--wbarh', Math.round(Math.max(t, b) + 10) + 'px');
  }
  barHeight();
  window.addEventListener('resize', barHeight);

  // ---- give the slot back ----------------------------------------------------------
  // DUPLICATED FROM tools/build/build_pages.py::STREAMER_JS ON PURPOSE, and it must stay identical.
  // `sendBeacon` and not `fetch`: a request started in an unload handler is cancelled when
  // the document goes away, and beacons are explicitly exempt from that. It only does POST,
  // which is why the server has a POST route beside the DELETE one.
  function release(id) {
    if (!id) return;
    var u = '/api/streamer/session/' + encodeURIComponent(id) + '/stop';
    if (navigator.sendBeacon) { navigator.sendBeacon(u, ''); return; }
    try { fetch(u, {method: 'POST', keepalive: true}); } catch (e) {}
  }

  function stopTimers() {
    if (waitT) { clearInterval(waitT); waitT = null; }
    if (watchT) { clearInterval(watchT); watchT = null; }
    if (statsT) { clearInterval(statsT); statsT = null; }
  }

  function letGo() {
    var id = sid; sid = null;
    stopTimers();
    if (hls) { try { hls.destroy(); } catch (e) {} hls = null; }
    release(id);
  }
  window.addEventListener('pagehide', letGo);
  window.addEventListener('beforeunload', letGo);

  // A hidden tab is not a viewer, and on a two-slot box a slot held for a tab nobody is
  // looking at is half the streamer. Picture-in-picture is the exception and it is a real one:
  // the document is hidden while the visitor is genuinely watching, so the grace period is
  // not started at all in that case.
  var HIDDEN_GRACE_MS = 20000;
  document.addEventListener('visibilitychange', function () {
    if (document.hidden) {
      if (!sid || hiddenT) return;
      if (document.pictureInPictureElement === video) return;
      hiddenT = setTimeout(function () {
        hiddenT = null;
        if (!sid || !document.hidden) return;
        if (document.pictureInPictureElement === video) return;
        letGo();
        video.pause();
        nowEl.textContent = 'released';
        showFail('The stream was closed while this tab was in the background.',
                 'This box has a small number of streamer slots and holding one for a tab '
                 + 'nobody is watching makes the streamer unavailable to everyone, including '
                 + 'you in another window. Press the channel again to reopen it — '
                 + 'nothing has failed.', null, null);
      }, HIDDEN_GRACE_MS);
    } else if (hiddenT) {
      clearTimeout(hiddenT); hiddenT = null;
    }
  });

  // ---- failure, said out loud ------------------------------------------------------
  function clearFail() {
    failEl.hidden = true; failD.hidden = true; failSticky = false;
    failH.textContent = ''; failP.textContent = ''; failC.textContent = '';
  }

  // The codec diagnosis outranks what follows it -- see STREAMER_JS::showFail for the mechanism.
  // A stream this browser will not decode raises a fatal hls.js error moments after the codec
  // panel is written, and letting that overwrite it replaces the cause with a symptom.
  var failSticky = false;

  function showFail(head, mine, said, tech, sticky) {
    if (failSticky && !sticky) return;
    failSticky = !!sticky;
    failH.textContent = head;
    failP.textContent = mine || '';
    if (said) {
      var q = document.createElement('span');
      q.className = 'wsaid';
      q.textContent = said;
      failP.appendChild(q);
    }
    if (tech) { failC.textContent = tech; failD.hidden = false; }
    failEl.hidden = false;
    wake();
  }

  function session() {
    if (!sid) return Promise.resolve(null);
    return fetch('/api/streamer/session/' + encodeURIComponent(sid))
      .then(function (r) { return r.ok ? r.json() : null; })
      .catch(function () { return null; });
  }

  // Same rules as STREAMER_JS, and the same reason it is asked rather than tabulated: THIS browser
  // is the only authority on what THIS browser will decode. The audio half is not an extra --
  // MSE refuses the entire segment over a soundtrack it will not take, so an h264 stream with
  // AC-3 audio decodes zero frames and every reading on the box stays green. That was a real
  // channel of the owner's: live, vcodec h264, 87 MB pulled, black rectangle, no explanation.
  var VMIME = {h264: 'avc1.42E01E', hevc: 'hvc1.1.6.L93.B0', h265: 'hvc1.1.6.L93.B0',
               av1: 'av01.0.04M.08', vp9: 'vp09.00.10.08', vp8: 'vp8',
               mpeg2video: 'mp4v.61', vc1: 'vc-1', mpeg4: 'mp4v.20.9'};
  var AMIME = {aac: 'mp4a.40.2', ac3: 'ac-3', eac3: 'ec-3', mp2: 'mp4a.6B', mp3: 'mp4a.69',
               opus: 'opus', flac: 'flac', dts: 'dtsc', truehd: 'mlpa', vorbis: 'vorbis'};
  var CODEC_NAMES = {hevc: 'H.265 / HEVC', h265: 'H.265 / HEVC', av1: 'AV1', vp9: 'VP9',
                     vp8: 'VP8', mpeg2video: 'MPEG-2', vc1: 'VC-1', mpeg4: 'MPEG-4 Part 2',
                     ac3: 'Dolby Digital (AC-3)', eac3: 'Dolby Digital Plus (E-AC-3)',
                     dts: 'DTS', truehd: 'Dolby TrueHD', opus: 'Opus', flac: 'FLAC',
                     vorbis: 'Vorbis'};

  // Either container passing is enough: the box serves MPEG-TS and hls.js remuxes to fMP4. A
  // false alarm is the expensive mistake here -- it teaches the viewer to ignore the panel.
  function decodable(token, isVideo) {
    var m = (isVideo ? VMIME : AMIME)[token];
    if (!m) return true;
    if (!window.MediaSource || !window.MediaSource.isTypeSupported) return true;
    return window.MediaSource.isTypeSupported('video/mp2t; codecs="' + m + '"')
        || window.MediaSource.isTypeSupported((isVideo ? 'video/mp4' : 'audio/mp4')
                                              + '; codecs="' + m + '"');
  }

  function codecWarning(j) {
    var v = j && j.vcodec ? String(j.vcodec).toLowerCase() : '';
    if (v && !decodable(v, true)) return CODEC_NAMES[v] || v;
    var a = j && j.acodec ? String(j.acodec).toLowerCase() : '';
    if (a && !decodable(a, false)) return (CODEC_NAMES[a] || a) + ' audio';
    return '';
  }

  function codecFail(j, warn) {
    showFail('This stream is ' + warn + '.',
             'The box is receiving it and copying it through without re-encoding, so nothing '
             + 'here has failed — but this browser cannot decode ' + warn + '. When it is the '
             + 'sound it will not take, it refuses the whole stream rather than just the '
             + 'audio, so the picture stays black either way. Play it in VLC, or pick another '
             + 'quality from your provider.',
             null,
             'reported by the transcoder — video: ' + (j.vcodec || 'not reported')
             + ', audio: ' + (j.acodec || 'not reported'),
             true);
  }

  var FIRST_VIDEO_MS = 45000;

  // ---- open a channel ---------------------------------------------------------------
  function tune(c, releaseId) {
    if (!c || !c.url) return;
    chan = c;
    stopTimers(); clearFail();
    coldEl.hidden = true;
    if (hls) { hls.destroy(); hls = null; }
    if (video.getAttribute('src')) { video.removeAttribute('src'); video.load(); }
    var leaving = releaseId || sid;
    sid = null;
    nameEl.textContent = c.name || '(unnamed)';
    groupEl.textContent = c.group || '';
    nowEl.textContent = 'opening…';
    nnEl.textContent = '';
    remember(c);
    markCurrent();
    var creds_ = creds();
    fetch('/api/streamer/tune', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({url: c.url, label: c.name || '', release: leaving || '',
                            username: creds_.user || '', password: creds_.pass || ''})
    }).then(function (r) {
        return r.json().then(function (j) { return {ok: r.ok, status: r.status, j: j}; });
      })
      .then(function (res) {
        var j = res.j || {};
        if (!res.ok) {
          var why = j.detail || j.error || 'no reason given';
          if (res.status === 503 && /slot/i.test(String(why))) {
            nowEl.textContent = 'no free streamer slot';
            showFail('Every streamer slot on this box is in use.',
                     'This is a limit here, not your provider and nothing to do with this '
                     + 'channel. A slot frees the moment another stream is closed, and an '
                     + 'abandoned one is collected within seconds. Try again.', why, null);
            return;
          }
          nowEl.textContent = 'did not open';
          showFail('This channel did not open.',
                   'The box asked your provider for it and was refused. That is a reading '
                   + 'from the provider, not a limit here — nothing on this machine '
                   + 'filters what you may watch.', why, null);
          return;
        }
        sid = j.id || null;
        // Rewrite the handoff record now that there IS a session id. `remember` above the
        // fetch stores the channel with `sid: ''` -- deliberately, so a reload during the
        // seconds a tune takes still knows what to open. Without this second call that empty
        // id is all a reload ever sees after a channel change made on this page: it would
        // cold-tune with no `release`, holding one slot of a two-slot box on a stream nobody
        // is watching until the reaper gets to it, and the new tune can be refused meanwhile.
        remember(c);
        var warn = codecWarning(j);
        // DUPLICATED FROM STREAMER_JS ON PURPOSE. `live` plus at least one segment actually
        // named by the playlist. The playlist file exists before it lists anything, so
        // `state === 'live'` alone can hand hls.js an empty manifest; it then sits silent on
        // a black rectangle while the page claims to be playing.
        if (j.state === 'live' && !j.note && (j.segments || 0) > 0) {
          nowEl.textContent = 'live';
          if (warn) codecFail(j, warn);
          play('/api/streamer/' + j.playlist, c, j);
          return;
        }
        waitFor(c, j);
      })
      .catch(function (e) {
        nowEl.textContent = 'could not reach the box';
        showFail('The streamer could not be reached.',
                 'The request to this machine failed before your provider was ever '
                 + 'contacted, so this says nothing about the channel.',
                 null, String(e && e.message ? e.message : e));
      });
  }

  function waitFor(c, first) {
    var t0 = Date.now();
    nowEl.textContent = 'opening…';
    waitT = setInterval(function () {
      var waited = Date.now() - t0;
      session().then(function (j) {
        if (!waitT) return;
        if (!j) {
          stopTimers();
          nowEl.textContent = 'ended';
          showFail('The session ended before any video arrived.',
                   'The box opened a slot for this channel and the slot closed again '
                   + 'without producing a picture.', null, null);
          return;
        }
        if (j.state === 'failed') {
          stopTimers();
          nowEl.textContent = 'failed';
          showFail('This channel did not start.',
                   'This is what the box got back when it tried. Nothing here blocks or '
                   + 'filters streams.', j.error || 'no reason given', null);
          return;
        }
        if (j.state === 'live' && (j.segments || 0) > 0) {
          stopTimers();
          nowEl.textContent = 'live';
          var warn = codecWarning(j);
          if (warn) codecFail(j, warn);
          play('/api/streamer/' + j.playlist, c, j);
          return;
        }
        if (waited > FIRST_VIDEO_MS) {
          stopTimers();
          nowEl.textContent = 'no video';
          showFail('No video arrived within ' + Math.round(FIRST_VIDEO_MS / 1000)
                   + ' seconds.',
                   'The upstream connection opened but never produced anything the '
                   + 'transcoder could copy. That usually means the provider is answering '
                   + 'with something other than a stream.', j.error || null,
                   'session state: ' + j.state + ' · bytes read from upstream: '
                   + (j.bytes_in || 0));
          return;
        }
        nowEl.textContent = 'opening… (' + Math.round(waited / 1000) + 's)';
      });
    }, 700);
  }

  // AUTOPLAY. On streamer.html the video is one element on a page full of words, so a stream that
  // arrives paused is obvious. Here the picture IS the page, and a browser that declines to
  // start it leaves a black rectangle — which is the exact failure this surface is built to
  // never produce. Chrome's autoplay policy depends on the visitor's own engagement history,
  // so it is not reproducible and cannot be designed around: measured on this box, the same
  // handoff played on one run and arrived paused on the next.
  //
  // So it is said out loud and given a button. The button is a real user gesture, which is the
  // one thing the policy always accepts. Nothing is muted to get around it: a muted TV channel
  // that never says it is muted is the same class of lie as a status light that is always green.
  var playBtn = document.getElementById('wplay');
  var pauseT = null;

  function blocked(why) {
    if (!sid) return;
    playBtn.hidden = false;
    nowEl.textContent = 'live · waiting for you to press play';
    if (why) playBtn.title = String(why);
    wake();
  }

  function safePlay() {
    playBtn.hidden = true;
    var pr = video.play();
    if (pr && pr.catch) {
      pr.catch(function (e) { blocked(e && e.message); });
    }
    // A resolved play() is not proof of a moving picture: it resolves and then the element can
    // sit at currentTime 0 with nothing decoded. Check the reading rather than the promise.
    if (pauseT) clearTimeout(pauseT);
    pauseT = setTimeout(function () {
      if (sid && video.paused) blocked('the element is paused and no frames have decoded');
    }, 1500);
  }

  playBtn.addEventListener('click', function () {
    playBtn.hidden = true;
    var pr = video.play();
    if (pr && pr.catch) {
      pr.catch(function (e) {
        blocked(e && e.message);
        nowEl.textContent = 'live · this browser refused to start playback';
      });
    }
  });
  video.addEventListener('playing', function () {
    playBtn.hidden = true;
    if (sid) nowEl.textContent = 'live';
  });

  function play(src, c, j) {
    if (hls) { hls.destroy(); hls = null; }
    statsStart(j);
    nowNext(c);
    // hls.js FIRST -- same order, same reason, as STREAMER_JS::play(). Chrome's
    // `canPlayType('application/vnd.apple.mpegurl')` returns the truthy string 'maybe', so
    // testing it first sent every Chrome visitor down the native path and made the whole
    // hls.js block below dead code: no `liveSyncDurationCount: 1` (31 s to first frame instead
    // of 2.5), no fatal-error handler, and a statistics panel whose bitrate and throughput
    // could only ever read `-`. Safari has no MSE HLS path, `Hls.isSupported()` is false
    // there, and it falls through to the native branch correctly.
    if (!window.Hls || !window.Hls.isSupported()) {
      if (video.canPlayType('application/vnd.apple.mpegurl')) {
        engine = 'the browser’s own HLS';
        video.src = src; safePlay(); watch(c); return;
      }
      showFail('This browser cannot play HLS.',
               'hls.js is vendored at /hls.js and either did not load or is not supported '
               + 'here, and this browser has no HLS support of its own. The stream itself '
               + 'is fine.', null, null);
      return;
    }
    // DUPLICATED FROM STREAMER_JS ON PURPOSE, and this block is the one that must not drift.
    // ffmpeg stream-copies, so it can only cut on a keyframe: a provider stream with a
    // 10-second GOP yields 10-second segments however small `-hls_time` is. hls.js then
    // defaults to `liveSyncDurationCount: 3` and waits for thirty-one seconds of video
    // before showing a frame. Starting one segment back is the whole fix; the honest cost is
    // a shallower jitter buffer, which is why 3 is the library default.
    var segS = (j && j.segment_s) || 2;
    hls = new window.Hls({
      lowLatencyMode: false,
      liveSyncDurationCount: 1,
      liveMaxLatencyDurationCount: 6,
      maxBufferLength: Math.max(10, Math.ceil(segS * 2)),
      startFragPrefetch: true,
      manifestLoadingTimeOut: 20000,
      manifestLoadingMaxRetry: 4,
      manifestLoadingRetryDelay: 250,
      levelLoadingRetryDelay: 250,
      fragLoadingRetryDelay: 250,
      backBufferLength: 30
    });
    engine = 'hls.js ' + (window.Hls.version || '');
    statsTick();
    hls.loadSource(src); hls.attachMedia(video);
    hls.on(window.Hls.Events.MANIFEST_PARSED, function () {
      safePlay(); watch(c); fillLevels();
    });
    hls.on(window.Hls.Events.ERROR, function (_e, d) {
      if (!d || !d.fatal) return;
      var tech = 'hls.js: ' + d.type + ' / ' + d.details
               + (d.response && d.response.code ? ' (HTTP ' + d.response.code + ')' : '');
      session().then(function (s) {
        stopTimers();
        nowEl.textContent = 'stopped';
        if (s && s.error) {
          showFail('Playback stopped.',
                   'The box was still connected to your provider when this happened, and '
                   + 'this is what it reported.', s.error, tech);
        } else {
          showFail('Playback stopped.',
                   'The player could not fetch the next part of the stream and the box '
                   + 'reported no upstream error, so the fault is between this browser and '
                   + 'this machine rather than at your provider.', null, tech);
        }
      });
    });
  }

  function watch(c) {
    if (watchT) clearInterval(watchT);
    watchT = setInterval(function () {
      session().then(function (j) {
        if (!watchT) return;
        if (!j) { stopTimers(); return; }
        lastSession = j;
        if (j.state === 'failed' || j.state === 'ended') {
          stopTimers();
          nowEl.textContent = j.state;
          showFail(j.state === 'ended' ? 'The stream ended.' : 'The stream stopped.',
                   j.state === 'ended'
                     ? 'Your provider closed the connection. For a live channel that '
                       + 'usually means the channel went off air.'
                     : 'The box lost the upstream while playing.',
                   j.error || null, null);
        }
      });
    }, 5000);
  }

  // ---- what is on: the one-line answer above the picture ---------------------------
  // One request for the channel actually playing, refreshed every five minutes. This is the
  // reason the bar is worth having: it answers "what am I watching" without opening
  // anything. A channel the provider publishes no schedule for says so and stays quiet.
  var nnT = null;
  function nowNext(c) {
    if (nnT) { clearTimeout(nnT); nnT = null; }
    nnEl.textContent = '';
    var cr = creds();
    var sidn = c && c.stream_id ? String(c.stream_id) : '';
    if (cr.mode !== 'xtream' || !sidn) return;
    fetch('/api/streamer/epg', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({server: cr.host, username: cr.user, password: cr.pass,
                            stream_id: sidn, limit: 4})
    }).then(function (r) { return r.ok ? r.json() : null; })
      .then(function (j) {
        if (!j || chan !== c) return;
        gCache[sidn] = (j.channels && j.channels[sidn]) || [];
        // `now` is the SERVER'S answer, not this browser's arithmetic, and the route says why:
        // the clock the provider's timestamps are on is the one that matters, and a visitor
        // with a wrong system clock would otherwise see a guide wrong in a way nothing on the
        // page could explain. It is keyed by stream id -- reading it as an epoch is a mistake
        // that renders as a silently empty line, which is how it was caught.
        drawNowNext(j.now && j.now[sidn]);
        nnT = setTimeout(function () { nowNext(c); }, 300000);
      })
      .catch(function () { /* the guide is not the stream; a failure here says nothing */ });
  }

  function drawNowNext(nn) {
    nnEl.textContent = '';
    if (!nn) return;
    var cur = nn.now, nxt = nn['next'];
    if (cur) {
      var a = document.createElement('i'); a.textContent = 'Now';
      nnEl.appendChild(a);
      var line = cur.title + ' · ' + hhmm(cur.start) + '–' + hhmm(cur.stop);
      // The share elapsed is arithmetic on the provider's own two timestamps and the server's
      // clock. It is a reading, so it is printed as one and not drawn as a bar that could be
      // moving for any other reason.
      if (typeof nn.progress === 'number') {
        line += ' · ' + Math.round(nn.progress * 100) + '% through';
      }
      // A real space, not only the label's margin: read aloud, "NowSportsCenter" is one word.
      nnEl.appendChild(document.createTextNode(' ' + line));
    }
    if (nxt) {
      var b = document.createElement('s');
      b.textContent = (cur ? '   ·   ' : '') + 'Next: ' + nxt.title + ' at ' + hhmm(nxt.start);
      nnEl.appendChild(b);
    }
    // The bar just got taller, and the panels are positioned off its height.
    barHeight();
  }

  // ---- the handoff ----------------------------------------------------------------
  // Rewritten on every channel change, carrying the live session id, so a reload ADOPTS the
  // stream that is already running rather than tearing it down and reopening it.
  function remember(c) {
    try {
      localStorage.setItem(WK, JSON.stringify({name: c.name || '', url: c.url || '',
        stream_id: c.stream_id || '', group: c.group || '', sid: sid || ''}));
    } catch (e) { /* private mode -- this session still plays, a reload just starts cold */ }
  }

  // Adopt a session somebody else already opened -- the streamer page's, on a handoff, or this
  // page's own after a reload. It is one request to check, and it is worth making: the
  // alternative is releasing a working stream and asking the provider for it again, which
  // costs a fresh upstream connect and several seconds of black screen for no gain.
  //
  // A stale id is the normal case, not an error: the visitor may be arriving hours later, and
  // the box reaps an unwatched session in seconds. So a session that is missing, failed or
  // has no segments falls through to a fresh tune, passing the dead id as `release` -- which
  // the box treats as "make sure that slot is free", true in every one of those cases.
  function adopt(c, id) {
    chan = c;
    nameEl.textContent = c.name || '(unnamed)';
    groupEl.textContent = c.group || '';
    nowEl.textContent = 'rejoining…';
    fetch('/api/streamer/session/' + encodeURIComponent(id))
      .then(function (r) { return r.ok ? r.json() : null; })
      .catch(function () { return null; })
      .then(function (j) {
        if (!j || j.state !== 'live' || (j.segments || 0) < 1) { tune(c, id); return; }
        sid = id;
        coldEl.hidden = true;
        nowEl.textContent = 'live';
        remember(c);
        var warn = codecWarning(j);
        if (warn) codecFail(j, warn);
        play('/api/streamer/' + j.playlist, c, j);
      });
  }

  // ---- the guide ------------------------------------------------------------------
  var WINDOW_S = 10800, STEP_S = 5400, GROWS = 30;
  var live = [], view = [], gCache = {}, gLeft = 0, gPage = 0, gBusy = false, gTick = null;
  var loaded = false, loading = false;

  function snapHalfHour(t) { return Math.floor(t / 1800) * 1800; }
  function hhmm(epoch) {
    var d = new Date(epoch * 1000), h = d.getHours(), m = d.getMinutes();
    return (h < 10 ? '0' : '') + h + ':' + (m < 10 ? '0' : '') + m;
  }

  // Open on the block containing the channel being watched, not on row 1 of 10,072. The first
  // thirty rows of a big provider's list are usually PPV placeholders with no schedule at all,
  // so the panel used to open on thirty empty strips bearing no relation to what was playing.
  function focusCurrent() {
    if (!chan || !chan.url) return;
    for (var i = 0; i < view.length; i++) {
      if (live[view[i]].url === chan.url) { gPage = Math.floor(i / GROWS); return; }
    }
  }

  function openGuide() {
    barHeight();
    gPanel.hidden = false;
    sPanel.hidden = true;
    wake();
    if (!gLeft) gLeft = snapHalfHour(Date.now() / 1000);
    if (!gTick) gTick = setInterval(nowLine, 30000);
    if (!loaded && !loading) { loadChannels(); }
    else { focusCurrent(); gDraw(); gLoad(); }
    qBox.focus();
  }
  function closeGuide() {
    gPanel.hidden = true;
    if (gTick) { clearInterval(gTick); gTick = null; }
    wake();
  }

  // The catalogue, live only. A film has no schedule, so asking for Movies and Series here
  // would be a request nobody could use -- the streamer page is where a catalogue is browsed.
  function loadChannels() {
    var cr = creds();
    if (cr.mode === 'none') {
      gNote.textContent = 'No playlist is saved in this browser. Load one on the streamer and '
        + 'it will be here.';
      return;
    }
    loading = true;
    gNote.textContent = 'asking your ' + (cr.mode === 'm3u' ? 'playlist' : 'panel')
      + ' for its live channels…';
    var url = cr.mode === 'm3u' ? '/api/streamer/playlist' : '/api/streamer/xtream/channels';
    var body = cr.mode === 'm3u' ? {url: cr.url}
             : {server: cr.host, username: cr.user, password: cr.pass, kinds: ['live']};
    fetch(url, {method: 'POST', headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(body)})
      .then(function (r) { return r.json().then(function (j) { return {ok: r.ok, j: j}; }); })
      .then(function (res) {
        loading = false;
        if (!res.ok) {
          gNote.textContent = 'The channel list could not be loaded: '
            + (res.j.error || res.j.detail || 'no reason given');
          return;
        }
        loaded = true;
        live = (res.j.channels || []).filter(function (c) {
          var k = (c.kind ? String(c.kind) : 'live').toLowerCase();
          return k !== 'vod' && k !== 'series';
        });
        applyFilter();
        focusCurrent();
        gDraw();
        gLoad();
      })
      .catch(function (e) {
        loading = false;
        gNote.textContent = 'Could not reach this box for the channel list ('
          + String(e && e.message) + ').';
      });
  }

  function applyFilter() {
    var q = qBox.value.trim().toLowerCase();
    var terms = q ? q.split(/\s+/).filter(function (t) { return t.length > 1; }) : [];
    view = [];
    for (var i = 0; i < live.length; i++) {
      if (!terms.length) { view.push(i); continue; }
      var h = ((live[i].name || '') + ' ' + (live[i].group || '')).toLowerCase();
      var all_ = true;
      for (var k = 0; k < terms.length; k++) {
        if (h.indexOf(terms[k]) < 0) { all_ = false; break; }
      }
      if (all_) view.push(i);
    }
    gPage = 0;
    gDraw();
    gLoad();
  }
  var qT = null;
  qBox.addEventListener('input', function () {
    if (qT) clearTimeout(qT);
    qT = setTimeout(applyFilter, 160);
  });

  function gRows() { return view.slice(gPage * GROWS, gPage * GROWS + GROWS); }

  function gDraw() {
    var rows = gRows(), right = gLeft + WINDOW_S;
    whenEl.textContent = hhmm(gLeft) + '–' + hhmm(right) + '  ·  rows '
      + (rows.length ? gPage * GROWS + 1 : 0) + '–' + (gPage * GROWS + rows.length)
      + ' of ' + view.length;

    ticksEl.innerHTML = '';
    for (var t = gLeft; t < right; t += 1800) {
      var tick = document.createElement('div');
      tick.className = 'wgtick';
      tick.style.left = ((t - gLeft) / WINDOW_S * 100) + '%';
      tick.style.width = (1800 / WINDOW_S * 100) + '%';
      tick.textContent = hhmm(t);
      ticksEl.appendChild(tick);
    }

    rowsEl.innerHTML = '';
    rows.forEach(function (idx) {
      var c = live[idx];
      var row = document.createElement('div');
      row.className = 'wgrow';
      var btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'wgchan';
      btn.dataset.url = c.url || '';
      btn.appendChild(document.createTextNode(c.name || '(unnamed)'));
      var em = document.createElement('em');
      em.textContent = c.group || '(no group)';
      btn.appendChild(em);
      btn.addEventListener('click', function () { pickChannel(c); });
      row.appendChild(btn);
      var strip = document.createElement('div');
      strip.className = 'wgstrip';
      gStrip(strip, c);
      row.appendChild(strip);
      rowsEl.appendChild(row);
    });
    markCurrent();
    nowLine();
  }

  function gStrip(strip, c) {
    var sidn = String(c.stream_id || '');
    var progs = sidn ? gCache[sidn] : null;
    var right = gLeft + WINDOW_S;
    strip.innerHTML = '';
    if (!sidn) {
      var m = document.createElement('div');
      m.className = 'wgnone';
      m.textContent = 'no guide for a pasted playlist — an Xtream panel login is what '
        + 'carries one';
      strip.appendChild(m);
      return;
    }
    if (progs === undefined) {
      var l = document.createElement('div');
      l.className = 'wgnone';
      l.textContent = 'asking your provider…';
      strip.appendChild(l);
      return;
    }
    var any = false, now = Date.now() / 1000;
    (progs || []).forEach(function (p) {
      if (p.stop <= gLeft || p.start >= right) return;
      var a = Math.max(p.start, gLeft), b = Math.min(p.stop, right);
      var el = document.createElement('button');
      el.type = 'button';
      el.className = 'wgprog' + (p.start <= now && now < p.stop ? ' wgon' : '');
      el.style.left = ((a - gLeft) / WINDOW_S * 100) + '%';
      el.style.width = (Math.max(60, b - a) / WINDOW_S * 100) + '%';
      el.appendChild(document.createTextNode(p.title || '(untitled)'));
      var u = document.createElement('u');
      u.textContent = hhmm(p.start) + '–' + hhmm(p.stop);
      el.appendChild(u);
      el.title = (p.title || '') + '  ' + hhmm(p.start) + '–' + hhmm(p.stop)
               + (p.desc ? '\n\n' + p.desc : '');
      el.addEventListener('click', function () { pickChannel(c); });
      strip.appendChild(el);
      any = true;
    });
    if (!any) {
      var n = document.createElement('div');
      n.className = 'wgnone';
      n.textContent = (progs && progs.length)
        ? 'nothing published for this part of the day'
        : 'no guide published for this channel';
      strip.appendChild(n);
    }
  }

  // A reading, so it is only drawn when now is inside the window on screen.
  function nowLine() {
    var old = rowsEl.querySelectorAll('.wgline');
    for (var i = 0; i < old.length; i++) old[i].remove();
    var now = Date.now() / 1000;
    if (now < gLeft || now > gLeft + WINDOW_S) return;
    var pct = (now - gLeft) / WINDOW_S * 100;
    var strips = rowsEl.querySelectorAll('.wgstrip');
    for (var n = 0; n < strips.length; n++) {
      var line = document.createElement('div');
      line.className = 'wgline';
      line.style.left = pct + '%';
      strips[n].appendChild(line);
    }
  }

  function markCurrent() {
    var url = chan && chan.url ? chan.url : '';
    var btns = rowsEl.querySelectorAll('.wgchan');
    for (var i = 0; i < btns.length; i++) {
      btns[i].classList.toggle('wcur', !!url && btns[i].dataset.url === url);
    }
  }

  function gLoad() {
    var cr = creds();
    if (cr.mode !== 'xtream') {
      gNote.textContent = 'A pasted M3U carries no guide endpoint, so there is nothing to '
        + 'ask for. Channels still play; log in with an Xtream panel and the guide fills in '
        + 'from your provider’s own schedule.';
      return;
    }
    var want = [];
    gRows().forEach(function (idx) {
      var s = String(live[idx].stream_id || '');
      if (s && gCache[s] === undefined) want.push(s);
    });
    if (!want.length || gBusy) { if (!want.length) gDraw(); return; }
    gBusy = true;
    gNote.textContent = 'asking your provider for ' + want.length + ' channel'
      + (want.length === 1 ? '' : 's') + ' of guide…';
    fetch('/api/streamer/epg', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({server: cr.host, username: cr.user, password: cr.pass,
                            stream_ids: want, limit: 8})
    }).then(function (r) {
      return r.json().then(function (j) { return {ok: r.ok, j: j}; });
    }).then(function (res) {
      gBusy = false;
      if (!res.ok) {
        gNote.textContent = 'The guide request failed: '
          + ((res.j && res.j.detail) ? String(res.j.detail) : 'no reason given')
          + '  Nothing on this box filters a guide; this is what came back.';
        return;
      }
      // An empty answer is CACHED as empty rather than left unknown, or every redraw asks
      // somebody else's panel again for a channel that has no guide.
      want.forEach(function (s) {
        gCache[s] = (res.j.channels && res.j.channels[s]) || [];
      });
      // Counted over the rows ON SCREEN, not over the ids just asked for. Those differ: the
      // channel being watched already has its guide from the now/next request, so it is not in
      // `want` -- and a note reading "0 of 30 published a guide" above a row visibly full of
      // programmes is the page contradicting itself. Measured: that is exactly what it said.
      var rows = gRows(), have = 0;
      rows.forEach(function (idx) {
        var s = String(live[idx].stream_id || '');
        if (s && gCache[s] && gCache[s].length) have += 1;
      });
      var failed = Object.keys(res.j.failed || {}).length;
      gNote.textContent = have + ' of ' + rows.length + ' channels on screen publish a guide'
        + '  ·  ' + want.length + ' asked for just now'
        + (failed ? ', ' + failed + ' request' + (failed === 1 ? '' : 's') + ' failed' : '')
        + ', ' + (res.j.elapsed_ms || 0) + ' ms — that wait is your provider’s, straight through'
        + '  ·  nothing about it is stored on this box.'
        + (have < rows.length
            ? '  A channel with no guide is one your provider publishes no schedule for; it is '
              + 'not hidden and it still plays.'
            : '');
      gDraw();
    }).catch(function (e) {
      gBusy = false;
      gNote.textContent = 'Could not reach this box for the guide ('
        + String(e && e.message) + '). Your provider was never contacted.';
    });
  }

  function pickChannel(c) {
    closeGuide();
    tune(c, sid);
  }

  document.getElementById('wgback').addEventListener('click', function () {
    gLeft -= STEP_S; gDraw(); gLoad();
  });
  document.getElementById('wgfwd').addEventListener('click', function () {
    gLeft += STEP_S; gDraw(); gLoad();
  });
  document.getElementById('wgnow').addEventListener('click', function () {
    gLeft = snapHalfHour(Date.now() / 1000); gDraw(); gLoad();
  });
  document.getElementById('wgpage').addEventListener('click', function () {
    gPage += 1;
    if (gPage * GROWS >= view.length) gPage = 0;
    gDraw(); gLoad();
  });
  document.getElementById('wgclose').addEventListener('click', closeGuide);
  document.getElementById('wgbtn').addEventListener('click', function () {
    if (gPanel.hidden) openGuide(); else closeGuide();
  });

  // ---- statistics -----------------------------------------------------------------
  function put(id, text) { document.getElementById(id).textContent = text; }

  function fmtRate(bps) {
    if (!bps || bps < 1) return '-';
    if (bps >= 1e6) return (bps / 1e6).toFixed(2) + ' Mb/s';
    return Math.round(bps / 1e3) + ' kb/s';
  }
  function fmtBytes(n) {
    if (!n) return '-';
    if (n >= 1e9) return (n / 1e9).toFixed(2) + ' GB';
    if (n >= 1e6) return (n / 1e6).toFixed(1) + ' MB';
    return Math.round(n / 1e3) + ' kB';
  }
  function bufferAhead() {
    try {
      for (var i = 0; i < video.buffered.length; i++) {
        if (video.buffered.start(i) <= video.currentTime
            && video.currentTime <= video.buffered.end(i)) {
          return video.buffered.end(i) - video.currentTime;
        }
      }
    } catch (e) { /* buffered throws on a detached element */ }
    return null;
  }

  function statsTick() {
    var q = video.getVideoPlaybackQuality ? video.getVideoPlaybackQuality() : null;
    var w = video.videoWidth, h = video.videoHeight;
    put('ps-res', (w && h) ? w + ' × ' + h : '-');
    var buf = bufferAhead();
    put('ps-buf', buf === null ? '-' : buf.toFixed(1) + ' s');
    put('ps-drop', q ? String(q.droppedVideoFrames) : '-');
    put('ps-dec', q ? String(q.totalVideoFrames) : '-');
    put('ps-eng', engine || '-');
    if (hls) {
      // `currentLevel` is **-1 while the level is being chosen automatically**, which is the
      // default and therefore the normal case -- so reading it alone printed `-` for the level
      // bitrate on a stream that was plainly playing at a known bitrate. `loadLevel` is the
      // index actually being fetched, and it resolves the auto choice. Measured: 286 Mb/s of
      // throughput and 2 levels beside a bitrate of `-`, which is what gave it away.
      var li = hls.currentLevel;
      if (li < 0 && typeof hls.loadLevel === 'number') li = hls.loadLevel;
      var lv = (li >= 0 && hls.levels) ? hls.levels[li] : null;
      put('ps-rate', lv ? fmtRate(lv.bitrate)
                          + (hls.currentLevel < 0 ? ' (auto)' : '') : '-');
      put('ps-tp', fmtRate(hls.bandwidthEstimate));
    } else {
      put('ps-rate', '-'); put('ps-tp', '-');
    }
    var j = lastSession;
    put('ps-seg', j && j.segment_s ? Number(j.segment_s).toFixed(2) + ' s' : '-');
    put('ps-segn', j && j.segments !== undefined ? String(j.segments) : '-');
    put('ps-in', j ? fmtBytes(j.bytes_in) : '-');
    put('ps-mode', j && j.mode ? (j.mode === 'direct' ? 'stream copy, no GPU' : String(j.mode))
                              : '-');
    put('ps-age', j && j.age_s !== undefined ? Math.round(j.age_s) + ' s' : '-');
  }

  // The panel reads once a second whether or not it is open: the numbers a viewer opens it
  // for are dropped frames and buffer, and both are only meaningful as a running count.
  function statsStart(j) {
    lastSession = j || null;
    if (statsT) clearInterval(statsT);
    statsT = setInterval(statsTick, 1000);
    statsTick();
    fillLevels();
    psWhy.textContent = 'Quality is your provider’s — this box stream-copies and '
      + 'does not re-encode, so there is one level unless they publish more. Everything '
      + 'above is measured by the player in this browser or read from the session on the box.';
  }

  function fillLevels() {
    while (psLevel.options.length > 1) psLevel.remove(1);
    while (psAudio.options.length > 1) psAudio.remove(1);
    if (!hls) return;
    (hls.levels || []).forEach(function (lv, i) {
      var o = document.createElement('option');
      o.value = String(i);
      o.textContent = (lv.height ? lv.height + 'p' : 'level ' + (i + 1))
        + (lv.bitrate ? ' · ' + fmtRate(lv.bitrate) : '');
      psLevel.appendChild(o);
    });
    (hls.audioTracks || []).forEach(function (tr, i) {
      var o = document.createElement('option');
      o.value = String(i);
      o.textContent = tr.name || tr.lang || ('track ' + (i + 1));
      psAudio.appendChild(o);
    });
  }

  psLevel.addEventListener('change', function () {
    if (hls) hls.currentLevel = parseInt(psLevel.value, 10);
  });
  psAudio.addEventListener('change', function () {
    var v = parseInt(psAudio.value, 10);
    if (hls && v >= 0) hls.audioTrack = v;
  });

  function openStats() {
    barHeight();
    sPanel.hidden = false; gPanel.hidden = true;
    if (gTick) { clearInterval(gTick); gTick = null; }
    statsTick(); fillLevels(); wake();
  }
  function closeStats() { sPanel.hidden = true; wake(); }
  document.getElementById('wsclose').addEventListener('click', closeStats);
  document.getElementById('wsbtn').addEventListener('click', function () {
    if (sPanel.hidden) openStats(); else closeStats();
  });

  // ---- picture in picture and full screen ------------------------------------------
  var pipBtn = document.getElementById('wpip'), fullBtn = document.getElementById('wfull');
  if (!document.pictureInPictureEnabled || !video.requestPictureInPicture) {
    pipBtn.disabled = true;
    pipBtn.title = 'This browser does not offer picture-in-picture.';
  }
  pipBtn.addEventListener('click', function () {
    if (document.pictureInPictureElement === video) {
      document.exitPictureInPicture().catch(function () {});
      return;
    }
    if (!video.requestPictureInPicture) return;
    video.requestPictureInPicture().catch(function (e) {
      psWhy.textContent = 'Picture-in-picture was refused: ' + String(e && e.message);
      openStats();
    });
  });
  video.addEventListener('enterpictureinpicture', function () {
    pipBtn.classList.add('won');
  });
  video.addEventListener('leavepictureinpicture', function () {
    pipBtn.classList.remove('won');
  });

  fullBtn.addEventListener('click', function () {
    if (document.fullscreenElement) {
      document.exitFullscreen().catch(function () {});
      return;
    }
    var el = document.getElementById('wstage');
    if (el.requestFullscreen) el.requestFullscreen().catch(function () {});
  });
  document.addEventListener('fullscreenchange', function () {
    fullBtn.classList.toggle('won', !!document.fullscreenElement);
  });

  // ---- keys ------------------------------------------------------------------------
  document.addEventListener('keydown', function (e) {
    if (e.target && /^(INPUT|SELECT|TEXTAREA)$/.test(e.target.tagName)) {
      if (e.key === 'Escape') { e.target.blur(); }
      return;
    }
    if (e.key === 'Escape') {
      if (!gPanel.hidden) closeGuide();
      else if (!sPanel.hidden) closeStats();
      return;
    }
    if (e.key === 'g' || e.key === 'G') { if (gPanel.hidden) openGuide(); else closeGuide(); }
    else if (e.key === 's' || e.key === 'S') { if (sPanel.hidden) openStats(); else closeStats(); }
    else if (e.key === 'f' || e.key === 'F') { fullBtn.click(); }
    else if (e.key === 'p' || e.key === 'P') { if (!pipBtn.disabled) pipBtn.click(); }
  });

  // ---- what this page opened on ----------------------------------------------------
  var hand = null;
  try { hand = JSON.parse(localStorage.getItem(WK) || 'null'); } catch (e) { hand = null; }
  if (hand && hand.url) {
    var c0 = {name: hand.name || '', url: hand.url, stream_id: hand.stream_id || '',
              group: hand.group || ''};
    // `sid` is the session the streamer page was still holding when it sent us here. It is
    // adopted if it is alive, and passed as /tune's `release` if it is not, so a handoff
    // never holds both streamers of a two-slot box at once and never leaves one behind.
    if (hand.sid) { adopt(c0, hand.sid); } else { tune(c0, ''); }
  } else {
    coldEl.hidden = false;
    nameEl.textContent = 'SyMoNeuRaL Streamer';
    nowEl.textContent = 'nothing playing';
    if (!cfg) {
      coldP.textContent = 'No playlist is saved in this browser either. The streamer is where '
        + 'you load one — it stays in this browser and is never written to disk on '
        + 'this box.';
    }
    wake();
  }
})();
</script>
</body>
</html>
"""


def watch_page() -> None:
    """Write frontend/site/pages/streamer-watch.html.

    Not routed through `page()`: this surface has no header, no footer and no prose measure,
    because the picture is the page. It is still generated rather than hand-written so the
    streamer's frontend has one home -- tools/build/build_pages.py -- rather than two.
    """
    out = SITE / "streamer-watch.html"
    out.write_text(WATCH_HTML)
    print(f"  streamer-watch.html  ({len(WATCH_HTML):,} bytes)")


def main() -> int:
    print("building surface pages:")
    page("chat.html", app=True, gpu=True, surface="Chat",
         title="SyMoNeuRaL Chat — talk to the box",
         desc="A 7B running locally on an RTX 5070 Ti. Nothing leaves the machine.",
         icon="/chat-64.png", eyebrow="Live surface",
         heading="Ask SyMon.",
         lede="This is a 7B at Q4 on the RTX 5070 Ti described on the home page, streaming "
              "tokens as the card produces them. The tokens-per-second under each answer is "
              "measured, not claimed.",
         body=CHAT_BODY, script=CHAT_JS)

    page("image.html", app=True, gpu=True, surface="Image",
         title="SyMoNeuRaL Image — make it draw",
         desc="FLUX.1-schnell in four steps, rendered locally on a consumer GPU.",
         icon="/image-64.png", eyebrow="Live surface",
         heading="Make it draw something.",
         lede="FLUX.1-schnell, quantized to q4_k and rendered on the card in this machine. "
              "Every image below prints the wall-clock it actually took.",
         # `css=`/`js=` rather than `script=`: the first page split into static
         # html + js + css per #81. The other surfaces follow one at a time, image
         # first and all the way through -- *"a pattern proven on one page is worth
         # more than nine half-migrations."*
         body=IMAGE_BODY, css=IMAGE_CSS, js=IMAGE_JS)

    page("ravencalc.html", app=True, gpu=False, surface="RavenCalc",
         title="SyMoNeuRaL RavenCalc — exact mathematics",
         desc="Exact symbolic computation that checks its own work.",
         icon="/calc-64.png", eyebrow="Live surface · CPU",
         heading="Mathematics, computed rather than predicted.",
         lede="RavenCalc is an exact symbolic engine, not a language model guessing at algebra. It "
              "runs on the CPU, so it is the one surface here that never waits for the GPU.",
         body=CALC_BODY, script=CALC_JS)

    page("remix.html", app=True, gpu=True, surface="Remix",
         title="SyMoNeuRaL Remix — playlists that are ordered sets",
         desc="Prompt to sequenced tracklist, generated locally.",
         icon="/dj-64.png", eyebrow="Live surface",
         heading="Playlists that are ordered sets, not piles of songs.",
         lede="Remix asks the same local 7B that answers questions on the chat page. One "
              "model, one GPU, one server underneath — which is the whole architecture in "
              "one page.",
         body=REMIX_BODY, script=REMIX_JS)

    page("miner.html", app=True, gpu=True, surface="SyMoNeuRaL Miner",
         why="<b>SyMoNeuRaL Miner</b> is the one surface here that holds the card for its "
             "whole process lifetime rather than for a single job, and it cannot be "
             "preempted. While <i>holding</i> reads <b>miner</b>, chat, image and remix will "
             "queue and then fail &mdash; which is why it is started by hand and stopped by "
             "hand.",
         title="SyMoNeuRaL Miner — the GPU in this box, and ASIC rigs on your network",
         desc="The GPU + ASIC operator surface for mining experiments and hardware control. "
              "Measured readings only, and a benchmark says it is a benchmark.",
         icon="/terminal-64.png", eyebrow="Operator surface · GPU + ASIC",
         heading="Mining hardware, read the same way as the card.",
         lede="SyMoNeuRaL Miner is the GPU + ASIC operator surface for mining experiments "
              "and hardware control. Two units answer here. The GPU half is the intended "
              "KawPow path for the RTX 5070 Ti in this room, through the same governor every "
              "other surface queues on; it is offline unless configured, and the engine work "
              "is incomplete, so it reports offline rather than a hashrate. SyMoNeuRaL ASIC "
              "below is the operator panel for Antminer and MicroBT rigs on your own network "
              "— plus a firmware emulator and a network scanner, which work with no rig "
              "attached. No rigs are attached to this machine, so it reports offline, which "
              "is the reading rather than a placeholder.",
         body=MINER_BODY, script=MINER_JS)

    # `gpu=False, surface="Gateway"` for the same reason streamer.html passes it: this is a
    # bus="net" surface that never takes the governor lock, so the shared "you may be queued
    # behind a render" callout was describing a machine constraint that cannot apply here. The
    # gpu=False variant still shows the card — it is shared and worth seeing — while saying
    # outright that this page does not wait for it. (backend/gateway/docs/gateway-completion.md flag 3.)
    #
    # Every line below is written to stay true in BOTH states, before and after a contract is
    # deployed. The previous copy hardcoded "nothing is deployed yet" and "nothing here is
    # measured", which a deployment turns into a live page contradicting the API — this repo's
    # most-repeated failure. What the chain actually holds is not asserted here at all; it is
    # read from the chain and printed in the status line, verbatim.
    page("gateway.html", app=True, gpu=False, surface="Gateway",
         title="SyMoNeuRaL Gateway — stablecoin licensing, honestly labelled",
         desc="A TRON/USDT licensing and validation gateway. Its status is read from the chain.",
         icon="/terminal-64.png", eyebrow="Surface · network · TRON",
         heading="Licensing that settles on-chain, and says whose number that is.",
         lede="A licensing gateway on the TRON Virtual Machine, settling in USDT, with a "
              "local daemon that makes a human approve the configuration before anything "
              "is broadcast. The status line below is read live from this box: it names the "
              "network it is pointed at, what it last read from the chain, and how old that "
              "reading is.",
         body=GATEWAY_BODY, script=GATEWAY_JS)

    page("streamer.html", app=True, gpu=False, surface="Streamer",
         title="SyMoNeuRaL Streamer — your playlist, your credentials",
         desc="IPTV over ffmpeg stream copy. Credentials stay in your browser.",
         icon="/terminal-64.png", eyebrow="Live surface · network",
         heading="Bring your own playlist.",
         lede="Load an M3U or Xtream Codes subscription and the box will copy the stream "
              "rather than re-encode it. Your credentials stay in this browser and are "
              "never written to disk here — which is the same promise the rest of this "
              "site makes about your data.",
         body=STREAMER_BODY, script=STREAMER_JS)

    watch_page()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
