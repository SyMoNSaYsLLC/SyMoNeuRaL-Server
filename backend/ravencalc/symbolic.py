"""Facade over the upstream symbolic engine (sympy).

This module is the ONLY file in the `ravencalc` package allowed to `import sympy`. 
Every other file imports from here. This satisfies the architectural requirement 
to keep third-party vendor names out of the application's domain vocabulary.
"""
import sympy
from typing import Any

# Types
Expr = sympy.Expr
Symbol = sympy.Symbol
Integral = sympy.Integral
Rational = sympy.Rational
Integer = sympy.Integer
Eq = sympy.Eq
Tuple = sympy.Tuple
SympifyError = sympy.SympifyError
PolynomialError = sympy.PolynomialError

# Expose Boolean types correctly
try:
    Boolean = sympy.logic.boolalg.Boolean
except AttributeError:
    Boolean = Any

# Expression node types. `steps.py` asks what KIND of node it is looking at in order to
# name the rule that applies to it, and that question cannot be answered without the
# classes. Bound, not wrapped: they are used with isinstance and .args, which no wrapper
# could improve on.
Add = sympy.Add
Mul = sympy.Mul
Pow = sympy.Pow
Function = sympy.Function
AppliedUndef = sympy.core.function.AppliedUndef
Number = sympy.Number
S = sympy.S


def is_constant(expression, variable) -> bool:
    """True when `variable` does not occur in `expression`."""
    return variable not in expression.free_symbols


# Engine metadata
def version() -> str:
    return sympy.__version__

# Core symbolic functions
def diff(expression, variable, order=1):
    return sympy.diff(expression, variable, order)

def integrate(expression, *args):
    return sympy.integrate(expression, *args)

def limit(expression, variable, point, dir="+"):
    return sympy.limit(expression, variable, point, dir=dir)

def series(expression, variable, point, order):
    return sympy.series(expression, variable, point, n=order)

def simplify(expression):
    return sympy.simplify(expression)

def expand(expression):
    return sympy.expand(expression)

def solve(equation, variable, dict=False):
    return sympy.solve(equation, variable, dict=dict)

def evalf(expression, digits):
    return sympy.N(expression, digits)

# Formatting
def sstr(expression):
    return sympy.sstr(expression)

def latex(expression):
    return sympy.latex(expression)

def srepr(expression):
    return sympy.srepr(expression)

def factorial(n):
    return sympy.factorial(n)

def globals_dict():
    return {name: obj for name, obj in vars(sympy).items() if not name.startswith('_')}
