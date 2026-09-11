"""Correctness tests for the operators, models and scheduler.

Every operator is checked against a CuPy reference. CuPy is the oracle only --
the engine's own maths runs entirely in hand-written kernels.
"""

from __future__ import annotations

from symoneural.compute._cupy import cp
import numpy as np
import pytest

from symoneural.core.errors import AllocationError, SchedulerError, SymoneuralError
from symoneural.core.memory import escapes_l2
from symoneural.scheduler.allocator import round_to_block
from symoneural.model.micro import (
    AttentionConfig,
    MicroAttention,
    MicroMLP,
    MLPConfig,
)
from symoneural.scheduler.allocator import BlockAllocator  # noqa: F811
from symoneural.scheduler.queue import RequestQueue

TOL = dict(rtol=1e-4, atol=1e-4)


class TestDeviceContext:
    def test_reports_real_hardware(self, ctx):
        c = ctx.caps
        assert c.multiprocessor_count > 0
        assert c.total_memory > 0
        assert c.warp_size == 32
        assert c.theoretical_bandwidth_gbs > 0

    def test_free_memory_is_live(self, ctx):
        assert 0 < ctx.free_memory() <= ctx.caps.total_memory


class TestElementwise:
    def test_saxpy(self, ops, stream):
        x = cp.random.rand(8192, dtype=cp.float32)
        y = cp.random.rand(8192, dtype=cp.float32)
        got = ops.saxpy(x, y, 2.5, stream=stream); stream.sync()
        cp.testing.assert_allclose(got, 2.5 * x + y, **TOL)

    def test_relu(self, ops, stream):
        x = (cp.random.rand(4096, dtype=cp.float32) - 0.5)
        got = ops.relu_(x.copy(), stream=stream); stream.sync()
        cp.testing.assert_allclose(got, cp.maximum(x, 0), **TOL)

    def test_gelu(self, ops, stream):
        x = (cp.random.rand(4096, dtype=cp.float32) - 0.5) * 4
        got = ops.gelu_(x.copy(), stream=stream); stream.sync()
        k0, k1 = 0.7978845608028654, 0.044715
        cp.testing.assert_allclose(got, 0.5 * x * (1 + cp.tanh(k0 * (x + k1 * x**3))), **TOL)

    def test_add_bias_broadcasts_over_rows(self, ops, stream):
        x = cp.random.rand(37, 64, dtype=cp.float32)
        b = cp.random.rand(64, dtype=cp.float32)
        got = ops.add_bias_(x.copy(), b, stream=stream); stream.sync()
        cp.testing.assert_allclose(got, x + b, **TOL)

    def test_float64_rejected_not_reinterpreted(self, ops):
        """A float64 buffer in a float32 kernel yields garbage, not an error.

        Regression: this exact bug produced ~1e20 values in MicroMLP.
        """
        with pytest.raises(SymoneuralError, match="float32"):
            ops.relu_(cp.zeros(16, dtype=cp.float64))

    def test_noncontiguous_rejected(self, ops):
        x = cp.random.rand(32, 32, dtype=cp.float32)
        with pytest.raises(SymoneuralError, match="contiguous"):
            ops.relu_(x[:, ::2])


class TestCopyAndTranspose:
    @pytest.mark.parametrize("n", [4096, 4095, 1])   # vec4 path and scalar fallback
    def test_copy_roundtrip(self, ops, stream, n):
        src = cp.random.rand(n, dtype=cp.float32)
        got = ops.copy(src, stream=stream); stream.sync()
        cp.testing.assert_array_equal(got, src)

    @pytest.mark.parametrize("shape", [(64, 64), (128, 32), (33, 65)])
    def test_transpose(self, ops, stream, shape):
        x = cp.random.rand(*shape, dtype=cp.float32)
        got = ops.transpose(x, stream=stream); stream.sync()
        cp.testing.assert_array_equal(got, x.T)


class TestMatmul:
    @pytest.mark.parametrize("m,k,n", [(64, 64, 64), (128, 96, 64), (33, 47, 65)])
    def test_against_reference(self, ops, stream, m, k, n):
        a = cp.random.rand(m, k, dtype=cp.float32)
        b = cp.random.rand(k, n, dtype=cp.float32)
        got = ops.matmul(a, b, stream=stream); stream.sync()
        cp.testing.assert_allclose(got, a @ b, rtol=1e-3, atol=1e-3)

    def test_inner_dim_mismatch(self, ops):
        with pytest.raises(SymoneuralError, match="inner dims"):
            ops.matmul(cp.zeros((4, 5), dtype=cp.float32),
                       cp.zeros((6, 7), dtype=cp.float32))


class TestReductions:
    def test_sum_exact_on_ones(self, ops):
        assert ops.sum(cp.ones(1 << 20, dtype=cp.float32)) == pytest.approx(1 << 20)

    def test_sum_matches_cupy(self, ops):
        x = cp.random.rand(1 << 18, dtype=cp.float32)
        assert ops.sum(x) == pytest.approx(float(x.sum()), rel=1e-4)

    def test_max(self, ops):
        x = cp.random.rand(1 << 16, dtype=cp.float32)
        assert ops.max(x) == pytest.approx(float(x.max()), rel=1e-6)

    @pytest.mark.cooperative
    def test_single_pass_cg_matches_two_stage(self, ops):
        x = cp.random.rand(1 << 20, dtype=cp.float32)
        assert ops.sum_cooperative(x) == pytest.approx(ops.sum(x), rel=1e-4)


class TestSoftmax:
    def test_rows_sum_to_one(self, ops, stream):
        x = cp.random.rand(32, 128, dtype=cp.float32) * 6
        got = ops.softmax_(x.copy(), stream=stream); stream.sync()
        cp.testing.assert_allclose(got.sum(axis=1), cp.ones(32), rtol=1e-5)

    def test_numerically_stable_on_large_inputs(self, ops, stream):
        """Without the max-subtraction this overflows to NaN."""
        x = cp.full((4, 64), 500.0, dtype=cp.float32)
        got = ops.softmax_(x, stream=stream); stream.sync()
        assert bool(cp.isfinite(got).all())


class TestMicroModels:
    def test_mlp_forward(self, ops, stream):
        mlp = MicroMLP(ops, MLPConfig(d_in=128, d_hidden=256, d_out=64))
        x = cp.random.rand(16, 128, dtype=cp.float32)
        cp.cuda.runtime.deviceSynchronize()   # x ready before kernels read it
        got = mlp.forward(x, stream=stream); stream.sync()
        cp.cuda.runtime.deviceSynchronize()
        assert got.shape == (16, 64)
        cp.testing.assert_allclose(got, mlp.reference(x), rtol=1e-3, atol=1e-3)

    def test_attention_forward(self, ops, stream):
        att = MicroAttention(ops, AttentionConfig(d_model=64, seq_len=32))
        x = cp.random.rand(32, 64, dtype=cp.float32)
        cp.cuda.runtime.deviceSynchronize()
        got = att.forward(x, stream=stream); stream.sync()
        cp.cuda.runtime.deviceSynchronize()
        assert got.shape == (32, 64)
        cp.testing.assert_allclose(got, att.reference(x), rtol=1e-3, atol=1e-3)

    def test_deterministic_weights(self, ops):
        a = MicroMLP(ops, MLPConfig(seed=7))
        b = MicroMLP(ops, MLPConfig(seed=7))
        cp.testing.assert_array_equal(a.w1, b.w1)

    def test_wrong_input_width_rejected(self, ops):
        mlp = MicroMLP(ops, MLPConfig(d_in=128))
        with pytest.raises(SymoneuralError):
            mlp.forward(cp.zeros((4, 99), dtype=cp.float32))


class TestAllocator:
    def test_rounds_to_power_of_two(self):
        assert round_to_block(1) == 4096
        assert round_to_block(5000) == 8192
        assert round_to_block(1 << 20) == 1 << 20

    def test_recycles_freed_blocks(self, pools):
        alloc = BlockAllocator(pools)
        b = alloc.allocate(8192)
        alloc.free(b)
        b2 = alloc.allocate(8192)
        assert alloc.stats.hits == 1
        assert b2 is b
        alloc.release_all()

    def test_rejects_nonpositive(self, pools):
        with pytest.raises(AllocationError):
            BlockAllocator(pools).allocate(0)

    def test_capacity_ceiling_is_enforced(self, pools):
        alloc = BlockAllocator(pools, capacity_bytes=8192)
        alloc.allocate(4096)
        alloc.allocate(4096)
        with pytest.raises(AllocationError, match="capacity"):
            alloc.allocate(4096)
        alloc.release_all()


class TestL2Guard:
    def test_detects_cache_resident_sizes(self, ctx):
        l2 = ctx.caps.l2_bytes
        assert not escapes_l2(8 * 2**20, l2)      # 8 MB: measures cache
        assert escapes_l2(512 * 2**20, l2)        # 512 MB: measures DRAM


class TestRequestQueue:
    def test_batches_concurrent_submissions(self):
        seen: list[int] = []

        def handler(batch):
            seen.append(len(batch))
            return [p * 2 for p in batch]

        with RequestQueue(handler, max_batch=8, max_wait_ms=20) as q:
            reqs = [q.submit(i) for i in range(8)]
            assert [r.wait(10) for r in reqs] == [i * 2 for i in range(8)]
        assert max(seen) > 1, "nothing batched; max_wait_ms may be too short"

    def test_handler_error_propagates_to_caller(self):
        def bad(batch):
            raise ValueError("kernel exploded")

        with RequestQueue(bad, max_batch=2) as q:
            with pytest.raises(ValueError, match="exploded"):
                q.submit_and_wait(1, timeout=5)

    def test_submit_before_start_is_rejected(self):
        q = RequestQueue(lambda b: b)
        with pytest.raises(SchedulerError, match="not running"):
            q.submit(1)


class TestGraphs:
    def test_capture_and_replay_matches_direct(self, ctx, ops):
        """Graph replay produces the same result as a direct launch.

        Note the explicit ``deviceSynchronize()`` calls. CuPy operations
        (``fill``, arithmetic, ``random``) run on CuPy's current stream, while
        the graph replays on a ``cuda.core`` stream. Nothing synchronises those
        two implicitly, so without the barriers ``out.fill(0)`` can be ordered
        *after* the graph's write and silently zero the result -- an
        intermittent failure that reproduced roughly 1 run in 8.

        Same root cause as the benchmark harness bug documented in
        ``bench/suite.py::_time_device``: mixing CuPy streams with cuda.core
        streams requires an explicit barrier every time.
        """
        from cuda.core import LaunchConfig, launch
        from symoneural.compute.ops import DEFAULT_BLOCK, _grid_for
        from symoneural.scheduler.graph import GraphCache

        stream = ctx.create_stream()
        n = 1 << 14
        x = cp.random.rand(n, dtype=cp.float32)
        y = cp.random.rand(n, dtype=cp.float32)
        out = cp.zeros(n, dtype=cp.float32)
        expected = 1.5 * x + y
        cp.cuda.runtime.deviceSynchronize()   # inputs ready before capture

        k = ops.cache.kernel("elementwise", "saxpy<float>")
        cfg = LaunchConfig(grid=_grid_for(n, DEFAULT_BLOCK,
                                          ctx.caps.multiprocessor_count),
                           block=DEFAULT_BLOCK)

        def record(target):
            launch(target, cfg, k, x.data.ptr, y.data.ptr, out.data.ptr,
                   np.float32(1.5), np.uint64(n))

        g = GraphCache(ctx).capture("t", stream, record, buffers={"out": out})
        cp.cuda.runtime.deviceSynchronize()   # fill retired before replay
        g.launch(stream)
        stream.sync()
        cp.cuda.runtime.deviceSynchronize()   # replay retired before reading
        cp.testing.assert_allclose(out, expected, **TOL)
        assert g.replays == 1

    def test_missing_graph_raises(self, ctx):
        from symoneural.scheduler.graph import GraphCache
        with pytest.raises(SchedulerError, match="no captured graph"):
            GraphCache(ctx).replay("nope", ctx.create_stream())


class TestKernelCache:
    def test_compiles_once_then_reuses(self, ctx):
        from symoneural.compute.program import KernelCache
        kc = KernelCache(ctx.caps.arch)
        kc.compile("elementwise")
        assert kc.compile_count == 1
        kc.compile("elementwise")
        assert kc.compile_count == 1, "recompiled a cached module"

    def test_unknown_source_named_in_error(self, ctx):
        from symoneural.compute.program import KernelCache
        from symoneural.core.errors import CompilationError
        with pytest.raises(CompilationError, match="unknown kernel source"):
            KernelCache(ctx.caps.arch).compile("does_not_exist")
