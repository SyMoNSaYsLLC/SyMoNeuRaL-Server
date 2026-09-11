"""Shared fixtures, and the four hardware constraints the local audit found.

Each constraint below cost real debugging time against the cuda-samples
curriculum. They are encoded here so no test in this repository rediscovers
them.

1. **Green context (greenContext).** Auto-split fails on 70-SM sm_120; the
   driver enforces TPC alignment beyond ``min_partition_size``. Tests use
   ``--split 8,8`` via :data:`symoneural.core.green.SAFE_SPLIT`, never auto.
2. **Cooperative-group includes (reductionMultiBlockCG).** NVRTC needs *both*
   the CUDA toolkit include dir and the cuda-cccl libcu++ headers, joined by
   ``os.pathsep``. One alone gives ``cannot open source file
   "cuda/std/type_traits"``. See :data:`CUDA_INCLUDE_ARG`.
3. **MPI launcher (multiGPUGradientAverage).** Bare execution reports "requires
   at least 2 MPI processes". Tests launch via
   ``mpirun --oversubscribe -np 2`` so a single-GPU box still exercises the
   logic. See :data:`MPI_LAUNCH`.
4. **P2P waiver (simpleP2P).** Single-GPU topology is checked *before*
   execution so peer tests raise :class:`CapabilityWaived` and skip cleanly
   rather than failing.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(next(_p for _p in Path(__file__).resolve().parents if (_p / "backend" / "server.py").is_file())))

# `cupy` is deliberately absent from the system interpreter: backend/DEPENDENCIES.md
# records that this plugin's tests are excluded from the `apps/` run because "cupy is
# not on the system interpreter and must not be, because that is the serving path."
#
# That exclusion used to live only in an `--ignore` flag operators had to remember, and
# the path in the documented command (`apps/reinforce/tests`) no longer exists -- this
# package moved under `apps/studio/plugins/`. So a plain repository-wide `pytest` hit the
# import below and reported `ModuleNotFoundError: No module named 'cupy'` as a collection
# ERROR, which is indistinguishable from a broken test at a glance.
#
# Skipping here makes the exclusion self-enforcing and keeps cupy off the serving
# interpreter, which is the same "waive the capability, skip cleanly rather than fail"
# rule constraint 4 in this module's docstring already applies to single-GPU P2P.
pytest.importorskip(
    "cupy",
    reason="cupy-cuda13x is intentionally not installed on the serving interpreter; "
           "run this plugin's suite in its own venv (see requirements.txt)",
)

from symoneural.compute.ops import Ops                      # noqa: E402
from symoneural.compute.program import (                    # noqa: E402
    KernelCache,
    resolve_include_paths,
)
from symoneural.core.context import DeviceContext           # noqa: E402
from symoneural.core.errors import CapabilityWaived, DeviceError  # noqa: E402
from symoneural.core.green import SAFE_SPLIT, default_split  # noqa: E402
from symoneural.core.memory import MemoryPools              # noqa: E402

# --------------------------------------------------------------------------
# Constraint 2 -- cooperative-group include paths
# --------------------------------------------------------------------------
#: Colon-separated include path for NVRTC. Combines the CUDA toolkit include
#: dir with the cuda-cccl libcu++ headers. Passing only one produces:
#:     catastrophic error: cannot open source file "cuda/std/type_traits"
CUDA_INCLUDE_ARG: str = os.pathsep.join(resolve_include_paths())


def has_libcudacxx() -> bool:
    """True when libcu++ (``cuda/std/type_traits``) is reachable."""
    return any((Path(p) / "cuda" / "std" / "type_traits").exists()
               for p in resolve_include_paths())


# --------------------------------------------------------------------------
# Constraint 3 -- MPI launcher
# --------------------------------------------------------------------------
#: How to launch MPI-backed work. ``--oversubscribe`` lets 2 ranks share one
#: GPU, which is enough to exercise gradient-averaging logic on a dev box.
MPI_LAUNCH: list[str] = ["mpirun", "--oversubscribe", "-np", "2"]


def has_mpirun() -> bool:
    """``mpi4py`` alone is not enough -- a launcher binary is required.

    On this box ``libopenmpi40`` was present but ``mpirun`` was not, until
    ``apt install openmpi-bin``.
    """
    return shutil.which("mpirun") is not None


def mpi_run(script: Path, *args: str, timeout: int = 120) -> subprocess.CompletedProcess:
    """Run *script* under ``mpirun --oversubscribe -np 2``."""
    if not has_mpirun():
        pytest.skip("mpirun not found; install openmpi-bin")
    return subprocess.run([*MPI_LAUNCH, sys.executable, str(script), *args],
                          capture_output=True, text=True, timeout=timeout)


# --------------------------------------------------------------------------
# Fixtures
# --------------------------------------------------------------------------
@pytest.fixture(scope="session")
def ctx() -> DeviceContext:
    try:
        return DeviceContext(0)
    except DeviceError as exc:
        pytest.skip(f"no CUDA device: {exc}")


@pytest.fixture(scope="session")
def cache(ctx: DeviceContext) -> KernelCache:
    return KernelCache(ctx.caps.arch)


@pytest.fixture(scope="session")
def ops(ctx: DeviceContext, cache: KernelCache) -> Ops:
    return Ops(ctx, cache)


@pytest.fixture(scope="session")
def pools() -> MemoryPools:
    return MemoryPools(0)


@pytest.fixture
def stream(ctx: DeviceContext):
    s = ctx.create_stream()
    yield s
    s.sync()


@pytest.fixture(scope="session")
def split_plan(ctx: DeviceContext):
    """Constraint 1 -- always an explicit, validated split. Never auto."""
    return default_split(ctx)


# --------------------------------------------------------------------------
# Markers and capability-aware skipping
# --------------------------------------------------------------------------
def pytest_configure(config: pytest.Config) -> None:
    for marker, desc in [
        ("multigpu", "requires 2+ GPUs; waived on single-GPU boxes (constraint 4)"),
        ("cooperative", "requires cooperative launch + libcu++ (constraint 2)"),
        ("mpi", "requires mpirun --oversubscribe -np 2 (constraint 3)"),
        ("green", "requires green-context SM partitioning (constraint 1)"),
        ("slow", "benchmark-scale test"),
    ]:
        config.addinivalue_line("markers", f"{marker}: {desc}")


def pytest_collection_modifyitems(config: pytest.Config,
                                  items: list[pytest.Item]) -> None:
    """Constraint 4 -- check topology *before* running, then skip cleanly.

    Peer-to-peer tests are waived rather than failed on a single-GPU box, the
    same convention ``simpleP2P`` itself follows.
    """
    try:
        ndev = len(DeviceContext(0).device.get_all_devices())
    except Exception:
        ndev = 0

    skip_multigpu = pytest.mark.skip(
        reason=f"waived: 2+ GPUs required, {ndev} present (P2P cannot be "
               "demonstrated on this topology)")
    skip_no_cccl = pytest.mark.skip(
        reason="waived: libcu++ headers not found. pip install 'cuda-cccl[cu13]'")
    skip_no_mpi = pytest.mark.skip(
        reason="waived: mpirun not found. sudo apt install openmpi-bin")

    cccl_ok = has_libcudacxx()
    mpi_ok = has_mpirun()

    for item in items:
        if "multigpu" in item.keywords and ndev < 2:
            item.add_marker(skip_multigpu)
        if "cooperative" in item.keywords and not cccl_ok:
            item.add_marker(skip_no_cccl)
        if "mpi" in item.keywords and not mpi_ok:
            item.add_marker(skip_no_mpi)


def pytest_report_header(config: pytest.Config) -> list[str]:
    """Print the constraint state up front, so skips are self-explaining."""
    lines = ["symoneural_reinforce -- hardware constraint check"]
    try:
        c = DeviceContext(0)
        lines.append(f"  device      : {c.caps.summary()}")
        lines.append(f"  GPUs        : {c.device_count} "
                     f"({'P2P testable' if c.device_count > 1 else 'P2P waived'})")
        lines.append(f"  green split : --split {default_split(c).as_flag()} "
                     f"(auto-split rejected on {c.caps.multiprocessor_count} SMs)")
    except Exception as exc:
        lines.append(f"  device      : UNAVAILABLE ({exc})")
    lines.append(f"  libcu++     : {'found' if has_libcudacxx() else 'MISSING'}")
    lines.append(f"  mpirun      : "
                 f"{'found -- ' + ' '.join(MPI_LAUNCH) if has_mpirun() else 'MISSING'}")
    lines.append(f"  NVRTC -I    : {len(resolve_include_paths())} paths")
    return lines


__all__ = ["CUDA_INCLUDE_ARG", "MPI_LAUNCH", "SAFE_SPLIT", "has_libcudacxx",
           "has_mpirun", "mpi_run", "CapabilityWaived"]
