"""Readers of the records that describe this system, and nothing that decides anything.

`ports` and `runtimes` read the TSVs that say where each surface listens and what runs behind
it. `roster`, `route_matrix`, `appdocs`, `suites` and `fabric` answer "what exists" by reading
what is written down, so that no second source of truth is created by asking twice.
"""
