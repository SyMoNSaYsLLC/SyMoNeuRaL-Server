# backend/status/

The **rack** — one row per unit, with what it is, what state it is in, and where its page is.
`GET /api/status` for clients that cannot hold a socket, and the same data pushed over
`/api/ws` for those that can.

Prefer the socket. It stays quiet until something actually changes: one handshake, one
baseline snapshot, then patches of a few dozen bytes. The poller supports `If-None-Match`, so
an unchanged rack costs a bare `304` with no body.

**A rack row is a reading, never a claim.** `lib/build.py` asks each component for its state
rather than holding a table, so a row cannot say `ready` about something that is not. Rows
for delegated surfaces are polled over HTTP and go stale rather than lying — `DELEGATE_STALE_S`
is how long before a row admits it does not know.

There is deliberately **no `voice` row** yet: `voice.status()` is written and correct, but its
href would point at a page that does not exist, and a dead link on the front page is worse
than a missing row. Add the row in the same commit as the page.

<!-- generated: do not edit below -->

## Operations — 1

|  | path | what it does |
|---|---|---|
| GET | `/api/status` | Rack state over plain HTTP, for clients that cannot hold a socket. |

## Library — no routes, no side effects on import

| file |  |
|---|---|
| `build.py` | Lifted from server.py, 2026-09-11. |

<!-- end generated -->
