# Control-board coder launcher and batch rotation

Owner requirements R-182 / R-183, 2026-09-02. Implementation is carried by PROJECT-TASKS.md
#109 with #77, #90, and #104 dependencies. This is a product/execution specification,
not a second state tracker. Current delivery is documentation only.

## Required launcher selections

| Mode | Coders |
|---|---|
| Single | Symon |
| Single | Claude |
| Single | Codex |
| Dual | Symon + Claude |
| Dual | Codex + Symon |
| Dual | Codex + Claude |
| Tri-coder batch | Symon + Claude + Codex |

Show all seven selections. Each selected coder needs a real availability/authentication
reading. If a coder is absent, unauthenticated, or not qualified, explain the exact reason
and disable only the affected combinations. Do not simulate availability or hide the option.
User-facing names are Symon, Claude, and Codex; Symon means the local SyMoNeuRaL Coder.

The existing control board is the entry point. Extend its established UI, API, account
authorization, and task infrastructure. Do not create a separate unrelated dashboard or
expose raw shell commands, provider credentials, or implementation environment variables
as the normal product flow.

## Selection and launch

The user chooses the project/workspace, existing numbered tasks or a bounded task batch,
participating coders, their order/starting executor, and limits. Display the actual scope,
incoming plan, next executor, and constraints before Start. Remember chosen settings without
storing credentials in browser storage or embedding them in pages.

Default to the agreed Codex → Claude sequence today. The default three-coder cycle after
qualification is Codex → Claude → Symon → Codex; allow the operator to choose a recorded
starting point/order. A pair alternates its selected coders. A single coder handles the same
phases itself while still producing separate plan and result artifacts.

Batch processing means consuming the selected queue with those assignments and handing off
between coders. It does not implicitly authorize unrelated tasks, indefinite work, additional
spending, or simultaneous writes to one checkout.

## Execution cycle and handoff contract

For each item:
1. Load the owner request, numbered task, incoming plan, and previous evidence.
2. Verify prerequisites and current revision/runtime identity.
3. Execute the scoped work.
4. Run the declared meaningful checks and real application acceptance.
5. Save the Markdown execution response and update the canonical records.
6. Write the bounded next-coder plan, with recipient and source-response links.
7. Advance only when the handoff artifacts exist and accurately reflect the result.

The next coder verifies the prior work before continuing. An error, missing prerequisite,
unavailable provider, rejected permission, or interrupted process must be recorded honestly;
it must not count as success or silently advance the batch.

Use supported installed APIs/CLIs or existing provider integrations. Detect their actual
capabilities and authentication before writing adapters. Do not invent command-line flags,
scrape private provider sessions, bypass permission prompts, or assume that launching a
terminal is equivalent to a functioning coder. Reuse existing Studio/runtime contracts
where applicable instead of creating a competing registry or GPU governor.

## Controls and persistence

Provide Start, pause after the current safe step, Resume, graceful Cancel/Stop, and explicit
Retry from a recorded checkpoint. Display a queue, current coder and task, phase, last useful
progress, checks/results, handoff destination, and links to saved plans/responses.

Persist batch/run/task IDs, coder order, workspace/revision, process/session identity,
timestamps, bounded scope, status transitions, exit reasons, and artifact paths. After a page
refresh or controller restart, reconcile records against actual processes. Prevent duplicate
launches and accidental replay of completed effects. A canceled job must not leave an orphan
coder, an abandoned workspace lock, or an unreleased GPU lease.

Expose configurable task/iteration/time/usage limits supported by each adapter; show unknown
usage honestly. End when the selected queue is complete, a configured limit is reached, or
the operator stops it. Do not create an unbounded automatic planning loop.

Keep operator control distinct from coder-generated text. A plan cannot grant itself new
permissions, change its allowed workspace, increase its budget, or promote itself to admin.
Use the approved authenticated owner/operator path for privileged launches; normal users
and anonymous callers must not gain command execution through the launcher.

## Shared workspace and GPU

Use one writer per checkout. If independent jobs run concurrently, isolate their writable
workspaces or explicitly nonoverlapping files, including generated assets. Preserve user
changes and show the base/result revision in each handoff. Do not let multiple coders rewrite
the same task block or frontend generator outputs concurrently.

All local inference/training/render/mining contention goes through the existing GPU governor.
Follow its job-scoped lease and drain rules; do not evict protected training or start a second
scheduler for the same card.

## Symon admission and the training objective

Before enabling Symon as an executing member, demonstrate a bounded task using the actual
local Symon model: read a plan/context, reason and call authorized tools, apply a change,
run meaningful verification, save a complete response, resume, and produce a valid next plan.
Verify permission refusal, interrupted-run behavior, and artifact preservation.

Carry the broader training objective through the existing model/LoRA tasks: documented
training data and split, configuration, base/adapter provenance, held-out evaluation,
serving-compatible artifacts, rollback, and real channel tests. Do not treat loading a base
model or a decreasing training loss as proof that the trained Symon model is ready.

Use each channel's appropriate runtime. Chat/cowork/Coder reasoning, Image/Sigils rendering,
Studio tools/plugins, LoRA training, and Miner operation need distinct real acceptance proof.
Do not force all supporting computation onto the GPU or claim that the LLM performs mining.

## Session modes — R-184 / R-185

The launcher has three distinct session modes. The coder selections above apply to all of
them; the modes differ in what happens to the prompt and to the responses.

| Mode | Prompt | Coders | Result |
|---|---|---|---|
| **Rotation** (R-182) | a bounded task batch | act **in sequence** | each executes, verifies, hands off to the next |
| **Multi-response** (R-184) | **one** user prompt | act **in parallel** | every coder answers; all answers shown attributed |
| **Training** (R-185) | a training subject | trainers → receiver | trainers agree on one prompt, then send it |

Rotation is the sequential execution contract already specified above. The two modes below
are additions, not replacements — a session selects one.

### Multi-coder response mode — R-184

One prompt, fanned out to **every selected coder**. Each response renders **separately and
attributed by name** (Symon / Claude / Codex), in the shape the owner specified:

```
User Prompt ... How do you count to 10?
  symon  response  1,2,3,4,5,6,7,8,9,10
  codex  response  1,2,3,4,5,6,7,8,9,10
  claude response  1,2,3,4,5,6,7,8,9,10
```

- **Never merge, average, summarise into one voice, or silently rank responses.** The user
  asked to see each coder's answer; a blended answer destroys the thing being asked for.
- **Never hide a dissenting answer**, and never drop a coder that failed — show the failure
  with its measured cause.
- **Attribution must be exact.** A response labelled with the wrong coder is worse than an
  unlabelled one. Bind each response to the adapter identity that produced it.
- On **agreement**, state that they agree and still show each attributed response.
- On **disagreement**, the launcher **must not choose**. Present every coder's option and
  let the user decide. Offer a **discussion/debate** option in which the coders exchange
  positions for clarification; the user keeps the decision, and every round is recorded.
- Determining agreement is a comparison, not a judgement call by one coder. Compare the
  actual responses; do not appoint one coder as arbiter of another's answer.
- Record the prompt, every response with attribution, the agreement/disagreement finding,
  any debate rounds, and the user's final decision.

Partial availability is honest: if two of three coders answer, show two answers and the
measured reason the third did not. Do not present that as a three-coder session.

### Training mode — R-185

Selected inside a tri-coder (or pair) session. The operator picks three things:

| Selection | Example |
|---|---|
| **Training subject** | OpenEmbedded coding |
| **Training providers (trainers)** | Codex + Claude |
| **Training receiver** | Symon |

Sequence:

1. Each trainer **independently** produces its training output for the subject. Independent
   means not shown the other trainer's answer first.
2. The trainers converge on **one** training prompt.
3. **100% agreement is mandatory** before anything reaches the receiver.
4. Only then is the single agreed prompt sent to the receiver.

**What 100% agreement means, and what it does not:**

- It means **every trainer explicitly assents to the identical final prompt**. Record the
  assent from each trainer alongside the verbatim agreed text.
- A similarity score, an embedding distance, or "close enough" is **not** agreement.
- Every selected trainer must approve; a majority rule must not replace unanimity.
- **An orchestrator must never synthesise a compromise prompt and present it as consensus.**
  That would be the launcher inventing a trainer opinion that no trainer held.
- If the trainers do not fully agree, **nothing is sent to the receiver.** The disagreement
  surfaces to the user under R-184, who decides or invokes debate. A blocked run is a
  correct outcome, not a failure to route around.

Constraints:

- A receiver must not also be one of its own trainers in the same run.
- The receiver's training path is the **existing model/LoRA work**: documented training data
  and split, configuration, base/adapter provenance, held-out evaluation, serving-compatible
  artifacts, and rollback. **Agreement on a prompt is not evidence that training occurred,
  and a sent prompt is not a trained model.** Do not archive a training task on the strength
  of a consensus record.
- Training runs take the GPU through the existing governor lease and drain rules, and must
  not evict protected training.

Record per run: subject, trainer and receiver identities, each trainer's independent output,
the agreed prompt verbatim, each trainer's assent, what was sent, what the receiver did, and
the resulting artifacts or the reason none were produced.

## Required acceptance evidence

- All seven selections render correctly at desktop and mobile sizes; unavailable selections
  state a measured cause and available combinations remain usable.
- Each provider adapter passes meaningful contract/error tests. Actual connected single-coder
  executions are demonstrated for every available coder; mocks are labeled as mocks.
- Every requested pair completes a real bounded handoff with the second coder consuming the
  first coder's saved result/plan. The tri-coder batch completes a real three-member cycle
  after Symon qualifies. Unavailable coverage remains unverified.
- Queue ordering, duplicate Start protection, pause/resume, graceful cancellation, failure,
  retry, limits, refresh/restart recovery, and permission denial have evidence.
- Canonical request/task/handoff/progress records match the actual run, with preserved
  Markdown plans and responses. No task is archived because a placeholder report exists.
- Repo/GPU concurrency and secret protection are checked; real application and output
  evidence accompanies source tests.
- **Multi-response (R-184):** one prompt reaches every selected coder; each response renders
  attributed and unmerged; an induced disagreement surfaces every option without the launcher
  picking one; the debate option runs and is recorded; a failed coder shows a measured cause
  rather than vanishing; attribution is proven correct by binding responses to adapter identity.
- **Training (R-185):** trainers produce independent outputs; an agreed run sends exactly the
  agreed prompt, with each trainer's assent recorded; **an induced disagreement sends nothing
  to the receiver** and surfaces to the user; a synthesised-compromise attempt is rejected;
  receiver-is-also-trainer is refused. Evidence of a real receiver run, not only a routed prompt.

Write ops/registry/SMOKE-CODER-LAUNCHER.md only after the actual integrated browser/runtime
exercise. Include tested revision, provider/runtime identities, timestamp, actions, outcomes,
and precise remaining coverage. A full PASS requires the requested single, dual, and
three-coder paths to work; partial availability is not full completion.

## Delivery sequence

First restore the real local model/application prerequisites described by the existing
repair handoff. During that batch identify the installed Claude/Codex integration options
and return their measured prerequisites in the next Codex plan. Then implement the launcher
incrementally: connected adapters and single-coder execution, persisted dual rotation,
followed by Symon admission and tri-coder batch execution. Keep all requirements visible
under #109 until their real checks pass. Preserve earlier evidence and newer owner decisions.

## Implementation clarifications after provider readiness — 2026-09-02

Claude's R-184/R-185 sections above remain the product contract. Codex measured actual
Claude/Codex response paths and restored Symon's local Chat backend in R-186; evidence and
the proposed per-provider envelope are in
review/RESPONSE-2026-09-02-codex-provider-readiness.md. These measurements do not mean the
launcher or a provider adapter has been implemented.

Readiness is activity-specific: answering through the real local model can be enabled
before Symon qualifies for workspace tool execution. Preserve the execution-admission
requirement for the latter. Keep all participant presets visible with exact failure causes.

For ordinary multi-response comparison, retain every answer. Exact normalized text or a
declared structured comparison can establish matching outputs; differing or uncertain
answers need user review. Do not label all paraphrases contradictory or allow one model to
choose a winner. A discussion starts only when the user requests it and uses bounded rounds.

For training, every selected trainer approves the identical versioned candidate, with an
approval record tied to its session, trainer identity, and content hash. Recheck the complete
approval set atomically at delivery. Edits invalidate prior approvals; roster/receiver changes
start a new round. Missing/failed trainers are never silently removed. A user may select a
proposal for renewed review, but delivery still requires every trainer's approval. Apply this
to every training prompt in a batch. No "send anyway" path may claim unanimity.

Limit debate and preserve non-converged drafts; unanimity is a delivery condition, not a
promise that models will converge or that the agreed lesson is correct. Prevent replay or
duplicate delivery after retries/restarts and reconcile uncertain receipts before resending.
Show trainer approvals, the exact final prompt, and the receiver's measured outcome.

A teaching exchange alone does not change weights. Persistent training must use the existing
model/LoRA route and record data/configuration, resulting artifacts, held-out evaluation, and
rollback. Test stale approvals, changed candidates/roles, provider failure, non-convergence,
cancellation, and duplicate delivery before claiming R-185 complete.
