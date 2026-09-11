# `frontend/app/src/lib/auth/` — who is asking

`session.ts`. Two functions and one rule: **`getUser()` returns null, `requireUser()`
redirects.** A caller that forgets the null gets a type error rather than a rendered page
belonging to somebody else.

## Identity comes from the proxy, not the browser

The front door — Caddy → symon-gateway → FastAPI — resolves the session cookie and sets
`x-symoneural-user-*` headers on the upstream request. A page reads those. It never parses a
cookie, never validates a signature, and never sees the secret that signs one.

One place can be wrong, rather than two. A page that verified its own cookie would be a
second implementation of "is this session valid", and that drift shows up as a page you can
reach one way and not the other.

**The headers are trustworthy only because nothing but the proxy can set them.** The gateway
strips them inbound before adding its own. Served without that proxy, every function here
returns null and every guarded page redirects — the correct failure direction, and the reason
there is no fallback.

## No tokens

No API key, no bearer token, and there will not be. The session cookie is a different thing:
nobody types it, no caller presents it to be let in, and it is what makes a session
unforgeable. Removing it would not open a door — it would make every session forgeable by
anyone who can write a cookie.

## The `return_to` defence

`safeReturnPath` handles three cases and the middle one is the one that gets missed:

```
https://evil.example/   absolute. Rejected -- must start with "/"
//evil.example/         protocol-relative. A browser treats this as ABSOLUTE, and a
                        leading-slash check alone PASSES it
/signin?return_to=...   reserved auth path. Not a hole, an infinite loop
```

Parsed against a fixed base rather than pattern-matched, because URL parsing is where
backslashes, encoded slashes and userinfo tricks are already solved.
