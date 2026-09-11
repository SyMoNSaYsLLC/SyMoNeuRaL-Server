/**
 * Who is asking, read from the request rather than from anything the client holds.
 *
 * Two functions and one rule: `getUser()` returns null, `requireUser()` redirects. A caller
 * that does not check the null has a type error rather than a rendered page belonging to
 * somebody else.
 *
 * ## Identity comes from the proxy, not from the browser
 *
 * The front door (`ops/Caddyfile` -> symon-gateway -> FastAPI) resolves the session cookie
 * and sets the headers below on the upstream request. Next reads THOSE. A page never parses
 * a cookie, never validates a signature, and never sees the secret that signs one.
 *
 * That matters because there is exactly one place that can be wrong. A page that verified
 * its own cookie would be a second implementation of "is this session valid", and the way
 * that drift shows up is a page you can reach one way and not the other.
 *
 * **These headers are only trustworthy because nothing but the proxy can set them.** The
 * gateway strips them from the inbound request before adding its own, for the same reason
 * `X-Forwarded-For` handling is left to Caddy's default: a header a client can forge is not
 * an identity, it is a suggestion. If this app is ever served without that proxy in front,
 * every function here returns null and every guarded page redirects -- which is the correct
 * failure direction, and is the reason this reads headers rather than trusting a fallback.
 *
 * ## No tokens
 *
 * There is no API key and no bearer token on this box and there will not be. The session
 * cookie is a different thing: nobody types it, no caller presents it to be let in, and it
 * is what makes a session unforgeable. Removing it would not open a door, it would make
 * every session forgeable by anyone who can write a cookie.
 */
import { headers } from "next/headers";
import { redirect } from "next/navigation";

export type SymoneuralUser = {
  /** Stable account id. Never an email -- an email changes, this does not. */
  userId: string;
  /** What to render. Full name when we have one, email otherwise. Never empty. */
  displayName: string;
  email: string;
  fullName: string | null;
};

const USER_ID_HEADER = "x-symoneural-user-id";
const USER_EMAIL_HEADER = "x-symoneural-user-email";
const USER_FULL_NAME_HEADER = "x-symoneural-user-full-name";

/**
 * A name is not ASCII and a header is. The encoding is declared in its own header rather
 * than assumed, so a proxy that has not been taught to encode sends no encoding header and
 * we drop the name instead of rendering mojibake beside somebody's account.
 */
const USER_FULL_NAME_ENCODING_HEADER = "x-symoneural-user-full-name-encoding";
const PERCENT_ENCODED_UTF8 = "percent-encoded-utf-8";

const SIGN_IN_PATH = "/signin";
const SIGN_OUT_PATH = "/signout";
const CALLBACK_PATH = "/callback";

/** The signed-in account, or null. Never throws -- a malformed header is "not signed in". */
export async function getUser(): Promise<SymoneuralUser | null> {
  const requestHeaders = await headers();
  const userId = requestHeaders.get(USER_ID_HEADER);
  const email = requestHeaders.get(USER_EMAIL_HEADER);

  // Both, not either. An id with no email is a half-resolved session, and rendering a page
  // for one is worse than sending the visitor back through the front door.
  if (!userId || !email) return null;

  const encodedFullName = requestHeaders.get(USER_FULL_NAME_HEADER);
  const fullName =
    encodedFullName &&
    requestHeaders.get(USER_FULL_NAME_ENCODING_HEADER) === PERCENT_ENCODED_UTF8
      ? safeDecodeURIComponent(encodedFullName)
      : null;

  return { userId, displayName: fullName ?? email, email, fullName };
}

/**
 * The signed-in account, or a redirect. Returns `SymoneuralUser`, not a nullable one, so the
 * guarded path has no branch to forget.
 */
export async function requireUser(returnTo: string): Promise<SymoneuralUser> {
  const user = await getUser();
  if (user) return user;
  redirect(signInPath(returnTo));
}

export function signInPath(returnTo: string): string {
  return `${SIGN_IN_PATH}?return_to=${encodeURIComponent(safeReturnPath(returnTo))}`;
}

export function signOutPath(returnTo = "/"): string {
  return `${SIGN_OUT_PATH}?return_to=${encodeURIComponent(safeReturnPath(returnTo))}`;
}

/**
 * The open-redirect defence, and the loop defence, in one place.
 *
 * A `return_to` is attacker-controlled by construction -- it arrives in a URL somebody can
 * send you. Three ways it goes wrong and all three are handled here:
 *
 *   `https://evil.example/`  an absolute URL. Rejected: must start with "/".
 *   `//evil.example/`        protocol-relative. A browser treats this as absolute, and the
 *                            leading-slash check alone would PASS it. This is the one that
 *                            gets missed.
 *   `/signin?return_to=...`  a reserved auth path. Not a security hole, an infinite loop:
 *                            sign in, get sent to sign in, forever.
 *
 * Parsed against a fixed base rather than pattern-matched, because URL parsing is where
 * `/\evil.example`, backslashes, encoded slashes and userinfo tricks are already solved.
 * Anything that does not come back with our base origin is discarded.
 */
function safeReturnPath(value: string): string {
  if (!value.startsWith("/") || value.startsWith("//")) return "/";

  let url: URL;
  try {
    url = new URL(value, "https://symoneural.local");
  } catch {
    return "/";
  }
  if (url.origin !== "https://symoneural.local") return "/";
  if (isReservedAuthPath(url.pathname)) return "/";

  return `${url.pathname}${url.search}${url.hash}`;
}

function isReservedAuthPath(pathname: string): boolean {
  return (
    pathname === SIGN_IN_PATH ||
    pathname === SIGN_OUT_PATH ||
    pathname === CALLBACK_PATH
  );
}

/** `decodeURIComponent` throws on a lone `%`. A bad name is not a reason to 500 a page. */
function safeDecodeURIComponent(value: string): string | null {
  try {
    return decodeURIComponent(value);
  } catch {
    return null;
  }
}
