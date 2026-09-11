# SyMoNeuRaL Miner (ASIC) — operator notes

The ASIC control panel: Antminer (Bitmain) and MicroBT/Whatsminer rigs on **your** network.
`backend/apps/cryptominer/` is a different surface — the GPU KawPow miner on the RTX 5070 Ti.
They share no code, no route prefix, no rack unit and no token. Do not conflate them.

This file exists partly because `probe()` has always returned
`"asicminer venv not installed -- see backend/apps/asicminer/README.md"` and there was no
such file to see.

## Turning it on

Two variables, both required, and **`SYMONEURAL_ASIC_ENABLED` must be the literal string `1`**:

| Variable | Form | Required |
|---|---|---|
| `SYMONEURAL_ASIC_ENABLED` | exactly `1`. The check is `== "1"`, not truthiness — `true`, `yes` and `on` all leave the surface **off**, silently | yes |
| `SYMONEURAL_ASIC_TOKEN` | any non-empty string; presented as the `X-Symoneural-Token` header on every request | yes |
| `SYMONEURAL_ASIC_RIGS` | comma-separated addresses, `10.0.0.11,10.0.0.12`. Whitespace is stripped, empty elements dropped | no — empty is the normal state |

Generate a token rather than choosing one:

```bash
python3 -c 'import secrets; print(secrets.token_urlsafe(32))'
```

It is a shared secret that gates starting a QEMU process and scanning a network. Do not
reuse `SYMONEURAL_MINER_TOKEN` (the GPU miner's) for it: two surfaces with different blast radii
should not fall together.

### What these two variables do NOT do

Asked directly, so it is answered where it is read. **They gate this HTTP API and nothing
else** — `/api/asicminer/scan`, `/firmware`, and the `/emulator` route that starts a QEMU
guest for you. That is why they exist: those are remote-control endpoints on a box that
faces the public internet, and one of them takes a filename.

- **The emulator does not need them.** `scripts/qemu-antminer.sh <firmware.tar.gz> --shell
  --serve` boots Antminer firmware from a terminal with no environment set at all. If you
  are working on the flash path, that is the whole command.
- **Setting them will not make the Miner panel show an emulated rig.** QEMU emulates the
  Zynq-7007 CPU, not the FPGA fabric or the hashboards, so `bmminer` never starts and
  nothing answers pyasic on port 4028. The panel reads `offline`, which is correct rather
  than broken. Telemetry needs a rig; the emulator is for `upgrade.cgi`.
- **`ENABLED` is not a boolean.** It reads like one. `SYMONEURAL_ASIC_ENABLED=true` leaves the
  surface off and says nothing, because the check is `== "1"`.

### Where the variables actually have to go

`scripts/symoneural.sh` starts the API with `setsid python3 backend/server.py` and sources no
env file, and `ops/units/symoneural-api.service` carries only `PYTHONUNBUFFERED` and
`SYMONEURAL_PORT`. So there are exactly two working places to put them:

```bash
# one-off, for a hand-started API — the variables must be in the environment that
# `symoneural.sh on` inherits, not in the shell you type the curl into
SYMONEURAL_ASIC_ENABLED=1 SYMONEURAL_ASIC_TOKEN=… SYMONEURAL_ASIC_RIGS=10.0.0.11 ./scripts/symoneural.sh on
```

```ini
# permanent, under systemd — add to ops/units/symoneural-api.service, then
#   sudo systemctl daemon-reload && sudo systemctl restart symoneural-api
Environment=SYMONEURAL_ASIC_ENABLED=1
Environment=SYMONEURAL_ASIC_TOKEN=…
Environment=SYMONEURAL_ASIC_RIGS=10.0.0.11,10.0.0.12
```

Setting them in your own shell and then querying an API that was started without them is
the failure everybody hits first; it looks exactly like a broken token.

Check it took:

```bash
curl -s localhost:8800/api/status | python3 -c \
  'import json,sys;print([u for u in json.load(sys.stdin)["units"] if u["id"]=="asicminer"])'
# state "offline", detail "disabled — set SYMONEURAL_ASIC_ENABLED=1 and SYMONEURAL_ASIC_TOKEN"
#   -> the API does not have the variables
# state "offline", detail "no rigs configured"  -> it does; SYMONEURAL_ASIC_RIGS is empty
```

### In the browser

`site/miner.html` prompts for the token on the first operator action, keeps it in
`sessionStorage` under `sym.asic.token`, sends it as `X-Symoneural-Token` (and as
`X-Sym-Token`, the name it replaced, until the deployed API is known to read the new
one), and clears it on a 401. The reader is `_operator_token` in `backend/server.py`; it
accepts either name, new first.
It is never written to disk by the page and does not survive closing the tab.

## What the rack unit says, and why

`unit_state()` drives it. Every branch, measured:

| Condition | state | detail |
|---|---|---|
| Not enabled, or `SYMONEURAL_ASIC_ENABLED` is not exactly `1` | `offline` | `disabled — set SYMONEURAL_ASIC_ENABLED=1 and SYMONEURAL_ASIC_TOKEN` |
| `.venv` missing | `offline` | `control venv not installed` |
| Enabled, never probed yet | `offline` | `not yet probed` |
| Probe returned an error | `offline` | the error, first 90 chars |
| Enabled, `SYMONEURAL_ASIC_RIGS` empty | `offline` | `no rigs configured` |
| Rigs configured, none answering | `offline` | `2 configured, none answering` |
| Rigs answering | `ready` | `1 rig answering · 53.2 TH/s measured · AntMiner` |

There is no demo rig and no placeholder hashrate. A number that reaches a page from here was
read off real hardware.

## The QEMU emulator

`scripts/qemu-antminer.sh` boots real Antminer firmware (S17 Pro, S17+, T17) to a busybox
shell under `qemu-system-arm`. `emulator_start(<package id>)` wraps it and records
`run/qemu-antminer.pid`; the console goes to `run/qemu-antminer.log`.

**Started by id, never by path.** `package_by_id` resolves only against the files already
enumerated from the two known firmware directories, so the endpoint cannot be pointed at an
arbitrary file on this box.

**`running` and `booted` are different questions and both are answered.** Measured on this
machine: the pid exists 0.5s after launch; the guest reaches a shell at 6.0s (warm — the
kernel, ramdisk and dtb were already unpacked in `run/qemu-antminer/`; a cold run also
extracts a 17 MB package and a 100 MB rootfs and takes considerably longer). Poll
`emulator_status()` and wait for `booted`, which is read out of the console log, not timed.

**Nothing answers on port 8080.** `--shell` boots `init=/bin/sh`, so lighttpd never starts.
The port accepts a TCP connection because QEMU's SLIRP `hostfwd` is listening on the *host*
side; that proves the forward is configured and nothing about the guest. Same for 4028 —
`qemu-antminer.sh` says so directly. There are no hashboards, so `bmminer` will never run and
**telemetry cannot be tested through the emulator**. It is good for the flash/upgrade path
(`upgrade.cgi`), useless for hashrate.

**Only start it through `emulator_start()`.** Running `scripts/qemu-antminer.sh` by hand
writes no pidfile, so `emulator_status()` reports `running: false` while a qemu is live,
`emulator_start()` will happily launch a second one, and `emulator_stop()` cannot reach the
first. If you have done that, find it with `pgrep -a qemu-system-arm` and kill it yourself.

MicroBT/Whatsminer firmware is encrypted and cannot be emulated at all — `fwcheck.py`
measures the payload at 7.999 bits/byte and says so.

## Tests

```bash
python3 backend/apps/asicminer/test_scan.py     # the CIDR guard
python3 backend/apps/asicminer/test_asic.py     # the gate, unit_state, emulator pidfile
```

Both run on the **system** interpreter and must keep doing so. `.venv` here carries pyasic
and 30 other packages and the serving path must never import from it — that separation is
the whole reason `probe.py` is a subprocess that prints JSON. `test_scan.py` exercises
`allowed_network` without the venv precisely because that guard is the one that matters on a
box with a public IP: a scanner that accepts an arbitrary CIDR is one somebody can aim at the
internet from this address.

`probe.py`'s pyasic type coercion (`_num`, `probe_one`) cannot be tested from the system
interpreter and is not covered.
