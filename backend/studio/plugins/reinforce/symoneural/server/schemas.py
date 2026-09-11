"""Pydantic request/response models for the HTTP API."""
from __future__ import annotations


from typing import Any

from pydantic import BaseModel, Field


class MLPRequest(BaseModel):
    rows: list[list[float]] = Field(
        ..., description="Batch of input rows, each of length d_in.",
        min_length=1,
    )
    batched: bool = Field(
        False,
        description="Route through the continuous batching queue instead of "
                    "executing immediately. Higher latency per request, higher "
                    "aggregate throughput under concurrency.",
    )


class AttentionRequest(BaseModel):
    rows: list[list[float]] = Field(
        ..., description="A (seq_len, d_model) block.", min_length=1
    )


class ReduceRequest(BaseModel):
    values: list[float] = Field(..., min_length=1)
    cooperative: bool = Field(
        False,
        description="Use the single-pass grid.sync() reduction (one launch) "
                    "instead of the two-stage kernel.",
    )


class TensorResponse(BaseModel):
    shape: list[int]
    data: list[list[float]]
    device_ms: float | None = None


class ScalarResponse(BaseModel):
    value: float
    method: str


class DeviceResponse(BaseModel):
    name: str
    arch: str
    compute_capability: str
    multiprocessors: int
    total_memory_gib: float
    free_memory_gib: float
    l2_mib: int
    theoretical_bandwidth_gbs: float
    driver: str
    device_count: int
    cooperative_launch: bool
    pcie_bound: bool
    overlap_profitable: bool


class StatsResponse(BaseModel):
    allocator: dict[str, Any]
    memory_pools: dict[str, Any]
    queue: dict[str, Any]
    graphs: dict[str, Any]
    kernel_compiles: int
    queue_depth: int


class HealthResponse(BaseModel):
    status: str
    device: str
    queue_running: bool


# ---------------------------------------------------------------------------
# Ten-agent platform
# ---------------------------------------------------------------------------
class AgentInfo(BaseModel):
    name: str
    role: str
    tier: str
    workloads: list[str]
    vram_bytes: int
    gpu_local: bool
    interactive: bool
    depends_on: list[str]
    nominal_rps: float
    notes: str


class RosterResponse(BaseModel):
    agents: list[AgentInfo]
    count: int
    residency: dict[str, Any]


class RouteRequest(BaseModel):
    workload: str = Field(
        ..., description="One of: classify, extract, generate, reason, "
                         "telemetry, control, verify, train.")
    latency_budget_ms: float = Field(
        500.0, gt=0,
        description="At or below 500 ms the request is treated as interactive, "
                    "which forbids eviction regardless of allow_evict.")
    allow_evict: bool = Field(
        False,
        description="Permit paying a model swap. On this host that is ~600 ms "
                    "for a 7B and ~1.2 s for a 14B across PCIe Gen 3 x8.")


class RouteResponse(BaseModel):
    agent: str
    tier: str
    reason: str
    degraded: bool
    would_evict: bool
    estimated_swap_ms: float
    considered: list[str]


class PromptResponse(BaseModel):
    system_prompt: str
    characters: int
    hardware_facts: dict[str, Any]


class SealRequest(BaseModel):
    checkpoint_id: str
    subject: str = Field(..., description="Identity the licence is checked against.")
    payload_b64: str = Field(..., description="Base64 checkpoint bytes to seal.")
    algorithm: str = Field(
        "aes256gcm",
        description="'fernet' (AES-128-CBC + HMAC-SHA256) or 'aes256gcm' "
                    "(true AES-256). Fernet is NOT AES-256 despite the common "
                    "shorthand.")


class UnsealRequest(BaseModel):
    checkpoint_id: str
    subject: str
    sealed_b64: str


class SealResponse(BaseModel):
    checkpoint_id: str
    algorithm: str
    sealed_b64: str
    plaintext_sha256: str
    warning: str


class AuditResponse(BaseModel):
    records: list[dict[str, Any]]
    denials: int
