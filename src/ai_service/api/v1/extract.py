"""/extract: messy text to a validated object, using the model's structured output."""

import logging
import time
from typing import cast

from fastapi import APIRouter, Request

from ai_service.api.deps import CurrentUser, DbSession, Llm
from ai_service.core.middlewares import request_id_of
from ai_service.schemas.extract import Enquiry, ExtractMeta, ExtractRequest, ExtractResponse
from ai_service.services import extract_service
from ai_service.services.llm_types import Backend, CallContext

logger = logging.getLogger("ai_service.extract")

router = APIRouter(prefix="/extract", tags=["extract"])


@router.post("", response_model=ExtractResponse)
async def extract_enquiry(
    body: ExtractRequest, request: Request, user: CurrentUser, llm: Llm, session: DbSession
) -> ExtractResponse:
    """Read a messy student enquiry (email, WhatsApp-style message) and return clean fields.

    A value the text does not contain comes back as null or "unknown", never guessed.
    If the first reply is not valid, the model is shown its mistake and asked to fix it, up to
    twice: `meta.attempts` says how many tries it took. A model that declines answers
    `422 EXTRACTION_REFUSED`; one that cannot produce valid data answers `422 EXTRACTION_FAILED`.
    """
    # Authentication read the user inside a transaction, which keeps a database connection checked
    # out until the request ends. The model call below takes seconds: give the connection back
    # first, or a burst of requests empties the pool (QueuePool limit, answered as a 500).
    await session.commit()
    client = llm.get(body.backend)
    context = CallContext(
        request_id=request_id_of(request),
        tenant_id=str(user.tenant_id),
        user_id=str(user.id),
        feature="extract",
    )
    started = time.perf_counter()
    result = await extract_service.extract(client, Enquiry, body.text, context=context)
    latency_ms = round((time.perf_counter() - started) * 1000, 1)
    usage = result.usage
    logger.info(
        "extract %s ok in %.0f ms, %d attempt(s)",
        result.backend,
        latency_ms,
        result.attempts,
        extra={"request_id": context.request_id, "tenant_id": context.tenant_id},
    )
    return ExtractResponse(
        data=result.data,
        meta=ExtractMeta(
            backend=cast(Backend, result.backend),
            model=result.model,
            latency_ms=latency_ms,
            attempts=result.attempts,
            fallback_used=result.backend != body.backend,
            input_tokens=usage.prompt_tokens if usage else None,
            output_tokens=usage.output_tokens if usage else None,
            cache_read_tokens=usage.cache_read_tokens if usage else None,
        ),
    )
