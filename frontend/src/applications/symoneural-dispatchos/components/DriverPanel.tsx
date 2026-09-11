"use client";

import { useState, type FormEvent } from "react";
import { Panel } from "@/components/ui/Panel";
import { ApiError } from "@/lib/api/client";
import { addDriver } from "../api/client";
import type { Driver } from "../types";
import styles from "../styles/dispatchos.module.css";

/** Operator-only. The route answers 403 to a customer regardless of what is rendered here. */
export function DriverPanel({
  drivers,
  onChanged,
}: {
  readonly drivers: readonly Driver[];
  readonly onChanged: () => void | Promise<void>;
}) {
  const [name, setName] = useState("");
  const [vehicle, setVehicle] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await addDriver(name, vehicle);
      setName("");
      setVehicle("");
      await onChanged();
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "the driver could not be added");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Panel title="Drivers" note={`${drivers.length}`}>
      <div className={styles.column}>
        {drivers.length === 0 ? (
          <p className={styles.empty}>No drivers yet. A trip can still be dispatched without one.</p>
        ) : (
          <ul className={styles.trail}>
            {drivers.map((d) => (
              <li key={d.id}>
                {d.name}
                {d.vehicle ? ` — ${d.vehicle}` : ""}
                {d.active ? "" : " (inactive)"}
              </li>
            ))}
          </ul>
        )}

        <form className={styles.form} onSubmit={submit}>
          <div className={styles.field}>
            <label className={styles.label} htmlFor="dr-name">
              Name
            </label>
            <input
              id="dr-name"
              className={styles.input}
              required
              value={name}
              onChange={(e) => setName(e.target.value)}
            />
          </div>
          <div className={styles.field}>
            <label className={styles.label} htmlFor="dr-vehicle">
              Vehicle
            </label>
            <input
              id="dr-vehicle"
              className={styles.input}
              value={vehicle}
              onChange={(e) => setVehicle(e.target.value)}
            />
          </div>
          {error ? (
            <p className={styles.error} role="alert">
              {error}
            </p>
          ) : null}
          <div className={styles.row}>
            <button className={styles.button} type="submit" disabled={busy}>
              {busy ? "Adding…" : "Add driver"}
            </button>
          </div>
        </form>
      </div>
    </Panel>
  );
}
