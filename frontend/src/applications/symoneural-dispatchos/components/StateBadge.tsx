import type { BookingState } from "../types";
import styles from "../styles/dispatchos.module.css";

/** `cancelled` is a terminal exit, not a step -- it is marked differently on purpose. */
export function StateBadge({ state }: { readonly state: BookingState }) {
  const cls =
    state === "cancelled"
      ? styles.badgeTerminal
      : state === "reviewed"
        ? styles.badgeActive
        : "";
  return <span className={`${styles.badge} ${cls}`}>{state}</span>;
}
