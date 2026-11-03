"""Share / summary-download API tests.

Approach: fresh FastAPI app mounting the analyze, checks and share
routers (share is NOT registered in ``app/main.py`` — the coordinator
wires it), with the same ``get_db`` override and mocks as conftest.
The ``client`` fixture name intentionally shadows conftest's.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker

from app.database import get_db
from app.routers import analyze, checks, share
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
    app.include_router(checks.router, prefix="/api/v1")
    app.include_router(share.router, prefix="/api/v1")
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


async def test_share_payload(client, db_session):
    check = await _make_check(client, db_session)
    response = client.get(f"/api/v1/checks/{check['id']}/share")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["url"] == f"/check/{check['id']}"
    assert "http" not in body["url"]
    text = body["text"]
    assert check["title"] in text
    assert check["verdict"] in text
    assert check["plain_truth"] in text
    assert "82" in text  # expected band price
    assert check["red_flags"][0] in text
    assert "General guidance, not financial advice. Verify before paying." in text
    assert client.get("/api/v1/checks/missing/share").status_code == 404


async def test_summary_download_txt(client, db_session):
    check = await _make_check(client, db_session)
    response = client.get(f"/api/v1/checks/{check['id']}/summary", params={"format": "txt"})
    assert response.status_code == 200, response.text
    assert response.headers["content-disposition"] == (
        f'attachment; filename="check-{check["id"]}.txt"'
    )
    assert check["title"] in response.text
    assert check["verdict"] in response.text
    assert "General guidance, not financial advice. Verify before paying." in response.text


async def test_summary_download_md_and_bad_format(client, db_session):
    check = await _make_check(client, db_session)
    response = client.get(f"/api/v1/checks/{check['id']}/summary", params={"format": "md"})
    assert response.status_code == 200, response.text
    assert response.headers["content-disposition"] == (
        f'attachment; filename="check-{check["id"]}.md"'
    )
    assert f"# {check['title']}" in response.text
    assert "**Verdict:**" in response.text
    assert "General guidance, not financial advice. Verify before paying." in response.text

    assert (
        client.get(
            f"/api/v1/checks/{check['id']}/summary", params={"format": "pdf"}
        ).status_code
        == 422
    )
    assert (
        client.get("/api/v1/checks/missing/summary", params={"format": "txt"}).status_code
        == 404
    )
