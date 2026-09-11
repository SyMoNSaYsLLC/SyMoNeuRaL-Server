# SyMoNeuRaL Miner — scope, and what the page is allowed to claim

**Scope captured 2026-08-22 (R-176).** Docs and page copy only. **No miner engine work, no
device is touched, no network is scanned, no firmware is flashed, and `@miner.tar.gz` is not
imported.**

## Classification: AUDIT / overhaul

R-176 calls for a full overhaul across **GPU miner · Antminer · Whatsminer/MicroBT ·
Bitfury/Braiins · emulators.** The verdict lives in `ops/docs/BOX-REALITY-AUDIT.md` §10.6, and
this document is the scope behind it.

**Miner stays AUDIT / overhaul until all six of these are true:**

1. `symoneural-miner` exists
2. the command path is valid
3. the local benchmark is **reproducible from the shipped tree**
4. telemetry reads from a live process
5. tests prove the *offline*, *missing-engine* and *stale-benchmark* states are each represented
   correctly
6. no stale hashrate is ever shown as current telemetry

**Not one of the six is true today.** That is the finding, and the page must not read as though
it were otherwise.

## 1. What SyMoNeuRaL Miner is

> **SyMoNeuRaL Miner is the GPU + ASIC operator surface for mining experiments and hardware
> control.**

An operator surface, and a **miner-family controller area** — not a product that mines for
visitors. `backend/apps/cryptominer/__init__.py:11` already says the equivalent about the ASIC
half: *"It is an operator tool, not a public [one] … there is no honest public version of a live
panel."*

Measured on this box, 2026-08-22: rack row `backend/server.py:2041` is a **6U unit with three
subunits** — `gpuminer`, `asicminer`, `gateway`. So the current rack model *does* fold Gateway
under Miner, and §4 records that as-is rather than proposing a change.

## 2. Why the GPU half cannot run as shipped — the measurement

This is the core correction and every page claim follows from it.

| What | Reading, 2026-08-22 |
|---|---|
| `contrib/` | **does not exist** — already recorded in `BOX-REALITY-AUDIT.md` §8.3 |
| `contrib/kawpowminer/` | therefore absent; the built binary is not in the tree |
| `SYMONEURAL_MINER_CMD` in `miner.env.example:36` | **empty**, and the commented examples at `:25`, `:30`, `:34` all point at `…/contrib/kawpowminer/build/kawpowminer/kawpowminer` — **a dead path** |
| `contrib/build-kawpowminer.sh` | **not tracked.** Three copies exist and every one is outside the repo: `/home/google/.symoneural-full/contrib/` (the IP vault, mode 700) and two under gitignored `references/` |
| `symoneural-miner` | **does not exist** — no such binary, in `bin/` or anywhere |
| the 52–53 MH/s figures | produced by **`kawpowminer 1.2.4+commit.8bd0d598.dirty`**, a third-party binary, on 2026-08-17 |

**So the shipped tree cannot reproduce the benchmark, and the reason is precise: the build
script that produced the binary is not in it.** Not lost — outside it. A clone of this
repository has no path from source to a running miner.

`cryptominer/__init__.py:102` is already honest about its half of this: `KAWPOW_BINARY` is *"a
SIGNPOST, not a"* default, and `:799` phrases the hint conditionally — *"a miner built by
contrib/build-kawpowminer.sh is at …"*. The defect is not in the module. It is in the page.

## 3. The page copy rules

### 3.1 Three claims that must not stand as current production claims

| Do not say | Why |
|---|---|
| *"SyMoNeuRaL Miner **runs** KawPow"* | present-tense capability. §2: the engine path is dead, so nothing runs as shipped. Allowed only with current run proof. |
| *"the only thing here that has ever hashed"* | may stay **only** tied to the historical benchmark evidence, never as a statement about current engine state. |
| *"Every figure below is read from the running miner"* | requires a running miner and current telemetry proof. There is no reachable running miner from the shipped tree. |

### 3.2 The historical benchmark may be preserved — labelled as provenance

**52.3 – 53.2 MH/s is real data and is not deleted.** `cryptominer/README.md:109-117` records
four runs, the spread rather than the best figure, and the binary's own summary line
(`Max 53.209880 Mh Mean 53.026032 Mh`). That is good provenance and it stays.

What changes is its **frame**: historical benchmark, dated, attributed to a third-party binary,
and **accompanied by the statement that the current shipped tree cannot reproduce it.** A
measured figure with a date and no reproducibility note reads as current capability, which is
the whole defect.

The existing honesty around it is kept, not weakened: all four runs were **benchmarks against
no pool**, a miner with nowhere to submit a share earns nothing, and **no income figure is
published** because that depends on difficulty, pool fees and the RVN price — none of which this
box measures.

### 3.3 Required wording

> **SyMoNeuRaL Miner is the GPU + ASIC operator surface for mining experiments and hardware
> control.**

**GPU Miner:**

- the **intended** KawPow / Ravencoin path for the RTX 5070 Ti
- **currently disabled / offline** unless `SYMONEURAL_MINING_ENABLED=1`,
  `SYMONEURAL_MINER_CMD` and `SYMONEURAL_MINER_TOKEN` are configured
- historical benchmark evidence exists around **52–53 MH/s**, and the current audit says the
  shipped tree **cannot reproduce it yet** because the `symoneural-miner` / kawpowminer engine
  work is incomplete
- must report **"offline / engine missing / not reproducible"** — never a stale hashrate — when
  it is not running

**ASIC:** operator panel for Antminer, Whatsminer/MicroBT and Bitfury/Braiins **direction**.
Scanner and emulator concepts remain **AUDIT**.

## 4. The three subunits, and the facts each must keep

### GPU · Ravencoin
Holds the GPU. See §5.

### ASIC · Antminer + MicroBT
- **No rig attached means `offline` is a real reading, not a placeholder.** Already true in the
  copy and it stays.
- **The scanner refuses public IP ranges.** `asicminer/__init__.py:129` — *"Find rigs on a
  private network. Operator-gated, and refuses public ranges."* This is a property of the code
  and must be stated, not implied.
- **The QEMU emulator is for control-board and firmware-path testing only, and must not claim
  hashrate.** `scripts/qemu-antminer.sh:16-17` is unambiguous: QEMU emulates the Zynq-7007's ARM
  cores and *"does NOT emulate the FPGA fabric or the SPI links to the hashboards, and no amount
  of configuration will change that."* Consequently `:27` and `:46` — **bmminer does not run**,
  and nothing answers on port 4028. An emulator quoting a hashrate would be inventing one.

### Gateway · TRON USDT licensing
Folded under Miner in the current rack model (`backend/server.py:2056`), so it is described as a
**Miner-family subunit** — because that is the observable state, not because the code belongs
there.

**The code stays separate.** Gateway is a `bus="net"` surface that never takes the governor
lock. **Do not move gateway code into the miner package.** Folding a rack row is a display
decision; moving a package is a migration, and no migration is authorized.

## 5. GPU governor — Miner is not a normal job

- **Miner holds the GPU for its whole process lifetime**, not for a job.
- **It is not preemptible.** `backend/cryptominer/docs/miner-preemption.md` specifies the yield protocol and is
  *"deliberately not implemented — read its §7 first."*
- While Miner holds the card, **Chat, Image and Remix queue and may time out.**
- Because this is a **shared 16 GB consumer GPU test bench**, Miner **starts and stops
  deliberately** — by hand, both ways.
- **RavenCalc is unaffected**, because RavenCalc is CPU-only by design
  (`BOX-REALITY-AUDIT.md` §10.4).

This is the one place where the existing page copy is already exactly right —
`tools/build/build_pages.py:5900-5904` — and it is not touched.

## 6. Security — two tokens, and they stay two

| Gate | Authorizes |
|---|---|
| `SYMONEURAL_ASIC_ENABLED` | **HTTP API controls only** |
| `SYMONEURAL_MINER_TOKEN` | taking the card — the GPU miner |
| `SYMONEURAL_ASIC_TOKEN` | operator rig / scanner / emulator controls |

**`SYMONEURAL_MINER_TOKEN` and `SYMONEURAL_ASIC_TOKEN` must remain separate.** They authorize
different classes of action against different hardware: one spends this box's GPU, the other
reaches machines on an operator's network. Merging them would make a scanner credential
sufficient to seize the card.

`SYMONEURAL_ASIC_ENABLED` is checked as `== "1"`, not for truthiness —
`asicminer/test_asic.py:68` asserts that `SYMONEURAL_ASIC_ENABLED=true` leaves the surface
**off**. That strictness is deliberate and stays.

**Do not remove token gates for destructive or control paths without explicit authorization.**
`asicminer/__init__.py:29,40` gives the reason: `/api*` is proxied to the public internet, and
rig control is not something to expose by accident.

## 7. Not authorized by this document

No miner engine work · no `symoneural-miner` implementation · no real mining device touched · no
network scanned · no firmware flashed · no `@miner.tar.gz` import (and it is **ambiguous** —
two files match, `symoneural-application-lab.md` §2) · no raw archive committed · no token gate
changed · no gateway code moved · no folder migration · no deploy.

**And no current hashrate claim without current proof.** Which, per §2, does not exist today.

## 8. Where the related work already lives

| Concern | Owner |
|---|---|
| verdict | `ops/docs/BOX-REALITY-AUDIT.md` §10.6, §8.3 |
| the miner page's *layout* | open task **#85** — *"the miner page, embedded the way RavenCalc is"* |
| GPU yield protocol | `backend/cryptominer/docs/miner-preemption.md` — specified, deliberately unimplemented |
| benchmark provenance | `backend/apps/cryptominer/README.md` §on measurement |
| inventory and archive mapping | `backend/studio/docs/symoneural-application-lab.md` §3.9 |

**#85 is layout; this is truth.** They touch the same page and are not the same task: #85 moves
the instrument to the top, this stops the words overstating what the instrument does. Neither
authorizes the other's work.
