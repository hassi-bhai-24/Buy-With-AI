"""Health and baseline listing."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..database import get_db
from ..models.baseline import PriceBaseline
from ..services.ollama_client import OllamaClient

router = APIRouter()


class BaselineOut(BaseModel):
    id: str
    keyword: str
    country: str
    city: str
    low_price: float
    median_price: float
    high_price: float
    unit: str
    currency: str
    sources_json: list[dict]
    scraped_at: datetime


@router.get("/health")
async def health() -> dict:
    settings = get_settings()
    ollama_reachable = await OllamaClient().check_health()
    return {
        "status": "ok",
        "app": settings.APP_NAME,
        "version": settings.APP_VERSION,
        "ollama_reachable": ollama_reachable,
        "engine": "ollama" if ollama_reachable else "rule-based",
        "price_sources": ["live scrape", "baseline", "estimate"],
    }


@router.get("/baselines", response_model=list[BaselineOut])
async def list_baselines(
    session: AsyncSession = Depends(get_db),
    keyword: str | None = None,
    city: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> list[BaselineOut]:
    stmt = select(PriceBaseline).order_by(PriceBaseline.keyword, PriceBaseline.city)
    if keyword:
        stmt = stmt.where(PriceBaseline.keyword.ilike(f"%{keyword}%"))
    if city:
        stmt = stmt.where(PriceBaseline.city.ilike(f"%{city}%"))
    rows = (await session.execute(stmt.limit(limit).offset(offset))).scalars().all()
    return [
        BaselineOut(
            id=row.id,
            keyword=row.keyword,
            country=row.country,
            city=row.city,
            low_price=row.low_price,
            median_price=row.median_price,
            high_price=row.high_price,
            unit=row.unit,
            currency=row.currency,
            sources_json=list(row.sources_json or []),
            scraped_at=row.scraped_at,
        )
        for row in rows
    ]
