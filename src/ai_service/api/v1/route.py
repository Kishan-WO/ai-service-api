"""POST /route

Classifies the user's message with a small model, dispatches to a specialised prompt, and
returns the answer.  Unclear messages fall through to the large model using the general prompt.
"""

import logging

from fastapi import APIRouter, Request

from ai_service.api.deps import AppSettings, CurrentUser, DbSession, Llm
from ai_service.core.middlewares import request_id_of
from ai_service.schemas.route import RouteMeta, RouteRequest, RouteResponse
from ai_service.services import router_service
from ai_service.services.llm_types import CallContext

logger = logging.getLogger("ai_service.route")

router = APIRouter(prefix="/route", tags=["route"])


@router.post("", response_model=RouteResponse)
async def route_message(
    body: RouteRequest,
    request: Request,
    user: CurrentUser,
    llm: Llm,
    session: DbSession,
    settings: AppSettings,
) -> RouteResponse:
    """Classify `message` and return a specialised answer.

    The small backend classifies the intent (admission / fees / schedule / academic /
    complaint / other) and answers with a specialised system prompt.
    Messages whose intent cannot be determined are answered by the large backend using the
    general chat prompt.

    The `meta` field carries full timing and token counts so you can compare the router's cost
    against the always-large-model baseline.
    """
    # Release the DB connection before the (potentially slow) model calls.
    await session.commit()

    context = CallContext(
        request_id=request_id_of(request),
        tenant_id=str(user.tenant_id),
        user_id=str(user.id),
        feature="route",
    )

    small_client = llm.get(body.small_backend)
    large_backend = body.large_backend or ("hosted_large" if settings.LLM_LARGE_MODEL else "hosted")
    large_client = llm.get(large_backend)

    result = await router_service.route(
        body.message,
        small_client=small_client,
        large_client=large_client,
        context=context,
    )

    cu = result.classify_usage
    au = result.answer_usage

    logger.info(
        "route: intent=%s rule=%s backend=%s latency=%.0f ms",
        result.intent,
        result.rule_matched,
        result.answer_backend,
        result.total_latency_ms,
        extra={"request_id": context.request_id, "tenant_id": context.tenant_id},
    )

    return RouteResponse(
        answer=result.answer,
        meta=RouteMeta(
            intent=result.intent,
            rule_matched=result.rule_matched,
            answer_model=result.answer_model,
            answer_backend=result.answer_backend,
            classify_latency_ms=result.classify_latency_ms,
            answer_latency_ms=result.answer_latency_ms,
            total_latency_ms=result.total_latency_ms,
            classify_input_tokens=cu.prompt_tokens if cu else None,
            classify_output_tokens=cu.output_tokens if cu else None,
            answer_input_tokens=au.prompt_tokens if au else None,
            answer_output_tokens=au.output_tokens if au else None,
        ),
    )
