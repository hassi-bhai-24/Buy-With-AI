"""Perishable edge cases (Part 3): defensive math, transit-damage
override + assumptions transparency, and API validation of the new
field. Best/expected/worst scenarios are unchanged."""

from __future__ import annotations

import math

import pytest

from app.services.cash_flow import CashFlowInputs, build_cash_flow
from app.services.rules import salable_quantity
from tests.helpers import add_baseline

TOMATO = {
    "description": "30 kg tomatoes wholesale at Bahawalpur mandi",
    "category": "perishable",
    "asking_price": 2400.0,
    "quantity": 30,
    "unit": "kg",
    "days_to_sell": 7,
}


def _inputs(**overrides):
    base = dict(
        quantity=30.0,
        wholesale_price_per_unit=80.0,
        retail_price_per_unit=105.0,
        days_to_sell=7,
        temperature_c=32.0,
        temperature_assumed=False,
        transit_damage=0.10,
    )
    base.update(overrides)
    return CashFlowInputs(**base)


def test_build_cash_flow_rejects_zero_and_negative_quantity():
    with pytest.raises(ValueError):
        build_cash_flow(_inputs(quantity=0))
    with pytest.raises(ValueError):
        build_cash_flow(_inputs(quantity=-5))


def test_selling_price_zero_gives_no_positive_profit():
    # Retail 0: liquidation is also 0, so every scenario's net must
    # be <= 0 (the purchase cost is still paid) — never a profit.
    table, spoilage, _margin = build_cash_flow(_inputs(retail_price_per_unit=0.0))
    assert table.best_case.net_profit_loss <= 0
    assert table.expected_case.net_profit_loss <= 0
    assert table.worst_case.net_profit_loss <= 0
    assert spoilage.salable_quantity >= 0


def test_extreme_spoilage_is_finite_and_bounded():
    table, spoilage, margin = build_cash_flow(
        _inputs(days_to_sell=365, temperature_c=55.0)
    )
    assert spoilage.salable_quantity >= 0
    assert 0 <= spoilage.spoilage_loss_percent <= 100
    for case in (table.best_case, table.expected_case, table.worst_case):
        assert math.isfinite(case.net_profit_loss)
        assert 0 <= case.spoilage_loss_percent <= 100
    assert math.isfinite(margin)
    assert math.isfinite(spoilage.lambda_per_hour)


def test_days_to_sell_zero_direct_call():
    table, spoilage, _margin = build_cash_flow(_inputs(days_to_sell=0))
    # hours 0: only transit damage applies.
    assert spoilage.hours_to_sell == 0
    assert spoilage.salable_quantity == pytest.approx(30.0 * 0.9)
    for case in (table.best_case, table.expected_case, table.worst_case):
        assert math.isfinite(case.net_profit_loss)


def test_negative_temperature_within_schema_range_is_finite():
    table, spoilage, _margin = build_cash_flow(_inputs(temperature_c=-10.0))
    assert spoilage.lambda_per_hour == 0.008
    assert spoilage.salable_quantity >= 0
    assert math.isfinite(table.expected_case.net_profit_loss)


def test_transit_damage_09_is_allowed_and_non_negative():
    _table, spoilage, _margin = build_cash_flow(_inputs(transit_damage=0.9))
    assert spoilage.salable_quantity >= 0
    assert spoilage.transit_damage_fraction == pytest.approx(0.9)


def test_transit_damage_clamped_defensively_for_direct_callers():
    # Above 0.9: clamped to 0.9, never a negative salable quantity.
    _table, spoilage, _margin = build_cash_flow(_inputs(transit_damage=1.5))
    assert spoilage.transit_damage_fraction == pytest.approx(0.9)
    assert spoilage.salable_quantity >= 0
    # Negative: clamped to 0.
    _table, spoilage, _margin = build_cash_flow(_inputs(transit_damage=-0.5))
    assert spoilage.transit_damage_fraction == pytest.approx(0.0)
    assert spoilage.salable_quantity <= 30.0
    # salable_quantity itself clamps too.
    assert salable_quantity(30.0, 24.0, 20.0, 2.0) >= 0
    assert salable_quantity(30.0, 24.0, 20.0, -1.0) <= 30.0


# ---------------------------------------------------------------------------
# API: override wiring, assumptions, validation
# ---------------------------------------------------------------------------


async def _seed(db_session):
    await add_baseline(db_session, "tomato")


async def test_api_transit_damage_override_wires_through(client, db_session):
    await _seed(db_session)
    default = client.post("/api/v1/analyze", json=TOMATO).json()
    assert default["spoilage"]["transit_damage_fraction"] == pytest.approx(0.10)
    overridden = client.post(
        "/api/v1/analyze",
        json={**TOMATO, "transit_damage_percent": 0.5},
    ).json()
    assert overridden["spoilage"]["transit_damage_fraction"] == pytest.approx(0.5)
    assert (
        overridden["spoilage"]["salable_quantity"]
        < default["spoilage"]["salable_quantity"]
    )


async def test_api_assumptions_only_for_values_not_supplied(client, db_session):
    await _seed(db_session)
    # Nothing supplied: selling price, temperature and transit
    # assumptions all appear, with concrete values.
    body = client.post("/api/v1/analyze", json=TOMATO).json()
    assumptions = body["spoilage"]["assumptions"]
    assert any("selling price" in a.lower() for a in assumptions)
    assert any("32" in a for a in assumptions)
    assert any("10%" in a for a in assumptions)
    assert any("not guaranteed" in a for a in assumptions)
    # Everything supplied: no value assumptions remain, only the
    # projection disclaimer.
    supplied = client.post(
        "/api/v1/analyze",
        json={
            **TOMATO,
            "selling_price": 105.0,
            "temperature_c": 20.0,
            "transit_damage_percent": 0.05,
        },
    ).json()
    supplied_assumptions = supplied["spoilage"]["assumptions"]
    assert supplied_assumptions == [
        "Profit figures are projections based on these assumptions, not guaranteed."
    ]


async def test_api_assumptions_survive_history_round_trip(client, db_session):
    await _seed(db_session)
    created = client.post("/api/v1/analyze", json=TOMATO).json()
    history = client.get(f"/api/v1/checks/{created['id']}").json()
    assert history["spoilage"]["assumptions"] == created["spoilage"]["assumptions"]
    assert history["spoilage"]["assumptions"]


async def test_api_quantity_zero_and_transit_out_of_range_422(client):
    assert (
        client.post("/api/v1/analyze", json={**TOMATO, "quantity": 0}).status_code
        == 422
    )
    assert (
        client.post(
            "/api/v1/analyze", json={**TOMATO, "transit_damage_percent": 1.5}
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/v1/analyze", json={**TOMATO, "transit_damage_percent": -0.1}
        ).status_code
        == 422
    )
    # Boundary 0.9 is accepted.
    assert (
        client.post(
            "/api/v1/analyze", json={**TOMATO, "transit_damage_percent": 0.9}
        ).status_code
        == 200
    )


async def test_api_selling_price_and_temperature_still_wired(client, db_session):
    await _seed(db_session)
    body = client.post(
        "/api/v1/analyze",
        json={**TOMATO, "selling_price": 120.0, "temperature_c": 20.0},
    ).json()
    assert body["spoilage"]["temperature_c"] == 20.0
    assert body["spoilage"]["temperature_assumed"] is False
