/* SyMoNeuRaL Coder — the page script.
 *
 * A separate file rather than an inline block, per his standing instruction on the app pages
 * ("Make sure to update the applications to be static with js css and html").
 *
 * Everything this file renders is a reading taken from this box. Where a reading is absent it
 * renders an em dash in dim type and NEVER a `false` -- "not asked yet" and "asked, and the
 * answer is no" are different facts, and a gate panel that showed four red crosses before the
 * first fetch resolved would be reporting an answer it does not have. That is the same rule
 * live.js states for dropped-frame counts and the same one the progress page follows when a
 * task with no checks reads `—` and never `0%`.
 *
 * THE TOKEN IS NOT IN THIS FILE AND MUST NEVER BE. `backend/apps/coder` gates on a token, and
 * the server process reads it from its own environment, uses it in-process and does not send
 * it here. A page that held the credential would mean the token in a URL, in localStorage, or
 * committed into this repository's own HTML, and a credential that has been displayed is
 * spent. If you find yourself adding an input for it, the design has gone wrong.
 */
(function () {
  'use strict';

  var $ = function (id) { return document.getElementById(id); };

  var lamp    = $('cd-lamp');
  var say     = $('cd-say');
  var headSt  = $('cd-headstate');
  var headLed = document.querySelector('#cd-head s');
  var listEl  = $('cd-list');
  var listSay = $('cd-listsay');
  var pathEl  = $('cd-path');
  var upBtn   = $('cd-up');
  var fileEl  = $('cd-file');

  var cwd = '.';           // the directory currently listed, as the API reports it
  var live = false;        // did /local/coder/status answer ok? nothing else runs until it does

  // ---- honest formatters ---------------------------------------------------------------

  // `null`/`undefined` is "not measured"; `false` is a measurement. They must not render the
  // same way, which is why this is a function and not an inline `||` -- `false || '—'` would
  // collapse exactly the distinction the panel exists to show.
  function put(id, value, cls) {
    var el = $(id);
    if (!el) return;
    if (value === null || value === undefined || value === '') {
      el.textContent = '—';
      el.className = 'cd-none';
      return;
    }
    el.textContent = String(value);
    el.className = cls || '';
  }

  // A gate reading. `good` says which direction is the permissive one, because it is not the
  // same for every gate: `enabled` and `token_set` being true is the working state, and
  // `allow_remote` being true is the one an operator should notice. Green is never decoration
  // here -- it means "this predicate is in the state that lets the surface answer".
  function gate(id, value, good) {
    if (value === null || value === undefined) { put(id, null); return; }
    put(id, value ? 'yes' : 'no', value === good ? 'cd-yes' : 'cd-no');
  }

  function bytes(n) {
    if (n === null || n === undefined) return null;
    if (n < 1024) return n + ' B';
    var u = ['KB', 'MB', 'GB', 'TB'], i = -1, v = n;
    do { v /= 1024; i++; } while (v >= 1024 && i < u.length - 1);
    return (v >= 10 ? Math.round(v) : Math.round(v * 10) / 10) + ' ' + u[i];
  }

  // Both timestamp fields this API returns are ISO-8601 strings, not epoch seconds:
  // `_journal` writes datetime.now(timezone.utc).isoformat(), and `history` composes its
  // `when` from the version tag. Passing either through `new Date(n * 1000)` yields Invalid
  // Date, which renders as the literal text "Invalid Date" -- a value that looks like a
  // reading and is not one. An unparseable stamp renders as nothing at all instead.
  function when(iso) {
    if (!iso) return '';
    var d = new Date(iso);
    return isNaN(d.getTime()) ? '' : d.toLocaleString();
  }

  function setLamp(state, headline) {
    lamp.className = 'cd-lamp' + (state ? ' is-' + state : '');
    if (headLed) headLed.className = state === 'on' ? 'is-on' : '';
    headSt.textContent = headline;
  }

  function refuse(heading, sentence, fix) {
    $('cd-refuse-h').textContent = heading;
    $('cd-refuse-p').textContent = sentence;
    var f = $('cd-refuse-fix');
    if (fix) { f.textContent = fix; f.hidden = false; } else { f.hidden = true; }
    $('cd-refuse').hidden = false;
  }
  function clearRefusal() { $('cd-refuse').hidden = true; }

  // ---- the transport --------------------------------------------------------------------

  // `/local/*` is refused off-box by the API's own peer check and is not delegated by Caddy,
  // so a visitor on the public site gets a 404 from the static file server and never reaches
  // this process at all. That is the designed outcome, not a fault, and it is reported as a
  // reading rather than as an error -- which is also why a non-200 is handed back as a value
  // instead of thrown.
  function get(path) {
    return fetch(path, { headers: { 'Accept': 'application/json' }, cache: 'no-store' })
      .then(function (r) {
        return r.text().then(function (body) {
          var data = null;
          try { data = JSON.parse(body); } catch (e) { /* not JSON: 404 from disk, usually */ }
          return { status: r.status, data: data };
        });
      })
      .catch(function (e) { return { status: 0, data: null, err: String(e) }; });
  }

  // ---- status ---------------------------------------------------------------------------

  function loadStatus() {
    return get('/local/coder/status').then(function (res) {
      var d = res.data;

      if (res.status === 0) {
        setLamp('off', 'unreachable');
        say.textContent = 'This page could not reach the machine it is meant to be reading.';
        refuse('No answer from the box',
               'The request for /local/coder/status did not complete. ' +
               (res.err || '') , 'If the API is not running, start it with ' +
               'scripts/symoneural.sh on and reload.');
        return;
      }

      // 404 with no JSON body is the public case: either Caddy served it off disk because
      // /local/* is deliberately not delegated, or the API's peer check refused a request
      // that did not come from a process on this machine. It answers 404 rather than 403 on
      // purpose -- a 403 would confirm to a remote caller that this box has a private
      // surface here at all.
      if (res.status === 404 && !d) {
        setLamp('off', 'not available here');
        say.textContent = 'The workspace surface is not reachable from this address.';
        refuse('This page is not being served by the box',
               'The reads this page makes are local-only by design: they are not proxied to ' +
               'the internet and the API refuses them from any peer that is not this ' +
               'machine. From the public site the tree, the files and the journal are all ' +
               'unreachable, and that is the intended behaviour rather than an outage.',
               'To use it, open it on the machine itself at ' +
               // /livestack/coder, not /live-stack/coder. Both are served and neither
               // redirects, but 2026-08-22 made the unhyphenated form the ONLY one this
               // site publishes -- one spelling in front of a person, two answering.
               'http://127.0.0.1:8800/livestack/coder');
        return;
      }

      if (!d) {
        setLamp('off', 'unreadable answer');
        say.textContent = 'The box answered, but not with a reading this page can render.';
        refuse('HTTP ' + res.status + ', and not JSON',
               'Something is answering /local/coder/status that is not this API.');
        return;
      }

      // The gate panel renders on EVERY answer, including a refusal. That is the whole
      // reason the endpoint reports the four predicates separately: authorize() returns the
      // first refusal and stops, so an operator told only "surface disabled" would switch the
      // flag on and be moved straight to the next closed gate with no warning it was there.
      var g = d.gates || {};
      var m = d.mount || {};
      gate('cd-r-enabled', g.enabled, true);
      gate('cd-r-token', g.token_set, true);
      gate('cd-r-remote', g.allow_remote, false);

      if (m.peer) {
        put('cd-r-peer', m.peer + (g.peer_loopback ? ' · loopback' : ' · not loopback'),
            g.peer_loopback ? 'cd-yes' : 'cd-no');
      } else {
        put('cd-r-peer', null);
      }
      put('cd-r-ws', d.workspace || null);

      if (m.read_only) {
        $('cd-rosay').firstChild.textContent =
          'This surface serves reads over ' + (m.prefix || '/local/coder') + '. ';
      }

      if (d.ok) {
        live = true;
        clearRefusal();
        setLamp('on', 'reading');
        put('cd-r-surface', 'answering', 'cd-yes');
        say.textContent = 'The workspace surface answered. Everything below is read off this machine.';
        return loadDir('.');
      }

      // A refusal, which is a normal configuration and not a fault: the surface ships off.
      setLamp('off', 'refused');
      put('cd-r-surface', 'refused', 'cd-no');
      say.textContent = 'The box answered, and the answer is no. Which gate said so is below.';

      var fix = [];
      if (g.enabled === false) fix.push('SYMONEURAL_CODER_ENABLED=1');
      if (g.token_set === false) fix.push('SYMONEURAL_CODER_TOKEN=<a value only this box holds>');
      refuse('The surface refused the read',
             String(d.error || 'no reason was given'),
             fix.length
               ? 'Set ' + fix.join(' and ') + ' in the API’s environment and restart it. ' +
                 'Every gate is shown above rather than only the first, so turning one on ' +
                 'does not just move you to the next closed one.'
               : '');
      listSay.textContent = 'Not listed — the surface refused the read.';
    });
  }

  // ---- the tree --------------------------------------------------------------------------

  function loadDir(path) {
    listSay.textContent = 'Reading…';
    return get('/local/coder/ls?path=' + encodeURIComponent(path)).then(function (res) {
      var d = res.data;
      listEl.replaceChildren();
      $('cd-trunc').hidden = true;

      if (!d || !d.ok) {
        listSay.textContent = d && d.error
          ? 'Refused: ' + d.error
          : 'The listing could not be read (HTTP ' + res.status + ').';
        return;
      }

      cwd = d.path;
      pathEl.textContent = d.path;
      upBtn.disabled = (d.path === '.' || d.path === '');

      var denied = 0;
      d.entries.forEach(function (e) {
        var li = document.createElement('li');
        li.className = 'cd-row' + (e.denied ? ' is-denied' : '');

        // A denied entry is listed and FLAGGED, never omitted. coder.list_dir's own docstring
        // argues for it and this is the visual half of the same decision: the operator should
        // be able to see that a refused file EXISTS, rather than be shown a tree that quietly
        // is not the tree on disk. Silently dropping it would also teach them there is no
        // denylist, so the first time they wondered where a file went they would go hunting a
        // bug instead of finding a rule.
        if (e.denied) {
          denied++;
          var nm = document.createElement('span');
          nm.className = 'cd-name';
          nm.textContent = e.name;
          li.appendChild(nm);
        } else if (e.type === 'dir') {
          var b = document.createElement('button');
          b.type = 'button';
          b.className = 'cd-name';
          b.textContent = e.name + '/';
          b.addEventListener('click', function () {
            loadDir(cwd === '.' ? e.name : cwd + '/' + e.name);
          });
          li.appendChild(b);
        } else if (e.type === 'file') {
          var fb = document.createElement('button');
          fb.type = 'button';
          fb.className = 'cd-name';
          fb.textContent = e.name;
          fb.addEventListener('click', function () {
            openFile(cwd === '.' ? e.name : cwd + '/' + e.name);
          });
          li.appendChild(fb);
        } else {
          var sp = document.createElement('span');
          sp.className = 'cd-name';
          sp.textContent = e.name;
          li.appendChild(sp);
        }

        var kind = document.createElement('span');
        kind.className = 'cd-kind';
        kind.textContent = e.type;
        li.appendChild(kind);

        if (e.bytes !== null && e.bytes !== undefined) {
          var sz = document.createElement('span');
          sz.className = 'cd-size';
          sz.textContent = bytes(e.bytes);
          li.appendChild(sz);
        }

        if (e.denied) {
          var why = document.createElement('span');
          why.className = 'cd-deny';
          // The reason is rendered in full and wraps. It is never trimmed: a refusal an
          // operator cannot read is a refusal they cannot act on.
          why.textContent = 'refused — ' + (e.reason || 'covered by the denylist');
          li.appendChild(why);
        }

        listEl.appendChild(li);
      });

      listSay.textContent = d.entries.length
        ? d.entries.length + ' ' + (d.entries.length === 1 ? 'entry' : 'entries') +
          (denied ? ', ' + denied + ' refused and shown as such' : '')
        : 'This directory is empty.';

      if (d.truncated) {
        var t = $('cd-trunc');
        t.textContent = 'The listing stopped at the entry cap, so this is not the whole ' +
                        'directory. The cap is applied during the walk rather than after it.';
        t.hidden = false;
      }
    });
  }

  function up() {
    if (cwd === '.' || cwd === '') return;
    var i = cwd.lastIndexOf('/');
    loadDir(i === -1 ? '.' : cwd.slice(0, i));
  }

  // ---- the reader ---------------------------------------------------------------------

  function openFile(path) {
    fileEl.hidden = false;
    $('cd-filemeta').textContent = 'Reading ' + path + '…';
    $('cd-filetext').textContent = '';
    $('cd-hist').replaceChildren();
    $('cd-histsay').textContent = '';

    get('/local/coder/file?path=' + encodeURIComponent(path)).then(function (res) {
      var d = res.data;
      if (!d || !d.ok) {
        // A refused or unreadable file says why, in the reader, rather than leaving the last
        // file's contents on screen under a new name -- which would be the worst possible
        // outcome on a page whose whole claim is that it shows what is on the disk.
        $('cd-filemeta').textContent = d && d.error
          ? path + ' — refused: ' + d.error
          : path + ' — could not be read (HTTP ' + res.status + ').';
        return;
      }
      $('cd-filemeta').innerHTML = '';
      var b = document.createElement('b');
      b.textContent = d.path;
      $('cd-filemeta').appendChild(b);
      $('cd-filemeta').appendChild(document.createTextNode(' · ' + bytes(d.bytes)));
      $('cd-filetext').textContent = d.text;
      loadHistory(d.path);
    });
  }

  function loadHistory(path) {
    get('/local/coder/history?path=' + encodeURIComponent(path)).then(function (res) {
      var d = res.data;
      var ul = $('cd-hist');
      ul.replaceChildren();
      if (!d || !d.ok) {
        $('cd-histsay').textContent = '';
        return;
      }
      var vs = d.versions || [];
      $('cd-histsay').textContent = vs.length
        ? 'Rollback snapshots this module holds for this file: ' + vs.length
        : 'This module holds no rollback snapshots for this file.';
      vs.forEach(function (v) {
        var li = document.createElement('li');
        var t = document.createElement('b');
        t.textContent = v.version || '';
        li.appendChild(t);
        var meta = [];
        // `absent` is a real snapshot kind, not a missing reading: it records that the file
        // did not exist at that version, which is what makes a delete undoable. It carries a
        // null byte count on purpose and must not be rendered as a zero-byte file.
        if (v.absent) meta.push('file did not exist');
        else if (v.bytes !== null && v.bytes !== undefined) meta.push(bytes(v.bytes));
        if (v.when) meta.push(when(v.when));
        if (meta.length) li.appendChild(document.createTextNode(' · ' + meta.join(' · ')));
        ul.appendChild(li);
      });
    });
  }

  // ---- the journal ---------------------------------------------------------------------

  var journalRead = false;

  function loadJournal() {
    if (journalRead) return;
    journalRead = true;
    $('cd-jrnsay').textContent = 'Reading…';
    get('/local/coder/journal?n=50').then(function (res) {
      var d = res.data;
      var ul = $('cd-jrn');
      ul.replaceChildren();
      if (!d || !d.ok) {
        $('cd-jrnsay').textContent = d && d.error
          ? 'Refused: ' + d.error
          : 'The journal could not be read (HTTP ' + res.status + ').';
        journalRead = false;
        return;
      }
      var rows = d.records || [];
      $('cd-jrnsay').textContent = rows.length
        ? 'The last ' + rows.length + ' recorded ' + (rows.length === 1 ? 'action' : 'actions') + '.'
        : 'Nothing has been recorded in this workspace’s journal yet.';
      rows.forEach(function (r) {
        var li = document.createElement('li');
        var a = document.createElement('span');
        a.className = 'cd-act';
        a.textContent = r.action || 'action';
        li.appendChild(a);
        li.appendChild(document.createTextNode(' '));
        var p = document.createElement('b');
        p.textContent = r.path || '';
        li.appendChild(p);
        var ts = when(r.ts);
        if (ts) li.appendChild(document.createTextNode(' · ' + ts));
        ul.appendChild(li);
      });
    });
  }

  // ---- wiring ---------------------------------------------------------------------------

  upBtn.addEventListener('click', up);
  $('cd-reload').addEventListener('click', function () { if (live) loadDir(cwd); });
  $('cd-jrnwrap').addEventListener('toggle', function () {
    if ($('cd-jrnwrap').open && live) loadJournal();
  });

  loadStatus();
})();
