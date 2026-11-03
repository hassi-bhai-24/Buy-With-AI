"""Test fixtures: isolated temp SQLite DB, mocked scraper/Ollama.

No network and no Ollama daemon are required: the scraper returns no
live samples and Ollama reports unhealthy by default, so every analyze
call exercises the rule-based engine + baseline/estimate fallback.
Individual tests re-patch as needed.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app import models  # noqa: F401  (register models on Base)
from app.database import get_db
from app.main import app
from app.models.base import Base
from app.routers.analyze import reset_rate_limits
from app.services.ollama_client import OllamaClient
from app.services.scraper import AsyncScraperService


@pytest.fixture(autouse=True)
def _no_geocode(monkeypatch):
    """Analyze calls must not hit Nominatim by default.

    Only the analyzer module's reference is patched, so tests that call
    app.services.integrations.geocode_place directly still exercise the
    real service code (with mocked httpx). Enrichment tests re-patch
    app.services.analyzer.geocode_place as needed.
    """
    from app.services import analyzer as _analyzer

    monkeypatch.setattr(
        _analyzer, "geocode_place", AsyncMock(return_value=None)
    )


@pytest.fixture()
def _engine(tmp_path):
    url = f"sqlite+aiosqlite:///{tmp_path / 'test.db'}"
    engine = create_async_engine(url, connect_args={"check_same_thread": False})

    @event.listens_for(engine.sync_engine, "connect")
    def _pragmas(dbapi_connection, _record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL;")
        cursor.execute("PRAGMA foreign_keys=ON;")
        cursor.execute("PRAGMA busy_timeout=5000;")
        cursor.close()

    async def _create():
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

    asyncio.run(_create())
    yield engine
    asyncio.run(engine.dispose())


@pytest_asyncio.fixture()
async def db_session(_engine):
    session_factory = async_sessionmaker(_engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session


@pytest.fixture()
def client(_engine, monkeypatch):
    session_factory = async_sessionmaker(_engine, expire_on_commit=False)

    async def override_get_db():
        async with session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    reset_rate_limits()
    monkeypatch.setattr(
        AsyncScraperService, "search_market", AsyncMock(return_value=[])
    )
    monkeypatch.setattr(
        OllamaClient, "check_health", AsyncMock(return_value=False)
    )
    monkeypatch.setattr(
        OllamaClient, "generate_verdict", AsyncMock(return_value=None)
    )
    yield TestClient(app)
    app.dependency_overrides.clear()
