"""TRON base58check addresses -- decode, validate, and convert to the hex the TVM uses.

The module this replaces validated addresses with `^T[1-9A-HJ-NP-Za-km-z]{33}$`, which checks
the base58 *alphabet and length* and nothing else. TRON addresses are base58**check**: a
21-byte payload beginning `0x41` followed by four bytes of double-SHA256 checksum. A
transposed or mistyped character passes that regex and is not a real address, and the rack
would then print `Nile testnet · TAbc12…wxyz configured` for an address that cannot exist.

Everything here is stdlib (`hashlib` only) and does no I/O. `reason()` returns the specific
fault rather than a boolean, because "you typed 33 characters" and "you transposed two
characters" are different problems for the operator and the rack should say which one it is.
"""
from __future__ import annotations

import hashlib

ALPHABET = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
INDEX = {c: i for i, c in enumerate(ALPHABET)}

MAINNET_PREFIX = 0x41       # every TRON address, on every network, starts with this byte
PAYLOAD_LEN = 21            # prefix + 20-byte account
CHECKSUM_LEN = 4


class AddressError(ValueError):
    """Raised by `decode`. Callers that render to a page use `reason()` instead."""


def _b58_decode(s: str) -> bytes:
    """Raw base58 decode. Leading '1's are leading zero bytes, as the encoding defines."""
    n = 0
    for ch in s:
        d = INDEX.get(ch)
        if d is None:
            raise AddressError(f"{ch!r} is not a base58 character")
        n = n * 58 + d
    body = n.to_bytes((n.bit_length() + 7) // 8, "big") if n else b""
    pad = len(s) - len(s.lstrip("1"))
    return b"\x00" * pad + body


def _b58_encode(raw: bytes) -> str:
    n = int.from_bytes(raw, "big")
    out = ""
    while n:
        n, r = divmod(n, 58)
        out = ALPHABET[r] + out
    pad = len(raw) - len(raw.lstrip(b"\x00"))
    return "1" * pad + out


def checksum(payload: bytes) -> bytes:
    return hashlib.sha256(hashlib.sha256(payload).digest()).digest()[:CHECKSUM_LEN]


def decode(addr: str) -> bytes:
    """The 21-byte payload, or raise `AddressError` naming the fault."""
    if not addr:
        raise AddressError("empty")
    if not addr.startswith("T"):
        raise AddressError("does not start with T")
    if len(addr) != 34:
        raise AddressError(f"is {len(addr)} characters, expected 34")
    raw = _b58_decode(addr)
    if len(raw) != PAYLOAD_LEN + CHECKSUM_LEN:
        raise AddressError(f"decodes to {len(raw)} bytes, expected {PAYLOAD_LEN + CHECKSUM_LEN}")
    payload, want = raw[:PAYLOAD_LEN], raw[PAYLOAD_LEN:]
    if payload[0] != MAINNET_PREFIX:
        raise AddressError(f"prefix byte is 0x{payload[0]:02x}, expected 0x41")
    if checksum(payload) != want:
        raise AddressError("checksum does not match — mistyped or transposed")
    return payload


def reason(addr: str) -> str | None:
    """`None` when the address is well-formed, otherwise why it is not."""
    try:
        decode(addr)
    except AddressError as e:
        return str(e)
    return None


def valid(addr: str) -> bool:
    return reason(addr) is None


def to_hex(addr: str) -> str:
    """Base58check -> the 21-byte `41…` hex form the TVM and the node API accept."""
    return decode(addr).hex()


def from_hex(hexaddr: str) -> str:
    """`41…` (or bare 20-byte) hex -> base58check. Round-trips `to_hex`."""
    h = hexaddr.lower().removeprefix("0x")
    raw = bytes.fromhex(h)
    if len(raw) == 20:
        raw = bytes([MAINNET_PREFIX]) + raw
    if len(raw) != PAYLOAD_LEN:
        raise AddressError(f"{len(raw)} bytes, expected 20 or 21")
    if raw[0] != MAINNET_PREFIX:
        raise AddressError(f"prefix byte is 0x{raw[0]:02x}, expected 0x41")
    return _b58_encode(raw + checksum(raw))


def evm(addr: str) -> bytes:
    """The 20-byte account, prefix stripped -- what an ABI `address` parameter carries."""
    return decode(addr)[1:]


def short(addr: str) -> str:
    """`TR7NHq…Lj6t`. Only ever applied to an address that has already been validated.

    This is the one place a string is shortened, and it is not the CSS truncation
    `.claude/CLAUDE.md` forbids: an address is a fixed-width identifier whose head and tail
    identify it, the full value is in the environment, and the rest of the detail line is
    never trimmed.
    """
    return f"{addr[:6]}…{addr[-4:]}"
