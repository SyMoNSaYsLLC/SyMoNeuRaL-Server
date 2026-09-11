# Which installer is authoritative

Commissioning, 2026-09-09. The commissioning prompt asked for this because the unit files
disagree with each other about who installs them, and **four** installers exist rather than
the three it listed.

## The decision

| script | verdict |
|---|---|
| **`ops/install-runtime.sh`** | **AUTHORITATIVE for the system units** — `symoneural-api`, `symoneural-gateway`, `symoneural-deploy` |
| `scripts/install-gateway.sh` | **KEEP** — gateway-specific, does work nothing else does |
| `ops/install-service.sh` | **KEEP, narrowed** — the only thing that installs the `--user` progress units |
| `scripts/install-service.sh` | **DEPRECATED** — superseded, and now refuses to run |

## Why `ops/install-runtime.sh` wins

It is the only one that behaves like a deployment rather than a sequence of copies. Measured
from the source:

- `--dry-run` prints every action and changes nothing (`:3`).
- It **refuses** rather than installing something wrong: an unsubstituted `@@PLACEHOLDER@@`
  aborts (`:162-163`), and a rendered unit still naming `/yocto` in a directive aborts
  (`:165-166`). Both are failures this repo has actually had.
- It is idempotent — `cmp -s` against the installed copy reports `unchanged` instead of
  rewriting (`:168-169`).
- It backs up every unit it replaces (`:182-183`) and rolls back on failure.
- `--no-restart` installs without touching running services.

The others copy files. That difference is the whole argument.

## Why the other three are not simply deleted

`scripts/install-service.sh` is **superseded in full**: it renders the same
`ops/symoneural-api.service` with the same `sed` substitution (`:23-24`) and installs it to
the same path, but with no dry-run, no backup, no placeholder check and no rollback. It also
writes a logrotate config and kills a `run/api.pid` from the pre-systemd era.

It has **not been deleted**, because deleting tracked content is not commissioning's call.
Instead it now **refuses to run** and names its replacement. The prompt's own standard is
that *"a second installer that still works is worse than one that is gone"* — a refusal
satisfies that without destroying anything. Override with
`--i-know-this-is-deprecated` if there is a reason nobody has thought of yet.

`scripts/install-gateway.sh` **stays as-is.** It is not redundant: it reads
`ops/manifests/gateway-build.json` to learn which binary to install and **refuses if the
gateway has not been built** (`:33`, `:42`), which `install-runtime.sh` does not do. It
installs one unit that nothing else needs to touch, and the gateway is disabled by design on
this box anyway.

`ops/install-service.sh` **stays, narrowed to one job.** It is the *only* installer that
handles the `--user` units — `symoneural-progress.service` and `.timer` go to
`~/.config/systemd/user/`, not `/etc/systemd/system/`, and `install-runtime.sh` has no
`--user` handling at all (measured: zero occurrences). Deprecating it would leave the progress
units with no installer. **For system units, prefer `install-runtime.sh`.**

## Two documentation errors found while deciding this

Both are in the units' own headers, which is exactly what made the question hard:

1. **`ops/symoneural-web.service:1` says `ops/install-runtime.sh` installs it. It does not.**
   `install-runtime.sh`'s `UNITS` array (`:41`) is
   `(symoneural-api symoneural-gateway symoneural-deploy)` — no `symoneural-web`. So the web
   unit currently has **no installer at all**, despite being installed and running.
2. **`ops/symoneural-api.service`, `-deploy` and `-progress` all name `install-service.sh`**,
   which is ambiguous — two files have that basename, in `ops/` and in `scripts/`. That
   ambiguity is the actual defect the prompt was pointing at.

## The warning that matters before anyone runs the authoritative installer

**`ops/install-runtime.sh` installs `symoneural-deploy.service`, which has never been
installed on this box.** Measured: `systemctl list-unit-files 'symoneural-deploy*'` returns
`0 unit files listed`.

So running the authoritative installer **adds a unit that is currently absent**. Whether
`symoneural-deploy` should be live is a disposition commissioning deliberately did not decide
— it is carried in `ops/` and has never run here, and that could be either an oversight or a
deliberate omission. Decide that *before* running `install-runtime.sh`, or pass
`--no-restart` and remove the unit afterwards if it was not wanted.

## What commissioning did not do

It did not run any of these. All four write to `/etc/systemd/system/` and act on units, which
is root work on a box where `systemctl start|stop|restart` is polkit-gated for the service
user. The unit repair they exist to perform is carried in `ops/commission-apply.sh` instead,
as a reviewable dry-run-by-default script.
