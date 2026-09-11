# Open-item reconciliation — 2026-09-08

Every open item from the canonical state and handoff, compared against the repository and
the running box, and classified. Five classes only:

**A** completed and verified now · **B** safe source/documentation work completed now ·
**C** blocked on licensing · **D** blocked on deployment, restart, privilege, network,
hardware or an owner decision · **E** obsolete or superseded, with evidence.

Nothing is erased. Measured at HEAD `78e675c2` unless a row says otherwise.

| Item | Class | Evidence |
|---|---|---|
| **API restart and `engines/` shim removal** | **A** | **The blocker was already closed and I had it wrong.** The split-form path fix landed at `6dd06d43`, 02:46. The API process restarted at **03:51:08** — so it has been running the fixed code for over an hour. Proven rather than assumed: `engines/` was moved aside entirely and the live API still answered **200** with the rack reporting chat `ready`. The five shims are now **deleted** and `engines/` is gone; all four engine binaries resolve at their canonical top-level paths. |
| `bin/` launcher symlinks | A | Kept deliberately — this is the documented install path that `scripts/install-cli.sh` and 39 tracked files use. Not transitional. |
| **Caddy config-path migration (step 1)** | **A** | Live `ExecStart` reads `--config /home/google/Symoneural/ops/Caddyfile`. Applied by the owner in their own shell; certificate unchanged, no re-issue. The root-owned `/etc/caddy/Caddyfile` copy is no longer the live source. |
| **Caddy user/state migration (step 2)** | **D** | Measured: `User=caddy`, `WorkingDirectory=/var/lib/caddy`. Needs root. `/var/lib/caddy/.local/share/caddy/certificates` holds **live Let's Encrypt production** state, certificate valid to **2026-11-15**. It must be **copied and chowned, never moved** — a move loses it and the next start re-issues, spending rate limit on a public site. |
| **Miner ownership** | **C** | `symoneural-miner/LICENSE` is GNU GPL v3 and the build clones `RavenCommunity/kawpowminer` 1.2.4. `fork_engines.sh` refuses to stamp our licence on it, and that refusal is tested. First-party layers exist and are verified in `symoneural-miner-core/` (51 tests, 13/13 smoke); the ProgPoW loop and CUDA kernel are **not** implemented. `cpp-kawpow` 1.1.0 is **Apache-2.0**, which is the fact that makes a first-party miner possible. |
| **Render/UI ownership** | **C** | `symoneural-ui` is ComfyUI, GPL-3.0. Owner's chosen route is a first-party render surface over the already-MIT `symoneural-diffuse`. Not started. |
| **Path-fragility findings** | **D** | Still **81** silent `depth-root` findings, unchanged. Counted and ratcheted by `test_path_fragility.py`; adding one fails the suite. Repair is mechanical source work and is an owner-priority decision, not a blocker on anything else. |
| **`Downloads/` classification** | **D** | 34 GB, **411** entries (up from 408 — it is still in active use). Holds personal material including résumés. Deliberately unswept: a work repository is not the place for it, and the 2026-09-03 audit already classifies PERSONAL separately. Needs a classified pass, not a move. |
| **Root-owned directories** | **D**, and **one correction** | `AI_PURGE_PSEUDOFS` is genuinely `root:root`. `symoneural-cutover-rollback-20260826-154113` is **owned by `google`** — what blocked the move was its mode, `dr-xr-xr-x`, with no owner write bit, and it contains **6 root-owned files** including a live credential file. I earlier reported both as root-owned; that was right for one and wrong for the other. |
| **Stale "next executor: Claude"** | **B** | Neutralised in `docs/HANDOFF.md`. The four remaining occurrences are inside `docs/history/handoffs/HANDOVER-ARCHIVE-pre-20260908.md`, which is a historical record carrying a first-line banner saying so — rewriting them would falsify the log. |
| Repository dependency on `.claude` | B | 0 functional. 13 of 14 path-shaped references are in the vendored Anthropic SDK; the 14th is the archive guard's protection rule, which must keep refusing a directory that still physically exists. |
| ~128 `.claude` prose citations | **D** | Inert docstring references. Left deliberately: the last blanket sweep of that kind silently edited an assertion, and doing this at the end of a long session is how that recurs. |
| The two detached build trees | **D** | `archive/build-20260902-src{,-b}`. Documented never-deployed build evidence — `BUILD-REPORT.md` states *"Deployment performed: NO"*. Recommend leaving; long-term retention is unruled. |
| Six declared-versus-enforced defects | **A** | All fixed and tested: `project` auth declaration, unenforced rate limits (one table now published from and enforced from), `_require_local` proxy headers 3 → 7, the `train` rack row, the `rack/power` 422 leak, and nine unowned `/local/*` routes. |
| Two GPL engines relicensable to MIT | **E** | Asked three times, refused three times. A licence is a grant from the copyright holders; editing `LICENSE` removes a notice the project must keep rather than changing the grant. Now refused **in code**, with tests. |
| `symoneural-diffuse` RUNPATH "installer blocker" | **E** | Never real. `readelf -d` shows system CUDA paths, which are portable. `symoneural-llm` was the leak and it was fixed at `b4d701cc`. |
| ProjectStatus stale pin | **A** | Re-pinned; the suite count is measured at HEAD, not carried forward. |
| Nine runtime folders | **E** | Superseded — there are now **eleven**, including `symoneural-miner-core`. `COMPONENT-MAP.tsv` has 18 rows and a test asserts every runtime directory has one. |

## Corrections to my own earlier reporting

1. **The API/shim blocker was already closed.** I reported it as open in the final response
   and in the Desktop transfer document, having recorded the API's pid as 1507 before it
   restarted and never re-measured. It is pid 143775, started 03:51:08, running the fixed
   code. The shims are gone.
2. **`symoneural-cutover-rollback` is not root-owned.** It is `google`-owned and
   read-only-by-mode. Six files inside it are root-owned.
3. `Downloads/` has grown from 408 to 411 entries during the session — it is live, which is
   another reason not to sweep it from under the owner.
