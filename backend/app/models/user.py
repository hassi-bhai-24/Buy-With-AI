"""User model: one row per device (guest mode, no email/password)."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Boolean, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin

if TYPE_CHECKING:
    from .check import Check
    from .journal import DealJournal
    from .project import Project


class User(Base, TimestampMixin):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    device_uuid: Mapped[str] = mapped_column(
        String(64), unique=True, index=True, nullable=False
    )
    country: Mapped[str] = mapped_column(String(64), default="Pakistan", nullable=False)
    province: Mapped[str] = mapped_column(String(64), default="Punjab", nullable=False)
    city: Mapped[str] = mapped_column(String(64), default="Bahawalpur", nullable=False)
    preferred_currency: Mapped[str] = mapped_column(
        String(10), default="PKR", nullable=False
    )
    preferred_unit_system: Mapped[str] = mapped_column(
        String(20), default="metric_traditional", nullable=False
    )
    is_anonymous_guest: Mapped[bool] = mapped_column(default=True, nullable=False)
    auto_delete_days: Mapped[Optional[int]] = mapped_column(
        Integer, default=None, nullable=True
    )

    checks: Mapped[list["Check"]] = relationship(
        "Check", back_populates="user", cascade="all, delete-orphan"
    )
    journal_entries: Mapped[list["DealJournal"]] = relationship(
        "DealJournal", back_populates="user", cascade="all, delete-orphan"
    )
    projects: Mapped[list["Project"]] = relationship(
        "Project", back_populates="user", cascade="all, delete-orphan"
    )
