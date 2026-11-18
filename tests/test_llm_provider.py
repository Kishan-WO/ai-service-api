"""The real provider class, against a fake HTTP server (no network, no key).

The OpenAI SDK has its own HTTP library (httpx2), so respx cannot intercept it; its MockTransport
plays the server instead and records what the SDK sent.
"""

import json
from typing import Any

import httpx2
import pytest
from openai import AsyncOpenAI

from ai_service.services.llm import (
    AuthError,
    BadRequestError,
    ChatMessage,
    ContextTooLongError,
    Finish,
    LLMError,
    LLMRequest,
    OpenAICompatProvider,
    OverloadedError,
    QuotaExhaustedError,
    RateLimitedError,
    StreamStart,
    TextDelta,
    Usage,
)

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


def request(text: str = "hi", **kwargs: Any) -> LLMRequest:
    return LLMRequest([ChatMessage("user", text)], **kwargs)


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
    events = [e async for e in server.provider().stream(request())]

    assert events == [
        StreamStart("test-model", "hosted"),
        TextDelta("Hel"),
        TextDelta("lo"),
        Finish("stop", Usage(input_tokens=7, output_tokens=2)),
    ]
    assert server.sent["model"] == "test-model"
    assert server.sent["stream"] is True
    assert server.sent["stream_options"] == {"include_usage": True}
    assert server.sent["max_tokens"] == 123
    assert server.sent["messages"] == [{"role": "user", "content": "hi"}]


async def test_stream_failure_before_the_first_byte_is_an_llm_error() -> None:
    server = FakeServer(httpx2.Response(500, json={"error": {"message": "boom"}}))
    with pytest.raises(OverloadedError, match="could not start the stream"):
        await anext(server.provider().stream(request()))
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
    result = await server.provider().generate_structured(
        request("x"), schema_name="Thing", schema=schema
    )

    assert (result.text, result.stop_reason, result.usage) == ('{"a": 1}', "stop", Usage(5, 3))
    assert (result.model, result.backend) == ("test-model", "hosted")
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
    result = await server.provider().generate_structured(
        request("x", max_tokens=50), schema_name="T", schema={}
    )
    assert server.sent["max_tokens"] == 50
    assert result.usage is None  # no usage block sent: unknown, which is not the same as 0


async def test_a_429_is_a_rate_limit_error_that_remembers_retry_after() -> None:
    server = FakeServer(
        httpx2.Response(429, headers={"retry-after": "7"}, json={"error": {"message": "slow down"}})
    )
    with pytest.raises(RateLimitedError, match="the call failed") as caught:
        await server.provider().generate_structured(request("x"), schema_name="T", schema={})
    assert caught.value.retry_after == 7
    assert caught.value.retryable
    assert len(server.requests) == 1  # the SDK does not retry on its own: the wrapper does


async def test_cached_prompt_tokens_are_counted_apart_from_new_input() -> None:
    """OpenAI style: prompt_tokens includes the cached part, Usage.input_tokens must not."""
    server = FakeServer(
        httpx2.Response(
            200,
            json={
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "ok"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 1000,
                    "completion_tokens": 20,
                    "total_tokens": 1020,
                    "prompt_tokens_details": {"cached_tokens": 800},
                },
            },
        )
    )
    result = await server.provider().generate(request())
    assert result.usage == Usage(input_tokens=200, output_tokens=20, cache_read_tokens=800)
    assert result.usage.prompt_tokens == 1000


async def test_a_blocked_prompt_with_no_choices_is_a_content_filter_stop() -> None:
    server = FakeServer(httpx2.Response(200, json={"choices": []}))
    result = await server.provider().generate(request())
    assert (result.text, result.stop_reason) == ("", "content_filter")


@pytest.mark.parametrize(
    ("status", "body", "expected", "retryable"),
    [
        (429, {"error": {"message": "too fast"}}, RateLimitedError, True),
        (429, {"error": {"message": "quota exceeded per day"}}, QuotaExhaustedError, False),
        (
            429,
            {"error": {"code": "insufficient_quota", "message": "pay up"}},
            QuotaExhaustedError,
            False,
        ),
        (500, {"error": {"message": "boom"}}, OverloadedError, True),
        (503, {"error": {"message": "busy"}}, OverloadedError, True),
        (401, {"error": {"message": "bad key"}}, AuthError, False),
        (403, {"error": {"message": "no access"}}, AuthError, False),
        (
            400,
            {"error": {"message": "The input is too long for the model"}},
            ContextTooLongError,
            False,
        ),
        (413, {"error": {"message": "payload"}}, ContextTooLongError, False),
        (400, {"error": {"message": "unknown parameter"}}, BadRequestError, False),
        (404, {"error": {"message": "model not found"}}, BadRequestError, False),
    ],
)
async def test_each_failure_becomes_the_right_error_type(
    status: int, body: dict[str, Any], expected: type[LLMError], retryable: bool
) -> None:
    server = FakeServer(httpx2.Response(status, json=body))
    with pytest.raises(expected) as caught:
        await server.provider().generate(request())
    assert type(caught.value) is expected
    assert caught.value.retryable is retryable


async def test_a_dropped_connection_and_a_timeout_are_retryable() -> None:
    from ai_service.services.llm import LLMConnectionError, LLMTimeoutError

    def drop(_: httpx2.Request) -> httpx2.Response:
        raise httpx2.ConnectError("connection refused")

    def slow(_: httpx2.Request) -> httpx2.Response:
        raise httpx2.ReadTimeout("took too long")

    for handler, expected in ((drop, LLMConnectionError), (slow, LLMTimeoutError)):
        http_client = httpx2.AsyncClient(transport=httpx2.MockTransport(handler))
        client = AsyncOpenAI(api_key="t", base_url=BASE, http_client=http_client, max_retries=0)
        provider = OpenAICompatProvider(client, "m", 10)
        with pytest.raises(expected) as caught:
            await provider.generate(request())
        assert caught.value.retryable


async def test_geminis_wait_is_read_from_the_error_text_when_there_is_no_header() -> None:
    """Seen live: the 429 has no retry-after header, only "Please retry in 23.6s." in the body."""
    server = FakeServer(
        httpx2.Response(
            429,
            json=[
                {
                    "error": {
                        "code": 429,
                        "message": "Requests per minute limit exceeded on Free Tier. "
                        "Please retry in 23.605992143s.",
                        "status": "RESOURCE_EXHAUSTED",
                    }
                }
            ],
        )
    )
    with pytest.raises(RateLimitedError) as caught:
        await server.provider().generate(request())
    assert caught.value.retry_after == pytest.approx(23.6, abs=0.01)


async def test_thinking_tokens_are_part_of_the_output_even_when_completion_tokens_omit_them() -> (
    None
):
    """Seen live on gemini-3-flash-preview: prompt 8, completion 1, total 49 (about 40 thinking)."""
    server = FakeServer(
        httpx2.Response(
            200,
            json={
                "choices": [
                    {
                        "index": 0,
                        "message": {"role": "assistant", "content": "ok"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 8, "completion_tokens": 1, "total_tokens": 49},
            },
        )
    )
    result = await server.provider().generate(request())
    assert result.usage == Usage(input_tokens=8, output_tokens=41)
