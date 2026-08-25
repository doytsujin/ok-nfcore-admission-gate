"""Policy evaluation.

Each condition in a descriptor's `permissibleActions[].conditions` is checked
against the request context. The evaluator returns every condition's outcome,
not just a boolean, because the decision record has to show what was checked --
a refusal that cannot say *why* is not auditable.

Conditions are intentionally a small closed set. An open expression language
would be more expressive and much harder to defend to an inspector.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ConditionResult:
    name: str
    operator: str
    expected: object
    observed: object
    passed: bool

    @property
    def detail(self) -> str:
        if self.passed:
            return f"{self.name}: {self.observed!r} satisfies {self.operator} {self.expected!r}"
        return f"{self.name}: {self.observed!r} violates {self.operator} {self.expected!r}"


def _as_number(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _check(name: str, spec, observed) -> ConditionResult:
    """Evaluate one condition.

    Supported forms:
      "key": {"min": n}        observed >= n
      "key": {"max": n}        observed <= n
      "key": {"in": [...]}     observed is a member
      "key": {"equals": v}     observed == v
      "key": {"present": true} observed is not None
    """
    if not isinstance(spec, dict):
        return ConditionResult(name, "equals", spec, observed, observed == spec)

    if "min" in spec:
        lhs, rhs = _as_number(observed), _as_number(spec["min"])
        ok = lhs is not None and rhs is not None and lhs >= rhs
        return ConditionResult(name, ">=", spec["min"], observed, ok)

    if "max" in spec:
        lhs, rhs = _as_number(observed), _as_number(spec["max"])
        ok = lhs is not None and rhs is not None and lhs <= rhs
        return ConditionResult(name, "<=", spec["max"], observed, ok)

    if "in" in spec:
        allowed = spec["in"]
        return ConditionResult(name, "in", allowed, observed, observed in allowed)

    if "equals" in spec:
        return ConditionResult(
            name, "==", spec["equals"], observed, observed == spec["equals"]
        )

    if "present" in spec:
        want = bool(spec["present"])
        ok = (observed is not None) == want
        return ConditionResult(name, "present", want, observed, ok)

    # An unrecognised condition fails closed. A gate that silently ignores a
    # rule it does not understand is worse than one that refuses.
    return ConditionResult(name, "unsupported", spec, observed, False)


def evaluate(conditions: dict, context: dict) -> list[ConditionResult]:
    """Evaluate every condition against the context. Order is stable."""
    return [_check(key, spec, context.get(key)) for key, spec in sorted(conditions.items())]


def all_passed(results: list[ConditionResult]) -> bool:
    return all(r.passed for r in results)


def failures(results: list[ConditionResult]) -> list[ConditionResult]:
    return [r for r in results if not r.passed]
