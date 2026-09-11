"""Engine exception hierarchy.

The error-handling strategy mirrors what the cuda-samples curriculum verified on
this box (see ``docs/02-setup-environments.md``): a capability that the hardware
genuinely cannot provide is *waived*, not failed. ``simpleP2P`` exits cleanly on a
single-GPU machine and that is the sample behaving correctly; the engine follows
the same convention so that "cannot run here" never masquerades as "broken".
"""
from __future__ import annotations



class SymoneuralError(Exception):
    """Base class for every engine-raised error."""


class DeviceError(SymoneuralError):
    """No usable CUDA device, or the device rejected an operation."""


class CapabilityWaived(SymoneuralError):
    """The hardware cannot provide a capability the caller asked for.

    Distinct from :class:`DeviceError`: nothing is wrong, the box simply does not
    have the feature. Callers are expected to catch this and degrade, the way
    ``simpleP2P`` waives rather than failing when a second GPU is absent.
    """


class CompilationError(SymoneuralError):
    """NVRTC rejected a kernel.

    Carries the kernel name and the compiler log, because the failure mode seen
    most often on this box -- ``cannot open source file "cuda/std/type_traits"``
    from ``reductionMultiBlockCG`` -- is only diagnosable from the log.
    """

    def __init__(self, name: str, log: str, source: str | None = None) -> None:
        self.name = name
        self.log = log
        self.source = source
        super().__init__(f"failed to compile kernel {name!r}:\n{log}")


class AllocationError(SymoneuralError):
    """The allocator could not satisfy a request."""


class SchedulerError(SymoneuralError):
    """Invalid scheduler or graph state transition."""
