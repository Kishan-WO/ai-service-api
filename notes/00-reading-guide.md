# Reading `ai-service` from the start, step by step

> **Update (Day 7):** the `/chat` system prompt is now a **registry prompt**: the long handbook is `prompts/chat_system/v1.md` and the one-line default is `prompts/chat_basic/v1.md`, chosen by the settings `CHAT_PROMPT_NAME` and `CHAT_PROMPT_VERSION`. `CHAT_SYSTEM_PROMPT`, `CHAT_SYSTEM_PROMPT_FILE` and `chat_service.system_prompt()` no longer exist (it is `chat_service.chat_prompt()` now). The text below describes Day 6.

> **Where things are now:** the notes are in `day-3/`, `day-5/` and `day-6/` (see [README.md](README.md)). Day 3 notes are numbered in the order of the Day 3 tasks, Day 6 explanations in the order the layer was built. Every note a step names is listed with its path.

Read in this order. Each step names the file, what to look for, and the note that explains it. Paths are inside `src/ai_service/` unless they start with `tests/`, `alembic/` or `scripts/`. A good habit: read the file, then the test that proves it, then run `uv run pytest -k <word>`.

## Before the code (10 minutes)
1. `README.md` and `notes/day-3/01-how-to-run-ai-service.md`: what the service is and how to start it.
2. `notes/day-3/02-express_to_fastapi.md`: the Express to FastAPI map. Keep it open while reading.
3. `.env.example`: every setting the service reads.

---

## Days 1 to 3: the foundation (one service, multi-tenant, auth, documents)

### Step 1. Start at `main.py`
- `create_app()` builds the app: middleware, error handlers, the router. `lifespan` runs once at start and at stop.
- Notes: `day-3/14-lifespan-and-shared-client.md`, `day-3/03-request-response-cycle.md`.

### Step 2. Settings: `core/config.py`
- The `Settings` class reads `.env`. `get_settings()` is cached. Read only the first half for now (Day 1 to 3 settings); the LLM block is Day 5 and 6.
- Note: `day-3/13-pydantic-settings-config.md`.

### Step 3. Errors and logs: `core/exceptions.py`, `core/logging.py`
- `AppError` and its children carry a status code and a stable `code`. The logger prints one JSON line per event.
- Note: `day-3/11-exception-handlers-vs-express.md`.

### Step 4. Middleware: `core/middlewares.py`
- Request ID, timing, the JSON request log, and the error handlers that turn exceptions into one error shape.
- Note: `day-3/12-asgi-middleware-explained.md`. Test: `tests/test_middleware.py`.

### Step 5. Passwords and tokens: `core/security.py`
- Password hashing, creating and reading the JWT.

### Step 6. The database: `db/base.py`, `db/session.py`
- `Base`, the naming convention, `TimestampMixin`; then the async engine, the session factory and `get_db_session`.
- Notes: `day-3/04-async-engine-and-session.md`, `day-3/10-transactions-commit-rollback.md`.

### Step 7. The models: `db/models/tenant.py`, `user.py`, `document.py`
- Tenant, then User (belongs to a tenant), then Document (belongs to a tenant). Notice `tenant_id` everywhere.
- Note: `day-3/05-sqlalchemy-models-and-timestamps.md`.

### Step 8. Migrations: `alembic/env.py`, `alembic/versions/a7920f359d11_.py`
- How Alembic finds the models, and the first migration.
- Note: `day-3/06-alembic-setup-and-commands.md`.

### Step 9. Dependencies: `api/deps.py`
- `get_current_user` (token to user to tenant), `DbSession`, `CurrentUser`. The most important file for understanding how a route gets its user.
- Notes: `day-3/07-dependencies-deps-walkthrough.md`, `day-3/08-swagger-authorize-and-oauth2.md`.

### Step 10. Schemas: `schemas/common.py`, `auth.py`, `document.py`
- The request and response shapes (Pydantic). `ErrorResponse` is the common error envelope.

### Step 11. Auth feature: `services/auth_service.py`, then `api/v1/auth.py`
- Register creates a tenant and a user; login checks the password. Read the service first, then the thin route.
- Tests: `tests/test_auth.py`.

### Step 12. Documents feature: `services/document_service.py`, then `api/v1/documents.py`
- Upload, size and type checks, duplicate detection, every query filtered by tenant.
- Notes: `day-3/09-select-scalar-existence-check.md`. Tests: `tests/test_documents.py`, `tests/test_isolation.py` (one tenant can never see another's data).

### Step 13. Routing and streaming demo: `api/v1/router.py`, `api/v1/stream.py`
- How routers are joined under `/api/v1`, then the first Server-Sent Events example.
- Notes: `day-3/15-sse-streaming-and-stream-py.md`. Test: `tests/test_stream.py`.

### Step 14. How the tests are built: `tests/conftest.py`
- In-memory SQLite, an HTTP client wired straight to the app, `register` and `auth_headers`.
- Note: `day-3/16-test-database-strategy.md`.

### Step 15. Running it: `Dockerfile`, `docker-compose.yml`
- Notes: `day-3/17-dockerfile-and-compose-explained.md`, `day-3/18-postgres-in-docker-psql.md`.

---

## Day 4: no code in this repo
Day 4 (tokens, context, cost, hallucination tests) lives in `ai-eng-learning/day-4/`. Read `day-4/Notes/` for the ideas behind Days 5 and 6 (token counts, cost formula, the hosted vs local comparison).

---

## Day 5: `/chat` and `/extract` (the first LLM code)
Concept notes first: `ai-eng-learning/day-5/learning/` (messages API, streaming, structured output). Then `notes/day-5/01-chat-and-extract.md` for the map.

### Step 16. Data: `db/models/conversation.py`, `alembic/versions/c2b3d69c8756_conversations_and_messages.py`
- `Conversation` and `Message`, both with `tenant_id`; the composite index on `(conversation_id, id)`.

### Step 17. Shapes: `schemas/chat.py`, `schemas/extract.py`
- `ChatRequest` (optional `conversation_id`), and `Enquiry`, the object the model must fill.

### Step 18. The first provider layer (Day 5 version)
- Day 5 had one class that talked to Gemini and Ollama. It was replaced on Day 6; read the Day 6 files below instead and use `git show 57a721b -- src/ai_service/services/llm.py` if you want the old one.

### Step 19. `services/chat_service.py`
- Conversation queries, `load_history`, `start_turn`, and `chat_stream()` (the SSE generator that streams, collects the text and saves it, even when the client leaves). Read `chat_stream()` slowly.

### Step 20. `api/v1/chat.py`, `api/v1/extract.py`
- The routes: wait for the first token, then store and stream; `/extract` calls the service.

### Step 21. Tests: `tests/fakes.py`, `tests/test_chat.py`, `tests/test_extract.py`
- The fake model, the disconnect tests, the repair tests.

---

## Day 6: reliability, cost and providers
Concept notes first: `ai-eng-learning/day-6/learning/` (four notes). Then `notes/day-6/01-reliability-cost-and-providers.md`. Decisions 25 to 38 in `decisions.md` explain the why.

### Step 22. Types and errors: `services/llm_types.py`
- Read this first. `LLMClient` (the interface), `LLMRequest`, `LLMResponse`, `Usage`, stream events, and the error classes with `retryable` and `fallback_ok`.

### Step 23. The adapters: `services/llm_openai.py`, then `services/llm_anthropic.py`
- Each turns one SDK into the `LLMClient` shape: error mapping (`map_openai_error`), usage normalising, structured output. Compare how the two differ.

### Step 24. The layers: `services/llm_wrappers.py`
- `RateLimiter` and `LimitedClient`, `RetryingClient` (backoff, jitter, `retry-after`, time budget), `FallbackClient`. Note the helper `_prime`: why a stream is only retried before its first text.

### Step 25. Money and logs: `services/llm_cost.py`, `services/llm_accounting.py`, `db/models/llm_call.py`
- `compute_cost`, then `AccountingClient` (one log line and one row per real call), then the table and its migration `alembic/versions/86fde07d2bc3_llm_calls.py`.

### Step 26. Putting it together: `services/llm.py`, `main.py` (the lifespan line), `core/config.py` (the LLM block)
- `SettingsLLMRegistry` builds `Fallback(Retrying(Limited(Accounting(adapter))))` per backend from the settings.

### Step 27. The repair loop: `services/extract_service.py` and the checks in `schemas/extract.py`
- Up to 2 repairs, refusals, cut-off replies, and the Pydantic sanity checks that start a repair.

### Step 28. What changed in the routes: `api/v1/chat.py`, `api/v1/extract.py`, `services/chat_service.py`
- `CallContext` (who and what a call is for), `cache_system`, the `session.commit()` before the model call, and `system_prompt()` reading `prompts/chat_system.md`.

### Step 29. The tests for the layers
- `tests/test_llm_wrappers.py` (retry, fallback, limits; scripted clients, no waiting), `tests/test_llm_accounting.py` (cost and rows), `tests/test_llm_provider.py` and `tests/test_llm_anthropic.py` (fake HTTP servers), `tests/test_llm_registry.py` (settings to stack).

### Step 30. The 50-input run: `scripts/messy_inputs.py`, `scripts/run_messy_inputs.py`, `scripts/results/`
- The inputs with what a correct answer is, the runner and its outcome categories, and the saved reports (`..._schema_only.json` is the first pass, the others have the sanity checks).

---

## Last: the three files that explain "why"
1. `decisions.md`: numbered decisions, Day 5 (16 to 24) and Day 6 (25 to 38).
2. `gotchas.md`: the traps found by running the code.
3. `notes/README.md`: the index of every note.

## A fast path (one hour)
`main.py` -> `api/deps.py` -> `services/auth_service.py` -> `services/chat_service.py` (`chat_stream`) -> `services/llm_types.py` -> `services/llm_wrappers.py` -> `services/extract_service.py` -> `tests/test_chat.py` (the disconnect test) -> `tests/test_llm_wrappers.py`.
