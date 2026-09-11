"""Green context SM partitioning.

A green context reserves a subset of SMs so a latency-critical kernel is not
stuck behind a long-running one. Measured on this box: critical-kernel latency
fell from 26.614 ms to 4.526 ms, a **5.88x** improvement, with the baseline
spending ~26.02 ms merely waiting for SMs.

**The 70-SM problem.** This part has 70 SMs, ``min_partition_size`` 8 and
``alignment`` 8. Auto-splitting fails outright::

    Error: could not find an SM split that the driver accepts on this device
           (total SMs=70, min_partition_size=8)

Explicit large splits fail too -- ``56,8``, ``48,16`` and ``32,32`` were all
tried and all returned ``CUDA_ERROR_INVALID_RESOURCE_CONFIGURATION``. The
driver enforces TPC-alignment rules beyond the advertised
``min_partition_size``, and 70 does not partition cleanly.

**Only ``8,8`` was accepted.** :data:`SAFE_SPLIT` is that value, and it is the
default here so nothing in this repository ever relies on auto-split.
"""
from __future__ import annotations


from dataclasses import dataclass
from typing import Any

from .errors import CapabilityWaived

#: The only SM split the driver accepted on this 70-SM sm_120 part.
#: Verified 2026-08-16; see the module docstring for what was rejected.
SAFE_SPLIT: tuple[int, int] = (8, 8)

#: Splits confirmed rejected on this hardware. Kept so tests can assert the
#: guard rejects them without re-discovering it against the driver each time.
KNOWN_BAD_SPLITS: tuple[tuple[int, int], ...] = ((56, 8), (48, 16), (32, 32))


@dataclass(frozen=True)
class SplitPlan:
    """A validated (long, critical) SM partition."""

    long_sms: int
    critical_sms: int

    @property
    def total(self) -> int:
        return self.long_sms + self.critical_sms

    def as_flag(self) -> str:
        """Render as the ``--split`` argument the greenContext sample takes."""
        return f"{self.long_sms},{self.critical_sms}"

    def __str__(self) -> str:
        return f"{self.long_sms}+{self.critical_sms} SMs"


def validate_split(split: tuple[int, int], total_sms: int,
                   min_partition: int = 8, alignment: int = 8) -> SplitPlan:
    """Check a split against the documented rules before touching the driver.

    Catches the arithmetic errors locally. It cannot catch every driver rule --
    ``32,32`` passes all of these checks and is still rejected on this part --
    which is exactly why :data:`SAFE_SPLIT` is a measured constant rather than
    something computed.
    """
    lo, hi = split
    for label, v in (("long", lo), ("critical", hi)):
        if v <= 0:
            raise CapabilityWaived(f"{label} partition must be positive, got {v}")
        if v % alignment:
            raise CapabilityWaived(
                f"{label} partition {v} is not a multiple of alignment {alignment}"
            )
        if v < min_partition:
            raise CapabilityWaived(
                f"{label} partition {v} is below min_partition_size {min_partition}"
            )
    if lo + hi > total_sms:
        raise CapabilityWaived(
            f"split {lo}+{hi}={lo + hi} exceeds the device's {total_sms} SMs"
        )
    return SplitPlan(long_sms=lo, critical_sms=hi)


def default_split(ctx: Any) -> SplitPlan:
    """The split to use on this device.

    Always returns :data:`SAFE_SPLIT` on a 70-SM part. **Never auto-computes** --
    auto-split is precisely what fails here.
    """
    total = ctx.caps.multiprocessor_count
    if total == 70:
        return validate_split(SAFE_SPLIT, total)
    # Other parts: still avoid auto-split, but a conservative even division of
    # a power-of-two SM count is more likely to be accepted.
    half = max(8, (total // 2) & ~7)
    try:
        return validate_split((half, 8), total)
    except CapabilityWaived:
        return validate_split(SAFE_SPLIT, total)


def describe_constraint(ctx: Any) -> str:
    """Human-readable summary for logs and test output."""
    total = ctx.caps.multiprocessor_count
    plan = default_split(ctx)
    return (
        f"green context on {total} SMs: using --split {plan.as_flag()} "
        f"(auto-split and {', '.join(f'{a},{b}' for a, b in KNOWN_BAD_SPLITS)} "
        f"are rejected by the driver on this part)"
    )
