"""A fake language model: scripted answers, no network, and it records how it was used."""

import asyncio
from collections.abc import AsyncGenerator
from typing import Any

from ai_service.services.llm import (
    Backend,
    ChatMessage,
    Finish,
    JsonCompletion,
    LLMError,
    LLMProvider,
    StreamEvent,
    TextDelta,
)


class FakeProvider:
    def __init__(
        self,
        model: str = "fake-model",
        *,
        texts: tuple[str, ...] = ("Hello", " there", "!"),
        fail_before_first: bool = False,
        fail_at: int | None = None,  # raise LLMError instead of sending text number `fail_at`
        delay: float = 0.0,  # pause after each piece
        first_delay: float = 0.0,  # pause before the first piece (a slow model)
        json_replies: list[JsonCompletion] | None = None,
        fail_json: bool = False,
    ) -> None:
        self.model = model
        self.texts = texts
        self.fail_before_first = fail_before_first
        self.fail_at = fail_at
        self.delay = delay
        self.first_delay = first_delay
        self.json_replies = list(json_replies or [])
        self.fail_json = fail_json
        self.calls: list[list[ChatMessage]] = []  # the messages of every call, in order
        self.json_calls: list[dict[str, Any]] = []
        self.closed = False  # True once the upstream stream has been closed

    async def stream_chat(self, messages: list[ChatMessage]) -> AsyncGenerator[StreamEvent]:
        self.calls.append(messages)
        self.closed = False
        try:
            if self.fail_before_first:
                raise LLMError("the provider is down")
            if self.first_delay:
                await asyncio.sleep(self.first_delay)
            for index, text in enumerate(self.texts):
                if self.fail_at == index:
                    raise LLMError("the stream broke")
                yield TextDelta(text)
                if self.delay:
                    await asyncio.sleep(self.delay)
            yield Finish("stop", input_tokens=len(messages), output_tokens=len(self.texts))
        finally:
            self.closed = True

    async def complete_json(
        self,
        messages: list[ChatMessage],
        *,
        schema_name: str,
        schema: dict[str, Any],
        max_tokens: int | None = None,
    ) -> JsonCompletion:
        self.json_calls.append(
            {
                "messages": list(messages),
                "name": schema_name,
                "schema": schema,
                "max_tokens": max_tokens,
            }
        )
        if self.fail_json:
            raise LLMError("the provider is down")
        return self.json_replies.pop(0)


class FakeRegistry:
    """Hands out the same fake for both backends unless told otherwise."""

    def __init__(
        self, hosted: FakeProvider | None = None, local: FakeProvider | None = None
    ) -> None:
        self.hosted = hosted or FakeProvider("fake-hosted")
        self.local = local or FakeProvider("fake-local")

    def get(self, backend: Backend) -> LLMProvider:
        return self.hosted if backend == "hosted" else self.local
