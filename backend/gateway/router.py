"""The Gateway's HTTP surface: one read-only endpoint that serves the cache.

    import gateway
    app.include_router(gateway.router, prefix="/api/gateway")   # before the static mount

## Two properties, both deliberate

**It never triggers a fetch.** It returns whatever the background refresher last measured, or
`null`. An endpoint that probed on demand would be an unauthenticated outbound-request
trigger on a public-facing box -- anyone able to reach `/api/gateway/state` could make this
machine call a TRON node as fast as they could type. The refresher owns the rate.

**It carries no token, and needs none.** Unlike `asicminer`, which controls hardware, this
returns only what `/api/status` already publishes plus the reading behind it: a public
contract address, a public block number, and whether a public contract exists. There is no
key material anywhere in this package to leak. It answers **503 while the surface is
switched off**, so a box that has not been configured says so rather than half-answering.
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException

router = APIRouter()


@router.get("/state", summary="What the Gateway last read from the chain")
def state() -> dict:
    """The configuration, the last measured reading, and the rack unit built from them.

    The imports are function-local on purpose: `__init__.py` imports this module while it is
    still executing, so these names do not exist yet at import time. By the time a request
    arrives the package is fully initialised. It is the same reason `api.py` includes this
    router before the static mount -- ordering here is load-bearing, not stylistic.
    """
    from . import CACHE, ChainCache, NODES, configured, contract, enabled, network, status

    if not enabled():
        raise HTTPException(
            status_code=503,
            detail="gateway surface is off — set SYMONEURAL_GATEWAY_ENABLED=1, SYMONEURAL_GATEWAY_NETWORK "
                   "and SYMONEURAL_GATEWAY_CONTRACT, then restart the service",
        )
    ok, why = configured()
    net = network()
    reading = CACHE.get()
    return {
        "enabled": True,
        "configured": ok,
        "problem": why or None,
        "network": net or None,
        "network_name": NODES[net][0] if net in NODES else None,
        "endpoint": NODES[net][1] if net in NODES else None,
        "contract": contract() or None,
        # The reading is exactly what `chain.probe` produced -- including its `error` when it
        # failed. A surface that hides its failures is the one this site argues against.
        "reading": reading,
        "reading_ttl_s": ChainCache.TTL,
        "stale": CACHE.stale(),
        "unit": status(reading),
    }
