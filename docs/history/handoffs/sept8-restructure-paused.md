# Sept 8 — Restructure paused mid-flight

> **REDACTED COPY.** Credential filenames and infrastructure posture masked as `*****`.

## Continues from

`sept8-home-consolidation.md`. That window ended at HEAD `8572847f`, tree clean.

## Control point — measured at the pause

```
HEAD    c6b1414e   branch main   tree CLEAN (0 changes)
api     HTTP 200   (pid 1507, not restarted)
site    HTTP 302 https, 308 :80   symoneural-web active/enabled, unit UNCHANGED
engines no engine process running
trees   4 worktrees
```

## What landed in this window

| Commit | |
|---|---|
| `6f856db7`, `c534af32` | reference-isolation tripwire: nothing under `references/` or `archive/` may execute, enforced statically and against `/proc`. Four synthetic controls, all measured. The first version had a dead `ExecStart` branch that could never fire; the control caught it and `c534af32` fixed it. |
| `dbf04f57` | `fork_engines.sh` licence stamping. Three permissive engines get the SyMoNeuRaL licence with the upstream notice preserved; the two copyleft engines are **refused**. |
| `c6b1414e` | the five runtimes promoted to top-level folders, and ignored before anything could sweep 11 GB into history. |

Also done, not a commit: **`symoneural-llm` pid 7138 stopped**, releasing 8,330 MiB of VRAM.
It was running because *this session* ran `tools/probe_apps.py` at 00:54:23, which made real
chat-surface requests; `api.py` spawned the engine 42 seconds later and kept the model
resident. Owned rather than explained away.

## The restructure — where it stopped

**Step 1 of 8 is complete.** The five runtimes now live at the repo root:

```
symoneural-llm/  symoneural-diffuse/  symoneural-listen/  symoneural-miner/  symoneural-ui/
engines/         five compatibility symlinks -> ../symoneural-*
```

The shims are deliberate. `api.py` resolves engine paths at spawn time and has **not** been
restarted, so the old paths must keep resolving until every reference is updated. Verified
both directions: the llm binary is reachable at the old path, the miner binary at the new one.

**Remaining, not started:**

1. Update the **56 tracked files** that hardcode `engines/symoneural`.
2. Rename `references/` → `external/` (the owner named `external` as a folder to keep, and it
   does not exist yet — this is what it means), and fold `archive/` into it.
3. Collapse `archive/` and `archives/`. Two similarly-named top-level directories, and the
   first one is mine from this session's consolidation.
4. Rewrite `README.md` to list every top-level folder, what it is, and how to use it.
5. Remove the compat shims — **only after** 1 and a deliberate `symoneural-api` restart.
6. Full suite, the engine probe, and a real request against the site.

## Blocked on the owner — permission, not a technical problem

The caddy config-path switch is prepared and validated but could not be applied: `sudo
systemctl restart symoneural-web` was **denied by this session's permission classifier**.
Not worked around, and not delegated to another session — that would launder a permission
decision the owner's settings made. Nothing was half-applied; the unit is untouched and the
site is up. The commands are in the reply for the owner to run.

## Hazard recorded for the second derename step

`/var/lib/caddy/.local/share/caddy/certificates` holds **live Let's Encrypt production**
ACME state, and the certificate is valid to 2026-11-15. Changing `User=caddy` and
`WorkingDirectory=/var/lib/caddy` requires that state to be **copied and chowned, never
moved**. A move loses it, the next start re-issues, and that spends Let's Encrypt rate
limit on a box whose site is public. This is why the derename is two steps and not one.

## Still open

- The two GPL-3.0 engines cannot be relicensed. Asked twice, answered twice: a licence is a
  grant from the copyright holders, and editing `LICENSE` removes a notice we must keep
  rather than changing the grant. `fork_engines.sh` now refuses it in code. Routes to
  5-of-5 first-party: a clean-room miner over the algorithm layer (`cpp-kawpow`'s licence
  is **unverified** — it is not on disk and was not guessed), or the render surface over
  MIT `symoneural-diffuse`.
- Six live findings from `probe_apps.py`, untouched.
- `Downloads/` unswept — 34 GB, holds personal material.
- Two root-owned directories that could not be moved.

## To resume

```
HEAD c6b1414e, tree clean. Restructure step 1 of 8 done.
Next: update the 56 path references, then references/ -> external/, then README.md,
then drop the engines/ shims after a deliberate symoneural-api restart.
Do not move /var/lib/caddy state -- copy it.
```
