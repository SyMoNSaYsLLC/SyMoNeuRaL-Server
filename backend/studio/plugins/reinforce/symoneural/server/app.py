"""FastAPI backend routing tensors through custom CUDA execution streams.

Run it::

    uvicorn symoneural.server.app:app --host 127.0.0.1 --port 8000

The engine is a single process-wide instance created on startup, because a
CUDA context is per-process and building one per request would be absurd. The
batching queue is what provides concurrency; the ASGI layer stays thin.
"""
from __future__ import annotations


import time
from contextlib import asynccontextmanager
from typing import Any

import numpy as np
from fastapi import FastAPI, HTTPException

from ..core.errors import CapabilityWaived, SymoneuralError
from ..engine import Engine
from .schemas import (
    AttentionRequest,
    DeviceResponse,
    HealthResponse,
    MLPRequest,
    ReduceRequest,
    ScalarResponse,
    StatsResponse,
    TensorResponse,
)

_engine: Engine | None = None


def get_engine() -> Engine:
    if _engine is None:
        raise HTTPException(503, "engine not initialised")
    return _engine


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Build the engine once, tear it down cleanly."""
    global _engine
    _engine = Engine().start()
    # Warm the kernel cache so the first real request does not pay ~3.6 s of
    # NVRTC compilation, the cost measured on vectorAdd's first run.
    _engine.mlp_forward(np.zeros((1, _engine.mlp.cfg.d_in), dtype=np.float32))
    try:
        yield
    finally:
        _engine.stop()
        _engine = None


app = FastAPI(
    title="symoneural_reinforce",
    version="0.1.0",
    summary="Native CUDA inference and compute engine",
    description=(
        "Tensor operations executed by hand-written CUDA kernels compiled at "
        "runtime through cuda.core.Program. No third-party inference runtime."
    ),
    lifespan=lifespan,
)


def _tensor_response(arr: np.ndarray, device_ms: float | None = None) -> TensorResponse:
    a = np.atleast_2d(np.asarray(arr, dtype=np.float32))
    return TensorResponse(shape=list(a.shape),
                          data=a.tolist(),
                          device_ms=device_ms)


@app.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    eng = get_engine()
    return HealthResponse(status="ok", device=eng.ctx.caps.name,
                          queue_running=eng.queue.running)


@app.get("/device", response_model=DeviceResponse)
def device() -> DeviceResponse:
    return DeviceResponse(**get_engine().device_info())


@app.get("/stats", response_model=StatsResponse)
def stats() -> StatsResponse:
    return StatsResponse(**get_engine().stats())


@app.post("/v1/mlp", response_model=TensorResponse)
def mlp(req: MLPRequest) -> TensorResponse:
    """Forward a batch through the micro-MLP."""
    eng = get_engine()
    t0 = time.perf_counter()
    try:
        if req.batched:
            out = np.stack([eng.infer(r) for r in req.rows])
        else:
            out = eng.mlp_forward(req.rows)
    except SymoneuralError as exc:
        raise HTTPException(400, str(exc)) from exc
    return _tensor_response(out, (time.perf_counter() - t0) * 1e3)


@app.post("/v1/attention", response_model=TensorResponse)
def attention(req: AttentionRequest) -> TensorResponse:
    """Single-head scaled dot-product attention over one block."""
    eng = get_engine()
    t0 = time.perf_counter()
    try:
        out = eng.attention_forward(req.rows)
    except SymoneuralError as exc:
        raise HTTPException(400, str(exc)) from exc
    return _tensor_response(out, (time.perf_counter() - t0) * 1e3)


@app.post("/v1/reduce", response_model=ScalarResponse)
def reduce(req: ReduceRequest) -> ScalarResponse:
    """Sum a vector on the GPU.

    ``cooperative=true`` selects the single-pass ``grid.sync()`` kernel. If the
    device cannot launch cooperatively the request returns 501 rather than
    failing opaquely -- the waive convention from ``core.errors``.
    """
    eng = get_engine()
    try:
        v = eng.reduce_sum(req.values, cooperative=req.cooperative)
    except CapabilityWaived as exc:
        raise HTTPException(501, f"waived: {exc}") from exc
    except SymoneuralError as exc:
        raise HTTPException(400, str(exc)) from exc
    return ScalarResponse(
        value=v,
        method="single_pass_cg" if req.cooperative else "two_stage_shared",
    )


# ===========================================================================
# Ten-agent platform
# ===========================================================================
# The orchestrator prompt, roster, routing engine and checkpoint custody.
# Everything below is either fully implemented (prompt, routing, sealing) or
# clearly marked as a stub (Akash client, TRON TVM verifier). See
# docs/06-agent-platform.md for the boundary.

import base64  # noqa: E402

from ..agents import (  # noqa: E402
    AGENTS,
    Aes256GcmSealer,
    DenyAllVerifier,
    FernetSealer,
    LicenceError,
    Router,
    SealError,
    Workload,
    WeightCustodian,
    build_system_prompt,
    hardware_facts,
    plan_residency,
)
from .schemas import (  # noqa: E402
    AgentInfo,
    AuditResponse,
    PromptResponse,
    RosterResponse,
    RouteRequest,
    RouteResponse,
    SealRequest,
    SealResponse,
    UnsealRequest,
)

_router: Router | None = None
_custodian: WeightCustodian | None = None


def get_router() -> Router:
    global _router
    if _router is None:
        _router = Router(get_engine().ctx)
    return _router


def get_custodian() -> WeightCustodian:
    """Custodian with an ephemeral key and the deny-by-default verifier.

    The key lives only for this process, so sealed blobs do not survive a
    restart. That is correct for a demonstration endpoint and wrong for
    production -- supply a managed key and a real LicenceVerifier.
    """
    global _custodian
    if _custodian is None:
        _custodian = WeightCustodian(
            sealer=Aes256GcmSealer(Aes256GcmSealer.generate_key()),
            verifier=DenyAllVerifier(),
        )
    return _custodian


@app.get("/v1/agents", response_model=RosterResponse)
def agents_roster() -> RosterResponse:
    """The ten agents, with the live VRAM residency plan."""
    eng = get_engine()
    return RosterResponse(
        agents=[
            AgentInfo(
                name=a.name, role=a.role, tier=a.tier.value,
                workloads=[w.value for w in a.workloads],
                vram_bytes=a.vram_bytes, gpu_local=a.gpu_local,
                interactive=a.interactive, depends_on=list(a.depends_on),
                nominal_rps=a.nominal_rps, notes=a.notes,
            )
            for a in AGENTS
        ],
        count=len(AGENTS),
        residency=plan_residency(eng.ctx.free_memory()),
    )


@app.get("/v1/prompt", response_model=PromptResponse)
def orchestrator_prompt() -> PromptResponse:
    """The orchestrator system prompt, generated from live hardware.

    Regenerated per call, so the VRAM and residency figures inside it are
    current rather than whatever was true at deploy time.
    """
    ctx = get_engine().ctx
    text = build_system_prompt(ctx)
    return PromptResponse(system_prompt=text, characters=len(text),
                          hardware_facts=hardware_facts(ctx))


@app.post("/v1/route", response_model=RouteResponse)
def route(req: RouteRequest) -> RouteResponse:
    """Choose an agent for a workload class."""
    try:
        wl = Workload(req.workload)
    except ValueError:
        raise HTTPException(
            400, f"unknown workload {req.workload!r}; expected one of "
                 f"{[w.value for w in Workload]}") from None
    d = get_router().route(wl, latency_budget_ms=req.latency_budget_ms,
                           allow_evict=req.allow_evict)
    return RouteResponse(**d.as_dict())


@app.get("/v1/route/residency")
def residency() -> dict:
    """VRAM residency plan and per-tier swap costs across PCIe."""
    return get_router().residency_report()


@app.get("/v1/route/stats")
def route_stats() -> dict:
    return get_router().stats()


@app.post("/v1/checkpoint/seal", response_model=SealResponse)
def seal_checkpoint(req: SealRequest) -> SealResponse:
    """Encrypt a checkpoint for storage at rest."""
    try:
        payload = base64.b64decode(req.payload_b64, validate=True)
    except Exception:
        raise HTTPException(400, "payload_b64 is not valid base64") from None

    if req.algorithm == "fernet":
        sealer = FernetSealer(FernetSealer.generate_key())
    elif req.algorithm == "aes256gcm":
        sealer = Aes256GcmSealer(Aes256GcmSealer.generate_key())
    else:
        raise HTTPException(400, "algorithm must be 'fernet' or 'aes256gcm'")

    import hashlib
    try:
        blob = sealer.seal(payload)
    except SealError as exc:
        raise HTTPException(500, str(exc)) from exc

    return SealResponse(
        checkpoint_id=req.checkpoint_id,
        algorithm=sealer.algorithm,
        sealed_b64=base64.b64encode(blob).decode(),
        plaintext_sha256=hashlib.sha256(payload).hexdigest(),
        warning=("Key is ephemeral to this process and is NOT returned, so this "
                 "blob cannot be unsealed later -- the endpoint demonstrates the "
                 "envelope, it is not a key-management service. Encryption "
                 "protects checkpoints at rest only: once unsealed into VRAM the "
                 "weights are readable by anyone who can attach to this process."),
    )


@app.post("/v1/checkpoint/unseal")
def unseal_checkpoint(req: UnsealRequest) -> dict:
    """Unseal a checkpoint -- only after a positive licence verification.

    Returns **403** when the licence agent denies. The default verifier denies
    everything, because a stub that granted by default would silently disable
    the control it exists to enforce.
    """
    try:
        blob = base64.b64decode(req.sealed_b64, validate=True)
    except Exception:
        raise HTTPException(400, "sealed_b64 is not valid base64") from None

    cust = get_custodian()
    try:
        plaintext = cust.unseal(req.checkpoint_id, req.subject, blob)
    except LicenceError as exc:
        raise HTTPException(403, str(exc)) from exc
    except SealError as exc:
        raise HTTPException(400, str(exc)) from exc

    import hashlib
    return {
        "checkpoint_id": req.checkpoint_id,
        "bytes": len(plaintext),
        "sha256": hashlib.sha256(plaintext).hexdigest(),
    }


@app.get("/v1/checkpoint/audit", response_model=AuditResponse)
def checkpoint_audit() -> AuditResponse:
    """Append-only unseal record. Denials are logged as carefully as grants."""
    c = get_custodian()
    return AuditResponse(records=c.audit_trail(), denials=c.denial_count)
