/* The helpers every prompt surface uses -- one file, instead of one copy per page.
 *
 * This block used to live inside `tools/build_pages.py`'s SHELL constant and was emitted
 * INLINE into thirteen pages: chat, exp, gateway, image, miner, project, ravencalc,
 * reinforce, remix, sigils, streamer and studio all carried a byte-identical 1,368-byte
 * copy. Identical in the generator is not identical on the wire -- it was re-parsed on
 * every navigation and could never be cached, and `const $` was declared at global scope
 * on each of those pages independently.
 *
 * ## It is loaded WITHOUT `defer`, and that is deliberate
 *
 * Every page that uses these helpers follows this tag with its own INLINE `<script>`, and
 * an inline script runs at parse time -- before any deferred script has executed. Deferring
 * this file would therefore leave `$`, `api()` and `status()` undefined at exactly the
 * moment the page's own code first reaches for them. `console.js` and `ui.js` keep their
 * `defer` because nothing calls into them; they only ever call out.
 *
 * Everything below is unchanged from the inline version. The bounds it describes are still
 * enforced on the server; these exist to make the UI honest about the limits, not to be them.
 */
// Shared helpers. Every bound below is also enforced on the server -- these exist to make
// the UI honest about the limits, not to be the limits.
const $ = (s, r=document) => r.querySelector(s);
function status(el, text, busy) {
  const dot = $('s', el); if (dot) dot.className = busy ? 'busy' : 'on';
  const grow = $('.grow', el); if (grow) grow.textContent = text;
}
// These three surfaces use a <textarea> rather than an <input> so a long prompt WRAPS and
// can be read back. A textarea takes Enter as a newline, so submit is restored explicitly;
// Shift+Enter still gives a deliberate line break. Applied to whichever box the page has.
document.addEventListener('DOMContentLoaded', () => {
  const box = $('#prompt') || $('#expr') || $('#brief');
  const f = $('#form');
  if (!box || !f || box.tagName !== 'TEXTAREA' || box.dataset.enterBound) return;
  box.dataset.enterBound = '1';
  box.addEventListener('keydown', e => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); f.requestSubmit(); }
  });
});
async function api(path, payload) {
  const r = await fetch(path, {
    method: 'POST', headers: {'Content-Type': 'application/json'},
    body: JSON.stringify(payload)
  });
  const body = await r.json().catch(() => ({error: 'Unreadable response.'}));
  if (!r.ok) throw new Error(body.error || ('HTTP ' + r.status));
  return body;
}
