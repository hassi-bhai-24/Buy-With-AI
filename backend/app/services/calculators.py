"""Pure deterministic math for TOOL-2, TOOL-3 and TOOL-8.

No I/O, no LLM, no invented benchmarks: the only thresholds used are
the ones documented here (the 30% discretionary rule for TOOL-3 and
the 5% tolerance for TOOL-8). TOOL-5 (currency conversion) lives in
``integrations.py`` because it needs a live upstream rate.
"""

from __future__ import annotations

import math
from typing import Any

# TOOL-3 classification rule, documented in the response ``notes`` field:
# these categories are essential; every other category is discretionary.
ESSENTIAL_CATEGORIES = {
    "housing",
    "utilities",
    "groceries",
    "transport",
    "health",
    "education",
}

DISCRETIONARY_THRESHOLD_PERCENT = 30.0
FAKE_DISCOUNT_TOLERANCE = 0.05


def savings_goal(
    target_amount: float,
    current_savings: float,
    monthly_deposit: float | None = None,
    months: int | None = None,
) -> dict[str, Any]:
    """Interest-free timeline.

    ``months_required`` is ``months`` when given, else
    ``ceil(shortfall / monthly_deposit)``. ``monthly_deposit_required``
    is always ``shortfall / months_required`` (0 when already funded).
    ``feasible`` is False only when a supplied monthly deposit cannot
    reach the target within the supplied number of months.
    """
    if monthly_deposit is None and months is None:
        raise ValueError("Provide at least one of monthly_deposit or months.")
    shortfall = target_amount - current_savings
    if shortfall <= 0:
        return {
            "monthly_deposit_required": 0.0,
            "months_required": 0,
            "target_amount": round(target_amount, 2),
            "current_savings": round(current_savings, 2),
            "shortfall": 0.0,
            "feasible": True,
        }
    months_required = (
        months
        if months is not None
        else math.ceil(shortfall / monthly_deposit)  # type: ignore[operator]
    )
    monthly_required = shortfall / months_required
    feasible = True
    if monthly_deposit is not None and months is not None:
        feasible = monthly_deposit * months >= shortfall
    return {
        "monthly_deposit_required": round(monthly_required, 2),
        "months_required": months_required,
        "target_amount": round(target_amount, 2),
        "current_savings": round(current_savings, 2),
        "shortfall": round(shortfall, 2),
        "feasible": feasible,
    }


def _expense_fields(expense: Any) -> tuple[str, float, str]:
    if isinstance(expense, dict):
        return (
            str(expense["name"]),
            float(expense["amount"]),
            str(expense["category"]),
        )
    return str(expense.name), float(expense.amount), str(expense.category)


def expense_leakage(income: float, expenses: list[Any]) -> dict[str, Any]:
    """Classify expenses and flag leakage.

    Essential: housing, utilities, groceries, transport, health,
    education. Everything else is discretionary. Flags: discretionary
    spending above 30% of income; total expenses above income; and the
    single largest discretionary expense, named.
    """
    total = 0.0
    essential = 0.0
    discretionary = 0.0
    largest: tuple[str, float] | None = None
    for expense in expenses:
        name, amount, category = _expense_fields(expense)
        total += amount
        if category.strip().lower() in ESSENTIAL_CATEGORIES:
            essential += amount
        else:
            discretionary += amount
            if largest is None or amount > largest[1]:
                largest = (name, amount)
    discretionary_percent = discretionary / income * 100.0 if income else 0.0
    savings_rate = (income - total) / income * 100.0 if income else 0.0
    flags: list[str] = []
    if discretionary_percent > DISCRETIONARY_THRESHOLD_PERCENT:
        flags.append(
            f"Discretionary spending is {discretionary_percent:.1f}% of "
            f"income, above the 30% threshold."
        )
    if total > income:
        flags.append(
            f"Total expenses ({total:.2f}) exceed income ({income:.2f})."
        )
    if largest is not None:
        flags.append(
            f"Largest discretionary expense: {largest[0]} ({largest[1]:.2f})."
        )
    return {
        "income": round(income, 2),
        "total_expenses": round(total, 2),
        "essential_total": round(essential, 2),
        "discretionary_total": round(discretionary, 2),
        "discretionary_percent": round(discretionary_percent, 2),
        "savings_rate_percent": round(savings_rate, 2),
        "flags": flags,
        "notes": (
            "Essential categories are housing, utilities, groceries, "
            "transport, health, education; all other categories are "
            "treated as discretionary. A flag is raised when discretionary "
            "spending exceeds 30% of income."
        ),
    }


def discount_validator(
    advertised_price: float,
    claimed_original_price: float,
    baseline_price: float,
) -> dict[str, Any]:
    """Compare a claimed discount against the pre-sale baseline.

    ``fake_discount`` is True only when the claimed original price
    exceeds the baseline by more than the 5% tolerance; ``inflated_original``
    is True whenever the claimed original price is above the baseline
    at all. The real discount is measured against the baseline and can
    be negative when the advertised price is above the baseline.
    """
    if advertised_price > claimed_original_price:
        raise ValueError(
            "advertised_price must not exceed claimed_original_price"
        )
    claimed_pct = (
        (claimed_original_price - advertised_price) / claimed_original_price * 100.0
    )
    real_pct = (baseline_price - advertised_price) / baseline_price * 100.0
    inflated = claimed_original_price > baseline_price
    fake = claimed_original_price > baseline_price * (1.0 + FAKE_DISCOUNT_TOLERANCE)
    if fake:
        verdict_text = (
            f"Fake discount: the claimed original price is inflated above "
            f"the baseline price by more than the 5% tolerance, so the "
            f"claimed {claimed_pct:.2f}% discount overstates the real "
            f"{real_pct:.2f}% discount against the baseline."
        )
    elif inflated:
        verdict_text = (
            f"The claimed original price is slightly above the baseline "
            f"price, within the 5% tolerance; the real discount is "
            f"{real_pct:.2f}% versus a claimed {claimed_pct:.2f}%."
        )
    elif real_pct < 0:
        verdict_text = (
            f"No real discount: the advertised price is above the baseline "
            f"price, so the real discount is {real_pct:.2f}% versus a "
            f"claimed {claimed_pct:.2f}%."
        )
    else:
        verdict_text = (
            f"The claimed discount matches the baseline: the real discount "
            f"is {real_pct:.2f}% versus a claimed {claimed_pct:.2f}%."
        )
    return {
        "claimed_discount_percent": round(claimed_pct, 2),
        "real_discount_percent": round(real_pct, 2),
        "fake_discount": fake,
        "inflated_original": inflated,
        "verdict_text": verdict_text,
    }
