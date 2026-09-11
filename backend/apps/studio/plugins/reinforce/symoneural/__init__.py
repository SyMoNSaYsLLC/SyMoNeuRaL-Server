"""symoneural_reinforce -- a native CUDA inference and compute engine.

Built from cuda.core / cuda.bindings primitives and hand-written CUDA C++
kernels compiled at runtime. No third-party inference runtime is wrapped.
"""

from .engine import Engine
from .core.context import DeviceContext
from .core.errors import (
    AllocationError,
    CapabilityWaived,
    CompilationError,
    DeviceError,
    SchedulerError,
    SymoneuralError,
)

__version__ = "0.1.0"
__all__ = [
    "Engine", "DeviceContext", "SymoneuralError", "DeviceError",
    "CapabilityWaived", "CompilationError", "AllocationError", "SchedulerError",
]
