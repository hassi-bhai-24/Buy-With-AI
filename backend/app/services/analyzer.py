"""Analysis orchestrator: scrape + baseline -> rules -> Ollama (optional).

Ollama is tried only when its daemon answers a health check. When it
returns a usable verdict, its wording is used but the deterministic
rule tier, price band and cash-flow numbers always win: an LLM result
can never soften a rule-based Risky/Avoid tier. When Ollama is
unreachable or its output fails validation, the rule-based engine is
used and the response is labelled engine="rule-based".
"""

from __future__ import annotations

import asyncio
import json
import statistics
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..models.baseline import PriceBaseline
from ..models.check import Check
from ..models.user import User
from ..schemas.request import AnalyzeRequest
from ..schemas.response import (
    BrandMarkupAudit,
    CategoryEnum,
    ConfidenceLevel,
    Coordinates,
    EvidenceQuality,
    PriceBand,
    VerdictResponse,
    VerdictTier,
)
from .cash_flow import CashFlowInputs, build_cash_flow
from .guards import sanitize_text
from .integrations import geocode_place
from .ollama_client import SYSTEM_PROMPT, OllamaClient
from .rules import (
    _worst,
    audit_installment_plan,
    build_plain_truth,
    checklist_for,
    counter_offers,
    evaluate_tier,
    money_str,
    next_steps_for,
    parse_kilometres,
    parse_marla_area,
    parse_year,
    scan_text,
)
from .scraper import AsyncScraperService, select_live_samples


def _baseline_age_days(scraped_at: datetime | None) -> int:
    """Age of a baseline in whole days, safe for naive/aware datetimes.

    Naive datetimes (as stored by ``datetime.utcnow()`` seeding) are
    treated as UTC; aware datetimes are converted to UTC first.
    """
    if scraped_at is None:
        return 0
    if scraped_at.tzinfo is None:
        scraped = scraped_at.replace(tzinfo=timezone.utc)
    else:
        scraped = scraped_at.astimezone(timezone.utc)
    delta = datetime.now(timezone.utc) - scraped
    return max(0, delta.days)


def check_to_response(row: Check) -> VerdictResponse:
    """Rebuild the API response from a persisted Check row.

    ``coordinates`` is live-only: it is attached to the analyze
    response at analysis time and is NOT persisted (no column was
    added), so history rows always return ``coordinates=None``.

    Evidence fields are DERIVED from ``price_source`` only (no
    migration in Part 1, no DB columns added): estimate ->
    insufficient, baseline -> limited, live scrape -> limited with a
    note that sample detail was not retained. Missing evidence
    cannot be derived from a stored row, so it is empty.
    """
    from ..schemas.response import CashFlowTable, SpoilageSummary

    band = None
    if row.price_min is not None and row.price_expected is not None and row.price_max is not None:
        if row.price_source == "baseline":
            band_source = "baseline (cached/seed estimate)"
        elif row.price_source == "estimate":
            band_source = "estimate — asking-price-derived"
        elif row.price_source == "live scrape":
            band_source = "live scrape (detail not retained)"
        else:
            band_source = ""
        band = PriceBand(
            min_price=row.price_min,
            expected_price=row.price_expected,
            max_price=row.price_max,
            currency=row.currency,
            unit=row.unit_of_measure or "unit",
            source=band_source,
        )
    if row.price_source == "estimate":
        evidence_quality = EvidenceQuality.INSUFFICIENT
        evidence_notes = [
            "Price band was derived from the asking price; "
            "sample detail not retained for history rows."
        ]
    elif row.price_source == "live scrape":
        evidence_quality = EvidenceQuality.LIMITED
        evidence_notes = ["sample detail not retained for history rows"]
    else:
        evidence_quality = EvidenceQuality.LIMITED
        evidence_notes = [
            "Baseline evidence; sample detail not retained for history rows."
        ]
    markup = None
    if row.estimated_bom_cost is not None and row.brand_markup_percent is not None:
        markup = BrandMarkupAudit(
            estimated_making_cost=row.estimated_bom_cost,
            retail_asking_price=row.asking_price or 0.0,
            markup_percentage=row.brand_markup_percent,
            notes="Rough estimate, not a measured BOM.",
        )
    cash_flow = (
        CashFlowTable(**row.cash_flow_json) if row.cash_flow_json else None
    )
    spoilage = (
        SpoilageSummary(**row.spoilage_json) if row.spoilage_json else None
    )
    return VerdictResponse(
        id=row.id,
        title=row.item_title,
        category=CategoryEnum(row.category),
        location=row.location_str,
        verdict=VerdictTier(row.verdict_tier),
        plain_truth=row.plain_truth,
        confidence=ConfidenceLevel(row.confidence_score),
        price_band=band,
        brand_markup=markup,
        cash_flow=cash_flow,
        red_flags=list(row.red_flags_json or []),
        verify_checklist=list(row.verify_checklist_json or []),
        counter_offers=dict(row.counter_offers_json or {}),
        sources_cited=list(row.sources_cited_json or []),
        engine=row.engine,  # type: ignore[arg-type]
        price_source=row.price_source,  # type: ignore[arg-type]
        evidence_quality=evidence_quality,
        evidence_notes=evidence_notes,
        missing_evidence=[],
        spoilage=spoilage,
        coordinates=None,
        next_steps=list(row.next_steps_json or []),
        created_at=row.created_at,
        is_pinned=bool(row.is_pinned),
    )


class AnalysisOrchestrator:
    def __init__(
        self,
        session: AsyncSession,
        scraper: AsyncScraperService | None = None,
        ollama: OllamaClient | None = None,
    ) -> None:
        self.session = session
        self.scraper = scraper or AsyncScraperService()
        self.ollama = ollama or OllamaClient()

    async def analyze(
        self,
        request: AnalyzeRequest,
        on_progress: Any | None = None,
    ) -> VerdictResponse:
        """Run the full analysis.

        ``on_progress`` is an optional async callback invoked at genuine
        stage boundaries with ``(step, status)``: (1) classification /
        validation done, (2) market-rate lookup done, (3) markup and
        cash-flow computation done, (4) red-flag scan done. It is used by
        the SSE stream endpoint so progress reflects real work, not a
        timer. When no callback is given, behaviour and return value are
        unchanged. A failing callback never breaks the analysis.
        """
        description = sanitize_text(request.description)
        seller_notes = sanitize_text(request.seller_notes)
        combined = f"{description} {seller_notes}".strip()
        # The title is also untrusted text that reaches the LLM
        # payload, so it must be scanned too: a title-only injection
        # ("Ignore all instructions…") previously bypassed detection
        # entirely. Scan the sanitized full title (not the truncated
        # derived title) together with description + seller notes.
        # The title is used ONLY for scanning here; baseline lookup
        # and vehicle/property parsing keep using `combined` as before.
        sanitized_title = (
            sanitize_text(request.title, max_length=255)
            if request.title
            else ""
        )
        scan_combined = f"{sanitized_title} {combined}".strip()
        scan = scan_text(scan_combined)
        location_str = request.location.display()
        currency = request.currency.value
        title = self._derive_title(request, description)

        async def _report(step: int, status: str) -> None:
            if on_progress is None:
                return
            try:
                await on_progress(step, status)
            except Exception:
                pass

        await _report(1, "Classifying category and location parameters...")

        # -- concurrent market data -------------------------------------
        async def _safe_search() -> list[dict]:
            try:
                return await self.scraper.search_market(
                    description[:120], location_str
                )
            except Exception:
                return []

        async def _safe_baseline() -> PriceBaseline | None:
            try:
                return await self.scraper.lookup_baseline(
                    self.session, combined,
                    request.location.city, request.location.country,
                )
            except Exception:
                return None

        async def _safe_geocode() -> Coordinates | None:
            # Best-effort enrichment: any failure leaves coordinates
            # null and never affects the verdict. Runs concurrently
            # with the market lookup, capped by the 8s upstream timeout.
            try:
                result = await geocode_place(location_str)
            except Exception:
                return None
            if not result:
                return None
            try:
                return Coordinates(
                    lat=float(result["lat"]),
                    lon=float(result["lon"]),
                    display_name=str(result["display_name"]),
                )
            except (KeyError, TypeError, ValueError):
                return None

        results, baseline, coordinates = await asyncio.gather(
            _safe_search(), _safe_baseline(), _safe_geocode()
        )

        # -- price band ---------------------------------------------------
        # Sample quality (Part 1): currency filtering, dedupe and
        # IQR outlier trimming happen in select_live_samples; the
        # selection is computed even when the live band is not used,
        # so fallback bands can report the live attempt honestly.
        selection = select_live_samples(results, currency)
        usable = selection.usable_values
        sources_cited: list[str] = []
        evidence_notes: list[str] = []
        stale_baseline = False
        baseline_age_days: int | None = None
        band: PriceBand
        if len(usable) >= 3:
            ordered = usable  # already sorted by select_live_samples
            band = PriceBand(
                min_price=ordered[0],
                expected_price=float(statistics.median(ordered)),
                max_price=ordered[-1],
                currency=currency,
                unit=request.unit,
                source=(
                    f"live scrape — {len(ordered)} usable sample(s) from "
                    f"{selection.source_count} source(s)"
                ),
                usable_sample_count=len(ordered),
                dropped_sample_count=selection.dropped_count,
            )
            price_source = "live scrape"
            for result in results:
                label = result.get("title") or "DuckDuckGo HTML result"
                url = result.get("url") or ""
                sources_cited.append(f"{label} — {url} (live scrape)".strip())
            sources_cited.append(
                f"Live scrape: {len(ordered)} usable price sample(s) from "
                f"{selection.source_count} distinct source(s); "
                f"{selection.dropped_count} sample(s) dropped "
                "(currency mismatch, duplicates or outliers)."
            )
            if selection.unknown_currency_count:
                evidence_notes.append(
                    f"{selection.unknown_currency_count} usable sample(s) "
                    "had no detected currency and were treated as usable "
                    "(unknown currency)."
                )
        else:
            if selection.raw_count > 0:
                evidence_notes.append(
                    f"Live scrape returned {len(usable)} usable sample(s) "
                    f"({selection.dropped_count} dropped); fewer than 3 "
                    "usable, so the live band was not used."
                )
            # Baseline eligibility: currency must match the request
            # currency AND the unit must match (or the request unit
            # is the generic "unit"). On mismatch the baseline is
            # skipped entirely — never silently relabelled.
            baseline_usable = False
            if baseline is not None:
                baseline_age_days = _baseline_age_days(baseline.scraped_at)
                stale_baseline = baseline_age_days > 90
                currency_ok = baseline.currency.upper() == currency.upper()
                unit_ok = (
                    baseline.unit.lower() == request.unit.lower()
                    or request.unit.lower() == "unit"
                )
                if currency_ok and unit_ok:
                    baseline_usable = True
                else:
                    reasons = []
                    if not currency_ok:
                        reasons.append(
                            f"baseline currency {baseline.currency} does "
                            f"not match request currency {currency}"
                        )
                    if not unit_ok:
                        reasons.append(
                            f"baseline unit {baseline.unit} does not match "
                            f"request unit {request.unit}"
                        )
                    evidence_notes.append(
                        "Baseline skipped (" + "; ".join(reasons) + "); "
                        "fell back to an asking-price estimate rather than "
                        "silently relabelling units or currency."
                    )
                    stale_baseline = False
                    baseline_age_days = None
            if baseline is not None and baseline_usable:
                band = PriceBand(
                    min_price=baseline.low_price,
                    expected_price=baseline.median_price,
                    max_price=baseline.high_price,
                    currency=baseline.currency,
                    unit=baseline.unit,
                    source=(
                        f"Baseline '{baseline.keyword}' in {baseline.city}, "
                        f"scraped at {baseline.scraped_at.isoformat()} "
                        f"({baseline_age_days} days ago)"
                    ),
                    usable_sample_count=0,
                    dropped_sample_count=selection.dropped_count,
                )
                price_source = "baseline"
                for source in baseline.sources_json or []:
                    if isinstance(source, dict):
                        note = source.get("note") or source.get("source") or str(source)
                        sources_cited.append(str(note))
                    else:
                        sources_cited.append(str(source))
                sources_cited.append(
                    f"Baseline for '{baseline.keyword}' in {baseline.city}, "
                    f"scraped at {baseline.scraped_at.isoformat()} "
                    f"({baseline_age_days} days ago; baseline, not live)."
                )
                if stale_baseline:
                    evidence_notes.append(
                        f"Baseline is stale: scraped {baseline_age_days} "
                        "days ago (older than 90 days)."
                    )
            else:
                asking_per_unit = request.asking_price / request.quantity
                band = PriceBand(
                    min_price=asking_per_unit * 0.85,
                    expected_price=asking_per_unit,
                    max_price=asking_per_unit * 1.15,
                    currency=currency,
                    unit=request.unit,
                    source=(
                        "estimate — asking-price-derived "
                        "(no live or baseline data)"
                    ),
                    usable_sample_count=0,
                    dropped_sample_count=selection.dropped_count,
                )
                price_source = "estimate"
                sources_cited.append(
                    "Estimate from the asking price: no live scrape or baseline data was available."
                )
                evidence_notes.append(
                    "Price band is derived only from the asking price."
                )

        await _report(
            2,
            f"Market rates checked in {location_str} "
            f"({price_source} data)...",
        )

        asking_per_unit = request.asking_price / request.quantity

        # -- cash flow / spoilage -----------------------------------------
        cash_flow = None
        spoilage = None
        expected_margin: float | None = None
        if request.category in (CategoryEnum.PERISHABLE, CategoryEnum.INVENTORY):
            temperature_assumed = request.temperature_c is None
            temperature = request.temperature_c if request.temperature_c is not None else 32.0
            retail_assumed = request.selling_price is None
            retail_price = (
                request.selling_price
                if request.selling_price is not None
                else band.expected_price * 1.3
            )
            transit_assumed = request.transit_damage_percent is None
            transit_damage = (
                request.transit_damage_percent
                if request.transit_damage_percent is not None
                else 0.10
            )
            cash_flow, spoilage, expected_margin = build_cash_flow(
                CashFlowInputs(
                    quantity=request.quantity,
                    wholesale_price_per_unit=asking_per_unit,
                    retail_price_per_unit=retail_price,
                    days_to_sell=request.days_to_sell,
                    temperature_c=temperature,
                    temperature_assumed=temperature_assumed,
                    transit_damage=transit_damage,
                )
            )
            # Assumptions transparency (Part 3): only entries that
            # actually apply — a user-supplied value never appears
            # as an assumption. days_to_sell is the time horizon
            # (hours = days * 24); no lambda override exists.
            assumptions: list[str] = []
            if retail_assumed:
                assumptions.append(
                    f"Assumed selling price {retail_price:,.0f} {currency} "
                    f"per {request.unit} (1.3x the expected band price) "
                    "because no selling price was supplied."
                )
            if temperature_assumed:
                assumptions.append(
                    f"Assumed temperature {temperature:.1f}C because "
                    "none was supplied."
                )
            if transit_assumed:
                assumptions.append(
                    f"Assumed transit damage {transit_damage:.0%} because "
                    "none was supplied."
                )
            assumptions.append(
                "Profit figures are projections based on these "
                "assumptions, not guaranteed."
            )
            spoilage.assumptions = assumptions
            if retail_assumed:
                spoilage.rationale += (
                    " Assumed resale price is 1.3x the expected band price "
                    "because no selling price was supplied."
                )
            if temperature_assumed:
                spoilage.rationale += (
                    " Temperature assumed 32C because none was supplied."
                )

        # -- installment markup -------------------------------------------
        installment_markup: float | None = None
        if (
            request.down_payment is not None
            and request.monthly_installment is not None
            and request.installment_months is not None
        ):
            audit = audit_installment_plan(
                request.asking_price,
                request.down_payment,
                request.monthly_installment,
                request.installment_months,
            )
            installment_markup = audit.markup_percent

        # -- vehicle mileage ----------------------------------------------
        mileage_flag = False
        vehicle_year: int | None = None
        vehicle_km: float | None = None
        if request.category == CategoryEnum.VEHICLE:
            vehicle_year = parse_year(combined)
            vehicle_km = parse_kilometres(combined)
            if vehicle_year is not None and vehicle_km is not None:
                age = datetime.now().year - vehicle_year
                if age > 0 and vehicle_km < 0.40 * age * 12000:
                    mileage_flag = True

        # -- property discrepancy ------------------------------------------
        discrepancy: float | None = None
        if request.category == CategoryEnum.PROPERTY:
            area = request.area_marla or parse_marla_area(combined)
            if area:
                per_marla = request.asking_price / area
                if band.expected_price > 0:
                    discrepancy = (per_marla - band.expected_price) / band.expected_price * 100.0

        await _report(3, "Auditing manufacturing cost and brand marketing markup...")

        # -- missing evidence (Part 1) ------------------------------------
        # Listed only: missing evidence creates NO new red flag and NO
        # tier downgrade, EXCEPT the pre-existing property-no-title
        # behaviour (red flag + Risky floor in evaluate_tier), which
        # is kept exactly as-is AND also listed here. That deliberate
        # exception is documented in BUILD-REPORT.md.
        missing_evidence: list[str] = []
        if request.category in (CategoryEnum.PERISHABLE, CategoryEnum.INVENTORY):
            if request.selling_price is None:
                missing_evidence.append(
                    "Selling price not supplied — resale price was assumed "
                    "for cash-flow estimates."
                )
            if request.temperature_c is None:
                missing_evidence.append(
                    "Temperature not supplied — 32C assumed for spoilage estimates."
                )
        if request.category == CategoryEnum.VEHICLE:
            if vehicle_year is None or vehicle_km is None:
                missing_evidence.append(
                    "Mileage or vehicle year not supplied — odometer check skipped."
                )
        if request.category == CategoryEnum.PROPERTY and not scan["title_docs"]:
            missing_evidence.append(
                "Title documents not supplied — NOC, Fard or registry "
                "papers not mentioned in the seller notes."
            )

        outcome = evaluate_tier(
            category=request.category,
            asking_per_unit=asking_per_unit,
            min_price=band.min_price,
            expected_price=band.expected_price,
            max_price=band.max_price,
            price_source=price_source,
            scan=scan,
            expected_margin_percent=expected_margin,
            installment_markup_percent=installment_markup,
            mileage_flag=mileage_flag,
            property_discrepancy_percent=discrepancy,
            usable_sample_count=selection.usable_count,
            dropped_sample_count=selection.dropped_count,
            source_count=selection.source_count,
            stale_baseline=stale_baseline,
            missing_evidence=missing_evidence,
        )
        # Merge analyzer-level evidence notes (band age, fallback,
        # unknown currency) with the rule outcome's notes, deduped.
        merged_evidence_notes = list(outcome.evidence_notes)
        for note in evidence_notes:
            if note not in merged_evidence_notes:
                merged_evidence_notes.append(note)

        await _report(4, "Scanning fraud patterns and advance-token traps...")

        offers = counter_offers(
            request.asking_price, band.expected_price * request.quantity
        )
        checklist = checklist_for(request.category, scan)
        steps = next_steps_for(
            outcome.tier, offers, currency, request.category, scan
        )
        plain_truth = build_plain_truth(
            tier=outcome.tier,
            title=title,
            asking_total=request.asking_price,
            asking_per_unit=asking_per_unit,
            quantity=request.quantity,
            unit=request.unit,
            currency=currency,
            band_min=band.min_price,
            band_expected=band.expected_price,
            band_max=band.max_price,
            price_source=price_source,
            offers=offers,
            top_flag=outcome.red_flags[0] if outcome.red_flags else None,
        )

        # -- Ollama (only if reachable; rules always win on tier/numbers) --
        engine: str = "rule-based"
        tier = outcome.tier
        try:
            healthy = await self.ollama.check_health()
        except Exception:
            healthy = False
        if healthy:
            payload = {
                "title": title,
                "description": description,
                "seller_notes": seller_notes,
                "category": request.category.value,
                "location": location_str,
                "asking_price": request.asking_price,
                "currency": currency,
                "quantity": request.quantity,
                "unit": request.unit,
                "price_band": band.model_dump(),
                "price_source": price_source,
                "red_flags": outcome.red_flags,
                "verdict": outcome.tier.value,
                "plain_truth": plain_truth,
            }
            ollama_result = await self.ollama.generate_verdict(
                SYSTEM_PROMPT, json.dumps(payload)
            )
            if ollama_result is not None:
                engine = "ollama"
                try:
                    ollama_tier = VerdictTier(ollama_result["verdict"])
                    # Severity wins: _worst() uses the _SEVERITY map, so an
                    # Ollama result can only worsen the deterministic tier
                    # — it can never soften a rule-based Risky/Avoid (in
                    # particular never an injection-forced Risky) back
                    # toward a better tier.
                    tier = _worst(tier, ollama_tier)
                except (KeyError, ValueError):
                    pass
                plain_truth = str(ollama_result["plain_truth"])
                ollama_flags = ollama_result.get("red_flags")
                if isinstance(ollama_flags, list):
                    merged = list(outcome.red_flags)
                    for flag in ollama_flags:
                        if isinstance(flag, str) and flag not in merged:
                            merged.append(flag)
                    outcome.red_flags = merged
                ollama_checklist = ollama_result.get("verify_checklist")
                if isinstance(ollama_checklist, list) and 3 <= len(ollama_checklist) <= 5:
                    checklist = [str(item) for item in ollama_checklist]
                ollama_steps = ollama_result.get("next_steps")
                if isinstance(ollama_steps, list) and 2 <= len(ollama_steps) <= 4:
                    steps = [str(item) for item in ollama_steps]
                # If Ollama softened nothing but the tier worsened, rebuild
                # next steps from the final tier so they stay consistent.
                if tier != outcome.tier:
                    steps = next_steps_for(
                        tier, offers, currency, request.category, scan
                    )

        brand_markup = None
        if request.category == CategoryEnum.RETAIL:
            making = request.asking_price * 0.2
            markup_pct = (
                (request.asking_price - making) / making * 100.0 if making else 0.0
            )
            brand_markup = BrandMarkupAudit(
                estimated_making_cost=round(making, 2),
                retail_asking_price=request.asking_price,
                markup_percentage=round(markup_pct, 2),
                notes="Rough estimate, not a measured BOM.",
            )

        response = VerdictResponse(
            id=str(uuid.uuid4()),
            title=title,
            category=request.category,
            location=location_str,
            verdict=tier,
            plain_truth=plain_truth,
            confidence=outcome.confidence,
            price_band=band,
            brand_markup=brand_markup,
            cash_flow=cash_flow,
            red_flags=outcome.red_flags,
            verify_checklist=checklist,
            counter_offers=offers,
            sources_cited=sources_cited,
            engine=engine,  # type: ignore[arg-type]
            price_source=price_source,  # type: ignore[arg-type]
            evidence_quality=outcome.evidence_quality,
            evidence_notes=merged_evidence_notes,
            missing_evidence=outcome.missing_evidence,
            spoilage=spoilage,
            # Live-only: coordinates are not persisted (see _persist /
            # check_to_response); history rows return coordinates=None.
            coordinates=coordinates,
            next_steps=steps,
            created_at=datetime.utcnow(),
        )

        if not request.private_mode:
            await self._persist(request, response, description, scan)
        return response

    async def _persist(
        self,
        request: AnalyzeRequest,
        response: VerdictResponse,
        query_raw: str,
        scan: dict,
    ) -> None:
        device_uuid = request.device_uuid or f"guest-{uuid.uuid4()}"
        result = await self.session.execute(
            select(User).where(User.device_uuid == device_uuid)
        )
        user = result.scalars().first()
        if user is None:
            user = User(
                device_uuid=device_uuid,
                country=request.location.country,
                province=request.location.province,
                city=request.location.city,
                preferred_currency=request.currency.value,
            )
            self.session.add(user)
            await self.session.flush()

        band = response.price_band
        row = Check(
            id=response.id,
            user_id=user.id,
            query_raw=query_raw,
            item_title=response.title,
            category=response.category.value,
            verdict_tier=response.verdict.value,
            plain_truth=response.plain_truth,
            confidence_score=response.confidence.value,
            price_min=band.min_price if band else None,
            price_expected=band.expected_price if band else None,
            price_max=band.max_price if band else None,
            currency=request.currency.value,
            unit_of_measure=band.unit if band else request.unit,
            asking_price=request.asking_price,
            quantity=request.quantity,
            location_str=response.location,
            estimated_bom_cost=(
                response.brand_markup.estimated_making_cost
                if response.brand_markup
                else None
            ),
            brand_markup_percent=(
                response.brand_markup.markup_percentage
                if response.brand_markup
                else None
            ),
            cash_flow_json=(
                response.cash_flow.model_dump() if response.cash_flow else None
            ),
            red_flags_json=response.red_flags,
            verify_checklist_json=response.verify_checklist,
            counter_offers_json=response.counter_offers,
            sources_cited_json=response.sources_cited,
            engine=response.engine,
            price_source=response.price_source,
            spoilage_json=response.spoilage.model_dump() if response.spoilage else None,
            next_steps_json=response.next_steps,
            is_private_check=False,
        )
        self.session.add(row)
        await self.session.commit()

    @staticmethod
    def _derive_title(request: AnalyzeRequest, description: str) -> str:
        if request.title:
            raw = sanitize_text(request.title, max_length=255)
        else:
            raw = description
        # A title must not carry sentence punctuation into plain_truth.
        raw = raw.split(".")[0].split("!")[0].split("?")[0].strip()
        words = raw.split()
        title = " ".join(words[:10])
        if len(title) > 70:
            title = title[:70].rsplit(" ", 1)[0]
        return title or "This item"


# Re-export for routers that only need the money helper.
__all__ = ["AnalysisOrchestrator", "check_to_response", "money_str"]
