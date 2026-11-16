"""Layers that wrap any LLMClient and are LLMClients themselves, so they stack:

    FallbackClient( RetryingClient( LimitedClient( AccountingClient( adapter ) ) ) , ...)

  LimitedClient     at most N calls in flight, and at most M calls per minute
  RetryingClient    transient errors are retried with exponential back-off and jitter
  FallbackClient    when a backend still fails, the next one answers

For a stream, retries and fallbacks only happen BEFORE the first piece of text: after that the
client has already seen words, and starting again would show them twice.
"""

import asyncio
import logging
import random
import time
from collections import deque
from collections.abc import AsyncGenerator, Awaitable, Callable, Sequence
from dataclasses import dataclass
from typing import Any

import anyio

from ai_service.core.config import Settings
from ai_service.services.llm_types import (
    LLMClient,
    LLMError,
    LLMRequest,
    LLMResponse,
    StreamEvent,
    StreamStart,
)

logger = logging.getLogger("ai_service.llm")


async def _prime(events: AsyncGenerator[StreamEvent]) -> list[StreamEvent]:
    """Read up to and including the first event that is not a StreamStart.

    Errors that happen before any text (a timeout waiting for the first token, a 429) surface
    here, while the caller can still retry or fall back.
    """
    buffered: list[StreamEvent] = []
    async for event in events:
        buffered.append(event)
        if not isinstance(event, StreamStart):
            break
    return buffered


async def _close(events: AsyncGenerator[StreamEvent]) -> None:
    with anyio.CancelScope(shield=True):
        await events.aclose()


# ---------- limits


class RateLimiter:
    """At most `per_minute` calls start in any 60 seconds (a sliding window)."""

    def __init__(
        self,
        per_minute: int,
        *,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._per_minute = per_minute
        self._clock = clock
        self._sleep = sleep
        self._starts: deque[float] = deque()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        async with self._lock:  # one waiter at a time keeps the order fair
            while True:
                now = self._clock()
                while self._starts and now - self._starts[0] >= 60:
                    self._starts.popleft()
                if len(self._starts) < self._per_minute:
                    self._starts.append(now)
                    return
                await self._sleep(self._starts[0] + 60 - now)


class LimitedClient:
    """A semaphore (calls in flight) plus an optional per-minute limit, for ONE backend."""

    def __init__(self, inner: LLMClient, *, max_concurrency: int, per_minute: int = 0) -> None:
        self._inner = inner
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._limiter = RateLimiter(per_minute) if per_minute > 0 else None
        self.backend = inner.backend
        self.model = inner.model

    async def _start(self) -> None:
        if self._limiter is not None:
            await self._limiter.acquire()

    async def generate(self, request: LLMRequest) -> LLMResponse:
        async with self._semaphore:
            await self._start()
            return await self._inner.generate(request)

    async def generate_structured(
        self, request: LLMRequest, *, schema_name: str, schema: dict[str, Any]
    ) -> LLMResponse:
        async with self._semaphore:
            await self._start()
            return await self._inner.generate_structured(
                request, schema_name=schema_name, schema=schema
            )

    async def stream(self, request: LLMRequest) -> AsyncGenerator[StreamEvent]:
        async with self._semaphore:  # held for the whole stream
            await self._start()
            events = self._inner.stream(request)
            try:
                async for event in events:
                    yield event
            finally:
                await _close(events)


# ---------- retries


@dataclass(frozen=True)
class RetryPolicy:
    attempts: int = 3  # tries, the first one included
    base_delay: float = 1.0
    max_delay: float = 20.0
    total_seconds: float = 90.0  # give up when the next wait would pass this

    @classmethod
    def from_settings(cls, settings: Settings) -> RetryPolicy:
        return cls(
            attempts=settings.LLM_RETRY_ATTEMPTS,
            base_delay=settings.LLM_RETRY_BASE_DELAY_SECONDS,
            max_delay=settings.LLM_RETRY_MAX_DELAY_SECONDS,
            total_seconds=settings.LLM_RETRY_TOTAL_SECONDS,
        )


class RetryingClient:
    def __init__(
        self,
        inner: LLMClient,
        policy: RetryPolicy,
        *,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        jitter: Callable[[], float] = random.random,  # 0 <= x < 1
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._inner = inner
        self._policy = policy
        self._sleep = sleep
        self._jitter = jitter
        self._clock = clock
        self.backend = inner.backend
        self.model = inner.model

    def _delay_or_raise(self, exc: LLMError, attempt: int, started: float) -> float:
        """How long to wait before the next try, or re-raise when retrying is pointless."""
        policy = self._policy
        if not exc.retryable or attempt >= policy.attempts:
            raise exc
        ceiling = min(policy.max_delay, policy.base_delay * float(2 ** (attempt - 1)))
        delay = self._jitter() * ceiling  # "full jitter": clients do not retry in step
        if exc.retry_after is not None:
            delay = max(delay, exc.retry_after)  # the provider said how long to wait: obey it
        if (self._clock() - started) + delay > policy.total_seconds:
            raise exc
        logger.warning(
            "llm retry %d/%d for %s after %s, waiting %.1f s",
            attempt + 1,
            policy.attempts,
            self.backend,
            exc.kind,
            delay,
        )
        return delay

    async def _call[T](self, call: Callable[[], Awaitable[T]]) -> T:
        started = self._clock()
        attempt = 0
        while True:
            attempt += 1
            try:
                return await call()
            except LLMError as exc:
                delay = self._delay_or_raise(exc, attempt, started)
            await self._sleep(delay)

    async def generate(self, request: LLMRequest) -> LLMResponse:
        return await self._call(lambda: self._inner.generate(request))

    async def generate_structured(
        self, request: LLMRequest, *, schema_name: str, schema: dict[str, Any]
    ) -> LLMResponse:
        return await self._call(
            lambda: self._inner.generate_structured(request, schema_name=schema_name, schema=schema)
        )

    async def stream(self, request: LLMRequest) -> AsyncGenerator[StreamEvent]:
        started = self._clock()
        attempt = 0
        while True:
            attempt += 1
            events = self._inner.stream(request)
            try:
                buffered = await _prime(events)
            except LLMError as exc:
                await _close(events)
                delay = self._delay_or_raise(exc, attempt, started)
            except BaseException:
                await _close(events)
                raise
            else:
                break
            await self._sleep(delay)
        try:
            for event in buffered:
                yield event
            async for event in events:
                yield event
        finally:
            await _close(events)


# ---------- fallback


class FallbackClient:
    """Tries the clients in order. Only availability problems move on to the next one.

    A wrong key or a bad request would fail on the next provider too, or hide a bug, so those
    are raised at once. Which client answered is in the response (`backend`, `model`).
    """

    def __init__(self, clients: Sequence[LLMClient]) -> None:
        self._clients = list(clients)
        self.backend = self._clients[0].backend
        self.model = self._clients[0].model

    def _next_or_raise(self, exc: LLMError, index: int) -> None:
        if not exc.fallback_ok or index == len(self._clients) - 1:
            raise exc
        logger.warning(
            "llm fallback: %s failed (%s), trying %s",
            self._clients[index].backend,
            exc.kind,
            self._clients[index + 1].backend,
        )

    async def generate(self, request: LLMRequest) -> LLMResponse:
        for index, client in enumerate(self._clients):
            try:
                return await client.generate(request)
            except LLMError as exc:
                self._next_or_raise(exc, index)
        raise AssertionError("unreachable: the last client re-raises")

    async def generate_structured(
        self, request: LLMRequest, *, schema_name: str, schema: dict[str, Any]
    ) -> LLMResponse:
        for index, client in enumerate(self._clients):
            try:
                return await client.generate_structured(
                    request, schema_name=schema_name, schema=schema
                )
            except LLMError as exc:
                self._next_or_raise(exc, index)
        raise AssertionError("unreachable: the last client re-raises")

    async def stream(self, request: LLMRequest) -> AsyncGenerator[StreamEvent]:
        for index, client in enumerate(self._clients):
            events = client.stream(request)
            try:
                buffered = await _prime(events)
            except LLMError as exc:
                await _close(events)
                self._next_or_raise(exc, index)
                continue
            except BaseException:
                await _close(events)
                raise
            try:
                for event in buffered:
                    yield event
                async for event in events:
                    yield event
            finally:
                await _close(events)
            return
