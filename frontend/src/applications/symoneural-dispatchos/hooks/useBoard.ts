"use client";

import { useCallback, useEffect, useState } from "react";
import { ApiError } from "@/lib/api/client";
import { fetchBoard } from "../api/client";
import type { BoardResponse } from "../types";

/**
 * The board, and a way to ask for it again.
 *
 * Every mutation in this application returns the updated booking, but the board also carries
 * `counts` and `drivers`, so an action that changes state calls `refresh()` rather than
 * patching a local array. One source of truth, and it is the server's.
 *
 * There is no polling. A dispatch board that refetches on a timer would hold the connection
 * open behind Caddy's basicauth for as long as the tab is open, and nothing in the v1
 * workflow changes without this operator doing it.
 *
 * ## Why the effect is written as a promise chain and not as `await`
 *
 * `react-hooks/set-state-in-effect` rejects an effect body that CALLS a function containing
 * setState -- it cannot see that the call happens after network I/O, and being conservative
 * there is correct. The shape it endorses is the one used below: the effect body calls the
 * fetch, and setState happens inside the resolution callbacks, which is the rule's own
 * "calling setState in a callback function when external state changes". The first paint is
 * carried by the initial `loading` value instead of by a synchronous setState.
 */

export type BoardState = {
  readonly board: BoardResponse | null;
  readonly loading: boolean;
  readonly error: string | null;
};

function failure(cause: unknown): BoardState {
  return {
    board: null,
    loading: false,
    error: cause instanceof ApiError ? cause.message : "the board could not be loaded",
  };
}

export function useBoard(enabled: boolean) {
  const [state, setState] = useState<BoardState>({
    board: null,
    loading: enabled,
    error: null,
  });

  useEffect(() => {
    // Nothing is fetched and nothing is reset when there is no session. The consumer does not
    // render board data in that state, so there is no stale value to clear.
    if (!enabled) return;
    const controller = new AbortController();
    fetchBoard(controller.signal)
      .then((board) => setState({ board, loading: false, error: null }))
      .catch((cause: unknown) => {
        if (controller.signal.aborted) return;
        setState(failure(cause));
      });
    return () => controller.abort();
  }, [enabled]);

  /**
   * For event handlers after a mutation. Called from a click, never from an effect, so it is
   * free to show the spinner first.
   */
  const refresh = useCallback(async () => {
    setState((s) => ({ ...s, loading: true }));
    try {
      const board = await fetchBoard();
      setState({ board, loading: false, error: null });
    } catch (cause) {
      setState(failure(cause));
    }
  }, []);

  return { ...state, refresh } as const;
}
