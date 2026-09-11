/* SyMoNeuRaL Studio -- the chrome around the agent and the bench.
 *
 * Deploys to `site/studio.js`; `page.html` loads it with <script src="/studio.js" defer>.
 *
 * Vanilla, 'use strict', one IIFE, no build step -- the house idiom, and the same shape as
 * site/reinforce.js. There is no bundler in this repo and adding one would break the
 * generator -> build_cachebust.py discipline every page depends on.
 *
 * ## Two rules this file is written around
 *
 * 1. **No reading, no pixel.** Where the API has not answered, the cell says so in words. There
 *    are no spinners standing in for state and no indicator that is lit by anything other than
 *    a value that came back over the wire. The site's whole argument is that its readouts are
 *    real; a placeholder LED here would be the one dishonest pixel on it.
 * 2. **The node editor is not ours.** It is ComfyUI's own frontend in an iframe, served
 *    same-origin at /studio/editor/. This file does not reimplement a canvas, does not proxy its
 *    events and does not decorate it. It gives it the token and gets out of the way.
 */
'use strict';
(function () {
  var API = '/api/studio';
  var TOKEN_KEY = 'sym.studio.token';

  function $(id) { return document.getElementById(id); }
  function el(tag, cls, text) {
    var n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined && text !== null) n.textContent = String(text);
    return n;
  }
  function token() { try { return sessionStorage.getItem(TOKEN_KEY) || ''; } catch (e) { return ''; } }
  function setToken(v) { try { sessionStorage.setItem(TOKEN_KEY, v); } catch (e) {} }

  /* sessionStorage, not localStorage: the operator token dies with the tab. It is the key to a
   * surface that can run commands on the host, and surviving a browser restart is not a feature
   * anybody asked for. */
  function headers(extra) {
    var h = extra || {};
    var t = token();
    if (t) {
      h['X-Symoneural-Token'] = t;
      // And the name this header had until the rename. Both, because the site and the API are
      // deployed by two separate commands (`deploy.sh`, then `systemctl restart`), so there is
      // a window where this file is new and the server answering it is not. The server reads
      // both too, which covers the other direction -- a cached copy of this file against a new
      // API. Same secret, same origin, twice in one request header block; it comes out once
      // the API is known to be restarted.
      h['X-Sym-Token'] = t;
    }
    return h;
  }

  function getJSON(path, opts) {
    return fetch(API + path, Object.assign({ headers: headers({}) }, opts || {}))
      .then(function (r) {
        return r.json().catch(function () { return {}; }).then(function (body) {
          return { status: r.status, ok: r.ok, body: body };
        });
      });
  }

  function postJSON(path, payload) {
    return getJSON(path, {
      method: 'POST',
      headers: headers({ 'Content-Type': 'application/json' }),
      body: JSON.stringify(payload || {})
    });
  }

  /* ---- status strip ------------------------------------------------------ */
  function cell(title, value, cls, sub) {
    var c = el('div', 'st-cell');
    c.appendChild(el('h3', null, title));
    var p = el('p', cls || null, value);
    c.appendChild(p);
    if (sub) c.appendChild(el('p', 'sub', sub));
    return c;
  }

  function renderStrip(s) {
    var strip = $('st-strip');
    strip.textContent = '';

    strip.appendChild(cell('Surface',
      s.enabled ? 'on' : 'off',
      s.enabled ? 'st-on' : 'st-off',
      s.enabled ? 'both switches set' : s.detail));

    var inf = s.inference || {};
    var active = inf.active;
    var backends = inf.backends || {};
    strip.appendChild(cell('Inference',
      active || 'not answering',
      active ? 'st-on' : 'st-warn',
      active && backends[active] ? backends[active].url
        : (inf.detail || (backends.llamacpp && backends.llamacpp.detail) || '')));

    /* The down branch prints the command that fixes it, so this cell has to name a script
     * that exists. It named `scripts/comfyui.sh` for a day after the fork renamed that file
     * to `scripts/symoneural-ui.sh`, which is worse than an unhelpful cell: an operator who
     * pastes it gets "No such file or directory" and reasonably concludes the page is
     * stale about more than this. `tests/studio.mjs` asserts the label; nothing asserts the
     * hint, which is why it drifted. */
    var comfy = s.render_ui || {};
    strip.appendChild(cell('Render UI',
      comfy.up ? 'up' : 'down',
      comfy.up ? 'st-on' : 'st-warn',
      comfy.up ? comfy.url : 'scripts/symoneural-ui.sh start'));

    strip.appendChild(cell('Tools', s.tools, s.tools ? 'st-on' : 'st-off',
      (s.workflows || []).length + ' stock workflow'
        + ((s.workflows || []).length === 1 ? '' : 's')));

    var lease = s.lease || {};
    /* The lease cell reports the lock this page's own work takes. When nothing is in flight it
     * says so in words rather than showing an idle indicator -- an idle indicator and a broken
     * one look identical. */
    strip.appendChild(cell('GPU lease',
      lease.holding ? ('held · ' + lease.in_flight + ' in flight') : 'not held',
      lease.holding ? 'st-on' : 'st-off',
      lease.last && lease.last.drain_wait_s !== undefined && lease.last.drain_wait_s !== null
        ? ('last drain ' + lease.last.drain_wait_s + ' s to '
           + (lease.last.vram_after_mib !== null ? lease.last.vram_after_mib + ' MiB' : 'unknown'))
        : ''));

    var ws = s.workspace || {};
    strip.appendChild(cell('Workspace', ws.root || 'not found', ws.root ? null : 'st-warn',
      ws.root ? ('located by ' + ws.found_by) : 'set SYMONEURAL_STUDIO_ROOT'));
  }

  /* ---- the gate ---------------------------------------------------------- */
  function showGate(state, reason) {
    var g = $('st-gate');
    g.textContent = '';
    g.hidden = false;

    if (state && state.enabled === false) {
      g.appendChild(el('h2', null, 'This surface is switched off'));
      var p = el('p', null, 'It reaches the whole filesystem and can run commands, so it is off '
        + 'unless the operator sets both switches and restarts the API:');
      g.appendChild(p);
      var pre = el('p', null, '');
      var c1 = el('code', null, 'SYMONEURAL_STUDIO_ENABLED=1');
      var c2 = el('code', null, 'SYMONEURAL_STUDIO_TOKEN=<secret>');
      pre.appendChild(c1); pre.appendChild(document.createTextNode(' '));
      pre.appendChild(c2);
      g.appendChild(pre);
      return;
    }

    g.appendChild(el('h2', null, reason === 'bad' ? 'That token was not accepted'
                                                  : 'Operator token'));
    g.appendChild(el('p', null,
      'The agent, the bench and the renderer all need it. It is held for this tab only and is '
      + 'not written to disk.'));
    var form = el('form');
    var input = document.createElement('input');
    input.type = 'password';
    input.placeholder = 'SYMONEURAL_STUDIO_TOKEN';
    input.autocomplete = 'off';
    var btn = el('button', null, 'Unlock');
    btn.type = 'submit';
    form.appendChild(input);
    form.appendChild(btn);
    form.addEventListener('submit', function (e) {
      e.preventDefault();
      if (!input.value) return;
      setToken(input.value);
      boot();
    });
    g.appendChild(form);
    input.focus();
  }

  function hideGate() { $('st-gate').hidden = true; $('st-gate').textContent = ''; }

  /* ---- agent transcript --------------------------------------------------- */
  var LABEL = {
    backend: 'engine', notice: 'notice', thinking: 'thinking', tool_call: 'tool call',
    tool_result: 'tool result', answer: 'answer', error: 'error', done: 'done'
  };

  function logEvent(ev) {
    var log = $('st-log');
    var kind = ev.event;
    if (kind === 'done') {
      var used = ev.tools_used || 0;
      var d = el('div', 'st-ev');
      d.appendChild(el('h4', null, LABEL.done));
      d.appendChild(el('p', null,
        ev.steps + ' step' + (ev.steps === 1 ? '' : 's') + ' · '
        /* `tools_used` is a count, not a list. `agent.py:270` opens `used = 0`, `:327`
         * increments it, and both `done` frames (`:296`, `:353`) yield it as `tools_used`. This
         * line used to read `(ev.tools_used || []).length`, which is `undefined` on a number, so
         * every turn that actually called a tool rendered "undefined tool calls" -- and it looked
         * right in exactly the case nobody checks, a turn with zero calls, where `0 || []` falls
         * through to the empty array and `.length` is 0. */
        + used + ' tool call' + (used === 1 ? '' : 's') + ' · ' + ev.seconds + ' s'
        + (ev.hit_step_limit ? ' · stopped at the step limit' : '')));
      log.appendChild(d);
      log.scrollTop = log.scrollHeight;
      return;
    }

    var box = el('div', 'st-ev'
      + (kind === 'tool_call' ? ' call' : '')
      + (kind === 'error' ? ' err' : '')
      + (kind === 'answer' ? ' answer' : ''));
    box.appendChild(el('h4', null, LABEL[kind] || kind));

    if (kind === 'backend') {
      box.appendChild(el('p', null, ev.name + ' · ' + ev.url));
    } else if (kind === 'error') {
      box.appendChild(el('p', null, (ev.code ? ev.code + ': ' : '') + (ev.detail || ev.error || '')));
    } else if (kind === 'tool_call') {
      box.appendChild(el('p', null, ev.name));
      box.appendChild(el('pre', null, JSON.stringify(ev.arguments, null, 2)));
    } else if (kind === 'tool_result') {
      box.appendChild(el('p', null, ev.name + ' · ' + ev.seconds + ' s'));
      /* The raw return value, not a summary of it. That is the point of the panel: the model
       * is fed exactly this, so the operator should be able to read exactly this. Long results
       * scroll inside their own box rather than being cut. */
      box.appendChild(el('pre', null, JSON.stringify(ev.result, null, 2)));
      renderImagesFrom(ev.result);
    } else {
      box.appendChild(el('p', null, ev.text || ev.detail || ''));
    }
    log.appendChild(box);
    log.scrollTop = log.scrollHeight;
  }

  function askAgent(query) {
    var send = $('st-send');
    send.disabled = true;
    $('st-agent-note').textContent = '';
    var box = el('div', 'st-ev');
    box.appendChild(el('h4', null, 'you'));
    box.appendChild(el('p', null, query));
    $('st-log').appendChild(box);

    return fetch(API + '/agent', {
      method: 'POST',
      headers: headers({ 'Content-Type': 'application/json' }),
      body: JSON.stringify({ query: query })
    }).then(function (r) {
      if (!r.ok || !r.body) {
        return r.json().catch(function () { return {}; }).then(function (b) {
          logEvent({ event: 'error', code: String(r.status), detail: b.detail || b.error || '' });
          if (r.status === 401 || r.status === 503) showGate(null, 'bad');
        });
      }
      /* SSE read by hand rather than with EventSource, because EventSource cannot POST and the
       * query does not belong in a URL. Frames are separated by a blank line; a partial frame
       * is kept in `buf` until the rest of it arrives. */
      var reader = r.body.getReader();
      var decoder = new TextDecoder();
      var buf = '';
      function pump() {
        return reader.read().then(function (chunk) {
          if (chunk.done) return;
          buf += decoder.decode(chunk.value, { stream: true });
          var parts = buf.split('\n\n');
          buf = parts.pop();
          parts.forEach(function (frame) {
            var line = frame.split('\n').filter(function (l) { return l.indexOf('data:') === 0; })[0];
            if (!line) return;
            try { logEvent(JSON.parse(line.slice(5).trim())); } catch (e) {}
          });
          return pump();
        });
      }
      return pump();
    }).catch(function (e) {
      logEvent({ event: 'error', detail: String(e) });
    }).then(function () {
      send.disabled = false;
      refresh();
    });
  }

  /* ---- renders ------------------------------------------------------------ */
  function renderImagesFrom(result) {
    if (!result || !result.images || !result.images.length) return;
    var shots = $('st-shots');
    result.images.forEach(function (img) {
      if (!img.proxy_url) return;
      var fig = el('figure');
      var i = document.createElement('img');
      i.src = img.proxy_url + '&token=' + encodeURIComponent(token());
      i.alt = img.filename || 'render';
      i.loading = 'lazy';
      fig.appendChild(i);
      fig.appendChild(el('figcaption', null, img.filename || ''));
      shots.insertBefore(fig, shots.firstChild);
    });
  }

  function doRender(e) {
    e.preventDefault();
    var go = $('st-go');
    var note = $('st-render-note');
    var prompt = ($('st-prompt').value || '').trim();
    if (!prompt) { note.textContent = 'A prompt is required.'; return; }
    var size = ($('st-size').value || '1024x1024').split('x');
    go.disabled = true;
    note.textContent = 'queued · the card is acquired for this job and released after it';
    var started = Date.now();
    postJSON('/queue', {
      workflow: $('st-wf').value || undefined,
      params: { prompt: prompt, width: parseInt(size[0], 10), height: parseInt(size[1], 10) }
    }).then(function (r) {
      var b = r.body || {};
      if (!r.ok || b.ok === false) {
        note.textContent = 'failed: ' + (b.detail || b.error || ('HTTP ' + r.status));
        if (b.node_errors) note.textContent += ' · ' + JSON.stringify(b.node_errors);
        return;
      }
      var lease = b.lease || {};
      /* `elapsed_s`, not `wall_clock_s`. `/queue` returns `comfy_tool.execute`'s dict
       * verbatim (`routes.py:547-550`) and that dict is stamped `result["elapsed_s"]` at
       * `comfy_tool.py:202`; nothing anywhere produces `wall_clock_s`, so this segment never
       * rendered. It is also not "in ComfyUI" time: `started` is taken at `comfy_tool.py:98`,
       * above the `/object_info` fetch, the graph validation and `lease()`, so it spans the
       * queue wait for the card and the VRAM drain as well as the render. The browser's own
       * figure to its left is the same span plus HTTP, which is why both are printed. */
      note.textContent = ((Date.now() - started) / 1000).toFixed(1) + ' s wall clock'
        + (b.elapsed_s ? ' · ' + b.elapsed_s + ' s server-side' : '')
        + (lease.drain_wait_s !== undefined && lease.drain_wait_s !== null
            ? ' · card back in ' + lease.drain_wait_s + ' s' : '')
        + (lease.released ? ' · lock released' : '')
        /* Parameters the graph had no home for. Reported rather than swallowed: a name the
         * stock workflow does not carry is exactly the mistake worth seeing. */
        + (b.unapplied && b.unapplied.length
            ? ' · ignored: ' + b.unapplied.map(function (u) { return u.address; }).join(', ')
            : '');
      renderImagesFrom(b);
    }).catch(function (err) {
      note.textContent = String(err);
    }).then(function () {
      go.disabled = false;
      refresh();
    });
  }

  /* ---- tools and workflows ------------------------------------------------ */
  function renderTools(tools) {
    var body = $('st-tools');
    body.textContent = '';
    tools.forEach(function (t) {
      var tr = el('tr');
      var td1 = el('td');
      td1.appendChild(el('b', null, t.name));
      if (t.dangerous) {
        td1.appendChild(document.createTextNode(' '));
        td1.appendChild(el('b', 'st-danger', 'writes'));
      }
      tr.appendChild(td1);
      tr.appendChild(el('td', null, t.group));
      /* First sentence only: the full description is the model's, and the table is the
       * operator's. The whole thing is one fetch away at /api/studio/tools. */
      tr.appendChild(el('td', null, (t.description || '').split('\n')[0]));
      body.appendChild(tr);
    });
    $('st-tools-wrap').querySelector('summary').textContent =
      tools.length + ' tools the agent can call';
  }

  function renderWorkflows(list, dflt) {
    var sel = $('st-wf');
    sel.textContent = '';
    list.forEach(function (w) {
      var o = document.createElement('option');
      o.value = w.name;
      o.textContent = w.name + ' · ' + w.node_count + ' nodes';
      if (w.name === dflt) o.selected = true;
      sel.appendChild(o);
    });
  }

  /* ---- the bench ---------------------------------------------------------- */
  function mountBench() {
    var frame = $('st-bench-frame');
    var absent = $('st-bench-absent');
    if (!token()) { frame.hidden = true; absent.hidden = false; return; }
    if (frame.getAttribute('src')) return;   // never remount: it would reset the user's graph
    /* The token rides in the query string because an iframe cannot carry a header. The proxy
     * strips it before forwarding, so it never reaches ComfyUI's access log. */
    frame.src = '/studio/editor/?token=' + encodeURIComponent(token());
    frame.hidden = false;
    absent.hidden = true;
  }

  /* Expand -- the bench over the whole viewport.
   *
   * `st-wide` is toggled on `.st-bench` and nothing is moved. That is the whole reason this is
   * a class toggle rather than the obvious `document.body.appendChild(bench)`: re-parenting an
   * iframe reloads its document, which would throw away the graph being edited. Same argument
   * as `mountBench`'s never-remount guard, from the other direction.
   *
   * The preference is in localStorage, not sessionStorage. The token dies with the tab on
   * purpose; a window-size preference is not a secret and there is no reason to make the
   * operator re-expand on every visit.
   */
  var WIDE_KEY = 'sym.studio.bench.wide';

  function setWide(on) {
    var bench = $('st-bench');
    var btn = $('st-expand');
    if (!bench || !btn) return;
    bench.classList.toggle('st-wide', !!on);
    btn.textContent = on ? 'Collapse' : 'Expand';
    btn.setAttribute('aria-pressed', on ? 'true' : 'false');
    /* Inline rather than a stylesheet rule: `body` is outside this panel, and every selector in
     * page.html is `#studio`-prefixed precisely so this file cannot reach out and restyle the
     * rest of the site. One property set from here is the honest exception. */
    document.body.style.overflow = on ? 'hidden' : '';
    try { localStorage.setItem(WIDE_KEY, on ? '1' : '0'); } catch (e) { /* private mode */ }
  }

  function wireBench() {
    var btn = $('st-expand');
    if (!btn) return;
    /* No token means the frame is an "it needs the operator token" box, and expanding that to
     * fill the viewport would be a full-screen apology. `token()` is a synchronous
     * sessionStorage read, so this is accurate here even though `boot()` has not resolved. */
    btn.disabled = !token();
    btn.addEventListener('click', function () {
      setWide(!$('st-bench').classList.contains('st-wide'));
    });
    /* Escape is what every full-screen surface on the web answers to, and a fixed panel with no
     * keyboard way out is a trap -- the site header is covered, so there is nothing else to
     * click. Bound on document because focus is usually inside the iframe, which means the
     * keydown never reaches this document at all: hence the button stays visible while wide. */
    document.addEventListener('keydown', function (ev) {
      if (ev.key === 'Escape' && $('st-bench').classList.contains('st-wide')) setWide(false);
    });
    var stored = null;
    try { stored = localStorage.getItem(WIDE_KEY); } catch (e) { /* private mode */ }
    if (stored === '1' && token()) setWide(true);
  }

  /* ---- boot --------------------------------------------------------------- */
  var timer = null;

  function refresh() {
    return getJSON('/state').then(function (r) {
      renderStrip(r.body || {});
      return r.body || {};
    }).catch(function () { return {}; });
  }

  function boot() {
    refresh().then(function (state) {
      if (state.enabled === false) { showGate(state); return; }
      if (!token()) { showGate(state); return; }
      return getJSON('/tools').then(function (r) {
        if (r.status === 401) { showGate(state, 'bad'); return; }
        if (!r.ok) return;
        hideGate();
        renderTools((r.body || {}).tools || []);
        mountBench();
        return getJSON('/workflows').then(function (w) {
          if (w.ok) renderWorkflows((w.body || {}).workflows || [], (w.body || {}).default);
        });
      });
    });
    if (timer === null) {
      /* 15 s. Fast enough that a lease taken by the bench shows up while it still matters, slow
       * enough that an idle tab is not a load. /state runs no subprocess and takes no lock. */
      timer = setInterval(refresh, 15000);
    }
  }

  document.addEventListener('DOMContentLoaded', function () {
    $('st-ask').addEventListener('submit', function (e) {
      e.preventDefault();
      var q = ($('st-q').value || '').trim();
      if (!q) return;
      $('st-q').value = '';
      askAgent(q);
    });
    $('st-render').addEventListener('submit', doRender);
    wireBench();
    boot();
  });
})();
