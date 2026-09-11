"use client";

import { useCallback, useEffect, useState } from "react";
import { ApiError } from "@/lib/api/client";
import { fetchMe, fetchStatus, signIn, signOut } from "../api/client";
import type { StatusResponse, User } from "../types";

/**
 * Whether the surface is on, and who -- if anyone -- is signed in.
 *
 * Both answers come from the API. The session cookie is HttpOnly, so there is nothing on the
 * client to read and no local "logged in" flag that could disagree with the server. On mount
 * the hook asks `/status` and then `/me`; a 401 from `/me` is the normal signed-out answer and
 * is not an error worth showing anybody.
 */

export type SessionState = {
  readonly status: StatusResponse | null;
  readonly user: User | null;
  readonly loading: boolean;
  /** Only set for failures a person should see -- not for the ordinary signed-out 401. */
  readonly error: string | null;
  /** Seconds to wait, when the login throttle has engaged. */
  readonly retryAfterSeconds: number | null;
};

export function useDispatchSession() {
  const [state, setState] = useState<SessionState>({
    status: null,
    user: null,
    loading: true,
    error: null,
    retryAfterSeconds: null,
  });

  const load = useCallback(async (signal?: AbortSignal) => {
    try {
      const status = await fetchStatus(signal);
      if (!status.enabled) {
        setState({
          status,
          user: null,
          loading: false,
          error: null,
          retryAfterSeconds: null,
        });
        return;
      }
      try {
        const { user } = await fetchMe(signal);
        setState({ status, user, loading: false, error: null, retryAfterSeconds: null });
      } catch (cause) {
        // 401 here means "not signed in", which is a state and not a failure.
        if (cause instanceof ApiError && cause.isUnauthenticated) {
          setState({ status, user: null, loading: false, error: null, retryAfterSeconds: null });
          return;
        }
        throw cause;
      }
    } catch (cause) {
      if (signal?.aborted) return;
      setState({
        status: null,
        user: null,
        loading: false,
        error: cause instanceof ApiError ? cause.message : "the surface could not be reached",
        retryAfterSeconds: null,
      });
    }
  }, []);

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load]);

  const login = useCallback(async (username: string, password: string) => {
    setState((s) => ({ ...s, loading: true, error: null, retryAfterSeconds: null }));
    try {
      const { user } = await signIn(username, password);
      setState((s) => ({ ...s, user, loading: false, error: null, retryAfterSeconds: null }));
      return true;
    } catch (cause) {
      const isApi = cause instanceof ApiError;
      setState((s) => ({
        ...s,
        user: null,
        loading: false,
        // The server's own sentence. A generic "login failed" would hide the 429, and the
        // difference between a wrong password and a throttle is the whole point of that code.
        error: isApi ? cause.message : "sign-in could not be completed",
        retryAfterSeconds: isApi ? cause.retryAfterSeconds : null,
      }));
      return false;
    }
  }, []);

  const logout = useCallback(async () => {
    try {
      await signOut();
    } finally {
      setState((s) => ({ ...s, user: null, error: null, retryAfterSeconds: null }));
    }
  }, []);

  return { ...state, login, logout, reload: load } as const;
}
