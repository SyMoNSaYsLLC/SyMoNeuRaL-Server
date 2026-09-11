# SyMoNeuRaL Miner GPU (KawPow / Ravencoin) — operator notes

The GPU miner surface: an external KawPow binary on the RTX 5070 Ti, arbitrated by the GPU
governor. `backend/apps/asicminer/` is a **different surface** — Antminer and Whatsminer rigs
on your network. They share no code, no route prefix, no rack unit and no token. Do not
conflate them; `.claude/HANDOVER.md` §5 item 8 says so and it has already caused one round of
confusion.

This module does **not** implement KawPow. It runs a binary you supply. The value here is the
orchestration — governor integration, honest telemetry, and a rack unit that tells the truth.

`selftest()` cites this file by name, so it exists. (`asicminer.probe()` cited a README for
weeks before there was one to read; that is the mistake this file is not repeating.)

## Turning it on

Mining is **off by default and there is no default that turns it on.** With no configuration
the surface reports `offline`, `start()` refuses, and nothing is spawned.

```bash
cp backend/apps/cryptominer/miner.env.example backend/apps/cryptominer/miner.env
$EDITOR backend/apps/cryptominer/miner.env
cd backend/apps && python3 -m cryptominer selftest    # checks it WITHOUT mining
```

| Variable | Form | Required |
|---|---|---|
| `SYMONEURAL_MINING_ENABLED` | exactly `1`. The check is `== "1"` — `true`, `yes` and `on` all leave the surface **off**, silently | yes |
| `SYMONEURAL_MINER_CMD` | the full command, e.g. `/path/to/kawpowminer -U -P stratum+tcp://WALLET.rig@pool:4444` | yes |
| `SYMONEURAL_MINER_GPU` | device index, defaults to `0` | no |

Generate the token rather than choosing one:

```bash
python3 -c 'import secrets; print(secrets.token_urlsafe(32))'
```

Do not reuse `SYMONEURAL_ASIC_TOKEN` for it. This token gates a process that **takes the card from
every other surface**; the two blast radii should not fall together.

### Where the variables go — this surface differs from `asicminer`

`miner.env` is read by this module itself, on every status poll. So unlike the ASIC surface,
you do **not** need `Environment=` lines in `ops/symoneural-api.service`: edit the file and
watch the rack unit move `offline → ready` without restarting the API.

An **exported variable always wins.** `miner.env` never overwrites a variable already in the
environment, so a systemd unit or a one-off `SYMONEURAL_MINING_ENABLED=1 …` overrides the file rather
than fighting it. Only the four keys above are honoured — a stray `LD_PRELOAD=` in that file
is a code-execution path dressed as configuration, and is dropped and reported in
`ignored_keys`.

The file holds a shared secret and is gitignored by `backend/apps/cryptominer/.gitignore`.

## Benchmark or pool: the distinction that has to stay visible

**A miner with nowhere to submit a share earns nothing, whatever its hashrate says.**

The discriminator this code uses is the **absence of a pool URL**, not the presence of `-M`.
That is kawpowminer's own rule, from `kawpowminer -H test`:

> When playing with benchmark or simulation no connection specification is needed ie. you can
> omit any -P argument.

So `pool()` reads the configured command for `-P` / `--pool` / `--pool=…`, or a bare
positional `stratum*://…`, and `benchmarking()` is true when it finds none. Both are reported
by
`GET /api/gpuminer/status` and by `selftest`, and the rack unit's detail line says it in
words:

```
ready   configured as a benchmark, no pool — starting it measures the card and earns nothing
busy    benchmarking · 53.01 MH/s, no pool — earns nothing
busy    holding the card · 53.01 MH/s reported by the miner        # a real pool run
```

This exists because it went wrong. `SYMONEURAL_MINER_CMD` on this box was `-U -M 500000` —
kawpowminer's `--benchmark` — and the rack read `holding the card · 53.01 MH/s reported by
the miner`. Every digit of that was real and measured on this card. A reader would still have
concluded the machine was mining Ravencoin, which it was not. The caveat had been written into
`miner.env`, which is gitignored and never leaves the box, while the number went to the one
place everybody sees. **"Measured" and "earning" are different claims** and the surface now
makes both.

The bare form is restricted to `stratum*` on purpose. kawpowminer also accepts an `http`
getWork pool, but `--api-bind http://127.0.0.1:3333` is an http URL too, and reading that as a
pool would switch the benchmark caveat **off** while the rack showed a real hashrate. So an
http pool has to be written the documented way, with `-P`. The cost is the opposite error — a
"earns nothing" caveat on a configuration that might earn — and that is the direction to err
in.

`pool()` returns the pool **without userinfo**. For Ravencoin the `user` field is the
operator's wallet address and the command may carry a pool password; `status()` is serialised
wholesale over `/api/gpuminer/status`, and while that route is token-gated, echoing a wallet
and a password out of a public-facing web process is not something to do by accident.

## What has actually been measured on this box

Both figures below are **measured**, on this machine, and both are benchmark runs against no
pool. Neither is a vendor number and neither is a projection.

| | |
|---|---|
| Card | NVIDIA GeForce RTX 5070 Ti, 16303 MiB, 300 W limit, driver 610.57.04 |
| Binary | `kawpowminer 1.2.4+commit.8bd0d598.dirty`, built by `contrib/build-kawpowminer.sh` |
| Command | `kawpowminer -U -M 500000` — CUDA only, `--benchmark` on block 500000, **no pool** |
| Date | 2026-08-17 |
| **Steady state** | **52.3 – 53.2 MH/s** across four runs (below) |
| First sample | `0.0` — the miner has not reported at t+7s; that is spin-up, not a stall |

| Run | Length | Reading |
|---|---|---|
| 1 | ~96 s | 52.90 – 53.01 MH/s |
| 2 | ~42 s | 52.75 – 52.81 MH/s |
| 3 | ~70 s | 52.63 → 53.21 MH/s climbing; the binary's own summary line reads `Simulation results : Max 53.209880 Mh Mean 53.026032 Mh` |
| 4 | ~26 s | 52.32 – 52.46 MH/s |

Runs 3 and 4 were added 2026-08-17 and are the first two driven **through the HTTP surface
rather than the CLI** — `POST /api/gpuminer/control {"action":"start"}` and the matching
`stop`, which is the path the button on `/miner.html` uses. Both returned 200 with a real pid,
and after `stop` the card measurably came back: no `kawpowminer` process, 876 MiB / 19.4 W on
`nvidia-smi`, and the `image` tenant that had been queued behind the miner took the lock.

The run-to-run spread is now about 0.9 MH/s, or under two percent, and **no cause has been
established** for it — clocks, temperature and the benchmark's own variance are all candidates
and none has been isolated. The range is quoted rather than the best run, and the spread is
stated rather than smoothed away. Anyone quoting a single number from this table should quote
the low end.

Run 4 is the shortest and reads lowest, which is the same effect the 48.36 mean below is an
instance of: a short capture's average carries proportionally more spin-up. It is **not**
evidence of a slower card, and a run should not be cut short and then quoted.

One line in run 3's log is easy to misread and is not what it looks like:
`**Accepted 5 ms. localhost:0` — that is kawpowminer's *simulated* pool in benchmark mode
accepting its own solution. **No share was submitted to anybody and nothing was earned.**
Nothing on the site quotes it, and nothing should.

The committed fixture `testdata/kawpowminer-1.2.4-sm120-bench.log` is a separate, shorter
capture (`timeout -s INT 150`), and kawpowminer's own summary line for it reads:

```
i 10:05:54 main      Simulation results : Max 52.631720 Mh Mean 48.357568 Mh
```

**The 48.36 mean is not a second, lower steady rate.** It is the mean over the whole run
including spin-up — the per-tick figures in that same log climb 50.74 → 52.02 → 52.44 →
52.55 → 52.57 → 52.59 → 52.63. The `Max 52.63` is the steady figure and it agrees with the
52.9–53.0 measured above. Both captures are recorded here rather than quoting the flattering
one.

Nothing here is a Ravencoin earnings figure, and this file will not offer one: earnings depend
on network difficulty, pool fees and the RVN price, none of which this box measures. For
pricing questions, symonsayadmin@symoneural.com.

## The GPU lock, and the one exception this surface takes

One card, one tenant, arbitrated by `run/gpu.lock.d`. Everything goes through
`scripts/gpu-governor.sh with miner -- <cmd>`, which releases even on a crash.

The miner holds the lock **for its process lifetime**, which is a deliberate exception to the
project rule "hold the lock for a job, never for a process lifetime" — and it is exactly why
this surface never auto-starts.

Read this part carefully, because the obvious reading of "the miner yields to everything" is
wrong:

- `gpu-governor.sh` has a `miner)` eviction arm and it works.
- But eviction is reached only **after** `cmd_acquire`'s `mkdir` on the lock directory
  succeeds — and while the miner runs, its `with miner` shell holds that directory.
- So a surface arriving while the miner is **genuinely running** does not evict it. It spins
  in the `until mkdir` loop for up to `ACQUIRE_TIMEOUT_S` (300 s) and gives up. Measured:
  `gpu-governor.sh acquire chat 10` against a live miner logs
  `'chat' TIMED OUT after 10s behind 'miner'`.

The yield protocol that would make it genuinely preemptible is specified in
`docs/specs/miner-preemption.md` and is deliberately **not** implemented: it changes the hot
path of the only arbitrator of the only contended resource in this system.

**So: start it deliberately, stop it deliberately, and do not leave it holding the card on a
box that is also serving chat and image.**

## Driving it

From `backend/apps/`:

```bash
python3 -m cryptominer status      # what the surface is doing right now
python3 -m cryptominer selftest    # dry run: config + `binary --version`, no GPU, no mining
python3 -m cryptominer start       # takes the card
python3 -m cryptominer stop        # signals the process GROUP, gives the card back
```

Over HTTP — both require `X-Symoneural-Token`, and both 503 when the surface is
disabled. `X-Sym-Token`, the name it replaced, is still accepted by `_operator_token`
in `backend/server.py`; new wins when both are sent:

```bash
curl -s localhost:8800/api/gpuminer/status
curl -s -X POST -H 'Content-Type: application/json' \
     -d '{"action":"stop"}' localhost:8800/api/gpuminer/control
```

`stop` signals the process **group**, not the pid. The miner runs under the governor's `with`
shell, so SIGTERM to the pid alone would leave the child hashing and the lock held.

## Honest states

`unit_state()` returns one of `api.py`'s four `Unit.state` literals. Two of them are easy to
get wrong and are tested:

- A miner that is alive but **has not won the lock yet** is `queued`, not `busy`. Reporting
  `busy` would claim a card it does not have.
- A hashrate is **never** shown without the binary having reported it. `hashrate_source` is
  `null` when there is no number, because "reported by the miner binary" printed beside a
  `null` reads as though the miner reported nothing when in fact it has not reported yet.
- After 120 s with no new output the detail line appends `· no output for Ns` rather than
  continuing to show a stale figure as current.

## Tests

```bash
python3 backend/apps/cryptominer/test_miner.py     # 70 tests, no GPU, nothing is started
```

The hashrate parser is tested hardest, and against **captured bytes, not invented ones**. A
shipped bug is why: the old regex required a literal `/s`, kawpowminer prints `48.51 Mh`
without one, and a perfectly healthy miner reported "no hashrate reported yet" for its entire
run. Nothing caught it because the only test data anyone had was hand-written, and a human
writing a hashrate always writes the `/s`. Hence
`testdata/kawpowminer-1.2.4-sm120-bench.log` — byte-for-byte real stdout, ANSI colour and
interleaved governor lines included.

That fixture is committed on purpose, and `.gitignore` in this directory carries
`!testdata/*.log` to force it past the repo-root `*.log` rule. Without that negation the
fixture is never committed, and the suite fails on a fresh checkout while passing on the
machine that wrote it — the worst way for a test to be broken.
