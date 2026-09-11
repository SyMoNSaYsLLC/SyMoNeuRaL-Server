# backend/chat/

The language surface. `POST /api/chat` takes the **GPU lease**, spawns `symoneural-llm` if it
is not already resident, and streams the answer back token by token as Server-Sent Events.

**The lease is taken before the engine is checked**, so a cold request holds the card for the
whole load. That is deliberate: the alternative is two requests both deciding the engine is
absent and both spawning one, onto a card that fits exactly one.

Conversations live in the **browser**, not here. There is no history endpoint and no
conversation id on the server; the transcript is replayed on every turn so the model can
follow along, and nothing is kept. That is a promise, not a gap.

Bounds are enforced here and never trusted from the client. `temperature` and `max_tokens`
are **clamped** rather than rejected — an out-of-range value is a caller bug, and refusing the
whole request over one is worse than correcting it. An oversized prompt **hard-fails**,
because answering a truncated question is worse than refusing it.

`/api/ws` is the same surface over a socket, rate-limited identically. Holding a socket open
is not a way around the caps.

**What will bite you:** `ctx.chat_deltas()` posts to the engine's own
`/v1/chat/completions`, so the hop to the engine is OpenAI-shaped but this surface is not.
See `../core/docs/MODEL-CALL-TRACE-20260911.md` for the measured chain, and for why the
persona adapter does not apply to the model currently loaded.

<!-- generated: do not edit below -->

## Operations — 2

|  | path | what it does |
|---|---|---|
| POST | `/api/chat` | Ask the local model. Streams Server-Sent Events as the card produces tok |
| WS | `/api/ws` |  |

## Documents

- [`README.md`](docs/README.md)
- [`chat-spec.md`](docs/chat-spec.md)
- [`symoneural-chat-scope.md`](docs/symoneural-chat-scope.md)

<!-- end generated -->
