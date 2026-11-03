"""Geo + barcode endpoints backed by Nominatim and Open Food Facts.

The coordinator wires this router into main.py under /api/v1. Hosts are
allow-listed in services/integrations.py; no user-supplied URL is fetched.
"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from ..services import integrations

router = APIRouter()


class GeocodeOut(BaseModel):
    lat: float
    lon: float
    display_name: str
    source: str


@router.get("/geo/geocode", response_model=GeocodeOut)
async def geocode(q: str = Query(min_length=1, max_length=200)) -> GeocodeOut:
    try:
        result = await integrations.geocode_place(q)
    except integrations.GeocodeNotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except integrations.UpstreamError as exc:
        raise HTTPException(
            status_code=502, detail=f"Geocoding service unavailable: {exc}"
        ) from exc
    return GeocodeOut(**result)


class BarcodeOut(BaseModel):
    found: bool
    barcode: str
    product_name: str | None
    ingredients: str | None
    nutriscore: str | None
    source: str


@router.get("/barcode/{barcode}", response_model=BarcodeOut)
async def barcode_lookup(barcode: str) -> BarcodeOut:
    if not integrations.is_valid_barcode(barcode):
        raise HTTPException(
            status_code=422,
            detail="Invalid barcode: must be an 8- or 13-digit EAN with a valid check digit.",
        )
    try:
        result = await integrations.fetch_product_by_barcode(barcode)
    except integrations.UpstreamError as exc:
        raise HTTPException(
            status_code=502, detail=f"Open Food Facts unavailable: {exc}"
        ) from exc
    return BarcodeOut(**result)
