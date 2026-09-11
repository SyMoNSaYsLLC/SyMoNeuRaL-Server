# run/ — runtime state

**Nothing here is in git.** It is what the running system writes, and it is all
reconstructible: delete the directory and the next start rebuilds what it needs.

```
api.log             the service log
api.pid             the pid, when started by scripts/symoneural.sh
gpu.lock.d/         the GPU LEASE. A mkdir mutex -- see below
gpu.lock.d/holder   "<surface> <pid> <pgid>"
engine              the resident engine: surface, pid, process group
governor.log        every acquire, evict, drain and release, with VRAM readings
progress.html       the generated handover page
config/             api.env and miner.env -- MODE 600, never printed
```

## The lock is a directory, and that is not an accident

`mkdir` is atomic on POSIX; a lockfile plus a check is not. Two surfaces racing for the card
is precisely the case that needs atomicity, because both would otherwise load weights and
~12 GB would hit a 16 GB card.

`holder` records the **process group**, not just the pid, so eviction can signal the whole
tree an engine spawned. `engine` is stamped with the boot id: a stale entry from before a
reboot names a pid that may now belong to something else entirely.

**`ROOT/run`, never `backend/run`.** `gpu-governor.sh` takes its lock here, and two lock
directories means two engines.

## config/

`api.env` and `miner.env` are mode 600 and stay that way. **Never print them, and never
echo a value from them into a log, a test or a report.** A test that checks them asserts on
key names only.

## If it will not start

```bash
cat run/gpu.lock.d/holder                 # who has it
tail -50 run/governor.log                 # what the card was doing
pkill -f 'gpu-governor.sh acquire'        # the restart deadlock -- see scripts/README.md
```
