"""/extract: messy text to a validated object, using the model's structured output."""

import logging
import time

from fastapi import APIRouter

from ai_service.api.deps import CurrentUser, Llm
from ai_service.schemas.extract import Enquiry, ExtractMeta, ExtractRequest, ExtractResponse
from ai_service.services import extract_service

logger = logging.getLogger("ai_service.extract")

router = APIRouter(prefix="/extract", tags=["extract"])


@router.post("", response_model=ExtractResponse)
async def extract_enquiry(body: ExtractRequest, user: CurrentUser, llm: Llm) -> ExtractResponse:
    """Read a messy student enquiry (email, WhatsApp-style message) and return clean fields.

    A value the text does not contain comes back as null or "unknown", never guessed.
    `meta.attempts` is 2 when the first reply was not valid and the model had to correct itself.
    """
    provider = llm.get(body.backend)
    started = time.perf_counter()
    result = await extract_service.extract(provider, Enquiry, body.text)
    latency_ms = round((time.perf_counter() - started) * 1000, 1)
    logger.info(
        "extract %s ok in %.0f ms, %d attempt(s)",
        body.backend,
        latency_ms,
        result.attempts,
        extra={"tenant_id": str(user.tenant_id), "user_id": str(user.id)},
    )
    return ExtractResponse(
        data=result.data,
        meta=ExtractMeta(
            backend=body.backend,
            model=provider.model,
            latency_ms=latency_ms,
            attempts=result.attempts,
            input_tokens=result.input_tokens,
            output_tokens=result.output_tokens,
        ),
    )
