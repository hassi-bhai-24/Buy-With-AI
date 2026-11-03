"""Math tests: spoilage decay, cash flow, land conversion, APR."""

import math

import pytest

from app.services.cash_flow import CashFlowInputs, build_cash_flow
from app.services.rules import (
    audit_installment_plan,
    convert_acre_to_kanal,
    convert_kanal_to_marla,
    convert_land,
    convert_marla_to_sqft,
    lambda_for_temperature,
    salable_quantity,
)


def test_lambda_bands():
    assert lambda_for_temperature(10) == 0.008
    assert lambda_for_temperature(22) == 0.008
    assert lambda_for_temperature(23) == 0.025
    assert lambda_for_temperature(32) == 0.025
    assert lambda_for_temperature(33) == 0.055
    assert lambda_for_temperature(40) == 0.055


def test_salable_quantity_formula():
    qty = salable_quantity(30.0, 24.0, 20.0, 0.10)
    expected = 30.0 * math.exp(-0.008 * 24) * 0.90
    assert qty == pytest.approx(expected)
    # Hotter storage decays faster.
    assert salable_quantity(30.0, 24.0, 38.0, 0.10) < qty
    # No time elapsed: only transit damage applies.
    assert salable_quantity(30.0, 0.0, 20.0, 0.10) == pytest.approx(27.0)


def test_cash_flow_ordering_best_expected_worst():
    table, spoilage, _margin = build_cash_flow(
        CashFlowInputs(
            quantity=30.0,
            wholesale_price_per_unit=80.0,
            retail_price_per_unit=105.0,
            days_to_sell=7,
            temperature_c=32.0,
            temperature_assumed=False,
            transit_damage=0.10,
        )
    )
    assert table.best_case.net_profit_loss > table.expected_case.net_profit_loss
    assert table.expected_case.net_profit_loss > table.worst_case.net_profit_loss
    assert table.best_case.spoilage_loss_percent == pytest.approx(2.0)
    assert table.worst_case.spoilage_loss_percent == pytest.approx(25.0)
    assert spoilage.temperature_c == 32.0
    assert spoilage.lambda_per_hour == 0.025
    assert spoilage.hours_to_sell == pytest.approx(168.0)


def test_cash_flow_best_case_numbers_short_horizon():
    # 1 day at 20C: expected salable is high; best case is near the
    # textbook example (29.4 kg salable, 2% loss).
    table, _spoilage, _margin = build_cash_flow(
        CashFlowInputs(
            quantity=30.0,
            wholesale_price_per_unit=80.0,
            retail_price_per_unit=105.0,
            days_to_sell=1,
            temperature_c=20.0,
            temperature_assumed=False,
            transit_damage=0.0,
        )
    )
    assert table.best_case.spoilage_loss_percent == pytest.approx(2.0)
    assert table.best_case.net_profit_loss > 0


def test_cash_flow_rejects_non_positive_quantity():
    with pytest.raises(ValueError):
        build_cash_flow(
            CashFlowInputs(
                quantity=0,
                wholesale_price_per_unit=80.0,
                retail_price_per_unit=105.0,
                days_to_sell=7,
                temperature_c=32.0,
                temperature_assumed=False,
            )
        )


def test_land_conversions():
    assert convert_marla_to_sqft(5, standard="punjab_225") == 1125.0
    assert convert_marla_to_sqft(5, standard="lahore_272") == 1360.0
    assert convert_marla_to_sqft(5, standard="225") == 1125.0
    assert convert_marla_to_sqft(5, standard="272") == 1360.0
    # Revenue standard keeps the documented 272.25 factor.
    assert convert_marla_to_sqft(5, standard="272.25") == pytest.approx(1361.25)
    assert convert_kanal_to_marla(2) == 40.0
    assert convert_acre_to_kanal(1) == 8.0
    assert convert_land(1, "kanal", "marla", "225") == 20.0
    assert convert_land(1, "acre", "sqft", "225") == pytest.approx(43560.0)
    assert convert_land(1125, "sqft", "marla", "225") == pytest.approx(5.0)
    assert convert_land(5, "marla", "kanal", "225") == pytest.approx(0.25)
    with pytest.raises(ValueError):
        convert_land(1, "furlong", "marla", "225")


def test_installment_apr_constant_ratio():
    audit = audit_installment_plan(
        cash_price=165_000, down_payment=20_000,
        monthly_installment=18_500, months=12,
    )
    assert audit.total_paid == pytest.approx(242_000.0)
    assert audit.finance_charge == pytest.approx(77_000.0)
    assert audit.markup_percent == pytest.approx(46.67, abs=0.01)
    # The documented constant-ratio formula yields ~98% for these inputs,
    # not the ~42% quoted in the test plan; the formula is authoritative.
    assert audit.apr_percent == pytest.approx(98.04, abs=1.0)
    assert audit.markup_percent > 35


# ---------------------------------------------------------------------------
# Cash-flow IRR (Part 2): effective annual rate alongside the legacy figure.
# ---------------------------------------------------------------------------


def _npv_at_effective_rate(audit) -> float:
    """NPV of the plan at the monthly rate implied by the effective rate.

    Inverts effective_annual_rate_percent back to a monthly rate and
    discounts the installments against the financed principal. At the
    true IRR this is ~0; it is recomputed here, independently of the
    solver in rules.py, from the returned effective rate alone.
    """
    monthly = (1.0 + audit.effective_annual_rate_percent / 100.0) ** (1.0 / 12.0) - 1.0
    principal = audit.cash_price - audit.down_payment
    present_value = sum(
        audit.monthly_installment / (1.0 + monthly) ** t
        for t in range(1, audit.months + 1)
    )
    return principal - present_value


def test_installment_irr_zero_interest_case():
    audit = audit_installment_plan(
        cash_price=1200, down_payment=0, monthly_installment=100, months=12,
    )
    assert audit.total_paid == pytest.approx(1200.0)
    assert audit.finance_charge == pytest.approx(0.0)
    assert audit.apr_percent == pytest.approx(0.0)
    assert audit.effective_annual_rate_percent == pytest.approx(0.0)
    assert audit.apr_method.startswith("cash-flow IRR")
    assert "no finance charge" in audit.apr_method
    assert _npv_at_effective_rate(audit) == pytest.approx(0.0, abs=1e-6)


def test_installment_irr_single_month_hand_computable():
    # 1000 financed, repaid as 1100 after one month: monthly rate 10%,
    # effective annual rate (1.10**12 - 1) * 100 = 213.84%.
    audit = audit_installment_plan(
        cash_price=1000, down_payment=0, monthly_installment=1100, months=1,
    )
    assert audit.effective_annual_rate_percent == pytest.approx(213.84, abs=0.01)
    assert audit.apr_method == "cash-flow IRR (effective annual rate)"
    assert _npv_at_effective_rate(audit) == pytest.approx(0.0, abs=1e-6)


def test_installment_irr_documented_example_is_not_42_percent():
    audit = audit_installment_plan(
        cash_price=165_000, down_payment=20_000,
        monthly_installment=18_500, months=12,
    )
    # Legacy constant-ratio figure is unchanged (regression).
    assert audit.apr_percent == pytest.approx(98.04, abs=1.0)
    # Cash-flow IRR: monthly 7.2502%, nominal 87.00%, effective 131.62%.
    # No standard IRR on these inputs yields ~42% (see NOTES.md).
    assert audit.effective_annual_rate_percent == pytest.approx(131.62, abs=0.5)
    assert audit.effective_annual_rate_percent != pytest.approx(42.0, abs=5.0)
    assert audit.apr_method == "cash-flow IRR (effective annual rate)"
    assert _npv_at_effective_rate(audit) == pytest.approx(0.0, abs=0.1)


def test_installment_irr_edge_cases_return_zero():
    # Zero finance charge (total paid equals cash price).
    audit = audit_installment_plan(
        cash_price=12_000, down_payment=0, monthly_installment=1000, months=12,
    )
    assert audit.effective_annual_rate_percent == pytest.approx(0.0)
    assert "no finance charge" in audit.apr_method

    # Discount: total paid below the cash price.
    audit = audit_installment_plan(
        cash_price=12_000, down_payment=0, monthly_installment=900, months=12,
    )
    assert audit.effective_annual_rate_percent == pytest.approx(0.0)

    # Down payment covers (or exceeds) the cash price.
    audit = audit_installment_plan(
        cash_price=10_000, down_payment=10_000, monthly_installment=500, months=12,
    )
    assert audit.effective_annual_rate_percent == pytest.approx(0.0)
    assert "down payment" in audit.apr_method
    audit = audit_installment_plan(
        cash_price=10_000, down_payment=12_000, monthly_installment=100, months=12,
    )
    assert audit.effective_annual_rate_percent == pytest.approx(0.0)

    # Zero installment.
    audit = audit_installment_plan(
        cash_price=10_000, down_payment=0, monthly_installment=0, months=12,
    )
    assert audit.effective_annual_rate_percent == pytest.approx(0.0)
    assert "no installments" in audit.apr_method


def test_installment_irr_bracket_expands_for_extreme_rate():
    # Monthly rate above 100%: the [0, 1.0] bracket must expand, and
    # the returned effective rate must still solve NPV ~= 0.
    audit = audit_installment_plan(
        cash_price=1000, down_payment=0, monthly_installment=10_000, months=12,
    )
    assert math.isfinite(audit.effective_annual_rate_percent)
    assert audit.effective_annual_rate_percent > 0
    assert audit.apr_method == "cash-flow IRR (effective annual rate)"
    assert _npv_at_effective_rate(audit) == pytest.approx(0.0, abs=0.1)
