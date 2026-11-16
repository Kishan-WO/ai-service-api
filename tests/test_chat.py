import asyncio
import logging
import uuid
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ai_service.core.config import get_settings
from ai_service.db.models import Conversation, Message
from ai_service.services.chat_service import chat_stream
from ai_service.services.llm import Finish, LLMRequest, StreamStart, TextDelta, Usage

from .fakes import FakeProvider, FakeRegistry
from .test_stream import FakeRequest, parse_sse

CHAT_URL = "/api/v1/chat"
CONVERSATIONS_URL = "/api/v1/chat/conversations"


async def send(
    client: httpx.AsyncClient,
    headers: dict[str, str],
    message: str,
    headers_extra: dict[str, str] | None = None,
    **extra: Any,
) -> tuple[httpx.Response, list[tuple[str, dict[str, Any]]]]:
    """POST /chat and read the whole stream."""
    async with client.stream(
        "POST",
        CHAT_URL,
        json={"message": message, **extra},
        headers={**headers, **(headers_extra or {})},
    ) as response:
        raw = "".join([chunk async for chunk in response.aiter_text()])
    events = parse_sse(raw) if response.status_code == 200 and raw.strip() else []
    return response, events


async def test_chat_streams_tokens_and_saves_both_messages(
    client: httpx.AsyncClient, auth_headers: dict[str, str], llm: FakeRegistry
) -> None:
    response, events = await send(client, auth_headers, "Hi there")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.headers["cache-control"] == "no-cache"
    names = [name for name, _ in events]
    assert names == ["start", "token", "token", "token", "done"]
    assert [data["text"] for name, data in events if name == "token"] == ["Hello", " there", "!"]

    start, done = events[0][1], events[-1][1]
    conversation_id = start["conversation_id"]
    assert response.headers["x-conversation-id"] == conversation_id
    assert start["model"] == "fake-hosted"
    assert done["stop_reason"] == "stop"

    detail = (
        await client.get(f"{CONVERSATIONS_URL}/{conversation_id}", headers=auth_headers)
    ).json()
    assert detail["title"] == "Hi there"
    user_message, assistant_message = detail["messages"]
    assert (user_message["role"], user_message["content"]) == ("user", "Hi there")
    assert user_message["id"] == start["user_message_id"]
    assert assistant_message["role"] == "assistant"
    assert assistant_message["content"] == "Hello there!"  # what the client received, joined
    assert assistant_message["id"] == done["message_id"]
    assert assistant_message["status"] == "complete"
    assert assistant_message["model"] == "fake-hosted"
    assert assistant_message["stop_reason"] == "stop"
    assert assistant_message["input_tokens"] == 2  # system + user message
    assert assistant_message["output_tokens"] == 3
    assert llm.hosted.closed


async def test_second_turn_sends_the_stored_history(
    client: httpx.AsyncClient, auth_headers: dict[str, str], llm: FakeRegistry
) -> None:
    _, events = await send(client, auth_headers, "My name is Asha.")
    conversation_id = events[0][1]["conversation_id"]
    await send(client, auth_headers, "What is my name?", conversation_id=conversation_id)

    sent = [(m.role, m.content) for m in llm.hosted.calls[-1]]
    assert sent[0][0] == "system"
    assert sent[1:] == [
        ("user", "My name is Asha."),
        ("assistant", "Hello there!"),
        ("user", "What is my name?"),
    ]
    detail = (
        await client.get(f"{CONVERSATIONS_URL}/{conversation_id}", headers=auth_headers)
    ).json()
    assert len(detail["messages"]) == 4


async def test_only_the_latest_messages_are_sent(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    llm: FakeRegistry,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(get_settings(), "CHAT_HISTORY_LIMIT", 2)
    _, events = await send(client, auth_headers, "first")
    conversation_id = events[0][1]["conversation_id"]
    await send(client, auth_headers, "second", conversation_id=conversation_id)
    await send(client, auth_headers, "third", conversation_id=conversation_id)

    sent = [m.content for m in llm.hosted.calls[-1]][1:]
    # the stored history has 4 messages; only the newest 2 are sent, plus the new one
    assert sent == ["second", "Hello there!", "third"]


async def test_the_local_backend_is_used_when_asked(
    client: httpx.AsyncClient, auth_headers: dict[str, str], llm: FakeRegistry
) -> None:
    _, events = await send(client, auth_headers, "hello", backend="local")
    assert events[0][1]["model"] == "fake-local"
    assert len(llm.local.calls) == 1
    assert not llm.hosted.calls


async def test_a_blank_message_is_rejected(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    response = await client.post(CHAT_URL, json={"message": "   "}, headers=auth_headers)
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "VALIDATION_ERROR"


async def test_chat_requires_authentication(client: httpx.AsyncClient) -> None:
    assert (await client.post(CHAT_URL, json={"message": "hi"})).status_code == 401
    assert (await client.get(CONVERSATIONS_URL)).status_code == 401


# ---------- conversations are private to their tenant


async def test_an_unknown_conversation_is_404(
    client: httpx.AsyncClient, auth_headers: dict[str, str], llm: FakeRegistry
) -> None:
    response, _ = await send(client, auth_headers, "hi", conversation_id=str(uuid.uuid4()))
    assert response.status_code == 404
    assert not llm.hosted.calls  # the model was never called


async def test_another_tenant_cannot_see_or_use_a_conversation(
    client: httpx.AsyncClient, register: Any, llm: FakeRegistry
) -> None:
    alice = await register("alice@example.com")
    bob = await register("bob@example.com")
    _, events = await send(client, alice, "a private question")
    conversation_id = events[0][1]["conversation_id"]

    assert (
        await client.get(f"{CONVERSATIONS_URL}/{conversation_id}", headers=bob)
    ).status_code == 404
    assert (
        await client.delete(f"{CONVERSATIONS_URL}/{conversation_id}", headers=bob)
    ).status_code == 404
    assert (await client.get(CONVERSATIONS_URL, headers=bob)).json()["total"] == 0
    response, _ = await send(client, bob, "hello", conversation_id=conversation_id)
    assert response.status_code == 404
    assert len(llm.hosted.calls) == 1  # only Alice's message ever reached the model

    # Alice still has it
    assert (await client.get(CONVERSATIONS_URL, headers=alice)).json()["total"] == 1


async def test_list_and_delete_conversations(
    client: httpx.AsyncClient, auth_headers: dict[str, str]
) -> None:
    for text in ("one", "two", "three"):
        await send(client, auth_headers, text)

    listing = (
        await client.get(CONVERSATIONS_URL, params={"limit": 2}, headers=auth_headers)
    ).json()
    assert listing["total"] == 3
    assert len(listing["items"]) == 2
    assert listing["items"][0]["title"] == "three"  # most recently updated first

    victim = listing["items"][0]["id"]
    assert (
        await client.delete(f"{CONVERSATIONS_URL}/{victim}", headers=auth_headers)
    ).status_code == 204
    assert (
        await client.get(f"{CONVERSATIONS_URL}/{victim}", headers=auth_headers)
    ).status_code == 404
    assert (await client.get(CONVERSATIONS_URL, headers=auth_headers)).json()["total"] == 2


# ---------- failures


async def test_a_provider_that_is_down_gives_502_and_stores_nothing(
    client: httpx.AsyncClient, auth_headers: dict[str, str], llm: FakeRegistry
) -> None:
    llm.hosted = FakeProvider("fake-hosted", fail_before_first=True)
    response, _ = await send(client, auth_headers, "hello")
    assert response.status_code == 502
    assert (await client.get(CONVERSATIONS_URL, headers=auth_headers)).json()["total"] == 0
    assert llm.hosted.closed


async def test_an_error_in_the_middle_is_an_event_and_the_partial_text_is_kept(
    client: httpx.AsyncClient, auth_headers: dict[str, str], llm: FakeRegistry
) -> None:
    llm.hosted = FakeProvider("fake-hosted", fail_at=1)
    response, events = await send(client, auth_headers, "hello")

    assert response.status_code == 200  # the status line was sent before the failure
    assert [name for name, _ in events] == ["start", "token", "error"]
    assert events[-1][1]["code"] == "LLM_STREAM_FAILED"
    assert "stream broke" not in str(events[-1][1])  # no internal details for the client

    detail = (
        await client.get(
            f"{CONVERSATIONS_URL}/{events[0][1]['conversation_id']}", headers=auth_headers
        )
    ).json()
    assistant = detail["messages"][1]
    assert (assistant["content"], assistant["status"]) == ("Hello", "error")
    assert llm.hosted.closed


def test_hosted_model_without_a_key_is_reported_as_not_configured() -> None:
    from ai_service.core.config import Settings
    from ai_service.core.exceptions import LLMNotConfiguredError
    from ai_service.services.llm import SettingsLLMRegistry

    settings = Settings(
        _env_file=None,
        SECRET_KEY="x" * 32,
        DATABASE_URL="sqlite+aiosqlite://",
        LLM_API_KEY=None,
    )
    registry = SettingsLLMRegistry(settings)
    with pytest.raises(LLMNotConfiguredError):
        registry.get("hosted")
    assert registry.get("local").model == settings.LOCAL_LLM_MODEL  # the local one needs no key


# ---------- the client goes away


async def _stored_ids(
    session_factory: async_sessionmaker[AsyncSession],
) -> tuple[uuid.UUID, uuid.UUID, int]:
    async with session_factory() as session:
        conversation = (await session.scalars(select(Conversation))).one()
        user_message = (await session.scalars(select(Message))).first()
        assert user_message is not None
        return conversation.id, conversation.tenant_id, user_message.id


async def _assistant_messages(session_factory: async_sessionmaker[AsyncSession]) -> list[Message]:
    async with session_factory() as session:
        rows = await session.scalars(select(Message).where(Message.role == "assistant"))
        return list(rows)


async def test_disconnect_closes_the_upstream_call_and_keeps_the_partial_answer(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
    caplog: pytest.LogCaptureFixture,
) -> None:
    await send(client, auth_headers, "set up a conversation")
    conversation_id, tenant_id, user_message_id = await _stored_ids(session_factory)
    async with session_factory() as session:  # start from a clean slate: drop the first answer
        for message in await session.scalars(select(Message).where(Message.role == "assistant")):
            await session.delete(message)
        await session.commit()

    provider = FakeProvider("fake-hosted", texts=("one ", "two ", "three ", "four "))
    events = provider.stream(LLMRequest([]))
    assert isinstance(await anext(events), StreamStart)  # who answers, no text yet
    first = await anext(events)
    assert isinstance(first, TextDelta)

    with caplog.at_level(logging.INFO, logger="ai_service.chat"):
        chunks = [
            chunk
            async for chunk in chat_stream(
                request=FakeRequest(connected_checks=2),  # connected for 2 tokens, then gone
                events=events,
                first=first,
                conversation_id=conversation_id,
                user_message_id=user_message_id,
                tenant_id=tenant_id,
                model="fake-hosted",
                session_factory=session_factory,
            )
        ]

    assert "done" not in "".join(chunks)
    assert chunks[0].startswith("event: start")
    assert len([c for c in chunks if c.startswith("event: token")]) == 2
    assert provider.closed  # the upstream call was closed: the model stops producing tokens
    (saved,) = await _assistant_messages(session_factory)
    assert (saved.content, saved.status) == ("one two ", "cancelled")
    messages = [record.message for record in caplog.records]
    assert "chat client disconnected after 2 chunks" in messages
    assert "chat upstream closed" in messages


async def test_cancelling_the_stream_task_still_saves_and_closes(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """What the server does when a connection drops while it is waiting for the next token."""
    await send(client, auth_headers, "set up a conversation")
    conversation_id, tenant_id, user_message_id = await _stored_ids(session_factory)
    async with session_factory() as session:
        for message in await session.scalars(select(Message).where(Message.role == "assistant")):
            await session.delete(message)
        await session.commit()

    provider = FakeProvider("fake-hosted", texts=("a ", "b ", "c ", "d "), delay=0.05)
    events = provider.stream(LLMRequest([]))
    assert isinstance(await anext(events), StreamStart)  # who answers, no text yet
    first = await anext(events)
    assert isinstance(first, TextDelta)
    stream = chat_stream(
        request=FakeRequest(connected_checks=10_000),
        events=events,
        first=first,
        conversation_id=conversation_id,
        user_message_id=user_message_id,
        tenant_id=tenant_id,
        model="fake-hosted",
        session_factory=session_factory,
    )
    received: list[str] = []

    async def read() -> None:
        async for chunk in stream:
            received.append(chunk)

    task = asyncio.create_task(read())
    await asyncio.sleep(0.12)  # a few tokens arrive...
    task.cancel()  # ...then the connection drops
    with pytest.raises(asyncio.CancelledError):
        await task

    assert provider.closed
    (saved,) = await _assistant_messages(session_factory)
    assert saved.status == "cancelled"
    assert saved.content.startswith("a b")
    assert saved.content != "a b c d "  # it did not run to the end


async def test_no_answer_text_means_nothing_is_saved_for_the_assistant(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    await send(client, auth_headers, "set up")
    conversation_id, tenant_id, user_message_id = await _stored_ids(session_factory)
    before = len(await _assistant_messages(session_factory))

    provider = FakeProvider(texts=())  # a model that answers with nothing but the finish event
    events = provider.stream(LLMRequest([]))
    assert isinstance(await anext(events), StreamStart)  # who answers, no text yet
    first = await anext(events)
    assert isinstance(first, Finish)
    chunks = [
        chunk
        async for chunk in chat_stream(
            request=FakeRequest(10),
            events=events,
            first=first,
            conversation_id=conversation_id,
            user_message_id=user_message_id,
            tenant_id=tenant_id,
            model="fake",
            session_factory=session_factory,
        )
    ]
    assert chunks[-1].startswith("event: done")
    assert len(await _assistant_messages(session_factory)) == before


# ---------- the client leaves before the first token (a slow model)


async def test_a_client_that_gives_up_while_the_model_is_thinking_leaves_nothing_behind(
    client: httpx.AsyncClient, auth_headers: dict[str, str], llm: FakeRegistry
) -> None:
    llm.hosted = FakeProvider("fake-hosted", first_delay=5)  # a very slow first token
    with pytest.raises(TimeoutError):
        await asyncio.wait_for(send(client, auth_headers, "hello"), timeout=0.2)

    assert llm.hosted.closed  # the upstream call was closed, not left running
    assert (await client.get(CONVERSATIONS_URL, headers=auth_headers)).json()["total"] == 0


class GoneRequest:
    """A request whose client has already disconnected."""

    state = SimpleNamespace(request_id="test-request")

    async def is_disconnected(self) -> bool:
        return True


async def test_a_client_gone_by_the_first_token_stores_nothing(
    register: Any,
    session_factory: async_sessionmaker[AsyncSession],
    llm: FakeRegistry,
) -> None:
    from typing import cast

    from fastapi import Request

    from ai_service.api.v1.chat import chat
    from ai_service.db.models import User
    from ai_service.schemas.chat import ChatRequest

    await register("gone@example.com")
    async with session_factory() as session:
        user = (await session.scalars(select(User))).one()
        response = await chat(
            body=ChatRequest(message="hello"),
            request=cast(Request, GoneRequest()),
            user=user,
            session=session,
            session_factory=session_factory,
            settings=get_settings(),
            llm=llm,
        )
        stored = await session.scalar(select(Conversation))

    assert response.status_code == 499
    assert llm.hosted.closed
    assert stored is None


async def test_the_call_is_labelled_and_asks_for_the_system_prompt_to_be_cached(
    client: httpx.AsyncClient, auth_headers: dict[str, str], llm: FakeRegistry
) -> None:
    await send(client, auth_headers, "hello", headers_extra={"X-Request-ID": "chat-req-1"})
    request = llm.hosted.requests[-1]

    assert request.cache_system is True  # the system prompt is stable: let the provider cache it
    assert request.messages[0].role == "system"  # stable part first, the new message last
    assert request.messages[-1].content == "hello"
    assert (request.context.feature, request.context.request_id) == ("chat", "chat-req-1")
    assert request.context.tenant_id and request.context.user_id


async def test_the_done_event_reports_cached_tokens(
    client: httpx.AsyncClient, auth_headers: dict[str, str], llm: FakeRegistry
) -> None:
    llm.hosted = FakeProvider("fake-hosted", stream_usage=Usage(10, 5, cache_read_tokens=90))
    _, events = await send(client, auth_headers, "hello")

    done = events[-1][1]
    assert (done["input_tokens"], done["output_tokens"], done["cache_read_tokens"]) == (100, 5, 90)


async def test_the_saved_message_names_the_model_that_really_answered(
    client: httpx.AsyncClient,
    auth_headers: dict[str, str],
    llm: FakeRegistry,
) -> None:
    # the registry returns a client that fell back to another model before the first token
    llm.hosted = FakeProvider("fallback-model", backend="local")
    _, events = await send(client, auth_headers, "hello")

    assert events[0][1]["model"] == "fallback-model"
    detail = (
        await client.get(
            f"{CONVERSATIONS_URL}/{events[0][1]['conversation_id']}", headers=auth_headers
        )
    ).json()
    assert detail["messages"][1]["model"] == "fallback-model"
