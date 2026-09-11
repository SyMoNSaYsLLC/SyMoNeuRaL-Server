/* The application shell: narrow-viewport navigation, and nothing else.
 *
 * ## Why this is a separate file rather than a fifth IIFE in ui.js
 *
 * `site/ui.js` is documentation tabs, the render lightbox, the Symon Say News bar and the
 * maintenance banner -- four unrelated concerns that share a file for historical reasons,
 * and whose own comments record the cost: each one had to be written as its own top-level
 * IIFE because "the first block in this file returns early on any page with no documentation
 * tabs, which is nearly every page". Adding a fifth would repeat that. The shell owns one
 * thing, so it gets one file.
 *
 * ## What it replaces
 *
 * Below 780px the stylesheet used to carry `nav a:not(.cta){display:none}`, and between 781
 * and 900px a second block tightened the gap and let the row wrap. Both are gone; this file
 * and one media query cover the whole range. The first of them left the
 * "Have one built" button as the only navigation anywhere on the site at phone widths -- no
 * Account, no Documentation, no Live stack, no API -- and it did not fix the overflow it was
 * written for: measured at 360, 390 and 430px the header laid out identically with the CTA at
 * left=336, right=405, outside all three viewports. This file gives those links somewhere to
 * go instead of deleting them.
 *
 * ## Progressive enhancement, and why the class goes on first
 *
 * Every drawer rule in symoneural.css is gated on `html.js`. Without this file the nav stays
 * in normal flow and wraps onto a second row: folding rather than dropping, which is what
 * CLAUDE.md permits. The class is set at the TOP of this file, synchronously, before the
 * toggle is built -- if it were set afterwards, or if this were not `defer`red, a slow page
 * would paint the drawer's fixed-position panel over the header with nothing able to close it.
 *
 * ## It builds its own markup
 *
 * The toggle is created here rather than emitted into the pages, because the header lives in
 * 24 files owned by nine different generators plus five hand-written pages. Reading the `<nav>`
 * that is already there and adding one button beside it makes every page get the drawer from a
 * single file, and makes it impossible for one page to be missed. There is no markup to keep
 * in sync, so there is nothing to drift.
 */
(function () {
  'use strict';

  var root = document.documentElement;
  root.classList.add('js');

  // Must match the drawer's media query in symoneural.css exactly. A media query cannot read
  // a custom property, so this number is repeated in exactly two places and both say so.
  // 900px is measured, not a device class: the six-link nav runs ~634px and only clears the
  // bar at 860px.
  var NARROW = '(max-width:900px)';

  // The site header, not a page's own. `header > .bar > nav` is the shape all 24 pages share;
  // chat's conversation rail is a `<div role=navigation>` and the footer's is `.foot nav`, and
  // neither must be picked up here.
  var header = document.querySelector('header');
  var bar = header && header.querySelector('.bar');
  var nav = bar && bar.querySelector(':scope > nav');
  if (!nav) return;                  // streamer-watch and share-dispatchos have no header

  // Guard against a second run. A page that loaded this file twice -- or a generator that
  // emitted the tag twice -- would otherwise get two toggles and two sets of listeners, and
  // the second would immediately undo the first's every click.
  if (nav.dataset.shellBound) return;
  nav.dataset.shellBound = '1';

  if (!nav.id) nav.id = 'sitenav';

  var btn = document.createElement('button');
  btn.type = 'button';
  btn.className = 'navtoggle';
  btn.setAttribute('aria-label', 'Menu');
  btn.setAttribute('aria-expanded', 'false');
  btn.setAttribute('aria-controls', nav.id);
  // Inline SVG rather than a glyph: the hamburger characters that look right (U+2630, U+2261)
  // render as a serif stack or as a maths symbol depending on the font that answers for them,
  // and this header's stack is five deep.
  btn.innerHTML =
    '<svg viewBox="0 0 20 20" fill="none" stroke="currentColor" stroke-width="1.8" ' +
      'stroke-linecap="round" aria-hidden="true">' +
      '<path d="M3 5h14M3 10h14M3 15h14"></path>' +
    '</svg>';

  // Before the nav, so the tab order is wordmark -> toggle -> the links it opens. Putting it
  // after would make a keyboard user tab through every drawer link to reach the control that
  // opens the drawer.
  bar.insertBefore(btn, nav);

  var open = false;

  function set(next) {
    open = next;
    nav.classList.toggle('open', open);
    btn.setAttribute('aria-expanded', String(open));
  }

  function close(focusToggle) {
    if (!open) return;
    set(false);
    // Only pull focus back when the drawer was dismissed by a keyboard action. Doing it on
    // every close would yank focus to the toggle when somebody taps a link, fighting the
    // navigation they just asked for.
    if (focusToggle) btn.focus();
  }

  btn.addEventListener('click', function (e) {
    e.stopPropagation();             // or the document listener below closes it again at once
    set(!open);
    if (open) {
      var first = nav.querySelector('a');
      if (first) first.focus();
    }
  });

  // Tapping a link closes the drawer. Most of these are real navigations that replace the
  // document anyway, but `/documentation.html#hardware` from documentation.html is a same-page
  // hash change: the page does not reload and the drawer would stay open over the thing it
  // just scrolled to.
  nav.addEventListener('click', function (e) {
    if (e.target.closest('a')) close(false);
  });

  document.addEventListener('click', function (e) {
    if (!open) return;
    if (!nav.contains(e.target) && !btn.contains(e.target)) close(false);
  });

  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') close(true);
  });

  // Crossing back to a wide viewport must not leave `open` set: the drawer rules stop applying
  // above 900px, so the class would sit on a normal horizontal nav doing nothing
  // visible -- and then reappear as an already-open drawer the next time the window narrowed.
  // The brief asks that responsive transitions not require a reload; this is that.
  var mq = window.matchMedia(NARROW);
  var onChange = function (e) { if (!e.matches) close(false); };
  if (mq.addEventListener) mq.addEventListener('change', onChange);
  else if (mq.addListener) mq.addListener(onChange);        // Safari < 14

  /* ---- the scoped documentation link ------------------------------------------------
   *
   * Every application now has one canonical docs URL at `/docs/<id>`, listing only the
   * routes that application owns. A page that does not link it has one in name only, so the
   * link is built HERE for the same reason the drawer toggle is: the header lives in 24
   * files owned by nine generators plus five hand-written pages, and a link added per page
   * is a link some page does not get. One file, no markup to keep in sync, nothing to drift.
   *
   * The mapping is from PAGE PATH to application id and is deliberately explicit rather than
   * derived from the filename. Three of them do not follow the pattern -- `/livestack/coder`
   * and `/livestack/live` have no `.html` at all, `/reinforce.html` documents the id `train`,
   * and `/streamer-watch.html` is a viewer for the streamer application rather than an
   * application of its own -- and a filename rule would get all three wrong quietly.
   *
   * THE HYPHENATED SPELLINGS ARE DELIBERATELY ABSENT. `/live-stack/coder`,
   * `/live-stack/live` and `/live-stack/image` all still answer and none of them redirects,
   * so a visitor who typed one gets the page -- they simply do not get this link. That is
   * the standing rule rather than an oversight: Garrett, on the two spellings, *"we need to
   * get rid of live-stack i believe its only livestack"*, and
   * `apps/test_deploy_routes.py::test_nothing_published_carries_the_hyphenated_spelling`
   * greps every published file for it. This table is published, so a key here is a
   * published occurrence even though nothing renders it as an href -- which is exactly what
   * that test caught, and it was right to.
   *
   * A page not in this table gets NO link, which is the correct outcome rather than a
   * fallback: `/credits.html`, `/build.html` and `/documentation.html` are site pages, not
   * applications, and pointing them at a scoped API reference would be inventing an
   * ownership claim to fill a gap. `/docs` is in the footer of every page already.
   */
  var DOCS = {
    '/chat.html': 'chat',
    '/image.html': 'image',
    '/livestack/image': 'image',
    '/remix.html': 'remix',
    '/ravencalc.html': 'ravencalc',
    '/sigils.html': 'sigils',
    '/project.html': 'project',
    '/miner.html': 'miner',
    '/gateway.html': 'gateway',
    '/streamer.html': 'streamer',
    '/studio.html': 'studio',
    '/studio': 'studio',
    '/reinforce.html': 'train',
    '/exp.html': 'exp',
    '/exp': 'exp',
    '/live.html': 'live',
    '/livestack/live': 'live',
    '/coder.html': 'coder',
    '/livestack/coder': 'coder',
    '/account.html': 'accounts',
    '/controlboard.html': 'controlboard',
    '/controlboard': 'controlboard'
  };

  /* ---- the page family: VALIDATE, do not decide ---------------------------------------
   *
   * Handshake 6.1 set `data-family` from a table in this file. Handshake 6.2 moved the
   * authority into static markup -- `tools/page_families.py` is the one authored source, the
   * generators emit the attribute, and the hand-authored pages carry it -- because a family
   * set from JavaScript is a family the page does not have until JavaScript runs. Measured
   * before that move: 14 pages rendered 224px narrower with scripting off, 1120px instead of
   * 1344px at a 1440px viewport. Measured after: 0.
   *
   * So this no longer carries a map, and deliberately so. Restating the pairs here would put
   * one fact in four places -- the authored source, the generated markup, this file and the
   * tests -- which is the failure `backend/apps/ROSTER.md` exists to prevent.
   *
   * What is left is a check. If a page that has a workspace arrives with no family, the
   * layout silently falls back to the 1120px prose width, which looks like a design choice
   * rather than a missing attribute. Saying so in the console is the difference between a
   * bug someone can find and one they cannot. It NEVER writes the attribute: a fallback that
   * quietly supplies the right answer would hide exactly the omission it is watching for,
   * and `tests/architecture.mjs` asserts the static value on every page anyway.
   */
  var family = root.getAttribute('data-family');
  if (!family && (document.querySelector('.apphead') || document.getElementById('units'))) {
    // `.apphead` is the application page header and `#units` is the rack or its compact
    // rail; either means this page has a workspace and should have been classified.
    if (window.console && console.warn) {
      console.warn('[symoneural] this page has a workspace and no data-family: it will use '
                 + 'the 1120px prose width. Classify it in tools/page_families.py.');
    }
  }

  var appId = DOCS[location.pathname];
  if (!appId) return;
  // Guard against a page that already carries one -- a generator may grow its own later,
  // and two "Docs" links in one header is worse than none.
  if (nav.querySelector('a[data-appdocs]')) return;

  var docs = document.createElement('a');
  docs.href = '/docs/' + appId;
  docs.setAttribute('data-appdocs', appId);
  docs.textContent = 'Docs';
  // Before the call to action, so the order is destinations then action -- the same reason
  // the toggle is inserted before the nav rather than after it. `.cta` is the last child of
  // every one of these headers; if it is ever not, appending is still correct.
  var cta = nav.querySelector('a.cta');
  if (cta) nav.insertBefore(docs, cta); else nav.appendChild(docs);
})();
