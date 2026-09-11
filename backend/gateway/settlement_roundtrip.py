"""The licence round trip, end to end, printed. Run: cd backend && python3 -m gateway.settlement_roundtrip

    settled licence (real EVM output)
      -> node response shape
      -> verify_payment  (the four fields the reviewed PoC never checked)
      -> Clearance recorded
      -> entitlement minted and verified
      -> gateway.unit_state reports `ready`

## What this proves, and what it does not

It proves the **wiring**: that a settlement decoded from bytes a real EVM produced satisfies
the verifier, that the verifier's output records a clearance, that a clearance is what turns
the rack green, and that removing any one of those returns it to `offline`. Every step is the
production code path, not a re-implementation.

It does **not** prove a real payment happened. The licence record is replayed from
`ops/gateway/artifacts/licence-record.json`, which `ops/gateway/test_contracts.mjs` produced by
redeeming in a local EVM; the node is a function that returns that record. No TRON network is
contacted, no money moves, and condition 5 of `docs/specs/gateway-completion.md` §4 — the round
trip completed against a real chain — remains unmet until somebody deploys and buys.

So this is a **rehearsal**, and it writes its clearance to a temporary file rather than to
`backend/state/`. Running it can never light the real rack, which is the point: if it could,
the green light would be a thing an agent can produce on demand, and
`.claude/CLAUDE.md` forbids exactly that.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

_APPS = Path(__file__).resolve().parent.parent
if str(_APPS) not in sys.path:
    sys.path.insert(0, str(_APPS))

import gateway                                                     # noqa: E402
from gateway import address as A                                   # noqa: E402
from gateway import entitlement, store, verify                   # noqa: E402

FIXTURE = _APPS.parent.parent / "ops/gateway/artifacts/licence-record.json"
# NET is the canonical chain key -- what readings, `verify` and the clearance store are all
# keyed by. NET_ENV is the name an operator sets, which is a different vocabulary on purpose
# (gateway/chain.py argues why). The two must agree, so NET_ENV is resolved rather than typed.
NET, CONTRACT = "nile", "TNPeeaaFB7K9cmo4uQpcU32zGK8G1NYqeL"
NET_ENV = next(k for k, v in gateway.chain.OPERATOR_NETWORKS.items() if v == NET)

GREEN, RED, DIM, OFF = "\033[32m", "\033[31m", "\033[2m", "\033[0m"


def step(n: str, ok: bool, note: str = "") -> bool:
    print(f"  {GREEN + 'ok ' if ok else RED + 'NO '}{OFF}{n}" + (f"  {DIM}{note}{OFF}" if note else ""))
    return ok


def main() -> int:
    if not FIXTURE.exists():
        print(f"missing {FIXTURE}\nrun: node ops/gateway/test_contracts.mjs", file=sys.stderr)
        return 2
    f = json.loads(FIXTURE.read_text())
    payer = A.from_hex(f["expect"]["payer_hex"])
    token = A.from_hex(f["expect"]["token_hex"])
    workspace = "0x" + f["expect"]["workspace_hex"]
    amount = int(f["expect"]["amount"])
    nonce = f["nonce"]

    def node(url, body, timeout):
        return 200, json.dumps({"result": {"result": True},
                                "constant_result": [f["raw"]]}).encode()

    def dead(url, body, timeout):
        raise OSError("network is unreachable")

    ok = True
    print("\n1. the settlement, as the chain reports it")
    print(f"   {DIM}replayed from a local-EVM redemption; no network is contacted{OFF}")
    rec = verify.read_licence(NET, CONTRACT, nonce, fetch=node)
    ok &= step("the licence record decodes", not isinstance(rec, verify.Refused), str(rec)[:80])
    print(f"      payer     {payer}\n      token     {token}\n"
          f"      amount    {amount:,}\n      workspace {workspace[:18]}…")

    print("\n2. verification — every field must match")
    args = dict(expect_payer=payer, expect_token=token, expect_workspace=workspace,
                min_amount=amount)
    granted = verify.verify_payment(NET, CONTRACT, nonce, fetch=node, **args)
    ok &= step("a matching request is granted", bool(granted), str(granted))
    for label, wrong in (("a different payer", dict(expect_payer=CONTRACT)),
                         ("a different token", dict(expect_token=CONTRACT)),
                         ("a different workspace", dict(expect_workspace="0x" + "11" * 32)),
                         ("paying one unit less", dict(min_amount=amount + 1))):
        r = verify.verify_payment(NET, CONTRACT, nonce, fetch=node, **{**args, **wrong})
        ok &= step(f"{label} is refused", not r, r.reason if r is not None and not r else "")

    print("\n3. the failure the review found — the node is unreachable")
    r = verify.verify_payment(NET, CONTRACT, nonce, fetch=dead, **args)
    ok &= step("an unreachable node REFUSES rather than granting", not r,
               "one firewall rule used to grant the licence")

    print("\n4. the clearance record, and what it does to the rack")
    with tempfile.TemporaryDirectory() as td:
        s = store.ClearanceStore(Path(td) / "clearances.jsonl")
        reading = {"network": NET, "contract": CONTRACT, "age_s": 1.0, "block": 70_152_715,
                   "contract_present": True, "abi_functions": 12,
                   "contract_name": "SymoneuralLicence", "error": None}

        import os
        os.environ.update(SYMONEURAL_GATEWAY_ENABLED="1", SYMONEURAL_GATEWAY_NETWORK=NET_ENV,
                          SYMONEURAL_GATEWAY_CONTRACT=CONTRACT)
        before, detail_before = gateway.unit_state(reading)
        ok &= step("before any settlement the rack is offline", before == "offline",
                   detail_before[-60:])

        s.append(store.Clearance(nonce=granted.nonce, payer=granted.payer, token=granted.token,
                                 amount=granted.amount, workspace=granted.workspace,
                                 network=NET, contract=CONTRACT, at_block=granted.at_block,
                                 at_time=granted.at_time))
        ok &= step("the clearance is durable", s.has_cleared(NET, CONTRACT), str(s.path))

        # unit_state reads the REAL store location, so point _cleared at this rehearsal one.
        real = gateway._cleared
        # `_cleared` returns (clearance, problem); the rehearsal store is healthy, so None.
        gateway._cleared = lambda n, a: (s.latest(n, a), None)       # noqa: SLF001
        try:
            after, detail_after = gateway.unit_state(reading)
            ok &= step("with a settlement on record the rack is ready", after == "ready",
                       detail_after[-70:])
            # Point the surface at mainnet while the only settlement on record is a Nile one.
            # A testnet purchase must not light the mainnet light.
            os.environ["SYMONEURAL_GATEWAY_NETWORK"] = "symoneural-live"
            mstate, _ = gateway.unit_state({**reading, "network": "mainnet"})
            os.environ["SYMONEURAL_GATEWAY_NETWORK"] = NET_ENV
            ok &= step("a settlement on ANOTHER network does not light this one",
                       mstate == "offline", f"mainnet reads {mstate} with only a {NET} licence")
        finally:
            gateway._cleared = real                                  # noqa: SLF001

    print("\n5. the entitlement handed to the buyer")
    key, pem = entitlement.generate()
    tok = entitlement.mint(key, workspace=workspace, payer=payer, nonce=nonce,
                           network=NET, contract=CONTRACT)
    ok &= step("it verifies against the public key alone",
               entitlement.verify(tok, key.public_key()) is not None, f"{len(tok)} chars")
    other, _ = entitlement.generate()
    ok &= step("another authority's key does not verify it",
               entitlement.verify(tok, other.public_key()) is None)
    ok &= step("an expired one is refused",
               entitlement.verify(entitlement.mint(key, workspace=workspace, payer=payer,
                                                   nonce=nonce, network=NET, contract=CONTRACT,
                                                   ttl_s=1, now=0), key.public_key()) is None)

    print(f"\n{'all steps passed' if ok else 'SOMETHING FAILED'} — rehearsal only: no chain was "
          f"contacted and the real rack is untouched.\n")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
