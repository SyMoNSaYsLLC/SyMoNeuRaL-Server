/* SyMoNeuRaL Exp -- the operator surface for the plugin runtime.
 *
 * Deploys to `site/exp.js`; `page.html` loads it with <script src="/exp.js" defer>.
 *
 * Vanilla, 'use strict', one IIFE, no build step -- the house idiom, and the same shape as
 * site/studio.js and site/reinforce.js. There is no bundler in this repo and adding one would
 * break the generator -> build_cachebust.py discipline every page depends on.
 *
 * ## Three rules this file is written around
 *
 * 1. **No reading, no pixel.** Where the API has not answered, the cell says so in words. No
 *    spinner stands in for state and no dot is lit by anything other than a value that came
 *    back over the wire. A pulsing `loading` indicator would keep pulsing after the process
 *    died, which is the failure mode hardest to notice and the easiest to fake.
 * 2. **Off and refused are different conditions.** `/api/exp/*` writes answer 503 when the
 *    surface is switched off and 401 when a token was wrong, and the gate draws those two
 *    differently: 503 names the two environment variables, 401 shows the token box. Telling an
 *    operator "wrong token" when the switch is off sends them to the wrong fix.
 * 3. **The runtime's own vocabulary, unchanged.** Six fiber states and four entry
 *    pseudo-states, spelled the way `fiber.py` and `loader.py` spell them. Renaming
 *    `disposing` to something friendlier on the way to the browser would mean the page and the
 *    trace disagree about what happened.
 */
'use strict';
(function () {
  var API = '/api/exp';
  var TOKEN_KEY = 'sym.exp.token';

  /* Two cadences. Events are cheap -- a cursor read off a deque -- and they are what makes a
   * reload legible, so they poll often. State walks every entry and every service, so it polls
   * rarely, and every successful write refreshes it immediately anyway. */
  var EVENT_MS = 2500;
  var STATE_MS = 15000;
  var FEED_MAX = 240;

  var seq = 0;           // last trace sequence rendered
  var last = null;       // last /state payload
  var services = [];     // last /services payload

  function $(id) { return document.getElementById(id); }
  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined && text !== null) n.textContent = String(text);
    return n;
  }
  function token() { try { return sessionStorage.getItem(TOKEN_KEY) || ''; } catch (e) { return ''; } }
  function setToken(v) { try { sessionStorage.setItem(TOKEN_KEY, v); } catch (e) {} }

  /* sessionStorage, not localStorage: the operator token dies with the tab. It unlocks a
   * surface that mounts arbitrary code into the API process and calls arbitrary methods on it,
   * and surviving a browser restart is not a feature anybody asked for. */
  function headers(extra) {
  // No credential header. Nothing on this box reads one -- the gates were removed on
  // 2026-09-11 and will not come back. A client that keeps sending one looks exactly
  // like a client that is authenticated, which is the failure hardest to notice.
    return extra || {};
  }

  function getJSON(path, opts) {
    return fetch(API + path, Object.assign({ headers: headers({}) }, opts || {}))
      .then(function (r) {
        return r.json().catch(function () { return {}; }).then(function (body) {
          return { status: r.status, ok: r.ok, body: body };
        });
      })
      .catch(function (e) { return { status: 0, ok: false, body: { detail: String(e) } }; });
  }

  function postJSON(path, payload) {
    return getJSON(path, {
      method: 'POST',
      headers: headers({ 'Content-Type': 'application/json' }),
      body: JSON.stringify(payload || {})
    });
  }

  /* ---- what the runtime said last ---------------------------------------- */
  function said(text, ok) {
    var p = $('ex-said');
    p.textContent = text || '';
    p.style.color = ok ? 'var(--dim)' : 'var(--amber)';
  }

  /* Every write funnels through here, so the 503/401 distinction is made in exactly one place
   * and the error message the runtime wrote is shown verbatim. Those messages are written to be
   * read by a person -- "no entry 'clok'; have: bus, memory, gpu, clock" -- and replacing one
   * with "Request failed" would throw away the only useful part. */
  function write(path, payload, describe) {
    said(describe + ' …', true);
    return postJSON(path, payload).then(function (r) {
      if (r.status === 503 || r.status === 401) {
        showGate(r.body, r.status === 401 ? 'bad' : 'off');
        said(r.body.detail || (r.status + ''), false);
        return null;
      }
      if (!r.ok) {
        said(r.body.detail || ('HTTP ' + r.status), false);
        return null;
      }
      said(describe + ' — done', true);
      return r.body;
    }).then(function (body) {
      return refresh().then(function () { return body; });
    });
  }

  /* ---- status strip ------------------------------------------------------ */
  function cell(title, value, cls, sub) {
    var c = el('div', 'ex-cell');
    c.appendChild(el('h3', null, title));
    c.appendChild(el('p', cls || null, value));
    if (sub) c.appendChild(el('p', 'sub', sub));
    return c;
  }

  function countsLine(states) {
    var keys = Object.keys(states || {}).sort();
    if (!keys.length) return 'no fibers';
    return keys.map(function (k) { return states[k] + ' ' + k; }).join(' · ');
  }

  function renderStrip(s) {
    var strip = $('ex-strip');
    strip.textContent = '';

    strip.appendChild(cell('Mutations',
      s.enabled ? (s.writable ? 'open' : 'locked') : 'off',
      s.enabled ? (s.writable ? 'ex-on' : 'ex-warn') : 'ex-off',
      s.enabled ? (s.writable ? 'token accepted for this tab' : 'switched on, token needed')
                : 'reads answer; writes are switched off'));

    strip.appendChild(cell('Source', s.source || 'nothing mounted',
      s.source ? null : 'ex-off',
      'default preset ' + (s.default_preset || '(none)')));

    strip.appendChild(cell('Entries', (s.entries || []).length,
      (s.entries || []).length ? null : 'ex-off',
      countsLine(s.states)));

    var reloads = (s.fibers || []).reduce(function (n, f) { return n + (f.reloads || 0); }, 0);
    strip.appendChild(cell('Fibers', (s.fibers || []).length,
      (s.fibers || []).length ? null : 'ex-off',
      reloads + ' reload' + (reloads === 1 ? '' : 's') + ' since boot'));

    strip.appendChild(cell('Services', (s.services || []).length,
      (s.services || []).length ? null : 'ex-off',
      (s.services || []).join(', ') || 'nothing provided'));

    /* The trace cell is the one that can report its own failure. `dropped_writes` counts
     * appends the runtime could not make -- a full disk is a real state this box has been in --
     * and a trace that silently stopped writing while the page kept drawing events from memory
     * is exactly the quiet lie this rule exists to prevent. */
    strip.appendChild(cell('Trace', s.events + ' buffered',
      s.dropped_writes ? 'ex-warn' : null,
      s.dropped_writes ? (s.dropped_writes + ' file writes dropped')
                       : (s.trace_path || 'memory only, no file sink')));
  }

  /* ---- the gate ---------------------------------------------------------- */
  function hideGate() { var g = $('ex-gate'); g.hidden = true; g.textContent = ''; }

  function showGate(state, reason) {
    var g = $('ex-gate');
    g.textContent = '';
    g.hidden = false;

    if (reason === 'off' || (state && state.enabled === false)) {
      g.appendChild(el('h2', null, 'Writes are switched off'));
      g.appendChild(el('p', null,
        'Reads are open and the tables below are live. Mounting, patching, reloading and '
        + 'calling into a service change what runs inside the API process, so they need both '
        + 'switches set and the API restarted:'));
      var line = el('p', null, '');
      line.appendChild(el('code', null, 'SYMONEURAL_EXP_ENABLED=1'));
      line.appendChild(document.createTextNode(' '));
      line.appendChild(el('code', null, 'SYMONEURAL_EXP_TOKEN=<secret>'));
      g.appendChild(line);
      return;
    }

    g.appendChild(el('h2', null, reason === 'bad' ? 'That token was not accepted'
                                                  : 'Operator token'));
    g.appendChild(el('p', null,
      'The surface is switched on. Mounting a plugin, patching a config, reloading a module and '
      + 'calling a method all need the token; it is held for this tab only and is never written '
      + 'to disk.'));

    var form = el('form');
    var input = document.createElement('input');
    input.type = 'password';
    input.id = 'ex-token';
    input.placeholder = 'SYMONEURAL_EXP_TOKEN';
    input.autocomplete = 'off';
    input.value = '';
    var go = el('button', null, 'Use it');
    go.type = 'submit';
    form.appendChild(input);
    form.appendChild(go);
    form.addEventListener('submit', function (ev) {
      ev.preventDefault();
      setToken(input.value.trim());
      refresh();
    });
    g.appendChild(form);
  }

  /* ---- entries ----------------------------------------------------------- */
  function fiberOf(s, entry) {
    if (!entry.fiber) return null;
    var list = s.fibers || [];
    for (var i = 0; i < list.length; i++) if (list[i].id === entry.fiber) return list[i];
    return null;
  }

  function stateSpan(state) {
    return el('span', 'ex-st ex-st-' + state, state);
  }

  function actionButton(label, ghost, fn) {
    var b = el('button', 'tiny' + (ghost ? ' ghost' : ''), label);
    b.type = 'button';
    b.addEventListener('click', fn);
    return b;
  }

  function renderEntries(s) {
    var body = $('ex-entries');
    body.textContent = '';
    $('ex-acts-h').textContent = s.writable ? 'Do' : '';

    var entries = s.entries || [];
    /* Three conditions make `writable` false and they want three different fixes. It is one
     * boolean over all of them -- `routes.py:66-67` is `enabled() and token_ok(...)` -- so it
     * cannot be the whole message. The switch being off means no token helps, so asking for one
     * sends the reader after a secret that would not work; a token this tab is holding and the
     * API refused wants replacing, not presenting; and no token at all wants presenting. Saying
     * "no valid token was presented" covers the last two at once and is wrong for whichever one
     * the reader is in. The page can tell them apart without asking the API anything further:
     * `s.enabled` is the switch (`routes.py:118`) and `token()` is what this tab is sending.
     * Rule 2 at the top of this file, applied to a table cell. */
    var withheld = '';
    if (!s.writable) {
      if (!s.enabled) {
        withheld = 'Config values are withheld: the surface is switched off, so no token '
                 + 'unlocks them. Set SYMONEURAL_EXP_ENABLED=1 and '
                 + 'SYMONEURAL_EXP_TOKEN on the API process.';
      } else if (token()) {
        withheld = 'Config values are withheld: the API refused the token this tab is holding.';
      } else {
        withheld = 'Config values are withheld: this tab has presented no token.';
      }
      withheld += ' Every other column is the whole truth.';
    }
    $('ex-entries-note').textContent = entries.length ? withheld
      : 'Nothing is mounted. The container is up and empty, which is a state and not an error.';

    entries.forEach(function (e) {
      var tr = el('tr');

      var td = el('td');
      var name = el('b', null, e.id);
      td.appendChild(name);
      if (e.group) td.appendChild(document.createTextNode(' (group)'));
      td.appendChild(document.createElement('br'));
      td.appendChild(el('code', 'ex-mono', e.use || '—'));
      if (e.isolate && e.isolate.length) {
        td.appendChild(document.createElement('br'));
        td.appendChild(el('code', 'ex-mono', 'isolate: ' + e.isolate.join(', ')));
      }
      if (e.config) {
        td.appendChild(document.createElement('br'));
        td.appendChild(el('code', 'ex-mono', JSON.stringify(e.config)));
      }
      tr.appendChild(td);

      var f = fiberOf(s, e);
      var sd = el('td');
      sd.appendChild(stateSpan(e.state));
      if (f && f.reloads) {
        sd.appendChild(document.createElement('br'));
        sd.appendChild(document.createTextNode(f.reloads + ' reload'
          + (f.reloads === 1 ? '' : 's')));
      }
      if (e.error) sd.appendChild(el('p', 'ex-err', e.error));
      tr.appendChild(sd);

      /* "Wants" is the useful column on a page about hot-plugging, because a PENDING fiber is
       * not broken -- it is waiting, and the difference is entirely in which of these names is
       * still missing. */
      var wd = el('td');
      if (f) {
        if (f.inject.length) wd.appendChild(el('code', 'ex-mono', f.inject.join(', ')));
        else wd.appendChild(document.createTextNode('nothing'));
        if (f.optional.length) {
          wd.appendChild(document.createElement('br'));
          wd.appendChild(el('code', 'ex-mono', 'optional: ' + f.optional.join(', ')));
        }
        if (f.missing.length) {
          wd.appendChild(document.createElement('br'));
          wd.appendChild(el('code', 'ex-mono', 'missing: ' + f.missing.join(', ')));
          wd.lastChild.style.color = 'var(--amber)';
        }
      } else {
        wd.appendChild(document.createTextNode(e.group ? 'a group asks for nothing'
                                                       : 'no fiber'));
      }
      tr.appendChild(wd);

      var pd = el('td');
      if (f && f.provides.length) pd.appendChild(el('code', 'ex-mono', f.provides.join(', ')));
      else if (e.children && e.children.length) {
        pd.appendChild(document.createTextNode(e.children.length + ' child'
          + (e.children.length === 1 ? '' : 'ren')));
      } else pd.appendChild(document.createTextNode('—'));
      if (f && f.effects) {
        pd.appendChild(document.createElement('br'));
        pd.appendChild(document.createTextNode(f.effects + ' effect'
          + (f.effects === 1 ? '' : 's') + ' to undo'));
      }
      tr.appendChild(pd);

      if (s.writable) {
        var ad = el('td', 'acts');
        ad.appendChild(actionButton(e.disabled ? 'enable' : 'disable', true, function () {
          write('/enable', { id: e.id, on: !!e.disabled },
            (e.disabled ? 'enabling ' : 'disabling ') + e.id);
        }));
        if (!e.group) {
          ad.appendChild(actionButton('reload', true, function () {
            write('/reload', { id: e.id }, 'reloading ' + e.id).then(function (body) {
              /* A module that no longer parses leaves the fiber running the code it has and
               * reports why. That is a success for the process and a failure for the edit, and
               * both are true -- so the error is surfaced even though the call returned 200. */
              if (body && body.entry && body.entry.error) said(body.entry.error, false);
            });
          }));
          ad.appendChild(actionButton('config', true, function () {
            $('ex-add-wrap').open = true;
            $('ex-add-id').value = e.id;
            $('ex-add-config').value = JSON.stringify(e.config || {}, null, 2);
            $('ex-add-out').textContent = 'Loaded ' + e.id
              + '’s config. Patch replaces it and restarts that fiber.';
          }));
        }
        ad.appendChild(actionButton('remove', true, function () {
          write('/remove', { id: e.id }, 'removing ' + e.id);
        }));
        tr.appendChild(ad);
      }

      body.appendChild(tr);
    });
  }

  /* ---- the preset row ---------------------------------------------------- */
  function renderMountRow(s) {
    var row = $('ex-mount-row');
    row.textContent = '';

    if (!s.writable) {
      row.appendChild(el('label', null, 'Presets on disk: '
        + ((s.presets || []).join(', ') || 'none')
        + '. Mounting one needs the token.'));
      return;
    }

    var sel = document.createElement('select');
    sel.id = 'ex-preset';
    (s.presets || []).forEach(function (name) {
      var o = document.createElement('option');
      o.value = name;
      o.textContent = name;
      if (name === s.source) o.selected = true;
      sel.appendChild(o);
    });
    row.appendChild(el('label', null, 'Preset'));
    row.appendChild(sel);

    /* A diff, not a rebuild: switching from `dev` to `failures` leaves the `bus` both presets
     * name running -- same fiber, same object -- and replaces everything else. Saying so on the
     * button is worth the words, because "mount" otherwise reads as "restart everything". The
     * two manifests give that entry identical config deliberately; a changed config keeps the
     * fiber id but does unwind and re-mount it, so the feed is where to check what happened. */
    var go = el('button', null, 'Mount (diffed)');
    go.type = 'button';
    go.addEventListener('click', function () {
      write('/preset', { name: sel.value }, 'mounting preset ' + sel.value);
    });
    row.appendChild(go);
  }

  /* ---- services --------------------------------------------------------- */
  function renderServices(list) {
    services = list || [];
    var body = $('ex-services');
    body.textContent = '';
    $('ex-services-note').textContent = services.length ? ''
      : 'The container is empty. Nothing has called provide() yet.';

    services.forEach(function (s) {
      var tr = el('tr');
      var td = el('td');
      td.appendChild(el('b', null, s.name));
      td.appendChild(document.createElement('br'));
      td.appendChild(el('code', 'ex-mono', s.realm ? ('realm ' + s.realm) : 'root realm'));
      td.appendChild(document.createElement('br'));
      td.appendChild(el('code', 'ex-mono', 'epoch ' + s.epoch));
      tr.appendChild(td);
      tr.appendChild(el('td', null, s.owner || '—'));
      tr.appendChild(el('td', null, s.type));
      var md = el('td');
      md.appendChild(el('code', 'ex-mono', (s.methods || []).join(', ') || 'none public'));
      tr.appendChild(md);
      body.appendChild(tr);
    });

    var sel = $('ex-call-service');
    var keep = sel.value;
    sel.textContent = '';
    services.forEach(function (s) {
      var o = document.createElement('option');
      o.value = s.key;
      o.textContent = s.realm ? (s.name + '  (' + s.realm + ')') : s.name;
      sel.appendChild(o);
    });
    if (keep) sel.value = keep;
    renderMethods();
  }

  function renderMethods() {
    var sel = $('ex-call-method');
    var key = $('ex-call-service').value;
    var chosen = null;
    for (var i = 0; i < services.length; i++) if (services[i].key === key) chosen = services[i];
    sel.textContent = '';
    (chosen ? chosen.methods : []).forEach(function (m) {
      var o = document.createElement('option');
      o.value = m;
      o.textContent = m;
      sel.appendChild(o);
    });
  }

  /* ---- the trace feed --------------------------------------------------- */
  function evClass(name) {
    if (/error|fail/.test(name)) return 'ex-ev ex-e-error';
    if (/provide|active|start|create/.test(name)) return 'ex-ev ex-e-provide';
    if (/revoke|unwind|unmount|dispose|skip/.test(name)) return 'ex-ev ex-e-dispose';
    return 'ex-ev';
  }

  function evLine(e) {
    var out = [];
    Object.keys(e).forEach(function (k) {
      if (k === 'seq' || k === 't' || k === 'event') return;
      var v = e[k];
      out.push(k + '=' + (typeof v === 'object' ? JSON.stringify(v) : String(v)));
    });
    return out.join('  ') || '(no fields)';
  }

  /* What became of the events the ring dropped. `last` is the most recent /state payload, so
   * before the first one answers this says it does not know rather than guessing. */
  function evicted() {
    if (!last) return 'whether anything kept the older ones is unknown until /state answers';
    if (!last.trace_path) return 'there is no file sink, so the older ones are gone';
    if (last.dropped_writes) return last.dropped_writes + ' writes to ' + last.trace_path
      + ' failed, so the file is missing some of them too';
    return 'the file sink at ' + last.trace_path + ' has the rest';
  }

  function renderEvents(payload) {
    var feed = $('ex-feed');
    var atBottom = feed.scrollTop + feed.clientHeight >= feed.scrollHeight - 24;
    (payload.events || []).forEach(function (e) {
      if (e.seq <= seq) return;
      seq = e.seq;
      var node = el('div', evClass(e.event));
      var h = el('h4', null, e.event);
      h.appendChild(document.createTextNode(' '));
      h.appendChild(el('span', 'ex-seq', '#' + e.seq));
      node.appendChild(h);
      node.appendChild(el('p', null, evLine(e)));
      feed.appendChild(node);
    });
    while (feed.childNodes.length > FEED_MAX) feed.removeChild(feed.firstChild);
    if (atBottom) feed.scrollTop = feed.scrollHeight;

    /* The ring is capped. When the buffer is full the page is no longer showing everything that
     * ever happened, and it says so rather than implying the runtime went quiet. Whether the
     * evicted events are recoverable is a separate reading, and it comes from `/state`: no
     * `trace_path` means there is no file sink and they are gone, and any `dropped_writes`
     * means the file that does exist has holes in it. Promising a durable copy that is not
     * there would be the reassuring-but-unmeasured claim this file's first rule forbids. */
    $('ex-feed-note').textContent = payload.seq
      ? (payload.buffered + ' events in the ring, ' + payload.seq + ' recorded since boot'
         + (payload.buffered < payload.seq ? ' — the ring has wrapped; ' + evicted() : ''))
      : 'Nothing has happened yet.';
  }

  /* ---- catalogue -------------------------------------------------------- */
  function renderCatalogue(payload) {
    var body = $('ex-catalogue');
    body.textContent = '';
    (payload.plugins || []).forEach(function (p) {
      var tr = el('tr');
      var td = el('td');
      td.appendChild(el('b', null, p.name));
      td.appendChild(document.createElement('br'));
      td.appendChild(el('code', 'ex-mono', p.use));
      tr.appendChild(td);
      tr.appendChild(el('td', null, p.error ? 'unresolvable' : p.kind));
      var wd = el('td');
      wd.appendChild(el('code', 'ex-mono',
        (p.inject || []).join(', ') || 'nothing'));
      if (p.optional && p.optional.length) {
        wd.appendChild(document.createElement('br'));
        wd.appendChild(el('code', 'ex-mono', 'optional: ' + p.optional.join(', ')));
      }
      tr.appendChild(wd);
      var dd = el('td', null, p.error || (p.doc || '').replace(/\s+/g, ' ').trim());
      if (p.schema && Object.keys(p.schema).length) {
        dd.appendChild(document.createElement('br'));
        dd.appendChild(el('code', 'ex-mono', 'config: ' + JSON.stringify(p.schema)));
      }
      tr.appendChild(dd);
      body.appendChild(tr);
    });

    var sel = $('ex-add-use');
    var keep = sel.value;
    sel.textContent = '';
    (payload.plugins || []).forEach(function (p) {
      if (p.error) return;
      var o = document.createElement('option');
      o.value = p.use;
      o.textContent = p.name;
      sel.appendChild(o);
    });
    if (keep) sel.value = keep;
  }

  /* ---- forms ------------------------------------------------------------ */
  function parseJSON(text, fallback, where) {
    var raw = (text || '').trim();
    if (!raw) return fallback;
    try { return JSON.parse(raw); } catch (e) {
      said(where + ' is not valid JSON: ' + e.message, false);
      return undefined;
    }
  }

  function wireForms() {
    $('ex-call-service').addEventListener('change', renderMethods);

    $('ex-call').addEventListener('submit', function (ev) {
      ev.preventDefault();
      var args = parseJSON($('ex-call-args').value, [], 'the argument list');
      if (args === undefined) return;
      if (!Array.isArray(args)) { said('the argument list must be a JSON array', false); return; }
      var svc = $('ex-call-service').value;
      var method = $('ex-call-method').value;
      $('ex-call-out').textContent = 'calling …';
      postJSON('/call', { service: svc, method: method, args: args }).then(function (r) {
        if (r.status === 503 || r.status === 401) {
          showGate(r.body, r.status === 401 ? 'bad' : 'off');
          $('ex-call-out').textContent = r.body.detail || ('HTTP ' + r.status);
          return;
        }
        /* The plugin's own exception, verbatim, including the type name. `/call` exists to find
         * out what a service does; "500 Internal Server Error" would make it useless for that. */
        $('ex-call-out').textContent = r.ok
          ? (svc + '.' + method + ' → ' + JSON.stringify(r.body.result)
             + '   (epoch ' + r.body.epoch + ')')
          : (r.body.detail || ('HTTP ' + r.status));
        refresh();
      });
    });

    $('ex-add').addEventListener('submit', function (ev) {
      ev.preventDefault();
      var config = parseJSON($('ex-add-config').value, {}, 'the config');
      if (config === undefined) return;
      var id = $('ex-add-id').value.trim();
      write('/add', { id: id, use: $('ex-add-use').value, config: config },
        'mounting ' + (id || '(unnamed)')).then(function (body) {
          if (body) $('ex-add-out').textContent = 'mounted as ' + body.entry.id
            + ', state ' + body.entry.state;
        });
    });

    $('ex-patch-go').addEventListener('click', function () {
      var config = parseJSON($('ex-add-config').value, {}, 'the config');
      if (config === undefined) return;
      var id = $('ex-add-id').value.trim();
      if (!id) { said('patch needs the id of an entry that is already mounted', false); return; }
      write('/patch', { id: id, config: config }, 'patching ' + id).then(function (body) {
        if (body) $('ex-add-out').textContent = id + ' restarted, state ' + body.entry.state;
      });
    });
  }

  /* ---- polling ---------------------------------------------------------- */
  function refresh() {
    return getJSON('/state').then(function (r) {
      if (!r.ok) {
        /* /state is an open read. If it fails, the app is not off -- something is wrong -- and
         * the strip says that instead of drawing zeros, which would look like a healthy empty
         * runtime. */
        $('ex-strip').textContent = '';
        $('ex-strip').appendChild(cell('Runtime', 'no answer', 'ex-warn',
          (r.body && r.body.detail) || ('HTTP ' + r.status)));
        return;
      }
      last = r.body;
      renderStrip(last);
      renderMountRow(last);
      renderEntries(last);
      if (!last.enabled) showGate(last, 'off');
      else if (!last.writable) showGate(last, 'need');
      else hideGate();
      return getJSON('/services').then(function (sr) {
        if (sr.ok) renderServices(sr.body.services);
      });
    });
  }

  function pollEvents() {
    getJSON('/events?since=' + seq).then(function (r) {
      if (r.ok) renderEvents(r.body);
    });
  }

  function boot() {
    wireForms();
    refresh();
    getJSON('/catalogue').then(function (r) { if (r.ok) renderCatalogue(r.body); });
    pollEvents();
    setInterval(pollEvents, EVENT_MS);
    setInterval(refresh, STATE_MS);
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', boot);
  else boot();
}());
