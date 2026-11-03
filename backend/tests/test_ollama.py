"""Ollama reliability (Part 2): mocked-response validation + merge safety.

No live daemon is required: httpx is replaced with a fake client, and
the analyzer tests use fake Ollama subclasses in the style of the
existing _DeadOllama fakes. A live daemon, if present, is covered by
the separate smoke-test record in BUILD-REPORT.md, not here.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import httpx
import pytest

from app.models.check import Check
from app.routers.chat import _ollama_reply
from app.schemas.request import AnalyzeRequest
from app.schemas.response import CategoryEnum
from app.services.analyzer import AnalysisOrchestrator
from app.services.ollama_client import OllamaClient
from app.services.scraper import AsyncScraperService


# ---------------------------------------------------------------------------
# Fake httpx
# ---------------------------------------------------------------------------


class _FakeResponse:
    def __init__(self, status_code, payload):
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload


class _FakeClient:
    """AsyncClient stand-in serving a sequence of post() results.

    Each post() consumes the next result (an exception is raised, a
    _FakeResponse is returned); once the sequence is exhausted the
    last result repeats, so a retrying caller sees the same answer.
    """

    def __init__(self, results, calls):
        # Shared sequence (not copied): each AsyncClient the caller
        # constructs consumes the next result, so a retry sees the
        # following response rather than the first one again.
        self._results = results
        self._calls = calls
        self._last = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url, **kwargs):
        return _FakeResponse(200, {"models": []})

    async def post(self, url, json=None, **kwargs):
        self._calls.append(json)
        if self._results:
            result = self._results.pop(0)
            self._last = result
        else:
            result = self._last
        if isinstance(result, Exception):
            raise result
        return result


def _patch_httpx(monkeypatch, results):
    """Replace httpx.AsyncClient; return the recorded post() calls."""
    calls: list = []

    def _factory(*args, **kwargs):
        return _FakeClient(results, calls)

    monkeypatch.setattr(httpx, "AsyncClient", _factory)
    return calls


def _ok(payload) -> _FakeResponse:
    return _FakeResponse(200, {"response": json.dumps(payload)})


def _valid_payload(**overrides):
    payload = {
        "verdict": "Good Buy",
        "plain_truth": "First sentence here. Second sentence here.",
        "red_flags": ["Check the papers in person."],
        "verify_checklist": ["Item one.", "Item two.", "Item three."],
        "next_steps": ["Step one.", "Step two."],
    }
    payload.update(overrides)
    return payload


async def _generate(monkeypatch, results):
    calls = _patch_httpx(monkeypatch, results)
    client = OllamaClient()
    result = await client.generate_verdict("system", "{}")
    return result, calls


# ---------------------------------------------------------------------------
# generate_verdict: mocked transport + validation
# ---------------------------------------------------------------------------


async def test_ollama_valid_json_is_usable(monkeypatch):
    result, calls = await _generate(monkeypatch, [_ok(_valid_payload())])
    assert result == _valid_payload()
    assert len(calls) == 1


async def test_ollama_invalid_json_returns_none(monkeypatch):
    result, calls = await _generate(
        monkeypatch, [_FakeResponse(200, {"response": "{not json"})]
    )
    assert result is None
    # A JSON parse failure ends the call; it is not retried forever.
    assert len(calls) == 1


async def test_ollama_non_dict_json_returns_none(monkeypatch):
    result, calls = await _generate(
        monkeypatch, [_FakeResponse(200, {"response": "[1, 2, 3]"})]
    )
    assert result is None
    # A schema-shape failure retries once at temperature 0, then stops.
    assert len(calls) == 2


async def test_ollama_wrong_verdict_returns_none(monkeypatch):
    result, calls = await _generate(
        monkeypatch, [_ok(_valid_payload(verdict="Great Deal"))]
    )
    assert result is None
    assert len(calls) == 2


async def test_ollama_wrong_case_verdict_returns_none(monkeypatch):
    # Tier values are case-sensitive: "good buy" is not "Good Buy".
    result, _calls = await _generate(
        monkeypatch, [_ok(_valid_payload(verdict="good buy"))]
    )
    assert result is None


async def test_ollama_one_sentence_plain_truth_returns_none(monkeypatch):
    result, calls = await _generate(
        monkeypatch,
        [_ok(_valid_payload(plain_truth="Only one sentence here."))],
    )
    assert result is None
    assert len(calls) == 2


async def test_ollama_red_flags_wrong_type_returns_none(monkeypatch):
    result, _calls = await _generate(
        monkeypatch, [_ok(_valid_payload(red_flags="Check the papers."))]
    )
    assert result is None


async def test_ollama_red_flags_non_string_item_returns_none(monkeypatch):
    result, _calls = await _generate(
        monkeypatch, [_ok(_valid_payload(red_flags=["Fine.", 42]))]
    )
    assert result is None


async def test_ollama_checklist_wrong_type_returns_none(monkeypatch):
    result, _calls = await _generate(
        monkeypatch, [_ok(_valid_payload(verify_checklist={"a": 1}))]
    )
    assert result is None


async def test_ollama_timeout_returns_none_without_retry(monkeypatch):
    result, calls = await _generate(
        monkeypatch, [httpx.TimeoutException("timed out")]
    )
    assert result is None
    assert len(calls) == 1


async def test_ollama_unreachable_returns_none_without_retry(monkeypatch):
    result, calls = await _generate(
        monkeypatch, [httpx.ConnectError("connection refused")]
    )
    assert result is None
    assert len(calls) == 1


async def test_ollama_non_200_returns_none(monkeypatch):
    result, calls = await _generate(
        monkeypatch, [_FakeResponse(500, {"error": "boom"})]
    )
    assert result is None
    assert len(calls) == 1


async def test_ollama_schema_failure_retries_once_then_succeeds(monkeypatch):
    result, calls = await _generate(
        monkeypatch,
        [
            _ok(_valid_payload(plain_truth="Only one sentence here.")),
            _ok(_valid_payload()),
        ],
    )
    assert result == _valid_payload()
    assert len(calls) == 2


# ---------------------------------------------------------------------------
# _is_usable: direct validation cases
# ---------------------------------------------------------------------------


def test_is_usable_rejects_empty_and_whitespace_plain_truth():
    assert OllamaClient._is_usable(_valid_payload(plain_truth="")) is False
    assert OllamaClient._is_usable(_valid_payload(plain_truth="   ")) is False


def test_is_usable_rejects_missing_verdict_and_extra_typed_fields():
    payload = _valid_payload()
    del payload["verdict"]
    assert OllamaClient._is_usable(payload) is False
    assert (
        OllamaClient._is_usable(_valid_payload(next_steps=None)) is False
    )
    assert (
        OllamaClient._is_usable(_valid_payload(red_flags=None)) is False
    )


def test_is_usable_accepts_payload_without_optional_lists():
    payload = {
        "verdict": "Risky",
        "plain_truth": "First sentence here. Second sentence here.",
    }
    assert OllamaClient._is_usable(payload) is True


# ---------------------------------------------------------------------------
# Analyzer merge: the model can never soften a tier or move numbers
# ---------------------------------------------------------------------------


class _RaisingScraper(AsyncScraperService):
    async def search_market(self, query, location, max_results=5):  # noqa: ANN001, ANN201
        raise RuntimeError("simulated scraper failure")


class _DeadOllama(OllamaClient):
    async def check_health(self) -> bool:
        return False

    async def generate_verdict(self, system_prompt, user_payload):  # noqa: ANN001, ANN201
        return None


class _FixedOllama(OllamaClient):
    def __init__(self, payload):
        super().__init__()
        self._payload = payload

    async def check_health(self) -> bool:
        return True

    async def generate_verdict(self, system_prompt, user_payload):  # noqa: ANN001, ANN201
        return self._payload


def _installment_request(**overrides):
    data = {
        "description": "Installment purchase of a used motorcycle",
        "category": CategoryEnum.OTHER,
        "asking_price": 165_000.0,
        "quantity": 1,
        "unit": "unit",
        "down_payment": 20_000.0,
        "monthly_installment": 18_500.0,
        "installment_months": 12,
        "private_mode": True,
    }
    data.update(overrides)
    return AnalyzeRequest(**data)


async def test_ollama_cannot_soften_risky_tier(db_session):
    # Rule tier is Risky: 46.67% installment markup exceeds the 35%
    # threshold. The model answers "Good Buy".
    model = _valid_payload(
        verdict="Good Buy",
        plain_truth="Model wording here. Second model sentence.",
    )
    response = await AnalysisOrchestrator(
        db_session, scraper=_RaisingScraper(), ollama=_FixedOllama(model)
    ).analyze(_installment_request())
    assert response.engine == "ollama"
    assert response.verdict.value == "Risky"
    assert response.plain_truth == model["plain_truth"]
    assert any("markup" in flag.lower() for flag in response.red_flags)


async def test_ollama_cannot_soften_avoid_tier(db_session):
    model = _valid_payload(
        verdict="Good Buy",
        plain_truth="Model wording here. Second model sentence.",
    )
    response = await AnalysisOrchestrator(
        db_session, scraper=_RaisingScraper(), ollama=_FixedOllama(model)
    ).analyze(
        _installment_request(
            description="Used car, advance payment required before viewing"
        )
    )
    assert response.engine == "ollama"
    assert response.verdict.value == "Avoid"


async def test_ollama_numbers_cannot_override_rule_numbers(db_session):
    # The model payload carries invented band / cash-flow / offer
    # numbers. The response must carry the rule-computed numbers,
    # identical to a rule-only run of the same request.
    request = _installment_request()
    rule_only = await AnalysisOrchestrator(
        db_session, scraper=_RaisingScraper(), ollama=_DeadOllama()
    ).analyze(request)
    tampering = _valid_payload(
        verdict="Risky",
        plain_truth="Model wording here. Second model sentence.",
        price_band={"min_price": 1.0, "expected_price": 2.0, "max_price": 3.0},
        cash_flow={"best_case": {"net_profit_loss": 999_999.0}},
        counter_offers={"opening": 1.0, "target": 2.0, "walk_away": 3.0},
        expected_price=2.0,
    )
    response = await AnalysisOrchestrator(
        db_session, scraper=_RaisingScraper(), ollama=_FixedOllama(tampering)
    ).analyze(request)
    assert response.engine == "ollama"
    assert response.plain_truth == tampering["plain_truth"]
    assert response.price_band is not None
    assert rule_only.price_band is not None
    assert response.price_band.min_price == pytest.approx(
        rule_only.price_band.min_price
    )
    assert response.price_band.expected_price == pytest.approx(
        rule_only.price_band.expected_price
    )
    assert response.price_band.max_price == pytest.approx(
        rule_only.price_band.max_price
    )
    assert response.counter_offers == rule_only.counter_offers
    assert response.cash_flow == rule_only.cash_flow


# ---------------------------------------------------------------------------
# Chat: model text never overrides the stored check's numbers
# ---------------------------------------------------------------------------


async def test_chat_ollama_reply_grounds_in_stored_numbers(monkeypatch):
    check = Check(
        user_id="user-1",
        query_raw="installment purchase",
        item_title="Test item",
        category="other",
        verdict_tier="Risky",
        plain_truth="Saved truth. Saved second sentence.",
        confidence_score="Low",
        price_min=140_250.0,
        price_expected=165_000.0,
        price_max=189_750.0,
        currency="PKR",
        unit_of_measure="unit",
        asking_price=165_000.0,
        quantity=1.0,
        red_flags_json=["Saved flag."],
        price_source="estimate",
    )
    tampering = _valid_payload(
        verdict="Good Buy",
        plain_truth="Model wording here. Second model sentence.",
        price_band={"min_price": 1.0, "expected_price": 2.0, "max_price": 3.0},
        counter_offers={"opening": 999_999.0, "target": 999_999.0},
    )
    monkeypatch.setattr(
        OllamaClient, "check_health", AsyncMock(return_value=True)
    )
    monkeypatch.setattr(
        OllamaClient, "generate_verdict", AsyncMock(return_value=tampering)
    )
    result = await _ollama_reply("tell me more", check)
    assert result is not None
    text, engine = result
    assert engine == "ollama"
    assert "165,000 PKR" in text
    assert "999,999" not in text
    assert "Saved flag." in text
