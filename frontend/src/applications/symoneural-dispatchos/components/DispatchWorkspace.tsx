"use client";

import { useCallback, useEffect, useState } from "react";
import { SymoneuralShell } from "@/applications/symoneural-home";
import { Panel } from "@/components/ui/Panel";
import { ApiError } from "@/lib/api/client";
import { fetchBooking } from "../api/client";
import { useBoard } from "../hooks/useBoard";
import { useDispatchSession } from "../hooks/useDispatchSession";
import type { BookingDetail } from "../types";
import { BoardTable } from "./BoardTable";
import { BookingDetailPanel } from "./BookingDetailPanel";
import { DriverPanel } from "./DriverPanel";
import { IntakeForm } from "./IntakeForm";
import { SignInPanel } from "./SignInPanel";
import styles from "../styles/dispatchos.module.css";

/**
 * The whole DispatchOS surface: a workspace, not a marketing page.
 *
 * Three states it must render honestly, because each one is a real thing that happens:
 *   - the surface is switched off on this box (503, `SYMONEURAL_DISPATCHOS_ENABLED` unset);
 *   - nobody is signed in (401 from /me, which is a state and not a failure);
 *   - signed in, at one of two tiers.
 */
export function DispatchWorkspace() {
  const session = useDispatchSession();
  const signedIn = session.user !== null;
  const board = useBoard(signedIn);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [detail, setDetail] = useState<BookingDetail | null>(null);
  const [detailError, setDetailError] = useState<string | null>(null);

  const loadDetail = useCallback(async (id: number) => {
    try {
      const { booking } = await fetchBooking(id);
      setDetail(booking);
      setDetailError(null);
    } catch (cause) {
      setDetail(null);
      setDetailError(
        cause instanceof ApiError ? cause.message : "that booking could not be opened",
      );
    }
  }, []);

  useEffect(() => {
    // Written as a promise chain rather than `await loadDetail(...)` for the reason set out in
    // useBoard: the lint rule rejects an effect body that calls a setState-containing function
    // and endorses setState inside a resolution callback. Nothing is cleared when the
    // selection returns to null -- `shownDetail` derives visibility from the selection, so a
    // stale booking can never be rendered against a different row.
    if (selectedId === null) return;
    const id = selectedId;
    fetchBooking(id)
      .then(({ booking }) => {
        setDetail(booking);
        setDetailError(null);
      })
      .catch((cause: unknown) => {
        setDetail(null);
        setDetailError(
          cause instanceof ApiError ? cause.message : "that booking could not be opened",
        );
      });
  }, [selectedId]);

  /** The detail panel shows only when the loaded booking IS the selected one. */
  const shownDetail = detail !== null && detail.id === selectedId ? detail : null;

  const refreshAll = useCallback(async () => {
    await board.refresh();
    if (selectedId !== null) await loadDetail(selectedId);
  }, [board, selectedId, loadDetail]);

  const headerActions = signedIn ? (
    <>
      <span className={styles.note}>
        {session.user?.username} · {session.user?.role}
      </span>
      <button type="button" className={styles.button} onClick={() => void session.logout()}>
        Sign out
      </button>
    </>
  ) : null;

  return (
    <SymoneuralShell
      eyebrow="Transport dispatch"
      title="DispatchOS"
      {...(headerActions ? { headerActions } : {})}
    >
      {session.loading && session.status === null ? (
        <p className={styles.empty}>Loading…</p>
      ) : session.status !== null && !session.status.enabled ? (
        <Panel title="DispatchOS is switched off on this box" note="503">
          <p className={styles.empty}>
            The surface exists and is not enabled here. An operator switches it on with{" "}
            <code>SYMONEURAL_DISPATCHOS_ENABLED=1</code>; nothing on this page can do it.
          </p>
        </Panel>
      ) : session.error !== null && !signedIn ? (
        <Panel title="The surface could not be reached" note="">
          <p className={styles.error}>{session.error}</p>
        </Panel>
      ) : !signedIn ? (
        <SignInPanel
          onSubmit={session.login}
          busy={session.loading}
          error={session.error}
          retryAfterSeconds={session.retryAfterSeconds}
        />
      ) : (
        <div className={styles.layout}>
          <div className={styles.column}>
            {board.error ? (
              <p className={styles.error} role="alert">
                {board.error}
              </p>
            ) : null}

            <BoardTable
              bookings={board.board?.bookings ?? []}
              role={session.user!.role}
              selectedId={selectedId}
              onSelect={setSelectedId}
            />

            {detailError ? (
              <p className={styles.error} role="alert">
                {detailError}
              </p>
            ) : null}

            {shownDetail ? (
              <BookingDetailPanel
                booking={shownDetail}
                role={session.user!.role}
                drivers={board.board?.drivers ?? []}
                onChanged={refreshAll}
              />
            ) : null}
          </div>

          <div className={styles.column}>
            <IntakeForm role={session.user!.role} onCreated={refreshAll} />

            {session.user!.role === "operator" ? (
              <>
                <DriverPanel drivers={board.board?.drivers ?? []} onChanged={refreshAll} />
                <Panel title="Rate rules" note={board.board?.rates_configured ? "configured" : "not configured"}>
                  <p className={styles.note}>
                    {board.board?.rates_configured
                      ? "Quotes use the operator's configured rules."
                      : "No rate rules are configured, so a quote carries no figure. Rules are agreed in written scope before any price is shown."}
                  </p>
                </Panel>
              </>
            ) : null}
          </div>
        </div>
      )}
    </SymoneuralShell>
  );
}
