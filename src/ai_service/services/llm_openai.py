"""Adapter for every server that speaks the OpenAI chat-completions protocol.

One class serves Gemini (its OpenAI-compatible endpoint), OpenAI itself, and Ollama; only the
base URL, key and model name differ. This is the only file that imports the OpenAI SDK.
"""

import logging
import re
from collections.abc import AsyncGenerator
from typing import Any, cast

import httpx2
from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AsyncOpenAI,
    OpenAIError,
)

from ai_service.services.llm_types import (
    CONTENT_FILTER,
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
    QuotaExhaustedError,
    RateLimitedError,
    StreamEvent,
    StreamStart,
    TextDelta,
    Usage,
)

logger = logging.getLogger("ai_service.llm")

_CONTEXT_HINTS = (
    "context length",
    "context_length",
    "maximum context",
    "too long",
    "too many tokens",
    "token limit",
    "exceeds the maximum",
)
_DAILY_QUOTA_HINTS = ("insufficient_quota", "per day", "perday", "daily")


# Gemini does not send a retry-after header with its 429: the wait is in the message instead
# ("Please retry in 23.6s.") and in the error details.
_RETRY_IN_TEXT = re.compile(r"retry in ([0-9]+(?:\.[0-9]+)?)\s*s", re.IGNORECASE)


def _retry_after(exc: APIStatusError) -> float | None:
    """How many seconds the provider asked us to wait, from the header or the error text."""
    raw = exc.response.headers.get("retry-after")
    if raw is not None:
        try:
            return max(float(raw), 0.0)
        except ValueError:  # an HTTP date instead of seconds: fall through to the text
            pass
    try:
        match = _RETRY_IN_TEXT.search(exc.response.text)
    except httpx2.ResponseNotRead:
        return None
    return float(match.group(1)) if match else None


def map_openai_error(exc: OpenAIError, what: str) -> LLMError:
    """Turn an OpenAI SDK exception into one of my error types (see llm_types)."""
    if isinstance(exc, APITimeoutError):  # must come before APIConnectionError, its parent
        return LLMTimeoutError(f"{what}: timed out")
    if isinstance(exc, APIConnectionError):
        return LLMConnectionError(f"{what}: could not connect")
    if isinstance(exc, APIStatusError):
        status = exc.status_code
        text = f"{exc.code or ''} {exc.message}".lower()
        message = f"{what}: HTTP {status}: {exc.message}"
        if status == 429:
            if any(hint in text for hint in _DAILY_QUOTA_HINTS):
                return QuotaExhaustedError(message)
            return RateLimitedError(message, retry_after=_retry_after(exc))
        if status in (401, 403):
            return AuthError(message)
        if status == 413 or (status == 400 and any(hint in text for hint in _CONTEXT_HINTS)):
            return ContextTooLongError(message)
        if status in (408, 409) or status >= 500:
            return OverloadedError(message, retry_after=_retry_after(exc))
        return BadRequestError(message)
    return LLMError(f"{what}: {exc}")


def _params(messages: list[ChatMessage]) -> Any:
    # the SDK's own type is a strict union of many message kinds; plain dicts are what it sends
    return [{"role": m.role, "content": m.content} for m in messages]


def usage_from_openai(usage: Any) -> Usage:
    """`prompt_tokens` includes the cached part, so subtract it: Usage.input_tokens is new input."""
    details = getattr(usage, "prompt_tokens_details", None)
    cached = int(getattr(details, "cached_tokens", 0) or 0)
    prompt = int(usage.prompt_tokens or 0)
    completion = int(usage.completion_tokens or 0)
    # A thinking model (gemini-3-flash-preview) bills its thinking as output but does not count it
    # in completion_tokens: total_tokens still has it. Seen live: prompt 8, completion 1, total 49.
    total = int(getattr(usage, "total_tokens", 0) or 0)
    return Usage(
        input_tokens=max(prompt - cached, 0),
        output_tokens=max(completion, total - prompt),
        cache_read_tokens=cached,
    )


class OpenAICompatProvider:
    def __init__(
        self,
        client: AsyncOpenAI,
        model: str,
        max_output_tokens: int,
        *,
        backend: str = "hosted",
    ) -> None:
        self._client = client
        self.model = model
        self.backend = backend
        self._max_output_tokens = max_output_tokens

    async def generate(self, request: LLMRequest) -> LLMResponse:
        try:
            response = await self._client.chat.completions.create(
                model=self.model,
                messages=_params(request.messages),
                max_tokens=request.max_tokens or self._max_output_tokens,
            )
        except OpenAIError as exc:
            raise map_openai_error(exc, "the call failed") from exc
        return self._to_response(response)

    async def generate_structured(
        self, request: LLMRequest, *, schema_name: str, schema: dict[str, Any]
    ) -> LLMResponse:
        try:
            response = await self._client.chat.completions.create(
                model=self.model,
                messages=_params(request.messages),
                temperature=0,
                max_tokens=request.max_tokens or self._max_output_tokens,
                response_format=cast(
                    Any,
                    {
                        "type": "json_schema",
                        "json_schema": {"name": schema_name, "schema": schema, "strict": True},
                    },
                ),
            )
        except OpenAIError as exc:
            raise map_openai_error(exc, "the call failed") from exc
        return self._to_response(response)

    def _to_response(self, response: Any) -> LLMResponse:
        usage = usage_from_openai(response.usage) if response.usage else None
        if not response.choices:
            # Gemini answers a blocked prompt with no candidates at all: that is a refusal.
            return LLMResponse("", CONTENT_FILTER, usage, self.model, self.backend)
        choice = response.choices[0]
        return LLMResponse(
            text=choice.message.content or "",
            stop_reason=choice.finish_reason,
            usage=usage,
            model=self.model,
            backend=self.backend,
        )

    async def stream(self, request: LLMRequest) -> AsyncGenerator[StreamEvent]:
        try:
            stream = await self._client.chat.completions.create(
                model=self.model,
                messages=_params(request.messages),
                max_tokens=request.max_tokens or self._max_output_tokens,
                stream=True,
                stream_options={"include_usage": True},  # token counts arrive in the last chunk
            )
        except OpenAIError as exc:
            raise map_openai_error(exc, "could not start the stream") from exc
        try:
            yield StreamStart(self.model, self.backend)
            stop_reason: str | None = None
            usage: Usage | None = None
            async for chunk in stream:
                if chunk.usage:
                    usage = usage_from_openai(chunk.usage)
                if not chunk.choices:  # a usage-only chunk
                    continue
                choice = chunk.choices[0]
                if choice.delta.content:
                    yield TextDelta(choice.delta.content)
                if choice.finish_reason:
                    stop_reason = choice.finish_reason
            yield Finish(stop_reason, usage)
        except OpenAIError as exc:
            raise map_openai_error(exc, "the stream failed") from exc
        finally:
            await stream.close()  # stops the upstream call, so no tokens are generated for nobody


class OllamaProvider(OpenAICompatProvider):
    """The local model. Ollama speaks the same protocol, so only the defaults differ."""

    def __init__(self, client: AsyncOpenAI, model: str, max_output_tokens: int) -> None:
        super().__init__(client, model, max_output_tokens, backend="local")
