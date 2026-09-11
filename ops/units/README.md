# ops/units/ — systemd

```
symoneural-api.service          the FastAPI service on :8800
symoneural-gateway.service      symon-gateway on :8000
symoneural-web.service          the Next.js frontend
symoneural-surface@.service     one delegated surface per instance
symoneural-deploy.service       publish the static site
symoneural-progress.{service,timer}   regenerate the progress page
symoneural-watch.{service,timer}      the watchdog
```

## Installing

```bash
sudo scripts/install-service.sh
sudo systemctl daemon-reload
sudo systemctl enable --now symoneural-api.service
```

## The instance template

`symoneural-surface@.service` takes its port from `ops/PORTS.tsv` through a generated
per-instance environment file. **No port is written in a unit**, which is the whole reason
the registry is a TSV.

## Environment, and the trap in it

`/etc/symoneural/api.env` is root-owned, attached through a drop-in that `systemctl cat` does
**not** show, and declared `ignore_errors=yes`. Deleting that directory once disabled every
surface on this box while the service still reported **healthy**.

The process now reads its own configuration from a directory owned by the account that runs
it, so `/etc/symoneural` is optional rather than load-bearing. `EnvironmentFile` still wins
where present, because a name already in `os.environ` is never overridden.

## Before you start something that is stopped

Read `ops/deploy/SERVICE-HOLD.md`. A unit that is down is usually down on purpose, and the
reason is recorded there.

`systemctl is-active` is not evidence a surface answers. Use
`ops/deploy/api-readiness-probe.sh`.
