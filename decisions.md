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
