"""The DispatchOS page, as one self-contained string.

Task #106. Served by `routes.ui_router` at `/demo/dispatchos`.

## Why the markup lives here and not in `site/`

The path Garrett named has no extension, and `scripts/deploy.sh` publishes `site/` at
`-maxdepth 1` into the webroot -- so `/demo/dispatchos` cannot be a file there. Serving it
from the API is the same thing `@sections`, `@studio` and `@exp` already do in
`ops/Caddyfile`, and it has a second benefit worth stating: the #107 maintenance banner is
stamped into the generated static pages and injected by `site/ui.js`, and this page loads
neither. The customer surface cannot inherit a "down for maintenance" strip by accident.

## No external request, and no framework

Same rule as the rest of the site: everything a visitor loads comes off this box. No CDN,
no font fetch, no analytics. The styles are inline because this page is behind basicauth and
is not part of the cache-busted asset set that `tools/build/build_cachebust.py` stamps -- a
stylesheet link here would be the one asset on the page with no cache story.

## What is deliberately absent from the interface

The customer preview's "Deferred" column is a written promise to Donnie that those things
are *"a deliberate omission with a reason, not a gap to be quietly filled in later"*. So
there is no revenue tile, no customer database view, no repeat-rider panel and no metrics
row. The rider-facing estimate renders the preview's own em-dash pair until rate rules are
configured, and the page says why rather than showing a zero.
"""
from __future__ import annotations

PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>DispatchOS — SyMoNeuRaL</title>
<meta name="robots" content="noindex, nofollow">
<meta name="referrer" content="no-referrer">
<style>
:root{--bg:#0e100f;--panel:#151816;--line:#252a27;--fg:#e8efe9;--dim:#8fa096;
      --accent:#3ddc97;--warn:#d2a24c;--bad:#e06c6c;--chip:#1d2320}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--fg);
     font:15px/1.55 ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif}
a{color:var(--accent)}
header{border-bottom:1px solid var(--line);background:#0b0d0c}
.wrap{max-width:1180px;margin:0 auto;padding:0 20px}
.bar{display:flex;align-items:center;gap:14px;padding:14px 0}
.brand{font-weight:700;letter-spacing:.2px}
.brand i{font-style:normal;color:var(--accent)}
.tag{font-size:12px;color:var(--dim);border:1px solid var(--line);border-radius:99px;
     padding:2px 9px}
.spacer{flex:1}
.who{font-size:13px;color:var(--dim)}
button{font:inherit;cursor:pointer;border-radius:7px;border:1px solid var(--line);
       background:var(--chip);color:var(--fg);padding:7px 12px}
button:hover{border-color:var(--accent)}
button.primary{background:var(--accent);color:#06110b;border-color:var(--accent);font-weight:600}
button:disabled{opacity:.45;cursor:not-allowed}
input,select,textarea{font:inherit;background:#0f1211;color:var(--fg);
       border:1px solid var(--line);border-radius:7px;padding:8px 10px;width:100%}
label{display:block;font-size:12.5px;color:var(--dim);margin:10px 0 4px}
section{padding:22px 0}
h1{font-size:26px;margin:18px 0 4px}
h2{font-size:17px;margin:0 0 10px}
.lede{color:var(--dim);margin:0 0 18px;max-width:70ch}
.grid{display:grid;gap:16px}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:11px;padding:16px}
.cols{display:grid;grid-template-columns:1fr 340px;gap:16px}
@media(max-width:900px){.cols{grid-template-columns:1fr}}
.job{border:1px solid var(--line);border-radius:9px;padding:12px;margin-bottom:10px;
     background:#121514}
.job h3{margin:0 0 6px;font-size:15px}
.row{display:flex;gap:10px;align-items:center;flex-wrap:wrap}
.state{font-size:11.5px;text-transform:uppercase;letter-spacing:.6px;padding:2px 8px;
       border-radius:99px;border:1px solid var(--line);color:var(--dim)}
.state.requested{color:var(--warn);border-color:#4a3a12}
.state.quoted{color:#8fb7ff;border-color:#22345a}
.state.confirmed,.state.dispatched{color:var(--accent);border-color:#1d4a35}
.state.completed,.state.reviewed{color:var(--dim)}
.state.cancelled{color:var(--bad);border-color:#4a2020}
.meta{color:var(--dim);font-size:13px}
.kv{display:grid;grid-template-columns:118px 1fr;gap:4px 10px;font-size:13.5px;margin:8px 0}
.kv dt{color:var(--dim)}
.kv dd{margin:0}
.trail{border-left:2px solid var(--line);margin:10px 0 0;padding:0 0 0 12px;font-size:13px;
       color:var(--dim)}
.trail li{margin:3px 0;list-style:none}
.est{font-size:20px;font-weight:600}
.note{font-size:12.5px;color:var(--dim);margin-top:6px}
.err{color:var(--bad);font-size:13.5px;min-height:19px}
.ok{color:var(--accent)}
.ai-answer{white-space:pre-wrap;background:#0f1211;border:1px solid var(--line);
           border-radius:8px;padding:11px;margin-top:10px}
.badge{font-size:11.5px;color:var(--dim);border:1px solid var(--line);border-radius:99px;
       padding:1px 8px}
.badge.local{color:var(--warn);border-color:#4a3a12}
.hide{display:none}
footer{border-top:1px solid var(--line);color:var(--dim);font-size:12.5px;padding:18px 0;
       margin-top:30px}
</style>
</head>
<body>
<header><div class="wrap bar">
  <span class="brand">SyMoNeu<i>RaL</i> · DispatchOS</span>
  <span class="tag" id="envtag">preview</span>
  <span class="spacer"></span>
  <span class="who" id="who"></span>
  <button id="out" class="hide">Sign out</button>
</div></header>

<div class="wrap">

<!-- ------------------------------------------------------------------ sign in -->
<section id="signin">
  <h1>DispatchOS</h1>
  <p class="lede">Bookings, quotes, dispatch and reminders for a solo operator. Sign in with
     the account you were given.</p>
  <div class="panel" style="max-width:400px">
    <label for="u">Username</label><input id="u" autocomplete="username">
    <label for="p">Password</label><input id="p" type="password" autocomplete="current-password">
    <div style="margin-top:14px" class="row">
      <button class="primary" id="go">Sign in</button>
    </div>
    <p class="err" id="loginerr"></p>
  </div>
</section>

<!-- ------------------------------------------------------------------ the app -->
<section id="app" class="hide">
  <div class="cols">
    <div>
      <div class="row" style="justify-content:space-between;margin-bottom:12px">
        <h2 id="boardtitle">The board</h2>
        <span class="meta" id="countline"></span>
      </div>
      <div id="jobs"></div>
      <p class="meta" id="empty"></p>
    </div>

    <div>
      <div class="panel">
        <h2>Request a trip</h2>
        <label for="pickup">Pickup</label><input id="pickup" placeholder="Riverside Ave">
        <label for="dropoff">Drop-off</label><input id="dropoff" placeholder="Regional airport">
        <label for="when">When</label><input id="when" placeholder="Tuesday, 9:40 am">
        <div class="row" style="gap:10px">
          <div style="flex:1"><label for="pax">Passengers</label>
            <input id="pax" type="number" min="1" max="16" value="1"></div>
          <div style="flex:1"><label for="bags">Luggage</label>
            <input id="bags" type="number" min="0" max="32" value="0"></div>
        </div>
        <label for="rider">Rider name</label><input id="rider">
        <label for="contact">Contact</label><input id="contact" placeholder="mobile on file">
        <div style="margin-top:14px"><button class="primary" id="book">Request trip</button></div>
        <p class="err" id="bookerr"></p>
      </div>

      <div class="panel" style="margin-top:16px">
        <h2>SyMon AI <span class="badge" id="aibadge">assistant</span></h2>
        <p class="note" style="margin-top:0">Tied to this board — it answers from the jobs
           above, not from the internet.</p>
        <label for="q">Ask about the board</label>
        <textarea id="q" rows="2" placeholder="What is the next job?"></textarea>
        <div style="margin-top:10px"><button id="ask">Ask</button></div>
        <div class="ai-answer hide" id="answer"></div>
      </div>

      <div class="panel hide" id="rulespanel" style="margin-top:16px">
        <h2>Rate rules</h2>
        <p class="note" style="margin-top:0" id="rulestate"></p>
      </div>
    </div>
  </div>
</section>
</div>

<footer><div class="wrap">
  Private preview for a named recipient. Sample data only — no message, booking or payment
  here is real, and nothing on this page is a contract.
</div></footer>

<script>
var API = '/api/dispatchos';
var me = null, board = null;
var $ = function (s) { return document.querySelector(s); };

function esc(s) {
  return String(s == null ? '' : s).replace(/[&<>"']/g, function (c) {
    return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c];
  });
}

// Every server call goes through here so a 401 has exactly one handler. Without it, a
// session that expired mid-session leaves the board on screen with stale rows and every
// button silently failing -- which reads as "the app is broken", not "sign in again".
async function call(path, opts) {
  var r = await fetch(API + path, Object.assign({
    headers: {'Content-Type': 'application/json'}, credentials: 'same-origin'
  }, opts || {}));
  if (r.status === 401) { me = null; paint(); throw new Error('sign in again'); }
  var body = r.status === 204 ? {} : await r.json().catch(function () { return {}; });
  if (!r.ok) throw new Error(body.detail || body.error || ('HTTP ' + r.status));
  return body;
}

function stateChip(s) { return '<span class="state ' + esc(s) + '">' + esc(s) + '</span>'; }

function when(ts) {
  if (!ts) return '';
  var d = new Date(ts * 1000);
  return d.toLocaleString();
}

// The operator's next legal step. Mirrors store.NEXT -- the server refuses anything else,
// so this only decides which button to draw, never whether the move is allowed.
var NEXT = {
  requested: [], quoted: ['confirmed'], confirmed: ['dispatched'],
  dispatched: ['completed'], completed: ['reviewed'], reviewed: [], cancelled: []
};

function jobHtml(b) {
  var op = me && me.role === 'operator';
  var q = b.quote || null;
  var h = '<div class="job" data-id="' + b.id + '">';
  h += '<div class="row" style="justify-content:space-between">';
  h += '<h3>' + esc(b.ref) + ' &middot; ' + esc(b.pickup) + ' &rarr; ' + esc(b.dropoff) + '</h3>';
  h += stateChip(b.state) + '</div>';
  h += '<dl class="kv">';
  h += '<dt>When</dt><dd>' + (esc(b.when_text) || '<span class="meta">unspecified</span>') + '</dd>';
  h += '<dt>Passengers</dt><dd>' + esc(b.passengers) + ' &middot; ' + esc(b.luggage) + ' bags</dd>';
  if (b.rider) h += '<dt>Rider</dt><dd>' + esc(b.rider) + '</dd>';
  if (op && b.contact) h += '<dt>Contact</dt><dd>' + esc(b.contact) + '</dd>';
  if (b.driver) h += '<dt>Driver</dt><dd>' + esc(b.driver.name) + '</dd>';
  h += '</dl>';

  if (q) {
    h += '<div class="row" style="justify-content:space-between;align-items:baseline">';
    h += '<span class="meta">Estimate shown to rider</span>';
    h += '<span class="est">' + esc(q.display) + '</span></div>';
    if (q.basis) h += '<p class="note">' + esc(q.basis) + '</p>';
  }

  if (op) {
    h += '<div class="row" style="margin-top:10px">';
    if (b.state === 'requested') h += '<button data-act="quote">Quote</button>';
    (NEXT[b.state] || []).forEach(function (n) {
      h += '<button data-act="advance" data-to="' + n + '">' +
           (n === 'dispatched' ? 'Dispatch' : n === 'confirmed' ? 'Confirm' :
            n === 'completed' ? 'Complete' : 'Mark reviewed') + '</button>';
    });
    if (b.state === 'confirmed' || b.state === 'dispatched')
      h += '<button data-act="msg" data-kind="reminder">Compose reminder</button>';
    if (b.state === 'completed')
      h += '<button data-act="msg" data-kind="review_request">Request review</button>';
    if (['requested','quoted','confirmed','dispatched'].indexOf(b.state) >= 0)
      h += '<button data-act="advance" data-to="cancelled">Cancel</button>';
    h += '</div>';
  }

  if (b.events && b.events.length) {
    h += '<ul class="trail">';
    b.events.forEach(function (e) {
      h += '<li>' + esc(when(e.at)) + ' &mdash; ' + esc(e.kind) +
           (e.detail ? ': ' + esc(e.detail) : '') + ' <span class="meta">(' +
           esc(e.actor) + ')</span></li>';
    });
    h += '</ul>';
  }
  if (b.messages && b.messages.length) {
    h += '<p class="note"><b>Messages composed:</b> ' + b.messages.length +
         ' &mdash; none sent. Live routing needs approved email configuration.</p>';
  }
  h += '<p class="err" data-err></p></div>';
  return h;
}

async function load() {
  board = await call('/board');
  me = board.user;
  paint();
}

function paint() {
  if (!me) {
    $('#app').classList.add('hide'); $('#signin').classList.remove('hide');
    $('#who').textContent = ''; $('#out').classList.add('hide');
    return;
  }
  $('#signin').classList.add('hide'); $('#app').classList.remove('hide');
  $('#out').classList.remove('hide');
  $('#who').textContent = me.label || me.username;
  $('#who').innerHTML = esc(me.label || me.username) +
      ' <span class="badge">' + esc(me.role) + '</span>';
  $('#boardtitle').textContent = me.role === 'operator' ? 'The board' : 'Your trips';

  var bs = board.bookings || [];
  $('#jobs').innerHTML = bs.map(jobHtml).join('');
  $('#empty').textContent = bs.length ? '' :
      (me.role === 'operator' ? 'No jobs yet.' : 'You have not requested a trip yet.');

  var c = board.counts || {};
  var parts = Object.keys(c).filter(function (k) { return c[k]; })
                    .map(function (k) { return c[k] + ' ' + k; });
  $('#countline').textContent = parts.join(' · ');

  if (me.role === 'operator') {
    $('#rulespanel').classList.remove('hide');
    $('#rulestate').textContent = board.rates_configured
      ? 'Rate rules are configured; quotes produce a figure.'
      : 'No rate rules configured, so every quote shows —— rather than a number. Rates are '
        + 'agreed in written scope before any figure is shown to a rider.';
  } else {
    $('#rulespanel').classList.add('hide');
  }
}

$('#go').addEventListener('click', async function () {
  $('#loginerr').textContent = '';
  try {
    await call('/login', {method:'POST', body: JSON.stringify(
      {username: $('#u').value, password: $('#p').value})});
    $('#p').value = '';
    await load();
  } catch (e) { $('#loginerr').textContent = e.message; }
});
$('#p').addEventListener('keydown', function (e) { if (e.key === 'Enter') $('#go').click(); });

$('#out').addEventListener('click', async function () {
  try { await call('/logout', {method:'POST'}); } catch (e) { /* going anyway */ }
  me = null; paint();
});

$('#book').addEventListener('click', async function () {
  $('#bookerr').textContent = '';
  try {
    await call('/bookings', {method:'POST', body: JSON.stringify({
      pickup: $('#pickup').value, dropoff: $('#dropoff').value,
      when_text: $('#when').value, passengers: +$('#pax').value || 1,
      luggage: +$('#bags').value || 0, rider: $('#rider').value,
      contact: $('#contact').value})});
    ['#pickup','#dropoff','#when','#rider','#contact'].forEach(function (s) { $(s).value=''; });
    await load();
  } catch (e) { $('#bookerr').textContent = e.message; }
});

// One delegated listener rather than one per button: the board is re-rendered on every
// action, so per-button listeners would be re-attached constantly and leak.
$('#jobs').addEventListener('click', async function (ev) {
  var btn = ev.target.closest('button[data-act]');
  if (!btn) return;
  var job = btn.closest('.job'), id = job.getAttribute('data-id');
  var err = job.querySelector('[data-err]');
  err.textContent = '';
  btn.disabled = true;
  try {
    if (btn.dataset.act === 'quote') {
      await call('/bookings/' + id + '/quote', {method:'POST', body:'{}'});
    } else if (btn.dataset.act === 'advance') {
      await call('/bookings/' + id + '/advance',
                 {method:'POST', body: JSON.stringify({to: btn.dataset.to})});
    } else if (btn.dataset.act === 'msg') {
      await call('/bookings/' + id + '/message',
                 {method:'POST', body: JSON.stringify({kind: btn.dataset.kind})});
    }
    await load();
  } catch (e) { err.textContent = e.message; btn.disabled = false; }
});

$('#ask').addEventListener('click', async function () {
  var box = $('#answer');
  box.classList.remove('hide');
  box.textContent = 'Asking…';
  try {
    var out = await call('/ask', {method:'POST',
                                  body: JSON.stringify({question: $('#q').value})});
    box.textContent = out.answer;
    var b = $('#aibadge');
    // The page says which one answered. An answer produced without the model, rendered as
    // though the model produced it, is the decorative-indicator failure this project has a
    // standing rule about.
    b.textContent = out.model ? 'assistant' : 'assistant unavailable';
    b.className = 'badge' + (out.model ? '' : ' local');
    if (!out.model && out.reason) box.textContent += '\n\n(' + out.reason + ')';
  } catch (e) { box.textContent = e.message; }
});

// A session cookie may already be valid, so try the board before showing a login form.
call('/board').then(function (b) { board = b; me = b.user; paint(); })
              .catch(function () { paint(); });
</script>
</body>
</html>
"""
