# Sept 8 — Home-directory consolidation

> **REDACTED COPY.** Credential filenames and infrastructure posture masked as `*****`.
> Concepts kept, identifiers blurred. This file now lives *in* the repo: the handoff chain
> was moved from `/home/google/SyMoNeuRaL-Workspace/handoffs` into `docs/handoffs/` during
> this window, so a clone finally carries the project's own decision record.

## Continues from

`sept4-concurrent-session-decision-gate.md` (2026-09-05, HEAD `30add06b`, tree clean).

**Gap in the chain, stated plainly:** a session ran on this box on **2026-09-07** and left
no handoff. Its work was found untracked and is preserved at `ecb3f11e` — see §3.

## Control point

```
then    30add06b   2026-09-05, tree clean
now     3deb1643     2026-09-08, tree clean, 9 commits this window
```

## 1. What was asked, and the three things that changed its shape

Merge ~26 loose directories under `/home/google` into the repo, update the documentation,
test, commit — with the goal that all engines are first-party code in `backend/apps`.

**(a) The mechanism already existed.** `references/` is gitignored at `.gitignore:68`, holds
72 entries of third-party material, and carries a standing owner rule quoted in
`tools/index_references.py`: *"we cannot use code in references its for reference only we
must rebrand if we want to use it"*. `incoming/` is the adoption path, and
`incoming/*/PROVENANCE.md` is **tracked while the copied tree is not** — the exact
"record the provenance, not the payload" shape this job needed. Inventing an `external/`
scheme would have created a second source of truth, which this repo forbids.

**(b) A 291-entry audit already existed and was never authorised.** `HOME-CLEANUP-AUDIT-
20260903.md` inventoried **291 of 291** top-level entries with zero gaps on 2026-09-03 and
has been sitting unread. It is a better map than the 26 names in the request. Adopted to
`docs/ops/home-cleanup-audit-20260903/`; **the remaining phases should be driven from its
manifest, not from a list.**

**(c) The licence wall.** Four engines are MIT-derived, which is why the first-party fork
worked four times. `symoneural-ui` is **ComfyUI, GPL-3.0** — verified at
`engines/symoneural-ui/LICENSE`. MIT permits relicensing the combined work; GPL-3.0 does
not. `tools/fork_engines.sh` defines `fork_llm | fork_diffuse | fork_listen | fork_miner`
and **no `fork_ui`** — the codebase already knew. Decision taken: replace it with a
first-party render surface over the MIT `symoneural-diffuse`. **That is a project, not a
migration, and it has not been started.**

## 2. What moved

Three destinations, one rule each. Full map in `docs/ops/CONSOLIDATION-20260908.md`.

| | Tracked | Contents |
|---|---|---|
| `docs/` | **yes** | 24 decision records, the 37-file handoff chain, the LoRA restoration manifest, the host diagnostic dump, the 291-entry audit, `RAVENCALC.docx` |
| `references/` | no | `oss/` (46 upstream trees), TensorRT-LLM, ComfyUI-Installs, ComfyUI-Shared, bentoml, ninjatraining, Toolchains, Platforms, vendor agent material |
| `archive/` | no | 253 G workspace archives, 16 G backups, build outputs, weight staging, session transcripts, the 2026-09-02 build evidence, the Desktop project material |

**Cost: zero disk.** Every move was a same-filesystem rename — 618 GB used before, 618 GB
after. Both detached build worktrees were relocated with `git worktree move`, so their
metadata survived; `git worktree list` now shows all four trees inside the repo.

## 3. Found uncommitted, again

Six files, 158 KB, written **2026-09-07** by a session with no handoff and no record here:
`tools/probe_engines.py`, `tools/probe_apps.py`, `tools/bench_llm.py`,
`tools/bench_llm_spec_ab.py` and two test modules. Committed verbatim at `ecb3f11e`.

**Second time in four days** that substantive work was found modified-but-uncommitted
(`00ecad02` was the first, an 80-line HANDOVER entry that had sat three days). There is no
remote here by policy, so uncommitted work has one copy and no history.

## 4. Two real defects found by running things

**The audit tool was asserting a false negative.** `probe_engines.py` hardcoded
`symoneural-miner` as `binary: None` with the note *"no built binary under build/bin"*.
Measured: the binary exists at `build/kawpowminer/symoneural-miner`, 6,293,648 bytes, built
2026-09-04, answering `SyMoNeuRaL Miner 1.2.4`. The note was true of the **path** and false
of the **engine** — the vendored CMake project emits to `build/kawpowminer/`. Written
2026-09-07, three days after the engine was built. Fixed at `aac16db9` with a per-engine
`bindir`; the audit now agrees with ProjectStatus at 4 of 5 built. **This is the same
reading-not-running failure the repo keeps hitting, this time inside the tool built to
catch it.**

**A 101 MB protected-inventory leak, caught before it was committed.**
`Symoneuraltree.md` was sitting in the handoff directory — a full filesystem listing that
names `training/corpus.jsonl` and `training/build_dataset.py`. `docs/ops/EXPORTS.md` rule 2
puts those in the protected class: *never in an export, never served, never quoted into a
page or commit message*. Moving the handoff chain into tracked `docs/` would have put that
inventory in git history permanently. Caught by the grep EXPORTS.md publishes as its own
acceptance check, and quarantined to `archive/tree-dumps/`.

## 5. Test result

The consolidation broke one test and it was my doing. Adopting the decision records into
`docs/` put them inside `TheEnvNameTripwire`'s scan scope;
`p2-complete-non-forgeable-release-identity.md` names the pre-rename `SYM_TAG_VERIFY_CMD`
without its `SYMONEURAL_TAG_VERIFY_CMD` spelling. Suite went to **2327 passed / 1 failed**.
Fixed the way the tripwire's own message asks — by adding the current spelling, not deleting
the historical one.

**Then it caught this file.** The first draft of this handoff quoted `SYM_TAG_VERIFY_CMD`
while describing the fix, and wrote the modern name only as the glob `SYMONEURAL_*`. The
tripwire wants the actual name, so the re-run failed again — on the handoff, not on the
ruling. Working exactly as designed: a document that teaches a deprecated variable name is
the thing it exists to stop, and it does not care that the document is about the tripwire.

## 6. Answered: the `symoneural-code` process

A `symoneural-code` process (pid 12736) was observed against `127.0.0.1:8800`. **Not
launched by me.** Measured: the pid is already gone; `bin/symoneural-code` is a 4 KB bash
wrapper over `bin/symoneural-cli repl`, not a server; `:8800` is held by the long-running
API (`python3` pid 1507); and neither probe I ran references it. It is invoked by
`desktop/shell.py` and `backend/apps/test_desktop_shell.py` — a test subprocess during the
suite run, consistent with its lifetime and its argument shape.

## 7. Not done, and named rather than quietly dropped

- **Engines are still in `engines/`, not `backend/apps`.** Deliberately not moved. `.gitignore`
  lines 189–193 declare `engines/` a **derived** tree produced by `fork_engines.sh`, with
  *"do not track a derived copy of an untracked source"*. Moving derived binaries into a
  tracked `backend/apps` would contradict that rule, so **what belongs there is a design
  question, not a `git mv`** — see the open question in the reply.
- **The first-party render surface** replacing ComfyUI: not started.
- **`Downloads/`** — 34 GB, 408 entries, and it contains **personal material** (résumés,
  screenshots). Not swept. The 2026-09-03 audit already classifies PERSONAL separately and a
  work repository is not the place for it; this needs a classified pass, not a move.
- **`Desktop/`** — project material taken (`symon*`), including `symoneural-buildv2`, the
  5 GB native ELF auditor that found the hardening gaps. Personal and unrelated tooling left.
  `symoneural-buildv2` is first-party and is the top candidate for real integration.
- **Two directories could not be moved:** the cutover-rollback set and `AI_PURGE_PSEUDOFS`
  are root-owned. The first holds a live `*****` credential file and is better left in place
  than worked around.
- **Six live findings from `probe_apps.py`** — undocumented `/local/*` routes, a rate-limit
  layer that publishes figures it does not enforce, declared-vs-enforced auth mismatch on one
  surface, an incomplete forwarded-header secondary check, and the rack reporting `train`
  ready while it answers 503. **Real, and a separate task from this one.** Not touched.

## To resume

```
repo    /home/google/Symoneural   branch main   tree CLEAN
docs    docs/ops/CONSOLIDATION-20260908.md   what moved where and why
        docs/ops/home-cleanup-audit-20260903/  291-entry map, drives the next phase
next    (1) decide what backend/apps should actually contain for an engine
        (2) classified pass over Downloads/ -- project vs personal
        (3) integrate symoneural-buildv2 as first-party tooling
        (4) the render-surface project, and the six probe_apps findings
```
