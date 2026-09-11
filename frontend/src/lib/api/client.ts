import { API_ROOT } from "@/lib/config";

/**
 * The one place this project talks to FastAPI.
 *
 * Everything about the existing contract is preserved rather than re-invented: same origin,
 * cookie-based sessions, JSON bodies, and FastAPI's `{"detail": "..."}` error shape. There is
 * no client-side auth state to get out of step with the server -- the cookie is HttpOnly, so
 * this code cannot read it and must not try. Whether a caller is signed in is answered by
 * asking the API, never by inspecting a token.
 */

/** FastAPI's error envelope. `detail` is a string on every route this project calls. */
type ErrorEnvelope = { detail?: unknown };

export class ApiError extends Error {
  readonly status: number;
  /**
   * Seconds, from the `Retry-After` header. Only ever set on a 429 from the DispatchOS login
   * route, which is the throttle added in `fix(dispatchos): complete and secure the v1
   * workflow`. Surfacing it is the difference between "wrong password" and "wait 40 seconds",
   * and a UI that conflates the two teaches people to retype a password that was correct.
   */
  readonly retryAfterSeconds: number | null;

  constructor(status: number, message: string, retryAfterSeconds: number | null = null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.retryAfterSeconds = retryAfterSeconds;
  }

  /** The surface is switched off on this box (`SYMONEURAL_DISPATCHOS_ENABLED` unset). */
  get isDisabled(): boolean {
    return this.status === 503;
  }

  get isUnauthenticated(): boolean {
    return this.status === 401;
  }

  get isForbidden(): boolean {
    return this.status === 403;
  }

  get isThrottled(): boolean {
    return this.status === 429;
  }
}

function messageFrom(body: unknown, fallback: string): string {
  if (body && typeof body === "object") {
    const detail = (body as ErrorEnvelope).detail;
    if (typeof detail === "string" && detail.trim() !== "") return detail;
  }
  return fallback;
}

function retryAfterFrom(response: Response): number | null {
  const raw = response.headers.get("retry-after");
  if (raw === null) return null;
  const parsed = Number.parseInt(raw, 10);
  return Number.isFinite(parsed) && parsed >= 0 ? parsed : null;
}

type RequestOptions = {
  readonly method?: "GET" | "POST" | "PUT";
  /** Serialised as JSON. Omitted entirely for GET, which is what FastAPI expects. */
  readonly body?: unknown;
  readonly signal?: AbortSignal;
};

/**
 * `T` is asserted, not validated. That is a deliberate boundary and it is worth being honest
 * about: these types are transcribed from the FastAPI route signatures in
 * `backend/apps/dispatchos/routes.py`, and a runtime validator here would be a second
 * schema to keep in step with the first. The types describe the contract; the contract is
 * enforced on the server, where it has to be anyway, since the API is reachable by anything
 * holding a session cookie.
 */
export async function apiFetch<T>(path: string, options: RequestOptions = {}): Promise<T> {
  const { method = "GET", body, signal } = options;

  const headers: Record<string, string> = { Accept: "application/json" };
  if (body !== undefined) headers["Content-Type"] = "application/json";

  let response: Response;
  try {
    response = await fetch(`${API_ROOT}${path}`, {
      method,
      headers,
      // The session cookie is the whole auth model. Same-origin rather than `include`:
      // this client never talks to another origin, and saying so keeps it that way.
      credentials: "same-origin",
      // Dispatch data is a named customer's bookings. It must not be reusable from a cache,
      // and the server says so too -- the router carries a no-store dependency. Both halves,
      // because a cached board is the failure nobody sees.
      cache: "no-store",
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
      ...(signal ? { signal } : {}),
    });
  } catch {
    // A network failure is not a 500 and must not be reported as one: the API may simply not
    // be running, which is the normal state on a developer's box. The underlying TypeError
    // says only "Failed to fetch" and is not worth carrying.
    throw new ApiError(0, "the API did not answer; it may not be running on this box", null);
  }

  if (response.status === 204) return undefined as T;

  const text = await response.text();
  let parsed: unknown = null;
  if (text !== "") {
    try {
      parsed = JSON.parse(text) as unknown;
    } catch {
      parsed = null;
    }
  }

  if (!response.ok) {
    throw new ApiError(
      response.status,
      messageFrom(parsed, `${method} ${path} failed with ${response.status}`),
      retryAfterFrom(response),
    );
  }

  return parsed as T;
}
