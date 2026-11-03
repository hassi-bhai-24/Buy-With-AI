"""Project folders and the project/check join table."""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Optional

from sqlalchemy import Column, ForeignKey, String, Table, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin

if TYPE_CHECKING:
    from .check import Check
    from .user import User

project_items = Table(
    "project_items",
    Base.metadata,
    Column(
        "project_id", String(36),
        ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True,
    ),
    Column(
        "check_id", String(36),
        ForeignKey("checks.id", ondelete="CASCADE"), primary_key=True,
    ),
)


class Project(Base, TimestampMixin):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"),
        index=True, nullable=False,
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    user: Mapped["User"] = relationship("User", back_populates="projects")
    checks: Mapped[list["Check"]] = relationship(
        "Check", secondary="project_items", back_populates="projects"
    )
