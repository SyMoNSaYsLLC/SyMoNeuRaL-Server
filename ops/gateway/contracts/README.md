# `ops/gateway/contracts/` — the on-chain contracts

```
SymoneuralLicence.sol   the licence contract the gateway reads
MockTRC20.sol           a stand-in token, for tests. NEVER deployed to mainnet
```

Solidity, for the TVM. The gateway is **read-only against the chain**: it holds no wallet, no
key and no signature path, and `backend/gateway/lib/chain.py` is stdlib `urllib` with nothing
that could sign anything.

That split is the design. Minting an entitlement is an operator action taken elsewhere;
checking one is what this box does. Never the reverse.

`test_contracts.mjs` one directory up exercises them. `backend/gateway/lib/abi.py` and
`keccak.py` are how Python reaches them without a web3 dependency.
