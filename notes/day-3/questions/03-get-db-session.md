# Q18. Explain `get_db_session`

```python
async def get_db_session() -> AsyncGenerator[AsyncSession]:
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
```

Gives each request its own session and **commits on success / rolls back on error**.

## Line by line
- `async with async_session_factory() as session`: new session; closed when the block ends.
- `yield session`: route runs while paused here.
- `await session.commit()`: runs if the route finished without raising.
- `except Exception: rollback(); raise`: no half-finished changes; re-raises so FastAPI still returns the proper error.

## Flow
```
request -> create session -> route
            |-- success -> commit -> close
            |-- error   -> rollback -> re-raise -> close
```

## In routes
You normally **don't call `commit()`**:
```python
db.add(user)
await db.flush()   # to get user.id
return user        # commit after route returns
```
Pattern: **unit of work per request**.

## Things to know
- In recent FastAPI, code after `yield` runs *after the response is sent*; if the commit fails the client may already have a 200. Commit explicitly in the route if it matters.
- `HTTPException` also triggers rollback.
- `AsyncGenerator[AsyncSession]` with one arg needs newer Python; older needs `, None`.
- Read-only requests also commit (harmless round trip).
- `asyncio.CancelledError` is a `BaseException`, not caught by `except Exception`, but `async with` still closes the session and uncommitted work is discarded.
