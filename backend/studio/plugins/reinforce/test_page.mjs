// The training bay's panel, in a real browser.
//
//   node backend/studio/plugins/reinforce/test_page.mjs
//
// `test_reinforce.py` asserts on the arithmetic and the protocol. This asserts on what the DOM
// actually SHOWS, which is a different question and the one this repo keeps getting wrong: three
// separate bugs here came from generic class names colliding across components, and one render
// succeeded server-side while every visitor saw a broken image. Reading a computed style beats
// reasoning about the cascade.
//
// The API is stubbed by route interception rather than started, for two reasons. The real
// `/api/train` needs `SYMONEURAL_REINFORCE_ENABLED` and a token, and more importantly the interesting
// states -- a reinforcement run mid-flight, a refused reward, an unreachable rollout backend --
// cannot be produced on demand from a box with one GPU and no finished RL run. Every stub below
// is shaped like the real response; `test_reinforce.py` is what holds the real ones to that shape.
//
// Nothing here downloads a browser: it uses the system Chrome, the way `tests/frontend.mjs` does.
import { createRequire } from 'node:module';
import { dirname, join } from 'node:path';
import { existsSync, readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO = dirname(dirname(dirname(HERE)));

// One resolution, shared with tests/. The three candidates that stood here were all
// wrong: two named a path that moved under references/, and REPO above is
// backend/apps, not the repo root, so `join(REPO, 'contrib/...')` never existed.
import { chromium } from '../../../../../tests/browser.mjs';

const results = [];
const record = (name, ok, detail) => {
  results.push({ name, ok, detail });
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${name}${detail ? '  -- ' + detail : ''}`);
};

/* ---------------------------------------------------------------- the stubbed API */

const METHODS = {
  sft: {
    id: 'sft', label: 'imitation', is_rl: false, samples: false, needs_reference: false,
    dataset_schema: 'messages', trainer: 'transformers.Trainer',
    optimises: 'the likelihood of example answers you provide',
    metrics: ['loss', 'val_loss'],
    why: 'the default, and what the shipped adapter was trained with',
  },
  preference: {
    id: 'preference', label: 'preference', is_rl: false, samples: false, needs_reference: true,
    dataset_schema: 'preference', trainer: 'trl.DPOTrainer',
    optimises: 'the gap between a preferred and a rejected answer to the same prompt',
    metrics: ['loss', 'reward_accuracy', 'reward_margin'],
    why: 'a closed-form surrogate for RLHF; it never samples, so it is not reinforcement learning',
  },
  reinforcement: {
    id: 'reinforcement', label: 'reinforcement', is_rl: true, samples: true,
    needs_reference: false, dataset_schema: 'prompt', trainer: 'trl.GRPOTrainer',
    optimises: 'a reward computed on answers the model writes itself',
    metrics: ['reward', 'reward_std', 'kl', 'completion_len'],
    why: 'group-relative policy optimisation: no value head, the group mean is the baseline',
  },
};

const SCHEMAS = {
  messages: { required: ['messages'], shape: 'a `messages` list of role/content turns',
              why: 'the chat format the tokeniser template expects', method: 'sft' },
  preference: { required: ['prompt', 'chosen', 'rejected'],
                shape: 'a `prompt`, plus `chosen` and `rejected` answers to it',
                why: 'two answers to one prompt is the whole signal', method: 'preference' },
  prompt: { required: ['prompt'], shape: 'a `prompt` and no answer',
            why: 'the model writes the answer; a reward function scores it', method: 'reinforcement' },
};

const REWARDS = [
  { id: 'house_style', label: 'House style', weight: 1.0, requires: null, range: [-1, 1],
    why: 'the floor: no boilerplate, no repetition collapse', provenance: 'convention',
    patterns_published: false, available: true },
  { id: 'pricing_refusal', label: 'Pricing refusal', weight: 1.2, requires: null, range: [-1, 1],
    why: 'never invent a price; direct it to the admin address', provenance: 'repo rule',
    patterns_published: false, available: true },
  { id: 'figure_labelling', label: 'Figure labelling', weight: 0.6, requires: null, range: [0, 1],
    why: 'a figure without measured/vendor/projected is unlabelled', provenance: 'repo rule',
    patterns_published: false, available: true },
  { id: 'answer_match', label: 'Answer match', weight: 1.0, requires: 'answer', range: [0, 1],
    why: 'exact-match against a known answer column', provenance: 'convention',
    patterns_published: false, available: false },
];

const ROLLOUT = {
  default: 'transformers',
  llm_engine_present: true,
  llm_engine_note: 'present on this box and still not used for rollouts.',
  note: 'only the reinforcement method generates anything.',
  vllm: { configured: false, reachable: false, url: null, detail: 'no external rollout server configured.' },
  backends: [
    { id: 'transformers', label: 'transformers (in-process)', on_policy: true, available: true,
      why: 'the model being trained generates its own completions', cost: 'no extra weights' },
    { id: 'vllm', label: 'vLLM (server mode, external host)', on_policy: false, available: false,
      why: 'how RL is done at scale; colocate is refused by arithmetic',
      cost: 'a machine that is not this one', detail: 'no external rollout server configured.' },
    { id: 'llama.cpp', label: 'llama.cpp (refused for rollouts)', on_policy: false, available: false,
      why: 'REFUSED on correctness: it cannot carry the adapter being trained',
      cost: 'not offered at any price' },
  ],
};

const plan = (over = {}) => ({
  projected_peak_bytes: 12.4 * 1024 ** 3,
  budget_bytes: 14.2 * 1024 ** 3,
  headroom_bytes: 1.8 * 1024 ** 3,
  budget_basis: 'practical, not nameplate',
  verdict: 'tight', verdict_why: 'It fits with 1.68 GiB spare.',
  label: 'projected',
  trainable_params: 40370176, trainable_pct: 0.53,
  trainable_pct_note: 'a fraction of the base',
  terms: {
    weights_4bit: { bytes: 4.1 * 1024 ** 3, label: 'projected', basis: 'NF4 plus double quantisation' },
    rollout_kv_cache: { bytes: 0.4 * 1024 ** 3, label: 'projected', basis: 'group size x prompt+completion' },
  },
  accuracy: { runs_measured: 1, cell: '7B / voice', content_term_error: '2.03 GiB light',
              direction: 'the projection was under', first_correction: 'the fp32 resident term' },
  method: 'reinforcement',
  method_bytes: 1.1 * 1024 ** 3,
  method_notes: ['the reference forward is charged only when beta > 0'],
  method_accuracy: 'no reinforcement term here has NEVER been checked against a real peak.',
  ladder: ['lower num_generations from 4 to 2', 'shorten max_completion_length'],
  ...over,
});

const PRESETS = {
  presets: [
    { id: 'voice', label: 'House voice', method: 'sft', method_label: 'imitation',
      dataset_schema: 'messages', is_rl: false, when: 'teach the model how to talk',
      rank: 16, lora_alpha: 32, target_modules: ['q_proj', 'v_proj'], epochs: 3,
      learning_rate: 0.0002, lr_scheduler_type: 'cosine', max_length: 1024,
      gradient_accumulation_steps: 8, effective_batch: 8, val_split: 0.1,
      trainer: 'transformers.Trainer', metrics: ['loss', 'val_loss'], method_config: {},
      rationale: { rank: 'sixteen is enough for style' } },
    { id: 'prefer', label: 'Preference', method: 'preference', method_label: 'preference',
      dataset_schema: 'preference', is_rl: false, when: 'you have pairs',
      rank: 16, lora_alpha: 32, target_modules: ['q_proj', 'v_proj'], epochs: 1,
      learning_rate: 0.000005, lr_scheduler_type: 'cosine', max_length: 1024,
      gradient_accumulation_steps: 8, effective_batch: 8, val_split: 0.1,
      trainer: 'trl.DPOTrainer', metrics: ['loss', 'reward_accuracy'],
      method_config: { beta: 0.1, precompute_ref_log_probs: true },
      rationale: { learning_rate: 'an order of magnitude below the supervised rate' } },
    { id: 'reward', label: 'Rules-based reinforcement', method: 'reinforcement',
      method_label: 'reinforcement', dataset_schema: 'prompt', is_rl: true,
      when: 'you have prompts and rules but no answers',
      rank: 16, lora_alpha: 32, target_modules: ['q_proj', 'v_proj'], epochs: 1,
      learning_rate: 0.000001, lr_scheduler_type: 'constant', max_length: 384,
      gradient_accumulation_steps: 8, effective_batch: 8, val_split: 0.0,
      trainer: 'trl.GRPOTrainer', metrics: ['reward', 'kl'],
      method_config: { num_generations: 4, max_completion_length: 192, beta: 0.0,
                       rewards: ['house_style', 'pricing_refusal', 'figure_labelling'],
                       rollout: 'transformers' },
      rationale: { val_split: 'there is no held-out loss to hold anything out for' } },
  ],
  shared: { batch_size: { value: 1, why: 'one card', provenance: 'measured here' } },
  not_offered: { full_fine_tuning: 'roughly eight times this card', reward_model_training:
    'a second network beside the policy does not fit' },
  fit: [
    { preset: 'voice', model: 'Qwen/Qwen2.5-7B-Instruct', plan: plan({ method: 'sft', verdict: 'fits' }) },
    { preset: 'prefer', model: 'Qwen/Qwen2.5-7B-Instruct', plan: plan({ method: 'preference' }) },
    { preset: 'reward', model: 'Qwen/Qwen2.5-7B-Instruct', plan: plan() },
  ],
  free_vram_label: 'measured',
  measured_peaks: {},
  methods: METHODS,
  schemas: SCHEMAS,
  rewards: REWARDS,
  rollout: ROLLOUT,
  rl_note: 'nothing about the preference or reinforcement methods has been measured on this box.',
  labels: { measured: 'read off this machine', vendor: 'somebody else', projected: 'arithmetic' },
  note: 'every VRAM figure here is projected until a run records a real peak.',
};

const MODELS = {
  models: [
    { id: 'Qwen/Qwen2.5-7B-Instruct', label: 'Qwen2.5 7B Instruct', kind: 'hf', present: true,
      bytes_on_disk: 15.2 * 1024 ** 3, quantisation: 'bf16', quant_label: 'measured',
      path: 'models/qwen2.5-7b-instruct', trainable: true,
      params: { total: 7.6e9, quantised_4bit: 6.5e9, resident_bf16: 1.1e9, label: 'measured',
                note: 'derived from the architecture metadata' } },
    { id: 'gguf-thing', label: 'Qwen2.5 7B Q4_K_M', kind: 'gguf', present: true,
      bytes_on_disk: 4.36 * 1024 ** 3, quantisation: 'Q4_K_M', quant_label: 'measured',
      path: 'models/qwen.gguf', trainable: false,
      reason: 'a serving-format file; its tensors cannot take a gradient' },
  ],
  free_vram_bytes: 15.1 * 1024 ** 3, free_vram_label: 'measured',
  budget_bytes: 14.2 * 1024 ** 3, budget_label: 'projected',
  budget_note: 'budgeting against the nameplate is how a run OOMs at step 0.',
  fetch_note: 'rows with present=false are not fetched.',
};

// A reinforcement run mid-flight. `metrics` carries only RL keys -- no val_loss -- and `events`
// is a TAIL, which is the thing the caption has to admit to.
const RL_STATUS = {
  state: 'running', detail: 'step 18 of 40',
  job: { model: 'Qwen/Qwen2.5-7B-Instruct', preset: 'reward', dataset_rows: 240,
         method: 'reinforcement', dataset_schema: 'prompt', init_adapter: 'training/adapter' },
  exit_code: null, holder: 'train', step: 18, total_steps: 40, epoch: 0.45,
  train_loss: null, train_loss_label: null, val_loss: null, val_loss_label: null,
  learning_rate: 1e-6, elapsed_s: 640.2, elapsed_label: 'measured',
  eta_s: 782.4, eta_label: 'projected', eta_note: 'arithmetic on a rate that is not constant',
  vram_peak_alloc_bytes: 11.9 * 1024 ** 3, vram_peak_reserved_bytes: 12.6 * 1024 ** 3,
  vram_label: 'measured', vram_note: 'torch.cuda.max_memory_allocated()',
  method: 'reinforcement', method_label: 'reinforcement',
  metrics: { reward: 0.612, reward_std: 0.184, kl: 0.0041, completion_len: 96.5 },
  metrics_label: 'measured',
  metrics_note: 'reward is the weighted sum of this run’s rules-based reward functions.',
  events: [14, 15, 16, 17, 18].map((s, i) => ({
    event: 'step', step: s, total_steps: 40,
    reward: 0.51 + i * 0.025, reward_std: 0.2 - i * 0.004,
    kl: 0.003 + i * 0.0003, completion_len: 90 + i * 1.6,
  })),
  measured_peaks: {},
  log_note: 'built from an allowlist of known-shaped runner output.',
};

const NO_RUN = { state: 'none', detail: 'no run has been started from this surface',
                 job: null, events: [], measured_peaks: {} };

const PREFLIGHT_RL = {
  ok: true, reason: '', message: '',
  model: MODELS.models[0], preset: PRESETS.presets[2], plan: plan(),
  shared: PRESETS.shared, method: 'reinforcement', method_info: METHODS.reinforcement,
  dataset_schema: 'prompt', schema_spec: SCHEMAS.prompt,
  dataset: { rows: 240, bytes_on_disk: 90112, schema: 'prompt', fields: ['prompt'],
             note: 'shape only; no content is read into this response' },
  rollout: { backend: 'transformers', configured: false, reachable: true,
             detail: 'the model being trained generates its own completions.' },
  rewards: {
    active: ['house_style', 'pricing_refusal', 'figure_labelling'],
    weights: { house_style: 1.0, pricing_refusal: 1.2, figure_labelling: 0.6 },
    // The case that must reach the screen: a configured function that cannot run.
    refused: [{ id: 'answer_match', why: 'needs an `answer` column and this dataset has none' }],
    offered: REWARDS,
  },
  init_adapter: 'training/adapter',
  init_adapter_note: 'continuing from an existing adapter. Nothing is written back to it.',
  gpu_note: 'a training run is never evicted to serve a page view.',
};

/* ---------------------------------------------------------------- the harness */

// The panel is a fragment: a marker-delimited <section> plus a <script src="/reinforce.js">.
// Wrapped in the minimum document that makes it render, with the script served from the same
// origin so the relative `/api/train` calls resolve.
const FRAGMENT = readFileSync(join(HERE, 'page.html'), 'utf8');
const SCRIPT = readFileSync(join(HERE, 'page.js'), 'utf8');
const DOC = `<!doctype html><html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>body{margin:0;background:#0e1116;color:#e8e8e8;font:15px/1.5 system-ui,sans-serif}
.wrap{max-width:1100px;margin:0 auto;padding:16px}.sub{opacity:.8}</style>
</head><body>${FRAGMENT}</body></html>`;

async function main() {
  const browser = await chromium.launch({ channel: 'chrome' });
  const page = await browser.newPage({ viewport: { width: 1280, height: 1000 } });
  const consoleErrors = [];
  page.on('pageerror', (e) => consoleErrors.push(String(e)));
  page.on('console', (m) => { if (m.type() === 'error') consoleErrors.push(m.text()); });

  let status = NO_RUN;
  await page.route('**/reinforce.js', (r) =>
    r.fulfill({ contentType: 'application/javascript', body: SCRIPT }));
  await page.route('**/api/train/models', (r) => r.fulfill({ json: MODELS }));
  await page.route('**/api/train/presets*', (r) => r.fulfill({ json: PRESETS }));
  await page.route('**/api/train/status', (r) => r.fulfill({ json: status }));
  await page.route('**/api/train/preflight', (r) => r.fulfill({ json: PREFLIGHT_RL }));
  await page.route('**/base/**', (r) => r.fulfill({ contentType: 'text/html', body: DOC }));

  await page.goto('http://127.0.0.1:9/base/panel.html', { waitUntil: 'domcontentloaded' })
    .catch(() => {});
  await page.setContent(DOC, { waitUntil: 'load' });
  // `page.js` is loaded with `defer` and boots on DOMContentLoaded; setContent resolves before
  // the routed script has run, so wait for a cell that only the JS can have written.
  await page.waitForFunction(
    () => document.querySelectorAll('#rf-presets tbody tr').length > 1, null, { timeout: 15000 });

  // ---- 1. the three objectives are rendered, and only one of them claims to be RL
  const methodRows = await page.$$eval('#rf-methods tbody tr', (rows) => rows.map((r) => ({
    badge: r.querySelector('.rf-obj')?.textContent || '',
    isrl: r.querySelector('.rf-isrl')?.textContent || '',
    text: r.textContent,
  })));
  record('the objective table renders all three objectives', methodRows.length === 3,
         methodRows.map((r) => r.badge).join(', '));
  const claimsRl = methodRows.filter((r) => r.isrl.startsWith('this one is'));
  record('exactly one objective claims to be reinforcement learning', claimsRl.length === 1,
         claimsRl.map((r) => r.badge).join(', ') || 'none');
  const pref = methodRows.find((r) => r.badge === 'preference');
  record('the preference row says it is NOT reinforcement learning',
         !!pref && pref.isrl.includes('not reinforcement learning'), pref?.isrl);
  record('the reference model is described as costing no extra weights',
         !!pref && pref.text.includes('no extra weights'));

  // ---- 2. there is no objective dropdown. The API has no `method` field and neither has this.
  const selects = await page.$$eval('#reinforce select', (els) => els.map((e) => e.id));
  record('there is no objective picker, only model and profile',
         selects.length === 2 && selects.includes('rf-pick-model') && selects.includes('rf-pick-preset'),
         selects.join(', '));

  // ---- 3. every preset row carries its objective badge and its schema
  const presetRows = await page.$$eval('#rf-presets tbody tr', (rows) =>
    rows.filter((r) => r.querySelector('.rf-obj')).map((r) => ({
      badge: r.querySelector('.rf-obj').textContent,
      cells: r.children.length,
      text: r.textContent,
    })));
  record('every profile row shows its objective', presetRows.length === 3,
         presetRows.map((r) => r.badge).join(', '));
  const rlRow = presetRows.find((r) => r.badge === 'reinforcement');
  record('the reinforcement row separates the prompt cap from the generated budget',
         !!rlRow && rlRow.text.includes('384 prompt tokens') && rlRow.text.includes('192 generated'),
         rlRow?.text.match(/384[^·]*·/)?.[0]);
  record('the reinforcement row states its group size',
         !!rlRow && rlRow.text.includes('4 completions per prompt'));

  // ---- 4. the rationale row must span the whole table. A colSpan that no longer matches the
  // header is how a "why these values" fold ends up narrower than the row it explains.
  const headerCols = await page.$$eval('#rf-presets thead th', (t) => t.length);
  const spans = await page.$$eval('#rf-presets tbody td[colspan]', (t) =>
    t.map((e) => Number(e.getAttribute('colspan'))));
  record('the rationale fold spans every column of the preset table',
         headerCols === 8 && spans.every((s) => s === headerCols),
         `header ${headerCols}, spans ${spans.join('/')}`);

  // ---- 5. the reward table, including the one that cannot run
  const rewardRows = await page.$$eval('#rf-rewards tbody tr', (rows) => rows.map((r) => ({
    text: r.textContent, dim: r.className.includes('rf-unavailable'),
  })));
  record('the reward table renders every offered function', rewardRows.length === 4);
  record('a reward needing an absent column is dimmed and still named',
         rewardRows.some((r) => r.dim && r.text.includes('Answer match')));
  record('the figure-labelling reward is weighted below the pricing rule',
         await page.evaluate(() => {
           const w = {};
           document.querySelectorAll('#rf-rewards tbody tr').forEach((r) => {
             w[r.children[0].textContent.trim().split('\n')[0]] = Number(r.children[1].textContent);
           });
           return w['Figure labelling'] < w['Pricing refusal'];
         }));

  // ---- 6. no reward row publishes its detection rule
  const rewardBlob = await page.$eval('#rf-rewards', (e) => e.textContent);
  record('the reward table never publishes a pattern',
         !/re\.compile|\\b|symonsayadmin@/.test(rewardBlob));

  // ---- 7. llama.cpp is on the rollout table, refused, with the reason
  const rollout = await page.$eval('#rf-rollout', (e) => e.textContent);
  record('llama.cpp is listed and refused on correctness',
         rollout.includes('llama.cpp') && rollout.includes('cannot carry the adapter'));
  // Listed AND marked unusable, rather than quietly omitted. Asserted on the verdict cell rather
  // than on prose: the point is that the table says "no" next to it, so nobody selects it
  // expecting a fallback -- and there is no fallback, by design.
  const rolloutVerdicts = await page.$$eval('#rf-rollout tbody tr', (rows) => rows.map((r) => ({
    name: r.children[0].textContent,
    usable: r.querySelector('.rf-verdict').textContent,
  })));
  record('every backend is listed with a usable/not-usable verdict', rolloutVerdicts.length === 3,
         rolloutVerdicts.map((r) => `${r.name}=${r.usable}`).join(', '));
  record('vLLM is listed and marked unusable here rather than omitted',
         rolloutVerdicts.some((r) => r.name.includes('vLLM') && r.usable === 'no'));
  record('transformers is the one backend marked usable',
         rolloutVerdicts.filter((r) => r.usable === 'yes').length === 1 &&
         rolloutVerdicts.find((r) => r.usable === 'yes').name.includes('transformers'));

  // ---- 8. the dataset field names the shape the SELECTED objective needs
  const labelFor = async (presetId) => {
    await page.selectOption('#rf-pick-preset', presetId);
    return {
      label: await page.$eval('#rf-dataset-label', (e) => e.textContent),
      schema: await page.$eval('#rf-schema-out', (e) => e.textContent),
      init: await page.$eval('#rf-init-out', (e) => e.textContent),
    };
  };
  const sft = await labelFor('voice');
  const prf = await labelFor('prefer');
  const rl = await labelFor('reward');
  record('the dataset field renames itself per objective',
         sft.label.includes('messages') && prf.label.includes('preference') &&
         rl.label.includes('prompt'),
         [sft.label, prf.label, rl.label].join(' | '));
  record('the preference field asks for chosen and rejected answers',
         prf.schema.includes('chosen') && prf.schema.includes('rejected'), prf.schema);
  record('the reinforcement field says the dataset has no answers',
         rl.schema.includes('no answer'), rl.schema);
  record('a reinforcement run is told a fresh adapter is the wrong choice',
         rl.init.includes('should NOT be empty') && !sft.init.includes('should NOT be empty'));

  // ---- 9. changing the profile revokes a previous fit
  await page.click('#rf-preflight-btn');
  await page.waitForFunction(
    () => document.getElementById('rf-preflight-out').textContent.includes('fits'),
    null, { timeout: 10000 });
  record('the start button unlocks only after a fit',
         (await page.$eval('#rf-start-btn', (e) => e.disabled)) === false);
  const out = await page.$eval('#rf-preflight-out', (e) => e.textContent);
  record('preflight names the refused reward function rather than dropping it',
         out.includes('answer_match') && out.includes('Not scored'),
         out.match(/Not scored[^.]*/)?.[0]);
  record('preflight states the rollout backend', out.includes('Rollout backend: transformers'));
  record('preflight states which adapter the run starts from',
         out.includes('training/adapter') && out.includes('written back'));
  record('preflight reports dataset shape and columns but no content',
         out.includes('240 example(s)') && out.includes('prompt schema'));
  await page.selectOption('#rf-pick-preset', 'voice');
  record('changing the objective revokes the fit',
         (await page.$eval('#rf-start-btn', (e) => e.disabled)) === true);

  // ---- 10. the job panel with no run says so, and draws nothing
  record('with no run the metrics block is hidden',
         (await page.$eval('#rf-metrics', (e) => e.hidden)) === true);
  record('with no run there is no sparkline in the document',
         (await page.$$('#reinforce svg.rf-spark')).length === 0);

  // ---- 11. a reinforcement run mid-flight
  status = RL_STATUS;
  await page.evaluate(() => { window.__rf_forcePoll = true; });
  await page.reload({ waitUntil: 'load' });
  await page.waitForFunction(
    () => !document.getElementById('rf-metrics').hidden, null, { timeout: 15000 });
  const metricRows = await page.$$eval('#rf-metrics-tab tbody tr', (rows) => rows.map((r) => ({
    name: r.children[0].textContent, value: r.children[1].textContent,
    hasSpark: !!r.querySelector('svg.rf-spark'),
  })));
  const names = metricRows.map((r) => r.name).join(' | ');
  record('an RL run shows reward, spread, KL and completion length', metricRows.length === 4, names);
  record('the reward row is labelled as a reading of the scoring functions, not of the model',
         names.includes('weighted sum'), names);
  record('no validation-loss row appears for an objective that has none',
         !names.includes('validation loss'));
  record('every RL metric with enough points draws a series',
         metricRows.every((r) => r.hasSpark));

  // The assertion this whole block exists for: a series must admit its window.
  const caps = await page.$$eval('#rf-metrics-tab .rf-note', (n) => n.map((e) => e.textContent));
  record('every series names the step range it was drawn from',
         caps.length >= 4 && caps.every((c) => /steps 14–18 of 40/.test(c)),
         caps[0]);
  record('every series admits it is a tail of the log, not the whole run',
         caps.every((c) => c.includes('not the whole run')));
  const mnote = await page.$eval('#rf-metrics-note', (e) => e.textContent);
  record('a rising reward is explicitly not claimed to be a better model',
         mnote.includes('not by itself evidence the model improved'));

  // ---- 12. the job identity table carries the objective and the starting adapter
  const jobText = await page.$eval('#rf-job', (e) => e.textContent);
  record('the job table names the objective and the schema',
         jobText.includes('reinforcement') && jobText.includes('prompt'));
  record('the job table names the adapter the run started from',
         jobText.includes('training/adapter'));
  record('training loss is not duplicated between the two tables',
         !jobText.includes('training loss'));

  // ---- 13. the running dot is a real state, and nothing animates
  const dot = await page.$eval('#rf-dot', (e) => ({
    state: e.getAttribute('data-state'),
    anim: getComputedStyle(e).animationName,
    trans: getComputedStyle(e).transitionProperty,
  }));
  record('the state dot reflects the real state and does not animate',
         dot.state === 'running' && (dot.anim === 'none' || !dot.anim),
         `state=${dot.state} animation=${dot.anim}`);

  // ---- 14. CSS: nothing truncates. This is a licence condition, not a preference.
  const clipped = await page.evaluate(() => {
    const bad = [];
    document.querySelectorAll('#reinforce *').forEach((el) => {
      const s = getComputedStyle(el);
      if (s.textOverflow === 'ellipsis') bad.push(el.tagName + '.' + el.className + ' ellipsis');
      // A fixed height with hidden overflow on a text node clips just as effectively.
      if (s.overflowY === 'hidden' && s.display !== 'none' && el.scrollHeight > el.clientHeight + 2
          && el.matches('td, dd, p, li')) {
        bad.push(el.tagName + '.' + el.className + ' overflow-clipped');
      }
    });
    return bad;
  });
  record('no element in the panel truncates its text', clipped.length === 0,
         clipped.slice(0, 3).join('; '));

  // ---- 15. 390px: wide tables scroll in their own container, the body never does
  await page.setViewportSize({ width: 390, height: 900 });
  await page.waitForTimeout(150);
  const overflow = await page.evaluate(() => ({
    body: document.documentElement.scrollWidth - document.documentElement.clientWidth,
    offenders: Array.from(document.querySelectorAll('#reinforce *'))
      .filter((el) => {
        const r = el.getBoundingClientRect();
        return r.width > 0 && r.right > window.innerWidth + 1 &&
               !el.closest('.rf-scroll') && !el.matches('.rf-scroll');
      })
      .slice(0, 5).map((el) => el.tagName + '.' + el.className),
  }));
  record('the page body does not scroll horizontally at 390px', overflow.body <= 1,
         `overflow ${overflow.body}px`);
  record('nothing outside a scroll container spills past 390px',
         overflow.offenders.length === 0, overflow.offenders.join('; '));
  const scrollers = await page.$$eval('#reinforce .rf-scroll', (els) =>
    els.map((e) => ({ x: getComputedStyle(e).overflowX, wide: e.scrollWidth > e.clientWidth })));
  record('every wide table sits in an overflow-x:auto container',
         scrollers.length >= 4 && scrollers.every((s) => s.x === 'auto'),
         `${scrollers.length} containers`);

  // ---- 16. the sparkline does not blow out the layout at 390px
  const sparkFit = await page.$$eval('#reinforce svg.rf-spark', (els) =>
    els.every((e) => e.getBoundingClientRect().right <= window.innerWidth + 1 ||
                     !!e.closest('.rf-scroll')));
  record('the sparklines stay inside the viewport at 390px', sparkFit);

  // ---- 17. no JS errors, ever. A syntax error here blanks the whole panel silently.
  record('the panel raised no JavaScript errors', consoleErrors.length === 0,
         consoleErrors.slice(0, 2).join(' | '));

  // ---- 18. the DEPLOYED page, not the fragment above.
  //
  // Everything to this point builds its own document around `page.html`. That is the right
  // way to test the panel's behaviour and it cannot see the one thing `tools/build/build_reinforce.py`
  // can break: that generator unwraps the fragment's `<section><div class="wrap">` because the
  // site shell already opens both, and it has to carry `id="reinforce"` through the unwrap.
  // Every selector in the fragment's stylesheet is written `#reinforce .rf-*`, so losing the id
  // renders the whole panel UNSTYLED rather than broken -- it still has all its text, so a
  // content assertion passes and a human skimming a screenshot might not notice either.
  //
  // The generator was written against the supervised-only fragment and this branch replaced it,
  // so "it worked once, by hand, on the old page" is the only evidence that existed. Read a
  // computed colour instead: `.rf-lab-measured` is green only if the scoped sheet resolved.
  const DEPLOYED = join(REPO, 'site/reinforce.html');
  if (existsSync(DEPLOYED)) {
    const deployErrors = [];
    const dp = await browser.newPage({ viewport: { width: 1280, height: 1000 } });
    dp.on('pageerror', (e) => deployErrors.push(String(e)));
    // The real page pulls /reinforce.js and the live API; neither is up here, and neither is
    // what this assertion is about. Serve the script and let the API calls fail -- the
    // stylesheet is inline in the markup and resolves with no network at all.
    await dp.route('**/reinforce.js', (r) =>
      r.fulfill({ contentType: 'application/javascript', body: SCRIPT }));
    await dp.route('**/api/train/**', (r) => r.fulfill({ status: 503, json: { detail: 'off' } }));
    await dp.route('**/deployed/**', (r) => r.fulfill({
      contentType: 'text/html', body: readFileSync(DEPLOYED, 'utf8') }));
    await dp.goto('http://127.0.0.1:9/deployed/reinforce.html', { waitUntil: 'load' });

    const scoped = await dp.evaluate(() => {
      const root = document.getElementById('reinforce');
      const lab = document.querySelector('#reinforce .rf-lab-measured');
      return {
        hasRoot: !!root,
        // A nested .wrap doubles the page's side padding; the unwrap exists to prevent it.
        nestedWrap: !!root?.closest('.wrap') && !!root?.querySelector('.wrap'),
        labColour: lab ? getComputedStyle(lab).color : null,
      };
    });
    record('the deployed page keeps id="reinforce" through the unwrap', scoped.hasRoot);
    record('the deployed page resolves its #reinforce-scoped stylesheet',
           scoped.labColour !== null && scoped.labColour !== 'rgb(232, 232, 232)',
           `.rf-lab-measured computes to ${scoped.labColour}`);
    record('the unwrap did not leave a .wrap nested inside a .wrap', !scoped.nestedWrap);
    record('the deployed page raised no JavaScript errors', deployErrors.length === 0,
           deployErrors.slice(0, 2).join(' | '));
    await dp.close();
  } else {
    record('the deployed page keeps id="reinforce" through the unwrap', false,
           'site/reinforce.html is absent -- run tools/build/build_reinforce.py');
  }

  await browser.close();

  const failed = results.filter((r) => !r.ok);
  console.log(`\n${results.length - failed.length}/${results.length} passed`);
  if (failed.length) {
    console.log('failed:\n  ' + failed.map((f) => f.name).join('\n  '));
    process.exit(1);
  }
}

main().catch((e) => { console.error(e); process.exit(1); });
