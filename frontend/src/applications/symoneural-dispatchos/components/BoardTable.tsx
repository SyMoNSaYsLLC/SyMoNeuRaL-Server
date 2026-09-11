"use client";

import { Panel } from "@/components/ui/Panel";
import type { BookingSummary, Role } from "../types";
import { StateBadge } from "./StateBadge";
import styles from "../styles/dispatchos.module.css";

/**
 * The board. An operator sees every job; a customer sees only their own, and that filtering
 * happens on the server (`_visible()`), not here -- this component renders whatever the API
 * returned and could not show another customer's trip even if it tried.
 */

export type BoardTableProps = {
  readonly bookings: readonly BookingSummary[];
  readonly role: Role;
  readonly selectedId: number | null;
  readonly onSelect: (id: number) => void;
};

function when(value: string): string {
  return value.trim() === "" ? "—" : value;
}

export function BoardTable({ bookings, role, selectedId, onSelect }: BoardTableProps) {
  const note = `${bookings.length} ${bookings.length === 1 ? "trip" : "trips"}`;

  if (bookings.length === 0) {
    return (
      <Panel title="The board" note={note}>
        <p className={styles.empty}>
          {role === "operator"
            ? "No trips on the board yet. Take one below."
            : "You have no trips yet. Request one below."}
        </p>
      </Panel>
    );
  }

  return (
    <Panel title="The board" note={note}>
      <div className={styles.tableWrap}>
        <table className={styles.table}>
          <thead>
            <tr>
              <th scope="col">Ref</th>
              <th scope="col">State</th>
              <th scope="col">Rider</th>
              <th scope="col">Pickup</th>
              <th scope="col">Dropoff</th>
              <th scope="col">When</th>
              <th scope="col">Pax</th>
              <th scope="col">Bags</th>
              <th scope="col">Open</th>
            </tr>
          </thead>
          <tbody>
            {bookings.map((b) => (
              <tr key={b.id} className={b.id === selectedId ? styles.selected : undefined}>
                <td>{b.ref}</td>
                <td>
                  <StateBadge state={b.state} />
                </td>
                <td>{when(b.rider)}</td>
                <td>{when(b.pickup)}</td>
                <td>{when(b.dropoff)}</td>
                <td>{when(b.when_text)}</td>
                <td>{b.passengers}</td>
                <td>{b.luggage}</td>
                <td>
                  <button
                    type="button"
                    className={styles.rowButton}
                    onClick={() => onSelect(b.id)}
                  >
                    Open
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Panel>
  );
}
