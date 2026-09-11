import type { NextConfig } from "next";

/**
 * The one thing in this file that can break the live API, so it is the thing that is
 * explained.
 *
 * FastAPI is the authoritative backend and owns every `/api/*` path. Next.js must never
 * answer one. Two rules keep that true and they have to hold together:
 *
 *   1. There is no `src/app/api/` directory in this project, and there must never be one.
 *      An App Router route handler there would shadow the rewrite below silently -- Next
 *      matches its own filesystem routes before it consults `rewrites()`.
 *   2. `/api/:path*` is rewritten to the FastAPI upstream, verbatim. No path rewriting, no
 *      prefix stripping: `/api/dispatchos/board` arrives at FastAPI as `/api/dispatchos/board`.
 *
 * `frontend/tests/route-ownership.test.mjs` asserts both -- the absence of the directory as
 * well as the passthrough -- because rule 1 is the kind of thing a later feature adds without
 * noticing what it took away.
 *
 * ## SYMONEURAL_API_UPSTREAM IS READ AT BUILD TIME, NOT AT RUN TIME
 *
 * Measured, because an earlier version of this comment claimed otherwise and was wrong.
 * `next build` evaluates `rewrites()` and writes the resolved destination into
 * `.next/routes-manifest.json`; `next start` serves that manifest and does NOT re-resolve the
 * variable. Setting it before `next start` has no effect at all.
 *
 * The cost of believing otherwise is not theoretical: the first draft of the slice test set
 * this variable when starting the server and pointed its assertions through the proxy, so
 * every /api call went to the DEFAULT destination -- the LIVE API on :8800 -- and the suite
 * authenticated fixture credentials against production. The test now exercises the API on the
 * fixture's own origin and never sends a credential through this rewrite.
 *
 * So: this rewrite is a DEVELOPMENT convenience. In production `ops/Caddyfile` is the front
 * door and routes /api/* to the gateway on :8000, which forwards to FastAPI on :8800; Next
 * never sees an /api request there. Relying on this rewrite in production would pin the API
 * host to whatever machine happened to run `next build`.
 *
 * The default is the port `ops/Caddyfile` and `symoneural-api.service` already use, so an
 * unset variable behaves like this box.
 */
const API_UPSTREAM = process.env.SYMONEURAL_API_UPSTREAM ?? "http://127.0.0.1:8800";

const nextConfig: NextConfig = {
  reactStrictMode: true,

  // The header names the framework and version to every visitor and buys nothing.
  poweredByHeader: false,

  async rewrites() {
    return [{ source: "/api/:path*", destination: `${API_UPSTREAM}/api/:path*` }];
  },
};

export default nextConfig;
