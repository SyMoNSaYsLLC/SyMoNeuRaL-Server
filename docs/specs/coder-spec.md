# SyMoNeuRaL Coder — design spec

**Status: PROPOSAL. Nothing here is built. Nothing here is state.**
`.claude/HANDOVER.md` is the one state document; this is an input to a decision, in the
sense `docs/specs/README.md` describes.

Written 2026-08-17 against the working tree at `595835d` **plus uncommitted changes** (see
§2.2 — that detail turns out to matter for the central number in this spec).

Requested by Garrett as *"like claude coder"* — an agentic coding assistant that reads and
writes files and runs commands. He first raised it in the form recorded at
`.claude/HANDOVER.md` §2g item 2: *"i want to be able to somehow integrate site development
agent but we have to be careful to only give me that maybe by the seat — only thing with
seat is i use xrdp also for this."*

**This spec builds on the conclusion already reached there and does not re-derive it.** That
conclusion, restated so this file stands alone: an agent that can develop the site is
arbitrary code execution on the box that serves the public internet; it must never be
reachable from a visitor-facing route; "behind a password" is not sufficient on its own for
that capability; and the xrdp habit is the *safest* answer rather than a complication,
because an agent running inside his desktop session is local-only and never exposed on
`:8800` or through Caddy at all.

What follows is the engineering consequence of that decision, plus one argument §2g does not
make and which independently reaches the same place (§4.4).

---

## 1. What it is, and what it is not

### 1.1 What it is

A **local operator tool**: an agentic loop running inside Garrett's desktop session that can
read the repository, write files in it, and run commands as his user, driven by a language
model served locally on this box.

Its job is the work this repo already generates by hand — edit a generator under `tools/`,
run it twice and diff, run `node tests/frontend.mjs`, read `git log`, write a commit
message. That is a narrow, well-described loop against a codebase whose conventions are
written down in `.claude/CLAUDE.md`, which is the most favourable possible setting for a
small model.

### 1.2 What it is not

- **It is not a product surface.** Nothing about it is offered to a visitor. There is no
  "try our coding agent" page and this spec does not propose one.
- **It is not a hosted agent.** It does not answer HTTP from anywhere but loopback (§4).
- **It is not a Claude Code replacement.** Claude Code is a frontier model behind an API.
  This is a 7B at 4-bit on a consumer card. §3.5 states plainly what that model cannot do,
  because writing that down is cheaper than discovering it after a download.
- **It is not a deploy tool.** It cannot publish and it cannot restart the service. That is
  not a policy we would have to enforce — it is already true of the process boundary, and
  §7.3 explains why that boundary is the whole containment story.
- **It does not get the corpus.** `training/corpus.jsonl` and `training/build_dataset.py`
  are the two protected artefacts in `.claude/CLAUDE.md`. §7.5.

### 1.3 The relationship to SyMoNeuRaL Project

`docs/specs/project-spec.md` is the companion. The short version, because it constrains this
document: **Project is an input to Coder.** If Project stores work items and Coder acts on
them, then a world-writable Project plus a local Coder is remote code execution in two hops,
with the network step and the execution step in different specs where neither review sees
both. Project's gate therefore cannot be looser than Coder's. That is stated in both files
on purpose.

---

## 2. The hard constraint: one card, one tenant

### 2.1 The numbers, measured

One **RTX 5070 Ti**, Blackwell `sm_120`. `nvidia-smi` reports `memory.total = 16303 MiB`
(15.92 GiB), read directly on 2026-08-17. Idle baseline with no surface resident measured
**1,012 MiB** the same day.

Tenancy is arbitrated by `scripts/gpu-governor.sh`, a `mkdir` lock at `run/gpu.lock.d`. One
tenant at a time. `run/resident` holds exactly **one** surface name.

**Chat's real resident footprint — measured, not projected.** From `run/governor.log`:

```
2026-08-17 08:39:23  acquire  'chat' holds the card -- 9778 MiB free, waited 0s
```

16,303 − 9,778 = **6,525 MiB in use**, less the ~1,012 MiB idle baseline, gives
**≈ 5,513 MiB ≈ 5.4 GiB attributable to chat**. That confirms the rack's own detail line,
`~5 GB resident`, which is therefore a **measured** figure and correctly labelled.

Image is `~7 GB resident` per the rack. The weight *files* are larger than that —
`symoneural-image-unet-q4_k.gguf` 6.41 GiB plus `symoneural-image-t5-q8_0.gguf` 4.84 GiB plus the VAE and CLIP —
which is the ordinary gap between a file and what is resident at any one moment, and is the
reason the file sizes below are labelled as file sizes and nothing more.

### 2.2 A number that is about to be wrong, and why this section exists

The working-tree copy of `backend/server.py` starts `llama-server` with `-c 65536` and carries
a comment projecting that this takes chat *"from ~5 GB to ~8.7 GB of 15.92 GiB"*.

**Do not build headroom arithmetic on 8.7 GB.** Three checks, all run for this spec:

1. `git show HEAD:backend/server.py` starts llama-server with **`-c 8192`**. The 65536 change is
   **uncommitted** — `git diff --stat` shows `backend/server.py` modified by 274 lines.
2. `backend/server.py` was last written at **09:12:04**. `symoneural-api.service` last started
   at **09:00:29**. The running service therefore predates the edit and is serving `-c 8192`.
3. The 5.4 GiB measurement in §2.1 was taken at **08:39**, also under `-c 8192`.

So `~8.7 GB` is **projected** KV-cache arithmetic for a configuration that has never been
run on this machine and is not committed. It may well be right. It has not been reproduced.

This matters beyond pedantry: at 5.4 GiB resident there is ~9.5 GiB of headroom and a coder
model numerically fits alongside chat; at 8.7 GiB there is ~6.2 GiB and it is much tighter.
**Anyone acting on this spec must first establish which context size is live**, because the
answer changes the arithmetic in §2.4. Quoting a code comment's projection as a measured
resident footprint is exactly the failure this project's honesty rules exist to prevent, and
it nearly happened here.

### 2.3 What is actually on the box

`backend/models/` — note the path. `.claude/CLAUDE.md`'s build block says weights go to
`models/`; **there is no `models/` directory**, it is `backend/models/`, and that line in
CLAUDE.md is stale. File sizes read off disk 2026-08-17:

| File | Size on disk | Role |
|---|---|---|
| `llm/symon-1.0-7b-q4_k_m.gguf` | 4.36 GiB | `CHAT_MODEL` — SymonChat S1-7B |
| `llm/symon-1.0-14b-q4_k_m.gguf` | 8.37 GiB | present, **not wired to any surface** |
| `llm/symon-1.0-draft-0.5b-q4_k_m.gguf` | 379 MiB | `DRAFT_MODEL` — speculative decoding for chat |
| `image/symoneural-image-unet-q4_k.gguf` | 6.41 GiB | SymonImage F1 |
| `image/symoneural-image-t5-q8_0.gguf` | 4.84 GiB | text encoder for the above |

**There is no code model on this box.** Nothing named `Coder`, nothing from the
Qwen2.5-Coder family, no StarCoder, no DeepSeek-Coder. Anyone who assumed otherwise —
including an earlier draft of this spec — was wrong. Disk is not the obstacle: `df` reports
**884 GB available** on `/home`.

The 0.5B is worth flagging because it is easy to miss: it is chat's speculative-decoding
draft model, so the 5.4 GiB measured in §2.1 **already includes it**. It is not spare
capacity.

### 2.4 So which model serves Coder?

Three candidates. The recommendation is the third, and the reasoning is the point.

**Candidate A — reuse SymonChat S1-7B, already resident.**

Costs nothing: zero download, zero new VRAM, no new governor tenant, and when chat is
already up a coder request is served with no eviction at all. That is a real advantage and
it is why this option is listed first.

It is still the wrong answer, for a reason specific to this build rather than to
Qwen2.5-7B-Instruct: **the persona adapter is loaded**. `start_llama()` appends
`--lora <CHAT_ADAPTER>` whenever the adapter exists, and that adapter was trained on
`training/corpus.jsonl` to make the model speak as SyMoNeuRaL's admin representative and to
refuse to invent pricing. Those are exactly the behaviours you do not want between a
developer and a diff. Serving Coder off the chat process means either accepting the persona
or running a second llama-server without `--lora` — and a second llama-server is a second
copy of the weights, which is candidate C with extra steps and none of its benefits.

Base Qwen2.5-7B-Instruct is also simply not a strong coding model. It writes plausible
Python. It is materially weaker than a code-specialised model of the same size at the things
this loop needs: multi-file edits, following an existing convention, and producing a diff
that applies.

**Candidate B — Qwen2.5-14B, already on disk.**

Tempting because the file is sitting there. It is 8.37 GiB, so it cannot co-reside with a
5.4 GiB chat (13.8 GiB of 15.92 GiB before any KV cache, below the governor's 1.5 GiB floor)
and definitely not with image. It would be a full-eviction tenant on every request. And it
is an *Instruct* model, not a Coder model — you pay 8.37 GiB for general capability rather
than for coding. **Rejected**: it costs the most and buys the wrong axis.

**Candidate C — a dedicated code model. Qwen2.5-Coder-7B-Instruct at Q4_K_M. RECOMMENDED.**

Same architecture family and same quantisation as the 7B already on disk, so the file size
is **projected at ≈ 4.4 GiB by direct analogy** with the measured 4.36 GiB of
`symon-1.0-7b-q4_k_m.gguf`. That is a projection, not a measurement, and must be
labelled as one until the file is actually downloaded and `stat`'d.

It is the obvious candidate for the ordinary reason: it is the same family the rest of the
stack is built on, so llama.cpp support, chat template and tokeniser are all already proven
here.

> **Licence check before download, not after.** `LICENSES.md` already warns that
> **"Qwen licences vary by model size"** and that 7B, 14B and 0.5B are Apache-2.0 (verified),
> while other sizes are not. The Coder family has its own per-size licensing and at least one
> size is under a non-Apache Qwen research licence. **Verify the licence of the exact
> Coder size chosen and record it in `LICENSES.md` before fetching**, the same way every
> other weight set on this box was handled. Do not assume the family inherits the base
> model's terms.

**VRAM arithmetic, with both context sizes, since §2.2 leaves that open:**

| Scenario | Chat | Coder | Total | Of 16,303 MiB |
|---|---|---|---|---|
| Coder alone | — | ~4.4 GiB | ~4.4 GiB | comfortable |
| Coder + chat, `-c 8192` (**measured chat**) | 5.4 GiB | ~4.4 GiB | ~9.8 GiB | ~6.1 GiB spare — fits |
| Coder + chat, `-c 65536` (**projected chat**) | ~8.7 GiB | ~4.4 GiB | ~13.1 GiB | ~2.8 GiB spare — marginal |
| Coder + image | — | ~4.4 GiB | ~11.4 GiB | does not clear the floor |

All Coder rows are **projected**. Nothing has been downloaded and nothing has been loaded.

### 2.5 Headroom is not permission — the governor is the blocker

The first two Coder rows above fit numerically, and it would be easy to read that as "so run
them together." **It does not follow, and this is the most important paragraph in §2.**

`scripts/gpu-governor.sh` is one-tenant-at-a-time *by construction*, not by policy:

- `run/resident` holds **one** surface name. There is no representation of two.
- `evict()` is a `case` statement over single surface names, and its default arm is
  `pkill -f 'llama-server|sd-cli'` — which would kill a coder llama-server as collateral
  while logging a successful eviction of something else. The `miner)` arm exists in the
  working tree precisely because a previous surface hitting that default arm was identified
  as a bug in waiting; the comment there says so.
- `cmd_acquire` records `echo "$surface $owner" > "$HOLDER"` — single-valued again.

Co-residency is therefore a **governor redesign**, not a configuration change: it needs a
notion of a resident *set*, a VRAM budget check before admitting a second tenant, and an
eviction policy that picks a victim. That is real work with a real failure mode — the one
`.claude/HANDOVER.md` describes for containers, where two things both believe they own the
card, both load, and ~12 GB of weights hit a 16 GB card as a silent OOM at step 0 rather
than an honest deadlock.

**Recommendation: do not redesign the governor for this.** Ship Coder as an ordinary
single tenant that evicts like everything else, because §2.6 shows the cost of doing so is
small and measured.

### 2.6 What eviction actually costs — measured, and it is cheap

This is the question "does Coder evict chat on every request, and what does that do to
latency?" It does, and the answer is **about four seconds, once per alternation**.

**Drain after eviction**, from `run/governor.log`:

```
2026-08-17 08:42:06  drain    settled at 1069 MiB after 1s (floor 1500 MiB)
2026-08-17 09:07:57  drain    settled at  970 MiB after 0s (floor 1500 MiB)
2026-08-17 09:16:26  drain    settled at  996 MiB after 0s (floor 1500 MiB)
```

**0–1 s.** The 1.5 GiB floor is cleared almost immediately in practice.

**Cold start of a 7B**, from `run/api.log` (`starting chat surface` → `chat surface up`):

| Start | Up | Elapsed |
|---|---|---|
| 2026-08-16 18:25:20 | 18:25:23 | 3 s |
| 2026-08-16 22:08:01 | 22:08:04 | 3 s |
| 2026-08-17 05:41:00 | 05:41:04 | 4 s |
| 2026-08-17 08:39:10 | 08:39:14 | 4 s |

**3–4 s**, which is `mmap` plus PCIe Gen 3 ×8 staging, consistent with the ~675 ms figure
already published for staging a 7B plus llama-server's own startup.

So the honest headline is: **evict-chat-then-load-coder adds ~4–5 s to first token, on the
first coder request after a chat request and not on subsequent ones.** For an agentic loop
that then runs for minutes, that is negligible. For a visitor waiting on `/chat.html` while
a fine-tune-length coder session holds the card, it is not — which is a scheduling problem,
not a latency one, and §7.2 covers it.

**The negative result, which belongs in this spec rather than being discovered later.** Two
of the cold starts in `run/api.log` did **not** succeed — they hit the 120-second timeout and
logged `chat surface failed to come up`:

```
2026-08-16 21:28:59  starting chat surface   ->  21:30:59  ERROR chat surface failed to come up
2026-08-17 03:41:57  starting chat surface   ->  03:43:57  ERROR chat surface failed to come up
```

Two failures against eight recorded starts. The cause is not established here and should not
be guessed at, but the operational fact stands: **loading a model on this box is not
100% reliable**, and any Coder design must treat "the model did not come up" as a normal
branch with an honest error, not an exceptional one. A coding agent that silently proceeds
without its model is worse than one that refuses.

---

## 3. Shape of the thing

### 3.1 It is a local process, not a service

The recommendation in §4 is local-only, and the concrete consequence is that **Coder needs no
FastAPI route at all**. It is a CLI or TUI that Garrett runs in a terminal in his xrdp
desktop session, talking to `llama-server` on `127.0.0.1`. That is the same shape as Claude
Code itself, and it is the shape that makes the security argument trivially true rather than
enforced.

**Reach and GPU tenancy are orthogonal, and conflating them is the easy mistake here.**
Coder has no route, and it *still* needs to be a governor surface — because it loads weights
onto the one card. So:

- `scripts/gpu-governor.sh` gains a `coder)` arm in `evict()` that stops the coder
  llama-server **specifically**, by port or pidfile, rather than falling through to the
  `*)` arm that pkills every `llama-server` on the box. See §2.5; this is the exact bug the
  `miner)` arm was added to prevent.
- Coder acquires as `gpu-governor.sh with coder -- <cmd>` so the lock is always released,
  including on crash.
- **Coder holds the lock for a job, never for the session.** `.claude/CLAUDE.md` is explicit
  and `backend/server.py` already learned this the hard way — holding across a process lifetime
  once locked the CLI out until the acquire timeout. An agentic session lasts minutes to
  hours; holding the card for all of it would take the public site down for the duration.
  The lock is taken per model call and released on the token stream ending.
- **Coder never evicts `train`.** The governor already refuses this and Coder inherits the
  refusal for free by going through it.

### 3.2 If it ever does get a route — the shape, stated once

This is the **fallback design**, not the recommendation. It is written down so that if
someone later chooses §4.2 they do not improvise it, and so the constraints are on record.

Routes go at `/api/coder/*`, matching the Backstage-shaped convention
`.claude/HANDOVER.md` §5 item 13 records and that `/api/chat`, `/api/image`,
`/api/ravencalc`, `/api/tuner/*`, `/api/asicminer/*` and `/api/gpuminer/*` already follow.

**They must be declared BEFORE the `StaticFiles` mount** in `backend/server.py`. That mount is
at line 1988 and it is at `/`, so it matches everything; a route declared after it is
unreachable. `app.include_router(tuner.router, prefix="/api/tuner")` at line 1937 is the
worked example, and its comment says exactly this.

**Caddy: no change required, and knowing why is the point.** `ops/Caddyfile` only delegates
specific paths to FastAPI — `/api/*`, `/docs*`, `/openapi.json`, and the exact-match set
`/ /overview /livestack /controlboard /receipts`. Everything else is answered off disk by
`file_server` and never reaches the API. That has already shipped broken once: the four
section pages 404'd in production while returning 200 on `127.0.0.1:8800`, because the
routes existed and Caddy never asked.

Applied here:

| What you add | Caddyfile change? |
|---|---|
| `/api/coder/...` | **None.** `handle /api/*` already covers it. |
| A page at `site/coder.html`, linked as `/coder.html` | **None.** Falls through to `file_server`. |
| An extensionless `/coder` | **Yes** — and three other files. |

That last row is the expensive one: an extensionless route means editing
`tools/build/build_split.py`, `backend/server.py`, `ops/Caddyfile`, **and** `is_route()` in
`scripts/deploy.sh` (which otherwise reports `MISSING coder`, because pages link `/coder`
while the file is `coder.html`). **Do not add an extensionless route for this surface.**

And a local test run cannot catch a mistake in that list — against `127.0.0.1:8800` the API
answers directly and the Caddyfile is not exercised. `node tests/frontend.mjs
https://symoneural.com` is the only check that would.

### 3.3 No browser session assumptions

Garrett intends to build an iPhone app against this server (`.claude/HANDOVER.md` §5, items
12 and 13). Even though Coder is local-only, the same discipline applies to anything it
exposes, because "local-only" has been revised before and the cost of designing it session-free
now is zero:

- **No cookies, no server-side session.** Authentication, where it exists, is the
  `X-Symoneural-Token` header — a header any client can set, including one that is not a browser.
- **State is addressed by an explicit id in the path**, the way
  `backend/apps/streamer/routes.py` does with `/session/{sid}`.
- **Credentials never appear in a path.** `backend/apps/streamer/test_tuner.py` has
  `test_router_paths_never_carry_a_credential`, which walks `router.routes` and asserts it.
  Copy that test rather than the intention.
- **A stable JSON contract**, versioned in the response, not implied by the page that calls it.

### 3.4 What the agent is allowed to touch

Not a suggestion — this is the security boundary that makes the rest of the spec true, and it
should be enforced in code, not in a prompt.

**Allowed:** the repository at `/home/google/Symoneural`, minus the denials below.

**Denied, hard:**

- `training/corpus.jsonl` and `training/build_dataset.py` — §7.5.
- Anything matching `*.key`.
- `.claude/settings.local.json` — the deny rules live there and an agent that can edit its
  own permission file has none.
- `/var/www/symoneural` — the live webroot. It is root-owned, so this is already true; state
  it anyway so nobody "fixes" the permissions.
- Everything outside the repo root.

**Commands: allowlist, not denylist.** A denylist over a shell is not a boundary — `sudo`,
`curl | sh`, `python3 -c`, and a hundred spellings of each defeat it. The allowlist that
covers the actual work is small: `git` (minus `push`, which has nothing to push to — there is
no remote), `python3 tools/build_*.py`, `node tests/frontend.mjs`, `./scripts/symoneural.sh`,
and the read-only inspection commands.

**`sudo` is not on the list and must never be.** §7.3.

### 3.5 What this model cannot do — say it before the download, not after

A 7B at Q4_K_M doing agentic multi-file editing is **weak**, and this project's own voice is
to publish negative results rather than discover them in front of the operator.

Expect, and design for:

- **Single-file, single-function edits: workable.** Rename, add a helper, fix an off-by-one,
  write a test that mirrors an existing one.
- **Multi-file coordinated changes: unreliable.** The change that adds a section touches four
  files with an invariant between them (§3.2). A 7B will do two of the four and report
  success.
- **Long-context reasoning over this repo: constrained.** `.claude/CLAUDE.md` and
  `.claude/HANDOVER.md` are together well over 1,500 lines. At the committed `-c 8192`
  divided by `-np 2`, each slot has 4,096 tokens — the handover alone does not fit. This is
  a concrete argument for the uncommitted `-c 65536` change in §2.2, and it is the strongest
  one; it should be evaluated on its merits and *measured*, not assumed.
- **Structured output: a known failure on this hardware.** `.claude/HANDOVER.md` §2c-bis
  records this 7B looping forever when asked for a JSON object, emitting
  `{"match":["premier league","nfl","nba",…` until the token cap, so the object never closed
  and nothing parsed. The lesson recorded there — **pick the output format the model can
  finish** — applies directly and severely to a coding agent, whose entire protocol is
  structured tool calls. **This is the single largest technical risk in this spec.** A
  tool-calling loop that a 7B cannot reliably close is a feature whose happy path never
  executes, which HANDOVER rightly calls worse than an honestly absent one.
  **Prototype the tool-call format against the actual model before building anything else.**

---

## 4. Reachability and authentication

Three options, per `.claude/HANDOVER.md` §2g. The recommendation is (a), which is §2g's own
conclusion; what this section adds is the comparison written out and one further argument.

### 4.1 (a) Local-only, in the xrdp desktop session — RECOMMENDED

Coder runs as a process in Garrett's desktop session. It binds nothing, or binds
`127.0.0.1` only. Caddy has no rule for it and could not proxy it without one. There is no
route, so there is no token to leak, no gate to misconfigure, and nothing for the missing
rate limiter (§4.5) to have protected.

The security property is **structural rather than enforced**. Every other option's safety
depends on a check being correct and staying correct across future edits; this one depends
on a socket not existing. That is the difference between a control and a property, and for
arbitrary code execution on a public-facing box it is the right side of that line.

It also matches how Garrett already works — this is his existing xrdp habit, not a new one.

**The honest cost:** it only works when he is at a desktop session. No phone, no remote
kick-off, no scheduled runs. That is a real limitation and it should be stated to him
directly rather than discovered. If it becomes the binding constraint, the correct next step
is **not** to open a route; it is to reach the desktop session itself over the channel that
already exists — xrdp, or an SSH tunnel — which keeps the "no public route" property intact.

### 4.2 (b) An operator-gated route, `SYMONEURAL_CODER_ENABLED` + `SYMONEURAL_CODER_TOKEN`

The pattern is already in the repo, in `backend/apps/asicminer/__init__.py`: off unless
`SYMONEURAL_ASIC_ENABLED=1` **and** `SYMONEURAL_ASIC_TOKEN` are both set, `enabled()` requiring both,
`token_ok()` using `hmac.compare_digest` so a wrong token cannot be found a character at a
time, and `_asic_auth()` in `backend/server.py` answering 503 when the surface is off and 401
on a bad token. It fails closed on a misconfiguration, which is the right default for a box
serving the public.

**It is a good pattern and it is still not sufficient here**, for a reason that is about the
capability rather than the gate. `backend/server.py`'s own comment on the GPU miner gate gets
at it: an unauthenticated route there would let a stranger evict chat and hold the GPU — "a
denial of service with a wallet address attached." Coder is a strict escalation of that. The
worst case for a leaked ASIC token is rig telemetry and a scan of a private range. The worst
case for a leaked Coder token is **arbitrary code execution as the user that owns the
repository, the site and the model weights**.

A shared secret in an environment variable is a fine gate for an operator tool. It is not a
fine gate for RCE on a public host, and §2g already says so: *"behind a password" is not
sufficient on its own for that capability*.

**If it is chosen anyway** — which is Garrett's call, not an agent's — then at minimum: bind
the route to loopback and reach it through an SSH tunnel rather than through Caddy; keep it
out of `ops/Caddyfile` so it is unreachable from the internet by construction even when
enabled; and treat the token as a second layer rather than the layer.

**A third gate, and it is better than the two above — `SYMONEURAL_CODER_ALLOW_REMOTE`.** This is not
this spec's invention; it already exists in `backend/apps/coder/__init__.py` (§10) and it
should be treated as **mandatory** if option (b) is ever chosen. The idea: with
`SYMONEURAL_CODER_ENABLED=1` and a correct `SYMONEURAL_CODER_TOKEN`, a peer whose address is not loopback
is **still refused** unless `SYMONEURAL_CODER_ALLOW_REMOTE=1` is also set.

That is a genuine improvement on the argument in §4.1 rather than a belt-and-braces extra.
§4.1 says local-only is safe because it depends on *a socket not existing* — structural, but
it evaporates the moment someone later wires a route, and specs do not stop that. The peer
check is the version of the property that **survives the route being wired**: the socket may
exist, the token may be correct, and a remote caller is refused anyway. It converts
"local-only" from a deployment convention into a code-enforced invariant with a test.

Two implementation notes worth carrying, both already handled in that module: the peer must
be the **real socket peer** (`request.client.host` in FastAPI), never a forwarded header,
which an attacker sets freely; and uvicorn on a dual-stack bind reports `::ffff:127.0.0.1`,
whose `.is_loopback` is **False** — so a naive check refuses legitimate local traffic and
someone "fixes" it by widening the check. Handle the mapped form explicitly.

### 4.3 (c) Public — rejected

No conditions. A public route to an agent that writes files and runs commands on the host
serving symoneural.com is the failure this whole section exists to avoid. It is listed only
so the comparison is complete.

### 4.4 One argument §2g does not make, reaching the same conclusion

§2g's reasoning is about **execution**: an agent that develops the site is RCE on a public
box. There is a second, independent argument from **exfiltration**.

An agentic coder needs to read the repository. The repository contains
`training/corpus.jsonl` — 327 hand-authored examples that `.claude/CLAUDE.md` identifies as
one of exactly two artefacts protected *only by not being public*, and it makes the legal
point sharply: trade secret, unlike copyright, exists only while reasonable measures are
taken to keep it that way, and once it is out it cannot be pulled back.

So any route to Coder is an exfiltration path as well as an execution path — and one that
leaves no trace, since reading a file is not a change anyone reviews. Even a *read-only*
Coder, which one might reason is safe enough to expose, would carry this risk in full.

This lands in the same place as §2g by a different road, which is the useful part: the
local-only recommendation does not depend on the RCE argument alone.

### 4.5 Rate limiting is off, so a token would be the only gate

Per-endpoint rate limits were **switched off across the API on 2026-08-17 at Garrett's
instruction**. `backend/server.py` builds `LIMITS` from `SYMONEURAL_RATE_*` environment variables and
unset means `(0, 0)`, which means no limiter object at all. Nothing is metered right now.

The code is explicit about the consequence, in the GPU miner gate: *"The token IS the gate
now. Rate limiting was switched off across the API on the operator's instruction, so there is
no second layer catching a brute-force attempt."*

For option (b) this is decisive: there would be exactly one gate, no lockout, no backoff, and
no throttle on guessing. `hmac.compare_digest` defeats timing attacks but does nothing about
volume. **This is not an argument for turning rate limiting back on** — Garrett's reasoning
holds, and `backend/server.py` records it: on one GPU a rate limit never bought throughput, the
one-deep queue rations the card by itself. It is an argument that option (b) is thinner than
it looks. Option (a) is unaffected: there is nothing to brute-force.

---

## 5. The rack unit

### 5.1 Naming — get this right, because a live example is wrong

The convention, from the `Unit` list in `backend/server.py`: **`label` is the product name and
nothing else.** SyMoNeuRaL Chat, SyMoNeuRaL Image, SyMoNeuRaL Remix, SyMoNeuRaL RavenCalc,
SyMoNeuRaL Miner, SyMoNeuRaL Miner GPU, SyMoNeuRaL Gateway. The technique goes in `spec`,
the footprint and attribution in `detail`.

`Unit(id="train", label="SyMoNeuRaL Quantized Low-Rank Adaptation Tool", …)` **is a defect**
and this spec must not copy it. Two things are wrong with it. It prefixes our name onto a
generic technique expansion rather than being a product name — "SyMoNeuRaL Quantized
Low-Rank Adaptation Tool" is not a thing anyone would call anything. And it is visibly
breaking the rack layout by wrapping to **five lines**, in a section that
`.claude/HANDOVER.md` already measures as over its vertical budget. Its own `spec` field
already says `SymonChat persona adapter · QLoRA`, so the technique is stated correctly one
line below the label that duplicates it badly.

(Fixing that unit is out of scope here — this spec is not permitted to edit `backend/` — but
it is a one-line change and worth raising: **`label="SyMoNeuRaL Tuner"`** collides with the
IPTV Tuner, so something like **`label="SyMoNeuRaL Forge"`** or simply **`"SyMoNeuRaL
Adapter"`** would follow the convention. Garrett's call; it is a product name.)

### 5.2 The unit

```python
Unit(id="coder", label="SyMoNeuRaL Coder", slot="1U",
     state=coder_state,          # computed, never hardcoded -- see 5.3
     bus="gpu",
     href="/documentation.html#coder",   # an explainer, NOT a control -- see 5.4
     spec="SymonCoder C1-7B · Q4_K_M",
     detail=coder_detail)
```

| Field | Value | Why |
|---|---|---|
| `id` | `coder` | Matches the governor surface name in `run/resident` and the `coder)` arm in `evict()`. One name for one thing. |
| `label` | `SyMoNeuRaL Coder` | Product name only. §5.1. |
| `slot` | `1U` | It is one model, comparable to chat's 1U. Image is 2U for two weight sets; Coder has one. |
| `bus` | `gpu` | It loads weights onto the card and contends for the lock. **Do not invent a fifth bus value.** |
| `state` | computed | §5.3. |
| `spec` | `SymonCoder C1-7B · Q4_K_M` | Product name first, then quantisation — the shape `SymonChat S1-7B` and `SymonImage F1 · q4_k` already use. |
| `detail` | see §5.3 | Carries the Apache-2.0 attribution, **if and only if** the chosen model turns out to be Apache-2.0 (§2.4). |

**On `bus`: use one of the existing four.** `Literal["gpu", "cpu", "asic", "net"]`. Adding
`asic` and `net` for the mining and IPTV surfaces exposed a live bug — `site/console.js`
rendered `u.bus === 'cpu' ? 'CPU' : 'GPU'`, so an ASIC surface printed "GPU", the wrong
hardware on the one plate the page asks a visitor to trust. It is a `BUSES` lookup now
returning `--` for anything unrecognised, which fails honestly but still fails. A new bus
value means editing `console.js` in the same change or shipping a `--`. Coder runs on the
GPU; `gpu` is both correct and free.

### 5.3 The honest default state

**`offline`**, and it must be *computed*, not hardcoded — the same way `gateway_state`,
`asic_state` and `gpuminer_state` already are.

The rule this follows is the one already applied to the GPU miner in `backend/server.py`:
`offline` until a miner binary is configured, because there is none on this box and nothing
here has ever hashed, so any hashrate figure would be invented. Coder is in exactly that
position: no weights, no process, nothing has ever run.

```
no coder model file on disk         -> "offline",  "no coder model installed"
model present, not resident         -> "ready",    "~4.4 GB when loaded · built on <base>"
run/resident == "coder"             -> "busy",     "agent session holding the card"
governor held by another surface    -> "queued"
```

`ready` may only be reported once the weights are actually on disk and a load has been
demonstrated. **A unit reporting `ready` for a model nobody has ever loaded is the
decorative indicator this site exists to argue against** — indistinguishable from a working
one in a screenshot, which is precisely the trap `.claude/HANDOVER.md` §2c-ter describes for
the GPU panel.

### 5.4 Two problems with putting Coder on the public rack at all

**Problem one: `href`.** Every existing unit's `href` goes to a page a visitor can *use* —
`/chat.html`, `/image.html`, `/ravencalc.html`, `/miner.html`. Coder has no such page and
must not have one (§1.2). Pointing its `href` at a control surface would contradict this
entire spec; pointing it at nothing breaks the pattern. The proposal above sends it to a
**documentation anchor that explains and does not control**. That is honest, but it is a
different kind of destination from every neighbour, and a visitor who clicks expecting a
surface gets a paragraph.

**Problem two: the rack is already over budget.** `backend/server.py` currently builds **nine**
units — chat, image, remix, ravencalc, train, asicminer, gpuminer, tuner, gateway. (Note:
`.claude/HANDOVER.md` §0 still says eight; `gpuminer` was added after that line was written.
Counted directly for this spec.) `.claude/HANDOVER.md` §3.0 measures Live stack as fitting at
1920×1080, 1855×745 and 1440×900, but **over by 76px at 1301×740** — with nine units and
with the `train` label already wrapping to five lines.

A tenth unit is a real layout regression, not a cosmetic one. **Implementing this requires
re-measuring Live stack at 1301×740 and at 1855×745 (Garrett's own window) as part of the
same change**, reading computed styles rather than reasoning about it, per
`.claude/CLAUDE.md`.

**Recommendation: specify the unit now, add it only when Coder actually runs.** Until then
its state is permanently `offline` and no visitor can ever use it, which makes it a row that
costs vertical budget and conveys nothing — close enough to decoration to be worth avoiding.
When it does run, it earns its place honestly: the card genuinely has a tenant named `coder`
sometimes, the rack genuinely reads that from `run/resident`, and "this box also runs the
agent that develops this site" is a true and unusually good thing to be able to show.

---

## 6. What must be measured before any figure about this reaches the site

`.claude/CLAUDE.md` requires every figure be labelled **measured** on this machine,
**vendor** specification, or **projected** arithmetic. Nothing in this spec has been
measured about Coder, because Coder does not exist. **Every Coder number in this document is
projected**, and the table below is the list of things that must be turned into measurements
before any of them appears on a page.

| Figure | Status now | How to measure |
|---|---|---|
| Coder weights, file size | projected ~4.4 GiB by analogy | `stat` the `.gguf` after download |
| Coder resident VRAM | projected | `nvidia-smi memory.free` while loaded, minus the ~1,012 MiB idle baseline — the method §2.1 uses |
| Coder tok/s | **unknown** | llama-bench or an instrumented request. **Do not reuse chat's 80–92 tok/s** — different weights, and code generation has a different token mix |
| Cold-start time | projected 3–4 s from chat's | Time `starting` → `up` in the log, ≥ 5 runs, and record the failures too |
| Evict + drain | **measured 0–1 s** ✓ | `run/governor.log`, already done |
| Chat resident | **measured ~5.4 GiB at `-c 8192`** ✓ | §2.1, already done |
| Chat resident at `-c 65536` | **projected ~8.7 GiB, never run** | Commit the change, restart, re-measure. §2.2 |
| "Coder edits this site" as a claim | **unproven** | A real change, generated by the agent, that passes `node tests/frontend.mjs` and survives review |

That last row is the one to be careful with. It is the only Coder claim with marketing value
and it is the easiest to overstate. It is true when a diff the agent wrote is in `git log`
and the suite is green — not when the agent has produced text that resembles a diff.

---

## 7. What could go wrong

### 7.1 The agent is asked to modify the running API — the required scenario

Garrett asks Coder to add an endpoint. It edits `backend/server.py`. Four things can happen, in
increasing order of nastiness:

**(1) It writes a syntax error.** The running service is unaffected — a running Python
process pins its imports at start (`.claude/HANDOVER.md` §0b). Nothing breaks until someone
restarts. Caught by `python3 -m py_compile`, which should be a mandatory post-edit step in
the agent's own loop.

**(2) It adds a route after the `StaticFiles` mount.** The mount is at `/` and matches
everything, so the route is silently unreachable — no error, no log line, a 404 that looks
like a typo. `backend/server.py` warns about this in two places and a 7B will still do it,
because the file is 1,992 lines and the mount is at the bottom. **Detection:** assert the
route answers, not that the code contains it.

**(3) It adds a route Caddy never delegates.** Works perfectly on `127.0.0.1:8800`, 404s in
production. This has already shipped once (§3.2). **Detection:** `node tests/frontend.mjs
https://symoneural.com`. A local run cannot catch it — this is the single most likely way a
Coder change reaches production broken, because every local signal says it is fine.

**(4) It breaks the status endpoint.** The worst one, and the least obvious. Every unit's
state is computed inside one `Status` response; `backend/apps/asicminer` has an explicit
comment that its probe *never raises*, because the rack renders it and **a surface that
throws takes the whole status endpoint with it** — which means the rack, the control board,
the GPU panel on five pages, and the WebSocket feed all go dark together. An agent adding a
tenth unit that raises on a missing file would do exactly this. **Detection:** the suite
asserts units render from `/api/status` with real values, so it catches this — *if it is
run*.

### 7.2 Coder holds the card while a visitor waits

An agent session is minutes to hours. Chat is a page view. If Coder holds the governor lock
for its session, symoneural.com's chat and image surfaces queue behind it until the acquire
timeout, and a visitor sees a dead surface on a site whose entire argument is that the
machine is live.

**Mitigations, in order of preference:**

1. **Per-job locking** (§3.1) — the lock is held for a model call, not a session. This is
   already the rule and it mostly solves the problem: between calls the agent is thinking,
   editing files, and running tests, none of which touch the card.
2. **Coder yields, like the GPU miner.** `backend/server.py` describes `gpuminer` as the
   opposite of `train`: it yields to everything, because no hashrate is worth making a
   visitor wait. The same reasoning applies — no refactor is worth a dead chat surface. The
   cost is that a Coder session gets slower when the site is busy, which is correct.
3. **Do not make Coder un-evictable.** `train` has that status because a half-finished
   fine-tune is unrecoverable. A coder turn is not: it can simply be re-run.

### 7.3 The blast radius, and why it stops where it does — rollback

**This is the containment story and it is built from what already exists. Do not invent
machinery for it.**

- **No git remote.** History never leaves this box. `git log`, `git diff`, `git stash` and
  `git worktree` are the safety net, and they are enough because every change is local and
  every commit in this repo states its reason. **Coder should work in a `git worktree`** —
  its edits then cannot touch the tree Garrett is looking at, and abandoning a bad session is
  `rm -rf` on a directory rather than an unpick.
- **The agent cannot deploy.** `sudo scripts/deploy.sh --prune` needs root. It is not on the
  allowlist (§3.4) and must never be. So a bad edit to `site/` **cannot reach a visitor**,
  full stop — the staging `site/` and the live `/var/www/symoneural` are different
  directories and only root crosses between them.
- **The agent cannot restart the service.** `sudo systemctl restart symoneural-api` needs
  root. Combined with §7.1(1), a bad edit to `backend/server.py` is **inert** until a restart
  that someone with root chooses to run.
- **`./scripts/symoneural.sh off` is the kill switch**, and it frees the card too.
- **`node tests/frontend.mjs` is the gate before that restart** — 26/26 locally and against
  production.

The shape of that is worth stating plainly: **every path from a Coder edit to a visitor
passes through a `sudo` command that Garrett types.** That is a human review step enforced by
file permissions rather than by policy, and it is why local-only Coder is a bounded risk
rather than an open one.

**The rollback procedure, in order:**

```bash
cd <the coder worktree>
git diff                      # what did it actually do
git stash                     # or: git checkout -- <file>
node tests/frontend.mjs       # confirm the tree is sane again
# only if a bad edit was already committed:
git revert <sha>              # not reset -- keep the record of what happened
```

If a bad edit was already restarted into the service: `git revert`, then
`sudo systemctl restart symoneural-api`. If it was already deployed:
`sudo scripts/deploy.sh --prune` after reverting, since prune removes what the deploy would
no longer publish.

### 7.4 The agent edits its own guardrails

An agent that can edit `.claude/settings.local.json`, its own allowlist, or its own system
prompt has no guardrails — it has suggestions. Those files are on the deny list in §3.4.
Note the second-order version: an agent that can edit `.claude/CLAUDE.md` can rewrite the
rules the *next* agent follows, which is a slower and much harder-to-notice version of the
same problem.

### 7.5 The corpus walks out

Covered in §4.4 as an argument. As a failure mode: the agent reads `training/corpus.jsonl`
for context, summarises it into a commit message, a comment, or a page, and the method is
public. `.claude/CLAUDE.md` anticipates precisely this — *"an agent asked to 'publish the
manual' could reasonably mistake the corpus for documentation."*

**Deny at the filesystem level (§3.4), not in the prompt.** A prompt instruction is a request;
a path deny is a boundary. And note that "no git remote" is doing a lot of the protecting
here — if a remote is ever added, this becomes materially worse, which `.claude/CLAUDE.md`
already flags.

### 7.6 Two agents, one repo

`.claude/CLAUDE.md` warns that the generator scripts all rewrite files under `site/`, so two
writers in that directory clobber each other. Coder is a writer. If Garrett runs Coder while
a Claude Code session is also working, that hazard is live and neither side can see the
other. The `git worktree` recommendation in §7.3 addresses this as a side effect, which is a
second reason to adopt it.

### 7.7 The model is not good enough and the loop looks fine anyway

The structured-output failure in §3.5 is the specific version of this. The general version is
worse: an agent that produces confident, plausible, wrong diffs is more expensive than no
agent, because reviewing them costs more than writing the change. **Measure this before
building the UI**, on real tasks from this repo, and be willing to record "a 7B could not do
this" as the finding. That result is publishable in this project's voice and it is a genuine
saving.

---

## 8. Recommendation, in one paragraph

Build Coder as a **local-only agentic CLI in Garrett's xrdp desktop session**, driven by
**Qwen2.5-Coder-7B-Instruct at Q4_K_M** (≈4.4 GiB projected, licence verified before
download), registered as a **governor surface named `coder` with its own `evict()` arm**,
holding the lock **per model call and never per session**, working in a **`git worktree`**,
with a **command allowlist that excludes `sudo`** and a **path deny list covering
`training/corpus.jsonl`**. Give it **no FastAPI route and no Caddyfile entry**. Specify the
rack unit as `label="SyMoNeuRaL Coder"`, `bus="gpu"`, default state **`offline`** computed
from disk and `run/resident`, but **do not add it to the rack until it actually runs** — Live
stack is already 76px over budget at 1301×740 with nine units.

**Before any of that, do two things in this order:** settle whether the live context size is
`-c 8192` or `-c 65536` (§2.2), because it changes the headroom arithmetic; and prototype the
tool-call format against the actual model (§3.5), because if a 7B cannot reliably close a
tool call, none of the rest of this matters.

---

## 9. Open questions for Garrett

1. **Is desktop-session-only acceptable?** It is the recommendation and it means no phone,
   no remote start. If not, the next step is reaching the desktop over xrdp or an SSH
   tunnel — **not** opening a route.
2. **What should the `train` unit actually be called?** `SyMoNeuRaL Quantized Low-Rank
   Adaptation Tool` is wrong and is wrapping to five lines (§5.1). It is a product name, so
   it is his call.
3. **Does Coder appear on the public rack at all?** The recommendation is yes, but only once
   it is real (§5.4). "This box runs the agent that develops this site" is a strong and true
   claim; it is worth nothing while the unit reads `offline`.
4. **Per-seat licensing** — §2g notes this is a separate question from access control and
   should not be conflated with it. `backend/apps/licensing/` can gate *use*; it does not
   gate *reach*. Worth deciding separately, and note the signing key's private half is gone
   (`.claude/HANDOVER.md` §5 item 0), so nothing can be issued today regardless.

---

## 10. A concurrent implementation exists — read this before acting on §2 or §5

**Found while writing this spec, at 09:27–09:31 on 2026-08-17:** `backend/apps/coder/` is
present in the working tree and **untracked**. It is `__init__.py` (36 KB) plus
`test_coder.py` (30 KB), written by another agent working in parallel. This spec was drafted
independently and the two were reconciled afterwards rather than merged.

**Where they agree**, which is most of it and is reassuring rather than redundant: local-first
and off by default; the `SYMONEURAL_CODER_ENABLED` + `SYMONEURAL_CODER_TOKEN` pattern copied from
`backend/apps/asicminer/`; `hmac` constant-time token comparison; fail-closed everywhere,
written explicitly against the SyMoN_ML `return True` fallback in `.claude/HANDOVER.md` §5
item 1; a denylist covering `training/corpus.jsonl`, `training/build_dataset.py` and
`training/adapter/`, applied to the **resolved** path so a symlink cannot launder it; path
containment via `Path.resolve()`; commands run argv-only, never through a shell. That module
independently reached §4.4's exfiltration conclusion and §3.4's allowlist boundary.

**Where they diverge, and it is one real question, not a wording difference.**

That module's `unit_state()` reports the surface as taking **"no GPU lease"** and holding no
card. This spec's §3.1 and §5.2 say Coder is a governor surface with `bus="gpu"` and its own
`coder)` arm in `evict()`.

Both are correct about different things, and the gap between them is the unanswered question:

- The module is the **harness** — file operations, path containment, command execution. A
  harness genuinely holds no weights and needs no lease. Its `unit_state()` is accurate about
  itself.
- This spec is about the **whole surface**, including which model serves it (§2.4). If Coder
  runs a dedicated code model, *something* takes the lock and `bus="gpu"` is right. If Coder
  drives the existing `/api/chat`, then chat takes the lock, Coder itself does not, and
  `bus="cpu"` would be right — but that is candidate A, which §2.4 rejects because the
  persona adapter is loaded and those refusals do not belong between a developer and a diff.

**So the model decision in §2.4 is upstream of the `bus` value, and it has not been made.**
Do not resolve this by picking whichever label is closer to hand. Decide the model first;
`bus` then follows, and only then is the rack unit specifiable.

**Two things verified rather than assumed**, because they change what is left to do:

- **`scripts/gpu-governor.sh` has no `coder)` arm.** Its uncommitted +14 lines are the
  `miner)` arm, not a coder one. So §3.1's recommendation stands as work to do, and the
  collateral-kill hazard is live: a coder `llama-server` would today hit the `*)` default and
  be pkilled as part of evicting something else.
- **`backend/server.py` has no coder route and no coder `Unit`**, and `ops/Caddyfile` has no
  coder reference. Nothing is wired. The label `SyMoNeuRaL Coder` is unclaimed, so §5.1's
  naming prescription is still a specification rather than a rename.

**The honest status: the harness is largely built; the model, the governor integration and
the rack unit are not.** Anyone continuing should read `backend/apps/coder/__init__.py`
first — it is ahead of this document on sandboxing and its `SYMONEURAL_CODER_ALLOW_REMOTE` gate
(§4.2) is better than anything specified here — and treat §2, §5, §6 and §7 of this file as
the parts still open.
