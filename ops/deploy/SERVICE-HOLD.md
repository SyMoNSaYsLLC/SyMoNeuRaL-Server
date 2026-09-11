# How to hold the API down, and why `stop` is not it

Commissioning, 2026-09-09. This exists because a hold that everyone believed was in force
was not, and nobody could have told from looking.

## What happened

The API was deliberately stopped, with a standing written instruction not to restart it. On
2026-09-09 the owner rebooted the box to pick up a new kernel and driver — and the API
**started itself**, because the hold was a runtime `systemctl stop` on a unit that is
`enabled`. A commissioning session then found it up and serving.

Nothing was wrong with the instruction and nobody ignored it. **The mechanism simply could
not do what it was being asked to do**, and there was no way to tell:
`systemctl is-active` reported `inactive` and `systemctl is-enabled` reported `enabled`,
which together mean "down right now, and will come back at boot" — but only if you thought
to read the second one.

This is the same class of defect as `StartLimitIntervalSec` sitting in `[Service]`, where
systemd silently ignored it for months: **a control believed to be in force that the system
was never going to honour.**

## The three levels, and when each is right

| you want | command | survives reboot | startable by hand |
|---|---|---|---|
| stop it for a minute | `sudo systemctl stop symoneural-api` | **no** | yes |
| hold it down | `sudo systemctl disable --now symoneural-api` | **yes** | yes |
| hold it down hard | `sudo systemctl mask --now symoneural-api` | **yes** | **no** |

- **`stop`** — for a restart, a quick test, anything measured in minutes while you watch it.
  Never for a hold. `Restart=always` does not bring it back after a *deliberate* stop, but a
  **reboot** does, because `enabled` is what boot reads.
- **`disable --now`** — the correct hold. Stops it and removes the
  `multi-user.target.wants` symlink, so boot has nothing to start. Reversed with
  `sudo systemctl enable --now symoneural-api`.
- **`mask --now`** — links the unit to `/dev/null`. Nothing can start it, including a
  well-meaning operator, a script, or another unit's dependency. Use when the reason for the
  hold is that starting it would cause harm — mid-migration, mid-storage-run, a half-applied
  upgrade. Reversed with `sudo systemctl unmask symoneural-api` **and then** `enable --now`;
  unmask alone leaves it disabled.

## Verify the hold, do not assume it

One command, and read **both** fields:

```bash
systemctl is-active symoneural-api ; systemctl is-enabled symoneural-api
```

| is-active | is-enabled | what you actually have |
|---|---|---|
| `inactive` | `enabled` | **NOT A HOLD.** It comes back at the next boot. This was the 2026-09-09 state. |
| `inactive` | `disabled` | a real hold |
| `inactive` | `masked` | a hard hold |
| `active` | anything | not held at all |

`systemctl is-enabled` alone is the whole test. If it says `enabled`, there is no hold, no
matter what any note or instruction says.

## Write the reason down where the next person will look

A hold is a decision, and the machine records the mechanism but not the motive. Whoever
finds a stopped service at 3am needs to know whether starting it is safe.

```bash
sudo systemctl disable --now symoneural-api
printf 'HELD %s by %s\nreason: %s\nrelease when: %s\n' \
  "$(date -Is)" "$USER" "storage migration in flight" "the storage run reports terminal" \
  | sudo tee /etc/systemd/system/symoneural-api.service.d/00-HELD.conf.README >/dev/null
```

That path is deliberate: it sits beside the unit, so `systemctl cat symoneural-api` and
anyone listing the drop-in directory trips over it. Note the `.README` suffix — it is **not**
a `.conf`, so systemd does not parse it and it cannot change the unit's behaviour.

## This is polkit-gated for the service user

Every command above needs root on this box. Measured 2026-09-09 as the `google` user:
`systemctl stop`, `start` and `restart` all **hang until timeout** (rc 124/143) waiting for
a polkit authentication that cannot arrive non-interactively. So a hold cannot be applied or
lifted by the account the service runs as — which is correct, but it means "hold the API" is
always an owner action, never something a coding session can do or undo.

## What the API itself does about being down

Nothing, and that is right: a stopped service cannot report on itself. What it *can* now do
is refuse to overstate its health while running — `/api/status` reports
`gpu.driver: "mismatch"` with `REBOOT REQUIRED` in `gpu.driver_detail` when the driver and
the kernel module disagree, instead of reporting `chat: ready` off files on disk. See
`backend/apps/test_gpu_driver_health.py`.

The static site is served by `symoneural-web` and is **unaffected** by any hold here, which
is the point of them being separate units.
