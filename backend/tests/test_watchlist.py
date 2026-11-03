"""Watchlist API tests.

Approach (per task brief): the new routers are NOT registered in
``app/main.py`` (the coordinator wires them), so these tests mount the
routers on a fresh FastAPI app in this module with the same ``get_db``
override and the same scraper/Ollama mocks as ``tests/conftest.py``.
The ``client`` fixture name intentionally shadows conftest's.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.database import get_db
from app.routers import analyze, watchlist
from app.routers.analyze import reset_rate_limits
from app.services.ollama_client import OllamaClient
from app.services.scraper import AsyncScraperService
from tests.helpers import add_baseline

TOMATO = {
    "description": "30 kg tomatoes wholesale at Bahawalpur mandi",
    "category": "perishable",
    "asking_price": 2400.0,
    "quantity": 30,
    "unit": "kg",
    "days_to_sell": 7,
}


@pytest.fixture()
def client(_engine, monkeypatch):
    session_factory = async_sessionmaker(_engine, expire_on_commit=False)

    async def override_get_db():
        async with session_factory() as session:
            yield session

    app = FastAPI()
    app.include_router(analyze.router, prefix="/api/v1")
    app.include_router(watchlist.router, prefix="/api/v1")
    app.dependency_overrides[get_db] = override_get_db
    reset_rate_limits()
    monkeypatch.setattr(
        AsyncScraperService, "search_market", AsyncMock(return_value=[])
    )
    monkeypatch.setattr(OllamaClient, "check_health", AsyncMock(return_value=False))
    monkeypatch.setattr(OllamaClient, "generate_verdict", AsyncMock(return_value=None))
    yield TestClient(app)
    app.dependency_overrides.clear()


async def _make_check(client, db_session):
    await add_baseline(db_session, "tomato")
    response = client.post("/api/v1/analyze", json=TOMATO)
    assert response.status_code == 200, response.text
    return response.json()


async def test_watchlist_create_list_delete(client, db_session):
    check = await _make_check(client, db_session)
    created = client.post(
        "/api/v1/watchlist",
        json={"check_id": check["id"], "target_price": 75.0},
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["check_id"] == check["id"]
    assert body["target_price"] == 75.0
    assert body["currency"] == "PKR"
    assert body["title"] == check["title"]
    assert body["created_at"]

    listed = client.get("/api/v1/watchlist")
    assert listed.status_code == 200
    assert len(listed.json()) == 1
    assert listed.json()[0]["id"] == body["id"]
    assert listed.json()[0]["title"] == check["title"]

    deleted = client.delete(f"/api/v1/watchlist/{body['id']}")
    assert deleted.status_code == 200
    assert deleted.json() == {"deleted": body["id"]}
    assert client.get("/api/v1/watchlist").json() == []
    assert client.delete(f"/api/v1/watchlist/{body['id']}").status_code == 404


async def test_watchlist_create_missing_check_and_bad_price(client, db_session):
    assert (
        client.post(
            "/api/v1/watchlist",
            json={"check_id": "does-not-exist", "target_price": 10},
        ).status_code
        == 404
    )
    check = await _make_check(client, db_session)
    assert (
        client.post(
            "/api/v1/watchlist",
            json={"check_id": check["id"], "target_price": 0},
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/v1/watchlist",
            json={"check_id": check["id"], "target_price": -5},
        ).status_code
        == 422
    )


async def test_watchlist_recheck_with_baseline(client, db_session):
    check = await _make_check(client, db_session)
    item = client.post(
        "/api/v1/watchlist",
        json={"check_id": check["id"], "target_price": 90.0},
    ).json()
    rechecked = client.post(f"/api/v1/watchlist/{item['id']}/recheck")
    assert rechecked.status_code == 200, rechecked.text
    body = rechecked.json()
    assert body["current_expected_price"] == 82.0
    assert body["target_price"] == 90.0
    assert body["target_met"] is True
    assert body["price_source"] == "baseline"
    assert body["band"] == {"min": 70.0, "expected": 82.0, "max": 95.0}

    # A target below the fresh expected price is not met.
    item2 = client.post(
        "/api/v1/watchlist",
        json={"check_id": check["id"], "target_price": 80.0},
    ).json()
    body2 = client.post(f"/api/v1/watchlist/{item2['id']}/recheck").json()
    assert body2["target_met"] is False
    assert body2["current_expected_price"] == 82.0


async def test_watchlist_recheck_without_baseline(client, db_session):
    # No baseline seeded: analyze falls back to an estimate band and the
    # recheck must return the saved band, never an invented price.
    payload = {
        "description": "handmade oak chair with carved back",
        "category": "other",
        "asking_price": 8000.0,
        "quantity": 1,
        "unit": "unit",
    }
    check = client.post("/api/v1/analyze", json=payload).json()
    assert check["price_source"] == "estimate"
    item = client.post(
        "/api/v1/watchlist",
        json={"check_id": check["id"], "target_price": 7000.0},
    ).json()
    rechecked = client.post(f"/api/v1/watchlist/{item['id']}/recheck")
    assert rechecked.status_code == 200, rechecked.text
    body = rechecked.json()
    assert body["current_expected_price"] is None
    assert body["target_met"] is False
    assert body["price_source"] == "none"
    assert body["band"] == {"min": 6800.0, "expected": 8000.0, "max": 9200.0}
    assert (
        body["note"]
        == "No fresh baseline data — showing the saved check price band only"
    )
    assert client.post("/api/v1/watchlist/missing/recheck").status_code == 404
