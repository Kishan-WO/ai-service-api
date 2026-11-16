"""Adapter for Anthropic's Messages API. This is the only file that imports the Anthropic SDK.

What differs from the OpenAI style, and is hidden here:
  - the system prompt is not a message but a separate `system` parameter;
  - the reply is a list of content blocks, and `max_tokens` is required;
  - there is no native "JSON schema" switch here: a tool whose input is my schema is forced, and
    its arguments are the answer (the classic tool-as-schema method);
  - cached input is reported apart from `input_tokens`, and marked with `cache_control`;
  - stop reasons have other names (`end_turn`, `max_tokens`, `refusal`).
"""

import json
import logging
from collections.abc import AsyncGenerator
from typing import Any

from anthropic import (
    AnthropicError,
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AsyncAnthropic,
)

from ai_service.services.llm_types import (
    CONTENT_FILTER,
    LENGTH,
    STOP,
    AuthError,
    BadRequestError,
    ChatMessage,
    ContextTooLongError,
    Finish,
    LLMConnectionError,
    LLMError,
    LLMRequest,
    LLMResponse,
    LLMTimeoutError,
    OverloadedError,
    RateLimitedError,
    StreamEvent,
    StreamStart,
    TextDelta,
    Usage,
)

logger = logging.getLogger("ai_service.llm")

_STOP_REASONS = {
    "end_turn": STOP,
    "stop_sequence": STOP,
    "tool_use": STOP,  # a forced tool call is how structured output ends
    "max_tokens": LENGTH,
    "refusal": CONTENT_FILTER,
}


def _retry_after(exc: APIStatusError) -> float | None:
    raw = exc.response.headers.get("retry-after")
    try:
        return max(float(raw), 0.0) if raw is not None else None
    except ValueError:
        return None


def map_anthropic_error(exc: AnthropicError, what: str) -> LLMError:
    if isinstance(exc, APITimeoutError):
        return LLMTimeoutError(f"{what}: timed out")
    if isinstance(exc, APIConnectionError):
        return LLMConnectionError(f"{what}: could not connect")
    if isinstance(exc, APIStatusError):
        status = exc.status_code
        message = f"{what}: HTTP {status}: {exc.message}"
        if status == 429:
            return RateLimitedError(message, retry_after=_retry_after(exc))
        if status in (401, 403):
            return AuthError(message)
        if status == 413 or (status == 400 and "too long" in exc.message.lower()):
            return ContextTooLongError(message)
        if status == 529 or status in (408, 409) or status >= 500:  # 529 = overloaded
            return OverloadedError(message, retry_after=_retry_after(exc))
        return BadRequestError(message)
    return LLMError(f"{what}: {exc}")


def usage_from_anthropic(usage: Any) -> Usage:
    """`input_tokens` here already excludes the cached parts, which are separate fields."""
    return Usage(
        input_tokens=int(getattr(usage, "input_tokens", 0) or 0),
        output_tokens=int(getattr(usage, "output_tokens", 0) or 0),
        cache_read_tokens=int(getattr(usage, "cache_read_input_tokens", 0) or 0),
        cache_write_tokens=int(getattr(usage, "cache_creation_input_tokens", 0) or 0),
    )


def split_system(messages: list[ChatMessage], *, cache: bool) -> tuple[list[dict[str, Any]], Any]:
    """Anthropic wants the system prompt apart from the messages."""
    system: list[dict[str, Any]] = [
        {"type": "text", "text": m.content} for m in messages if m.role == "system"
    ]
    if cache and system:
        # everything up to and including this block is cached (tools, then system)
        system[-1]["cache_control"] = {"type": "ephemeral"}
    rest: Any = [{"role": m.role, "content": m.content} for m in messages if m.role != "system"]
    return system, rest


class AnthropicProvider:
    backend = "anthropic"

    def __init__(self, client: AsyncAnthropic, model: str, max_output_tokens: int) -> None:
        self._client = client
        self.model = model
        self._max_output_tokens = max_output_tokens

    def _args(self, request: LLMRequest) -> dict[str, Any]:
        system, messages = split_system(request.messages, cache=request.cache_system)
        args: dict[str, Any] = {
            "model": self.model,
            "max_tokens": request.max_tokens or self._max_output_tokens,
            "messages": messages,
        }
        if system:
            args["system"] = system
        return args

    def _response(self, message: Any, text: str) -> LLMResponse:
        stop = message.stop_reason
        return LLMResponse(
            text=text,
            stop_reason=_STOP_REASONS.get(stop, stop) if stop else None,
            usage=usage_from_anthropic(message.usage) if message.usage else None,
            model=self.model,
            backend=self.backend,
        )

    async def generate(self, request: LLMRequest) -> LLMResponse:
        try:
            message = await self._client.messages.create(**self._args(request))
        except AnthropicError as exc:
            raise map_anthropic_error(exc, "the call failed") from exc
        text = "".join(block.text for block in message.content if block.type == "text")
        return self._response(message, text)

    async def generate_structured(
        self, request: LLMRequest, *, schema_name: str, schema: dict[str, Any]
    ) -> LLMResponse:
        args = self._args(request)
        args["tools"] = [
            {
                "name": schema_name,
                "description": "Return the extracted data.",
                "input_schema": schema,
            }
        ]
        args["tool_choice"] = {"type": "tool", "name": schema_name}
        try:
            message = await self._client.messages.create(**args)
        except AnthropicError as exc:
            raise map_anthropic_error(exc, "the call failed") from exc
        for block in message.content:
            if block.type == "tool_use":
                return self._response(message, json.dumps(block.input))
        # no tool call: a refusal, or a cut-off before the call; the stop reason says which
        return self._response(message, "")

    async def stream(self, request: LLMRequest) -> AsyncGenerator[StreamEvent]:
        try:
            manager = self._client.messages.stream(**self._args(request))
            stream = await manager.__aenter__()
        except AnthropicError as exc:
            raise map_anthropic_error(exc, "could not start the stream") from exc
        try:
            yield StreamStart(self.model, self.backend)
            async for text in stream.text_stream:
                if text:
                    yield TextDelta(text)
            final = await stream.get_final_message()
            response = self._response(final, "")
            yield Finish(response.stop_reason, response.usage)
        except AnthropicError as exc:
            raise map_anthropic_error(exc, "the stream failed") from exc
        finally:
            await manager.__aexit__(None, None, None)  # closes the upstream call
