"""The registry builds each backend from the settings, with the retry and fallback layers on top."""

from pathlib import Path

import pytest

from ai_service.core.config import Settings
from ai_service.core.exceptions import LLMNotConfiguredError
from ai_service.services.chat_service import system_prompt
from ai_service.services.llm import SettingsLLMRegistry
from ai_service.services.llm_wrappers import FallbackClient, RetryingClient


def settings(**overrides: object) -> Settings:
    values: dict[str, object] = {
        "SECRET_KEY": "x" * 32,
        "DATABASE_URL": "sqlite+aiosqlite://",
        "LLM_API_KEY": "key",
        "LLM_MODEL": "hosted-model",
        "LOCAL_LLM_MODEL": "local-model",
    }
    return Settings(**{**values, **overrides})  # type: ignore[arg-type]


async def test_each_backend_is_retried_and_knows_its_model() -> None:
    registry = SettingsLLMRegistry(settings())
    hosted, local = registry.get("hosted"), registry.get("local")

    assert isinstance(hosted, RetryingClient)
    assert (hosted.backend, hosted.model) == ("hosted", "hosted-model")
    assert (local.backend, local.model) == ("local", "local-model")
    assert registry.get("hosted") is hosted  # built once, so the limits are shared
    await registry.aclose()


async def test_the_sdk_does_not_retry_on_its_own() -> None:
    registry = SettingsLLMRegistry(settings())
    registry.get("hosted")
    registry.get("local")
    # RetryingClient retries; an SDK that also retried would multiply the calls
    assert [client.max_retries for client in registry._sdk_clients] == [0, 0]
    await registry.aclose()


async def test_a_fallback_backend_wraps_the_primary() -> None:
    registry = SettingsLLMRegistry(settings(LLM_FALLBACK_BACKEND="local"))
    client = registry.get("hosted")

    assert isinstance(client, FallbackClient)
    assert (client.backend, client.model) == ("hosted", "hosted-model")
    # the fallback is never wrapped in itself
    assert isinstance(registry.get("local"), RetryingClient)
    await registry.aclose()


async def test_a_fallback_that_is_not_configured_is_skipped_not_fatal() -> None:
    registry = SettingsLLMRegistry(settings(LLM_FALLBACK_BACKEND="anthropic"))  # no key
    assert isinstance(registry.get("hosted"), RetryingClient)
    await registry.aclose()


def test_a_backend_without_its_key_is_reported_as_not_configured() -> None:
    registry = SettingsLLMRegistry(settings(LLM_API_KEY=None))
    with pytest.raises(LLMNotConfiguredError):
        registry.get("hosted")
    with pytest.raises(LLMNotConfiguredError):
        registry.get("anthropic")


def test_the_system_prompt_comes_from_the_file_when_one_is_set(tmp_path: Path) -> None:
    prompt_file = tmp_path / "prompt.md"
    prompt_file.write_text("  You are the long, stable prompt.  \n", encoding="utf-8")

    assert system_prompt(settings(CHAT_SYSTEM_PROMPT="short")) == "short"
    assert system_prompt(settings(CHAT_SYSTEM_PROMPT_FILE=str(prompt_file))) == (
        "You are the long, stable prompt."
    )


def test_the_shipped_system_prompt_is_long_enough_to_be_cached() -> None:
    path = Path(__file__).parent.parent / "src" / "ai_service" / "prompts" / "chat_system.md"
    # about 4 characters per token; providers cache prefixes only above a minimum size
    assert len(path.read_text(encoding="utf-8")) > 16_000


def test_a_blank_value_in_the_env_file_means_not_set() -> None:
    # `.env.example` ships `LLM_API_KEY=`, `ANTHROPIC_API_KEY=` and `LLM_FALLBACK_BACKEND=` empty
    blank = settings(LLM_API_KEY="", ANTHROPIC_API_KEY="  ", LLM_FALLBACK_BACKEND="")
    assert blank.LLM_API_KEY is None
    assert blank.ANTHROPIC_API_KEY is None
    assert blank.LLM_FALLBACK_BACKEND is None
    with pytest.raises(LLMNotConfiguredError):
        SettingsLLMRegistry(blank).get("hosted")
