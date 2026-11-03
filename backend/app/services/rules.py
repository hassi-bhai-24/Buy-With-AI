"""Deterministic rule engine: land conversion, APR, spoilage, tiers.

Formulas follow Documents/13_MARKET_INTELLIGENCE_HEURISTICS.md and the
edge-case handbook (12), with two documented deviations required by the
build task:

* ``lahore_272`` uses a marla factor of exactly 272.0 sq ft so that
  5 marla converts to 1360.0 sq ft (test plan). The revenue standard
  272.25 sq ft is available as standard ``"272.25"`` / ``"revenue"``.
* The constant-ratio APR formula is implemented exactly as documented.
  For cash 165000 / down 20000 / 18500 x 12 it yields ~98%, not the
  ~42% quoted in the test plan; the formula, not the quoted figure, is
  authoritative (see the APR function docstring). Part 2 adds a
  cash-flow IRR effective annual rate alongside it as
  ``effective_annual_rate_percent``; ``apr_percent`` keeps its legacy
  constant-ratio meaning (see NOTES.md "APR resolution").
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from datetime import datetime

from ..schemas.response import (
    CategoryEnum,
    ConfidenceLevel,
    EvidenceQuality,
    VerdictTier,
)
from .guards import detect_injection

# ---------------------------------------------------------------------------
# Land conversion
# ---------------------------------------------------------------------------

_MARLA_FACTORS = {
    "225": 225.0,
    "punjab_225": 225.0,
    "urban": 225.0,
    "urban_scheme": 225.0,
    "272": 272.0,
    "lahore_272": 272.0,
    "punjab_272": 272.0,
    "272.25": 272.25,
    "revenue": 272.25,
}

_SQFT_PER_UNIT = {
    "sqft": 1.0,
    "sq_ft": 1.0,
    "sqf": 1.0,
    "sqyd": 9.0,
    "sq_yd": 9.0,
    "acre": 43560.0,
    "hectare": 107639.1,
    "sqm": 10.7639,
    "sq_m": 10.7639,
}


def marla_factor(standard: str) -> float:
    return _MARLA_FACTORS[standard.strip().lower()]


def convert_marla_to_sqft(marlas: float, standard: str = "punjab_225") -> float:
    return marlas * marla_factor(standard)


def convert_kanal_to_marla(kanals: float) -> float:
    return kanals * 20.0


def convert_acre_to_kanal(acres: float) -> float:
    return acres * 8.0


def convert_land(
    value: float, from_unit: str, to_unit: str, standard: str = "225"
) -> float:
    """Convert between marla, kanal, sqft, sqyd, acre, hectare and sqm."""

    def to_sqft(amount: float, unit: str) -> float:
        unit = unit.strip().lower()
        if unit in ("marla", "marlas"):
            return amount * marla_factor(standard)
        if unit in ("kanal", "kanals"):
            return amount * 20.0 * marla_factor(standard)
        if unit in _SQFT_PER_UNIT:
            return amount * _SQFT_PER_UNIT[unit]
        raise ValueError(f"unknown land unit: {unit}")

    def from_sqft(sqft: float, unit: str) -> float:
        unit = unit.strip().lower()
        if unit in ("marla", "marlas"):
            return sqft / marla_factor(standard)
        if unit in ("kanal", "kanals"):
            return sqft / (20.0 * marla_factor(standard))
        if unit in _SQFT_PER_UNIT:
            return sqft / _SQFT_PER_UNIT[unit]
        raise ValueError(f"unknown land unit: {unit}")

    return from_sqft(to_sqft(value, from_unit), to_unit)


# ---------------------------------------------------------------------------
# Installment APR (constant-ratio formula, heuristics 2.4)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class InstallmentAudit:
    cash_price: float
    down_payment: float
    monthly_installment: float
    months: int
    total_paid: float
    finance_charge: float
    markup_percent: float
    # Legacy constant-ratio approximation (see audit_installment_plan).
    # Kept with its existing meaning; do not reinterpret it as an IRR.
    apr_percent: float
    # Primary rate (Part 2): cash-flow IRR expressed as an effective
    # annual rate. See _solve_monthly_irr / audit_installment_plan.
    effective_annual_rate_percent: float
    # How effective_annual_rate_percent was produced, e.g.
    # "cash-flow IRR (effective annual rate)" or the fallback label
    # when the IRR did not converge (then the effective figure falls
    # back to the legacy constant-ratio value).
    apr_method: str


def _solve_monthly_irr(
    principal: float, monthly_installment: float, months: int
) -> float | None:
    """Monthly IRR for end-of-month installments, by bisection.

    Sign convention, from the buyer's perspective: at t=0 the buyer
    receives goods worth ``cash_price`` and pays ``down_payment``, so
    the financed principal is ``principal = cash_price - down_payment``.
    The installments at t=1..n must satisfy
    NPV(r) = principal - sum(monthly_installment / (1+r)**t) = 0.
    No fees are involved: fees are not an input anywhere in this
    calculation. Returns the monthly rate, or None if no bracketing
    rate is found (bracket [0, 1.0] expanded by doubling) or the
    bisection residual is not ~0 after 200 iterations; the caller
    then falls back to the constant-ratio figure and labels it.
    """
    if principal <= 0 or monthly_installment <= 0 or months <= 0:
        return None

    def npv(rate: float) -> float:
        return principal - sum(
            monthly_installment / (1.0 + rate) ** t
            for t in range(1, months + 1)
        )

    low, high = 0.0, 1.0
    while npv(high) < 0.0:
        high *= 2.0
        if high > 1024.0:
            return None
    for _ in range(200):
        mid = (low + high) / 2.0
        if npv(mid) < 0.0:
            low = mid
        else:
            high = mid
    rate = (low + high) / 2.0
    if abs(npv(rate)) > max(1.0, principal * 1e-6):
        return None
    return rate


def _effective_annual_rate(
    *,
    principal: float,
    monthly_installment: float,
    months: int,
    finance_charge: float,
    legacy_apr_percent: float,
) -> tuple[float, str]:
    """Cash-flow IRR as an effective annual rate, with edge cases.

    Returns (rate_percent, method). Edge cases return 0.0 with the
    reason carried in the method string; they never raise and never
    invent a rate. A non-converging IRR falls back to the legacy
    constant-ratio figure, labelled as such.
    """
    if principal <= 0:
        return 0.0, (
            "cash-flow IRR (effective annual rate) — down payment "
            "covers the cash price, rate 0"
        )
    if monthly_installment == 0 or months <= 0:
        return 0.0, (
            "cash-flow IRR (effective annual rate) — no installments, "
            "rate 0"
        )
    if finance_charge <= 0:
        return 0.0, (
            "cash-flow IRR (effective annual rate) — no finance charge, "
            "rate 0"
        )
    rate = _solve_monthly_irr(principal, monthly_installment, months)
    if rate is None:
        return (
            legacy_apr_percent,
            "constant-ratio approximation (IRR did not converge)",
        )
    return ((1.0 + rate) ** 12 - 1.0) * 100.0, (
        "cash-flow IRR (effective annual rate)"
    )


def audit_installment_plan(
    cash_price: float,
    down_payment: float,
    monthly_installment: float,
    months: int,
) -> InstallmentAudit:
    """Constant-ratio APR: APR = 2*m*I / (P*(n+1)), m=12, I=total-cash,
    P=cash-down. Markup % = I / cash_price * 100.

    Note: for the test-plan example (165000/20000/18500x12) this gives
    I=77000, markup 46.67% and APR ~98.0%. The test plan's "~42%" does
    not follow from its own formula for these inputs; the formula is
    implemented as written.

    ``apr_percent`` keeps that legacy constant-ratio meaning (it is an
    approximation, not an IRR, and is neither a nominal APR compounded
    monthly nor an effective annual rate; see NOTES.md "APR
    resolution"). The primary rate is
    ``effective_annual_rate_percent``: the cash-flow IRR (down payment
    at t=0, n equal end-of-month installments, no fees — fees are not
    an input) expressed as an effective annual rate. The
    installment-markup rule uses ``markup_percent`` only, never
    either rate.
    """
    if cash_price <= 0:
        raise ValueError("cash_price must be > 0")
    total_paid = down_payment + months * monthly_installment
    finance_charge = total_paid - cash_price
    principal = cash_price - down_payment
    if principal <= 0:
        apr = 0.0
    else:
        apr = (2 * 12 * finance_charge) / (principal * (months + 1)) * 100.0
    markup = finance_charge / cash_price * 100.0
    effective_rate, apr_method = _effective_annual_rate(
        principal=principal,
        monthly_installment=monthly_installment,
        months=months,
        finance_charge=finance_charge,
        legacy_apr_percent=apr,
    )
    return InstallmentAudit(
        cash_price=cash_price,
        down_payment=down_payment,
        monthly_installment=monthly_installment,
        months=months,
        total_paid=total_paid,
        finance_charge=finance_charge,
        markup_percent=markup,
        apr_percent=apr,
        effective_annual_rate_percent=effective_rate,
        apr_method=apr_method,
    )


# ---------------------------------------------------------------------------
# Spoilage decay (heuristics 2.1)
# ---------------------------------------------------------------------------


def lambda_for_temperature(temp_c: float) -> float:
    if temp_c <= 22:
        return 0.008
    if temp_c <= 32:
        return 0.025
    return 0.055


def salable_quantity(
    initial_qty: float, hours: float, temp_c: float, transit_damage: float
) -> float:
    """Q_salable = Q0 * exp(-lambda*t) * (1 - delta).

    Transit damage is clamped to [0, 0.9] and hours floored at 0 so
    a direct caller cannot produce a negative or above-initial
    salable quantity (see also the clamp in build_cash_flow).
    """
    lam = lambda_for_temperature(temp_c)
    delta = min(0.9, max(0.0, float(transit_damage)))
    return initial_qty * math.exp(-lam * max(0.0, float(hours))) * (1.0 - delta)


# ---------------------------------------------------------------------------
# Text scanning helpers
# ---------------------------------------------------------------------------

_SCAM_ADVANCE_PATTERNS = [
    r"advance\s+(payment|token|money)",
    r"token\s+(money|payment|advance)",
    r"deposit\s+before\s+viewing",
    r"send\s+money\s+now",
    r"transfer\s+(money|token|payment)\s+(before|now|first)",
    r"pay\s+(in\s+)?advance",
    r"token\s+.*\b(before|first)\b",
]
_SCAM_PRESSURE_KEYWORDS = [
    "5 buyers",
    "five buyers",
    "other buyers waiting",
    "buyers waiting",
    "send money now",
    "urgent",
    "no inspection",
    "army officer",
    "out of country",
    "out of the country",
    "deposit before viewing",
    "advance payment",
]
_ILLEGAL_KEYWORDS = [
    "unregistered firearm",
    "firearm",
    "narcotics",
    "heroin",
    "cocaine",
    "counterfeit currency",
    "fake currency",
    "smuggled",
]
_STRUCTURAL_KEYWORDS = [
    "repainted roof",
    "roof repaint",
    "repainted pillar",
    "pillar damage",
    "structural damage",
    "chassis damage",
    "chassis bent",
    "rollover",
    "roof damage",
    "foundation crack",
]
_DEFECT_KEYWORDS = [
    "engine fault",
    "engine problem",
    "gearbox fault",
    "head gasket",
    "milky oil",
    "major defect",
    "flood damage",
    "accident",
    "accidental",
    "repainted",
    "non genuine",
    "non-genuine",
    "seized engine",
    "blown engine",
]
_TITLE_KEYWORDS = [
    "noc", "deed", "fard", "registry", "patwari",
    "aks-shajra", "aks shajra", "title deed", "ownership papers",
    "mutation", "intiqal",
]

_NEGATED_ACCIDENT = re.compile(
    r"(non[\s-]?accidental|no\s+accident|accident[\s-]?free|never\s+had\s+an\s+accident)"
)


def _contains(text: str, phrases: list[str]) -> list[str]:
    return [p for p in phrases if p in text]


def scan_text(text: str) -> dict:
    """Scan combined description + seller notes for fraud/defect signals."""
    lowered = text.lower()
    cleaned = _NEGATED_ACCIDENT.sub(" ", lowered)
    advance = any(re.search(p, lowered) for p in _SCAM_ADVANCE_PATTERNS)
    pressure = _contains(lowered, _SCAM_PRESSURE_KEYWORDS)
    illegal = _contains(lowered, _ILLEGAL_KEYWORDS)
    structural = _contains(cleaned, _STRUCTURAL_KEYWORDS)
    defects = _contains(cleaned, _DEFECT_KEYWORDS)
    # "repainted" inside a structural phrase is structural, not a plain defect.
    defects = [d for d in defects if d not in structural]
    title_docs = _contains(lowered, _TITLE_KEYWORDS)
    return {
        "advance_token": advance,
        "pressure": pressure,
        "illegal": illegal,
        "structural": structural,
        "defects": defects,
        "title_docs": title_docs,
        "injection": detect_injection(text),
    }


def parse_year(text: str) -> int | None:
    match = re.search(r"\b(19|20)\d{2}\b", text or "")
    if not match:
        return None
    year = int(match.group(0))
    current = datetime.now().year
    if 1980 <= year <= current + 1:
        return year
    return None


def parse_kilometres(text: str) -> float | None:
    """Find a number stated near km / mileage / odometer wording."""
    lowered = (text or "").lower()
    match = re.search(r"(\d[\d,]*\.?\d*)\s*(km|kilometres?|kilometers?)", lowered)
    if match:
        return float(match.group(1).replace(",", ""))
    match = re.search(
        r"(mileage|odometer|driven|run)\D{0,20}(\d[\d,]*\.?\d*)", lowered
    )
    if match:
        return float(match.group(2).replace(",", ""))
    return None


def parse_marla_area(text: str) -> float | None:
    match = re.search(r"(\d+(?:\.\d+)?)\s*marla", (text or "").lower())
    return float(match.group(1)) if match else None


# ---------------------------------------------------------------------------
# Counter-offers (heuristics 2.5)
# ---------------------------------------------------------------------------


def counter_offers(asking_total: float, target_total: float) -> dict[str, float]:
    """Opening = target - 0.5*(asking-target) when asking>target, else
    target*0.9. Walk-away = target*1.05."""
    if asking_total > target_total:
        opening = target_total - 0.5 * (asking_total - target_total)
        # Never anchor at (or near) zero: an opening offer below half the
        # fair target is not a credible negotiation anchor.
        opening = max(opening, 0.5 * target_total)
    else:
        opening = target_total * 0.9
    return {
        "opening": round(max(opening, 0.0), 2),
        "target": round(target_total, 2),
        "walk_away": round(target_total * 1.05, 2),
    }


# ---------------------------------------------------------------------------
# Checklists / next steps
# ---------------------------------------------------------------------------

_CHECKLISTS: dict[str, list[str]] = {
    "perishable": [
        "Overturn at least 2 random crates and inspect the bottom layers for rot before paying.",
        "Confirm the morning auction average for this mandi today before accepting the price.",
        "Check that at least 60% of the lot is firm and semi-green, not soft or overripe.",
        "Ask how long the lot sat in the sun and whether it was kept in shade or cold storage.",
    ],
    "inventory": [
        "Inspect a random sample batch, not only the top layer or display sample.",
        "Check expiry dates and batch numbers on a sample from the middle of the stock.",
        "Confirm storage conditions (heat, damp, sunlight) where the stock was kept.",
        "Verify the supplier invoice and return policy for unsold or damaged stock.",
    ],
    "vehicle": [
        "Check the oil cap and dipstick for milky foam (head-gasket failure sign).",
        "Match the chassis number on the car with the excise registration record.",
        "Test the AC at noon in full sun and check for weak cooling or rattles.",
        "Use a paint thickness gauge on the roof pillars, door aprons and strut towers.",
        "Confirm token tax is paid up to date and there are no pending challans.",
    ],
    "property": [
        "Verify the Fard and Aks-Shajra at the Patwari / land revenue office match the seller's papers.",
        "Confirm the development authority NOC and approved layout for this scheme.",
        "Check road access, utilities and that the plot boundaries match the site plan on the ground.",
        "Confirm the registry / mutation (Intiqal) chain and that no dispute is recorded.",
    ],
    "retail": [
        "Weigh the item and compare with the official manufacturer specification.",
        "Check the receipt, warranty card and serial number against the brand's records.",
        "Inspect seals, packaging and build quality for counterfeit signs.",
        "Compare the same model at two other sellers before paying.",
    ],
    "business": [
        "Verify the claimed revenue or yield with a second independent source.",
        "List the fixed monthly costs and check the break-even point in writing.",
        "Talk to one existing operator in the same trade before committing capital.",
        "Start with the smallest viable test batch before scaling up.",
    ],
    "other": [
        "Verify the seller's identity and get a written receipt before paying.",
        "Inspect the item in person and test every claimed function.",
        "Compare the price with at least two other sellers in the same city.",
        "Do not pay any advance before inspection and written terms.",
    ],
}


def checklist_for(category: CategoryEnum, scan: dict) -> list[str]:
    items = list(_CHECKLISTS.get(category.value, _CHECKLISTS["other"]))
    if category == CategoryEnum.PROPERTY and not scan["title_docs"]:
        items = [
            "Ask the seller for the NOC, Fard and registry papers before any payment.",
            *items[1:],
        ]
    return items[:5]


def next_steps_for(
    tier: VerdictTier,
    offers: dict[str, float],
    currency: str,
    category: CategoryEnum,
    scan: dict,
) -> list[str]:
    def money(value: float) -> str:
        return f"{value:,.0f} {currency}"

    steps: list[str] = []
    if tier == VerdictTier.AVOID:
        steps.append("Do not pay anything and do not share bank or ID details with this seller.")
        if scan["advance_token"]:
            steps.append("Never transfer token or advance money before in-person verification at the land revenue or excise office.")
        steps.append("Walk away and report the listing if it pressures you to pay before inspection.")
        return steps[:4]
    if tier in (VerdictTier.RISKY, VerdictTier.THINK_TWICE):
        steps.append(f"Complete every item on the verification checklist before paying anything.")
        steps.append(f"Offer {money(offers['opening'])} first and do not go above {money(offers['walk_away'])}.")
        steps.append("Get the key facts (papers, condition, price) confirmed in writing from the seller.")
        return steps[:4]
    steps.append(f"Offer {money(offers['opening'])} and aim to settle near {money(offers['target'])}.")
    steps.append("Complete the verification checklist in person before handing over money.")
    if category in (CategoryEnum.PERISHABLE, CategoryEnum.INVENTORY):
        steps.append("Sell the fastest-moving portion first and re-check spoilage daily.")
    else:
        steps.append("Get a written receipt showing the final price and any warranty promised.")
    return steps[:4]


# ---------------------------------------------------------------------------
# Tier evaluation
# ---------------------------------------------------------------------------

_SEVERITY = {
    VerdictTier.GREAT_BUY: 0,
    VerdictTier.GOOD_BUY: 1,
    VerdictTier.THINK_TWICE: 2,
    VerdictTier.RISKY: 3,
    VerdictTier.AVOID: 4,
}


def _worst(*tiers: VerdictTier) -> VerdictTier:
    return max(tiers, key=lambda t: _SEVERITY[t])


@dataclass
class RuleOutcome:
    tier: VerdictTier
    confidence: ConfidenceLevel
    red_flags: list[str] = field(default_factory=list)
    rationale_parts: list[str] = field(default_factory=list)
    evidence_quality: EvidenceQuality = EvidenceQuality.LIMITED
    evidence_notes: list[str] = field(default_factory=list)
    missing_evidence: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Evidence quality (Part 1 hardening).
#
# Evidence quality is separate from the verdict tier and from
# confidence. Rules:
# * "verified" iff price_source is "live scrape" AND usable>=5 AND
#   source_count>=2.
# * "limited" iff a live scrape with 3-4 usable samples or 1 source,
#   or a fresh baseline.
# * "insufficient" iff price_source is "estimate", or the baseline is
#   stale (>90 days), or a live attempt that fell back to a baseline /
#   estimate had <3 usable samples.
# Confidence: insufficient forces Low; limited caps High -> Medium
# (only when sample detail was supplied); stale forces Low; otherwise
# the existing price-source mapping (live=High, baseline=Medium,
# estimate=Low) is kept.
# Legacy exception: when NO sample detail is supplied at all
# (usable=dropped=source_count=0, e.g. a direct rule call or the chat
# what-if recompute), the legacy price-source confidence is kept and
# evidence is reported as limited with a note, rather than inventing
# sample counts. The caps above apply when the analyzer supplies
# real sample detail.
# Estimate / stale cap: a band derived ONLY from the asking price
# (or a stale baseline) can never independently justify Great Buy;
# such a Great Buy is capped to Good Buy with a note. Safety
# early-return Avoids are unaffected, and the injection floor still
# applies after the cap (Risky wins).
# ---------------------------------------------------------------------------


def _assess_evidence(
    *,
    price_source: str,
    usable_sample_count: int,
    dropped_sample_count: int,
    source_count: int,
    stale_baseline: bool,
) -> tuple[EvidenceQuality, list[str], bool]:
    usable = usable_sample_count
    dropped = dropped_sample_count
    has_detail = usable > 0 or dropped > 0 or source_count > 0
    notes: list[str] = []
    if price_source == "estimate":
        quality = EvidenceQuality.INSUFFICIENT
        notes.append(
            "Price evidence insufficient: the price band is derived only "
            "from the asking price, not from market data."
        )
    elif stale_baseline:
        quality = EvidenceQuality.INSUFFICIENT
        notes.append(
            "Price evidence insufficient: the baseline used is stale "
            "(older than 90 days)."
        )
    elif price_source == "live scrape":
        if usable >= 5 and source_count >= 2:
            quality = EvidenceQuality.VERIFIED
            notes.append(
                f"Price evidence verified: live scrape with {usable} usable "
                f"sample(s) from {source_count} source(s)."
            )
        elif usable >= 3:
            quality = EvidenceQuality.LIMITED
            notes.append(
                f"Price evidence limited: live scrape with {usable} usable "
                f"sample(s) from {source_count} source(s)."
            )
        elif not has_detail:
            quality = EvidenceQuality.LIMITED
            notes.append(
                "Price evidence limited: sample detail not supplied."
            )
        else:
            quality = EvidenceQuality.INSUFFICIENT
            notes.append(
                f"Price evidence insufficient: only {usable} usable live "
                f"sample(s) from {source_count} source(s); fewer than 3 "
                "usable samples."
            )
    elif price_source == "baseline":
        if (0 < usable < 3) or (usable == 0 and dropped > 0):
            # A live attempt fell back to this baseline with <3 usable
            # live samples (or only dropped samples).
            quality = EvidenceQuality.INSUFFICIENT
            notes.append(
                "Price evidence insufficient: the live scrape returned "
                f"only {usable} usable sample(s) and fell back to a baseline."
            )
        else:
            quality = EvidenceQuality.LIMITED
            notes.append("Price evidence limited: fresh baseline used.")
    else:
        quality = EvidenceQuality.LIMITED
        notes.append("Price evidence limited: unknown price source.")
    return quality, notes, has_detail


def evaluate_tier(
    *,
    category: CategoryEnum,
    asking_per_unit: float,
    min_price: float,
    expected_price: float,
    max_price: float,
    price_source: str,
    scan: dict,
    expected_margin_percent: float | None = None,
    installment_markup_percent: float | None = None,
    mileage_flag: bool = False,
    property_discrepancy_percent: float | None = None,
    usable_sample_count: int = 0,
    dropped_sample_count: int = 0,
    source_count: int = 0,
    stale_baseline: bool = False,
    missing_evidence: list[str] | None = None,
) -> RuleOutcome:
    """Deterministic tier boundaries (heuristics section 3 + edge cases)."""
    flags: list[str] = []
    rationale: list[str] = []
    missing = list(missing_evidence or [])
    evidence_quality, evidence_notes, _has_detail = _assess_evidence(
        price_source=price_source,
        usable_sample_count=usable_sample_count,
        dropped_sample_count=dropped_sample_count,
        source_count=source_count,
        stale_baseline=stale_baseline,
    )
    if missing:
        evidence_notes.append(
            "Some requested evidence was not supplied; see missing_evidence."
        )

    if scan["injection"]:
        flags.append("Adversarial input detected")

    if scan["illegal"]:
        flags.append(
            "Illegal or restricted item detected: do not buy; this is not a purchase to facilitate."
        )
        return RuleOutcome(
            VerdictTier.AVOID, ConfidenceLevel.LOW, flags, rationale,
            evidence_quality, evidence_notes, missing,
        )

    if scan["advance_token"]:
        flags.append(
            "Advance token scam pattern detected: money demanded before inspection or papers."
        )
        return RuleOutcome(
            VerdictTier.AVOID, ConfidenceLevel.LOW, flags, rationale,
            evidence_quality, evidence_notes, missing,
        )

    if scan["structural"]:
        flags.append(
            f"Structural damage reported or suspected ({', '.join(scan['structural'])}): avoid regardless of price."
        )
        return RuleOutcome(
            VerdictTier.AVOID, ConfidenceLevel.LOW, flags, rationale,
            evidence_quality, evidence_notes, missing,
        )

    # Price-band tier (before downgrades).
    if asking_per_unit < min_price:
        tier: VerdictTier = VerdictTier.GREAT_BUY
        rationale.append("asking price is below the market minimum")
    elif asking_per_unit <= expected_price:
        tier = VerdictTier.GOOD_BUY
        rationale.append("asking price is within the fair market band")
    elif asking_per_unit <= max_price:
        tier = VerdictTier.THINK_TWICE
        rationale.append("asking price is above the expected market price")
        flags.append("Asking price is above the expected market price; negotiate down.")
    else:
        tier = VerdictTier.THINK_TWICE
        rationale.append("asking price is above the market maximum")
        flags.append("Asking price is above the market maximum.")
        if asking_per_unit > max_price * 1.15:
            tier = VerdictTier.RISKY
            flags.append("Asking price is more than 15% above the market maximum.")

    # Scam pressure: never a Great Buy; at least Risky when combined with
    # a too-good-to-be-true price, otherwise a flag + cap at Think Twice.
    if scan["pressure"]:
        flags.append(
            "High-pressure seller tactics detected "
            f"({', '.join(scan['pressure'])}): verify in person before paying."
        )
        if asking_per_unit < min_price:
            tier = _worst(tier, VerdictTier.RISKY)
        else:
            tier = _worst(tier, VerdictTier.THINK_TWICE)

    if scan["defects"]:
        flags.append(
            f"Major defect reported ({', '.join(scan['defects'])}): get an independent inspection."
        )
        tier = _worst(tier, VerdictTier.RISKY)

    if (
        installment_markup_percent is not None
        and installment_markup_percent > 35
    ):
        flags.append(
            f"Installment markup is {installment_markup_percent:.1f}%, above the 35% predatory threshold."
        )
        tier = _worst(tier, VerdictTier.RISKY)

    if expected_margin_percent is not None and expected_margin_percent < 5:
        flags.append(
            f"Expected margin is {expected_margin_percent:.1f}%, below 5% after spoilage and costs."
        )
        if tier in (VerdictTier.GREAT_BUY, VerdictTier.GOOD_BUY):
            tier = VerdictTier.THINK_TWICE

    if category == CategoryEnum.PROPERTY and not scan["title_docs"]:
        flags.append(
            "No NOC, deed, Fard or registry evidence in the seller notes: title is unverified."
        )
        tier = _worst(tier, VerdictTier.RISKY)

    if property_discrepancy_percent is not None:
        if property_discrepancy_percent > 15:
            flags.append("Overpriced compared to the neighbourhood benchmark by more than 15%.")
            tier = _worst(tier, VerdictTier.THINK_TWICE)
        elif property_discrepancy_percent < -25:
            flags.append(
                "Price is more than 25% below benchmark: possible title dispute, unapproved scheme or token fraud."
            )
            tier = _worst(tier, VerdictTier.RISKY)

    if mileage_flag:
        flags.append(
            "Claimed mileage is far below the expected mileage for the vehicle's age: odometer audit needed."
        )

    # Estimate / stale-baseline cap: a band derived ONLY from the
    # asking price (or a stale baseline) can never independently
    # justify Great Buy. Cap to Good Buy with a note. Applied after
    # the other downgrades (which may already have moved the tier
    # away from Great Buy) and before the injection floor, so an
    # injection still forces Risky.
    if tier == VerdictTier.GREAT_BUY and (
        price_source == "estimate" or stale_baseline
    ):
        if price_source == "estimate":
            cap_note = (
                "Price band is derived only from the asking price, so "
                "Great Buy is capped to Good Buy."
            )
        else:
            cap_note = (
                "Baseline is stale (older than 90 days), so Great Buy "
                "is capped to Good Buy."
            )
        tier = VerdictTier.GOOD_BUY
        rationale.append(cap_note)
        evidence_notes.append(cap_note)

    # Injection floor: an injection attempt forces at least Risky, no
    # matter how cheap the price looks. It never softens a worse tier
    # (Avoid stays Avoid — the early returns above already handle the
    # scam/illegal/structural cases), and an injected tier demand is
    # always ignored because the tier here comes only from rules.
    if scan["injection"]:
        tier = _worst(tier, VerdictTier.RISKY)

    # Confidence: existing price-source mapping, adjusted by evidence
    # quality (insufficient -> Low; limited caps High -> Medium only
    # when sample detail was supplied; stale -> Low).
    if price_source == "live scrape":
        confidence = ConfidenceLevel.HIGH
    elif price_source == "baseline":
        confidence = ConfidenceLevel.MEDIUM
    else:
        confidence = ConfidenceLevel.LOW
    if evidence_quality == EvidenceQuality.INSUFFICIENT:
        confidence = ConfidenceLevel.LOW
    elif (
        evidence_quality == EvidenceQuality.LIMITED
        and _has_detail
        and confidence == ConfidenceLevel.HIGH
    ):
        confidence = ConfidenceLevel.MEDIUM
    if stale_baseline:
        confidence = ConfidenceLevel.LOW
    if scan["injection"] or scan["pressure"] or mileage_flag:
        confidence = ConfidenceLevel.LOW

    # Red flags: most severe first, keep the list focused.
    ordered = []
    for key in (
        "Adversarial input detected",
    ):
        if key in flags:
            ordered.append(key)
    ordered.extend(f for f in flags if f not in ordered)
    return RuleOutcome(
        tier, confidence, ordered, rationale,
        evidence_quality, evidence_notes, missing,
    )


def money_str(value: float, currency: str) -> str:
    return f"{value:,.0f} {currency}"


def build_plain_truth(
    *,
    tier: VerdictTier,
    title: str,
    asking_total: float,
    asking_per_unit: float,
    quantity: float,
    unit: str,
    currency: str,
    band_min: float,
    band_expected: float,
    band_max: float,
    price_source: str,
    offers: dict[str, float],
    top_flag: str | None,
) -> str:
    """Exactly two sentences, built from templates with numbers."""
    per_unit = (
        f"{money_str(asking_per_unit, currency)} per {unit}"
        if quantity != 1
        else money_str(asking_total, currency)
    )
    band = (
        f"{money_str(band_min, currency)} to {money_str(band_max, currency)} "
        f"per {unit} (expected {money_str(band_expected, currency)})"
    )
    if tier == VerdictTier.AVOID:
        first = (
            f"Do not buy {title} at {per_unit} because "
            f"{(top_flag or 'a serious risk was detected').lower().rstrip('.')}."
        )
        second = "Walk away and do not pay any advance before in-person verification."
    elif tier == VerdictTier.RISKY:
        first = (
            f"{title} at {per_unit} is risky against a market band of {band} "
            f"from {price_source} data."
        )
        second = (
            f"Only proceed after the checklist checks pass and offer no more than "
            f"{money_str(offers['walk_away'], currency)}."
        )
    elif tier == VerdictTier.THINK_TWICE:
        if asking_per_unit > band_expected:
            position = "is above the expected market price"
        elif asking_per_unit < band_min:
            position = "is below the market band, but costs or spoilage erode the margin"
        else:
            position = "is within the market band, but costs or spoilage erode the margin"
        first = (
            f"{title} at {per_unit} {position}, with a market band of "
            f"{band} from {price_source} data."
        )
        second = (
            f"Counter at {money_str(offers['opening'], currency)} and walk away above "
            f"{money_str(offers['walk_away'], currency)}."
        )
    elif tier == VerdictTier.GREAT_BUY:
        first = (
            f"{title} at {per_unit} is below the market band of {band} "
            f"from {price_source} data."
        )
        second = (
            f"Verify it in person, then offer {money_str(offers['opening'], currency)} "
            f"and settle near {money_str(offers['target'], currency)}."
        )
    else:
        first = (
            f"{title} at {per_unit} is fairly priced within the market band of "
            f"{band} from {price_source} data."
        )
        second = (
            f"Verify it in person and aim to settle near "
            f"{money_str(offers['target'], currency)}."
        )
    return f"{first} {second}"
