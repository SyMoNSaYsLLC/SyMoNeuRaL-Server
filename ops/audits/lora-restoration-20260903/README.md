# `lora-restoration-20260903/` — the adapter payloads, and their hashes

What was restored, and `SHA256SUMS` proving which bytes. Adapters are training **output** and
live outside `models/` for that reason — they are not fetched, they are produced, and losing
one means re-running the training rather than re-downloading it.

Point-in-time. Whether an adapter currently **applies** is a different question, answered by
`adapter_applies()` at spawn and by `GET /lora-adapters` on the engine — which returns `[]`
today, because the adapter was trained against the 7B and the active model is the 30B-A3B.
