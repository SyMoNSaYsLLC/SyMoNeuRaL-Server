"""Keccak-256 -- the hash the TVM derives function selectors from. Pure stdlib.

`hashlib.sha3_256` is **not** this. NIST changed the domain-separation byte from `0x01` to
`0x06` when SHA-3 was standardised, so SHA3-256 and the Keccak-256 that Ethereum and the
TRON Virtual Machine actually use produce different digests for the same input. Using
`hashlib.sha3_256` here would silently compute wrong function selectors -- every call would
hit a non-existent method and the contract would revert, which is a confusing failure a long
way from its cause.

There is no Keccak-256 in the standard library and `.claude/CLAUDE.md` forbids installing
into the serving interpreter, so it is implemented here. ~60 lines, no state, no I/O.
Verified in `test_gateway.py` against the published vectors for the empty string, `abc`,
and the two selectors this repo will actually use.
"""
from __future__ import annotations

M = (1 << 64) - 1

# Rotation offsets and the lane permutation, in the order the round applies them.
RHO = (1, 3, 6, 10, 15, 21, 28, 36, 45, 55, 2, 14,
       27, 41, 56, 8, 25, 43, 62, 18, 39, 61, 20, 44)
PI = (10, 7, 11, 17, 18, 3, 5, 16, 8, 21, 24, 4,
      15, 23, 19, 13, 12, 2, 20, 14, 22, 9, 6, 1)
RC = (0x0000000000000001, 0x0000000000008082, 0x800000000000808a, 0x8000000080008000,
      0x000000000000808b, 0x0000000080000001, 0x8000000080008081, 0x8000000000008009,
      0x000000000000008a, 0x0000000000000088, 0x0000000080008009, 0x000000008000000a,
      0x000000008000808b, 0x800000000000008b, 0x8000000000008089, 0x8000000000008003,
      0x8000000000008002, 0x8000000000000080, 0x000000000000800a, 0x800000008000000a,
      0x8000000080008081, 0x8000000000008080, 0x0000000080000001, 0x8000000080008008)

RATE = 136          # 1088 bits, the rate for a 256-bit Keccak digest


def _rol(x: int, n: int) -> int:
    return ((x << n) | (x >> (64 - n))) & M


def _f(a: list[int]) -> None:
    """Keccak-f[1600], in place on 25 64-bit lanes."""
    for rnd in range(24):
        # theta
        c = [a[i] ^ a[i + 5] ^ a[i + 10] ^ a[i + 15] ^ a[i + 20] for i in range(5)]
        d = [c[(i + 4) % 5] ^ _rol(c[(i + 1) % 5], 1) for i in range(5)]
        for i in range(5):
            for j in range(0, 25, 5):
                a[j + i] ^= d[i]
        # rho and pi
        t = a[1]
        for i in range(24):
            j = PI[i]
            a[j], t = _rol(t, RHO[i]), a[j]
        # chi
        for j in range(0, 25, 5):
            row = a[j:j + 5]
            for i in range(5):
                a[j + i] = row[i] ^ ((~row[(i + 1) % 5] & M) & row[(i + 2) % 5])
        # iota
        a[0] ^= RC[rnd]


def _sponge(data: bytes, domain: int) -> bytes:
    """The 256-bit sponge, parameterised only by the domain-separation byte.

    Keccak-256 is `domain=0x01`; SHA3-256 is `domain=0x06` and is otherwise identical. The
    parameter exists so the test suite can drive this same permutation, padding, absorb and
    squeeze against `hashlib.sha3_256` over hundreds of inputs of every length -- there is no
    second Keccak implementation on this box to check against, and four published vectors do
    not exercise the multi-block path. Nothing outside the tests passes anything but 0x01.
    """
    a = [0] * 25
    padded = bytearray(data)
    padded.append(domain)
    while len(padded) % RATE:
        padded.append(0x00)
    padded[-1] |= 0x80

    for off in range(0, len(padded), RATE):
        block = padded[off:off + RATE]
        for i in range(RATE // 8):
            a[i] ^= int.from_bytes(block[i * 8:i * 8 + 8], "little")
        _f(a)

    return b"".join(lane.to_bytes(8, "little") for lane in a[:4])


def keccak256(data: bytes) -> bytes:
    """32-byte Keccak-256 digest. Original padding (0x01), not SHA-3's 0x06."""
    return _sponge(data, 0x01)
