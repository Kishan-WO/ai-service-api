"""Conversations, stored messages, and the streaming generator behind POST /chat.

Every query is scoped to the tenant AND the user: a conversation of another tenant or another
user is reported exactly like a missing one.
"""

import asyncio
import json
import logging
import uuid
from collections.abc import AsyncGenerator, AsyncIterator
from datetime import UTC, datetime
from typing import Protocol

import anyio
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from ai_service.core.config import Settings
from ai_service.core.exceptions import ConversationNotFoundError
from ai_service.db.models import Conversation, Message
from ai_service.db.models.conversation import STATUS_CANCELLED, STATUS_COMPLETE, STATUS_ERROR
from ai_service.services.llm import ChatMessage, Finish, LLMError, StreamEvent, TextDelta
from ai_service.services.prompt_registry import Prompt, get_prompt

logger = logging.getLogger("ai_service.chat")


class DisconnectCheck(Protocol):
    async def is_disconnected(self) -> bool: ...


def chat_prompt(settings: Settings) -> Prompt:
    """The /chat system prompt, from the registry (the name and version are settings).

    It is the first thing in every request and never changes between turns, so a long one is
    read from the provider's prompt cache (cheaper and faster) from the second turn on.
    """
    return get_prompt(settings.CHAT_PROMPT_NAME, settings.CHAT_PROMPT_VERSION)


def sse_event(event: str, data: dict[str, object]) -> str:
    """One Server-Sent Event: an `event:` line, a `data:` line, and a blank line."""
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


# ---------- database


async def get_conversation(
    session: AsyncSession, *, tenant_id: uuid.UUID, user_id: uuid.UUID, conversation_id: uuid.UUID
) -> Conversation:
    conversation = await session.scalar(
        select(Conversation).where(
            Conversation.id == conversation_id,
            Conversation.tenant_id == tenant_id,
            Conversation.user_id == user_id,
        )
    )
    if conversation is None:
        raise ConversationNotFoundError()
    return conversation


async def get_conversation_with_messages(
    session: AsyncSession, *, tenant_id: uuid.UUID, user_id: uuid.UUID, conversation_id: uuid.UUID
) -> tuple[Conversation, list[Message]]:
    conversation = await get_conversation(
        session, tenant_id=tenant_id, user_id=user_id, conversation_id=conversation_id
    )
    rows = await session.scalars(
        select(Message).where(Message.conversation_id == conversation.id).order_by(Message.id)
    )
    return conversation, list(rows)


async def list_conversations(
    session: AsyncSession, *, tenant_id: uuid.UUID, user_id: uuid.UUID, limit: int, offset: int
) -> tuple[list[Conversation], int]:
    scope = (Conversation.tenant_id == tenant_id, Conversation.user_id == user_id)
    total = await session.scalar(select(func.count()).select_from(Conversation).where(*scope))
    rows = await session.scalars(
        select(Conversation)
        .where(*scope)
        .order_by(Conversation.updated_at.desc(), Conversation.id)
        .limit(limit)
        .offset(offset)
    )
    return list(rows), total or 0


async def delete_conversation(
    session: AsyncSession, *, tenant_id: uuid.UUID, user_id: uuid.UUID, conversation_id: uuid.UUID
) -> None:
    conversation = await get_conversation(
        session, tenant_id=tenant_id, user_id=user_id, conversation_id=conversation_id
    )
    await session.delete(conversation)
    await session.commit()


async def load_history(
    session: AsyncSession, *, conversation_id: uuid.UUID, limit: int
) -> list[ChatMessage]:
    """The last `limit` stored messages, oldest first, ready to send to the model."""
    rows = await session.scalars(
        select(Message)
        .where(Message.conversation_id == conversation_id, Message.content != "")
        .order_by(Message.id.desc())
        .limit(limit)
    )
    latest_first = list(rows)
    return [
        ChatMessage("user" if m.role == "user" else "assistant", m.content)
        for m in reversed(latest_first)
    ]


async def start_turn(
    session: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    conversation: Conversation | None,
    user_text: str,
) -> tuple[Conversation, Message]:
    """Create the conversation if needed and store the user's message, in one commit."""
    if conversation is None:
        conversation = Conversation(
            tenant_id=tenant_id,
            user_id=user_id,
            title=user_text[:117] + "..." if len(user_text) > 120 else user_text,
        )
        session.add(conversation)
        await session.flush()
    message = Message(
        conversation_id=conversation.id,
        tenant_id=tenant_id,
        role="user",
        content=user_text,
        status=STATUS_COMPLETE,
    )
    session.add(message)
    conversation.updated_at = datetime.now(UTC)
    await session.commit()
    return conversation, message


async def save_assistant_message(
    session_factory: async_sessionmaker[AsyncSession],
    *,
    tenant_id: uuid.UUID,
    conversation_id: uuid.UUID,
    content: str,
    status: str,
    model: str,
    finish: Finish | None,
) -> int:
    """Store the assistant's reply in a session of its own (the request's session is long gone)."""
    async with session_factory() as session:
        message = Message(
            conversation_id=conversation_id,
            tenant_id=tenant_id,
            role="assistant",
            content=content,
            status=status,
            model=model,
            stop_reason=finish.stop_reason if finish else None,
            input_tokens=finish.input_tokens if finish else None,
            output_tokens=finish.output_tokens if finish else None,
        )
        session.add(message)
        await session.execute(
            update(Conversation)
            .where(Conversation.id == conversation_id)
            .values(updated_at=datetime.now(UTC))
        )
        await session.commit()
        return message.id


# ---------- the stream


async def chat_stream(
    *,
    request: DisconnectCheck,
    events: AsyncGenerator[StreamEvent],
    first: StreamEvent,
    conversation_id: uuid.UUID,
    user_message_id: int,
    tenant_id: uuid.UUID,
    model: str,
    session_factory: async_sessionmaker[AsyncSession],
    log_context: dict[str, object] | None = None,
) -> AsyncIterator[str]:
    """Relay the model's answer as SSE events, collect it, and save it when the stream ends.

    Ends in one of three ways, and the saved message records which one:
      complete   the model finished            -> a `done` event is sent
      cancelled  the client went away          -> upstream call closed, partial text kept
      error      the provider failed mid-way   -> an `error` event is sent, the partial text is kept
    """
    extra = log_context or {}
    parts: list[str] = []
    chunks = 0
    finish: Finish | None = None
    status = STATUS_COMPLETE
    message_id: int | None = None

    async def persist() -> None:
        nonlocal message_id
        if message_id is not None or not parts:
            return
        message_id = await save_assistant_message(
            session_factory,
            tenant_id=tenant_id,
            conversation_id=conversation_id,
            content="".join(parts),
            status=status,
            model=model,
            finish=finish,
        )

    logger.info("chat stream started", extra=extra)
    try:
        yield sse_event(
            "start",
            {
                "conversation_id": str(conversation_id),
                "user_message_id": user_message_id,
                "model": model,
            },
        )
        pending: StreamEvent = first
        while True:
            if isinstance(pending, TextDelta):
                if await request.is_disconnected():
                    status = STATUS_CANCELLED
                    logger.info("chat client disconnected after %d chunks", chunks, extra=extra)
                    return
                parts.append(pending.text)
                chunks += 1
                yield sse_event("token", {"text": pending.text})
            elif isinstance(pending, Finish):
                finish = pending
            try:
                pending = await anext(events)
            except StopAsyncIteration:
                break
        await persist()
        yield sse_event(
            "done",
            {
                "message_id": message_id,
                "stop_reason": finish.stop_reason if finish else None,
                "input_tokens": finish.input_tokens if finish else None,
                "output_tokens": finish.output_tokens if finish else None,
                "cache_read_tokens": finish.cache_read_tokens if finish else None,
            },
        )
    except asyncio.CancelledError:
        # the server cancels the stream when the connection drops while we were waiting
        status = STATUS_CANCELLED
        logger.info("chat stream cancelled after %d chunks", chunks, extra=extra)
        raise
    except LLMError as exc:
        status = STATUS_ERROR
        logger.warning("chat stream failed after %d chunks: %s", chunks, exc, extra=extra)
        yield sse_event(
            "error",
            {
                "code": "LLM_STREAM_FAILED",
                "message": "The model stopped answering. Please try again.",
            },
        )
    finally:
        # Shielded, so the clean-up still finishes when this task is being cancelled.
        with anyio.CancelScope(shield=True):
            await events.aclose()  # closes the upstream call: no tokens are produced for nobody
            logger.info("chat upstream closed", extra=extra)
            await persist()
            logger.info(
                "chat stream finished: %s, %d chunks saved as message %s",
                status,
                chunks,
                message_id,
                extra=extra,
            )
