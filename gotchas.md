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

## Day 5: LLM integration
- **The OpenAI SDK 3.x has its own HTTP library (`httpx2`)**: `respx` patches `httpx` and does not see the SDK's calls, so a mocked test silently made a real connection attempt. Use `httpx2.MockTransport` as the SDK client's `http_client` (see `tests/test_llm_provider.py`). The "provider failure" tests passed by accident at first because a connection error is also an `LLMError`; each failure test now asserts that the fake server received the request.
- **Clean-up in a cancelled stream needs shielding**: when the client drops, the server cancels the generator, and any `await` in its `finally` is cancelled again immediately. The close-upstream and save-reply code runs inside `anyio.CancelScope(shield=True)`; without it the partial answer is never saved.
- **Closing the upstream call is what stops the billing**: leaving the OpenAI `AsyncStream` (`await stream.close()` in a `finally`) makes the provider stop generating. Tokens produced before the close are still billed.
- **`StreamingResponse` + `yield` dependencies**: the session dependency exits after the response is sent, so the stream saves the reply with its own session from `get_session_factory`. In tests that factory is overridden to the in-memory database; forgetting that sends the save to the real database.
- **Gemini sometimes sends the whole answer as one chunk** (small models especially), so a "stream" can contain a single `token` event. Ollama sends word by word.
- **`BigInteger` primary keys do not auto-increment on SQLite**: `BigInteger().with_variant(Integer, "sqlite")` keeps PostgreSQL on `BIGSERIAL` and the tests working.
- **Windows: `os.execvpe` does not replace the process**: a launcher script that used it left an orphaned server. Use `subprocess.call` and run it as a background task.
- **A valid shape is not a correct answer**: the 270M local model returns JSON that passes validation (phone `"python"`, the whole message as the email). Validation catches format, not truth.
- **A route handler is not cancelled when the client leaves before the response starts**: uvicorn only reports the disconnect to code that listens for it (a `StreamingResponse` does, a plain `await` inside the handler does not). Seen live: Gemini took 60 s to send its first event, `curl` gave up at 60 s, and the server still stored the question. `POST /chat` now checks `request.is_disconnected()` right after the first event and, if the client is gone, closes the upstream call and stores nothing (answers `499`).
- **Waiting for the first event means a slow model looks like a dead connection**: the response headers are only sent once the model has started answering, and Gemini's first token ranged from 1 s to over 25 s in my runs (60 s once). That is the price of returning a clean `502` when the provider is down. Clients need a generous timeout; `LLM_TIMEOUT_SECONDS` bounds the wait on the server.
- **The SDK's retries multiply the timeout**: with the default `max_retries=2` and a 60 s timeout, a stuck local model held one `/extract` request for 182 s. `LLM_MAX_RETRIES` (default 1) and a 400-token cap on extraction (an `Enquiry` is about 150 tokens) bring the worst case to about 26 s for the 270M model, and a model that cannot stop writing now ends in `EXTRACTION_FAILED` instead of a timeout.
