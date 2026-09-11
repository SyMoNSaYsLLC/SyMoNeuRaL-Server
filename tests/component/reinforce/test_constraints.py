"""Tests for the four hardware constraints found in the local CUDA audit.

These are regression tests for facts about *this hardware*, not about the code.
If one starts failing, the box changed -- different GPU, different toolkit, or
a driver update -- and the numbers in ``frontend/site/docs/01-hardware-dossier.md`` need
re-measuring.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from symoneural.core.errors import CapabilityWaived, CompilationError
from symoneural.core.green import (
    KNOWN_BAD_SPLITS,
    SAFE_SPLIT,
    default_split,
    describe_constraint,
    validate_split,
)
from symoneural.compute.program import KernelCache, resolve_include_paths

from .conftest import CUDA_INCLUDE_ARG, MPI_LAUNCH, has_libcudacxx, has_mpirun


# ===========================================================================
# Constraint 1 -- green context: never auto-split on 70 SMs
# ===========================================================================
class TestGreenContextSplit:
    def test_default_is_explicit_never_auto(self, ctx):
        """The default must be a concrete split, not a request to auto-size."""
        plan = default_split(ctx)
        assert plan.long_sms > 0 and plan.critical_sms > 0
        assert plan.total <= ctx.caps.multiprocessor_count

    def test_seventy_sm_part_uses_safe_split(self, ctx):
        """On this exact part, 8,8 is the only split the driver accepted."""
        if ctx.caps.multiprocessor_count != 70:
            pytest.skip(f"constraint is specific to 70-SM parts; this has "
                        f"{ctx.caps.multiprocessor_count}")
        plan = default_split(ctx)
        assert (plan.long_sms, plan.critical_sms) == SAFE_SPLIT
        assert plan.as_flag() == "8,8"

    def test_alignment_violations_rejected_locally(self, ctx):
        """Non-multiples of 8 are caught before reaching the driver."""
        total = ctx.caps.multiprocessor_count
        for bad in ((62, 8), (7, 8), (8, 3)):
            with pytest.raises(CapabilityWaived):
                validate_split(bad, total)

    def test_oversized_split_rejected(self, ctx):
        total = ctx.caps.multiprocessor_count
        with pytest.raises(CapabilityWaived):
            validate_split((total, total), total)

    def test_known_bad_splits_are_recorded(self, ctx):
        """32,32 passes arithmetic validation yet the driver rejects it.

        That gap is why SAFE_SPLIT is a measured constant, not a computation --
        this test documents the limit of local validation.
        """
        total = ctx.caps.multiprocessor_count
        if total != 70:
            pytest.skip("driver rejections were measured on the 70-SM part")
        assert (32, 32) in KNOWN_BAD_SPLITS
        validate_split((32, 32), total)      # passes locally...
        # ...and is still rejected by the driver. Not asserted against hardware
        # here because a rejected green context can leave driver state dirty.

    def test_constraint_is_described_for_logs(self, ctx):
        text = describe_constraint(ctx)
        assert "--split" in text and "rejected" in text


# ===========================================================================
# Constraint 2 -- cooperative-group includes need BOTH directories
# ===========================================================================
class TestCooperativeIncludes:
    def test_include_arg_is_colon_separated(self):
        assert CUDA_INCLUDE_ARG, "no include paths resolved"
        assert os.pathsep in CUDA_INCLUDE_ARG or len(resolve_include_paths()) == 1

    def test_every_resolved_path_exists(self):
        for p in resolve_include_paths():
            assert Path(p).is_dir(), f"resolved a non-existent include dir: {p}"

    @pytest.mark.cooperative
    def test_libcudacxx_reachable(self):
        """cuda/std/type_traits must resolve, or the CG kernel cannot compile."""
        assert has_libcudacxx(), (
            "libcu++ headers missing. cooperative_groups.h includes "
            "<cuda/std/type_traits>, which ships in cuda-cccl, not the CUDA "
            "toolkit include dir. pip install 'cuda-cccl[cu13]>=1.0.0'"
        )

    @pytest.mark.cooperative
    def test_cg_kernel_compiles_with_combined_paths(self, cache):
        """The whole point: <cooperative_groups.h> compiles with both dirs."""
        mod = cache.compile("reduction_cg")
        assert mod.get("reduce_single_pass_cg") is not None

    def test_missing_libcudacxx_gives_actionable_error(self, ctx):
        """Compiling with only the toolkit dir must fail with a usable hint."""
        toolkit_only = [p for p in resolve_include_paths()
                        if "cccl" not in p and "site-packages" not in p]
        if not toolkit_only:
            pytest.skip("no toolkit-only include dir on this box")
        isolated = KernelCache(ctx.caps.arch)
        with pytest.raises(CompilationError) as ei:
            isolated.compile("reduction_cg", include_paths=toolkit_only[:1])
        msg = str(ei.value)
        assert "cuda/std" in msg or "cooperative_groups" in msg
        assert "cuda-cccl" in msg, "error should name the package that fixes it"


# ===========================================================================
# Constraint 3 -- MPI needs a launcher, and --oversubscribe on one GPU
# ===========================================================================
class TestMPILauncher:
    def test_launch_command_shape(self):
        """--oversubscribe is required for 2 ranks on a single-GPU box."""
        assert MPI_LAUNCH[0] == "mpirun"
        assert "--oversubscribe" in MPI_LAUNCH
        assert MPI_LAUNCH[MPI_LAUNCH.index("-np") + 1] == "2"

    @pytest.mark.mpi
    def test_mpirun_present(self):
        assert has_mpirun(), (
            "mpirun not found. mpi4py alone is insufficient -- it links against "
            "the system MPI but ships no launcher. sudo apt install openmpi-bin"
        )

    @pytest.mark.mpi
    def test_two_ranks_actually_start(self, tmp_path):
        """Two oversubscribed ranks must both come up on one GPU."""
        from .conftest import mpi_run
        script = tmp_path / "rank_probe.py"
        script.write_text(
            "from mpi4py import MPI\n"
            "c = MPI.COMM_WORLD\n"
            "print(f'rank {c.Get_rank()} of {c.Get_size()}')\n"
        )
        proc = mpi_run(script)
        assert proc.returncode == 0, f"mpirun failed: {proc.stderr[:400]}"
        assert "of 2" in proc.stdout
        assert proc.stdout.count("rank") == 2


# ===========================================================================
# Constraint 4 -- P2P: check topology first, waive cleanly
# ===========================================================================
class TestP2PWaiver:
    def test_topology_checked_before_execution(self, ctx):
        """require_devices must raise CapabilityWaived, not a generic error."""
        if ctx.device_count >= 2:
            pytest.skip("box has 2+ GPUs; the waiver path is not exercised")
        with pytest.raises(CapabilityWaived) as ei:
            ctx.require_devices(2)
        assert "waiving" in str(ei.value).lower()

    def test_waiver_is_not_a_device_error(self, ctx):
        """A waiver means 'cannot here', not 'broken'. Callers rely on this."""
        from symoneural.core.errors import DeviceError, SymoneuralError
        assert issubclass(CapabilityWaived, SymoneuralError)
        assert not issubclass(CapabilityWaived, DeviceError)

    @pytest.mark.multigpu
    def test_peer_access_when_available(self, ctx):
        """Only runs with 2+ GPUs; auto-skipped otherwise by conftest."""
        ctx.require_devices(2)
        assert ctx.device_count >= 2

    def test_single_gpu_engine_still_fully_functional(self, ctx, ops):
        """The point of waiving: everything else must still work."""
        import cupy as cp
        x = cp.ones(4096, dtype=cp.float32)
        assert ops.sum(x) == pytest.approx(4096.0, rel=1e-5)
