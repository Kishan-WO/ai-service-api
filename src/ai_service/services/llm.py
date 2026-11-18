"""The language-model layer: one `LLMClient` interface, adapters behind it, and the registry.

Gemini (hosted) and Ollama (local) both speak the OpenAI chat-completions protocol, Anthropic has
its own adapter, and every backend is wrapped the same way:

    Fallback( Retrying( Limited( Accounting( adapter ) ) ) , the same for the second backend)

Routes depend on `LLMRegistry` and `LLMClient` only, so tests can swap in a fake that never
touches the network. The types live in `llm_types`; they are re-exported here so callers can
import everything from one place.
"""

import logging

import httpx2
from anthropic import AsyncAnthropic
from openai import AsyncOpenAI

from ai_service.core.config import Settings
from ai_service.core.exceptions import LLMNotConfiguredError
from ai_service.services.llm_accounting import AccountingClient, CallRecorder
from ai_service.services.llm_anthropic import AnthropicProvider
from ai_service.services.llm_openai import OllamaProvider, OpenAICompatProvider
from ai_service.services.llm_types import (
    CONTENT_FILTER,
    LENGTH,
    REFUSAL_REASONS,
    STOP,
    AuthError,
    Backend,
    BadRequestError,
    CallContext,
    ChatMessage,
    ContextTooLongError,
    Finish,
    LLMClient,
    LLMConnectionError,
    LLMError,
    LLMRegistry,
    LLMRequest,
    LLMResponse,
    LLMTimeoutError,
    OverloadedError,
    QuotaExhaustedError,
    RateLimitedError,
    Role,
    StreamEvent,
    StreamStart,
    TextDelta,
    Usage,
)
from ai_service.services.llm_wrappers import (
    FallbackClient,
    LimitedClient,
    RetryingClient,
    RetryPolicy,
)

logger = logging.getLogger("ai_service.llm")

__all__ = [
    "CONTENT_FILTER",
    "LENGTH",
    "REFUSAL_REASONS",
    "STOP",
    "AuthError",
    "Backend",
    "BadRequestError",
    "CallContext",
    "ChatMessage",
    "ContextTooLongError",
    "Finish",
    "LLMClient",
    "LLMConnectionError",
    "LLMError",
    "LLMRegistry",
    "LLMRequest",
    "LLMResponse",
    "LLMTimeoutError",
    "OllamaProvider",
    "OpenAICompatProvider",
    "OverloadedError",
    "QuotaExhaustedError",
    "RateLimitedError",
    "Role",
    "SettingsLLMRegistry",
    "StreamEvent",
    "StreamStart",
    "TextDelta",
    "Usage",
]


class SettingsLLMRegistry:
    """Builds each backend once, on first use, from the settings."""

    def __init__(self, settings: Settings, recorder: CallRecorder | None = None) -> None:
        self._settings = settings
        self._recorder = recorder
        self._stacks: dict[Backend, LLMClient] = {}  # one per backend: the limits are shared
        self._routes: dict[Backend, LLMClient] = {}
        self._sdk_clients: list[AsyncOpenAI | AsyncAnthropic] = []

    def get(self, backend: Backend) -> LLMClient:
        if backend not in self._routes:
            self._routes[backend] = self._route(backend)
        return self._routes[backend]

    def _route(self, backend: Backend) -> LLMClient:
        primary = self._stack(backend)
        second = self._settings.LLM_FALLBACK_BACKEND
        if second is None or second == backend:
            return primary
        try:
            return FallbackClient([primary, self._stack(second)])
        except LLMNotConfiguredError:
            logger.warning("fallback backend %s is not configured; running without it", second)
            return primary

    def _stack(self, backend: Backend) -> LLMClient:
        if backend not in self._stacks:
            s = self._settings
            client: LLMClient = AccountingClient(
                self._adapter(backend), prices=s.LLM_PRICES, recorder=self._recorder
            )
            client = LimitedClient(
                client,
                max_concurrency=s.LLM_MAX_CONCURRENCY,
                # the per-minute limit is the hosted free tier's; the others have none
                per_minute={
                    "hosted": s.LLM_REQUESTS_PER_MINUTE,
                    "hosted_large": s.LLM_LARGE_REQUESTS_PER_MINUTE,
                }.get(backend, 0),
            )
            self._stacks[backend] = RetryingClient(client, RetryPolicy.from_settings(s))
        return self._stacks[backend]

    def _adapter(self, backend: Backend) -> LLMClient:
        s = self._settings
        timeout = httpx2.Timeout(s.LLM_TIMEOUT_SECONDS, connect=5.0)
        # max_retries=0 everywhere: RetryingClient retries, so the SDK must not do it as well
        if backend in ("hosted", "hosted_large"):
            model = s.LLM_LARGE_MODEL if backend == "hosted_large" else s.LLM_MODEL
            if s.LLM_API_KEY is None or not model:
                raise LLMNotConfiguredError(
                    "Set LLM_API_KEY and "
                    + ("LLM_LARGE_MODEL" if backend == "hosted_large" else "LLM_MODEL")
                    + " to use this hosted model."
                )
            openai_client = AsyncOpenAI(
                api_key=s.LLM_API_KEY.get_secret_value(),
                base_url=s.LLM_BASE_URL,
                timeout=timeout,
                max_retries=0,
            )
            self._sdk_clients.append(openai_client)
            return OpenAICompatProvider(
                openai_client, model, s.LLM_MAX_OUTPUT_TOKENS, backend=backend
            )
        if backend == "anthropic":
            if s.ANTHROPIC_API_KEY is None or not s.ANTHROPIC_MODEL:
                raise LLMNotConfiguredError(
                    "Set ANTHROPIC_API_KEY and ANTHROPIC_MODEL to use the anthropic backend."
                )
            anthropic_client = AsyncAnthropic(
                api_key=s.ANTHROPIC_API_KEY.get_secret_value(),
                timeout=timeout,
                max_retries=0,
            )
            self._sdk_clients.append(anthropic_client)
            return AnthropicProvider(anthropic_client, s.ANTHROPIC_MODEL, s.LLM_MAX_OUTPUT_TOKENS)
        # Ollama ignores the key, but the SDK insists on a non-empty one.
        local_client = AsyncOpenAI(
            api_key="ollama", base_url=s.LOCAL_LLM_BASE_URL, timeout=timeout, max_retries=0
        )
        self._sdk_clients.append(local_client)
        return OllamaProvider(local_client, s.LOCAL_LLM_MODEL, s.LLM_MAX_OUTPUT_TOKENS)

    async def aclose(self) -> None:
        for client in self._sdk_clients:
            await client.close()
