"""Deal journal: log outcomes and cumulative savings stats."""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models.check import Check
from ..models.journal import DealJournal
from ..schemas.request import JournalCreateRequest

router = APIRouter()

_DEAL_STATUSES = {"Purchased", "Walked Away", "In Negotiation"}


class JournalOut(BaseModel):
    id: str
    check_id: str
    user_id: str
    original_asking_price: float
    final_negotiated_price: float
    net_savings_amount: float
    deal_status: str
    outcome_notes: str | None
    closed_at: datetime
    created_at: datetime


@router.post("/journal", response_model=JournalOut, status_code=201)
async def create_journal_entry(
    payload: JournalCreateRequest, session: AsyncSession = Depends(get_db)
) -> JournalOut:
    if payload.deal_status not in _DEAL_STATUSES:
        raise HTTPException(
            status_code=422, detail=f"deal_status must be one of {sorted(_DEAL_STATUSES)}."
        )
    check = await session.get(Check, payload.check_id)
    if check is None:
        raise HTTPException(status_code=404, detail="Check not found.")
    asking = (
        payload.original_asking_price
        if payload.original_asking_price is not None
        else (check.asking_price or payload.final_negotiated_price)
    )
    entry = DealJournal(
        check_id=check.id,
        user_id=check.user_id,
        original_asking_price=asking,
        final_negotiated_price=payload.final_negotiated_price,
        net_savings_amount=asking - payload.final_negotiated_price,
        deal_status=payload.deal_status,
        outcome_notes=payload.outcome_notes,
    )
    session.add(entry)
    await session.commit()
    await session.refresh(entry)
    return JournalOut(
        id=entry.id,
        check_id=entry.check_id,
        user_id=entry.user_id,
        original_asking_price=entry.original_asking_price,
        final_negotiated_price=entry.final_negotiated_price,
        net_savings_amount=entry.net_savings_amount,
        deal_status=entry.deal_status,
        outcome_notes=entry.outcome_notes,
        closed_at=entry.closed_at,
        created_at=entry.created_at,
    )


@router.get("/journal", response_model=list[JournalOut])
async def list_journal(
    session: AsyncSession = Depends(get_db),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> list[JournalOut]:
    rows = (
        await session.execute(
            select(DealJournal)
            .order_by(DealJournal.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
    ).scalars().all()
    return [
        JournalOut(
            id=row.id,
            check_id=row.check_id,
            user_id=row.user_id,
            original_asking_price=row.original_asking_price,
            final_negotiated_price=row.final_negotiated_price,
            net_savings_amount=row.net_savings_amount,
            deal_status=row.deal_status,
            outcome_notes=row.outcome_notes,
            closed_at=row.closed_at,
            created_at=row.created_at,
        )
        for row in rows
    ]


@router.get("/journal/stats")
async def journal_stats(session: AsyncSession = Depends(get_db)) -> dict:
    total_savings = await session.scalar(
        select(func.coalesce(func.sum(DealJournal.net_savings_amount), 0.0))
    )
    total_deals = await session.scalar(select(func.count(DealJournal.id))) or 0
    purchased = (
        await session.scalar(
            select(func.count(DealJournal.id)).where(
                DealJournal.deal_status == "Purchased"
            )
        )
        or 0
    )
    walked_away = (
        await session.scalar(
            select(func.count(DealJournal.id)).where(
                DealJournal.deal_status == "Walked Away"
            )
        )
        or 0
    )
    return {
        "total_savings": float(total_savings),
        "total_deals": int(total_deals),
        "purchased_count": int(purchased),
        "walked_away_count": int(walked_away),
        "average_savings": float(total_savings) / int(total_deals) if total_deals else 0.0,
    }
