"""Tests for the intent router — Day 8, Task 1.

What is covered
---------------
- Rule-based fast path (regex matching, no model calls)
- Classifier output parser (happy path, bare label, bad label → unclear)
- Full route() logic using a fake LLM client:
    - known intent → small client answers with specialised prompt
    - unclear intent → large client answers with general prompt
    - classifier failure (LLMError) → falls back to unclear → large client
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Any

import httpx
import pytest

from ai_service.core.exceptions import LLMUnavailableError
from ai_service.services.llm_types import (
    LLMError,
    LLMRequest,
    LLMResponse,
    Usage,
)
from ai_service.services.prompt_registry import get_prompt
from ai_service.services.router_service import (
    KNOWN_INTENTS,
    _parse_intent,
    _rule_based_intent,
    route,
)

from .fakes import FakeRegistry

# ---------------------------------------------------------------------------
# Fake LLM client
# ---------------------------------------------------------------------------


class FakeLLMClient:
    """Minimal LLMClient-compatible fake. Records every request it receives."""

    def __init__(self, reply: str, backend: str = "fake", model: str = "fake-model") -> None:
        self.reply = reply
        self.backend = backend
        self.model = model
        self.calls: list[LLMRequest] = []

    async def generate(self, request: LLMRequest) -> LLMResponse:
        self.calls.append(request)
        return LLMResponse(
            text=self.reply,
            stop_reason="stop",
            usage=Usage(input_tokens=10, output_tokens=5),
            model=self.model,
            backend=self.backend,
        )

    async def generate_structured(
        self, request: LLMRequest, *, schema_name: str, schema: dict[str, Any]
    ) -> LLMResponse:
        return await self.generate(request)

    def stream(self, request: LLMRequest) -> AsyncGenerator[Any]:
        raise NotImplementedError

    async def aclose(self) -> None:
        pass


class ErrorLLMClient(FakeLLMClient):
    """Always raises LLMError on generate()."""

    async def generate(self, request: LLMRequest) -> LLMResponse:
        self.calls.append(request)
        raise LLMError("simulated provider failure")


# ---------------------------------------------------------------------------
# Unit: rule-based fast path
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "message, expected",
    [
        ("I was charged twice for the same installment", "complaint"),
        ("What is your refund policy?", "fees"),
        ("I can't login, no access after paying", "complaint"),
        ("Hi!", "other"),
        ("Thanks", "other"),
        ("Hi, I want to know the eligibility criteria", None),  # a greeting inside a question
        ("Hello, is anyone there?", None),
        ("I want a refund for my payment", None),  # no rule: the model decides
        ("What is the syllabus?", None),  # no rule → None → classifier
        ("When does the batch start?", None),
    ],
)
def test_rule_based_intent(message: str, expected: str | None) -> None:
    assert _rule_based_intent(message) == expected


# ---------------------------------------------------------------------------
# Unit: classifier output parser
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("Intent: asks about fees\nCATEGORY: fees", "fees"),
        ("Intent: joining the course\nCATEGORY: admission", "admission"),
        ("CATEGORY: schedule", "schedule"),
        ("academic", "academic"),  # bare label
        ("COMPLAINT", "complaint"),  # bare label, uppercase
        ("I don't know", "unclear"),  # unrecognised → unclear
        ("CATEGORY: unknown_label", "unclear"),
        ("", "unclear"),
    ],
)
def test_parse_intent(raw: str, expected: str) -> None:
    assert _parse_intent(raw) == expected


# ---------------------------------------------------------------------------
# Integration: route() with fake clients
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_route_rule_match_no_classify_call() -> None:
    """Rule-based match: classifier is never called."""
    small = FakeLLMClient(reply="Here's some help with your refund.")
    large = FakeLLMClient(reply="Large model answer")

    result = await route("What is your refund policy?", small_client=small, large_client=large)

    assert result.rule_matched is True
    assert result.intent == "fees"
    # Rule path → no classify call; only the answer call goes to small
    assert len(small.calls) == 1  # one answer call
    assert len(large.calls) == 0
    assert result.classify_latency_ms == 0.0
    assert result.answer == "Here's some help with your refund."


@pytest.mark.asyncio
async def test_route_known_intent_uses_small_client() -> None:
    """Classifier returns a known intent → small client answers."""

    class SequenceFake(FakeLLMClient):
        def __init__(self, replies: list[str]) -> None:
            super().__init__(reply="", backend="fake-small", model="small-model")
            self._replies = iter(replies)

        async def generate(self, request: LLMRequest) -> LLMResponse:
            self.calls.append(request)
            text = next(self._replies)
            return LLMResponse(
                text=text,
                stop_reason="stop",
                usage=Usage(input_tokens=10, output_tokens=5),
                model=self.model,
                backend=self.backend,
            )

    small_seq = SequenceFake(
        replies=[
            "Intent: batch timing\nCATEGORY: schedule",  # classify
            "The batch starts on Monday.",  # answer
        ]
    )
    large = FakeLLMClient(reply="Large model fallback")

    result = await route(
        "When does the next batch start?",
        small_client=small_seq,
        large_client=large,
    )

    assert result.intent == "schedule"
    assert result.rule_matched is False
    assert result.answer == "The batch starts on Monday."
    assert result.answer_backend == "fake-small"
    assert len(large.calls) == 0  # large model never called
    assert len(small_seq.calls) == 2  # classify + answer


@pytest.mark.asyncio
async def test_route_unclear_intent_uses_large_client() -> None:
    """Classifier returns unrecognised label → unclear → large client answers."""

    class SequenceFake(FakeLLMClient):
        def __init__(self, replies: list[str], backend: str) -> None:
            super().__init__(reply="", backend=backend, model=f"{backend}-model")
            self._replies = iter(replies)

        async def generate(self, request: LLMRequest) -> LLMResponse:
            self.calls.append(request)
            text = next(self._replies)
            return LLMResponse(
                text=text,
                stop_reason="stop",
                usage=Usage(input_tokens=10, output_tokens=5),
                model=self.model,
                backend=self.backend,
            )

    small = SequenceFake(replies=["CATEGORY: gibberish_label"], backend="small")
    large = FakeLLMClient(reply="I'm not sure, but here's my best answer.", backend="large")

    result = await route(
        "asdfgh qwerty zxcvb",
        small_client=small,
        large_client=large,
    )

    assert result.intent == "unclear"
    assert result.answer_backend == "large"
    assert len(large.calls) == 1


@pytest.mark.asyncio
async def test_route_classifier_error_falls_back_to_unclear() -> None:
    """If the classifier raises LLMError → intent becomes unclear → large client answers."""
    small = ErrorLLMClient(reply="")
    large = FakeLLMClient(reply="General answer from large model.", backend="large")

    result = await route(
        "What is the meaning of life?",
        small_client=small,
        large_client=large,
    )

    assert result.intent == "unclear"
    assert result.answer_backend == "large"
    assert len(large.calls) == 1


# ---------------------------------------------------------------------------
# Added after the first review: answer failures, the prompts, the endpoint
# ---------------------------------------------------------------------------


class ClassifyThenFail(FakeLLMClient):
    """Classifies as fees, then fails on the answer call."""

    async def generate(self, request: LLMRequest) -> LLMResponse:
        self.calls.append(request)
        if request.context.feature == "router_classify":
            return LLMResponse("fees", "stop", Usage(10, 1), self.model, self.backend)
        raise LLMError("the answer call failed")


@pytest.mark.asyncio
async def test_a_failed_answer_call_is_a_clean_error_not_a_raw_llm_error() -> None:
    with pytest.raises(LLMUnavailableError):
        await route(
            "what does the course cost?",
            small_client=ClassifyThenFail(reply=""),
            large_client=FakeLLMClient(reply="unused"),
        )


@pytest.mark.asyncio
async def test_the_classifier_uses_prompt_v5_with_a_small_token_cap() -> None:
    small = FakeLLMClient(reply="fees", backend="small", model="small-model")
    await route("how much is the course?", small_client=small, large_client=FakeLLMClient("x"))

    classify, answer = small.calls
    assert (classify.context.prompt_name, classify.context.prompt_version) == (
        "classify_query",
        "v5",
    )
    assert classify.max_tokens == 20
    assert (answer.context.prompt_name, answer.context.prompt_version) == ("router_fees", "v2")


def test_every_intent_has_a_registry_prompt() -> None:
    for intent in KNOWN_INTENTS:
        assert get_prompt(f"router_{intent}", "v2").render().strip()
    assert "{{ message }}" in get_prompt("classify_query", "v5").template
    assert "unclear" in get_prompt("classify_query", "v5").template


ROUTE_URL = "/api/v1/route"


@pytest.mark.asyncio
async def test_post_route_answers_with_the_small_backend_and_reports_the_meta(
    client: httpx.AsyncClient, auth_headers: dict[str, str], llm: FakeRegistry
) -> None:
    llm.local = FakeLLMClient(reply="fees", backend="local", model="small")  # type: ignore[assignment]
    llm.hosted = FakeLLMClient(reply="large", backend="hosted", model="large")  # type: ignore[assignment]
    response = await client.post(
        ROUTE_URL, json={"message": "How much is the course?"}, headers=auth_headers
    )

    assert response.status_code == 200
    body = response.json()
    assert body["answer"] == "fees"
    assert (body["meta"]["intent"], body["meta"]["answer_backend"]) == ("fees", "local")
    assert body["meta"]["rule_matched"] is False
    assert body["meta"]["classify_input_tokens"] == 10


@pytest.mark.asyncio
async def test_post_route_sends_an_unclear_message_to_the_large_backend(
    app: Any, client: httpx.AsyncClient, auth_headers: dict[str, str], llm: FakeRegistry
) -> None:
    llm.local = FakeLLMClient(reply="none of these", backend="local", model="small")  # type: ignore[assignment]
    llm.hosted = FakeLLMClient(reply="large", backend="hosted", model="large")  # type: ignore[assignment]
    from ai_service.core.config import get_settings

    no_large = get_settings().model_copy(update={"LLM_LARGE_MODEL": ""})
    app.dependency_overrides[get_settings] = lambda: no_large  # whatever the .env says
    response = await client.post(ROUTE_URL, json={"message": "asdf qwerty"}, headers=auth_headers)

    assert response.status_code == 200
    assert response.json()["meta"]["intent"] == "unclear"
    assert response.json()["meta"]["answer_backend"] == "hosted"
    assert response.json()["answer"] == "large"


@pytest.mark.asyncio
async def test_post_route_answers_502_when_the_answer_call_fails(
    client: httpx.AsyncClient, auth_headers: dict[str, str], llm: FakeRegistry
) -> None:
    llm.local = ClassifyThenFail(reply="", backend="local", model="small")  # type: ignore[assignment]
    response = await client.post(
        ROUTE_URL, json={"message": "How much is the course?"}, headers=auth_headers
    )

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "LLM_UNAVAILABLE"


@pytest.mark.asyncio
async def test_post_route_needs_a_login_and_a_message(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    assert (await client.post(ROUTE_URL, json={"message": "hi"})).status_code == 401
    assert (
        await client.post(ROUTE_URL, json={"message": "   "}, headers=auth_headers)
    ).status_code == 422


@pytest.mark.asyncio
async def test_the_large_model_gets_a_bigger_answer_cap_than_the_small_one() -> None:
    """A thinking model spends most of its cap on thinking: 1000 tokens left one answer cut."""
    small = FakeLLMClient(reply="fees", backend="small", model="small-model")
    await route("how much is the course?", small_client=small, large_client=FakeLLMClient("x"))
    assert [c.max_tokens for c in small.calls] == [20, 512]  # the classifier, then the small answer

    unclear = FakeLLMClient(reply="unclear", backend="small", model="small-model")
    large = FakeLLMClient(reply="large answer", backend="large", model="large-model")
    await route("a long, tangled request", small_client=unclear, large_client=large)
    assert large.calls[0].max_tokens == 2000


@pytest.mark.asyncio
async def test_post_route_uses_the_large_model_setting_for_unclear_messages(
    app: Any, client: httpx.AsyncClient, auth_headers: dict[str, str], llm: FakeRegistry
) -> None:
    from ai_service.core.config import get_settings

    llm.local = FakeLLMClient(reply="none of these", backend="local", model="small")  # type: ignore[assignment]
    llm.hosted_large = FakeLLMClient(  # type: ignore[assignment]
        reply="from large", backend="hosted_large", model="big"
    )
    settings = get_settings().model_copy(update={"LLM_LARGE_MODEL": "big"})
    app.dependency_overrides[get_settings] = lambda: settings

    response = await client.post(ROUTE_URL, json={"message": "asdf qwerty"}, headers=auth_headers)

    assert response.status_code == 200
    assert response.json()["meta"]["answer_backend"] == "hosted_large"
    assert response.json()["answer"] == "from large"
