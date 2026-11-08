"""Pure, allowlisted, deterministic sandbox tasks; never execute recorded code."""
from __future__ import annotations
from decimal import Decimal
from typing import Any

# Fixtures have known ground truth, NOT inferred from a model-generated answer.
DECIMAL_SUM_CASES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("0.1", "0.2"), "0.3"),
    (("0.1", "0.2", "0.3"), "0.6"),
    (("0.7", "0.1"), "0.8"),
    (("1.01", "2.02", "3.03"), "6.06"),
    (("0.01", "0.02"), "0.03"),
    (("12.10", "0.20"), "12.30"),
)


def decimal_sum(inputs: tuple[str, ...], action: str) -> str:
    """Report a numeric result, not a tolerance-based approximation."""
    if action == "binary_float":
        return str(sum(float(x) for x in inputs))
    if action == "decimal_arithmetic":
        return str(sum((Decimal(x) for x in inputs), Decimal(0)))
    raise ValueError("Action not in allowlist")


def evaluate_counterfactual(scenario: str, original_action: str) -> dict[str, Any] | None:
    """Return measured synthetic evidence for an allowlisted experiment.

    This does NOT generalize beyond the pre-registered cases.
    """
    if scenario != "decimal_sum" or original_action not in {"binary_float", "decimal_arithmetic"}:
        return None
    alternatives = ("binary_float", "decimal_arithmetic")
    scores: dict[str, int] = {}
    for action in alternatives:
        scores[action] = sum(
            Decimal(decimal_sum(inputs, action)) == Decimal(expected)
            for inputs, expected in DECIMAL_SUM_CASES
        )
    best = max(alternatives, key=lambda a: (scores[a], a == "decimal_arithmetic"))
    baseline = scores[original_action]
    passed = scores[best]
    improved = (best != original_action and passed - baseline >= 2 and passed >= 5)
    return {
        "scenario": scenario,
        "original_action": original_action,
        "proposed_action": best,
        "cases": len(DECIMAL_SUM_CASES),
        "baseline_pass": baseline,
        "candidate_pass": passed,
        "improved": improved,
        "rule": "Use decimal_arithmetic for exact decimal-valued monetary summation in this sandbox.",
        "scope": "Only the registered decimal_sum fixtures; validate separately in production.",
    }
