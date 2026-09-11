"""HTTP API tests. Uses FastAPI's TestClient, which runs the real lifespan."""

from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from symoneural.server.app import app  # noqa: E402


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
    assert r.json()["queue_running"] is True


def test_device_reports_real_hardware(client):
    d = client.get("/device").json()
    assert d["multiprocessors"] > 0
    assert d["total_memory_gib"] > 0
    assert d["arch"].startswith("sm_")


def test_mlp_direct(client):
    d_in = 256
    r = client.post("/v1/mlp", json={"rows": [[0.01] * d_in, [0.02] * d_in]})
    assert r.status_code == 200
    body = r.json()
    assert body["shape"] == [2, 256]
    assert np.isfinite(body["data"]).all()


def test_mlp_batched_path(client):
    r = client.post("/v1/mlp", json={"rows": [[0.01] * 256], "batched": True})
    assert r.status_code == 200
    assert r.json()["shape"] == [1, 256]


def test_attention(client):
    r = client.post("/v1/attention", json={"rows": [[0.01] * 128] * 64})
    assert r.status_code == 200
    assert r.json()["shape"] == [64, 128]


def test_reduce_two_stage(client):
    r = client.post("/v1/reduce", json={"values": [1.0] * 1024})
    assert r.status_code == 200
    assert r.json()["value"] == pytest.approx(1024.0)
    assert r.json()["method"] == "two_stage_shared"


def test_reduce_cooperative_or_waived(client):
    """501 is a correct answer here -- the waive convention, over HTTP."""
    r = client.post("/v1/reduce", json={"values": [1.0] * 4096,
                                        "cooperative": True})
    assert r.status_code in (200, 501)
    if r.status_code == 200:
        assert r.json()["value"] == pytest.approx(4096.0)
        assert r.json()["method"] == "single_pass_cg"
    else:
        assert "waived" in r.json()["detail"]


def test_bad_shape_is_400_not_500(client):
    r = client.post("/v1/mlp", json={"rows": [[0.1, 0.2, 0.3]]})
    assert r.status_code == 400


def test_empty_rows_rejected_by_schema(client):
    assert client.post("/v1/mlp", json={"rows": []}).status_code == 422


def test_stats_after_traffic(client):
    client.post("/v1/mlp", json={"rows": [[0.01] * 256]})
    s = client.get("/stats").json()
    assert s["kernel_compiles"] >= 1
    assert "allocator" in s and "queue" in s
