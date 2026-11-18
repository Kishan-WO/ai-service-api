"""Records every provider call: one JSON log line and one `llm_calls` row, with cost and latency.

`AccountingClient` wraps ONE adapter and sits closest to the provider, so every real call is
counted, including the ones that fail and the retries and fallbacks that the layers above make.
"""

import asyncio
import logging
import time
import uuid
from collections.abc import AsyncGenerator, Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Protocol

import anyio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ai_service.core.config import ModelPrice
from ai_service.db.models.llm_call import CALL_CANCELLED, CALL_ERROR, CALL_OK, LLMCall
from ai_service.services.llm_cost import compute_cost
from ai_service.services.llm_types import (
    Finish,
    LLMClient,
    LLMError,
    LLMRequest,
    LLMResponse,
    StreamEvent,
    Usage,
)

logger = logging.getLogger("ai_service.llm")


@dataclass(frozen=True)
class LLMCallRecord:
    request_id: str | None
    tenant_id: str | None
    user_id: str | None
    feature: str
    backend: str
    model: str
    operation: str
    status: str
    error_type: str | None
    stop_reason: str | None
    usage: Usage | None
    cost_usd: Decimal | None
    latency_ms: float
    prompt_name: str | None = None
    prompt_version: str | None = None


class CallRecorder(Protocol):
    async def record(self, call: LLMCallRecord) -> None: ...


def _as_uuid(value: str | None) -> uuid.UUID | None:
    try:
        return uuid.UUID(value) if value else None
    except ValueError:
        return None


class DbCallRecorder:
    """Saves each call in its own short session; the request's session may be long gone."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def record(self, call: LLMCallRecord) -> None:
        usage = call.usage
        async with self._session_factory() as session:
            session.add(
                LLMCall(
                    request_id=call.request_id,
                    tenant_id=_as_uuid(call.tenant_id),
                    user_id=_as_uuid(call.user_id),
                    feature=call.feature,
                    prompt_name=call.prompt_name,
                    prompt_version=call.prompt_version,
                    backend=call.backend,
                    model=call.model,
                    operation=call.operation,
                    status=call.status,
                    error_type=call.error_type,
                    stop_reason=call.stop_reason,
                    input_tokens=usage.input_tokens if usage else None,
                    output_tokens=usage.output_tokens if usage else None,
                    cache_read_tokens=usage.cache_read_tokens if usage else None,
                    cache_write_tokens=usage.cache_write_tokens if usage else None,
                    cost_usd=call.cost_usd,
                    latency_ms=call.latency_ms,
                )
            )
            await session.commit()


class AccountingClient:
    def __init__(
        self,
        inner: LLMClient,
        *,
        prices: Mapping[str, ModelPrice],
        recorder: CallRecorder | None = None,
    ) -> None:
        self._inner = inner
        self._prices = prices
        self._recorder = recorder
        self.backend = inner.backend
        self.model = inner.model

    # ---------- the three calls

    async def generate(self, request: LLMRequest) -> LLMResponse:
        return await self._timed("generate", request, lambda: self._inner.generate(request))

    async def generate_structured(
        self, request: LLMRequest, *, schema_name: str, schema: dict[str, Any]
    ) -> LLMResponse:
        return await self._timed(
            "structured",
            request,
            lambda: self._inner.generate_structured(
                request, schema_name=schema_name, schema=schema
            ),
        )

    async def stream(self, request: LLMRequest) -> AsyncGenerator[StreamEvent]:
        started = time.perf_counter()
        events = self._inner.stream(request)
        status, error_type = CALL_OK, None
        finish: Finish | None = None
        model = self._inner.model
        try:
            async for event in events:
                if isinstance(event, Finish):
                    finish = event
                yield event
        except LLMError as exc:
            status, error_type = CALL_ERROR, exc.kind
            raise
        except asyncio.CancelledError, GeneratorExit:
            if finish is None:  # stopped before the end: the client left
                status = CALL_CANCELLED
            raise
        finally:
            # shielded: the task may be cancelled; the row and the upstream close must still happen
            with anyio.CancelScope(shield=True):
                await events.aclose()
                await self._finish(
                    "stream",
                    request,
                    started,
                    status=status,
                    error_type=error_type,
                    model=model,
                    stop_reason=finish.stop_reason if finish else None,
                    usage=finish.usage if finish else None,
                )

    # ---------- shared

    async def _timed(self, operation: str, request: LLMRequest, call: Any) -> LLMResponse:
        started = time.perf_counter()
        try:
            response: LLMResponse = await call()
        except LLMError as exc:
            await self._finish(
                operation,
                request,
                started,
                status=CALL_ERROR,
                error_type=exc.kind,
                model=self._inner.model,
            )
            raise
        except asyncio.CancelledError:
            with anyio.CancelScope(shield=True):
                await self._finish(
                    operation,
                    request,
                    started,
                    status=CALL_CANCELLED,
                    model=self._inner.model,
                )
            raise
        await self._finish(
            operation,
            request,
            started,
            status=CALL_OK,
            model=response.model,
            stop_reason=response.stop_reason,
            usage=response.usage,
        )
        return response

    async def _finish(
        self,
        operation: str,
        request: LLMRequest,
        started: float,
        *,
        status: str,
        model: str,
        error_type: str | None = None,
        stop_reason: str | None = None,
        usage: Usage | None = None,
    ) -> None:
        latency_ms = round((time.perf_counter() - started) * 1000, 1)
        cost = compute_cost(usage, self._prices.get(model))
        context = request.context
        record = LLMCallRecord(
            request_id=context.request_id,
            tenant_id=context.tenant_id,
            user_id=context.user_id,
            feature=context.feature,
            backend=self.backend,
            model=model,
            operation=operation,
            status=status,
            error_type=error_type,
            stop_reason=stop_reason,
            usage=usage,
            cost_usd=cost,
            latency_ms=latency_ms,
            prompt_name=context.prompt_name,
            prompt_version=context.prompt_version,
        )
        logger.log(
            logging.INFO if status == CALL_OK else logging.WARNING,
            "llm %s %s: %s %s, %s ms",
            operation,
            status,
            self.backend,
            model,
            latency_ms,
            extra={
                "request_id": context.request_id,
                "tenant_id": context.tenant_id,
                "user_id": context.user_id,
                "feature": context.feature,
                "prompt_name": context.prompt_name,
                "prompt_version": context.prompt_version,
                "backend": self.backend,
                "model": model,
                "operation": operation,
                "status": status,
                "error_type": error_type,
                "stop_reason": stop_reason,
                "input_tokens": usage.input_tokens if usage else None,
                "output_tokens": usage.output_tokens if usage else None,
                "cache_read_tokens": usage.cache_read_tokens if usage else None,
                "cache_write_tokens": usage.cache_write_tokens if usage else None,
                "cost_usd": str(cost) if cost is not None else None,
                "latency_ms": latency_ms,
            },
        )
        if self._recorder is None:
            return
        try:
            await self._recorder.record(record)
        except Exception:  # accounting must never break the request it is measuring
            logger.exception(
                "could not save the llm call", extra={"request_id": context.request_id}
            )
