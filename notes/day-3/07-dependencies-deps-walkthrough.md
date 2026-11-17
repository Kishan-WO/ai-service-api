# `api/deps.py` explained: dependency injection and `get_current_user`

Question: what is happening in `deps.py` (skipping the imports)?

## 1. Dependency injection in one idea
Instead of building things inside every endpoint, an endpoint **declares what it needs** in its parameters. FastAPI calls the right functions, passes the results in, and cleans up afterwards.

```python
async def upload_document(file: UploadFile, user: CurrentUser, session: DbSession, settings: AppSettings): ...
```
Express comparison: middleware that attaches `req.user` and `req.db`, but here each need is explicit, typed and testable (`dependency_overrides`).

## 2. Type aliases with `Annotated` (lines 18-19)
```python
DbSession = Annotated[AsyncSession, Depends(get_db_session)]
AppSettings = Annotated[Settings, Depends(get_settings)]
```
`Annotated[Type, extra]` attaches extra information to a type. FastAPI reads `Depends(...)` from it.

Without the alias every endpoint would repeat:
```python
session: AsyncSession = Depends(get_db_session)
```
With it: `session: DbSession`. Same behaviour, shorter and consistent.

## 3. The token reader (lines 21-24)
```python
oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl=f"{get_settings().API_V1_PREFIX}/auth/token", auto_error=False
)
```
- It reads the `Authorization: Bearer <token>` header and returns the token string.
- `tokenUrl` tells Swagger where to send the username and password (the **Authorize** button; see `08-swagger-authorize-and-oauth2.md`).
- `auto_error=False`: if the header is missing, return `None` instead of raising FastAPI's own 401. That lets my code raise the project's error with the standard envelope.

## 4. `get_current_user` step by step (lines 27-49)
```python
async def get_current_user(request: Request, token: Annotated[str | None, Depends(oauth2_scheme)], session: DbSession) -> User:
```
It has **dependencies of its own**: the token reader and the database session.

| Step | Code | Purpose |
|---|---|---|
| 1 | `if token is None: raise NotAuthenticatedError()` | No header → 401 |
| 2 | `payload = decode_access_token(token)` | Check the signature and expiry |
| 3 | `uuid.UUID(payload["sub"])`, `uuid.UUID(payload["tenant_id"])` | Read the user id and tenant id from the token |
| 4 | `except jwt.PyJWTError, KeyError, ValueError, TypeError` | Any bad or incomplete token → one generic 401, no details leaked |
| 5 | `user = await session.get(User, user_id)` | Load the user from the database |
| 6 | `if user is None or user.tenant_id != token_tenant_id` | The token's tenant must match the user's real tenant |
| 7 | `request.state.tenant_id = ...` | Store ids for the request log line |
| 8 | `return user` | The endpoint receives the `User` object |

Notes:
- `except A, B, C:` without parentheses is valid in Python 3.14.
- `from None` hides the technical exception chain from the error.
- The tenant used by every query comes from `user.tenant_id`, never from the request.

## 5. The alias that uses it (line 52)
```python
CurrentUser = Annotated[User, Depends(get_current_user)]
```
An endpoint that writes `user: CurrentUser` is automatically protected: no valid token, no entry. The endpoint body only ever runs for an authenticated user.

## 6. The HTTP client dependency (lines 55-61)
```python
def get_http_client(request: Request) -> httpx.AsyncClient:
    return request.app.state.http_client
HttpClient = Annotated[httpx.AsyncClient, Depends(get_http_client)]
```
Hands the shared client created in `lifespan` to any endpoint that asks for `HttpClient`.

## 7. Good to know
- **Per-request cache:** if several dependencies need `get_db_session` in one request, FastAPI calls it **once** and shares the result. So `get_current_user` and the endpoint get the **same session**.
- **Order:** sub-dependencies run before the function that needs them.
- **Failing early:** if a dependency raises (401), the endpoint never runs.
- **Testing:** `app.dependency_overrides[get_db_session] = fake` swaps any dependency.

## Common mistakes
| Mistake | What happens |
|---|---|
| Taking `tenant_id` from a query or body | Anyone can read another tenant's data |
| `auto_error=True` while using my own error format | FastAPI's default 401 shape appears instead |
| Not checking that the token's tenant matches the user | A token could be forged with a swapped tenant |
| Catching `Exception` around token decoding | Hides real bugs; catch the specific errors |
| Creating the database session inside the endpoint | Cannot be overridden in tests |

## Quick check
- What does `Annotated[AsyncSession, Depends(get_db_session)]` save me from writing?
- Why is `auto_error=False` used?
- What are the checks in `get_current_user`, in order?
- Why is the tenant taken from the user and never from the request?
- Why do `get_current_user` and the endpoint share one database session?
