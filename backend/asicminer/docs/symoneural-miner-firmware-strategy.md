# SyMoNeuRaL Miner: how to make it ours, and make it work

The ask: build SyMoNeuRaL Miner on Braiins as an SDK/source base so the hashboards actually
hash, and have it be **our custom code**. Those two goals pull in opposite directions in one
specific place, and there is a clean way to get both. Everything below was checked against
live repositories or the files in `references/`.

---

## The licence boundary, because it decides the architecture

Every piece of code that can drive an Antminer hashboard today is **GPLv3**:

- **cgminer** — GPLv3 (its own `COPYING`, read from the reference tree earlier in this work)
- **bmminer** — Bitmain's cgminer fork, therefore GPLv3-derived
- **bosminer** — Braiins' rewrite, GPLv3

So a fork of Braiins source *is a derivative work* and must ship under GPLv3, with source
made available to anyone who receives the binary. "Fork Braiins and keep it proprietary" is
not available, and this matters beyond principle: the SyMoN_ML blueprint's IP-moat strategy
assumes the opposite, and `.claude/HANDOVER.md` records that nothing in this project is GPL.

**But the GPL binds derivative works, not separate programs that talk over an interface.** A
control plane in its own process, communicating with a miner over a network API, is not a
derivative of it. That is the boundary every commercial mining-firmware vendor uses, and it
is the one to build on.

## The finding that makes this easy: BOS+ has a public API

`github.com/braiins/bos-plus-api` — **last pushed 2026-08-13**, actively maintained. It is a
complete gRPC surface, defined in `.proto`:

| Proto | What it gives SyMoNeuRaL Miner |
|---|---|
| `authentication.proto` | login — the "it will ask for login" step |
| `miner.proto` | live telemetry |
| `cooling.proto` | fans and temperatures |
| `performance.proto` | **autotuning, power targets** — the part with real commercial value |
| `pool.proto` | pool configuration |
| `network.proto` | network settings |
| `actions.proto` | reboot, pause, resume |
| `upgrade.proto` | **firmware upgrade** |
| `configuration.proto`, `constraints.proto`, `advanced_settings.proto`, `license.proto`, `units.proto`, `common.proto` | the rest |

This is the whole feature list of the miner settings page, as a documented, supported,
versioned API. No reverse engineering, no forking, no GPL obligation on our side.

It also explains something already in the tree: pyasic ships
`pyasic/web/braiins_os/boser.py` built on `betterproto`, which consumes exactly these
definitions. (And why pyasic 0.78+ breaks at import — it ships without the *generated* proto
stubs. We are pinned to 0.75.0 for that reason.)

## The recommended shape

```
  ON THE RIG                              ON OUR BOX / THE CUSTOMER'S SERVER
  ──────────────────────────              ─────────────────────────────────────
  Braiins OS+          (GPLv3)   <──────  SyMoNeuRaL Miner        (ours, closed)
    bosminer, drivers,            gRPC      discovery + IP scan
    autotune engine               API       fleet management
    upgrade.proto                           telemetry + history
                                            tuning POLICY
                                            firmware pre-flight + rollout
                                            branding, UI, licensing
```

- **The engine is a commodity.** Braiins already solved hashboard control; we would spend
  years reproducing it and end up with something worse that we still had to open-source.
- **The control plane is the product**, and it is where the value and the differentiation
  live: fleet policy, pre-flight validation, telemetry, and the SyMoNeuRaL brand.
- **`backend/apps/asicminer/` is already this.** The architecture is not a rewrite; it is
  what has been built. What it gains from BOS+ is a first-class API instead of the
  lowest-common-denominator one.

If firmware genuinely must carry our name on the rig, the honest version is a **branded BOS+
distribution**: our configuration, our defaults, our provisioning, GPL-compliant, with the
source offer included. That is a packaging and support product, not a code-ownership one, and
it is achievable. What is not achievable is a proprietary fork.

## What the local Braiins reference actually is

`references/braiins-os-feeds-master/` is **packaging recipes, not miner source**. Every
`Makefile` is OpenWrt (`include $(TOPDIR)/rules.mk`, `PKG_NAME`, `PKG_RELEASE`) and the
sources point at Braiins' internal host:

```make
PKG_SOURCE_URL:=git@gitlab.bo:x/bmminer.git      # unreachable
PKG_SOURCE_URL:=git@gitlab.bo:x/cgminer.git      # unreachable
```

There is a supported escape hatch — `CONFIG_EXTERNAL_BMMINER_TREE`,
`CONFIG_EXTERNAL_CGMINER_TREE`, `CONFIG_EXTERNAL_UBOOT_TREE` point a build at a local tree —
but you must supply that tree yourself. The feeds do not contain it.

Also note: **Braiins OS source is not on GitHub.** `braiins/braiins-os`,
`braiins/braiins-os-plus`, `bitmaintech/meta-bitmain` and `bitmaintech/openwrt` all 404. The
`braiins` GitHub org holds old Puppet infrastructure. Only `braiins/bos-plus-api` is live —
which is the API, and which is the point.

---

## MicroBT / Whatsminer

**The same analysis cannot be done, because there is no MicroBT firmware here.** All five
files in `references/Projects_Crypto/Antminer/Whatsminer/` are failed downloads saved with a
`.bin` extension:

| File | Size | What it actually is |
|---|---|---|
| `WhatsMiner-all-2026.bin` | 138 B | an **nginx 404 page** |
| `WhatsMiner-M30-Series-2025.bin` | 0 B | empty |
| `WhatsMiner-M50-Series-2025.bin` | 0 B | empty |
| `WhatsMiner-M30-Series-Stable.bin` | 4,983 B | an HTML page |
| `WhatsMiner-all-20260104.bin` | 77 KB | an HTML document |

Real Whatsminer firmware is tens of megabytes. Nothing here can be extracted, verified or
flashed. Re-download from MicroBT's own portal before any MicroBT firmware work.

### Update: real firmware obtained, and it is encrypted

`Whatsminer-all-20260416.14` (41 MB, M3x/M5x/M6x) is now in `references/Projects_Crypto/`.
Opening it settles the emulator question for MicroBT, and the answer is no.

The container header is readable: magic `0xae640a3f`, a declared payload size, a header
length of 6,812 bytes, and the **control board type as ASCII** — `h616`. Everything after
the header measures **7.999 bits/byte of entropy** across the whole 41 MB, which is
indistinguishable from random. Scanning for gzip, squashfs, UBI, JFFS2, ext, xz and cramfs
magic finds only coincidental byte pairs with no valid structure behind them — precisely what
random data produces.

**So the payload is encrypted, and that is a category difference from Bitmain.** An Antminer
package is a plain signed tarball: `tar` opens it, and its `runme.sh`, version gate and NAND
offsets can all be read before flashing. A Whatsminer image cannot be opened at all without
MicroBT's key. There is therefore no `runme.sh` pre-flight to reproduce, **and no emulation
is possible** — you cannot extract a kernel from ciphertext.

Two further nails in the emulator idea, independent of the encryption: the board is `h616`,
an Allwinner SoC, and `qemu-system-arm` has machines only for Allwinner **H3, A10 and R40**.
The one Whatsminer image on a SoC QEMU can model is the H3-based `bt1000` build for the
M1/M2/M3 — hardware from 2016.

`fwcheck.py --microbt` validates what can be validated: the magic, the size consistency and
the declared board. That last one is the mistake worth catching, since MicroBT ships one
`.bin` covering several models but only for the board named in its header. It also cleanly
rejects the five fake `.bin` files described above — the 138-byte one reports magic
`0x6d74683c`, which is ASCII `<htm`.

**The good news is that MicroBT does not need any of it.** Whatsminer exposes the **btminer
API** on TCP 4028 — JSON over a socket, with read-only status unauthenticated and privileged
commands (reboot, power mode, pool change) sent as AES-encrypted tokens. `pyasic` already
speaks it via `pyasic/rpc/btminer.py`, which is installed and verified in
`backend/apps/asicminer/.venv`.

So the MicroBT path is **the control plane only, and it already works** — the same shape
recommended for Antminer above, and reachable today without touching firmware.

---

## Recommended order

1. **Point `fwcheck.py` and the panel at a real BOS+ rig** — nothing else can be validated
   against hardware until one exists.
2. **Generate Python stubs from `bos-plus-api` protos** into `backend/apps/asicminer/`, so
   SyMoNeuRaL Miner drives BOS+ natively rather than through pyasic's
   lowest-common-denominator model. This is the real "Braiins as an SDK" step, and it is an
   API dependency, not a code fork — our side stays ours.
3. **Keep pyasic for breadth** — stock Antminer and Whatsminer, where no BOS+ API exists.
4. **Re-obtain the MicroBT firmware** if firmware work there is actually wanted.
5. **Only then**, if a branded on-rig image is still wanted, scope a GPL-compliant BOS+
   distribution — with the source offer, which is the cost of that route.

## Stale paths, corrected

`references/CGMiner-master/` and `references/Pete/` no longer exist — they were present
earlier in this work and have since been removed. `backend/asicminer/docs/antminer-firmware-upgrade.md` and
`.claude/HANDOVER.md` §5 both cite them. pyasic is unaffected: it was installed from PyPI
into the app's own venv, not from the reference tree.

---

## How Braiins gets paid, and what it costs us

Found in the API rather than inferred: `proto/bos/v1/license.proto` and `units.proto`.

**The dev fee is a licence field, expressed in basis points.**

```proto
message ValidLicense {
  LicenseType type = 1;          // STANDARD | CUSTOM
  string contract_name = 2;
  uint32 time_to_restricted = 3;
  bos.v1.BasesPoints dev_fee = 4;
}

// units.proto
message BasesPoints {
  // A basis point is one hundredth of 1 percentage point.
  // For example: 1bps = 0.01%, 250bps = 2.5%
  uint32 bsp = 1;
}
```

Three things follow, and each matters commercially:

- **The fee is per-contract, not hardcoded.** It arrives inside the licence, which is why
  `LicenseType` distinguishes `STANDARD` from `CUSTOM` — large fleets negotiate a rate. Their
  own worked example in `units.proto` is `250bps = 2.5%`. Do not quote that as *the* rate:
  it is a comment illustrating the unit, not a published price. Read the real number off a
  rig with `GetLicenseState`.
- **Activation is a contract key**, applied over the API:
  `ApplyContractKey(contract_key, keep_existing)`. So licensing is an operator action the
  control plane can perform, not something baked into an image.
- **Enforcement degrades rather than blocks.** Both `NoneLicense` and `ValidLicense` carry
  `time_to_restricted`, and there are distinct `Limited` and `Expired` states. An unlicensed
  or lapsed miner becomes *restricted* after a countdown; it does not simply stop.

### What this means for SyMoNeuRaL Miner

**If customers run BOS+, they pay Braiins a per-rig fee we neither control nor receive.**
That is the true cost of not writing hashboard drivers, and it is almost certainly worth
paying — but it should be a decision made with the number in front of you, not a surprise
discovered after pricing.

It also argues *for* the control-plane strategy rather than against it. Competing with the
engine means reproducing years of driver and autotune work to escape a fee measured in single
-digit percent. Charging for the fleet layer — policy, telemetry, pre-flight, rollout across
hundreds of rigs — is a separate line item on top, and it is the part Braiins does not sell.

**One feature falls straight out of this**, and it fits the site's argument exactly: the
panel can read `GetLicenseState` per rig and **show the operator the dev fee they are
actually paying**, alongside contract name and time-to-restricted. That is a real reading off
real hardware — measured, not quoted — and nobody else puts it on the screen.
