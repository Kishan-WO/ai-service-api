"""Schemas for POST /summarise."""

import uuid

from pydantic import BaseModel, Field, field_validator

from ai_service.services.llm import Backend

MAX_DOCUMENTS = 20


class SummariseRequest(BaseModel):
    document_ids: list[uuid.UUID] = Field(
        min_length=1,
        max_length=MAX_DOCUMENTS,
        description="Ids of the caller's own documents (from /documents)",
    )
    backend: Backend = Field(default="hosted", description="Which model writes the summaries")
    concurrency: int = Field(
        default=4, ge=1, le=8, description="Most model calls running at the same time"
    )

    @field_validator("document_ids")
    @classmethod
    def no_duplicates(cls, value: list[uuid.UUID]) -> list[uuid.UUID]:
        if len(set(value)) != len(value):
            raise ValueError("Each document may be listed only once.")
        return value


class SummaryItem(BaseModel):
    document_id: uuid.UUID
    title: str
    summary: str


class FailedItem(BaseModel):
    document_id: uuid.UUID
    title: str
    error: str = Field(description="The kind of error, for example OverloadedError")
    attempts: int


class SummariseMeta(BaseModel):
    documents_requested: int
    documents_summarised: int
    coverage: str = Field(description="For example 'all 10 documents' or '9 of 10 documents (...)'")
    concurrency: int
    peak_in_flight: int
    model_calls: int = Field(description="Every model call made, retries and the combine included")
    map_seconds: float
    combine_seconds: float
    input_tokens: int
    output_tokens: int


class SummariseResponse(BaseModel):
    overview: str
    summaries: list[SummaryItem]
    failed: list[FailedItem]
    meta: SummariseMeta
