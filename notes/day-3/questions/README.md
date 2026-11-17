# Day 3: questions and answers

Questions I asked while reading the Day 1 to 3 foundation of `ai-service`, arranged **in the order of the Day 3 tasks** (the `Q` number in each title is the order in which I asked it).

Related notes: [`../README.md`](../README.md). Day 3 tasks are listed there.

## Task 1: tables, async SQLAlchemy and Alembic

| # | Question | File |
|---|---|---|
| 01 | Q16. Explain the engine and session factory | [01-engine-session-factory.md](01-engine-session-factory.md) |
| 02 | Q17. Meaning of async generator, async session, and autoflush | [02-asyncgenerator-asyncsession-autoflush.md](02-asyncgenerator-asyncsession-autoflush.md) |
| 03 | Q18. Explain `get_db_session` | [03-get-db-session.md](03-get-db-session.md) |

## Task 2: register / login with JWT, `get_current_user`

| # | Question | File |
|---|---|---|
| 04 | Q13. Explain the expiry block in `create_access_token` | [04-expiry-block.md](04-expiry-block.md) |
| 05 | Q14. What is `options` in `jwt.decode`? | [05-decode-options.md](05-decode-options.md) |
| 06 | Q19. Explain `OAuth2PasswordBearer` | [06-oauth2-scheme.md](06-oauth2-scheme.md) |
| 07 | Q20. Explain `OAuth2PasswordRequestForm` | [07-oauth2-password-request-form.md](07-oauth2-password-request-form.md) |
| 08 | Q21. Explain `get_current_user` / `/me` route, dependency handling and how values are passed | [08-get-current-user-dependencies.md](08-get-current-user-dependencies.md) |

## Task 3: documents (upload, schemas)

| # | Question | File |
|---|---|---|
| 09 | Q22. Meaning of `:=` and `b"".join(...)` | [09-walrus-bytes-join.md](09-walrus-bytes-join.md) |
| 10 | Q12. What is ConfigDict()? | [10-configdict.md](10-configdict.md) |

## Task 4: settings, shared client, error envelope, middleware, JSON logs

| # | Question | File |
|---|---|---|
| 11 | Q1. What is base setting in FastAPI? | [11-basesettings.md](11-basesettings.md) |
| 12 | Q2. Why have brackets while assigning default "development"? | [12-brackets-default.md](12-brackets-default.md) |
| 13 | Q3. Meaning of `...` in `Field(...)` | [13-ellipsis-field.md](13-ellipsis-field.md) |
| 14 | Q4. Explain this env_file syntax | [14-env-file-syntax.md](14-env-file-syntax.md) |
| 15 | Q15. Meaning of `*` in a parameter list (AppError) | [15-bare-star.md](15-bare-star.md) |
| 16 | Q5. Explain this logging line | [16-uvicorn-access-logger.md](16-uvicorn-access-logger.md) |
| 17 | Q6. What is json.dumps? | [17-json-dumps.md](17-json-dumps.md) |
| 18 | Q7. What is lifespan in FastAPI (instance attribute passed)? | [18-lifespan.md](18-lifespan.md) |
| 19 | Q8. Explain `app.state.http_client = httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=5.0))` | [19-http-client.md](19-http-client.md) |
| 20 | Q9. Explain the `setdefault("state", {})` line | [20-scope-setdefault-state.md](20-scope-setdefault-state.md) |
| 21 | Q10. Explain `send_with_headers` (especially the `http.response.start` block) | [21-send-with-headers.md](21-send-with-headers.md) |
| 22 | Q11. What is JSONResponse vs error response, and `send`? | [22-jsonresponse-vs-error-send.md](22-jsonresponse-vs-error-send.md) |
