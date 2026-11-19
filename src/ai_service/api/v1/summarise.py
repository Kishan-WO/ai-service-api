"""POST /summarise: summarise several stored documents in parallel, then combine (Day 8, task 4).

The work is in `summarise_service`: parallel calls limited by a semaphore, one retry for a failed
document, a stop when too many fail, and a combined overview that says how many documents it
covers. This route loads the caller's documents, runs the chain and shapes the answer.
"""

import logging

from fastapi import APIRouter, Request

from ai_service.api.deps import AppSettings, CurrentUser, DbSession, Llm
from ai_service.core.exceptions import DocumentTooLongError, SummariseFailedError
from ai_service.core.middlewares import request_id_of
from ai_service.schemas.summarise import (
    FailedItem,
    SummariseMeta,
    SummariseRequest,
    SummariseResponse,
    SummaryItem,
)
from ai_service.services import document_service
from ai_service.services.llm_types import CallContext
from ai_service.services.summarise_service import (
    Document,
    TooManyFailuresError,
    summarise_documents,
)

logger = logging.getLogger("ai_service.summarise")

router = APIRouter(prefix="/summarise", tags=["summarise"])


@router.post("", response_model=SummariseResponse)
async def summarise(
    body: SummariseRequest,
    request: Request,
    user: CurrentUser,
    llm: Llm,
    session: DbSession,
    settings: AppSettings,
) -> SummariseResponse:
    """Summarise each document (in parallel, at most `concurrency` calls at once), then combine.

    A document that fails is retried once. If at most 2 still fail, the overview is built from
    the rest and `failed` lists the missing ones; if more fail, the answer is a 502.
    """
    # Load every document of this tenant first (a missing or foreign id is a 404 for the request).
    loaded = [
        await document_service.get_document(session, tenant_id=user.tenant_id, document_id=i)
        for i in body.document_ids
    ]
    for doc in loaded:
        if len(doc.content) > settings.SUMMARISE_MAX_DOCUMENT_CHARS:
            raise DocumentTooLongError(
                f"Document '{doc.title}' has {len(doc.content):,} characters; "
                f"the limit is {settings.SUMMARISE_MAX_DOCUMENT_CHARS:,}.",
                details={"document_id": str(doc.id)},
            )
    titles = {str(d.id): d.title for d in loaded}
    docs = [Document(str(d.id), d.content) for d in loaded]
    # Release the DB connection before the (slow) model calls.
    await session.commit()

    context = CallContext(
        request_id=request_id_of(request),
        tenant_id=str(user.tenant_id),
        user_id=str(user.id),
        feature="summarise",
    )
    try:
        result = await summarise_documents(
            docs, llm.get(body.backend), concurrency=body.concurrency, context=context
        )
    except TooManyFailuresError as exc:
        logger.warning("summarise: %s", exc, extra={"request_id": context.request_id})
        raise SummariseFailedError(
            details=[
                {"document_id": f.id, "title": titles[f.id], "error": f.error} for f in exc.failed
            ]
        ) from exc

    return SummariseResponse(
        overview=result.overview,
        summaries=[
            SummaryItem(document_id=i, title=titles[i], summary=s)
            for i, s in result.summaries.items()
        ],
        failed=[
            FailedItem(document_id=f.id, title=titles[f.id], error=f.error, attempts=f.attempts)
            for f in result.failed
        ],
        meta=SummariseMeta(
            documents_requested=result.total_documents,
            documents_summarised=len(result.summaries),
            coverage=result.coverage,
            concurrency=body.concurrency,
            peak_in_flight=result.peak_in_flight,
            model_calls=result.calls,
            map_seconds=result.map_seconds,
            combine_seconds=result.combine_seconds,
            input_tokens=result.usage.prompt_tokens,
            output_tokens=result.usage.output_tokens,
        ),
    )
