# frontend/docs/ — route ownership and the frontend smokes

```
FRONTEND-ROUTE-OWNERSHIP.md   which of the two frontends owns which path
SMOKE-FRONTEND.md             what was opened, and what it did
SMOKE-ACCESSIBILITY.md        keyboard, contrast, focus order
SMOKE-maintenance-banner.md   the banner, observed rather than asserted
```

## The rule the ownership document records

**FastAPI owns every `/api/*` path.** Neither frontend answers one — the Next.js app proxies
them in development and never in production, where Caddy is the front door.

Two things keep that true and they have to hold together: there is no `src/app/api/`
directory and there must never be one, and `/api/:path*` passes through verbatim. Next
matches its own filesystem routes **before** it consults `rewrites()`, so a route handler
there would shadow the proxy silently.

## Why the smokes are here and not in tests/

A smoke record is written by **opening the page**. It says what was observed, on what date,
on what revision. A test can read markup; it cannot tell you the page rendered, and a client
whose eighteen checks were green shipped dead on arrival once already.

A smoke file containing a failure is worth more than no file, and far more than a passing one
written from the source.
