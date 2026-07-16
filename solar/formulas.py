"""Safe arithmetic formulas for financial report calculations."""

from __future__ import annotations

import ast
import operator


ALLOWED_VARIABLES = frozenset({
    "operating_cf",
    "capex",
    "interest_expense",
    "tax_rate",
    "ebit",
    "da",
    "change_nwc",
    "revenue",
})

DEFAULT_FORMULAS = {
    "free_cash_flow": {
        "label": "Free cash flow",
        "expression": "operating_cf - capex",
        "description": "Operating cash flow less normalized positive capital expenditure.",
    },
    "fcff": {
        "label": "FCFF (CFO-based approximation)",
        "expression": "operating_cf + interest_expense * (1 - tax_rate) - capex",
        "description": (
            "Operating cash flow plus after-tax financing expense less normalized "
            "positive capital expenditure."
        ),
    },
}

_BINARY_OPERATORS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
}
_UNARY_OPERATORS = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}


class FormulaValidationError(ValueError):
    """Raised when an editable financial formula is unsafe or invalid."""


class FormulaInputError(ValueError):
    """Raised when a valid formula cannot be calculated for a company."""


def _calculate(node: ast.AST, values: dict[str, float]) -> float:
    if isinstance(node, ast.Expression):
        return _calculate(node.body, values)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            raise FormulaValidationError("Only numeric constants are allowed")
        return float(node.value)
    if isinstance(node, ast.Name):
        if node.id not in ALLOWED_VARIABLES:
            raise FormulaValidationError(f"Unknown variable: {node.id}")
        if node.id not in values:
            raise FormulaInputError(f"Missing required input: {node.id}")
        return float(values[node.id])
    if isinstance(node, ast.BinOp):
        operation = _BINARY_OPERATORS.get(type(node.op))
        if operation is None:
            raise FormulaValidationError("Only +, -, * and / operators are allowed")
        left = _calculate(node.left, values)
        right = _calculate(node.right, values)
        if isinstance(node.op, ast.Div) and right == 0:
            raise FormulaInputError("Division by zero")
        return float(operation(left, right))
    if isinstance(node, ast.UnaryOp):
        operation = _UNARY_OPERATORS.get(type(node.op))
        if operation is None:
            raise FormulaValidationError("Only unary + and - are allowed")
        return float(operation(_calculate(node.operand, values)))
    raise FormulaValidationError(
        "Only numbers, approved variables, parentheses and +, -, *, / are allowed"
    )


def parse_formula(expression: str) -> ast.Expression:
    normalized = expression.strip()
    if not normalized:
        raise FormulaValidationError("Formula cannot be blank")
    try:
        parsed = ast.parse(normalized, mode="eval")
    except SyntaxError as exc:
        raise FormulaValidationError("Invalid formula syntax") from exc
    _calculate(
        parsed,
        {
            "operating_cf": 100.0,
            "capex": 40.0,
            "interest_expense": 10.0,
            "tax_rate": 0.25,
            "ebit": 80.0,
            "da": 20.0,
            "change_nwc": 5.0,
            "revenue": 200.0,
        },
    )
    return parsed


def validate_formula(expression: str) -> None:
    parse_formula(expression)


def evaluate_formula(expression: str, values: dict[str, float | None]) -> float:
    parsed = parse_formula(expression)
    available = {name: float(value) for name, value in values.items() if value is not None}
    return _calculate(parsed, available)
