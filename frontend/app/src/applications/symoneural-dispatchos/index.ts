/**
 * `symoneural-dispatchos` owns `/demo/dispatchos`: its frontend behaviour, its typed API
 * client, its preview state and its application-specific components.
 *
 * The route imports from here and nothing else. Everything below this file is internal.
 */
export { DispatchWorkspace } from "./components/DispatchWorkspace";
export type { BookingState, Role } from "./types";
