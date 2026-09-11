/* SyMoNeuRaL Reinforce -- the training bay's frontend.
 *
 * Deploys to `site/reinforce.js`; `page.html` loads it with `<script src="/reinforce.js" defer>`.
 *
 * Talks to the API on the SAME ORIGIN, at `/api/train/*`. That is not incidental: FastAPI does
 * all the routing here and mounts `site/` last, and a split origin breaks the rest of the
 * site's live plumbing. There is no base URL to configure and there must not be one.
 *
 * ## Two rules this file is written around
 *
 * **Nothing renders that is not a reading.** Every number below comes out of a response body.
 * There is no placeholder progress, no simulated loss and no default job. With no run, the job
 * panel says there is no run -- which is why `renderJob` has an explicit `none` branch instead
 * of falling through to a zeroed-out table. A progress bar with no total behind it is the
 * dishonest pixel the no-decorative-indicators rule exists to prevent.
 *
 * **Every figure carries its label.** `lab()` renders the measured / vendor / projected badge,
 * and it is called at every point a byte count or a VRAM figure reaches the DOM. A figure
 * without one is a bug, not a style choice.
 *
 * ## Two things this file deliberately does not do
 *
 * **There is no objective picker.** The three objectives -- imitation, preference and
 * reinforcement -- are rendered as a badge on each profile's row and as a select-option suffix,
 * and never as a second dropdown. `routes.py`'s `StartBody` has no `method` field for the same
 * reason: a request that paired `preset="voice"` with `method="reinforcement"` would produce a
 * configuration whose dataset schema and hyperparameters contradict each other. The objective is
 * read off the profile. `describeSelectedPreset()` is what makes that legible -- it rewrites the
 * dataset field's own label from the selected profile's schema, because the field used to assert
 * "a JSONL file of chat examples" and that is now true for one objective out of three.
 *
 * **No series is drawn without its window.** `/status` returns a *tail* of the run's log, not its
 * history. A reward curve drawn from the last few dozen log lines while looking like the whole
 * run is the no-decorative-indicators rule broken with a chart instead of an LED, so every
 * sparkline carries the step range and the reading count it was drawn from, and `sparkline()`
 * returns null below three points -- two readings are not a trend. Which metrics render is
 * decided by what the run actually reported (`snap.metrics`), never by what its objective is
 * capable of reporting: an axis with no data behind it is the fake activity light.
 *
 * ## Text handling
 *
 * All server strings go in through `textContent`, never `innerHTML`. The API's own guard means
 * these strings are written by us rather than echoed from a file, but a dataset path is
 * operator-supplied and ends up in an error message, so the sink is kept safe rather than the
 * source trusted.
 *
 * Nothing here truncates. Long reasons and long attributions wrap, or fold into a <details>.
 * The CSS block in page.html says the same thing at more length and for the same reason.
 */
(function () {
  'use strict';

  var API = '/api/train';
  var GIB = 1024 * 1024 * 1024;
  var state = {
    models: [], presets: [], fit: [], measured: {}, poll: null,
    // Filled from `/presets`. `methods` and `schemas` are what let the dataset field name the
    // shape the selected profile actually needs, instead of the markup asserting one shape for
    // all three objectives.
    methods: {}, schemas: {}, byId: {}, rewardRows: []
  };

  function $(id) { return document.getElementById(id); }

  /* The metric names each objective reports, and how to say them in English. A metric absent
   * from a run's output is absent from the panel -- see `renderMetrics`. */
  var METRIC_LABELS = {
    loss: 'training loss',
    val_loss: 'validation loss',
    grad_norm: 'gradient norm',
    reward: 'reward (weighted sum of this run’s scoring functions)',
    reward_std: 'reward spread within the group',
    kl: 'KL from the starting policy',
    entropy: 'entropy of the sampled completions',
    clip_ratio: 'fraction of tokens clipped',
    completion_len: 'mean completion length, tokens',
    completion_len_ok: 'mean length of the completions that finished',
    reward_chosen: 'implicit reward, preferred answer',
    reward_rejected: 'implicit reward, rejected answer',
    reward_accuracy: 'pairs ranked correctly',
    reward_margin: 'margin between the two',
    logps_chosen: 'log-probability, preferred answer',
    logps_rejected: 'log-probability, rejected answer'
  };

  function gib(bytes) {
    if (bytes === null || bytes === undefined) { return '--'; }
    if (bytes < GIB / 10) { return (bytes / (1024 * 1024)).toFixed(0) + ' MiB'; }
    return (bytes / GIB).toFixed(2) + ' GiB';
  }

  /* The measured / vendor / projected badge. Called wherever a figure reaches the DOM. */
  function lab(kind) {
    if (!kind) { return null; }
    var span = document.createElement('span');
    // A compound label such as "measured (architecture read from the GGUF...)" keeps its
    // explanation in a title attribute and shows its first word -- the explanation is data, so
    // it is preserved rather than dropped.
    var head = String(kind).split(' ')[0];
    span.className = 'rf-lab rf-lab-' + head;
    span.textContent = head;
    if (String(kind) !== head) { span.title = String(kind); }
    return span;
  }

  /* The objective badge. A reading of the selected profile, never a control -- there is no
   * method dropdown on this page and there must not be one, for the reason `routes.py` gives:
   * a request that could pair a profile with a contradicting objective would produce a
   * configuration whose dataset schema and hyperparameters disagree. */
  function objBadge(methodId) {
    var span = document.createElement('span');
    span.className = 'rf-obj rf-obj-' + methodId;
    var m = state.methods[methodId] || {};
    span.textContent = m.label || methodId;
    return span;
  }

  function cell(row, text, labelKind, numeric) {
    var td = document.createElement('td');
    if (numeric) { td.className = 'rf-num'; }
    td.appendChild(document.createTextNode(text === null || text === undefined ? '--' : String(text)));
    var badge = lab(labelKind);
    if (badge) { td.appendChild(badge); }
    row.appendChild(td);
    return td;
  }

  function get(path) {
    return fetch(API + path, { headers: { accept: 'application/json' } })
      .then(function (r) {
        return r.json().then(function (body) { return { ok: r.ok, status: r.status, body: body }; });
      });
  }

  function post(path, payload, token) {
    var headers = { 'content-type': 'application/json', accept: 'application/json' };
    // The operator token travels in a header, never in the URL. uvicorn logs the full request
    // line, so a secret in a query string is a secret written to the server's log on every
    // request.
    if (token) { headers['x-reinforce-token'] = token; }
    return fetch(API + path, { method: 'POST', headers: headers, body: JSON.stringify(payload || {}) })
      .then(function (r) {
        return r.json().then(function (body) { return { ok: r.ok, status: r.status, body: body }; });
      });
  }

  /* ------------------------------------------------------------------ 1. models */

  function renderModels(data) {
    var tbody = $('rf-models').querySelector('tbody');
    tbody.textContent = '';
    state.models = data.models || [];

    state.models.forEach(function (m) {
      var tr = document.createElement('tr');

      var name = document.createElement('td');
      var strong = document.createElement('strong');
      strong.textContent = m.label;
      name.appendChild(strong);
      // The path is shown in full. It is short, it is the answer to "which copy is this", and
      // truncating it would hide the difference between two snapshots of one repository.
      var path = document.createElement('div');
      path.className = 'rf-note';
      path.textContent = m.path;
      name.appendChild(path);
      tr.appendChild(name);

      cell(tr, m.kind === 'hf' ? 'safetensors' : 'GGUF');
      if (m.present) {
        cell(tr, gib(m.bytes_on_disk), 'measured', true);
      } else {
        cell(tr, 'not on this box · ' + gib(m.fetch_bytes) + ' to fetch', 'projected', true);
      }
      cell(tr, m.quantisation || '--', m.quant_label);

      var params = document.createElement('td');
      params.className = 'rf-num';
      if (m.params) {
        params.appendChild(document.createTextNode(
          (m.params.total / 1e9).toFixed(2) + 'B total · ' +
          (m.params.quantised_4bit / 1e9).toFixed(2) + 'B to four bits · ' +
          (m.params.resident_bf16 / 1e9).toFixed(2) + 'B stays full width'));
        params.appendChild(lab(m.params.label));
        var note = document.createElement('div');
        note.className = 'rf-note';
        note.textContent = m.params.note;
        params.appendChild(note);
      } else {
        params.textContent = '--';
      }
      tr.appendChild(params);

      var ok = document.createElement('td');
      if (m.trainable) {
        var yes = document.createElement('span');
        yes.className = 'rf-verdict rf-fits';
        yes.textContent = 'yes';
        ok.appendChild(yes);
      } else {
        var no = document.createElement('span');
        no.className = 'rf-verdict rf-refused';
        no.textContent = 'no';
        ok.appendChild(no);
        // The reason, in full and never clipped. "Unsupported" on its own is what makes an
        // operator file a bug report; the reason is what makes them pick the other row.
        var why = document.createElement('div');
        why.className = 'rf-note';
        why.textContent = m.reason;
        ok.appendChild(why);
      }
      tr.appendChild(ok);
      tbody.appendChild(tr);
    });

    var vram = $('rf-vram');
    vram.textContent = '';
    if (data.free_vram_bytes) {
      vram.appendChild(document.createTextNode('Free on the card right now: ' + gib(data.free_vram_bytes)));
      vram.appendChild(lab(data.free_vram_label));
      vram.appendChild(document.createTextNode('. Planning budget: ' + gib(data.budget_bytes)));
      vram.appendChild(lab(data.budget_label));
      vram.appendChild(document.createTextNode('. ' + data.budget_note + ' ' + data.fetch_note));
    } else {
      vram.textContent = 'Free VRAM could not be read: ' + (data.free_vram_label || 'unknown') +
        '. Nothing is guessed in its place — the fit column falls back to the planning budget.';
    }

    var pick = $('rf-pick-model');
    pick.textContent = '';
    state.models.filter(function (m) { return m.trainable; }).forEach(function (m) {
      var opt = document.createElement('option');
      opt.value = m.id;
      opt.textContent = m.label;
      pick.appendChild(opt);
    });
    if (!pick.options.length) {
      var none = document.createElement('option');
      none.textContent = 'no model on this box can be fine-tuned';
      none.value = '';
      pick.appendChild(none);
    }
  }

  /* ------------------------------------------------------------------ 2. objectives */

  function renderMethods(data) {
    var tbody = $('rf-methods').querySelector('tbody');
    tbody.textContent = '';
    Object.keys(state.methods).forEach(function (id) {
      var m = state.methods[id];
      var tr = document.createElement('tr');

      var name = document.createElement('td');
      name.appendChild(objBadge(id));
      // The one claim on this row rather than a name: DPO optimises a preference objective in
      // closed form and never samples, so it is not reinforcement learning and is not labelled
      // as it. Stated per row because the industry usually does call it that.
      var isrl = document.createElement('span');
      isrl.className = 'rf-isrl';
      isrl.textContent = m.is_rl
        ? 'this one is reinforcement learning'
        : 'not reinforcement learning, despite where it is usually filed';
      name.appendChild(isrl);
      tr.appendChild(name);

      cell(tr, m.optimises);

      var sch = document.createElement('td');
      var shape = (state.schemas[m.dataset_schema] || {}).shape || m.dataset_schema;
      var code = document.createElement('strong');
      code.textContent = m.dataset_schema;
      sch.appendChild(code);
      var sd = document.createElement('div');
      sd.className = 'rf-note';
      sd.textContent = shape;
      sch.appendChild(sd);
      tr.appendChild(sch);

      // The reference model, and the answer to the objection that kept preference tuning out of
      // this bay: it costs no extra weight bytes. The reference IS this model with the adapter
      // switched off, so there is never a second copy resident.
      cell(tr, m.needs_reference
        ? 'yes — and it costs no extra weights: the reference is this same model with the adapter switched off'
        : 'no');
      cell(tr, m.samples ? 'yes — it writes its own answers and is scored on them' : 'no');

      var met = document.createElement('td');
      met.textContent = (m.metrics || []).map(function (k) {
        return METRIC_LABELS[k] || k;
      }).join('; ');
      var tw = document.createElement('div');
      tw.className = 'rf-note';
      tw.textContent = m.trainer + ' — ' + m.why;
      met.appendChild(tw);
      tr.appendChild(met);

      tbody.appendChild(tr);
    });
    $('rf-rlnote').textContent = data.rl_note || '';
  }

  /* ------------------------------------------------------------------ rewards and rollout */

  function renderRewards(rows, activeNames) {
    var tbody = $('rf-rewards').querySelector('tbody');
    tbody.textContent = '';
    (rows || []).forEach(function (r) {
      var tr = document.createElement('tr');
      // Dimmed, never dropped. A reward function that cannot run because the dataset has no such
      // column is stated by name: `resolve()` refuses rather than quietly training against fewer
      // functions than were configured, and that refusal only helps if it reaches the screen.
      if (r.available === false) { tr.className = 'rf-unavailable'; }

      var name = document.createElement('td');
      var b = document.createElement('strong');
      b.textContent = r.label;
      name.appendChild(b);
      if (activeNames && activeNames.indexOf(r.id) !== -1) {
        var act = document.createElement('div');
        act.className = 'rf-note';
        act.textContent = 'active for the selected profile';
        name.appendChild(act);
      }
      tr.appendChild(name);

      cell(tr, r.weight, null, true);
      cell(tr, r.range[0] + ' to ' + r.range[1], null, true);
      cell(tr, r.why);
      cell(tr, r.requires ? 'a ' + r.requires + ' column in the dataset' : 'nothing beyond the completion');
      cell(tr, r.provenance);
      tbody.appendChild(tr);
    });
  }

  function renderRollout(data) {
    var det = $('rf-rollout');
    var tbody = det.querySelector('tbody');
    tbody.textContent = '';
    (data.backends || []).forEach(function (b) {
      var tr = document.createElement('tr');
      cell(tr, b.label);
      cell(tr, b.on_policy ? 'yes' : 'no');

      var ok = document.createElement('td');
      var v = document.createElement('span');
      v.className = 'rf-verdict ' + (b.available ? 'rf-fits' : 'rf-refused');
      v.textContent = b.available ? 'yes' : 'no';
      ok.appendChild(v);
      if (b.detail) {
        var d = document.createElement('div');
        d.className = 'rf-note';
        d.textContent = b.detail;
        ok.appendChild(d);
      }
      tr.appendChild(ok);

      cell(tr, b.why);
      cell(tr, b.cost);
      tbody.appendChild(tr);
    });
    var note = $('rf-rollout-note');
    note.textContent = data.note + ' ' +
      (data.llm_engine_present ? data.llm_engine_note : '') +
      ' Default: ' + data.default + '.';
  }

  /* ------------------------------------------------------------------ 3. presets */

  function renderPresets(data) {
    state.presets = data.presets || [];
    state.fit = data.fit || [];
    state.measured = data.measured_peaks || {};
    state.methods = data.methods || {};
    state.schemas = data.schemas || {};
    state.byId = {};
    state.presets.forEach(function (p) { state.byId[p.id] = p; });
    var fitById = {};
    state.fit.forEach(function (f) { fitById[f.preset] = f; });

    state.rewardRows = data.rewards || [];
    renderMethods(data);
    renderRewards(state.rewardRows, null);
    if (data.rollout) { renderRollout(data.rollout); }

    var tbody = $('rf-presets').querySelector('tbody');
    tbody.textContent = '';

    state.presets.forEach(function (p) {
      var f = fitById[p.id];
      var plan = f ? f.plan : null;
      var tr = document.createElement('tr');

      var name = document.createElement('td');
      var b = document.createElement('strong');
      b.textContent = p.label;
      name.appendChild(b);
      var tn = document.createElement('div');
      tn.className = 'rf-note';
      tn.textContent = p.trainer;
      name.appendChild(tn);
      tr.appendChild(name);

      var obj = document.createElement('td');
      obj.appendChild(objBadge(p.method));
      var od = document.createElement('div');
      od.className = 'rf-note';
      od.textContent = 'needs a ' + p.dataset_schema + ' dataset';
      obj.appendChild(od);
      tr.appendChild(obj);

      cell(tr, p.when);
      cell(tr, 'r=' + p.rank + ' · alpha=' + p.lora_alpha + ' · ' +
               p.target_modules.length + ' target module(s)', null, true);
      cell(tr, p.epochs + ' epoch(s) · ' + p.learning_rate + ' · ' + p.lr_scheduler_type, null, true);

      /* Sequence and batch. For a reinforcement profile `max_length` is the PROMPT cap and the
       * completion budget is separate, so the cell says which is which -- reading it as a total
       * would understate what the run generates. The group size is here rather than buried in
       * the rationale because it, not the rank, is what decides whether the run fits. */
      var seq = document.createElement('td');
      seq.className = 'rf-num';
      if (p.method === 'reinforcement') {
        var mc = p.method_config || {};
        seq.textContent = p.max_length + ' prompt tokens + ' + mc.max_completion_length +
          ' generated · ' + mc.num_generations + ' completions per prompt · batch 1 x ' +
          p.gradient_accumulation_steps;
      } else if (p.method === 'preference') {
        seq.textContent = p.max_length + ' tokens per answer, two answers per example · batch 1 x ' +
          p.gradient_accumulation_steps + ' (effective ' + p.effective_batch + ')';
      } else {
        seq.textContent = p.max_length + ' tokens · batch 1 x ' + p.gradient_accumulation_steps +
          ' (effective ' + p.effective_batch + ')';
      }
      tr.appendChild(seq);

      /* Peak VRAM. A cell shows a MEASURED figure only when a run of this exact model and
       * preset has recorded one; otherwise the projection, labelled as such. Scaling one
       * measurement onto the other cells would be a projection wearing a measurement's badge. */
      var vram = document.createElement('td');
      vram.className = 'rf-num';
      var key = (f ? f.model : '') + '|' + p.id;
      if (state.measured[key]) {
        vram.appendChild(document.createTextNode(gib(state.measured[key].peak_alloc) + ' allocated'));
        vram.appendChild(lab('measured'));
        var res = document.createElement('div');
        res.className = 'rf-note';
        res.textContent = gib(state.measured[key].peak_reserved) + ' reserved, over ' +
          state.measured[key].steps + ' step(s). Projection for this configuration was ' +
          (plan ? gib(plan.projected_peak_bytes) : '--') + '.';
        vram.appendChild(res);
      } else if (plan) {
        vram.appendChild(document.createTextNode(gib(plan.projected_peak_bytes)));
        vram.appendChild(lab('projected'));
        var terms = document.createElement('details');
        terms.className = 'rf-why';
        var sum = document.createElement('summary');
        sum.textContent = 'show the arithmetic';
        terms.appendChild(sum);
        var dl = document.createElement('dl');
        Object.keys(plan.terms).forEach(function (k) {
          var dt = document.createElement('dt');
          dt.textContent = k.replace(/_/g, ' ') + ' — ' + gib(plan.terms[k].bytes);
          dt.appendChild(lab(plan.terms[k].label));
          dl.appendChild(dt);
          var dd = document.createElement('dd');
          dd.textContent = plan.terms[k].basis;
          dl.appendChild(dd);
        });
        var dt2 = document.createElement('dt');
        dt2.textContent = 'how accurate has this been?';
        dl.appendChild(dt2);
        var dd2 = document.createElement('dd');
        dd2.textContent = plan.accuracy.runs_measured + ' run measured so far (' +
          plan.accuracy.cell + '): ' + plan.accuracy.content_term_error + '. ' +
          plan.accuracy.direction + '. ' + plan.accuracy.first_correction + '.';
        dl.appendChild(dd2);
        /* The one measurement behind this arithmetic is a SUPERVISED run. Saying so on every
         * non-supervised row is the difference between a projection with a known error bar and a
         * projection borrowing somebody else's. */
        if (plan.method && plan.method !== 'sft') {
          var dt3 = document.createElement('dt');
          dt3.textContent = 'and how accurate is the ' + plan.method + ' part?';
          dl.appendChild(dt3);
          var dd3 = document.createElement('dd');
          dd3.textContent = plan.method_accuracy;
          dl.appendChild(dd3);
          (plan.method_notes || []).forEach(function (n) {
            var ddn = document.createElement('dd');
            ddn.textContent = n;
            dl.appendChild(ddn);
          });
        }
        terms.appendChild(dl);
        vram.appendChild(terms);
      } else {
        vram.textContent = '--';
      }
      tr.appendChild(vram);

      var verdict = document.createElement('td');
      if (plan) {
        var v = document.createElement('span');
        v.className = 'rf-verdict rf-' + plan.verdict;
        v.textContent = plan.verdict;
        verdict.appendChild(v);
        var vw = document.createElement('div');
        vw.className = 'rf-note';
        vw.textContent = plan.verdict_why + ' Headroom ' + gib(plan.headroom_bytes) +
          ' against a ' + gib(plan.budget_bytes) + ' budget.';
        verdict.appendChild(vw);
        if (plan.ladder && plan.ladder.length) {
          var lad = document.createElement('div');
          lad.className = 'rf-note';
          lad.textContent = 'To make it fit: ' + plan.ladder.join('; ') + '.';
          verdict.appendChild(lad);
        }
        var pct = document.createElement('div');
        pct.className = 'rf-note';
        pct.textContent = plan.trainable_params.toLocaleString() + ' trainable parameters, ' +
          plan.trainable_pct + '% of the base — ' + plan.trainable_pct_note + '.';
        verdict.appendChild(pct);
      }
      tr.appendChild(verdict);

      /* The rationale, folded rather than trimmed. This is the answer to "predetermined
       * professional tuning methods": a preset whose values cannot be justified is a form. */
      var why = document.createElement('tr');
      var wtd = document.createElement('td');
      // Must match the header in page.html. An objective column was added, so this is 8.
      wtd.colSpan = 8;
      var det = document.createElement('details');
      det.className = 'rf-why';
      var s2 = document.createElement('summary');
      s2.textContent = 'why these values for ' + p.label;
      det.appendChild(s2);
      var dl2 = document.createElement('dl');
      Object.keys(p.rationale).forEach(function (k) {
        var dt = document.createElement('dt');
        dt.textContent = k.replace(/_/g, ' ');
        dl2.appendChild(dt);
        var dd = document.createElement('dd');
        dd.textContent = p.rationale[k];
        dl2.appendChild(dd);
      });
      det.appendChild(dl2);
      wtd.appendChild(det);
      why.appendChild(wtd);

      tbody.appendChild(tr);
      tbody.appendChild(why);
    });

    fillDefinitionList($('rf-shared').querySelector('dl'), data.shared, true);
    fillDefinitionList($('rf-notoffered').querySelector('dl'), data.not_offered, false);

    var pick = $('rf-pick-preset');
    pick.textContent = '';
    state.presets.forEach(function (p) {
      var opt = document.createElement('option');
      opt.value = p.id;
      // The objective is named in the option text. The picker is the one place an operator
      // chooses anything, and "voice" does not tell them whether it wants chat examples or
      // preference pairs.
      opt.textContent = p.label + ' — ' +
        ((state.methods[p.method] || {}).label || p.method);
      pick.appendChild(opt);
    });
    describeSelectedPreset();
  }

  /* What the selected profile needs, written from the response rather than fixed in the markup.
   * The dataset field used to read "a JSONL file of chat examples", which is now true for one
   * objective out of three -- and a field naming the wrong shape sends an operator off to build
   * the wrong file and discover it at preflight. */
  function describeSelectedPreset() {
    var p = state.byId[$('rf-pick-preset').value];
    var lab = $('rf-dataset-label');
    var out = $('rf-method-out');
    var sch = $('rf-schema-out');
    var init = $('rf-init-out');
    if (!p) { return; }
    var m = state.methods[p.method] || {};
    var s = state.schemas[p.dataset_schema] || {};

    out.textContent = '';
    out.appendChild(objBadge(p.method));
    out.appendChild(document.createTextNode(' ' + (m.optimises || '') + ' Trainer: ' +
      (p.trainer || '') + '.'));

    lab.textContent = 'Dataset — a JSONL file of ' + p.dataset_schema + ' rows';
    sch.textContent = 'Each line needs ' + (s.shape || 'the fields this objective requires') +
      '. ' + (s.why || '');

    // The starting-adapter hint is objective-specific because the right answer is. For a
    // reinforcement run, starting fresh discards the persona and optimises a reward function
    // against the raw base model.
    init.textContent = p.method === 'reinforcement'
      ? 'For a reinforcement run this usually should NOT be empty. The standard pipeline is ' +
        'supervised first and reinforcement on top, so leaving it blank starts from the raw base ' +
        'model and optimises a scoring function against a model that has never seen the house ' +
        'voice. The adapter you name is opened read-only; its rank and target modules override ' +
        'this profile’s, because an adapter’s shape is fixed when it is created.'
      : 'Optional. Leave it empty to start from a freshly initialised adapter. Naming one ' +
        'continues training from it, read-only — nothing is written back.';

    var active = p.method === 'reinforcement' ? (p.method_config || {}).rewards : null;
    renderRewards(state.rewardRows, active);
  }

  function fillDefinitionList(dl, obj, structured) {
    dl.textContent = '';
    Object.keys(obj || {}).forEach(function (k) {
      var dt = document.createElement('dt');
      dt.textContent = k.replace(/_/g, ' ');
      dl.appendChild(dt);
      var dd = document.createElement('dd');
      if (structured) {
        dd.textContent = String(obj[k].value) + ' — ' + obj[k].why +
          ' (source: ' + obj[k].provenance + ')';
      } else {
        dd.textContent = obj[k];
      }
      dl.appendChild(dd);
    });
  }

  /* ------------------------------------------------------------------ 3. preflight and start */

  function body() {
    return {
      model: $('rf-pick-model').value,
      preset: $('rf-pick-preset').value,
      dataset: $('rf-pick-dataset').value,
      // Sent on both preflight and start. There is deliberately no `method` field: the objective
      // is a property of the profile, and the API rejects the idea of choosing them separately.
      init_adapter: $('rf-pick-init').value
    };
  }

  function showPreflight(res) {
    var out = $('rf-preflight-out');
    out.textContent = '';
    // 501 is not an error and is not rendered as one: it means this box does not have the
    // capability for that configuration. The arithmetic comes back in the body either way.
    var data = (res.status === 501 && res.body && res.body.detail) ? res.body.detail : res.body;
    var line = document.createElement('div');
    if (data.ok) {
      line.textContent = 'This run fits. ' + (data.plan ? data.plan.verdict_why : '');
      $('rf-start-btn').disabled = false;
    } else {
      line.textContent = (res.status === 501 ? 'This box cannot run that: ' : 'Not started: ') +
        (data.message || data.reason || 'refused');
      $('rf-start-btn').disabled = true;
    }
    out.appendChild(line);
    if (data.plan) {
      var sums = document.createElement('div');
      sums.className = 'rf-note';
      sums.textContent = 'Projected peak ' + gib(data.plan.projected_peak_bytes) +
        ' against ' + gib(data.plan.budget_bytes) + ' available (' +
        data.plan.budget_basis + '). Headroom ' + gib(data.plan.headroom_bytes) + '.';
      out.appendChild(sums);
    }
    if (data.gpu_note) {
      var note = document.createElement('div');
      note.className = 'rf-note';
      note.textContent = data.gpu_note;
      out.appendChild(note);
    }
    if (data.dataset) {
      var ds = document.createElement('div');
      ds.className = 'rf-note';
      // Shape only. The API returns no dataset content and this shows none -- including the
      // column names, which are reported against a fixed allowlist so a column named after what
      // is inside it cannot leak through this line.
      ds.textContent = 'Dataset accepted: ' + data.dataset.rows + ' example(s), ' +
        gib(data.dataset.bytes_on_disk) + ' on disk, matching the ' + data.dataset.schema +
        ' schema' + (data.dataset.fields && data.dataset.fields.length
          ? ' (columns: ' + data.dataset.fields.join(', ') + ')' : '') + '. ' + data.dataset.note;
      out.appendChild(ds);
    }

    /* Where this run's completions would come from. Shown whether or not it is usable, because a
     * refused rollout is the reason a reinforcement run will not start and "refused" without the
     * reason is what makes an operator file a bug report. */
    if (data.rollout) {
      var ro = document.createElement('div');
      ro.className = 'rf-note';
      ro.textContent = 'Rollout backend: ' + data.rollout.backend +
        (data.rollout.reachable === false && data.rollout.configured
          ? ' — configured but not answering. ' : ' — ') + (data.rollout.detail || '');
      out.appendChild(ro);
    }

    /* The reward functions this run would actually optimise, and by name the ones it would not.
     * `resolve()` refuses rather than silently training against fewer functions than were
     * configured; that refusal is only useful if it is displayed. */
    if (data.rewards) {
      var rw = document.createElement('div');
      rw.className = 'rf-note';
      rw.textContent = 'Scoring this run against: ' + data.rewards.active.join(', ') +
        ' (weights ' + data.rewards.active.map(function (n) {
          return n + '=' + data.rewards.weights[n];
        }).join(', ') + ').';
      out.appendChild(rw);
      if (data.rewards.refused && data.rewards.refused.length) {
        var rf = document.createElement('div');
        rf.className = 'rf-note';
        rf.textContent = 'Not scored, and named rather than dropped: ' +
          data.rewards.refused.map(function (r) { return r.id + ' — ' + r.why; }).join('; ') + '.';
        out.appendChild(rf);
      }
      renderRewards(data.rewards.offered, data.rewards.active);
    }

    /* Which adapter this run starts from. Stated even when it is "a fresh one", because that is a
     * decision rather than a blank field -- and for a reinforcement run it is usually the wrong
     * one. */
    if (data.init_adapter_note) {
      var ia = document.createElement('div');
      ia.className = 'rf-note';
      ia.textContent = 'Starting adapter: ' + (data.init_adapter || 'a freshly initialised one') +
        '. ' + data.init_adapter_note;
      out.appendChild(ia);
    }
  }

  /* ------------------------------------------------------------------ 4. job state */

  function renderJob(snap) {
    var dot = $('rf-dot');
    var text = $('rf-state-text');
    dot.setAttribute('data-state', snap.state);
    text.textContent = snap.state === 'none' ? snap.detail : snap.state + ' — ' + snap.detail;
    $('rf-stop-btn').hidden = !(snap.state === 'running' || snap.state === 'queued');

    var tbody = $('rf-job').querySelector('tbody');
    tbody.textContent = '';

    if (snap.state === 'none') {
      var tr = document.createElement('tr');
      var td = document.createElement('td');
      td.textContent = 'There is no run. Nothing on this panel is a placeholder — when a run ' +
        'exists, every figure below is a reading taken from it.';
      tr.appendChild(td);
      tbody.appendChild(tr);
      $('rf-metrics').hidden = true;
      return;
    }

    var rows = [
      ['method', snap.job ? snap.job.preset : null, null],
      ['objective', snap.method_label || snap.method, null],
      ['dataset schema', snap.job ? snap.job.dataset_schema : null, null],
      ['started from adapter', snap.job ? (snap.job.init_adapter || null) : null, null],
      ['base model', snap.job ? snap.job.model : null, null],
      ['examples', snap.job ? snap.job.dataset_rows : null, 'measured'],
      ['step', snap.total_steps ? (snap.step + ' of ' + snap.total_steps) : snap.step, 'measured'],
      ['epoch', snap.epoch, 'measured'],
      // Training loss is NOT repeated here: the metrics table below renders it with its series
      // and its window. `validation loss` stays, because it comes from eval events rather than
      // step events and is the only place it appears.
      ['validation loss', snap.val_loss, snap.val_loss_label],
      ['learning rate', snap.learning_rate, 'measured'],
      ['elapsed', snap.elapsed_s === null ? null : snap.elapsed_s + ' s', snap.elapsed_label],
      ['time remaining', snap.eta_s === null || snap.eta_s === undefined ? null : snap.eta_s + ' s',
       snap.eta_label],
      ['peak VRAM allocated', gib(snap.vram_peak_alloc_bytes), snap.vram_label],
      ['peak VRAM reserved', gib(snap.vram_peak_reserved_bytes), snap.vram_label],
      ['GPU held by', snap.holder, 'measured'],
      ['exit code', snap.exit_code, null]
    ];
    rows.forEach(function (r) {
      if (r[1] === null || r[1] === undefined || r[1] === '--') { return; }
      var tr = document.createElement('tr');
      var th = document.createElement('th');
      th.textContent = r[0];
      tr.appendChild(th);
      cell(tr, r[1], r[2], true);
      tbody.appendChild(tr);
    });
    if (snap.eta_s !== null && snap.eta_s !== undefined) {
      var tr2 = document.createElement('tr');
      var td2 = document.createElement('td');
      td2.colSpan = 2;
      td2.className = 'rf-note';
      td2.textContent = snap.eta_note;
      tr2.appendChild(td2);
      tbody.appendChild(tr2);
    }

    renderMetrics(snap);
  }

  /* A minimal series: no axis, no gridlines, no smoothing, and nothing drawn below three points
   * because two readings are not a trend. Returns null when there is not enough to draw. */
  function sparkline(values, cssClass) {
    if (!values || values.length < 3) { return null; }
    var lo = Math.min.apply(null, values);
    var hi = Math.max.apply(null, values);
    var span = (hi - lo) || 1;
    var w = 100, h = 30;
    var d = values.map(function (v, i) {
      var x = (i / (values.length - 1)) * w;
      // Inverted: SVG y grows downward and a rising reward should rise.
      var y = h - ((v - lo) / span) * h;
      return (i ? 'L' : 'M') + x.toFixed(2) + ' ' + y.toFixed(2);
    }).join(' ');
    var svg = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
    svg.setAttribute('viewBox', '0 0 ' + w + ' ' + h);
    svg.setAttribute('preserveAspectRatio', 'none');
    svg.setAttribute('class', 'rf-spark ' + (cssClass || 'rf-metric'));
    svg.setAttribute('aria-hidden', 'true');
    var path = document.createElementNS('http://www.w3.org/2000/svg', 'path');
    path.setAttribute('d', d);
    svg.appendChild(path);
    return svg;
  }

  /* The objective's own readings.
   *
   * Two rules, and both are the no-decorative-indicators rule applied to a chart:
   *
   * 1. **Only metrics the run actually reported appear.** The row set comes from
   *    `snap.metrics`, which the API builds from what the training process printed -- not from
   *    `METHODS[...].metrics`, which is what the objective *can* report. A supervised run has no
   *    reward and a reinforcement run has no validation loss, and an axis with no data behind it
   *    is exactly the fake activity light this repo forbids.
   * 2. **Every series names the window it was drawn from.** `/status` returns a TAIL of the log,
   *    not the run's history, so a line drawn from it shows the last few dozen readings while
   *    looking like the whole run. The caption states the step range and the count.
   */
  function renderMetrics(snap) {
    var box = $('rf-metrics');
    var metrics = snap.metrics || {};
    var keys = Object.keys(metrics);
    if (!keys.length) { box.hidden = true; return; }
    box.hidden = false;

    // Step events only. `events` also carries eval, error and done lines, and mixing them into a
    // series would plot different things on one axis.
    var steps = (snap.events || []).filter(function (e) { return e.event === 'step'; });
    var first = steps.length ? steps[0].step : null;
    var last = steps.length ? steps[steps.length - 1].step : null;

    var tbody = $('rf-metrics-tab').querySelector('tbody');
    tbody.textContent = '';
    keys.forEach(function (k) {
      var tr = document.createElement('tr');
      var th = document.createElement('th');
      th.textContent = METRIC_LABELS[k] || k;
      tr.appendChild(th);

      var td = document.createElement('td');
      td.className = 'rf-num';
      td.appendChild(document.createTextNode(String(metrics[k])));
      td.appendChild(lab(snap.metrics_label));
      var series = steps.map(function (e) { return e[k]; })
                        .filter(function (v) { return typeof v === 'number'; });
      var spark = sparkline(series, k.indexOf('reward') === 0 ? 'rf-metric-reward' : 'rf-metric');
      if (spark) {
        td.appendChild(spark);
        var cap = document.createElement('div');
        cap.className = 'rf-note';
        // The window, stated. Without this the line is a claim about the run rather than a
        // reading of the last few log lines.
        cap.textContent = series.length + ' reading(s), steps ' + first + '–' + last +
          ' of ' + (snap.total_steps || '?') + ' — the tail of the log this panel is given, ' +
          'not the whole run. Range ' + Math.min.apply(null, series).toFixed(4) + ' to ' +
          Math.max.apply(null, series).toFixed(4) + '.';
        td.appendChild(cap);
      }
      tr.appendChild(td);
      tbody.appendChild(tr);
    });

    var note = $('rf-metrics-note');
    note.textContent = '';
    var head = document.createElement('div');
    head.textContent = (snap.method_label || snap.method || '') + '. ' + (snap.metrics_note || '');
    note.appendChild(head);
    // For a reinforcement run, the sentence that keeps a rising line honest.
    if (snap.method === 'reinforcement') {
      var warn = document.createElement('div');
      warn.textContent = 'A rising reward means this run’s scoring functions returned a higher ' +
        'number. It is not by itself evidence the model improved: no human evaluation has been ' +
        'run on this box, and no quality claim is made here.';
      note.appendChild(warn);
    }
  }

  /* Polling rather than a socket: a training run reports once per logging step, which is
   * minutes apart on a real preset, so a socket would idle. The interval slows right down when
   * nothing is running, because the rack panel already carries the state a visitor needs. */
  function pollJob() {
    get('/status').then(function (res) {
      if (!res.ok) { return; }
      renderJob(res.body);
      var busy = res.body.state === 'running' || res.body.state === 'queued';
      if (state.poll) { clearTimeout(state.poll); }
      state.poll = setTimeout(pollJob, busy ? 4000 : 20000);
    }).catch(function () {
      if (state.poll) { clearTimeout(state.poll); }
      state.poll = setTimeout(pollJob, 20000);
    });
  }

  /* ------------------------------------------------------------------ wiring */

  function boot() {
    get('/models').then(function (res) {
      if (res.status === 503) {
        $('rf-gate').hidden = false;
        // Every control is disabled rather than hidden. A surface that vanishes when it is off
        // reads as broken; one that says why reads as configured.
        ['rf-preflight-btn', 'rf-start-btn', 'rf-pick-model', 'rf-pick-preset',
         'rf-pick-dataset', 'rf-pick-init', 'rf-token']
          .forEach(function (id) { $(id).disabled = true; });
        return;
      }
      renderModels(res.body);
      return get('/presets?model=' + encodeURIComponent($('rf-pick-model').value || ''))
        .then(function (p) { if (p.ok) { renderPresets(p.body); } });
    }).catch(function () { /* offline: the panel keeps its "loading" text rather than inventing one */ });

    pollJob();

    $('rf-pick-model').addEventListener('change', function () {
      get('/presets?model=' + encodeURIComponent($('rf-pick-model').value))
        .then(function (p) { if (p.ok) { renderPresets(p.body); } });
    });

    // Changing the profile changes the objective, which changes the dataset shape the run needs
    // and whether a starting adapter matters. Re-describing on change is what keeps the dataset
    // field from naming the wrong shape. It also clears any previous fit: a "this run fits" from
    // the last profile does not authorise starting this one.
    $('rf-pick-preset').addEventListener('change', function () {
      describeSelectedPreset();
      $('rf-start-btn').disabled = true;
      $('rf-preflight-out').textContent =
        'Profile changed — check the fit again before starting.';
    });

    $('rf-preflight-btn').addEventListener('click', function () {
      $('rf-preflight-out').textContent = 'Costing the run…';
      post('/preflight', body()).then(showPreflight);
    });

    $('rf-start-btn').addEventListener('click', function () {
      post('/start', body(), $('rf-token').value).then(function (res) {
        var out = $('rf-preflight-out');
        out.textContent = '';
        var line = document.createElement('div');
        if (res.ok) {
          line.textContent = 'Started. ' + res.body.warning;
          $('rf-start-btn').disabled = true;
        } else {
          var d = res.body && res.body.detail;
          line.textContent = 'Not started: ' +
            (typeof d === 'string' ? d : (d && d.message) || ('HTTP ' + res.status));
        }
        out.appendChild(line);
        pollJob();
      });
    });

    $('rf-stop-btn').addEventListener('click', function () {
      post('/stop', {}, $('rf-token').value).then(function (res) {
        var out = $('rf-preflight-out');
        out.textContent = res.ok
          ? (res.body.stopped ? res.body.note : res.body.reason)
          : 'Stop refused: HTTP ' + res.status;
        pollJob();
      });
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot);
  } else {
    boot();
  }
})();
