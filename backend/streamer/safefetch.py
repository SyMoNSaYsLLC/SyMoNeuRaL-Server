"""The one door out. Every outbound byte caused by a visitor-supplied URL goes through here.

The Streamer's whole hazard is that a visitor hands us a URL and this box fetches it. Without a
control, `http://127.0.0.1:8800/` reaches the API itself, `http://192.168.x.x/` reaches the
LAN, and `http://169.254.169.254/` reaches a cloud metadata endpoint. So there is exactly one
function that decides whether a URL may be fetched -- `validate_url` -- and exactly one way to
open a socket to it -- `open_stream`, which connects to the *address validate_url already
approved* rather than re-resolving the name.

**The validator is not advisory, and no visitor-supplied URL is ever passed to a subprocess.**
That is the load-bearing sentence of this module. If we handed the URL to ffmpeg, ffmpeg would
do its own DNS resolution, its own redirect following, and its own protocol handling in another
process with another resolver -- and this file would be decoration. Python opens the upstream
socket here and pipes the bytes into ffmpeg's stdin (see `sessions.py`). ffmpeg is additionally
launched with `-protocol_whitelist pipe,fd` so it could not open a URL even if one reached it.

**DNS rebinding.** The classic bypass is to answer the validator's lookup with a public address
and the connection's lookup with 127.0.0.1. That requires two lookups. There is only one here:
`validate_url` calls `getaddrinfo` once, checks *every* address it returned (not just the one
it will use -- a name with both a public and a private A record is an attack, not a fallback),
and returns the chosen address as `Target.ip`. `open_stream` then connects to that literal.
The name is never resolved again, so the check and the connection cannot see different answers.
The hostname survives only as the `Host:` header and the TLS SNI/certificate name, which is
what makes name-based virtual hosts and certificate validation still work.

**Redirects** are followed by this module, never by the transport: `http.client` does not
follow them, so each `Location` comes back here and goes through `validate_url` again with the
same rules. A public host redirecting to `http://127.0.0.1/` is the second-most common SSRF
shape and it is caught by the fact that there is no path that skips the validator.

**Credentials.** IPTV URLs carry the visitor's username and password in the path or query.
Nothing in this module logs a URL, and every exception it raises is constructed from a fixed
string plus a host, never from the URL and never from an upstream exception's message. Use
`redact()` on anything that might have touched one before it goes near a log.

There is exactly **one** exception to "never from the body", and it is deliberate: an HTTP
error response's body is excerpted into the `FetchError` message, because "account expired" is
the answer the visitor needs and "upstream returned HTTP 403" is not. That excerpt is the most
dangerous string in this file -- panels reflect the requested path, credentials and all -- so it
goes through `Scrubber.from_urls`, which treats every path segment and query value of both the
requested and the reached URL as a secret. See the section headed "what the provider said".
"""
from __future__ import annotations

import base64
import html
import http.client
import ipaddress
import os
import re
import socket
import ssl
import time
import urllib.parse
from dataclasses import dataclass
from typing import Iterable

__all__ = [
    "BlockedURL", "FetchError", "ResponseTooLarge", "Policy", "Target",
    "validate_url", "open_stream", "fetch", "redact", "Scrubber",
    "DEFAULT_USER_AGENT", "text_excerpt",
]


# ---------------------------------------------------------------- the User-Agent question
#
# Why this is not "SyMoNeuRaL-Streamer/1", which is what it used to be, and which is the polite,
# honest, correct thing for a bot to send:
#
# An IPTV provider's edge is not a web server serving documents to crawlers. It is a paywall
# whose only real enforcement is per-connection, and the cheapest filter any panel operator
# applies is on User-Agent: the paying customer is running VLC, Kodi, TiviMate or a set-top box,
# so anything that is not one of those is a scraper, a reseller re-streaming their feed, or a
# competitor's probe. A large fraction of providers therefore refuse an unknown agent outright.
#
# The refusal is often *not* an honest 403. Panels commonly answer HTTP 200 with an HTML
# "access denied" or "please use a supported player" page, which then arrives at the pump as
# the stream body -- which is precisely the blank-screen-with-everything-green failure this
# module's callers spend so much effort explaining. Sending the agent the provider expects is
# the difference between a stream that plays and a stream that does not.
#
# This is not spoofing to defeat a security control: the credential in the URL is the visitor's
# own, and the request is the one their own player would make. It is stating the client the
# protocol expects. If a provider genuinely wants to identify this box, the override below is
# how an operator gives it a name.
_UA_ENV = "SYMONEURAL_STREAMER_USER_AGENT"
_UA_FALLBACK = "VLC/3.0.20 LibVLC/3.0.20"


def _default_user_agent() -> str:
    """Read the operator's override once, at import, and make it safe to put in a header.

    This is the **only** environment variable this module reads, and it deliberately cannot
    touch anything but the agent string -- see `Policy`'s docstring for why `allow_private` in
    particular has no such switch. A CR or LF here would be request smuggling into every
    upstream connection, so control characters are dropped rather than the value refused: an
    operator typo must not take the streamer offline.
    """
    raw = os.environ.get(_UA_ENV, "") or ""
    cleaned = "".join(c for c in raw if c.isprintable() and c not in "\r\n").strip()
    return cleaned[:200] or _UA_FALLBACK


#: The agent every outbound request carries unless a `Policy` says otherwise.
DEFAULT_USER_AGENT = _default_user_agent()


class BlockedURL(Exception):
    """A URL was refused by policy. The message is safe to show a visitor and to log.

    It deliberately never contains the URL: the reason and the hostname are enough to debug
    with, and the rest of the URL is the visitor's credential.
    """


class FetchError(Exception):
    """An allowed URL could not be fetched. Message is sanitized -- see the module docstring."""


class ResponseTooLarge(FetchError):
    """The upstream answered, and the answer was bigger than `Policy.max_bytes`.

    A subclass rather than a flag because callers need to tell it apart from every other fetch
    failure to say an honest sentence about it: "this panel has no VOD" and "this box refused to
    load that panel's VOD" are different facts, and reporting the second as the first blames the
    provider for our own ceiling. Nothing that only catches `FetchError` changes behaviour.
    """


@dataclass(frozen=True)
class Policy:
    """What this door will open for.

    `allow_private` exists for unit tests, which need to talk to a loopback socket that the
    production policy exists to forbid. It is a constructor argument and there is deliberately
    **no environment variable and no request field that can set it** -- a switch that disables
    SSRF protection on a live public box is a worse bug than the one it would help debug. The
    serving path builds `Policy()` and nothing reaches in to change it.
    """
    allow_private: bool = False
    #: Xtream stream URLs chain redirects as a matter of course -- the panel answers `/live/...`
    #: with a 302 to a load balancer, which redirects to a region, which redirects to the edge
    #: node actually holding the channel, and a `?token=` handoff can add another hop. Three was
    #: not a security bound (every hop is re-validated by `validate_url`, so a longer chain is
    #: no more dangerous than a short one) -- it was a guess, and it was low enough to fail
    #: perfectly ordinary providers with "too many redirects". Six covers the chains seen in the
    #: wild while still ending a redirect loop promptly.
    max_redirects: int = 6
    connect_timeout: float = 8.0
    read_timeout: float = 20.0
    #: **No byte cap by default.** `0` means uncapped, and `0` is the default at the owner's
    #: explicit instruction (2026-08-17). It was 24 MiB, sized for an M3U playlist, and on a real
    #: account it refused a 27.57 MB movie catalogue and left the Movies section empty. Every
    #: number chosen here was wrong for somebody's catalogue, so the number is gone. What still
    #: bounds a `fetch` is `total_timeout` plus the deadline in the read loop, which is the bound
    #: that was doing the real work: a slow-drip server satisfies any byte cap indefinitely.
    #: A caller that genuinely needs a ceiling passes one (`Policy(max_bytes=N)`); the tests do.
    max_bytes: int = 0
    #: Wall clock for a whole `fetch`. `read_timeout` only bounds the gap between packets, which
    #: a slow-drip server satisfies indefinitely.
    total_timeout: float = 60.0
    #: See the note above this class. Overridable per-Policy, and by `SYMONEURAL_STREAMER_USER_AGENT`
    #: at import; nothing a visitor sends can reach it.
    user_agent: str = DEFAULT_USER_AGENT


@dataclass(frozen=True)
class Target:
    """A URL that has passed `validate_url`, decomposed so it can never be re-parsed wrongly."""
    scheme: str
    host: str                  # the name, for Host: and SNI
    port: int
    ip: str                    # the address validate_url approved; the only thing we connect to
    path: str                  # path + query, already encoded
    auth: str | None = None    # Basic credential from userinfo, if any. Never logged.

    @property
    def origin(self) -> str:
        """Loggable identity of the target: scheme, host, port. No path, so no credential."""
        return f"{self.scheme}://{self.host}:{self.port}"

    def join(self, ref: str) -> str:
        """Resolve a relative reference (an HLS segment URI) against this target."""
        base = f"{self.scheme}://{self.host}:{self.port}{self.path}"
        return urllib.parse.urljoin(base, ref)


# ---------------------------------------------------------------- address classification

def _reject_reason(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> str | None:
    """Why this address may not be contacted, or None if it may.

    Each rule is named separately rather than collapsed into `is_global` because the point of
    this function is that an auditor can read it against the requirement list. The final
    `is_global` clause is the catch-all that picks up the ranges nobody enumerated: CGNAT
    (100.64.0.0/10), documentation ranges (192.0.2.0/24, 198.51.100.0/24, 203.0.113.0/24),
    benchmarking (198.18.0.0/15), and the IPv6 equivalents.
    """
    # An IPv6 address can carry an IPv4 one inside it. `::ffff:127.0.0.1` is loopback,
    # `2002:7f00:1::` (6to4) and Teredo both embed a v4 address that the outer classification
    # would otherwise not look at. Unwrap and judge the inner address on its own merits.
    # CPython already reports all three as non-global, so this is defence in depth -- but it is
    # the layer that keeps that true if a future CPython relaxes one of them.
    if isinstance(ip, ipaddress.IPv6Address):
        for inner in (ip.ipv4_mapped,
                      ip.sixtofour,
                      (ip.teredo[1] if ip.teredo else None)):
            if inner is not None:
                reason = _reject_reason(inner)
                if reason:
                    return f"embedded IPv4 address is {reason}"

    if ip.is_unspecified:
        return "unspecified (0.0.0.0 / ::)"
    if ip.is_loopback:
        return "loopback"                    # 127.0.0.0/8, ::1 -- this box, including our API
    if ip.is_link_local:
        return "link-local"                  # 169.254.0.0/16 -- includes 169.254.169.254, and fe80::/10
    if ip.is_multicast:
        return "multicast"                   # 224.0.0.0/4, ff00::/8. Note: CPython reports
                                             # 224.0.0.1 as is_global=True, so this rule is not
                                             # redundant with the catch-all below.
    if ip.is_reserved:
        return "reserved"                    # 240.0.0.0/4 and friends
    if ip.is_private:
        return "private"                     # RFC1918 10/8 172.16/12 192.168/16, and fc00::/7
                                             # unique-local. CPython folds several of the above
                                             # into is_private too; order gives the better name.
    if not ip.is_global:
        return "not globally routable"
    return None


# ---------------------------------------------------------------- the auditable function

def validate_url(raw: str, policy: Policy = Policy(), *,
                 _resolver=None) -> Target:
    """Decide whether a visitor-supplied URL may be fetched, and pin the address to use.

    The rules, in the order they are applied:

    1. **Parseable, and absolute.** A URL with no scheme or no host is refused rather than
       guessed at; `urljoin`-ing a visitor string onto some assumed base is how an SSRF gets
       built by accident.
    2. **http and https only.** Everything else is refused by allow-list, so `file:`, `gopher:`,
       `ftp:`, `data:` and the rest need no individual rule. `file:///etc/passwd` dies here.
    3. **A real port.** Any port is permitted -- IPTV providers genuinely serve on 8080, 2082,
       25461 and stranger -- because once the *address* is known to be public, the port adds no
       protection. Port 0 and non-numeric ports are refused.
    4. **The name is resolved exactly once, and every answer must pass.** `getaddrinfo` is
       called here and nowhere else. If a name returns four addresses and one of them is
       private, the whole URL is refused: a name that resolves to both a public and a private
       address is a rebinding attack, not a legitimate fallback.
    5. **The resolved address is judged, never the hostname string.** `_reject_reason` rejects
       loopback, private/RFC1918, link-local (169.254.0.0/16, so cloud metadata), unique-local,
       multicast, reserved and everything else that is not globally routable, for IPv4 and IPv6
       alike, and unwraps IPv4 addresses embedded in IPv6 ones. There is no hostname denylist,
       because `localtest.me` resolves to 127.0.0.1 and `127.0.0.1.nip.io` is not the string
       "127.0.0.1" -- string checks lose this game every time.
    6. **The approved address is returned and is the only thing connected to.** See the module
       docstring on rebinding.

    Raises `BlockedURL` with a reason safe to log; the URL itself never appears in it.

    `_resolver` is a seam for the hostile-input unit tests, which must run with no network and
    cannot rely on any name existing. Production never passes it.
    """
    raw = (raw or "").strip()
    if not raw:
        raise BlockedURL("empty URL")
    if len(raw) > 4096:
        raise BlockedURL("URL too long")
    if any(c in raw for c in "\r\n\t"):
        # Header/request smuggling into the upstream connection. Also stops a newline splitting
        # a log line, which is how a scrubbed log becomes an unscrubbed one.
        raise BlockedURL("URL contains a control character")

    try:
        u = urllib.parse.urlsplit(raw)
    except ValueError:
        raise BlockedURL("URL could not be parsed") from None

    # (2) scheme allow-list
    scheme = u.scheme.lower()
    if scheme not in ("http", "https"):
        raise BlockedURL(f"scheme {scheme or '(none)'!r} is not allowed; only http and https")

    # (1) absolute, with a host
    try:
        host = u.hostname
    except ValueError:
        raise BlockedURL("URL has a malformed host") from None
    if not host:
        raise BlockedURL("URL has no host")
    host = host.strip("[]")

    # (3) port. `u.port or default` is the obvious spelling and it is wrong: port 0 is falsy,
    # so `http://host:0/` would silently become port 80 and be allowed. Test `is None`.
    try:
        raw_port = u.port
    except ValueError:
        raise BlockedURL("URL has a non-numeric or out-of-range port") from None
    port = raw_port if raw_port is not None else (443 if scheme == "https" else 80)
    if not 1 <= port <= 65535:
        raise BlockedURL("URL has an out-of-range port")

    auth = None
    if u.username is not None:
        # Some playlists use http://user:pass@host/. Keep it, move it into an Authorization
        # header so it never rides in a request line that something might log, and never
        # mention it again.
        cred = f"{urllib.parse.unquote(u.username)}:{urllib.parse.unquote(u.password or '')}"
        auth = "Basic " + base64.b64encode(cred.encode("utf-8")).decode("ascii")

    # (4) resolve once
    resolve = _resolver or _resolve
    try:
        addresses = resolve(host, port)
    except OSError:
        # The resolver's exception text can echo the name back; build our own.
        raise BlockedURL(f"host {host!r} could not be resolved") from None
    if not addresses:
        raise BlockedURL(f"host {host!r} resolved to nothing")

    # (5) judge every answer
    chosen: str | None = None
    for addr in addresses:
        try:
            parsed = ipaddress.ip_address(addr)
        except ValueError:
            raise BlockedURL(f"host {host!r} resolved to an unparseable address") from None
        reason = _reject_reason(parsed)
        if reason and not policy.allow_private:
            raise BlockedURL(f"host {host!r} resolves to a {reason} address, which is not allowed")
        if chosen is None:
            chosen = addr

    assert chosen is not None
    path = u.path or "/"
    if u.query:
        path = f"{path}?{u.query}"
    return Target(scheme=scheme, host=host, port=port, ip=chosen, path=path, auth=auth)


def _resolve(host: str, port: int) -> list[str]:
    """Every address this name has, v4 and v6. Called from `validate_url` and nowhere else."""
    infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    seen: list[str] = []
    for family, _type, _proto, _canon, sockaddr in infos:
        addr = sockaddr[0]
        if addr not in seen:
            seen.append(addr)
    return seen


# ---------------------------------------------------------------- pinned transport

class _PinnedHTTPConnection(http.client.HTTPConnection):
    """Connects to `target.ip` while remaining, in every other respect, a connection to the name.

    `self.host` stays the hostname, so `putrequest` emits the right `Host:` header for a
    name-based virtual host. Only `connect()` is overridden, so the address is decided by
    `validate_url` and cannot be re-derived from the name here.
    """

    def __init__(self, target: Target, timeout: float):
        super().__init__(target.host, target.port, timeout=timeout)
        self._pinned_ip = target.ip

    def connect(self) -> None:
        self.sock = socket.create_connection((self._pinned_ip, self.port), self.timeout,
                                             self.source_address)
        try:
            self.sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        except OSError:
            pass


class _PinnedHTTPSConnection(_PinnedHTTPConnection):
    """As above, then TLS with SNI and certificate validation against the *name*, not the address.

    This is the reason the pinning is done by overriding `connect` rather than by passing the IP
    as the host: an IP in `self.host` would make SNI an address and every certificate check
    fail, and the usual "fix" for that is to disable verification, which trades one hole for a
    worse one.
    """
    default_port = 443

    def __init__(self, target: Target, timeout: float, context: ssl.SSLContext):
        super().__init__(target, timeout)
        self._context = context

    def connect(self) -> None:
        super().connect()
        self.sock = self._context.wrap_socket(self.sock, server_hostname=self.host)


def _connect(target: Target, policy: Policy) -> http.client.HTTPConnection:
    if target.scheme == "https":
        ctx = ssl.create_default_context()          # verify_mode=CERT_REQUIRED, check_hostname=True
        return _PinnedHTTPSConnection(target, policy.connect_timeout, ctx)
    return _PinnedHTTPConnection(target, policy.connect_timeout)


# ---------------------------------------------------------------- what the provider said
#
# The user's diagnostic, in their words: "if it's not active you will come to a page from the
# server saying it's down, not just a blank screen." A dead channel and a broken streamer are two
# different bugs, and the only thing that tells them apart is the provider's own message --
# "account expired", "maximum connections reached", "stream not found". This module used to
# throw all of that away (`resp.read(0)`) and report `upstream returned HTTP 403`, which
# describes the transport and says nothing about the channel.
#
# The reason it threw it away is real and has not gone away: **an error body is attacker-shaped
# text and it routinely contains the visitor's credentials.** Panels reflect the requested path
# back -- "Stream not found: /live/<user>/<pass>/12345.ts" -- and an Xtream password lives in a
# path segment, where `redact()` cannot see it. So every excerpt goes through a `Scrubber` built
# from the URL itself with `Scrubber.from_url`, which treats every path segment and query value
# as a secret whether or not it looks like one. Over-scrubbing costs readability; under-scrubbing
# publishes a password.

#: How much of an error body to look at. Small on purpose: this is a sentence for a human, not
#: a document, and the whole read must fit in one buffered read (see `_read_error_excerpt`).
ERROR_BODY_BYTES = 8192
#: How much of it may reach a message. A provider page is mostly navigation and boilerplate;
#: 300 characters is enough for the sentence that matters and short enough to sit in a log line.
EXCERPT_CHARS = 300

_SCRIPTISH = re.compile(r"(?is)<(script|style|head)\b.*?</\1\s*>")
_ANY_TAG = re.compile(r"(?s)<[^>]*>")
_WHITESPACE = re.compile(r"\s+")


def text_excerpt(raw: bytes | str, scrub=None, limit: int = EXCERPT_CHARS) -> str:
    """Turn an HTML or plain-text error body into one short, scrubbed, log-safe sentence.

    Order matters and is not arbitrary:

    1. decode leniently -- an error page's charset is frequently a lie, and a decode error must
       not swallow the message;
    2. drop `<script>`, `<style>` and `<head>` *with their contents*, or a page's JavaScript and
       CSS become the "message";
    3. **unescape entities first, then strip tags.** The obvious order is the other way round
       and it puts markup back after removing it: a panel that echoes the requested path through
       an HTML escaper sends `Error: &lt;img src=x onerror=alert(1)&gt;`, which has no literal
       tags for the tag-stripper to find, and unescaping afterwards reconstitutes them into the
       message. Unescaping once and stripping after leaves double-encoded input inert, and the
       final `<>` sweep catches anything the tag pattern would not match as a tag;
    4. flatten every non-printable and every run of whitespace to single spaces -- a newline
       here is how a scrubbed log line becomes two lines, only one of which was scrubbed;
    5. **scrub**, with the caller's session scrubber;
    6. only then truncate. Truncating first could cut a credential in half and leave the half
       that is still a credential.

    The result is plain text and is safe to render as plain text. It is not sanitised HTML and
    must never be inserted as markup -- but it also does not rely on the consumer knowing that,
    which is why the angle brackets go rather than merely the tags.
    """
    if isinstance(raw, bytes):
        text = raw.decode("utf-8", "replace")
    else:
        text = raw or ""
    text = _SCRIPTISH.sub(" ", text)
    text = html.unescape(text)
    text = _SCRIPTISH.sub(" ", text)
    text = _ANY_TAG.sub(" ", text)
    text = text.replace("<", " ").replace(">", " ")
    text = "".join(c if c.isprintable() else " " for c in text)
    text = _WHITESPACE.sub(" ", text).strip()
    if scrub is not None:
        text = scrub(text)
    text = _WHITESPACE.sub(" ", text).strip()
    if len(text) > limit:
        text = text[:limit].rstrip() + "..."
    return text


def _read_error_excerpt(resp: http.client.HTTPResponse, url: str, target: Target) -> str:
    """A few kilobytes of an error body, scrubbed. Never raises; returns "" if it cannot.

    `read1`, not `read`: `read(8192)` blocks until it has 8192 bytes or EOF, so a server
    dribbling its error page one byte at a time would hold this thread for `read_timeout` per
    packet, indefinitely. `read1` takes at most one underlying read and returns what arrived.
    A partial page is a fine excerpt; a hang is not.

    Failure here must never replace the error we already have -- an HTTP 403 with an unreadable
    body is still an HTTP 403, and reporting "socket timeout" instead would lose the one fact
    the visitor needs.
    """
    try:
        raw = resp.read1(ERROR_BODY_BYTES)
    except Exception:
        return ""
    if not raw:
        return ""
    # Both URLs: the one the visitor typed and the one we actually reached. A provider that
    # redirects and then reflects the *redirected* path back would otherwise be scrubbed
    # against the wrong string.
    try:
        scrub = Scrubber.from_urls(url, target.join(""))
    except Exception:                                     # pragma: no cover - defence in depth
        scrub = Scrubber.from_url(url)
    return text_excerpt(raw, scrub)


# ---------------------------------------------------------------- request

def open_stream(url: str, policy: Policy = Policy(), *, headers: dict[str, str] | None = None,
                method: str = "GET", _resolver=None
                ) -> tuple[http.client.HTTPResponse, http.client.HTTPConnection, Target]:
    """Validate, connect to the pinned address, follow validated redirects, return the response.

    The response is live and unread -- callers stream from it. The connection is returned
    alongside because the caller must close it; the response alone does not own the socket.

    Redirects are followed here, capped at `policy.max_redirects`, and **every `Location` goes
    back through `validate_url`**. Relative locations are resolved against the target we
    actually reached, not against the URL the visitor typed.
    """
    target = validate_url(url, policy, _resolver=_resolver)
    hops = 0
    while True:
        conn = _connect(target, policy)
        try:
            req_headers = {
                "Host": target.host if target.port in (80, 443) else f"{target.host}:{target.port}",
                "User-Agent": policy.user_agent,
                "Accept": "*/*",
                "Connection": "close",
            }
            if target.auth:
                req_headers["Authorization"] = target.auth
            req_headers.update(headers or {})
            conn.request(method, target.path, headers=req_headers)
            conn.sock.settimeout(policy.read_timeout)
            resp = conn.getresponse()
        except BlockedURL:
            conn.close()
            raise
        except (OSError, http.client.HTTPException, ssl.SSLError) as exc:
            conn.close()
            # `exc` can carry the URL (ssl and http.client both quote it in places). Report the
            # class and the origin, never the message.
            raise FetchError(f"{target.origin}: {type(exc).__name__}") from None

        if resp.status in (301, 302, 303, 307, 308):
            location = resp.getheader("Location") or ""
            resp.read(0)
            conn.close()
            hops += 1
            if hops > policy.max_redirects:
                raise FetchError(f"{target.origin}: too many redirects (> {policy.max_redirects})")
            if not location:
                raise FetchError(f"{target.origin}: redirect with no Location")
            # Re-validate. A public host redirecting to 127.0.0.1 dies here, exactly as if the
            # visitor had typed 127.0.0.1 in the first place.
            target = validate_url(target.join(location), policy, _resolver=_resolver)
            continue

        if resp.status >= 400:
            # Read the provider's own words before closing. See the section above for why this
            # is worth the risk and what makes it safe.
            excerpt = _read_error_excerpt(resp, url, target)
            conn.close()
            msg = f"{target.origin}: upstream returned HTTP {resp.status}"
            if excerpt:
                msg = f"{msg} - {excerpt}"
            raise FetchError(msg)
        return resp, conn, target


def fetch(url: str, policy: Policy = Policy(), *, headers: dict[str, str] | None = None,
          _resolver=None) -> tuple[bytes, str, Target]:
    """Fetch a whole small document (a playlist, a JSON API response) with a hard byte cap.

    The cap is not politeness -- an upstream that streams forever into a `read()` with no limit
    is a memory exhaustion bug reachable by anyone who can type a URL into the page.
    """
    resp, conn, target = open_stream(url, policy, headers=headers, _resolver=_resolver)
    try:
        # Read in chunks against a wall-clock deadline rather than one `read(max_bytes)`. The
        # socket timeout only bounds the gap between packets, so a server dribbling a byte
        # every few seconds satisfies it forever and holds a worker thread for as long as it
        # likes. The byte cap alone does not stop that; a deadline does.
        deadline = time.monotonic() + policy.total_timeout
        chunks: list[bytes] = []
        total = 0
        # `max_bytes == 0` means no byte cap, which is now the default -- see `Policy`. The
        # deadline is what still bounds this loop, and it is the bound that actually mattered:
        # a slow-drip server was never stopped by the byte cap anyway.
        while not policy.max_bytes or total <= policy.max_bytes:
            if time.monotonic() > deadline:
                raise FetchError(f"{target.origin}: took longer than "
                                 f"{policy.total_timeout:g}s to respond")
            chunk = resp.read(65536)
            if not chunk:
                break
            chunks.append(chunk)
            total += len(chunk)
        if policy.max_bytes and total > policy.max_bytes:
            raise ResponseTooLarge(
                f"{target.origin}: response exceeds {policy.max_bytes} bytes")
        ctype = (resp.getheader("Content-Type") or "").split(";")[0].strip().lower()
        return b"".join(chunks), ctype, target
    except (OSError, http.client.HTTPException, ssl.SSLError) as exc:
        raise FetchError(f"{target.origin}: {type(exc).__name__}") from None
    finally:
        conn.close()


# ---------------------------------------------------------------- redaction

# Query parameters and path segments that carry a credential in the IPTV world. Matched
# case-insensitively. `password` is the Xtream one; the rest are here because playlist URLs in
# the wild use all of them and a scrubber that only knows one name is a scrubber that leaks.
_SECRET_KEYS = ("password", "passwd", "pass", "pwd", "username", "user", "token", "auth", "key")
_QUERY_SECRET = re.compile(
    r"(?i)\b(" + "|".join(_SECRET_KEYS) + r")=([^&\s\"'<>]*)")
_USERINFO = re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://)([^/\s@]+)@")


def redact(text: str) -> str:
    """Strip the obvious credential shapes out of a string before it goes near a log.

    This is the *last* line of defence, not the first: nothing in this module logs a URL at all.
    It exists because ffmpeg's stderr and third-party exception text are outside our control and
    can quote a URL we handed them.
    """
    if not text:
        return text
    text = _USERINFO.sub(r"\1***@", text)
    text = _QUERY_SECRET.sub(lambda m: f"{m.group(1)}=***", text)
    return text


def _url_secrets(url: str) -> list[str]:
    """Every literal in one URL that could be a credential. See `Scrubber.from_url`."""
    try:
        u = urllib.parse.urlsplit(url or "")
    except ValueError:
        return []
    secrets = [urllib.parse.unquote(seg) for seg in u.path.split("/") if seg]
    for _k, v in urllib.parse.parse_qsl(u.query, keep_blank_values=False):
        secrets.append(v)
    if u.password:
        secrets.append(urllib.parse.unquote(u.password))
    if u.username:
        secrets.append(urllib.parse.unquote(u.username))
    return secrets


class Scrubber:
    """Redaction plus the exact secrets of one session.

    `redact()` catches credentials that look like credentials. A password sitting in a URL
    *path segment* -- which is how Xtream stream URLs are built, `/live/<user>/<pass>/<id>.ts`
    -- looks like nothing at all. So a session registers its own literals and this replaces
    them wherever they appear, including inside ffmpeg's stderr.
    """

    def __init__(self, secrets: Iterable[str] = ()):
        # Longest first, so a password that contains the username does not get half-scrubbed.
        self._secrets = sorted({s for s in secrets if s and len(s) >= 3},
                               key=len, reverse=True)

    def add(self, *secrets: str) -> "Scrubber":
        return Scrubber([*self._secrets, *secrets])

    @classmethod
    def from_url(cls, url: str, *extra: str) -> "Scrubber":
        """Build a scrubber that knows one URL's own secrets, without being told what they are.

        The caller does not always have the credentials to register. A visitor who pastes an
        M3U exported from an Xtream panel sends `/tune` a URL shaped
        `http://host/live/<user>/<pass>/1.ts` and no username or password field at all -- so a
        scrubber primed from the request body would be empty, and a password in a *path
        segment* is invisible to `redact()`.

        So: treat every path segment and every query value in the URL as though it were a
        secret. Over-scrubbing is free here -- this is only ever applied to internal error text
        and log lines, where turning "live" into "***" costs a little readability and turning a
        password into "***" is the entire point.
        """
        return cls([*(s for s in extra if s), *_url_secrets(url)])

    @classmethod
    def from_urls(cls, *urls: str) -> "Scrubber":
        """`from_url` over several URLs at once.

        Needed because a request can reach a different URL than the one it was given: a
        provider that redirects and then reflects the *redirected* path back into its error
        page would be scrubbed against the wrong string if only the original were registered.
        """
        secrets: list[str] = []
        for u in urls:
            secrets.extend(_url_secrets(u))
        return cls(secrets)

    def __call__(self, text: str) -> str:
        text = redact(text)
        for s in self._secrets:
            if s in text:
                text = text.replace(s, "***")
            quoted = urllib.parse.quote(s, safe="")
            if quoted != s and quoted in text:
                text = text.replace(quoted, "***")
        return text
