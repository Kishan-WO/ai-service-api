"""Request and response schemas for authentication."""

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field


class UserRegister(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    tenant_name: str = Field(
        min_length=1, max_length=255, description="Name of the new organization"
    )


class UserLogin(BaseModel):
    email: str = Field(max_length=255)
    password: str = Field(max_length=128)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int = Field(description="Seconds until the token expires")


class TenantRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    tenant_id: uuid.UUID
    created_at: datetime


class MeResponse(BaseModel):
    user: UserRead
    tenant: TenantRead
