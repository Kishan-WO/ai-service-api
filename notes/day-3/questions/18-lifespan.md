# Q7. What is lifespan in FastAPI (instance attribute passed)?

`lifespan` is a parameter of `FastAPI()`. It takes an **async context manager** that runs code **once at startup** and **once at shutdown**.

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI

@asynccontextmanager
async def lifespan(app: FastAPI):
    # startup
    app.state.db = await connect_to_db()
    yield              # app serves requests here
    # shutdown
    await app.state.db.close()

app = FastAPI(lifespan=lifespan)
```

## How it works
- Before `yield`: startup. After `yield`: shutdown.
- Pass the function itself: `lifespan=lifespan`, not `lifespan()`.

## Used for
DB pools, loading ML models, background tasks, Redis/HTTP clients, logging setup.

## Sharing resources
Store on `app.state`, read via `request.app.state`:
```python
@app.get("/users")
async def users(request: Request):
    db = request.app.state.db
```

## Replaces the old way
`@app.on_event("startup")` / `("shutdown")` are deprecated. `lifespan` keeps setup and teardown together. If you pass `lifespan`, `on_event` handlers are ignored.
