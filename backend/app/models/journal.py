"""Deal journal: post-purchase outcome ledger (one row per check)."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import DateTime, Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin

if TYPE_CHECKING:
    from .check import Check
    from .user import User


class DealJournal(Base, TimestampMixin):
    __tablename__ = "deal_journal"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    check_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("checks.id", ondelete="CASCADE"),
        unique=True, nullable=False,
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"),
        index=True, nullable=False,
    )
    original_asking_price: Mapped[float] = mapped_column(Float, nullable=False)
    final_negotiated_price: Mapped[float] = mapped_column(Float, nullable=False)
    net_savings_amount: Mapped[float] = mapped_column(Float, nullable=False)
    deal_status: Mapped[str] = mapped_column(String(32), default="Purchased", nullable=False)
    outcome_notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    closed_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, nullable=False
    )

    check: Mapped["Check"] = relationship("Check", back_populates="journal_entry")
    user: Mapped["User"] = relationship("User", back_populates="journal_entries")
