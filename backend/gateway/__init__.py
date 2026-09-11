"""SyMoNeuRaL Gateway -- stablecoin licensing and validation, on TRON.

From the proof of concept at `external/Projects_Crypto/TRX_POC (1).pdf`: SyMoN SaYs LLC,
a Global Stablecoin Licensing & Validation Gateway. A visitor pays a micro-licensing fee in
USDT (TRC-20) for a custom Debian/Ubuntu workspace compilation; a local TronWeb daemon
validates the environment configuration and, once the payment confirms, unlocks the compiled
workspace.

## Status: the read side is built and measured. The surface is still `offline`, and that is
## the truth, not a defect.

This package can now read the chain: it resolves and checksums a TRON address, reaches a
public node with no key material of any kind, and reports whether a contract is actually
deployed at the configured address and at which block it looked. That is a real measurement
and it is the first this surface has ever produced.

It is still `offline`, on **every** path, because `offline` here means what it means for
every other unit on the rack: *this surface will not do its job if you click it.* A visitor
cannot obtain a licence. There is no deployed contract, no off-chain daemon, and no payment
has ever cleared. A contract existing at an address is not a working licensing service, and
lighting the rack on the strength of one would be exactly the decorative indicator
`.claude/CLAUDE.md` forbids. What the reading buys is a **better** offline: a detail line
that says precisely what is missing and how to supply it.

## Do not invent a fifth state string

`api.py`'s `Unit.state` is `Literal["ready","busy","queued","offline"]`, so `configured` or
`provisioned` is a pydantic `ValidationError` -- a 500 on `/api/status`, which is polled and
drives the websocket, so it would take the whole rack down for every visitor. And even if the
model allowed it, `site/console.js:47` is `u.state === 'offline' ? 'led' : 'led on'`: any
other string lights the green power LED. The truth goes in the detail line, which is
free-text and reaches the page verbatim (`site/gateway.html` sets `d.textContent = u.detail`).

## Every figure the PoC quotes belongs to someone else

`.claude/CLAUDE.md` requires each figure be labelled **measured** on this machine, **vendor**
specification, or **projected** arithmetic:

- **~3 second block confirmation** -- VENDOR. TRON's DPoS block time as published by the
  network, not a timing taken here. The PoC says "exactly three seconds"; block times are a
  target, not a guarantee, and this module does not repeat the word "exactly".
- **27 Super Representatives** -- VENDOR. A parameter of the TRON network.
- **"transaction fee is effectively zero"** -- PROJECTED, and the wording matters. Energy
  rental does not make execution free; it moves the cost from the end user to whoever rents
  the Energy. Presenting that as "zero fees" would describe an accounting choice as a
  physical property.
- **Head block number, contract presence, node latency** -- MEASURED, by `chain.probe`, and
  the detail line says how old the reading is. Nothing else here is measured, because
  nothing else has run.

## Pricing

There is none here, deliberately. The site's standing rule is that prices are quoted, not
published, and inventing one on a licensing surface would be the most damaging possible place
to break it. Fee questions go to symonsayadmin@symoneural.com.

## Switches, off by default -- and there are exactly three

    SYMONEURAL_GATEWAY_ENABLED=1        # the surface exists at all
    SYMONEURAL_GATEWAY_NETWORK=symoneural-test      # or symoneural-live (REAL money),
                                             # or symoneural-test-old
    SYMONEURAL_GATEWAY_CONTRACT=T...    # deployed licensing contract address, base58check

Mainnet moves real money, so it is never the default and the state line always names the
network it is pointed at. A gateway that does not say which chain it is on is one
misconfiguration away from taking real USDT while everyone believes it is a test.

**There is no wallet variable and there must not be one.** Reading the chain -- which is all
this package does -- is unauthenticated: no address, no key, no signature. A wallet is needed
to *receive* a payment and a private key to *sign* one, and neither belongs in the
environment of a public-facing web process. Signing belongs in the off-chain daemon on the
operator's own machine, which is exactly where the PoC puts it. There is also deliberately no
`SYMONEURAL_GATEWAY_NODE_URL`: endpoints come from `chain.NODES`, keyed by the validated network
name, so this process can never be pointed at an arbitrary host.

## Switching it on -- the whole operator procedure

The three values above go in a systemd drop-in rather than in `ops/units/symoneural-api.service`,
because a drop-in is one command, is reversible by deleting one file, and does not modify a
tracked template for what is still a testnet experiment. When a real mainnet contract exists,
move them into the `@@ROOT@@` template so a reinstall carries them.

    sudo install -d /etc/systemd/system/symoneural-api.service.d
    sudo tee /etc/systemd/system/symoneural-api.service.d/gateway.conf >/dev/null <<'EOF'
    [Service]
    Environment=SYMONEURAL_GATEWAY_ENABLED=1
    Environment=SYMONEURAL_GATEWAY_NETWORK=symoneural-test
    Environment=SYMONEURAL_GATEWAY_CONTRACT=T...
    EOF
    sudo systemctl daemon-reload && sudo systemctl restart symoneural-api
    curl -s localhost:8800/api/gateway/state | python3 -m json.tool

To undo it: `sudo rm /etc/systemd/system/symoneural-api.service.d/gateway.conf` and repeat
the reload and restart. **No private key belongs in that file, or in any file systemd reads.**

## Layout

    address.py   base58check decode/encode/validate -- catches a transposed character
    keccak.py    Keccak-256 (NOT hashlib.sha3_256 -- different padding, different digest)
    abi.py       encode/decode for address, uint256, bool, string
    chain.py     the read-only node client, and the fail-closed rule in full
    routes.py    the APIRouter; serves the cache, never triggers a fetch
    __main__.py  `python3 -m apps.gateway` -- reads three REAL networks. See below.

## The suite is offline. The transport is not, and that gap is covered separately

`test_gateway.py` is 57 tests and every one injects `fetch=`, deliberately: a suite that needs
egress to pass is the next entry in `.claude/HANDOVER.md` §3.0d's list of verification steps
that failed on healthy input. But stubbing the transport means `chain.http_post` -- the only
code here that touches the network -- is never exercised by it.

`python3 -m apps.gateway` closes that gap by hand, against real nodes, both directions
(a present contract and an absent one) plus four negative controls. Run it after any change to
`chain.py`. Measured 2026-08-17: mainnet head block 85,439,122 in 430 ms; USDT reads back as
`TetherToken` with 33 ABI functions; the same address on Nile and Shasta reads absent.

## The operator half lives in `ops/gateway/` and the dependency runs one way

Contracts, the compiler toolchain, deployment and quote signing are all over there, in their
own venv, because they hold a private key and this package must never be able to. That tool
imports `address.py`, `keccak.py` and `chain.NODES` from here so there is one implementation
of base58check and one endpoint map. **Nothing here may import from `ops/`.** See
`ops/gateway/DEPLOY.md` for the procedure that turns the switches above on.

# --------------------------------------------------------------------------------------
## The settlement half, merged in

`apps/gateway/` and `apps/gateway/` are one package as of the app restructure: the chain
reading and the thing that decides whether a payment covers a request were always two halves
of one surface, and they shared no other consumer. They are still two halves -- the modules
below the fold are settlement's and say so -- but there is one rack row, one router and one
import path.

**How the merge went wrong once, so nobody repeats it.** The folders were moved by hand and
`settlement/__init__.py` and `settlement/__main__.py` *overwrote* the gateway files of the same
name. Nothing in `git status` distinguished that from a rename, and the symptom was
`module 'gateway' has no attribute 'router'` at import time -- three directories away from the
cause. Both files were recovered from history and merged deliberately. `python3 -m apps.gateway`
is the chain probe, which is what it has always been; settlement's round trip kept its content
and took a name of its own, `settlement_roundtrip.py`, rather than fighting for `__main__`.

## This is NOT `backend/licensing/`, and the difference matters

Two things in this repo are called licensing and they are unrelated:

| | `apps/licensing/` | `apps/gateway/` settlement half |
|---|---|---|
| What | a **dev fee** on mining firmware | a **workspace licence** bought with USDT |
| Artefact | `SYMN1.<payload>.<sig>` contract key | on-chain payment + a short-lived entitlement |
| Question | "what rate is this rig running, and is it disclosed?" | "did this buyer pay for this build?" |
| Consumer | the miner surface | the Gateway surface |

They both use Ed25519 and both talk about "licences", which is exactly why this note is at the
top: an earlier revision of this work was written *into* `apps/licensing/` and overwrote it.
If the two are ever unified that should be a deliberate commit that reconciles the token
formats, not a name collision. Note that `apps/licensing` verifies via `openssl` by exec on
the grounds that the serving interpreter has no asymmetric crypto; that is worth revisiting,
because `cryptography` 43.0.0 is in fact an OS package here and is what this module uses.

The chain-reading half above reads the chain and reports what it sees. This half is the other one — it decides whether a settlement covers a request. `docs/specs/gateway-completion.md`
§7 phase 3 calls these items 10–13 and blocks them on `docs/specs/symon-ml-review.md`
findings 1 and 2 having written-down answers. Both answers are written down here, because a
design decision that lives only in a review is not a decision.

## Finding 2 — answered: this is a payment rail, not DRM. Say so.

The review asked how a decryption key reaches a buyer such that only a payer can use it, and
noted it may not be resolvable as posed. It is not. A blockchain is public: a key in the
contract, in calldata, or in an event is a key published to everyone. The only constructions
that work put a server we run in the loop — and at that point *that server* is the licence
authority, and the chain is a payment rail rather than a moat.

So the chain is a payment rail. It is a good one: settlement is final, auditable, and needs no
card processor. What it is not is a technical guarantee that an unlicensed copy cannot run, and
this repo does not get to claim one it cannot back. `.claude/CLAUDE.md`: the site's whole
argument is that its numbers are real, and a DRM claim we cannot back is precisely the thing
that argument exists to oppose.

Concretely: at-rest encryption stays, the payment rail stays, and neither is described as more
than it is. **Nothing in this package may be described on the site as preventing copying.**

## Finding 1 — answered: fail closed, and re-check every time.

The bug in the reviewed PoC was `_check_local_sandbox_state()` returning `True`
unconditionally, so blocking `api.trongrid.io` with one firewall rule *granted* the licence. A
check that fails open is worse than no check, because the product around it claims protection.

Two rules follow, and both are enforced by tests that were verified to go red when the bug is
put back:

1. **Every failure path returns a refusal.** No `except` here may return an entitlement, and
   none may return "allowed". Unreachable node, malformed answer, timeout, unparseable
   record — all of them are `Refused`, and `Refused` is falsy.
2. **A positive result is never cached for the process lifetime.** The reviewed code set
   `is_licensed = True` once and never re-checked or expired it. Entitlements here carry an
   explicit expiry, are re-verified on use, and `verify_payment` keeps no state at all.

## What is checked, and why each one

The review's checklist, which the PoC failed: it verified only *recipient* and *confirmed*, so
any confirmed transfer of any token, of any size, at any time, granted a permanent licence.
`verify_payment` checks the **payer**, the **token contract**, the **amount** and the
**workspace**, and refuses if any disagrees.

## Layout

    verify.py        read a settled licence off-chain and decide if it covers this request
    entitlement.py   Ed25519 entitlement: mint (operator side) and verify (server side)
    store.py         the durable record of cleared settlements — what earns `ready`
    settlement_roundtrip.py   the round trip, printed:
                     python3 -m gateway.settlement_roundtrip
    test_settlement.py

## Where the keys are, and are not

The Ed25519 **signing** key is the authority's and lives on the operator's machine, exactly
like the TRON key in `ops/gateway/`. The serving process gets the **public** key only, and
`entitlement.verify` needs nothing else. That asymmetry is the point: a web process that is
compromised cannot mint a licence, only check one.

**Nothing here may import from `ops/`.** Same one-way rule the chain half states: the
server side must remain runnable without the operator toolchain, which has its own venv and a
signing key the server must never be able to reach.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time

from .lib import abi
from .lib import address
from .lib import chain
from .lib.chain import NODES, OPERATOR_NETWORKS
from .router import router
# The settlement half. `entitlement.verify` is reached through the module rather than
# re-exported bare: `from .verify import ...` below binds the NAME `verify` to the
# submodule as a side effect of importing it, so a bare `verify` here would silently
# become the module and any caller expecting the function would get a TypeError.
from .lib import store as clearance_store
from .apps import verify as settlement_verify
from .lib import entitlement
from .lib.entitlement import Entitlement, EntitlementError, mint
from .lib.store import Clearance, ClearanceStore
from .apps.verify import Granted, Refused, verify_payment

__all__ = ["Clearance", "ClearanceStore", "Entitlement", "EntitlementError",
           "Granted", "Refused", "clearance_store", "entitlement", "mint",
           "settlement_verify", "verify_payment",
           "enabled", "network", "contract", "unit_state", "status", "router",
           "CACHE", "refresher", "address", "chain", "abi", "NODES",
           "OPERATOR_NETWORKS"]

log = logging.getLogger("symoneural.gateway")


def enabled() -> bool:
    return os.environ.get("SYMONEURAL_GATEWAY_ENABLED") == "1"


def network_raw() -> str:
    """Exactly what the operator set, for error messages. Never used to reach a chain."""
    return (os.environ.get("SYMONEURAL_GATEWAY_NETWORK") or "").strip().lower()


def network() -> str:
    """The chain key, resolved from the name the operator sets.

    Returns "" for anything outside `chain.OPERATOR_NETWORKS` -- including TRON\'s own names,
    which are not accepted here; chain.py argues why. Every caller feeds the result to `NODES`,
    so an unresolved name must not pass through as itself: "nile" would be a valid key and
    would quietly configure a chain nobody named. `configured()` reports the raw value.
    """
    return OPERATOR_NETWORKS.get(network_raw(), "")


def contract() -> str:
    return (os.environ.get("SYMONEURAL_GATEWAY_CONTRACT") or "").strip()


def configured() -> tuple[bool, str]:
    """(is the environment complete, what is wrong if not).

    The message is written for the operator reading it off the rack: it names the variable
    and what a valid value looks like, because "offline" on its own does not distinguish a
    broken unit from one awaiting configuration.
    """
    if not enabled():
        return False, ("not configured — set SYMONEURAL_GATEWAY_ENABLED=1, SYMONEURAL_GATEWAY_NETWORK "
                       "(symoneural-live|symoneural-test|symoneural-test-old) and "
                       "SYMONEURAL_GATEWAY_CONTRACT (a T… address) · see /gateway.html")
    net = network()
    if net not in NODES:
        return False, (f"SYMONEURAL_GATEWAY_NETWORK={network_raw() or 'unset'} — expected one of "
                       + ", ".join(OPERATOR_NETWORKS))
    addr = contract()
    if not addr:
        return False, (f"{NODES[net][0]} — SYMONEURAL_GATEWAY_CONTRACT unset; it takes the deployed "
                       "licensing contract address, 34 characters beginning with T")
    why = address.reason(addr)
    if why:
        return False, f"{NODES[net][0]} — SYMONEURAL_GATEWAY_CONTRACT is malformed: {why}"
    return True, ""


# --------------------------------------------------------------------- the reading cache


class ChainCache:
    """Last known chain reading, refreshed off the request path.

    `/api/status` is polled and also drives the websocket, so nothing in it may block --
    `backend/server.py` states that rule at the status handler and `AsicCache` above it is the
    precedent this copies. A node read measured 0.69-2.64 s from this box; inline, that would
    be added to every status poll and every websocket frame for every visitor.

    `None` means "not yet probed", which `unit_state` reports as offline rather than
    inventing an optimistic default. The age is carried with the value so a stale reading is
    labelled rather than presented as current: "real but N seconds old" is a different claim
    from "real right now", and this rack's whole argument is that it does not blur those.
    """

    TTL = 60.0

    def __init__(self) -> None:
        self._value: dict | None = None
        self._at: float = 0.0

    def get(self) -> dict | None:
        if self._value is None:
            return None
        return {**self._value, "age_s": round(time.monotonic() - self._at, 1)}

    def stale(self) -> bool:
        return time.monotonic() - self._at >= self.TTL

    def put(self, value: dict) -> None:
        self._value, self._at = value, time.monotonic()


CACHE = ChainCache()


async def refresh_once() -> dict | None:
    """One probe, off the event loop thread. Returns the reading, or None if not configured.

    `chain.probe` is blocking `urllib`, so it runs in a worker thread. It never raises; the
    `except` here is for a bug in this function, and it stores nothing rather than storing
    something reassuring.
    """
    ok, _ = configured()
    if not ok:
        return None
    try:
        reading = await asyncio.to_thread(chain.probe, network(), contract())
    except Exception as e:                       # never let a bug here look like a success
        reading = {"network": network(), "contract": contract(), "at": time.time(),
                   "error": f"{e.__class__.__name__}: {e}", "block": None,
                   "contract_present": None}
    CACHE.put(reading)
    return reading


async def refresher() -> None:
    """Keep `CACHE` warm while the surface is configured. Started from api.py's lifespan.

    It logs its first pass, once. `asicminer`'s equivalent is announced by `api.py` at start
    (`log.info("asic surface enabled; probing %d configured rig(s)")`); this task cannot be
    announced there because whether it has anything to do depends on all three switches, not
    just the one `api.py` checks. Without the line, an operator who set `SYMONEURAL_GATEWAY_ENABLED`
    and mistyped the network would see a loop that runs forever, does nothing, and says
    nothing in `journalctl -u symoneural-api`.
    """
    announced = False
    while True:
        try:
            reading = await refresh_once()
            if not announced:
                announced = True
                if reading is None:
                    log.info("gateway refresher idle: %s", configured()[1])
                elif reading.get("error"):
                    log.info("gateway refresher running; %s could not be read: %s",
                             network(), reading["error"])
                else:
                    log.info("gateway refresher running; %s head block %s, contract %s",
                             network(), reading.get("block"),
                             "present" if reading.get("contract_present") else "absent")
        except asyncio.CancelledError:
            raise
        except Exception:                        # never let this kill the loop
            log.exception("gateway chain refresh failed")
        await asyncio.sleep(ChainCache.TTL)


# --------------------------------------------------------------------- the rack unit


def _cleared(net: str, addr: str):
    """The newest licence that actually settled against this network and contract, or None.

    Wrapped in a bare `except` on purpose, and returning None on every failure. This function
    is the one thing that can light this surface's LED, so every way it can go wrong has to
    land on "not lit". A missing `settlement` package, an unreadable store, a permissions
    error, a partially-written record — all of them mean the same thing here, and it is not
    "ready". This is the inverse of `docs/specs/symon-ml-review.md` finding 1: that bug turned
    a failed check into a grant, and this turns every failed check into a refusal.

    `settlement`, NOT `licensing`. `backend/licensing/` is the mining dev-fee model and
    has nothing to do with this surface; see `settlement/__init__.py` for the table. Imported
    lazily so that `gateway` keeps working with neither package present, which is what every
    test that predates them relies on.

    Returns `(clearance_or_None, problem_or_None)`. The second half exists because failing
    closed is necessary but not sufficient: `ClearanceStore.all` turns an unreadable file into
    zero clearances, which is the right *state* and the wrong *sentence*. Without this the
    surface said "no licence has ever cleared against this contract" when the truth was that
    nobody could tell — a page confidently reporting a fact it did not have, on a site whose
    argument is that its readings are real. The state is `offline` either way.
    """
    try:
        from .store import ClearanceStore
        s = ClearanceStore()
        found = s.latest(net, addr)
        bad = s.bad_lines
        if bad == -1:
            return None, f"the clearance store at {s.path.name} exists but could not be read"
        if bad > 0:
            return found, (f"{bad} record{'s' if bad != 1 else ''} in the clearance store "
                           "could not be parsed")
        return found, None
    except Exception:                             # noqa: BLE001 - see the docstring
        return None, "the clearance store could not be consulted"


def unit_state(reading: dict | None = None) -> tuple[str, str]:
    """(state, detail) for the rack.

    `reading` is the cached output of `chain.probe`, exactly as `asicminer.unit_state` takes
    `_asic_cache.get()`. It defaults to `None` so an existing zero-argument call keeps
    working; `None` means "not yet probed", never "assume fine".

    ### THE RULE, and it is the whole point of this surface

    **No `except` in this package may return anything but `offline`.** A gateway that cannot
    verify must say so. `docs/specs/symon-ml-review.md` finding 1 is a licence check whose
    TRON lookup fell back to `return True`, so blocking `api.trongrid.io` with one iptables
    rule *granted* the licence -- a check that fails open is worse than no check, because the
    surface around it claims the weights are protected.

    This function is the place that bug would be born, so the rule is phrased about failure
    paths rather than about the whole function.

    ### There is now exactly one `ready` return, and what it costs

    An earlier revision of this docstring said every return here is `offline`, which was true
    when nothing could ever earn otherwise. `backend/licensing/` now exists, so the
    honest statement is narrower: **the only `ready` return requires a licence to have
    actually settled** against the configured network and contract, recorded by the code path
    that verified it -- see `_cleared`. §4 of `docs/specs/gateway-completion.md` lists five
    conditions, and that record is the only one that cannot be faked by configuration.

    The warning that mattered still stands, and is the reason `_cleared` is not a config
    read: *the natural next commit is "the contract is there, so report ready", and that
    commit is wrong.* A deployed contract is not a working licensing service. If you find
    yourself widening this branch -- treating a configured contract, a reachable node, or a
    non-empty settings file as sufficient -- you are writing that commit. Everything except a
    real settlement is a better `offline`.

    Do not add a fifth state string either. `site/console.js:47` lights the green LED for any
    state that is not the literal `offline`, so `configured` or `provisioned` would light it
    while meaning less than `ready` does.
    """
    ok, why = configured()
    if not ok:
        return "offline", why

    net, addr = network(), contract()
    name, short = NODES[net][0], address.short(addr)

    # A reading taken against a different network or contract answers a question nobody
    # asked. Discard it rather than letting it describe the current configuration.
    if not reading or reading.get("network") != net or reading.get("contract") != addr:
        return "offline", (f"{name} · {short} configured — the chain has not been read yet; "
                           "the status refresher supplies that reading")

    age = reading.get("age_s")
    when = f"{age:.0f}s ago" if isinstance(age, (int, float)) else "just now"

    if reading.get("error"):
        return "offline", f"{name} · {short} — cannot verify ({when}): {reading['error']}"

    block = reading.get("block")
    at_block = f"block {block:,}" if isinstance(block, int) else "an unknown block"

    if reading.get("contract_present") is False:
        return "offline", (f"{name} · {short} — measured {when}: the node answered at "
                           f"{at_block} and no contract is deployed at that address")
    if reading.get("contract_present") is True:
        fns = reading.get("abi_functions")
        what = f"a contract with {fns} function{'s' if fns != 1 else ''}" if fns else "a contract"
        cname = reading.get("contract_name")
        deployed = (f"{name} · {short} — measured {when}: {what}"
                    + (f" named {cname}" if cname else "")
                    + f" is deployed, read at {at_block}")

        # The ONLY route to a lit LED on this surface, and it is deliberately narrow.
        #
        # `docs/specs/gateway-completion.md` §4 warns that the natural next commit here is
        # "the contract is there, so report ready", and that that commit is wrong. It still
        # is. What makes `ready` honest is not configuration but *evidence*: a licence that
        # actually settled against this exact network and this exact contract address,
        # recorded by the code path that verified it, and re-checkable against the chain by
        # anyone who doubts it. An operator cannot turn this light green by editing a
        # setting, which is what `.claude/CLAUDE.md`'s ban on decorative indicators requires.
        # Guarded a second time, at the call site. `_cleared` already swallows everything,
        # so this looks redundant -- it is not. `unit_state` is called from api.py's
        # `/api/status` handler, which builds the WHOLE rack; an exception escaping here does
        # not degrade the gateway unit, it takes down every unit's reading at once. The cost
        # of the second guard is three lines and the failure it prevents is site-wide.
        try:
            cleared, problem = _cleared(net, addr)
        except Exception:                         # noqa: BLE001
            cleared, problem = None, "the clearance store could not be consulted"
        if cleared is not None:
            note = f" ({problem})" if problem else ""
            return "ready", (f"{deployed}. Licence #{cleared.nonce} settled at block "
                             f"{cleared.at_block:,} — the payment path has completed "
                             f"end to end{note}")
        if problem:
            # Offline, but NOT because nothing has settled — because we cannot tell. Saying
            # the former here would be the site asserting a fact it does not have.
            return "offline", (f"{deployed}. Offline because {problem}, so no settlement can "
                               "be confirmed either way")
        return "offline", (deployed + ". Offline because no licence has ever cleared against "
                           "this contract — the payment path is built and tested but has "
                           "never carried a real settlement")

    # contract_present is None with no error: the probe returned a shape this function does
    # not understand. Unverified is offline, and says so rather than guessing.
    return "offline", (f"{name} · {short} — the chain reading came back in an unexpected "
                       "shape and was not trusted")


def status(reading: dict | None = None) -> dict:
    """The rack unit as a plain dict, for `Unit(**gateway.status(gateway.CACHE.get()))`.

    Deliberately not built from `api.py`'s `Unit` model -- importing it would put this
    package inside `api.py`'s import graph. The keys match `Unit`'s fields, `bus` included,
    so nothing has to be patched in at the call site. Built on `unit_state` rather than
    beside it, so the two can never drift.
    """
    state, detail = unit_state(reading)
    return {
        "id": "gateway",
        "label": "SyMoNeuRaL Gateway",
        "slot": "1U",
        "state": state,
        "bus": "net",
        "href": "/gateway.html",
        "spec": "TRON TVM · USDT (TRC-20) licensing",
        "detail": detail,
    }
