"""Response schemas for documents. Uploads are multipart, so there is no JSON create schema."""

import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class DocumentResponse(BaseModel):
    """A document without its (possibly large) text. Used for uploads and lists."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    source: str
    content_hash: str
    # the ORM attribute is `metadata_json` (SQLAlchemy reserves `metadata`)
    metadata: dict[str, Any] = Field(validation_alias="metadata_json")
    created_at: datetime
    updated_at: datetime


class DocumentDetail(DocumentResponse):
    content: str


class DocumentList(BaseModel):
    items: list[DocumentResponse]
    total: int
    limit: int
    offset: int
