"""`docs/SERVER-READY.md` must cover every row the roster declares.

Task #73's title is "every application online", and the document is the evidence for it: a
measured reading of every row in `apps/ROSTER.md`, asked on the address the roster gives it.
A reading is only worth having while it still describes the roster it was taken against, and
the way that stops being true is not a bug anyone commits -- it is a **new row landing and
nobody re-measuring**. Then the document says "all thirteen rows answer" and the rack has
fourteen, which is exactly the shape of the published-figure failure `.claude/CLAUDE.md`
warns about in its own voice: a number carried forward past the tree it was true of.

So this suite is a tripwire, and going red when a row is added is the **feature**:

    add a row to ROSTER.md  ->  this suite goes red  ->  re-take the reading, update the doc

That is a nuisance for about ten minutes and it is the entire point. Do not silence it by
loosening the comparison; re-measure and stamp, which is the rule everywhere else in this repo.

## Dry by default, live on request

`RowCoverageTests` reads two files off the disk. No server, no GPU, no network -- so it runs
in the ordinary `pytest apps/ -q` sweep and cannot be the reason a suite is slow.

`LiveProbeTests` actually asks a running server and is **skipped unless
`SYMONEURAL_SERVER_READY_BASE` names one**. Point it at a spare port, never at the service on
:8800: probing the deployed instance measures what was last deployed, not what is on disk,
and that is the same rule `tests/frontend.mjs` is run under.

    cd backend && python3 -m uvicorn api:app --port 8878          # a spare port
    SYMONEURAL_SERVER_READY_BASE=http://127.0.0.1:8878 \
        python3 -m pytest apps/test_server_ready.py -q

The doc is not imported and the API is not imported. `api.py` is the serving module: importing
it builds every rate limiter, resolves the GPU governor and mounts `site/`, which is not
something a documentation assertion has any business doing.
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import unittest
import urllib.error
import urllib.request

from apps import roster

REPO = pathlib.Path(__file__).resolve().parents[2]
DOC = REPO / "docs" / "SERVER-READY.md"

# The environment variable that turns the live half on, and the base URL it carries.
BASE_ENV = "SYMONEURAL_SERVER_READY_BASE"


def _table_ids(text: str) -> list[str]:
    """The id column of every markdown table row in the document, in file order.

    Deliberately narrow: a row is `| <id> | <href> |...`, the id is bare (no backticks, no
    link) and the href starts with a slash. That last condition is what keeps the header
    separator, the environment table at the top and any future prose table out of this list
    without needing to know where the reading's table begins.
    """
    return [m.group(1) for m in
            re.finditer(r"^\|\s*([A-Za-z][\w-]*)\s*\|\s*(/\S*)\s*\|", text, re.M)]


def _uncovered(row_ids, text: str) -> list[str]:
    """Roster rows the document's table does not carry. Empty means covered."""
    covered = set(_table_ids(text))
    return [rid for rid in row_ids if rid not in covered]


class RowCoverageTests(unittest.TestCase):
    """The dry half: does the document still describe the roster on disk?"""

    def setUp(self):
        self.assertTrue(DOC.is_file(),
                        f"{DOC} is missing -- #73's reading is the deliverable, not this test")
        self.text = DOC.read_text()
        self.rows = roster.rows()

    def test_the_comparison_was_given_something_to_compare(self):
        """The vacuity guard, and it is not ceremony.

        `_uncovered([], "")` is `[]`, so every assertion below passes against an empty roster
        and an empty document. Two of #73's own checks have already been retired for exactly
        this: one was `grep ^| ...`, a regex whose empty right alternative matched the empty
        string, so `touch` scored it green. A check that cannot fail is worse than no check,
        because it archives the task.
        """
        self.assertTrue(self.rows, "roster.rows() returned nothing")
        self.assertTrue(_table_ids(self.text),
                        "no `| id | /href |` rows parsed out of the document; the table was "
                        "reformatted and this parse must be rewritten, not deleted")

    def test_the_parse_finds_a_planted_row_and_misses_a_decorated_one(self):
        """Runs on synthetic text, so it runs identically on a machine where the doc is wrong.

        The decorated case is the one that matters: the id column has to stay bare. #73 carries
        `check: grep \\n\\|\\s*gateway\\s*\\| -- docs/SERVER-READY.md`, and `\\s*` does not match
        a backtick -- so formatting the ids as code would read better in prose and would
        silently fail the task's own check.
        """
        self.assertEqual(_table_ids("| gateway | /gateway.html | 200 |\n"), ["gateway"])
        self.assertEqual(_table_ids("| `gateway` | /gateway.html | 200 |\n"), [])
        self.assertEqual(_table_ids("| id | href | page |\n|---|---|---|\n"), [])

        self.assertEqual(_uncovered(["gateway", "sigils"], "| gateway | /gateway.html |\n"),
                         ["sigils"])
        self.assertEqual(_uncovered(["gateway"], "| gateway | /gateway.html |\n"), [])

    def test_every_roster_row_appears_in_the_reading(self):
        missing = _uncovered([r["id"] for r in self.rows], self.text)
        self.assertEqual(missing, [], (
            f"{DOC.name} does not carry a reading for {missing}. A row was added to "
            "ROSTER.md after the document was measured. Re-take the reading against a "
            "server on a spare port and update the table -- do not add the rows by hand, "
            "and do not loosen this comparison."))

    def test_the_reading_names_the_commit_it_was_taken_on(self):
        """A figure with no SHA beside it cannot be checked, only believed -- and this repo has
        published a test count that was never true of the commit it sat next to."""
        self.assertRegex(self.text, r"`[0-9a-f]{7,40}`",
                         "the reading does not name the commit it was taken on")

    def test_the_reading_does_not_claim_more_rows_than_the_roster_has(self):
        """The opposite drift: a row deleted from ROSTER.md leaves a stale line in the doc."""
        ids = [r["id"] for r in self.rows]
        stale = sorted(set(_table_ids(self.text)) - set(ids))
        self.assertEqual(stale, [], (
            f"{DOC.name} carries readings for {stale}, which are not roster rows. A row was "
            "removed from ROSTER.md; the document is now describing a rack that does not "
            "exist."))


@unittest.skipUnless(os.environ.get(BASE_ENV),
                     f"set {BASE_ENV}=http://127.0.0.1:<spare-port> to re-take the reading")
class EveryRosterRowAnswersTests(unittest.TestCase):
    """The live half: every roster row answers 200 on the href the roster gives for it.

    This is the assertion the document's headline sentence rests on. It is skipped in the
    ordinary sweep because it needs a server, and it must be pointed at one you started --
    not at :8800, which serves what was last deployed.
    """

    @classmethod
    def setUpClass(cls):
        cls.base = os.environ[BASE_ENV].rstrip("/")

    def _get(self, path: str):
        req = urllib.request.Request(self.base + path, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    def test_every_row_serves_its_href(self):
        bad = []
        for row in roster.rows():
            code, body = self._get(row["href"])
            if code != 200 or not body:
                bad.append(f'{row["id"]} {row["href"]} -> {code} ({len(body)}B)')
        self.assertEqual(bad, [], "roster rows that did not serve their page: " + "; ".join(bad))

    def test_the_status_rack_renders_exactly_the_roster(self):
        """Not a subset and not a superset -- and in the roster's order, which is load-bearing:
        the client-side rack and `build_rack.py`'s fallback markup agree only if it holds."""
        code, body = self._get("/api/status")
        self.assertEqual(code, 200, body[:400])
        rendered = [u["id"] for u in json.loads(body)["units"]]
        self.assertEqual(rendered, [r["id"] for r in roster.rows()])


if __name__ == "__main__":
    # At the END of the file, with backend/ on the path: see the block at the foot of
    # apps/test_streamer_migration.py for what a misplaced one of these hides.
    import sys

    sys.path.insert(0, str(REPO / "backend"))
    unittest.main()
