"""Schemas shared by every endpoint: the error envelope."""

from typing import Any

from pydantic import BaseModel


class ErrorDetail(BaseModel):
    code: str
    message: str
    request_id: str | None = None
    details: Any = None


class ErrorResponse(BaseModel):
    """{"error": {"code": "...", "message": "...", "request_id": "..."}}"""

    error: ErrorDetail
