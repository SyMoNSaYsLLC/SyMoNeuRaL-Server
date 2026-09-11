# A-4 Enablement — BLOCKED on Privilege, Artifacts Staged

> **REDACTED COPY.** Paths, credential filenames and infrastructure details are masked as `*****`. **No secret was generated, read, or printed** — none exists yet.

## Continues from

`a4-runtime-prerequisite-plan.md`. You authorized enablement including the three consequences. **I could not complete it: the privileged step is blocked in this session.**

## Verdict

# ENABLEMENT FAILED — FURTHER AUTHORIZATION REQUIRED

Not a technical failure and not a policy objection — a **permission** one. Creating root-owned files under the system configuration tree requires `sudo` beyond `systemctl`, and this session's allow-rule covers `sudo systemctl` only. Two attempts were denied by the harness.

**Nothing was changed.** No partial state exists.

## State — identical to pre-state

| | Before | Now |
|---|---|---|
| `enabled()` | False | **False** |
| Service | active, PID 1506 | **active, PID 1506** |
| Restart count | 0 | **0** |
| Start time | 16:28:06 | **unchanged** |
| Shared DB | absent | **absent** |
| App identity column | absent | **absent** |
| Config directory | 0 entries | **0 entries** |
| Repository | 1 pre-existing mod | **1, untouched** |

**No secret was generated.** The authorization permitted exactly one; none was created, so there is no key material to protect or rotate.

## What I completed

**Inspected the sanctioned mechanism** and captured its exact shapes from the existing tooling: the env-file path, drop-in directory and filename, `EnvironmentFile=-<path>` with the **leading `-`** — which the tooling documents as a deliberate panic button, so deleting the env file turns the surface off without bricking the service — plus drop-in mode 0644 and env file root-owned 0600.

**Staged both artifacts**, syntax-verified, in the session scratchpad (outside the repository):

| File | Purpose |
|---|---|
| `10-surfaces.conf` | The drop-in, byte-for-byte in the sanctioned format |
| `install.sh` | Generates the secret in place, installs both, reloads, restarts |

**The installer is written to be safe rather than convenient:**
- `umask 077` **before** writing, so the file is never briefly world-readable
- **refuses if the env file already exists** — it will not overwrite existing secret material
- the secret is generated and redirected in one step; the value is never echoed, never interpolated into a visible argument, never written to the repo
- reports **shape only** — owner, mode, byte count, flag present, length ≥32 — never the value
- `install -o root -g root -m 0644` for the drop-in

## What you need to run

```
sudo bash /tmp/.../scratchpad/enable-shared-accounts/install.sh
```

It performs exactly the authorized scope: directories, env file with one generated secret, drop-in, `daemon-reload`, restart of the API service only. No reboot, no other service.

Full path is in the scratchpad; the script prints service state on completion.

## What I will verify the moment it lands

The complete mandatory sequence, unchanged:

**Runtime prerequisite** — `enabled()` True · ungated status reports enabled · gated surface no longer 503 · service active · restart count stable after the intentional restart.

**Persistence** — shared DB exists *only if first use created it* · 9 expected tables *if created* · **account rows exactly 0** · **entitlement rows exactly 0** · app identity column present after the startup migration.

**D-3(b) separation** — application login, logout, session store and cookie identity all unchanged · no shared login/session implementation merged in.

**Identity and entitlement isolation** — customer accounts 0 · correspondences 0 · grants 0 · **and the four protected routes still return 403 to an authenticated user with no correspondence**, without provisioning anything to make that check pass.

**Regression** — authorization, application, exporter and control-model suites.

**Export/release** — manifest still 7 entries · stage 2 passes · exporter unchanged · 0 archives · D-11 OPEN · external release not authorized.

## Reporting items 1–15

| # | Item | Status |
|---|---|---|
| 1 | Runtime files created/changed | **NONE** |
| 2 | Secret file ownership/mode | **N/A** — no secret generated |
| 3 | Drop-in installed | **NONE** — staged only |
| 4 | Service state before/after | **unchanged**: active, PID 1506, 0 restarts, start 16:28:06 |
| 5 | App column added | **No** |
| 6 | Shared DB created | **No** |
| 7 | Expected-table verification | **N/A** — no database |
| 8 | Customer/account rows | **N/A** — no store |
| 9 | Identity correspondences | **0** |
| 10 | Entitlements | **0** |
| 11 | Four-route unentitled 403 | **not run** — pending enablement |
| 12 | D-3(b) separation | **unchanged** — nothing touched |
| 13 | Regression | **not run** — no change to regress |
| 14 | Exporter/release | **unchanged** — 7 entries, stage 2 passes, 0 archives |
| 15 | `git status --short` | ` M ops/docs/EXPORTS.md` — pre-existing, untouched |

## Not authorized, not done

No customer account · no identity correspondence · no entitlement · route classifications unchanged · no auth merge · cookies and session semantics unchanged · exporter code and policy unchanged · manifest unchanged · D-11 unmodified · D-12 unimplemented · no signing or custody infrastructure · no archive · **no commit** · **no push**.

Policy document left untouched. **No repository commit is warranted** — nothing in the repository changed.

## To resume

Run the staged installer, paste its output, and I will execute the full verification sequence immediately. If any check fails I will stop and report the evidence before acting, and the only corrective action I will take unprompted is restoring the prior disabled configuration.

**Customer account and entitlement provisioning remain a separate authorization.**
