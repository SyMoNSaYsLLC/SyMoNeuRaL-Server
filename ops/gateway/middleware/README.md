# `ops/gateway/middleware/` — gateway middleware

`limiter.go`. The rate limit **in front of** the API, distinct from the per-address budgets
FastAPI applies to each surface.

Two limits, on purpose, at different layers: this one protects the box from a flood before it
reaches anything that takes the GPU lease; the API's protects each surface from one address
monopolising it. Collapsing them into one would mean either the flood reaches the lease or a
legitimate burst is refused at the door.

`X-Forwarded-For` is load-bearing here and the handling is Caddy's default deliberately.
