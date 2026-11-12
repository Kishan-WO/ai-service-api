import json
from typing import Any

import httpx

from ai_service.schemas.extract import Enquiry
from ai_service.services.llm import JsonCompletion

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


def reply(data: dict[str, Any] | str, stop_reason: str = "stop") -> JsonCompletion:
    text = data if isinstance(data, str) else json.dumps(data)
    return JsonCompletion(text, stop_reason, input_tokens=100, output_tokens=40)


async def post(
    client: httpx.AsyncClient, headers: dict[str, str], text: str = MESSY, **extra: Any
) -> httpx.Response:
    return await client.post(EXTRACT_URL, json={"text": text, **extra}, headers=headers)


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
    llm.hosted = FakeProvider(json_replies=[reply(incomplete), reply(incomplete)])
    response = await post(client, auth_headers)

    assert response.status_code == 422
    error = response.json()["error"]
    assert error["code"] == "EXTRACTION_FAILED"
    assert error["details"] == [{"field": "city", "problem": "Field required"}]
    assert len(llm.hosted.json_calls) == 2  # one try and one retry, then it gives up


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
    llm.local = FakeProvider("fake-local", json_replies=[reply(VALID)])
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
