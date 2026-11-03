"""Shared schema pieces: location, currency, sentence counting."""

from __future__ import annotations

import re
from enum import Enum

from pydantic import BaseModel, Field


class CurrencyEnum(str, Enum):
    PKR = "PKR"
    USD = "USD"
    INR = "INR"
    GBP = "GBP"
    EUR = "EUR"
    AED = "AED"


class Location(BaseModel):
    country: str = Field(default="Pakistan", max_length=64)
    province: str = Field(default="Punjab", max_length=64)
    city: str = Field(default="Bahawalpur", max_length=64)

    def display(self) -> str:
        return f"{self.city}, {self.province}, {self.country}"


_DECIMAL_RE = re.compile(r"\d\.\d")


def count_sentences(text: str) -> int:
    """Count sentences, ignoring decimal points inside numbers (e.g. 82.50)."""
    cleaned = _DECIMAL_RE.sub("00", text.strip())
    parts = [p.strip() for p in re.split(r"[.!?]+(?:\s+|$)", cleaned) if p.strip()]
    return len(parts)


def split_sentences(text: str) -> list[str]:
    cleaned = text.strip()
    parts = [
        p.strip()
        for p in re.split(r"(?<=[.!?])\s+", cleaned)
        if p.strip()
    ]
    return parts
