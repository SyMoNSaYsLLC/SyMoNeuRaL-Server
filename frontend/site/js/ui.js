/* Documentation tabs, and the lightbox for the renders.
 *
 * The header used to have two JavaScript dropdowns. They are gone: both opened onto a
 * single destination anyway, and the menu -- z-index:60 inside a header that is itself a
 * z-index:20 stacking context -- painted underneath the hero. A nav link cannot do that.
 *
 * The tabs are progressive enhancement. Without this file every documentation panel is
 * visible, so the page degrades to a long document rather than to eight empty boxes --
 * the same reason the rack ships a <noscript> unit.
 */
(function () {
  'use strict';

  // ---- documentation tabs -------------------------------------------------
  var tabs = [].slice.call(document.querySelectorAll('.tab[role="tab"]'));
  if (!tabs.length) return;

  function show(id, push) {
    tabs.forEach(function (t) {
      var on = t.id === 'tab-' + id;
      t.classList.toggle('on', on);
      t.setAttribute('aria-selected', String(on));
    });
    [].slice.call(document.querySelectorAll('.tabpanel')).forEach(function (p) {
      p.hidden = p.id !== 'panel-' + id;
    });
    // The header menu deep-links straight to a section, and people share those urls,
    // so the hash has to survive a reload rather than always landing on the first tab.
    if (push && history.replaceState) history.replaceState(null, '', '#' + id);
  }

  tabs.forEach(function (t) {
    t.addEventListener('click', function () { show(t.id.replace(/^tab-/, ''), true); });
  });

  // JS is running, so it is now safe to hide the inactive panels.
  var want = (location.hash || '').replace(/^#/, '');
  var known = tabs.some(function (t) { return t.id === 'tab-' + want; });
  show(known ? want : tabs[0].id.replace(/^tab-/, ''), false);

  window.addEventListener('hashchange', function () {
    var h = (location.hash || '').replace(/^#/, '');
    if (tabs.some(function (t) { return t.id === 'tab-' + h; })) show(h, false);
  });
})();

/* Lightbox for the constellation renders.
 *
 * Separate IIFE on purpose: the block above returns early on any page with no
 * documentation tabs, which is every page the band appears on.
 *
 * The renders sit at 38-59px so the band reads as a network rather than a contact sheet,
 * and at that size the watermark burned into each one -- model, quantisation, resolution,
 * steps, seed, and the wall-clock it took on this card -- cannot be read at all. That
 * watermark is the entire claim: these were drawn by the machine on this page. Clicking
 * opens the full 768px render with its prompt and seed beside it. The markup is a plain
 * link to the PNG, so with no JavaScript the click still shows the file.
 */
(function () {
  'use strict';
  var links = [].slice.call(document.querySelectorAll('a.art, a.gart'));
  if (!links.length) return;

  var box, img, cap, meta, opener;
  var generation = 0;   // bumped per open, so a stale image load cannot rewrite the caption

  function build() {
    box = document.createElement('div');
    box.className = 'lightbox';
    box.setAttribute('role', 'dialog');
    box.setAttribute('aria-modal', 'true');
    box.setAttribute('aria-label', 'Full-size render');
    box.innerHTML =
      '<button class="lb-close" aria-label="Close">&times;</button>' +
      '<figure class="lb-fig">' +
        '<img alt="">' +
        '<figcaption><q class="lb-prompt"></q><span class="lb-meta"></span></figcaption>' +
      '</figure>';
    document.body.appendChild(box);
    img = box.querySelector('img');
    cap = box.querySelector('.lb-prompt');
    meta = box.querySelector('.lb-meta');
    box.addEventListener('click', function (e) {
      // the backdrop and the close button dismiss; the figure itself does not
      if (!e.target.closest('.lb-fig') || e.target.closest('.lb-close')) close();
    });
  }

  function open(a) {
    if (!box) build();
    opener = a;
    img.src = a.getAttribute('href');
    img.alt = a.querySelector('img').alt;
    cap.textContent = a.getAttribute('data-prompt') || '';
    // Deliberately not a repeat of the strip along the bottom of the image. That strip is
    // burned into the PNG by tools/build_gallery.py and already names the model, size,
    // steps, seed and seconds; printing the same line underneath would read as a page
    // caption *about* the image rather than as something the file itself carries.
    //
    // Whether there IS a strip is measured, not assumed. Only build_gallery.py burns one;
    // a render that came back from /api/gen has none, and telling a visitor to look at a
    // strip that is not there would be a false provenance claim on the one feature whose
    // entire purpose is provenance. Every render the lightbox is currently bound to
    // (a.art, a.gart -- all art-*.png) does carry one, so this is a guard against the
    // claim becoming false rather than a fix for it being false today. The signal is the
    // file's own shape: the bar makes it taller than it is wide, where an unstamped render
    // is square. That survives a rename, which a path check would not.
    var secs = a.getAttribute('data-secs');
    // `open` can run again before a slow image has loaded, and a {once:true} listener that
    // never fired stays attached -- so without this token a stale listener would later
    // write the previous render's caption over the current one.
    var mine = ++generation;
    var say = function () {
      if (mine !== generation) return;
      var stamped = img.naturalWidth > 0 && img.naturalHeight > img.naturalWidth;
      meta.textContent = !secs ? ''
        : stamped
          ? 'The strip along the bottom is printed into the file, not added by this page. '
            + secs + ' seconds, start to finish, on the card in the rack below.'
          : secs + ' seconds, start to finish, on the card in the rack below.';
    };
    meta.textContent = '';
    if (img.complete) say(); else img.addEventListener('load', say, { once: true });
    box.classList.add('on');
    document.documentElement.style.overflow = 'hidden';
    box.querySelector('.lb-close').focus();
  }

  function close() {
    if (!box) return;
    box.classList.remove('on');
    document.documentElement.style.overflow = '';
    // hand focus back to the render that was clicked, or a keyboard user is dropped
    // at the top of the document
    if (opener) opener.focus();
  }

  links.forEach(function (a) {
    a.addEventListener('click', function (e) {
      if (e.metaKey || e.ctrlKey || e.shiftKey || e.button) return;  // let "open in new tab" work
      e.preventDefault();
      open(a);
    });
  });

  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape' && box && box.classList.contains('on')) close();
  });
})();

/* Symon Say News -- the live headline bar along the bottom of every page.
 *
 * Garrett: "ESPN has a ticker on the bottom of their tv screens that everyone has always
 * loved ... instead of sports live fed news; it will be news relevent to the the website."
 * The headlines come from `backend/apps/symoneuralnews`, which fetches ten release feeds
 * and three search engines on a 15-minute timer and serves the ranked result at
 * /api/news/ticker. Nothing here fetches a publisher directly; the browser only ever talks
 * to this box.
 *
 * Separate top-level IIFE, for the same reason the lightbox is one: the tabs block above
 * returns early on every page that has no documentation tabs, which is most of them.
 *
 * Three properties worth stating, because each one is a decision and not an accident:
 *
 *   1. THE BAR IS BUILT IN JAVASCRIPT AND DOES NOT EXIST UNTIL THERE ARE HEADLINES. No
 *      markup in any of the 23 pages, no placeholder, no "loading news..." row. With the
 *      surface off (the default -- SYMONEURAL_NEWS_ENABLED is unset) the endpoint answers
 *      200 with an empty list and this file appends nothing at all, so the page is exactly
 *      what it was before. An empty ESPN ticker is a broken television.
 *
 *   2. IT LABELS ITS OWN AGE FROM THE SERVER'S READING. `newest_age_s` is the age of the
 *      newest headline, not of the fetch, and that is what makes the word "live" true or
 *      false. Fresh gets the pulsing lamp; anything over SIX HOURS says how old it is
 *      instead. A lamp on a bar of yesterday's news is the decorative indicator CLAUDE.md
 *      forbids.
 *
 *   3. EVERY STRING FROM A PUBLISHER GOES IN AS textContent. Headlines are third-party
 *      text arriving over HTTP; `innerHTML` anywhere in this function would make thirteen
 *      strangers' feeds an injection surface on symoneural.com. Link hrefs are re-checked
 *      for https here as well -- the collector already guarantees it, and this costs one
 *      comparison to keep guaranteeing it if that ever changes.
 */
(function () {
  'use strict';

  var ENDPOINT = '/api/news/ticker';
  var POLL_MS = 300000;          // 5 min; the server refreshes every 15, so this is cheap
  var PX_PER_SEC = 92;           // px/s of crawl -- see the note in render()
  var OLD_S = 21600;             // 6h -- past this the bar stops claiming to be live
  var DISMISS = 'symonsaynews:off';

  var bar = null, run = null, brand = null, stamp = 0;

  function stored(key) {
    // Safari in private mode throws on sessionStorage access rather than returning null.
    try { return window.sessionStorage.getItem(key); } catch (e) { return null; }
  }

  if (stored(DISMISS)) return;   // dismissed for this tab; stay gone until it is reopened

  function chip(cls, text) {
    var el = document.createElement('span');
    el.className = cls;
    el.textContent = text;
    return el;
  }

  function lane(items, dupe) {
    var box = document.createElement('div');
    box.className = 'sn-lane';
    // The second lane is the same headlines again, and it exists only so the crawl can
    // wrap at -50% with nothing visibly restarting. A screen reader reading the page
    // twice would be a bug, so the copy is hidden from the accessibility tree.
    if (dupe) box.setAttribute('aria-hidden', 'true');
    items.forEach(function (it) {
      var a = document.createElement('a');
      a.className = 'sn-item';
      a.href = it.url;
      a.target = '_blank';
      a.rel = 'noopener noreferrer';
      if (dupe) a.tabIndex = -1;               // the copy is not a second tab stop
      a.appendChild(chip('sn-topic', it.topic || 'news'));
      if (it.source) a.appendChild(chip('sn-src', it.source));
      a.appendChild(chip('sn-head', it.title));
      box.appendChild(a);
    });
    return box;
  }

  function build() {
    bar = document.createElement('aside');
    bar.id = 'symonsaynews';
    bar.setAttribute('aria-label', 'Symon Say News: live headlines');

    brand = document.createElement('span');
    brand.className = 'sn-brand';
    bar.appendChild(brand);

    var win = document.createElement('div');
    win.className = 'sn-window';
    run = document.createElement('div');
    run.className = 'sn-run';
    win.appendChild(run);
    bar.appendChild(win);

    var x = document.createElement('button');
    x.className = 'sn-x';
    x.type = 'button';
    x.setAttribute('aria-label', 'Hide the news bar');
    x.textContent = '×';
    x.addEventListener('click', function () {
      try { window.sessionStorage.setItem(DISMISS, '1'); } catch (e) { /* private mode */ }
      document.documentElement.classList.remove('sn-on');
      if (bar) { bar.remove(); bar = null; }
    });
    bar.appendChild(x);

    document.body.appendChild(bar);
    document.documentElement.classList.add('sn-on');
  }

  function label(data) {
    var age = data.newest_age_s;
    // No reading -> no claim. The lamp is only lit when the server told us how old the
    // newest headline is AND that answer is under six hours.
    if (typeof age !== 'number' || data.stale || age > OLD_S) {
      brand.textContent = 'Symon Say News';
      var said = typeof age === 'number'
        ? (age < 172800 ? Math.round(age / 3600) + 'h' : Math.round(age / 86400) + 'd')
        : null;
      brand.appendChild(chip('sn-age', said ? said + ' old' : 'last known'));
      bar.classList.add('sn-old');
      return;
    }
    bar.classList.remove('sn-old');
    var lamp = document.createElement('s');       // the same lamp the rack rows use
    lamp.className = 'sn-lamp';
    brand.textContent = '';
    brand.appendChild(lamp);
    brand.appendChild(document.createTextNode('Symon Say News'));
  }

  function render(data) {
    var items = (data.items || []).filter(function (it) {
      return it && it.title && typeof it.url === 'string' && it.url.indexOf('https://') === 0;
    });
    if (!items.length) {                          // off, or a pass that reached nothing
      if (bar) { document.documentElement.classList.remove('sn-on'); bar.remove(); bar = null; }
      return;
    }
    if (!bar) build();
    run.textContent = '';
    run.appendChild(lane(items, false));
    run.appendChild(lane(items, true));
    label(data);

    // Constant speed, whatever the length. A fixed duration would crawl 12 headlines and
    // sprint 36; the distance travelled per wrap is one lane's width, so the duration has
    // to be measured from it. Set inline because only the browser knows how wide the text
    // rendered -- and left unset if the measurement fails, which leaves the bar still and
    // readable rather than animating at some guessed rate.
    //
    // 92 px/s is the second value tried and the reason is worth writing down, because the
    // first one was chosen by feel and measured badly: at 58 px/s, 32 headlines render
    // 16,420px of lane, so the last headline in the list arrives 283 SECONDS after the
    // page loads. Nobody waits five minutes for a bar. 92 px/s puts a full pass at ~178s
    // and still leaves a 500px headline sitting completely on a 1300px screen for about
    // nine seconds, which is three times what reading it takes.
    var w = run.firstChild.getBoundingClientRect().width;
    run.style.animationDuration = w > 0 ? Math.round(w / PX_PER_SEC) + 's' : '';
  }

  function load() {
    if (document.hidden) return;                  // a background tab does not need headlines
    fetch(ENDPOINT, { cache: 'no-store' })
      .then(function (r) { return r.ok ? r.json() : null; })
      .then(function (d) {
        // Only rebuild when the server actually measured something new. Re-rendering on
        // every poll would restart the crawl from the left every five minutes, mid-sentence.
        if (!d || (bar && d.at === stamp)) return;
        stamp = d.at;
        render(d);
      })
      .catch(function () { /* the bar keeps whatever it has; a failed poll is not news */ });
  }

  load();
  window.setInterval(load, POLL_MS);
  document.addEventListener('visibilitychange', function () { if (!document.hidden) load(); });
})();

/* Maintenance banner.
 *
 * Garrett, 2026-08-26: "Maintenance banner would be great for the symoneural portion and we
 * will be 100% powering dispatch through symoneural domain", and against a screenshot of the
 * rack, "all of these in image can be taken off and maintenance banners up".
 *
 * Separate IIFE, for the reason the lightbox block above already documents: the first block
 * in this file returns early on any page with no documentation tabs, which is nearly every
 * page this banner has to appear on. Appending to that block would have shipped a banner that
 * showed up on exactly one page.
 *
 * THE LIST IS NOT "EVERY PAGE". `ops/docs/MAINTENANCE-SURFACES.md` holds the same list with
 * the reading each entry was put there on, and backend/apps/test_maintenance_banner.py fails
 * if the two disagree. The reason it is a list is the house honesty rule read in the direction
 * people forget: a surface that works and is labelled down is as false as a dead one labelled
 * ready. RavenCalc, Coder, Project, Streamer and Live all read `ready` on /api/status at 08:23
 * on 2026-08-26, so they are not here and must not be added without a reading that says
 * otherwise.
 *
 * /demo/dispatchos is not on the list, and is additionally safe by construction: it is served
 * by backend/api.py and does not load this file at all. Both facts are asserted by the test,
 * because "it does not load ui.js" is true until somebody adds a script tag.
 */
(function () {
  'use strict';

  // Paths exactly as location.pathname. Both spellings are listed where the site answers on
  // both -- /livestack is a route in ops/Caddyfile and /livestack.html is the file on disk,
  // and a visitor can arrive by either.
  var DOWN = [
    // Corrected 2026-08-26 after the runtime cutover. chat, image, remix, reinforce,
    // sigils and studio were all on this list and all six now read `ready` on
    // /api/status -- the engines were rebuilt, the FLUX weights restored and the render
    // UI started, so the banner had become the exact falsehood the list was written to
    // prevent: "a surface that works and is labelled down is as false as a dead one
    // labelled ready". Only surfaces measured NOT ready remain.
    '/miner.html',
    '/exp.html', '/exp'
  ];

  var here = (location.pathname || '').replace(/\/+$/, '') || '/';
  if (DOWN.indexOf(here) === -1) return;

  // Styles are created here rather than added to symoneural.css on purpose: the banner is
  // meant to be deleted, and a rule left behind in a stylesheet after the markup stops being
  // emitted is the kind of residue nobody goes looking for.
  var css = document.createElement('style');
  css.textContent =
    '.maint{background:#3a2a00;border-bottom:1px solid #6b4f00;color:#ffd479;' +
      'font-size:14.5px;line-height:1.5}' +
    '.maint .wrap{display:flex;gap:12px;align-items:baseline;padding:11px 0}' +
    '.maint b{color:#ffe6ad}' +
    '.maint a{color:#ffe6ad}' +
    '@media (prefers-reduced-motion:no-preference){.maint{transition:none}}';
  document.head.appendChild(css);

  var bar = document.createElement('div');
  bar.className = 'maint';
  bar.setAttribute('role', 'status');
  bar.innerHTML =
    '<div class="wrap">' +
      '<b>Down for maintenance.</b>' +
      '<span>This surface is not being attended to right now, so treat anything it shows as ' +
      'stale. The rest of the site still works. Nothing here is lost &mdash; it is paused.</span>' +
    '</div>';

  // After the header, not before it: the masthead is how somebody navigates away from a page
  // that just told them not to trust it.
  var header = document.querySelector('header');
  if (header && header.parentNode) header.parentNode.insertBefore(bar, header.nextSibling);
  else document.body.insertBefore(bar, document.body.firstChild);
})();
