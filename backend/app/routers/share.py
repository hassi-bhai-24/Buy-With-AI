"""Sharing: plain-text / markdown summaries of a persisted check.

The share URL is a relative path only (``/check/{id}``) — no public host
is invented. Both the share payload and the downloadable summary carry
the same content and the same disclaimer.
"""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import PlainTextResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..models.check import Check
from ..services.rules import money_str

router = APIRouter()

DISCLAIMER = "General guidance, not financial advice. Verify before paying."


def _band_line(check: Check) -> str | None:
    if (
        check.price_min is None
        or check.price_expected is None
        or check.price_max is None
    ):
        return None
    unit = check.unit_of_measure or "unit"
    return (
        f"Price band: {money_str(check.price_min, check.currency)} to "
        f"{money_str(check.price_max, check.currency)} per {unit} "
        f"(expected {money_str(check.price_expected, check.currency)})."
    )


def build_summary_text(check: Check) -> str:
    lines = [
        f"Buy with AI check: {check.item_title}",
        f"Verdict: {check.verdict_tier} (confidence {check.confidence_score})",
        check.plain_truth,
    ]
    band = _band_line(check)
    if band is not None:
        lines.append(band)
    flags = list(check.red_flags_json or [])
    if flags:
        lines.append(f"Top concern: {flags[0]}")
    lines.append(DISCLAIMER)
    return "\n".join(lines)


def build_summary_markdown(check: Check) -> str:
    lines = [
        f"# {check.item_title}",
        "",
        f"**Verdict:** {check.verdict_tier} (confidence {check.confidence_score})",
        "",
        check.plain_truth,
        "",
    ]
    band = _band_line(check)
    if band is not None:
        lines.extend([f"**{band}**", ""])
    flags = list(check.red_flags_json or [])
    if flags:
        lines.extend([f"**Top concern:** {flags[0]}", ""])
    lines.append(f"_{DISCLAIMER}_")
    return "\n".join(lines)


async def _get_check(check_id: str, session: AsyncSession) -> Check:
    row = await session.get(Check, check_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Check not found.")
    return row


@router.get("/checks/{check_id}/share")
async def share_check(
    check_id: str, session: AsyncSession = Depends(get_db)
) -> dict:
    check = await _get_check(check_id, session)
    return {
        "text": build_summary_text(check),
        "url": f"/check/{check_id}",
    }


@router.get("/checks/{check_id}/summary")
async def download_summary(
    check_id: str,
    session: AsyncSession = Depends(get_db),
    format: Literal["txt", "md"] = Query(default="txt"),
) -> Response:
    """Downloadable summary; any other ``format`` value is a 422."""
    check = await _get_check(check_id, session)
    if format == "md":
        content = build_summary_markdown(check)
        return Response(
            content=content,
            media_type="text/markdown",
            headers={
                "Content-Disposition": f'attachment; filename="check-{check.id}.md"'
            },
        )
    content = build_summary_text(check)
    return PlainTextResponse(
        content=content,
        headers={
            "Content-Disposition": f'attachment; filename="check-{check.id}.txt"'
        },
    )
