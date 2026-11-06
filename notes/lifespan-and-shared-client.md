# `lifespan`: start-up and shut-down code

Question: explain `main.py` lines 21-29.

```python
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    app.state.http_client = httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=5.0))
    try:
        yield
    finally:
        await app.state.http_client.aclose()
        await engine.dispose()
```
and `FastAPI(..., lifespan=lifespan)`.

## 1. The idea
`lifespan` runs code **once when the server starts** and **once when it stops**. It is the place for things that must exist for the whole life of the app: shared clients, connection pools, caches.

```
server starts  → code before `yield` runs        (start-up)
   ...the app serves requests...
server stops   → code after `yield` runs         (shut-down)
```
Express comparison: code before `app.listen(...)`, plus a `process.on("SIGTERM", ...)` handler to close connections.

## 2. How it is built
- `@asynccontextmanager` (from `contextlib`) turns an async generator into an **async context manager**: something usable with `async with`. FastAPI/Starlette enters it at start and exits it at shut-down. (The sync version, `@contextmanager`, is explained in `day-2/learning/5.context-managers.md`.)
- `yield` splits the function: before it is start-up, after it is shut-down.
- `try / finally` makes sure the shut-down part runs even if something went wrong.
- Return type `AsyncGenerator[None]` is what the decorator expects ("yields once, no value"); `AsyncIterator` is the older, deprecated spelling.

## 3. What this app does
| Step | Code | Why |
|---|---|---|
| Start-up | `app.state.http_client = httpx.AsyncClient(...)` | **One** HTTP client for the whole app: reuses connections (faster) and gives one place to set timeouts (30 s, 5 s to connect) |
| Shut-down | `await app.state.http_client.aclose()` | Close the client's connections cleanly |
| Shut-down | `await engine.dispose()` | Close the database connection pool |

`app.state` is a place on the app object to store shared things. Request code reads it through a dependency:
```python
def get_http_client(request: Request) -> httpx.AsyncClient:
    return request.app.state.http_client
```

## 4. Why not create the client per request
A new client per request means a new connection pool and a new TLS handshake every time: slow and wasteful, and the connections are easy to leak. One shared client, created once, is the normal pattern.

## 5. Things to know
- `lifespan` replaces the older `@app.on_event("startup")` / `("shutdown")` hooks, which are deprecated.
- In tests, `httpx.ASGITransport` does **not** run `lifespan` by default, so `app.state.http_client` doesn't exist there unless the test enters the lifespan itself.
- Anything slow in start-up delays the server becoming ready.

## Common mistakes
| Mistake | What happens |
|---|---|
| Creating an `AsyncClient` per request | Slow; many open connections |
| Forgetting `aclose()` | Open connections and warnings at exit |
| No `try/finally` around `yield` | Shut-down code is skipped after an error |
| Reading `app.state.http_client` in a test without lifespan | `AttributeError` |
| Using `AsyncIterator[None]` for the return type | Deprecation warning |

## Quick check
- What runs before `yield`, and what after?
- What does `@asynccontextmanager` turn the function into?
- Why is one shared `AsyncClient` better than one per request?
- Where does request code get the client from?
