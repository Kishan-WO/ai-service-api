# Express to FastAPI: what I used in ai-service

The left column is the Express habit, the right column is what I wrote in this repo.

## Mapping
| Express | FastAPI (this repo) |
|---|---|
| `app.get("/x/:id", handler)` | `@router.get("/{document_id}")` with `document_id: uuid.UUID`; a bad id is a 422 before my code runs |
| `express.Router()` | `APIRouter(prefix="/documents", tags=[...])`, combined in `api/v1/router.py` |
| `app.use(cors())` | `CORSMiddleware`, added only when `CORS_ORIGINS` is set |
| middleware `(req, res, next)` | a plain ASGI class `RequestContextMiddleware` (`core/middlewares.py`) |
| joi / zod | Pydantic models: a bad body gives an automatic 422, which my handler turns into the error envelope |
| values attached to `req` (`req.user`) | dependency injection: `CurrentUser = Annotated[User, Depends(get_current_user)]` |
| `app.listen(8000)` | Uvicorn (an ASGI server), started by the Docker `command` |
| Swagger set up by hand | automatic OpenAPI at `/docs` and `/openapi.json` |
| Mongoose | SQLAlchemy 2.0 async (`Mapped[...]`) and Alembic |
| supertest | `httpx.AsyncClient(transport=ASGITransport(app=app))` |
| `res.status(404).json({...})` | `raise DocumentNotFoundError()`, handled in one place |
| `res.write()` / SSE | `StreamingResponse` over an async generator |
| `process.env` + dotenv | `pydantic-settings` (`core/config.py`), validated at start-up |
| `app.listen` callback / shared clients | `lifespan`: create the `httpx.AsyncClient` once, close it on shutdown |

## Request flow in this service
```
request
  -> RequestContextMiddleware      request id, timing, one JSON log line per request
  -> router + path/query/body validation (Pydantic)
  -> dependencies                  get_db_session, get_current_user (tenant comes from the token)
  -> endpoint                      thin: calls a service function
  -> service                       business rules, tenant-scoped queries, commits
  -> response / AppError           errors become {"error": {"code", "message", "request_id"}}
```

## Differences that surprised me
- **Dependencies replace middleware for most things.** Auth is a dependency, not middleware, so it shows up in the OpenAPI docs and can be overridden in tests with `app.dependency_overrides`.
- **`async def` vs `def` endpoints.** An `async def` endpoint runs on the event loop, so blocking calls (reading a PDF) must go to `asyncio.to_thread`. A plain `def` endpoint runs in a thread pool automatically.
- **Validation is part of the signature.** `Query(ge=1, le=100)`, `UploadFile`, `Form(...)` replace hand-written checks.
- **Errors are exceptions.** There is no `next(err)`. I raise an `AppError` subclass anywhere and exception handlers build the response.
- **`response_model` filters the output.** `DocumentResponse` has no `content` field, so a list never sends 20 MB of text per document.
- **Exit code of `yield` dependencies runs after the response is sent.** Commit inside the service, not after the `yield` (see `gotchas.md`).
- **The ASGI test client does not run `lifespan`** unless I enter it explicitly, so `app.state.http_client` does not exist in tests.

## Status codes I decided on
| Situation | Code |
|---|---|
| Missing or bad token | 401 with `WWW-Authenticate: Bearer` |
| Wrong email or password | 401, same message for both |
| Another tenant's document | 404 (never 403, so ids cannot be probed) |
| Malformed UUID in the path | 422 |
| Duplicate email or document | 409 |
| Unsupported extension | 415 |
| File over 20 MB | 413 |
| Unreadable file | 422 |

## See also
- `03-request-response-cycle.md`: one request traced through every layer, with the four error paths.
- `11-exception-handlers-vs-express.md`: why handler order does not matter but middleware order does.
