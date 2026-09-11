"""The GPU lease comes back when the visitor closes the tab -- and the gate that broke it.

R-173's structural fix moved `gpu.hold("chat")` out of the streaming generator and into the
handler, so a contended card answers **503 with a body** instead of a bodyless 500 after the
headers had already said 200. That is asserted here as well, because it is cheap.

The interesting half is the one that fix opened up. Once the lease is acquired in the handler,
something has to give it back, and `finally` inside the generator is not enough: uvicorn's
`send` **silently discards on a dead client** rather than raising, so an abandoned stream is
resumed forever and its `finally` never runs. `/api/chat` therefore arms a watchdog that polls
`request.is_disconnected()`.

**And that watchdog is only able to answer because `RackPowerGate` is raw ASGI.** Starlette's
`BaseHTTPMiddleware` -- which is what the `@app.middleware("http")` decorator builds -- runs the
endpoint against a *substitute* receive channel, so `http.disconnect` never reaches the
endpoint's own `Request` and `is_disconnected()` never returns True. Measured 2026-08-21, one
handler, one abandoned socket, four stacks:

    bare app                 -> RELEASED    + GZipMiddleware      -> RELEASED
    + BaseHTTPMiddleware     -> LEAKED      + raw-ASGI rack gate  -> RELEASED

So the two halves of this file are one fact: the mounting style of a middleware that has
nothing to do with chat decides whether chat leaks the card. `backend/SMOKE-lease-503.md` has
both runs and the A/B against the tree before the fix.

## Dry and live, and the live half is not optional

The source assertions cannot see whether any of it works -- `grep` asks what is written, not
what happens, which is #94's lesson in this repo's own words. `TheLeaseComesBackTests` starts
`tests/chat-contention-harness.py` on an ephemeral port with a **stub governor**, abandons a
real socket, and reads the governor's own log for a `release chat`. No GPU, no card, no lock:
the stub is what makes it safe to run beside the live service, which is the only way anyone
will run it.
"""
from __future__ import annotations

import pathlib
import re
import socket
import subprocess
import sys
import tempfile
import time
import unittest

REPO = next(_p for _p in pathlib.Path(__file__).resolve().parents if (_p / "backend" / "server.py").is_file())
API = REPO / "backend" / "server.py"
HARNESS = REPO / "tests" / "chat-contention-harness.py"


# ------------------------------------------------------------------ dry: what is written


class TheGateIsRawAsgiTests(unittest.TestCase):
    """`RackPowerGate` must never go back to `@app.middleware("http")`.

    Read as source rather than imported: `api.py` is the serving module, and importing it
    builds every rate limiter, resolves the GPU governor and mounts `site/` -- which is why
    nothing else under `apps/` imports it either.
    """

    def setUp(self) -> None:
        self.src = API.read_text()

    def test_no_basehttpmiddleware_is_registered(self):
        """The decorator IS `BaseHTTPMiddleware`; that is the whole trap.

        It reads like a lightweight hook and it replaces the receive channel. If a future
        surface needs a middleware, write it as a class like `RackPowerGate` -- or measure
        the disconnect path again and update `SMOKE-lease-503.md`.
        """
        # A *registration*, not a mention: `RackPowerGate`'s own docstring names both, which
        # is the point of it, so a substring test here would go red on its own explanation.
        decorated = [ln for ln in self.src.splitlines()
                     if ln.lstrip().startswith("@app.middleware(")]
        self.assertEqual(decorated, [], f"BaseHTTPMiddleware is back: {decorated}")
        self.assertNotIn("from starlette.middleware.base import", self.src)

    def test_the_gate_is_a_class_that_passes_receive_straight_through(self):
        self.assertIn("class RackPowerGate:", self.src)
        self.assertIn("async def __call__(self, scope: Scope, receive: Receive, send: Send)",
                      self.src)
        self.assertIn("app.add_middleware(RackPowerGate)", self.src)
        # Every exit from __call__ hands the ORIGINAL receive onward. A wrapped or buffered
        # receive here would reintroduce the defect with none of the warning signs.
        self.assertEqual(self.src.count("self.app(scope, receive, send)"), 2)

    def test_the_gate_still_decides_exactly_what_it_decided_before(self):
        """Converted, not rewritten. Same prefix walk, same 503, same Retry-After.

        `controlboard/test_rackpower.py` asserts the rack reading and this gate ship
        together; this asserts the conversion did not quietly change the verdict.
        """
        self.assertIn("rackpower.unit_for_path(", self.src)
        self.assertIn('rackpower.is_disabled(unit_id)', self.src)
        self.assertIn('"Retry-After": "300"', self.src)
        self.assertIn("has been taken off the rack by an operator", self.src)

    def test_the_measurement_that_justifies_the_class_is_written_down(self):
        """A bare `class RackPowerGate` invites tidying back into a decorator.

        The docstring carries the four-stack reading, so the next agent finds the reason at
        the point of temptation rather than in a commit message they will not read.
        """
        self.assertIn("Do not convert it back", self.src)
        self.assertIn("LEAKED", self.src)


class TheWatchdogIsWiredTests(unittest.TestCase):
    def setUp(self) -> None:
        self.src = API.read_text()

    def test_the_watchdog_holds_a_strong_reference_to_itself(self):
        """The loop keeps only a weak reference to a task.

        A watchdog created inside a request frame can be garbage-collected before it ever
        runs, and the symptom is a lease that leaks *sometimes* -- the worst shape of bug
        this handler could have.
        """
        self.assertIn("_WATCHDOGS", self.src)
        self.assertIn("guard.add_done_callback(_WATCHDOGS.discard)", self.src)

    def test_the_release_is_idempotent(self):
        """Watchdog and generator both call it, and on a clean close both get there.

        Asserted as an *ordering*, not as the presence of two lines. Setting the flag
        after the await is the whole race: the watchdog enters `drop_lease`, suspends
        on `__aexit__`, the generator's `finally` calls in behind it, finds the flag
        still clear, and the card is released twice -- a second `release chat` against
        a lease that no longer exists, which is how one surface hands another's lock
        away. A substring test for `if released.is_set():` stays green straight
        through that reordering, and this file has already been bitten once by an
        assertion that passed on the broken tree (see the test below).
        """
        block = re.search(
            r"async def drop_lease\(\):\n"
            r"(?:[ \t]*(?:#.*|\"\"\".*)?\n)*"
            r"[ \t]*if released\.is_set\(\):\n"
            r"[ \t]*return\n"
            r"[ \t]*released\.set\(\)\n"
            r"[ \t]*await lease\.__aexit__\(", self.src)
        self.assertIsNotNone(
            block,
            "drop_lease must set the flag BEFORE awaiting __aexit__, so a second "
            "caller arriving during that await finds it set and returns")

    def test_the_orphaned_anticipate_task_is_cancelled_when_the_lease_is_refused(self):
        """R-173's own defect: `anticipate()` starts before `__aenter__`, so a 503 from
        `hold()` used to leave it running and never awaited.

        Asserted as the *acquire-failure* path, not as a bare `thinking.cancel()` anywhere
        in the file -- the handler has always cancelled it on the RavenCalc branch, so the
        loose form passed on the tree that still had the bug. A check that goes green
        without the work being done is worse than no check: it archives the task.
        """
        block = re.search(
            r"await lease\.__aenter__\(\)\n"
            r"\s*except BaseException:\n"
            r"(?:\s*#.*\n)*"
            r"\s*thinking\.cancel\(\)\n"
            r"\s*raise\n", self.src)
        self.assertIsNotNone(
            block, "a refused acquire must cancel the RavenCalc task before it propagates")


# ------------------------------------------------------------------ live: what happens


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _abandon(port: int) -> None:
    """Send a chat request and hang up without reading a byte."""
    body = b'{"prompt":"hello","max_tokens":4096}'
    s = socket.create_connection(("127.0.0.1", port), timeout=5)
    s.sendall(b"POST /api/chat HTTP/1.1\r\nHost: x\r\n"
              b"Content-Type: application/json\r\n"
              b"Content-Length: %d\r\n\r\n" % len(body) + body)
    time.sleep(0.05)
    s.close()


class TheLeaseComesBackTests(unittest.TestCase):
    """One harness, two visitors: one who leaves, one who stays.

    The second case is not padding. A watchdog that false-positives on a live-but-unhurried
    reader would drop the lease mid-answer and truncate a real visitor's reply, which is a
    worse bug than the leak it was written to fix.
    """

    proc: subprocess.Popen | None = None

    @classmethod
    def setUpClass(cls) -> None:
        cls.port = _free_port()
        cls.tmp = tempfile.mkdtemp(prefix="symoneural-lease-")
        cls.log = pathlib.Path(cls.tmp) / "governor.log"
        env = {**__import__("os").environ,
               "SYMONEURAL_HARNESS_MODE": "grant",
               "SYMONEURAL_HARNESS_LOG": str(cls.log)}
        cls.proc = subprocess.Popen(
            [sys.executable, str(HARNESS), str(cls.port)],
            env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        deadline = time.time() + 30
        while time.time() < deadline:
            try:
                with socket.create_connection(("127.0.0.1", cls.port), timeout=0.5):
                    return
            except OSError:
                time.sleep(0.2)
        raise AssertionError("the harness never bound its port")

    @classmethod
    def tearDownClass(cls) -> None:
        if cls.proc is not None:
            cls.proc.terminate()
            try:
                cls.proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                cls.proc.kill()

    def _log_lines(self) -> list[str]:
        if not self.log.exists():
            return []
        return [ln.strip() for ln in self.log.read_text().splitlines() if ln.strip()]

    def _wait_for(self, n: int, timeout: float = 15.0) -> list[str]:
        deadline = time.time() + timeout
        while time.time() < deadline:
            lines = self._log_lines()
            if len(lines) >= n:
                return lines
            time.sleep(0.25)
        return self._log_lines()

    def test_1_an_abandoned_stream_returns_the_card(self):
        """Against the tree before this fix the log reads `acquire chat` and stops there.

        The stub governor writes a line per call, so a leaked lease is an acquire with no
        matching release -- readable from outside the process, which is the point: nothing
        inside the app can be trusted to report its own leak.
        """
        _abandon(self.port)
        lines = self._wait_for(2)
        self.assertEqual(lines, ["acquire chat", "release chat"],
                         "the lease was not returned after the client hung up")

    def test_2_a_live_but_unhurried_reader_is_never_dropped(self):
        body = b'{"prompt":"hello","max_tokens":4096}'
        s = socket.create_connection(("127.0.0.1", self.port), timeout=5)
        s.sendall(b"POST /api/chat HTTP/1.1\r\nHost: x\r\n"
                  b"Content-Type: application/json\r\n"
                  b"Content-Length: %d\r\n\r\n" % len(body) + body)
        s.settimeout(1.0)
        start, total, closed_early = time.time(), 0, False
        # Well past the 0.25 s poll interval and past the ~0.5 s a real disconnect takes to
        # be noticed, so a watchdog that fires on a live socket has ample room to do it.
        while time.time() - start < 4:
            try:
                chunk = s.recv(4096)
            except socket.timeout:
                continue
            if not chunk:
                closed_early = True
                break
            total += len(chunk)
        s.close()
        self.assertFalse(closed_early, "the server hung up on a client that was still reading")
        self.assertGreater(total, 0, "no tokens reached a live client")
        lines = self._wait_for(4)
        self.assertEqual(lines, ["acquire chat", "release chat",
                                 "acquire chat", "release chat"],
                         "the second visitor's lease did not pair")


if __name__ == "__main__":
    unittest.main()
