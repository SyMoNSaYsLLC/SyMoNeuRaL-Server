"use client";

import { useState, type FormEvent } from "react";
import { Panel } from "@/components/ui/Panel";
import styles from "../styles/dispatchos.module.css";

/**
 * The application's own sign-in, which is the SECOND gate.
 *
 * The first is Caddy's basicauth on `/demo/dispatchos`: one flat tier that authenticates and
 * does not authorise. This form is where the operator/customer tiers begin, and it is the one
 * that decides what a person can see. The panel says so, because a visitor who has already
 * typed one password is entitled to know why they are being asked for a second.
 */

export type SignInPanelProps = {
  readonly onSubmit: (username: string, password: string) => Promise<boolean>;
  readonly busy: boolean;
  readonly error: string | null;
  readonly retryAfterSeconds: number | null;
};

export function SignInPanel({ onSubmit, busy, error, retryAfterSeconds }: SignInPanelProps) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");

  async function handle(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const ok = await onSubmit(username, password);
    if (ok) setPassword("");
  }

  return (
    <Panel title="Sign in to DispatchOS" note="operator or customer">
      <form className={`${styles.form} ${styles.signIn}`} onSubmit={handle}>
        <div className={styles.field}>
          <label className={styles.label} htmlFor="do-user">
            Username
          </label>
          <input
            id="do-user"
            className={styles.input}
            autoComplete="username"
            spellCheck={false}
            required
            value={username}
            onChange={(e) => setUsername(e.target.value)}
          />
        </div>

        <div className={styles.field}>
          <label className={styles.label} htmlFor="do-pass">
            Password
          </label>
          <input
            id="do-pass"
            className={styles.input}
            type="password"
            autoComplete="current-password"
            required
            value={password}
            onChange={(e) => setPassword(e.target.value)}
          />
        </div>

        {error ? (
          <p className={styles.error} role="alert">
            {error}
            {retryAfterSeconds === null ? null : ` (retry in ${retryAfterSeconds}s)`}
          </p>
        ) : null}

        <div className={styles.row}>
          <button className={`${styles.button} ${styles.primary}`} type="submit" disabled={busy}>
            {busy ? "Signing in…" : "Sign in"}
          </button>
        </div>

        <p className={styles.note}>
          This is the application&rsquo;s own sign-in and it is separate from the password on
          the door. Accounts are issued by the operator; there is no self-service sign-up and
          no password reset on this box.
        </p>
      </form>
    </Panel>
  );
}
