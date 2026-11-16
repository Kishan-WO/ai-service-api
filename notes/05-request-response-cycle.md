# The request and response cycle in ai-service

How one HTTP request travels through middlewares, dependencies, routes and error handlers, and how it becomes a JSON response.

## 1. The layers, from outside in
```
client
  │
uvicorn                              reads the HTTP bytes, builds the ASGI scope
  │
ServerErrorMiddleware                Starlette; catches anything nobody else handled and returns a 500
  │
RequestContextMiddleware             mine: request id, timing, log line
  │
CORSMiddleware                       only if CORS_ORIGINS is set
  │
ExceptionMiddleware                  Starlette; runs my handlers for AppError, HTTP errors and 422
  │
Router → route                       path matching, then FastAPI's request handler
  │      ├─ read the body (JSON, or multipart for uploads)
  │      ├─ resolve dependencies: get_db_session, get_current_user, settings
  │      ├─ validate path, query and body with Pydantic
  │      └─ call the endpoint
  │
endpoint → service → database        thin endpoint, business rules in the service
```
The order comes from `create_app()` in `main.py`. `add_middleware` puts the **last one added outermost**, so `RequestContextMiddleware`, added after CORS, wraps it.

## 2. A request that works: `POST /api/v1/documents/upload`
1. **uvicorn** receives the request and calls the app with a `scope` (method, path, headers).
2. **`RequestContextMiddleware`** (`core/middlewares.py`):
   - Reads `X-Request-ID`. If it is 1 to 64 safe characters it is kept; otherwise a new UUID is made.
   - Stores the id in `scope["state"]["request_id"]`, a dictionary shared by everything below it, and starts a timer.
   - Wraps `send`, so it can add headers to the response later.
3. **CORS** (if enabled) answers preflight requests or passes the request on.
4. **The router** matches the path to `upload_document` in `api/v1/documents.py`.
5. **FastAPI's handler** reads the multipart body, then solves the dependencies of the endpoint:
   - `DbSession` opens an `AsyncSession` (`get_db_session`).
   - `CurrentUser` runs `get_current_user` (`api/deps.py`): it takes the `Authorization: Bearer` token, decodes the JWT, loads the user, and checks the token's `tenant_id` against the database. It writes `tenant_id` and `user_id` into the shared state, so the log line can show them.
   - `AppSettings` supplies the upload limit.
6. **Validation** checks the file and the optional `title` form field. A problem here becomes a 422.
7. **The endpoint** calls `document_service.read_upload` (reads in 1 MB chunks, stops at 20 MB), then `create_document`:
   - checks the extension and extracts the text (PDFs in `asyncio.to_thread`),
   - hashes the raw bytes with SHA-256 and looks for an existing `(tenant_id, content_hash)`,
   - inserts the row and **commits** (the service commits itself).
8. **`response_model=DocumentResponse`** turns the ORM object into JSON, leaving out `content`. The result is a 201 `JSONResponse`.
9. **On the way out**, the response passes back through the layers. `RequestContextMiddleware`'s wrapped `send` sees `http.response.start` and adds `X-Request-ID` and `X-Process-Time`.
10. **The body is sent**, then the `finally` block writes the one JSON log line (method, path, status, duration, request id, tenant id). Only after that does the session dependency close: the exit code of a `yield` dependency runs after the response is sent, which is why the commit lives in the service.

## 3. What happens when something fails
Every failure ends in the same envelope:
```json
{"error": {"code": "DOCUMENT_NOT_FOUND", "message": "Document not found.", "request_id": "…"}}
```
There are four routes to it, all registered in `register_error_handlers`.

| Source | Example | Handler | Result |
|---|---|---|---|
| **My `AppError` subclass**, raised anywhere (service, dependency) | wrong password, duplicate file, another tenant's document | `handle_app_error` | The class decides status and code: 401 `INVALID_CREDENTIALS`, 409 `DUPLICATE_DOCUMENT`, 404 `DOCUMENT_NOT_FOUND`, 413, 415 |
| **Starlette `HTTPException`** | unknown URL, wrong method | `handle_http_exception` | 404 `NOT_FOUND`, 405 `METHOD_NOT_ALLOWED` |
| **`RequestValidationError`** (Pydantic) | bad email, `limit=0`, bad UUID | `handle_validation_error` | 422 `VALIDATION_ERROR` with `details`: a list of `{location, message, type}` |
| **Any other exception** (a bug) | `RuntimeError` | `handle_unexpected_error` | 500 `INTERNAL_ERROR`, a generic message; the traceback goes to the log only |

The first three run inside `ExceptionMiddleware`, **below** my middleware. Their responses pass back out through `RequestContextMiddleware` and get the request-id and timing headers like any other response.

### The 500 case is different
```
endpoint raises RuntimeError
  → ExceptionMiddleware: no handler for plain Exception here, so it re-raises
  → RequestContextMiddleware: its `finally` logs the line with status 500, re-raises
  → ServerErrorMiddleware: calls handle_unexpected_error
```
`ServerErrorMiddleware` sits **outside** my middleware, so its response never passes through my wrapped `send`. That is why `error_response` puts `X-Request-ID` into the headers itself. Starlette also re-raises the exception afterwards so the server logs it, which is why the test client needs `raise_app_exceptions=False`.

## 4. Four short traces
- **No token** (`GET /auth/me`): `get_current_user` finds no token and raises `NotAuthenticatedError` → `handle_app_error` → **401** with `WWW-Authenticate: Bearer`, code `NOT_AUTHENTICATED`.
- **Another tenant's document** (`GET /documents/{id}`): the service queries `id == … AND tenant_id == user.tenant_id`, finds nothing, raises `DocumentNotFoundError` → **404**, identical to a document that never existed.
- **Bad body** (register with `"password": "short"`): FastAPI raises `RequestValidationError` before the endpoint runs → **422** listing every bad field at once.
- **Upload of a 21 MB file**: `read_upload` raises `PayloadTooLargeError` → **413** `FILE_TOO_LARGE`. Nothing is saved.

## 5. Streaming is a variation
For `GET /stream/demo` the endpoint returns a `StreamingResponse` around an async generator.
- The headers go out at the first `yield`, so `X-Process-Time` measures time to the first byte, not the whole stream.
- The log line is written after the last word.
- If the client hangs up, uvicorn cancels the generator. `word_stream` catches `CancelledError`, logs "cancelled after N words", and re-raises it.
- This is why the middleware is plain ASGI and not `BaseHTTPMiddleware`: the wrapper must not interfere with streaming.

## 6. Where the pieces live
| Concern | File |
|---|---|
| App assembly, middleware order, lifespan | `src/ai_service/main.py` |
| Request id, timing, log line, all error handlers | `src/ai_service/core/middlewares.py` |
| Error classes (status and code) | `src/ai_service/core/exceptions.py` |
| Envelope schema | `src/ai_service/schemas/common.py` |
| Token and tenant check | `src/ai_service/api/deps.py` |
| Business rules and commits | `src/ai_service/services/` |

Tests: `tests/test_middleware.py`, `tests/test_auth.py`, `tests/test_isolation.py`.
Related: `07-exception-handlers-vs-express.md`, `04-express_to_fastapi.md`.

## Quick check
- Which layer is outermost, and why do 500 responses need to set `X-Request-ID` themselves?
- Why does a missing-document error and an other-tenant error look identical?
- When does the session commit happen, and why is it not in the dependency?
