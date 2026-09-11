"""The calculus engine itself -- sympy, and nothing above it.

`ravencalc.say`: "engine.py is the whole of the mathematics: standard library plus sympy, no
web stack, importable by anything in this tree." That is not tidiness. This module is the
thing other layers are supposed to trust, and a component that can only be reached through a
web framework can only be tested through one.

The surface is seven operations -- differentiate, integrate, limit, series, solve, simplify,
evaluate -- and one entry point, `run_request`, which takes a `ravencalc/request/v1` document
and returns a `ravencalc/result/v1` document. Symbolic in, symbolic out: every expression
crosses the boundary as a string in sympy's own syntax, so a caller in another process (or
another language) gets an exact answer rather than a float that has already lost the argument.

Three decisions are worth stating outright, because they are what make this an engine rather
than a wrapper.

**The document is validated whole before sympy is asked anything.** Same rule as a build plan
(`symonbuild/schema.py`): a document that is half-valid is not half-computable, and finding
out at operand three that the variable was never named leaves a caller with a partial answer
it cannot interpret. Validation here answers *shape*; whether the integral has a closed form
is sympy's question, asked afterwards.

**Assumptions are inputs, never guesses.** `sqrt(x**2)` is `x` if x is positive and `|x|` if it
is merely real, and an engine that silently picks one is wrong roughly half the time. The
request carries `assume`, every symbol is built with the assumptions it was given, and the
result echoes back the assumption set that produced it. A caller that assumed nothing is told
that it assumed nothing.

**Results are checked when checking is cheap.** An antiderivative gets differentiated and the
difference simplified against zero; a root gets substituted back. sympy is very good and still
returns things `simplify` cannot confirm, so `check.passed` is three-valued -- true, false, or
unknown -- and "unknown" is reported rather than rounded up to true. A check that cannot fail
is not a check.

Parsing is the one genuinely dangerous thing here and it is treated that way; see `parse`.
"""
from __future__ import annotations

import math
import re
import sys
from dataclasses import dataclass, field
from typing import Any, Iterable

# Relative, because this module is part of the `apps.ravencalc` package. These were
# bare sibling imports that resolved only while `api.py` put backend/ravencalc on
# sys.path -- the second import route. Removing that insert took this surface to 503
# until these were converted; the route handler imports lazily, so /api/status stayed
# green and only /api/ravencalc failed.
from ..apps import steps as derivation_steps
from ..lib import symbolic
from sympy.parsing.sympy_parser import (  # Keep the parser direct until we wrap it
    parse_expr, standard_transformations, implicit_multiplication_application, convert_xor
)

REQUEST_SCHEMA_ID = "ravencalc/request/v1"
RESULT_SCHEMA_ID = "ravencalc/result/v1"

#: Every operation the engine knows, with the request fields each one requires beyond
#: `expression`. An operation not listed here is refused whole -- there is no "close enough"
#: fallback, because guessing which operation the caller meant is precisely the mistake the
#: request document exists to make impossible.
OPERATIONS: dict[str, set[str]] = {
    "differentiate": {"variable"},
    "integrate": {"variable"},
    "limit": {"variable", "point"},
    "series": {"variable"},
    "solve": {"variable"},
    "simplify": set(),
    "evaluate": set(),
}

#: How long an expression may be. Not a security boundary -- see `parse` for that -- but a
#: service on a port should not accept a megabyte of nested radicals and find out what sympy
#: does with it while another caller waits.
MAX_EXPRESSION = 4096
MAX_SYMBOLS = 32

#: Assumption names a caller may attach to a symbol. Deliberately a short list of the ones
#: that change an answer rather than everything sympy accepts: each of these flips a real
#: result, and a longer list is a larger surface to explain in a refusal message.
ASSUMPTIONS = frozenset(
    {
        "real", "complex", "integer", "rational", "positive", "negative",
        "nonnegative", "nonpositive", "nonzero", "even", "odd", "finite",
    }
)

#: The only characters an expression may contain. A whitelist, because the blacklist version
#: of this question has no correct answer. See `parse`.
_ALLOWED = re.compile(r"^[0-9A-Za-z_+\-*/^%().,=<>!\s\[\]]*$")
_ATTRIBUTE = re.compile(r"\.\s*[A-Za-z_]")
_IDENT = re.compile(r"^[A-Za-z][A-Za-z0-9_]*$")

_TRANSFORMS = standard_transformations + (convert_xor,)


class RavenCalcError(ValueError):
    """A refusal, said the way this repo says refusals: what, where, and what to fix.

    Modelled on `symonbuild.errors.LoudFailure` rather than importing it -- this layer does
    not depend on the build orchestrator and should not acquire a dependency on it to reuse
    an exception shape. The fields are the same three because those are the three an operator
    needs, and `service.py` turns them straight into an HTTP body.
    """

    def __init__(self, message: str, detail: Iterable[str] = (), where: str = ""):
        self.message = message
        self.detail = list(detail)
        self.where = where
        super().__init__(message if not self.detail else f"{message}: {'; '.join(self.detail)}")

    def as_record(self) -> dict[str, Any]:
        return {"ok": False, "error": self.message, "detail": self.detail, "where": self.where}


def _safe_globals() -> dict[str, Any]:
    """The names an expression is allowed to mention.

    sympy's public namespace and nothing else -- crucially including `__builtins__: {}`, which
    stops Python from helpfully injecting the real builtins into the eval that `parse_expr`
    performs. Without that line `__import__` is one attribute lookup away.
    """
    namespace = symbolic.globals_dict()
    namespace["__builtins__"] = {}
    return namespace


_GLOBALS = _safe_globals()


def parse(text: str, symbols: dict[str, symbolic.Symbol] | None = None) -> symbolic.Expr:
    """Turn a string into a sympy expression, defensively.

    The thing to be honest about: `parse_expr` tokenises and then **evals**. It is a compiler
    entry point, this engine listens on a port, and no amount of docstring changes that. What
    is here is defence in depth, and it is layered because any one layer of it could be wrong:

    1. A **character whitelist**. Quotes, backslashes, colons, semicolons, braces, `@`, `$`,
       `#`, `&`, `|`, `~` and backtick cannot appear at all. Almost every published escape
       from an expression parser needs one of them, and none of them are needed to write
       mathematics.
    2. **No attribute access** (`.` followed by a letter) and **no dunder anywhere**. `3.5` is
       fine because a digit follows the dot; `x.__class__` is refused twice over.
    3. A **restricted global namespace** with builtins emptied, so even a name that survives
       the first two layers resolves to a sympy object or to a free `Symbol`.

    Layer 3 alone would probably do it, and that is exactly why layers 1 and 2 are here: a
    parser hardened by one argument is hardened until that argument turns out to be wrong.

    This is mitigation, not a sandbox, and it is recorded as an open item rather than claimed
    as a solved problem.
    """
    if not isinstance(text, str) or not text.strip():
        raise RavenCalcError("expression must be a non-empty string", [f"got: {text!r}"])
    if len(text) > MAX_EXPRESSION:
        raise RavenCalcError(
            "expression is too long",
            [f"{len(text)} characters, limit {MAX_EXPRESSION}"],
        )
    if not _ALLOWED.match(text):
        bad = sorted({c for c in text if not _ALLOWED.match(c)})
        raise RavenCalcError(
            "expression contains characters this engine does not accept",
            [f"refused: {' '.join(repr(c) for c in bad)}",
             "mathematics can be written without quotes, backslashes, braces or semicolons"],
        )
    if "__" in text or _ATTRIBUTE.search(text):
        raise RavenCalcError(
            "expression looks like python, not mathematics",
            ["attribute access and dunder names are refused before the parser sees them"],
        )

    try:
        expression = parse_expr(
            text,
            local_dict=dict(symbols or {}),
            global_dict=_GLOBALS,
            transformations=_TRANSFORMS,
            evaluate=True,
        )
    except RavenCalcError:
        raise
    except Exception as exc:  # sympy raises a wide spread here; all of it means "unparseable"
        raise RavenCalcError(
            "cannot parse that expression",
            [f"{type(exc).__name__}: {exc}", f"input: {text}"],
        ) from exc

    if not isinstance(expression, (symbolic.Expr, symbolic.Boolean, symbolic.Eq)):
        raise RavenCalcError(
            "that parsed to something this engine cannot compute with",
            [f"got a {type(expression).__name__}", f"input: {text}"],
        )
    return expression


def make_symbols(assume: dict[str, Any] | None) -> dict[str, symbolic.Symbol]:
    """Build the caller's symbols carrying the caller's assumptions.

    An empty `assume` produces an empty dict, not a set of real symbols: sympy's default is a
    fully general complex symbol, and quietly upgrading every variable to real would make this
    engine answer a different question than the one it was asked. The absence of an assumption
    is itself an assumption, and it belongs to the caller.
    """
    if not assume:
        return {}
    if len(assume) > MAX_SYMBOLS:
        raise RavenCalcError(
            "too many assumed symbols", [f"{len(assume)}, limit {MAX_SYMBOLS}"]
        )
    symbols: dict[str, symbolic.Symbol] = {}
    for name, raw in assume.items():
        if not isinstance(name, str) or not _IDENT.match(name):
            raise RavenCalcError(
                "an assumed symbol must be a plain identifier", [f"got: {name!r}"]
            )
        wanted = [raw] if isinstance(raw, str) else list(raw or [])
        flags: dict[str, bool] = {}
        for item in wanted:
            if not isinstance(item, str) or item not in ASSUMPTIONS:
                raise RavenCalcError(
                    f"unknown assumption for {name}",
                    [f"got: {item!r}", "known: " + ", ".join(sorted(ASSUMPTIONS))],
                )
            flags[item] = True
        symbols[name] = symbolic.Symbol(name, **flags)
    return symbols


@dataclass(frozen=True)
class Request:
    """A validated `ravencalc/request/v1`. Constructed only by `validate_request`."""

    operation: str
    expression: str
    variable: str = ""
    order: int = 1
    point: str = "0"
    direction: str = "+-"
    lower: str = ""
    upper: str = ""
    at: dict[str, str] = field(default_factory=dict)
    digits: int = 0
    assume: dict[str, Any] = field(default_factory=dict)
    #: Ask for the derivation as well as the answer. Off by default: every existing
    #: caller's result document must be byte-identical to what it was before this field
    #: existed, and a step list appearing unasked-for in symonsaymath's output would be a
    #: silent change to a contract other code parses.
    steps: bool = False

    def as_record(self) -> dict[str, Any]:
        """The document as it was understood, echoed back to the caller.

        This is what lets a caller -- symonsaymath in particular -- show what was actually
        computed rather than only what came out. A request document that reads `integrate`
        when the human said "rate of change" is a visible mistake; a number with no document
        beside it is not.
        """
        record: dict[str, Any] = {
            "schema": REQUEST_SCHEMA_ID,
            "operation": self.operation,
            "expression": self.expression,
        }
        if self.variable:
            record["variable"] = self.variable
        if self.operation in {"differentiate", "series"}:
            record["order"] = self.order
        if self.operation in {"limit", "series"}:
            record["point"] = self.point
        if self.operation == "limit":
            record["direction"] = self.direction
        if self.operation == "integrate" and self.lower:
            record["lower"], record["upper"] = self.lower, self.upper
        if self.operation == "differentiate" and self.steps:
            record["steps"] = True
        if self.operation == "evaluate":
            record["at"] = dict(self.at)
            if self.digits:
                record["digits"] = self.digits
        if self.assume:
            record["assume"] = dict(self.assume)
        return record


def validate_request(doc: Any) -> Request:
    """Validate a request document whole, before sympy is asked anything.

    Every problem found is collected and reported together. A caller that got three fields
    wrong should learn about three fields, not discover them one redeployment at a time --
    and when the caller is a language model translating natural language (symonsaymath), the
    full list is what lets a single retry fix the document instead of half of it.
    """
    if not isinstance(doc, dict):
        raise RavenCalcError(
            "a request must be a json object", [f"got: {type(doc).__name__}"], REQUEST_SCHEMA_ID
        )

    problems: list[str] = []
    schema = doc.get("schema", REQUEST_SCHEMA_ID)
    if schema != REQUEST_SCHEMA_ID:
        problems.append(f"schema must be {REQUEST_SCHEMA_ID!r}, got {schema!r}")

    operation = doc.get("operation")
    if operation not in OPERATIONS:
        problems.append(
            f"unknown operation {operation!r} -- known: {', '.join(sorted(OPERATIONS))}"
        )

    expression = doc.get("expression")
    if not isinstance(expression, str) or not expression.strip():
        problems.append(f"expression must be a non-empty string, got {expression!r}")

    variable = doc.get("variable", "")
    if not isinstance(variable, str):
        problems.append(f"variable must be a string, got {variable!r}")
        variable = ""
    elif variable and not _IDENT.match(variable):
        problems.append(f"variable must be a plain identifier, got {variable!r}")

    if operation in OPERATIONS:
        for required in sorted(OPERATIONS[operation]):
            if not str(doc.get(required, "")).strip():
                problems.append(f"{operation} requires {required!r}")

    want_steps = doc.get("steps", False)
    if not isinstance(want_steps, bool):
        problems.append(f"steps must be true or false, got {want_steps!r}")
        want_steps = False
    elif want_steps and operation not in {"differentiate"}:
        # Refused rather than ignored. A caller who asked for a derivation and got a
        # result document with no `derivation` key has been told nothing, and will read
        # the absence as "this expression has no interesting steps" instead of "this
        # operation cannot produce them".
        problems.append(
            f"steps are available for differentiate, not {operation!r} -- "
            "the other operations have no rule-by-rule derivation to show")

    order = doc.get("order", 1)
    if not isinstance(order, int) or isinstance(order, bool) or not 1 <= order <= 12:
        problems.append(f"order must be an integer between 1 and 12, got {order!r}")
        order = 1

    direction = doc.get("direction", "+-")
    if direction not in {"+", "-", "+-"}:
        problems.append(f"direction must be '+', '-' or '+-', got {direction!r}")
        direction = "+-"

    lower, upper = doc.get("lower", ""), doc.get("upper", "")
    if not isinstance(lower, str) or not isinstance(upper, str):
        problems.append("lower and upper must be strings (engine syntax: 'pi', 'oo', '0')")
        lower, upper = "", ""
    elif bool(lower.strip()) != bool(upper.strip()):
        # Half a definite integral is not a definite integral, and the natural failure --
        # silently returning the antiderivative -- looks like an answer.
        problems.append("a definite integral needs both lower and upper, or neither")

    at = doc.get("at", {}) or {}
    if not isinstance(at, dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in at.items()
    ):
        problems.append("at must be a mapping of symbol name to expression string")
        at = {}
    if operation == "evaluate" and not at:
        problems.append("evaluate requires at: {symbol: value} -- there is nothing to evaluate at")

    digits = doc.get("digits", 0)
    if not isinstance(digits, int) or isinstance(digits, bool) or not 0 <= digits <= 200:
        problems.append(f"digits must be an integer between 0 and 200, got {digits!r}")
        digits = 0

    assume = doc.get("assume", {}) or {}
    if not isinstance(assume, dict):
        problems.append("assume must be a mapping of symbol name to assumption(s)")
        assume = {}

    unknown = sorted(
        set(doc)
        - {
            "schema", "operation", "expression", "variable", "order", "point",
            "direction", "lower", "upper", "at", "digits", "assume", "steps",
        }
    )
    if unknown:
        # Refused rather than ignored. An unrecognised key is either a typo for a real one --
        # in which case ignoring it silently answers a different question -- or a field this
        # engine does not implement, in which case the caller should hear so.
        problems.append(f"unknown field(s): {', '.join(repr(k) for k in unknown)}")

    if problems:
        raise RavenCalcError("request document is not valid", problems, REQUEST_SCHEMA_ID)

    return Request(
        operation=str(operation),
        expression=str(expression).strip(),
        variable=variable,
        order=order,
        point=str(doc.get("point", "0")),
        direction=direction,
        lower=lower.strip(),
        upper=upper.strip(),
        at={k: v for k, v in at.items()},
        digits=digits,
        assume=assume,
        steps=want_steps,
    )


def _print_digits(value: Any) -> int:
    """About how many decimal digits the widest integer inside `value` needs in order to print.

    Estimated from `int.bit_length()` and never measured with `len(str(n))`, because measuring
    is the very conversion the interpreter refuses to perform. The cheap-looking exact
    alternative is not cheap: `Decimal(factorial(99999)).adjusted()` takes **11.8 s measured on
    this box**, so counting the digits exactly would answer a refusal with the denial of service
    the limit exists to prevent. `bit_length` is O(1).

    The estimate agreed exactly with the true digit count on every case checked here
    (`factorial(3000)` -> 9,131) and can sit one digit either side of it near a power of ten.
    That is why every message built from this says "about" -- an engine whose whole argument is
    exactness does not get to quote an estimate as a measurement.

    Returns 0 when nothing here is an integer worth measuring, so the policy -- which limit,
    and what to do about it -- lives entirely in the caller.
    """
    ints: list[int] = []
    if isinstance(value, int):
        ints.append(value)
    else:
        try:
            atoms = value.atoms(symbolic.Rational)
        except Exception:
            return 0
        for atom in atoms:
            # sympy Rationals (Integer among them) carry Python ints as .p and .q.
            for part in (getattr(atom, "p", None), getattr(atom, "q", None)):
                if isinstance(part, int):
                    ints.append(part)
    widest = max((abs(n) for n in ints), default=0)
    if widest == 0:
        return 0
    return int(widest.bit_length() * math.log10(2)) + 1


def _unprintable_error(digits: int, limit: int) -> RavenCalcError:
    """The refusal for an answer that computed correctly and cannot be written down.

    CPython 3.11+ will not convert an integer wider than `sys.get_int_max_str_digits()` --
    4,300 digits by default -- into a string, because that conversion is quadratic
    (CVE-2020-10735). It is an *interpreter* limit, not a sympy one, so it fires inside the
    printer: `factorial(3000)` is computed exactly, correctly, and then dies on the way out.
    Unguarded it leaves this module as a bare `ValueError`, which `run_request`'s contract
    promises never happens and which reaches a visitor as an unexplained 500.

    Raising the interpreter's limit is the other available fix and is deliberately not taken.
    This engine answers an unauthenticated public route, the cost being guarded against is
    real, and a visitor can type `2**200000` (about 60,000 digits) as easily as `2+2`.

    `digits == 0` means the width could not be measured cheaply -- said plainly rather than
    guessed at.
    """
    how_wide = (
        f"it is an integer of about {digits:,} decimal digits" if digits
        else "it contains an integer too wide to measure without performing the conversion itself"
    )
    return RavenCalcError(
        "the exact answer is too wide for this engine to print",
        [
            how_wide,
            f"this interpreter converts integers up to {limit:,} digits into text",
            "the mathematics succeeded and only rendering it did not, so narrow the request -- "
            "a smaller factorial or exponent -- rather than rephrasing it",
        ],
        RESULT_SCHEMA_ID,
    )


def _rendered(value: Any) -> dict[str, Any]:
    """One sympy object, rendered the three ways a caller might need it.

    `text` is sympy syntax and round-trips through `parse` -- that is the contract that lets a
    result be fed straight back in as the next request's expression. `latex` is for display.
    `tree` is `srepr`, the unambiguous form, kept because two different expressions can print
    identically once a renderer gets involved.

    All three go through the integer printer, so all three are guarded together; see
    `_unprintable_error`. The guard is layered the same way `parse` is, because either layer
    could be wrong: the estimate refuses before the printer is asked, and the `except` catches
    an integer the estimate failed to find rather than letting a bare `ValueError` escape.
    """
    limit = sys.get_int_max_str_digits()
    digits = _print_digits(value)
    if limit and digits > limit:
        raise _unprintable_error(digits, limit)
    try:
        return {
            "text": symbolic.sstr(value),
            "latex": symbolic.latex(value),
            "tree": symbolic.srepr(value),
        }
    except ValueError as exc:
        if "integer string conversion" not in str(exc):
            raise
        raise _unprintable_error(digits, limit) from exc


def _zero(expression: symbolic.Expr) -> bool | None:
    """Is this expression identically zero? Three-valued on purpose.

    `simplify(e) == 0` is a proof; `e.equals(0)` returning None is sympy telling us it could
    not decide. Collapsing that None to False would report a correct antiderivative as a
    failed check, and collapsing it to True would report an unchecked one as verified. Both
    are worse than saying "unknown".
    """
    try:
        if symbolic.simplify(expression) == 0:
            return True
    except Exception:
        pass
    try:
        return expression.equals(0)
    except Exception:
        return None


def _check(passed: bool | None, how: str) -> dict[str, Any]:
    return {"performed": True, "passed": passed, "how": how}


_UNCHECKED = {"performed": False, "passed": None, "how": ""}


def run_request(doc: Any) -> dict[str, Any]:
    """Validate a request document and compute it. The engine's single entry point.

    Returns a `ravencalc/result/v1` document. Raises `RavenCalcError` for anything a caller
    can fix -- a malformed document, an unparseable expression, an operation sympy declines --
    and lets nothing else out silently.
    """
    request = validate_request(doc)
    symbols = make_symbols(request.assume)
    expression = parse(request.expression, symbols)

    variable = None
    if request.variable:
        # A variable named in `assume` keeps its assumptions; one that is not gets sympy's
        # default. Reusing the same Symbol object matters -- Symbol('x', real=True) and
        # Symbol('x') are different symbols to sympy, and differentiating with the wrong one
        # returns 0 for an expression that plainly depends on x.
        variable = symbols.get(request.variable) or symbolic.Symbol(request.variable)

    result, check, note = _compute(request, expression, symbols, variable)

    derivation = None
    if request.steps and variable is not None:
        # Computed from the same parsed expression and the same Symbol object the answer
        # was computed from. Re-parsing here would be the bug this file already documents
        # for `variable`: Symbol('x', real=True) and Symbol('x') are different symbols,
        # and a derivation built on the wrong one narrates a different question.
        derivation = derivation_steps.steps_for_derivative(expression, variable, request.order)

    return {
        "schema": RESULT_SCHEMA_ID,
        "ok": True,
        "request": request.as_record(),
        "input": _rendered(expression),
        "result": _rendered(result),
        "exact": not result.free_symbols and result.is_number and not result.is_Float
        if isinstance(result, symbolic.Expr)
        else True,
        "check": check,
        "note": note,
        "assumed": _assumed(symbols),
        "engine": f"RavenCalc (symbolic core {symbolic.version()})",
        **({"derivation": derivation} if derivation is not None else {}),
    }


def _assumed(symbols: dict[str, symbolic.Symbol]) -> dict[str, list[str]]:
    """What the answer actually depends on, echoed back.

    Reported even when it is empty, and the empty case is the important one: a caller reading
    `"assumed": {}` has been told, in the result, that every variable was treated as an
    arbitrary complex number. Omitting the key when nothing was assumed would make the most
    dangerous case the invisible one.
    """
    return {
        name: sorted(k for k, v in symbol.assumptions0.items() if v is True)
        for name, symbol in sorted(symbols.items())
    }


def _compute(
    request: Request,
    expression: symbolic.Expr,
    symbols: dict[str, symbolic.Symbol],
    variable: symbolic.Symbol | None,
) -> tuple[Any, dict[str, Any], str]:
    """Dispatch to the operation. Each branch returns (result, check, note)."""
    operation = request.operation
    try:
        if operation == "differentiate":
            result = symbolic.diff(expression, variable, request.order)
            return result, _UNCHECKED, ""

        if operation == "integrate":
            return _integrate(request, expression, symbols, variable)

        if operation == "limit":
            point = parse(request.point, symbols)
            result = symbolic.limit(expression, variable, point, dir=request.direction)
            note = (
                "two-sided limit: the engine's '+-' asks for both one-sided limits to agree"
                if request.direction == "+-"
                else f"one-sided limit from the {'right' if request.direction == '+' else 'left'}"
            )
            return result, _UNCHECKED, note

        if operation == "series":
            point = parse(request.point, symbols)
            result = symbolic.series(expression, variable, point, request.order)
            return result, _UNCHECKED, f"expanded to O(({request.variable} - {point})**{request.order})"

        if operation == "solve":
            return _solve(expression, variable)

        if operation == "simplify":
            result = symbolic.simplify(expression)
            # The one check that is free: simplify must not change what the expression means.
            same = _zero(symbolic.expand(expression - result)) if isinstance(result, symbolic.Expr) else None
            return result, _check(same, "subtracted the simplified form from the original"), ""

        if operation == "evaluate":
            return _evaluate(request, expression, symbols)
    except RavenCalcError:
        raise
    except (NotImplementedError, symbolic.PolynomialError, symbolic.SympifyError) as exc:
        # sympy saying "I cannot do this one" is a real answer and belongs to the caller
        # unedited. Turning it into a generic failure would hide the single most useful
        # sentence in the exchange.
        raise RavenCalcError(
            f"RavenCalc cannot {operation} that",
            [f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__],
            REQUEST_SCHEMA_ID,
        ) from exc
    except RecursionError as exc:
        raise RavenCalcError(
            f"{operation} did not terminate on that input",
            ["the engine recursed past python's limit -- the expression is too deeply nested"],
            REQUEST_SCHEMA_ID,
        ) from exc
    except Exception as exc:
        raise RavenCalcError(
            f"{operation} failed", [f"{type(exc).__name__}: {exc}"], REQUEST_SCHEMA_ID
        ) from exc

    raise AssertionError(f"unhandled operation {operation!r}")  # pragma: no cover


def _integrate(
    request: Request,
    expression: symbolic.Expr,
    symbols: dict[str, symbolic.Symbol],
    variable: symbolic.Symbol,
) -> tuple[Any, dict[str, Any], str]:
    if request.lower:
        lower, upper = parse(request.lower, symbols), parse(request.upper, symbols)
        result = symbolic.integrate(expression, (variable, lower, upper))
        # A definite integral sympy could not close comes back as an unevaluated Integral.
        # Handing that back as "the answer" is the failure worth catching: it renders as
        # tidy LaTeX and says nothing.
        if result.has(symbolic.Integral):
            return result, _UNCHECKED, "the engine returned this unevaluated -- no closed form was found"
        return result, _UNCHECKED, f"definite integral over [{lower}, {upper}]"

    result = symbolic.integrate(expression, variable)
    if result.has(symbolic.Integral):
        return result, _UNCHECKED, "the engine returned this unevaluated -- no closed form was found"
    # The check that earns its place: differentiate the antiderivative and see whether the
    # difference is zero. It catches a wrong answer outright, and it costs one diff.
    passed = _zero(symbolic.diff(result, variable) - expression)
    return (
        result,
        _check(passed, "differentiated the antiderivative and simplified the difference against 0"),
        "antiderivative, constant of integration omitted",
    )


def _solve(expression: Any, variable: symbolic.Symbol) -> tuple[Any, dict[str, Any], str]:
    """Roots, plus the substitution that confirms them.

    `solve` is handed the expression as an equation against zero unless the caller wrote one
    with `=`, which is the convention every CAS uses and the one that matches how people write
    the request.
    """
    equation = expression if isinstance(expression, symbolic.Eq) else symbolic.Eq(expression, 0)
    roots = symbolic.solve(equation, variable, dict=False)
    if not isinstance(roots, list):
        roots = [roots]
    result = symbolic.Tuple(*roots)

    verdicts = [_zero((equation.lhs - equation.rhs).subs(variable, root)) for root in roots]
    if not roots:
        passed: bool | None = None
        how = "no roots returned -- nothing to substitute back"
    elif all(v is True for v in verdicts):
        passed, how = True, f"substituted all {len(roots)} root(s) back into the equation"
    elif any(v is False for v in verdicts):
        passed, how = False, "at least one returned root does not satisfy the equation"
    else:
        passed, how = None, "substitution did not simplify to 0 for every root -- undecided"
    note = (
        "RavenCalc's solve does not promise completeness for every equation class;"
        " an empty list means it found none, not that none exist"
    )
    return result, _check(passed, how), note


def _exact_note(result: symbolic.Expr) -> str:
    """The pre-rounding exact form, or an honest description of it when it cannot be printed.

    This is deliberately *not* the refusal `_rendered` raises, and the difference is the point.
    Here the answer the caller asked for is fine -- `evaluate` at `x: 3000` with `digits: 20`
    returns a 20-digit Float that prints perfectly -- and only this note about the exact form
    behind it is too wide. Refusing the whole request over a note would throw away a good
    answer, so the note says what it could not show and how wide it was.

    That is the same rule this project applies to any truncated line: name the limit, never cut
    silently. A note reading `exact form before rounding:` followed by nothing would be the
    `text-overflow:ellipsis` bug wearing a different hat.
    """
    limit = sys.get_int_max_str_digits()
    digits = _print_digits(result)
    if limit and digits > limit:
        return (
            f"exact form before rounding: an integer of about {digits:,} digits, too wide for "
            f"this interpreter to print (its limit is {limit:,})"
        )
    return f"exact form before rounding: {symbolic.sstr(result)}"


def _evaluate(
    request: Request, expression: symbolic.Expr, symbols: dict[str, symbolic.Symbol]
) -> tuple[Any, dict[str, Any], str]:
    """Substitute values in, and only then -- if asked -- go numeric.

    Substitution happens symbolically and `digits` is opt-in, so the default result of
    `evaluate` is still exact. That ordering is the whole point of a symbolic engine: floating
    point applied before simplification is how `1e16 + 1 - 1e16` becomes 0.
    """
    bindings = {
        (symbols.get(name) or symbolic.Symbol(name)): parse(value, symbols)
        for name, value in request.at.items()
    }
    result = expression.subs(bindings)
    if request.digits:
        numeric = symbolic.evalf(result, request.digits)
        return numeric, _UNCHECKED, _exact_note(result)
    return symbolic.simplify(result), _UNCHECKED, "exact -- pass digits: N for a decimal"


def selfcheck() -> list[dict[str, Any]]:
    """A handful of requests with answers known independently of sympy.

    Not a test suite -- `tests/` is where those go, and law 1 keeps them out of this file's
    business. This exists so that `ravencalc --selfcheck` can answer the only question an
    operator has about a freshly built `.pyz`: does the engine inside it compute, on this
    interpreter, with this sympy. A packaged artifact that imports and then returns nonsense
    passes every check the build pipeline makes.
    """
    cases = [
        ({"operation": "differentiate", "expression": "sin(x)**2", "variable": "x"},
         "2*sin(x)*cos(x)"),
        ({"operation": "integrate", "expression": "x**2*sin(x)", "variable": "x"},
         "-x**2*cos(x) + 2*x*sin(x) + 2*cos(x)"),
        ({"operation": "integrate", "expression": "exp(-x**2)", "variable": "x",
          "lower": "-oo", "upper": "oo"}, "sqrt(pi)"),
        ({"operation": "limit", "expression": "sin(x)/x", "variable": "x", "point": "0"}, "1"),
        ({"operation": "solve", "expression": "x**2 - 4", "variable": "x"}, "(-2, 2)"),
        ({"operation": "evaluate", "expression": "sqrt(x**2)", "variable": "x",
          "at": {"x": "-3"}}, "3"),
    ]
    report = []
    for doc, expected in cases:
        try:
            got = run_request(doc)["result"]["text"]
            report.append({"request": doc, "expected": expected, "got": got, "ok": got == expected})
        except RavenCalcError as exc:
            report.append({"request": doc, "expected": expected, "got": exc.message, "ok": False})
    return report
