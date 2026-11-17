# Q17. Meaning of async generator, async session, and autoflush

## AsyncGenerator
An **async generator** is an `async def` using `yield`; it can `await` between values. FastAPI uses it for dependencies needing **setup and cleanup**.
```python
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_factory() as session:
        yield session
    # cleanup after the route finishes
```
`AsyncGenerator[AsyncSession, None]`: first = yielded type, second = type that can be sent in (almost always `None`).

FastAPI runs up to `yield`, passes the value into the route, then resumes for cleanup. Same idea as `lifespan`.

## AsyncSession
SQLAlchemy's async workspace for the database. It borrows a connection, tracks objects (unit of work), and sends changes in a transaction on `commit()`.
```python
db.add(user)          # not awaited: in-memory only
await db.flush()      # sends INSERT inside the transaction
await db.commit()     # permanent
result = await db.execute(select(User).where(User.id == 1))
```
- One session **per request**, never global.
- `add()` is sync; `execute`, `flush`, `commit`, `refresh`, `rollback` are awaited.
- Lazy loading doesn't work implicitly; use `selectinload()` / `joinedload()` or `await db.refresh(obj, [...])`.

## autoflush
A **flush** sends pending changes as SQL **without committing**.

- `autoflush=True` (default): flush automatically before each query, so queries see pending changes.
- `autoflush=False`: nothing sent until `flush()` / `commit()`.
```python
db.add(User(email="a@b.com"))
result = await db.execute(select(User).where(User.email == "a@b.com"))
# True  -> found; False -> NOT found
```
Why disable: predictability, avoiding surprise constraint errors, fewer unplanned round trips. Trade-off: flush first if you need to query what you added or need the generated primary key:
```python
db.add(user); await db.flush(); print(user.id)
```
