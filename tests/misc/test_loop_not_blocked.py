"""The event loop must keep running while an engine spawn is being recorded.

`record_engine` shells out to `gpu-governor.sh engine <pid>`. It shipped as a SYNC def calling
`subprocess.run(..., timeout=10)` from two coroutines, which stalls the entire loop for as
long as the governor takes -- no other request, no streaming token, and not `/api/status`.

The consequence was self-inflicted and specific: `tools/lib/watch.py` polls `/api/status` every
five minutes, so every engine spawn would have read as an outage. A monitor whose first week
is false alarms is a monitor nobody reads.

A test that only asserts `record_engine` returns would pass against the blocking version --
the vacuous guard this branch keeps catching. This asserts the property that actually differs:
**other coroutines make progress while it runs.**
"""
from __future__ import annotations

import asyncio
import os
import pathlib
import sys
import time
import unittest

ROOT = next(_p for _p in pathlib.Path(__file__).resolve().parents if (_p / "backend" / "server.py").is_file())
sys.path.insert(0, str(ROOT / "backend"))

BLOCK_S = 0.6          # what the fake governor call costs
TICK_S = 0.02          # how often the competing coroutine wants to run


class TheLoopSurvivesAnEngineSpawn(unittest.TestCase):

    def setUp(self):
        import server as api
        self.api = api
        self._real_run = api.subprocess.run

    def tearDown(self):
        self.api.subprocess.run = self._real_run

    def _ticks_during_record(self) -> int:
        """Count how many times a competing coroutine is scheduled while recording."""
        api = self.api

        def slow_run(*a, **k):                      # the governor, made slow and blocking
            time.sleep(BLOCK_S)
            class R:  # noqa: D401
                returncode = 0
            return R()
        api.subprocess.run = slow_run

        async def scenario() -> int:
            ticks = 0

            async def ticker():
                nonlocal ticks
                deadline = time.monotonic() + BLOCK_S * 1.5
                while time.monotonic() < deadline:
                    await asyncio.sleep(TICK_S)
                    ticks += 1

            t = asyncio.create_task(ticker())
            await api.record_engine(os.getpid())
            t.cancel()
            try:
                await t
            except asyncio.CancelledError:
                pass
            return ticks

        return asyncio.run(scenario())

    def test_other_coroutines_run_while_the_spawn_is_recorded(self):
        ticks = self._ticks_during_record()
        # Offloaded, the ticker gets roughly BLOCK_S / TICK_S turns. Blocking, it gets none
        # until the subprocess returns. The threshold is deliberately far below the ideal so
        # this measures "the loop moved at all" rather than scheduler precision.
        self.assertGreater(
            ticks, 5,
            f"only {ticks} coroutine turns happened while record_engine ran. The loop was "
            "blocked: record_engine is executing the governor synchronously instead of via "
            "asyncio.to_thread, so every engine spawn stalls the whole server")

    def test_record_engine_is_a_coroutine(self):
        self.assertTrue(asyncio.iscoroutinefunction(self.api.record_engine),
                        "record_engine is not async, so its call sites cannot await it and "
                        "any offloading inside it is unreachable")


if __name__ == "__main__":
    unittest.main()
