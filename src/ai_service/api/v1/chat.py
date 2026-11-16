"""/chat endpoints: a streaming chat with stored, tenant-scoped conversations."""

import logging
import uuid
from typing import Annotated

from fastapi import APIRouter, Query, Request, Response, status
from fastapi.responses import StreamingResponse

from ai_service.api.deps import AppSettings, CurrentUser, DbSession, Llm, SessionFactory
from ai_service.core.exceptions import LLMUnavailableError
from ai_service.schemas.chat import (
    ChatRequest,
    ConversationDetail,
    ConversationList,
    ConversationResponse,
    MessageResponse,
)
from ai_service.services import chat_service
from ai_service.services.llm import (
    CallContext,
    ChatMessage,
    LLMError,
    LLMRequest,
    StreamStart,
)

logger = logging.getLogger("ai_service.chat")

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post(
    "",
    response_class=StreamingResponse,
    responses={200: {"content": {"text/event-stream": {}}, "description": "Server-Sent Events"}},
)
async def chat(
    body: ChatRequest,
    request: Request,
    user: CurrentUser,
    session: DbSession,
    session_factory: SessionFactory,
    settings: AppSettings,
    llm: Llm,
) -> Response:
    """Send a message and stream the answer.

    Events: `start` (ids), many `token` (`text`), then `done` (message id, stop reason, token
    counts) or `error`. Omit `conversation_id` to start a new conversation; the first event
    carries its id.
    """
    client = llm.get(body.backend)

    conversation = None
    history: list[ChatMessage] = []
    if body.conversation_id is not None:
        conversation = await chat_service.get_conversation(
            session,
            tenant_id=user.tenant_id,
            user_id=user.id,
            conversation_id=body.conversation_id,
        )
        history = await chat_service.load_history(
            session, conversation_id=conversation.id, limit=settings.CHAT_HISTORY_LIMIT
        )
    # Give the database connection back before the (slow) wait for the model; see /extract.
    # The session opens a new transaction by itself when start_turn needs it below.
    await session.commit()

    # Stable part first (system prompt, then the old messages), the new message last: that order
    # is what lets the provider reuse its cache of the prefix.
    messages = [
        ChatMessage("system", chat_service.system_prompt(settings)),
        *history,
        ChatMessage("user", body.message),
    ]
    call_context = CallContext(
        request_id=getattr(request.state, "request_id", None),
        tenant_id=str(user.tenant_id),
        user_id=str(user.id),
        feature="chat",
    )

    # Wait for the first text before answering. Until then nothing has been sent or stored, so a
    # provider that is down can still be reported as a normal 502, and nothing is left behind.
    # (Retries and the fallback backend also happen in this wait, below this route.)
    events = client.stream(LLMRequest(messages, cache_system=True, context=call_context))
    served_model = client.model
    try:
        first = await anext(events)
        if isinstance(first, StreamStart):  # which model really answers (maybe the fallback)
            served_model = first.model
            first = await anext(events)
    except (LLMError, StopAsyncIteration) as exc:
        await events.aclose()
        raise LLMUnavailableError() from exc
    except BaseException:  # the client left while we waited: close the upstream call
        await events.aclose()
        raise

    context: dict[str, object] = {
        "request_id": call_context.request_id,
        "tenant_id": call_context.tenant_id,
        "user_id": call_context.user_id,
    }
    if await request.is_disconnected():
        # The model can be slow, and the server is not told about a client that leaves before
        # the response starts. Do not store a question nobody is waiting for; stop the call.
        await events.aclose()
        logger.info("chat client left before the first token; nothing stored", extra=context)
        return Response(status_code=499)

    conversation, user_message = await chat_service.start_turn(
        session,
        tenant_id=user.tenant_id,
        user_id=user.id,
        conversation=conversation,
        user_text=body.message,
    )
    return StreamingResponse(
        chat_service.chat_stream(
            request=request,
            events=events,
            first=first,
            conversation_id=conversation.id,
            user_message_id=user_message.id,
            tenant_id=user.tenant_id,
            model=served_model,
            session_factory=session_factory,
            log_context=context,
        ),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "X-Conversation-ID": str(conversation.id),
        },
    )


@router.get("/conversations", response_model=ConversationList)
async def list_conversations(
    user: CurrentUser,
    session: DbSession,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> ConversationList:
    conversations, total = await chat_service.list_conversations(
        session, tenant_id=user.tenant_id, user_id=user.id, limit=limit, offset=offset
    )
    return ConversationList(
        items=[ConversationResponse.model_validate(c) for c in conversations],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/conversations/{conversation_id}", response_model=ConversationDetail)
async def get_conversation(
    conversation_id: uuid.UUID, user: CurrentUser, session: DbSession
) -> ConversationDetail:
    conversation, messages = await chat_service.get_conversation_with_messages(
        session, tenant_id=user.tenant_id, user_id=user.id, conversation_id=conversation_id
    )
    return ConversationDetail(
        id=conversation.id,
        title=conversation.title,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
        messages=[MessageResponse.model_validate(m) for m in messages],
    )


@router.delete("/conversations/{conversation_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_conversation(
    conversation_id: uuid.UUID, user: CurrentUser, session: DbSession
) -> Response:
    await chat_service.delete_conversation(
        session, tenant_id=user.tenant_id, user_id=user.id, conversation_id=conversation_id
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
