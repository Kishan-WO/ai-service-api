"""Language-model providers behind one small interface.

Gemini (hosted) and Ollama (local) both speak the OpenAI chat-completions protocol, so one SDK
class serves both; only the base URL, key and model name differ. Routes depend on the
`LLMProvider` protocol, so tests can swap in a fake that never touches the network.
"""

import logging
from collections.abc import AsyncGenerator
from dataclasses import dataclass
from typing import Any, Literal, Protocol, cast

from openai import AsyncOpenAI, OpenAIError

from ai_service.core.config import Settings
from ai_service.core.exceptions import LLMNotConfiguredError

logger = logging.getLogger("ai_service.llm")

Backend = Literal["hosted", "local"]
Role = Literal["system", "user", "assistant"]


class LLMError(Exception):
    """The provider failed. The original error is chained; routes show a generic message."""


@dataclass(frozen=True)
class ChatMessage:
    role: Role
    content: str


@dataclass(frozen=True)
class TextDelta:
    """A piece of the answer."""

    text: str


@dataclass(frozen=True)
class Finish:
    """The last event of a stream: why it ended, and the token counts if the provider gave them."""

    stop_reason: str | None
    input_tokens: int | None
    output_tokens: int | None


StreamEvent = TextDelta | Finish


@dataclass(frozen=True)
class JsonCompletion:
    text: str
    stop_reason: str | None
    input_tokens: int | None
    output_tokens: int | None


class LLMProvider(Protocol):
    model: str

    def stream_chat(self, messages: list[ChatMessage]) -> AsyncGenerator[StreamEvent]:
        """Yield TextDelta events, then one Finish. Raises LLMError.

        Closing the generator closes the upstream call.
        """
        ...

    async def complete_json(
        self,
        messages: list[ChatMessage],
        *,
        schema_name: str,
        schema: dict[str, Any],
        max_tokens: int | None = None,
    ) -> JsonCompletion:
        """One non-streaming call whose answer is constrained to `schema`. Raises LLMError.

        `max_tokens` overrides the provider's default output cap for this call.
        """
        ...


class LLMRegistry(Protocol):
    def get(self, backend: Backend) -> LLMProvider: ...


def _as_params(messages: list[ChatMessage]) -> Any:
    return [{"role": m.role, "content": m.content} for m in messages]


class OpenAICompatProvider:
    def __init__(self, client: AsyncOpenAI, model: str, max_output_tokens: int) -> None:
        self._client = client
        self.model = model
        self._max_output_tokens = max_output_tokens

    async def stream_chat(self, messages: list[ChatMessage]) -> AsyncGenerator[StreamEvent]:
        try:
            stream = await self._client.chat.completions.create(
                model=self.model,
                messages=_as_params(messages),
                max_tokens=self._max_output_tokens,
                stream=True,
                stream_options={"include_usage": True},  # token counts arrive in the last chunk
            )
        except OpenAIError as exc:
            raise LLMError(f"could not start the stream: {exc}") from exc
        try:
            stop_reason: str | None = None
            input_tokens: int | None = None
            output_tokens: int | None = None
            async for chunk in stream:
                if chunk.usage:
                    input_tokens = chunk.usage.prompt_tokens
                    output_tokens = chunk.usage.completion_tokens
                if not chunk.choices:  # a usage-only chunk
                    continue
                choice = chunk.choices[0]
                if choice.delta.content:
                    yield TextDelta(choice.delta.content)
                if choice.finish_reason:
                    stop_reason = choice.finish_reason
            yield Finish(stop_reason, input_tokens, output_tokens)
        except OpenAIError as exc:
            raise LLMError(f"the stream failed: {exc}") from exc
        finally:
            await stream.close()  # stops the upstream call, so no tokens are generated for nobody

    async def complete_json(
        self,
        messages: list[ChatMessage],
        *,
        schema_name: str,
        schema: dict[str, Any],
        max_tokens: int | None = None,
    ) -> JsonCompletion:
        try:
            response = await self._client.chat.completions.create(
                model=self.model,
                messages=_as_params(messages),
                temperature=0,
                max_tokens=max_tokens or self._max_output_tokens,
                response_format=cast(
                    Any,
                    {
                        "type": "json_schema",
                        "json_schema": {"name": schema_name, "schema": schema, "strict": True},
                    },
                ),
            )
        except OpenAIError as exc:
            raise LLMError(f"the call failed: {exc}") from exc
        if not response.choices:
            raise LLMError("the provider returned no choices")
        choice = response.choices[0]
        usage = response.usage
        return JsonCompletion(
            text=choice.message.content or "",
            stop_reason=choice.finish_reason,
            input_tokens=usage.prompt_tokens if usage else None,
            output_tokens=usage.completion_tokens if usage else None,
        )


class SettingsLLMRegistry:
    """Builds each provider once, on first use, from the settings."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._providers: dict[Backend, OpenAICompatProvider] = {}
        self._clients: list[AsyncOpenAI] = []

    def get(self, backend: Backend) -> LLMProvider:
        if backend not in self._providers:
            self._providers[backend] = self._build(backend)
        return self._providers[backend]

    def _build(self, backend: Backend) -> OpenAICompatProvider:
        s = self._settings
        if backend == "hosted":
            if s.LLM_API_KEY is None or not s.LLM_MODEL:
                raise LLMNotConfiguredError(
                    "Set LLM_API_KEY and LLM_MODEL to use the hosted model."
                )
            client = AsyncOpenAI(
                api_key=s.LLM_API_KEY.get_secret_value(),
                base_url=s.LLM_BASE_URL,
                timeout=s.LLM_TIMEOUT_SECONDS,
                max_retries=s.LLM_MAX_RETRIES,
            )
            model = s.LLM_MODEL
        else:
            # Ollama ignores the key, but the SDK insists on a non-empty one.
            client = AsyncOpenAI(
                api_key="ollama",
                base_url=s.LOCAL_LLM_BASE_URL,
                timeout=s.LLM_TIMEOUT_SECONDS,
                max_retries=s.LLM_MAX_RETRIES,
            )
            model = s.LOCAL_LLM_MODEL
        self._clients.append(client)
        return OpenAICompatProvider(client, model, s.LLM_MAX_OUTPUT_TOKENS)

    async def aclose(self) -> None:
        for client in self._clients:
            await client.close()
