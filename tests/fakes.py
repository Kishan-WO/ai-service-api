"""A fake language model: scripted answers, no network, and it records how it was used."""

import asyncio
from collections.abc import AsyncGenerator
from typing import Any

from ai_service.services.llm_types import (
    Backend,
    Finish,
    LLMClient,
    LLMError,
    LLMRequest,
    LLMResponse,
    StreamEvent,
    StreamStart,
    TextDelta,
    Usage,
)


def reply(text: str, stop_reason: str = "stop") -> LLMResponse:
    """A scripted structured answer. The model name is filled in by the fake that sends it."""
    return LLMResponse(text, stop_reason, Usage(100, 40), model="", backend="")


class FakeProvider:
    def __init__(
        self,
        model: str = "fake-model",
        *,
        backend: str = "hosted",
        texts: tuple[str, ...] = ("Hello", " there", "!"),
        fail_before_first: bool = False,
        fail_at: int | None = None,  # raise LLMError instead of sending text number `fail_at`
        delay: float = 0.0,  # pause after each piece
        first_delay: float = 0.0,  # pause before the first piece (a slow model)
        json_replies: list[LLMResponse] | None = None,
        fail_json: bool = False,
        error: LLMError | None = None,  # what fail_* raise (default: a plain LLMError)
        stream_usage: Usage | None = None,
    ) -> None:
        self.model = model
        self.backend = backend
        self.texts = texts
        self.fail_before_first = fail_before_first
        self.fail_at = fail_at
        self.delay = delay
        self.first_delay = first_delay
        self.json_replies = list(json_replies or [])
        self.fail_json = fail_json
        self.error = error
        self.stream_usage = stream_usage
        self.requests: list[LLMRequest] = []  # every streamed request, in order
        self.json_calls: list[dict[str, Any]] = []
        self.closed = False  # True once the upstream stream has been closed

    def _failure(self, message: str) -> LLMError:
        return self.error or LLMError(message)

    @property
    def calls(self) -> list[list[Any]]:
        """The messages of every streamed call (for tests that only look at the history)."""
        return [r.messages for r in self.requests]

    async def stream(self, request: LLMRequest) -> AsyncGenerator[StreamEvent]:
        self.requests.append(request)
        self.closed = False
        try:
            if self.fail_before_first:
                raise self._failure("the provider is down")
            if self.first_delay:
                await asyncio.sleep(self.first_delay)
            yield StreamStart(self.model, self.backend)
            for index, text in enumerate(self.texts):
                if self.fail_at == index:
                    raise self._failure("the stream broke")
                yield TextDelta(text)
                if self.delay:
                    await asyncio.sleep(self.delay)
            usage = self.stream_usage or Usage(len(request.messages), len(self.texts))
            yield Finish("stop", usage)
        finally:
            self.closed = True

    async def generate(self, request: LLMRequest) -> LLMResponse:
        return LLMResponse("".join(self.texts), "stop", Usage(1, 1), self.model, self.backend)

    async def generate_structured(
        self, request: LLMRequest, *, schema_name: str, schema: dict[str, Any]
    ) -> LLMResponse:
        self.json_calls.append(
            {
                "messages": list(request.messages),
                "name": schema_name,
                "schema": schema,
                "max_tokens": request.max_tokens,
                "context": request.context,
            }
        )
        if self.fail_json:
            raise self._failure("the provider is down")
        scripted = self.json_replies.pop(0)
        return LLMResponse(
            scripted.text, scripted.stop_reason, scripted.usage, self.model, self.backend
        )


class FakeRegistry:
    """Hands out the same fake for both backends unless told otherwise."""

    def __init__(
        self, hosted: FakeProvider | None = None, local: FakeProvider | None = None
    ) -> None:
        self.hosted = hosted or FakeProvider("fake-hosted")
        self.local = local or FakeProvider("fake-local", backend="local")

    def get(self, backend: Backend) -> LLMClient:
        return self.hosted if backend == "hosted" else self.local
