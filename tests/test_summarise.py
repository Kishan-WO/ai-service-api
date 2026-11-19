"""Day 8 task 4: summarise many documents in parallel, then combine (no network)."""

import asyncio
from typing import Any

import pytest

from ai_service.core.exceptions import LLMUnavailableError
from ai_service.services.llm_types import (
    LLMError,
    LLMRequest,
    LLMResponse,
    RateLimitedError,
    Usage,
)
from ai_service.services.prompt_registry import get_prompt
from ai_service.services.summarise_service import (
    Document,
    TooManyFailuresError,
    summarise_documents,
)

DOCS = [Document(f"d{i}", f"text of document {i}") for i in range(1, 11)]


class MapClient:
    """Answers a summary call from the document text and the combine call from the summaries.

    `fail` maps a document id to how many times its call raises (use a big number for "always").
    `delay` is how long every call takes, so parallel calls overlap in time.
    """

    backend = "hosted"
    model = "fake"

    def __init__(
        self,
        *,
        fail: dict[str, int] | None = None,
        error: LLMError | None = None,
        delay: float = 0.0,
        fail_combine: bool = False,
    ) -> None:
        self.fail = dict(fail or {})
        self.error = error or LLMError("boom")
        self.delay = delay
        self.fail_combine = fail_combine
        self.requests: list[str] = []

    async def generate(self, request: LLMRequest) -> LLMResponse:
        text = request.messages[-1].content
        self.requests.append(text)
        if self.delay:
            await asyncio.sleep(self.delay)
        if "<summaries>" in text:
            if self.fail_combine:
                raise LLMError("combine failed")
            return LLMResponse("OVERVIEW", "stop", Usage(50, 20), self.model, self.backend)
        for doc_id, left in self.fail.items():
            if f"text of document {doc_id[1:]}\n" in text + "\n" and left > 0:
                self.fail[doc_id] = left - 1
                raise self.error
        number = text.split("text of document ")[1].split("\n")[0]
        return LLMResponse(f"- summary {number}", "stop", Usage(10, 5), self.model, self.backend)

    async def generate_structured(self, *a: Any, **k: Any) -> LLMResponse:
        raise NotImplementedError

    def stream(self, *a: Any, **k: Any) -> Any:
        raise NotImplementedError


async def test_ten_documents_are_summarised_then_combined_in_one_call() -> None:
    client = MapClient()
    result = await summarise_documents(DOCS, client)

    assert result.overview == "OVERVIEW"
    assert list(result.summaries) == [d.id for d in DOCS]  # same order as the input
    assert result.summaries["d10"] == "- summary 10"
    assert result.failed == []
    assert result.calls == 11  # 10 summaries + 1 combine
    combine = client.requests[-1]
    assert (
        "- summary 1" in combine and "text of document" not in combine
    )  # summaries, not documents
    assert "covers all documents" in combine
    assert result.usage == Usage(10 * 10 + 50, 10 * 5 + 20)


async def test_the_concurrency_limit_is_respected_and_used() -> None:
    result = await summarise_documents(DOCS, MapClient(delay=0.02), concurrency=3)
    assert result.peak_in_flight == 3  # ten documents, never more than three at once

    result = await summarise_documents(DOCS, MapClient(delay=0.02), concurrency=1)
    assert result.peak_in_flight == 1  # one at a time is the sequential case


async def test_parallel_is_faster_than_one_at_a_time() -> None:
    sequential = await summarise_documents(DOCS, MapClient(delay=0.03), concurrency=1)
    parallel = await summarise_documents(DOCS, MapClient(delay=0.03), concurrency=10)
    assert parallel.map_seconds < sequential.map_seconds / 3


async def test_one_failing_document_does_not_lose_the_other_nine() -> None:
    client = MapClient(fail={"d7": 99})
    result = await summarise_documents(DOCS, client)

    assert [f.id for f in result.failed] == ["d7"]
    assert (result.failed[0].error, result.failed[0].attempts) == ("LLMError", 2)  # one retry
    assert len(result.summaries) == 9 and "d7" not in result.summaries
    assert result.coverage == "9 of 10 documents (failed: d7)"
    assert result.calls == 9 + 2 + 1  # nine worked, d7 twice, one combine
    assert "covers only 9 of 10 documents (failed: d7)" in client.requests[-1]  # the reader is told


async def test_a_failed_document_that_works_on_the_retry_is_not_reported() -> None:
    client = MapClient(fail={"d7": 1}, error=RateLimitedError("429"))
    result = await summarise_documents(DOCS, client)

    assert result.failed == []
    assert len(result.summaries) == 10
    assert result.calls == 10 + 1 + 1  # d7 ran twice


async def test_without_the_retry_the_failure_is_reported_after_one_attempt() -> None:
    result = await summarise_documents(DOCS, MapClient(fail={"d7": 1}), retry_failed=False)
    assert [(f.id, f.attempts) for f in result.failed] == [("d7", 1)]


async def test_too_many_failures_stop_the_chain_before_the_combine_call() -> None:
    client = MapClient(fail={"d1": 99, "d2": 99, "d3": 99})
    with pytest.raises(TooManyFailuresError) as caught:
        await summarise_documents(DOCS, client, max_failures=2)

    assert [f.id for f in caught.value.failed] == ["d1", "d2", "d3"]
    assert not any("<summaries>" in r for r in client.requests)  # nothing was combined


async def test_a_call_that_takes_too_long_counts_as_a_failed_document() -> None:
    client = MapClient(delay=0.2)
    with pytest.raises(TooManyFailuresError) as caught:
        await summarise_documents(DOCS[:2], client, timeout=0.01, max_failures=1)
    assert {f.error for f in caught.value.failed} == {"TimeoutError"}


async def test_a_failed_combine_call_is_a_clean_unavailable_error() -> None:
    with pytest.raises(LLMUnavailableError):
        await summarise_documents(DOCS, MapClient(fail_combine=True))


async def test_a_bug_in_the_map_step_is_not_hidden_as_a_failed_document() -> None:
    client = MapClient()
    client.generate = lambda request: (_ for _ in ()).throw(KeyError("bug"))  # type: ignore[method-assign]
    with pytest.raises(KeyError):
        await summarise_documents(DOCS[:2], client)


async def test_bad_input_is_refused() -> None:
    with pytest.raises(ValueError, match="at least one"):
        await summarise_documents([], MapClient())
    with pytest.raises(ValueError, match="unique"):
        await summarise_documents([Document("a", "x"), Document("a", "y")], MapClient())


def test_the_chain_prompts_exist() -> None:
    assert "{{ document }}" in get_prompt("summarise_document", "v1").template
    assert "{{ summaries }}" in get_prompt("combine_summaries", "v1").template
