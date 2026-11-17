# Q8. Explain `app.state.http_client = httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=5.0))`

Creates one shared **async HTTP client** at startup and stores it on `app.state` so every route reuses it.

- **`httpx.AsyncClient(...)`**: async HTTP client for calling other APIs.
- **`httpx.Timeout(30.0, connect=5.0)`**: `30.0` is the default timeout for everything; `connect=5.0` overrides just the connection step.
- **`app.state.http_client`**: lives as long as the app.

## Why those timeouts
Dead server fails fast (5s); slow but reachable server gets up to 30s. Exceeding raises `httpx.TimeoutException` (or `ConnectTimeout` / `ReadTimeout`).

## Why one shared client
It keeps a **connection pool**, reusing TCP/TLS connections: much faster than one client per request.

## Full pattern
```python
@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.http_client = httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=5.0))
    yield
    await app.state.http_client.aclose()

@app.get("/proxy")
async def proxy(request: Request):
    client = request.app.state.http_client
    r = await client.get("https://api.example.com/data")
    return r.json()
```
Always close with `await client.aclose()` after `yield` to avoid leaking connections.
