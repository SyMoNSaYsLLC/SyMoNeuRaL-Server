/**
 * The DispatchOS wire contract, transcribed from the backend rather than guessed.
 *
 * Sources, and they are the things to re-read if any of this drifts:
 *   backend/apps/dispatchos/routes.py    the routes and their response envelopes
 *   backend/apps/dispatchos/store.py     _SCHEMA, get_booking(), list_bookings()
 *   backend/apps/dispatchos/quotes.py    quote() and its "no figure" result
 */

/** `store.STATES`, in lifecycle order. `cancelled` is a terminal exit, not a step. */
export const BOOKING_STATES = [
  "requested",
  "quoted",
  "confirmed",
  "dispatched",
  "completed",
  "reviewed",
  "cancelled",
] as const;

export type BookingState = (typeof BOOKING_STATES)[number];

/** The six panels of the customer preview's "booking loop", in the order it presents them. */
export const LIFECYCLE_STEPS = [
  "requested",
  "quoted",
  "confirmed",
  "dispatched",
  "completed",
  "reviewed",
] as const satisfies readonly BookingState[];

export type Role = "operator" | "customer";

export type User = {
  readonly id: number;
  readonly username: string;
  readonly role: Role;
  readonly label: string;
};

export type Driver = {
  readonly id: number;
  readonly name: string;
  readonly vehicle: string;
  readonly active: number;
};

/** One line of a quote breakdown. `minor` is minor currency units -- pence, cents. */
export type QuoteLine = {
  readonly label: string;
  readonly minor: number;
  readonly note?: string;
};

/**
 * `quotes.quote()`'s return value.
 *
 * `estimate` is null and `display` is the no-figure placeholder whenever the operator's rate
 * rules are unconfigured, which is TODAY'S NORMAL STATE and not an error. The customer
 * preview says in writing that it "carries no pricing of any kind" and that rate rules are
 * agreed in written scope first. A UI that renders a placeholder number here would be
 * inventing the one thing that document promises is absent.
 */
export type Quote = {
  readonly route: string;
  readonly vehicle: string;
  readonly basis: string;
  readonly currency: string;
  readonly lines: readonly QuoteLine[];
  readonly estimate: number | null;
  readonly display: string;
  readonly operator_confirms: boolean;
};

/** An append-only record-trail row. Nothing in the store updates or deletes one. */
export type BookingEvent = {
  readonly at: number;
  readonly actor: string;
  readonly kind: string;
  readonly detail: string;
};

export type MessageKind = "reminder" | "review_request" | "confirmation";

/**
 * A composed message. `sent_at` is ALWAYS null: there is no sender in the package and no code
 * path that sets it. Live routing requires approved email configuration. Render this as
 * composed-not-sent or the surface is claiming something it did not do.
 */
export type ComposedMessage = {
  readonly id: number;
  readonly at: number;
  readonly kind: MessageKind;
  readonly to_whom: string;
  readonly body: string;
  readonly sent_at: number | null;
};

/** A booking as `list_bookings()` returns it -- no events, messages or resolved driver. */
export type BookingSummary = {
  readonly id: number;
  readonly ref: string;
  readonly state: BookingState;
  readonly owner_id: number | null;
  readonly rider: string;
  readonly contact: string;
  readonly pickup: string;
  readonly dropoff: string;
  readonly when_text: string;
  readonly passengers: number;
  readonly luggage: number;
  readonly notes: string;
  readonly driver_id: number | null;
  readonly created_at: number;
  readonly updated_at: number;
  readonly quote: Quote | null;
};

/** A booking as `get_booking()` returns it -- the summary plus its trail. */
export type BookingDetail = BookingSummary & {
  readonly events: readonly BookingEvent[];
  readonly messages: readonly ComposedMessage[];
  readonly driver: { readonly name: string; readonly vehicle: string } | null;
};

// ---------------------------------------------------------------- response envelopes

export type StatusResponse = {
  readonly enabled: boolean;
  readonly assistant_connected: boolean;
  readonly rates_configured: boolean;
  readonly states: readonly BookingState[];
};

export type SessionResponse = { readonly user: User };

/**
 * `counts` and `drivers` are empty for a customer -- the route omits them by role rather than
 * hiding them in the UI. Typed as possibly-empty rather than optional so a customer view
 * cannot accidentally read an operator field.
 */
export type BoardResponse = {
  readonly user: User;
  readonly bookings: readonly BookingSummary[];
  readonly counts: Readonly<Record<string, number>>;
  readonly drivers: readonly Driver[];
  readonly rates_configured: boolean;
};

export type BookingResponse = { readonly booking: BookingDetail };
export type DriverResponse = { readonly driver: Driver };
export type DriversResponse = { readonly drivers: readonly Driver[] };

export type MessageResponse = {
  readonly message: ComposedMessage;
  /** The API repeats the not-sent fact in the payload so a UI cannot render "sent". */
  readonly delivery: string;
};

/** What an operator may fill in when taking a booking; a customer sends the same shape. */
export type IntakeDraft = {
  rider: string;
  contact: string;
  pickup: string;
  dropoff: string;
  when_text: string;
  passengers: number;
  luggage: number;
  notes: string;
};
