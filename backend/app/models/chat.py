"""Chat threads and messages.

Plain SQLAlchemy mapped models on ``Base`` (no exotic types) so they
work with both ``create_all`` (current ``init_db``) and Alembic
autogenerate. A thread optionally links to one persisted check so
follow-up replies can be grounded in that check's stored numbers.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import TYPE_CHECKING, Optional

from sqlalchemy import DateTime, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin

if TYPE_CHECKING:
    from .check import Check
    from .user import User


class ChatThread(Base, TimestampMixin):
    __tablename__ = "chat_threads"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    user_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="CASCADE"),
        index=True, nullable=False,
    )
    check_id: Mapped[Optional[str]] = mapped_column(
        String(36), ForeignKey("checks.id", ondelete="CASCADE"),
        index=True, nullable=True,
    )

    user: Mapped["User"] = relationship("User")
    check: Mapped[Optional["Check"]] = relationship("Check")
    messages: Mapped[list["ChatMessage"]] = relationship(
        "ChatMessage", back_populates="thread", cascade="all, delete-orphan",
        order_by="ChatMessage.created_at",
    )


class ChatMessage(Base):
    __tablename__ = "chat_messages"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )
    thread_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("chat_threads.id", ondelete="CASCADE"),
        index=True, nullable=False,
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # Engine that produced an assistant message ("rule-based" / "ollama");
    # null for user messages.
    engine: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.utcnow, server_default=func.now(),
        nullable=False, index=True,
    )

    thread: Mapped["ChatThread"] = relationship(
        "ChatThread", back_populates="messages"
    )
