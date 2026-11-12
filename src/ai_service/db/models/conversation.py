"""Conversation and message database models. Both carry tenant_id so every query can be scoped."""

import uuid

from sqlalchemy import BigInteger, ForeignKey, Index, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ai_service.db.base import Base, TimestampMixin

# BigInteger primary keys do not auto-increment on SQLite (the test database); Integer does.
_MESSAGE_ID = BigInteger().with_variant(Integer, "sqlite")

# message.status values
STATUS_COMPLETE = "complete"
STATUS_CANCELLED = "cancelled"  # the client went away; the text received so far is kept
STATUS_ERROR = "error"  # the provider failed in the middle; the text received so far is kept


class Conversation(Base, TimestampMixin):
    __tablename__ = "conversations"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(120), nullable=False)

    messages: Mapped[list[Message]] = relationship(
        "Message",
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="Message.id",
    )


class Message(Base, TimestampMixin):
    __tablename__ = "messages"

    # An increasing number, so "oldest first" is exact even when two rows share a timestamp.
    id: Mapped[int] = mapped_column(_MESSAGE_ID, primary_key=True, autoincrement=True)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)  # "user" or "assistant"
    content: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default=STATUS_COMPLETE)
    model: Mapped[str | None] = mapped_column(String(128), nullable=True)
    stop_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)

    conversation: Mapped[Conversation] = relationship("Conversation", back_populates="messages")

    __table_args__ = (Index("ix_messages_conversation_id_id", "conversation_id", "id"),)
