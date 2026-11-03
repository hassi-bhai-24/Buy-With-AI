"""Watchlist: saved checks a user wants re-priced later.

Plain SQLAlchemy mapped model on ``Base`` (no exotic types) so it works
with both ``create_all`` (current ``init_db``) and Alembic autogenerate.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import Float, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin

if TYPE_CHECKING:
    from .check import Check
    from .user import User


class WatchlistItem(Base, TimestampMixin):
    __tablename__ = "watchlist_items"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"),
        index=True, nullable=False,
    )
    check_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("checks.id", ondelete="CASCADE"),
        index=True, nullable=False,
    )
    # Target is compared against the expected per-unit price from a
    # fresh baseline lookup (the same per-unit scale as the check's
    # stored price band), in the check's currency.
    target_price: Mapped[float] = mapped_column(Float, nullable=False)
    currency: Mapped[str] = mapped_column(String(10), default="PKR", nullable=False)

    user: Mapped["User"] = relationship("User")
    check: Mapped["Check"] = relationship("Check")
