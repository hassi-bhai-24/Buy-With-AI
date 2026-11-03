"""Check model: one persisted verdict per analysis (unless private mode)."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Optional

from sqlalchemy import JSON, Boolean, Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin

if TYPE_CHECKING:
    from .journal import DealJournal
    from .project import Project
    from .user import User


class Check(Base, TimestampMixin):
    __tablename__ = "checks"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"),
        index=True, nullable=False,
    )
    query_raw: Mapped[str] = mapped_column(Text, nullable=False)
    item_title: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str] = mapped_column(String(64), index=True, nullable=False)
    verdict_tier: Mapped[str] = mapped_column(String(32), index=True, nullable=False)
    plain_truth: Mapped[str] = mapped_column(Text, nullable=False)
    confidence_score: Mapped[str] = mapped_column(String(16), nullable=False)
    price_min: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    price_expected: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    price_max: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    currency: Mapped[str] = mapped_column(String(10), default="PKR", nullable=False)
    unit_of_measure: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    asking_price: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    quantity: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    location_str: Mapped[str] = mapped_column(String(255), default="", nullable=False)
    estimated_bom_cost: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    brand_markup_percent: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    cash_flow_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    red_flags_json: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    verify_checklist_json: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    counter_offers_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    sources_cited_json: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    engine: Mapped[str] = mapped_column(String(32), default="rule-based", nullable=False)
    price_source: Mapped[str] = mapped_column(
        String(32), default="baseline", nullable=False
    )
    spoilage_json: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    next_steps_json: Mapped[list] = mapped_column(JSON, default=list, nullable=False)
    is_pinned: Mapped[bool] = mapped_column(
        Boolean, default=False, index=True, nullable=False
    )
    is_private_check: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )

    user: Mapped["User"] = relationship("User", back_populates="checks")
    journal_entry: Mapped[Optional["DealJournal"]] = relationship(
        "DealJournal", back_populates="check", uselist=False,
        cascade="all, delete-orphan",
    )
    projects: Mapped[list["Project"]] = relationship(
        "Project", secondary="project_items", back_populates="checks"
    )
