"""Cost from the price table, and the per-call log line and database row."""

import logging
import uuid
from decimal import Decimal
from typing import Any

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ai_service.core.config import ModelPrice, Settings
from ai_service.db.models import LLMCall
from ai_service.services.llm_accounting import AccountingClient, DbCallRecorder, LLMCallRecord
from ai_service.services.llm_cost import compute_cost
from ai_service.services.llm_types import (
    CallContext,
    ChatMessage,
    Finish,
    LLMRequest,
    LLMResponse,
    RateLimitedError,
    StreamStart,
    TextDelta,
    Usage,
)

from .test_llm_wrappers import Scripted

PRICES = {"m": ModelPrice(input=0.25, output=1.5, cache_read=0.025)}
CONTEXT = CallContext(request_id="req-1", tenant_id=str(uuid.uuid4()), feature="chat")
REQUEST = LLMRequest([ChatMessage("user", "hi")], context=CONTEXT)


class MemoryRecorder:
    def __init__(self, *, broken: bool = False) -> None:
        self.calls: list[LLMCallRecord] = []
        self.broken = broken

    async def record(self, call: LLMCallRecord) -> None:
        if self.broken:
            raise RuntimeError("database is down")
        self.calls.append(call)


# ---------- cost


def test_cost_is_the_sum_of_the_four_token_kinds_at_their_own_prices() -> None:
    usage = Usage(input_tokens=1000, output_tokens=500, cache_read_tokens=2000)
    # (1000 x 0.25 + 500 x 1.50 + 2000 x 0.025) / 1,000,000
    assert compute_cost(usage, PRICES["m"]) == Decimal("0.00105000")


def test_cache_writes_have_their_own_price() -> None:
    price = ModelPrice(input=3.0, output=15.0, cache_read=0.3, cache_write=3.75)
    assert compute_cost(Usage(cache_write_tokens=1_000_000), price) == Decimal("3.75000000")


def test_an_unknown_usage_or_price_gives_no_cost_not_zero() -> None:
    assert compute_cost(None, PRICES["m"]) is None
    assert compute_cost(Usage(10, 10), None) is None
    assert compute_cost(Usage(10, 10), ModelPrice()) == Decimal("0E-8")  # a free model is really 0


def test_the_default_price_table_knows_the_models_this_project_uses() -> None:
    prices = Settings(SECRET_KEY="x" * 32, DATABASE_URL="sqlite+aiosqlite://").LLM_PRICES
    assert prices["gemini-3.1-flash-lite"].cache_read < prices["gemini-3.1-flash-lite"].input
    assert prices["gemma3:270m"] == ModelPrice()


# ---------- the accounting wrapper


async def test_a_successful_call_is_recorded_with_tokens_cost_and_context() -> None:
    recorder = MemoryRecorder()
    answer = LLMResponse("ok", "stop", Usage(1000, 500, 2000), "m", "hosted")
    client = AccountingClient(Scripted([answer]), prices=PRICES, recorder=recorder)

    await client.generate(REQUEST)

    (row,) = recorder.calls
    assert (row.status, row.operation, row.backend, row.model) == ("ok", "generate", "hosted", "m")
    assert (row.request_id, row.tenant_id, row.feature) == ("req-1", CONTEXT.tenant_id, "chat")
    assert row.usage == Usage(1000, 500, 2000)
    assert row.cost_usd == Decimal("0.00105000")
    assert row.latency_ms >= 0


async def test_a_failed_call_is_recorded_with_the_error_type_and_still_raised() -> None:
    recorder = MemoryRecorder()
    client = AccountingClient(Scripted([RateLimitedError("429")]), prices=PRICES, recorder=recorder)

    with pytest.raises(RateLimitedError):
        await client.generate(REQUEST)

    (row,) = recorder.calls
    assert (row.status, row.error_type, row.usage, row.cost_usd) == (
        "error",
        "RateLimitedError",
        None,
        None,
    )


async def test_every_retry_is_its_own_row() -> None:
    from .test_llm_wrappers import Clock, retrying

    recorder = MemoryRecorder()
    inner = Scripted(
        [RateLimitedError("429"), LLMResponse("ok", "stop", Usage(1, 1), "m", "hosted")]
    )
    counted = AccountingClient(inner, prices=PRICES, recorder=recorder)
    await retrying(counted, Clock()).generate(REQUEST)  # type: ignore[arg-type]
    assert [c.status for c in recorder.calls] == ["error", "ok"]


async def test_a_stream_is_recorded_when_it_ends_with_the_final_usage() -> None:
    recorder = MemoryRecorder()
    events = [StreamStart("m", "hosted"), TextDelta("Hi"), Finish("stop", Usage(10, 5, 90))]
    client = AccountingClient(Scripted([events]), prices=PRICES, recorder=recorder)

    seen = [e async for e in client.stream(REQUEST)]

    assert len(seen) == 3
    (row,) = recorder.calls
    assert (row.operation, row.status, row.stop_reason) == ("stream", "ok", "stop")
    assert row.usage == Usage(10, 5, 90)


async def test_a_stream_the_reader_abandons_is_recorded_as_cancelled() -> None:
    recorder = MemoryRecorder()
    events = [
        StreamStart("m", "hosted"),
        TextDelta("a"),
        TextDelta("b"),
        Finish("stop", Usage(1, 2)),
    ]
    inner = Scripted([events])
    stream = AccountingClient(inner, prices=PRICES, recorder=recorder).stream(REQUEST)

    await anext(stream)
    await anext(stream)
    await stream.aclose()  # the client went away

    (row,) = recorder.calls
    assert (row.status, row.usage, row.cost_usd) == ("cancelled", None, None)
    assert inner.closed == 1  # the upstream call was closed too


async def test_a_model_without_a_price_is_logged_with_no_cost() -> None:
    recorder = MemoryRecorder()
    answer = LLMResponse("ok", "stop", Usage(5, 5), "m", "hosted")
    await AccountingClient(Scripted([answer]), prices={}, recorder=recorder).generate(REQUEST)
    assert recorder.calls[0].cost_usd is None


async def test_a_broken_recorder_never_breaks_the_call() -> None:
    answer = LLMResponse("ok", "stop", Usage(5, 5), "m", "hosted")
    client = AccountingClient(
        Scripted([answer]), prices=PRICES, recorder=MemoryRecorder(broken=True)
    )
    assert await client.generate(REQUEST) is answer


async def test_the_log_line_carries_the_cache_tokens_and_the_cost(
    caplog: pytest.LogCaptureFixture,
) -> None:
    answer = LLMResponse("ok", "stop", Usage(10, 5, 90), "m", "hosted")
    client = AccountingClient(Scripted([answer]), prices=PRICES)
    with caplog.at_level(logging.INFO, logger="ai_service.llm"):
        await client.generate(REQUEST)

    (record,) = [r for r in caplog.records if r.name == "ai_service.llm"]
    fields: dict[str, Any] = record.__dict__
    assert fields["cache_read_tokens"] == 90
    assert (fields["input_tokens"], fields["output_tokens"]) == (10, 5)
    assert fields["cost_usd"] == "0.00001225"  # (2.5 + 7.5 + 2.25) / 1e6
    assert (fields["feature"], fields["request_id"], fields["backend"]) == (
        "chat",
        "req-1",
        "hosted",
    )


# ---------- the database row


async def test_the_database_recorder_saves_one_row(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await DbCallRecorder(session_factory).record(
        LLMCallRecord(
            request_id="req-9",
            tenant_id=None,  # a script run: no tenant
            user_id="not-a-uuid",  # unreadable ids become NULL instead of failing the save
            feature="extract",
            backend="hosted",
            model="m",
            operation="structured",
            status="ok",
            error_type=None,
            stop_reason="stop",
            usage=Usage(10, 5, 90),
            cost_usd=Decimal("0.000012"),
            latency_ms=123.4,
        )
    )
    async with session_factory() as session:
        row = (await session.scalars(select(LLMCall))).one()
    assert (row.feature, row.status, row.tenant_id, row.user_id) == ("extract", "ok", None, None)
    assert (row.input_tokens, row.output_tokens, row.cache_read_tokens, row.cache_write_tokens) == (
        10,
        5,
        90,
        0,
    )
    assert row.cost_usd == Decimal("0.000012")
