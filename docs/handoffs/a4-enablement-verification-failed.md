# A-4 Enablement Verification — FAILED (installer refused; nothing enabled)

> **REDACTED COPY.** Paths, credential filenames and infrastructure details are masked as `*****`. No secret value was read or printed.

## Continues from

`a4-enablement-blocked-on-privilege.md`. You ran the installer under sudo. **It refused, so enablement did not occur** — and the verification below is against a still-disabled subsystem.

## The installer output

```
REFUSING: *****/api.env already exists -- not overwriting existing secret material
```

Exit before any work. **No secret generated, no drop-in installed, no restart, no state created.** The guard did its job.

---

## Mandatory verification — results

| # | Check | Result |
|---|---|---|
| 1 | `enabled()` is True | **❌ FAIL — False** |
| 2 | Status surface reports enabled | **❌ FAIL** — `{"enabled": false, … "note": "This box has not been given a session secret"}` |
| 3 | Gated surface no longer 503 | **❌ FAIL — HTTP 503** |
| 4 | Service active and stable | ✅ active |
| 5 | Post-restart PID / count / start | **no restart occurred** — PID **1506**, restarts **0**, start **16:28:06** (unchanged) |
| 6 | Shared store created by first use | **absent** — consistent with no restart |
| 7 | Expected 9 tables | N/A — no database |
| 8 | Account rows = 0 | N/A — no store |
| 9 | Correspondences = 0 | **0** ✅ (column absent) |
| 10 | Entitlement grants = 0 | N/A — no store |
| 11 | App identity column present | **❌ FAIL — absent.** The authorized migration never ran, because the service never restarted |
| 12 | D-3(b) separation intact | ✅ cookie constant unchanged · own login/logout/session present · **0** shared session/login imports · password seam intact · **0** files modified |
| 13 | Four routes 403, authenticated + no correspondence | ✅ **PASS — all four 403** |
| 14 | Regression | ✅ **159 passed** |
| 15 | Export/release boundary | ✅ manifest **7** entries · stage 2 passes · exporter **0** changes · **0** archives · D-11 **OPEN** |
| 16 | Repository | ✅ only the pre-existing policy-doc modification |

### Verification 13 in detail

Run against a throwaway store, no production state touched:

```
login (customer-tier user)   HTTP 200      ← authenticated
correspondence               None          ← none exists
  GET  /board                HTTP 403
  POST /bookings             HTTP 403
  GET  /bookings/{id}        HTTP 403
  POST /ask                  HTTP 403
```

**No correspondence or entitlement was created to make this pass.** A first attempt returned 401 across all four because I sent no session — 401 is authentication failing, not entitlement. I re-ran it authenticated, which is what the check actually specifies.

---

## Why enablement could not have taken effect

Two independent reasons, both measured:

1. **No drop-in exists** — `0` files in the drop-in directory, and the unit carries no `EnvironmentFile=`. Nothing in the env file reaches the process **regardless of its contents**.
2. **No restart occurred** — PID and start timestamp are unchanged, so even a correct environment would not have been acquired.

So the missing piece is the **drop-in**, and possibly nothing else.

## Correction to my earlier report, restated

I previously recorded the configuration directory as *"0 entries."* It is mode **700 root:root**; my listing ran unprivileged, was denied, and returned nothing — and I read that as *"empty"* rather than *"unreadable."* The file existed throughout.

Same failure mode this session has now recorded three times: **treating an inability to observe as an observation of absence.** The guard I wrote is the only reason that error did not overwrite live secret material.

## What is in that file is still unknown

`sudo grep` on it is blocked for me, and the sanctioned no-secrets reporting mode also requires sudo. **I will not write over pre-existing secret material without knowing what it holds** — it may carry surface tokens from the earlier surface-enabling run in this session, which writes to exactly that path.

## Disposition

# ENABLEMENT FAILED — FURTHER AUTHORIZATION REQUIRED

Verifications **1, 2, 3 and 11 fail**. Nothing was enabled, so nothing needs rolling back — the system is already in the prior disabled configuration. **No corrective action was taken**, because none was needed for service safety: the API is active, healthy, HTTP 200, with 0 restarts.

## To resume — one read, then one small step

**Step 1 — inspect, without exposing values.** Either:
```
sudo bash /home/google/Symoneural/scripts/enable-surfaces.sh --show
```
which the tooling documents as *"what is set, no secrets"* — or just the key names:
```
sudo grep -oE '^[A-Z_]+=' *****/api.env
```

**Step 2 depends on what that shows:**

| If the file already has a ≥32-char session secret | Then |
|---|---|
| **Yes** | Enablement needs **only the drop-in plus the enable flag** — **no secret generation at all.** Strictly less invasive than what you authorized |
| **No** | I restage the installer to **append only the missing keys**, leaving every existing line untouched |

Either way the authorized secret-generation step may prove unnecessary — which is the better outcome.

## Gates preserved

```
customer account        NO      identity correspondence  NO (0)
entitlement granted     NO      route classifications    unchanged
authentication merged   NO      cookies/session          unchanged
exporter code/policy    unchanged   export manifest      unchanged (7)
D-11                    OPEN    D-12                     unimplemented
signing/custody infra   NO      archive produced         NO (0)
secret regenerated      NO      env file overwritten     NO
drop-in altered         NO      persistent state deleted NO
committed               NO      pushed                   NO
policy document         untouched
```

**Customer account, identity correspondence, and entitlement provisioning remain a separate authorization.**
