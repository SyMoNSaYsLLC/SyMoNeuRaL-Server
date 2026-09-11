"""Turn a verified on-chain settlement into a recorded clearance. The only writer there is.

## Why this file has to exist

`unit_state` lights the Gateway's LED when `_cleared` finds a clearance for the configured
network and contract. `verify_payment` can prove a settlement happened. Until this module,
nothing joined the two: a real customer could have paid on a real chain and the rack would
have stayed dark forever, because no code path anywhere wrote a clearance. `DEPLOY.md` claimed
a purchase would turn the surface green "with no further code", and that was simply false.
This is the further code.

## It is deliberately the only writer

`ClearanceStore.append` is reachable from here and from the rehearsal in `__main__.py`, which
writes to a temp file it creates itself. Nothing else in the serving path can append. That
matters because the clearance file *is* the LED: anything that can write it can light the
lamp, and a lamp that can be lit by something other than a settlement is the decorative
indicator `.claude/CLAUDE.md` forbids.

So there is exactly one way to get a line into that file, and it runs a chain read first.
There is no `--force`, no `--assume-paid` and no way to pass in a record; the only inputs are
what to expect, and the answer comes from the node.

## Recording is not deciding

This writes down that a settlement *happened*. It is not an entitlement and it is not a
grant — `entitlement.mint` still needs the authority key, and `verify_payment` is still
re-run per request rather than trusting this file. The clearance is evidence, kept because
re-reading the whole chain on every page view is not sensible, and it carries the block and
the nonce precisely so it can be re-checked against the chain later.

## Idempotent, because operators re-run things

Recording the same nonce twice appends nothing the second time and reports that it was
already there. An append-only log with a duplicate in it is not corrupt, but "how many
licences have settled" would start lying, and the retry after a half-visible error is the
most likely way anyone ever runs this twice.
"""
from __future__ import annotations

import argparse
import os
import sys

from ..lib.store import Clearance, ClearanceStore
from .verify import Granted, Refused, verify_payment

# Relative first -- see the note in verify.py.
try:
    from . import chain, keccak
except ImportError:                             # pragma: no cover - exercised by __main__
    from gateway.lib import chain, keccak      # type: ignore[no-redef]


def workspace_key(workspace: str) -> str:
    """The 32-byte workspace word, from either the human string or the word itself.

    `gateway-cli.py quote` takes `--workspace "debian-13 · cuda-12.8 · sm_120"` and stores
    `keccak256` of it, because the contract's field is a `bytes32`. `verify_payment` compares
    against that word exactly. So an operator who quoted with the readable string and then
    recorded with the same readable string would get "the licence covers a different
    workspace" — a refusal that reads like the customer did something wrong, for two commands
    that were given identical arguments.

    Both commands therefore accept both forms and mean the same thing by them. This is the
    same rule as `gateway-cli.py`, reimplemented rather than imported: nothing under
    `backend/` may import from `ops/`. `keccak` is the backend's own copy.
    """
    if workspace.startswith("0x"):
        return workspace
    return "0x" + keccak.keccak256(workspace.encode()).hex()


class AlreadyRecorded(Refused):
    """Not a denial of the payment — a statement that this nonce is already on file.

    It subclasses `Refused` so it is falsy, which keeps `if record_settlement(...):` meaning
    "a new clearance was written". A caller that wants to treat a repeat as success can test
    for this type explicitly; a caller that does not think about it gets the conservative
    answer rather than a second log line.
    """


def already_recorded(store: ClearanceStore, network: str, contract: str,
                     nonce: int) -> Clearance | None:
    """The existing clearance for this exact nonce on this exact contract, if any.

    Keyed on all three because a nonce is only unique within one deployment: the same nonce
    exists on Nile and on mainnet and they are different licences.
    """
    for c in store.all():
        if c.nonce == nonce and c.network == network and c.contract == contract:
            return c
    return None


def record_settlement(network: str, contract: str, nonce: int, *,
                      expect_payer: str, expect_token: str, expect_workspace: str,
                      min_amount: int, store: ClearanceStore | None = None,
                      fetch=None, timeout: float = chain.TIMEOUT) -> Granted | Refused:
    """Verify a settlement against the chain and, only if it holds, record it.

    Returns exactly what `verify_payment` returned, so every refusal reason survives to the
    caller unchanged. On `Refused` **nothing is written** — that is the property the tests
    exercise one failure mode at a time, because "the chain was unreachable" must not be able
    to leave a clearance behind that outlives the outage.

    The `expect_*` arguments are keyword-only and all required, inherited from
    `verify_payment` for the same reason: an optional check is a check somebody omits.
    """
    store = store if store is not None else ClearanceStore()

    seen = already_recorded(store, network, contract, nonce)
    if seen is not None:
        return AlreadyRecorded("this nonce is already recorded",
                               f"nonce {nonce} on {network} at block {seen.at_block:,}")

    result = verify_payment(network, contract, nonce,
                            expect_payer=expect_payer, expect_token=expect_token,
                            expect_workspace=expect_workspace, min_amount=min_amount,
                            fetch=fetch, timeout=timeout)
    if not result:
        return result                            # Refused: write nothing, say why

    store.append(Clearance(
        nonce=result.nonce, payer=result.payer, token=result.token, amount=result.amount,
        workspace=result.workspace, network=network, contract=contract,
        at_block=result.at_block, at_time=result.at_time,
    ))
    return result


def main(argv: list[str] | None = None) -> int:
    """`python3 -m gateway.record` — the operator's post-purchase step.

    Prints the refusal reason and exits non-zero on anything but a fresh recording, so it can
    be run from a shell script without the caller having to parse the output.
    """
    p = argparse.ArgumentParser(
        prog="python3 -m gateway.record",
        description="Verify one settled licence against the chain and record it.")
    # The operator vocabulary, not `chain.NODES`' keys -- one set of names for a human to
    # type, resolved to the canonical key before anything reaches a chain.
    p.add_argument("--network", required=True, choices=sorted(chain.OPERATOR_NETWORKS))
    p.add_argument("--contract", required=True, help="the deployed SymoneuralLicence address")
    p.add_argument("--nonce", required=True, type=int)
    p.add_argument("--payer", required=True, help="the address that was quoted")
    p.add_argument("--token", required=True, help="the token the fee was denominated in")
    p.add_argument("--workspace", required=True,
                   help="the workspace as quoted: either the readable string or its 0x… word")
    p.add_argument("--min-amount", required=True, type=int)
    a = p.parse_args(argv)

    # Resolve once, here, at the edge. Everything downstream -- `chain`, `verify`, the
    # clearance store -- is keyed by the canonical name, and passing the operator name
    # through reached `chain.call` as an unknown network: a refusal that read like the node
    # was unreachable when the argument was simply in the other vocabulary.
    net = chain.OPERATOR_NETWORKS[a.network]

    result = record_settlement(net, a.contract, a.nonce,
                               expect_payer=a.payer, expect_token=a.token,
                               expect_workspace=workspace_key(a.workspace),
                               min_amount=a.min_amount)
    print(result)
    if isinstance(result, AlreadyRecorded):
        return 0                                 # re-running is not an error
    if not result:
        return 1

    # Only claim the lamp will change if this settlement is against the pair the web process
    # is actually configured for. Recording a Nile licence while the service points at
    # mainnet is a perfectly reasonable thing to do and changes nothing on the rack, and
    # telling the operator otherwise sends them restarting a service that was never wrong.
    # Both sides resolved to the canonical key before comparing. They happen to be in the
    # same vocabulary today -- `a.network` and the env var are both operator names -- and a
    # comparison that is only correct because of that would break silently the first time one
    # side moved. An env value outside the map resolves to "" and takes the mismatch branch,
    # which is the honest answer: a surface configured with a name it refuses is not lit.
    raw_env = (os.environ.get("SYMONEURAL_GATEWAY_NETWORK") or "").strip().lower()
    net_env = chain.OPERATOR_NETWORKS.get(raw_env, "")
    addr_env = (os.environ.get("SYMONEURAL_GATEWAY_CONTRACT") or "").strip()
    if not raw_env or not addr_env:
        print("recorded. This shell has no SYMONEURAL_GATEWAY_NETWORK/CONTRACT set, so whether the "
              "rack turns green depends on what the API service is configured for.")
    elif (net_env, addr_env) == (net, a.contract):
        print("recorded — the Gateway unit will read `ready` on the next status poll")
    else:
        print(f"recorded, but the configured surface is {raw_env} · {addr_env}, so this "
              "settlement does not light it. That is correct, not a bug.")
    return 0


if __name__ == "__main__":                       # pragma: no cover
    sys.exit(main())
