# How to run `ai-service`

Question: how do I run this project?

All commands run from `C:\Projects\ai-eng\ai-service`.

## 1. The easiest way: everything in Docker
Needs Docker Desktop running.

```bash
docker compose up --build
```
This starts three containers:
| Service | Container | Host port | Purpose |
|---|---|---|---|
| `api` | `ai-service-api` | **8000** | The FastAPI app (applies migrations first, then starts uvicorn with reload) |
| `postgres` | `ai-service-postgres` | **5433** | PostgreSQL with pgvector (host port 5433 because 5432 is already used on this machine) |
| `redis` | `ai-service-redis` | **6380** | Redis (running, not used by the code yet) |

Then open:
- http://localhost:8000/docs for Swagger
- http://localhost:8000/health returns `{"status":"ok"}`

Useful:
```bash
docker compose up -d --build     # run in the background
docker compose logs -f api       # follow the API log
docker compose ps                # status and health
docker compose stop              # stop (data is kept in volumes)
docker compose down              # remove containers (volumes stay)
```
The source folder is mounted into the container, so editing a file in `src/` restarts the server.

## 2. Run the app on the host, database in Docker
Good for debugging with an editor.

```bash
docker compose up -d postgres          # only the database
uv sync                                # install packages into .venv
uv run alembic upgrade head            # create the tables
uv run uvicorn ai_service.main:app --reload
```
The app reads `.env`, where `DATABASE_URL` uses `localhost:5433`.

## 3. First steps in the API
1. Open `/docs`, call `POST /api/v1/auth/register` with an email, a password of 8+ characters and a tenant name.
2. Click **Authorize** and log in with the email and password (see `08-swagger-authorize-and-oauth2.md`).
3. Try `POST /api/v1/documents/upload` with a `.txt`, `.md` or `.pdf` file, then list, get and delete.
4. For the stream, use curl, not Swagger:
   ```bash
   curl -N -H "Authorization: Bearer <token>" "http://localhost:8000/api/v1/stream/demo"
   ```

## 4. Tests and checks
```bash
uv run pytest             # 70 tests, in-memory SQLite, no Docker needed
uv run mypy               # strict type check
uv run ruff check .       # lint
```

## 5. The settings file
`.env` (copy from `.env.example`). The two required values are `SECRET_KEY` (32+ characters) and `DATABASE_URL`. The app refuses to start if they are missing or invalid (see `13-pydantic-settings-config.md`).

## 6. When something fails
| Symptom | Likely cause |
|---|---|
| `port is already allocated` | Another program uses 8000, 5433 or 6380; change the left side of the port mapping |
| `ValidationError ... Settings` at start | Missing or invalid `.env` value |
| `connection refused` to the database | Postgres not running; `docker compose up -d postgres` |
| `relation "users" does not exist` | Migrations not applied: `uv run alembic upgrade head` |
| Docker commands fail with a pipe error | Docker Desktop is not running |
| Swagger shows "loading" on the stream | Expected; use `curl -N` |
| 401 on every call | No token, an expired token, or Authorize not done |

## Quick check
- Which command starts the whole stack?
- Which three ports does it use, and why 5433 and 6380?
- How do I run the app on the host while Postgres stays in Docker?
- Where do I see the live stream?
