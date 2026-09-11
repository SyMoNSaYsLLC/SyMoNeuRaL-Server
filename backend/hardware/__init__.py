"""The card and the host: what they are, what they are doing, and what they will allow.

`gpu` and `telemetry` read the GPU. `hostmetrics` and `modelmetrics` read the CPU, the memory
and the model's own per-request timings. `overclock` computes power and quota budgets and
never applies them. `metricsroutes` is the one router that serves all of it.

These were seventeen loose files directly under `apps/` alongside eighty-two test files.
"""
