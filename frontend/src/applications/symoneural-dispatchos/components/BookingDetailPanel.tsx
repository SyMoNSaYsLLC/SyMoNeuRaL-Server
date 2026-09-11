"use client";

import { useState } from "react";
import { Panel } from "@/components/ui/Panel";
import { ApiError } from "@/lib/api/client";
import { advanceBooking, composeMessage, quoteBooking } from "../api/client";
import type { BookingDetail, BookingState, Driver, MessageKind, Role } from "../types";
import { StateBadge } from "./StateBadge";
import styles from "../styles/dispatchos.module.css";

/**
 * One booking, and every operator action the v1 workflow has.
 *
 * `NEXT` is transcribed from `store.NEXT` so the UI offers exactly the transitions the store
 * will accept. It is a courtesy, not the boundary: `advance()` re-checks, because the API is
 * reachable by anything holding a session cookie and an out-of-order transition corrupts the
 * record trail rather than erroring.
 */
const NEXT: Readonly<Record<BookingState, readonly BookingState[]>> = {
  requested: ["quoted", "cancelled"],
  quoted: ["confirmed", "cancelled"],
  confirmed: ["dispatched", "cancelled"],
  dispatched: ["completed", "cancelled"],
  completed: ["reviewed"],
  reviewed: [],
  cancelled: [],
};

function stamp(seconds: number): string {
  return new Date(seconds * 1000).toISOString().replace("T", " ").slice(0, 19);
}

export type BookingDetailPanelProps = {
  readonly booking: BookingDetail;
  readonly role: Role;
  readonly drivers: readonly Driver[];
  readonly onChanged: () => void | Promise<void>;
};

export function BookingDetailPanel({
  booking,
  role,
  drivers,
  onChanged,
}: BookingDetailPanelProps) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [distanceKm, setDistanceKm] = useState("");
  const [driverId, setDriverId] = useState("");
  const isOperator = role === "operator";
  const allowed = NEXT[booking.state];

  async function run(action: () => Promise<unknown>) {
    setBusy(true);
    setError(null);
    try {
      await action();
      await onChanged();
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "that action did not complete");
    } finally {
      setBusy(false);
    }
  }

  function advanceTo(to: BookingState) {
    // Driver assignment rides on the move to `dispatched`: in this backend assigning and
    // dispatching are one operator action, and `advance()` takes the driver on that call.
    const chosen = to === "dispatched" && driverId !== "" ? Number(driverId) : null;
    return run(() => advanceBooking(booking.id, to, { driverId: chosen }));
  }

  function compose(kind: MessageKind) {
    return run(() => composeMessage(booking.id, kind));
  }

  return (
    <Panel title={booking.ref} note={booking.state}>
      <div className={styles.column}>
        <dl className={styles.dl}>
          <dt>State</dt>
          <dd>
            <StateBadge state={booking.state} />
          </dd>
          <dt>Rider</dt>
          <dd>{booking.rider || "—"}</dd>
          <dt>Contact</dt>
          <dd>{booking.contact || "—"}</dd>
          <dt>Route</dt>
          <dd>
            {booking.pickup || "—"} &rarr; {booking.dropoff || "—"}
          </dd>
          <dt>When</dt>
          <dd>{booking.when_text || "—"}</dd>
          <dt>Party</dt>
          <dd>
            {booking.passengers} passenger{booking.passengers === 1 ? "" : "s"},{" "}
            {booking.luggage} bag{booking.luggage === 1 ? "" : "s"}
          </dd>
          <dt>Driver</dt>
          <dd>
            {booking.driver
              ? `${booking.driver.name}${booking.driver.vehicle ? ` — ${booking.driver.vehicle}` : ""}`
              : "not assigned"}
          </dd>
          {booking.notes ? (
            <>
              <dt>Notes</dt>
              <dd>{booking.notes}</dd>
            </>
          ) : null}
        </dl>

        {/* ---------------------------------------------------------------- quote */}
        <div>
          <p className={styles.label}>Quote</p>
          {booking.quote === null ? (
            <p className={styles.empty}>Not quoted yet.</p>
          ) : booking.quote.estimate === null ? (
            <>
              {/* The no-figure case is the NORMAL one today, and it is rendered as the API
                  states it. A placeholder number here would invent the one thing the customer
                  preview promises in writing is absent. */}
              <p className={styles.noFigure}>{booking.quote.display}</p>
              <p className={styles.note}>{booking.quote.basis}</p>
            </>
          ) : (
            <>
              <p className={styles.noFigure}>{booking.quote.display}</p>
              <ul className={styles.quoteLines}>
                {booking.quote.lines.map((line, i) => (
                  <li key={`${line.label}-${i}`}>
                    <span>
                      {line.label}
                      {line.note ? ` — ${line.note}` : ""}
                    </span>
                    <span>{line.minor}</span>
                  </li>
                ))}
              </ul>
              <p className={styles.note}>{booking.quote.basis}</p>
            </>
          )}
          {booking.quote?.operator_confirms ? (
            <p className={styles.note}>The operator keeps the final say on every job.</p>
          ) : null}
        </div>

        {isOperator && booking.state === "requested" ? (
          <div className={styles.row}>
            <input
              className={styles.input}
              style={{ maxWidth: "160px" }}
              inputMode="decimal"
              placeholder="distance (km)"
              aria-label="Measured distance in kilometres"
              value={distanceKm}
              onChange={(e) => setDistanceKm(e.target.value)}
            />
            <button
              type="button"
              className={styles.button}
              disabled={busy}
              onClick={() =>
                run(() =>
                  quoteBooking(booking.id, distanceKm.trim() === "" ? null : Number(distanceKm)),
                )
              }
            >
              Quote this trip
            </button>
            <span className={styles.note}>
              Distance is never estimated. Left blank, the breakdown says so.
            </span>
          </div>
        ) : null}

        {/* ---------------------------------------------------------------- lifecycle */}
        {isOperator && allowed.length > 0 ? (
          <div className={styles.row}>
            {allowed.includes("dispatched") ? (
              <select
                className={styles.input}
                style={{ maxWidth: "220px" }}
                aria-label="Assign a driver"
                value={driverId}
                onChange={(e) => setDriverId(e.target.value)}
              >
                <option value="">No driver assigned</option>
                {drivers.map((d) => (
                  <option key={d.id} value={String(d.id)}>
                    {d.name}
                    {d.vehicle ? ` — ${d.vehicle}` : ""}
                  </option>
                ))}
              </select>
            ) : null}
            {allowed.map((to) => (
              <button
                key={to}
                type="button"
                className={styles.button}
                disabled={busy}
                onClick={() => advanceTo(to)}
              >
                Move to {to}
              </button>
            ))}
          </div>
        ) : null}

        {/* ---------------------------------------------------------------- messages */}
        {isOperator ? (
          <div className={styles.row}>
            <button
              type="button"
              className={styles.button}
              disabled={busy}
              onClick={() => compose("reminder")}
            >
              Compose reminder
            </button>
            <button
              type="button"
              className={styles.button}
              disabled={busy}
              onClick={() => compose("review_request")}
            >
              Compose review request
            </button>
          </div>
        ) : null}

        {booking.messages.length > 0 ? (
          <div className={styles.column}>
            <p className={styles.label}>Composed messages</p>
            {booking.messages.map((m) => (
              <div className={styles.composed} key={m.id}>
                <div className={styles.row}>
                  <span className={styles.badge}>{m.kind}</span>
                  {/* sent_at is always null: there is no sender in the package. Saying
                      "composed, not sent" is the whole honesty requirement of this surface. */}
                  <span className={styles.badgeTerminal + " " + styles.badge}>
                    {m.sent_at === null ? "not sent" : "sent"}
                  </span>
                  <span className={styles.note}>{stamp(m.at)}</span>
                </div>
                <p className={styles.composedBody}>{m.body}</p>
                <p className={styles.note}>
                  Stored and shown here only. Live routing requires approved email
                  configuration.
                </p>
              </div>
            ))}
          </div>
        ) : null}

        {/* ---------------------------------------------------------------- trail */}
        <div>
          <p className={styles.label}>Record trail</p>
          <ul className={styles.trail}>
            {booking.events.map((e, i) => (
              <li key={`${e.at}-${i}`}>
                {stamp(e.at)} · {e.actor} · {e.kind}
                {e.detail ? ` — ${e.detail}` : ""}
              </li>
            ))}
          </ul>
        </div>

        {error ? (
          <p className={styles.error} role="alert">
            {error}
          </p>
        ) : null}
      </div>
    </Panel>
  );
}
