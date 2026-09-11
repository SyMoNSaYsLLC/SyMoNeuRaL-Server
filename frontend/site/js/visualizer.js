/* SyMoNeuRaL token visualizer — raw WebGL, no dependencies.
 *
 * A dim core (the card) with particles leaving it (tokens). It is driven by
 * `SymonVisualizer.setVelocity(tokensPerSecond)`, which the chat page calls from inside its
 * SSE reader.
 *
 * ---------------------------------------------------------------------------------------
 * THE HONESTY RULE APPLIES TO THIS FILE.
 *
 * `.claude/CLAUDE.md`: "No decorative status indicators. Every LED and gauge on the site
 * reflects a real reading; a fake activity light is the one dishonest pixel on a page
 * arguing for measurement."
 *
 * So this is not an ambient background animation. It emits a particle when a token actually
 * arrives and at the rate tokens are actually arriving, and when nothing is being generated
 * it visibly stops: emission goes to zero, the particles in flight finish their arcs and
 * expire, and the core sits at a low steady glow. An idle box looks idle. If you are tempted
 * to add a slow drift "so it does not look dead" -- that is the dishonest pixel, and the
 * page it sits on is arguing that its numbers are real.
 *
 * The rate passed in is the same measured figure the page prints under the answer: token
 * count over wall clock, timed on the card.
 * ---------------------------------------------------------------------------------------
 *
 * Failure is silent and total. No WebGL, no canvas, a shader that will not compile, or a
 * reader who prefers reduced motion, and the page is exactly as it was -- setVelocity stays
 * callable and does nothing, so no caller needs to feature-detect.
 */
(function () {
  'use strict';

  var MAX = 900;                 // hard cap on particles in flight
  var LIFE = 2.6;                // seconds a particle lives
  var ACCENT = [0.18, 0.88, 0.54];

  // The public surface, installed immediately and unconditionally. Every early return below
  // leaves these no-ops in place, which is what lets chat.html call setVelocity without
  // knowing whether any of this initialised.
  var api = {
    setVelocity: function () {},
    tick: function () {},
    available: false
  };
  window.SymonVisualizer = api;

  if (typeof document === 'undefined') return;

  // Motion here is decorative in the accessibility sense even though it is honest in the
  // data sense, so an explicit preference wins outright.
  var reduce = window.matchMedia && window.matchMedia('(prefers-reduced-motion: reduce)');
  if (reduce && reduce.matches) return;

  function start() {
    var canvas = document.createElement('canvas');
    canvas.id = 'symon-viz';
    // Never a child of `.cu`. That element is `display:grid` with an explicit
    // `grid-template-columns:230px minmax(0,1fr)` (symoneural.css:1677), so appending a
    // canvas inside it would create a third grid item and shift the whole chat layout.
    // Fixed positioning takes it out of flow entirely: no grid participates, no stylesheet
    // changes, nothing reflows.
    //
    // z-index:-1 rather than 0. `body` sets an opaque `background:var(--bg)`
    // (symoneural.css:63-64) and `html` sets none, so the body background propagates to the
    // viewport canvas and is painted as the root background -- which means a negative
    // z-index element paints ON TOP of it and is still visible, while a z-index:0 fixed
    // element would paint above the page's static text instead of behind it.
    canvas.setAttribute('aria-hidden', 'true');
    canvas.style.cssText =
      'position:fixed;inset:0;width:100%;height:100%;z-index:-1;pointer-events:none;';

    var gl = null;
    try {
      var opts = {alpha: true, antialias: false, premultipliedAlpha: false,
                  powerPreference: 'low-power'};
      gl = canvas.getContext('webgl', opts) || canvas.getContext('experimental-webgl', opts);
    } catch (e) { gl = null; }
    if (!gl) return;

    var prog = build(gl);
    if (!prog) return;

    document.body.insertBefore(canvas, document.body.firstChild);

    var loc = {
      pos:  gl.getAttribLocation(prog, 'a_pos'),
      life: gl.getAttribLocation(prog, 'a_life'),
      size: gl.getAttribLocation(prog, 'a_size'),
      res:  gl.getUniformLocation(prog, 'u_res'),
      dpr:  gl.getUniformLocation(prog, 'u_dpr'),
      col:  gl.getUniformLocation(prog, 'u_col'),
      dim:  gl.getUniformLocation(prog, 'u_dim')
    };

    // Interleaved [x, y, life, size] so one buffer and one bufferSubData covers a frame.
    var STRIDE = 4;
    var data = new Float32Array(MAX * STRIDE);
    var vx = new Float32Array(MAX), vy = new Float32Array(MAX);
    var count = 0;

    var buf = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, buf);
    gl.bufferData(gl.ARRAY_BUFFER, data.byteLength, gl.DYNAMIC_DRAW);

    var W = 0, H = 0, dpr = 1;
    function resize() {
      dpr = Math.min(window.devicePixelRatio || 1, 2);
      W = canvas.clientWidth; H = canvas.clientHeight;
      canvas.width = Math.max(1, Math.round(W * dpr));
      canvas.height = Math.max(1, Math.round(H * dpr));
      gl.viewport(0, 0, canvas.width, canvas.height);
    }
    resize();
    window.addEventListener('resize', resize, {passive: true});

    // --- state driven from outside ---------------------------------------------------
    var rate = 0;        // tokens/second, as measured by the server
    var budget = 0;      // fractional particles owed, so slow rates still emit correctly
    var glow = 0;        // 0..1, eased toward whether work is actually happening
    var last = 0;

    function origin() { return [W * 0.5, H * 0.42]; }

    function emit(n) {
      var o = origin();
      for (var k = 0; k < n && count < MAX; k++) {
        var a = Math.random() * Math.PI * 2;
        var speed = 46 + Math.random() * 92;
        var i = count++;
        data[i * STRIDE]     = o[0];
        data[i * STRIDE + 1] = o[1];
        data[i * STRIDE + 2] = 1;                          // life, 1 -> 0
        data[i * STRIDE + 3] = 1.6 + Math.random() * 2.6;  // size in CSS px
        vx[i] = Math.cos(a) * speed;
        vy[i] = Math.sin(a) * speed * 0.55;                // flattened, reads as a disc
      }
    }

    function step(dt) {
      // Emit at the measured rate. `budget` carries the fraction across frames, so 3 tok/s
      // at 60 fps still produces three particles a second rather than rounding to zero.
      if (rate > 0) {
        budget += rate * dt;
        var n = Math.floor(budget);
        if (n > 0) { budget -= n; emit(Math.min(n, 24)); }
      } else {
        budget = 0;
      }

      var decay = dt / LIFE;
      var w = 0;
      for (var i = 0; i < count; i++) {
        var b = i * STRIDE;
        var life = data[b + 2] - decay;
        if (life <= 0) continue;                 // dead: dropped by not copying it forward
        var x = data[b] + vx[i] * dt;
        var y = data[b + 1] + vy[i] * dt;
        vx[i] *= 0.982; vy[i] *= 0.982;          // drag, so they ease outward and settle
        var c = w * STRIDE;
        data[c] = x; data[c + 1] = y; data[c + 2] = life; data[c + 3] = data[b + 3];
        vx[w] = vx[i]; vy[w] = vy[i];
        w++;
      }
      count = w;

      // The core brightens while tokens are arriving and falls back when they stop. Eased
      // rather than binary so a pause between tokens does not strobe, but it does reach a
      // genuine floor: nothing generating means a dim core, not a pulsing one.
      var target = rate > 0 ? 1 : 0;
      glow += (target - glow) * Math.min(1, dt * 3.2);
    }

    function draw() {
      gl.clearColor(0, 0, 0, 0);
      gl.clear(gl.COLOR_BUFFER_BIT);
      gl.enable(gl.BLEND);
      gl.blendFunc(gl.SRC_ALPHA, gl.ONE);        // additive: overlapping tokens read brighter
      gl.useProgram(prog);
      gl.uniform2f(loc.res, W, H);
      gl.uniform1f(loc.dpr, dpr);
      gl.uniform3f(loc.col, ACCENT[0], ACCENT[1], ACCENT[2]);

      gl.bindBuffer(gl.ARRAY_BUFFER, buf);
      gl.enableVertexAttribArray(loc.pos);
      gl.enableVertexAttribArray(loc.life);
      gl.enableVertexAttribArray(loc.size);
      var S = STRIDE * 4;
      gl.vertexAttribPointer(loc.pos, 2, gl.FLOAT, false, S, 0);
      gl.vertexAttribPointer(loc.life, 1, gl.FLOAT, false, S, 8);
      gl.vertexAttribPointer(loc.size, 1, gl.FLOAT, false, S, 12);

      // The core, drawn as a single point from a scratch record past the live ones.
      var o = origin();
      var core = new Float32Array([o[0], o[1], 1, 22 + glow * 26]);
      gl.bufferSubData(gl.ARRAY_BUFFER, 0, core);
      gl.uniform1f(loc.dim, 0.05 + glow * 0.30);
      gl.drawArrays(gl.POINTS, 0, 1);

      if (count > 0) {
        gl.bufferSubData(gl.ARRAY_BUFFER, 0, data.subarray(0, count * STRIDE));
        gl.uniform1f(loc.dim, 0.42);
        gl.drawArrays(gl.POINTS, 0, count);
      }
    }

    function frame(now) {
      var dt = last ? Math.min((now - last) / 1000, 0.05) : 0.016;
      last = now;
      step(dt);
      draw();
      // Keep running only while there is something to show. Once the rate is zero, the last
      // particle has expired and the core has reached its floor, the loop stops entirely --
      // an idle tab should not hold a GPU context awake redrawing an unchanging frame.
      if (rate > 0 || count > 0 || glow > 0.02) {
        raf = requestAnimationFrame(frame);
      } else {
        raf = 0; last = 0;
        draw();
      }
    }

    var raf = 0;
    function wake() { if (!raf) raf = requestAnimationFrame(frame); }

    api.setVelocity = function (tokensPerSecond) {
      var v = Number(tokensPerSecond);
      rate = (isFinite(v) && v > 0) ? Math.min(v, 400) : 0;
      wake();
    };
    // One token landed, rate unknown. Used for the per-delta call, where the honest signal
    // is "a token arrived now" rather than an average that is not measured until the end.
    api.tick = function () { emit(1); wake(); };
    api.available = true;

    // A backgrounded tab gets no rAF; without this the elapsed wall time reappears as one
    // enormous dt and every particle jumps across the screen on return.
    document.addEventListener('visibilitychange', function () {
      if (document.hidden) { rate = 0; } else { last = 0; wake(); }
    });

    wake();
  }

  function build(gl) {
    // u_res is in CSS pixels and u_dpr scales the sprite, deliberately kept as two uniforms.
    // Positions are computed on the CPU in CSS pixels, so mixing device pixels into u_res
    // would offset every particle by the device ratio on exactly the machines that have one.
    var vs =
      'attribute vec2 a_pos; attribute float a_life; attribute float a_size;' +
      'uniform vec2 u_res; uniform float u_dpr; varying float v_life;' +
      'void main(){' +
      '  vec2 c = a_pos / u_res * 2.0 - 1.0;' +             // CSS px -> clip space
      '  gl_Position = vec4(c.x, -c.y, 0.0, 1.0);' +        // y is flipped: CSS grows down
      '  gl_PointSize = a_size * u_dpr;' +
      '  v_life = a_life;' +
      '}';
    var fs =
      'precision mediump float; varying float v_life;' +
      'uniform vec3 u_col; uniform float u_dim;' +
      'void main(){' +
      // Round the square point sprite off and fall away from the middle, so there are no
      // visible boxes and the core reads as a glow rather than a tile.
      '  vec2 d = gl_PointCoord - vec2(0.5);' +
      '  float r = length(d) * 2.0;' +
      '  if (r > 1.0) discard;' +
      '  float a = pow(1.0 - r, 2.2) * v_life * u_dim;' +
      '  gl_FragColor = vec4(u_col * a, a);' +
      '}';

    function sh(type, src) {
      var s = gl.createShader(type);
      gl.shaderSource(s, src);
      gl.compileShader(s);
      // Deliberately not thrown. A driver that will not compile this is a reason to have no
      // visualizer, not a reason to break the chat page it sits behind.
      if (!gl.getShaderParameter(s, gl.COMPILE_STATUS)) return null;
      return s;
    }
    var v = sh(gl.VERTEX_SHADER, vs), f = sh(gl.FRAGMENT_SHADER, fs);
    if (!v || !f) return null;
    var p = gl.createProgram();
    gl.attachShader(p, v); gl.attachShader(p, f); gl.linkProgram(p);
    if (!gl.getProgramParameter(p, gl.LINK_STATUS)) return null;
    return p;
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', start);
  } else {
    start();
  }
})();
