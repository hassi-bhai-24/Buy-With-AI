"""Analyze endpoints: synchronous verdict + SSE progress stream.

Rate limiting (30/min per IP, token bucket, see ``app.rate_limit``)
applies to both POST /api/v1/analyze and POST /api/v1/analyze/stream
(the stream limit is consumed once, at stream start).
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from ..database import get_db
from ..rate_limit import rate_limit, reset_rate_limits
from ..schemas.request import AnalyzeRequest
from ..schemas.response import VerdictResponse
from ..services.analyzer import AnalysisOrchestrator

router = APIRouter()

# Re-exported for existing tests: ``from app.routers.analyze import
# reset_rate_limits`` keeps working; the buckets live in app.rate_limit.
__all__ = ["router", "reset_rate_limits", "rate_limit"]

# Back-compat alias for the previous private name.
_rate_limit = rate_limit


@router.post("/analyze", response_model=VerdictResponse)
async def analyze(
    payload: AnalyzeRequest,
    request: Request,
    session: AsyncSession = Depends(get_db),
    _limited: None = Depends(rate_limit),
) -> VerdictResponse:
    orchestrator = AnalysisOrchestrator(session)
    return await orchestrator.analyze(payload)


@router.post("/analyze/stream")
async def analyze_stream(
    payload: AnalyzeRequest,
    session: AsyncSession = Depends(get_db),
    _limited: None = Depends(rate_limit),
) -> StreamingResponse:
    """SSE stream driven by real analysis stages.

    Step events (1-4) are yielded as the orchestrator reports each stage
    boundary; the final event (step 5) carries the full verdict. The
    check is persisted exactly once, by the same ``analyze()`` call the
    synchronous endpoint uses. On failure mid-stream a single
    ``{"error": ...}`` event is yielded; no traceback is leaked.
    """

    async def event_stream() -> AsyncIterator[str]:
        def event(data: dict) -> str:
            return f"data: {json.dumps(data, default=str)}\n\n"

        queue: asyncio.Queue[tuple[str, object]] = asyncio.Queue()

        async def on_progress(step: int, status: str) -> None:
            queue.put_nowait(("step", {"step": step, "status": status}))

        orchestrator = AnalysisOrchestrator(session)

        async def _run() -> None:
            try:
                verdict = await orchestrator.analyze(
                    payload, on_progress=on_progress
                )
                queue.put_nowait(("verdict", verdict))
            except Exception:
                queue.put_nowait(("error", None))

        task = asyncio.create_task(_run())
        try:
            while True:
                kind, value = await queue.get()
                if kind == "step":
                    yield event(value)  # type: ignore[arg-type]
                elif kind == "verdict":
                    verdict = value  # type: ignore[assignment]
                    yield event(
                        {"step": 5, "verdict": verdict.model_dump(mode="json")}
                    )
                    break
                else:
                    yield event(
                        {"error": "Analysis failed. Please try again."}
                    )
                    break
        finally:
            await task

    return StreamingResponse(event_stream(), media_type="text/event-stream")
