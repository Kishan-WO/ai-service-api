# The async engine, the session factory and `get_db_session`

Question: explain `db/session.py` (lines 16-29 and the dependency below it).

```python
engine = create_async_engine(settings.DATABASE_URL, echo=settings.DEBUG, pool_pre_ping=True)

async_session_factory = async_sessionmaker(
    bind=engine, class_=AsyncSession, expire_on_commit=False, autoflush=False,
)

async def get_db_session() -> AsyncGenerator[AsyncSession]:
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
```

## 1. The pieces, with Node comparisons
| Piece | What it is | Node equivalent |
|---|---|---|
| **Engine** | Owns the **connection pool** to PostgreSQL. Created once per process | `new pg.Pool(...)` |
| **Session factory** | Makes sessions on demand, all tied to the engine | a function returning a client from the pool |
| **Session** | One unit of work: runs queries, tracks changed objects, owns one transaction | a transaction / Prisma client for one request |

The engine is **long-lived and shared**; sessions are **short-lived, one per request**.

## 2. The engine options
| Option | Meaning |
|---|---|
| `settings.DATABASE_URL` | `postgresql+asyncpg://user:pass@host:port/db`. `asyncpg` is the async driver |
| `echo=settings.DEBUG` | Print every SQL statement (handy while developing) |
| `pool_pre_ping=True` | Before reusing a pooled connection, test it. A connection the database closed (restart, idle timeout) is replaced instead of causing an error |

## 3. The session factory options
| Option | Meaning |
|---|---|
| `bind=engine` | Which engine the sessions use |
| `class_=AsyncSession` | Make async sessions (`await session.execute(...)`) |
| `expire_on_commit=False` | After `commit()`, **keep the object's loaded values**. By default SQLAlchemy marks them expired and re-reads them on next access. In async code that hidden re-read is a database call outside an `await`, which raises an error. Turning expiry off lets me return the object after the commit |
| `autoflush=False` | Do not send pending changes to the database automatically before each query. I decide when |

## 4. `get_db_session` as a FastAPI dependency
It is an **async generator**: code before `yield` is setup, code after is cleanup.

1. `async with async_session_factory() as session:` opens a session; leaving the block closes it and returns the connection to the pool.
2. `yield session` hands the session to the endpoint (through `Depends`).
3. When the endpoint is finished, the code after `yield` runs: `commit()` on success.
4. If an exception passed through, `rollback()` runs and the error is raised again.

Express comparison: middleware that opens a client before the handler and releases it after (in `finally`).

## 5. A catch I measured
In current FastAPI, the code after `yield` runs **after the response has been sent**. A `commit()` placed there means the client can receive a success answer before the data is saved, and a failed commit cannot change the response any more.

So the services call `await session.commit()` themselves (before returning). The `commit()` in `get_db_session` is only a safety net. More in `gotchas.md` and `transactions-commit-rollback.md`.

## 6. Closing the pool
The engine is disposed when the app shuts down (`await engine.dispose()` in the `lifespan`), which closes all pooled connections cleanly.

## Common mistakes
| Mistake | What happens |
|---|---|
| One global session for all requests | Requests share state and transactions |
| `expire_on_commit=True` with async | `MissingGreenlet` errors when reading attributes after commit |
| Forgetting `await session.commit()` | Changes are lost when the session closes |
| Creating a new engine per request | A new pool each time; connections run out |
| Using a sync driver (`psycopg2`) URL with the async engine | Error at start-up; use `postgresql+asyncpg://` |

## Quick check
- What is the difference between the engine, the session factory and a session?
- What does `pool_pre_ping=True` protect against?
- Why is `expire_on_commit=False` needed in async code?
- When does the part of `get_db_session` after `yield` run, and why do the services commit themselves?
