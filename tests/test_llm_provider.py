"""The real provider class, against a fake HTTP server (no network, no key).

The OpenAI SDK has its own HTTP library (httpx2), so respx cannot intercept it; its MockTransport
plays the server instead and records what the SDK sent.
"""

import json
from typing import Any

import httpx2
import pytest
from openai import AsyncOpenAI

from ai_service.services.llm import ChatMessage, Finish, LLMError, OpenAICompatProvider, TextDelta

BASE = "http://llm.test/v1"


class FakeServer:
    def __init__(self, response: httpx2.Response) -> None:
        self.response = response
        self.requests: list[httpx2.Request] = []

    def handler(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        return self.response

    @property
    def sent(self) -> dict[str, Any]:
        assert len(self.requests) == 1, f"expected one call, got {len(self.requests)}"
        assert self.requests[0].url.path == "/v1/chat/completions"
        body: dict[str, Any] = json.loads(self.requests[0].content)
        return body

    def provider(self) -> OpenAICompatProvider:
        http_client = httpx2.AsyncClient(transport=httpx2.MockTransport(self.handler))
        # max_retries=0: a failing server should fail at once, not after the SDK's back-off
        client = AsyncOpenAI(api_key="test", base_url=BASE, http_client=http_client, max_retries=0)
        return OpenAICompatProvider(client, "test-model", max_output_tokens=123)


def sse(*chunks: dict[str, object]) -> str:
    return "".join(f"data: {json.dumps(c)}\n\n" for c in chunks) + "data: [DONE]\n\n"


def delta(text: str | None, finish: str | None = None) -> dict[str, object]:
    return {"choices": [{"index": 0, "delta": {"content": text}, "finish_reason": finish}]}


async def test_stream_yields_text_then_the_finish_event_with_usage() -> None:
    server = FakeServer(
        httpx2.Response(
            200,
            headers={"content-type": "text/event-stream"},
            text=sse(
                {"choices": [{"index": 0, "delta": {"role": "assistant"}}]},  # role only: no text
                delta("Hel"),
                delta("lo"),
                delta(None, finish="stop"),
                {
                    "choices": [],
                    "usage": {"prompt_tokens": 7, "completion_tokens": 2, "total_tokens": 9},
                },
            ),
        )
    )
    events = [e async for e in server.provider().stream_chat([ChatMessage("user", "hi")])]

    assert events == [TextDelta("Hel"), TextDelta("lo"), Finish("stop", 7, 2)]
    assert server.sent["model"] == "test-model"
    assert server.sent["stream"] is True
    assert server.sent["stream_options"] == {"include_usage": True}
    assert server.sent["max_tokens"] == 123
    assert server.sent["messages"] == [{"role": "user", "content": "hi"}]


async def test_stream_failure_before_the_first_byte_is_an_llm_error() -> None:
    server = FakeServer(httpx2.Response(500, json={"error": {"message": "boom"}}))
    with pytest.raises(LLMError, match="could not start the stream"):
        await anext(server.provider().stream_chat([ChatMessage("user", "hi")]))
    assert len(server.requests) == 1  # it really reached the (fake) server


async def test_complete_json_sends_the_schema_and_reads_the_reply() -> None:
    server = FakeServer(
        httpx2.Response(
            200,
            json={
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": '{"a": 1}'},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 5, "completion_tokens": 3, "total_tokens": 8},
            },
        )
    )
    schema = {"type": "object", "properties": {"a": {"type": "integer"}}, "required": ["a"]}
    result = await server.provider().complete_json(
        [ChatMessage("user", "x")], schema_name="Thing", schema=schema
    )

    assert (result.text, result.stop_reason, result.input_tokens, result.output_tokens) == (
        '{"a": 1}',
        "stop",
        5,
        3,
    )
    assert server.sent["response_format"] == {
        "type": "json_schema",
        "json_schema": {"name": "Thing", "schema": schema, "strict": True},
    }
    assert server.sent["temperature"] == 0
    assert server.sent["max_tokens"] == 123  # the provider's default cap


async def test_complete_json_can_use_its_own_token_cap() -> None:
    server = FakeServer(
        httpx2.Response(
            200,
            json={
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "{}"},
                        "finish_reason": "stop",
                    }
                ]
            },
        )
    )
    result = await server.provider().complete_json(
        [ChatMessage("user", "x")], schema_name="T", schema={}, max_tokens=50
    )
    assert server.sent["max_tokens"] == 50
    assert (result.input_tokens, result.output_tokens) == (None, None)  # no usage block sent


async def test_complete_json_failure_is_an_llm_error() -> None:
    server = FakeServer(httpx2.Response(429, json={"error": {"message": "slow down"}}))
    with pytest.raises(LLMError, match="the call failed"):
        await server.provider().complete_json(
            [ChatMessage("user", "x")], schema_name="T", schema={}
        )
    assert len(server.requests) == 1
