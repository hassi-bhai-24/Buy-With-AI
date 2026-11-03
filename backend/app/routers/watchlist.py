"""Watchlist: save a check with a target price and re-check it later.

The target price is compared against the expected per-unit price from a
fresh baseline lookup (the same per-unit scale as the check's stored
price band). No price is ever invented: when no fresh baseline exists,
the recheck returns the saved check's own band and a null current price.
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..rate_limit import rate_limit
from ..models.check import Check
from ..models.watchlist import WatchlistItem
from ..services.scraper import AsyncScraperService

router = APIRouter()

_NO_BASELINE_NOTE = (
    "No fresh baseline data — showing the saved check price band only"
)


class WatchlistCreate(BaseModel):
    check_id: str = Field(min_length=1, max_length=36)
    target_price: float = Field(gt=0)


class WatchlistOut(BaseModel):
    id: str
    check_id: str
    title: str
    target_price: float
    currency: str
    created_at: datetime
    updated_at: datetime


def _out(item: WatchlistItem, title: str) -> WatchlistOut:
    return WatchlistOut(
        id=item.id,
        check_id=item.check_id,
        title=title,
        target_price=item.target_price,
        currency=item.currency,
        created_at=item.created_at,
        updated_at=item.updated_at,
    )


def _split_location(location_str: str) -> tuple[str, str]:
    """'City, Province, Country' -> (city, country); defaults when empty."""
    parts = [part.strip() for part in (location_str or "").split(",") if part.strip()]
    if not parts:
        return "Bahawalpur", "Pakistan"
    city = parts[0]
    country = parts[-1] if len(parts) >= 2 else "Pakistan"
    return city, country


@router.post("/watchlist", response_model=WatchlistOut, status_code=201)
async def create_watchlist_item(
    payload: WatchlistCreate,
    session: AsyncSession = Depends(get_db),
    _limited: None = Depends(rate_limit),
) -> WatchlistOut:
    check = await session.get(Check, payload.check_id)
    if check is None:
        raise HTTPException(status_code=404, detail="Check not found.")
    item = WatchlistItem(
        user_id=check.user_id,
        check_id=check.id,
        target_price=payload.target_price,
        currency=check.currency,
    )
    session.add(item)
    await session.commit()
    await session.refresh(item)
    return _out(item, check.item_title)


@router.get("/watchlist", response_model=list[WatchlistOut])
async def list_watchlist_items(
    session: AsyncSession = Depends(get_db),
) -> list[WatchlistOut]:
    rows = (
        await session.execute(
            select(WatchlistItem, Check)
            .join(Check, Check.id == WatchlistItem.check_id)
            .order_by(WatchlistItem.created_at.desc())
        )
    ).all()
    return [_out(item, check.item_title) for item, check in rows]


@router.delete("/watchlist/{item_id}")
async def delete_watchlist_item(
    item_id: str, session: AsyncSession = Depends(get_db)
) -> dict:
    row = await session.get(WatchlistItem, item_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Watchlist item not found.")
    await session.execute(
        delete(WatchlistItem).where(WatchlistItem.id == item_id)
    )
    await session.commit()
    return {"deleted": item_id}


@router.post("/watchlist/{item_id}/recheck")
async def recheck_watchlist_item(
    item_id: str,
    session: AsyncSession = Depends(get_db),
    _limited: None = Depends(rate_limit),
) -> dict:
    item = await session.get(WatchlistItem, item_id)
    if item is None:
        raise HTTPException(status_code=404, detail="Watchlist item not found.")
    check = await session.get(Check, item.check_id)
    if check is None:
        raise HTTPException(status_code=404, detail="Check not found.")
    city, country = _split_location(check.location_str)
    baseline = None
    try:
        baseline = await AsyncScraperService().lookup_baseline(
            session, check.item_title, city, country
        )
    except Exception:
        baseline = None

    saved_band = None
    if (
        check.price_min is not None
        and check.price_expected is not None
        and check.price_max is not None
    ):
        saved_band = {
            "min": check.price_min,
            "expected": check.price_expected,
            "max": check.price_max,
        }

    if baseline is not None:
        band = {
            "min": baseline.low_price,
            "expected": baseline.median_price,
            "max": baseline.high_price,
        }
        return {
            "id": item.id,
            "check_id": check.id,
            "current_expected_price": baseline.median_price,
            "target_price": item.target_price,
            "target_met": baseline.median_price <= item.target_price,
            "price_source": "baseline",
            "band": band,
            "currency": item.currency,
            "note": (
                f"Fresh baseline for '{baseline.keyword}' in {baseline.city}: "
                f"expected {baseline.median_price:,.0f} {baseline.currency} "
                f"per {baseline.unit} (baseline, not a live price)."
            ),
        }
    return {
        "id": item.id,
        "check_id": check.id,
        "current_expected_price": None,
        "target_price": item.target_price,
        "target_met": False,
        "price_source": "none",
        "band": saved_band,
        "currency": item.currency,
        "note": _NO_BASELINE_NOTE,
    }
