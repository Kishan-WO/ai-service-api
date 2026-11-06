# ASGI middleware, line by line

Question: what does `app.add_middleware(RequestContextMiddleware)` do, in which order does a request pass through, and what are `scope`, `send_with_headers` and the `try/finally` in `core/middlewares.py`?

For the full request journey see `request-response-cycle.md`; for error handler placement see `exception-handlers-vs-express.md`.

## 1. What ASGI is
ASGI is the standard interface between a Python web server (uvicorn) and the app. Every ASGI app is a function with **three arguments**:

```python
async def app(scope, receive, send): ...
```
| Argument | What it is |
|---|---|
| `scope` | A dictionary describing the connection: `type`, `method`, `path`, `headers`, `query_string`, ... |
| `receive` | An async function to **read** incoming messages (the request body) |
| `send` | An async function to **write** outgoing messages (the response) |

A response is not returned; it is **sent as messages**:
1. `{"type": "http.response.start", "status": 200, "headers": [...]}`
2. one or more `{"type": "http.response.body", "body": b"...", "more_body": ...}`

Express comparison: `scope` ≈ `req`, `send` ≈ `res`, but at a lower level.

## 2. A middleware is an app that wraps an app
```python
class RequestContextMiddleware:
    def __init__(self, app):
        self.app = app          # the next layer inside

    async def __call__(self, scope, receive, send):
        ...
        await self.app(scope, receive, send)   # pass control inward
```
Express: `next()`. Here it is `await self.app(...)`. Code before that line runs on the way **in**; code after runs on the way **out**.

## 3. `app.add_middleware(RequestContextMiddleware)` (main.py line 47)
It registers the middleware class; FastAPI builds the wrapping later, on the first request. Rules:
- The **last middleware added is the outermost** (it sees the request first).
- So the request travels: `ServerErrorMiddleware` → `RequestContextMiddleware` → CORS (if enabled) → `ExceptionMiddleware` → router → endpoint. The response travels back the same way, in reverse (the "onion model").

## 4. The `scope["type"]` check (lines 49-52)
```python
if scope["type"] != "http":
    await self.app(scope, receive, send)
    return
```
ASGI carries more than HTTP: `scope["type"]` is `"http"`, `"websocket"` or `"lifespan"` (start-up/shut-down). This middleware only knows how to handle HTTP requests, so it **passes everything else through untouched** and returns.

## 5. Intercepting the response: `send_with_headers` (lines 63-70)
```python
async def send_with_headers(message):
    nonlocal status_code
    if message["type"] == "http.response.start":
        status_code = message["status"]
        headers = MutableHeaders(scope=message)
        headers["X-Request-ID"] = request_id
        headers["X-Process-Time"] = f"{...:.2f}ms"
    await send(message)
```
- The middleware gives the inner app **its own `send`** instead of the real one. Every outgoing message passes through it first.
- Only the first message, `http.response.start`, has the status and headers, so only that one is changed: the status code is recorded, and two headers are added.
- Then `await send(message)` forwards it to the real `send`. All other messages (body chunks) pass through unchanged, so **streaming still works**.
- `nonlocal status_code` lets this inner function update the outer variable (see `day-1/learning/closures-nonlocal-and-finally.md`).
- Express comparison: wrapping `res.writeHead` / monkey-patching `res.end`.

## 6. `try / finally` around the app (line 74)
```python
try:
    await self.app(scope, receive, send_with_headers)
finally:
    ...write the JSON log line (method, path, status, duration, request id, tenant id)...
```
- `await self.app(...)` runs **the rest of the application**: the router, the endpoint, the response.
- `finally` runs whether the request succeeded or raised. So **every** request is logged, even a crash (the status then stays at its starting value, 500).
- An exception still continues outward to the error handler after `finally`.

## 7. Shared state between layers
```python
state = scope.setdefault("state", {})
state["request_id"] = request_id
```
`scope` is the same dictionary for every layer. The middleware stores the request id there, and `get_current_user` later stores `tenant_id` and `user_id` in `request.state` (which reads the same dictionary). The log line in `finally` therefore knows the tenant.

## 8. Why plain ASGI and not `BaseHTTPMiddleware`
`BaseHTTPMiddleware` is easier to write but wraps the response in its own streaming layer, which complicates streaming responses and client-disconnect detection. A plain ASGI class is a few more lines and does not interfere.

## Common mistakes
| Mistake | What happens |
|---|---|
| Not passing `websocket` / `lifespan` scopes through | The app breaks at start-up or for websockets |
| Forgetting `await send(message)` in the wrapper | The response never leaves |
| Changing headers on every message, not only `http.response.start` | Errors or ignored changes |
| Reading the whole body inside middleware | Breaks streaming and uses memory |
| Expecting the first `add_middleware` to run first | The last one added is outermost |

## Quick check
- What are `scope`, `receive` and `send`?
- Why does the middleware pass non-HTTP scopes straight through?
- Why does it wrap `send`, and which message does it change?
- Why is the log line in a `finally` block?
- Which middleware sees the request first: the first or the last one added?
