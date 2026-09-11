"""Decide whether a settled on-chain licence covers a specific request. Fail closed, always.

This is where `docs/specs/symon-ml-review.md` finding 1 lands in our code. The reviewed PoC
checked the *recipient* and the *confirmed* flag and nothing else, so any confirmed transfer of
any token, of any size, at any time granted a permanent licence — and its chain lookup returned
`True` on failure, so blocking the node with one firewall rule granted it too.

Everything below is a read. This module cannot build, sign or broadcast a transaction; it has
no key material and no way to obtain any. `licenceByNonce` is a `view`, reached through
`gateway.chain.constant_call`, which is unauthenticated.

## The return type is the safety property

`verify_payment` returns `Granted` or `Refused`. `Refused` is falsy and `Granted` is truthy, so
`if verify_payment(...):` is correct by construction. There is deliberately **no** boolean
return and no exception-as-denial: an exception that escapes would have to be caught by a
caller, and a caller that writes `except: pass` around a licence check has just written the
reviewed bug again. Every failure path here — including every unexpected exception — is
converted to a `Refused` carrying the reason.

## No memoisation. Not here, not by a caller.

`verify_payment` holds no state between calls. That is not an oversight to be optimised away
later: the reviewed code's second bug was setting `is_licensed = True` once, never re-checking
and never expiring it, so a revoked or expired licence kept working until the process
restarted. If a cache is ever added it belongs in front of the *chain read*, keyed on the
nonce, with a TTL, and it must cache the reading rather than the decision.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

# Two ways in, because there are two legitimate ways to run this. `api.py` puts `backend/apps`
# on `sys.path` and imports `settlement` as a top-level package, so `gateway` is top-level too;
# `python3 -m apps.gateway.settlement_roundtrip` from `backend/` makes both of them submodules of `apps`, where
# only the relative form resolves. Supporting one and not the other means either the server or
# the round-trip rehearsal is broken, and which one is broken is not obvious from the error.
# Relative first: this module is part of the `apps.gateway` package and that is the one
# route to it. The bare `from gateway import ...` that used to be primary only resolved
# because `api.py` put `backend/apps` on `sys.path`, which made every module under it
# importable by two names and therefore loadable as two objects.
try:
    from . import abi, address, chain
except ImportError:                             # pragma: no cover - exercised by __main__
    from apps.gateway import abi, address, chain   # type: ignore[no-redef]

# `licenceByNonce` on SymoneuralLicence. The tuple order is the contract's, and the tests pin
# it against ops/gateway/artifacts/SymoneuralLicence.json rather than against this comment.
LICENCE_SIG = "licenceByNonce(uint256)"
LICENCE_RETURNS = ["address", "address", "uint256", "bytes32", "uint64", "uint64"]

ZERO = "0x" + "00" * 32

# A settled licence older than this is still valid, but the *reading* of it is not fresh
# evidence that the chain still says so. Used only to describe the reading, never to grant.
DEFAULT_MAX_AGE_S = 3600.0


@dataclass(frozen=True)
class Refused:
    """A denial with a reason. Falsy, so `if result:` denies by default."""
    reason: str
    detail: str = ""

    def __bool__(self) -> bool:
        return False

    def __str__(self) -> str:
        return f"refused: {self.reason}" + (f" ({self.detail})" if self.detail else "")


@dataclass(frozen=True)
class Granted:
    """A licence that covers the request, with the record it was granted from."""
    nonce: int
    payer: str
    token: str
    amount: int
    workspace: str
    at_block: int
    at_time: int
    read_at: float = field(default_factory=time.time)

    def __bool__(self) -> bool:
        return True

    def __str__(self) -> str:
        return (f"granted: nonce {self.nonce} · {self.amount} of {address.short(self.token)} "
                f"from {address.short(self.payer)} at block {self.at_block:,}")


def read_licence(network: str, contract: str, nonce: int, *, fetch=None,
                 timeout: float = chain.TIMEOUT) -> dict | Refused:
    """The raw licence record for one nonce, or a `Refused` saying why it could not be read.

    Split out from `verify_payment` so the "could not read" and "read, but does not match"
    cases cannot be conflated — they are different answers to an operator, and only one of
    them means the buyer did something wrong.
    """
    try:
        raw = chain.constant_call(network, contract, LICENCE_SIG, ["uint256"], [nonce],
                                  fetch=fetch, timeout=timeout)
    except chain.ChainError as e:
        # The reviewed bug, precisely: this is the branch that returned True.
        return Refused("the chain could not be read", str(e))
    except Exception as e:                      # noqa: BLE001 - see the module docstring
        return Refused("the chain read failed unexpectedly", f"{type(e).__name__}: {e}")

    try:
        payer, token, amount, workspace, at_block, at_time = abi.decode_params(
            LICENCE_RETURNS, raw)
    except abi.AbiError as e:
        return Refused("the licence record could not be decoded", str(e))
    except Exception as e:                      # noqa: BLE001
        return Refused("the licence record was unreadable", f"{type(e).__name__}: {e}")

    return {
        "nonce": nonce, "payer": payer, "token": token, "amount": amount,
        "workspace": "0x" + workspace.hex(), "at_block": at_block, "at_time": at_time,
    }


def verify_payment(network: str, contract: str, nonce: int, *,
                   expect_payer: str, expect_token: str, expect_workspace: str,
                   min_amount: int, fetch=None,
                   timeout: float = chain.TIMEOUT) -> Granted | Refused:
    """Does the licence at `nonce` cover this exact request?

    Every `expect_*` argument is required and keyword-only. That is deliberate: the reviewed
    PoC's failure was *not checking enough fields*, and an optional check is a check somebody
    omits at the call site. There is no way to call this function without saying who you
    expect to have paid, in what token, for what workspace, and how much.
    """
    if not isinstance(nonce, int) or nonce < 0:
        return Refused("the nonce is not a non-negative integer", repr(nonce))
    for label, value in (("contract", contract), ("expect_payer", expect_payer),
                         ("expect_token", expect_token)):
        why = address.reason(value)
        if why:
            return Refused(f"{label} is not a valid TRON address", why)
    if not isinstance(min_amount, int) or min_amount <= 0:
        # A zero minimum would grant on an empty record, whose amount is also zero.
        return Refused("min_amount must be a positive integer", repr(min_amount))

    record = read_licence(network, contract, nonce, fetch=fetch, timeout=timeout)
    if isinstance(record, Refused):
        return record

    # An unset nonce decodes to an all-zero record rather than an error, so "no such licence"
    # and "a licence for nobody" arrive in the same shape. Reject it explicitly and first:
    # every check below would otherwise compare against zeros and produce a confusing reason.
    if record["at_time"] == 0 and record["amount"] == 0:
        return Refused("no licence has been issued for this nonce", f"nonce {nonce}")

    # The four fields the reviewed PoC never checked.
    if record["payer"] != expect_payer:
        return Refused("the licence was paid by a different address",
                       f"on-chain {address.short(record['payer'])}, "
                       f"expected {address.short(expect_payer)}")
    if record["token"] != expect_token:
        # Without this, a licence bought with a worthless token the buyer minted themselves
        # is indistinguishable from one bought with USDT.
        return Refused("the licence was paid in a different token",
                       f"on-chain {address.short(record['token'])}, "
                       f"expected {address.short(expect_token)}")
    if record["workspace"].lower() != expect_workspace.lower():
        return Refused("the licence covers a different workspace",
                       f"on-chain {record['workspace'][:14]}…, "
                       f"expected {expect_workspace[:14]}…")
    if record["amount"] < min_amount:
        return Refused("the licence was paid for less than this request requires",
                       f"on-chain {record['amount']}, needs at least {min_amount}")

    return Granted(nonce=record["nonce"], payer=record["payer"], token=record["token"],
                   amount=record["amount"], workspace=record["workspace"],
                   at_block=record["at_block"], at_time=record["at_time"])
