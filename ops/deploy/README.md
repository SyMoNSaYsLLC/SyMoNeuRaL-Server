# ops/deploy/ — install, verify, roll back

Bash, run as root, on the box. Nothing here is called by the application.

```bash
sudo ops/deploy/install-runtime.sh     # dependencies and paths
sudo ops/deploy/install-service.sh     # units into /etc/systemd/system
ops/deploy/api-readiness-probe.sh      # does it ANSWER -- not whether systemd says active
ops/deploy/verify-runtime.sh           # the full check
sudo ops/deploy/rollback-runtime.sh    # back to the previous
```

`commission-collect.sh` gathers the evidence; `commission-apply.sh` applies what was decided
from it. Run collect first and read it.

`Containerfile` builds the container image; `build-gateway.sh` and `build-symoneural-web.sh`
build the two Go binaries.

## Two files to read before touching a running box

**`SERVICE-HOLD.md`** — every unit deliberately held down, and why. A stopped unit is usually
stopped on purpose.

**`INSTALLERS.md`** — what each installer writes outside the repository. Everything in this
directory writes to `/etc`, `/var/www` or the unit directory, and that is the record of what
a rollback has to undo.

## The check that matters

`systemctl is-active` reports the process, not the surface. A service can be `active` while
every surface behind it answers 503 — that has happened here, after a config directory was
deleted. `api-readiness-probe.sh` asks the surface.
