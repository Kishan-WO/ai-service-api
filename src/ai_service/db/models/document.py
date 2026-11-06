"""Document database model."""

import uuid
from typing import TYPE_CHECKING, Any

from sqlalchemy import ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import JSON

from ai_service.db.base import Base, TimestampMixin

if TYPE_CHECKING:
    from ai_service.db.models.tenant import Tenant


class Document(Base, TimestampMixin):
    """Represents a document owned by a tenant."""

    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(
        primary_key=True,
        default=uuid.uuid4,
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    title: Mapped[str] = mapped_column(
        String(255),
        nullable=False,
    )
    source: Mapped[str] = mapped_column(
        String(512),
        nullable=False,
    )
    content: Mapped[str] = mapped_column(
        Text,
        nullable=False,
    )
    content_hash: Mapped[str] = mapped_column(
        String(64),
        nullable=False,
    )
    # Maps to 'metadata' column in DB, using JSONB on PostgreSQL and JSON on SQLite
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata",
        JSON().with_variant(JSONB, "postgresql"),
        default=dict,
        nullable=False,
    )

    # Relationships
    tenant: Mapped[Tenant] = relationship(
        "Tenant",
        back_populates="documents",
    )

    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "content_hash",
            name="uq_documents_tenant_content_hash",
        ),
    )

