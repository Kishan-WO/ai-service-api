"""Schemas for POST /route."""

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from ai_service.services.llm import Backend

# The intents the router knows about + "unclear" for unrecognised messages
RouteIntent = Literal["admission", "fees", "schedule", "academic", "complaint", "other", "unclear"]


class RouteRequest(BaseModel):
    message: str = Field(max_length=4000, description="The raw user message to route and answer")
    small_backend: Backend = Field(
        default="local",
        description="Backend used for classification and known-intent answers (should be cheap)",
    )
    large_backend: Backend | None = Field(
        default=None,
        description=(
            "Backend used only when the intent is unclear. Default: `hosted_large` when "
            "LLM_LARGE_MODEL is set, otherwise `hosted`"
        ),
    )

    @field_validator("message")
    @classmethod
    def not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("The message must not be empty.")
        return value


class RouteMeta(BaseModel):
    intent: RouteIntent
    rule_matched: bool = Field(
        description="True if a regex/keyword matched (no model call used for classification)"
    )
    answer_model: str
    answer_backend: str
    classify_latency_ms: float = Field(description="0 when rule_matched is True")
    answer_latency_ms: float
    total_latency_ms: float
    classify_input_tokens: int | None = None
    classify_output_tokens: int | None = None
    answer_input_tokens: int | None = None
    answer_output_tokens: int | None = None


class RouteResponse(BaseModel):
    answer: str
    meta: RouteMeta
