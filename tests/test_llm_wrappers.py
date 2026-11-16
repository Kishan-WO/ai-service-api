"""Retry, fallback and the limits, tested with scripted clients and no real waiting."""

import asyncio
from collections.abc import AsyncGenerator
from typing import Any

import pytest

from ai_service.services.llm_types import (
    AuthError,
    ChatMessage,
    ContextTooLongError,
    Finish,
    LLMError,
    LLMRequest,
    LLMResponse,
    LLMTimeoutError,
    OverloadedError,
    QuotaExhaustedError,
    RateLimitedError,
    StreamEvent,
    StreamStart,
    TextDelta,
    Usage,
)
from ai_service.services.llm_wrappers import (
    FallbackClient,
    LimitedClient,
    RateLimiter,
    RetryingClient,
    RetryPolicy,
)

REQUEST = LLMRequest([ChatMessage("user", "hi")])
OK = LLMResponse("ok", "stop", Usage(1, 1), "m", "hosted")


class Scripted:
    """Answers each call from a list: an exception is raised, anything else is returned."""

    def __init__(self, outcomes: list[Any], backend: str = "hosted", model: str = "m") -> None:
        self.outcomes = list(outcomes)
        self.backend = backend
        self.model = model
        self.calls = 0
        self.closed = 0

    def _next(self) -> Any:
        self.calls += 1
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    async def generate(self, request: LLMRequest) -> LLMResponse:
        result: LLMResponse = self._next()
        return result

    async def generate_structured(
        self, request: LLMRequest, *, schema_name: str, schema: dict[str, Any]
    ) -> LLMResponse:
        result: LLMResponse = self._next()
        return result

    async def stream(self, request: LLMRequest) -> AsyncGenerator[StreamEvent]:
        try:
            events: list[Any] = self._next()
            for event in events:
                if isinstance(event, Exception):
                    raise event
                yield event
        finally:
            self.closed += 1


class Clock:
    """Time that only moves when a test sleeps."""

    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def __call__(self) -> float:
        return self.now

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def retrying(
    inner: Scripted,
    clock: Clock,
    *,
    attempts: int = 3,
    jitter: float = 1.0,
    total: float = 90.0,
) -> RetryingClient:
    policy = RetryPolicy(attempts=attempts, base_delay=1.0, max_delay=20.0, total_seconds=total)
    return RetryingClient(inner, policy, sleep=clock.sleep, jitter=lambda: jitter, clock=clock)


def good_stream(*texts: str) -> list[StreamEvent]:
    return [
        StreamStart("m", "hosted"),
        *[TextDelta(t) for t in texts],
        Finish("stop", Usage(1, len(texts))),
    ]


async def collect(client: Any) -> list[StreamEvent]:
    return [event async for event in client.stream(REQUEST)]


# ---------- retry


async def test_a_transient_error_is_retried_with_growing_waits() -> None:
    clock = Clock()
    inner = Scripted([RateLimitedError("429"), OverloadedError("503"), OK])
    result = await retrying(inner, clock).generate(REQUEST)

    assert result is OK
    assert inner.calls == 3
    assert clock.sleeps == [1.0, 2.0]  # base x 2^n; jitter fixed at 1.0 for the test


async def test_jitter_spreads_the_wait_between_zero_and_the_ceiling() -> None:
    clock = Clock()
    await retrying(Scripted([RateLimitedError("429"), OK]), clock, jitter=0.25).generate(REQUEST)
    assert clock.sleeps == [0.25]  # 0.25 x the 1 s ceiling


@pytest.mark.parametrize(
    "error",
    [AuthError("401"), ContextTooLongError("too long"), QuotaExhaustedError("daily limit")],
)
async def test_errors_that_waiting_cannot_fix_are_not_retried(error: LLMError) -> None:
    clock = Clock()
    inner = Scripted([error, OK])
    with pytest.raises(type(error)):
        await retrying(inner, clock).generate(REQUEST)
    assert inner.calls == 1
    assert clock.sleeps == []


async def test_it_gives_up_after_the_attempts_and_raises_the_last_error() -> None:
    clock = Clock()
    inner = Scripted([OverloadedError("a"), OverloadedError("b"), OverloadedError("c"), OK])
    with pytest.raises(OverloadedError, match="c"):
        await retrying(inner, clock, attempts=3).generate(REQUEST)
    assert inner.calls == 3
    assert len(clock.sleeps) == 2


async def test_retry_after_from_the_provider_is_obeyed() -> None:
    clock = Clock()
    inner = Scripted([RateLimitedError("429", retry_after=7.0), OK])
    await retrying(inner, clock, jitter=0.0).generate(REQUEST)
    assert clock.sleeps == [7.0]  # jitter alone would have said 0


async def test_it_stops_when_the_next_wait_would_pass_the_time_budget() -> None:
    clock = Clock()
    inner = Scripted([RateLimitedError("429", retry_after=60.0), OK])
    with pytest.raises(RateLimitedError):
        await retrying(inner, clock, total=30.0).generate(REQUEST)
    assert inner.calls == 1 and clock.sleeps == []


async def test_structured_calls_are_retried_too() -> None:
    clock = Clock()
    inner = Scripted([LLMTimeoutError("slow"), OK])
    result = await retrying(inner, clock).generate_structured(REQUEST, schema_name="T", schema={})
    assert result is OK and inner.calls == 2


async def test_a_stream_is_retried_while_no_text_has_been_sent() -> None:
    clock = Clock()
    inner = Scripted([[StreamStart("m", "hosted"), RateLimitedError("429")], good_stream("Hi")])
    events = await collect(retrying(inner, clock))

    assert events == good_stream("Hi")  # one StreamStart, one text: the failed try left no trace
    assert inner.calls == 2
    assert inner.closed == 2


async def test_a_stream_is_not_retried_after_text_was_sent() -> None:
    clock = Clock()
    inner = Scripted([[StreamStart("m", "hosted"), TextDelta("Hel"), OverloadedError("cut")]])
    seen: list[StreamEvent] = []
    with pytest.raises(OverloadedError):
        async for event in retrying(inner, clock).stream(REQUEST):
            seen.append(event)
    assert seen == [StreamStart("m", "hosted"), TextDelta("Hel")]
    assert inner.calls == 1  # starting again would show "Hel" twice


# ---------- fallback


async def test_the_second_backend_answers_when_the_first_keeps_failing() -> None:
    primary = Scripted([RateLimitedError("429")], backend="hosted")
    second = Scripted([LLMResponse("from local", "stop", None, "gemma", "local")], backend="local")
    result = await FallbackClient([primary, second]).generate(REQUEST)

    assert (result.text, result.backend, result.model) == ("from local", "local", "gemma")
    assert (primary.calls, second.calls) == (1, 1)


async def test_the_primary_is_used_when_it_works() -> None:
    primary = Scripted([OK])
    second = Scripted([])
    assert await FallbackClient([primary, second]).generate(REQUEST) is OK
    assert second.calls == 0


async def test_a_quota_error_moves_on_to_the_next_backend() -> None:
    second = Scripted([OK], backend="local")
    result = await FallbackClient([Scripted([QuotaExhaustedError("daily")]), second]).generate(
        REQUEST
    )
    assert result is OK


@pytest.mark.parametrize("error", [AuthError("bad key"), ContextTooLongError("too long")])
async def test_errors_another_provider_would_not_fix_are_raised_at_once(error: LLMError) -> None:
    second = Scripted([OK])
    with pytest.raises(type(error)):
        await FallbackClient([Scripted([error]), second]).generate(REQUEST)
    assert second.calls == 0


async def test_when_every_backend_fails_the_last_error_is_raised() -> None:
    with pytest.raises(OverloadedError, match="second"):
        await FallbackClient(
            [Scripted([RateLimitedError("first")]), Scripted([OverloadedError("second")])]
        ).generate(REQUEST)


async def test_a_stream_falls_back_before_the_first_text() -> None:
    primary = Scripted([[OverloadedError("503")]])
    second = Scripted([good_stream("Hi")], backend="local", model="gemma")
    events = await collect(FallbackClient([primary, second]))
    assert events[0] == StreamStart("m", "hosted")  # the scripted start of the second client
    assert [e.text for e in events if isinstance(e, TextDelta)] == ["Hi"]
    assert primary.closed == 1


async def test_a_stream_that_breaks_after_text_does_not_fall_back() -> None:
    primary = Scripted([[StreamStart("m", "hosted"), TextDelta("Hel"), OverloadedError("cut")]])
    second = Scripted([good_stream("never")])
    with pytest.raises(OverloadedError):
        await collect(FallbackClient([primary, second]))
    assert second.calls == 0


# ---------- limits


async def test_at_most_n_calls_run_at_the_same_time() -> None:
    running = 0
    peak = 0

    class Slow(Scripted):
        async def generate(self, request: LLMRequest) -> LLMResponse:
            nonlocal running, peak
            running += 1
            peak = max(peak, running)
            await asyncio.sleep(0.01)
            running -= 1
            return OK

    client = LimitedClient(Slow([]), max_concurrency=2)
    await asyncio.gather(*[client.generate(REQUEST) for _ in range(6)])
    assert peak == 2


async def test_the_per_minute_limit_makes_the_next_call_wait() -> None:
    clock = Clock()
    limiter = RateLimiter(3, clock=clock, sleep=clock.sleep)
    for _ in range(3):
        await limiter.acquire()
    assert clock.sleeps == []  # three calls fit in the minute

    await limiter.acquire()  # the fourth must wait for the first to leave the window
    assert clock.sleeps == [60.0]

    await limiter.acquire()  # the window moved on: no more waiting needed yet
    assert clock.sleeps == [60.0]
