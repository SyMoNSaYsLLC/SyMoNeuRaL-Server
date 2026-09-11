"use client";

/**
 * The route's error boundary. It exists because this workspace is the only surface in the
 * project that renders live customer data, and an unhandled render error would otherwise
 * replace a dispatch board with a blank page and no way back.
 *
 * There is deliberately NO `loading.tsx` beside it. The page shell renders instantly and the
 * workspace carries its own in-component loading state, so a route-level loading file would
 * never be seen -- a file added only to make the folder look complete.
 *
 * `error.message` is not printed. A server-side stack can name internal paths, and this page
 * is behind a customer-facing door.
 */
export default function DispatchOsError({ reset }: { readonly reset: () => void }) {
  return (
    <main style={{ padding: "24px" }}>
      <h1 style={{ fontSize: "var(--t3)", margin: "0 0 8px" }}>DispatchOS could not be shown</h1>
      <p style={{ fontSize: "var(--t5)", color: "var(--dim)", margin: "0 0 16px" }}>
        Something failed while rendering this page. Your session and the board are unaffected.
      </p>
      <button
        type="button"
        onClick={reset}
        style={{
          minHeight: "var(--ctl)",
          padding: "0 var(--s4)",
          border: "1px solid var(--line)",
          borderRadius: "var(--r1)",
          background: "var(--e2)",
          color: "var(--fg)",
          cursor: "pointer",
        }}
      >
        Try again
      </button>
    </main>
  );
}
