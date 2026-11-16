"""The Anthropic adapter against a fake HTTP server (no network, no key).

Written from Anthropic's documented message and stream formats; it has not talked to the real
service, because this project has no Anthropic key. The Gemini and Ollama adapters were run live.
"""

import json
from typing import Any

import httpx2
import pytest
from anthropic import AsyncAnthropic

from ai_service.services.llm import (
    AuthError,
    ChatMessage,
    ContextTooLongError,
    Finish,
    LLMRequest,
    OverloadedError,
    RateLimitedError,
    StreamStart,
    TextDelta,
    Usage,
)
from ai_service.services.llm_anthropic import AnthropicProvider

MESSAGES = [ChatMessage("system", "Be brief."), ChatMessage("user", "hi")]


def message_json(**overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "id": "msg_1",
        "type": "message",
        "role": "assistant",
        "model": "claude-test",
        "content": [{"type": "text", "text": "Hello"}],
        "stop_reason": "end_turn",
        "stop_sequence": None,
        "usage": {
            "input_tokens": 12,
            "output_tokens": 5,
            "cache_read_input_tokens": 800,
            "cache_creation_input_tokens": 0,
        },
    }
    body.update(overrides)
    return body


class FakeServer:
    def __init__(self, response: httpx2.Response) -> None:
        self.response = response
        self.requests: list[httpx2.Request] = []

    def handler(self, request: httpx2.Request) -> httpx2.Response:
        self.requests.append(request)
        return self.response

    @property
    def sent(self) -> dict[str, Any]:
        assert len(self.requests) == 1
        body: dict[str, Any] = json.loads(self.requests[0].content)
        return body

    def provider(self) -> AnthropicProvider:
        http_client = httpx2.AsyncClient(transport=httpx2.MockTransport(self.handler))
        client = AsyncAnthropic(
            api_key="test", base_url="http://anthropic.test", http_client=http_client, max_retries=0
        )
        return AnthropicProvider(client, "claude-test", max_output_tokens=321)


def sse(*events: tuple[str, dict[str, Any]]) -> str:
    return "".join(f"event: {name}\ndata: {json.dumps(data)}\n\n" for name, data in events)


async def test_the_system_prompt_is_sent_apart_and_marked_for_caching() -> None:
    server = FakeServer(httpx2.Response(200, json=message_json()))
    await server.provider().generate(LLMRequest(MESSAGES, cache_system=True))

    sent = server.sent
    assert sent["system"] == [
        {"type": "text", "text": "Be brief.", "cache_control": {"type": "ephemeral"}}
    ]
    assert sent["messages"] == [{"role": "user", "content": "hi"}]  # no system message in the list
    assert sent["max_tokens"] == 321  # required by this API, so the adapter always sends it
    assert sent["model"] == "claude-test"


async def test_without_the_cache_flag_no_cache_marker_is_sent() -> None:
    server = FakeServer(httpx2.Response(200, json=message_json()))
    await server.provider().generate(LLMRequest(MESSAGES))
    assert server.sent["system"] == [{"type": "text", "text": "Be brief."}]


async def test_the_reply_text_stop_reason_and_usage_are_normalised() -> None:
    server = FakeServer(
        httpx2.Response(
            200,
            json=message_json(
                usage={
                    "input_tokens": 12,
                    "output_tokens": 5,
                    "cache_read_input_tokens": 800,
                    "cache_creation_input_tokens": 40,
                }
            ),
        )
    )
    result = await server.provider().generate(LLMRequest(MESSAGES))

    assert (result.text, result.stop_reason, result.backend) == ("Hello", "stop", "anthropic")
    # Anthropic's input_tokens already excludes the cached parts: nothing to subtract
    assert result.usage == Usage(12, 5, cache_read_tokens=800, cache_write_tokens=40)
    assert result.usage.prompt_tokens == 852


@pytest.mark.parametrize(
    ("raw", "normalised"),
    [("end_turn", "stop"), ("max_tokens", "length"), ("refusal", "content_filter")],
)
async def test_stop_reasons_use_the_shared_names(raw: str, normalised: str) -> None:
    server = FakeServer(httpx2.Response(200, json=message_json(stop_reason=raw)))
    assert (await server.provider().generate(LLMRequest(MESSAGES))).stop_reason == normalised


async def test_structured_output_forces_a_tool_and_returns_its_arguments_as_json() -> None:
    server = FakeServer(
        httpx2.Response(
            200,
            json=message_json(
                content=[{"type": "tool_use", "id": "tu_1", "name": "Thing", "input": {"a": 1}}],
                stop_reason="tool_use",
            ),
        )
    )
    schema = {"type": "object", "properties": {"a": {"type": "integer"}}, "required": ["a"]}
    result = await server.provider().generate_structured(
        LLMRequest(MESSAGES), schema_name="Thing", schema=schema
    )

    assert json.loads(result.text) == {"a": 1}
    assert result.stop_reason == "stop"
    assert server.sent["tools"][0]["name"] == "Thing"
    assert server.sent["tools"][0]["input_schema"] == schema
    assert server.sent["tool_choice"] == {"type": "tool", "name": "Thing"}


async def test_a_refusal_with_no_tool_call_comes_back_as_empty_text_and_content_filter() -> None:
    server = FakeServer(httpx2.Response(200, json=message_json(content=[], stop_reason="refusal")))
    result = await server.provider().generate_structured(
        LLMRequest(MESSAGES), schema_name="Thing", schema={}
    )
    assert (result.text, result.stop_reason) == ("", "content_filter")


async def test_a_stream_yields_text_then_the_finish_with_cache_usage() -> None:
    body = sse(
        (
            "message_start",
            {
                "type": "message_start",
                "message": {
                    **message_json(content=[], stop_reason=None),
                    "usage": {
                        "input_tokens": 25,
                        "output_tokens": 1,
                        "cache_read_input_tokens": 700,
                        "cache_creation_input_tokens": 0,
                    },
                },
            },
        ),
        (
            "content_block_start",
            {
                "type": "content_block_start",
                "index": 0,
                "content_block": {"type": "text", "text": ""},
            },
        ),
        (
            "content_block_delta",
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "text_delta", "text": "Hel"},
            },
        ),
        (
            "content_block_delta",
            {
                "type": "content_block_delta",
                "index": 0,
                "delta": {"type": "text_delta", "text": "lo"},
            },
        ),
        ("content_block_stop", {"type": "content_block_stop", "index": 0}),
        (
            "message_delta",
            {
                "type": "message_delta",
                "delta": {"stop_reason": "end_turn", "stop_sequence": None},
                "usage": {"output_tokens": 15},
            },
        ),
        ("message_stop", {"type": "message_stop"}),
    )
    server = FakeServer(
        httpx2.Response(200, headers={"content-type": "text/event-stream"}, text=body)
    )
    events = [e async for e in server.provider().stream(LLMRequest(MESSAGES, cache_system=True))]

    assert events[:3] == [
        StreamStart("claude-test", "anthropic"),
        TextDelta("Hel"),
        TextDelta("lo"),
    ]
    finish = events[3]
    assert isinstance(finish, Finish)
    assert finish.stop_reason == "stop"
    assert finish.usage == Usage(25, 15, cache_read_tokens=700)
    assert server.sent["stream"] is True
    assert server.sent["system"][0]["cache_control"] == {"type": "ephemeral"}


@pytest.mark.parametrize(
    ("status", "message", "expected"),
    [
        (429, "rate limited", RateLimitedError),
        (529, "Overloaded", OverloadedError),
        (500, "internal error", OverloadedError),
        (401, "invalid x-api-key", AuthError),
        (400, "prompt is too long: 250000 tokens > 200000 maximum", ContextTooLongError),
    ],
)
async def test_http_failures_become_the_shared_error_types(
    status: int, message: str, expected: type[Exception]
) -> None:
    server = FakeServer(
        httpx2.Response(
            status,
            headers={"retry-after": "3"},
            json={"type": "error", "error": {"type": "api_error", "message": message}},
        )
    )
    with pytest.raises(expected) as caught:
        await server.provider().generate(LLMRequest(MESSAGES))
    assert type(caught.value) is expected
    if expected is RateLimitedError:
        assert caught.value.retry_after == 3  # type: ignore[attr-defined]
