"""Request and response schemas for /chat."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from ai_service.services.llm import Backend


class ChatRequest(BaseModel):
    message: str = Field(max_length=8000, description="The user's new message")
    conversation_id: uuid.UUID | None = Field(
        default=None, description="Omit to start a new conversation"
    )
    backend: Backend = Field(default="hosted", description="Which model answers")

    @field_validator("message")
    @classmethod
    def not_blank(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("The message must not be empty.")
        return value


class MessageResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    role: Literal["user", "assistant"]
    content: str
    status: Literal["complete", "cancelled", "error"]
    model: str | None
    stop_reason: str | None
    input_tokens: int | None
    output_tokens: int | None
    created_at: datetime


class ConversationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    created_at: datetime
    updated_at: datetime


class ConversationDetail(ConversationResponse):
    messages: list[MessageResponse]


class ConversationList(BaseModel):
    items: list[ConversationResponse]
    total: int
    limit: int
    offset: int
