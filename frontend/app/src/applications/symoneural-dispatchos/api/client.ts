import { apiFetch } from "@/lib/api/client";
import type {
  BoardResponse,
  BookingResponse,
  BookingState,
  DriverResponse,
  DriversResponse,
  IntakeDraft,
  MessageKind,
  MessageResponse,
  SessionResponse,
  StatusResponse,
} from "../types";

/**
 * One typed function per DispatchOS route, and no route that the backend does not have.
 *
 * The tier rules are enforced server-side in `routes.py` (`_operator()` / `_signed_in()`), so
 * nothing here tries to pre-empt them. A customer calling an operator route gets a 403 from
 * FastAPI, which is the behaviour the smoke record proved; the UI hides those controls as a
 * courtesy, not as the boundary.
 */

const BASE = "/dispatchos";

export function fetchStatus(signal?: AbortSignal): Promise<StatusResponse> {
  return apiFetch<StatusResponse>(`${BASE}/status`, { ...(signal ? { signal } : {}) });
}

export function fetchMe(signal?: AbortSignal): Promise<SessionResponse> {
  return apiFetch<SessionResponse>(`${BASE}/me`, { ...(signal ? { signal } : {}) });
}

export function signIn(username: string, password: string): Promise<SessionResponse> {
  return apiFetch<SessionResponse>(`${BASE}/login`, {
    method: "POST",
    body: { username, password },
  });
}

export function signOut(): Promise<void> {
  return apiFetch<void>(`${BASE}/logout`, { method: "POST" });
}

export function fetchBoard(signal?: AbortSignal): Promise<BoardResponse> {
  return apiFetch<BoardResponse>(`${BASE}/board`, { ...(signal ? { signal } : {}) });
}

export function fetchBooking(id: number, signal?: AbortSignal): Promise<BookingResponse> {
  return apiFetch<BookingResponse>(`${BASE}/bookings/${id}`, { ...(signal ? { signal } : {}) });
}

/** Intake. An operator's booking is unowned; a customer's is owned by them -- server-side. */
export function createBooking(draft: IntakeDraft): Promise<BookingResponse> {
  return apiFetch<BookingResponse>(`${BASE}/bookings`, { method: "POST", body: draft });
}

/**
 * `distance_km` is optional and is NOT estimated when absent. The quote engine says so in the
 * breakdown rather than inventing a number, and this signature keeps that possible.
 */
export function quoteBooking(id: number, distanceKm: number | null): Promise<BookingResponse> {
  return apiFetch<BookingResponse>(`${BASE}/bookings/${id}/quote`, {
    method: "POST",
    body: { distance_km: distanceKm },
  });
}

/**
 * One step along the lifecycle. `driver_id` is how a driver is assigned, and it is carried on
 * the same call that moves the booking to `dispatched` -- assignment and dispatch are one
 * operator action in this backend, not two.
 */
export function advanceBooking(
  id: number,
  to: BookingState,
  options: { driverId?: number | null; detail?: string } = {},
): Promise<BookingResponse> {
  const { driverId = null, detail = "" } = options;
  return apiFetch<BookingResponse>(`${BASE}/bookings/${id}/advance`, {
    method: "POST",
    body: { to, driver_id: driverId, detail },
  });
}

/** Composes and stores. Never sends -- see `MessageResponse.delivery`. */
export function composeMessage(id: number, kind: MessageKind): Promise<MessageResponse> {
  return apiFetch<MessageResponse>(`${BASE}/bookings/${id}/message`, {
    method: "POST",
    body: { kind },
  });
}

export function fetchDrivers(signal?: AbortSignal): Promise<DriversResponse> {
  return apiFetch<DriversResponse>(`${BASE}/drivers`, { ...(signal ? { signal } : {}) });
}

export function addDriver(name: string, vehicle: string): Promise<DriverResponse> {
  return apiFetch<DriverResponse>(`${BASE}/drivers`, {
    method: "POST",
    body: { name, vehicle },
  });
}
