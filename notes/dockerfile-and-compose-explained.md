# The Dockerfile and `docker-compose.yml`, and the problems I found in them

Question: what are the issues in the Docker files, fix the Redis port, and what remains after the virtual-environment change?

## 1. The Dockerfile: a multi-stage build
```dockerfile
FROM ghcr.io/astral-sh/uv:python3.14-bookworm-slim AS builder
WORKDIR /app
ENV UV_COMPILE_BYTECODE=1  UV_LINK_MODE=copy
COPY pyproject.toml uv.lock* ./
RUN uv sync --frozen --no-install-project --no-dev     # 1. dependencies only
COPY . .
RUN uv sync --frozen --no-dev                          # 2. the project itself

FROM python:3.14-slim-bookworm AS runner
RUN groupadd -r appuser && useradd -r -g appuser appuser
COPY --from=builder --chown=appuser:appuser /app /app
ENV PATH="/app/.venv/bin:$PATH"
USER appuser
CMD ["uvicorn", "ai_service.main:app", "--host", "0.0.0.0", "--port", "8000"]
```
| Idea | Why |
|---|---|
| **Two stages** | The builder has uv and the build tools; the final image only gets the finished `/app` with the `.venv`. Smaller and cleaner |
| **Dependencies first** | `COPY pyproject.toml uv.lock` + `uv sync` run before the source is copied. Docker caches that layer, so changing only my code does not reinstall packages |
| `--frozen` | Install exactly what `uv.lock` says; it needs `uv.lock` in the build folder |
| `--no-dev` | No test or lint tools in the image |
| **Non-root user** | If the app is compromised, it is not root inside the container |
| `PATH=/app/.venv/bin` | `uvicorn` and `alembic` are found without activating anything |

Image size: about 320 MB.

## 2. `.dockerignore`
Keeps files out of `COPY . .`:
```
.env  .venv  .git  __pycache__/  *.py[oc]  caches  tests/  notes/
```
Without it the `.env` (secrets) and the Windows `.venv` would be copied into the image.

## 3. The compose file: three services
| Service | Image | Host port → container | Notes |
|---|---|---|---|
| `postgres` | `pgvector/pgvector:pg16` | **5433** → 5432 | Data in the volume `postgres_data`; health check with `pg_isready` |
| `redis` | `redis:7-alpine` | **6380** → 6379 | Data in `redis_data`; health check with `redis-cli ping` |
| `api` | built from the Dockerfile | 8000 → 8000 | Starts only when postgres and redis are **healthy** |

The `api` service:
```yaml
depends_on:
  postgres: {condition: service_healthy}
  redis:    {condition: service_healthy}
env_file: [.env]
environment:
  - DATABASE_URL=postgresql+asyncpg://postgres:postgres@postgres:5432/ai_service
volumes: [./src:/app/src]
command: ["sh", "-c", "alembic upgrade head && uvicorn ai_service.main:app --host 0.0.0.0 --port 8000 --reload"]
healthcheck:
  test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/health', timeout=3)"]
```
- `env_file` loads `.env`; `environment` **overrides** `DATABASE_URL` so the container uses the host name `postgres` (Docker's internal network name) and the container port 5432.
- The `volumes` line mounts my `src/` folder, so editing a file restarts the server (`--reload`).
- `command` first applies migrations, then starts uvicorn; if a migration fails, uvicorn never starts.
- The health check uses Python itself because the slim image has no `curl`.

## 4. Why the host ports are different
The ports on the left of `:` are the **host** side. This machine already had a PostgreSQL service on 5432 and another container's Redis on 6379, so:
- Postgres is published on **5433**,
- Redis on **6380**.
Inside the Docker network the services still talk to each other on 5432 and 6379. From the host, tools (Alembic, `psql`) use 5433.

## 5. The issues and their fixes
| Issue | Fix |
|---|---|
| Port 5432 / 6379 already in use | Host ports 5433 and 6380 |
| `uv.lock` missing in the build folder (the project was a workspace member) | Make `ai-service` a standalone uv project with its own `uv.lock` |
| No `.dockerignore`: `.env` and `.venv` copied into the image | Added `.dockerignore` |
| Tables not created in a fresh stack | `alembic upgrade head` before uvicorn |
| No health check on `api` | Added `/health` and a `healthcheck` |
| `./src` mount would not take effect | Not an issue: `uv sync` installs the project in editable mode, so `ai_service` loads from `/app/src` |
| uv might download its own Python | Not happening: the venv uses the image's Python; the builder and runner both use 3.14 |

## Common mistakes
| Mistake | What happens |
|---|---|
| Copying `.env` into the image | Secrets baked into the image |
| `COPY . .` before installing dependencies | Every code change reinstalls packages |
| Using `localhost` as the database host inside a container | It is the container itself; use the service name `postgres` |
| Forgetting `depends_on` health conditions | The API starts before the database is ready |
| Running as root | Larger blast radius if compromised |

## Quick check
- Why two stages, and why copy `pyproject.toml` and `uv.lock` first?
- Why is the container's database host `postgres` and not `localhost`?
- What do the host ports 5433 and 6380 map to inside Docker?
- What does the `command` do before starting uvicorn?
- Why is `.dockerignore` important?
