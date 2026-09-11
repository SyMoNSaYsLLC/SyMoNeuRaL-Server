# PERSONA / LORA WEIGHT RESTORATION

**Date:** 2026-09-03
**Executor:** Claude — sole mutation owner, this task only
**Authoriser:** Garrett (sole task authoriser)
**Gate:** SYMONEURAL TASK GATE — PERSONA / LORA WEIGHT RESTORATION

**VERDICT: PERSONA / LORA RESTORATION VERIFIED**

No activation gate is required. The already-running API recognised the restored adapter
without any restart, and the inference engine was launched with the restored payload.

---

## 1. Starting checkpoint and control state

| Field | Expected by gate | Measured | Match |
|---|---|---|---|
| Repository | `/home/google/Symoneural` | same | ✅ |
| Branch | `main` | `main` | ✅ |
| HEAD | `5427f2a5f5ec40761d6d957fab810644bae6292a` | identical | ✅ |
| Subject | `docs: establish canonical project authorities` | identical | ✅ |
| Staged | 0 | 0 | ✅ |
| Stash | 0 | 0 | ✅ |

`git status --short` at start matched the gate's reconciled state exactly, all ten entries:

```
 M .claude/HANDOVER.md
 M .claude/settings.local.json
 M PROJECT-TASKS.md
 M backend/server.py
 M backend/apps/ROSTER.md
 M ops/registry/EXPORTS.md
 M ops/registry/MEASUREMENTS.md
?? backend/apps/coders/
?? site/coders.html
?? tests/coders_smoke.mjs
```

### Control boundary

Codex holds **no** mutation authority and none was contended for:

- No process has a working directory inside `/home/google/Symoneural` other than the API
  (pid 1505), the gateway (pid 1538), and this session's own shell and `claude` process.
- No `.git/index.lock` or `.git/HEAD.lock` exists — no git operation in flight.
- HEAD remained at `5427f2a5` for the whole task.

The Codex **Desktop application** is running (Electron renderers, `codex app-server`,
`codex-code-mode-host`). Those are the GUI application's own processes; none holds a repo
working directory, a git lock, or a GPU compute context. This is consistent with
`Codex: STOPPED — MUTATION AUTHORITY: NONE`, and it is recorded here so the distinction is
explicit rather than assumed.

---

## 2. Vault exact identity

| Field | Value |
|---|---|
| Path | `/home/google/Downloads/symoneural-vault-2026-08-19-v2.tar.gz` |
| Owner | `google:google` |
| Mode | **600** |
| Bytes | **398,369,206** |
| SHA-256 | `86aa9d85f7894640ace5e21b59aff2549b10bab72482dd41d8a6bbdab117644f` |
| mtime | 2026-08-19 17:53:59 −0400 |

The size and digest match the values recorded by the completed home-cleanup audit. The
archive was **not** modified, renamed, moved, or recompressed; its SHA-256 was re-measured
after extraction and after adoption and is unchanged.

---

## 3. Archive integrity

```
gzip -t  → OK
tar -tzf → readable, 393 members enumerated
```

---

## 4. Relevant archive members

Twelve adapter/LoRA members exist. All are `-rw------- google/google` inside the archive:

| Member | Bytes | mtime |
|---|---:|---|
| `.symoneural-full/training/adapter/symoneural-lora.gguf` | 80,767,680 | 2026-08-16 16:36 |
| `.symoneural-full/training/adapter/adapter_model.safetensors` | 161,533,192 | 2026-08-16 16:35 |
| `.symoneural-full/training/adapter/tokenizer.json` | 11,421,892 | 2026-08-16 16:35 |
| `.symoneural-full/training/adapter-qwen36/adapter_model.safetensors` | 200,384,784 | 2026-08-18 09:27 |
| `.symoneural-full/training/adapter-qwen36/tokenizer.json` | 19,989,325 | 2026-08-18 09:27 |
| `.symoneural-full/run/reinforce/adapters/20260817-102314-8e6000/adapter_model.safetensors` | 10,107,280 | 2026-08-17 10:23 |
| `…/20260817-102314-8e6000/tokenizer.json` | 11,421,892 | 2026-08-17 10:23 |
| `…/20260817-102314-8e6000/{adapter_config.json, chat_template.jinja, README.md, run-manifest.json, tokenizer_config.json}` | small | 2026-08-17 10:23 |

**Correction to the gate's summary, verified rather than assumed as instructed.** The gate
lists the 27B adapter as `training/adapter/adapter-qwen36/adapter_model.safetensors`
(nested inside `adapter/`). The real archive path is
`training/adapter-qwen36/adapter_model.safetensors` — a **sibling** of `adapter/`, not a
child. This matters because it is also the destination path, and it agrees with
`control/models/models-adapters.sh:7`, which iterates `training/adapter` and
`training/adapter-qwen36` as two peer directories.

### In-archive identity evidence (Phase A item 11)

The vault carries its own `MANIFEST.md`. It records **no per-file SHA-256**, but it does
record aggregate sizes that reconcile exactly with the members above:

| MANIFEST.md claim | Sum of archived members | Match |
|---|---|---|
| "`training/adapter/` (243 M)" | 80,767,680 + 161,533,192 + 11,421,892 = 253,722,764 B = **242.0 MiB** | ✅ |
| "`training/adapter-qwen36/` (211 M)" | 200,384,784 + 19,989,325 = 220,374,109 B = **210.2 MiB** | ✅ |
| "Reinforce outputs `…20260817-102314-8e6000` (21 M)" | 10,107,280 + 11,421,892 + configs ≈ **21.6 MiB** | ✅ |

`MANIFEST.md` also states the trained weights are "Proprietary to SymonSays LLC, all rights
reserved" and "derived from Apache-2.0 bases, under no obligation to publish" — consistent
with the mode-600 handling applied throughout this task.

Identity therefore rests on four independent readings, not on the gate's summary:
1. archive member sizes;
2. `MANIFEST.md` aggregate sizes inside the same archive;
3. exact byte counts recorded in the repository's own test suite (§6);
4. GGUF architecture read with the application's own parser (§6).

---

## 5. Classification of every candidate

Per-payload detail is in `LORA-PAYLOADS.tsv`. Summary:

| Payload | Class | Action |
|---|---|---|
| `training/adapter/symoneural-lora.gguf` | **REQUIRED_CURRENT** | **RESTORED** |
| `training/adapter/adapter_model.safetensors` | **REINFORCE_CURRENT** | **RESTORED** |
| `training/adapter-qwen36/adapter_model.safetensors` | **REINFORCE_CURRENT** | **RESTORED** |
| `training/adapter/tokenizer.json` | **UNKNOWN_STOP** | not restored |
| `training/adapter-qwen36/tokenizer.json` | **UNKNOWN_STOP** | not restored |
| `run/reinforce/adapters/20260817-102314-8e6000/adapter_model.safetensors` | **HISTORICAL** | not restored |

---

## 6. Current consumer and destination evidence

### The primary required payload — `symoneural-lora.gguf`

Proven from current source, not from documentation:

```
backend/server.py:237   CHAT_ADAPTER = ROOT / "training" / "adapter" / "symoneural-lora.gguf"
backend/server.py:306   if not CHAT_ADAPTER.exists(): return False        # inside adapter_applies()
backend/server.py:309   adapter_arch = _gguf_arch(CHAT_ADAPTER)
backend/server.py:312   return model_arch == adapter_arch
backend/server.py:1320  if adapter_applies():
backend/server.py:1321      argv += ["--lora", str(CHAT_ADAPTER)]
backend/server.py:2212  spec=CHAT_MODEL_LABEL + (" + persona adapter" if adapter_applies() else " · Q4_K_M")
```

**Exact expected destination:** `/home/google/Symoneural/training/adapter/symoneural-lora.gguf`.

**Architecture gate — the discriminator for this verdict.** `adapter_applies()` returns True
only when the adapter's GGUF architecture equals the chat model's. Both were read with
api.py's own `_gguf_arch`, extracted from the source by AST and executed unmodified:

```
CHAT_MODEL  arch = 'qwen2'   backend/models/llm/symon-1.0-7b-q4_k_m.gguf
staged LoRA arch = 'qwen2'   staged symoneural-lora.gguf
=> adapter_applies() would return True
```

Corroborated by `training/adapter/adapter_config.json`, already on disk, which declares
`base_model_name_or_path: "Qwen/Qwen2.5-7B-Instruct"` — the same base as `CHAT_MODEL`.

**Dynamic or activation-requiring?** Dynamic. Neither `_gguf_arch` nor `adapter_applies()`
carries any caching decorator; both read the filesystem on every call. The adapter enters the
engine as a launch argument, and `symoneural-llm` was **not resident** at restoration time
(governor: 0 MiB compute, no compute apps), so the next chat request launched it fresh with
`--lora`. No systemd unit required restarting, reloading, starting or stopping, and none was.

### Secondary payloads

`training/adapter/adapter_model.safetensors` — `reinforce/jobs.py:87` declares
`SHIPPED_ADAPTER = ROOT / "training" / "adapter"`. Consumers: `test_reinforce.py:1009`,
`test_coder.py:183` ("adapter weights"), `test_cleanroom.py:246`,
`tools/lib/modelops_inventory.py:148`. **`test_reinforce.py:546-549` records the exact figure:**
"`adapter_model.safetensors` is **161,533,192 bytes**, which is 40,370,176 fp32 parameters
plus a 52 KB safetensors header" — identical to the archived member, and consistent with
`adapter_config.json`'s `r: 16` over seven target modules.

`training/adapter-qwen36/adapter_model.safetensors` — destination declared by
`control/models/_models_common.sh:49` and `control/models/models-adapters.sh:7` (both iterate
the two peer adapter directories and count payload files), and written by
`training/train_lora.py:410` for the 27B path. `test_coder.py:246` describes it as "a real
**200 MB** LoRA sitting beside it in this repo" — the archived member is 200,384,784 bytes.

### Why the reinforce output is HISTORICAL and was not restored

Three current source statements, and the archive's own manifest, all agree it has no serving
role:

```
reinforce/jobs.py:81-84  OUTPUT_DIR = JOBS_DIR / "adapters"
                         "Where finished adapters land. NOT `training/adapter/` -- that
                          directory holds the shipped [adapter]"
reinforce/routes.py:55   "It does not promote a run to the serving adapter."
reinforce/runner.py:782  "Nothing here promotes a run to the serving adapter."
```

Its own `run-manifest.json` states: *"this adapter is PEFT safetensors. The chat surface
loads a GGUF adapter, so it is not served until somebody converts it deliberately. Nothing
here promotes a run to the serving adapter."* The manifest also shows it is a `"smoke"`
preset run — 8 steps, rank 8, `q_proj`/`v_proj` only, 2,523,136 trainable params,
`val_loss 4.619`. That is a pipeline smoke test, not a production adapter. A grep for
`reinforce/adapters` across all Python, shell and JSON found **no inference loader**.

### Why the tokenizers were not restored

`training/adapter/tokenizer.json` and `training/adapter-qwen36/tokenizer.json` are not weight
payloads and are **not in this gate's authorized candidate list**. A grep for consumers of
either path returned empty. They are left staged and unrestored.

Recorded for a follow-up gate: `.gitignore:49` and `.gitignore:50` name both paths
explicitly, which is current project configuration declaring those exact destinations, and
`MANIFEST.md` counts them inside its "243 M" / "211 M" figures. So the two adapter
directories remain **incomplete relative to the vault manifest** by 11,421,892 and
19,989,325 bytes respectively. Nothing measured in this task needs them, but authorizing
them would be a one-line extension rather than a new investigation.

---

## 7. Staged identities

Staging root: `/home/google/symoneural-lora-restore-staging-20260903/` (mode 700, outside the
canonical repository, on the same filesystem — device `66308` — as the destinations).

Extracted with `tar -xpzf` naming only the relevant members. The full vault was **not**
extracted: 8 of 393 members were taken.

| Staged member | Bytes | SHA-256 | Mode |
|---|---:|---|---|
| `training/adapter/symoneural-lora.gguf` | 80,767,680 | `29a893c5e208fa88be06dec076372fa362ea30d3a9319a1a0d9230e991e8dcd7` | 600 |
| `training/adapter/adapter_model.safetensors` | 161,533,192 | `ce10b0c6b71762fa77863c3fb4100fecd2df3b37c8f41bbf846b277e5826eb6f` | 600 |
| `training/adapter/tokenizer.json` | 11,421,892 | `3fd169731d2cbde95e10bf356d66d5997fd885dd8dbb6fb4684da3f23b2585d8` | 600 |
| `training/adapter-qwen36/adapter_model.safetensors` | 200,384,784 | `c7a5b67cf37dbcddecfdf02d230a8ae9c9280fe87f609c6c6707ab777f752fd0` | 600 |
| `training/adapter-qwen36/tokenizer.json` | 19,989,325 | `06b9509352d2af50381ab2247e083b80d32d5c0aba91c272ca9ff729b6a0e523` | 600 |
| `run/reinforce/adapters/20260817-102314-8e6000/adapter_model.safetensors` | 10,107,280 | `71870cc5eb4732b43ff664afefae62c55fb50d257d52280a86444b3bb3d2c665` | 600 |
| `MANIFEST.md` | 5,677 | (identity evidence, §4) | 600 |
| `…/20260817-102314-8e6000/run-manifest.json` | 1,659 | (identity evidence, §6) | 600 |

Every staged size equals its archive-listed size, and `tar -xp` preserved mode 600 — verified
with `stat`, not assumed, because extraction as a non-root user can otherwise apply the
umask and land at 664.

---

## 8. Restored destinations

Pre-adoption overwrite check: **all three destinations were ABSENT**, so nothing
non-identical was overwritten. Both parent directories already existed (`training/adapter`
and `training/adapter-qwen36`, mode 775) and were declared by current configuration, so **no
directory was created**.

Adoption was `mv` within one filesystem — an atomic rename, so the bytes were never
rewritten.

```
/home/google/Symoneural/training/adapter/symoneural-lora.gguf              80,767,680
/home/google/Symoneural/training/adapter/adapter_model.safetensors        161,533,192
/home/google/Symoneural/training/adapter-qwen36/adapter_model.safetensors 200,384,784
                                                                   total  442,685,656
```

---

## 9 & 10. Post-restoration identity — staged/adopted SHA-256 equality

| Adopted path | SHA-256 | Equals staged |
|---|---|---|
| `training/adapter/symoneural-lora.gguf` | `29a893c5e208fa88be06dec076372fa362ea30d3a9319a1a0d9230e991e8dcd7` | ✅ |
| `training/adapter/adapter_model.safetensors` | `ce10b0c6b71762fa77863c3fb4100fecd2df3b37c8f41bbf846b277e5826eb6f` | ✅ |
| `training/adapter-qwen36/adapter_model.safetensors` | `c7a5b67cf37dbcddecfdf02d230a8ae9c9280fe87f609c6c6707ab777f752fd0` | ✅ |

Chain closed end to end: vault member → staged bytes → adopted bytes, identical at every
step, with the vault's own digest unchanged afterwards.

---

## 11. Payload permissions

All three adopted payloads are **mode 600**, owner `google:google`, original mtimes
preserved:

```
600  training/adapter/symoneural-lora.gguf                 (Aug 16 16:36)
600  training/adapter/adapter_model.safetensors            (Aug 16 16:35)
600  training/adapter-qwen36/adapter_model.safetensors     (Aug 18 09:27)
```

This is deliberately stricter than the 664 config files sitting beside them:
`control/models/models-adapters.sh` states adapter weights are protected and "never printed
or exported", and `MANIFEST.md` marks them proprietary. Mode was verified after adoption, not
inferred from the extraction flags.

---

## 12. Application recognition — dynamic, no activation required

The API process was **not restarted, reloaded, started or stopped** at any point. It picked
up the restored adapter immediately:

| Reading | Before adoption | After adoption |
|---|---|---|
| `/api/status` → `chat.spec` | `SymonChat S1-7B · Q4_K_M` | **`SymonChat S1-7B + persona adapter`** |
| `/api/status` → `train.state` | `offline` | **`ready`** |
| `/api/status` → `train.detail` | `no adapter built` | **`adapter loaded · for model/adapter tuning`** |

Both flips are direct readings of `adapter_applies()` (api.py:2186-2189, :2212) inside the
already-running process, so they prove the function now returns True on live disk state.

**No activation gate is required.** No affected unit, no command to authorize.

---

## 13. Chat verification — one bounded request through the governed path

`POST /api/chat`, prompt `"In one sentence, what is SyMoNeuRaL?"`, temperature 0.3.
**HTTP 200**, 4.62 s wall clock including a cold engine load.

Final SSE event:

```json
{"done": true, "tokens": 33, "seconds": 0.38, "tok_per_s": 87.8,
 "model": "symon-1.0-7b-q4_k_m", "adapter": true}
```

`"adapter": true` is the serving path's own assertion, not a status-page inference.

### Primary runtime proof — the live engine's argv

Captured from `/proc/124349/cmdline` **while the process was running**:

```
/home/google/Symoneural/engines/symoneural-llm/build/bin/symoneural-llm
-m /home/google/Symoneural/backend/models/llm/symon-1.0-7b-q4_k_m.gguf
-ngl 99 --host 127.0.0.1 --port 8081 -c 65536 --no-warmup -cb -np 2
-md /home/google/Symoneural/backend/models/llm/symon-1.0-draft-0.5b-q4_k_m.gguf
-ngld 99 --spec-draft-n-max 2
--lora /home/google/Symoneural/training/adapter/symoneural-lora.gguf
```

The restored payload was actually passed to the inference engine. This is the strongest
available proof because the engine is launched with `stdout`/`stderr` set to `DEVNULL`
(api.py:1329-1330), so its own "loaded lora adapter" line is discarded and cannot be read.

### The missing-adapter branch was not taken

`api.log`, new lines only (marked at 6,195 before the request):

```
2026-09-03 05:13:06 INFO  starting chat surface
2026-09-03 05:13:10 INFO  chat surface up
```

api.py:1322-1326 emits `persona adapter NOT applied: …` when the adapter exists but its
architecture mismatches. Measured unambiguously against the whole file rather than inferred
from a tail-scoped grep:

```
wc -l   run/api.log                    → 6197
grep -c "NOT applied"     run/api.log  → 0
grep -c "persona adapter" run/api.log  → 0
```

Zero occurrences in all 6,197 lines. Its absence, next to a launch that carries `--lora`, is
affirmative evidence the adapter was accepted rather than refused. Note that the argv in the
preceding subsection — not this absence — is the primary proof; a log line that has never
fired is corroboration, not the load-bearing evidence.

**Method note for the next executor: the engine binary is house-named `symoneural-llm`, not
`llama-server`.** The telemetry sampler's `pgrep -f "[l]lama-server"` therefore matched
nothing and captured no argv. The argv above was captured by reading
`/proc/124349/cmdline` directly while the process was still alive, after the compute
telemetry revealed the real process name. Anyone repeating this should match
`symoneural-llm`.

### On persona quality — deliberately not claimed as proof

The model replied: *"A small company building custom local AI hardware and the tools to run
on it. We make the machines and the software that runs on them, and we sell both."* It is
coherent and on-brand, but **that is not offered as evidence of adapter loading.** The proof
is the `--lora` argv, `"adapter": true`, the absence of the NOT-applied warning, and the two
status flips. A response "sounding like Symon" would prove nothing.

---

## 14. GPU / governor observations

**Before** — lock free, engine not resident, zero AI compute:

```
resident surface   sigil (not running -- stale marker)
lock               free
vram used          1077 MiB  (whole card, desktop included)
  of which compute 0 MiB
nvidia-smi --query-compute-apps → no rows
```

**Lease cycle** — `run/governor.log`, new lines only (marked at 6,773):

```
2026-09-03 05:13:06  wait     'chat' wants the card
2026-09-03 05:13:06  evict    'sigil' recorded but no run is active -- treating as stale
2026-09-03 05:13:06  drain    settled at 0 MiB compute after 0s (floor 1024 MiB; card 1027 MiB incl. desktop)
2026-09-03 05:13:06  acquire  'chat' holds the card -- 14832 MiB free, waited 0s
2026-09-03 05:13:11  release  'chat' releasing
```

Full `wait → evict → drain → acquire → release`. The eviction was of a **stale marker**, so
no live tenant was displaced.

**During** — per-process compute VRAM, sampled every 0.5 s across the request:

```
05:13:07  symoneural-llm (pid 124349)   222 MiB   ← CUDA context init
05:13:09  symoneural-llm (pid 124349)  4392 MiB   ← weights loading
05:13:10  symoneural-llm (pid 124349)  9524 MiB   ← peak
05:13:10+ symoneural-llm (pid 124349)  8330 MiB   ← steady resident
```

**After** — lock released, one controlled workload resident:

```
resident surface   chat (running)
lock               free
vram used          9365 MiB   of which compute 8330 MiB
vram free          6494 MiB
compute apps       124349  symoneural-llm  8330 MiB
```

**Compute versus graphics, kept distinct as the gate requires.** The 1,027–1,077 MiB present
throughout is the KDE desktop's **graphics** (`G`) contexts — plus the ChatGPT/Codex desktop
app and browsers. `nvidia-smi --query-compute-apps` reports **no** rows for any of them, and
the governor's own `drain` reads compute at 0 MiB while the whole card shows ~1 GB. None of
that is AI compute and none is counted as such here.

**The card is in a different state than at task start, and that is expected — stated plainly
rather than glossed.** `symoneural-llm` was **not resident** before this task (0 MiB compute,
no compute apps); it **is resident now**, holding 8,330 MiB. That transition is the direct
result of the one authorized chat request, not something this task engineered, and it is the
documented design in `ENGINEERING.md`: "Hold the lock for a job, never for a process
lifetime. Residency (weights loaded) and work (using the card) are separate."

**This is residency, not a leak, and there is no second uncontrolled workload.** Exactly one
compute process exists, it is the governed chat surface, and it holds weights with the
**governor lock released** — the governor itself reports `resident surface chat (running)` /
`lock free`. The next image, sigil or training request will evict it through the normal
governor path (`evict → drain → acquire`), exactly as this task's own lease evicted the stale
`sigil` marker. No manual intervention is needed to return the card.

Nothing was killed and no process was cycled — deliberately, since cycling the engine would
have been the restart this gate prohibits. Leaving it resident is the correct end state, and
§16 item 4 records it as a side effect of the authorized verification.

---

## 15. Candidates deliberately not restored

| Payload | Class | Reason | Where it is now |
|---|---|---|---|
| `run/reinforce/adapters/20260817-102314-8e6000/adapter_model.safetensors` | HISTORICAL | Three source statements plus its own `run-manifest.json` confirm nothing promotes it to serving; it is a `"smoke"` preset output, 8 steps, rank 8, `val_loss 4.619`. No inference consumer exists. | staged, unrestored |
| `training/adapter/tokenizer.json` | UNKNOWN_STOP | Not a weight payload, not in this gate's candidate list, no located consumer. `.gitignore:49` does declare the destination. | staged, unrestored |
| `training/adapter-qwen36/tokenizer.json` | UNKNOWN_STOP | Same reasoning; `.gitignore:50` declares the destination. | staged, unrestored |

All three remain at mode 600 in the external staging root and are recoverable from the vault
in any case. Nothing was restored on the strength of a guess.

---

## 16. Exact mutations performed

Inside the canonical repository — **three files created, nothing else**:

1. `training/adapter/symoneural-lora.gguf` (80,767,680 B, mode 600)
2. `training/adapter/adapter_model.safetensors` (161,533,192 B, mode 600)
3. `training/adapter-qwen36/adapter_model.safetensors` (200,384,784 B, mode 600)

All three are gitignored — `.gitignore:48 *.gguf` and `.gitignore:47 *.safetensors` — so
adoption is invisible to `git status`, verified with `git check-ignore -v` **before** adoption
rather than discovered afterwards. No directory was created; both parents already existed.

Side effects of the one authorized verification request:

4. `symoneural-llm` (pid 124349) launched by the API and left **resident**, holding 8,330 MiB
   of compute with the governor lock released. This is ordinary chat-surface behaviour, not a
   state change this task engineered.
5. Log appends: two `run/api.log` lines, five `run/governor.log` lines.

Outside the canonical repository:

6. `/home/google/symoneural-lora-restore-staging-20260903/` — the external staging root
   (mode 700), retaining the three unrestored payloads plus `MANIFEST.md` and
   `run-manifest.json` as identity evidence.
7. `/home/google/symoneural-lora-restoration-20260903/` — this evidence root.
8. Two scratchpad files (a telemetry sampler and its output) outside `/home/google`.

No other canonical filesystem mutation was performed.

---

## 17. Prohibited actions not performed

- **No source-code mutation.** `backend/server.py` untouched — it remains the pre-existing ` M`
  from the reconciled tree. Its `_gguf_arch` was read and executed in a **scratch namespace
  via AST extraction**, which does not modify the file.
- **No adapter configuration changed.** `adapter_config.json` in both directories was read
  only. Nothing was altered to make a restored payload fit.
- **No documentation mutation.** `ProjectStatus.md` and `SyMoNSaysLLC.md` were read only.
  `AGENTS.md`, `PROVENANCE.json`, fetch scripts, `docs/` — all untouched.
- **No service, systemd, or Git configuration change.** No restart, reload, start or stop.
- **No Git operation** — nothing staged, committed, amended, reset, restored, cleaned or
  stashed. No push.
- **The vault was not altered.** Not moved, deleted, renamed or recompressed; digest
  re-verified identical after extraction and after adoption.
- **The full vault was not extracted** — 8 of 393 members.
- **No substitute downloaded. No adapter regenerated or retrained.**
- **No non-identical payload overwritten** — all three destinations were verified absent
  first.
- **No process killed. No second uncontrolled CUDA workload introduced.**
- **All existing reconciled working-tree changes preserved.**
- **Home cleanup not begun.** Studio not begun. Symon Coder not begun. No unrelated source
  defect repaired. No unrelated model restored. Codex not dispatched.

---

## 18. Final repository status

| Field | Value | vs. start |
|---|---|---|
| HEAD | `5427f2a5f5ec40761d6d957fab810644bae6292a` | unchanged |
| Staged | 0 | unchanged |
| Stash | 0 | unchanged |
| `git status --short` | the same ten entries | **unchanged** |

The 442,685,656 bytes of restored payload land in gitignored paths, so restoration is
invisible to git — as the project intends for adapter weights.

---

## 19. Vault retained and protected

`/home/google/Downloads/symoneural-vault-2026-08-19-v2.tar.gz` is **retained, unmodified,
mode 600**, digest `86aa9d85…` re-verified after all work.

Its custody classification for the pending home-cleanup execution is **unchanged: KEEP /
DURABLE_EVIDENCE**, and it must stay so until a separately authorized custody task
establishes an equivalent or stronger protected recovery location. It remains the recovery
source for the three payloads restored here and the only located copy of the three that were
not.

One honest note on its status: it is no longer the *only* copy of the three restored payloads
— those now also exist in the working tree. But the working tree is not a custody location:
the payloads are gitignored, so they are not in git history and a repository re-clone would
not carry them. The vault is still the only durable copy of everything in §4.

---

## 20. Does ProjectStatus.md now require a state update?

**Yes — one line.** `ProjectStatus.md:132`, in the "Remaining work by area" table:

> | Models | rembg and Whisper; owner-qualified training/LoRA work. Restored upstream base
> weights are not trained first-party model evidence. |

The second sentence remains true and should stay: restored upstream base weights (the
Image/Sigils FLUX payloads) are indeed not first-party model evidence. What is now stale is
that the row gives no indication the **first-party trained persona adapter is present and
applied**. After this task the box holds `training/adapter/` with its GGUF and PEFT weights,
and the chat surface reports `+ persona adapter` and serves with `--lora`.

**This does not complete the training milestone, and the reconciliation must not say it
does.** The standing rule requires training data/configuration, model/adapter artifacts, *and
held-out evaluation evidence* before that claim. This task restored **artifacts** from
custody — it performed no training and produced no held-out evaluation. The corpus
(`training/corpus.jsonl`) and configuration exist; evaluation evidence does not. A correct
reconciliation records "first-party persona adapter restored from custody and verified
applied at serving time; held-out evaluation still outstanding".

**Not edited under this gate**, as instructed. Recorded here for the next authorized
documentation/checkpoint commit.

---

## 21. Final verdict

**PERSONA / LORA RESTORATION VERIFIED**

The three payloads proven to belong to current SyMoNeuRaL state are restored to their exact
declared destinations at mode 600, with SHA-256 identity closed from vault member through
staging to adoption and the vault's own digest unchanged. Identity rests on four independent
readings — archive sizes, the vault's own `MANIFEST.md` aggregates, exact byte counts recorded
in the repository's test suite, and the GGUF architecture read with the application's own
parser.

Recognition is dynamic and required no activation: the unrestarted API flipped
`chat.spec` to `+ persona adapter` and `train` to `ready / adapter loaded`, and one bounded
governed chat request returned HTTP 200 with `"adapter": true` while the live engine's argv
carried `--lora …/training/adapter/symoneural-lora.gguf`. The `persona adapter NOT applied`
branch was never taken. The governor took and released a clean lease, exactly one compute
context exists, and no workload leaked.

Three candidates were deliberately not restored and are classified rather than guessed: the
reinforce smoke-run output as HISTORICAL on the strength of three source statements and its
own manifest, and the two `tokenizer.json` files as UNKNOWN_STOP for lacking both a located
consumer and gate authorization.

`ProjectStatus.md:132` requires reconciliation in a future documentation gate, and the wording
must stop short of claiming the training milestone — restoring artifacts from custody is not
training, and no held-out evaluation evidence exists.

---

## Control state at stop

```
Claude:  STOPPED — MUTATION AUTHORITY: NONE
Codex:   STOPPED — MUTATION AUTHORITY: NONE
Garrett: SOLE TASK AUTHORIZER
```

Home cleanup not begun. Studio not begun. Symon Coder not begun. Production not restarted.
Nothing committed. `ProjectStatus.md` and `SyMoNSaysLLC.md` not edited. Codex not dispatched.
