# `backend/remix/symoneural_dj/` — the Remix engine

What `/api/remix` drives. A **client of chat**, not its own GPU tenant: it asks the chat
surface for the words and never takes the lease itself.

```
connectors/   one per music service. Spotify, YouTube Music, local
symon_client.py  how this package talks to the chat surface
config.py     DJ_TOKEN and DJ_TOKEN_PATH live here -- see below
jobs.py       long-running work, off the request path
```

## `DJ_TOKEN` is not a gate

It is a **Spotify OAuth credential**: a secret this box presents *to* somebody else's
service. The no-tokens decision was about gates a caller presents *to this box*, and removing
this one would not simplify anything — it would break the integration.

`tests/structure/test_no_tokens.py` carries it in an explicit allowlist so the distinction is
a decision on the record rather than a regex that happened not to match.

## Never let a connector reach the card

A connector fetches metadata and audio. If one starts wanting the GPU it has stopped being a
connector, and it goes through the lease like everything else.
