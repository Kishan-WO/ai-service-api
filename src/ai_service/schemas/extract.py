"""/extract: the target shape (what the model must return) and the request and response."""

import re
from typing import Literal

from pydantic import BaseModel, Field, ValidationInfo, field_validator

from ai_service.services.llm import Backend

MAX_NAME_LENGTH = 60
MAX_BUDGET_INR = 10_000_000  # one crore: no course in this domain costs more
_PHONE = re.compile(r"\+?[\d\s\-()]+")
_EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")


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

    # Sanity checks the JSON schema cannot express. A model that returns the right TYPES can still
    # return nonsense (seen with the 270M local model: phone "python", a budget of 5 x 10^15, the
    # whole message as the name). These are not sent to the model; a failing check makes
    # extract_service show the model its own error and ask again (the repair loop).

    @field_validator("student_name", "city")
    @classmethod
    def _looks_like_a_name(cls, value: str | None, info: ValidationInfo) -> str | None:
        if value is not None and len(value) > MAX_NAME_LENGTH:
            raise ValueError(
                f"{info.field_name} must be at most {MAX_NAME_LENGTH} characters: "
                "copy only the name, not a sentence from the message"
            )
        return value

    @field_validator("phone")
    @classmethod
    def _looks_like_a_phone(cls, value: str | None) -> str | None:
        if value is not None:
            digits = sum(ch.isdigit() for ch in value)
            if not _PHONE.fullmatch(value) or not 8 <= digits <= 15:
                raise ValueError(
                    "phone must hold 8 to 15 digits (a leading + is allowed); "
                    "use null when the text has no phone number"
                )
        return value

    @field_validator("email")
    @classmethod
    def _looks_like_an_email(cls, value: str | None) -> str | None:
        if value is not None and not _EMAIL.fullmatch(value):
            raise ValueError("email must look like name@domain.tld; use null if there is none")
        return value

    @field_validator("budget_inr")
    @classmethod
    def _is_a_believable_budget(cls, value: int | None) -> int | None:
        if value is not None and not 0 <= value <= MAX_BUDGET_INR:
            raise ValueError(
                f"budget_inr must be between 0 and {MAX_BUDGET_INR:,} rupees; "
                "use null when the text gives no budget"
            )
        return value


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
    backend: Backend = Field(description="The backend that answered (not always the one asked for)")
    model: str
    latency_ms: float
    attempts: int = Field(
        description="1 = valid at once; 2 or 3 = the model was shown its mistake and fixed it"
    )
    fallback_used: bool = Field(
        default=False, description="True when the requested backend failed and another answered"
    )
    input_tokens: int | None = Field(description="All attempts added up, cached input included")
    output_tokens: int | None
    cache_read_tokens: int | None = Field(
        default=None, description="Part of the input that was read from the provider cache"
    )


class ExtractResponse(BaseModel):
    data: Enquiry
    meta: ExtractMeta
