"""One row per call to a language model: who asked, what it cost, how long it took.

A single user request can cause several rows: a retry, a call to the fallback provider, or a
repair attempt after the model returned invalid JSON. Cost questions ("who spends the money?")
are then one GROUP BY away.
"""

import uuid
from decimal import Decimal

from sqlalchemy import BigInteger, Float, ForeignKey, Index, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from ai_service.db.base import Base, TimestampMixin

# BigInteger primary keys do not auto-increment on SQLite (the test database); Integer does.
_ID = BigInteger().with_variant(Integer, "sqlite")

# llm_calls.status values
CALL_OK = "ok"
CALL_ERROR = "error"  # the provider failed; error_type says how
CALL_CANCELLED = "cancelled"  # a stream the client stopped reading


class LLMCall(Base, TimestampMixin):
    __tablename__ = "llm_calls"

    id: Mapped[int] = mapped_column(_ID, primary_key=True, autoincrement=True)
    request_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    # SET NULL, not CASCADE: the cost history stays when a tenant or user is deleted.
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("tenants.id", ondelete="SET NULL"), nullable=True
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    feature: Mapped[str] = mapped_column(String(32), nullable=False)  # chat, extract, ...
    backend: Mapped[str] = mapped_column(String(16), nullable=False)
    model: Mapped[str] = mapped_column(String(128), nullable=False)
    operation: Mapped[str] = mapped_column(
        String(16), nullable=False
    )  # generate, stream, structured
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    error_type: Mapped[str | None] = mapped_column(String(48), nullable=True)
    stop_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # NULL means "the provider did not say", which is not the same as 0
    input_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)  # new input only
    output_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cache_read_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cache_write_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(14, 8), nullable=True)
    latency_ms: Mapped[float] = mapped_column(Float, nullable=False)

    __table_args__ = (
        Index("ix_llm_calls_tenant_id_created_at", "tenant_id", "created_at"),
        Index("ix_llm_calls_feature_created_at", "feature", "created_at"),
    )
