# Serving path — canonical runtime under `/home/google/Symoneural`

**Migration completed 2026-08-26. Verified on the live box.** Supersedes the audit-only
version of this file.

The boundary and the machine baseline live in **`docs/ops/BUILD-BOUNDARY.md`**; this file is
the completion record — final paths, the coded path that produced them, and the evidence.

Classified with the Repo Update Audit System (`docs/ops/REPOSITORY-PURPOSE.md`): **PROD** =
proven working on this box · **AUDIT** = unverified or scaffold · **REMOVED** = wrong, dead,
or contradicted by the box.

---

## PROD — proven on this box

### Canonical paths, all live

| what | path |
|---|---|
| Repository / runtime root | `/home/google/Symoneural` |
| Models | `/home/google/Symoneural/backend/models` |
| Chat model | `/home/google/Symoneural/backend/models/llm/symon-1.0-7b-q4_k_m.gguf` |
| **Inference engine** | `/home/google/Symoneural/engines/symoneural-llm/build/bin/symoneural-llm` |
| Gateway | `/home/google/Symoneural/backend/apps/gateway/target/release/symon-gateway` |
| Deploy script | `/home/google/Symoneural/scripts/deploy.sh` |
| Webroot | `/var/www/symoneural` (unchanged) |

### Services

All three carry `WorkingDirectory=/home/google/Symoneural`, and **no enabled unit references
`/yocto` in any directive**:

    symoneural-api      ExecStart=/usr/bin/python3 /home/google/Symoneural/backend/api.py
    symoneural-gateway  ExecStart=/home/google/Symoneural/backend/apps/gateway/target/release/symon-gateway
    symoneural-deploy   ExecStart=/usr/bin/env bash /home/google/Symoneural/scripts/deploy.sh --prune
    caddy               unchanged — it never referenced /yocto

**A reboot cannot republish `/yocto` content**: `symoneural-deploy` is enabled and both its
`ExecStart` and `ConditionPathIsDirectory` name the canonical tree.

### Live processes — zero `/yocto`

| process | cwd | exe | fds | maps | env |
|---|---|---|---|---|---|
| `symoneural-api` | `/home/google/Symoneural` | `/usr/bin/python3.13` | 0 | 0 | 0 |
| `symoneural-gateway` | `/home/google/Symoneural` | canonical gateway binary | 0 | 0 | 0 |
| `symoneural-llm` (engine) | `/home/google/Symoneural` | canonical engine | 0 | 0 | 0 |

`PYTHONPATH` unset; no `.py` open from `/yocto`; no mount over the canonical tree; no symlink
under it pointing into `/yocto`.

### ELF artifacts

| artifact | interpreter | RPATH | RUNPATH | unresolved | `st_nlink` |
|---|---|---|---|---|---|
| gateway | `/lib64/ld-linux-x86-64.so.2` | none | none | 0 | 1 |
| engine | `/lib64/ld-linux-x86-64.so.2` | none | `…/engines/symoneural-llm/build/bin:` | 0 | 1 |

Neither resolves a library from `/yocto`. The engine's RUNPATH is inside the canonical tree.

### The engine on the GPU — no CPU fallback

    exe    /home/google/Symoneural/engines/symoneural-llm/build/bin/symoneural-llm
    argv   -m /home/google/Symoneural/backend/models/llm/symon-1.0-7b-q4_k_m.gguf
           -ngl 99 --host 127.0.0.1 --port 8081 -c 65536 --no-warmup -cb -np 2
           --lora /home/google/Symoneural/training/adapter/symoneural-lora.gguf
    VRAM   8330 MiB on the RTX 5070 Ti      GPU util 96%      178.39 W
    CUDA   libcuda.so.610.57.04  libcudart.so.13.3.29  libcublas.so.13.6.0.2  libcublasLt.so.13.6.0.2
    GGUF   canonical path mapped into the process

`-ngl 99` offloads every layer; the mapped CUDA libraries match the audited driver
(610.57.04) and toolkit (13.3) exactly. **PROD.**

### The real model round trip — `model: true`

Seeded booking `DX-5CD40A`, *Harbour Street → Central rail station*, pax 3, bags 1:

    Q  Which pickup address is on the board for the rail station trip?
    model: true   0.42 s
    A  "Harbour Street. The rider is Smoke Rider and the quote is blank…"

    Q  How many passengers are on the Friday evening job?
    model: true   0.44 s
    A  "The Friday evening job has three passengers. The job board states 'pax 3 bags 1'
        for the job DX-5CD40A…"

**Why this is not the fallback, beyond the flag.** `ai.local_answer()` can only ever emit one
of three fixed shapes — *"On the board right now: …"*, *"The live job is X: A to B, …"*, or
the "not available" sentence. It cannot read a pickup address, a rider name, or `pax 3 bags 1`
out of the board. These answers quote all of them. Chat also measured **90.9 tok/s** on a
67-token generation, which is GPU throughput.

### Health

    local  http://127.0.0.1:8800/api/status   200
    public https://symoneural.com/api/status  200
    public https://symoneural.com/overview    200
    public https://symoneural.com/demo/dispatchos  401 unauthenticated (edge auth intact)

### Tests

    apps/test_dispatchos.py  test_runtime_boundary.py  test_maintenance_banner.py
    apps/test_build_progress.py                              87 passed

Mutation-proved rather than trusted — each applied, caught, reverted:

| sabotage | caught by |
|---|---|
| unit template hardcodes `/yocto` in `ExecStart` | `test_no_template_hardcodes_yocto_in_a_path_directive` (+1 more) |
| template loses its `@@ROOT@@` placeholder | `test_templates_use_the_placeholder` |
| model manifest SHA truncated | `test_the_chat_model_manifest_is_present_and_complete` |
| installer stops running the verifier | `test_the_installer_runs_the_verifier` |
| customer isolation removed (DispatchOS) | `test_a_customer_sees_only_their_own_trips` |
| a default tariff appears | 6 quote tests |
| `sent_at` populated on a message | `test_a_composed_message_is_never_marked_sent` |
| operator role check dropped | `test_a_customer_cannot_quote_dispatch_or_set_rates` |
| lifecycle order not enforced | 2 lifecycle tests |

### The coded migration path, exercised end to end

Not a description — this was actually run, in this order, on the live box:

1. `ops/rollback-runtime.sh` → production **back onto the `/yocto` units**, health 200.
2. `ops/verify-runtime.sh` → **exit 1**, ten specific violations (cwd, argv, exe, 4 open fds,
   mapped files, deploy would republish from `/yocto`). That is the verifier's own proof.
3. `sudo ops/install-runtime.sh` → preflight, backup to
   `/etc/symoneural/unit-backups/20260826-092957`, atomic install of three units,
   `daemon-reload`, controlled restart (gateway then API), local 200 after ~4 s, public 200,
   verifier **clean**.
4. `ops/install-runtime.sh --dry-run` re-run → *"every unit is already correct — nothing to
   install"*. **Idempotent.**

### The gateway is built, not copied

`ops/build-gateway.sh --force` after deleting the binary **and** cargo's `deps/` copy: a real
43-second relink produced **byte-identical `sha256 41b9eda8…ad74`**, 27,232,992 bytes,
`st_nlink=1`, 0 unresolved deps, 0 `/yocto` linkage, no `/yocto` string in the binary. Record
in `ops/manifests/gateway-build.json`.

Built **natively** (`cargo 1.97.1`, `rustc 1.97.1`, host `x86_64-unknown-linux-gnu`) and not
with the Yocto SDK, because that SDK's `TARGET_SYS` is **`aarch64-oe-linux`** and cannot
produce a binary that runs on this host at all. See `docs/ops/BUILD-BOUNDARY.md`.

### The model is verified, not assumed

4,683,074,240 bytes · `sha256 65b8fcd9…aa1423` · GGUF v3 · 339 tensors · `qwen2` ·
*Qwen2.5 7B Instruct* · `file_type 15` (Q4_K_M) · `st_nlink=1` · not a symlink · different
inode **and different filesystem** from the read-only source, so a hardlink was never
possible. Manifest: `ops/manifests/llm-chat-model.json`. The `/yocto` source copy was **not**
moved, modified or deleted.

---

## REMOVED — wrong, dead, or contradicted by the box

- **`WorkingDirectory=/yocto/Symoneural`** on all three units. Replaced.
- **Gateway executed from `/yocto`.** Now the canonical, independently built artifact.
- **`symoneural-deploy` publishing from `/yocto`** — the one that would have silently reverted
  the site at every boot.
- **`backend/engines/…` as the native engine path.** It does not exist. `backend/api.py:183`
  computes `ROOT / "engines" / …`. Corrected here and in `docs/ops/BUILD-BOUNDARY.md`.
  *(Not to be confused with `.claude/HANDOVER.md`'s planned Python adapter package, also
  called `backend/engines/` — a different thing, correct as written.)*
- **Driver 590.48.01 / CUDA 13.1.** The box reads **610.57.04** and **13.3**.
- **Hand-run migration commands.** Replaced by `ops/install-runtime.sh` and friends. The
  installer's dry run proving "nothing to install" is the evidence that what was done by hand
  and what the repository does are the same thing.

---

## AUDIT — true but not proven here, or deliberately not claimed

- **Reboot behaviour is inferred, not observed.** Every enabled unit names the canonical root
  and the deploy condition path does too, so a reboot cannot republish `/yocto` content. The
  box has not actually been rebooted to watch it happen.
- **The engine is not resident at boot.** It starts on demand from a chat request and
  DispatchOS never starts it — by design, so a rider's question cannot evict a render. After
  any restart the first `/ask` will take the labelled fallback until something warms chat.
  That is correct behaviour, not a regression.
- **Rate rules remain unconfigured**, so every quote shows `——`. Required by the customer
  preview, which states it carries no pricing of any kind.
- **`/etc/symoneural/dispatchos-logins.txt`** holds the four application passwords, root-only
  0600, never printed. Read once, hand over, `shred -u`.
- **The four-status edge check on `/demo/dispatchos`** is 401/401/401 verified; the
  authenticated 200 is Garrett's own login to prove, because this repo holds bcrypt hashes.
- **`/yocto` build workspace continues to run** (BitBake, the 8-cell matrix). Untouched by
  this migration and explicitly allowed.

---

## REBOOT OBSERVATION — 2026-08-28 17:19:34 (provisional; #108 remains open)

A host reboot happened and the canonical runtime came back without help. That is the thing
`#108` has been waiting for, and it is recorded here **provisionally**: the reboot proved the
boundary, and then showed that the engine which actually served is not the engine this
document, the installer and the verifier all name. `#108` stays open for that reason. This
section deliberately does not carry the closing-check phrase, so no check flips on it.

**The reboot was independent.** Boot at `2026-08-28 17:19:34 EDT`, boot id
`2bc801b6-9d2b-498b-be68-f006317aecaf`. It occurred between two read-only measurements of the
`/yocto` Phase 2 audit and was **neither initiated nor caused by that audit**. No service was
manually restarted during this evidence-collection task; the recorded activations are boot
activations. There is no evidence that `symoneural-deploy.service` was restarted or modified,
and none is claimed: it activated at boot like the other three.

### What the boot proved

**The runtime boundary survived with zero live `/yocto` dependency.** Measured per process
across cwd, exe, argv, environ, memory maps and open file descriptors:

| process | pid | `/yocto` references |
|---|---|---|
| `symoneural-api` | 1840 | 0 |
| `symoneural-gateway` | 1865 | 0 |
| `symoneural-web` | 1791 | 0 (read via sudo; it runs as `caddy`) |
| inference engine | 54394 | 0 |

`ops/verify-runtime.sh` exits **0 — `RUNTIME BOUNDARY CLEAN`**. All four units report
`active`, `enabled`, `Result=success`. Current-boot journals hold **277 lines across the four
units and not one mentions `/yocto`**. No mount over the canonical tree; no symlink under it
pointing into `/yocto`.

**The boot deploy published from the canonical tree, not `/yocto`.** Of 96 webroot files, 95
are byte-identical to `site/`; the 96th is `index.prev-20260828-171944.html`, deploy's own
backup. The decisive part is the disagreement set: in **all 28 files where `site/` and
`/yocto/Symoneural/site/` differ, the webroot matches the canonical copy**.

**Health.** Local `:8800/api/status` 200, gateway `:8000/healthz` 200. Public
`/api/status` 200, `/overview` 200, `/` 302 → `/overview`, and both `/demo/dispatchos` and
`/share-dispatchos.html` **401 unauthenticated** — edge auth intact, no credential sent.
`symoneural-web` (pid 1791) owns `:80` and `:443`; the vendor `caddy` unit is disabled.

**A real GPU generation.** `POST /api/chat` started the engine on demand and returned
`tokens 55, seconds 0.59, tok_per_s 93.4, model symon-1.0-7b-q4_k_m, adapter true`. VRAM
climbed 222 → 4392 → 8316 → **8330 MiB**, GPU 96%, 108.72 W, `-ngl 99` (every layer offloaded).
CUDA mapped: `libcuda.so.610.57.04`, `libcudart.so.13.3.29`, `libcublas.so.13.6.0.2`,
`libcublasLt.so.13.6.0.2` — the audited driver and toolkit. The GGUF is mapped from the
canonical path. 93.4 tok/s is GPU throughput; **there is no CPU fallback here.**

**Tests.** `test_dispatchos.py`, `test_runtime_boundary.py`, `test_maintenance_banner.py`,
`test_build_progress.py` — **92 passed**, each against a throwaway store.

### Qualifications — why this is provisional

**1. The live engine is not the documented engine.** Same size, different builds:

    documented / installed / verified
      engines/symoneural-llm/build/bin/symoneural-llm
      sha256 0c4f804a5b18f754376acef6d73595eb191dafd6855cd81831844c941e3fe4c1
      RUNPATH /home/google/Symoneural/engines/symoneural-llm/build/bin:
      BuildID 5afe9f09b33992611830ed59d6fccdafd9844ba5

    what actually served this boot
      engines/symoneural-llm/staged-20260826-153043/bin/symoneural-llm
      sha256 619b918f3f0ac3629c1270320460893627fb8c78d0d4cb22f08e827380d0f35a
      RUNPATH $ORIGIN
      BuildID 22570837ba0a18e8a7e0dcca832f40401da5c805

Both are 17,952-byte launchers that link `libsymoneural_llm_server_impl.so`, and each `bin/`
holds 23 `.so` files beside it — the engine is a whole runtime directory, not one file. The
`$ORIGIN` RUNPATH is what makes the staged set relocatable; the `build/bin` copy hardcodes its
own absolute path. `ops/install-runtime.sh:78`, `ops/verify-runtime.sh:110` and
`ops/verify-runtime.sh:152` all name `build/bin`.

**A demonstrated consequence, not a theoretical one:** with the engine resident at pid 54394,
`verify-runtime.sh` still printed *"engine not resident … skipped"*, because line 110 greps for
the `build/bin` path. The verifier's engine checks never ran against the engine that served.

**2. The selection depends on uncommitted behaviour.** `/etc/symoneural/api.env` sets
`SYMONEURAL_LLM_ENGINE`, and the `_engine_path()` override that reads it exists **only in the
dirty working tree** — 59 uncommitted lines in `backend/api.py`. From a clean checkout of
`HEAD` the variable is ignored and the API resolves the *other* binary. The running production
service therefore depends on code that is not in git.

**3. `web/` is untracked and unpackaged.** `git ls-files web/` returns **0 files**. The live
`:443` binary `web/symoneural-web/build/symoneural-web`
(`b0d3234f9543bce2f83f01e1e010031b4b3928e859bd616d2ce7ae7d15d6eb06`, 76,206,670 bytes) is
explicitly ignored by `.gitignore:243`, and neither `scripts/build-deb.sh`,
`ops/install-runtime.sh` nor `ops/manifests/` references it. There is no source-to-live chain
in the repository for the process that currently serves the public site.

**4. The authenticated DispatchOS `model: true` response was not freshly proved.** That field
belongs to `POST /api/dispatchos/ask`, which requires a credential this repo does not hold and
which DispatchOS's freeze forbids probing. The model path was proved this boot through
`/api/chat` instead. The `model: true` record elsewhere remains its original 2026-08-26
measurement and has not been re-dated.

**5. There was no saved pre-reboot webroot hash.** The matching aggregate
`636646ee9c8d5ec7503b26e4b53c25c3dd7caeb82521dcf96550cc63640e646a` is a **within-boot
pre/post-model comparison** proving that running the model did not alter the published site.
It is not a pre-reboot versus post-reboot comparison, because no earlier baseline existed to
compare against.

## SECOND REBOOT OBSERVATION — 2026-08-29 10:30:32 (#108 remains open)

A second, independent host reboot happened and the canonical runtime came back without help.
This section records what that boot established and, as deliberately as the section above it,
**does not carry `#108`'s closing-check phrase** — see *Why the check is still not flipped*
at the end.

**Boot identity.** Boot id `8482ab4b-5b32-40c6-8d8c-46c7e958f7d9`, booted
`2026-08-29 10:30:32 EDT`. All four units activated at boot with `NRestarts=0` and
`Result=success`: `symoneural-api` (pid 1852), `symoneural-gateway` (1877) and
`symoneural-web` (1804) at 10:30:44, `symoneural-deploy` at 10:30:41. **No service was
started, stopped, restarted or reloaded by the evidence capture**, and none was restarted to
produce this record.

**Preserved evidence.** `/home/google/symoneural-108-postboot-20260829T152526Z`, mode `0700`,
17 files, hashed in its own `evidence-sha256.tsv` and provenance-stamped to the boot id above.
Every claim below is read out of that capture; nothing here is asserted beyond it.

### What this boot established

**The runtime boundary survived with zero live `/yocto` dependency.** Measured per process
across cwd, exe, cmdline, environ, maps and open file descriptors — eighteen measurements over
the three service processes — **0 references**. `ops/verify-runtime.sh` exits **0 —
`RUNTIME BOUNDARY CLEAN`**. Current-boot journals across the four units hold **198 lines and
not one mentions `/yocto`**. No mount over the canonical tree.

A naive `*/yocto*` symlink glob reports six hits under the canonical tree and **none of them is
a `/yocto` reference**: they are the npm packages `yocto-queue` and `yoctocolors` under
`references/`, a tree this project already forbids importing, building or linking.
`verify-runtime.sh` anchors on `/yocto*` and excludes `references/`, which is why it passes.
Written down so the next reader does not re-raise it as a finding.

**The boot deploy published from the canonical tree, not `/yocto`.** Comparing the HTML, CSS
and JS set three ways — `site/`, `/yocto/Symoneural/site/`, and the webroot — twelve files are
identical in both trees and carry no information either way, two have no `/yocto` counterpart,
and **twenty-nine disagree. In all twenty-nine the webroot matches the canonical copy and none
matches `/yocto`.** The disagreement set is the decisive one and it is unanimous.

**Health.** Local `:8800/api/status` 200 and gateway `:8000/healthz` 200. Public `/api/status`,
`/overview`, `/livestack` and `/docs` 200, `/` 302, and both `/demo/dispatchos` and
`/share-dispatchos.html` **401 unauthenticated** — edge auth intact, no credential sent and the
door not authenticated through. `symoneural-web` (pid 1804) owns `:80` and `:443`; the vendor
`caddy` unit is `disabled` and `inactive`.

### Which acceptance criterion this closes, and which it does not

**CLOSED by this boot: the post-boot runtime verification.** *"Whether the enabled units, and
only the enabled units, bring the canonical runtime back with no `/yocto` anywhere."* Two
independent reboots have now shown it, and this one is measured against a live boot id that can
be tied to the evidence root while it lasts.

**STILL OPEN: the engine identity.** `#108` also asks this repository to *prove SyMon AI answers
from the model*, and the engine that would answer is still not the engine this document, the
installer and the verifier all name:

    documented / installed / verified
      engines/symoneural-llm/build/bin/symoneural-llm
      sha256 0c4f804a5b18f754376acef6d73595eb191dafd6855cd81831844c941e3fe4c1

    what the live configuration selects
      engines/symoneural-llm/staged-20260826-153043/bin/symoneural-llm
      sha256 619b918f3f0ac3629c1270320460893627fb8c78d0d4cb22f08e827380d0f35a

The 2026-08-28 section above recorded that disagreement as a qualification. It is no longer only
a qualification: it is now **traced to its cause**. `/etc/symoneural/api.env` lines 14 and 15
(mode `600`, owner `root`, mtime `2026-08-26 15:52:08`) set `SYMONEURAL_LLM_ENGINE` and
`SYMONEURAL_DIFFUSE_ENGINE` to the staged builds, and the unit reads that file through
`EnvironmentFile=`. `backend/api.py::_engine_path()` prefers the environment variable whenever
it names a real file, and both staged binaries are present. So this is a standing configuration
fact, not a transient state.

**THAT OVERRIDE HAS NOT BEEN CHANGED.** `/etc/symoneural/api.env` is untouched by this record and
by the capture that produced it. Altering it is a live configuration mutation and was explicitly
withheld from this authorization: it needs its own pre-change baseline, intended value, rollback
condition and verification criteria. Documenting a defect is not licence to repair it.

**Also not established this boot: the model actually answering.** The engine starts on demand,
was not resident, and no inference job was submitted — that is a write-side action and the
capture was evidence-only. The `93.4 tok/s` generation recorded in the 2026-08-28 section stands
as its own dated measurement and **has not been re-dated to this boot**.

### Why the check is still not flipped

`#108`'s last unmet check is a grep of this file for a specific closing phrase. That phrase is
**deliberately absent here, exactly as it is absent from the 2026-08-28 section**, and for a
sharper reason now that the cause is known.

`tools/archive_tasks.py` moves any task at 100% into `review/CLOSED-TASKS.md` as finished. Typing
the phrase would take `#108` to 15/15 and archive it **as done** while the engine it is supposed
to prove is still not the engine that would answer. That is precisely the failure
`.claude/CLAUDE.md` warns about — *"a check that can pass without the work being finished is
worse than no check, since it will archive the task"* — and precisely how `#94` and `#74` were
lost.

So the post-boot half is recorded here and the task stays at **14/15**. The phrase belongs in this
file on the day the engine question is settled: either the override is authorized and changed so
the documented engine serves, or the staged engine is promoted to be the documented one and the
installer, the verifier and the manifests are updated to name it. Until one of those happens,
`#108` is not done and this file does not say it is.

## POST-REBOOT EVIDENCE — #108 closed 2026-08-29

The two conditions `#108` was left open for are both now met, and this section is the record
that earns its closing check. It is written only after the proof existed, not to produce it.

### 1. The reboot, and the runtime coming back on its own

Boot id `8482ab4b-5b32-40c6-8d8c-46c7e958f7d9`, booted `2026-08-29 10:30:32 EDT`, independent
of any agent action. All four units activated at boot with `NRestarts=0` and `Result=success`.

    /yocto references across 3 live services x 6 process fields ... 0 of 18
    ops/verify-runtime.sh ....................................... exit 0, RUNTIME BOUNDARY CLEAN
    current-boot journals, 4 units .............................. 198 lines, 0 mention /yocto
    mounts over the canonical tree .............................. 0
    webroot provenance, disagreement set ........................ 29 files: 29 canonical, 0 /yocto

Evidence: `/home/google/symoneural-108-postboot-20260829T152526Z`.

### 2. The documented engine now serves, and it was proved by execution

The engine that answers is no longer the one this document had to disclaim. The 2026-08-26
promotion was completed on 2026-08-29: the promoted server and its ten shared libraries were
installed at the canonical `build/bin`, and the `SYMONEURAL_LLM_ENGINE` override was removed
from `/etc/symoneural/api.env`, which is now byte-identical to the pre-cutover file preserved
in the August 26 rollback snapshot.

One controlled `POST /api/chat` then proved it, through the normal serving path:

    HTTP 200, streamed          tokens 6, tok_per_s 38.0
    model                       symon-1.0-7b-q4_k_m, adapter true
    engine child pid            43122, ppid 19338 (symoneural-api)
    /proc/43122/exe             engines/symoneural-llm/build/bin/symoneural-llm
    sha256 via /proc/<pid>/exe  619b918f3f0ac3629c1270320460893627fb8c78d0d4cb22f08e827380d0f35a
    GPU                         237 -> 8575 MiB, compute 0 -> 8330 MiB, nvidia-smi names pid 43122

**The hash was read through `/proc/<pid>/exe`** — the executable actually mapped by the running
process — not from a file at a path. `pgrep`, pathname expectation, `verify-runtime.sh` and
environment configuration were all excluded as identity evidence. Evidence:
`/home/google/symoneural-108-phase2-serving-proof-20260829T165111Z`.

### The one thing this does NOT claim

`symoneural-llm-cli` was **retained at its 2026-08-20 build** (`4216a62b…`) beside the promoted
2026-08-26 server (`619b918f…`). A matching CLI could not be produced on this host: no commit
identity, no build record, no preserved configuration, a missing source input, and a standing
`STOP — NOT REPRODUCIBLE` verdict for this engine. The two are **not** a reproducible same-build
pair and no manifest says they are.

What was established about the retained CLI, by execution against the promoted library set:
`ldd` missing objects 0, `LD_BIND_NOW=1 --version` exit 0, all nine first-party libraries
resolved from the canonical path, 134 launcher/contract tests passing. What was not: any
behaviour reachable only through model execution. This is a **bounded accepted skew**, recorded
in `/home/google/symoneural-108-phase1a-abi-20260829T164106Z/verify/SKEW-RECORD.md`, and it is
the one piece of unfinished business this task leaves behind.
