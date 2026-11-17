# Q19. Explain `OAuth2PasswordBearer`

```python
oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl=f"{get_settings().API_V1_PREFIX}/auth/token", auto_error=False
)
```

A FastAPI **security dependency** that extracts the Bearer token from the `Authorization` header and tells Swagger UI where to log in.

## What it does
With `Depends(oauth2_scheme)` it reads the header, expects `Bearer <token>`, and returns the token string. It does **not** validate; `decode_access_token` does.

## Arguments
**`tokenUrl`**: your login endpoint (e.g. `/api/v1/auth/token`), used for **documentation only**: Swagger's "Authorize" button posts username/password (form data) there. The endpoint must exist and return `{"access_token": "...", "token_type": "bearer"}`.

**`auto_error=False`**:
- `True` (default): missing/malformed header → immediate `401 Not authenticated`.
- `False`: returns `None`, letting you decide.

## Why `auto_error=False`
Control over the error response (e.g. your `AppError` envelope), and optional authentication:
```python
async def get_current_user(token: str | None = Depends(oauth2_scheme)):
    if token is None:
        raise UnauthorizedError("Missing authentication token")
    ...
```
```python
async def get_optional_user(token: str | None = Depends(oauth2_scheme)):
    if token is None:
        return None
```

## Things to know
- Type becomes `str | None`; you **must** handle `None`.
- `get_settings()` is called at import time, so settings must load then.
- Only reads the header (not cookies/query).
