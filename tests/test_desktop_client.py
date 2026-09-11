"""`desktop-client/` -- the Tauri window over the local API, and the claims it has to keep.

This is the sibling of `test_desktop_shell.py` and it is deliberately its mirror image. That
suite asserts `desktop/shell.py` **never** speaks to the API, because the shell's whole job is
to hand `bin/symoneural-cli` a real controlling terminal and a web client would be a second
implementation of the permission gate. This program does the opposite: talking to the API is
all it does. The two are different programs with opposite architectures, which is why they
have separate test files, and why nothing here may touch `desktop/shell.py` or its 15 tests.

Everything here is **structural** -- no display, no GPU, no running API -- so it runs in the
ordinary `pytest apps/` sweep on a headless box. There is no smoke test launching the window,
because there is no honest cheap one: `cargo build` takes tens of seconds on a warm cache and
minutes on a cold one, and a test that shells out to it would be a build, not an assertion.
The readings that cover the parts this file cannot are named in `desktop-client/README.md`:
a real window, and `cargo test` in `src-tauri/`.

The assertions worth knowing about, because they encode decisions rather than style:

* **Every `/api/` path the page names must exist in `backend/server.py`.** Parsed out of both
  sides rather than hardcoded here, so this goes red when a route is renamed -- which is the
  drift a hand-kept list would silently miss.
* **`ui/app.js` may not name a host.** The host is a constant in compiled Rust that the page
  cannot reach, so any host-looking literal in the page is either dead or a lie.
* **`tok_per_s` may not be recomputed.** The server measured it; a rate derived from a browser
  clock is a different quantity wearing the same name.
* **`check.passed` must have three renderings.** `null` means RavenCalc could not confirm the
  result, and it is reported rather than rounded up.
* **No `text-overflow` in the CSS.** House rule: an ellipsis is data loss with extra steps.

`strip_code` below matters as much as any single assertion. This program's source is heavily
commented, and those comments necessarily *name* the things the negative assertions forbid --
the header of `app.js` says in so many words that there is no `fetch()` in the file. A test
reading raw text would be satisfied, or rather defeated, by the file's own account of itself.
So comments come out and string literals stay, on the same reasoning as `strip_prose` in the
shell suite: a string used as a value is code, and `"/api/status"` passed to something is
exactly what these assertions are about.
"""
from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CLIENT = ROOT / "desktop-client"
APP_JS = CLIENT / "ui" / "app.js"
APP_CSS = CLIENT / "ui" / "app.css"
INDEX = CLIENT / "ui" / "index.html"
MAIN_RS = CLIENT / "src-tauri" / "src" / "main.rs"
CARGO = CLIENT / "src-tauri" / "Cargo.toml"
CONF = CLIENT / "src-tauri" / "tauri.conf.json"
CAPABILITY = CLIENT / "src-tauri" / "capabilities" / "default.json"
API_PY = ROOT / "backend" / "server.py"

SHELL = ROOT / "desktop" / "shell.py"


def strip_code(src: str) -> str:
    """C-family source with comments removed and string literals kept.

    Handles `//`, block comments, the three JavaScript quote forms and Rust's raw strings.
    The reason it tracks strings at all -- rather than deleting from `//` to end of line -- is
    that the single most important literal in this program is `"http://127.0.0.1:8800"`, and a
    naive line-comment stripper would cut it in half at the `//` and destroy the evidence the
    loopback assertion depends on.
    """
    out: list[str] = []
    i, n = 0, len(src)
    while i < n:
        ch = src[i]
        two = src[i:i + 2]
        if two == "//":
            i = src.find("\n", i)
            if i < 0:
                break
            continue
        if two == "/*":
            end = src.find("*/", i + 2)
            i = n if end < 0 else end + 2
            continue
        # Rust raw strings: r"..." / r#"..."# / r##"..."##
        raw = re.match(r'r(#*)"', src[i:])
        if raw and (i == 0 or not (src[i - 1].isalnum() or src[i - 1] == "_")):
            hashes = raw.group(1)
            close = '"' + hashes
            end = src.find(close, i + len(raw.group(0)))
            end = n if end < 0 else end + len(close)
            out.append(src[i:end])
            i = end
            continue
        if ch in "\"'`":
            j = i + 1
            while j < n:
                if src[j] == "\\":
                    j += 2
                    continue
                if src[j] == ch:
                    j += 1
                    break
                j += 1
            out.append(src[i:j])
            i = j
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def api_routes() -> set[str]:
    """Every path `backend/server.py` mounts on the app itself.

    Router includes are read too, so a path served under a prefix is not reported as missing.
    """
    src = API_PY.read_text()
    routes = set(
        m.group(2)
        for m in re.finditer(
            r"@app\.(get|post|put|delete|patch|websocket)\(\s*[\"']([^\"']+)[\"']", src
        )
    )
    for router, prefix in re.findall(
        r"app\.include_router\(\s*([\w.]+)\s*,\s*prefix=[\"']([^\"']+)[\"']", src
    ):
        routes.add(prefix + "/")
    return routes


class EndpointsExistTests(unittest.TestCase):
    """The page's paths, checked against the API that has to serve them."""

    @classmethod
    def setUpClass(cls):
        cls.code = strip_code(APP_JS.read_text())
        cls.named = sorted(set(re.findall(r"[\"'](/api/[^\"']*)[\"']", cls.code)))
        cls.routes = api_routes()

    def test_the_page_actually_names_the_four_surfaces(self):
        # If this list ever shrinks, a surface was dropped from the client and the checks on
        # #94 would still read 100%. Named explicitly for that reason.
        for path in ("/api/status", "/api/chat", "/api/image", "/api/ravencalc"):
            with self.subTest(path=path):
                self.assertIn(path, self.named)

    def test_every_path_the_page_names_is_served_by_api_py(self):
        self.assertTrue(self.named, "app.js named no /api/ path at all")
        for path in self.named:
            with self.subTest(path=path):
                # A page-side prefix such as "/api/gen/" matches the route "/api/gen/{name}".
                hit = any(
                    route == path
                    or (path.endswith("/") and route.startswith(path))
                    or re.fullmatch(re.sub(r"\{[^}]+\}", "[^/]+", route), path)
                    for route in self.routes
                )
                self.assertTrue(hit, f"{path} is not served by backend/server.py")

    def test_the_render_is_fetched_through_the_gen_route(self):
        # /api/image answers with a path, not bytes. A client that forgot the second call
        # would show a broken image while curl proved the endpoint answered -- which has
        # happened on this project before and is why the node suite asserts a decode.
        self.assertIn("/api/gen/", self.code)


class TheHostIsNotInThePageTests(unittest.TestCase):
    """`ui/app.js` names paths. The host lives in compiled Rust."""

    @classmethod
    def setUpClass(cls):
        cls.code = strip_code(APP_JS.read_text())

    def test_the_page_names_no_host(self):
        for forbidden in ("http://", "https://", "127.0.0.1", "0.0.0.0", "localhost", "://"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, self.code)

    def test_the_page_makes_no_request_of_its_own(self):
        # Not a style preference. api.py mounts no CORS middleware and must not gain one for
        # a desktop client, because /api* is proxied to the public internet.
        for forbidden in ("fetch(", "XMLHttpRequest", "WebSocket", "EventSource", "import("):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, self.code)

    def test_everything_goes_through_the_four_commands(self):
        called = set(re.findall(r"invoke\(\s*[\"'](\w+)[\"']", self.code))
        self.assertEqual(called, {"api_get", "api_post", "api_bytes", "api_chat"})


class TheRustSidePinsLoopbackTests(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        # The `#[cfg(test)]` module is cut off before scanning. Its whole job is to name
        # addresses that must be REFUSED -- "http://example.com" is in there deliberately --
        # so including it would make the one-host assertion fail on the evidence that the
        # refusal works. The assertion is about what the shipped binary can reach.
        cls.code = strip_code(MAIN_RS.read_text()).split("#[cfg(test)]")[0]
        cls.cargo = CARGO.read_text()

    def test_there_is_exactly_one_host_and_it_is_loopback(self):
        hosts = set(re.findall(r"https?://[\w.\-]+(?::\d+)?", self.code))
        self.assertEqual(hosts, {"http://127.0.0.1:8800"})

    def test_the_four_commands_are_registered(self):
        handler = re.search(r"generate_handler!\[(.*?)\]", self.code, re.S)
        self.assertIsNotNone(handler, "no generate_handler! block")
        registered = set(re.findall(r"\w+", handler.group(1)))
        self.assertEqual(registered, {"api_get", "api_post", "api_bytes", "api_chat"})

    def test_every_command_routes_through_checked(self):
        bodies = re.findall(r"async fn (api_\w+)\((.*?)\n\}\n", self.code, re.S)
        # Naming the four rather than asserting the list is merely non-empty. A regex that
        # matched one of four would satisfy `assertTrue(bodies)` and this test would then be
        # checking a quarter of the surface while reading as though it checked all of it.
        self.assertEqual(sorted(name for name, _ in bodies),
                         ["api_bytes", "api_chat", "api_get", "api_post"],
                         "the set of commands changed -- add it here deliberately")
        for name, body in bodies:
            with self.subTest(command=name):
                self.assertIn("checked(", body,
                              f"{name} builds a URL without going through checked()")

    def test_no_tls_backend_is_compiled_in(self):
        # default-features = false with no TLS feature: the binary cannot open an https
        # connection to a remote host, which is a stronger guarantee than the constant.
        self.assertIn("default-features = false", self.cargo)
        for forbidden in ("native-tls", "rustls", "openssl", "default-tls"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, self.cargo)


class NoSecondPermissionGateTests(unittest.TestCase):
    """The pty gate in `bin/symoneural-cli` is the only one, and stays the only one."""

    def test_neither_half_implements_a_gate(self):
        # `pty` is a substring of `empty`, and this test went red for a `parts.is_empty()` in
        # `describe()` -- the same trap as the MIT rule in `.claude/CLAUDE.md`, where most
        # matches are limits/limited/submit/emits.
        #
        # The fix is to subtract the one English word that collides, NOT to switch to a word
        # boundary. A boundary looks like the obvious answer and is the wrong one twice over:
        # `\b/dev/tty` never matches at all (a boundary needs a word character on one side,
        # and `/` is not one), and every real spelling of the thing being forbidden -- the
        # `openpty` call, the `portable_pty` crate -- is *glued to* another word, so a
        # boundary would skip precisely the cases worth catching while still reading as strict.
        for path in (APP_JS, MAIN_RS):
            code = strip_code(path.read_text())
            for forbidden in ("/dev/tty", "approve", "permission", "symoneural-cli", "pty"):
                with self.subTest(file=path.name, forbidden=forbidden):
                    haystack = code.replace("empty", "") if forbidden == "pty" else code
                    self.assertNotIn(forbidden, haystack,
                                     f"{forbidden} appears in {path.name}")

    def test_the_shell_is_not_touched_from_here(self):
        # The two programs share nothing. If this client ever grows a dependency on the GTK
        # shell, the argument for having both collapses.
        self.assertTrue(SHELL.is_file(), "desktop/shell.py vanished")
        for path in (APP_JS, MAIN_RS, CARGO, CONF):
            with self.subTest(file=path.name):
                self.assertNotIn("shell.py", strip_code(path.read_text()))


class TheCapabilityGrantsExactlyWhatThePageUsesTests(unittest.TestCase):
    """Tauri v2 gates the core plugins, and the failure is silent.

    This is here because it cost a real debugging session. Chat rendered its turn scaffold
    and then nothing -- no tokens, no error box -- while `curl` proved /api/chat was
    streaming `data: {"delta": ...}` frames immediately. The four commands in `main.rs` are
    the *app's own*, so they invoke without a grant; `listen()` is `core:event`, a core
    plugin, and with no `capabilities/` directory at all the listen was simply refused. The
    stream ran to completion into a window that had never been allowed to hear it.

    Nothing about that reads as a permissions problem from the outside, which is exactly why
    it is asserted here rather than left to be rediscovered.
    """

    @classmethod
    def setUpClass(cls):
        cls.page = strip_code(APP_JS.read_text())
        cls.grant = json.loads(CAPABILITY.read_text())

    def test_listening_in_the_page_implies_the_grant_for_it(self):
        if "listen(" not in self.page:
            self.skipTest("the page does not listen for events")
        self.assertIn("core:event:allow-listen", self.grant["permissions"])

    def test_the_capability_targets_the_window_that_exists(self):
        labels = [w.get("label") for w in json.loads(CONF.read_text())["app"]["windows"]]
        for target in self.grant["windows"]:
            with self.subTest(target=target):
                self.assertIn(target, labels,
                              "the capability names a window the config does not create")

    def test_no_permission_here_can_reach_the_network_or_the_disk(self):
        # The design's whole guarantee is that the page names paths and never a host, and
        # that every request is made by compiled Rust through `checked()`. A grant for
        # Tauri's own http, shell, fs or opener plugin would hand the page a second way out
        # that bypasses all of it -- and would do so from a JSON file nobody re-reads.
        for permission in self.grant["permissions"]:
            with self.subTest(permission=permission):
                for escape in ("http", "shell", "fs:", "opener", "process", "default"):
                    self.assertNotIn(escape, permission,
                                     f"{permission} is broader than listening for events")


class TheScrollerLandsOnTheTranscriptTests(unittest.TestCase):
    """`.transcript` declares `overflow-y: auto` and for a while it could never take effect.

    `body` was `min-height: 100vh`, which lets the flex column grow past the viewport; every
    child grows with it, so the transcript box was always exactly as tall as its content and
    had nothing to scroll. The page scrolled instead. Measured with a 100 kB prompt: the
    composer and the Send button went off the bottom of the window, and
    `transcript.scrollTop = transcript.scrollHeight` -- the line in app.js that keeps a stream
    in view -- was writing to an element that does not move.

    Nothing was ever hidden, so this is not the truncation the house rule bars. It is the
    subtler version: a scroller declared on one element and actually happening on another.
    """

    @classmethod
    def setUpClass(cls):
        cls.css = APP_CSS.read_text()
        cls.page = strip_code(APP_JS.read_text())

    def test_the_page_height_is_bounded(self):
        body = re.search(r"\nbody \{(.*?)\n\}", self.css, re.S)
        self.assertIsNotNone(body, "no body rule")
        self.assertIn("height: 100vh", body.group(1))
        self.assertNotIn("min-height: 100vh", body.group(1),
                         "min-height lets the column grow past the viewport again")

    def test_the_flex_chain_can_shrink_below_its_content(self):
        # `min-height: auto` is a flex item's default and refuses to shrink below content, so
        # bounding the body alone buys nothing -- the chain overflows it from the inside.
        for selector in ("main", ".panel"):
            with self.subTest(selector=selector):
                rule = re.search(rf"\n{re.escape(selector)} \{{(.*?)\}}", self.css, re.S)
                self.assertIsNotNone(rule, f"no rule for {selector}")
                self.assertIn("min-height: 0", rule.group(1))

    def test_a_bounded_panel_can_still_reach_all_of_its_content(self):
        # The image panel's content is a render at whatever size the model produced. Bounding
        # the page without a scroller here would put the bottom of a tall PNG -- and the
        # measurement block under it -- out of reach, which IS the data loss the rule bars.
        rule = re.search(r"\n\.panel \{(.*?)\}", self.css, re.S)
        self.assertIn("overflow-y: auto", rule.group(1))

    def test_an_error_scrolls_itself_into_view(self):
        # The transcript is scrolled on send and on each delta; an error arrives after both.
        # Measured: a 422 rendered twelve wheel clicks below the fold, so the window showed a
        # sent turn, no reply and no error -- which reads as "still thinking", not "refused".
        body = re.search(r"function fail\((.*?)\n\}", self.page, re.S)
        self.assertIsNotNone(body, "no fail()")
        self.assertIn("scrollIntoView", body.group(1),
                      "an error nobody scrolls to is an error nobody was shown")


class HonestyRulesTests(unittest.TestCase):
    """The rules from `.claude/CLAUDE.md` that this client is in a position to break."""

    @classmethod
    def setUpClass(cls):
        cls.code = strip_code(APP_JS.read_text())
        # Stripped for the same reason as everything else here: app.css opens by QUOTING the
        # house rule it keeps, so the words "text-overflow" and "ellipsis" appear in the file
        # precisely because there is no such rule in it. Reading the raw text would fail on
        # the comment explaining the compliance.
        cls.css = strip_code(APP_CSS.read_text())

    def test_a_failed_turn_leaves_no_dangling_user_role_in_the_history(self):
        # /api/chat is handed the transcript by the client, and a turn can fail two ways: an
        # {"error"} frame arriving inside an otherwise-successful 200 stream, or the invoke
        # itself rejecting. If the user turn were appended at send time, either failure would
        # leave it there with no assistant reply, and the NEXT send would carry two user roles
        # in a row to a chat template that does not expect them -- a bug that only shows up on
        # the turn after the one that actually broke.
        #
        # The invariant that prevents it: `history` is written in exactly one place, the
        # `done` frame, and both roles are pushed together. Counting the call sites is the
        # cheapest way to assert that, and it fails the moment somebody adds a second one.
        pushes = re.findall(r"history\.push\(", self.code)
        self.assertEqual(len(pushes), 1,
                         "history is written in more than one place; see `pendingUser`")
        self.assertIn("pendingUser", self.code)

    def test_the_measured_rate_is_displayed_and_never_recomputed(self):
        self.assertIn("tok_per_s", self.code)
        # A browser-clock rate wearing the server's name. Any of these would be that.
        for forbidden in ("tokens / ", "tokens/", "/ seconds", "/seconds", "Date.now()",
                          "performance.now()"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, self.code)

    def test_the_three_valued_check_has_three_renderings(self):
        # true, false and null must land in three different places. If the null branch were
        # folded into either of the others, an unconfirmed result would be shown as a verdict.
        self.assertIn("unconfirmed", self.code)
        self.assertIn("passed === true", self.code)
        self.assertIn("passed === false", self.code)

    def test_performed_false_is_not_silence(self):
        # A blank space where a verdict belongs reads as "fine".
        self.assertIn("performed !== true", self.code)

    def test_the_status_dot_starts_unread(self):
        # No decorative indicators: the dot may not carry a colour before a real read.
        self.assertIn('data-state="unread"', INDEX.read_text())
        self.assertIn("api_get", self.code)
        self.assertNotIn('dot.dataset.state = "up"', self.code.split("readStatus")[0])

    def test_nothing_is_truncated_by_css(self):
        for forbidden in ("text-overflow", "ellipsis", "nowrap", "-webkit-line-clamp"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, self.css)

    def test_user_text_reaches_the_dom_as_text(self):
        for forbidden in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write",
                          "eval("):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, self.code)


class ScaffoldTests(unittest.TestCase):
    """Hand-written, no npm, and a policy that names no network origin."""

    @classmethod
    def setUpClass(cls):
        cls.conf = json.loads(CONF.read_text())

    def test_there_is_no_npm_anywhere_in_the_client(self):
        for absent in ("package.json", "package-lock.json", "node_modules",
                       "yarn.lock", "pnpm-lock.yaml"):
            with self.subTest(absent=absent):
                self.assertFalse((CLIENT / absent).exists(),
                                 f"{absent} appeared; the scaffold is hand-written on purpose")

    def test_the_frontend_is_the_static_directory(self):
        self.assertEqual(self.conf["build"]["frontendDist"], "../ui")
        # No dev server and no build step: there is nothing to run before cargo.
        self.assertNotIn("beforeDevCommand", self.conf.get("build", {}))
        self.assertNotIn("devUrl", self.conf.get("build", {}))

    def test_the_page_can_reach_the_commands_without_a_bundler(self):
        self.assertTrue(self.conf["app"]["withGlobalTauri"])

    def test_the_policy_names_no_network_origin(self):
        csp = self.conf["app"]["security"]["csp"]
        self.assertIn("default-src 'self'", csp)
        # ipc.localhost is Tauri's own command channel, not a network host. Anything else
        # with a scheme would be this client reaching past the Rust side.
        hosts = [h for h in re.findall(r"https?://[\w.\-]+(?::\d+)?", csp)
                 if h != "http://ipc.localhost"]
        self.assertEqual(hosts, [])
        self.assertIn("img-src 'self' data:", csp)

    def test_the_declared_icon_is_on_disk(self):
        for icon in self.conf["bundle"]["icon"]:
            with self.subTest(icon=icon):
                self.assertTrue((CONF.parent / icon).is_file())

    def test_the_licence_and_readme_are_present(self):
        for name in ("LICENSE", "README.md"):
            with self.subTest(name=name):
                self.assertTrue((CLIENT / name).is_file())
        self.assertIn("All rights reserved", (CLIENT / "LICENSE").read_text())


class StripCodeTests(unittest.TestCase):
    """The instrument the negative assertions above depend on."""

    def test_comments_go_and_strings_stay(self):
        self.assertEqual(strip_code('a // fetch(\nb').strip(), "a \nb")
        self.assertEqual(strip_code('a /* fetch( */ b'), "a  b")
        self.assertIn('"fetch("', strip_code('x = "fetch(" // gone'))

    def test_a_url_is_not_cut_at_its_double_slash(self):
        # The failure this function exists to avoid.
        self.assertIn("http://127.0.0.1:8800", strip_code('const API = "http://127.0.0.1:8800";'))

    def test_rust_raw_strings_survive(self):
        self.assertIn('r#"{"detail":"x"}"#', strip_code('let s = r#"{"detail":"x"}"#;'))

    def test_the_client_source_is_not_all_comment(self):
        # A stripper with a bug that ate everything would make every assertNotIn above pass.
        # This is the guard against a green suite that measured nothing.
        for path in (APP_JS, MAIN_RS):
            with self.subTest(file=path.name):
                stripped = strip_code(path.read_text())
                self.assertGreater(len(stripped), 2000)
                self.assertIn("invoke" if path is APP_JS else "reqwest", stripped)


if __name__ == "__main__":
    unittest.main()
