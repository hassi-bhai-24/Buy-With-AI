"""Check history: list (pagination + category filter), get, delete, pin.

GET /api/v1/checks returns ONLY ``{items, total}``; ``total`` is the
filtered total from a separate SELECT COUNT(*) honouring the category
filter, not the page length.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models.chat import ChatMessage, ChatThread
from ..models.check import Check
from ..models.journal import DealJournal
from ..models.project import project_items
from ..models.watchlist import WatchlistItem
from ..schemas.response import CategoryEnum, ChecksListResponse, VerdictResponse
from ..services.analyzer import check_to_response

router = APIRouter()


@router.get("/checks", response_model=ChecksListResponse)
async def list_checks(
    session: AsyncSession = Depends(get_db),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    category: CategoryEnum | None = None,
) -> ChecksListResponse:
    where = []
    if category is not None:
        where.append(Check.category == category.value)
    count_stmt = select(func.count()).select_from(Check)
    if where:
        count_stmt = count_stmt.where(*where)
    total = (await session.execute(count_stmt)).scalar_one()
    stmt = (
        select(Check)
        .order_by(Check.is_pinned.desc(), Check.created_at.desc())
        .limit(limit)
        .offset(offset)
    )
    if where:
        stmt = stmt.where(*where)
    rows = (await session.execute(stmt)).scalars().all()
    return ChecksListResponse(
        items=[check_to_response(row) for row in rows],
        total=int(total),
    )


@router.get("/checks/{check_id}", response_model=VerdictResponse)
async def get_check(
    check_id: str, session: AsyncSession = Depends(get_db)
) -> VerdictResponse:
    row = await session.get(Check, check_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Check not found.")
    return check_to_response(row)


@router.delete("/checks/{check_id}")
async def delete_check(
    check_id: str, session: AsyncSession = Depends(get_db)
) -> dict:
    row = await session.get(Check, check_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Check not found.")
    # Explicit cleanup of every dependent row, instead of a bulk
    # DELETE that bypasses ORM cascades (and would orphan rows on any
    # connection where SQLite foreign-key enforcement is off, despite
    # the ondelete="CASCADE" declarations). Chat messages are deleted
    # before their threads; journal, watchlist and project-association
    # rows reference the check directly. The ORM delete below also
    # honours Check.journal_entry's delete-orphan cascade, so the
    # explicit journal delete is idempotent belt-and-braces.
    thread_ids = (
        await session.execute(
            select(ChatThread.id).where(ChatThread.check_id == check_id)
        )
    ).scalars().all()
    if thread_ids:
        await session.execute(
            delete(ChatMessage).where(ChatMessage.thread_id.in_(thread_ids))
        )
    await session.execute(
        delete(ChatThread).where(ChatThread.check_id == check_id)
    )
    await session.execute(
        delete(DealJournal).where(DealJournal.check_id == check_id)
    )
    await session.execute(
        delete(WatchlistItem).where(WatchlistItem.check_id == check_id)
    )
    await session.execute(
        delete(project_items).where(project_items.c.check_id == check_id)
    )
    await session.delete(row)
    await session.commit()
    # Physical-deletion standard: reclaim freed pages where possible.
    try:
        conn = await session.connection()
        await conn.exec_driver_sql("PRAGMA incremental_vacuum;")
    except Exception:
        pass
    return {"deleted": check_id}


@router.post("/checks/{check_id}/pin", response_model=VerdictResponse)
async def toggle_pin(
    check_id: str, session: AsyncSession = Depends(get_db)
) -> VerdictResponse:
    row = await session.get(Check, check_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Check not found.")
    row.is_pinned = not row.is_pinned
    await session.commit()
    await session.refresh(row)
    return check_to_response(row)
