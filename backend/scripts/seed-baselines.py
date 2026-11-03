"""Seed the price_baselines table with 100+ labelled estimates.

Run from the backend directory:

    python scripts/seed-baselines.py

HONESTY: every row inserted here is a seed ESTIMATE, not a live market
price. Each row's sources_json says so. Live prices come only from the
DuckDuckGo HTML scraper at request time; when it fails, responses are
labelled price_source="baseline" and cite the baseline's scrape time.
No credentials or paid APIs are used.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402

from app.database import AsyncSessionLocal, init_db  # noqa: E402
from app.models.baseline import PriceBaseline  # noqa: E402

SOURCE = [{"source": "seed-estimate", "note": "Seed baseline — estimate, not a live market price"}]

# (keyword, unit, low, median, high) — Bahawalpur base values.
COMMODITIES: list[tuple[str, str, float, float, float]] = [
    ("tomato", "kg", 70, 82, 95),
    ("potato", "kg", 55, 65, 78),
    ("onion", "kg", 60, 72, 85),
    ("wheat", "kg", 90, 100, 112),
    ("rice", "kg", 320, 360, 410),
    ("sugar", "kg", 145, 155, 168),
    ("cooking oil", "litre", 560, 600, 650),
    ("chicken", "kg", 480, 520, 570),
    ("eggs", "dozen", 260, 285, 310),
    ("milk", "litre", 170, 185, 200),
    ("garlic", "kg", 380, 420, 470),
    ("ginger", "kg", 420, 460, 520),
    ("apple", "kg", 220, 260, 300),
    ("banana", "dozen", 140, 160, 185),
    ("lentils", "kg", 280, 310, 345),
    ("flour", "kg", 130, 142, 155),
]

CITY_MULTIPLIERS: list[tuple[str, float]] = [
    ("Bahawalpur", 1.00),
    ("Lahore", 1.08),
    ("Karachi", 1.12),
    ("Islamabad", 1.15),
    ("Multan", 1.02),
]

VEHICLES: list[tuple[str, float, float, float]] = [
    ("suzuki alto", 1_780_000, 1_870_000, 1_980_000),
    ("suzuki cultus", 2_100_000, 2_250_000, 2_400_000),
    ("suzuki mehran", 650_000, 720_000, 800_000),
    ("suzuki mira", 2_200_000, 2_350_000, 2_500_000),
    ("honda city", 3_400_000, 3_650_000, 3_900_000),
    ("honda civic", 5_200_000, 5_600_000, 6_100_000),
    ("toyota corolla", 4_500_000, 4_800_000, 5_200_000),
    ("toyota yaris", 3_900_000, 4_150_000, 4_400_000),
]

PROPERTY_MARLA: list[tuple[str, float, float, float]] = [
    ("Bahawalpur", 220_000, 285_000, 350_000),
    ("Lahore", 450_000, 600_000, 750_000),
    ("Karachi", 500_000, 650_000, 800_000),
    ("Islamabad", 700_000, 900_000, 1_100_000),
]

RETAIL: list[tuple[str, float, float, float]] = [
    ("sneakers", 4_500, 6_000, 8_500),
    ("smartphone", 45_000, 65_000, 95_000),
    ("air conditioner", 95_000, 120_000, 150_000),
    ("led tv", 55_000, 75_000, 105_000),
    ("washing machine", 45_000, 58_000, 72_000),
    ("refrigerator", 85_000, 110_000, 145_000),
    ("headphones", 3_500, 5_500, 9_000),
]


def build_rows() -> list[PriceBaseline]:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    rows: list[PriceBaseline] = []
    for keyword, unit, low, median, high in COMMODITIES:
        for city, mult in CITY_MULTIPLIERS:
            rows.append(PriceBaseline(
                keyword=keyword, country="Pakistan", city=city,
                low_price=round(low * mult, 2),
                median_price=round(median * mult, 2),
                high_price=round(high * mult, 2),
                unit=unit, currency="PKR", sources_json=SOURCE, scraped_at=now,
            ))
    for keyword, low, median, high in VEHICLES:
        for city in ("Bahawalpur", "Lahore", "Karachi"):
            rows.append(PriceBaseline(
                keyword=keyword, country="Pakistan", city=city,
                low_price=low, median_price=median, high_price=high,
                unit="unit", currency="PKR", sources_json=SOURCE, scraped_at=now,
            ))
    for city, low, median, high in PROPERTY_MARLA:
        rows.append(PriceBaseline(
            keyword="marla", country="Pakistan", city=city,
            low_price=low, median_price=median, high_price=high,
            unit="marla", currency="PKR", sources_json=SOURCE, scraped_at=now,
        ))
        rows.append(PriceBaseline(
            keyword="kanal", country="Pakistan", city=city,
            low_price=low * 20, median_price=median * 20, high_price=high * 20,
            unit="kanal", currency="PKR", sources_json=SOURCE, scraped_at=now,
        ))
    for keyword, low, median, high in RETAIL:
        for city in ("Bahawalpur", "Lahore"):
            rows.append(PriceBaseline(
                keyword=keyword, country="Pakistan", city=city,
                low_price=low, median_price=median, high_price=high,
                unit="unit", currency="PKR", sources_json=SOURCE, scraped_at=now,
            ))
    return rows


async def main() -> None:
    await init_db()
    rows = build_rows()
    upserted = 0
    async with AsyncSessionLocal() as session:
        for row in rows:
            existing = (
                await session.execute(
                    select(PriceBaseline).where(
                        PriceBaseline.keyword == row.keyword,
                        PriceBaseline.city == row.city,
                        PriceBaseline.country == row.country,
                    )
                )
            ).scalars().first()
            if existing is None:
                session.add(row)
            else:
                existing.low_price = row.low_price
                existing.median_price = row.median_price
                existing.high_price = row.high_price
                existing.unit = row.unit
                existing.currency = row.currency
                existing.sources_json = row.sources_json
                existing.scraped_at = row.scraped_at
            upserted += 1
        await session.commit()
    print(
        f"Seeded/upserted {upserted} baselines. "
        "These are ESTIMATES, not live market prices."
    )


if __name__ == "__main__":
    asyncio.run(main())
