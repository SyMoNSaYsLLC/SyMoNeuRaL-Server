/* SyMoNeuRaL control board client.
 *
 * One socket drives every live element on the page: the rack units and the instrument
 * modules. It costs one upgrade handshake and one baseline snapshot, and after that the
 * server sends only what changed. An idle machine sends nothing at all -- which is most of
 * the time, and is the point.
 *
 * State lives here and gets patched in place. The server never re-sends a field that did
 * not move, so the client is the thing that knows the whole picture; the wire only ever
 * carries news. Falls back to conditional polling if the socket cannot be established,
 * because a proxy that will not upgrade should degrade to a working page rather than a
 * dead one.
 *
 * Served as a separate file on purpose: it is byte-identical across five pages, so the
 * browser fetches it once and reuses it. Inlining it would re-send the same 6 KB per page.
 */
(function () {
  'use strict';

  var state = null;          // the whole rack, patched in place
  var socket = null;
  var pollTimer = null;
  var etag = null;
  var retry = 0;
  var reconnectTimer = null;

  // ---------------------------------------------------------------- rendering

  var POWER =
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" ' +
    'stroke-linecap="round"><path d="M12 3v9"/><path d="M6.6 6.6a8 8 0 1 0 10.8 0"/></svg>';
  var WORDS = {ready: 'ready', busy: 'busy', queued: 'queued', offline: 'offline',
               unreachable: 'unreachable'};
  // Which states mean the surface is UP. Everything else -- including a state this
  // file has never heard of -- renders dark.
  //
  // It was the other way round twice here: `state === 'offline' ? dark : lit`, in
  // `leds()` and again in `subs()`. That is an allow-list of ways to be OFF, so any
  // new state arrived LIT. `unreachable` was added to the API on 2026-09-10 and would
  // have rendered a dead process as powered in both places -- the decorative status
  // light `RackPowerGate` exists to prevent, arriving from the display side.
  //
  // Inverted deliberately: a plate lights only for a state known to mean alive, so an
  // unknown state fails to 'looks down' rather than to 'looks fine'.
  var LIVE = {ready: 1, busy: 1, queued: 1};
  function powered(state) { return !!LIVE[state]; }
  // The bus plate names the hardware a surface actually runs on. It used to be
  // `u.bus === 'cpu' ? 'CPU' : 'GPU'`, which was fine while there were only two buses and
  // silently wrong the moment there were more -- an ASIC surface would have printed "GPU",
  // a plate on a page arguing that every reading is real, claiming the wrong hardware.
  // Anything unrecognised prints '--' rather than guessing.
  var BUSES = {gpu: 'GPU', cpu: 'CPU', asic: 'ASIC', net: 'NET'};
  function busLabel(b) { return BUSES[b] || '--'; }

  function el(id) { return document.getElementById(id); }
  function txt(id, value) { var n = el(id); if (n) n.textContent = value; }

  function leds(u) {
    // `unreachable` is the split's state: the process that owns this row did not answer.
    // It must NOT be folded into `offline`, which means the weights or engine are missing.
    //
    // Both branches below used to fall through for any unrecognised state, and `pwr` fell
    // through to 'led on' -- so a dead surface rendered with its POWER LED LIT. That is the
    // decorative status light `RackPowerGate` exists to prevent, arriving from the display
    // side instead. Dark plate, amber activity blink: visibly not the same as `offline`,
    // and visibly not healthy.
    var act = u.state === 'busy' ? 'led amber blink'
            : u.state === 'queued' ? 'led blue blink'
            : u.state === 'unreachable' ? 'led amber blink' : 'led';
    var pwr = powered(u.state) ? 'led on' : 'led';
    return '<span class="leds"><i class="' + pwr + '"></i><i class="' + act + '"></i>' +
           '<i class="led ' + (u.bus !== 'gpu' ? 'blue' : '') + '"></i></span>';
  }

  // The child components a row owns, rendered UNDER it rather than beside it.
  //
  // This is the display half of the folds. `miner` has carried three children since the
  // gateway fold and `studio` has carried Reinforce and Exp since 2026-08-29, and until now
  // the rack rendered only the parent -- so a reader of the front page could see twelve rows
  // and had no way to learn that five more surfaces exist under three of them. The previous
  // shape was worse than that: `train` and `exp` were TOP-LEVEL rows, which did not merely
  // omit the relationship, it asserted the opposite one. They looked like peers of Studio.
  //
  // Rendered as `<span>` inside the parent `<a>`, not as their own links. A child is part of
  // the surface you are already clicking through to -- `/miner.html` gives each of its three
  // its own card, `/studio` its two -- and a nested `<a>` inside an `<a>` is invalid markup
  // that browsers recover from by closing the outer one early, which would silently break
  // the parent row's own click target.
  //
  // Every value here is a READING from /api/status. No child is drawn with a state this file
  // invents, and a row with no `sub` gets no strip at all rather than an empty one.
  function subs(u) {
    if (!u.sub || !u.sub.length) return '';
    return '<span class="usubs">' + u.sub.map(function (s) {
      return '<span class="usub" data-state="' + s.state + '">' +
        '<i class="led' + (powered(s.state) ? ' on' : '') + '"></i>' +
        '<b>' + s.label + '</b>' +
        '<em>' + busLabel(s.bus) + '</em>' +
        '<u>' + (WORDS[s.state] || s.state) + '</u>' +
      '</span>';
    }).join('') + '</span>';
  }

  function renderRack() {
    var host = el('units');
    if (!host || !state) return;
    host.innerHTML = state.units.map(function (u) {
      var kids = subs(u);
      // `has-subs` is on the row, not on the strip, so the CSS can give a parent the extra
      // height its children need without every childless row paying for it.
      return '<a class="unit' + (kids ? ' has-subs' : '') + '" data-state="' + u.state +
          '" href="' + u.href + '">' +
        leds(u) +
        '<span class="pwr">' + POWER + '</span>' +
        '<span class="uname"><b>' + u.label + '</b><span>' + u.spec +
          ' &middot; ' + u.detail + '</span></span>' +
        '<span class="ubus">' + busLabel(u.bus) + '</span>' +
        '<span class="ustate"><span class="txt">' + (WORDS[u.state] || u.state) + '</span>' +
          '<span class="slot">' + u.slot + '</span></span>' +
        '<span class="scan"><i></i></span>' +
        kids +
        '</a>';
    }).join('');
  }

  function meter(id, pct, warn) {
    var n = el(id);
    if (!n) return;
    n.firstElementChild.style.width = Math.max(0, Math.min(100, pct)) + '%';
    n.classList.toggle('warn', !!warn);
  }

  function renderConsole() {
    if (!state) return;
    var g = state.gpu || {};

    if (g.vram_free_mib != null && g.vram_total_mib) {
      txt('m-vram', (g.vram_free_mib / 1024).toFixed(1));
      var vn = el('m-vram');
      if (vn && !vn.querySelector('u')) vn.insertAdjacentHTML('beforeend', '<u>GiB</u>');
      meter('m-vrambar', g.vram_used_pct || 0, (g.vram_used_pct || 0) > 80);
    }
    if (g.power_w != null) {
      txt('m-pwr', g.power_w.toFixed(1));
      var pn = el('m-pwr');
      if (pn && !pn.querySelector('u')) pn.insertAdjacentHTML('beforeend', '<u>W</u>');
      meter('m-pwrbar', (g.power_w / 300) * 100, g.power_w > 240);
    }
    if (g.temp_c != null) {
      txt('m-temp', g.temp_c);
      var tn = el('m-temp');
      if (tn && !tn.querySelector('u')) tn.insertAdjacentHTML('beforeend', '<u>&deg;C</u>');
    }
    txt('m-holder', g.holder || 'idle');
    txt('m-queue', g.queued != null ? String(g.queued) : '0');

    // The rack chassis carries its own gauge ids. They were rendered and then never
    // written, so the chassis sat at "—" with both bars empty, directly beneath copy
    // saying the rack is live. Same data, second home.
    if (g.vram_total_mib) {
      txt('g-vram', (g.vram_free_mib / 1024).toFixed(1) + ' GiB free of ' +
                    (g.vram_total_mib / 1024).toFixed(2));
      meter('g-vrambar', g.vram_used_pct || 0, (g.vram_used_pct || 0) > 80);
    }
    if (g.power_w != null) {
      txt('g-pwr', g.power_w.toFixed(1) + ' W of 300');
      meter('g-pwrbar', (g.power_w / 300) * 100, g.power_w > 240);
    }
    if (g.temp_c != null) txt('g-temp', g.temp_c + ' \u00b0C');

    // The rack note doubles as the "someone else is using it" explanation.
    // Restore the explanation when the queue drains. Without an else branch the amber
    // "N waiting" banner was written once and never removed, so the page kept claiming a
    // queue long after the card went idle.
    var note = el('rack-note');
    if (note) {
      if (g.queued > 0) {
        note.innerHTML = '<strong style="color:var(--amber)">' + g.queued +
          ' job(s) waiting.</strong> One card, one job at a time &mdash; RavenCalc runs on ' +
          'the CPU and is still free.';
      } else if (note.dataset.original) {
        note.innerHTML = note.dataset.original;
      }
    }
  }

  function render() {
    renderRack();
    renderConsole();
    // One reader more, not one data path more. A page that needs a field this file does not
    // render -- the miner card wants the `gpuminer` unit's own state and detail -- listens
    // for this instead of opening a second poller. That matters beyond tidiness: everything
    // in here stops while the tab is hidden, on purpose, because it hits a real GPU on
    // somebody's desk, and a page-local setInterval would quietly break that promise.
    try {
      document.dispatchEvent(new CustomEvent('sym:status', {detail: state}));
    } catch (e) { /* no CustomEvent constructor: the rack above still rendered */ }
  }

  // Keep the original wording so the queue banner can be undone rather than being a
  // one-way replacement.
  (function () {
    var note = el('rack-note');
    if (note && !note.dataset.original) note.dataset.original = note.innerHTML;
  })();

  function offline(reason) {
    var host = el('units');
    if (host) {
      host.innerHTML = '<div class="unit" data-state="offline" style="cursor:default">' +
        '<span class="leds"><i class="led"></i><i class="led"></i><i class="led"></i></span>' +
        '<span class="pwr">' + POWER + '</span>' +
        '<span class="uname"><b>Stack powered down</b><span>' + reason +
        ' &mdash; the rest of the site is unaffected</span></span>' +
        '<span class="ubus">--</span>' +
        '<span class="ustate"><span class="txt">offline</span><span class="slot">--</span></span>' +
        '</div>';
    }
    ['m-vram', 'm-pwr', 'm-temp', 'm-queue'].forEach(function (id) { txt(id, '--'); });
    txt('m-holder', 'offline');
    link('socket: offline');
  }

  function link(text) { txt('con-link', text); }

  // ---------------------------------------------------------------- patching

  function applyPatch(patch) {
    if (!state) return;
    if (patch.units) {
      // Addressed by id, never by position -- a positional patch silently corrupts the
      // display the day a unit is added or reordered. Iterate the PATCH, not our own list,
      // so a unit the server has newly added actually appears; the server already sends
      // whole objects for that case and we were discarding them.
      var byId = {};
      state.units.forEach(function (u) { byId[u.id] = u; });
      Object.keys(patch.units).forEach(function (id) {
        var change = patch.units[id];
        if (byId[id]) { for (var k in change) byId[id][k] = change[k]; }
        else if (change.label) { state.units.push(change); }
      });
    }
    if (patch.gpu) for (var k in patch.gpu) state.gpu[k] = patch.gpu[k];
  }

  // ---------------------------------------------------------------- transport

  function connect() {
    var proto = location.protocol === 'https:' ? 'wss:' : 'ws:';
    var url = proto + '//' + location.host + '/api/ws';
    try { socket = new WebSocket(url); }
    catch (e) { return startPolling(); }

    socket.onopen = function () {
      retry = 0; clearTimeout(reconnectTimer); reconnectTimer = null;
      link('socket: live'); stopPolling();
    };

    socket.onmessage = function (ev) {
      var msg;
      try { msg = JSON.parse(ev.data); } catch (e) { return; }
      if (msg.t === 'welcome') {
        link('socket: live · proto ' + msg.proto);
      } else if (msg.t === 'rack') {
        state = {units: msg.units, gpu: msg.gpu, link: msg.link};
        render();
      } else if (msg.t === 'patch') {
        applyPatch(msg);
        render();
      } else if (msg.t === 'bus') {
        // An agent announcing what it did. Surfaced so a waiting visitor can see why.
        if (msg.event === 'queued' && msg.behind) {
          link('socket: live · ' + msg.from + ' waiting behind ' + msg.behind);
        } else if (msg.event === 'released') {
          link('socket: live');
        }
      }
    };

    socket.onclose = function () {
      socket = null;
      // Back off rather than hammering a box that may simply be switched off.
      retry = Math.min(retry + 1, 6);
      link('socket: reconnecting…');
      // Hold the handle. Without it, the visibility handler's `if (!socket) connect()`
      // fired a second connect while this one was still armed, and every close armed
      // another -- a hide/show cycle against a flapping backend multiplied connections
      // instead of replacing them.
      clearTimeout(reconnectTimer);
      reconnectTimer = setTimeout(function () {
        reconnectTimer = null;
        if (!document.hidden && !socket) connect();
      }, 1000 * retry);
      if (!document.hidden) startPolling();
    };

    socket.onerror = function () { try { socket.close(); } catch (e) {} };
  }

  // Fallback only. Conditional so an unchanged rack costs a bare 304 with no body.
  function poll() {
    var headers = etag ? {'If-None-Match': etag} : {};
    fetch('/api/status', {headers: headers, cache: 'no-store'})
      .then(function (r) {
        if (r.status === 304) return null;
        if (!r.ok) throw new Error('down');
        etag = r.headers.get('ETag');
        return r.json();
      })
      .then(function (data) { if (data) { state = data; render(); } })
      .catch(function () { offline('the live surfaces are off right now'); });
  }

  function startPolling() {
    if (pollTimer) return;
    pollTimer = setInterval(function () { if (!document.hidden) poll(); }, 4000);
    // The immediate poll needs the same guard as the interval. Closing the socket on
    // hide called startPolling(), which fired one request at a machine we had just
    // promised not to touch while the tab was hidden.
    if (!document.hidden) poll();
  }
  function stopPolling() { clearInterval(pollTimer); pollTimer = null; }

  // Nothing runs while the tab is hidden. This hits a real GPU on someone's desk.
  document.addEventListener('visibilitychange', function () {
    if (document.hidden) {
      stopPolling();
      clearTimeout(reconnectTimer); reconnectTimer = null;
      if (socket) { try { socket.close(); } catch (e) {} }
    } else if (!socket) {
      connect();
    }
  });

  // ---- the rack's fold control -------------------------------------------
  // In the one-screen layout the rack cannot fit with every unit's attribution on screen
  // (units 611px + chassis 71px against 584-589px of panel), so that line is collapsed by
  // default there and this puts it back. It is a fold, not a truncation: the text is intact
  // in the DOM and one click away, and the control is hidden entirely below the gate, where
  // the page scrolls and there is nothing to save.
  //
  // This attaches even though renderRack() rewrites #units on every update -- the class
  // lives on #rack, the container, which is never rewritten. Toggling a descendant's class
  // here would be undone by the next status push.
  var FOLD_KEY = 'symoneural.rack.detail';
  var foldBtn = el('rk-fold'), rackSec = document.getElementById('rack');
  if (foldBtn && rackSec) {
    var setFold = function (open) {
      rackSec.classList.toggle('rk-open', open);
      foldBtn.setAttribute('aria-pressed', open ? 'true' : 'false');
      foldBtn.textContent = open ? 'Hide what each unit is running'
                                 : 'Show what each unit is running';
      try { localStorage.setItem(FOLD_KEY, open ? '1' : '0'); } catch (e) {}
    };
    var remembered = '0';
    try { remembered = localStorage.getItem(FOLD_KEY) || '0'; } catch (e) {}
    setFold(remembered === '1');
    foldBtn.addEventListener('click', function () {
      setFold(!rackSec.classList.contains('rk-open'));
    });
  }

  // The control board's fold, same contract as the rack's. Its own key and its own class
  // so the two remember independently -- someone reading the rack in detail is not
  // necessarily reading nineteen module explanations too.
  var cnBtn = el('cn-fold'), cnSec = document.getElementById('console');
  if (cnBtn && cnSec) {
    var setCn = function (open) {
      cnSec.classList.toggle('cn-open', open);
      cnBtn.setAttribute('aria-pressed', open ? 'true' : 'false');
      cnBtn.textContent = open ? 'Hide what each reading means'
                               : 'Show what each reading means';
      try { localStorage.setItem('symoneural.console.detail', open ? '1' : '0'); } catch (e) {}
    };
    var cnSaved = '0';
    try { cnSaved = localStorage.getItem('symoneural.console.detail') || '0'; } catch (e) {}
    setCn(cnSaved === '1');
    cnBtn.addEventListener('click', function () {
      setCn(!cnSec.classList.contains('cn-open'));
    });
  }

  // ---- the operator's per-unit power panel --------------------------------
  //
  // `scripts/symoneural.sh off` is the kill switch for the whole API. This is the per-unit
  // one: take Image down while its weights are swapped and leave everything else serving.
  //
  // THREE THINGS ABOUT THIS BLOCK ARE DELIBERATE AND SHOULD NOT BE "TIDIED":
  //
  // 1. It appends to #rack and never touches a rack row. renderRack() rewrites #units on
  //    every push, so a control placed inside a row would be destroyed four seconds later.
  //    A row is also a single <a href>, and a <button> nested in an anchor is invalid HTML
  //    that both toggles the unit and navigates away on one click.
  //
  // 2. It renders nothing at all unless the operator asks for it -- `#operator` in the URL,
  //    or a token already held from earlier in this browser session. The rack is served to
  //    the public internet; an "Operator" affordance visible to every visitor advertises a
  //    control worth attacking, and the API answers 404 rather than 403 for the same reason.
  //
  // 3. Its styles are injected here, scoped under #op-panel, rather than added to
  //    symoneural.css. Three separate bugs in this repo have come from generic class names
  //    colliding across components (.bar, .live, #console .sub), and an operator control has
  //    no business being able to cause a fourth. There is no ellipsis rule: the panel wraps.
  //
  // The token lives in sessionStorage, not localStorage: it is a shared secret, and closing
  // the tab should not leave it on disk for the next person at this desk.
  var OP_KEY = 'symoneural.rack.token';
  function opToken() { try { return sessionStorage.getItem(OP_KEY) || ''; } catch (e) { return ''; } }
  function setOpToken(v) {
    try { v ? sessionStorage.setItem(OP_KEY, v) : sessionStorage.removeItem(OP_KEY); } catch (e) {}
  }

  function opPanel() {
    var rack = document.getElementById('rack');
    if (!rack) return;
    if (location.hash !== '#operator' && !opToken()) return;

    var style = document.createElement('style');
    style.textContent =
      '#op-panel{margin-top:14px;border:1px solid #1d2b22;border-radius:6px;' +
        'background:#080d0a;font-size:13px}' +
      '#op-panel>summary{padding:8px 12px;cursor:pointer;color:#7fdca4;' +
        'font-family:ui-monospace,monospace;letter-spacing:.04em}' +
      '#op-panel .op-body{padding:0 12px 12px}' +
      '#op-panel .op-row{display:flex;flex-wrap:wrap;gap:8px;align-items:baseline;' +
        'padding:6px 0;border-top:1px solid #16211b}' +
      '#op-panel .op-id{font-family:ui-monospace,monospace;min-width:9ch;color:#cfe9d8}' +
      '#op-panel .op-why{color:#8aa294;flex:1 1 18ch}' +
      '#op-panel button{font:inherit;padding:3px 10px;border-radius:4px;cursor:pointer;' +
        'border:1px solid #2b4636;background:#0f1a13;color:#9fe0b8}' +
      '#op-panel button[disabled]{opacity:.5;cursor:progress}' +
      '#op-panel input{font:inherit;padding:4px 8px;border-radius:4px;' +
        'border:1px solid #2b4636;background:#0b120d;color:#cfe9d8;flex:1 1 22ch}' +
      '#op-panel .op-msg{padding-top:8px;color:#e0b48a}';

    var panel = document.createElement('details');
    panel.id = 'op-panel';
    panel.open = true;
    panel.innerHTML = '<summary>Operator &mdash; unit power</summary>' +
                      '<div class="op-body"><div class="op-msg">Checking&hellip;</div></div>';
    rack.appendChild(style);
    rack.appendChild(panel);

    var body = panel.querySelector('.op-body');

    function msg(text) { body.innerHTML = '<div class="op-msg"></div>'; body.firstChild.textContent = text; }

    function askForToken(why) {
      body.innerHTML =
        '<div class="op-row"><input type="password" id="op-tok" placeholder="SYMONEURAL_RACK_TOKEN" ' +
        'autocomplete="off"><button type="button" id="op-go">unlock</button></div>' +
        '<div class="op-msg"></div>';
      if (why) body.querySelector('.op-msg').textContent = why;
      var go = function () {
        var v = body.querySelector('#op-tok').value.trim();
        if (!v) return;
        setOpToken(v);
        load();
      };
      body.querySelector('#op-go').addEventListener('click', go);
      body.querySelector('#op-tok').addEventListener('keydown', function (e) {
        if (e.key === 'Enter') go();
      });
    }

    // The panel reports what the API says and nothing else. It never guesses a unit's
    // state from the rack it sits under, because that reading and this one would drift and
    // an operator would be looking at two answers to one question.
    // Both header spellings on every send. The site and the API deploy by two separate
    // commands (`deploy.sh`, then `systemctl restart`), so this file can be the new one
    // talking to a server that has not been restarted; the server reads both as well, which
    // covers a cached copy of this file against a new API. One secret, one origin, named
    // twice -- the legacy key comes out once the deployed API is known to read the new name.
    function opHeaders(extra) {
      // No credential header. Nothing reads one; see
      // tests/structure/test_credential_header.py.
      return extra || {};
    }
    function load() {
      fetch('/api/rack/power', {headers: opHeaders()})
        .then(function (r) {
          if (r.status === 404) {
            // Absent, not forbidden. With SYMONEURAL_RACK_ENABLED unset there is nothing here to
            // unlock, so say that rather than asking for a token that cannot work.
            setOpToken('');
            throw new Error('The power surface is off on this installation. ' +
                            'Set SYMONEURAL_RACK_ENABLED=1 and SYMONEURAL_RACK_TOKEN to use it.');
          }
          if (r.status === 403) { setOpToken(''); throw new Error('__token__'); }
          if (!r.ok) throw new Error('The API answered ' + r.status + '.');
          return r.json();
        })
        .then(render)
        .catch(function (e) {
          if (e.message === '__token__') return askForToken('Refused. Wrong token, or this ' +
                                                           'browser is not on the machine.');
          msg(e.message);
        });
    }

    function render(doc) {
      body.innerHTML = '';
      doc.units.forEach(function (u) {
        var row = document.createElement('div');
        row.className = 'op-row';

        var id = document.createElement('span');
        id.className = 'op-id';
        id.textContent = u.id;

        var why = document.createElement('span');
        why.className = 'op-why';
        // Real readings only, and the whole reading: when it went down and where from.
        // "offline" on its own would leave an operator unable to tell their own
        // intervention from a fault, which is the entire point of recording who and when.
        why.textContent = u.disabled
          ? ('off since ' + new Date(u.at * 1000).toLocaleTimeString() + ' from ' + u.by)
          : 'serving';

        var btn = document.createElement('button');
        btn.type = 'button';
        btn.textContent = u.disabled ? 'put back' : 'take offline';
        btn.addEventListener('click', function () {
          btn.disabled = true;
          fetch('/api/rack/power/' + encodeURIComponent(u.id), {
            method: 'POST',
            headers: opHeaders({'Content-Type': 'application/json'}),
            body: JSON.stringify({offline: !u.disabled})
          }).then(function (r) {
            if (!r.ok) throw new Error('The API answered ' + r.status + '.');
            // Reload the panel from the API rather than flipping the label locally: the
            // POST is the request, the GET is the fact, and only one of them is allowed to
            // decide what this panel shows.
            load();
            // Pull a fresh rack immediately so the row above updates now instead of at the
            // next four-second tick. On the socket this is a frame; polling handles itself.
            if (socket && socket.readyState === 1) socket.send('{"t":"rack"}'); else poll();
          }).catch(function (e) { btn.disabled = false; msg(e.message); });
        });

        row.appendChild(id); row.appendChild(why); row.appendChild(btn);
        body.appendChild(row);
      });
    }

    if (opToken()) load(); else askForToken('');
  }

  if (el('units') || el('m-vram')) connect();
  opPanel();
})();
