"""FastAPI application entry point: lifespan, CORS, RFC 7807 errors."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from .config import get_settings
from .database import init_db
from .routers import analyze, chat, checks, health, images, integrations, journal, share, tools, watchlist

settings = get_settings()


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    await init_db()
    yield


app = FastAPI(
    title=settings.APP_NAME,
    version=settings.APP_VERSION,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _problem(
    status: int, title: str, detail: Any, instance: str,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content={
            "type": "about:blank",
            "title": title,
            "status": status,
            "detail": detail,
            "instance": instance,
        },
        media_type="application/problem+json",
        headers=headers,
    )


@app.exception_handler(RequestValidationError)
async def validation_error_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    # Never echo raw input values: strip 'input' and 'ctx' (which can
    # carry the submitted value / interpolation values) from every
    # Pydantic error, keeping only the field location, message and
    # error type. No logging module is configured, so nothing is
    # logged either.
    sanitized = [
        {
            "loc": list(err.get("loc", ())),
            "msg": err.get("msg", ""),
            "type": err.get("type", ""),
        }
        for err in exc.errors()
    ]
    return _problem(
        422, "Validation Error", sanitized, str(request.url.path)
    )


@app.exception_handler(HTTPException)
async def http_error_handler(request: Request, exc: HTTPException) -> JSONResponse:
    # Preserve headers such as Retry-After on 429s; the RFC 7807
    # body conversion must not drop them.
    return _problem(
        exc.status_code,
        "HTTP Error",
        str(exc.detail),
        str(request.url.path),
        headers=dict(exc.headers) if exc.headers else None,
    )


@app.exception_handler(Exception)
async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    # Generic detail only: never str(exc) — an unhandled exception's
    # message can contain tracebacks, filesystem paths, or internal
    # values. The exception itself is intentionally not logged (no
    # logging is configured in this app) and not returned.
    return _problem(
        500, "Internal Server Error", "Internal Server Error",
        str(request.url.path),
    )


app.include_router(analyze.router, prefix="/api/v1")
app.include_router(checks.router, prefix="/api/v1")
app.include_router(journal.router, prefix="/api/v1")
app.include_router(tools.router, prefix="/api/v1")
app.include_router(health.router, prefix="/api/v1")
app.include_router(integrations.router, prefix="/api/v1")
app.include_router(watchlist.router, prefix="/api/v1")
app.include_router(share.router, prefix="/api/v1")
app.include_router(chat.router, prefix="/api/v1")
app.include_router(images.router, prefix="/api/v1")


@app.get("/")
async def root() -> dict:
    return {"app": settings.APP_NAME, "version": settings.APP_VERSION}
