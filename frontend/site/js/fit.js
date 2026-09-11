/* fit.js -- make the one-screen layout fit the screen instead of clipping it.
 *
 * Owner, twice: "we took scroll feature away as i requested but that means we must auto
 * scale to user", and "need to figure out a way to display everything at 100 browser
 * percentage". The fold sets `overflow:hidden` on html and body, so a panel whose content
 * is taller than its box loses the bottom of it -- and the only workaround was to zoom the
 * browser out, which is asking the visitor to fix the layout.
 *
 * What this does: measures the active panel's content against the space it has, and scales
 * the panel down until it fits. `zoom` rather than `transform:scale()` -- transform leaves
 * the element's layout box at the original size, so the page still overflows and the
 * scrollbar still lies about where things are; zoom re-lays-out and the measurements stay
 * honest.
 *
 * The floor is 0.72. Below that the text is too small to read, so the panel gets its
 * scrollbar back rather than shrinking further. A page that scrolls is worse than one that
 * fits and better than one that is unreadable.
 *
 * It never runs below the fold's own breakpoint: the browser is asked, via matchMedia, so
 * there is one copy of the breakpoint and it is the one in the stylesheet.
 */
(function () {
  'use strict';

  var FLOOR = 0.72;
  var mq = window.matchMedia('(min-width:1301px) and (min-height:740px)');
  var PANELS = '#hero, #rack, #console, #more';
  var frame = 0;

  function panels() {
    return [].slice.call(document.querySelectorAll(PANELS));
  }

  function measure(el) {
    // scrollHeight includes the overflow; clientHeight is the box it has to live in.
    // Both are read with zoom already reset, or the ratio compounds on every resize.
    el.style.zoom = '';
    var have = el.clientHeight, want = el.scrollHeight;
    return (have > 0 && want > have) ? have / want : 1;
  }

  function apply() {
    frame = 0;
    var on = mq.matches && document.documentElement.classList.contains('ns');
    panels().forEach(function (el) {
      if (!on || el.hidden) { el.style.zoom = ''; el.style.overflowY = ''; return; }
      var ratio = measure(el);
      if (ratio >= 1) { el.style.zoom = ''; el.style.overflowY = 'hidden'; return; }
      if (ratio < FLOOR) { el.style.zoom = ''; el.style.overflowY = 'auto'; return; }
      // A hair under the exact ratio: sub-pixel rounding after re-layout can otherwise
      // leave one row still clipped, which looks identical to not having run at all.
      el.style.zoom = (ratio * 0.995).toFixed(4);
      el.style.overflowY = 'hidden';
    });
  }

  function schedule() {
    if (frame) return;
    frame = requestAnimationFrame(apply);
  }

  window.addEventListener('resize', schedule);
  window.addEventListener('hashchange', schedule);
  document.addEventListener('DOMContentLoaded', schedule);
  if (document.readyState !== 'loading') schedule();

  // The tab strip hides and shows panels without a resize or a hash change on every path,
  // and fonts land after first paint and change every measurement.
  if (window.MutationObserver) {
    new MutationObserver(schedule).observe(document.documentElement, {
      attributes: true, attributeFilter: ['class', 'hidden'], subtree: true
    });
  }
  if (document.fonts && document.fonts.ready) document.fonts.ready.then(schedule);

  // Exposed so a page that rebuilds a panel's contents can say so.
  window.symoneuralFit = schedule;
}());
