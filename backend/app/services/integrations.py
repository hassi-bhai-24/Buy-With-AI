"""Server-side free-service integrations: Nominatim, Open Food Facts, Frankfurter.

Allow-listed hosts ONLY — no user-supplied URL is ever fetched. Every
call uses httpx with a <= 8s timeout, an identifying User-Agent, an
in-memory TTL cache, and graceful failure: upstream failures raise
``UpstreamError`` (callers map it to HTTP 502) and no invented or
expired-cache data is ever returned. No API keys are used.
"""

from __future__ import annotations

import asyncio
import time
from typing import Any

import httpx

USER_AGENT = "BuyWithAI/1.0 (local market research; contact: none)"
_TIMEOUT_SECONDS = 8.0

_NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
_NOMINATIM_TTL_SECONDS = 24 * 3600.0
_NOMINATIM_MIN_INTERVAL_SECONDS = 1.0

_OFF_URL_TEMPLATE = "https://world.openfoodfacts.org/api/v2/product/{barcode}.json"

_FRANKFURTER_URL = "https://api.frankfurter.app/latest"
_FRANKFURTER_TTL_SECONDS = 3600.0


class UpstreamError(Exception):
    """The upstream service failed or returned unusable data."""


class GeocodeNotFound(Exception):
    """Nominatim returned no result for the query."""


# -- in-memory TTL caches: key -> (expires_at_monotonic, value) -----------
_geocode_cache: dict[str, tuple[float, dict[str, Any]]] = {}
_rates_cache: dict[tuple[str, str], tuple[float, tuple[float, str]]] = {}
_nominatim_lock = asyncio.Lock()
_nominatim_last_call: float = 0.0


def clear_integration_caches() -> None:
    """Reset caches and the Nominatim throttle (used by tests)."""
    global _nominatim_last_call
    _geocode_cache.clear()
    _rates_cache.clear()
    _nominatim_last_call = 0.0


def _cache_get(
    cache: dict, key: Any, now: float
) -> Any | None:
    entry = cache.get(key)
    if entry is not None and now < entry[0]:
        return entry[1]
    if entry is not None:
        del cache[key]
    return None


# ---------------------------------------------------------------------------
# Nominatim geocoding
# ---------------------------------------------------------------------------


async def geocode_place(query: str) -> dict[str, Any]:
    """Geocode a place name via Nominatim (first result only).

    Returns ``{lat, lon, display_name, source}``. Raises
    ``GeocodeNotFound`` when Nominatim returns no result and
    ``UpstreamError`` when the service fails. Results are cached for
    24h keyed by the lowercased query; at most one upstream request
    per second is made (Nominatim usage policy).
    """
    cleaned = query.strip()
    if not cleaned:
        raise ValueError("geocode query must not be empty")
    cache_key = cleaned.lower()
    now = time.monotonic()
    cached = _cache_get(_geocode_cache, cache_key, now)
    if cached is not None:
        return dict(cached)

    global _nominatim_last_call
    async with _nominatim_lock:
        now = time.monotonic()
        wait = _NOMINATIM_MIN_INTERVAL_SECONDS - (now - _nominatim_last_call)
        if wait > 0:
            await asyncio.sleep(wait)
        _nominatim_last_call = time.monotonic()
        try:
            async with httpx.AsyncClient(
                trust_env=False,
                timeout=_TIMEOUT_SECONDS,
                headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
                follow_redirects=True,
            ) as client:
                response = await client.get(
                    _NOMINATIM_URL,
                    params={"q": cleaned, "format": "json", "limit": 1},
                )
        except Exception as exc:
            raise UpstreamError(
                f"Geocoding service unavailable: {exc.__class__.__name__}"
            ) from exc
    if response.status_code != 200:
        raise UpstreamError(
            f"Geocoding service returned HTTP {response.status_code}."
        )
    try:
        results = response.json()
    except Exception as exc:
        raise UpstreamError("Geocoding service returned invalid data.") from exc
    if not isinstance(results, list) or not results:
        raise GeocodeNotFound(f"No result found for '{cleaned}'.")
    first = results[0]
    try:
        result = {
            "lat": float(first["lat"]),
            "lon": float(first["lon"]),
            "display_name": str(first["display_name"]),
            "source": "nominatim",
        }
    except (KeyError, TypeError, ValueError) as exc:
        raise UpstreamError("Geocoding service returned invalid data.") from exc
    _geocode_cache[cache_key] = (
        time.monotonic() + _NOMINATIM_TTL_SECONDS,
        dict(result),
    )
    return result


# ---------------------------------------------------------------------------
# Open Food Facts barcode lookup
# ---------------------------------------------------------------------------


def barcode_check_digit(body: str) -> int:
    """EAN check digit for the digits before the check digit.

    Alternating weights 3/1 from the right, excluding the check digit;
    the same rule covers EAN-8 and EAN-13.
    """
    total = 0
    weight = 3
    for digit in reversed(body):
        total += int(digit) * weight
        weight = 1 if weight == 3 else 3
    return (10 - (total % 10)) % 10


def is_valid_barcode(barcode: str) -> bool:
    """True only for digit-only EAN-8/EAN-13 strings with a valid check digit."""
    cleaned = barcode.strip()
    if len(cleaned) not in (8, 13) or not cleaned.isdigit():
        return False
    return barcode_check_digit(cleaned[:-1]) == int(cleaned[-1])


async def fetch_product_by_barcode(barcode: str) -> dict[str, Any]:
    """Look a barcode up in Open Food Facts.

    Returns ``{found, barcode, product_name, ingredients, nutriscore,
    source}`` with ``found=False`` (HTTP 200 at the router) when OFF
    reports no such product. Raises ``ValueError`` for an invalid
    barcode and ``UpstreamError`` when OFF fails. No product data is
    ever invented.
    """
    cleaned = barcode.strip()
    if not is_valid_barcode(cleaned):
        raise ValueError(
            "Invalid barcode: must be an 8- or 13-digit EAN with a valid check digit."
        )
    url = _OFF_URL_TEMPLATE.format(barcode=cleaned)
    try:
        async with httpx.AsyncClient(
            trust_env=False,
            timeout=_TIMEOUT_SECONDS,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            follow_redirects=True,
        ) as client:
            response = await client.get(url)
    except Exception as exc:
        raise UpstreamError(
            f"Open Food Facts unavailable: {exc.__class__.__name__}"
        ) from exc
    if response.status_code != 200:
        raise UpstreamError(
            f"Open Food Facts returned HTTP {response.status_code}."
        )
    try:
        data = response.json()
    except Exception as exc:
        raise UpstreamError("Open Food Facts returned invalid data.") from exc
    if not isinstance(data, dict):
        raise UpstreamError("Open Food Facts returned invalid data.")
    product = data.get("product")
    if data.get("status") in (0, "0") or not isinstance(product, dict):
        return {
            "found": False,
            "barcode": cleaned,
            "product_name": None,
            "ingredients": None,
            "nutriscore": None,
            "source": "openfoodfacts",
        }
    product_name = product.get("product_name") or product.get("product_name_en")
    ingredients = product.get("ingredients_text")
    nutriscore = product.get("nutriscore_grade")
    return {
        "found": True,
        "barcode": cleaned,
        "product_name": str(product_name) if product_name else None,
        "ingredients": str(ingredients) if ingredients else None,
        "nutriscore": str(nutriscore) if nutriscore else None,
        "source": "openfoodfacts",
    }


# ---------------------------------------------------------------------------
# Frankfurter exchange rates (backs TOOL-5)
# ---------------------------------------------------------------------------


async def _fetch_frankfurter_rate(
    from_currency: str, to_currency: str
) -> tuple[float, str]:
    """Fetch the unit rate (amount=1) for one currency pair."""
    try:
        async with httpx.AsyncClient(
            trust_env=False,
            timeout=_TIMEOUT_SECONDS,
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            follow_redirects=True,
        ) as client:
            response = await client.get(
                _FRANKFURTER_URL,
                params={
                    "amount": 1,
                    "from": from_currency,
                    "to": to_currency,
                },
            )
    except Exception as exc:
        raise UpstreamError(
            f"Currency service unavailable: {exc.__class__.__name__}"
        ) from exc
    if response.status_code != 200:
        raise UpstreamError(
            f"Currency service returned HTTP {response.status_code}."
        )
    try:
        data = response.json()
    except Exception as exc:
        raise UpstreamError("Currency service returned invalid data.") from exc
    rates = data.get("rates") if isinstance(data, dict) else None
    if not isinstance(rates, dict) or to_currency not in rates:
        raise UpstreamError(
            f"Currency service did not return a rate for {to_currency}."
        )
    try:
        rate = float(rates[to_currency])
    except (TypeError, ValueError) as exc:
        raise UpstreamError("Currency service returned an invalid rate.") from exc
    rate_date = str(data.get("date") or "")
    return rate, rate_date


async def convert_currency(
    amount: float, from_currency: str, to_currency: str
) -> dict[str, Any]:
    """Convert an amount using a live Frankfurter rate.

    Same-currency conversions are identity (rate 1, source "identity")
    with no upstream call. Otherwise the per-pair rate is cached for
    1h; on upstream failure with no fresh cached rate, ``UpstreamError``
    is raised — an expired or absent rate is never returned as if live.
    """
    from_currency = from_currency.strip().upper()
    to_currency = to_currency.strip().upper()
    if from_currency == to_currency:
        return {
            "amount": amount,
            "from_currency": from_currency,
            "to_currency": to_currency,
            "converted_amount": amount,
            "rate": 1.0,
            "rate_date": None,
            "source": "identity",
        }
    cache_key = (from_currency, to_currency)
    now = time.monotonic()
    cached = _cache_get(_rates_cache, cache_key, now)
    if cached is not None:
        rate, rate_date = cached
    else:
        rate, rate_date = await _fetch_frankfurter_rate(from_currency, to_currency)
        _rates_cache[cache_key] = (
            now + _FRANKFURTER_TTL_SECONDS,
            (rate, rate_date),
        )
    return {
        "amount": amount,
        "from_currency": from_currency,
        "to_currency": to_currency,
        "converted_amount": round(amount * rate, 2),
        "rate": rate,
        "rate_date": rate_date,
        "source": "frankfurter",
    }
