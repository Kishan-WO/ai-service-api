"""/auth endpoints."""

from typing import Annotated

from fastapi import APIRouter, Depends, status
from fastapi.security import OAuth2PasswordRequestForm

from ai_service.api.deps import CurrentUser, DbSession
from ai_service.db.models import Tenant
from ai_service.schemas.auth import (
    MeResponse,
    TenantRead,
    TokenResponse,
    UserLogin,
    UserRead,
    UserRegister,
)
from ai_service.services import auth_service

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=TokenResponse, status_code=status.HTTP_201_CREATED)
async def register(body: UserRegister, session: DbSession) -> TokenResponse:
    """Create a tenant and its first user, and return a token for it."""
    user = await auth_service.register(
        session, email=body.email, password=body.password, tenant_name=body.tenant_name
    )
    return auth_service.issue_token(user)


@router.post("/login", response_model=TokenResponse)
async def login(body: UserLogin, session: DbSession) -> TokenResponse:
    user = await auth_service.authenticate(session, email=body.email, password=body.password)
    return auth_service.issue_token(user)


@router.post("/token", response_model=TokenResponse, include_in_schema=True)
async def token(
    form: Annotated[OAuth2PasswordRequestForm, Depends()], session: DbSession
) -> TokenResponse:
    """OAuth2 password flow (form data) for Swagger "Authorize". `username` is the email."""
    user = await auth_service.authenticate(session, email=form.username, password=form.password)
    return auth_service.issue_token(user)


@router.get("/me", response_model=MeResponse)
async def me(user: CurrentUser, session: DbSession) -> MeResponse:
    tenant = await session.get(Tenant, user.tenant_id)
    assert tenant is not None  # guaranteed by the foreign key
    return MeResponse(user=UserRead.model_validate(user), tenant=TenantRead.model_validate(tenant))
