"""Response schemas: the 5-tier verdict contract."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

from .common import count_sentences


class VerdictTier(str, Enum):
    GREAT_BUY = "Great Buy"
    GOOD_BUY = "Good Buy"
    THINK_TWICE = "Think Twice"
    RISKY = "Risky"
    AVOID = "Avoid"


class ConfidenceLevel(str, Enum):
    HIGH = "High"
    MEDIUM = "Medium"
    LOW = "Low"


class EvidenceQuality(str, Enum):
    """How strong the price evidence behind a verdict is.

    Separate from the verdict tier and from confidence: a verdict can
    be Avoid on safety grounds with insufficient price evidence, and
    a Good Buy can rest on limited evidence. See the evidence rules
    documented on ``evaluate_tier`` in ``app/services/rules.py``.
    """

    VERIFIED = "verified"
    LIMITED = "limited"
    INSUFFICIENT = "insufficient"


class CategoryEnum(str, Enum):
    """Analysis categories.

    Names follow the rule engine's vocabulary. They map to the spec
    document's labels as: perishable/inventory ~ Produce/Commodity,
    vehicle ~ Vehicle, property ~ Real Estate, retail ~ Retail Product,
    business ~ Business Idea, other ~ Other.
    """

    PERISHABLE = "perishable"
    INVENTORY = "inventory"
    VEHICLE = "vehicle"
    PROPERTY = "property"
    RETAIL = "retail"
    BUSINESS = "business"
    OTHER = "other"


class PriceBand(BaseModel):
    min_price: float
    expected_price: float
    max_price: float
    currency: str
    unit: str
    # Additive (Part 1 hardening): honest provenance for the band.
    # Defaults keep every existing PriceBand construction working.
    source: str = ""
    usable_sample_count: int = 0
    dropped_sample_count: int = 0


class BrandMarkupAudit(BaseModel):
    estimated_making_cost: float
    retail_asking_price: float
    markup_percentage: float
    notes: str


class CashFlowScenario(BaseModel):
    scenario_name: str
    turnover_rate: str
    spoilage_loss_percent: float
    net_profit_loss: float
    rationale: str


class CashFlowTable(BaseModel):
    best_case: CashFlowScenario
    expected_case: CashFlowScenario
    worst_case: CashFlowScenario


class SpoilageSummary(BaseModel):
    initial_quantity: float
    salable_quantity: float
    spoilage_loss_percent: float
    lambda_per_hour: float
    temperature_c: float
    temperature_assumed: bool
    transit_damage_fraction: float
    hours_to_sell: float
    rationale: str
    # Additive (Part 3): concrete assumed values behind the
    # projections, populated only for values the user did not
    # supply. Defaults to [] so rows persisted before Part 3
    # (without this key) still parse via check_to_response.
    assumptions: list[str] = Field(default_factory=list)


class Coordinates(BaseModel):
    """Live-only geocoding result.

    Attached to the live analyze response only; never persisted to the
    checks table (see AnalysisOrchestrator / check_to_response).
    """

    lat: float
    lon: float
    display_name: str


class VerdictResponse(BaseModel):
    id: str
    title: str
    category: CategoryEnum
    location: str
    verdict: VerdictTier
    plain_truth: str = Field(description="Mandatory maximum 2 sentences; exactly 2.")
    confidence: ConfidenceLevel
    price_band: Optional[PriceBand] = None
    brand_markup: Optional[BrandMarkupAudit] = None
    cash_flow: Optional[CashFlowTable] = None
    red_flags: list[str] = Field(default_factory=list)
    verify_checklist: list[str] = Field(default_factory=list)
    counter_offers: dict[str, float] = Field(default_factory=dict)
    sources_cited: list[str] = Field(default_factory=list)
    engine: Literal["rule-based", "ollama"]
    price_source: Literal["live scrape", "baseline", "estimate"]
    # Additive (Part 1 hardening): evidence quality is separate from
    # the verdict tier and from confidence.
    evidence_quality: EvidenceQuality = EvidenceQuality.LIMITED
    evidence_notes: list[str] = Field(default_factory=list)
    missing_evidence: list[str] = Field(default_factory=list)
    spoilage: Optional[SpoilageSummary] = None
    coordinates: Optional[Coordinates] = None
    next_steps: list[str] = Field(default_factory=list)
    created_at: datetime
    is_pinned: bool = False

    @field_validator("plain_truth")
    @classmethod
    def _plain_truth_is_two_sentences(cls, value: str) -> str:
        if count_sentences(value) != 2:
            raise ValueError("plain_truth must contain exactly 2 sentences")
        return value


class ChecksListResponse(BaseModel):
    """The ONLY shape returned by GET /api/v1/checks.

    ``total`` is the filtered total count (separate COUNT query honouring
    the category filter), not the length of the returned page.
    """

    items: list[VerdictResponse]
    total: int = Field(ge=0)


class CheckSummary(BaseModel):
    """Compact history row (same fields as VerdictResponse, via VerdictResponse)."""
