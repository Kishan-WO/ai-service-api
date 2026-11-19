"""POST /summarise (Day 8, task 4): the route around the parallel summarise chain."""

import uuid
from typing import Any

import httpx

from ai_service.core.config import get_settings
from ai_service.services.llm_types import LLMError, LLMRequest, LLMResponse, Usage

from .conftest import Registrar
from .fakes import FakeRegistry
from .test_documents import upload

URL = "/api/v1/summarise"


class SummaryModel:
    """Summary calls echo the first words of the document; a document with FAIL in it fails."""

    backend = "hosted"
    model = "fake"

    def __init__(self) -> None:
        self.requests: list[str] = []

    async def generate(self, request: LLMRequest) -> LLMResponse:
        text = request.messages[-1].content
        self.requests.append(text)
        if "<summaries>" in text:
            return LLMResponse("OVERVIEW", "stop", Usage(50, 20), self.model, self.backend)
        if "FAIL" in text:
            raise LLMError("injected failure")
        words = text.split("<document>\n")[1].split()[:2]
        return LLMResponse("- " + " ".join(words), "stop", Usage(10, 5), self.model, self.backend)

    async def generate_structured(self, *a: Any, **k: Any) -> LLMResponse:
        raise NotImplementedError

    def stream(self, *a: Any, **k: Any) -> Any:
        raise NotImplementedError


async def make_docs(
    client: httpx.AsyncClient, headers: dict[str, str], texts: list[str]
) -> list[str]:
    ids = []
    for i, text in enumerate(texts):
        response = await upload(
            client, headers, f"d{i}.txt", f"{text} {uuid.uuid4()}".encode(), "text/plain"
        )
        assert response.status_code == 201, response.text
        ids.append(response.json()["id"])
    return ids


async def test_summarise_two_documents_returns_summaries_and_an_overview(
    client: httpx.AsyncClient, auth_headers: dict[str, str], llm: FakeRegistry
) -> None:
    llm.hosted = SummaryModel()  # type: ignore[assignment]
    ids = await make_docs(client, auth_headers, ["alpha beta", "gamma delta"])

    response = await client.post(URL, json={"document_ids": ids}, headers=auth_headers)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["overview"] == "OVERVIEW"
    assert [s["document_id"] for s in body["summaries"]] == ids  # the order of the request
    assert body["summaries"][0]["summary"] == "- alpha beta"
    assert body["failed"] == []
    meta = body["meta"]
    assert (meta["documents_requested"], meta["documents_summarised"]) == (2, 2)
    assert (meta["coverage"], meta["model_calls"]) == ("all 2 documents", 3)
    assert (meta["input_tokens"], meta["output_tokens"]) == (2 * 10 + 50, 2 * 5 + 20)


async def test_a_failing_document_is_listed_and_the_rest_are_combined(
    client: httpx.AsyncClient, auth_headers: dict[str, str], llm: FakeRegistry
) -> None:
    model = SummaryModel()
    llm.hosted = model  # type: ignore[assignment]
    ids = await make_docs(client, auth_headers, ["alpha beta", "gamma FAIL", "delta eps"])

    response = await client.post(URL, json={"document_ids": ids}, headers=auth_headers)

    assert response.status_code == 200, response.text
    body = response.json()
    assert len(body["summaries"]) == 2
    assert [(f["document_id"], f["error"], f["attempts"]) for f in body["failed"]] == [
        (ids[1], "LLMError", 2)
    ]
    assert body["meta"]["coverage"] == f"2 of 3 documents (failed: {ids[1]})"
    assert "covers only 2 of 3 documents" in model.requests[-1]


async def test_too_many_failures_is_a_502_with_the_failed_documents_named(
    client: httpx.AsyncClient, auth_headers: dict[str, str], llm: FakeRegistry
) -> None:
    llm.hosted = SummaryModel()  # type: ignore[assignment]
    ids = await make_docs(client, auth_headers, ["FAIL one", "FAIL two", "FAIL three"])

    response = await client.post(URL, json={"document_ids": ids}, headers=auth_headers)

    assert response.status_code == 502
    assert response.json()["error"]["code"] == "SUMMARISE_FAILED"
    assert len(response.json()["error"]["details"]) == 3


async def test_another_tenants_document_is_a_404(
    client: httpx.AsyncClient, auth_headers: dict[str, str], register: Registrar, llm: FakeRegistry
) -> None:
    llm.hosted = SummaryModel()  # type: ignore[assignment]
    other = await register("other@example.com")
    foreign = await make_docs(client, other, ["secret text"])

    response = await client.post(URL, json={"document_ids": foreign}, headers=auth_headers)

    assert response.status_code == 404
    assert response.json()["error"]["code"] == "DOCUMENT_NOT_FOUND"


async def test_a_document_over_the_size_limit_is_refused_before_any_model_call(
    app: Any, client: httpx.AsyncClient, auth_headers: dict[str, str], llm: FakeRegistry
) -> None:
    model = SummaryModel()
    llm.hosted = model  # type: ignore[assignment]
    small = get_settings().model_copy(update={"SUMMARISE_MAX_DOCUMENT_CHARS": 50})
    app.dependency_overrides[get_settings] = lambda: small
    ids = await make_docs(client, auth_headers, ["word " * 40])

    response = await client.post(URL, json={"document_ids": ids}, headers=auth_headers)

    assert response.status_code == 413
    assert response.json()["error"]["code"] == "DOCUMENT_TOO_LONG"
    assert model.requests == []


async def test_the_request_is_validated(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    one = str(uuid.uuid4())
    payloads: tuple[dict[str, Any], ...] = (
        {"document_ids": []},
        {"document_ids": [one, one]},  # a duplicate
        {"document_ids": [str(uuid.uuid4()) for _ in range(21)]},  # more than 20
        {"document_ids": [one], "concurrency": 9},
        {"document_ids": ["not-a-uuid"]},
    )
    for payload in payloads:
        response = await client.post(URL, json=payload, headers=auth_headers)
        assert response.status_code == 422, payload


async def test_summarise_needs_a_login(client: httpx.AsyncClient) -> None:
    response = await client.post(URL, json={"document_ids": [str(uuid.uuid4())]})
    assert response.status_code == 401
