# Sept 8 — Restructure finished; nine first-party runtime folders

> **REDACTED COPY.** Credential filenames and infrastructure posture masked as `*****`.

## Continues from

`sept8-restructure-paused.md` (HEAD `c6b1414e`, step 1 of 8 done).

## Control point

```
HEAD    0c3e0777   branch main   tree CLEAN
suite   2333 passed, 0 failed, 55 skipped   (measured at this HEAD)
commits 23 today
svc     symoneural-api active/enabled · symoneural-web active/enabled · site 302
audit   81 silent depth-root · 5 absolute-repo-path · 21 stale-dir
```

## The restructure — finished

| Step | |
|---|---|
| five runtimes promoted to top level | done, gitignored (derived, 11 GB) |
| 21 code files repointed | done |
| `references/` → `external/` | done, 149 GB, instant rename, 33 code files repointed |
| `archives/` → `releases/` | done — one letter from `archive/` was a hazard |
| README lists every folder | done |
| `engines/` and `bin/` shims | **still in place, deliberately temporary** |
| caddy config derename | **step 1 live**: `--config .../ops/Caddyfile`, cert unchanged, no re-issue |

## Nine runtime folders, and the split that matters

**Ours — tracked.** `symoneural-api/` (the entry point; the application stays in
`backend/`), `symoneural-code/` (CLI, session front door, discovery),
`symoneural-audit/` (finds move-fragile code), `symoneural-adaptive-fabric/`
(**PLANNED / NOT_IMPLEMENTED**, and its README says so in the first line).

**Derived — gitignored.** `symoneural-llm`, `-diffuse`, `-listen` carry the SyMoNeuRaL
licence over permissive upstreams with notices preserved. `-miner` and `-ui` are **refused**
— their upstreams are GPL-3.0 and `fork_engines.sh` will not stamp proprietary over copyleft.

## The licence answer, and the route through it

Asked three times, and the answer did not change: GPL-3.0 code cannot be relicensed MIT by
editing `LICENSE`. That deletes a notice we must keep instead of changing a grant.

**What did change is the route.** `cpp-kawpow` 1.1.0 is **Apache-2.0** — found at
`external/referencestochatgpt/kawpow-src/`, after I had said it was not on disk. It provides
the whole algorithm layer (`ethash`, `progpow`, `keccak`) **and its own test vectors**. The
GPL lives only in the kawpowminer *shell*: CLI, stratum, `libapicore`, the CL/CUDA kernels.
So a first-party proprietary miner is buildable: our CLI, our stratum client, our CUDA
kernel for sm_120, linking Apache-2.0 cpp-kawpow with a NOTICE. The test vectors mean it can
be **proved** correct, not hoped correct. `/yocto` does not help — its mining material is
`cgminer`, also GPL-3.0.

## Bugs found by moving things

**The client broke on promotion**, loudly, because someone had put an assert under
`ROOT = HERE.parent`. Its own comment already read *"this calculation has been wrong four
times in this repo"*. Five. `bin/symoneural-discovery` had been walking up for the marker
all along — the correct pattern was one file away from the one that broke.

`symoneural-audit` exists because of that, and found **81 more files with the same silent
bug**, plus 5 hardcoded checkout paths and 21 stale directory names.
`test_path_fragility.py` pins 81 as a ratchet: it may fall, never rise.

**The ratchet caught its own author** on the next run — 82, and the eighty-second was
`test_path_fragility.py` itself, opening with `parents[2]`. Recorded in the file rather than
quietly fixed.

**The window that kept appearing** was `test_desktop_shell.py`: un-stubbed by design, it
opened a real GTK window on display `:0` every suite run, and KWin raised
`kwin_killer_helper` against it when the client wedged. Now on a throwaway Xvfb display, and
it **skips rather than falling back** to the active display. `_reap()` kills the child the
test spawned instead of trusting a SIGHUP that only arrives on the tidy path.

**A blanket path rewrite edited an assertion** — the governor's regex lost the `engines/`
anchor that made it count directory spellings, so it started counting kill patterns too. A
broken path fails loudly; a weakened assertion passes quietly. Every later sweep was checked
for this and the second one caught two more, both consistent.

## Still open

- **`engines/` and `bin/` shims** — removable after a deliberate `symoneural-api` restart.
- **The 81 silent `depth-root` files.** Counted, ratcheted, not repaired.
- **The first-party miner** — next task, foundation confirmed permissive.
- **The render surface** over MIT `symoneural-diffuse`, replacing GPL `symoneural-ui`.
- **Caddy derename step 2** — `User=caddy`, `/var/lib/caddy`. `/var/lib/caddy/.local/share/caddy/certificates` holds live Let's Encrypt **production** state, cert valid to 2026-11-15: **copy and chown, never move**, or the next start re-issues and spends rate limit.
- **Six live findings from `probe_apps.py`** — rate limits published but not enforced, declared-vs-enforced auth mismatch on `project`, undocumented `/local/*` routes, an incomplete forwarded-header check, the rack reporting `train` ready while it answers 503. Untouched.
- **`Downloads/`** — 34 GB unswept; holds personal material.
- Two root-owned directories that could not be moved.

## To resume

```
HEAD 0c3e0777, tree clean, suite 2333/0.
Next: first-party miner. Adopt Apache-2.0 cpp-kawpow via tools/lib/index_references.py adopt,
stand up a CPU path that passes its own progpow test vectors, then the CUDA kernel.
Do not move /var/lib/caddy state -- copy it.
```
