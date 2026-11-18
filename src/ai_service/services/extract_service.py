"""Structured extraction: messy text in, a validated Pydantic object out.

If the model's reply is not valid, it is shown its own error and asked to fix it, at most
`MAX_REPAIRS` times. Every outcome is an answer or a clear, handled error: nothing a model
writes can reach the route as an unhandled parse error.
"""

import logging
from dataclasses import dataclass, replace

from pydantic import BaseModel, ValidationError

from ai_service.core.exceptions import (
    ExtractionFailedError,
    ExtractionRefusedError,
    LLMUnavailableError,
)
from ai_service.services.llm_types import (
    LENGTH,
    REFUSAL_REASONS,
    CallContext,
    ChatMessage,
    ContextTooLongError,
    LLMClient,
    LLMError,
    LLMRequest,
    Usage,
)
from ai_service.services.prompt_registry import get_prompt

logger = logging.getLogger("ai_service.extract")

MAX_REPAIRS = 2  # after the first try, the model may be asked to correct itself this many times
MAX_ATTEMPTS = MAX_REPAIRS + 1
# An Enquiry is about 150 tokens of JSON. A low cap turns a model that cannot stop writing
# (seen with the 270M local model) into a quick "cut off" error instead of a timeout.
EXTRACT_MAX_TOKENS = 400

# The prompt texts live in prompts/<name>/<version>.md. One version for the three of them: a new
# version (v2) changes all three files together. The system prompt's name is the one logged.
EXTRACT_PROMPT = "extract_system"
EXTRACT_USER_PROMPT = "extract_user"
EXTRACT_REPAIR_PROMPT = "extract_repair"
EXTRACT_PROMPT_VERSION = "v1"


@dataclass(frozen=True)
class Extraction[T: BaseModel]:
    data: T
    attempts: int  # 1 = valid at once; 2 or 3 = repaired after being shown its mistake
    usage: Usage | None  # all attempts added up
    model: str  # the model that really answered (a fallback can differ from the one asked for)
    backend: str


def _add(a: Usage | None, b: Usage | None) -> Usage | None:
    if a is None:
        return b
    return a if b is None else a + b


def _problems(exc: ValidationError) -> list[dict[str, str]]:
    return [
        {"field": ".".join(str(p) for p in e["loc"]) or "(whole reply)", "problem": e["msg"]}
        for e in exc.errors()
    ]


async def extract[T: BaseModel](
    client: LLMClient,
    model_cls: type[T],
    text: str,
    *,
    context: CallContext | None = None,
) -> Extraction[T]:
    prompt = get_prompt(EXTRACT_PROMPT, EXTRACT_PROMPT_VERSION)
    context = replace(
        context or CallContext(feature="extract"),
        prompt_name=prompt.name,
        prompt_version=prompt.version,
    )
    user_prompt = get_prompt(EXTRACT_USER_PROMPT, EXTRACT_PROMPT_VERSION)
    repair_prompt = get_prompt(EXTRACT_REPAIR_PROMPT, EXTRACT_PROMPT_VERSION)
    messages = [
        ChatMessage("system", prompt.render()),
        ChatMessage("user", user_prompt.render(message=text)),
    ]
    usage: Usage | None = None
    problems: list[dict[str, str]] = []

    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            response = await client.generate_structured(
                LLMRequest(messages, max_tokens=EXTRACT_MAX_TOKENS, context=context),
                schema_name=model_cls.__name__,
                schema=model_cls.model_json_schema(),
            )
        except ContextTooLongError as exc:
            logger.info("extract: the text does not fit the model: %s", exc)
            raise ExtractionFailedError("The text is too long for the model.") from exc
        except LLMError as exc:
            logger.warning("extract: provider failed (%s): %s", exc.kind, exc)
            raise LLMUnavailableError() from exc
        usage = _add(usage, response.usage)

        if response.stop_reason in REFUSAL_REASONS:
            # not a crash and not worth a retry: the model (or a safety filter) said no
            raise ExtractionRefusedError()
        if response.stop_reason == LENGTH:
            # the JSON is cut off; asking again with the same limit would cut it off again
            raise ExtractionFailedError("The model's answer was cut off before it finished.")
        try:
            data = model_cls.model_validate_json(response.text)
        except ValidationError as exc:
            problems = _problems(exc)
            logger.info("extract: attempt %d was not valid: %s", attempt, problems)
            messages = [
                *messages,
                ChatMessage("assistant", response.text),
                ChatMessage("user", repair_prompt.render(problems=problems)),
            ]
            continue
        return Extraction(data, attempt, usage, response.model, response.backend)

    raise ExtractionFailedError(details=problems)
