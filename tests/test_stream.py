import json
import logging

import httpx
import pytest

from ai_service.api.v1.stream import DEMO_TEXT, word_stream

STREAM_URL = "/api/v1/stream/demo"


def parse_sse(raw: str) -> list[tuple[str, dict[str, object]]]:
    events = []
    for block in raw.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines())
        events.append((lines["event"], json.loads(lines["data"])))
    return events


async def test_stream_sends_words_in_order(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    async with client.stream(
        "GET", STREAM_URL, params={"delay_ms": 0}, headers=auth_headers
    ) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        assert response.headers["cache-control"] == "no-cache"
        raw = "".join([chunk async for chunk in response.aiter_text()])

    events = parse_sse(raw)
    words = DEMO_TEXT.split()
    tokens = [data for name, data in events if name == "token"]
    assert [t["text"] for t in tokens] == words
    assert [t["index"] for t in tokens] == list(range(len(words)))
    assert events[-1] == ("done", {"words": len(words)})


async def test_stream_requires_authentication(client: httpx.AsyncClient) -> None:
    assert (await client.get(STREAM_URL)).status_code == 401


async def test_stream_validates_delay(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    response = await client.get(STREAM_URL, params={"delay_ms": 5000}, headers=auth_headers)
    assert response.status_code == 422


class FakeRequest:
    """Reports 'connected' for the first few checks, then 'disconnected'."""

    def __init__(self, connected_checks: int) -> None:
        self.remaining = connected_checks

    async def is_disconnected(self) -> bool:
        if self.remaining == 0:
            return True
        self.remaining -= 1
        return False


async def test_stream_stops_and_logs_when_the_client_disconnects(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.INFO, logger="ai_service.stream"):
        chunks = [
            chunk async for chunk in word_stream(FakeRequest(connected_checks=3), DEMO_TEXT, 0)
        ]

    assert len(chunks) == 3  # three words sent, then it stopped: no 'done' event
    assert "done" not in "".join(chunks)
    assert any("client disconnected after 3 of" in record.message for record in caplog.records)


async def test_a_complete_stream_does_not_log_a_disconnect(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.INFO, logger="ai_service.stream"):
        chunks = [chunk async for chunk in word_stream(FakeRequest(10_000), "just three words", 0)]
    assert len(chunks) == 4  # 3 tokens + done
    assert not caplog.records
