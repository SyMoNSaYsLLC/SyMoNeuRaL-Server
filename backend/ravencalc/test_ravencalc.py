"""Tests for the one thing this engine promises above being correct: that it never leaks.

`run_request`'s docstring says it "raises `RavenCalcError` for anything a caller can fix -- a
malformed document, an unparseable expression, an operation sympy declines -- and lets nothing
else out silently." That sentence is the contract these tests defend, because it is the
difference between a visitor reading why their input was refused and a visitor reading
`Internal Server Error`.

Every other surface in `backend/` carries a `test_<app>.py`; this module had none, and the
bug below is what turned up the first time anyone typed a large factorial at it. Run it the
same way as its neighbours:

    python3 -m unittest discover -s backend/ravencalc -p 'test_*.py'
"""
from __future__ import annotations

import pathlib
import sys
import time
import unittest


import sympy  # noqa: E402

from ravencalc.apps import ravencalc  # noqa: E402


def request(**fields) -> dict:
    return {"schema": ravencalc.REQUEST_SCHEMA_ID, **fields}


class TestWideIntegers(unittest.TestCase):
    """A correct answer too wide to print is still a refusal, not a crash.

    CPython 3.11+ caps integer-to-string conversion at 4,300 digits (CVE-2020-10735, the
    conversion being quadratic). The cap lives in the interpreter, so it fires inside sympy's
    printer -- *after* the mathematics has succeeded. Before this was guarded,
    `simplify factorial(3000)` computed the right answer and then escaped as a bare
    `ValueError`, which the API turned into a 500 on a public unauthenticated route.
    """

    def test_a_wide_answer_is_refused_not_crashed(self):
        with self.assertRaises(ravencalc.RavenCalcError) as caught:
            ravencalc.run_request(request(operation="simplify", expression="factorial(3000)"))
        # The refusal has to be actionable, which means naming both numbers: how wide the
        # answer is and what this interpreter will print. "too wide" on its own tells a caller
        # nothing they can act on.
        detail = " ".join(caught.exception.detail)
        self.assertIn("9,1", detail, f"the width of the answer is not named: {detail}")
        self.assertIn("4,300", detail, f"the limit itself is not named: {detail}")

    def test_the_escaping_exception_is_the_repo_s_own_type(self):
        """The regression guard, stated as the contract rather than as the symptom.

        `RavenCalcError` subclasses `ValueError`, so `assertRaises(ValueError)` would pass both
        before and after the fix and prove nothing. This asserts the exact type, which is what
        `backend/server.py` matches on to return 400 instead of 500.
        """
        for expression in ("factorial(3000)", "2**200000", "factorial(99999)"):
            with self.subTest(expression=expression):
                try:
                    ravencalc.run_request(request(operation="simplify", expression=expression))
                except ravencalc.RavenCalcError:
                    pass
                except Exception as exc:  # noqa: BLE001 -- naming what escaped is the report
                    self.fail(f"{expression} escaped as {type(exc).__name__}: {exc}")

    def test_ordinary_arithmetic_still_prints(self):
        """The guard must not have bought its safety by refusing real work.

        `factorial(100)` is 158 digits -- comfortably printable, and exactly the kind of
        request a too-eager limit would start rejecting.
        """
        result = ravencalc.run_request(request(operation="simplify", expression="factorial(100)"))
        self.assertTrue(result["ok"])
        self.assertTrue(result["result"]["text"].startswith("93326215443944"))

    def test_the_digit_estimate_agrees_with_an_independent_count(self):
        """9,131 comes from `Decimal(n).adjusted() + 1`, which never touches `bit_length`.

        Two methods that share no arithmetic agreeing is the only reason the estimate is
        quotable at all.
        """
        self.assertEqual(ravencalc._print_digits(sympy.factorial(3000)), 9131)

    def test_measuring_the_width_is_cheap(self):
        """The reason the estimate is an estimate.

        `Decimal(factorial(99999)).adjusted()` measured 11.8 s on this box. An exact count is
        therefore itself the denial of service the interpreter's limit exists to prevent, so
        the bound here is what makes the estimate the right call rather than a shortcut.
        """
        value = sympy.Integer(2) ** 200000
        started = time.time()
        digits = ravencalc._print_digits(value)
        elapsed = time.time() - started
        self.assertGreater(digits, 60000)
        self.assertLess(elapsed, 1.0, f"measuring the width took {elapsed:.2f}s")

    def test_nothing_to_measure_reports_nothing(self):
        """0 means "no integer worth measuring" so the policy stays in one place."""
        self.assertEqual(ravencalc._print_digits(sympy.Symbol("x")), 0)


class TestWideExactNoteBesideAGoodAnswer(unittest.TestCase):
    """A note that cannot print must not take a printable answer down with it.

    `evaluate` with `digits` returns a rounded Float and carries the exact pre-rounding form
    alongside it as a note. When the answer rounds fine and only the note is too wide, the
    honest move is to keep the answer and say what the note could not show -- not to refuse.
    """

    def test_the_rounded_answer_survives_an_unprintable_exact_form(self):
        result = ravencalc.run_request(request(
            operation="evaluate", expression="factorial(x)", at={"x": "3000"}, digits=20,
        ))
        self.assertTrue(result["ok"])
        self.assertTrue(result["result"]["text"], "the rounded answer went missing")

    def test_the_note_names_the_limit_instead_of_going_blank(self):
        result = ravencalc.run_request(request(
            operation="evaluate", expression="factorial(x)", at={"x": "3000"}, digits=20,
        ))
        note = result.get("note", "")
        self.assertIn("too wide", note, f"the note does not say what it could not show: {note}")
        self.assertIn("9,1", note, f"the note does not say how wide: {note}")

    def test_a_printable_exact_form_is_still_printed_in_full(self):
        result = ravencalc.run_request(request(
            operation="evaluate", expression="x**2", at={"x": "7"}, digits=6,
        ))
        self.assertIn("49", result.get("note", ""))


class TestTheContractHolds(unittest.TestCase):
    """The refusals that were already right, pinned so the guard above cannot loosen them."""

    def test_a_hostile_expression_is_refused_by_character(self):
        with self.assertRaises(ravencalc.RavenCalcError):
            ravencalc.run_request(request(
                operation="simplify", expression='__import__("os").system("id")',
            ))

    def test_an_unparseable_expression_is_refused(self):
        with self.assertRaises(ravencalc.RavenCalcError):
            ravencalc.run_request(request(operation="simplify", expression="x**"))

    def test_an_unknown_operation_is_refused_whole(self):
        with self.assertRaises(ravencalc.RavenCalcError):
            ravencalc.run_request(request(operation="integrate_by_vibes", expression="x"))

    def test_the_engine_still_computes_the_thing_the_site_advertises(self):
        """`x**3/3` is the answer `tests/frontend.mjs` reads off the rendered page."""
        result = ravencalc.run_request(request(
            operation="integrate", expression="x**2", variable="x",
        ))
        self.assertEqual(result["result"]["text"], "x**3/3")
        self.assertTrue(result["check"]["passed"])

    def test_selfcheck_passes_on_this_interpreter(self):
        for row in ravencalc.selfcheck():
            with self.subTest(case=row.get("name") or row.get("expression")):
                self.assertTrue(row.get("ok", row.get("passed")), row)


if __name__ == "__main__":
    unittest.main(verbosity=2)
