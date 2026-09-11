# D-11 custody topology — decision-origin reconciliation

> **REDACTED.** Service names, credential filenames, internal ports, hostnames and web-root
> paths are masked or referred to by role. No key or credential material exists.

**Date:** 2026-09-02 · **HEAD:** `98326529` (unchanged) · **Read-only. No commit.**

## Finding, stated first

**The removable-media requirement WAS explicitly owner-authorized, in owner prompt text, twice.**
It did not originate in an assistant handoff and was not promoted from proposal to decision by a
downstream document.

**However, the concern behind the challenge is partly valid**, and one thing does need correcting:
the requirement was recorded as **`D-11 CUSTODY TOPOLOGY`** and treated as a **release-blocking
gate**, which reads as though external drives are part of SyMoNeuRaL server/runtime scope. They
are not, and nothing in the codebase makes them so. **Recommendation at the end.**

## Provenance chain — exact evidence

### Where it entered: the C-1…C-4 options were MINE (proposal)

| Source | Status |
|---|---|
| My D-11 analysis handoff, custody options table | **PROPOSAL — assistant-authored** |

Exact text I authored:

> `| **C-2** | **Host-held for the subkey; primary offline on removable media** | **Recommended.** …`

Also mine: *"May hold private key material: removable/offline media for the primary…"* and
*"Awaiting owner decision on D-11: authority A-4, hierarchy H-2, custody **C-2**…"*

So **the idea originated with me**, presented as one of four options (C-1 host-held, C-2 hybrid,
C-3 fully offline, C-4 hardware token) with an explicit recommendation. That was a proposal
awaiting a ruling — correctly labelled at the time.

### Owner authorization #1 — the D-11 ruling adopted C-2 verbatim

**Source: owner prompt, "Authorize the D-11 owner decision as recommended."** Exact owner text:

> `* Custody: C-2 — primary key offline/removable; signing subkey may be host-held only in an
> operator-owned protected location, never service-readable and never inside the repository.`

**Explicitly owner-authorized: YES.** The owner wrote *"primary key offline/removable"* in their
own instruction, under a heading reading *"Record the following as the controlling D-11
architecture."* That is the first point the requirement entered the D-11 chain **as a decision**
rather than a proposal — and it entered by owner instruction.

Also owner-authored in the same prompt, and relevant to whether media was foreseen:

> `* Revocation: revocation certificate generated during the future key ceremony and held separately.`

### Owner authorization #2 — the three-media topology and LUKS

**Source: owner prompt, "D-11 Offline Custody — Remaining Owner Decisions."** Exact owner text:

> ```
> The owner rules:
>
> MEDIA TOPOLOGY:
> THREE PHYSICALLY INDEPENDENT REMOVABLE MEDIA
> Medium A — primary offline authority + recovery material
> Medium B — independent primary backup + recovery material
> Medium C — revocation-certificate custody
> TWO-MEDIUM FALLBACK:
> NOT ADOPTED
>
> The owner also rules:
>
> ENCRYPTION AT REST:
> E-2 — LUKS-encrypted removable custody media
> ```

**Explicitly owner-authorized: YES**, in the owner's own words, labelled *"The owner rules"*,
including the phrase **THREE PHYSICALLY INDEPENDENT REMOVABLE MEDIA** and **LUKS**.

### Owner authorization #3 — media acceptance as a prerequisite

**Source: owner prompt, "D-11 Custody Media Arrival — Read-Only Acceptance Gate."** Exact owner
text:

> `The owner has now physically supplied the removable media intended for:`
> `Medium A — D11-PRIMARY-A  /  Medium B — D11-PRIMARY-B  /  Medium C — D11-REVOCATION-C`
> `2. Require exactly three acceptable physical devices`
> `If fewer than three suitable physical devices are actually present: STOP`

**Explicitly owner-authorized: YES.** The instruction to *STOP* on fewer than three devices came
from the owner, not from me. A further owner prompt then authorized re-running that gate.

### Per-claim summary

| Claimed decision | Source | Owner-authorized? | Proposal only? | Wrongly promoted? |
|---|---|---|---|---|
| Removable media for the offline primary (C-2) | **owner prompt** (adopting my C-2 recommendation) | **YES** | no | **no** |
| Three physically independent media | **owner prompt** — *"The owner rules: THREE PHYSICALLY INDEPENDENT REMOVABLE MEDIA"* | **YES** | no | **no** |
| Two-medium fallback rejected | **owner prompt** — *"TWO-MEDIUM FALLBACK: NOT ADOPTED"* | **YES** | no | **no** |
| LUKS on those media (E-2) | **owner prompt** — *"ENCRYPTION AT REST: E-2"* | **YES** | no | **no** |
| Media acceptance as a STOP gate | **owner prompt** — *"If fewer than three… STOP"* | **YES** | no | **no** |
| Media *provisioning* performed | — | **never authorized, never done** | n/a | n/a |
| C-1…C-4 option set itself | **my analysis handoff** | proposal | **YES** | resolved by owner ruling |

**Owner prompts mentioning "removable": 9.** No step relied on inferred authorization or on a
handoff being mistaken for a ruling.

## Where the record IS wrong — and this is the valid part of the challenge

**Nothing in SyMoNeuRaL server, application, runtime, or programming scope touches removable
media. Measured:**

```
backend/ ops/ site/  files referencing removable|luks|cryptsetup   0
tools/export_snapshot.sh  references                              0
tools/verify_release_identity.sh  references                      0
```

The exporter, the verifier, every launcher, the API, the entitlement path — **none** has any
dependency on external drives. Media is purely an **operator custody procedure for one offline
key**, outside the application.

Two labelling problems follow, both mine:

1. **`D-11 CUSTODY TOPOLOGY` reads like system architecture.** It is an **offline operator
   custody procedure**, not a component of the server. My section headings and status blocks did
   not preserve that distinction clearly enough.
2. **I let it become the reported blocker for all of D-11.** Media absence blocks only the
   *key ceremony* — creating the offline primary in its ruled custody. It does **not** block P1,
   P2, P3, the exporter, the verifier, or any runtime work, and my "BLOCKED" status lines
   implied a broader halt than the facts support.

## Separate and more urgent: a real P2 defect, found during this task

While verifying scope I re-ran the exporter suite and **one P2 test failed that had passed in
every previous run**:

```
test_p2b_modified_candidate_refused_then_restored_succeeds
  -> restored tree still refused: DRIFT [differs from HEAD] deliverable/app.txt
```

**Root cause, proven in an isolated probe:** `git diff-index` reports a **stat-only** change as
modified. Restoring identical content updates the mtime, so drift is flagged even though the
content blob matches HEAD exactly:

```
blob hash matches HEAD:  YES
diff-index says:         [a.txt]     <-- false positive
after `git update-index --refresh`:  []   <-- resolved
```

This is the caveat I recorded in §22.3/P2 as *"accepted rather than worked around"* — I
underweighted it. It is **timing-dependent**, which is why earlier runs passed.

**Direction of the defect: fail-closed.** It refuses an export of a file that is actually
identical — an **availability** problem, not a security one. The forgery P2-b exists to block is
still blocked, and **the real 7-entry customer manifest still passes** (`stage 3: … 7 candidate(s)
correspond to HEAD`).

**Not fixed here** — this task is read-only and forbids repository modification. The fix is a
`git update-index --refresh` (or `--refresh`-equivalent) before the `diff-index` comparison, plus
a regression test that rewrites identical content. **Needs its own authorization.**

## State until provenance/scope is settled

As instructed, and pending your review:

- **D-11 removable-media topology: treated as UNVERIFIED for scope-placement purposes** — though
  the *decision* provenance above is owner-authorized, so the question is where it belongs in the
  record, not whether it was ruled.
- **Removable-media acceptance: no longer treated as a valid blocker** for anything other than
  the key ceremony itself.
- **No three-drive requirement asserted. No custody-media scanning as a prerequisite.**
- Nothing installed, no LUKS, no provisioning, no credentials, no keys, no repository change, no
  staging, no commit, no service change, no reboot.

## Recommendation

1. **Keep the decisions** — they are yours, recorded verbatim, and the layered custody reasoning
   is sound.
2. **Re-label them out of system architecture.** Move the media topology from `D-11 CUSTODY
   TOPOLOGY` to something like *"optional owner-controlled offline custody procedure — outside
   SyMoNeuRaL server/runtime scope"*, and state plainly that no server, application, runtime, or
   build component depends on removable media.
3. **Narrow the blocker.** Media absence gates **only** the key ceremony, not D-11 as a whole and
   not any runtime work.
4. **If you would rather not use external drives at all**, that is a live option and needs no
   provenance dispute — it means revisiting **C-1 / C-3 / C-4** (or accepting host-held primary
   custody with the service-UID caveat already documented). Say which and I will characterize it.
5. **Authorize the P2 stat-only fix separately** — it is a real latent defect, currently
   fail-closed.

## Return

| Item | Value |
|---|---|
| HEAD | `98326529` — unchanged |
| `git status --short` | ` M docs/ops/EXPORTS.md` (nothing staged) |
| Repository modified | **NO** |
| Packages installed | **NO** |
| Devices written / scanned as prerequisite | **NO / NO** |
| Media requirement asserted | **NO** |
| Provenance verdict | **owner-authorized in owner prompt text, 3 separate authorizations** |
| Scope verdict | **NOT part of server/runtime/programming scope — 0 code references** |
| Correction owed | **labelling and blocker breadth (mine)** |
| New defect found | **P2 stat-only `diff-index` false positive — fail-closed, unfixed, needs authorization** |
| External release | **NOT AUTHORIZED** |

# D-11 REMOVABLE-MEDIA DECISIONS: OWNER-AUTHORIZED — BUT MIS-SCOPED AS SYSTEM ARCHITECTURE
