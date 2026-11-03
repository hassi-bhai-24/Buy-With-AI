"""Scraper fallback: a raising scraper must fall back to the baseline,
and with no baseline at all the estimate band must be labelled honestly."""

from unittest.mock import AsyncMock

import pytest

from app.schemas.request import AnalyzeRequest
from app.schemas.response import CategoryEnum
from app.services.analyzer import AnalysisOrchestrator
from app.services.ollama_client import OllamaClient
from app.services.scraper import AsyncScraperService
from tests.helpers import add_baseline


class _RaisingScraper(AsyncScraperService):
    async def search_market(self, query, location, max_results=5):  # noqa: ANN001, ANN201
        raise RuntimeError("simulated scraper failure")


class _DeadOllama(OllamaClient):
    async def check_health(self) -> bool:
        return False

    async def generate_verdict(self, system_prompt, user_payload):  # noqa: ANN001, ANN201
        return None


async def test_baseline_fallback_when_scraper_raises(db_session):
    await add_baseline(db_session, "tomato")
    request = AnalyzeRequest(
        description="30 kg tomatoes wholesale",
        category=CategoryEnum.PERISHABLE,
        asking_price=2400.0,
        quantity=30.0,
        unit="kg",
        days_to_sell=7,
    )
    orchestrator = AnalysisOrchestrator(
        db_session, scraper=_RaisingScraper(), ollama=_DeadOllama()
    )
    response = await orchestrator.analyze(request)
    assert response.price_source == "baseline"
    assert response.engine == "rule-based"
    assert response.price_band is not None
    assert response.price_band.expected_price == pytest.approx(82.0)
    # 7 days at 32C: the documented decay curve leaves almost nothing
    # salable, so the <5% margin rule downgrades the verdict to Think Twice.
    assert response.verdict.value == "Think Twice"
    assert any("below 5%" in flag for flag in response.red_flags)


async def test_estimate_fallback_when_no_baseline(db_session):
    request = AnalyzeRequest(
        description="handmade wooden chair, unique item",
        category=CategoryEnum.RETAIL,
        asking_price=5000.0,
        quantity=1,
    )
    orchestrator = AnalysisOrchestrator(
        db_session, scraper=_RaisingScraper(), ollama=_DeadOllama()
    )
    response = await orchestrator.analyze(request)
    assert response.price_source == "estimate"
    assert response.confidence.value == "Low"
    assert response.price_band is not None
    assert response.price_band.min_price == pytest.approx(4250.0)
    assert response.price_band.max_price == pytest.approx(5750.0)


async def test_live_scrape_samples_used_when_enough(db_session, monkeypatch):
    samples = [
        {"title": "Tomatoes 78 PKR", "url": "http://example.test/1",
         "snippet": "78 PKR per kg", "prices": [78.0], "source": "duckduckgo html"},
        {"title": "Tomatoes 84 PKR", "url": "http://example.test/2",
         "snippet": "84 PKR per kg", "prices": [84.0], "source": "duckduckgo html"},
        {"title": "Tomatoes 90 PKR", "url": "http://example.test/3",
         "snippet": "90 PKR per kg", "prices": [90.0], "source": "duckduckgo html"},
    ]
    monkeypatch.setattr(
        AsyncScraperService, "search_market", AsyncMock(return_value=samples)
    )
    request = AnalyzeRequest(
        description="tomatoes wholesale",
        category=CategoryEnum.PERISHABLE,
        asking_price=2400.0,
        quantity=30.0,
        unit="kg",
    )
    response = await AnalysisOrchestrator(
        db_session, ollama=_DeadOllama()
    ).analyze(request)
    assert response.price_source == "live scrape"
    # Part 1 hardening: 3 usable samples from a single host (all three
    # fixtures share host example.test) is "limited" evidence, so High
    # is capped to Medium. Verified requires >=5 usable from >=2 sources.
    assert response.confidence.value == "Medium"
    assert response.evidence_quality.value == "limited"
    assert response.price_band is not None
    assert response.price_band.min_price == pytest.approx(78.0)
    assert response.price_band.expected_price == pytest.approx(84.0)
    assert response.price_band.usable_sample_count == 3
    assert "3 usable" in response.price_band.source
    assert "1 source" in response.price_band.source
    assert any(
        "3 usable price sample(s)" in line and "1 distinct source(s)" in line
        for line in response.sources_cited
    )


def test_scraper_parses_prices_from_html():
    html = """
    <html><body>
      <div class="result">
        <a class="result__a" href="http://example.test/a">Tomatoes Rs 82 per kg</a>
        <a class="result__snippet">Fresh tomatoes 82 PKR/kg in Bahawalpur mandi</a>
      </div>
      <div class="result">
        <a class="result__a" href="http://example.test/b">No price here</a>
        <a class="result__snippet">Just a description</a>
      </div>
    </body></html>
    """
    results = AsyncScraperService._parse_results(html, 5)
    assert len(results) == 2
    assert results[0]["prices"] == [82.0, 82.0]
    assert results[1]["prices"] == []
