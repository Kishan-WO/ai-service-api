"""Shared FastAPI dependencies. The tenant always comes from the authenticated user."""

import uuid
from typing import Annotated

import httpx
import jwt
from fastapi import Depends, Request
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from ai_service.core.config import Settings, get_settings
from ai_service.core.exceptions import NotAuthenticatedError
from ai_service.core.security import decode_access_token
from ai_service.db.models import User
from ai_service.db.session import get_db_session

DbSession = Annotated[AsyncSession, Depends(get_db_session)]
AppSettings = Annotated[Settings, Depends(get_settings)]

# auto_error=False so a missing token produces our own error envelope.
oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl=f"{get_settings().API_V1_PREFIX}/auth/token", auto_error=False
)


async def get_current_user(
    request: Request,
    token: Annotated[str | None, Depends(oauth2_scheme)],
    session: DbSession,
) -> User:
    if token is None:
        raise NotAuthenticatedError()
    try:
        payload = decode_access_token(token)
        user_id = uuid.UUID(payload["sub"])
        token_tenant_id = uuid.UUID(payload["tenant_id"])
    except jwt.PyJWTError, KeyError, ValueError, TypeError:
        raise NotAuthenticatedError("Invalid or expired token.") from None

    user = await session.get(User, user_id)
    # The tenant in the token must match the user's real tenant.
    if user is None or user.tenant_id != token_tenant_id:
        raise NotAuthenticatedError("Invalid or expired token.")

    # picked up by the request-logging middleware
    request.state.tenant_id = str(user.tenant_id)
    request.state.user_id = str(user.id)
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def get_http_client(request: Request) -> httpx.AsyncClient:
    """The shared client created once in the app lifespan."""
    client: httpx.AsyncClient = request.app.state.http_client
    return client


HttpClient = Annotated[httpx.AsyncClient, Depends(get_http_client)]
