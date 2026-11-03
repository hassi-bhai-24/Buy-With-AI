"""Phase 2 (rest): checks shape, 4 calculators, integrations, enrichment.

Upstream HTTP is mocked with a fake httpx.AsyncClient (no new test
dependencies, no network). The integrations router is mounted here
under /api/v1 for testing only — main.py wiring is the coordinator's
job; the guard below keeps the mount idempotent if main.py already
wires it.
"""

from __future__ import annotations

import time
from unittest.mock import AsyncMock

import httpx
import pytest

from app.main import app
from app.routers import integrations as integrations_router
from app.services import integrations
from app.services.calculators import (
    discount_validator,
    expense_leakage,
    savings_goal,
)
from tests.helpers import add_baseline

if not any(
    getattr(route, "path", "") == "/api/v1/geo/geocode" for route in app.routes
):
    app.include_router(integrations_router.router, prefix="/api/v1")


# -- fake httpx ------------------------------------------------------------


class _FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        if isinstance(self._payload, Exception):
            raise self._payload
        return self._payload


class _FakeClient:
    def __init__(self, handler, *args, **kwargs):
        self._handler = handler

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def get(self, url, params=None, **kwargs):
        return self._handler(url, params)


def _patch_httpx(monkeypatch, handler):
    def _factory(*args, **kwargs):
        return _FakeClient(handler)

    monkeypatch.setattr(httpx, "AsyncClient", _factory)


def _clear(monkeypatch):
    integrations.clear_integration_caches()


# -- 1. checks shape ---------------------------------------------------------


async def test_checks_shape_total_and_filter(client, db_session):
    await add_baseline(db_session, "tomato")
    payloads = [
        {
            "description": "30 kg tomatoes wholesale",
            "category": "perishable",
            "asking_price": 2400.0,
            "quantity": 30,
            "unit": "kg",
        },
        {
            "description": "10 kg tomatoes wholesale",
            "category": "perishable",
            "asking_price": 800.0,
            "quantity": 10,
            "unit": "kg",
        },
        {
            "description": "used bicycle for sale",
            "category": "vehicle",
            "asking_price": 20000.0,
            "quantity": 1,
            "unit": "unit",
        },
    ]
    for payload in payloads:
        assert client.post("/api/v1/analyze", json=payload).status_code == 200
    page = client.get("/api/v1/checks", params={"limit": 2})
    assert page.status_code == 200
    body = page.json()
    assert set(body.keys()) == {"items", "total"}
    assert len(body["items"]) == 2
    assert body["total"] == 3
    filtered = client.get(
        "/api/v1/checks", params={"category": "vehicle"}
    ).json()
    assert filtered["total"] == 1
    assert len(filtered["items"]) == 1
    filtered = client.get(
        "/api/v1/checks", params={"category": "perishable"}
    ).json()
    assert filtered["total"] == 2
    assert len(filtered["items"]) == 2


# -- 2a. savings goal --------------------------------------------------------


def test_savings_goal_unit():
    assert savings_goal(1200, 0, monthly_deposit=100) == {
        "monthly_deposit_required": 100.0,
        "months_required": 12,
        "target_amount": 1200.0,
        "current_savings": 0.0,
        "shortfall": 1200.0,
        "feasible": True,
    }
    # ceil(1000/300)=4 months; required deposit is shortfall/months.
    result = savings_goal(1000, 0, monthly_deposit=300)
    assert result["months_required"] == 4
    assert result["monthly_deposit_required"] == pytest.approx(250.0)
    result = savings_goal(1000, 200, months=4)
    assert result["monthly_deposit_required"] == pytest.approx(200.0)
    assert result["months_required"] == 4
    # Already funded.
    result = savings_goal(500, 600, monthly_deposit=100)
    assert result == {
        "monthly_deposit_required": 0.0,
        "months_required": 0,
        "target_amount": 500.0,
        "current_savings": 600.0,
        "shortfall": 0.0,
        "feasible": True,
    }
    # Both supplied but insufficient: infeasible, numbers still reported.
    result = savings_goal(1000, 0, monthly_deposit=100, months=5)
    assert result["feasible"] is False
    assert result["months_required"] == 5
    with pytest.raises(ValueError):
        savings_goal(1000, 0)


def test_savings_goal_api(client):
    body = client.post(
        "/api/v1/tools/savings-goal",
        json={"target_amount": 1200, "current_savings": 0, "monthly_deposit": 100},
    ).json()
    assert body["months_required"] == 12
    assert body["monthly_deposit_required"] == pytest.approx(100.0)
    assert body["feasible"] is True
    assert body["shortfall"] == pytest.approx(1200.0)
    # 422: neither timeline input, non-positive deposit, non-positive target.
    assert client.post(
        "/api/v1/tools/savings-goal",
        json={"target_amount": 1000, "current_savings": 0},
    ).status_code == 422
    assert client.post(
        "/api/v1/tools/savings-goal",
        json={"target_amount": 1000, "monthly_deposit": 0},
    ).status_code == 422
    assert client.post(
        "/api/v1/tools/savings-goal",
        json={"target_amount": 0, "months": 6},
    ).status_code == 422


# -- 2b. expense leakage -----------------------------------------------------


def test_expense_leakage_unit():
    expenses = [
        {"name": "Rent", "amount": 30000, "category": "Housing"},
        {"name": "Groceries", "amount": 10000, "category": "groceries"},
        {"name": "Dining out", "amount": 20000, "category": "dining"},
        {"name": "Shopping", "amount": 15000, "category": "shopping"},
        {"name": "Clinic", "amount": 5000, "category": "health"},
    ]
    result = expense_leakage(100000, expenses)
    assert result["total_expenses"] == pytest.approx(80000.0)
    assert result["essential_total"] == pytest.approx(45000.0)
    assert result["discretionary_total"] == pytest.approx(35000.0)
    assert result["discretionary_percent"] == pytest.approx(35.0)
    assert result["savings_rate_percent"] == pytest.approx(20.0)
    assert any("30%" in flag for flag in result["flags"])
    assert any("Dining out" in flag for flag in result["flags"])
    assert "housing" in result["notes"].lower()
    assert "discretionary" in result["notes"].lower()
    # Overspend flag + empty expenses.
    result = expense_leakage(1000, [{"name": "Rent", "amount": 1500, "category": "housing"}])
    assert any("exceed" in flag for flag in result["flags"])
    assert result["savings_rate_percent"] == pytest.approx(-50.0)
    result = expense_leakage(5000, [])
    assert result["total_expenses"] == 0.0
    assert result["flags"] == []


def test_expense_leakage_api(client):
    body = client.post(
        "/api/v1/tools/expense-leakage",
        json={
            "income": 100000,
            "expenses": [
                {"name": "Rent", "amount": 30000, "category": "housing"},
                {"name": "Dining out", "amount": 40000, "category": "dining"},
            ],
        },
    ).json()
    assert body["discretionary_percent"] == pytest.approx(40.0)
    assert any("Dining out" in flag for flag in body["flags"])
    assert client.post(
        "/api/v1/tools/expense-leakage", json={"income": 0, "expenses": []}
    ).status_code == 422
    assert client.post(
        "/api/v1/tools/expense-leakage",
        json={"income": 1000, "expenses": [{"name": "X", "amount": -1, "category": "other"}]},
    ).status_code == 422


# -- 2c. discount validator --------------------------------------------------


def test_discount_validator_unit():
    result = discount_validator(800, 1000, 1000)
    assert result["claimed_discount_percent"] == pytest.approx(20.0)
    assert result["real_discount_percent"] == pytest.approx(20.0)
    assert result["fake_discount"] is False
    assert result["inflated_original"] is False
    # Fake: claimed original > baseline * 1.05.
    result = discount_validator(800, 1200, 1000)
    assert result["fake_discount"] is True
    assert result["inflated_original"] is True
    assert result["real_discount_percent"] == pytest.approx(20.0)
    assert "5%" in result["verdict_text"]
    # Within the 5% tolerance: inflated but not fake.
    result = discount_validator(800, 1040, 1000)
    assert result["inflated_original"] is True
    assert result["fake_discount"] is False
    # Negative real discount (advertised above baseline).
    result = discount_validator(900, 1000, 800)
    assert result["real_discount_percent"] == pytest.approx(-12.5)
    with pytest.raises(ValueError):
        discount_validator(1100, 1000, 1000)


def test_discount_validator_api(client):
    body = client.post(
        "/api/v1/tools/discount-validator",
        json={
            "advertised_price": 800,
            "claimed_original_price": 1200,
            "baseline_price": 1000,
        },
    ).json()
    assert body["fake_discount"] is True
    assert body["claimed_discount_percent"] == pytest.approx(33.33, abs=0.01)
    assert client.post(
        "/api/v1/tools/discount-validator",
        json={
            "advertised_price": 1100,
            "claimed_original_price": 1000,
            "baseline_price": 1000,
        },
    ).status_code == 422


# -- 3a. Nominatim -----------------------------------------------------------


async def test_geocode_success_cache_and_throttle(monkeypatch):
    integrations.clear_integration_caches()
    calls = []

    def handler(url, params):
        calls.append((url, params))
        assert "nominatim.openstreetmap.org" in url
        return _FakeResponse(
            200,
            [
                {
                    "lat": "29.3544",
                    "lon": "71.6911",
                    "display_name": "Bahawalpur, Punjab, Pakistan",
                }
            ],
        )

    _patch_httpx(monkeypatch, handler)
    result = await integrations.geocode_place("Bahawalpur")
    assert result == {
        "lat": 29.3544,
        "lon": 71.6911,
        "display_name": "Bahawalpur, Punjab, Pakistan",
        "source": "nominatim",
    }
    # Cache: same query (different case) makes no second HTTP call.
    assert await integrations.geocode_place("BAHAWALPUR") == result
    assert len(calls) == 1
    # Throttle: a different query waits ~1s after the previous call.
    started = time.monotonic()
    await integrations.geocode_place("Lahore")
    assert time.monotonic() - started >= 0.9
    assert len(calls) == 2
    integrations.clear_integration_caches()


async def test_geocode_not_found_and_failure(monkeypatch):
    integrations.clear_integration_caches()

    def empty_handler(url, params):
        return _FakeResponse(200, [])

    _patch_httpx(monkeypatch, empty_handler)
    with pytest.raises(integrations.GeocodeNotFound):
        await integrations.geocode_place("nowhere-place-xyz")

    def failing_handler(url, params):
        return _FakeResponse(500, {})

    _patch_httpx(monkeypatch, failing_handler)
    integrations.clear_integration_caches()
    with pytest.raises(integrations.UpstreamError):
        await integrations.geocode_place("Bahawalpur")
    integrations.clear_integration_caches()


def test_geocode_api_success_not_found_failure(client, monkeypatch):
    integrations.clear_integration_caches()
    calls = []

    def handler(url, params):
        calls.append(url)
        if params and params.get("q") == "Nowhere":
            return _FakeResponse(200, [])
        return _FakeResponse(
            200,
            [{"lat": "29.3544", "lon": "71.6911", "display_name": "Bahawalpur"}],
        )

    _patch_httpx(monkeypatch, handler)
    body = client.get("/api/v1/geo/geocode", params={"q": "Bahawalpur"})
    assert body.status_code == 200, body.text
    assert body.json()["source"] == "nominatim"
    assert body.json()["lat"] == pytest.approx(29.3544)
    assert client.get("/api/v1/geo/geocode", params={"q": "Nowhere"}).status_code == 404
    integrations.clear_integration_caches()

    def failing(url, params):
        return _FakeResponse(503, {})

    _patch_httpx(monkeypatch, failing)
    assert client.get("/api/v1/geo/geocode", params={"q": "Bahawalpur"}).status_code == 502
    integrations.clear_integration_caches()


# -- 3b. Open Food Facts / barcode -------------------------------------------


def test_barcode_check_digit():
    assert integrations.is_valid_barcode("3017620422003") is True  # Nutella
    assert integrations.is_valid_barcode("3017620422004") is False
    assert integrations.is_valid_barcode("12345670") is True  # EAN-8
    assert integrations.is_valid_barcode("12345671") is False
    assert integrations.is_valid_barcode("123") is False
    assert integrations.is_valid_barcode("301762042200a") is False
    assert integrations.is_valid_barcode("") is False


async def test_barcode_found_not_found_failure(monkeypatch):
    def found_handler(url, params):
        assert "world.openfoodfacts.org" in url
        assert url.endswith("/api/v2/product/3017620422003.json")
        return _FakeResponse(
            200,
            {
                "status": 1,
                "product": {
                    "product_name": "Nutella",
                    "ingredients_text": "sugar, palm oil, hazelnuts",
                    "nutriscore_grade": "e",
                },
            },
        )

    _patch_httpx(monkeypatch, found_handler)
    result = await integrations.fetch_product_by_barcode("3017620422003")
    assert result["found"] is True
    assert result["product_name"] == "Nutella"
    assert result["nutriscore"] == "e"
    assert result["source"] == "openfoodfacts"

    def absent_handler(url, params):
        return _FakeResponse(200, {"status": 0})

    _patch_httpx(monkeypatch, absent_handler)
    result = await integrations.fetch_product_by_barcode("3017620422003")
    assert result["found"] is False
    assert result["product_name"] is None

    def failing_handler(url, params):
        return _FakeResponse(500, {})

    _patch_httpx(monkeypatch, failing_handler)
    with pytest.raises(integrations.UpstreamError):
        await integrations.fetch_product_by_barcode("3017620422003")
    with pytest.raises(ValueError):
        await integrations.fetch_product_by_barcode("123")


def test_barcode_api(client, monkeypatch):
    def handler(url, params):
        return _FakeResponse(
            200,
            {
                "status": 1,
                "product": {
                    "product_name": "Nutella",
                    "ingredients_text": "sugar",
                    "nutriscore_grade": "e",
                },
            },
        )

    _patch_httpx(monkeypatch, handler)
    body = client.get("/api/v1/barcode/3017620422003")
    assert body.status_code == 200
    assert body.json()["found"] is True
    assert body.json()["source"] == "openfoodfacts"
    # Invalid check digit / wrong length -> 422, never a lookup.
    assert client.get("/api/v1/barcode/3017620422004").status_code == 422
    assert client.get("/api/v1/barcode/123").status_code == 422

    def absent(url, params):
        return _FakeResponse(200, {"status": 0})

    _patch_httpx(monkeypatch, absent)
    body = client.get("/api/v1/barcode/3017620422003")
    assert body.status_code == 200
    assert body.json()["found"] is False

    def failing(url, params):
        return _FakeResponse(500, {})

    _patch_httpx(monkeypatch, failing)
    assert client.get("/api/v1/barcode/3017620422003").status_code == 502


# -- 2d/3c. currency convert (Frankfurter) ------------------------------------


async def test_currency_convert_success_cache_and_failure(monkeypatch):
    integrations.clear_integration_caches()
    calls = []

    def handler(url, params):
        calls.append((url, params))
        assert "api.frankfurter.app" in url
        return _FakeResponse(
            200,
            {"amount": 1.0, "base": "USD", "date": "2026-11-03", "rates": {"PKR": 280.5}},
        )

    _patch_httpx(monkeypatch, handler)
    result = await integrations.convert_currency(100, "USD", "PKR")
    assert result["converted_amount"] == pytest.approx(28050.0)
    assert result["rate"] == pytest.approx(280.5)
    assert result["rate_date"] == "2026-11-03"
    assert result["source"] == "frankfurter"
    # Cached rate: second conversion makes no second HTTP call.
    assert await integrations.convert_currency(10, "USD", "PKR")
    assert len(calls) == 1
    # Identity needs no upstream call.
    result = await integrations.convert_currency(50, "PKR", "PKR")
    assert result["source"] == "identity"
    assert result["rate"] == 1.0
    assert result["converted_amount"] == 50
    integrations.clear_integration_caches()

    def failing(url, params):
        return _FakeResponse(500, {})

    _patch_httpx(monkeypatch, failing)
    with pytest.raises(integrations.UpstreamError):
        await integrations.convert_currency(100, "USD", "PKR")
    integrations.clear_integration_caches()


def test_currency_convert_api(client, monkeypatch):
    integrations.clear_integration_caches()
    calls = []

    def handler(url, params):
        calls.append(url)
        return _FakeResponse(
            200,
            {"amount": 1.0, "base": "USD", "date": "2026-11-03", "rates": {"PKR": 280.5}},
        )

    _patch_httpx(monkeypatch, handler)
    body = client.post(
        "/api/v1/tools/currency-convert",
        json={"amount": 100, "from_currency": "usd", "to_currency": "pkr"},
    )
    assert body.status_code == 200, body.text
    assert body.json()["converted_amount"] == pytest.approx(28050.0)
    assert body.json()["source"] == "frankfurter"
    assert body.json()["from_currency"] == "USD"
    # Identity.
    body = client.post(
        "/api/v1/tools/currency-convert",
        json={"amount": 50, "from_currency": "PKR", "to_currency": "PKR"},
    )
    assert body.json()["source"] == "identity"
    assert body.json()["converted_amount"] == 50
    # Bad code format -> 422.
    assert client.post(
        "/api/v1/tools/currency-convert",
        json={"amount": 1, "from_currency": "US", "to_currency": "PKR"},
    ).status_code == 422
    assert client.post(
        "/api/v1/tools/currency-convert",
        json={"amount": 1, "from_currency": "US1", "to_currency": "PKR"},
    ).status_code == 422
    integrations.clear_integration_caches()

    def failing(url, params):
        return _FakeResponse(500, {})

    _patch_httpx(monkeypatch, failing)
    response = client.post(
        "/api/v1/tools/currency-convert",
        json={"amount": 100, "from_currency": "USD", "to_currency": "PKR"},
    )
    assert response.status_code == 502, response.text
    assert "frankfurter" in response.text.lower()
    integrations.clear_integration_caches()


# -- 3d. analyze enrichment ---------------------------------------------------


async def test_analyze_enrichment_success(client, db_session, monkeypatch):
    await add_baseline(db_session, "tomato")
    monkeypatch.setattr(
        "app.services.analyzer.geocode_place",
        AsyncMock(
            return_value={
                "lat": 29.3544,
                "lon": 71.6911,
                "display_name": "Bahawalpur, Punjab, Pakistan",
                "source": "nominatim",
            }
        ),
    )
    body = client.post(
        "/api/v1/analyze",
        json={
            "description": "30 kg tomatoes wholesale",
            "category": "perishable",
            "asking_price": 2400.0,
            "quantity": 30,
            "unit": "kg",
        },
    ).json()
    assert body["coordinates"] == {
        "lat": 29.3544,
        "lon": 71.6911,
        "display_name": "Bahawalpur, Punjab, Pakistan",
    }
    # Coordinates are live-only: the persisted history row has none.
    listed = client.get("/api/v1/checks").json()
    assert listed["items"][0]["coordinates"] is None


async def test_analyze_enrichment_failure_leaves_verdict(client, db_session, monkeypatch):
    await add_baseline(db_session, "tomato")
    monkeypatch.setattr(
        "app.services.analyzer.geocode_place",
        AsyncMock(side_effect=RuntimeError("nominatim down")),
    )
    body = client.post(
        "/api/v1/analyze",
        json={
            "description": "30 kg tomatoes wholesale",
            "category": "perishable",
            "asking_price": 2400.0,
            "quantity": 30,
            "unit": "kg",
        },
    )
    assert body.status_code == 200
    assert body.json()["coordinates"] is None
    assert body.json()["verdict"] == "Think Twice"
