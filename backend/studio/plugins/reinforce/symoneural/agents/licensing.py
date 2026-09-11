"""Checkpoint sealing and licence verification hooks.

What this module actually does
------------------------------

**Implemented and tested:** symmetric encryption of checkpoint files at rest,
a deny-by-default verification interface, and an unseal path that refuses to
produce plaintext unless verification passes. The audit record is real.

**Stubbed:** the TRON TVM client. :class:`DenyAllVerifier` is the default and
returns a denial with a reason. There is no chain RPC, no contract address, no
key material. Wire :class:`LicenceVerifier` to your own client to make it live.

Two accuracy notes, because getting these wrong changes what you can promise
-----------------------------------------------------------------------------

1. **Fernet is not AES-256.** Fernet is AES-128 in CBC mode with PKCS7 padding,
   authenticated by HMAC-SHA256. Its 32-byte key is *split* into a 16-byte
   signing key and a 16-byte encryption key. If a genuine 256-bit cipher is
   required — for a procurement checkbox or a compliance regime that names
   AES-256 — use :class:`Aes256GcmSealer`, which is AES-256-GCM. Both are
   provided; only the naming differs from the original brief.

2. **This protects checkpoints at rest, not in use.** Once weights are unsealed
   into VRAM, anyone who can attach a debugger to this process, read
   ``/proc/<pid>/mem``, or run code on the GPU can recover them. That is a
   property of executing a model at all, not a gap in this implementation. It
   raises the cost of casual copying and gives you an audit trail; describing it
   to end users as making extraction impossible would be false.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from ..core.errors import SymoneuralError


class LicenceError(SymoneuralError):
    """Verification failed, or an unseal was attempted without it."""


class SealError(SymoneuralError):
    """Sealing or unsealing failed for a non-licence reason."""


# ---------------------------------------------------------------------------
# Verification interface
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Entitlement:
    """The result of a licence check."""

    granted: bool
    subject: str
    reason: str
    expires_at: float | None = None
    evidence: dict[str, str] = field(default_factory=dict)

    @property
    def expired(self) -> bool:
        return self.expires_at is not None and time.time() > self.expires_at

    @property
    def usable(self) -> bool:
        return self.granted and not self.expired


class LicenceVerifier(Protocol):
    """Implement this against a real TRON TVM client."""

    def verify(self, checkpoint_id: str, subject: str) -> Entitlement: ...


class DenyAllVerifier:
    """Default verifier. Denies everything, loudly.

    Deny-by-default is deliberate: a stub that returns ``granted=True`` would
    silently disable the entire control the moment someone forgot to configure
    a real one.
    """

    def verify(self, checkpoint_id: str, subject: str) -> Entitlement:
        return Entitlement(
            granted=False, subject=subject,
            reason="no licence verifier configured; TRON TVM client is a stub. "
                   "Provide a LicenceVerifier implementation to enable unsealing.",
            evidence={"checkpoint_id": checkpoint_id, "verifier": "DenyAllVerifier"},
        )


class StaticAllowVerifier:
    """Allows a fixed set of checkpoint IDs. **Testing and local dev only.**"""

    def __init__(self, allowed: set[str], ttl_seconds: float = 3600.0) -> None:
        self.allowed = set(allowed)
        self.ttl = ttl_seconds

    def verify(self, checkpoint_id: str, subject: str) -> Entitlement:
        ok = checkpoint_id in self.allowed
        return Entitlement(
            granted=ok, subject=subject,
            reason=("allowed by static policy" if ok
                    else f"{checkpoint_id!r} not in the static allow-list"),
            expires_at=time.time() + self.ttl if ok else None,
            evidence={"checkpoint_id": checkpoint_id,
                      "verifier": "StaticAllowVerifier",
                      "warning": "static policy — not a real licence check"},
        )


# ---------------------------------------------------------------------------
# Sealers
# ---------------------------------------------------------------------------
class FernetSealer:
    """Fernet envelope. **AES-128-CBC + HMAC-SHA256**, despite common shorthand.

    Requires the ``cryptography`` package.
    """

    algorithm = "Fernet (AES-128-CBC + HMAC-SHA256)"
    key_bytes = 32          # split 16 signing / 16 encryption

    def __init__(self, key: bytes) -> None:
        try:
            from cryptography.fernet import Fernet
        except ImportError as exc:  # pragma: no cover
            raise SealError(
                "FernetSealer needs the 'cryptography' package: "
                "pip install cryptography"
            ) from exc
        self._fernet = Fernet(key)

    @staticmethod
    def generate_key() -> bytes:
        from cryptography.fernet import Fernet
        return Fernet.generate_key()

    def seal(self, plaintext: bytes) -> bytes:
        return self._fernet.encrypt(plaintext)

    def unseal(self, ciphertext: bytes) -> bytes:
        from cryptography.fernet import InvalidToken
        try:
            return self._fernet.decrypt(ciphertext)
        except InvalidToken as exc:
            raise SealError("checkpoint failed authentication — wrong key or "
                            "the file was modified") from exc


class Aes256GcmSealer:
    """AES-256-GCM. Use when 256-bit really is the requirement.

    Prepends a 12-byte nonce to the ciphertext.
    """

    algorithm = "AES-256-GCM"
    key_bytes = 32

    def __init__(self, key: bytes) -> None:
        if len(key) != 32:
            raise SealError(f"AES-256 needs a 32-byte key, got {len(key)}")
        try:
            from cryptography.hazmat.primitives.ciphers.aead import AESGCM
        except ImportError as exc:  # pragma: no cover
            raise SealError("needs the 'cryptography' package") from exc
        self._aead = AESGCM(key)

    @staticmethod
    def generate_key() -> bytes:
        return os.urandom(32)

    def seal(self, plaintext: bytes) -> bytes:
        nonce = os.urandom(12)
        return nonce + self._aead.encrypt(nonce, plaintext, None)

    def unseal(self, ciphertext: bytes) -> bytes:
        if len(ciphertext) < 13:
            raise SealError("ciphertext too short to contain a nonce")
        try:
            return self._aead.decrypt(ciphertext[:12], ciphertext[12:], None)
        except Exception as exc:
            raise SealError("checkpoint failed authentication — wrong key or "
                            "the file was modified") from exc


# ---------------------------------------------------------------------------
# Custodian
# ---------------------------------------------------------------------------
@dataclass
class UnsealRecord:
    """One audit entry. Written by the state-verifier agent."""

    checkpoint_id: str
    subject: str
    granted: bool
    reason: str
    sha256: str
    at: float
    algorithm: str

    def as_dict(self) -> dict[str, object]:
        return dict(self.__dict__)


class WeightCustodian:
    """Holds sealed checkpoints; unseals only after a positive verification.

    The ordering is the control: :meth:`unseal` calls the verifier *before*
    touching ciphertext, and raises :class:`LicenceError` on denial without
    decrypting anything.
    """

    def __init__(self, sealer: FernetSealer | Aes256GcmSealer,
                 verifier: LicenceVerifier | None = None,
                 audit_path: Path | None = None) -> None:
        self.sealer = sealer
        self.verifier: LicenceVerifier = verifier or DenyAllVerifier()
        self.audit_path = audit_path
        self.records: list[UnsealRecord] = []

    # -- at rest -----------------------------------------------------------
    def seal_to_file(self, plaintext: bytes, path: Path) -> dict[str, object]:
        path = Path(path)
        blob = self.sealer.seal(plaintext)
        path.write_bytes(blob)
        return {
            "path": str(path),
            "algorithm": self.sealer.algorithm,
            "plaintext_sha256": hashlib.sha256(plaintext).hexdigest(),
            "sealed_bytes": len(blob),
        }

    # -- unseal ------------------------------------------------------------
    def unseal(self, checkpoint_id: str, subject: str,
               ciphertext: bytes) -> bytes:
        """Verify, then decrypt. Never the other way round."""
        ent = self.verifier.verify(checkpoint_id, subject)

        if not ent.usable:
            why = ent.reason if not ent.expired else f"{ent.reason} (expired)"
            self._record(checkpoint_id, subject, False, why, "")
            raise LicenceError(
                f"unseal denied for {checkpoint_id!r} (subject {subject!r}): {why}"
            )

        plaintext = self.sealer.unseal(ciphertext)
        self._record(checkpoint_id, subject, True, ent.reason,
                     hashlib.sha256(plaintext).hexdigest())
        return plaintext

    def unseal_file(self, checkpoint_id: str, subject: str, path: Path) -> bytes:
        path = Path(path)
        if not path.exists():
            raise SealError(f"sealed checkpoint not found: {path}")
        return self.unseal(checkpoint_id, subject, path.read_bytes())

    # -- audit -------------------------------------------------------------
    def _record(self, checkpoint_id: str, subject: str, granted: bool,
                reason: str, sha: str) -> None:
        rec = UnsealRecord(checkpoint_id=checkpoint_id, subject=subject,
                           granted=granted, reason=reason, sha256=sha,
                           at=time.time(), algorithm=self.sealer.algorithm)
        self.records.append(rec)
        if self.audit_path:
            # Append-only. Denials are recorded as carefully as grants -- a
            # log of successes alone tells you nothing about attacks.
            with open(self.audit_path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec.as_dict()) + "\n")

    def audit_trail(self) -> list[dict[str, object]]:
        return [r.as_dict() for r in self.records]

    @property
    def denial_count(self) -> int:
        return sum(1 for r in self.records if not r.granted)
