# Q20. Explain `OAuth2PasswordRequestForm`

```python
async def token(
    form: Annotated[OAuth2PasswordRequestForm, Depends()], session: DbSession
) -> TokenResponse:
```

A FastAPI helper that **reads login form fields** from an `application/x-www-form-urlencoded` body (OAuth2 password flow).

## What it gives you
```python
form.username      # required
form.password      # required
form.scope         # space-separated string
form.scopes        # list[str]
form.grant_type    # "password" (optional)
form.client_id     # optional
form.client_secret # optional
```
Missing `username`/`password` → automatic `422`.

## Why `Depends()` with no argument
Means "use the annotated type itself as the dependency". FastAPI calls the class; its `__init__` declares fields as `Form(...)`. `Annotated[X, Depends()]` is the modern style; older: `form: OAuth2PasswordRequestForm = Depends()`.

## Connection to `oauth2_scheme`
1. `tokenUrl` points to this endpoint.
2. Swagger sends `username`/`password` as **form data**.
3. You return `{"access_token": ..., "token_type": "bearer"}`.
4. Swagger then sends `Authorization: Bearer ...`.

## Typical endpoint
```python
@router.post("/auth/token")
async def token(form: Annotated[OAuth2PasswordRequestForm, Depends()], session: DbSession) -> TokenResponse:
    user = await authenticate(session, form.username, form.password)
    if user is None:
        raise UnauthorizedError("Incorrect username or password")
    access_token = create_access_token({"sub": str(user.id), "tenant_id": str(user.tenant_id)})
    return TokenResponse(access_token=access_token, token_type="bearer")
```

## Things to know
- Install `python-multipart`.
- Field is always `username`, even if it's an email.
- It's form data, not JSON:
```bash
curl -X POST http://localhost:8000/api/v1/auth/token -d "username=a@b.com&password=secret"
```
- `DbSession` is likely `Annotated[AsyncSession, Depends(get_db_session)]`.
- `OAuth2PasswordRequestFormStrict` requires `grant_type=password`.
