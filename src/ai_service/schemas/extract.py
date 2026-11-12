"""/extract: the target shape (what the model must return) and the request and response."""

from typing import Literal

from pydantic import BaseModel, Field, field_validator

from ai_service.services.llm import Backend


class Enquiry(BaseModel):
    """What I want out of a messy student enquiry.

    Every field is required but many may be null: a field the text does not mention must be null
    (or "unknown"), never guessed. The descriptions are sent to the model as part of the schema.
    """

    student_name: str | None = Field(description="The student's name, null if not stated")
    phone: str | None = Field(
        description="Phone number, digits only (leading + allowed); null if not stated"
    )
    email: str | None = Field(description="Email address, null if not stated")
    city: str | None = Field(description="City the student lives in, null if not stated")
    course_interest: Literal[
        "python", "web-development", "data-science", "machine-learning", "other", "unknown"
    ] = Field(description="The course the student asks about; 'unknown' if it is not clear")
    budget_inr: int | None = Field(
        description="Budget in rupees as a whole number, null if not stated"
    )
    start_timing: Literal["immediately", "this-month", "later", "unknown"] = Field(
        description="When the student wants to begin"
    )
    urgency: Literal["low", "normal", "high"] = Field(
        description="high only if the text shows a deadline or asks for a quick reply"
    )
    language: Literal["english", "hindi", "hinglish", "gujarati", "other"] = Field(
        description="The language the message is written in"
    )
    summary: str = Field(description="One short sentence in English: what the student wants")


class ExtractRequest(BaseModel):
    text: str = Field(max_length=8000, description="The messy message to read")
    backend: Backend = Field(default="hosted", description="Which model reads it")

    @field_validator("text")
    @classmethod
    def not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("The text must not be empty.")
        return value


class ExtractMeta(BaseModel):
    backend: Backend
    model: str
    latency_ms: float
    attempts: int = Field(description="1 = valid on the first try; 2 = needed one retry")
    input_tokens: int | None
    output_tokens: int | None


class ExtractResponse(BaseModel):
    data: Enquiry
    meta: ExtractMeta
