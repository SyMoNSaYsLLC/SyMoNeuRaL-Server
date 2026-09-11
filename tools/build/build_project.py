"""Generate `frontend/site/pages/project.html` -- the web client for `backend/project`.

    python3 tools/build/build_project.py && python3 tools/build/build_cachebust.py

Runs BEFORE `build_cachebust.py`, which must run last. The `SHELL` this file borrows from
`build_pages` carries plain `href="/symoneural.css"`, so a bare run here emits ten asset
links with no `?v=` stamp -- and the Caddyfile marks .css/.js/.png/.svg/.woff2
`max-age=604800`, so a destamped page ships new markup against a stylesheet the browser may
keep for a week with no way to invalidate it. That has already produced one visibly broken
page in front of a visitor. This page shipped destamped exactly that way; a peer session
caught it and restamped in `8c8b89f`.

Nothing downstream catches it, which is what makes it worth a docstring: `scripts/deploy.sh`
strips `?v=` before checking that references resolve, so a destamped page deploys perfectly
quietly and the reference check stays green. Check it directly instead --
`grep -c '?v=' frontend/site/pages/project.html` must be non-zero before calling this surface done.

`backend/project/README.md` closes its "What is NOT implemented" list with, in first
place, *"There is no page."* The API has been complete and usable from `curl` since it was
written; nothing rendered it, so the rack tile pointed at `/documentation.html` and the
surface Garrett asked for -- *"like the claude cowork"* -- was invisible on the site that
advertises it. This is that page.

## It writes one file, and that file is new

Every other generator that touches `site/` rewrites a page some other generator also writes;
`.claude/CLAUDE.md` calls that out as the real hazard when several agents run at once. This
one writes `frontend/site/pages/project.html` and nothing else, so it cannot clobber another writer. It
imports `build_pages` for `SHELL` and `NAV` but never calls `build_pages.page()`, which would.

## Every class name is prefixed `pj-`

Four separate bugs on this site have come from a generic class name colliding across
components -- `.bar` collapsed the site header to 7px sitewide, `.live` restyled the control
board legend from a nav badge, `#console .sub` outranked `.mod .sub`. Every selector this
file emits starts `pj-`, and there are no `#project .something` descendant rules.

## What the page may claim

The surface's own README is careful about this and the page inherits it:

* Every number shown comes from `GET /api/project/state`, read live. There is no figure
  baked into this file, because there is no measurement of this surface worth quoting yet:
  README item 8 says search latency was deliberately not measured, and item 9 says the
  "works while the GPU is busy" claim is asserted in code but **not measured end to end**.
  So the page states that claim as a design guarantee and says plainly that the measurement
  has not been made. `.claude/CLAUDE.md`: never present a projection as a result.
* The two `draft/` endpoints return and never store. The buttons say so, because a draft
  that looked saved and was not is the kind of quiet lie this site exists to avoid.

## The token never goes in a URL

`ops/Caddyfile` writes an access log and uvicorn logs the request line, so a token in a
query string is a token written to disk on every request. It travels in `X-Symoneural-Token`, is
held in `localStorage`, and this file contains no token and no default.
"""
from __future__ import annotations

import pathlib
import sys

ROOT = next(_p for _p in pathlib.Path(__file__).resolve().parents if (_p / "backend" / "server.py").is_file())
assert (ROOT / "backend" / "server.py").is_file(), f"repo root not found at {ROOT}"
SITE = ROOT / "frontend" / "site"
sys.path.insert(0, str(ROOT / "tools"))

import build_pages  # noqa: E402  -- for NAV and SHELL. Read, not run: importing it is safe
                    # (its work is behind __main__) and calling page() would rewrite pages
                    # this generator does not own.

#: Where the API is mounted. One constant, because the page and the wiring have to agree and
#: a prefix scattered through the JavaScript is how they stop agreeing. Note the bare form:
#: the list route is declared as "" so it answers on `/api/project`, and the trailing-slash
#: form is claimed by the StaticFiles mount at `/` and 404s off disk.
API = "/api/project"

#: The four item states and five event kinds the store accepts. Mirrored from
#: `store.ITEM_STATES` / `store.EVENT_KINDS` -- a select offering a fifth value would be a
#: control that always fails with `bad_field`.
ITEM_STATES = ("open", "doing", "blocked", "done")
EVENT_KINDS = ("note", "session", "change", "decision", "draft")


CSS = r"""
#pj-app { display: grid; gap: 18px; grid-template-columns: minmax(0,1fr) 320px; }
@media (max-width: 900px) { #pj-app { grid-template-columns: minmax(0,1fr); } }

/* `[hidden]` is `display:none` in the UA stylesheet at specificity (0,0,1); `#pj-app` is
   (1,0,0) and beats it. Without this rule the whole workspace renders *behind the token
   gate* while still locked -- caught by reading the computed style in a real browser, which
   is the only reason it was found. Each selector here outranks the rule it has to beat. */
#pj-app[hidden], .pj-gate[hidden] { display: none; }

.pj-gate { border: 1px solid var(--line, #2a2f3a); border-radius: 10px; padding: 14px 16px;
           margin-bottom: 16px; background: rgba(255,255,255,.02); }
.pj-gate b { display: block; margin-bottom: 6px; }
.pj-gate code { white-space: pre-wrap; word-break: break-word; }
.pj-gate .pj-row { display: flex; gap: 8px; flex-wrap: wrap; margin-top: 10px; }
.pj-gate input { flex: 1 1 260px; min-width: 0; }

.pj-card { border: 1px solid var(--line, #2a2f3a); border-radius: 10px; padding: 14px 16px;
           margin-bottom: 16px; }
.pj-card > h2 { font-size: 15px; margin: 0 0 10px; letter-spacing: .02em; }
.pj-card > h2 .pj-count { opacity: .65; font-weight: 400; margin-left: 6px; }

.pj-list { list-style: none; margin: 0; padding: 0; }
.pj-list li { border-top: 1px solid var(--line, #2a2f3a); padding: 9px 0; }
.pj-list li:first-child { border-top: 0; }

/* Wrap, never clip. `.claude/CLAUDE.md`: an ellipsis rule on a detail line is data loss
   with extra steps -- the rack was cutting an Apache-2.0 attribution down to a stub. */
.pj-list li, .pj-item-body, .pj-ev-text, .pj-path { overflow-wrap: anywhere; }

.pj-item { display: grid; grid-template-columns: auto minmax(0,1fr) auto; gap: 10px;
           align-items: start; }
.pj-item-title { font-weight: 600; }
.pj-item-body { opacity: .8; font-size: 13.5px; margin-top: 3px; white-space: pre-wrap; }
.pj-item select { font-size: 12px; padding: 2px 4px; }

.pj-chip { display: inline-block; font-size: 11px; text-transform: uppercase;
           letter-spacing: .06em; padding: 2px 7px; border-radius: 999px;
           border: 1px solid var(--line, #2a2f3a); }
.pj-open    { color: #9fb4d8; }
.pj-doing   { color: #7fd3a2; }
.pj-blocked { color: #e0a45e; }
.pj-done    { color: #7a8496; }

.pj-ev { display: grid; grid-template-columns: auto minmax(0,1fr); gap: 10px; }
.pj-ev-text { white-space: pre-wrap; }
.pj-when { opacity: .55; font-size: 12px; }

.pj-path { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: 13px; }
.pj-stat { opacity: .6; font-size: 12px; }

.pj-row { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; }
.pj-row input, .pj-row select { min-width: 0; }
.pj-grow { flex: 1 1 160px; }

.pj-x { background: none; border: 0; color: inherit; opacity: .5; cursor: pointer;
        font-size: 15px; line-height: 1; padding: 2px 4px; }
.pj-x:hover { opacity: 1; }

.pj-proj { width: 100%; text-align: left; background: none; border: 0; color: inherit;
           cursor: pointer; padding: 0; font: inherit; }
.pj-proj[aria-current="true"] { font-weight: 700; }
.pj-proj .pj-sub { display: block; opacity: .6; font-size: 12px; font-weight: 400; }

.pj-note { opacity: .7; font-size: 13px; }
.pj-err { color: #e08080; font-size: 13px; margin-top: 8px; }
.pj-empty { opacity: .6; padding: 8px 0; }

.pj-readings { list-style: none; margin: 0; padding: 0; font-size: 13.5px; }
.pj-readings li { display: flex; justify-content: space-between; gap: 12px;
                  padding: 4px 0; }
.pj-readings b { font-weight: 600; }

.pj-draft { border: 1px dashed var(--line, #2a2f3a); border-radius: 8px; padding: 10px 12px;
            margin-top: 10px; }
.pj-draft h3 { font-size: 13px; margin: 0 0 8px; }

.pj-composer textarea { width: 100%; box-sizing: border-box; }
.pj-composer .pj-row { margin-top: 8px; }
"""


def body() -> str:
    """The middle of the page.

    Everything below renders empty and is filled from the API. Nothing here is a placeholder
    number: there is no `--` standing in for a reading that will arrive, because a visitor
    cannot tell a placeholder from a measurement that came back zero.
    """
    states = "\n".join(
        f'                <option value="{s}">{s}</option>' for s in ITEM_STATES)
    kinds = "\n".join(
        f'              <option value="{k}">{k}</option>' for k in EVENT_KINDS)

    return f"""    <div id="pj-gate" class="pj-gate" hidden></div>

    <div id="pj-app" hidden>
      <div>
        <section class="pj-card">
          <h2 id="pj-title">No workspace open</h2>
          <p id="pj-summary" class="pj-note"></p>
        </section>

        <section class="pj-card">
          <h2>Work items <span class="pj-count" id="pj-items-count"></span></h2>
          <ul class="pj-list" id="pj-items"></ul>
          <form class="pj-row" id="pj-item-form" style="margin-top:10px">
            <input class="pj-grow" id="pj-item-title" maxlength="400"
                   placeholder="what needs doing" autocomplete="off">
            <select id="pj-item-state">
{states}
            </select>
            <button class="cta" type="submit">Add</button>
          </form>
        </section>

        <section class="pj-card">
          <h2>Files this workspace refers to <span class="pj-count" id="pj-files-count"></span></h2>
          <p class="pj-note">A reference is a path, never a copy. Paths are resolved and
             checked against a denylist, so a reference cannot reach the training corpus,
             the GPU lock directory or this store.</p>
          <ul class="pj-list" id="pj-files"></ul>
          <form class="pj-row" id="pj-file-form" style="margin-top:10px">
            <input class="pj-grow" id="pj-file-path" maxlength="400"
                   placeholder="backend/project/README.md" autocomplete="off">
            <input class="pj-grow" id="pj-file-note" maxlength="400"
                   placeholder="why it matters (optional)" autocomplete="off">
            <button class="cta" type="submit">Reference</button>
          </form>
        </section>

        <section class="pj-card">
          <h2>History <span class="pj-count" id="pj-events-count"></span></h2>
          <p class="pj-note">Append-only. There is no route that edits or deletes an entry,
             which is what makes it worth reading.</p>
          <ul class="pj-list" id="pj-events"></ul>
        </section>

        <section class="pj-card pj-composer">
          <h2>Write it down</h2>
          <textarea id="pj-note" rows="4" maxlength="200000"
                    placeholder="what you did, what you tried, what is next"></textarea>
          <div class="pj-row">
            <select id="pj-ev-kind">
{kinds}
            </select>
            <button class="cta" id="pj-record" type="button">Record in history</button>
            <button id="pj-draft-items" type="button">Draft items from this</button>
            <button id="pj-draft-summary" type="button">Draft a summary</button>
          </div>
          <p class="pj-note" style="margin-top:8px">The two draft buttons ask the chat
             surface and <b>return the answer without storing it</b>. Nothing is written
             until you add it.</p>
          <div id="pj-draft" class="pj-draft" hidden></div>
          <p class="pj-err" id="pj-compose-err"></p>
        </section>
      </div>

      <aside>
        <section class="pj-card">
          <h2>Workspaces</h2>
          <ul class="pj-list" id="pj-projects"></ul>
          <form class="pj-row" id="pj-proj-form" style="margin-top:10px">
            <input class="pj-grow" id="pj-proj-name" maxlength="400"
                   placeholder="new workspace" autocomplete="off">
            <button class="cta" type="submit">Create</button>
          </form>
          <p class="pj-err" id="pj-proj-err"></p>
        </section>

        <section class="pj-card">
          <h2>Search</h2>
          <form class="pj-row" id="pj-search-form">
            <input class="pj-grow" id="pj-q" maxlength="400"
                   placeholder="full text over items and history" autocomplete="off">
            <button type="submit">Find</button>
          </form>
          <ul class="pj-list" id="pj-results" style="margin-top:10px"></ul>
        </section>

        <section class="pj-card">
          <h2>Readings</h2>
          <ul class="pj-readings" id="pj-readings"></ul>
          <p class="pj-note" style="margin-top:10px">Read from the store on every load.
             This surface loads no weights and never asks for the GPU lock, so it answers
             while the card is busy. That is a design guarantee asserted by its test suite;
             the end-to-end measurement &mdash; hold the lock with a render and confirm no
             wait line for <code>project</code> &mdash; has not been made, and is not
             claimed here as one.</p>
        </section>
      </aside>
    </div>
"""


SCRIPT = r"""<script>
(function () {
  'use strict';
  var API = '@@API@@';
  var TK = 'sym.project.token';      // the shared secret, never sent in a URL
  var OPEN = 'sym.project.open';     // which workspace was open, as the README suggests

  var open = null;                   // the currently open project row
  var lastNote = '';

  function $(id) { return document.getElementById(id); }
  function esc(s) {
    var d = document.createElement('div');
    d.textContent = (s === null || s === undefined) ? '' : String(s);
    return d.innerHTML;
  }
  function tok() { try { return localStorage.getItem(TK) || ''; } catch (e) { return ''; } }
  function when(t) {
    if (!t) { return ''; }
    try { return new Date(t * 1000).toLocaleString(); } catch (e) { return ''; }
  }
  function bytes(n) {
    if (!n) { return '0 B'; }
    var u = ['B', 'KiB', 'MiB', 'GiB'], i = 0, v = n;
    while (v >= 1024 && i < u.length - 1) { v /= 1024; i += 1; }
    return (i === 0 ? v : v.toFixed(1)) + ' ' + u[i];
  }

  // Every response is the same envelope: {ok, api_version, code?, error?}. A client that
  // branches on HTTP status instead of `code` would have to know which route maps which.
  function api(method, path, payload) {
    /* Both spellings: site/ and the API are deployed by separate commands, so this file can
       be the newer of the two. The server reads both as well, for a cached copy of this file
       against a new API. Drop the legacy key once the deployed API reads the new name. */
    var opt = { method: method, headers: { 'X-Symoneural-Token': tok(), 'X-Sym-Token': tok() } };
    if (payload !== undefined) {
      opt.headers['Content-Type'] = 'application/json';
      opt.body = JSON.stringify(payload);
    }
    return fetch(API + path, opt).then(function (r) {
      return r.json().catch(function () {
        return { ok: false, code: 'network',
                 error: 'the API answered ' + r.status + ' with no JSON body' };
      });
    }).catch(function (e) {
      return { ok: false, code: 'network', error: String(e) };
    });
  }

  // ---------------------------------------------------------------- the gate

  function showGate(res) {
    var g = $('pj-gate');
    g.hidden = false;
    $('pj-app').hidden = true;
    var code = res && res.code;
    if (code === 'disabled') {
      g.innerHTML =
        '<b>This workspace is switched off on this installation.</b>' +
        '<p class="pj-note">Both variables are required, so a half-configured surface ' +
        'fails closed rather than opening a private workspace on a public address. ' +
        'Set them in the systemd unit environment and restart the API:</p>' +
        '<p><code>SYMONEURAL_PROJECT_ENABLED=1</code><br><code>SYMONEURAL_PROJECT_TOKEN=' +
        '&lt;secrets.token_urlsafe(32)&gt;</code></p>' +
        '<p class="pj-note">Read <code>backend/project/README.md</code> first.</p>';
      return;
    }
    var msg = (code === 'unauthorized' || !code)
      ? 'This workspace needs its token.'
      : esc(res && res.error ? res.error : 'the surface did not answer');
    g.innerHTML =
      '<b>' + msg + '</b>' +
      '<p class="pj-note">It is sent as the <code>X-Symoneural-Token</code> header and kept in ' +
      'this browser only. It is never put in a URL, because the web server and the API ' +
      'both log request lines to disk.</p>' +
      '<div class="pj-row"><input id="pj-tok" type="password" autocomplete="off" ' +
      'placeholder="X-Symoneural-Token"><button class="cta" id="pj-tok-save">Use it</button></div>';
    var save = $('pj-tok-save');
    if (save) {
      save.addEventListener('click', function () {
        var v = ($('pj-tok').value || '').trim();
        if (!v) { return; }
        try { localStorage.setItem(TK, v); } catch (e) { /* private mode */ }
        boot();
      });
    }
  }

  // ---------------------------------------------------------------- rendering

  function readings(s) {
    var rows = [
      ['Workspaces', s.projects],
      ['Archived', s.projects_archived],
      ['Work items', s.items],
      ['Open', s.items_open],
      ['File references', s.files],
      ['History entries', s.events],
      ['Store on disk', bytes(s.bytes_on_disk)]
    ];
    var html = rows.map(function (r) {
      return '<li><span>' + esc(r[0]) + '</span><b>' + esc(r[1]) + '</b></li>';
    }).join('');
    if (s.note) { html += '<li><span class="pj-note">' + esc(s.note) + '</span></li>'; }
    $('pj-readings').innerHTML = html;
  }

  function projects(rows) {
    var ul = $('pj-projects');
    if (!rows.length) {
      ul.innerHTML = '<li class="pj-empty">No workspaces yet. Create one.</li>';
      return;
    }
    ul.innerHTML = rows.map(function (p) {
      var cur = open && open.id === p.id;
      return '<li><button class="pj-proj" data-pid="' + esc(p.id) + '" aria-current="' +
        (cur ? 'true' : 'false') + '">' + esc(p.name) +
        '<span class="pj-sub">' + esc(p.items_open) + ' open of ' + esc(p.items) +
        ' &middot; ' + esc(p.events) + ' in history</span></button></li>';
    }).join('');
    Array.prototype.forEach.call(ul.querySelectorAll('.pj-proj'), function (b) {
      b.addEventListener('click', function () { openProject(b.getAttribute('data-pid')); });
    });
  }

  function items(rows) {
    $('pj-items-count').textContent = rows.length ? rows.length : '';
    var ul = $('pj-items');
    if (!rows.length) {
      ul.innerHTML = '<li class="pj-empty">Nothing here yet.</li>';
      return;
    }
    ul.innerHTML = rows.map(function (it) {
      var opts = ['open', 'doing', 'blocked', 'done'].map(function (s) {
        return '<option value="' + s + '"' + (s === it.state ? ' selected' : '') + '>' +
          s + '</option>';
      }).join('');
      return '<li class="pj-item">' +
        '<select data-iid="' + esc(it.id) + '" data-ver="' + esc(it.version) + '">' +
        opts + '</select>' +
        '<div><div class="pj-item-title">' + esc(it.title) + '</div>' +
        (it.body ? '<div class="pj-item-body">' + esc(it.body) + '</div>' : '') + '</div>' +
        '<button class="pj-x" data-del="' + esc(it.id) + '" title="delete">&times;</button>' +
        '</li>';
    }).join('');
    Array.prototype.forEach.call(ul.querySelectorAll('select'), function (sel) {
      sel.addEventListener('change', function () {
        api('PATCH', '/' + open.id + '/items/' + sel.getAttribute('data-iid'),
            { state: sel.value, if_version: parseInt(sel.getAttribute('data-ver'), 10) })
          .then(function (r) { report(r, 'pj-compose-err'); openProject(open.id); });
      });
    });
    Array.prototype.forEach.call(ul.querySelectorAll('[data-del]'), function (b) {
      b.addEventListener('click', function () {
        api('DELETE', '/' + open.id + '/items/' + b.getAttribute('data-del'))
          .then(function (r) { report(r, 'pj-compose-err'); openProject(open.id); });
      });
    });
  }

  function files(rows) {
    $('pj-files-count').textContent = rows.length ? rows.length : '';
    var ul = $('pj-files');
    if (!rows.length) {
      ul.innerHTML = '<li class="pj-empty">No files referenced.</li>';
      return;
    }
    ul.innerHTML = rows.map(function (f) {
      var rd = f.reading || {};
      var stat = rd.exists === false ? 'not on disk now'
        : (rd.bytes !== undefined && rd.bytes !== null ? bytes(rd.bytes) : '');
      return '<li><div class="pj-row"><span class="pj-path pj-grow">' + esc(f.path) +
        '</span><span class="pj-stat">' + esc(stat) + '</span>' +
        '<button class="pj-x" data-fid="' + esc(f.id) + '" title="drop">&times;</button>' +
        '</div>' + (f.note ? '<div class="pj-note">' + esc(f.note) + '</div>' : '') + '</li>';
    }).join('');
    Array.prototype.forEach.call(ul.querySelectorAll('[data-fid]'), function (b) {
      b.addEventListener('click', function () {
        api('DELETE', '/' + open.id + '/files/' + b.getAttribute('data-fid'))
          .then(function (r) { report(r, 'pj-compose-err'); openProject(open.id); });
      });
    });
  }

  function events(rows) {
    var ul = $('pj-events');
    if (!rows.length) {
      ul.innerHTML = '<li class="pj-empty">Nothing recorded yet.</li>';
      return;
    }
    ul.innerHTML = rows.map(function (e) {
      return '<li class="pj-ev"><span class="pj-chip">' + esc(e.kind) + '</span>' +
        '<div><div class="pj-ev-text">' + esc(e.text) + '</div>' +
        '<div class="pj-when">' + esc(when(e.at)) +
        (e.actor ? ' &middot; ' + esc(e.actor) : '') + '</div></div></li>';
    }).join('');
  }

  function report(r, where) {
    var box = $(where);
    if (!box) { return r; }
    box.textContent = (r && r.ok) ? '' : ((r && r.error) ? r.error : 'that did not work');
    return r;
  }

  // ---------------------------------------------------------------- loading

  function openProject(pid) {
    if (!pid) { return Promise.resolve(); }
    return api('GET', '/' + pid).then(function (r) {
      if (!r.ok) { return report(r, 'pj-proj-err'); }
      open = r.project;
      try { localStorage.setItem(OPEN, pid); } catch (e) { /* private mode */ }
      $('pj-title').textContent = open.name;
      $('pj-summary').textContent = open.summary || '';
      items(r.items || []);
      files(r.files || []);
      $('pj-events-count').textContent = r.events ? r.events : '';
      return api('GET', '/' + pid + '/events').then(function (ev) {
        events((ev && ev.events) || []);
        return refreshList();
      });
    });
  }

  // Re-read rather than adjusting a counter in the browser. The panel is labelled
  // "Readings" and `.claude/CLAUDE.md` requires every gauge to reflect a real reading, so
  // it is refreshed from the store after anything that could change it -- a number left
  // over from page load is a decorative indicator with extra steps.
  function refreshReadings() {
    return api('GET', '/state').then(function (s) {
      if (s.ok) { readings(s); }
      return s;
    });
  }

  function refreshList() {
    refreshReadings();
    return api('GET', '').then(function (r) {
      if (r.ok) { projects(r.projects || []); }
      return r;
    });
  }

  function boot() {
    api('GET', '/state').then(function (s) {
      if (!s.ok) { showGate(s); return; }
      $('pj-gate').hidden = true;
      $('pj-app').hidden = false;
      readings(s);
      refreshList().then(function (r) {
        if (!r.ok) { return; }
        var rows = r.projects || [];
        var want = null;
        try { want = localStorage.getItem(OPEN); } catch (e) { want = null; }
        var pick = null, i;
        for (i = 0; i < rows.length; i += 1) {
          if (rows[i].id === want) { pick = rows[i].id; }
        }
        if (!pick && rows.length) { pick = rows[0].id; }
        if (pick) { openProject(pick); }
      });
    });
  }

  // ---------------------------------------------------------------- actions

  $('pj-proj-form').addEventListener('submit', function (e) {
    e.preventDefault();
    var name = ($('pj-proj-name').value || '').trim();
    if (!name) { return; }
    api('POST', '', { name: name }).then(function (r) {
      report(r, 'pj-proj-err');
      if (r.ok) { $('pj-proj-name').value = ''; openProject(r.project.id); }
    });
  });

  $('pj-item-form').addEventListener('submit', function (e) {
    e.preventDefault();
    if (!open) { return; }
    var t = ($('pj-item-title').value || '').trim();
    if (!t) { return; }
    api('POST', '/' + open.id + '/items',
        { title: t, state: $('pj-item-state').value }).then(function (r) {
      report(r, 'pj-compose-err');
      if (r.ok) { $('pj-item-title').value = ''; openProject(open.id); }
    });
  });

  $('pj-file-form').addEventListener('submit', function (e) {
    e.preventDefault();
    if (!open) { return; }
    var p = ($('pj-file-path').value || '').trim();
    if (!p) { return; }
    api('POST', '/' + open.id + '/files',
        { path: p, note: ($('pj-file-note').value || '').trim() }).then(function (r) {
      report(r, 'pj-compose-err');
      if (r.ok) { $('pj-file-path').value = ''; $('pj-file-note').value = ''; }
      openProject(open.id);
    });
  });

  $('pj-record').addEventListener('click', function () {
    if (!open) { return; }
    var t = ($('pj-note').value || '').trim();
    if (!t) { return; }
    api('POST', '/' + open.id + '/events',
        { kind: $('pj-ev-kind').value, text: t }).then(function (r) {
      report(r, 'pj-compose-err');
      if (r.ok) { $('pj-note').value = ''; openProject(open.id); }
    });
  });

  // Both draft buttons return without storing, and the panel says so on every render --
  // a draft that looked saved and was not is exactly the quiet lie this site avoids.
  $('pj-draft-items').addEventListener('click', function () {
    if (!open) { return; }
    lastNote = ($('pj-note').value || '').trim();
    if (!lastNote) { return; }
    var box = $('pj-draft');
    box.hidden = false;
    box.innerHTML = '<p class="pj-note">asking the chat surface&hellip;</p>';
    api('POST', '/' + open.id + '/draft/items', { note: lastNote }).then(function (r) {
      if (!r.ok) {
        box.innerHTML = '<p class="pj-err">' + esc(r.error || 'no answer') + '</p>';
        return;
      }
      var titles = r.titles || [];
      if (!titles.length) {
        box.innerHTML = '<p class="pj-note">The model returned no candidates.</p>';
        return;
      }
      box.innerHTML = '<h3>Candidates &mdash; nothing is saved until you add it</h3>' +
        '<ul class="pj-list">' + titles.map(function (t, i) {
          return '<li><div class="pj-row"><span class="pj-grow">' + esc(t) +
            '</span><button data-add="' + i + '">Add</button></div></li>';
        }).join('') + '</ul>';
      Array.prototype.forEach.call(box.querySelectorAll('[data-add]'), function (b) {
        b.addEventListener('click', function () {
          var t = titles[parseInt(b.getAttribute('data-add'), 10)];
          api('POST', '/' + open.id + '/items', { title: t }).then(function (rr) {
            report(rr, 'pj-compose-err');
            b.disabled = true;
            b.textContent = 'Added';
            openProject(open.id);
          });
        });
      });
    });
  });

  $('pj-draft-summary').addEventListener('click', function () {
    if (!open) { return; }
    var box = $('pj-draft');
    box.hidden = false;
    box.innerHTML = '<p class="pj-note">asking the chat surface&hellip;</p>';
    api('POST', '/' + open.id + '/draft/summary', {}).then(function (r) {
      if (!r.ok) {
        box.innerHTML = '<p class="pj-err">' + esc(r.error || 'no answer') + '</p>';
        return;
      }
      box.innerHTML = '<h3>Draft summary &mdash; returned, not stored</h3>' +
        '<div class="pj-ev-text">' + esc(r.draft) + '</div>' +
        '<div class="pj-row" style="margin-top:8px">' +
        '<button id="pj-use-summary">Save as this workspace summary</button></div>';
      $('pj-use-summary').addEventListener('click', function () {
        api('PATCH', '/' + open.id,
            { summary: r.draft, if_version: open.version }).then(function (rr) {
          report(rr, 'pj-compose-err');
          box.hidden = true;
          openProject(open.id);
        });
      });
    });
  });

  $('pj-search-form').addEventListener('submit', function (e) {
    e.preventDefault();
    var q = ($('pj-q').value || '').trim();
    var ul = $('pj-results');
    if (!q) { ul.innerHTML = ''; return; }
    api('GET', '/search?q=' + encodeURIComponent(q)).then(function (r) {
      if (!r.ok) {
        ul.innerHTML = '<li class="pj-err">' + esc(r.error || 'that search failed') + '</li>';
        return;
      }
      var rows = r.results || [];
      if (!rows.length) {
        ul.innerHTML = '<li class="pj-empty">Nothing matched.</li>';
        return;
      }
      ul.innerHTML = rows.map(function (x) {
        return '<li><span class="pj-chip">' + esc(x.kind) + '</span> ' +
          '<button class="pj-proj" data-goto="' + esc(x.project_id) + '">' +
          esc(x.title || '(untitled)') + '<span class="pj-sub">' + esc(x.excerpt || '') +
          '</span></button></li>';
      }).join('');
      Array.prototype.forEach.call(ul.querySelectorAll('[data-goto]'), function (b) {
        b.addEventListener('click', function () {
          openProject(b.getAttribute('data-goto'));
        });
      });
    });
  });

  boot();
}());
</script>"""


def main() -> int:
    html_out = build_pages.SHELL.replace("@@NAV@@", build_pages.NAV)
    fields = {
        "TITLE": "SyMoNeuRaL Project — a workspace you and the local models share",
        "DESC": ("Projects, work items, file references and session history, held on this "
                 "machine. CPU only, so it answers while the GPU is busy."),
        "ICON": "/assets/brand/mark-64.png",
        "EYEBROW": "Live surface · CPU",
        "HEADING": "A workspace you and the models share.",
        "LEDE": ("Somewhere to keep what you are working on across sessions — the projects, "
                 "what is left to do, the files each one touches and what happened last "
                 "time. It owns no weights and never queues for the card, which is the "
                 "point: the moment you most want to write down what you were doing is the "
                 "moment the GPU is busy for three hours."),
        "BODY": body(),
        "SCRIPT": f"<style>{CSS}</style>\n{SCRIPT.replace('@@API@@', API)}",
    }
    for key, value in fields.items():
        html_out = html_out.replace(f"@@{key}@@", value)
    # A leftover marker means the shell grew a field this generator does not fill, which
    # would ship the literal '@@SOMETHING@@' to a visitor.
    assert "@@" not in html_out, "unsubstituted placeholder left in the page"
    # Opt in to the application shell: no marketing hero above the workspace, and the
    # test-bench callout relocated out of it into a disclosure below the footer. This is a
    # CALL rather than a new `@@...@@` in the shared SHELL, which is the whole reason it is
    # shaped this way -- a placeholder added to SHELL would have broken the assert two lines
    # above on a correct page, which is exactly what `@@PAGECSS@@` did here once already.
    html_out = build_pages.appify(html_out)
    # The <main> landmark and the static data-family, from the one authored map in
    # tools/lib/page_families.py. Opted into the same way `appify` is, for the reason its
    # comment gives: a shared shell cannot grow a new placeholder without breaking
    # every consumer that substitutes its own field dict.
    html_out = build_pages.landmark(html_out, "project.html")
    assert "text-overflow" not in html_out, "an ellipsis rule reached the page"
    (SITE / "project.html").write_text(html_out)
    print("  project.html")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
