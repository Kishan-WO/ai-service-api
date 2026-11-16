# Why tests use a separate test database

Question: why did you use a test database?

## 1. The reasons
| Reason | Explanation |
|---|---|
| **Don't damage real data** | Tests register users, upload documents and delete them. Against the development database they would mix with my own data, or wipe it |
| **Repeatable** | Every test starts from an empty database, so a test cannot fail because of what an earlier run left behind |
| **Isolated** | One test's data cannot leak into another |
| **Fast** | An in-memory database needs no server and is created in milliseconds |
| **Safe anywhere** | Runs on any machine and in automated builds without Docker |

Express comparison: supertest tests that use an in-memory MongoDB (`mongodb-memory-server`) instead of the development database.

## 2. How this project does it
In `tests/conftest.py`:

```python
engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)
async with engine.begin() as connection:
    await connection.run_sync(Base.metadata.create_all)   # create all tables
```
- **SQLite in memory** (`aiosqlite` is its async driver): the database exists only while the test runs.
- **`Base.metadata.create_all`** builds the tables straight from the models; Alembic is not needed here.
- **`StaticPool`** is essential. An in-memory SQLite database belongs to one *connection*. With a normal pool each new connection would see its own empty database and the tables would "disappear". `StaticPool` makes every use share one connection.

The app is given this database by replacing the dependency:
```python
app.dependency_overrides[get_db_session] = override_get_db_session
```
`dependency_overrides` tells FastAPI: "wherever `get_db_session` is asked for, use this function instead". The application code is unchanged.

The environment variables the settings need are set at the top of `conftest.py` (`os.environ.setdefault(...)`), before any app code is imported, so the tests do not depend on my `.env` file.

(The settings class also has a `TEST_DATABASE_URL` field, but the fixture uses the SQLite URL directly.)

## 3. How a model works on both databases
`Document.metadata_json` uses `JSON().with_variant(JSONB, "postgresql")`: plain JSON on SQLite, JSONB on PostgreSQL. UUID and timezone-aware datetimes also work on both. Without such care, a model might only run on one of them.

## 4. The limit of this approach
SQLite is **not PostgreSQL**. The tests do not exercise:
- real `JSONB` behaviour,
- enforced foreign-key cascades (SQLite ignores foreign keys unless switched on),
- real concurrent unique-constraint races,
- PostgreSQL-specific SQL.

I covered these once by running the real Docker stack and calling it over HTTP. If it matters more later, a second mode can run the same tests against a throw-away PostgreSQL database.

## 5. Each test gets a fresh database
The `engine` fixture is created and disposed for every test, so tests never see each other's rows. That is why two tests can both register `user@example.com`.

## Common mistakes
| Mistake | What happens |
|---|---|
| In-memory SQLite without `StaticPool` | "no such table" errors |
| Tests pointing at the development database | Test data pollutes it, tests become order-dependent |
| Overriding the wrong dependency function | The real database is still used |
| Importing the app before setting test env vars | Settings validation fails |
| Assuming a green SQLite test proves PostgreSQL behaviour | Only the Docker/Postgres run does |

## Quick check
- Give three reasons to use a test database.
- Why does in-memory SQLite need `StaticPool`?
- What does `dependency_overrides` replace?
- Name two things SQLite tests cannot prove about PostgreSQL.
