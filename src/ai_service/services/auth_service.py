"""Registration and login. Services commit their own transactions."""

from functools import lru_cache

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ai_service.core.config import get_settings
from ai_service.core.exceptions import EmailAlreadyRegisteredError, InvalidCredentialsError
from ai_service.core.security import create_access_token, get_password_hash, verify_password
from ai_service.db.models import Tenant, User
from ai_service.schemas.auth import TokenResponse


def normalize_email(email: str) -> str:
    return email.strip().lower()


@lru_cache
def _dummy_hash() -> str:
    return get_password_hash("not-a-real-password")


async def register(session: AsyncSession, *, email: str, password: str, tenant_name: str) -> User:
    """Create a new tenant and its first user."""
    email = normalize_email(email)
    if await session.scalar(select(User.id).where(User.email == email)):
        raise EmailAlreadyRegisteredError()

    tenant = Tenant(name=tenant_name.strip())
    user = User(email=email, hashed_password=get_password_hash(password), tenant=tenant)
    session.add(user)
    try:
        await session.commit()
    except IntegrityError:  # two requests registered the same email at once
        await session.rollback()
        raise EmailAlreadyRegisteredError() from None
    return user


async def authenticate(session: AsyncSession, *, email: str, password: str) -> User:
    user = await session.scalar(select(User).where(User.email == normalize_email(email)))
    # Hash even when the user does not exist, so response time does not reveal valid emails.
    hashed = user.hashed_password if user else _dummy_hash()
    password_ok = verify_password(password, hashed)
    if user is None or not password_ok:
        raise InvalidCredentialsError()
    return user


def issue_token(user: User) -> TokenResponse:
    token = create_access_token({"sub": str(user.id), "tenant_id": str(user.tenant_id)})
    return TokenResponse(
        access_token=token, expires_in=get_settings().ACCESS_TOKEN_EXPIRE_MINUTES * 60
    )
