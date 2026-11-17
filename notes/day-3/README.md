# Day 3: the `ai-service` base (FastAPI for Express developers)

**Build target (from the plan):** a multi-tenant documents API with auth, SSE, tests and Docker. Every AI feature from Day 4 on is added to this repository. Days 1 and 2 (Python core, typing, asyncio) have no code in this repo; their notes are in `ai-eng-learning/day-1` and `day-2`.

The notes are in **the order of the Day 3 tasks**, so reading 01 to 18 follows the order the service was built. The questions I asked while reading the code are in [`questions/`](questions/README.md), in the same task order.

## Tasks and the notes for each

| Plan task | What it asked | Notes |
|---|---|---|
| Start | run it, and the Express to FastAPI mapping note | [01](01-how-to-run-ai-service.md), [02](02-express_to_fastapi.md), [03](03-request-response-cycle.md) |
| **1** | Tables and Alembic migrations: `tenants`, `users`, `documents` | [04 async engine and session](04-async-engine-and-session.md), [05 SQLAlchemy models](05-sqlalchemy-models-and-timestamps.md), [06 Alembic](06-alembic-setup-and-commands.md) |
| **2** | Register / login with JWT; every documents endpoint scoped to the tenant | [07 `deps.py` and `get_current_user`](07-dependencies-deps-walkthrough.md), [08 Swagger Authorize and the OAuth2 flow](08-swagger-authorize-and-oauth2.md) |
| **3** | Documents: upload (.txt, .md, .pdf up to 20 MB), list with pagination, get, delete; `(tenant_id, content_hash)` unique | [09 `select()` and the existence check](09-select-scalar-existence-check.md), [10 transactions: commit and rollback](10-transactions-commit-rollback.md) |
| **4** | Error envelope, request-ID middleware, JSON logs, settings from `.env`, shared `httpx.AsyncClient` in `lifespan` | [11 exception handlers](11-exception-handlers-vs-express.md), [12 ASGI middleware](12-asgi-middleware-explained.md), [13 settings](13-pydantic-settings-config.md), [14 lifespan](14-lifespan-and-shared-client.md) |
| **5** | `GET /stream/demo`: an SSE endpoint, log client disconnects | [15 SSE and `stream.py`](15-sse-streaming-and-stream-py.md) |
| **6 and 7** | Isolation test; integration tests; `docker compose up` | [16 test database](16-test-database-strategy.md), [17 Dockerfile and Compose](17-dockerfile-and-compose-explained.md), [18 `psql` in Docker](18-postgres-in-docker-psql.md) |

## All the notes, in order
| # | Note |
|---|---|
| 01 | [How to run `ai-service`](01-how-to-run-ai-service.md) |
| 02 | [Express to FastAPI: what I used](02-express_to_fastapi.md) |
| 03 | [The request and response cycle](03-request-response-cycle.md) |
| 04 | [The async engine, the session factory and `get_db_session`](04-async-engine-and-session.md) |
| 05 | [SQLAlchemy models: `Mapped`, `mapped_column`, timestamps](05-sqlalchemy-models-and-timestamps.md) |
| 06 | [Alembic: setup, `env.py` and the commands](06-alembic-setup-and-commands.md) |
| 07 | [`api/deps.py`: dependency injection and `get_current_user`](07-dependencies-deps-walkthrough.md) |
| 08 | [Swagger "Authorize" and the OAuth2 password flow](08-swagger-authorize-and-oauth2.md) |
| 09 | [`select()`, `session.scalar()` and the existence check](09-select-scalar-existence-check.md) |
| 10 | [Transactions: why `commit` and `rollback` are only in some services](10-transactions-commit-rollback.md) |
| 11 | [Exception handlers: Express vs FastAPI](11-exception-handlers-vs-express.md) |
| 12 | [ASGI middleware, line by line](12-asgi-middleware-explained.md) |
| 13 | [Settings from `.env` with `pydantic-settings`](13-pydantic-settings-config.md) |
| 14 | [`lifespan`: start-up and shut-down code](14-lifespan-and-shared-client.md) |
| 15 | [Server-Sent Events and `api/v1/stream.py`](15-sse-streaming-and-stream-py.md) |
| 16 | [Why tests use a separate test database](16-test-database-strategy.md) |
| 17 | [The Dockerfile and `docker-compose.yml`, and the problems in them](17-dockerfile-and-compose-explained.md) |
| 18 | [Looking inside PostgreSQL in Docker (`psql`)](18-postgres-in-docker-psql.md) |

Next: [Day 5](../day-5/README.md) (Day 4 has no code in this repo: its notes are in `ai-eng-learning/day-4`).
