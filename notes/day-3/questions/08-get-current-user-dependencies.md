# Q21. Explain `get_current_user` / `/me` route, dependency handling and how values are passed

```python
async def get_current_user(request: Request,
    token: Annotated[str | None, Depends(oauth2_scheme)], session: DbSession) -> User:
    if token is None:
        raise NotAuthenticatedError()
    try:
        payload = decode_access_token(token)
        user_id = uuid.UUID(payload["sub"])
        token_tenant_id = uuid.UUID(payload["tenant_id"])
    except jwt.PyJWTError, KeyError, ValueError, TypeError:
        raise NotAuthenticatedError("Invalid or expired token.") from None

    user = await session.get(User, user_id)
    if user is None or user.tenant_id != token_tenant_id:
        raise NotAuthenticatedError("Invalid or expired token.")

    request.state.tenant_id = str(user.tenant_id)
    request.state.user_id = str(user.id)
    return user

CurrentUser = Annotated[User, Depends(get_current_user)]

@router.get("/me", response_model=MeResponse)
async def me(user: CurrentUser, session: DbSession) -> MeResponse:
    tenant = await session.get(Tenant, user.tenant_id)
    assert tenant is not None
    return MeResponse(user=UserRead.model_validate(user), tenant=TenantRead.model_validate(tenant))
```

## Dependency tree
```
GET /me
└── me(user, session)
    ├── user: CurrentUser = Depends(get_current_user)
    │   ├── request: Request                 (injected by FastAPI)
    │   ├── token: Depends(oauth2_scheme)    -> reads Authorization header
    │   └── session: DbSession               -> Depends(get_db_session)
    └── session: DbSession                   (same instance, cached)
```
`CurrentUser` is an `Annotated` alias: same as `user: User = Depends(get_current_user)`.

## How FastAPI resolves it (depth-first)
1. `get_current_user` needs: `request` (passed directly), `token` (calls `oauth2_scheme(request)`; `None` if absent), `session` (runs `get_db_session` up to `yield`).
2. It calls `get_current_user(request=..., token=..., session=...)` matching **by name**; the return value becomes `user`.
3. `me`'s `session` points at the same dependency; results are **cached per request** (`use_cache=True`), so **one session**.
4. `me(user=..., session=...)` runs.
5. After the response, `get_db_session` resumes past `yield`: commit/rollback and close.

Values flow down by parameter name; return/yield values flow up. You never call these yourself.

## What `get_current_user` does
- `token is None` → reject (needed due to `auto_error=False`).
- `decode_access_token` verifies signature, expiry, required claims; `uuid.UUID(...)` converts strings; `except` covers bad/expired token, missing claim, malformed UUID, wrong type. `from None` hides the original exception; one generic message avoids leaking why.
- `session.get(User, user_id)`: user must still exist; token `tenant_id` must match DB tenant (multi-tenant isolation).
- `request.state.*` is backed by `scope["state"]` (same as the logging middleware's), so the middleware can log tenant/user after the request.
- **Syntax note:** `except A, B, C:` without parentheses is only valid in Python 3.14+ (PEP 758). Older: `except (A, B, C):`.

## The route
`user` is already authenticated when the body runs; `model_validate(user)` needs `from_attributes=True`; `assert` is stripped under `python -O`.

## Takeaways
- Matched by name/annotation; resolved inner-first; each dependency runs once per request.
- Errors in a dependency skip the route and go to exception handlers; session dependency still rolls back.
- Add `user: CurrentUser` to any route for authentication.
