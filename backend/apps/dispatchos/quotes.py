"""The quote engine: the operator's own rules, applied to the operator's own jobs.

Task #106. The customer preview states the requirement in the operator's language:

    "Quoting applies the operator's own rules to the operator's own jobs, so the same trip
    does not get two different answers on two different days. The operator keeps the final
    say on every job."

## This module ships NO RATES, and that is a requirement rather than a gap

The same page, in the panel a customer reads, says: *"No figure is shown here. Rate rules
are configured after written scope, and this preview carries no pricing of any kind."* The
rider-facing estimate on that page is a literal em-dash pair.

So `quote()` returns a structured result whose `estimate` is `None` until rules exist, and
`display` is `"——"` in that case. There is no default tariff, no fallback per-mile figure
and no "reasonable" starting value anywhere in this file. A default here would put a number
in front of a customer that nobody agreed to, on a page that promises there is none -- and
a wrong price a customer saw is much more expensive than a blank one.

## Determinism is the actual feature

"The same trip does not get two different answers on two different days" is a testable
claim, so `quote()` is a pure function of (booking fields, rules). It reads no clock, no
random source and no environment. `test_dispatchos.py` asserts that by quoting the same
trip twice and comparing.

## Rules shape

    {
      "currency": "GBP",
      "base": 250,                 # minor units (pence/cents) -- integers, never floats
      "per_km": 120,
      "per_minute": 0,
      "minimum": 500,
      "surcharges": [ {"when": "luggage_over", "value": 2, "add": 150},
                      {"when": "passengers_over", "value": 4, "add": 400} ]
    }

Minor units and integers throughout: money in binary floating point is how a quote and an
invoice disagree by a penny and somebody spends an afternoon on it.

**Distance is not invented.** Nothing in this package geocodes an address or estimates a
route, so `per_km` only contributes when the caller supplies a measured `distance_km`. When
it does not, the engine says so in `basis` instead of guessing -- an invented distance is an
invented price wearing arithmetic.
"""
from __future__ import annotations

from typing import Any

#: What a rider sees when there is no figure. Matches the customer preview exactly.
NO_FIGURE = "——"


class RulesError(Exception):
    """The operator's rules are malformed. Never shown to a customer."""


def validate_rules(rules: Any) -> dict:
    """Accept a rules document, or say precisely what is wrong with it."""
    if rules is None:
        return {}
    if not isinstance(rules, dict):
        raise RulesError("rules must be an object")
    out: dict[str, Any] = {}
    cur = rules.get("currency", "")
    if cur and (not isinstance(cur, str) or len(cur) != 3):
        raise RulesError("currency must be a three-letter code")
    out["currency"] = (cur or "").upper()
    for key in ("base", "per_km", "per_minute", "minimum"):
        v = rules.get(key, 0)
        if isinstance(v, bool) or not isinstance(v, int) or v < 0:
            raise RulesError(f"{key} must be a non-negative integer in minor units")
        out[key] = v
    sur = rules.get("surcharges", [])
    if not isinstance(sur, list):
        raise RulesError("surcharges must be a list")
    clean = []
    for s in sur:
        if not isinstance(s, dict):
            raise RulesError("each surcharge must be an object")
        when = s.get("when")
        if when not in ("luggage_over", "passengers_over"):
            raise RulesError(f"unknown surcharge condition {when!r}")
        for key in ("value", "add"):
            v = s.get(key, 0)
            if isinstance(v, bool) or not isinstance(v, int) or v < 0:
                raise RulesError(f"surcharge {key} must be a non-negative integer")
        clean.append({"when": when, "value": s["value"], "add": s["add"]})
    out["surcharges"] = clean
    return out


def configured(rules: Any) -> bool:
    """True only if the rules can actually produce a figure.

    An empty dict, or one whose money fields are all zero, is NOT configured. Treating
    `{}` as "charge nothing" would show a rider a confident 0.00 rather than the blank the
    preview promises.
    """
    try:
        r = validate_rules(rules)
    except RulesError:
        return False
    return any(r.get(k) for k in ("base", "per_km", "per_minute", "minimum"))


def money(minor: int, currency: str) -> str:
    """Minor units to a display string. Integer arithmetic only."""
    sign = "-" if minor < 0 else ""
    minor = abs(int(minor))
    return f"{sign}{minor // 100}.{minor % 100:02d}" + (f" {currency}" if currency else "")


def quote(booking: dict, rules: Any = None, *, distance_km: float | None = None) -> dict:
    """Price one trip, or explain why there is no price.

    Pure: same inputs, same output, always. No clock, no randomness, no environment.
    """
    r = validate_rules(rules)
    route = f"{booking.get('pickup','')} → {booking.get('dropoff','')}".strip(" →")
    base_result = {
        "route": route,
        "vehicle": "Standard saloon",
        "basis": "",
        "currency": r.get("currency", ""),
        "lines": [],
        "estimate": None,
        "display": NO_FIGURE,
        "operator_confirms": True,   # "The operator keeps the final say on every job."
    }

    if not configured(rules):
        base_result["basis"] = ("Operator's rate rules are not configured. Rate rules are "
                                "agreed in written scope before any figure is shown.")
        return base_result

    lines: list[dict] = []
    total = 0
    if r["base"]:
        lines.append({"label": "Base", "minor": r["base"]})
        total += r["base"]

    if r["per_km"]:
        if distance_km is None:
            # Say it rather than guess it. See the module docstring.
            lines.append({"label": "Distance", "minor": 0,
                          "note": "no measured distance supplied; distance is not estimated"})
        else:
            add = int(round(r["per_km"] * float(distance_km)))
            lines.append({"label": f"Distance ({distance_km:g} km)", "minor": add})
            total += add

    for s in r["surcharges"]:
        field = "luggage" if s["when"] == "luggage_over" else "passengers"
        if int(booking.get(field, 0) or 0) > s["value"]:
            lines.append({"label": f"{field.title()} over {s['value']}", "minor": s["add"]})
            total += s["add"]

    floored = False
    if r["minimum"] and total < r["minimum"]:
        lines.append({"label": "Minimum fare applied", "minor": r["minimum"] - total})
        total = r["minimum"]
        floored = True

    base_result.update({
        "basis": ("Operator's configured rate rules"
                  + (", minimum fare applied" if floored else "")),
        "lines": lines,
        "estimate": total,
        "display": money(total, r.get("currency", "")),
    })
    return base_result
