import json
from collections.abc import AsyncGenerator
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ai_service.db.session import get_db_session
from ai_service.schemas.extract import Enquiry
from ai_service.services.llm_types import LLMResponse, Usage

from .fakes import FakeProvider, FakeRegistry

EXTRACT_URL = "/api/v1/extract"

VALID: dict[str, Any] = {
    "student_name": "Riya Shah",
    "phone": "+919876543210",
    "email": None,
    "city": "Surat",
    "course_interest": "python",
    "budget_inr": 15000,
    "start_timing": "this-month",
    "urgency": "high",
    "language": "hinglish",
    "summary": "Riya wants a Python course in Surat this month.",
}
MESSY = (
    "hi sir, Riya here from Surat. python course chahiye, budget 15k, jaldi reply do. 9876543210"
)


def reply(data: dict[str, Any] | str, stop_reason: str = "stop") -> LLMResponse:
    text = data if isinstance(data, str) else json.dumps(data)
    return LLMResponse(text, stop_reason, Usage(100, 40), model="", backend="")


async def post(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    text: str = MESSY,
    headers_extra: dict[str, str] | None = None,
    **extra: Any,
) -> httpx.Response:
    return await client.post(
        EXTRACT_URL, json={"text": text, **extra}, headers={**headers, **(headers_extra or {})}
    )


async def test_extract_returns_a_validated_object(
    client: httpx.AsyncClient, auth_headers: dict[str, str], llm: FakeRegistry
) -> None:
    llm.hosted = FakeProvider("fake-hosted", json_replies=[reply(VALID)])
    response = await post(client, auth_headers)

    assert response.status_code == 200
    body = response.json()
    assert body["data"] == VALID
    assert body["meta"]["backend"] == "hosted"
    assert body["meta"]["model"] == "fake-hosted"
    assert body["meta"]["attempts"] == 1
    assert (body["meta"]["input_tokens"], body["meta"]["output_tokens"]) == (100, 40)
    assert body["meta"]["latency_ms"] >= 0


async def test_the_schema_comes_from_the_pydantic_model(
    client: httpx.AsyncClient, auth_headers: dict[str, str], llm: FakeRegistry
) -> None:
    llm.hosted = FakeProvider(json_replies=[reply(VALID)])
    await post(client, auth_headers)

    call = llm.hosted.json_calls[0]
    assert call["name"] == "Enquiry"
    assert call["max_tokens"] == 400  # a low cap: a model that cannot stop fails fast
    assert call["schema"] == Enquiry.model_json_schema()
    # every field is required, so the model cannot just leave one out
    assert set(call["schema"]["required"]) == set(VALID)
    # the text is passed as data between tags, after the instructions
    system, user = call["messages"]
    assert system.role == "system"
    assert user.content == f"<message>\n{MESSY}\n</message>"


async def test_a_wrong_first_reply_is_corrected_on_the_retry(
    client: httpx.AsyncClient, auth_headers: dict[str, str], llm: FakeRegistry
) -> None:
    bad = {**VALID, "course_interest": "cooking"}  # not one of the allowed values
    llm.hosted = FakeProvider(json_replies=[reply(bad), reply(VALID)])
    response = await post(client, auth_headers)

    assert response.status_code == 200
    assert response.json()["meta"]["attempts"] == 2
    assert response.json()["meta"]["input_tokens"] == 200  # both calls are counted
    retry_prompt = llm.hosted.json_calls[1]["messages"]
    assert [m.role for m in retry_prompt][-2:] == ["assistant", "user"]
    assert "course_interest" in retry_prompt[-1].content  # the model is shown its own mistake


async def test_text_around_the_json_counts_as_invalid(
    client: httpx.AsyncClient, auth_headers: dict[str, str], llm: FakeRegistry
) -> None:
    llm.hosted = FakeProvider(
        json_replies=[reply("Sure! Here you go: " + json.dumps(VALID)), reply(VALID)]
    )
    response = await post(client, auth_headers)
    assert response.status_code == 200
    assert response.json()["meta"]["attempts"] == 2


async def test_a_missing_field_is_invalid(
    client: httpx.AsyncClient, auth_headers: dict[str, str], llm: FakeRegistry
) -> None:
    incomplete = {k: v for k, v in VALID.items() if k != "city"}
    llm.hosted = FakeProvider(json_replies=[reply(incomplete)] * 3)
    response = await post(client, auth_headers)

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "EXTRACTION_FAILED"
    assert error["details"] == [{"field": "city", "problem": "Field required"}]
    assert len(llm.hosted.json_calls) == 3  # one try and two repairs, then it gives up


async def test_a_reply_cut_off_by_the_token_limit_is_not_retried(
    client: httpx.AsyncClient, auth_headers: dict[str, str], llm: FakeRegistry
) -> None:
    llm.hosted = FakeProvider(json_replies=[reply('{"student_name": "Ri', stop_reason="length")])
    response = await post(client, auth_headers)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "EXTRACTION_FAILED"
    assert len(llm.hosted.json_calls) == 1


async def test_a_provider_failure_is_a_502(
    client: httpx.AsyncClient, auth_headers: dict[str, str], llm: FakeRegistry
) -> None:
    llm.hosted = FakeProvider(fail_json=True)
    response = await post(client, auth_headers)
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "LLM_UNAVAILABLE"


async def test_the_local_backend_can_be_chosen(
    client: httpx.AsyncClient, auth_headers: dict[str, str], llm: FakeRegistry
) -> None:
    llm.local = FakeProvider("fake-local", backend="local", json_replies=[reply(VALID)])
    response = await post(client, auth_headers, backend="local")
    assert response.json()["meta"]["backend"] == "local"
    assert response.json()["meta"]["model"] == "fake-local"
    assert not llm.hosted.json_calls


async def test_extract_requires_authentication_and_text(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    assert (await client.post(EXTRACT_URL, json={"text": MESSY})).status_code == 401
    assert (await post(client, auth_headers, text="")).status_code == 422
    assert (await post(client, auth_headers, text="   ")).status_code == 422  # blank
    assert (await post(client, auth_headers, text="x" * 8001)).status_code == 422
    assert (await post(client, auth_headers, backend="other")).status_code == 422


async def test_the_model_gets_two_repairs_and_the_second_can_succeed(
    client: httpx.AsyncClient, auth_headers: dict[str, str], llm: FakeRegistry
) -> None:
    bad = {**VALID, "urgency": "extreme"}
    llm.hosted = FakeProvider(json_replies=[reply(bad), reply("not json at all"), reply(VALID)])
    response = await post(client, auth_headers)

    assert response.status_code == 200
    assert response.json()["meta"]["attempts"] == 3
    assert response.json()["meta"]["input_tokens"] == 300  # all three calls are counted
    # each repair prompt keeps the whole conversation so far: the model sees both mistakes
    third = llm.hosted.json_calls[2]["messages"]
    assert [m.role for m in third] == ["system", "user", "assistant", "user", "assistant", "user"]


async def test_a_refusal_is_its_own_handled_error_and_is_not_retried(
    client: httpx.AsyncClient, auth_headers: dict[str, str], llm: FakeRegistry
) -> None:
    llm.hosted = FakeProvider(json_replies=[reply("", stop_reason="content_filter")])
    response = await post(client, auth_headers)

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "EXTRACTION_REFUSED"
    assert len(llm.hosted.json_calls) == 1


async def test_the_call_is_labelled_with_the_tenant_and_the_feature(
    client: httpx.AsyncClient, auth_headers: dict[str, str], llm: FakeRegistry
) -> None:
    llm.hosted = FakeProvider(json_replies=[reply(VALID)])
    response = await post(client, auth_headers, headers_extra={"X-Request-ID": "req-123"})

    assert response.status_code == 200
    context = llm.hosted.json_calls[0]["context"]
    assert (context.feature, context.request_id) == ("extract", "req-123")
    assert context.tenant_id and context.user_id


async def test_the_meta_says_when_a_fallback_answered(
    client: httpx.AsyncClient, auth_headers: dict[str, str], llm: FakeRegistry
) -> None:
    # the registry hands back a client whose backend differs from the one asked for
    llm.hosted = FakeProvider("fallback-model", backend="local", json_replies=[reply(VALID)])
    response = await post(client, auth_headers)

    meta = response.json()["meta"]
    assert (meta["backend"], meta["model"], meta["fallback_used"]) == (
        "local",
        "fallback-model",
        True,
    )


async def test_the_database_connection_is_given_back_before_the_model_is_called(
    app: FastAPI,
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    llm: FakeRegistry,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A request must not hold a connection while it waits for the model, or a burst of slow
    requests empties the pool. Seen live: 25 at once gave ten 500s (QueuePool limit)."""
    sessions: list[AsyncSession] = []

    async def spy() -> AsyncGenerator[AsyncSession]:
        async with session_factory() as session:
            sessions.append(session)
            yield session

    in_transaction_during_the_call: list[bool] = []

    class Probe(FakeProvider):
        async def generate_structured(self, *args: Any, **kwargs: Any) -> LLMResponse:
            in_transaction_during_the_call.append(sessions[-1].in_transaction())
            return await super().generate_structured(*args, **kwargs)

    app.dependency_overrides[get_db_session] = spy
    llm.hosted = Probe(json_replies=[reply(VALID)])
    response = await post(client, auth_headers)

    assert response.status_code == 200
    assert in_transaction_during_the_call == [False]


@pytest.mark.parametrize(
    ("field", "bad", "complaint"),
    [
        ("phone", "python", "phone must hold 8 to 15 digits"),
        ("phone", "123", "phone must hold 8 to 15 digits"),
        ("email", "rohit", "email must look like"),
        ("budget_inr", 5_000_000_000_000_000, "budget_inr must be between 0 and 10,000,000"),
        ("budget_inr", -5000, "budget_inr must be between 0 and 10,000,000"),
        ("student_name", "x" * 61, "student_name must be at most 60 characters"),
        ("city", "the whole sentence " * 5, "city must be at most 60 characters"),
    ],
)
async def test_nonsense_that_fits_the_schema_is_repaired_by_showing_the_model_the_error(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    llm: FakeRegistry,
    field: str,
    bad: object,
    complaint: str,
) -> None:
    """Right type, wrong sense: the JSON schema cannot catch it, the Pydantic checks do."""
    llm.hosted = FakeProvider(json_replies=[reply({**VALID, field: bad}), reply(VALID)])
    response = await post(client, auth_headers)

    assert response.status_code == 200
    assert response.json()["meta"]["attempts"] == 2
    repair_prompt = llm.hosted.json_calls[1]["messages"][-1].content
    assert field in repair_prompt
    assert complaint in repair_prompt  # the model is told what is wrong, in words it can act on


async def test_a_model_that_keeps_returning_nonsense_ends_in_a_handled_422(
    client: httpx.AsyncClient, auth_headers: dict[str, str], llm: FakeRegistry
) -> None:
    llm.hosted = FakeProvider(json_replies=[reply({**VALID, "phone": "python"})] * 3)
    response = await post(client, auth_headers)

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "EXTRACTION_FAILED"
    assert error["details"][0]["field"] == "phone"


def test_the_sanity_checks_accept_ordinary_values() -> None:
    Enquiry.model_validate({**VALID, "phone": "+91 98765-43210", "email": "a.b@c.co.in"})
    Enquiry.model_validate({**VALID, "phone": None, "email": None, "budget_inr": 0})
    Enquiry.model_validate({**VALID, "student_name": "કિરણ પટેલ", "city": "અમદાવાદ"})


def test_the_sanity_checks_are_not_part_of_the_schema_sent_to_the_model() -> None:
    # they are enforced after the reply; the schema stays what every provider accepts
    budget = Enquiry.model_json_schema()["properties"]["budget_inr"]
    assert "minimum" not in str(budget) and "maximum" not in str(budget)
