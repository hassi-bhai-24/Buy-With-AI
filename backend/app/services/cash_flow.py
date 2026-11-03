"""3-scenario cash-flow engine for perishable / inventory lots.

Net profit formula (heuristics 2.1):
  Net = salable * P_retail + unsalable * P_liquidation
        - (Q0 * P_wholesale + transport + mandi_tax)
Transport is 0 unless supplied and mandi tax is 5% of the purchase cost;
both are stated explicitly in every scenario rationale so no cost is
hidden. Liquidation price is 50% of the expected retail price.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..schemas.response import CashFlowScenario, CashFlowTable, SpoilageSummary
from .rules import lambda_for_temperature, salable_quantity

MANDI_TAX_RATE = 0.05
LIQUIDATION_FRACTION = 0.5


@dataclass(frozen=True)
class CashFlowInputs:
    quantity: float
    wholesale_price_per_unit: float
    retail_price_per_unit: float
    days_to_sell: int
    temperature_c: float
    temperature_assumed: bool
    transit_damage: float = 0.10


def build_cash_flow(
    inputs: CashFlowInputs, transport_cost: float = 0.0
) -> tuple[CashFlowTable, SpoilageSummary, float]:
    """Return (cash-flow table, spoilage summary, expected margin %).

    Scenarios:
    * Best: 2% loss, selling price = retail * 1.1.
    * Expected: modelled spoilage decay, selling price = retail.
    * Worst: 25% loss, selling price = 50% of retail (liquidation).
    Unsold stock in best/expected is liquidated at 50% of retail.
    """
    qty = inputs.quantity
    if qty <= 0:
        raise ValueError("quantity must be > 0")
    # Defensive clamping (Part 3): a direct caller must not be able
    # to produce negative salable quantities or salable > qty via an
    # out-of-range transit fraction or a negative time horizon. The
    # API schema already rejects transit_damage_percent outside
    # [0, 0.9]; this clamp is the second line of defence for
    # in-process callers. Hours are floored at 0.
    transit_damage = min(0.9, max(0.0, float(inputs.transit_damage)))
    hours = max(0.0, float(inputs.days_to_sell) * 24.0)
    cost = qty * inputs.wholesale_price_per_unit
    tax = MANDI_TAX_RATE * cost
    total_cost = cost + transport_cost + tax

    expected_salable = salable_quantity(
        qty, hours, inputs.temperature_c, transit_damage
    )
    expected_loss_pct = (1.0 - expected_salable / qty) * 100.0 if qty else 0.0

    def scenario(
        name: str,
        salable: float,
        selling_price: float,
        loss_pct: float,
        liquidate_unsalable: bool,
    ) -> CashFlowScenario:
        unsalable = max(qty - salable, 0.0)
        revenue = salable * selling_price
        if liquidate_unsalable:
            revenue += unsalable * LIQUIDATION_FRACTION * inputs.retail_price_per_unit
        net = revenue - total_cost
        turnover = f"{(salable / qty * 100.0):.0f}%" if qty else "0%"
        rationale = (
            f"Salable {salable:.1f} of {qty:g} at {selling_price:,.0f} per unit; "
            f"cost {cost:,.0f} plus mandi tax 5% ({tax:,.0f}) and transport "
            f"{transport_cost:,.0f} (assumed zero unless supplied); "
            f"unsalable stock liquidated at 50% of retail."
            if liquidate_unsalable
            else f"Salable {salable:.1f} of {qty:g} liquidated at 50% of retail; "
            f"cost {cost:,.0f} plus mandi tax 5% ({tax:,.0f}) and transport "
            f"{transport_cost:,.0f} (assumed zero unless supplied)."
        )
        return CashFlowScenario(
            scenario_name=name,
            turnover_rate=turnover,
            spoilage_loss_percent=round(loss_pct, 2),
            net_profit_loss=round(net, 2),
            rationale=rationale,
        )

    best = scenario(
        "Best Case", qty * 0.98, inputs.retail_price_per_unit * 1.1, 2.0, True
    )
    expected = scenario(
        "Expected Case", expected_salable, inputs.retail_price_per_unit,
        expected_loss_pct, True,
    )
    worst = scenario(
        "Worst Case", qty * 0.75, inputs.retail_price_per_unit * 0.5, 25.0, False
    )

    table = CashFlowTable(best_case=best, expected_case=expected, worst_case=worst)
    expected_margin = (expected.net_profit_loss / total_cost * 100.0) if total_cost else 0.0

    spoilage = SpoilageSummary(
        initial_quantity=qty,
        salable_quantity=round(expected_salable, 2),
        spoilage_loss_percent=round(expected_loss_pct, 2),
        lambda_per_hour=lambda_for_temperature(inputs.temperature_c),
        temperature_c=inputs.temperature_c,
        temperature_assumed=inputs.temperature_assumed,
        transit_damage_fraction=transit_damage,
        hours_to_sell=hours,
        rationale=(
            f"Decay lambda {lambda_for_temperature(inputs.temperature_c)} per hour "
            f"at {inputs.temperature_c}°C over {hours:.0f} hours with "
            f"{transit_damage:.0%} transit damage; "
            f"{expected_loss_pct:.1f}% of the lot is expected to be unsalable."
        ),
    )
    return table, spoilage, expected_margin
