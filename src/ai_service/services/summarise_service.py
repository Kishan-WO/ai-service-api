"""Summarise many documents in parallel, then combine the summaries (Day 8, task 4).

A map-reduce chain:

    doc 1 -> summary 1 -+
    doc 2 -> summary 2 -+--> combine (one call) --> overview
    ...                 |
    doc N -> summary N -+      MAP: parallel, at most `concurrency` calls at once

The calls in the map step do not depend on each other, so they run together
(`asyncio.gather`). Three things keep that safe:

  * a semaphore limits how many calls are in flight (provider rate limit, our own connections);
  * `return_exceptions=True`, so one failed document does not throw away the other nine results;
  * an explicit policy for failures: retry the failed documents once, then continue without them
    and SAY so, or stop when too many failed. A failure is never dropped silently.
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field

from ai_service.core.exceptions import LLMUnavailableError
from ai_service.services.llm_types import (
    CallContext,
    ChatMessage,
    LLMClient,
    LLMError,
    LLMRequest,
    Usage,
)
from ai_service.services.prompt_registry import get_prompt

logger = logging.getLogger("ai_service.summarise")

_SUMMARISE_PROMPT = ("summarise_document", "v1")
_COMBINE_PROMPT = ("combine_summaries", "v1")


@dataclass(frozen=True)
class Document:
    id: str
    text: str


@dataclass(frozen=True)
class FailedDocument:
    id: str
    error: str  # the error kind, for example RateLimitedError
    attempts: int


@dataclass
class SummariseResult:
    overview: str
    summaries: dict[str, str]  # document id -> summary, only for the documents that worked
    failed: list[FailedDocument]
    total_documents: int
    map_seconds: float
    combine_seconds: float
    peak_in_flight: int  # the most map calls that were running at the same moment
    calls: int  # every model call made, retries included
    usage: Usage = field(default_factory=lambda: Usage(0, 0))

    @property
    def coverage(self) -> str:
        done = len(self.summaries)
        if not self.failed:
            return f"all {self.total_documents} documents"
        ids = ", ".join(f.id for f in self.failed)
        return f"{done} of {self.total_documents} documents (failed: {ids})"


class TooManyFailuresError(Exception):
    """More documents failed than the policy allows, so no combined result is built."""

    def __init__(self, failed: list[FailedDocument], total: int) -> None:
        super().__init__(f"{len(failed)} of {total} documents failed")
        self.failed = failed
        self.total = total


class _Counter:
    """Counts model calls and the highest number running at once (for the report and tests)."""

    def __init__(self) -> None:
        self.calls = 0
        self.in_flight = 0
        self.peak = 0
        self.usage = Usage(0, 0)

    def start(self) -> None:
        self.calls += 1
        self.in_flight += 1
        self.peak = max(self.peak, self.in_flight)

    def stop(self) -> None:
        self.in_flight -= 1


async def _summarise_one(
    doc: Document,
    client: LLMClient,
    gate: asyncio.Semaphore,
    counter: _Counter,
    *,
    timeout: float,
    max_tokens: int,
    context: CallContext,
) -> str:
    prompt = get_prompt(*_SUMMARISE_PROMPT)
    request = LLMRequest(
        messages=[ChatMessage("user", prompt.render(document=doc.text))],
        max_tokens=max_tokens,
        context=CallContext(
            request_id=context.request_id,
            tenant_id=context.tenant_id,
            user_id=context.user_id,
            feature="summarise_map",
            prompt_name=prompt.name,
            prompt_version=prompt.version,
        ),
    )
    async with gate:  # at most `concurrency` calls run at the same time
        counter.start()
        try:
            async with asyncio.timeout(timeout):  # a stuck call must not hold the whole fan-out
                response = await client.generate(request)
        finally:
            counter.stop()
    if response.usage:
        counter.usage = counter.usage + response.usage
    return response.text.strip()


async def _map(
    docs: list[Document],
    client: LLMClient,
    gate: asyncio.Semaphore,
    counter: _Counter,
    **options: object,
) -> list[str | BaseException]:
    """One summary per document, in the same order. A failed call leaves its exception."""
    return await asyncio.gather(
        *(_summarise_one(d, client, gate, counter, **options) for d in docs),  # type: ignore[arg-type]
        return_exceptions=True,
    )


async def summarise_documents(
    docs: list[Document],
    client: LLMClient,
    *,
    concurrency: int = 4,
    max_failures: int = 2,
    retry_failed: bool = True,
    timeout: float = 60.0,
    summary_max_tokens: int = 400,
    combine_max_tokens: int = 800,
    context: CallContext | None = None,
) -> SummariseResult:
    """Summarise every document (in parallel), then combine the summaries into one overview.

    concurrency   most model calls running at once in the map step
    max_failures  more failed documents than this (after the retry) stops the chain
    retry_failed  run the failed documents once more before giving up on them
    timeout       seconds for ONE call; a call that takes longer counts as failed
    """
    if not docs:
        raise ValueError("at least one document is needed")
    if len({d.id for d in docs}) != len(docs):
        raise ValueError("document ids must be unique")
    ctx = context or CallContext(feature="summarise")
    gate = asyncio.Semaphore(concurrency)
    counter = _Counter()
    options = {"timeout": timeout, "max_tokens": summary_max_tokens, "context": ctx}

    # ── MAP: all documents together, but never more than `concurrency` calls at once ──
    t_map = time.perf_counter()
    outcomes = await _map(docs, client, gate, counter, **options)
    attempts = dict.fromkeys((d.id for d in docs), 1)

    # ── retry only the failed documents, once ──
    if retry_failed:
        again = [d for d, r in zip(docs, outcomes, strict=True) if _is_failure(r)]
        if again:
            logger.warning("summarise: retrying %d failed document(s)", len(again))
            for d, redo in zip(
                again, await _map(again, client, gate, counter, **options), strict=True
            ):
                attempts[d.id] += 1
                outcomes[docs.index(d)] = redo
    map_seconds = time.perf_counter() - t_map

    summaries: dict[str, str] = {}
    failed: list[FailedDocument] = []
    for d, outcome in zip(docs, outcomes, strict=True):
        if isinstance(outcome, str):
            summaries[d.id] = outcome
        elif isinstance(outcome, (LLMError, TimeoutError)):
            failed.append(FailedDocument(d.id, _kind(outcome), attempts[d.id]))
        else:  # a bug (not a provider failure): do not hide it
            raise outcome

    # ── policy: too many failures, stop; a few, go on and report them ──
    if len(failed) > max_failures:
        raise TooManyFailuresError(failed, len(docs))
    if not summaries:
        raise TooManyFailuresError(failed, len(docs))

    # ── REDUCE: one call over the summaries (not the full documents) ──
    result = SummariseResult(
        overview="",
        summaries=summaries,
        failed=failed,
        total_documents=len(docs),
        map_seconds=round(map_seconds, 3),
        combine_seconds=0.0,
        peak_in_flight=counter.peak,
        calls=counter.calls,
    )
    prompt = get_prompt(*_COMBINE_PROMPT)
    coverage_rule = (
        "Say at the start that the overview covers all documents."
        if not failed
        else f"Say at the start that the overview covers only {result.coverage}, "
        "so a reader knows part of the handbook is missing."
    )
    body = "\n\n".join(f"[{doc_id}]\n{text}" for doc_id, text in summaries.items())
    t_combine = time.perf_counter()
    try:
        async with asyncio.timeout(timeout):
            response = await client.generate(
                LLMRequest(
                    messages=[
                        ChatMessage("user", prompt.render(summaries=body, coverage=coverage_rule))
                    ],
                    max_tokens=combine_max_tokens,
                    context=CallContext(
                        request_id=ctx.request_id,
                        tenant_id=ctx.tenant_id,
                        user_id=ctx.user_id,
                        feature="summarise_combine",
                        prompt_name=prompt.name,
                        prompt_version=prompt.version,
                    ),
                )
            )
    except (LLMError, TimeoutError) as exc:
        raise LLMUnavailableError() from exc
    counter.calls += 1
    result.overview = response.text.strip()
    result.combine_seconds = round(time.perf_counter() - t_combine, 3)
    result.calls = counter.calls
    result.usage = counter.usage + response.usage if response.usage else counter.usage
    return result


def _is_failure(result: object) -> bool:
    return isinstance(result, (LLMError, TimeoutError))


def _kind(exc: BaseException) -> str:
    return exc.kind if isinstance(exc, LLMError) else type(exc).__name__
