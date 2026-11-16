"""The shapes every language-model adapter speaks: requests, responses, usage and errors.

Nothing in here imports a provider SDK. Routes, services and tests depend on these types only,
so a provider can be swapped without touching them.
"""

from collections.abc import AsyncGenerator
from dataclasses import dataclass, field
from typing import Any, Literal, Protocol

Backend = Literal["hosted", "local", "anthropic"]
Role = Literal["system", "user", "assistant"]

# Stop reasons are mapped to this small vocabulary by every adapter.
STOP = "stop"  # the model finished by itself
LENGTH = "length"  # cut off by the output-token limit
CONTENT_FILTER = "content_filter"  # the model or a safety filter refused to answer
REFUSAL_REASONS = frozenset({CONTENT_FILTER})


# ---------- errors


class LLMError(Exception):
    """A provider call failed. The original error is chained; routes show a generic message.

    `retryable`   trying the same call again later can work (rate limit, overload, timeout)
    `fallback_ok` another provider may succeed even though waiting here will not
    """

    retryable = False
    fallback_ok = False

    def __init__(self, message: str, *, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retry_after = retry_after  # seconds the provider asked us to wait, if it said so

    @property
    def kind(self) -> str:
        return type(self).__name__


class RateLimitedError(LLMError):
    """429: too many requests or tokens per minute."""

    retryable = True
    fallback_ok = True


class OverloadedError(LLMError):
    """5xx / 529: the provider has no capacity or has a bug right now."""

    retryable = True
    fallback_ok = True


class LLMTimeoutError(LLMError):
    retryable = True
    fallback_ok = True


class LLMConnectionError(LLMError):
    retryable = True
    fallback_ok = True


class QuotaExhaustedError(LLMError):
    """The daily limit or the money is used up. Waiting does not help; another provider can."""

    fallback_ok = True


class ContextTooLongError(LLMError):
    """Input plus the output limit is bigger than the model's window."""


class AuthError(LLMError):
    """401 / 403: wrong key, or no access to the model."""


class BadRequestError(LLMError):
    """400 / 404 and anything else that will fail the same way again."""


# ---------- messages, requests, answers


@dataclass(frozen=True)
class ChatMessage:
    role: Role
    content: str


@dataclass(frozen=True)
class CallContext:
    """Who and what a call is for. Written to the log line and to the `llm_calls` row."""

    request_id: str | None = None
    tenant_id: str | None = None
    user_id: str | None = None
    feature: str = "unknown"  # "chat", "extract", ...


@dataclass(frozen=True)
class LLMRequest:
    messages: list[ChatMessage]
    max_tokens: int | None = None  # None = the adapter's default cap
    cache_system: bool = False  # the system prompt is stable: let the provider cache it
    context: CallContext = field(default_factory=CallContext)


@dataclass(frozen=True)
class Usage:
    """Token counts in one shape for every provider.

    `input_tokens` counts only NEW input. Cached input is counted apart (OpenAI style counts it
    inside prompt_tokens, Anthropic does not; the adapters make both look like this).
    """

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0

    @property
    def prompt_tokens(self) -> int:
        """Everything that was sent, cached or not."""
        return self.input_tokens + self.cache_read_tokens + self.cache_write_tokens

    def __add__(self, other: Usage) -> Usage:
        return Usage(
            self.input_tokens + other.input_tokens,
            self.output_tokens + other.output_tokens,
            self.cache_read_tokens + other.cache_read_tokens,
            self.cache_write_tokens + other.cache_write_tokens,
        )


@dataclass(frozen=True)
class LLMResponse:
    text: str
    stop_reason: str | None
    usage: Usage | None  # None = the provider did not say
    model: str  # the model that really answered (a fallback can differ from the one asked for)
    backend: str


@dataclass(frozen=True)
class StreamStart:
    """The first event of a stream: which model is answering. Carries no text."""

    model: str
    backend: str


@dataclass(frozen=True)
class TextDelta:
    """A piece of the answer."""

    text: str


@dataclass(frozen=True)
class Finish:
    """The last event of a stream: why it ended, and the token counts if the provider gave them."""

    stop_reason: str | None
    usage: Usage | None

    @property
    def input_tokens(self) -> int | None:
        return self.usage.prompt_tokens if self.usage else None

    @property
    def output_tokens(self) -> int | None:
        return self.usage.output_tokens if self.usage else None

    @property
    def cache_read_tokens(self) -> int | None:
        return self.usage.cache_read_tokens if self.usage else None


StreamEvent = StreamStart | TextDelta | Finish


class LLMClient(Protocol):
    """What the rest of the app needs from a model. Adapters and wrappers both fit it."""

    backend: str
    model: str

    async def generate(self, request: LLMRequest) -> LLMResponse:
        """One full answer. Raises LLMError."""
        ...

    def stream(self, request: LLMRequest) -> AsyncGenerator[StreamEvent]:
        """Yield a StreamStart, many TextDelta, then one Finish. Raises LLMError.

        Closing the generator closes the upstream call.
        """
        ...

    async def generate_structured(
        self, request: LLMRequest, *, schema_name: str, schema: dict[str, Any]
    ) -> LLMResponse:
        """One answer constrained to the JSON schema. `text` is JSON; the caller validates it."""
        ...


class LLMRegistry(Protocol):
    def get(self, backend: Backend) -> LLMClient: ...
