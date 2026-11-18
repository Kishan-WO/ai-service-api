"""Intent router

Flow
----
1. Rule-based fast path  — regex/keyword check for the clearest signals (free, zero latency).
2. Small model classifier — cheap model classifies into one of KNOWN_INTENTS.
   • Confidence is judged by whether the model's reply is one of the exact labels.
   • If the reply is not a known label → intent is UNCLEAR.
3. Dispatch
   • KNOWN_INTENT  → specialised system prompt loaded from the registry → cheap model answers.
   • UNCLEAR       → no specialised prompt → large model answers from the general chat prompt.

Design notes
------------
- Both the classifier and the answerer share the same LLMRegistry; the caller picks which
  Backend to treat as "small" and which as "large".
- The service returns a RouterResult that includes every timing and cost figure so the caller
  can compare it to the always-large-model baseline.
- Nothing here touches the database; that is the route's job.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from typing import Literal

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

logger = logging.getLogger("ai_service.router")

# Intent vocabulary

Intent = Literal["admission", "fees", "schedule", "academic", "complaint", "other", "unclear"]

KNOWN_INTENTS: frozenset[Intent] = frozenset(
    {"admission", "fees", "schedule", "academic", "complaint", "other"}
)

# Registry prompt names for each intent (router_<intent>/v1.md)
_PROMPT_NAME: dict[str, str] = {intent: f"router_{intent}" for intent in KNOWN_INTENTS}
_PROMPT_VERSION = "v2"

# Classifier prompt: Day 7's v2 plus an `unclear` label (a request that fits nowhere goes up)
_CLASSIFIER_PROMPT_NAME = "classify_query"
_CLASSIFIER_PROMPT_VERSION = "v5"

# General chat prompt used when intent is unclear (falls back to the hosted/large backend)
_GENERAL_PROMPT_NAME = "chat_system"
_GENERAL_PROMPT_VERSION = "v1"

# Rule-based fast path (zero cost, zero latency)

# Each entry: (pattern, intent).  First match wins.
_RULES: list[tuple[re.Pattern[str], Intent]] = [
    # a problem that already happened is a complaint, whatever the topic (the Day 7 tie rule)
    (re.compile(r"\b(double.?charged?|charged twice|overcharged|chargeback)\b", re.I), "complaint"),
    (
        re.compile(r"\b(no access|can'?t log ?in|not uploaded|missing recording)\b", re.I),
        "complaint",
    ),
    # asking about the refund POLICY is a fees question
    (re.compile(r"\brefund polic(y|ies)\b", re.I), "fees"),
    # a greeting only when the WHOLE message is one ("Hi, what are the fees?" is not)
    (re.compile(r"^\s*(hi|hello|hey|thanks|thank you|thx|bye)[\s!.,?]*$", re.I), "other"),
]


def _rule_based_intent(message: str) -> Intent | None:
    """Return an intent if a cheap regex catches it, otherwise None (→ call the model)."""
    for pattern, intent in _RULES:
        if pattern.search(message):
            return intent
    return None


# Classifier output parser
_LABEL_RE = re.compile(
    r"CATEGORY:\s*(" + "|".join(KNOWN_INTENTS) + r")\b",
    re.I,
)

def _parse_intent(raw: str) -> Intent:
    """Extract the label from the classifier's reply.

    The v2 prompt replies with the bare label; a 'CATEGORY: <label>' line is accepted too.
    If the label is not one of the known ones the intent is 'unclear'.
    """
    m = _LABEL_RE.search(raw)
    if m:
        label = m.group(1).lower()
        if label in KNOWN_INTENTS:
            return label
    # Fallback: maybe the model just replied with the bare label
    stripped = raw.strip().lower()
    if stripped in KNOWN_INTENTS:
        return stripped
    return "unclear"

# Result shape
def _add_usage(a: Usage | None, b: Usage | None) -> Usage | None:
    if a is None:
        return b
    return a if b is None else a + b


@dataclass(frozen=True)
class RouterResult:
    """Everything the route needs to build its response and to log the cost comparison."""

    intent: Intent
    rule_matched: bool  # True → no model call for classification

    answer: str  # the final reply to send to the user
    answer_model: str  # which model produced the answer
    answer_backend: str

    classify_latency_ms: float  # 0 if rule matched
    answer_latency_ms: float
    total_latency_ms: float

    classify_usage: Usage | None = field(default=None)
    answer_usage: Usage | None = field(default=None)

    @property
    def total_usage(self) -> Usage | None:
        return _add_usage(self.classify_usage, self.answer_usage)

# Router

async def route(
    message: str,
    *,
    small_client: LLMClient,  # used for classification AND for known-intent answers
    large_client: LLMClient,  # used only when intent is unclear
    context: CallContext | None = None,
    max_tokens: int = 512,
    large_max_tokens: int = 2000,
) -> RouterResult:
    """Classify `message` and produce a specialised answer.

    Parameters
    ----------
    message:       the raw user message
    small_client:  cheap/fast LLM — classifier + known-intent answerer
    large_client:  expensive/capable LLM — unclear-intent fallback
    context:       logging metadata (tenant, user, request id)
    max_tokens:    output cap for a known-intent answer (small model)
    large_max_tokens: output cap when the large model answers. A thinking model spends most of it
                   on thinking (about 450 of 540 output tokens in the Day 8 measurement), so a
                   cap of 512 or 1000 can leave a truncated answer.
    """
    ctx = context or CallContext(feature="router")
    t0 = time.perf_counter()

    # ── 1. Rule-based fast path ──────────────────────────────────────────
    rule_intent = _rule_based_intent(message)
    classify_usage: Usage | None = None
    classify_latency_ms = 0.0

    if rule_intent is not None:
        intent: Intent = rule_intent
        rule_matched = True
        logger.info("router: rule matched → %s", intent, extra={"request_id": ctx.request_id})
    else:
        # ── 2. Small model classifies ────────────────────────────────────
        rule_matched = False
        classifier_prompt = get_prompt(_CLASSIFIER_PROMPT_NAME, _CLASSIFIER_PROMPT_VERSION)
        classify_ctx = CallContext(
            request_id=ctx.request_id,
            tenant_id=ctx.tenant_id,
            user_id=ctx.user_id,
            feature="router_classify",
            prompt_name=classifier_prompt.name,
            prompt_version=classifier_prompt.version,
        )
        t_classify = time.perf_counter()
        try:
            classify_resp = await small_client.generate(
                LLMRequest(
                    messages=[
                        ChatMessage("user", classifier_prompt.render(message=message)),
                    ],
                    max_tokens=20,  # the v2 prompt replies with one label (about 1 token)
                    context=classify_ctx,
                )
            )
        except LLMError as exc:
            logger.warning(
                "router: classifier failed (%s): %s — falling back to unclear",
                exc.__class__.__name__,
                exc,
            )
            classify_resp = None

        classify_latency_ms = round((time.perf_counter() - t_classify) * 1000, 1)

        if classify_resp is None:
            intent = "unclear"
        else:
            classify_usage = classify_resp.usage
            intent = _parse_intent(classify_resp.text)

        logger.info(
            "router: classifier → %s (%.0f ms)",
            intent,
            classify_latency_ms,
            extra={"request_id": ctx.request_id},
        )

    # ── 3. Dispatch to specialised or general prompt ─────────────────────
    if intent in KNOWN_INTENTS:
        answerer = small_client
        system_prompt = get_prompt(_PROMPT_NAME[intent], _PROMPT_VERSION)
        answer_ctx = CallContext(
            request_id=ctx.request_id,
            tenant_id=ctx.tenant_id,
            user_id=ctx.user_id,
            feature=f"router_answer_{intent}",
            prompt_name=system_prompt.name,
            prompt_version=system_prompt.version,
        )
    else:  # unclear → large model, general prompt
        answerer = large_client
        system_prompt = get_prompt(_GENERAL_PROMPT_NAME, _GENERAL_PROMPT_VERSION)
        answer_ctx = CallContext(
            request_id=ctx.request_id,
            tenant_id=ctx.tenant_id,
            user_id=ctx.user_id,
            feature="router_answer_unclear",
            prompt_name=system_prompt.name,
            prompt_version=system_prompt.version,
        )

    t_answer = time.perf_counter()
    try:
        answer_resp = await answerer.generate(
            LLMRequest(
                messages=[
                    ChatMessage("system", system_prompt.render()),
                    ChatMessage("user", message),
                ],
                max_tokens=max_tokens if intent in KNOWN_INTENTS else large_max_tokens,
                context=answer_ctx,
            )
        )
    except LLMError as exc:
        logger.warning("router: the answer call failed (%s): %s", exc.kind, exc)
        raise LLMUnavailableError() from exc
    answer_latency_ms = round((time.perf_counter() - t_answer) * 1000, 1)
    total_latency_ms = round((time.perf_counter() - t0) * 1000, 1)

    logger.info(
        "router: answered via %s/%s in %.0f ms (classify %.0f ms + answer %.0f ms)",
        answer_resp.backend,
        answer_resp.model,
        total_latency_ms,
        classify_latency_ms,
        answer_latency_ms,
        extra={"request_id": ctx.request_id},
    )

    return RouterResult(
        intent=intent,
        rule_matched=rule_matched,
        answer=answer_resp.text,
        answer_model=answer_resp.model,
        answer_backend=answer_resp.backend,
        classify_latency_ms=classify_latency_ms,
        answer_latency_ms=answer_latency_ms,
        total_latency_ms=total_latency_ms,
        classify_usage=classify_usage,
        answer_usage=answer_resp.usage,
    )
