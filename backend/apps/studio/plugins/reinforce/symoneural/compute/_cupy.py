"""The one place this engine imports CuPy, and the one place it decides what absence means.

``core.errors`` opens with this project's rule:

    a capability that the hardware genuinely cannot provide is *waived*, not failed ...
    so that "cannot run here" never masquerades as "broken".

Five modules broke that rule with a bare ``import cupy as cp`` at module scope, and on a box
without CuPy -- which is this box -- each died with a raw ``ModuleNotFoundError`` that reads
exactly like a defect. Owner, 2026-09-09: *"That is a bug, not a design question, and it is
true regardless of what I decide about cupy itself."*

The guard lives here rather than being repeated at each site for two reasons. One place
decides what absence means, so the five sites cannot drift apart. And a bare ``import cupy``
copied into a sixth file is a visible inconsistency next to five ``from ... import cp``
lines, where before it would have looked like the house style.

Use it as::

    from ._cupy import cp          # inside symoneural.compute
    from .compute._cupy import cp  # inside symoneural
    from ..compute._cupy import cp # inside symoneural.model

**This is not on the API's startup path.** ``reinforce/__init__.py`` imports only
``.jobs.status`` and ``.routes.router``, so ``api.py:148`` never reaches any of this.
Verified by importing ``apps.studio.plugins.reinforce`` with CuPy absent: it succeeds and
``enabled()`` returns False.
"""

from __future__ import annotations

from ..core.errors import CapabilityWaived

try:
    import cupy as cp
except ImportError as exc:  # pragma: no cover -- depends on what is installed
    raise CapabilityWaived(
        "cupy is not installed on this interpreter, so the CUDA compute engine cannot run. "
        "Every operator allocates through CuPy as a typed allocation and DLPack layer; the "
        "arithmetic itself runs in kernels from symoneural.compute.kernels. This is a "
        "waiver, not a fault -- nothing is broken, the capability is absent. Whether to "
        "install it is a decision about whether this engine is part of the product: see "
        "review/commissioning-20260909/QUESTIONS-FOR-OWNER.md Q0."
    ) from exc

__all__ = ["cp"]
