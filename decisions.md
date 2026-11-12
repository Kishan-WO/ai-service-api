# Architecture & Technology Decisions

Every choice documented with reasoning and justification.

## Day 3: FastAPI Base
1. **Packaging**: We chose `uv` workspace structure over plain pip / poetry because dependency resolution and virtual environments are significantly faster (< 1s vs 30s+).
2. **Environment & Secrets Validation**: We chose strictly required environment fields without hardcoded defaults for `SECRET_KEY` (minimum 32 characters required) and `DATABASE_URL` (must use an async scheme like `postgresql+asyncpg://`). `ENVIRONMENT` is constrained to `Literal["development", "staging", "production", "testing"]`. Any invalid or missing configuration immediately raises a `ValidationError` at startup.
3. **Password Hashing**: We chose `pwdlib[argon2]` over `bcrypt`/`passlib` because `passlib` has been unmaintained since 2020 and fails on Python 3.14 due to missing `crypt` module.
4. **Database Driver**: We chose `asyncpg` + `SQLAlchemy 2.0 (async)` over synchronous drivers because FastAPI is an async ASGI framework and non-blocking I/O is critical for concurrency.
5. **Deduplication Strategy**: We chose SHA-256 content hashing with a composite unique index on `(tenant_id, content_hash)` over document-level filename checks so re-uploading identical content is detected regardless of the filename.
6. **Multi-Tenancy Model**: We chose a shared-database, shared-schema architecture with a strict `tenant_id` column enforced at the repository/dependency layer because it provides clean resource sharing with minimal operational complexity at early stage.
7. **Transactions are committed in services**: services own `commit()` and handle `IntegrityError` for races (same email or same file at once). The session dependency only opens and closes the session, because its exit code runs after the response is sent.
8. **Error envelope**: every error is `{"error": {"code", "message", "request_id", "details?"}}`. Application errors are `AppError` subclasses with a stable `code`; Starlette HTTP errors, validation errors and unexpected exceptions go through the same shape. Unexpected errors never leak their message.
9. **Document hash covers the raw bytes**: SHA-256 of the uploaded file, so the same file is detected whatever its name, and a changed PDF is a different document. Uniqueness is per tenant `(tenant_id, content_hash)`.
10. **Lists never include `content`**: `DocumentResponse` is a summary, `DocumentDetail` adds the text. A page of 100 documents cannot return gigabytes.
11. **Uploads are read in 1 MB chunks** and rejected with 413 as soon as the total passes the limit; PDF parsing runs in `asyncio.to_thread` because `pypdf` blocks.
12. **Two login endpoints**: `POST /auth/login` takes JSON, `POST /auth/token` takes the OAuth2 password form so Swagger's Authorize button works. Both use the same service.
13. **Token tenant must match the user's tenant**: `get_current_user` loads the user and rejects the token when its `tenant_id` claim differs from the database, so a claim cannot be swapped. `decode_access_token` also requires `exp`, `iat`, `sub` and `tenant_id`.
14. **The stream demo requires authentication**, like every future AI endpoint will.
15. **`email-validator`** was added for `EmailStr`; `CORS_ORIGINS` is optional and adds the CORS middleware only when set.

## Day 5: LLM integration (chat, streaming, structured output)
16. **One SDK for both models**: the `openai` SDK talks to Gemini (hosted) and Ollama (local) because both copy the OpenAI chat-completions protocol (Day 4). A request picks one with `backend: "hosted" | "local"`. Routes depend on a small `LLMProvider` protocol, so tests use a fake and never touch the network or a key.
17. **Providers are optional at start-up**: the service starts without `LLM_API_KEY`; only the hosted backend answers `503 LLM_NOT_CONFIGURED`. One client per backend is built on first use and closed in the lifespan.
18. **`conversations` and `messages` carry `tenant_id` (and conversations `user_id`)**: every query filters on tenant and user, and another tenant's or user's conversation is a 404, like documents. Message ids are an increasing integer, so "oldest first" is exact even when two rows share a timestamp.
19. **The history sent to the model is the last `CHAT_HISTORY_LIMIT` stored messages** (default 20) plus a system prompt that is never stored. The cap keeps cost and latency flat (Day 4 task 5); summarising old messages is a later step.
20. **Nothing is stored until the model has produced its first event**: `POST /chat` waits for the first event, and only then saves the conversation and the user message and starts answering. A provider that is down is a plain `502` and leaves no half-finished rows.
21. **The reply is saved by the stream itself**, in a session of its own (`get_session_factory`), because the request's session is gone by the time the stream ends. Its status says how it ended: `complete`, `cancelled` (client left, partial text kept) or `error` (provider failed mid-way, partial text kept). An empty reply is not saved.
22. **Errors in the middle of a stream are SSE events** (`event: error` with a generic message), because the `200` status line is already sent. Details go to the log only.
23. **`/extract` uses native structured output**: the JSON Schema comes from the Pydantic model (`Enquiry.model_json_schema()`), every field is required but may be `null` / `"unknown"` (the model is told never to guess), and the reply is validated with `model_validate_json`. One retry shows the model its own validation error; then `422 EXTRACTION_FAILED`. A reply cut off by the token limit is not retried.
24. **The text to extract is passed inside `<message>` tags** and the system prompt says it is data, not instructions (prompt-injection hygiene; there is a sample for it in the comparison script).
