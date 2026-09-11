"""`python3 -m apps.gateway` — read three real TRON networks and print what came back.

## Why this exists, and why it is not in the test suite

`test_gateway.py` is 57 tests and every one of them injects `fetch=`. That is deliberate and
correct — `.claude/HANDOVER.md` §3.0d is a list of verification steps that failed on healthy
input, and a suite needing egress to pass is the next one. But it leaves exactly one function
unexercised: `chain.http_post`, the only code in this package that touches the network. A suite
that stubs the transport cannot tell you the transport works.

That is the tuner lesson in a new costume (§2c: curl proved the endpoint answered while the
page was dead). So the real call lives here, run by hand, and the assertions are about things
only a real node can settle:

- a **present** contract really does come back with an ABI — mainnet USDT
- an **absent** one really does come back as `{}` — the same address on a testnet, where
  nothing is deployed at it
- the size cap, the redirect refusal and the JSON parse survive contact with a real body

Nothing here needs a wallet, a private key, a signature or a library: `wallet/getblock` and
`wallet/getcontract` are unauthenticated reads. Nothing here costs anything. Nothing here
writes to the chain — `chain.py` cannot build a transaction and `test_gateway.py` asserts it.

## It checks both directions, because half a check is the failure mode this repo keeps hitting

`.claude/HANDOVER.md` §3.0d: *"confirm it passes on known-good input — not only that it fails
on known-bad. Both halves, every time."* So the run ends with two negative controls that must
fail: a malformed address, and a network name that is not in `NODES`. If either of those comes
back clean the probe is not discriminating and the whole reading is worthless.

    python3 -m apps.gateway                 # from backend/
    python3 -m apps.gateway --json          # the readings, for pasting into a doc

Exit status is 0 only when every expectation below held.
"""
from __future__ import annotations

import json
import sys
import time

from . import chain
from .chain import NODES

# Tether USD on TRON mainnet. Chosen because it is the single most-deployed TRC-20 contract
# there is, it is public data, and the same address is empty on both testnets — so one literal
# gives us both the present and the absent case and they cannot drift apart.
USDT_MAINNET = "TR7NHqjeKQxGTCi8q8ZY4pL8otSzgjLj6t"

# A real base58check address that decodes cleanly and has nothing deployed at it on mainnet.
# `address.valid` passes, so this exercises "the node answered and said no contract" rather
# than "we rejected the string before calling". Those are different failures and the rack
# prints different lines for them.
EMPTY_MAINNET = "TNPeeaaFB7K9cmo4uQpcU32zGK8G1NYqeL"


def _fmt(reading: dict) -> str:
    if reading.get("error"):
        return f"error: {reading['error']}"
    block = reading.get("block")
    at = f"block {block:,}" if isinstance(block, int) else "an unknown block"
    if reading.get("contract_present") is True:
        fns = reading.get("abi_functions")
        name = reading.get("contract_name") or "unnamed"
        return f"present · {name} · {fns} functions · read at {at}"
    if reading.get("contract_present") is False:
        return f"absent · node answered at {at}"
    return f"UNEXPECTED SHAPE · read at {at}"


def main(argv: list[str]) -> int:
    as_json = "--json" in argv
    readings: dict[str, dict] = {}
    failures: list[str] = []

    def expect(label: str, condition: bool, why: str) -> None:
        if not condition:
            failures.append(f"{label}: {why}")

    print("SyMoNeuRaL Gateway — live chain read. No wallet, no key, no signature, no cost.")
    print(f"transport: chain.http_post (the real one) · timeout {chain.TIMEOUT}s · "
          f"cap {chain.MAX_BYTES:,} bytes\n")

    # ---------------------------------------------------------------- head block, per network
    print("head block")
    for net in NODES:
        name, url = NODES[net]
        t0 = time.monotonic()
        try:
            num, ts = chain.head_block(net)
            ms = round((time.monotonic() - t0) * 1000)
            age = round(time.time() - ts / 1000) if ts else None
            print(f"  {name:<15} {url:<32} block {num:>12,}  {ms:>5} ms"
                  + (f"  ({age}s old)" if age is not None else ""))
            readings[f"head:{net}"] = {"block": num, "ms": ms, "block_ts_ms": ts}
            expect(f"head:{net}", num > 0, "block number was not positive")
            # A node serving a block hours old is reachable and useless, and "reachable" is
            # what a naive check would report. The rack's detail line would then be honest
            # about a stale chain while sounding current.
            if age is not None:
                expect(f"head:{net}", age < 600, f"head block is {age}s old — node is behind")
        except chain.ChainError as e:
            print(f"  {name:<15} {url:<32} FAILED: {e}")
            failures.append(f"head:{net}: {e}")

    # -------------------------------------------------------------------- the present contract
    print("\npresent contract — USDT on mainnet")
    r = chain.probe("mainnet", USDT_MAINNET)
    readings["present"] = r
    print(f"  {USDT_MAINNET}  {_fmt(r)}  [{r['elapsed_ms']} ms]")
    expect("present", r.get("error") is None, f"probe errored: {r.get('error')}")
    expect("present", r.get("contract_present") is True,
           f"contract_present was {r.get('contract_present')!r}, expected True")
    expect("present", (r.get("abi_functions") or 0) > 0,
           "a deployed TRC-20 reported no ABI functions")

    # --------------------------------------------------------------------- the absent contract
    # The same literal on a chain where it was never deployed. `{}` from the node, `None` from
    # `contract_at`, `contract_present: False` here. This is the fail-closed-by-nature property
    # the whole surface rests on: absent and unreachable are different answers and neither can
    # be mistaken for present.
    print("\nabsent contract — the same address on the testnets, and an empty mainnet address")
    for net, addr in (("nile", USDT_MAINNET), ("shasta", USDT_MAINNET),
                      ("mainnet", EMPTY_MAINNET)):
        r = chain.probe(net, addr)
        readings[f"absent:{net}:{addr[:6]}"] = r
        print(f"  {NODES[net][0]:<15} {addr}  {_fmt(r)}  [{r['elapsed_ms']} ms]")
        expect(f"absent:{net}", r.get("error") is None, f"probe errored: {r.get('error')}")
        expect(f"absent:{net}", r.get("contract_present") is False,
               f"contract_present was {r.get('contract_present')!r}, expected False")

    # ------------------------------------------------------------------- the negative controls
    # HANDOVER §3.0d: a check that has only been seen to pass has not been seen to work.
    print("\nnegative controls — these MUST fail, or the probe is not discriminating")

    bad_addr = USDT_MAINNET[:-1] + ("A" if USDT_MAINNET[-1] != "A" else "B")   # broken checksum
    r = chain.probe("mainnet", bad_addr)
    print(f"  transposed checksum   {_fmt(r)}")
    expect("control:address", bool(r.get("error")), "a malformed address was accepted")
    expect("control:address", r.get("contract_present") is None,
           "a malformed address produced a presence verdict")

    r = chain.probe("not-a-network", USDT_MAINNET)
    print(f"  unknown network       {_fmt(r)}")
    expect("control:network", bool(r.get("error")), "an unknown network was accepted")

    # The host allowlist, checked at the transport rather than reasoned about. There is no
    # SYMONEURAL_GATEWAY_NODE_URL and there must never be one; this proves the floor under that.
    try:
        chain.http_post("https://example.com/wallet/getblock", b"{}", 2.0)
        print("  off-allowlist host    ACCEPTED — this is a fault")
        failures.append("control:host: http_post called a host outside NODES")
    except chain.ChainError as e:
        print(f"  off-allowlist host    refused: {e}")
    try:
        chain.http_post("http://api.trongrid.io/wallet/getblock", b"{}", 2.0)
        print("  plaintext http        ACCEPTED — this is a fault")
        failures.append("control:tls: http_post made a plaintext request")
    except chain.ChainError as e:
        print(f"  plaintext http        refused: {e}")

    # ------------------------------------------------------------------------------- the verdict
    print()
    if failures:
        print(f"FAILED — {len(failures)} expectation(s) did not hold:")
        for f in failures:
            print(f"  · {f}")
    else:
        print("OK — every expectation held. These are measured readings, taken just now.")

    if as_json:
        print("\n" + json.dumps(readings, indent=2, sort_keys=True))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
