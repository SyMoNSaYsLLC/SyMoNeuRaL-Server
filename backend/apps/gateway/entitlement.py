"""Ed25519 entitlements: minted by the operator, checked by the server. Never the reverse.

An entitlement is a short, signed statement that a specific payer settled a specific licence
for a specific workspace, and that it is good until a specific time. It is the artefact the
rest of the system checks, so that checking does not require a chain read on every request —
while still not being the "set `is_licensed = True` forever" bug from
`docs/specs/symon-ml-review.md` finding 1, because it **expires** and is re-verified on use.

## The key asymmetry, which is the whole security argument

Minting needs the Ed25519 *private* key and happens on the operator's machine. Verifying needs
only the *public* key. The serving process is given the public key and nothing else, so a
compromised web process can check licences and cannot issue them. `mint()` is in this module
for symmetry and testing; it is never called by the API, and `test_settlement.py` asserts the
serving path can reach no private key.

This is deliberately not "the chain proves it" — `__init__.py` explains why that cannot work
against a public ledger. The licence authority is a server we run, stated plainly.

## Expiry is not a formality

`verify()` refuses an expired entitlement, refuses one that is not yet valid, and refuses one
whose signature does not check. There is no grace period and no "expired but recently" branch:
that branch is how a revoked licence keeps working. Re-mint instead — it costs one signature.

The payload is canonical JSON with sorted keys and no whitespace, so the bytes that were signed
can be reconstructed exactly. A signature over a re-serialised dict that sorts differently
verifies on the minting machine and fails everywhere else.
"""
from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey, Ed25519PublicKey,
)

VERSION = 1
DEFAULT_TTL_S = 86_400          # one day; re-minting is cheap and revocation should bite fast


class EntitlementError(ValueError):
    """Raised by `mint`. `verify` never raises -- it returns None. See its docstring."""


@dataclass(frozen=True)
class Entitlement:
    """What the operator asserts. Every field is checked by somebody."""
    version: int
    workspace: str        # keccak of the build configuration, 0x-prefixed
    payer: str            # TRON base58check address that settled
    nonce: int            # the quote nonce, so this maps 1:1 to one on-chain licence
    network: str          # which chain it settled on -- a testnet licence is not a mainnet one
    contract: str         # which licensing contract, so a redeployment invalidates old grants
    issued_at: int
    expires_at: int

    def payload(self) -> bytes:
        """The exact bytes that get signed. Canonical, so both sides agree."""
        return json.dumps(asdict(self), sort_keys=True, separators=(",", ":")).encode()


def mint(key: Ed25519PrivateKey, *, workspace: str, payer: str, nonce: int, network: str,
         contract: str, ttl_s: int = DEFAULT_TTL_S, now: int | None = None) -> str:
    """Sign an entitlement. Operator side only -- this needs the private key.

    Returns `<base64url payload>.<base64url signature>`, which is a compact single token and
    is not a JWT: no algorithm field, so there is no `alg: none` to be confused by, and no
    negotiation about which key or curve was used. It is always Ed25519.
    """
    import base64

    if ttl_s <= 0:
        raise EntitlementError(f"ttl must be positive, got {ttl_s}")
    if not workspace.startswith("0x") or len(workspace) != 66:
        raise EntitlementError(f"workspace must be a 0x-prefixed 32-byte hash, got {workspace!r}")
    t = int(now if now is not None else time.time())
    ent = Entitlement(version=VERSION, workspace=workspace.lower(), payer=payer, nonce=nonce,
                      network=network, contract=contract, issued_at=t, expires_at=t + ttl_s)
    body = ent.payload()
    sig = key.sign(body)
    b64 = lambda b: base64.urlsafe_b64encode(b).rstrip(b"=").decode()   # noqa: E731
    return f"{b64(body)}.{b64(sig)}"


def verify(token: str, public_key: Ed25519PublicKey | bytes, *,
           now: float | None = None) -> Entitlement | None:
    """Check an entitlement token. Returns the `Entitlement`, or **None** for every failure.

    None rather than an exception, and None rather than False, for the reason given in
    `verify.py`: a caller that has to wrap a licence check in `try/except` will eventually
    write `except: pass`, which is the reviewed fail-open bug wearing a different hat. There
    is exactly one truthy return and it requires a valid signature on an unexpired payload.
    """
    import base64

    if isinstance(public_key, (bytes, bytearray)):
        try:
            public_key = Ed25519PublicKey.from_public_bytes(bytes(public_key))
        except Exception:                       # noqa: BLE001 - malformed key is a refusal
            return None
    if not isinstance(token, str) or token.count(".") != 1:
        return None

    def unb64(s: str) -> bytes:
        return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))

    try:
        body_s, sig_s = token.split(".")
        body, sig = unb64(body_s), unb64(sig_s)
    except Exception:                           # noqa: BLE001
        return None

    try:
        public_key.verify(sig, body)
    except InvalidSignature:
        return None
    except Exception:                           # noqa: BLE001
        return None

    try:
        data = json.loads(body)
        ent = Entitlement(**data)
    except Exception:                           # noqa: BLE001 - unknown/missing fields refuse
        return None

    if ent.version != VERSION:
        return None
    t = time.time() if now is None else now
    # Both bounds. An entitlement whose issued_at is in the future is a clock disagreement or a
    # forged payload, and neither should be honoured just because the signature checks out.
    if not (ent.issued_at <= t < ent.expires_at):
        return None
    return ent


# --------------------------------------------------------------------------- key handling


def load_public_key(pem_or_raw: bytes) -> Ed25519PublicKey | None:
    """Read a public key from PEM or from 32 raw bytes. None if it is neither."""
    try:
        return Ed25519PublicKey.from_public_bytes(pem_or_raw) if len(pem_or_raw) == 32 else \
            serialization.load_pem_public_key(pem_or_raw)                      # type: ignore
    except Exception:                           # noqa: BLE001
        return None


def generate() -> tuple[Ed25519PrivateKey, bytes]:
    """A new authority keypair, and the public half as PEM. Operator side; see `ops/gateway/`."""
    k = Ed25519PrivateKey.generate()
    pub = k.public_key().public_bytes(serialization.Encoding.PEM,
                                      serialization.PublicFormat.SubjectPublicKeyInfo)
    return k, pub
