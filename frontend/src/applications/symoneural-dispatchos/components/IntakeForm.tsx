"use client";

import { useState, type FormEvent } from "react";
import { Panel } from "@/components/ui/Panel";
import { ApiError } from "@/lib/api/client";
import { createBooking } from "../api/client";
import type { IntakeDraft, Role } from "../types";
import styles from "../styles/dispatchos.module.css";

/**
 * Basic intake.
 *
 * One form for both tiers, because the backend takes one shape. The only difference is
 * ownership and it is decided server-side: a customer's request is owned by them, an
 * operator's is unowned -- the preview calls that out explicitly, "whether the request came in
 * by phone or through the intake page".
 */

const EMPTY: IntakeDraft = {
  rider: "",
  contact: "",
  pickup: "",
  dropoff: "",
  when_text: "",
  passengers: 1,
  luggage: 0,
  notes: "",
};

export function IntakeForm({
  role,
  onCreated,
}: {
  readonly role: Role;
  readonly onCreated: () => void | Promise<void>;
}) {
  const [draft, setDraft] = useState<IntakeDraft>(EMPTY);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function set<K extends keyof IntakeDraft>(key: K, value: IntakeDraft[K]) {
    setDraft((d) => ({ ...d, [key]: value }));
  }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await createBooking(draft);
      setDraft(EMPTY);
      await onCreated();
    } catch (cause) {
      setError(cause instanceof ApiError ? cause.message : "the trip could not be requested");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Panel
      title={role === "operator" ? "Take a booking" : "Request a trip"}
      note={role === "operator" ? "phone or counter" : ""}
    >
      <form className={styles.form} onSubmit={submit}>
        <div className={styles.pair}>
          <div className={styles.field}>
            <label className={styles.label} htmlFor="in-rider">
              Rider
            </label>
            <input
              id="in-rider"
              className={styles.input}
              value={draft.rider}
              onChange={(e) => set("rider", e.target.value)}
              placeholder={role === "customer" ? "defaults to your name" : ""}
            />
          </div>
          <div className={styles.field}>
            <label className={styles.label} htmlFor="in-contact">
              Contact
            </label>
            <input
              id="in-contact"
              className={styles.input}
              value={draft.contact}
              onChange={(e) => set("contact", e.target.value)}
            />
          </div>
        </div>

        <div className={styles.pair}>
          <div className={styles.field}>
            <label className={styles.label} htmlFor="in-pickup">
              Pickup
            </label>
            <input
              id="in-pickup"
              className={styles.input}
              required
              value={draft.pickup}
              onChange={(e) => set("pickup", e.target.value)}
            />
          </div>
          <div className={styles.field}>
            <label className={styles.label} htmlFor="in-dropoff">
              Dropoff
            </label>
            <input
              id="in-dropoff"
              className={styles.input}
              required
              value={draft.dropoff}
              onChange={(e) => set("dropoff", e.target.value)}
            />
          </div>
        </div>

        <div className={styles.field}>
          <label className={styles.label} htmlFor="in-when">
            When
          </label>
          <input
            id="in-when"
            className={styles.input}
            value={draft.when_text}
            onChange={(e) => set("when_text", e.target.value)}
            placeholder="free text, as the rider said it"
          />
        </div>

        <div className={styles.pair}>
          <div className={styles.field}>
            <label className={styles.label} htmlFor="in-pax">
              Passengers
            </label>
            <input
              id="in-pax"
              className={styles.input}
              type="number"
              min={1}
              value={draft.passengers}
              onChange={(e) => set("passengers", Number(e.target.value) || 1)}
            />
          </div>
          <div className={styles.field}>
            <label className={styles.label} htmlFor="in-bags">
              Luggage
            </label>
            <input
              id="in-bags"
              className={styles.input}
              type="number"
              min={0}
              value={draft.luggage}
              onChange={(e) => set("luggage", Number(e.target.value) || 0)}
            />
          </div>
        </div>

        <div className={styles.field}>
          <label className={styles.label} htmlFor="in-notes">
            Notes
          </label>
          <textarea
            id="in-notes"
            className={styles.input}
            value={draft.notes}
            onChange={(e) => set("notes", e.target.value)}
          />
        </div>

        {error ? (
          <p className={styles.error} role="alert">
            {error}
          </p>
        ) : null}

        <div className={styles.row}>
          <button className={`${styles.button} ${styles.primary}`} type="submit" disabled={busy}>
            {busy ? "Saving…" : role === "operator" ? "Add to the board" : "Request"}
          </button>
        </div>
      </form>
    </Panel>
  );
}
