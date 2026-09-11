"""`ROSTER.md` reconciled against everything else that names a rack row.

The roster used to live in four places that could disagree: `backend/apps/` on disk, the
hand-written `Unit(...)` rows in `api.py:build_status()`, `TOGGLEABLE` in
`apps/controlboard`, and `EXPECTED` in `apps/test_status_rack.py`. Nothing compared them, so
each was believed on its own -- and three lists that disagree is the three-state-documents
failure with a different filename.

`ROSTER.md` is the fifth copy, and adding a copy only helps if something checks them against
each other. That is this file. Note what it deliberately does **not** do: it does not derive
`EXPECTED` from the roster, and it does not derive `TOGGLEABLE` from it either. Both are
hand-typed on purpose -- a tripwire wired to the thing it is watching stops being a tripwire,
and the defect that started all of this was code disagreeing with its own comment. Two
independent copies plus a test that they match is the check. One copy plus a derivation is a
tautology that passes forever.

`api.py` is read as source, never imported, for the reason `test_status_rack.py` gives: the
import builds every rate limiter, resolves the GPU governor and mounts `site/`. Its AST
helpers are imported from there rather than copied, so there is one reader of
`build_status()` and not two of them drifting apart.
"""
from __future__ import annotations

import pathlib
import re
import unittest

from apps import roster
from apps.test_status_rack import EXPECTED, _row_id, _unit_calls

REPO = pathlib.Path(__file__).resolve().parents[2]
APPS = REPO / "backend" / "apps"

#: `api.py` overrides exactly one field on one row at the call site:
#: `Unit(**{**streamer.status(), "bus": "net"})`. The roster records the row as it renders --
#: `net`, because an IPTV surface is bound by the network -- so the module's own `cpu` is a
#: known disagreement rather than a failure. Named here so that a SECOND override, or this one
#: moving to another field, fails instead of being absorbed.
KNOWN_OVERRIDES = {("streamer", "bus"): ("cpu", "net")}


def _module_rows() -> dict:
    """The rows a surface module publishes, read from what `api.py` actually spreads in.

    Which rows those are is a reading of `build_status()`, not a guess from what happens to
    be importable: `Unit(**sigils.status())` is a module row, `Unit(id="coder", ...)` is one
    `api.py` builds itself out of `coder.unit_state()`. Guessing by importability gets that
    wrong -- `apps.coder` has a `status()` and it is the CLI session view, which takes a
    token and a peer address and is not a rack row at all.
    """
    import importlib
    published = {}
    for call in _unit_calls():
        if not any(kw.arg is None for kw in call.keywords):
            continue                          # a literal row; nothing to compare against
        row_id = _row_id(call)
        module = None
        for dotted in (f"apps.{row_id}", f"apps.studio.plugins.{row_id}"):
            try:
                module = importlib.import_module(dotted)
                break
            except ImportError:
                continue
        assert module is not None, f"api.py spreads {row_id}.status() but it will not import"
        published[row_id] = module.status()
    return published


def _router_paths() -> set[str]:
    """Every path declared by a route decorator anywhere in this repo's routers.

    Read as SOURCE and never imported, for the reason `test_status_rack.py` states: importing
    the serving module builds every rate limiter, resolves the GPU governor and mounts
    `site/`. The same discipline is applied to the routers under `apps/`.

    It exists because a rack href can be served by a ROUTER rather than by a literal decorator
    in `api.py` -- `/demo/dispatchos` is the first one -- and grepping only `api.py` for it
    reports a working surface as unrouted.

    **Prefixes are deliberately not resolved and this set is deliberately not complete.** A
    router included at `/api/dispatchos` declares its routes as `"/status"`, so what lands
    here is `/status` and not the mounted path. Reconstructing the mounted paths means
    matching every `include_router(module.name, prefix=...)` to the file that defines
    `name` -- a second, weaker copy of the route table, which is the exact thing
    `apps/route_matrix.py` exists to argue against building. This set is used for ONE
    question, asked of hrefs the roster declares: is this page path declared by some router
    at all. A page route is mounted without a prefix (`app.include_router(ui_router)`), so
    its literal is what appears here, which is what makes the narrow question answerable
    from a narrow scan. Do not widen the caller without widening this.
    """
    paths: set[str] = set()
    decorator = re.compile(
        r"@[A-Za-z_][A-Za-z_0-9]*\.(?:get|post|put|patch|delete|websocket)"
        r"\(\s*[fr]?[\"']([^\"']*)[\"']")
    for f in [REPO / "backend" / "api.py",
              *sorted((REPO / "backend" / "apps").rglob("routes.py"))]:
        for m in decorator.finditer(f.read_text(encoding="utf-8")):
            if m.group(1).startswith("/"):
                paths.add(m.group(1))
    return paths


class RosterParsesTests(unittest.TestCase):
    def test_the_roster_reads_and_is_not_empty(self):
        rows = roster.rows()
        # 14 until the gateway fold, 2026-08-22; 13 until the Studio fold, 2026-08-29, which
        # took `train` and `exp` under `studio`; and 12 rather than 11 because the same change
        # finally WROTE DOWN `dispatchos`, which `build_status()` had been building since #95
        # while every description of the rack omitted it. The slot total on the next line
        # moves with this one -- the two must always move together or the roster is claiming
        # units its own table does not carry.
        self.assertEqual(len(rows), 12)
        # 21 until 2026-08-22, when gateway's 1U was folded into the miner row; 20 until
        # 2026-08-29, when train's 2U and exp's 1U were folded into studio and dispatchos's
        # 1U was added -- net minus two. A fold gives a slot BACK, which is the opposite
        # direction from most changes to this number and the reason it is worth a comment:
        # the one-screen budget in .claude/HANDOVER.md §0 was measured against fourteen rows,
        # so twelve is comfortably inside what was measured rather than past it.
        self.assertEqual(roster.slots(), 18)

    def test_a_malformed_row_raises_instead_of_being_skipped(self):
        """The failure mode that would make the roster a fourth disagreeing list.

        A parser that skips a line it cannot read loses a rack row silently: the symptom is
        a row missing from the fallback, not an error anybody sees.
        """
        head = "| id | label | slot | bus | href | implementation | toggle |\n"
        good = "| chat | C | 1U | gpu | /c.html | backend/api.py | yes |\n"
        for bad, why in [
            ("| chat | C | 1U | gpu | /c.html | backend/api.py |\n", "six columns"),
            ("| chat | C | 1X | gpu | /c.html | backend/api.py | yes |\n", "slot not NU"),
            ("| chat | C | 1U | usb | /c.html | backend/api.py | yes |\n", "unknown bus"),
            ("| chat | C | 1U | gpu | c.html | backend/api.py | yes |\n", "relative href"),
            ("| chat | C | 1U | gpu | /c.html | backend/api.py | maybe |\n", "toggle"),
            ("| Chat | C | 1U | gpu | /c.html | backend/api.py | yes |\n", "capital in id"),
            ("| chat |  | 1U | gpu | /c.html | backend/api.py | yes |\n", "empty label"),
            (good + good, "duplicate id"),
            ("", "header and no rows"),
        ]:
            with self.subTest(why=why):
                tmp = pathlib.Path(self.enterContext(_tempfile()))
                tmp.write_text(head + bad)
                with self.assertRaises(roster.RosterError):
                    roster.rows(tmp)

    def test_a_file_with_no_table_raises(self):
        tmp = pathlib.Path(self.enterContext(_tempfile()))
        tmp.write_text("# not a roster\n\nprose only.\n")
        with self.assertRaises(roster.RosterError):
            roster.rows(tmp)
        with self.assertRaises(roster.RosterError):
            roster.excluded(tmp)


class RosterMatchesApiTests(unittest.TestCase):
    def test_the_ids_and_their_order_match_build_status(self):
        """Order matters: it is the order the rack renders, so the fallback and the live
        markup agree only if both walk the same sequence."""
        self.assertEqual([r["id"] for r in roster.rows()],
                         [_row_id(call) for call in _unit_calls()])

    def test_the_ids_match_the_hand_typed_tripwire(self):
        """Two hand-typed lists, compared. Adding a row means editing both, on purpose --
        see this file's docstring on why neither is derived from the other."""
        self.assertEqual([r["id"] for r in roster.rows()], EXPECTED)

    def test_every_field_matches_the_module_that_publishes_the_row(self):
        published_rows = _module_rows()
        # `exp` left this list on 2026-08-29 and `dispatchos` joined it, and the two changes
        # are unrelated despite landing together. `exp` left because its row was folded under
        # `studio` -- `api.py` still reads `exp.status()`, but it spreads the result onto a
        # `SubUnit` now, and this list is about TOP-LEVEL rows built by spreading a module's
        # dict. `dispatchos` joined because it had been spread that way since #95 and this
        # hand-typed list, like every other description of the rack, had never been told.
        self.assertEqual(sorted(published_rows),
                         ["dispatchos", "live", "project", "sigils", "streamer", "studio"],
                         "the set of rows api.py spreads from a module changed")
        for row in roster.rows():
            published = published_rows.get(row["id"])
            if published is None:
                continue                     # a row `api.py` builds itself; covered above
            for field in ("label", "slot", "bus", "href"):
                expected, actual = row[field], published.get(field)
                override = KNOWN_OVERRIDES.get((row["id"], field))
                with self.subTest(row=row["id"], field=field):
                    if override:
                        self.assertEqual((actual, expected), override,
                                         "the one known call-site override changed; read "
                                         "KNOWN_OVERRIDES before editing either side")
                    else:
                        self.assertEqual(actual, expected)


class RosterMatchesDiskTests(unittest.TestCase):
    def test_every_implementation_path_exists(self):
        for row in roster.rows():
            with self.subTest(row=row["id"]):
                self.assertTrue((REPO / row["implementation"]).exists(),
                                f"{row['id']} says it lives at {row['implementation']}")

    def test_every_href_resolves_to_a_page_or_a_route(self):
        """The reason `voice` has no row: `status()` is correct and `/voice.html` does not
        exist, so the row would be a dead link on the front page of a live site."""
        source = (REPO / "backend" / "api.py").read_text()
        for row in roster.rows():
            href = row["href"]
            with self.subTest(row=row["id"], href=href):
                if href.endswith(".html"):
                    self.assertTrue((REPO / "site" / href.lstrip("/")).is_file(),
                                    f"the rack links to {href}, which is not in site/")
                elif href == "/demo/dispatchos":
                    # Routed by `apps/dispatchos/routes.py`, not by a literal decorator in
                    # api.py, so the source grep below cannot see it and would report a
                    # working surface as an unrouted one. Asserted against the ROUTER, which
                    # is the structure requests are actually matched against -- the same
                    # discipline `apps/route_matrix.py` exists to enforce.
                    self.assertIn(href, _router_paths(),
                                  f"the rack links to {href}, which no router serves")
                else:
                    self.assertIn(f'"{href}"', source,
                                  f"the rack links to {href}, which api.py does not route")

    def test_every_directory_under_apps_is_a_row_or_is_written_up_as_not_one(self):
        """A new directory that is neither a rack row nor explained is the ambiguity this
        file exists to remove -- it is how `ravencalc` and `remix` went missing from a
        roster built by looking for `__init__.py` files, since neither has one."""
        rows = roster.rows()
        accounted = roster.excluded() | {pathlib.Path(r["implementation"]).name for r in rows}
        found = {d.name for parent in (APPS, APPS / "studio" / "plugins")
                 for d in parent.iterdir()
                 if d.is_dir() and not d.name.startswith((".", "__"))}
        found -= {"plugins"}                 # the plugin container, not a plugin
        self.assertEqual(sorted(found - accounted), [],
                         "add these to ROSTER.md: as rows, or to the section saying why not")


class RosterMatchesControlboardTests(unittest.TestCase):
    def test_the_toggle_column_and_TOGGLEABLE_agree(self):
        """`TOGGLEABLE` stays the authority -- it carries the reasoning for every exclusion.
        This compares the two hand-maintained copies; deriving either would delete the check.
        """
        from apps import controlboard
        self.assertEqual(sorted(r["id"] for r in roster.rows() if r["toggle"]),
                         sorted(controlboard.TOGGLEABLE))

    def test_nothing_toggleable_is_absent_from_the_rack(self):
        ids = {r["id"] for r in roster.rows()}
        from apps import controlboard
        self.assertEqual(sorted(set(controlboard.TOGGLEABLE) - ids), [])


class GeneratedFallbackTests(unittest.TestCase):
    """`site/index.html`'s pre-JS fallback, which `tools/build_rack.py` writes from the roster.

    This is the assertion that catches the half of the work that is easy to forget: the row
    was added to the roster and `build_rack.py` was never re-run, so the committed page still
    lists the old rack. The generator is idempotent and cheap; there is no reason for the page
    to be behind, and this says so out loud rather than trusting it.
    """

    def _fallback(self) -> str:
        html = (REPO / "site" / "index.html").read_text()
        self.assertIn("<noscript>", html)
        return html.split("<noscript>", 1)[1].split("</noscript>", 1)[0]

    def test_the_fallback_lists_every_roster_row_and_nothing_else(self):
        block = self._fallback()
        rows = roster.rows()
        for row in rows:
            with self.subTest(row=row["id"]):
                self.assertIn(f'href="{row["href"]}"', block)
                self.assertIn(f'<b>{row["label"]}</b>', block)
                self.assertIn(f'<span class="slot">{row["slot"]}</span>', block)
        self.assertEqual(block.count('class="unit"'), len(rows),
                         "re-run tools/build_rack.py, then tools/build_cachebust.py")

    def test_the_fallback_claims_no_state_it_has_not_measured(self):
        """The defect this replaced: one row hardcoded `data-state="ready"`.

        A state word in a static file is a decorative indicator by CLAUDE.md's rule, and it
        is worse in the fallback than anywhere else -- the fallback renders precisely when
        the socket that could have measured it is unavailable.
        """
        block = self._fallback()
        self.assertNotIn("data-state", block)
        for word in ("ready", "busy", "queued", "offline"):
            self.assertNotIn(f'class="txt">{word}', block)
        self.assertNotIn('class="led on"', block)


class PluginRowsMatchRosterTests(unittest.TestCase):
    """Which Studio plugins get a rack row of their own -- pinned, because it is a decision.

    `ROSTER.md` states it in prose: *"`discovery` and `reinforce` (under `studio/plugins/`) --
    Studio plugins. `exp` is the only plugin with a row of its own."* Nothing asserted it, and
    prose that nothing checks is how this repo got four disagreeing copies of the roster in the
    first place -- which is the defect the rest of this file exists to close.

    It is not a detail. #73 carried `check: ngrep exp.status() -- backend/api.py`, on the
    reading that "Exp is still a rack row after being migrated into Studio, so the rack claims a
    unit that is a plugin". Satisfying that check meant DELETING a row that `ROSTER.md`,
    `EXPECTED` in `apps/test_status_rack.py`, `tools/build_rack.py`'s generated fallback and a
    live page at `/exp` all require, and that `apps/studio/plugins/__init__.py` argues at length
    must stay a hand-written mount ("This is a conformance contract, NOT a loader"). It would
    have taken a real unit off the front page to move a percentage, and turned two suites red on
    the way. Retired, and replaced by this: the same subject, asserted in the direction the disk
    actually supports.

    So a future reader who wants `exp` folded into the `studio` row has to change this test, and
    changing it is where the argument gets made rather than assumed.
    """

    def _plugin_names(self) -> tuple[str, ...]:
        from apps.studio import plugins
        return plugins.PLUGINS

    def test_the_lists_were_read_at_all(self):
        """Vacuity guard. Two empty sets are equal, and would pass every assertion below."""
        self.assertTrue(self._plugin_names(), "the plugin tuple is empty")
        self.assertTrue([_row_id(c) for c in _unit_calls()], "build_status() yielded no rows")
        self.assertTrue(roster.rows(), "ROSTER.md yielded no rows")

    def test_no_studio_plugin_has_a_rack_row_of_its_own(self):
        """The Studio fold, asserted from the direction that omission cannot check.

        `exp` was the one plugin with a row and `reinforce` published its state through a
        hand-written `train` row beside it, so the rack showed two Studio plugins standing
        as peers of their own parent. Both became `sub` entries on `studio` on 2026-08-29.

        This asserts the rows are GONE. That they are not merely deleted is asserted
        separately, by `test_status_rack.py::FOLDED`, which requires each folded id to come
        back as a `SubUnit` -- two halves of one fold, and only one of them is checked by a
        name being absent from a list.
        """
        rows = {_row_id(call) for call in _unit_calls()}
        with_rows = sorted(set(self._plugin_names()) & rows)
        self.assertEqual(
            with_rows, [],
            "ROSTER.md says every Studio plugin is a child surface of the studio row. "
            f"build_status() gives top-level rows to {with_rows}. Whichever is wrong, they "
            "cannot both stand -- and adding or removing a row is the five-step procedure "
            "in ROSTER.md's `Adding a row`, not a one-line edit to api.py")

    def test_the_roster_and_build_status_agree_on_which_plugins_are_rows(self):
        """The two are compared, never derived one from the other -- see this file's docstring."""
        names = set(self._plugin_names())
        in_api = names & {_row_id(call) for call in _unit_calls()}
        in_roster = names & {row["id"] for row in roster.rows()}
        self.assertEqual(
            sorted(in_api), sorted(in_roster),
            "a Studio plugin is a rack row in one of ROSTER.md / api.py and not the other")

    def test_the_roster_records_both_studio_plugins_as_folded_rather_than_absent(self):
        """A fold that loses the write-up is indistinguishable from a deletion.

        `exp` had a row and an `implementation` column pointing at its plugin directory; the
        column existed so a row could not read as a surface of its own. With the row gone the
        column is gone too, and the claim that has to survive is the one this replaces it
        with: `ROSTER.md`'s not-a-rack-row section must NAME both plugins, because that
        section is what `roster.excluded()` parses and what stops a directory being silently
        neither a row nor explained.
        """
        excluded = roster.excluded()
        for name in ("reinforce", "exp"):
            with self.subTest(plugin=name):
                self.assertIn(
                    name, excluded,
                    f"{name} is a Studio plugin with no rack row of its own, so ROSTER.md's "
                    "not-a-rack-row section has to say so -- otherwise the directory is "
                    "ambiguous, which is the state this file exists to remove")


def _tempfile():
    """A context manager yielding a temp path, so `enterContext` cleans it up."""
    import contextlib
    import tempfile
    @contextlib.contextmanager
    def _cm():
        with tempfile.TemporaryDirectory() as d:
            yield str(pathlib.Path(d) / "ROSTER.md")
    return _cm()


if __name__ == "__main__":
    unittest.main()
