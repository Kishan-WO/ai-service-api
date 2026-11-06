# Gotchas and Surprises

Records unexpected behaviors, bugs, and lessons learned during development.

## Day 3: FastAPI Base
- **Passlib vs Pwdlib**: `passlib` uses the deprecated `crypt` module which is completely removed in Python 3.13+. We use `pwdlib[argon2]` which is modern, secure, and officially recommended for FastAPI.
- **Tenant ID Source**: Never accept `tenant_id` from request parameters or body. It must always be decoded from the authenticated user's JWT claim to prevent tenant leakage.
- **Cross-Tenant Status Code**: Accessing another tenant's resource must return `404 Not Found` rather than `403 Forbidden` to prevent resource ID enumeration.
- **Async Database Sessions**: Always use `async_sessionmaker` with `expire_on_commit=False` in async FastAPI dependencies to prevent unexpected attribute refresh queries after transaction commit.

- **Commit in the service, not after `yield`**: with FastAPI 0.162 the exit code of a `yield` dependency runs *after* the response has been sent. I measured it: the order was endpoint returns, response start, response body, dependency exit. A commit placed there means the client can get a 201 before the data is saved, and a failed commit is invisible to it. Services call `session.commit()` themselves; the one in `get_db_session` is now a harmless safety net.
- **Pure ASGI middleware for streaming**: `BaseHTTPMiddleware` wraps the response and complicates streaming and disconnect detection. `RequestContextMiddleware` is a plain ASGI class.
- **Unhandled errors bypass user middleware**: the `Exception` handler runs in Starlette's outermost `ServerErrorMiddleware`, outside my middleware, so it must add `X-Request-ID` itself. In tests, `httpx.ASGITransport` re-raises app exceptions unless `raise_app_exceptions=False`.
- **SQLite in tests needs `StaticPool`**: an in-memory SQLite database is per connection, so without it every new connection sees empty tables.
- **PostgreSQL `text` cannot contain NUL (`\x00`)**: uploads are stripped of NUL characters before saving, otherwise asyncpg raises an error.
- **Client disconnects can arrive as cancellation**: when the client hangs up while the generator is waiting, the server cancels it (`CancelledError`); `request.is_disconnected()` only catches the case where the generator is running. The stream handles and logs both. Seen against the real server: "SSE stream cancelled after 3 of 40 words".
- **Untrusted `X-Request-ID`**: a client-supplied id is only accepted when it is 1 to 64 safe characters; otherwise a new UUID is used (protects logs and headers from injection).
- **Python 3.14 `except A, B:`**: PEP 758 allows listing exception types without parentheses when there is no `as`. `ruff format` rewrites `except (A, B):` that way. It is valid, just unfamiliar.
- **Same message for unknown email and wrong password**, and a dummy hash is verified when the user does not exist, so neither the response nor its timing reveals which emails are registered.
- **Port clashes on Windows**: the host already ran PostgreSQL on 5432 and a Redis container on 6379, so the stack publishes 5433 and 6380.
