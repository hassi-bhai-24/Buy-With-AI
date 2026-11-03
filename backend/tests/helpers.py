"""Shared seeding helper for tests."""

from __future__ import annotations

from datetime import datetime

from app.models.baseline import PriceBaseline

SEED_SOURCE = [
    {"source": "seed-estimate", "note": "Seed baseline — estimate, not a live market price"}
]


async def add_baseline(
    session,
    keyword: str,
    city: str = "Bahawalpur",
    low: float = 70.0,
    median: float = 82.0,
    high: float = 95.0,
    unit: str = "kg",
    country: str = "Pakistan",
    currency: str = "PKR",
) -> PriceBaseline:
    row = PriceBaseline(
        keyword=keyword,
        country=country,
        city=city,
        low_price=low,
        median_price=median,
        high_price=high,
        unit=unit,
        currency=currency,
        sources_json=SEED_SOURCE,
        scraped_at=datetime.utcnow(),
    )
    session.add(row)
    await session.commit()
    return row
