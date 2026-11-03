"""Price baseline cache: scraped/seeded market rates by keyword + place."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Float, String
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class PriceBaseline(Base):
    __tablename__ = "price_baselines"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    keyword: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    country: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    city: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    low_price: Mapped[float] = mapped_column(Float, nullable=False)
    median_price: Mapped[float] = mapped_column(Float, nullable=False)
    high_price: Mapped[float] = mapped_column(Float, nullable=False)
    unit: Mapped[str] = mapped_column(String(32), nullable=False)
    currency: Mapped[str] = mapped_column(String(10), default="PKR", nullable=False)
    sources_json: Mapped[list[dict[str, Any]]] = mapped_column(
        JSON, default=list, nullable=False
    )
    scraped_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, index=True, nullable=False
    )

    @property
    def scraped_sources_json(self) -> list[dict[str, Any]]:
        """Alias matching the schema document's field name."""
        return self.sources_json
