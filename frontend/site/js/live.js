/* SyMoNeuRaL Live — the page script.
 *
 * A separate file rather than an inline block, per his standing instruction on the app pages
 * ("Make sure to update the applications to be static with js css and html"), and #96 puts two
 * `ngrep` checks on live.html to keep it that way.
 *
 * Everything this file renders is a reading. Where a reading is absent it renders an em dash in
 * dim type and NEVER a zero -- a dropped-frame count of `0` before anything has connected is a
 * decorative gauge, which is the one thing this site does not put on a page. `obs.py` seeds its
 * whole reading table with `null` for exactly this reason; this file's job is to not undo that.
 */
(function () {
  'use strict';

  var $ = function (id) { return document.getElementById(id); };

  var video   = $('lv-video');
  var player  = $('lv-player');
  var lamp    = $('lv-lamp');
  var say     = $('lv-say');
  var nowEl   = $('lv-now');
  var headSt  = $('lv-headstate');
  var headLed = document.querySelector('#lv-head s');
  var vodsEl  = $('lv-vods');
  var vodSay  = $('lv-vodsay');
  var failEl  = $('lv-fail');

  var hls = null;          // the live hls.js instance, if any
  var playing = null;      // the playlist name currently attached
  var engine = '';         // which player is actually running, for the failure text

  // ---- small honest formatters --------------------------------------------------------

  // The one rule: `null` and `undefined` are "not measured", `0` is a measurement. They must
  // not render the same way. `0 || '—'` would collapse them, which is why this is a function
  // and not an inline `||`.
  function put(id, value, suffix) {
    var el = $(id);
    if (!el) return;
    if (value === null || value === undefined || value === '') {
      el.textContent = '—';
      el.className = 'lv-none';
      return;
    }
    el.textContent = String(value) + (suffix || '');
    el.className = '';
  }

  function hhmmss(seconds) {
    if (seconds === null || seconds === undefined) return null;
    var s = Math.max(0, Math.round(seconds));
    var h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), r = s % 60;
    var pad = function (n) { return (n < 10 ? '0' : '') + n; };
    return (h ? h + ':' + pad(m) : m) + ':' + pad(r);
  }

  function when(epoch) {
    if (!epoch) return '';
    try { return new Date(epoch * 1000).toLocaleString(); } catch (e) { return ''; }
  }

  function showFail(heading, sentence, technical) {
    $('lv-failh').textContent = heading;
    $('lv-failp').textContent = sentence;
    var d = $('lv-faild');
    if (technical) { $('lv-failc').textContent = technical; d.hidden = false; }
    else { d.hidden = true; }
    failEl.hidden = false;
  }
  function clearFail() { failEl.hidden = true; }

  // ---- playback -----------------------------------------------------------------------

  // A rejected play() is not a fault worth reporting: autoplay policy rejects here, and so
  // does an undecodable codec, and the second one arrives again as a fatal hls.js error which
  // IS reported. Same reasoning as site/streamer.html's safePlay.
  function safePlay() {
    var p = video.play();
    if (p && p.catch) p.catch(function () {});
  }

  function detach() {
    if (hls) { hls.destroy(); hls = null; }
    playing = null;
  }

  function attach(url, label, isLive) {
    if (playing === url) return;          // already showing it; re-attaching restarts playback
    detach();
    playing = url;
    clearFail();
    player.hidden = false;
    nowEl.innerHTML = '';
    nowEl.appendChild(document.createTextNode(isLive ? 'Live now · ' : 'Recording · '));
    var b = document.createElement('b');
    b.textContent = label;
    nowEl.appendChild(b);

    // hls.js FIRST, and the browser's own HLS only where hls.js will not run.
    //
    // This order is not a preference and it is not arbitrary. MEASURED in this repo and
    // written up at site/streamer.html:1989: Chrome returns **'maybe'** from
    // canPlayType('application/vnd.apple.mpegurl') -- a truthy string -- so the obvious
    // `if (canPlayType(...)) native; else hlsjs;` takes the NATIVE branch on every Chrome
    // visit and then plays nothing at all, with no error anywhere. Getting this backwards
    // already cost streamer.html a round; the fix is not being re-litigated here.
    //
    // Safari is what the fallback exists for: it has no MSE-based path, it does play HLS
    // natively, and there Hls.isSupported() is false so it falls through correctly.
    if (window.Hls && window.Hls.isSupported()) { hlsPlay(url, isLive); return; }
    if (video.canPlayType('application/vnd.apple.mpegurl')) {
      engine = 'the browser’s own HLS';
      video.src = url;
      safePlay();
      return;
    }
    showFail('This browser cannot play HLS.',
             'hls.js is vendored at /hls.js and either did not load or is not supported '
             + 'here, and this browser has no HLS support of its own. The stream itself is '
             + 'fine — Chrome, Firefox, Edge and Safari all play it.', null);
  }

  function hlsPlay(url, isLive) {
    engine = 'hls.js ' + (window.Hls.version || '');
    hls = new window.Hls({
      lowLatencyMode: false,        // LL-HLS needs partial segments; OBS's ffmpeg makes none
      // OBS is configured for 2-second segments with a matching 120-frame keyframe interval
      // (backend/apps/live/README.md), so one segment back from the live edge is ~2 s of
      // latency rather than the ~6 s the library's default of 3 would cost. streamer.html
      // documents the same change saving 31 s against a provider with a 10-second GOP; here
      // the segments are genuinely short because we own the encoder settings.
      liveSyncDurationCount: 1,
      liveMaxLatencyDurationCount: 6,
      backBufferLength: 30,         // a live stream needs no rewind buffer held in RAM
      startFragPrefetch: true,
      manifestLoadingMaxRetry: 4,
      manifestLoadingRetryDelay: 250,
      levelLoadingRetryDelay: 250,
      fragLoadingRetryDelay: 250
    });
    hls.loadSource(url);
    hls.attachMedia(video);
    hls.on(window.Hls.Events.MANIFEST_PARSED, function () { safePlay(); });
    hls.on(window.Hls.Events.ERROR, function (_e, d) {
      if (!d || !d.fatal) return;
      var tech = engine + ': ' + d.type + ' / ' + d.details
               + (d.response && d.response.code ? ' (HTTP ' + d.response.code + ')' : '');
      // A live stream ending mid-playback is the expected case, not a fault: OBS stopped and
      // the next segment the player asked for was never written. Saying "playback failed"
      // there would be wrong, and would train the operator to ignore this box.
      if (isLive) {
        showFail('The stream stopped.',
                 'The player asked for the next segment and it was not there, which is what '
                 + 'the end of a stream looks like from here. If it was not meant to end, OBS '
                 + 'stopped recording — the recording so far is listed below and is '
                 + 'watchable.', tech);
      } else {
        showFail('Playback stopped.',
                 'The player could not fetch the next part of this recording. The files are '
                 + 'on the box; this is between this browser and this machine.', tech);
      }
      detach();
    });
  }

  // ---- the live half ------------------------------------------------------------------

  function renderUnservable(list) {
    // Shown, never silently skipped. A recording OBS wrote perfectly well that this API will
    // not put in a URL -- a space in the filename, almost always -- is invisible on the site
    // and absent from every log unless the page says so. That is #94's shape exactly: green
    // everywhere, dead surface.
    (list || []).forEach(function (u) {
      var d = document.createElement('div');
      d.className = 'lv-bad';
      d.appendChild(document.createTextNode('A recording named '));
      var c = document.createElement('code');
      c.textContent = u.name;
      d.appendChild(c);
      d.appendChild(document.createTextNode(' cannot be served: ' + (u.detail || 'unusable name')
        + '. Change OBS’s Filename Formatting to %CCYY-%MM-%DD_%hh-%mm-%ss — the '
        + 'default contains a space.'));
      vodsEl.appendChild(d);
    });
  }

  function applyState(j) {
    if (!j.enabled) {
      lamp.className = 'lv-lamp';
      headSt.textContent = 'off';
      if (headLed) headLed.className = '';
      say.textContent = j.detail || 'The live surface is switched off on this box.';
      player.hidden = true;
      detach();
      return;
    }

    var live = j.live;
    var obs = j.obs || {};

    if (live) {
      lamp.className = 'lv-lamp is-on';
      headSt.textContent = 'live';
      if (headLed) headLed.className = 'on';
      say.textContent = 'Live now — recording since ' + when(live.started) + '.';
      attach(live.playlist_url, live.stem, true);
      put('lv-r-state', 'live');
      put('lv-r-dur', hhmmss(live.seconds));
      put('lv-r-segs', live.segments);
    } else {
      lamp.className = 'lv-lamp';
      headSt.textContent = 'idle';
      if (headLed) headLed.className = '';
      say.textContent = 'Nothing is being recorded right now. Anything already recorded is '
                      + 'below and plays in this same window.';
      put('lv-r-state', 'idle');
      put('lv-r-dur', null);
      put('lv-r-segs', null);
      // Deliberately does NOT tear down playback: if a visitor is part-way through a
      // recording, a poll finding no live stream must not yank the video out from under them.
      if (playing === null) player.hidden = true;
    }

    put('lv-r-fps', obs.fps === null || obs.fps === undefined ? null : obs.fps.toFixed(1));
    put('lv-r-drop', obs.output_skipped);
    // The bridge is the one reading that explains itself when absent, because "not
    // configured" is a supported state here and not a fault -- the video needs no password.
    put('lv-r-bridge', obs.connected ? ('connected · obs-websocket ' + (obs.obs_version || '?'))
                                     : (obs.detail || null));

    // OBS says it is recording and no playlist is being written. That is a real and likely
    // misconfiguration -- the recording output is pointed somewhere other than
    // backend/output/live -- and it is the kind of thing that otherwise looks like "the site
    // is broken" for weeks. /api/live/state reports both sides precisely so this is visible.
    if (!live && obs.recording === true) {
      showFail('OBS is recording, but not to this box’s live directory.',
               'The bridge reports an active recording and no playlist is being written to '
               + 'backend/output/live. The recording output is almost certainly still set to '
               + 'Standard, or is pointed at another folder. backend/apps/live/README.md has '
               + 'the exact settings.', null);
    }
  }

  function renderVods(j) {
    vodsEl.innerHTML = '';
    var items = (j && j.items) || [];
    if (!items.length) {
      vodSay.textContent = 'Nothing recorded yet. When a stream ends it appears here '
                         + 'immediately — the live playlist and the recording are the '
                         + 'same file.';
      return;
    }
    vodSay.textContent = items.length + (items.length === 1 ? ' recording' : ' recordings')
                       + ', newest first.';
    items.forEach(function (v) {
      var li = document.createElement('li');
      li.className = 'lv-vod' + (v.state === 'abandoned' ? ' is-stale' : '');

      var btn = document.createElement('button');
      btn.type = 'button';
      btn.textContent = 'Watch';
      btn.addEventListener('click', function () {
        attach(v.playlist_url, v.stem, false);
        video.scrollIntoView({block: 'nearest'});
      });
      li.appendChild(btn);

      var t = document.createElement('time');
      t.dateTime = new Date(v.started * 1000).toISOString();
      t.textContent = when(v.started);
      li.appendChild(t);

      var len = document.createElement('span');
      len.className = 'lv-len';
      len.textContent = hhmmss(v.seconds) + ' · ' + v.segments + ' segments';
      li.appendChild(len);

      if (v.state === 'abandoned') {
        var w = document.createElement('span');
        w.className = 'lv-warn';
        // Named for what it is. This is what OBS leaves behind when it is killed rather than
        // stopped, and the honest thing to say is that it plays but may be short, not to
        // present it as a complete recording.
        w.textContent = 'ended without a trailer — plays, may be incomplete';
        li.appendChild(w);
      }
      vodsEl.appendChild(li);
    });
  }

  // ---- polling ------------------------------------------------------------------------

  function poll() {
    fetch('/api/live/state', {cache: 'no-store'})
      .then(function (r) { return r.json(); })
      .then(function (j) {
        applyState(j);
        return fetch('/api/live/vods', {cache: 'no-store'}).then(function (r) { return r.json(); })
          .then(function (v) { renderVods(v); renderUnservable(j.unservable); });
      })
      .catch(function (err) {
        // The API being unreachable is a different fact from nothing being live, and the page
        // has to be able to tell them apart or a dead box reads as a quiet evening.
        lamp.className = 'lv-lamp is-stale';
        headSt.textContent = 'unreachable';
        say.textContent = 'Could not reach this box’s API, so whether anything is '
                        + 'streaming is unknown.';
        vodSay.textContent = '';
        showFail('The API did not answer.',
                 'This page could not load /api/live/state. The stream may well be running; '
                 + 'this box’s API is what is not answering.', String(err && err.message || err));
      });
  }

  poll();
  // 5 s. Segments are 2 s, so this notices a stream starting within about three of them,
  // and /api/live/state stats every segment on disk -- polling it per second would put that
  // walk on a loop for every open tab.
  setInterval(poll, 5000);
})();
