"""Tenant database model."""

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ai_service.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from ai_service.db.models.document import Document
    from ai_service.db.models.user import User


class Tenant(Base, TimestampMixin):
    """Represents a customer organization / tenant."""

    __tablename__ = "tenants"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
    )
    name: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )

    # Relationships
    users: Mapped[list[User]] = relationship(
        "User",
        back_populates="tenant",
        cascade="all, delete-orphan",
    )
    documents: Mapped[list[Document]] = relationship(
        "Document",
        back_populates="tenant",
        cascade="all, delete-orphan",
    )

