# `backend/gateway/lib/` — Library for `gateway`

No routes. **No side effects on import** -- a module here may be imported by a test, a
tool, or another component, and one that opens a socket or reads a config file at import
time makes all three unpredictable.

Anything that needs the app, the lease or a request belongs in `../gateway.py`.

| file |  |
|---|---|
| `abi.py` | Minimal ABI encoding and decoding for read-only TVM calls. Stdlib, no I/O, no keys. |
| `address.py` | TRON base58check addresses -- decode, validate, and convert to the hex the TVM uses. |
| `chain.py` | Read-only TRON node client. Stdlib `urllib` only, no wallet, no key, no signature. |
| `entitlement.py` | Ed25519 entitlements: minted by the operator, checked by the server. Never the reverse. |
| `keccak.py` | Keccak-256 -- the hash the TVM derives function selectors from. Pure stdlib. |
| `settlement_roundtrip.py` | The licence round trip, end to end, printed. Run: cd backend && python3 -m gateway.settlement_roundtrip |
| `store.py` | The record of licences that have actually cleared. This is what earns `ready`. |

See [`../README.md`](../README.md) for what `gateway` is and why.
