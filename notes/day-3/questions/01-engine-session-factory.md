# Q16. Explain the engine and session factory

```python
engine: AsyncEngine = create_async_engine(
    settings.DATABASE_URL, echo=settings.DEBUG, pool_pre_ping=True,
)

async_session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=engine, class_=AsyncSession, expire_on_commit=False, autoflush=False,
)
```

Sets up SQLAlchemy's **async connection** (engine) and a **factory that creates sessions**. Created once at module level; a session is opened per request.

## Engine
Owns the **connection pool**.
- **`DATABASE_URL`**: must use an async driver, e.g. `postgresql+asyncpg://...`.
- **`echo=settings.DEBUG`**: logs every SQL statement when `True`.
- **`pool_pre_ping=True`**: tests a pooled connection before use; dead ones are replaced (prevents "connection closed" errors).

## Session factory
Calling `async_session_factory()` returns a new `AsyncSession`.
- **`bind=engine`**: borrow connections from this pool.
- **`class_=AsyncSession`**: default already; explicit.
- **`expire_on_commit=False`**: important (below).
- **`autoflush=False`**: no automatic flush before queries.

## Why `expire_on_commit=False`
By default, commit expires loaded objects so the next attribute access lazy-reloads, which can't happen implicitly in async: `MissingGreenlet`. With `False`, objects keep values after commit:
```python
session.add(user)
await session.commit()
return user  # attributes still readable
```
Trade-off: data may be slightly stale; use `await session.refresh(user)` when needed.

## Why `autoflush=False`
Predictable control over when SQL is sent; avoids surprise flushes. Downside: a query right after `add()` won't see the object until you flush.

## Typical use
```python
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_factory() as session:
        yield session
```

## Shutdown
```python
@asynccontextmanager
async def lifespan(app):
    yield
    await engine.dispose()
```
