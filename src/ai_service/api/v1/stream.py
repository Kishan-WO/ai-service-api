"""/stream endpoints: Server-Sent Events."""

import asyncio
import json
import logging
from collections.abc import AsyncIterator
from typing import Annotated, Protocol

from fastapi import APIRouter, Query, Request
from fastapi.responses import StreamingResponse

from ai_service.api.deps import CurrentUser

logger = logging.getLogger("ai_service.stream")

router = APIRouter(prefix="/stream", tags=["stream"])

DEMO_TEXT = (
    "Streaming lets a client show an answer while it is still being written. "
    "A language model sends its reply in small pieces, and the server forwards "
    "each piece as soon as it exists instead of waiting for the whole answer."
)


class DisconnectCheck(Protocol):
    async def is_disconnected(self) -> bool: ...


def sse_event(event: str, data: dict[str, object]) -> str:
    """One Server-Sent Event: an `event:` line, a `data:` line, and a blank line."""
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


async def word_stream(
    request: DisconnectCheck,
    text: str,
    delay_seconds: float,
    log_context: dict[str, object] | None = None,
) -> AsyncIterator[str]:
    """Yield `text` word by word as SSE events, and stop quietly if the client goes away."""
    extra = log_context or {}
    words = text.split()
    sent = 0
    try:
        for index, word in enumerate(words):
            if await request.is_disconnected():
                logger.info(
                    "SSE client disconnected after %d of %d words", sent, len(words), extra=extra
                )
                return
            yield sse_event("token", {"index": index, "text": word})
            sent += 1
            await asyncio.sleep(delay_seconds)
        yield sse_event("done", {"words": sent})
    except asyncio.CancelledError:
        # the server cancels the stream when the connection drops while we were waiting
        logger.info("SSE stream cancelled after %d of %d words", sent, len(words), extra=extra)
        raise


@router.get("/demo")
async def stream_demo(
    request: Request,
    user: CurrentUser,
    delay_ms: Annotated[int, Query(ge=0, le=1000, description="Pause between words")] = 50,
) -> StreamingResponse:
    """A fake LLM stream: a paragraph sent one word at a time."""
    context = {
        "request_id": getattr(request.state, "request_id", None),
        "tenant_id": str(user.tenant_id),
        "user_id": str(user.id),
    }
    return StreamingResponse(
        word_stream(request, DEMO_TEXT, delay_ms / 1000, context),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
