/**
 * Site-wide constants. Nothing secret belongs in this file or anywhere else under `src/` --
 * every byte here is compiled into a bundle a browser downloads.
 */

export const BRAND = {
  name: "SyMoNeuRaL",
  /** The legacy pages render the wordmark this way and the shell must match it. */
  wordmark: "SyMoNeuRaL",
} as const;

/**
 * Same-origin. Not a configurable base URL, deliberately.
 *
 * The browser talks to the origin it was served from; `next.config.ts` rewrites `/api/*` to
 * FastAPI behind the scenes. Making this a public env var would invite a cross-origin
 * deployment, and the DispatchOS session cookie is `SameSite=Lax` -- it would simply stop
 * being sent, and the failure would look like "the board is empty" rather than like a
 * configuration mistake.
 */
export const API_ROOT = "/api";

export type NavItem = {
  readonly href: string;
  readonly label: string;
  /**
   * `legacy` means the destination is still served by `site/` through Caddy, not by this
   * project. A migrated route flips to `next`. The shell renders both identically; the flag
   * exists so the route-ownership record can be generated from code rather than remembered.
   */
  readonly owner: "next" | "legacy";
};

/**
 * Only what is actually reachable is listed. This is not the full 26-page legacy inventory:
 * a nav entry for a route this project does not own yet would be a link out of the new shell
 * into the old one, mid-migration, with no visual seam to warn anybody.
 */
export const PRIMARY_NAV: readonly NavItem[] = [
  { href: "/", label: "Home", owner: "next" },
  { href: "/demo/dispatchos", label: "DispatchOS", owner: "next" },
] as const;
