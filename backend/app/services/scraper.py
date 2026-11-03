"""Live market scraper (DuckDuckGo HTML only) + SQLite baseline lookup.

Only https://html.duckduckgo.com/html/ is ever fetched. No user-supplied
URL is fetched anywhere in v1. Any failure (timeout, 429, parse error)
returns an empty sample list so the caller falls back to the baseline
table; prices are never invented.
"""

from __future__ import annotations

import math
import re
import time
from dataclasses import dataclass, field
from urllib.parse import urlencode, urlparse

import httpx
from bs4 import BeautifulSoup
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..models.baseline import PriceBaseline

USER_AGENT = "BuyWithAI/1.0 (local market research; no contact)"
SEARCH_URL = "https://html.duckduckgo.com/html/"
MAX_CACHE_ENTRIES = 250

_PRICE_RE = re.compile(
    r"(PKR|Rs\.?|USD|\$)\s*([\d,]+(?:\.\d+)?)"
    r"|([\d,]+(?:\.\d+)?)\s*(PKR|Rs\.?|USD)",
    re.IGNORECASE,
)


def _currency_for_token(token: str | None) -> str:
    """Map a matched currency token to PKR / USD / unknown.

    ``$`` is treated as USD (the only dollar reading the scraper
    supports); ``Rs`` is treated as PKR. No conversion is ever done:
    the currency label only lets the caller drop mismatched samples.
    """
    if not token:
        return "unknown"
    cleaned = token.strip().lower().rstrip(".")
    if cleaned in ("pkr", "rs"):
        return "PKR"
    if cleaned in ("usd", "$"):
        return "USD"
    return "unknown"


def normalize_source_key(url: str, title: str) -> str:
    """Normalized identity of one listing for dedupe purposes.

    The host of the URL when one is present, otherwise the normalized
    title. Two samples with the same rounded price AND the same
    source key count once (see ``select_live_samples``).
    """
    try:
        host = (urlparse(url or "").hostname or "").lower()
    except Exception:
        host = ""
    if host:
        return host[4:] if host.startswith("www.") else host
    normalized = re.sub(r"[^a-z0-9]+", " ", (title or "").lower()).strip()
    return re.sub(r"\s+", " ", normalized)


def _percentile(sorted_values: list[float], fraction: float) -> float:
    if len(sorted_values) == 1:
        return sorted_values[0]
    pos = fraction * (len(sorted_values) - 1)
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return sorted_values[lo]
    return sorted_values[lo] * (hi - pos) + sorted_values[hi] * (pos - lo)


@dataclass
class LiveSampleSelection:
    """Result of filtering raw scrape samples for a live band.

    ``dropped_count`` is every raw sample that did not survive:
    currency mismatches, near-duplicate listings, and IQR outliers
    combined, so ``raw_count == len(usable_values) + dropped_count``.
    """

    usable_values: list[float] = field(default_factory=list)
    dropped_count: int = 0
    source_count: int = 0
    unknown_currency_count: int = 0
    raw_count: int = 0

    @property
    def usable_count(self) -> int:
        return len(self.usable_values)


def select_live_samples(
    results: list[dict], request_currency: str
) -> LiveSampleSelection:
    """Filter raw scrape results into usable live-band samples.

    Rules (documented choice): (a) samples whose detected currency
    does not match the request currency are dropped, never converted
    silently; samples with ``unknown`` currency are counted as
    usable — the query context gives no currency signal for them,
    and dropping them would discard most snippet prices — but the
    caller is told how many were unknown so it can note it; (b)
    near-duplicates — same rounded price AND same normalized source
    key — count once; (c) when >=5 usable samples survive dedupe,
    values outside Q1-1.5*IQR .. Q3+1.5*IQR are trimmed as outliers.
    """
    wanted = (request_currency or "").upper()
    candidates: list[tuple[float, str, str]] = []  # (value, source_key, currency)
    raw_count = 0
    dropped_currency = 0
    for result in results or []:
        entries = result.get("price_entries")
        if entries is None:
            # Fixtures / older callers that only carry `prices`.
            entries = [
                {"value": float(p), "currency": "unknown"}
                for p in result.get("prices", [])
            ]
        source_key = normalize_source_key(
            str(result.get("url") or ""), str(result.get("title") or "")
        )
        for entry in entries:
            try:
                value = float(entry["value"])  # type: ignore[index]
            except (KeyError, TypeError, ValueError):
                continue
            currency = str(entry.get("currency") or "unknown").upper()  # type: ignore[attr-defined]
            if currency not in ("PKR", "USD"):
                currency = "unknown"
            raw_count += 1
            if value <= 0:
                dropped_currency += 1
                continue
            if currency != "unknown" and currency != wanted:
                dropped_currency += 1
                continue
            candidates.append((value, source_key, currency))
    # Dedupe: same rounded price + same source key counts once.
    seen: set[tuple[float, str]] = set()
    deduped: list[tuple[float, str, str]] = []
    for value, source_key, currency in candidates:
        key = (round(value, 2), source_key)
        if key in seen:
            continue
        seen.add(key)
        deduped.append((value, source_key, currency))
    # Outlier trim (only with >=5 samples): 1.5xIQR rule.
    kept = deduped
    if len(deduped) >= 5:
        ordered = sorted(v for v, _k, _c in deduped)
        q1 = _percentile(ordered, 0.25)
        q3 = _percentile(ordered, 0.75)
        iqr = q3 - q1
        lower = q1 - 1.5 * iqr
        upper = q3 + 1.5 * iqr
        kept = [
            item for item in deduped if lower <= item[0] <= upper
        ]
    usable_values = sorted(v for v, _k, _c in kept)
    source_count = len({key for _v, key, _c in kept})
    unknown_count = sum(1 for _v, _k, c in kept if c == "unknown")
    return LiveSampleSelection(
        usable_values=usable_values,
        dropped_count=raw_count - len(kept),
        source_count=source_count,
        unknown_currency_count=unknown_count,
        raw_count=raw_count,
    )
_TOKEN_RE = re.compile(r"[a-z0-9]+")
_STOPWORDS = {
    "the", "a", "an", "in", "at", "for", "of", "to", "buy", "buying",
    "price", "prices", "per", "and", "or", "is", "are", "with", "near",
    "wholesale", "retail", "used", "new", "sale", "kg", "marla",
}


class AsyncScraperService:
    """Shared in-memory TTL cache (max 250 entries, class-level)."""

    _cache: dict[str, tuple[float, list[dict]]] = {}

    def __init__(self, ttl_seconds: float | None = None) -> None:
        settings = get_settings()
        self._ttl = ttl_seconds if ttl_seconds is not None else settings.CACHE_TTL_HOURS * 3600.0

    # -- live search ----------------------------------------------------
    async def search_market(
        self, query: str, location: str, max_results: int = 5
    ) -> list[dict]:
        cache_key = f"{query}|{location}|{max_results}".lower()
        now = time.monotonic()
        cached = self._cache.get(cache_key)
        if cached and now - cached[0] < self._ttl:
            return cached[1]
        results = await self._fetch_search(query, location, max_results)
        self._cache[cache_key] = (now, results)
        while len(self._cache) > MAX_CACHE_ENTRIES:
            self._cache.pop(next(iter(self._cache)))
        return results

    async def _fetch_search(
        self, query: str, location: str, max_results: int
    ) -> list[dict]:
        params = {"q": f"{query} price {location}"}
        url = f"{SEARCH_URL}?{urlencode(params)}"
        try:
            async with httpx.AsyncClient(
                trust_env=False,
                timeout=8.0,
                headers={"User-Agent": USER_AGENT},
                follow_redirects=True,
            ) as client:
                response = await client.get(url)
            if response.status_code in (429, 403) or response.status_code >= 400:
                return []
            return self._parse_results(response.text, max_results)
        except Exception:
            return []

    @staticmethod
    def _parse_results(html: str, max_results: int) -> list[dict]:
        soup = BeautifulSoup(html, "html.parser")
        results: list[dict] = []
        for block in soup.select("div.result")[:max_results]:
            link = block.select_one("a.result__a")
            snippet_el = block.select_one(".result__snippet")
            title = link.get_text(" ", strip=True) if link else ""
            href = link.get("href", "") if link else ""
            snippet = snippet_el.get_text(" ", strip=True) if snippet_el else ""
            prices: list[float] = []
            price_entries: list[dict] = []
            for match in _PRICE_RE.finditer(f"{title} {snippet}"):
                raw = match.group(2) or match.group(3)
                token = match.group(1) or match.group(4)
                try:
                    value = float(raw.replace(",", ""))
                except ValueError:
                    continue
                prices.append(value)
                price_entries.append(
                    {"value": value, "currency": _currency_for_token(token)}
                )
            results.append(
                {
                    "title": title,
                    "url": href,
                    "snippet": snippet,
                    "prices": prices,
                    # Additive: per-price currency metadata. `prices`
                    # above is unchanged; callers that ignore
                    # price_entries see exactly the old shape.
                    "price_entries": price_entries,
                    "source": "duckduckgo html",
                }
            )
        return results

    # -- baseline lookup --------------------------------------------------
    async def lookup_baseline(
        self,
        session: AsyncSession,
        description: str,
        city: str,
        country: str,
    ) -> PriceBaseline | None:
        rows = (await session.execute(select(PriceBaseline))).scalars().all()
        if not rows:
            return None
        text = description.lower()
        tokens = {t for t in _TOKEN_RE.findall(text) if t not in _STOPWORDS}

        def score(row: PriceBaseline) -> tuple[float, float]:
            keyword = row.keyword.lower().strip()
            points = 0.0
            if keyword and keyword in text:
                points += 10.0 + len(keyword)
            keyword_tokens = set(_TOKEN_RE.findall(keyword))
            overlap = keyword_tokens & tokens
            points += 3.0 * len(overlap)
            if keyword_tokens and overlap == keyword_tokens:
                points += 5.0
            if row.city.lower() == city.lower():
                points += 5.0
            elif row.country.lower() == country.lower():
                points += 2.0
            return points, len(keyword)

        scored = [(score(row), row) for row in rows]
        scored.sort(key=lambda item: (item[0][0], item[0][1]), reverse=True)
        best_score, best_row = scored[0]
        if best_score[0] <= 0:
            return None
        # Require at least a keyword/token hit, not only a city match.
        keyword = best_row.keyword.lower().strip()
        keyword_tokens = set(_TOKEN_RE.findall(keyword))
        if keyword not in text and not (keyword_tokens & tokens):
            return None
        return best_row
