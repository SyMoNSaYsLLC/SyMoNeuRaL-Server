# Sept 4 — Runtime First-Party Migration

> **REDACTED COPY.** Customer identifiers, credential values and infrastructure details masked as `*****`. No secret value appears in this file; every credential is referred to by NAME only.

## Continues from

`a4-shared-service-map-ruling.md`. That window ended at HEAD `698bef87` with **nothing enabled, started, configured, built or modified**.

**This window is the opposite.** HEAD `698bef87` → **`b4d701cc`**, **20 commits**, engines built, services stopped, configuration relocated, one directory deleted by the owner. Everything below was measured on the box on 2026-09-04.

---

## 1. What changed, in one line

**Four of five inference runtimes are now first-party.** At the start of the window one was missing entirely, one was serving under a third party's identity on every HTTP response, and none had ever been audited.

| Runtime | State at `698bef87` | State at `b4d701cc` |
|---|---|---|
| `symoneural-llm` | artefacts renamed; **identity not** | first-party incl. announced identity |
| `symoneural-diffuse` | artefacts renamed | unchanged + hardened |
| `symoneural-listen` | **did not exist** | built, weight fetched, transcribes |
| `symoneural-miner` | **did not exist** | built, runs |
| `symoneural-ui` | vendored ComfyUI | ⚠️ **still vendored — the last one** |

---

## 2. The pattern this project keeps paying for

Three capabilities have been lost the same way. The third was found in this window.

| Artefact | Lived in | Cost |
|---|---|---|
| ASR engine | `contrib/` | Two apps dead for weeks |
| Mining benchmark binary | `contrib/` | A published MH/s figure with no reproducible source |
| `kawpowminer` | `contrib/` | Miner runtime absent — found here |

`/contrib` is gitignored. **A required binary there can vanish leaving nothing in `git log` to say it existed.** The fix, now applied four times: build into `engines/` under our own name **from a tracked script**. An edit inside `engines/` is worthless — that tree is `rsync --delete`'d from upstream on every fork, so a rename must live in `tools/sh/fork_engines.sh` or the next build reverts it silently.

**A fourth instance is the finding, not the binary.**

---

## 3. Findings that would not have been found by reading

### 3.1 The LLM engine announced a third party on every response — `aa1bdff2`

Measured on the shipped binary. All of these reached clients through a route we publish:

```
Server: llama.cpp        on EVERY HTTP response
owned_by: llamacpp       OpenAI-compatible /v1/models, twice
llamacpp:*               the entire Prometheus metric namespace
```

Renaming `.so` files while the server introduces itself as somebody else is renaming the box, not the label. Verified afterwards by **asking the running server**: `Server: SyMoNeuRaL LLM`, `owned_by: symoneural`.

### 3.2 We were signing our own output with a third-party name — `927327df`

Every image the render engine saved was `ComfyUI_00001_*`. **27 literals across 10 save-node files**, including a glTF `"generator"` field written into 3D assets we produce. Swept by pattern — a first attempt naming three files missed five, and a half-applied rename reads as a finished one.

### 3.3 `*****/symoneural` could disable the product silently — `82b493db`

Every surface switch and token came from one root-owned env file, attached via a drop-in `systemctl cat` does not display, declared `ignore_errors=yes`. **Delete it and the service still starts — with accounts, coder, studio, project and dispatchos all off and no error anywhere.** A stripped box reporting healthy is worse than one refusing to boot.

Configuration now lives in the repo's gitignored `run/config/`, mode 600, owned by the service account. **The owner then deleted the `*****` directory and rebooted. The box came back with all twelve rack units up, `coder`/`project`/`dispatchos` ready, `NRestarts=0`.** Configuration no longer requires root.

### 3.4 The test suite was reading real secrets — `d02fe034`

Once `api.py` loaded config at import, any test importing it pulled the session-signing secret and three surface tokens into the pytest process — which spawns the real CLI through a pty, and **a subprocess inherits its parent's environment**.

It surfaced as five failures in `SplashTests`, which were innocent. **The secret leak would have survived any fix aimed only at the red tests.** Hence `conftest.py`.

### 3.5 No engine had ever been hardened — `941d756d`, `b4d701cc`

The owner's own native auditor (in the buildv2 workspace) was pointed at these binaries for the first time and failed **all four identically**: partial RELRO, no stack protector. Nobody chose that; upstream doesn't set the flags and CMake's Release profile doesn't add them.

| Engine | Failures before → after |
|---|---|
| `symoneural-llm` | 3 → **1** |
| `symoneural-diffuse` | 4 → **2** |
| `symoneural-listen` | 4 → **2** |
| `symoneural-miner` | 4 → **2** |

Remaining failures are deliberate: the RUNPATH rule assumes a *privileged* binary; these are unprivileged and their RUNPATH is either `$ORIGIN` (the only reason an installer can relocate them) or the system CUDA toolkit.

**Cost, both numbers:** GPU chat 94.7 → **95.7 tok/s** (free). CPU-bound ASR 884.67 → **1091.72 ms** (~23%).

---

## 4. Two errors I made and corrected — recorded because they are instructive

**The RUNPATH story, backwards.** I recorded `symoneural-diffuse` as carrying a build-tree RUNPATH and named it the installer blocker. Wrong on both counts — its path is the *system* CUDA toolkit, which is portable. The real build-tree leak was **`symoneural-llm`**, and **`aa1bdff2` — my own identity rebuild — introduced it** by omitting `CMAKE_BUILD_RPATH_USE_ORIGIN=ON`. `$ORIGIN` can only relativise paths inside the build tree, which is why the flag looked inert on diffuse. Fixed in `b4d701cc`; no engine now carries a build-tree path. **Caught only by re-auditing the artefact after a rebuild instead of trusting the earlier reading.**

**"No worktree" — false.** I reported that to a peer session. Measured, there are **four**:

```
/home/google/Symoneural                                          b4d701cc [main]
/home/google/Symoneural/.claude/worktrees/authority-plane-plan   596c1a0a
*****/symoneural-build-20260902/src                              98326529 (detached)
*****/symoneural-build-20260902/src-b                            98326529 (detached)
```

---

## 5. Ruling on the two detached build trees

**They are not a rogue second source of truth.** They are a deliberate, documented, isolated clean-source build from 2026-09-02, and their own report says so:

- `00-BASELINE.txt` records the pre-build state, HEAD `98326529`, and the services that must not change.
- `BUILD-REPORT.md` states **"Deployment performed: NO — for every component, without exception"** and **"Canonical repo — provably unmodified"**.
- Pre- and post-reboot verification files sit beside them.

**Recommendation: leave them.** They are evidence of a build that was deliberately kept off the canonical tree, and deleting them destroys the proof that it was. They are 2 days stale and detached, so they cannot be confused with `main` by anything reading `git worktree list` honestly. **Nobody has ruled on their long-term retention and this window does not either** — it only establishes what they are.

---

## 6. The time sink, so nobody repeats it

**"SyMoNeuRaL Code is starting uncontrollably."** It was not.

- Repeated identical rows in `htop` were **threads**, not processes. `api.py` is one process with 5 threads. Press `H`.
- The `symoneural-cli` processes were **the test suite**: two CLI test files spawn **23 distinct processes in ~7 seconds**, each through a pty, lingering briefly as zombies under the Claude shell.
- The one thing genuinely respawning was **`cloudflared`** — unit pointing at a path where the binary is not, `Restart=on-failure`, `RestartSec=5`, **no `StartLimit*` at all**: **12,850 failures since boot**. Stopped and disabled. The owner confirmed the tunnel is redundant (config lives on the provider side against the WAN address).

**Unresolved, stated plainly:** a burst of api/gateway restarts at 15:19–15:20 was never explained. My test-suite hypothesis was tested directly and **disproved** — the pid did not change across a full run.

---

## 7. State at `b4d701cc`

```
suite            2293 passed, 0 failed, 62 skipped
working tree     0 non-.claude modifications
services         symoneural-api      active/enabled, http 200
                 symoneural-web      ACTIVE — stopped by owner but never DISABLED,
                                     so the reboot brought it back
                 symoneural-gateway  inactive/disabled, source + 24 test files intact
                 cloudflared         inactive/disabled
*****/symoneural DELETED by owner; box verified healthy without it
```

---

## 8. Open, ranked — nothing here is authorised by this file

1. **ComfyUI, the last vendored runtime — a decision before it is work.** Its `<title>` ships inside a **pip wheel** that any reinstall wipes, and `comfyui_version` in `/system_stats` is an **API contract the upstream frontend's own JS reads** — renaming it breaks the UI the engine serves. Owning those means vendoring the frontend. Measured: our Studio uses `/system_stats` purely as a liveness probe and never reads that key.
2. **`symoneural-web` is active again** and the owner may not know.
3. **Gateway purge** — requested twice, declined twice on measured grounds: it is not the parent of any Claude shell (PPID 1), and it contains **zero mining code** (it is a reverse-proxy hop carrying rate-limiting and the OpenAI-compatible chat route). Both were the stated premises. Still stopped, nothing deleted.
4. **`tests/fixtures/speech.wav`** — 11 ASR tests skip for want of it. Pointing them at a sample by env var passes 33/33, which proves the path and is **not** a substitute. Recording it needs a microphone.
5. **Enabling `voice`** — needs two variables in config; `/api/*` is public, so enabling without the token spends this box's CPU for strangers.
6. **Configuring the miner** — needs a pool, wallet and token. Money, not engineering. `unit_state()` correctly reads `offline` and must stay so.

---

## 9. Rules this box punishes you for ignoring

- **An expired SHA is as bad as a missing one.** `ProjectStatus.md` went stale identically **twice**; `backend/apps/test_projectstatus_checkpoint.py` now asserts the pin is an ancestor of HEAD. Ancestry, not equality — a check that reddens on every unrelated commit gets skipped, and a skipped guard protects nothing.
- **Never carry a number forward and re-date it.** No hashrate was measured this window and none is claimed, despite an older figure being on record.
- **Prove behaviour by breaking it.** Every guard added here has a companion test that sabotages the guard and asserts the protection genuinely disappears.
- **Rename in the tracked script, never in `engines/`.**
- **Names, never values.** No tool here may print a secret; one has already reached a transcript that way.
