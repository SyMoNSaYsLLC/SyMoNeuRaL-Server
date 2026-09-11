/* One HTTP client for every page on this site.
 *
 * Before this file, each page rolled its own fetch: different error handling, different
 * timeouts, and several that read a token out of sessionStorage and put it in a header.
 *
 * ## There are no tokens
 *
 * Owner decision, 2026-09-11: "no api keys period -- everything is straight post get fetch".
 * Every gate was removed from the server, so a credential header here would be a lie about
 * how the system works. This client sends Content-Type and nothing else, and the test suite
 * asserts that.
 *
 * ## Why a client at all, if it is just fetch
 *
 * Four things every page was getting wrong in its own way:
 *
 *   1. An HTTP error is not an exception. `fetch` resolves a 500, so `await` succeeds and the
 *      page renders a JSON error body as if it were data. `request()` throws on !ok.
 *   2. No timeout. A hung GPU request left a spinner turning forever with nothing in the
 *      console. Every call here has an AbortController deadline.
 *   3. The body of a failure is the useful part. FastAPI puts the reason in `detail`, and a
 *      page that shows "request failed" has thrown away the sentence that explains it.
 *   4. Streaming chat is SSE, not JSON, and three pages had three near-identical parsers.
 *
 * ## The stream contract
 *
 * `POST /api/chat` returns `text/event-stream` with `data: {"delta": "..."}` per token. The
 * FINAL chunk carries the engine's own `timings` -- tokens in and out, tok/s both ways,
 * prompt-cache hits -- measured while it did the work. `stream()` hands those to `onDone`
 * rather than discarding them, which is what the dashboard reads.
 */
'use strict';

const DEFAULT_TIMEOUT_MS = 120000;      // GPU work is slow; a 30 s default would lie
const STREAM_TIMEOUT_MS = 600000;       // a long generation is minutes, not seconds

/** An HTTP failure that kept the server's explanation. */
export class ApiError extends Error {
  constructor(status, detail, path) {
    super(detail || `${path} failed with ${status}`);
    this.name = 'ApiError';
    this.status = status;
    this.detail = detail;
    this.path = path;
  }
}

async function request(path, { method = 'GET', body, timeout = DEFAULT_TIMEOUT_MS } = {}) {
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), timeout);
  let res;
  try {
    res = await fetch(path, {
      method,
      // No Authorization, no X-Symoneural-Token. See the header comment.
      headers: body === undefined ? {} : { 'Content-Type': 'application/json' },
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: ctl.signal,
    });
  } catch (err) {
    clearTimeout(timer);
    if (err.name === 'AbortError') {
      throw new ApiError(0, `no answer from ${path} within ${Math.round(timeout / 1000)}s`, path);
    }
    throw new ApiError(0, `cannot reach ${path} (${err.message})`, path);
  }
  clearTimeout(timer);

  if (!res.ok) {
    // FastAPI puts the reason in `detail`. Losing it turns a fixable problem into "failed".
    let detail = '';
    try {
      const text = await res.text();
      try { detail = JSON.parse(text).detail || text; } catch { detail = text; }
    } catch { /* body already consumed or empty */ }
    throw new ApiError(res.status, String(detail).slice(0, 600), path);
  }
  if (res.status === 204) return null;
  const ct = res.headers.get('content-type') || '';
  return ct.includes('application/json') ? res.json() : res.text();
}

export const get = (path, opts) => request(path, { ...opts, method: 'GET' });
export const post = (path, body, opts) => request(path, { ...opts, method: 'POST', body });
export const del = (path, opts) => request(path, { ...opts, method: 'DELETE' });

/**
 * Stream `POST /api/chat`, token by token.
 *
 * `onDelta(text)` fires per token. `onDone({timings})` fires once at the end with whatever
 * the engine measured. Returns a function that cancels the stream.
 */
export function stream(path, body, { onDelta, onDone, onError,
                                     timeout = STREAM_TIMEOUT_MS } = {}) {
  const ctl = new AbortController();
  const timer = setTimeout(() => ctl.abort(), timeout);

  (async () => {
    try {
      const res = await fetch(path, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
        signal: ctl.signal,
      });
      if (!res.ok || !res.body) {
        throw new ApiError(res.status, await res.text().catch(() => ''), path);
      }
      const reader = res.body.getReader();
      const dec = new TextDecoder();
      let buf = '';
      let timings = null;
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        buf += dec.decode(value, { stream: true });
        // SSE frames are newline-delimited. Keep the trailing partial in the buffer --
        // a chunk boundary lands mid-line often enough that not doing this drops tokens.
        const lines = buf.split('\n');
        buf = lines.pop() ?? '';
        for (const line of lines) {
          if (!line.startsWith('data:')) continue;
          const payload = line.slice(5).trim();
          if (!payload || payload === '[DONE]') continue;
          let obj;
          try { obj = JSON.parse(payload); } catch { continue; }
          if (obj.timings) timings = obj.timings;
          const piece = obj.delta ?? obj.choices?.[0]?.delta?.content;
          if (piece) onDelta?.(piece);
        }
      }
      clearTimeout(timer);
      onDone?.({ timings });
    } catch (err) {
      clearTimeout(timer);
      if (err.name === 'AbortError') return;          // cancelled by the caller, not a fault
      onError?.(err instanceof ApiError ? err : new ApiError(0, err.message, path));
    }
  })();

  return () => { clearTimeout(timer); ctl.abort(); };
}

/* ---- the surfaces, named, so a page does not retype a path ------------------------- */

export const api = {
  status:    () => get('/api/status'),
  metrics:   () => get('/api/metrics/live'),
  chat:      (body, handlers) => stream('/api/chat', body, handlers),
  image:     (body) => post('/api/image', body, { timeout: 600000 }),
  ravencalc: (body) => post('/api/ravencalc', body, { timeout: 30000 }),
  remix:     (body) => post('/api/remix', body, { timeout: 600000 }),
};

export default api;
