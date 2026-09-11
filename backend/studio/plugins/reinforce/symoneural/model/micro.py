"""Synthetic micro-models: an end-to-end forward pass on custom kernels only.

These exist to prove the stack composes, not to be a useful network. Weights
are generated from a seed rather than loaded from a checkpoint, so the forward
pass is fully reproducible and needs no model file.

Two models:

* :class:`MicroMLP` -- Linear -> GELU -> Linear -> bias. The minimum that
  exercises matmul, activation and broadcast-add together.
* :class:`MicroAttention` -- single-head scaled dot-product attention:
  Q,K,V projections, ``QK^T / sqrt(d)``, row softmax, ``* V``, output
  projection. Exercises matmul, transpose and softmax in the arrangement a real
  transformer block uses.

Every arithmetic step runs in a kernel from
:mod:`symoneural.compute.kernels`. CuPy allocates; it does not compute.

**Fits comfortably.** A 512-wide MLP at fp32 is ~2 MB of weights against 15.9
GiB, so nothing here approaches the capacity ceiling. That is deliberate --
the point is correctness of composition, and the benchmark suite is where
size gets pushed.
"""
from __future__ import annotations


from dataclasses import dataclass
from typing import Any

from ..compute._cupy import cp
import numpy as np

from ..compute.ops import Ops
from ..core.errors import SymoneuralError


@dataclass
class MLPConfig:
    d_in: int = 256
    d_hidden: int = 512
    d_out: int = 256
    seed: int = 0

    @property
    def param_count(self) -> int:
        return (self.d_in * self.d_hidden + self.d_hidden
                + self.d_hidden * self.d_out + self.d_out)

    @property
    def param_bytes(self) -> int:
        return self.param_count * 4


@dataclass
class AttentionConfig:
    d_model: int = 128
    seq_len: int = 64
    seed: int = 0

    @property
    def param_count(self) -> int:
        return 4 * self.d_model * self.d_model      # Wq, Wk, Wv, Wo

    @property
    def param_bytes(self) -> int:
        return self.param_count * 4


def _weights(shape: tuple[int, ...], seed: int, scale: float = 0.0) -> cp.ndarray:
    """Deterministic Xavier-ish init on the host, then staged to device once.

    The explicit ``.astype(np.float32, copy=False)`` is load-bearing: NumPy
    promotes ``float32_array * python_float`` to float64, and a float64 buffer
    handed to a float32 kernel is reinterpreted bytewise -- it produces
    plausible-looking garbage (~1e20) rather than raising.
    """
    rng = np.random.default_rng(seed)
    fan_in = shape[0]
    s = scale or (1.0 / np.sqrt(fan_in))
    w = (rng.standard_normal(shape, dtype=np.float32) * s).astype(np.float32,
                                                                 copy=False)
    return cp.asarray(w)


class MicroMLP:
    """Linear -> GELU -> Linear -> bias, on custom kernels throughout."""

    def __init__(self, ops: Ops, config: MLPConfig | None = None) -> None:
        self.ops = ops
        self.cfg = config or MLPConfig()
        c = self.cfg
        self.w1 = _weights((c.d_in, c.d_hidden), c.seed)
        self.b1 = cp.zeros(c.d_hidden, dtype=cp.float32)
        self.w2 = _weights((c.d_hidden, c.d_out), c.seed + 1)
        self.b2 = cp.zeros(c.d_out, dtype=cp.float32)

    def forward(self, x: cp.ndarray, stream: Any = None) -> cp.ndarray:
        """(batch, d_in) -> (batch, d_out)."""
        if x.ndim != 2 or x.shape[1] != self.cfg.d_in:
            raise SymoneuralError(
                f"expected (batch, {self.cfg.d_in}), got {tuple(x.shape)}"
            )
        x = cp.ascontiguousarray(x, dtype=cp.float32)
        h = self.ops.matmul(x, self.w1, stream=stream)
        self.ops.add_bias_(h, self.b1, stream=stream)
        self.ops.gelu_(h, stream=stream)
        out = self.ops.matmul(h, self.w2, stream=stream)
        self.ops.add_bias_(out, self.b2, stream=stream)
        return out

    __call__ = forward

    def reference(self, x: cp.ndarray) -> cp.ndarray:
        """CuPy reference for the same maths, for correctness tests only."""
        h = cp.asarray(x, dtype=cp.float32) @ self.w1 + self.b1
        k0, k1 = 0.7978845608028654, 0.044715
        h = 0.5 * h * (1.0 + cp.tanh(k0 * (h + k1 * h ** 3)))
        return h @ self.w2 + self.b2


class MicroAttention:
    """Single-head scaled dot-product attention on custom kernels."""

    def __init__(self, ops: Ops, config: AttentionConfig | None = None) -> None:
        self.ops = ops
        self.cfg = config or AttentionConfig()
        d = self.cfg.d_model
        s = self.cfg.seed
        self.wq = _weights((d, d), s)
        self.wk = _weights((d, d), s + 1)
        self.wv = _weights((d, d), s + 2)
        self.wo = _weights((d, d), s + 3)
        self.scale = 1.0 / float(np.sqrt(d))

    def forward(self, x: cp.ndarray, stream: Any = None) -> cp.ndarray:
        """(seq_len, d_model) -> (seq_len, d_model)."""
        if x.ndim != 2 or x.shape[1] != self.cfg.d_model:
            raise SymoneuralError(
                f"expected (seq, {self.cfg.d_model}), got {tuple(x.shape)}"
            )
        x = cp.ascontiguousarray(x, dtype=cp.float32)
        ops = self.ops

        q = ops.matmul(x, self.wq, stream=stream)
        k = ops.matmul(x, self.wk, stream=stream)
        v = ops.matmul(x, self.wv, stream=stream)

        kt = ops.transpose(k, stream=stream)          # (d, seq)
        scores = ops.matmul(q, kt, stream=stream)     # (seq, seq)

        # Scale by 1/sqrt(d) using saxpy against a zero vector, so even this
        # step stays inside a custom kernel rather than a CuPy elementwise op.
        zeros = cp.zeros_like(scores)
        scores = ops.saxpy(scores, zeros, self.scale, stream=stream)

        ops.softmax_(scores, stream=stream)
        ctx_ = ops.matmul(scores, v, stream=stream)
        return ops.matmul(ctx_, self.wo, stream=stream)

    __call__ = forward

    def reference(self, x: cp.ndarray) -> cp.ndarray:
        x = cp.asarray(x, dtype=cp.float32)
        q, k, v = x @ self.wq, x @ self.wk, x @ self.wv
        s = (q @ k.T) * self.scale
        s = cp.exp(s - s.max(axis=1, keepdims=True))
        s /= s.sum(axis=1, keepdims=True)
        return (s @ v) @ self.wo
