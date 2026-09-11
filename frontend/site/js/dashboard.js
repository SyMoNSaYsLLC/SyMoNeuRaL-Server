/* SyMoNeuRaL Dashboard.
 *
 * Reads /api/metrics/* and renders it. NO TOKEN, no headers -- plain fetch, per the owner's
 * 2026-09-11 decision. Every value arrives as {value, unit, source} and the source is
 * rendered beside the number, because a figure whose provenance you cannot see is a figure
 * you have to believe.
 *
 * `value === null` means COULD NOT BE READ and renders as a dash with the reason. It never
 * renders as 0: on a status page "0 GB free" and "we could not ask" look identical and mean
 * opposite things.
 *
 * Two poll rates. /live is the card, host and last request -- cheap, polled. /static is the
 * fabric registry read and an AST walk of 121 test files, ~0.5 s, fetched once. Polling that
 * every two seconds would spend half a core rendering numbers that cannot change.
 */
'use strict';

const $ = (id) => document.getElementById(id);
const LIVE_MS = 2000;

async function getJSON(path) {
  const r = await fetch(path, { headers: { 'Accept': 'application/json' } });
  if (!r.ok) throw new Error(path + ' -> ' + r.status);
  return r.json();
}

/* ---- rendering a Reading ------------------------------------------------------------- */

function fig(reading, label) {
  if (!reading) return '';
  const na = reading.value === null || reading.value === undefined;
  const v = na ? '—' : (typeof reading.value === 'number'
    ? reading.value.toLocaleString(undefined, { maximumFractionDigits: 2 })
    : String(reading.value));
  return `<div class="fig">
      <div class="v${na ? ' na' : ''}">${esc(v)}${reading.unit && !na
        ? `<span class="u">${esc(reading.unit)}</span>` : ''}</div>
      <div class="k">${esc(label)}</div>
      <div class="src" title="${esc(reading.source || '')}">${esc(reading.source || '')}</div>
    </div>`;
}

function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, (c) =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

function bar(pct, label) {
  const p = Math.max(0, Math.min(100, pct || 0));
  const cls = p > 90 ? 'hot' : p > 75 ? 'warn' : '';
  return `<div class="k" style="margin-top:10px">${esc(label)} — ${p.toFixed(0)}%</div>
          <div class="bar"><i class="${cls}" style="width:${p}%"></i></div>`;
}

/* ---- live half ----------------------------------------------------------------------- */

function renderCard(c) {
  $('gpu-name').textContent = c['name'] && c['name'].value ? c['name'].value : '';
  $('gpu-figs').innerHTML = [
    fig(c['memory.used'], 'VRAM used'), fig(c['memory.free'], 'VRAM free'),
    fig(c['utilization.gpu'], 'utilisation'), fig(c['temperature.gpu'], 'temperature'),
    fig(c['power.draw'], 'power draw'), fig(c['clocks.sm'], 'SM clock'),
  ].join('');
  const used = c['memory.used'];
  const tot = c['memory.total'];
  let html = '';
  if (used && tot && used.value != null && tot.value) {
    html += bar(100 * used.value / tot.value, `VRAM ${used.value} / ${tot.value} MiB`);
  }
  const pw = c['power.draw'], pl = c['power.limit'];
  if (pw && pl && pw.value != null && pl.value) {
    html += bar(100 * pw.value / pl.value, `power ${pw.value} / ${pl.value} W`);
  }
  $('gpu-bars').innerHTML = html;
}

function renderHost(h) {
  const cpu = h.cpu || {}, mem = h.memory || {}, disk = h.disk || {}, load = h.load || {};
  $('cpu-name').textContent = cpu.model && cpu.model.value ? cpu.model.value : '';
  $('cpu-figs').innerHTML = [
    fig(cpu.percent, 'utilisation'), fig(cpu.threads, 'threads'),
    fig(load.load1, 'load 1m'), fig(load.load15, 'load 15m'),
  ].join('');
  const per = cpu.per_core && Array.isArray(cpu.per_core.value) ? cpu.per_core.value : [];
  $('cpu-cores').innerHTML = per.map((p) =>
    `<div class="core" title="${p}%"><i style="height:${Math.max(2, p)}%"></i></div>`).join('');

  $('ram-figs').innerHTML = [
    fig(mem.available, 'available'), fig(mem.used, 'used'),
    fig(mem.total, 'total'), fig(mem.cached, 'page cache'),
  ].join('');
  $('ram-bars').innerHTML = mem.used_pct ? bar(mem.used_pct.value,
    'used (MemTotal − MemAvailable — not MemFree)') : '';

  $('disk-path').textContent = disk.path && disk.path.value ? disk.path.value : '';
  $('disk-figs').innerHTML = [fig(disk.free, 'free'), fig(disk.used, 'used'),
    fig(disk.total, 'total')].join('');
  $('disk-bars').innerHTML = disk.used_pct ? bar(disk.used_pct.value, 'disk used') : '';
}

function renderWork(w, labels) {
  const last = w.last || {};
  const order = ['predicted_n', 'predicted_per_second', 'prompt_n', 'prompt_per_second',
                 'cache_n', 'predicted_per_token_ms'];
  $('work-figs').innerHTML = order.map((k) =>
    fig(last[k], (labels && labels[k] ? labels[k][0] : k))).join('');
  $('work-when').textContent = w.at
    ? new Date(w.at * 1000).toLocaleTimeString() : 'no request yet';
  $('work-foot').textContent = w.samples
    ? `${w.samples} recent request(s) · captured from the engine's own timings, no probe issued`
    : 'nothing has been generated since the API started';
  spark(w.series || []);
}

function spark(series) {
  const el = $('work-spark');
  const pts = series.map((s) => s.predicted_per_second).filter((v) => typeof v === 'number');
  if (pts.length < 2) { el.innerHTML = ''; return; }
  const max = Math.max(...pts), min = Math.min(...pts), span = Math.max(1e-6, max - min);
  const d = pts.map((v, i) => {
    const x = (i / (pts.length - 1)) * 600;
    const y = 50 - ((v - min) / span) * 46;
    return `${i === 0 ? 'M' : 'L'}${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(' ');
  el.innerHTML = `<path class="fillp" d="${d} L600,54 L0,54 Z"></path><path d="${d}"></path>`;
}

function renderCtx(c) {
  $('ctx-figs').innerHTML = [
    fig(c.n_ctx_per_slot, 'per slot'), fig(c.total_slots, 'slots'),
    fig(c.n_ctx_total, 'total (computed)'),
  ].join('');
  $('ctx-foot').textContent = c.model_path && c.model_path.value
    ? 'serving ' + c.model_path.value.split('/').pop() : '';
}

/* ---- overclocking -------------------------------------------------------------------- */

let OC = null;

function renderPresets(presets) {
  $('oc-presets').innerHTML = presets.map((p, i) =>
    `<button data-i="${i}" class="${p.gpu > 100 ? 'over' : ''}">${esc(p.name)}</button>`).join('');
  $('oc-presets').querySelectorAll('button').forEach((b) => {
    b.onclick = () => {
      const p = presets[+b.dataset.i];
      $('oc-gpu').value = p.gpu; $('oc-cpu').value = p.cpu; $('oc-ram').value = p.ram;
      planNow();
    };
  });
}

async function planNow() {
  const g = +$('oc-gpu').value, c = +$('oc-cpu').value, r = +$('oc-ram').value;
  $('oc-gpu-v').textContent = g; $('oc-cpu-v').textContent = c; $('oc-ram-v').textContent = r;
  // Over 100% is the card's real firmware headroom, so it is coloured differently rather
  // than hidden: it is a deliberate choice, not a mistake.
  $('oc-gpu').classList.toggle('over', g > 100);
  let p;
  try { p = await getJSON(`/api/metrics/overclock/plan?gpu=${g}&cpu=${c}&ram=${r}`); }
  catch (e) { $('oc-commands').innerHTML = `<div class="warnbox">${esc(e.message)}</div>`; return; }

  $('oc-gpu-real').innerHTML = p.gpu
    ? `<b>${p.gpu.power_w} W</b> board limit${p.gpu.is_over_default ? ' — above default' : ''}`
      + (p.vram ? ` · VRAM budget <b>${p.vram.budget_mib}</b> MiB` : '') : '';
  $('oc-cpu-real').innerHTML = p.cpu
    ? `CPUQuota <b>${p.cpu.quota_pct}%</b> (${p.cpu.threads_equivalent} threads)` : '';
  $('oc-ram-real').innerHTML = p.ram ? `cap <b>${p.ram.cap_gib}</b> GiB` : '';

  $('oc-clamps').innerHTML = (p.clamps || []).map((c) =>
    `<div class="warnbox"><b>${esc(c.resource)}</b> — ${esc(c.why)}</div>`).join('');

  $('oc-commands').innerHTML = (p.commands || []).map((c) =>
    `<pre class="cmd">${esc(c.command)}
<span class="c"># ${esc(c.what)}${c.needs_root ? '  (needs root)' : ''}</span>
<span class="c"># undo: ${esc(c.undo)}</span></pre>`).join('');
  $('oc-foot').textContent = (p.note || '') + ' ' + (p.caps_are_not_load || '');
}

/* ---- static half --------------------------------------------------------------------- */

function renderParams(p) {
  $('params-settable').innerHTML = (p.settable || []).map((s) => `
    <div class="slider">
      <label>${esc(s.name)} <b>${esc(String(s.default))}</b></label>
      <div class="real">${esc(s.what)}${s.engine_default != null
        ? ` · engine default ${esc(String(s.engine_default))}` : ''}</div>
    </div>`).join('');
  $('params-why').textContent = p.why_split || '';
  $('params-ro-n').textContent = `${(p.read_only || []).length} read-only`;
  $('params-ro').innerHTML = '<tr><th>parameter</th><th>value</th></tr>' +
    (p.read_only || []).map((r) =>
      `<tr><td>${esc(r.name)}</td><td class="num">${esc(String(r.value))}</td></tr>`).join('');
}

function renderFabric(f) {
  const st = (f.component && f.component.fields) ? f.component.fields : {};
  const impl = st.IMPLEMENTATION_STATUS || 'unknown';
  $('fabric-status').innerHTML =
    `<span class="pill ${impl === 'NOT_IMPLEMENTED' ? 'planned' : 'ok'}">${esc(impl)}</span>`;
  $('fabric-head').textContent = f.headline || '';
  $('fabric-subs').innerHTML =
    '<tr><th>subcomponent</th><th>status</th><th>evidence</th></tr>' +
    (f.subcomponents || []).map((s) => `<tr>
        <td>${esc(s.name)}${s.adjacent_but_not_this
          ? `<div class="adjacent">${esc(s.adjacent_but_not_this)}</div>` : ''}</td>
        <td><span class="pill ${s.status === 'PLANNED_SUBCOMPONENT' ? 'planned' : 'ok'}">${
          esc(s.status)}</span></td>
        <td>${esc(s.evidence || '')}</td></tr>`).join('');
  const pr = f.profiler || {};
  $('fabric-profiler').innerHTML = `<div class="warnbox"><b>What this dashboard contributes:</b>
      ${esc(pr.claim || '')}<br><br><b>Not claimed:</b> ${esc(pr.not_claimed || '')}</div>`;
}

function renderSuites(s) {
  const inv = s.inventory || {};
  $('tests-figs').innerHTML = [
    fig({ value: inv.python_test_functions, unit: 'tests', source: inv.source }, 'python tests'),
    fig({ value: inv.python_test_files, unit: 'files', source: inv.source }, 'test files'),
    fig({ value: inv.browser_suites, unit: 'suites', source: 'tests/*.mjs' }, 'browser suites'),
  ].join('');
  $('tests-areas').innerHTML = '<tr><th>area</th><th>tests</th></tr>' +
    Object.entries(inv.by_area || {}).map(([k, v]) =>
      `<tr><td>${esc(k)}</td><td class="num">${v}</td></tr>`).join('');
  $('tests-blockers').innerHTML = (s.blockers || []).map((b) =>
    `<div class="warnbox"><b>${esc(b.what)}</b> — ${b.blocked ? 'BLOCKED' : 'ok'}: ${
      esc(b.reason)}</div>`).join('') +
    `<div class="foot">${esc(inv.note || '')}</div>`;
  $('tests-commands').innerHTML = (s.commands || []).map((c) =>
    `<pre class="cmd">${esc(c.command)}${c.note ? `\n<span class="c"># ${esc(c.note)}</span>` : ''}</pre>`).join('');
  $('bench-body').innerHTML = (s.benchmarks || []).map((b) => `
      <h2 style="margin-top:14px">${esc(b.pass || b.file)} <span class="badge pill info">${
        esc(b.measured_on || '')}</span></h2>
      <p class="foot">${esc(b.question || '')}</p>
      <div class="scroll"><table class="t">
        <tr><th>id</th><th>metric</th><th>median</th><th>unit</th><th>comparability</th><th>Δ%</th></tr>
        ${(b.measurements || []).map((m) => `<tr>
          <td>${esc(m.id)}</td><td>${esc(m.metric || '')}</td>
          <td class="num">${esc(String(m.median ?? m.mean ?? ''))}</td>
          <td>${esc(m.unit || '')}</td>
          <td><span class="pill info">${esc(m.comparability || '')}</span></td>
          <td class="num">${esc(String(m.delta_pct ?? ''))}</td></tr>`).join('')}
      </table></div>`).join('') || '<p class="foot">no finished benchmark results on disk</p>';
}

/* ---- loop ---------------------------------------------------------------------------- */

let LABELS = null;

async function tick() {
  try {
    const d = await getJSON('/api/metrics/live');
    renderCard(d.model.card);
    renderCtx(d.model.context);
    LABELS = d.model.labels || LABELS;
    renderWork(d.model.work, LABELS);
    renderHost(d.host);
    $('contract').textContent = d.model.contract || '';
    $('clock').textContent = 'read ' + new Date(d.model.read_at * 1000).toLocaleTimeString();
    $('clock').classList.remove('stale');
  } catch (e) {
    $('clock').textContent = 'could not read: ' + e.message;
    $('clock').classList.add('stale');
  }
}

async function boot() {
  await tick();
  setInterval(tick, LIVE_MS);
  try {
    const [st, params, oc] = await Promise.all([
      getJSON('/api/metrics/static'), getJSON('/api/metrics/params'),
      getJSON('/api/metrics/overclock'),
    ]);
    renderFabric(st.fabric);
    renderSuites(st.suites);
    renderParams(params);
    OC = oc;
    renderPresets(oc.presets || []);
    ['oc-gpu', 'oc-cpu', 'oc-ram'].forEach((id) => { $(id).oninput = planNow; });
    await planNow();
    $('page-foot').textContent =
      'Overclocking applies nothing: every command above needs root and is printed, not run. '
      + 'A web route that shells out to sudo is a privilege-escalation surface reachable from '
      + 'a browser.';
  } catch (e) {
    $('page-foot').textContent = 'static sections unavailable: ' + e.message;
  }
}

boot();
